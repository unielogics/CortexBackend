"""Single source of truth for emitting Cortex decisions to the shared
analytical Postgres (cortex_ml.decision_log).

Every Cortex engine (cross-dock, transfer, LTL, FTL, TMS, micro, billing,
forward-demand) calls publish_decision() with a typed payload. The WMS-side
decision-consumer worker picks the row up within seconds.

This module is intentionally schema-aware (it asserts the row shape against
the contract WMS expects) so a new engine cannot accidentally land an
unparseable row in the table.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_publisher_engine = None
_publisher_session_factory = None


def _resolve_secret_password(url: str) -> str:
    """Overlay the URL's password with the live Secrets Manager credential.

    The static password embedded in CORTEX_DATABASE_URL drifts whenever the
    DB credential is rotated (this silently killed decision publishing for a
    month in June 2026). When CORTEX_DATABASE_SECRET_ARN (or, as a fallback,
    SEMANTIC_DATABASE_SECRET_ARN — same cluster/user) is set, prefer the
    secret's password. Any failure falls back to the URL as-is.
    """
    arn = (
        os.environ.get("CORTEX_DATABASE_SECRET_ARN", "").strip()
        or os.environ.get("SEMANTIC_DATABASE_SECRET_ARN", "").strip()
    )
    if not arn:
        return url
    try:
        import boto3

        region = arn.split(":")[3] if arn.count(":") >= 4 else os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("secretsmanager", region_name=region)
        secret = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
        password = secret.get("password", "")
        if not password:
            return url
        from urllib.parse import quote

        import re as _re

        new_url, n = _re.subn(
            r"(://[^:/@]+:)[^@]*(@)", r"\g<1>" + quote(password, safe="") + r"\g<2>", url, count=1
        )
        if n == 1:
            logger.info("decision_publisher: using DB password from Secrets Manager (%s)", arn.rsplit(":", 1)[-1])
            return new_url
    except Exception as exc:
        logger.warning(
            "decision_publisher: could not resolve DB secret %s (%s: %s); falling back to CORTEX_DATABASE_URL password",
            arn,
            type(exc).__name__,
            exc,
        )
    return url


def _get_session_factory():
    """Lazily build a dedicated engine pointed at the shared analytical DB.

    Uses CORTEX_DATABASE_URL (same string the WMS-side decision-consumer
    reads from), with the password overlaid from Secrets Manager when a
    secret ARN is configured. Has its own pool — separate from the Cortex
    API's SessionLocal — so writes never block API requests.
    """
    global _publisher_engine, _publisher_session_factory
    if _publisher_session_factory is not None:
        return _publisher_session_factory
    url = os.environ.get("CORTEX_DATABASE_URL", "").strip()
    if not url:
        return None
    url = _resolve_secret_password(url)
    # Normalize driver
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    # Strip query (asyncpg dislikes ?sslmode=)
    if "?" in url:
        url = url.split("?", 1)[0]
    import ssl as _ssl

    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE
    _publisher_engine = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=600,
        pool_size=5,
        max_overflow=10,
        pool_use_lifo=True,
        pool_reset_on_return="rollback",
        connect_args={"ssl": ssl_ctx},
    )
    _publisher_session_factory = async_sessionmaker(
        _publisher_engine, class_=AsyncSession, expire_on_commit=False
    )
    return _publisher_session_factory


async def invalidate_session_factory() -> None:
    """Drop the cached engine so the next call re-resolves credentials.

    Called on auth failures: after a credential rotation the long-running API
    process would otherwise keep the stale password until restart.
    """
    global _publisher_engine, _publisher_session_factory
    engine = _publisher_engine
    _publisher_engine = None
    _publisher_session_factory = None
    if engine is not None:
        try:
            await engine.dispose()
        except Exception:  # noqa: BLE001 - disposal is best-effort
            pass


def _is_auth_failure(exc: BaseException) -> bool:
    text_ = f"{type(exc).__name__}: {exc}"
    return "password authentication failed" in text_.lower() or "InvalidPasswordError" in text_


VALID_DECISION_TYPES = frozenset(
    {
        # Macro
        "cross_dock_recommendation",
        "inter_warehouse_transfer",
        "ltl_consolidation_suggestion",
        "ftl_trigger",
        "tms_truck_schedule",
        "tms_pickup_request",
        "tms_dropoff_request",
        "tms_lane_reservation",
        "forward_demand_projection",
        # Micro
        "task_priority",
        "putaway_zone_suggestion",
        "cycle_count_target",
        "pick_batch",
        "sla_risk_alert",
        # Billing
        "pricing_recommendation",
        "billing_audit_finding",
        "client_cost_optimization",
        # OMS closed-loop decisions
        "oms_recommendation",
        "oms_business_double",
        "oms_inventory_placement",
        "oms_shipment_plan",
        "wms_execution_truth",
    }
)


@dataclass
class DecisionPayload:
    tenant_id: str
    warehouse_id: str
    decision_type: str
    output_ref: dict[str, Any]
    input_ref: dict[str, Any] = field(default_factory=dict)
    model_version: str = "v1"
    decision_id: str | None = None
    decided_at_utc: datetime | None = None
    ingest_batch_id: str | None = None
    target_warehouse_id: str | None = None
    # Client attribution — scopes a decision to a single OMS client so the WMS
    # per-client Cortex tab + the OMS relay can filter to it. origin distinguishes
    # a warehouse-invited client (owned by owning_warehouse_code, needs WH review
    # before the client sees it) from a direct UnieConnect signup (self-owned,
    # suggestions go straight to the client). All optional/back-compatible.
    client_id: str | None = None
    origin: str | None = None  # 'warehouse_invited' | 'direct'
    owning_warehouse_code: str | None = None

    def validate(self) -> None:
        if self.decision_type not in VALID_DECISION_TYPES:
            raise ValueError(
                f"decision_type {self.decision_type!r} not in VALID_DECISION_TYPES"
            )
        if not self.tenant_id:
            raise ValueError("tenant_id required")
        if not self.warehouse_id:
            raise ValueError("warehouse_id required")
        if not isinstance(self.output_ref, dict):
            raise ValueError("output_ref must be dict")


async def publish_decision(payload: DecisionPayload) -> str:
    """Insert (or upsert) a decision_log row. Returns the decision_id used."""
    payload.validate()
    decision_id = payload.decision_id or f"cortex-{uuid.uuid4().hex[:16]}"
    decided_at = payload.decided_at_utc or datetime.now(timezone.utc)
    target_wh = payload.target_warehouse_id or payload.warehouse_id

    session_factory = _get_session_factory()
    if session_factory is None:
        logger.warning("publish_decision: CORTEX_DATABASE_URL not configured; skipping %s", decision_id)
        return decision_id

    async def _insert(factory) -> None:
        async with factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO cortex_ml.decision_log
                        (tenant_id, warehouse_id, decision_id, decided_at_utc,
                         decision_type, model_version, input_ref, output_ref,
                         schema_version, ingest_batch_id, target_warehouse_id,
                         client_id, origin, owning_warehouse_code)
                    VALUES
                        (:tenant_id, :warehouse_id, :decision_id, :decided_at_utc,
                         :decision_type, :model_version,
                         CAST(:input_ref AS jsonb), CAST(:output_ref AS jsonb),
                         'cortex_v1', :ingest_batch_id, :target_warehouse_id,
                         :client_id, :origin, :owning_warehouse_code)
                    ON CONFLICT (tenant_id, decision_id) DO UPDATE SET
                        decided_at_utc = EXCLUDED.decided_at_utc,
                        decision_type = EXCLUDED.decision_type,
                        model_version = EXCLUDED.model_version,
                        input_ref = EXCLUDED.input_ref,
                        output_ref = EXCLUDED.output_ref,
                        target_warehouse_id = EXCLUDED.target_warehouse_id,
                        client_id = EXCLUDED.client_id,
                        origin = EXCLUDED.origin,
                        owning_warehouse_code = EXCLUDED.owning_warehouse_code,
                        updated_at_utc = now()
                    """
                ),
                {
                    "tenant_id": payload.tenant_id,
                    "warehouse_id": payload.warehouse_id,
                    "decision_id": decision_id,
                    "decided_at_utc": decided_at,
                    "decision_type": payload.decision_type,
                    "model_version": payload.model_version,
                    "input_ref": json.dumps(payload.input_ref),
                    "output_ref": json.dumps(payload.output_ref),
                    "ingest_batch_id": payload.ingest_batch_id,
                    "target_warehouse_id": target_wh,
                    "client_id": payload.client_id,
                    "origin": payload.origin,
                    "owning_warehouse_code": payload.owning_warehouse_code,
                },
            )
            await session.commit()

    try:
        await _insert(session_factory)
    except Exception as exc:
        if not _is_auth_failure(exc):
            raise
        logger.warning(
            "publish_decision: auth failure (%s) — re-resolving DB credential and retrying once",
            type(exc).__name__,
        )
        await invalidate_session_factory()
        session_factory = _get_session_factory()
        if session_factory is None:
            raise
        await _insert(session_factory)
    logger.info(
        "publish_decision id=%s type=%s wh=%s",
        decision_id,
        payload.decision_type,
        target_wh,
    )
    return decision_id


async def publish_decisions_batch(payloads: list[DecisionPayload]) -> list[str]:
    """Publish many decisions in one transaction."""
    if not payloads:
        return []
    ids: list[str] = []
    session_factory = _get_session_factory()
    if session_factory is None:
        return ids

    async with session_factory() as session:
        for p in payloads:
            p.validate()
            did = p.decision_id or f"cortex-{uuid.uuid4().hex[:16]}"
            decided_at = p.decided_at_utc or datetime.now(timezone.utc)
            target_wh = p.target_warehouse_id or p.warehouse_id
            await session.execute(
                text(
                    """
                    INSERT INTO cortex_ml.decision_log
                        (tenant_id, warehouse_id, decision_id, decided_at_utc,
                         decision_type, model_version, input_ref, output_ref,
                         schema_version, ingest_batch_id, target_warehouse_id,
                         client_id, origin, owning_warehouse_code)
                    VALUES
                        (:tenant_id, :warehouse_id, :decision_id, :decided_at_utc,
                         :decision_type, :model_version,
                         CAST(:input_ref AS jsonb), CAST(:output_ref AS jsonb),
                         'cortex_v1', :ingest_batch_id, :target_warehouse_id,
                         :client_id, :origin, :owning_warehouse_code)
                    ON CONFLICT (tenant_id, decision_id) DO NOTHING
                    """
                ),
                {
                    "tenant_id": p.tenant_id,
                    "warehouse_id": p.warehouse_id,
                    "decision_id": did,
                    "decided_at_utc": decided_at,
                    "decision_type": p.decision_type,
                    "model_version": p.model_version,
                    "input_ref": json.dumps(p.input_ref),
                    "output_ref": json.dumps(p.output_ref),
                    "ingest_batch_id": p.ingest_batch_id,
                    "target_warehouse_id": target_wh,
                    "client_id": p.client_id,
                    "origin": p.origin,
                    "owning_warehouse_code": p.owning_warehouse_code,
                },
            )
            ids.append(did)
        await session.commit()
    return ids
