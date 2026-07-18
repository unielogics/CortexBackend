from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from unie_cortex.db.models import (
    ApiClientTemplate,
    ApiCredential,
    ApiCredentialActivity,
    ApiCredentialLog,
)


OMS_TEMPLATE_ID = "oms-cortex-intelligence"
WMS_TEMPLATE_ID = "wms-cortex-runtime"
DEFAULT_OMS_SCOPES = [
    "cortex:product_research:run",
    "cortex:seller_optimization:run",
    "cortex:rate_shop:run",
    "cortex:oms_orchestration:write",
    "cortex:intelligence_context:read",
]
DEFAULT_MODEL_SETTINGS = {
    "model_profile": "marketplace_first",
    "data_priority": ["marketplace", "wms_truth", "csv", "manual"],
    "seller_optimization_cadence_days": 30,
    "inventory_snapshot_cadence_minutes": 10,
    "product_research_mode": "on_demand",
    "nvidia_cuopt_enabled": True,
    "confidence_thresholds": {
        "auto_recommend": 0.78,
        "approval_required": 0.65,
        "human_review_required": 0.0,
    },
    "guardrails": {
        "approval_required_for": [
            "wms_work_change",
            "tms_dispatch",
            "carrier_purchase",
            "billing_refund_submission",
            "physical_inventory_execution",
        ],
    },
}
DEFAULT_RATE_LIMITS = {"per_minute": 120, "concurrent_runs": 3}
DEFAULT_WMS_SCOPES = [
    "wms.runtime",
    "wms.decisions.read",
    "wms.outcomes.write",
    # WMS is an orchestration client too: it triggers per-client network optimization,
    # reads the decision review API, and posts operator grade/relay feedback under
    # /v1/orchestration/oms/*, all of which require this scope.
    "cortex:oms_orchestration:write",
]


class CredentialAuthError(Exception):
    def __init__(self, code: str, status_code: int = 401, credential: ApiCredential | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.credential = credential


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_secret(secret_key: str) -> str:
    return hashlib.sha256(secret_key.encode("utf-8")).hexdigest()


def generate_secret_key() -> str:
    return f"ctx_sk_{secrets.token_urlsafe(32)}"


def secret_prefix(secret_key: str) -> str:
    return secret_key[:14]


def generate_tenant_key() -> str:
    return f"ctx_tenant_{secrets.token_urlsafe(18)}"


def _slug(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    out = "-".join(part for part in out.split("-") if part)
    return (out or "client")[:28]


async def ensure_default_templates(session: AsyncSession) -> None:
    existing = await session.get(ApiClientTemplate, OMS_TEMPLATE_ID)
    now = utcnow()
    if existing is None:
        session.add(
            ApiClientTemplate(
                id=OMS_TEMPLATE_ID,
                name="OMS Cortex Intelligence",
                description="Marketplace-first OMS intelligence client for Product Research, Seller Optimization, rate shop, and orchestration.",
                category="oms_account",
                default_scopes=DEFAULT_OMS_SCOPES,
                default_model_settings=DEFAULT_MODEL_SETTINGS,
                default_rate_limits=DEFAULT_RATE_LIMITS,
                approval_required=False,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
    else:
        existing.name = "OMS Cortex Intelligence"
        existing.description = "Marketplace-first OMS intelligence client for Product Research, Seller Optimization, rate shop, and orchestration."
        existing.category = "oms_account"
        existing.default_scopes = DEFAULT_OMS_SCOPES
        existing.default_model_settings = DEFAULT_MODEL_SETTINGS
        existing.default_rate_limits = DEFAULT_RATE_LIMITS
        existing.status = "active"
        existing.updated_at = now
        await session.flush()

    # WMS template
    wms_existing = await session.get(ApiClientTemplate, WMS_TEMPLATE_ID)
    if wms_existing is None:
        session.add(
            ApiClientTemplate(
                id=WMS_TEMPLATE_ID,
                name="WMS Cortex Runtime",
                description="Per-warehouse Cortex runtime credential. Used by UnieWMS to call Cortex decision/orchestration endpoints.",
                category="wms_warehouse",
                default_scopes=DEFAULT_WMS_SCOPES,
                default_model_settings={},
                default_rate_limits=DEFAULT_RATE_LIMITS,
                approval_required=False,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
    else:
        wms_existing.name = "WMS Cortex Runtime"
        wms_existing.description = "Per-warehouse Cortex runtime credential. Used by UnieWMS to call Cortex decision/orchestration endpoints."
        wms_existing.category = "wms_warehouse"
        wms_existing.default_scopes = DEFAULT_WMS_SCOPES
        wms_existing.default_model_settings = {}
        wms_existing.default_rate_limits = DEFAULT_RATE_LIMITS
        wms_existing.status = "active"
        wms_existing.updated_at = now
        await session.flush()


def template_to_dict(t: ApiClientTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "default_scopes": t.default_scopes or [],
        "default_model_settings": t.default_model_settings or {},
        "default_rate_limits": t.default_rate_limits or {},
        "approval_required": bool(t.approval_required),
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def credential_to_dict(c: ApiCredential, *, include_secret: str | None = None) -> dict[str, Any]:
    data = {
        "id": c.id,
        "api_username": c.api_username,
        "secret_prefix": c.secret_prefix,
        "template_id": c.template_id,
        "category": c.category,
        "source_system": c.source_system,
        "environment": c.environment,
        "associated_user_id": c.associated_user_id,
        "external_user_id": c.external_user_id,
        "tenant_key": c.tenant_key,
        "account_name": c.account_name,
        "company_name": c.company_name,
        "relationship_owner_name": c.relationship_owner_name,
        "relationship_owner_email": c.relationship_owner_email,
        "scopes": c.scopes or [],
        "model_settings": c.model_settings or {},
        "rate_limits": c.rate_limits or {},
        "metadata": c.metadata_json or {},
        "status": c.status,
        "intelligence_enabled": bool(c.intelligence_enabled),
        "blocked_reason": c.blocked_reason,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
        "last_rotated_at": c.last_rotated_at.isoformat() if c.last_rotated_at else None,
        "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
        "created_by_user_id": c.created_by_user_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }
    if include_secret:
        data["secret_key"] = include_secret
    return data


def activity_to_dict(a: ApiCredentialActivity) -> dict[str, Any]:
    return {
        "id": a.id,
        "credential_id": a.credential_id,
        "actor_user_id": a.actor_user_id,
        "event_type": a.event_type,
        "summary": a.summary,
        "payload": a.payload or {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def log_to_dict(l: ApiCredentialLog) -> dict[str, Any]:
    return {
        "id": l.id,
        "credential_id": l.credential_id,
        "api_username": l.api_username,
        "request_id": l.request_id,
        "method": l.method,
        "path": l.path,
        "status_code": l.status_code,
        "duration_ms": l.duration_ms,
        "source_ip": l.source_ip,
        "user_agent": l.user_agent,
        "scope": l.scope,
        "run_type": l.run_type,
        "entity_refs": l.entity_refs or {},
        "error_summary": l.error_summary,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }


async def record_activity(
    session: AsyncSession,
    *,
    credential_id: str | None,
    event_type: str,
    summary: str | None = None,
    actor_user_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ApiCredentialActivity:
    row = ApiCredentialActivity(
        id=str(uuid.uuid4()),
        credential_id=credential_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        summary=summary,
        payload=payload or {},
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def list_templates(session: AsyncSession) -> list[ApiClientTemplate]:
    await ensure_default_templates(session)
    stmt = select(ApiClientTemplate).order_by(ApiClientTemplate.category.asc(), ApiClientTemplate.name.asc())
    return list((await session.execute(stmt)).scalars().all())


async def list_credentials(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[ApiCredential]:
    stmt = select(ApiCredential)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(ApiCredential.api_username).like(like),
                func.lower(ApiCredential.account_name).like(like),
                func.lower(ApiCredential.company_name).like(like),
                func.lower(ApiCredential.relationship_owner_email).like(like),
            )
        )
    if category:
        stmt = stmt.where(ApiCredential.category == category)
    if status:
        stmt = stmt.where(ApiCredential.status == status)
    stmt = stmt.order_by(ApiCredential.created_at.desc()).limit(max(1, min(limit, 500)))
    return list((await session.execute(stmt)).scalars().all())


async def _unique_username(session: AsyncSession, *, category: str, name: str) -> str:
    prefix = {
        "oms_account": "oms",
        "cortex_intelligence": "ctx",
        "wms_integration": "wms",
        "third_party_partner": "partner",
        "internal_service": "svc",
        "carrier_partner": "carrier",
    }.get(category, "api")
    base = f"{prefix}_{_slug(name)}"
    for _ in range(8):
        candidate = f"{base}_{secrets.token_hex(3)}"
        exists = (
            await session.execute(select(ApiCredential.id).where(ApiCredential.api_username == candidate))
        ).scalar_one_or_none()
        if not exists:
            return candidate
    return f"{base}_{secrets.token_hex(8)}"


async def create_credential(
    session: AsyncSession,
    *,
    template_id: str = OMS_TEMPLATE_ID,
    account_name: str | None = None,
    company_name: str | None = None,
    relationship_owner_name: str | None = None,
    relationship_owner_email: str | None = None,
    associated_user_id: str | None = None,
    external_user_id: str | None = None,
    source_system: str = "oms",
    environment: str = "production",
    scopes: list[str] | None = None,
    model_settings: dict[str, Any] | None = None,
    rate_limits: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    created_by_user_id: str | None = None,
) -> tuple[ApiCredential, str]:
    await ensure_default_templates(session)
    template = await session.get(ApiClientTemplate, template_id)
    if template is None:
        raise ValueError("template_not_found")
    now = utcnow()
    category = template.category
    display_name = account_name or company_name or relationship_owner_email or external_user_id or "client"
    secret_key = generate_secret_key()
    credential = ApiCredential(
        id=str(uuid.uuid4()),
        api_username=await _unique_username(session, category=category, name=display_name),
        secret_key_hash=hash_secret(secret_key),
        secret_prefix=secret_prefix(secret_key),
        template_id=template.id,
        category=category,
        source_system=source_system,
        environment=environment,
        associated_user_id=associated_user_id,
        external_user_id=external_user_id,
        tenant_key=generate_tenant_key(),
        account_name=account_name,
        company_name=company_name,
        relationship_owner_name=relationship_owner_name,
        relationship_owner_email=relationship_owner_email,
        scopes=scopes or template.default_scopes or [],
        model_settings={**(template.default_model_settings or {}), **(model_settings or {})},
        rate_limits={**(template.default_rate_limits or {}), **(rate_limits or {})},
        metadata_json=metadata or {},
        status="active",
        intelligence_enabled=True,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(credential)
    await session.flush()
    await record_activity(
        session,
        credential_id=credential.id,
        actor_user_id=created_by_user_id,
        event_type="credential_created",
        summary=f"Created API username {credential.api_username}",
        payload={"template_id": template.id, "source_system": source_system},
    )
    return credential, secret_key


async def provision_oms_credential(session: AsyncSession, payload: dict[str, Any]) -> tuple[ApiCredential, str, bool]:
    external_user_id = str(payload.get("external_user_id") or payload.get("oms_user_id") or "").strip() or None
    if external_user_id:
        stmt = select(ApiCredential).where(
            ApiCredential.source_system == "oms",
            ApiCredential.external_user_id == external_user_id,
            ApiCredential.status != "revoked",
        )
        existing = (await session.execute(stmt)).scalars().first()
        if existing is not None:
            existing_scopes = set(existing.scopes or [])
            missing_scopes = [scope for scope in DEFAULT_OMS_SCOPES if scope not in existing_scopes]
            if missing_scopes:
                existing.scopes = [*(existing.scopes or []), *missing_scopes]
                existing.updated_at = utcnow()
                await record_activity(
                    session,
                    credential_id=existing.id,
                    event_type="oms_scopes_repaired",
                    summary=f"Repaired OMS Cortex scopes for user {external_user_id}",
                    payload={"added_scopes": missing_scopes},
                )
            return existing, "", False
    credential, secret_key = await create_credential(
        session,
        template_id=str(payload.get("template_id") or OMS_TEMPLATE_ID),
        account_name=payload.get("account_name") or payload.get("name"),
        company_name=payload.get("company_name"),
        relationship_owner_name=payload.get("relationship_owner_name"),
        relationship_owner_email=payload.get("relationship_owner_email") or payload.get("email"),
        associated_user_id=payload.get("associated_user_id"),
        external_user_id=external_user_id,
        source_system="oms",
        environment=payload.get("environment") or "production",
        scopes=payload.get("scopes") if isinstance(payload.get("scopes"), list) else None,
        model_settings=payload.get("model_settings") if isinstance(payload.get("model_settings"), dict) else None,
        rate_limits=payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else None,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        created_by_user_id=payload.get("created_by_user_id"),
    )
    await record_activity(
        session,
        credential_id=credential.id,
        event_type="oms_auto_provisioned",
        summary="Auto-provisioned from UnieConnect OMS",
        payload={"external_user_id": external_user_id},
    )
    return credential, secret_key, True


async def rotate_secret(session: AsyncSession, credential: ApiCredential, actor_user_id: str | None = None) -> str:
    secret_key = generate_secret_key()
    now = utcnow()
    credential.secret_key_hash = hash_secret(secret_key)
    credential.secret_prefix = secret_prefix(secret_key)
    credential.last_rotated_at = now
    credential.revoked_at = None
    credential.status = "active"
    credential.updated_at = now
    await record_activity(
        session,
        credential_id=credential.id,
        actor_user_id=actor_user_id,
        event_type="secret_rotated",
        summary=f"Rotated secret for {credential.api_username}",
    )
    await session.flush()
    return secret_key


async def verify_username_secret(
    session: AsyncSession,
    *,
    api_username: str,
    secret_key: str,
) -> ApiCredential:
    stmt = select(ApiCredential).where(ApiCredential.api_username == api_username)
    credential = (await session.execute(stmt)).scalar_one_or_none()
    if credential is None:
        raise CredentialAuthError("credential_not_found")
    if credential.status in {"revoked", "inactive", "paused"} or credential.revoked_at is not None:
        raise CredentialAuthError("credential_inactive", 403, credential)
    if credential.expires_at and credential.expires_at <= utcnow():
        raise CredentialAuthError("credential_expired", 403, credential)
    if not hmac.compare_digest(credential.secret_key_hash or "", hash_secret(secret_key)):
        raise CredentialAuthError("invalid_secret", 401, credential)
    if not credential.intelligence_enabled or credential.status == "blocked":
        raise CredentialAuthError("credential_blocked", 403, credential)
    credential.last_used_at = utcnow()
    credential.updated_at = utcnow()
    await session.flush()
    return credential


def extract_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    if not authorization or not authorization.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(authorization[6:].strip()).decode("utf-8")
    except Exception:
        return None
    if ":" not in raw:
        return None
    username, secret_key = raw.split(":", 1)
    if not username or not secret_key:
        return None
    return username, secret_key


async def record_request_log(
    session: AsyncSession,
    *,
    credential: ApiCredential | None = None,
    api_username: str | None = None,
    request_id: str | None = None,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    scope: str | None = None,
    run_type: str | None = None,
    entity_refs: dict[str, Any] | None = None,
    error_summary: str | None = None,
) -> None:
    session.add(
        ApiCredentialLog(
            id=str(uuid.uuid4()),
            credential_id=credential.id if credential else None,
            api_username=credential.api_username if credential else api_username,
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            source_ip=source_ip,
            user_agent=user_agent,
            scope=scope,
            run_type=run_type,
            entity_refs=entity_refs or {},
            error_summary=error_summary,
            created_at=utcnow(),
        )
    )
    await session.flush()


async def provision_wms_credential(session: AsyncSession, payload: dict[str, Any]) -> tuple["ApiCredential", str, bool]:
    """Provision (or return existing) per-warehouse Cortex credential.

    Mirrors provision_oms_credential but keyed on warehouse_code via
    external_user_id slot (external_warehouse_code alias).
    """
    warehouse_code = str(payload.get("external_warehouse_code") or payload.get("warehouse_code") or "").strip() or None
    if warehouse_code:
        stmt = select(ApiCredential).where(
            ApiCredential.source_system == "wms",
            ApiCredential.external_user_id == warehouse_code,
            ApiCredential.status != "revoked",
        )
        existing = (await session.execute(stmt)).scalars().first()
        if existing is not None:
            return existing, "", False
    credential, secret_key = await create_credential(
        session,
        template_id=str(payload.get("template_id") or WMS_TEMPLATE_ID),
        account_name=payload.get("account_name") or (f"WMS warehouse {warehouse_code}" if warehouse_code else None),
        company_name=payload.get("company_name"),
        relationship_owner_name=payload.get("relationship_owner_name"),
        relationship_owner_email=payload.get("relationship_owner_email"),
        associated_user_id=payload.get("associated_user_id"),
        external_user_id=warehouse_code,
        source_system="wms",
        environment=payload.get("environment") or "production",
        scopes=payload.get("scopes") if isinstance(payload.get("scopes"), list) else None,
        model_settings=payload.get("model_settings") if isinstance(payload.get("model_settings"), dict) else None,
        rate_limits=payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else None,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {"warehouse_code": warehouse_code},
        created_by_user_id=payload.get("created_by_user_id"),
    )
    await record_activity(
        session,
        credential_id=credential.id,
        event_type="wms_auto_provisioned",
        summary=f"Auto-provisioned for WMS warehouse {warehouse_code}",
        payload={"warehouse_code": warehouse_code},
    )
    return credential, secret_key, True
