"""Public marketing-site intake + aggregate metrics.

Mounted under ``/v1/public`` and bypassed by ``APIAuthMiddleware`` via
``SKIP_PREFIXES`` (and absent from ``ModuleAccessMiddleware``'s
``PREFIX_TO_MODULE``), so these endpoints are reachable by anonymous visitors
on uniecortex.com.

- ``POST /v1/public/intake`` — Audit Request + Industry Pros application forms
  (discriminated on ``form``). Persists one row, returns a server-generated
  reference. No email service exists in this codebase; follow-up is manual via
  the authenticated listing below.
- ``GET  /v1/public/site-metrics`` — cached aggregate counters backing the
  homepage ticker / hero / network section. Live where an honest source
  exists, static marketing fallback otherwise (never returns a deflating 0).
- ``GET  /v1/public-intake/submissions`` — authenticated lead listing (mounted
  on a NON-``/v1/public`` prefix so ``APIAuthMiddleware`` enforces a key/session
  — leads must not be world-readable).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import random
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from unie_cortex.db.database import SessionLocal
from unie_cortex.db.models import (
    AuthInvitation,
    AuthUser,
    CortexAuditFinding,
    CortexAuditShipmentFact,
    CortexVaultCarrierCredential,
    EntityReport,
    LtlQuoteFullOutput,
    PublicIntakeSubmission,
    SellerOptimizationRun,
    SpecialistBooking,
)
from unie_cortex.middleware.rate_limit import check_rate_limit
from unie_cortex.config import settings
from unie_cortex.services.user_management import invitations as invites
from unie_cortex.services.user_management import store as um_store
from unie_cortex.services.user_management.access import require_authenticated_user
from unie_cortex.services.email_suppression import send_email_guarded

import logging

logger = logging.getLogger(__name__)

# audit_type → the grantable module the provisioned account gets.
AUDIT_MODULE = {
    "carrier": "cortex_audit",
    "rate": "rate_optimization",
    "warehouse": "warehouse_audit",
    "seller": "seller_optimization",
    "research": "product_research",
    "unsure": "cortex_audit",
}
AUDIT_LABEL = {
    "carrier": "Carrier Audit",
    "rate": "Rate Optimization",
    "warehouse": "Warehouse Audit",
    "seller": "Seller Optimization",
    "research": "Product Research",
    "unsure": "Cortex Audit",
}

router = APIRouter()
admin_router = APIRouter()

# Unambiguous alphabet for human-readable references (no 0/O/1/I).
_REF_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_REF_PREFIX = {"audit_request": "AUD", "partner_application": "APPLY"}

# email-validator is not a dependency here; use a pragmatic format check.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str) -> str:
    v = (v or "").strip()
    if not _EMAIL_RE.match(v) or len(v) > 320:
        raise ValueError("invalid email address")
    return v


# --------------------------------------------------------------------------- #
# Schemas — intake
# --------------------------------------------------------------------------- #
class AuditVolume(BaseModel):
    parcels: Optional[str] = Field(None, max_length=64)
    lanes: Optional[str] = Field(None, max_length=64)
    skus: Optional[str] = Field(None, max_length=64)
    revenue: Optional[str] = Field(None, max_length=64)


class AuditContact(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., max_length=320)
    role: str = Field(..., min_length=1, max_length=120)
    company: str = Field(..., min_length=1, max_length=200)
    company_site: Optional[str] = Field(None, max_length=300)
    phone: Optional[str] = Field(None, max_length=40)

    _ck_email = field_validator("email")(_validate_email)


class AuditRequestIn(BaseModel):
    form: Literal["audit_request"]
    audit_type: Literal["carrier", "rate", "warehouse", "seller", "unsure"]
    problems: list[str] = Field(default_factory=list, max_length=50)
    # Audit-specific baseline (the form's Section 03). Flexible map so each
    # audit can ask its own questions; `volume` kept for back-compat.
    baseline: dict[str, str] = Field(default_factory=dict, max_length=24)
    volume: AuditVolume = Field(default_factory=AuditVolume)
    has_data_ready: bool = False
    contact: AuditContact
    notes: Optional[str] = Field(None, max_length=4000)
    page_path: str = Field(..., max_length=300)

    @field_validator("baseline")
    @classmethod
    def _ck_baseline(cls, v: dict) -> dict:
        if len(v) > 24:
            raise ValueError("too many baseline keys")
        for k, val in v.items():
            if not isinstance(k, str) or not isinstance(val, str):
                raise ValueError("baseline must be string→string")
            if len(k) > 48 or len(val) > 64:
                raise ValueError("baseline key/value too long")
        return v


class PartnerContact(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., max_length=320)
    company: str = Field(..., min_length=1, max_length=200)
    site: Optional[str] = Field(None, max_length=300)
    phone: Optional[str] = Field(None, max_length=40)

    _ck_email = field_validator("email")(_validate_email)


class PartnerApplicationIn(BaseModel):
    form: Literal["partner_application"]
    partner_type: Literal["3pl", "broker", "consult", "saas", "advisor"]
    book_types: list[str] = Field(default_factory=list, max_length=50)
    focus_areas: list[str] = Field(default_factory=list, max_length=50)
    revenue_models: list[str] = Field(default_factory=list, max_length=50)
    book_size: str = Field("", max_length=120)
    contact: PartnerContact
    notes: Optional[str] = Field(None, max_length=4000)
    page_path: str = Field(..., max_length=300)


IntakeIn = Annotated[
    Union[AuditRequestIn, PartnerApplicationIn], Field(discriminator="form")
]


class IntakeResponse(BaseModel):
    reference: str
    status: str
    audit_type: Optional[str] = None
    onboarding_url: Optional[str] = None
    email_sent: Optional[bool] = None


class IntakeStatusStep(BaseModel):
    n: str
    label: str
    detail: str
    state: str  # done | active | pending


class IntakeStatusResult(BaseModel):
    reference: str
    status: str
    email_sent: bool = False
    onboarding_url: Optional[str] = None
    steps: list[IntakeStatusStep] = Field(default_factory=list)


class IntakeSubmissionRow(BaseModel):
    id: str
    reference: str
    form_type: str
    status: str
    email: str
    company: Optional[str] = None
    page_path: Optional[str] = None
    payload: dict[str, Any]
    created_at: str


class IntakeSubmissionsResult(BaseModel):
    submissions: list[IntakeSubmissionRow]
    count: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Schemas — site metrics
# --------------------------------------------------------------------------- #
class SiteMetric(BaseModel):
    id: str
    label: str
    value: str
    delta: str = ""
    trend: str = "flat"  # up | down | flat
    source: str = "static"  # live | static


class SiteMetricsResult(BaseModel):
    generated_at: str
    ticker: list[SiteMetric]
    hero: dict[str, Any]
    network: dict[str, Any]


@asynccontextmanager
async def _with_session():
    if SessionLocal is None:
        raise HTTPException(503, "Database not available")
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _safe_scalar(session, stmt, default=0):
    try:
        return (await session.execute(stmt)).scalar() or default
    except Exception:
        return default


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "anon"


def _fmt_count(n: int | float | None) -> str:
    v = float(n or 0)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 10_000:
        return f"{v / 1_000:.1f}k"
    return f"{int(round(v)):,}"


def _fmt_usd(n: int | float | None) -> str:
    v = float(n or 0)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.0f}k"
    return f"${int(round(v)):,}"


def _gen_reference(form_type: str) -> str:
    prefix = _REF_PREFIX.get(form_type, "REF")
    body = "".join(random.choice(_REF_ALPHABET) for _ in range(5))
    return f"{prefix}-{body}"


def _gen_access_code() -> str:
    """A 6-digit numeric access code (zero-padded, cryptographically random)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Intake
# --------------------------------------------------------------------------- #
def _audit_steps(status: str, email_sent: bool, email: str) -> list[dict]:
    provisioned = status in ("provisioned", "access_sent", "accepted")
    return [
        {"n": "01", "label": "Request received", "detail": "just now", "state": "done"},
        {
            "n": "02",
            "label": "Account provisioned",
            "detail": "invitation created" if provisioned else "provisioning…",
            "state": "done" if provisioned else "active",
        },
        {
            "n": "03",
            "label": "Onboarding link",
            "detail": f"emailed to {email}" if email_sent else "ready below",
            "state": ("done" if email_sent else "active") if provisioned else "pending",
        },
        {
            "n": "04",
            "label": "10-min audit run",
            "detail": "open workspace → upload → 4-track verdict",
            "state": "pending",
        },
    ]


async def provision_audit_access(
    session,
    *,
    inviter,
    email: str,
    company: str,
    module: str,
    label: str,
    reference: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Mint an end_user invitation + 6-digit access code + email, scoped to
    one audit ``module``. Shared by the public marketing funnel
    (``_provision_audit``) and the broker-initiated "create private access"
    flow. The caller commits the session.

    Returns ``{invitation, code, verify_url, onboarding_url, email_sent}``.
    """
    inv, token = await invites.create_invitation(
        session,
        inviter=inviter,
        email=str(email),
        target_account_type="end_user",
        allowed_modules=[module],
        display_name=f"{(company or '').strip()} · {label} · {reference or ''}".strip(" ·")[:255],
    )
    code = _gen_access_code()
    inv.code_hash = code_hash(code)
    inv.code_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.audit_code_ttl_minutes
    )
    inv.code_attempts = 0
    inv.intake_reference = reference
    inv.tenant_id = tenant_id
    base = settings.app_base_url.rstrip("/")
    onboarding_url = f"{base}/invite/{token}"
    verify_url = f"{base}/verify?email={quote(str(email))}"
    ref_line = f"\nReference: {reference}\n" if reference else "\n"
    ref_html = (
        f"<p style='color:#888'>Reference: {reference}</p>" if reference else ""
    )
    subject = (
        f"Your Cortex {label} access code"
        + (f" — {reference}" if reference else "")
    )
    text = (
        f"Your {label} workspace is ready.\n\n"
        f"Access code: {code}\n\n"
        f"Enter it here to open your audit dashboard:\n"
        f"{verify_url}\n\n"
        f"This code expires in {settings.audit_code_ttl_minutes} minutes.\n\n"
        f"Prefer a password? Use this link instead:\n{onboarding_url}\n"
        f"{ref_line}"
    )
    html = (
        f"<p>Your <strong>{label}</strong> workspace is ready.</p>"
        f"<p>Your access code is:</p>"
        f"<p style='font-size:28px;font-weight:700;letter-spacing:6px;"
        f"font-family:monospace'>{code}</p>"
        f'<p><a href="{verify_url}">Enter your code</a> to open your audit '
        f"dashboard. This code expires in "
        f"{settings.audit_code_ttl_minutes} minutes.</p>"
        f'<p style="color:#888">Prefer a password? '
        f'<a href="{onboarding_url}">Use this link instead</a>.</p>'
        f"{ref_html}"
    )
    email_sent = await send_email_guarded(to=str(email), subject=subject, html=html, text=text)
    if not email_sent:
        # EMAIL_ENABLED=false (or SES failure): the code is non-retrievable
        # by the recipient, so log it for testing/manual relay.
        logger.info(
            "audit-access provisioned ref=%s email=%s code=%s",
            reference, email, code,
        )
    return {
        "invitation": inv,
        "code": code,
        "verify_url": verify_url,
        "onboarding_url": onboarding_url,
        "email_sent": bool(email_sent),
    }


async def _provision_audit(session, row, body) -> dict:
    """Create a real user-management invitation for the audit lead, email the
    onboarding link, and advance the submission lifecycle. Best-effort: any
    failure leaves status='received' and is logged (intake never breaks)."""
    out: dict = {"status": row.status, "onboarding_url": None, "email_sent": False}
    try:
        inviter_email = settings.intake_inviter_email or settings.bootstrap_auth_email
        inviter = await um_store.get_user_by_email(session, inviter_email)
        if inviter is None:
            logger.warning("intake.provision: inviter %r not found — skipped", inviter_email)
            return out
        module = AUDIT_MODULE.get(body.audit_type, "cortex_audit")
        label = AUDIT_LABEL.get(body.audit_type, "Cortex Audit")
        res = await provision_audit_access(
            session,
            inviter=inviter,
            email=str(body.contact.email),
            company=row.company or "",
            module=module,
            label=label,
            reference=row.reference,
            tenant_id=None,  # public funnel: store.create_user auto-assigns
        )
        row.status = "access_sent" if res["email_sent"] else "provisioned"
        row.payload_json = {
            **(row.payload_json or {}),
            "provision": {
                "invitation_id": res["invitation"].id,
                "module": module,
                "onboarding_url": res["onboarding_url"],
                "verify_url": res["verify_url"],
                "email_sent": res["email_sent"],
            },
        }
        out = {
            "status": row.status,
            "onboarding_url": res["onboarding_url"],
            "email_sent": res["email_sent"],
        }
    except Exception as exc:  # noqa: BLE001 — never break intake
        logger.warning("intake.provision failed ref=%s err=%s", row.reference, exc)
    return out


def _build_uniesales_envelope(body: "IntakeIn", page_url: str | None) -> dict:
    """Convert the Pydantic intake body into the UnieSales envelope shape
    (see UnieSales_Backend/docs/public-site-intake.md).

    Tag is the form's discriminator (audit_request | partner_application).
    Contact is normalized to {contactName, email, phone?, company?, title?}.
    All structured fields land verbatim under `fields`.
    """
    c = body.contact
    if body.form == "audit_request":
        contact = {
            "contactName": f"{c.first_name} {c.last_name}".strip(),
            "email": c.email,
            "phone": c.phone or None,
            "company": c.company,
            "title": c.role,
        }
        fields = {
            "audit_type": body.audit_type,
            "problems": list(body.problems or []),
            "baseline": dict(body.baseline or {}),
            "volume": body.volume.model_dump() if body.volume else {},
            "has_data_ready": bool(body.has_data_ready),
            "notes": body.notes or "",
            "page_path": body.page_path,
            "company_site": c.company_site or "",
        }
    else:  # partner_application
        contact = {
            "contactName": c.name,
            "email": c.email,
            "phone": c.phone or None,
            "company": c.company,
        }
        fields = {
            "partner_type": body.partner_type,
            "book_types": list(body.book_types or []),
            "focus_areas": list(body.focus_areas or []),
            "revenue_models": list(body.revenue_models or []),
            "book_size": body.book_size or "",
            "site": c.site or "",
            "notes": body.notes or "",
            "page_path": body.page_path,
        }
    # Strip None values from contact (UnieSales doesn't want explicit nulls)
    contact = {k: v for k, v in contact.items() if v not in (None, "")}
    return {
        "tag": body.form,
        "page_url": page_url or body.page_path,
        "contact": contact,
        "fields": fields,
        "meta": {"submittedAt": datetime.now(timezone.utc).isoformat()},
    }


async def _mirror_to_uniesales(body: "IntakeIn", page_url: str | None) -> None:
    """Fire-and-forget HMAC-signed POST to UnieSales' uniecortex endpoint.

    Failure here never raises, never blocks the audit-onboarding email path,
    and never alters the user-facing response. Logs a warning on any error.

    Skipped silently when the base URL is empty or the HMAC secret is unset.
    """
    base = (settings.uniesales_public_intake_url or "").rstrip("/")
    secret = settings.uniesales_intake_hmac_secret or ""
    if not base or not secret:
        logger.debug(
            "uniesales mirror skipped: base_url=%r secret_set=%s",
            base, bool(secret),
        )
        return

    try:
        envelope = _build_uniesales_envelope(body, page_url)
        # Canonical JSON: sort_keys + no spaces, so the signature matches what
        # UnieSales recomputes from the raw body.
        raw = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hmac.new(
            secret.encode("utf-8"),
            raw,
            hashlib.sha256,
        ).hexdigest()
        url = f"{base}/public/intake/uniecortex"
        timeout = settings.uniesales_mirror_timeout_seconds
    except Exception as build_exc:  # noqa: BLE001
        logger.warning("uniesales mirror payload-build failed: %s", build_exc)
        return

    try:
        # Lazy-import httpx so import failures (or a chaos-mode replacement)
        # never break Cortex on startup.
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-UnieSales-Signature": f"sha256={signature}",
                    "User-Agent": "CortexBackend-mirror/1.0",
                },
            )
        if resp.status_code >= 400 and resp.status_code != 409:
            logger.warning(
                "uniesales mirror HTTP %s for %s: %s",
                resp.status_code,
                envelope.get("contact", {}).get("email"),
                resp.text[:300],
            )
        else:
            logger.info(
                "uniesales mirror ok status=%s email=%s tag=%s",
                resp.status_code,
                envelope.get("contact", {}).get("email"),
                envelope.get("tag"),
            )
    except Exception as exc:  # noqa: BLE001 — never break intake
        logger.warning(
            "uniesales mirror failed (cortex onboarding unaffected): %s",
            exc,
        )


@router.post("/intake", response_model=IntakeResponse)
async def submit_intake(
    request: Request,
    body: IntakeIn = Body(...),
) -> IntakeResponse:
    # This endpoint is kept ALIVE as-is. It drives Cortex's audit-request
    # auto-provisioning + onboarding email — interrupting it would break the
    # cortex audit workflow. After provisioning completes we fire a
    # fire-and-forget HMAC-signed mirror to UnieSales (_mirror_to_uniesales,
    # below) so the lead lands in the sales workspace. Mirror failure is
    # logged and never raised.
    client_ip = _client_ip(request)
    if not check_rate_limit(f"public-intake:{client_ip}"):
        raise HTTPException(429, "Too many requests, try again in a minute.")

    form_type = body.form
    payload = body.model_dump(mode="json")
    if form_type == "audit_request":
        email = body.contact.email
        company = body.contact.company
    else:
        email = body.contact.email
        company = body.contact.company

    user_agent = (request.headers.get("user-agent") or "")[:512]

    async with _with_session() as session:
        for _attempt in range(6):
            reference = _gen_reference(form_type)
            row = PublicIntakeSubmission(
                id=str(uuid.uuid4()),
                reference=reference,
                form_type=form_type,
                status="received",
                email=str(email),
                company=company,
                page_path=body.page_path,
                payload_json=payload,
                source_ip=client_ip,
                user_agent=user_agent,
            )
            session.add(row)
            try:
                await session.flush()
                break
            except IntegrityError:
                await session.rollback()
                continue
        else:
            raise HTTPException(500, "Could not allocate a reference, retry.")

        prov = {"status": "received", "onboarding_url": None, "email_sent": False}
        if form_type == "audit_request":
            prov = await _provision_audit(session, row, body)

    # ── Fire-and-forget UnieSales mirror ────────────────────────────────────
    # Runs AFTER the session commits (the `async with _with_session()` exited
    # above) so a slow / failing UnieSales never blocks the user response and
    # never affects the cortex onboarding email. Failure is logged in
    # _mirror_to_uniesales — we don't await its result.
    referer = request.headers.get("referer") or ""
    try:
        asyncio.create_task(_mirror_to_uniesales(body, referer or body.page_path))
    except Exception as exc:  # noqa: BLE001 — never break intake
        logger.warning("uniesales mirror dispatch failed: %s", exc)

    return IntakeResponse(
        reference=reference,
        status=prov["status"],
        audit_type=getattr(body, "audit_type", None),
        onboarding_url=prov["onboarding_url"],
        email_sent=prov["email_sent"],
    )


@router.get("/intake/{reference}/status", response_model=IntakeStatusResult)
async def intake_status(reference: str) -> IntakeStatusResult:
    async with _with_session() as session:
        row = (
            await session.execute(
                select(PublicIntakeSubmission).where(
                    PublicIntakeSubmission.reference == reference
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Unknown reference.")
    prov = (row.payload_json or {}).get("provision") or {}
    email_sent = bool(prov.get("email_sent"))
    return IntakeStatusResult(
        reference=row.reference,
        status=row.status,
        email_sent=email_sent,
        onboarding_url=prov.get("onboarding_url"),
        steps=[IntakeStatusStep(**s) for s in _audit_steps(row.status, email_sent, row.email)],
    )


@admin_router.get("/submissions", response_model=IntakeSubmissionsResult)
async def list_intake_submissions(
    form_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> IntakeSubmissionsResult:
    async with _with_session() as session:
        stmt = select(PublicIntakeSubmission)
        if form_type:
            stmt = stmt.where(PublicIntakeSubmission.form_type == form_type)
        if status:
            stmt = stmt.where(PublicIntakeSubmission.status == status)
        if email:
            stmt = stmt.where(
                func.lower(PublicIntakeSubmission.email) == email.strip().lower()
            )
        stmt = stmt.order_by(PublicIntakeSubmission.created_at.desc())
        total = int(
            await _safe_scalar(
                session, select(func.count()).select_from(stmt.subquery())
            )
        )
        rows = (
            (await session.execute(stmt.limit(limit).offset(offset)))
            .scalars()
            .all()
        )
    return IntakeSubmissionsResult(
        submissions=[
            IntakeSubmissionRow(
                id=r.id,
                reference=r.reference,
                form_type=r.form_type,
                status=r.status,
                email=r.email,
                company=r.company,
                page_path=r.page_path,
                payload=r.payload_json or {},
                created_at=(r.created_at.isoformat() if r.created_at else ""),
            )
            for r in rows
        ],
        count=total,
        limit=limit,
        offset=offset,
    )


_CORTEX_AUDIT_RUN_TYPE = "cortex_audit_v1"


class SubmissionRunRow(BaseModel):
    run_id: str
    tenant_id: Optional[str] = None
    status: str
    label: Optional[str] = None
    percent: Optional[float] = None
    input_summary: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class SubmissionRunsResult(BaseModel):
    reference: str
    invitation_id: Optional[str] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    tenant_id: Optional[str] = None
    accepted_at: Optional[str] = None
    runs: list[SubmissionRunRow] = Field(default_factory=list)


@admin_router.get(
    "/submissions/{reference}/runs", response_model=SubmissionRunsResult
)
async def submission_runs(reference: str) -> SubmissionRunsResult:
    """Join lead → invitation → provisioned user → tenant → Cortex Audit
    runs. Authenticated (mounted on the non-``/v1/public`` admin prefix)."""
    async with _with_session() as session:
        sub = (
            await session.execute(
                select(PublicIntakeSubmission).where(
                    PublicIntakeSubmission.reference == reference
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            raise HTTPException(404, "Unknown reference.")
        inv = (
            await session.execute(
                select(AuthInvitation)
                .where(AuthInvitation.intake_reference == reference)
                .order_by(AuthInvitation.created_at.desc())
            )
        ).scalars().first()
        user: Optional[AuthUser] = None
        if inv is not None and inv.accepted_user_id:
            user = (
                await session.execute(
                    select(AuthUser).where(AuthUser.id == inv.accepted_user_id)
                )
            ).scalar_one_or_none()
        if user is None:
            email = (inv.email if inv is not None else sub.email) or ""
            if email:
                user = (
                    await session.execute(
                        select(AuthUser).where(
                            func.lower(AuthUser.email) == email.strip().lower()
                        )
                    )
                ).scalar_one_or_none()
        rows: list[SellerOptimizationRun] = []
        if user is not None and user.tenant_id:
            rows = list(
                (
                    await session.execute(
                        select(SellerOptimizationRun)
                        .where(SellerOptimizationRun.tenant_id == user.tenant_id)
                        .where(
                            SellerOptimizationRun.run_type
                            == _CORTEX_AUDIT_RUN_TYPE
                        )
                        .where(SellerOptimizationRun.status != "deleted")
                        .order_by(SellerOptimizationRun.created_at.desc())
                    )
                ).scalars().all()
            )
    return SubmissionRunsResult(
        reference=reference,
        invitation_id=(inv.id if inv is not None else None),
        user_id=(user.id if user is not None else None),
        user_email=(user.email if user is not None else None),
        tenant_id=(user.tenant_id if user is not None else None),
        accepted_at=(
            inv.accepted_at.isoformat()
            if inv is not None and inv.accepted_at
            else None
        ),
        runs=[
            SubmissionRunRow(
                run_id=r.id,
                tenant_id=r.tenant_id,
                status=r.status,
                label=r.label,
                percent=r.percent,
                input_summary=r.input_summary,
                created_at=(r.created_at.isoformat() if r.created_at else None),
                completed_at=(
                    r.completed_at.isoformat() if r.completed_at else None
                ),
            )
            for r in rows
        ],
    )


class BookingRow(BaseModel):
    id: str
    email: str
    tenant_id: Optional[str] = None
    intake_reference: Optional[str] = None
    run_id: Optional[str] = None
    audit_type: Optional[str] = None
    specialist: Optional[str] = None
    slot_start: Optional[str] = None
    duration_min: int = 30
    timezone: Optional[str] = None
    notes: Optional[str] = None
    status: str = "requested"
    created_at: Optional[str] = None


class BookingsResult(BaseModel):
    bookings: list[BookingRow] = Field(default_factory=list)
    count: int = 0


@admin_router.get("/bookings", response_model=BookingsResult)
async def list_all_bookings(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> BookingsResult:
    """Every specialist booking, for the super-admin management tab.
    Authenticated (non-``/v1/public`` admin prefix)."""
    async with _with_session() as session:
        stmt = select(SpecialistBooking).order_by(
            SpecialistBooking.created_at.desc()
        )
        total = int(
            await _safe_scalar(
                session, select(func.count()).select_from(stmt.subquery())
            )
        )
        rows = (
            (await session.execute(stmt.limit(limit).offset(offset)))
            .scalars()
            .all()
        )
    return BookingsResult(
        bookings=[
            BookingRow(
                id=b.id,
                email=b.email,
                tenant_id=b.tenant_id,
                intake_reference=b.intake_reference,
                run_id=b.run_id,
                audit_type=b.audit_type,
                specialist=b.specialist,
                slot_start=(b.slot_start.isoformat() if b.slot_start else None),
                duration_min=b.duration_min,
                timezone=b.timezone,
                notes=b.notes,
                status=b.status,
                created_at=(b.created_at.isoformat() if b.created_at else None),
            )
            for b in rows
        ],
        count=total,
    )


class ApprovalResult(BaseModel):
    reference: str
    status: str
    user_id: Optional[str] = None
    granted_module: Optional[str] = None


class DenyBody(BaseModel):
    note: Optional[str] = Field(None, max_length=2000)


async def _load_pending_request(session, reference: str):
    sub = (
        await session.execute(
            select(PublicIntakeSubmission).where(
                PublicIntakeSubmission.reference == reference
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(404, "Unknown reference.")
    if sub.status != "pending_review":
        raise HTTPException(409, f"Request is not pending (status={sub.status}).")
    return sub


@admin_router.post(
    "/submissions/{reference}/approve", response_model=ApprovalResult
)
async def approve_audit_request(
    reference: str,
    approver=Depends(require_authenticated_user()),
) -> ApprovalResult:
    """Approve an in-app "request another / new type of audit". Grants the
    requested module to the requester through the canonical,
    permission-checked ``store.update_allowed_modules`` (super_admin → any;
    broker → only their own child users)."""
    async with _with_session() as session:
        sub = await _load_pending_request(session, reference)
        payload = sub.payload_json or {}
        req = payload.get("audit_request") or {}
        module = req.get("module")
        audit_type = req.get("requested_audit_type")
        requester_id = req.get("requested_by_user_id")
        if not module:
            module = AUDIT_MODULE.get(str(audit_type or ""), None)
        if not module:
            raise HTTPException(400, "Request is missing a target module.")
        label = AUDIT_LABEL.get(str(audit_type or ""), "Cortex Audit")

        user = None
        if requester_id:
            user = await um_store.get_user_by_id(session, requester_id)
        if user is None and sub.email:
            user = await um_store.get_user_by_email(session, sub.email)
        if user is None:
            raise HTTPException(404, "Requester account not found.")

        current = list(user.allowed_modules or [])
        union = current + ([module] if module not in current else [])
        try:
            user = await um_store.update_allowed_modules(
                session,
                viewer=approver,
                target_user_id=user.id,
                allowed_modules=union,
            )
        except PermissionError:
            raise HTTPException(403, "You cannot manage this user.")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        sub.status = "approved"
        sub.payload_json = {
            **payload,
            "audit_request": {
                **req,
                "approved_by": approver.id,
                "approved_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        # Best-effort heads-up; never block approval on email.
        try:
            await send_email_guarded(
                to=user.email,
                subject=f"Your {label} is enabled",
                html=(
                    f"<p>Good news — your <strong>{label}</strong> workspace "
                    f"is now enabled. Sign in and pick it from your audit "
                    f"switcher to upload data.</p>"
                ),
                text=(
                    f"Your {label} workspace is now enabled. Sign in and pick "
                    f"it from your audit switcher to upload data.\n"
                ),
            )
        except Exception:  # noqa: BLE001
            pass
        return ApprovalResult(
            reference=reference,
            status="approved",
            user_id=user.id,
            granted_module=module,
        )


@admin_router.post(
    "/submissions/{reference}/deny", response_model=ApprovalResult
)
async def deny_audit_request(
    reference: str,
    body: DenyBody = Body(default_factory=DenyBody),
    approver=Depends(require_authenticated_user()),
) -> ApprovalResult:
    async with _with_session() as session:
        sub = await _load_pending_request(session, reference)
        payload = sub.payload_json or {}
        req = payload.get("audit_request") or {}
        sub.status = "denied"
        sub.payload_json = {
            **payload,
            "audit_request": {
                **req,
                "denied_by": approver.id,
                "denied_at": datetime.now(timezone.utc).isoformat(),
                "deny_note": (body.note or "").strip() or None,
            },
        }
    return ApprovalResult(reference=reference, status="denied")


# --------------------------------------------------------------------------- #
# Site metrics (cached aggregate, live + static fallback)
# --------------------------------------------------------------------------- #
_METRICS_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}
_METRICS_TTL_SECONDS = 90
_METRICS_LOCK = asyncio.Lock()


def _metric(
    mid: str,
    label: str,
    live_value: float | None,
    static_value: str,
    formatter,
    delta: str = "",
    trend: str = "up",
) -> SiteMetric:
    """Live when the source has data; static marketing fallback on zero."""
    if live_value and float(live_value) > 0:
        return SiteMetric(
            id=mid,
            label=label,
            value=formatter(live_value),
            delta=delta,
            trend=trend,
            source="live",
        )
    return SiteMetric(
        id=mid,
        label=label,
        value=static_value,
        delta=delta,
        trend=trend,
        source="static",
    )


async def _compute_site_metrics() -> SiteMetricsResult:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    labels_30d = findings = found_usd = solver = lanes = asin = carriers = 0
    async with _with_session() as session:
        labels_30d = int(
            await _safe_scalar(
                session,
                select(func.count())
                .select_from(CortexAuditShipmentFact)
                .where(CortexAuditShipmentFact.ingested_at >= cutoff),
            )
        )
        findings = int(
            await _safe_scalar(
                session, select(func.count()).select_from(CortexAuditFinding)
            )
        )
        found_usd = float(
            await _safe_scalar(
                session,
                select(func.coalesce(func.sum(CortexAuditFinding.claimed_refund_usd), 0.0)),
            )
        )
        solver = int(
            await _safe_scalar(
                session,
                select(func.count())
                .select_from(SellerOptimizationRun)
                .where(
                    SellerOptimizationRun.status.in_(
                        ["completed", "complete", "done", "success", "succeeded"]
                    )
                ),
            )
        )
        lanes = int(
            await _safe_scalar(
                session, select(func.count()).select_from(LtlQuoteFullOutput)
            )
        )
        asin = int(
            await _safe_scalar(
                session, select(func.count()).select_from(EntityReport)
            )
        )
        carriers = int(
            await _safe_scalar(
                session,
                select(func.count(func.distinct(CortexVaultCarrierCredential.carrier_id))),
            )
        )

    ticker = [
        _metric("labels-30d", "Labels audited · 30d", labels_30d, "4.2M", _fmt_count, "+12.4%"),
        _metric("refunds", "Refunds recovered", found_usd, "$184k", _fmt_usd, "+8.1%"),
        _metric("anomalies", "Anomalies surfaced", findings, "12,840", _fmt_count, "+22%"),
        _metric("solver", "AI solver cycles", solver, "892/d", _fmt_count, "+38%"),
        _metric("lanes", "Lanes optimized", lanes, "1,432", _fmt_count, "+14%"),
        _metric("asin", "ASIN scores", asin, "38k", _fmt_count, "+9.2%"),
        SiteMetric(id="confidence", label="Avg confidence", value="0.94", delta="±0.01", trend="flat", source="static"),
        SiteMetric(id="latency", label="p95 API latency", value="47ms", delta="−6ms", trend="down", source="static"),
        SiteMetric(id="nodes", label="Live participating nodes", value="5,147", delta="+312", trend="up", source="static"),
        _metric("carriers", "Carriers in vault", carriers, "12", _fmt_count, "", "flat"),
    ]
    hero = {
        "p95_latency_ms": "47ms",
        "live_nodes": "5,147",
        "confidence": "0.94",
        "version": "v4.2.1",
    }
    network = {
        "yoy_pct": "+16%",
        "participating_nodes": "5,147",
        "refunds_recovered_30d": _fmt_usd(found_usd) if found_usd > 0 else "$184k",
        "refunds_source": "live" if found_usd > 0 else "static",
        "avg_cycle_minutes": "4.2m",
    }
    return SiteMetricsResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        ticker=ticker,
        hero=hero,
        network=network,
    )


@router.get("/site-metrics", response_model=SiteMetricsResult)
async def site_metrics(request: Request) -> SiteMetricsResult:
    now = time.monotonic()
    if _METRICS_CACHE["payload"] is not None and now < _METRICS_CACHE["expires_at"]:
        return _METRICS_CACHE["payload"]
    async with _METRICS_LOCK:
        now = time.monotonic()
        if _METRICS_CACHE["payload"] is not None and now < _METRICS_CACHE["expires_at"]:
            return _METRICS_CACHE["payload"]
        payload = await _compute_site_metrics()
        _METRICS_CACHE["payload"] = payload
        _METRICS_CACHE["expires_at"] = time.monotonic() + _METRICS_TTL_SECONDS
        return payload
