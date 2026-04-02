"""Unified persistence: MongoDB (MONGODB_URI) or SQLite/SQLAlchemy."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from unie_cortex.db.models import (
    AiInvocation,
    AsnFact,
    AuditRun,
    BillingLineFact,
    ColumnMapping,
    EmployeeFact,
    Engagement,
    FacilityFreightProfileRow,
    KeepaSnapshot,
    LabelFact,
    MaiwOperationalProposal,
    MaiwWhOutcome,
    MaiwWhProposal,
    MappingTemplate,
    OrderFinancialFact,
    OrderLineFact,
    ParcelQuoteObservation,
    RateShopQuoteCache,
    Recommendation,
    SkuCatalogItem,
    SkuDemandSnapshot,
    SpapiCatalogSnapshot,
    TaskFact,
    TaxJurisdictionSnapshot,
    TaxSyncRun,
    TenantSalesTaxNexus,
)


def _utc():
    return datetime.now(timezone.utc)


class CortexStore:
    """Abstract operations used by API + spine."""

    async def engagement_create(
        self, eid: str, name: str, org_tenant_id: str | None, external_ref: str | None
    ) -> None:
        raise NotImplementedError

    async def engagement_get(self, eid: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def engagement_set_network_context(self, eid: str, network_context: dict[str, Any]) -> None:
        """Merge into engagement.network_context (candidate_warehouses, item_intelligence_network, etc.)."""
        raise NotImplementedError

    async def mapping_save(self, engagement_id: str, mappings: dict) -> int:
        raise NotImplementedError

    async def mapping_latest(self, engagement_id: str) -> dict:
        raise NotImplementedError

    async def label_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def task_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def label_facts_list(
        self,
        engagement_id: str | None = None,
        tenant_id: str | None = None,
        warehouse_id: str | None = None,
    ) -> list[dict]:
        """Assessment: pass engagement_id only. Operational: tenant/warehouse without engagement_id excludes audit rows."""
        raise NotImplementedError

    async def task_facts_list(
        self,
        engagement_id: str | None = None,
        tenant_id: str | None = None,
        warehouse_id: str | None = None,
    ) -> list[dict]:
        raise NotImplementedError

    async def task_facts_delete_synthetic_for_engagement(self, engagement_id: str) -> int:
        """Remove task rows with extra.provenance == 'synthetic' for this engagement."""
        raise NotImplementedError

    async def asn_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def asn_facts_list(self, engagement_id: str) -> list[dict]:
        raise NotImplementedError

    async def order_line_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def order_line_facts_list(self, engagement_id: str) -> list[dict]:
        raise NotImplementedError

    async def billing_line_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def billing_line_facts_list(self, engagement_id: str) -> list[dict]:
        raise NotImplementedError

    async def employee_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def employee_facts_list(self, engagement_id: str) -> list[dict]:
        raise NotImplementedError

    async def order_financial_facts_insert(self, rows: list[dict]) -> None:
        raise NotImplementedError

    async def order_financial_facts_list(
        self,
        engagement_id: str | None = None,
        tenant_id: str | None = None,
        warehouse_id: str | None = None,
    ) -> list[dict]:
        raise NotImplementedError

    async def audit_run_insert(self, doc: dict) -> None:
        raise NotImplementedError

    async def audit_run_get(self, run_id: str) -> dict | None:
        raise NotImplementedError

    async def audit_run_set_narrative(self, run_id: str, text: str) -> None:
        raise NotImplementedError

    async def audit_run_latest_assessment(self, engagement_id: str) -> dict[str, Any] | None:
        """Latest assessment run for an engagement (MAIW context)."""
        raise NotImplementedError

    async def audit_run_latest_operational(
        self, tenant_id: str, warehouse_id: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def recommendations_for_warehouse(
        self, tenant_id: str, warehouse_id: str, limit: int = 15
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def recommendation_insert(self, doc: dict) -> None:
        raise NotImplementedError

    async def recommendation_get(self, rid: str) -> dict | None:
        raise NotImplementedError

    async def recommendation_set_status(
        self, rid: str, status: str, approve_note: str | None = None, deny_reason: str | None = None
    ) -> None:
        raise NotImplementedError

    async def templates_list(self) -> list[dict]:
        raise NotImplementedError

    async def templates_seed_default(self) -> None:
        raise NotImplementedError

    async def maiw_proposal_insert(self, doc: dict) -> None:
        raise NotImplementedError

    async def maiw_proposal_get(self, pid: str) -> dict | None:
        raise NotImplementedError

    async def maiw_proposal_list(
        self, tenant_id: str, warehouse_id: str, limit: int = 30
    ) -> list[dict]:
        raise NotImplementedError

    async def maiw_proposal_set_status(
        self,
        pid: str,
        status: str,
        approve_note: str | None = None,
        deny_reason: str | None = None,
    ) -> None:
        raise NotImplementedError

    async def maiw_wh_proposal_insert(self, doc: dict[str, Any]) -> None:
        raise NotImplementedError

    async def maiw_wh_proposal_get(self, pid: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def maiw_wh_proposal_set_decision(
        self,
        pid: str,
        status: str,
        chosen_variant: str | None = None,
        approve_note: str | None = None,
        deny_reason: str | None = None,
    ) -> None:
        raise NotImplementedError

    async def maiw_wh_proposals_for_metrics(
        self,
        tenant_id: str | None,
        capability: str | None,
        from_iso: str | None,
        to_iso: str | None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def maiw_wh_outcome_insert(self, doc: dict[str, Any]) -> None:
        raise NotImplementedError

    async def ai_invocation_insert(self, doc: dict[str, Any]) -> None:
        raise NotImplementedError

    async def ai_invocations_list(
        self, *, tenant_id: str, capability: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def keepa_snapshot_get(
        self, tenant_id: str, asin: str, domain: int = 1, max_age_days: int = 15
    ) -> dict | None:
        """Return cached Keepa data if within TTL; else None."""
        raise NotImplementedError

    async def keepa_snapshot_upsert(
        self, tenant_id: str, asin: str, data: dict, domain: int = 1
    ) -> None:
        """Persist Keepa snapshot for tenant+ASIN."""
        raise NotImplementedError

    async def spapi_catalog_snapshot_get(
        self,
        tenant_id: str,
        asin: str,
        marketplace_id: str,
        max_age_days: int = 30,
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def spapi_catalog_snapshot_upsert(
        self,
        tenant_id: str,
        asin: str,
        marketplace_id: str,
        payload: dict[str, Any],
        referral_bucket: str | None,
    ) -> None:
        raise NotImplementedError

    async def sku_catalog_upsert(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def sku_catalog_get(self, tenant_id: str, sku: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def sku_catalog_list(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def sku_catalog_find_by_asin(self, tenant_id: str, asin: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def sku_demand_upsert(
        self,
        tenant_id: str,
        asin: str,
        domain: int,
        derived: dict[str, Any],
        sku: str | None = None,
        method: str = "keepa_v1",
    ) -> None:
        raise NotImplementedError

    async def sku_demand_get(
        self, tenant_id: str, asin: str, domain: int = 1
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def sku_demand_list_for_tenant(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def rate_shop_cache_get(
        self, tenant_id: str, cache_key: str, max_age_days: int = 30
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def rate_shop_cache_put(
        self,
        tenant_id: str,
        cache_key: str,
        bucket: str,
        origin_postal: str,
        dest_postal: str,
        service_code: str,
        quote: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    async def parcel_quote_observations_insert(self, rows: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    async def tax_jurisdiction_replace_scope_provider(
        self,
        scope_tenant_id: str,
        provider: str,
        rows: list[dict[str, Any]],
    ) -> int:
        raise NotImplementedError

    async def tax_jurisdiction_get(
        self,
        scope_tenant_id: str,
        provider: str,
        country_code: str,
        region_code: str,
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def tax_jurisdiction_list_us_system(self, provider: str = "taxjar") -> list[dict[str, Any]]:
        """All US rows in __system__ scope (nationwide reference rates)."""
        raise NotImplementedError

    async def tax_sync_run_insert(self, run_id: str, provider: str) -> None:
        raise NotImplementedError

    async def tax_sync_run_finish(
        self,
        run_id: str,
        *,
        status: str,
        regions_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        raise NotImplementedError

    async def tenant_sales_tax_nexus_set(self, tenant_id: str, state_codes: list[str]) -> None:
        raise NotImplementedError

    async def tenant_sales_tax_nexus_list(self, tenant_id: str) -> list[str]:
        raise NotImplementedError

    async def facility_freight_profile_upsert(
        self, tenant_id: str, location_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def facility_freight_profile_get(
        self, tenant_id: str, location_id: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    async def facility_freight_profiles_list(
        self, tenant_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class SqlCortexStore(CortexStore):
    def __init__(self, session: AsyncSession):
        self.s = session

    async def engagement_create(self, eid, name, org_tenant_id, external_ref):
        self.s.add(
            Engagement(
                id=eid,
                org_tenant_id=org_tenant_id,
                name=name,
                external_ref=external_ref,
            )
        )
        await self.s.flush()

    async def engagement_get(self, eid):
        e = await self.s.get(Engagement, eid)
        if not e:
            return None
        return {
            "id": e.id,
            "name": e.name,
            "org_tenant_id": e.org_tenant_id,
            "created_at": e.created_at,
            "network_context": dict(e.network_context) if e.network_context else None,
        }

    async def engagement_set_network_context(self, eid: str, network_context: dict[str, Any]) -> None:
        e = await self.s.get(Engagement, eid)
        if not e:
            raise ValueError("engagement not found")
        cur = dict(e.network_context) if e.network_context else {}
        cur.update(network_context)
        e.network_context = cur
        await self.s.flush()

    async def mapping_save(self, engagement_id, mappings):
        r = await self.s.execute(
            select(ColumnMapping.version)
            .where(ColumnMapping.engagement_id == engagement_id)
            .order_by(desc(ColumnMapping.version))
            .limit(1)
        )
        row = r.first()
        ver = (row[0] + 1) if row else 1
        self.s.add(ColumnMapping(engagement_id=engagement_id, version=ver, mappings=dict(mappings)))
        await self.s.flush()
        return ver

    async def mapping_latest(self, engagement_id):
        r = await self.s.execute(
            select(ColumnMapping)
            .where(ColumnMapping.engagement_id == engagement_id)
            .order_by(desc(ColumnMapping.version))
            .limit(1)
        )
        row = r.scalar_one_or_none()
        return row.mappings if row else {}

    async def label_facts_insert(self, rows):
        for d in rows:
            self.s.add(LabelFact(**d))
        await self.s.flush()

    async def task_facts_insert(self, rows):
        for d in rows:
            self.s.add(TaskFact(**d))
        await self.s.flush()

    async def label_facts_list(self, engagement_id=None, tenant_id=None, warehouse_id=None):
        q = select(LabelFact)
        if engagement_id:
            q = q.where(LabelFact.engagement_id == engagement_id)
        else:
            if tenant_id is not None:
                q = q.where(LabelFact.tenant_id == tenant_id)
            if warehouse_id is not None:
                q = q.where(LabelFact.warehouse_id == warehouse_id)
            if tenant_id is not None or warehouse_id is not None:
                q = q.where(LabelFact.engagement_id.is_(None))
        res = await self.s.execute(q)
        out = []
        for lf in res.scalars().all():
            out.append(
                {
                    "tenant_id": lf.tenant_id,
                    "warehouse_id": lf.warehouse_id,
                    "engagement_id": lf.engagement_id,
                    "tracking_number": lf.tracking_number,
                    "carrier": lf.carrier,
                    "service_code": lf.service_code,
                    "label_amount_usd": lf.label_amount_usd,
                    "weight_lb": lf.weight_lb,
                    "origin_postal": lf.origin_postal,
                    "dest_postal": lf.dest_postal,
                    "ship_date": lf.ship_date,
                    "sku": lf.sku,
                    "qty": lf.qty,
                    "line_amount_usd": lf.line_amount_usd,
                }
            )
        return out

    async def task_facts_list(self, engagement_id=None, tenant_id=None, warehouse_id=None):
        q = select(TaskFact)
        if engagement_id:
            q = q.where(TaskFact.engagement_id == engagement_id)
        else:
            if tenant_id is not None:
                q = q.where(TaskFact.tenant_id == tenant_id)
            if warehouse_id is not None:
                q = q.where(TaskFact.warehouse_id == warehouse_id)
            if tenant_id is not None or warehouse_id is not None:
                q = q.where(TaskFact.engagement_id.is_(None))
        res = await self.s.execute(q)
        out = []
        for t in res.scalars().all():
            out.append(
                {
                    "tenant_id": t.tenant_id,
                    "warehouse_id": t.warehouse_id,
                    "engagement_id": t.engagement_id,
                    "batch_id": t.batch_id,
                    "completed_at": t.completed_at,
                    "zone": t.zone,
                    "operator_id": t.operator_id,
                    "task_type": t.task_type,
                    "duration_sec": t.duration_sec,
                    "sku": t.sku,
                    "extra": t.extra if isinstance(t.extra, dict) else None,
                }
            )
        return out

    async def task_facts_delete_synthetic_for_engagement(self, engagement_id: str) -> int:
        eid = engagement_id.strip()
        if not eid:
            return 0
        q = select(TaskFact).where(TaskFact.engagement_id == eid)
        res = await self.s.execute(q)
        ids = [
            t.id
            for t in res.scalars().all()
            if isinstance(t.extra, dict) and t.extra.get("provenance") == "synthetic"
        ]
        if not ids:
            return 0
        await self.s.execute(delete(TaskFact).where(TaskFact.id.in_(ids)))
        await self.s.flush()
        return len(ids)

    async def asn_facts_insert(self, rows):
        for d in rows:
            self.s.add(AsnFact(**d))
        await self.s.flush()

    async def asn_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        res = await self.s.execute(select(AsnFact).where(AsnFact.engagement_id == eid))
        out: list[dict] = []
        for row in res.scalars().all():
            out.append(
                {
                    "engagement_id": row.engagement_id,
                    "batch_id": row.batch_id,
                    "asn_line_id": row.asn_line_id,
                    "po_id": row.po_id,
                    "sku": row.sku,
                    "qty_expected": row.qty_expected,
                    "qty_received": row.qty_received,
                    "expected_at_iso": row.expected_at_iso,
                    "received_at_iso": row.received_at_iso,
                    "supplier_id": row.supplier_id,
                    "dock_zone": row.dock_zone,
                    "extra": row.extra,
                }
            )
        return out

    async def order_line_facts_insert(self, rows):
        for d in rows:
            self.s.add(OrderLineFact(**d))
        await self.s.flush()

    async def order_line_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        res = await self.s.execute(select(OrderLineFact).where(OrderLineFact.engagement_id == eid))
        out = []
        for row in res.scalars().all():
            out.append(
                {
                    "engagement_id": row.engagement_id,
                    "batch_id": row.batch_id,
                    "order_external_id": row.order_external_id,
                    "line_id": row.line_id,
                    "sku": row.sku,
                    "quantity": row.quantity,
                    "ordered_at_iso": row.ordered_at_iso,
                    "shipped_at_iso": row.shipped_at_iso,
                    "ship_to_postal": row.ship_to_postal,
                    "channel": row.channel,
                    "extra": row.extra,
                }
            )
        return out

    async def billing_line_facts_insert(self, rows):
        for d in rows:
            self.s.add(BillingLineFact(**d))
        await self.s.flush()

    async def billing_line_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        res = await self.s.execute(select(BillingLineFact).where(BillingLineFact.engagement_id == eid))
        out = []
        for row in res.scalars().all():
            out.append(
                {
                    "engagement_id": row.engagement_id,
                    "batch_id": row.batch_id,
                    "invoice_id": row.invoice_id,
                    "line_id": row.line_id,
                    "fee_code": row.fee_code,
                    "service_start_iso": row.service_start_iso,
                    "service_end_iso": row.service_end_iso,
                    "amount_usd": row.amount_usd,
                    "currency": row.currency,
                    "extra": row.extra,
                }
            )
        return out

    async def employee_facts_insert(self, rows):
        for d in rows:
            self.s.add(EmployeeFact(**d))
        await self.s.flush()

    async def employee_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        res = await self.s.execute(select(EmployeeFact).where(EmployeeFact.engagement_id == eid))
        out = []
        for row in res.scalars().all():
            out.append(
                {
                    "engagement_id": row.engagement_id,
                    "batch_id": row.batch_id,
                    "employee_id": row.employee_id,
                    "role": row.role,
                    "hire_date_iso": row.hire_date_iso,
                    "shift_name": row.shift_name,
                    "hourly_rate_usd": row.hourly_rate_usd,
                    "extra": row.extra,
                }
            )
        return out

    async def order_financial_facts_insert(self, rows):
        for d in rows:
            self.s.add(OrderFinancialFact(**d))
        await self.s.flush()

    async def order_financial_facts_list(self, engagement_id=None, tenant_id=None, warehouse_id=None):
        q = select(OrderFinancialFact)
        if engagement_id:
            q = q.where(OrderFinancialFact.engagement_id == engagement_id)
        else:
            if tenant_id is not None:
                q = q.where(OrderFinancialFact.tenant_id == tenant_id)
            if warehouse_id is not None:
                q = q.where(OrderFinancialFact.warehouse_id == warehouse_id)
            if tenant_id is not None or warehouse_id is not None:
                q = q.where(OrderFinancialFact.engagement_id.is_(None))
        res = await self.s.execute(q)
        out = []
        for row in res.scalars().all():
            ex = row.extra if isinstance(row.extra, dict) else {}
            out.append(
                {
                    "engagement_id": row.engagement_id,
                    "batch_id": row.batch_id,
                    "tenant_id": row.tenant_id,
                    "warehouse_id": row.warehouse_id,
                    "order_external_id": row.order_external_id,
                    "order_date_iso": row.order_date_iso,
                    "email": row.email,
                    "asin": row.asin,
                    "sku": row.sku,
                    "line_title": row.line_title,
                    "revenue_usd": row.revenue_usd,
                    "marketplace_fees_usd": row.marketplace_fees_usd,
                    "amazon_seller_fees_usd": ex.get("amazon_seller_fees_usd"),
                    "amazon_fba_fulfillment_fees_usd": ex.get("amazon_fba_fulfillment_fees_usd"),
                    "fba_fulfillment_fee_audit_line_total_usd": ex.get("fba_fulfillment_fee_audit_line_total_usd"),
                    "fba_fulfillment_fee_audit_per_unit_usd": ex.get("fba_fulfillment_fee_audit_per_unit_usd"),
                    "product_cogs_usd": row.product_cogs_usd,
                    "prep_cost_usd": row.prep_cost_usd,
                    "inbound_cost_usd": row.inbound_cost_usd,
                    "total_fees_usd": row.total_fees_usd,
                    "profit_usd": row.profit_usd,
                    "quantity": row.quantity,
                    "other_expenses_usd": row.other_expenses_usd,
                    "ship_to_city": row.ship_to_city,
                    "ship_to_state": row.ship_to_state,
                    "ship_to_postal": row.ship_to_postal,
                    "ship_to_country": row.ship_to_country,
                    "marketplace_fees_2026_csv_usd": row.marketplace_fees_2026_csv_usd,
                    "total_fees_2026_csv_usd": row.total_fees_2026_csv_usd,
                    "profit_2026_csv_usd": row.profit_2026_csv_usd,
                    "marketplace_fees_2026_synthetic_usd": row.marketplace_fees_2026_synthetic_usd,
                    "total_fees_2026_synthetic_usd": row.total_fees_2026_synthetic_usd,
                    "profit_2026_synthetic_usd": row.profit_2026_synthetic_usd,
                    "inflation_source": row.inflation_source,
                    "assumptions_version": row.assumptions_version,
                    "inflation_components": row.inflation_components,
                    "referral_fees_modeled_usd": row.referral_fees_modeled_usd,
                    "referral_fee_bucket": row.referral_fee_bucket,
                    "referral_fee_source": row.referral_fee_source,
                    "extra": row.extra,
                }
            )
        return out

    async def audit_run_insert(self, doc):
        self.s.add(
            AuditRun(
                id=doc["id"],
                engagement_id=doc.get("engagement_id"),
                tenant_id=doc.get("tenant_id"),
                warehouse_id=doc.get("warehouse_id"),
                mode=doc.get("mode", "assessment"),
                status=doc.get("status", "complete"),
                artifact_json=doc["artifact_json"],
                narrative_text=doc.get("narrative_text"),
            )
        )
        await self.s.flush()

    async def audit_run_get(self, run_id):
        r = await self.s.get(AuditRun, run_id)
        if not r:
            return None
        return {
            "id": r.id,
            "engagement_id": r.engagement_id,
            "tenant_id": r.tenant_id,
            "warehouse_id": r.warehouse_id,
            "artifact_json": r.artifact_json,
            "narrative_text": r.narrative_text,
        }

    async def audit_run_set_narrative(self, run_id, text):
        r = await self.s.get(AuditRun, run_id)
        if r:
            r.narrative_text = text
            await self.s.flush()

    async def audit_run_latest_assessment(self, engagement_id: str):
        r = await self.s.execute(
            select(AuditRun)
            .where(
                AuditRun.engagement_id == engagement_id,
                AuditRun.mode == "assessment",
            )
            .order_by(desc(AuditRun.created_at))
            .limit(1)
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": row.id,
            "engagement_id": row.engagement_id,
            "tenant_id": row.tenant_id,
            "warehouse_id": row.warehouse_id,
            "artifact_json": row.artifact_json,
            "narrative_text": row.narrative_text,
        }

    async def audit_run_latest_operational(self, tenant_id: str, warehouse_id: str):
        r = await self.s.execute(
            select(AuditRun)
            .where(
                AuditRun.tenant_id == tenant_id,
                AuditRun.warehouse_id == warehouse_id,
                AuditRun.mode == "operational",
            )
            .order_by(desc(AuditRun.created_at))
            .limit(1)
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": row.id,
            "engagement_id": row.engagement_id,
            "tenant_id": row.tenant_id,
            "warehouse_id": row.warehouse_id,
            "artifact_json": row.artifact_json,
            "narrative_text": row.narrative_text,
        }

    async def recommendations_for_warehouse(self, tenant_id: str, warehouse_id: str, limit: int = 15):
        r = await self.s.execute(
            select(Recommendation)
            .where(
                Recommendation.tenant_id == tenant_id,
                Recommendation.warehouse_id == warehouse_id,
            )
            .order_by(desc(Recommendation.created_at))
            .limit(limit)
        )
        out = []
        for rec in r.scalars().all():
            out.append(
                {
                    "id": rec.id,
                    "status": rec.status,
                    "original_summary": rec.original_summary,
                    "proposed_summary": rec.proposed_summary[:2000] if rec.proposed_summary else "",
                    "diff_json": list(rec.diff_json or [])[:20],
                }
            )
        return out

    async def recommendation_insert(self, doc):
        self.s.add(
            Recommendation(
                id=doc["id"],
                tenant_id=doc["tenant_id"],
                warehouse_id=doc["warehouse_id"],
                original_summary=doc["original_summary"],
                proposed_summary=doc["proposed_summary"],
                diff_json=doc.get("diff_json", []),
                status=doc.get("status", "pending"),
            )
        )
        await self.s.flush()

    async def recommendation_get(self, rid):
        r = await self.s.get(Recommendation, rid)
        if not r:
            return None
        return {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "warehouse_id": r.warehouse_id,
            "original_summary": r.original_summary,
            "proposed_summary": r.proposed_summary,
            "diff_json": list(r.diff_json or []),
            "status": r.status,
        }

    async def recommendation_set_status(self, rid, status, approve_note=None, deny_reason=None):
        r = await self.s.get(Recommendation, rid)
        if r:
            r.status = status
            r.approve_note = approve_note
            r.deny_reason = deny_reason
            await self.s.flush()

    async def maiw_proposal_insert(self, doc):
        self.s.add(
            MaiwOperationalProposal(
                id=doc["id"],
                tenant_id=doc["tenant_id"],
                warehouse_id=doc["warehouse_id"],
                engagement_id=doc.get("engagement_id"),
                run_id=doc.get("run_id"),
                title=doc["title"],
                before_json=doc["before_json"],
                after_json=doc["after_json"],
                diff_lines_json=json.dumps(doc.get("diff_lines") or []),
                status=doc.get("status", "pending"),
                source=doc.get("source", "deterministic"),
                nim_rationale=doc.get("nim_rationale"),
            )
        )
        await self.s.flush()

    async def maiw_proposal_get(self, pid):
        r = await self.s.get(MaiwOperationalProposal, pid)
        if not r:
            return None
        return {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "warehouse_id": r.warehouse_id,
            "engagement_id": r.engagement_id,
            "run_id": r.run_id,
            "title": r.title,
            "before": json.loads(r.before_json),
            "after": json.loads(r.after_json),
            "diff_lines": json.loads(r.diff_lines_json or "[]"),
            "status": r.status,
            "source": r.source,
            "nim_rationale": r.nim_rationale,
            "approve_note": r.approve_note,
            "deny_reason": r.deny_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    async def maiw_proposal_list(self, tenant_id: str, warehouse_id: str, limit: int = 30):
        r = await self.s.execute(
            select(MaiwOperationalProposal)
            .where(
                MaiwOperationalProposal.tenant_id == tenant_id,
                MaiwOperationalProposal.warehouse_id == warehouse_id,
            )
            .order_by(desc(MaiwOperationalProposal.created_at))
            .limit(limit)
        )
        out = []
        for row in r.scalars().all():
            out.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "status": row.status,
                    "source": row.source,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return out

    async def maiw_proposal_set_status(self, pid, status, approve_note=None, deny_reason=None):
        r = await self.s.get(MaiwOperationalProposal, pid)
        if r:
            r.status = status
            r.approve_note = approve_note
            r.deny_reason = deny_reason
            await self.s.flush()

    async def maiw_wh_proposal_insert(self, doc: dict[str, Any]) -> None:
        self.s.add(
            MaiwWhProposal(
                id=doc["id"],
                tenant_id=doc["tenant_id"],
                warehouse_id=doc["warehouse_id"],
                capability=doc["capability"],
                correlation_id=doc.get("correlation_id"),
                payload_hash=doc.get("payload_hash"),
                payload_json=doc["payload_json"],
                response_json=doc["response_json"],
                status=doc.get("status", "pending"),
                value_score_snapshot_json=doc.get("value_score_snapshot_json"),
            )
        )
        await self.s.flush()

    async def maiw_wh_proposal_get(self, pid: str) -> dict[str, Any] | None:
        r = await self.s.get(MaiwWhProposal, pid)
        if not r:
            return None
        return {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "warehouse_id": r.warehouse_id,
            "capability": r.capability,
            "correlation_id": r.correlation_id,
            "payload_hash": r.payload_hash,
            "payload": json.loads(r.payload_json),
            "four_variants": json.loads(r.response_json),
            "status": r.status,
            "chosen_variant": r.chosen_variant,
            "approve_note": r.approve_note,
            "deny_reason": r.deny_reason,
            "value_score_snapshot": json.loads(r.value_score_snapshot_json)
            if r.value_score_snapshot_json
            else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    async def maiw_wh_proposal_set_decision(
        self,
        pid: str,
        status: str,
        chosen_variant: str | None = None,
        approve_note: str | None = None,
        deny_reason: str | None = None,
    ) -> None:
        r = await self.s.get(MaiwWhProposal, pid)
        if r:
            r.status = status
            r.chosen_variant = chosen_variant
            r.approve_note = approve_note
            r.deny_reason = deny_reason
            await self.s.flush()

    async def maiw_wh_proposals_for_metrics(
        self,
        tenant_id: str | None,
        capability: str | None,
        from_iso: str | None,
        to_iso: str | None,
    ) -> list[dict[str, Any]]:
        q = select(MaiwWhProposal)
        if tenant_id:
            q = q.where(MaiwWhProposal.tenant_id == tenant_id)
        if capability:
            q = q.where(MaiwWhProposal.capability == capability)
        if from_iso:
            try:
                t0 = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
                q = q.where(MaiwWhProposal.created_at >= t0)
            except ValueError:
                pass
        if to_iso:
            try:
                t1 = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
                q = q.where(MaiwWhProposal.created_at <= t1)
            except ValueError:
                pass
        r = await self.s.execute(q)
        out = []
        for row in r.scalars().all():
            out.append(
                {
                    "status": row.status,
                    "capability": row.capability,
                    "tenant_id": row.tenant_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return out

    async def maiw_wh_outcome_insert(self, doc: dict[str, Any]) -> None:
        self.s.add(
            MaiwWhOutcome(
                id=doc["id"],
                proposal_id=doc["proposal_id"],
                body_json=doc["body_json"],
            )
        )
        await self.s.flush()

    async def ai_invocation_insert(self, doc: dict[str, Any]) -> None:
        self.s.add(
            AiInvocation(
                id=doc["id"],
                capability=doc["capability"],
                tenant_id=doc.get("tenant_id"),
                engagement_id=doc.get("engagement_id"),
                run_id=doc.get("run_id"),
                proposal_id=doc.get("proposal_id"),
                correlation_id=doc.get("correlation_id"),
                model=doc["model"],
                http_status=doc.get("http_status"),
                latency_ms=int(doc.get("latency_ms") or 0),
                source=doc["source"],
                prompt_sha256=doc["prompt_sha256"],
                response_sha256=doc.get("response_sha256"),
                prompt_preview=doc.get("prompt_preview"),
                response_preview=doc.get("response_preview"),
                extra_json=doc.get("extra_json"),
            )
        )
        await self.s.flush()

    async def ai_invocations_list(
        self, *, tenant_id: str, capability: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        q = select(AiInvocation).where(AiInvocation.tenant_id == tenant_id)
        if capability:
            q = q.where(AiInvocation.capability == capability)
        q = q.order_by(desc(AiInvocation.created_at)).limit(min(max(limit, 1), 500))
        r = await self.s.execute(q)
        out: list[dict[str, Any]] = []
        for row in r.scalars().all():
            out.append(
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "capability": row.capability,
                    "tenant_id": row.tenant_id,
                    "engagement_id": row.engagement_id,
                    "run_id": row.run_id,
                    "proposal_id": row.proposal_id,
                    "correlation_id": row.correlation_id,
                    "model": row.model,
                    "http_status": row.http_status,
                    "latency_ms": row.latency_ms,
                    "source": row.source,
                    "prompt_sha256": row.prompt_sha256,
                    "response_sha256": row.response_sha256,
                    "prompt_preview": row.prompt_preview,
                    "response_preview": row.response_preview,
                    "extra_json": row.extra_json,
                }
            )
        return out

    async def templates_list(self):
        r = await self.s.execute(select(MappingTemplate))
        return [
            {"vendor_key": t.vendor_key, "label": t.label, "mappings": t.mappings}
            for t in r.scalars().all()
        ]

    async def keepa_snapshot_get(
        self, tenant_id: str, asin: str, domain: int = 1, max_age_days: int = 15
    ):
        cutoff = _utc() - timedelta(days=max_age_days)
        r = await self.s.execute(
            select(KeepaSnapshot)
            .where(
                KeepaSnapshot.tenant_id == tenant_id,
                KeepaSnapshot.asin == asin,
                KeepaSnapshot.domain == domain,
                KeepaSnapshot.refreshed_at >= cutoff,
            )
            .limit(1)
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {"data": json.loads(row.data_json), "refreshed_at": row.refreshed_at.isoformat()}

    async def keepa_snapshot_upsert(
        self, tenant_id: str, asin: str, data: dict, domain: int = 1
    ):
        data_json = json.dumps(data)
        r = await self.s.execute(
            select(KeepaSnapshot).where(
                KeepaSnapshot.tenant_id == tenant_id,
                KeepaSnapshot.asin == asin,
                KeepaSnapshot.domain == domain,
            )
        )
        row = r.scalar_one_or_none()
        if row:
            row.data_json = data_json
            row.refreshed_at = _utc()
        else:
            self.s.add(
                KeepaSnapshot(
                    tenant_id=tenant_id,
                    asin=asin,
                    domain=domain,
                    data_json=data_json,
                    refreshed_at=_utc(),
                )
            )
        await self.s.flush()

    async def spapi_catalog_snapshot_get(
        self,
        tenant_id: str,
        asin: str,
        marketplace_id: str,
        max_age_days: int = 30,
    ):
        cutoff = _utc() - timedelta(days=max_age_days)
        r = await self.s.execute(
            select(SpapiCatalogSnapshot)
            .where(
                SpapiCatalogSnapshot.tenant_id == tenant_id,
                SpapiCatalogSnapshot.asin == asin.strip(),
                SpapiCatalogSnapshot.marketplace_id == marketplace_id.strip(),
                SpapiCatalogSnapshot.refreshed_at >= cutoff,
            )
            .limit(1)
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "payload": json.loads(row.payload_json),
            "referral_bucket": row.referral_bucket,
            "refreshed_at": row.refreshed_at.isoformat(),
        }

    async def spapi_catalog_snapshot_upsert(
        self,
        tenant_id: str,
        asin: str,
        marketplace_id: str,
        payload: dict[str, Any],
        referral_bucket: str | None,
    ):
        pj = json.dumps(payload, default=str)
        mp = marketplace_id.strip()
        a = asin.strip()
        r = await self.s.execute(
            select(SpapiCatalogSnapshot).where(
                SpapiCatalogSnapshot.tenant_id == tenant_id,
                SpapiCatalogSnapshot.asin == a,
                SpapiCatalogSnapshot.marketplace_id == mp,
            )
        )
        row = r.scalar_one_or_none()
        now = _utc()
        if row:
            row.payload_json = pj
            row.referral_bucket = referral_bucket
            row.refreshed_at = now
        else:
            self.s.add(
                SpapiCatalogSnapshot(
                    tenant_id=tenant_id,
                    asin=a,
                    marketplace_id=mp,
                    payload_json=pj,
                    referral_bucket=referral_bucket,
                    refreshed_at=now,
                )
            )
        await self.s.flush()

    async def sku_catalog_upsert(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        sku = (doc.get("sku") or "").strip()
        if not sku:
            raise ValueError("sku required")
        r = await self.s.execute(
            select(SkuCatalogItem).where(
                SkuCatalogItem.tenant_id == tenant_id,
                SkuCatalogItem.sku == sku,
            )
        )
        row = r.scalar_one_or_none()
        now = _utc()
        fields = {
            "asin": (doc.get("asin") or None) and str(doc["asin"]).strip() or None,
            "weight_lb": doc.get("weight_lb"),
            "length_in": doc.get("length_in"),
            "width_in": doc.get("width_in"),
            "height_in": doc.get("height_in"),
            "extra": doc.get("extra"),
            "updated_at": now,
        }
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
        else:
            row = SkuCatalogItem(
                tenant_id=tenant_id,
                sku=sku,
                **{k: v for k, v in fields.items() if k != "updated_at"},
                created_at=now,
                updated_at=now,
            )
            self.s.add(row)
        await self.s.flush()
        return await self.sku_catalog_get(tenant_id, sku)  # type: ignore[no-any-return]

    async def sku_catalog_get(self, tenant_id: str, sku: str) -> dict[str, Any] | None:
        r = await self.s.execute(
            select(SkuCatalogItem).where(
                SkuCatalogItem.tenant_id == tenant_id,
                SkuCatalogItem.sku == sku.strip(),
            )
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "tenant_id": row.tenant_id,
            "sku": row.sku,
            "asin": row.asin,
            "weight_lb": row.weight_lb,
            "length_in": row.length_in,
            "width_in": row.width_in,
            "height_in": row.height_in,
            "extra": row.extra,
            "physical_signature": None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def sku_catalog_list(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        r = await self.s.execute(
            select(SkuCatalogItem)
            .where(SkuCatalogItem.tenant_id == tenant_id)
            .order_by(desc(SkuCatalogItem.updated_at))
            .limit(limit)
        )
        out = []
        for row in r.scalars().all():
            out.append(
                {
                    "tenant_id": row.tenant_id,
                    "sku": row.sku,
                    "asin": row.asin,
                    "weight_lb": row.weight_lb,
                    "length_in": row.length_in,
                    "width_in": row.width_in,
                    "height_in": row.height_in,
                    "extra": row.extra,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
            )
        return out

    async def sku_catalog_find_by_asin(self, tenant_id: str, asin: str) -> list[dict[str, Any]]:
        r = await self.s.execute(
            select(SkuCatalogItem).where(
                SkuCatalogItem.tenant_id == tenant_id,
                SkuCatalogItem.asin == asin.strip(),
            )
        )
        out = []
        for row in r.scalars().all():
            d = await self.sku_catalog_get(tenant_id, row.sku)
            if d:
                out.append(d)
        return out

    async def sku_demand_upsert(
        self,
        tenant_id: str,
        asin: str,
        domain: int,
        derived: dict[str, Any],
        sku: str | None = None,
        method: str = "keepa_v1",
    ) -> None:
        asin = asin.strip()
        payload = json.dumps(derived, default=str)
        r = await self.s.execute(
            select(SkuDemandSnapshot).where(
                SkuDemandSnapshot.tenant_id == tenant_id,
                SkuDemandSnapshot.asin == asin,
                SkuDemandSnapshot.domain == domain,
            )
        )
        row = r.scalar_one_or_none()
        now = _utc()
        if row:
            row.derived_json = payload
            row.method = method
            row.refreshed_at = now
            if sku:
                row.sku = sku.strip()
        else:
            self.s.add(
                SkuDemandSnapshot(
                    tenant_id=tenant_id,
                    asin=asin,
                    domain=domain,
                    sku=sku.strip() if sku else None,
                    derived_json=payload,
                    method=method,
                    refreshed_at=now,
                )
            )
        await self.s.flush()

    async def sku_demand_get(
        self, tenant_id: str, asin: str, domain: int = 1
    ) -> dict[str, Any] | None:
        r = await self.s.execute(
            select(SkuDemandSnapshot).where(
                SkuDemandSnapshot.tenant_id == tenant_id,
                SkuDemandSnapshot.asin == asin.strip(),
                SkuDemandSnapshot.domain == domain,
            )
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "tenant_id": row.tenant_id,
            "asin": row.asin,
            "domain": row.domain,
            "sku": row.sku,
            "derived": json.loads(row.derived_json),
            "method": row.method,
            "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
        }

    async def sku_demand_list_for_tenant(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        r = await self.s.execute(
            select(SkuDemandSnapshot)
            .where(SkuDemandSnapshot.tenant_id == tenant_id)
            .order_by(desc(SkuDemandSnapshot.refreshed_at))
            .limit(limit)
        )
        out = []
        for row in r.scalars().all():
            out.append(
                {
                    "tenant_id": row.tenant_id,
                    "asin": row.asin,
                    "domain": row.domain,
                    "sku": row.sku,
                    "derived": json.loads(row.derived_json),
                    "method": row.method,
                    "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
                }
            )
        return out

    async def rate_shop_cache_get(
        self, tenant_id: str, cache_key: str, max_age_days: int = 30
    ) -> dict[str, Any] | None:
        cutoff = _utc() - timedelta(days=max_age_days)
        r = await self.s.execute(
            select(RateShopQuoteCache).where(
                RateShopQuoteCache.tenant_id == tenant_id,
                RateShopQuoteCache.cache_key == cache_key,
                RateShopQuoteCache.refreshed_at >= cutoff,
            )
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "quote": json.loads(row.quote_json),
            "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
            "bucket": row.bucket,
            "origin_postal_norm": row.origin_postal_norm,
            "dest_postal_norm": row.dest_postal_norm,
            "service_code": row.service_code,
        }

    async def rate_shop_cache_put(
        self,
        tenant_id: str,
        cache_key: str,
        bucket: str,
        origin_postal: str,
        dest_postal: str,
        service_code: str,
        quote: dict[str, Any],
    ) -> None:
        from unie_cortex.network.rate_bucket import normalize_postal_5

        on = normalize_postal_5(origin_postal)
        dn = normalize_postal_5(dest_postal)
        svc = (service_code or "GROUND").strip().upper() or "GROUND"
        qj = json.dumps(quote, default=str)
        r = await self.s.execute(
            select(RateShopQuoteCache).where(
                RateShopQuoteCache.tenant_id == tenant_id,
                RateShopQuoteCache.cache_key == cache_key,
            )
        )
        row = r.scalar_one_or_none()
        now = _utc()
        if row:
            row.bucket = bucket
            row.origin_postal_norm = on
            row.dest_postal_norm = dn
            row.service_code = svc
            row.quote_json = qj
            row.refreshed_at = now
        else:
            self.s.add(
                RateShopQuoteCache(
                    tenant_id=tenant_id,
                    cache_key=cache_key,
                    bucket=bucket,
                    origin_postal_norm=on,
                    dest_postal_norm=dn,
                    service_code=svc,
                    quote_json=qj,
                    refreshed_at=now,
                )
            )
        await self.s.flush()

    async def parcel_quote_observations_insert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        for d in rows:
            self.s.add(
                ParcelQuoteObservation(
                    tenant_id=d["tenant_id"],
                    origin_postal_norm=d["origin_postal_norm"],
                    dest_postal_norm=d["dest_postal_norm"],
                    physical_bucket=d["physical_bucket"],
                    length_in=d.get("length_in"),
                    width_in=d.get("width_in"),
                    height_in=d.get("height_in"),
                    weight_lb=d.get("weight_lb"),
                    carrier=d.get("carrier"),
                    service_code=d.get("service_code"),
                    amount_usd=float(d.get("amount_usd") or 0.0),
                    source=d.get("source") or "unknown",
                )
            )
        await self.s.flush()

    async def tax_jurisdiction_replace_scope_provider(
        self,
        scope_tenant_id: str,
        provider: str,
        rows: list[dict[str, Any]],
    ) -> int:
        sc = scope_tenant_id.strip() or "__system__"
        pv = provider.strip() or "unknown"
        await self.s.execute(
            delete(TaxJurisdictionSnapshot).where(
                TaxJurisdictionSnapshot.scope_tenant_id == sc,
                TaxJurisdictionSnapshot.provider == pv,
            )
        )
        now = _utc()
        for d in rows:
            self.s.add(
                TaxJurisdictionSnapshot(
                    scope_tenant_id=sc,
                    provider=pv,
                    country_code=str(d.get("country_code") or "US").upper(),
                    region_code=str(d.get("region_code") or "").upper()[:16],
                    raw_json=str(d.get("raw_json") or "{}"),
                    average_rate=d.get("average_rate"),
                    minimum_rate=d.get("minimum_rate"),
                    refreshed_at=now,
                )
            )
        await self.s.flush()
        return len(rows)

    async def tax_jurisdiction_get(
        self,
        scope_tenant_id: str,
        provider: str,
        country_code: str,
        region_code: str,
    ) -> dict[str, Any] | None:
        r = await self.s.execute(
            select(TaxJurisdictionSnapshot).where(
                TaxJurisdictionSnapshot.scope_tenant_id == (scope_tenant_id.strip() or "__system__"),
                TaxJurisdictionSnapshot.provider == provider.strip(),
                TaxJurisdictionSnapshot.country_code == country_code.strip().upper(),
                TaxJurisdictionSnapshot.region_code == region_code.strip().upper(),
            )
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "scope_tenant_id": row.scope_tenant_id,
            "provider": row.provider,
            "country_code": row.country_code,
            "region_code": row.region_code,
            "raw": json.loads(row.raw_json) if row.raw_json else {},
            "average_rate": row.average_rate,
            "minimum_rate": row.minimum_rate,
            "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
        }

    async def tax_jurisdiction_list_us_system(self, provider: str = "taxjar") -> list[dict[str, Any]]:
        r = await self.s.execute(
            select(TaxJurisdictionSnapshot)
            .where(
                TaxJurisdictionSnapshot.scope_tenant_id == "__system__",
                TaxJurisdictionSnapshot.provider == provider.strip(),
                TaxJurisdictionSnapshot.country_code == "US",
            )
            .order_by(TaxJurisdictionSnapshot.region_code)
        )
        rows = r.scalars().all()
        return [
            {
                "region_code": row.region_code,
                "average_rate": row.average_rate,
                "minimum_rate": row.minimum_rate,
                "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
            }
            for row in rows
        ]

    async def tax_sync_run_insert(self, run_id: str, provider: str) -> None:
        self.s.add(
            TaxSyncRun(
                id=run_id,
                provider=provider,
                status="running",
                regions_count=0,
                error_message=None,
                started_at=_utc(),
                finished_at=None,
            )
        )
        await self.s.flush()

    async def tax_sync_run_finish(
        self,
        run_id: str,
        *,
        status: str,
        regions_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        row = await self.s.get(TaxSyncRun, run_id)
        if row:
            row.status = status
            row.regions_count = regions_count
            row.error_message = error_message
            row.finished_at = _utc()
            await self.s.flush()

    async def tenant_sales_tax_nexus_set(self, tenant_id: str, state_codes: list[str]) -> None:
        tid = tenant_id.strip()
        await self.s.execute(delete(TenantSalesTaxNexus).where(TenantSalesTaxNexus.tenant_id == tid))
        now = _utc()
        for s in state_codes:
            code = str(s or "").strip().upper()[:8]
            if len(code) == 2:
                self.s.add(TenantSalesTaxNexus(tenant_id=tid, state_code=code, updated_at=now))
        await self.s.flush()

    async def tenant_sales_tax_nexus_list(self, tenant_id: str) -> list[str]:
        r = await self.s.execute(
            select(TenantSalesTaxNexus.state_code).where(
                TenantSalesTaxNexus.tenant_id == tenant_id.strip()
            )
        )
        return [x[0] for x in r.all()]

    async def facility_freight_profile_upsert(
        self, tenant_id: str, location_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        from unie_cortex.network.facility_freight_profile import to_broker_card

        tid, lid = tenant_id.strip(), location_id.strip()
        if not tid or not lid:
            raise ValueError("tenant_id and location_id required")
        prof = dict(profile or {})
        r = await self.s.execute(
            select(FacilityFreightProfileRow).where(
                FacilityFreightProfileRow.tenant_id == tid,
                FacilityFreightProfileRow.location_id == lid,
            )
        )
        row = r.scalar_one_or_none()
        now = _utc()
        if row:
            row.profile_json = prof
            row.updated_at = now
        else:
            row = FacilityFreightProfileRow(
                tenant_id=tid,
                location_id=lid,
                profile_json=prof,
                updated_at=now,
            )
            self.s.add(row)
        await self.s.flush()
        return {
            "tenant_id": tid,
            "location_id": lid,
            "profile": prof,
            "broker_card": to_broker_card(prof),
            "updated_at": row.updated_at.isoformat(),
        }

    async def facility_freight_profile_get(
        self, tenant_id: str, location_id: str
    ) -> dict[str, Any] | None:
        from unie_cortex.network.facility_freight_profile import to_broker_card

        tid, lid = tenant_id.strip(), location_id.strip()
        if not tid or not lid:
            return None
        r = await self.s.execute(
            select(FacilityFreightProfileRow).where(
                FacilityFreightProfileRow.tenant_id == tid,
                FacilityFreightProfileRow.location_id == lid,
            )
        )
        row = r.scalar_one_or_none()
        if not row:
            return None
        return {
            "tenant_id": row.tenant_id,
            "location_id": row.location_id,
            "profile": row.profile_json or {},
            "broker_card": to_broker_card(row.profile_json or {}),
            "updated_at": row.updated_at.isoformat(),
        }

    async def facility_freight_profiles_list(
        self, tenant_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        from unie_cortex.network.facility_freight_profile import to_broker_card

        tid = tenant_id.strip()
        if not tid:
            return []
        lim = max(1, min(5000, int(limit)))
        r = await self.s.execute(
            select(FacilityFreightProfileRow)
            .where(FacilityFreightProfileRow.tenant_id == tid)
            .order_by(desc(FacilityFreightProfileRow.updated_at))
            .limit(lim)
        )
        out: list[dict[str, Any]] = []
        for row in r.scalars().all():
            out.append(
                {
                    "tenant_id": row.tenant_id,
                    "location_id": row.location_id,
                    "profile": row.profile_json or {},
                    "broker_card": to_broker_card(row.profile_json or {}),
                    "updated_at": row.updated_at.isoformat(),
                }
            )
        return out

    async def templates_seed_default(self):
        r = await self.s.execute(select(MappingTemplate).limit(1))
        if r.scalar_one_or_none():
            return
        self.s.add(
            MappingTemplate(
                vendor_key="generic_labels_v1",
                label="Generic shipping labels CSV",
                mappings={
                    "labels": {
                        "tracking_number": "tracking_number",
                        "Tracking": "tracking_number",
                        "carrier": "carrier",
                        "Carrier": "carrier",
                        "service": "service_code",
                        "amount": "label_amount_usd",
                        "Amount": "label_amount_usd",
                        "cost": "label_amount_usd",
                        "weight": "weight_lb",
                        "Weight": "weight_lb",
                        "origin_zip": "origin_postal",
                        "dest_zip": "dest_postal",
                        "ship_date": "ship_date",
                        "sku": "sku",
                        "SKU": "sku",
                        "qty": "qty",
                        "Qty": "qty",
                        "line_amount": "line_amount_usd",
                    },
                    "tasks": {
                        "completed_at": "completed_at",
                        "timestamp": "completed_at",
                        "zone": "zone",
                        "Zone": "zone",
                        "operator": "operator_id",
                        "task_type": "task_type",
                        "duration_sec": "duration_sec",
                        "sku": "sku",
                        "SKU": "sku",
                    },
                },
            )
        )
        await self.s.flush()


class MongoCortexStore(CortexStore):
    def __init__(self, db: Any):
        self.db = db
        self.eng = db["cortex_engagements"]
        self.map = db["cortex_mappings"]
        self.lbl = db["cortex_label_facts"]
        self.tsk = db["cortex_task_facts"]
        self.run = db["cortex_audit_runs"]
        self.rec = db["cortex_recommendations"]
        self.maiw_p = db["cortex_maiw_proposals"]
        self.maiw_wh_p = db["cortex_maiw_wh_proposals"]
        self.maiw_wh_o = db["cortex_maiw_wh_outcomes"]
        self.ai_inv = db["cortex_ai_invocations"]
        self.tpl = db["cortex_mapping_templates"]
        self.keepa = db["cortex_keepa_snapshots"]
        self.sku_cat = db["cortex_sku_catalog"]
        self.sku_dem = db["cortex_sku_demand"]
        self.rate_shop = db["cortex_rate_shop_cache"]
        self.pqo = db["cortex_parcel_quote_observations"]
        self.tax_snap = db["cortex_tax_jurisdiction_snapshots"]
        self.tax_sync = db["cortex_tax_sync_runs"]
        self.tenant_nexus = db["cortex_tenant_sales_tax_nexus"]
        self.ofact = db["cortex_order_financial_facts"]
        self.ffp = db["cortex_facility_freight_profiles"]
        self.asnf = db["cortex_asn_facts"]
        self.olnf = db["cortex_order_line_facts"]
        self.blf = db["cortex_billing_line_facts"]
        self.empf = db["cortex_employee_facts"]

    async def engagement_create(self, eid, name, org_tenant_id, external_ref):
        await self.eng.insert_one(
            {
                "_id": eid,
                "name": name,
                "org_tenant_id": org_tenant_id,
                "external_ref": external_ref,
                "created_at": _utc(),
            }
        )

    async def engagement_get(self, eid):
        d = await self.eng.find_one({"_id": eid})
        if not d:
            return None
        nc = d.get("network_context")
        return {
            "id": d["_id"],
            "name": d["name"],
            "org_tenant_id": d.get("org_tenant_id"),
            "created_at": d["created_at"],
            "network_context": nc if isinstance(nc, dict) else None,
        }

    async def engagement_set_network_context(self, eid: str, network_context: dict[str, Any]) -> None:
        d = await self.eng.find_one({"_id": eid})
        if not d:
            raise ValueError("engagement not found")
        cur = dict(d.get("network_context") or {})
        cur.update(network_context)
        await self.eng.update_one({"_id": eid}, {"$set": {"network_context": cur}})

    async def mapping_save(self, engagement_id, mappings):
        cur = await self.map.find_one({"engagement_id": engagement_id}, sort=[("version", -1)])
        ver = (cur["version"] + 1) if cur else 1
        await self.map.insert_one(
            {
                "engagement_id": engagement_id,
                "version": ver,
                "mappings": dict(mappings),
                "created_at": _utc(),
            }
        )
        return ver

    async def mapping_latest(self, engagement_id):
        cur = await self.map.find_one({"engagement_id": engagement_id}, sort=[("version", -1)])
        return cur["mappings"] if cur else {}

    async def label_facts_insert(self, rows):
        if rows:
            await self.lbl.insert_many(rows)

    async def task_facts_insert(self, rows):
        if rows:
            await self.tsk.insert_many(rows)

    async def label_facts_list(self, engagement_id=None, tenant_id=None, warehouse_id=None):
        flt: dict = {}
        if engagement_id:
            flt["engagement_id"] = engagement_id
        else:
            if tenant_id is not None:
                flt["tenant_id"] = tenant_id
            if warehouse_id is not None:
                flt["warehouse_id"] = warehouse_id
            if tenant_id is not None or warehouse_id is not None:
                flt["engagement_id"] = None
        cur = self.lbl.find(flt)
        out = []
        async for d in cur:
            out.append(
                {
                    "tenant_id": d.get("tenant_id"),
                    "warehouse_id": d.get("warehouse_id"),
                    "engagement_id": d.get("engagement_id"),
                    "tracking_number": d.get("tracking_number"),
                    "carrier": d.get("carrier"),
                    "service_code": d.get("service_code"),
                    "label_amount_usd": d.get("label_amount_usd"),
                    "weight_lb": d.get("weight_lb"),
                    "origin_postal": d.get("origin_postal"),
                    "dest_postal": d.get("dest_postal"),
                    "ship_date": d.get("ship_date"),
                    "sku": d.get("sku"),
                    "qty": d.get("qty"),
                    "line_amount_usd": d.get("line_amount_usd"),
                }
            )
        return out

    async def task_facts_list(self, engagement_id=None, tenant_id=None, warehouse_id=None):
        flt: dict = {}
        if engagement_id:
            flt["engagement_id"] = engagement_id
        else:
            if tenant_id is not None:
                flt["tenant_id"] = tenant_id
            if warehouse_id is not None:
                flt["warehouse_id"] = warehouse_id
            if tenant_id is not None or warehouse_id is not None:
                flt["engagement_id"] = None
        out = []
        async for d in self.tsk.find(flt):
            out.append(
                {
                    "tenant_id": d.get("tenant_id"),
                    "warehouse_id": d.get("warehouse_id"),
                    "engagement_id": d.get("engagement_id"),
                    "batch_id": d.get("batch_id"),
                    "completed_at": d.get("completed_at"),
                    "zone": d.get("zone"),
                    "operator_id": d.get("operator_id"),
                    "task_type": d.get("task_type"),
                    "duration_sec": d.get("duration_sec"),
                    "sku": d.get("sku"),
                    "extra": d.get("extra") if isinstance(d.get("extra"), dict) else None,
                }
            )
        return out

    async def task_facts_delete_synthetic_for_engagement(self, engagement_id: str) -> int:
        eid = engagement_id.strip()
        if not eid:
            return 0
        r = await self.tsk.delete_many({"engagement_id": eid, "extra.provenance": "synthetic"})
        return int(getattr(r, "deleted_count", 0) or 0)

    async def asn_facts_insert(self, rows):
        if rows:
            await self.asnf.insert_many(rows)

    async def asn_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        out: list[dict] = []
        async for d in self.asnf.find({"engagement_id": eid}):
            out.append(
                {
                    "engagement_id": d.get("engagement_id"),
                    "batch_id": d.get("batch_id"),
                    "asn_line_id": d.get("asn_line_id"),
                    "po_id": d.get("po_id"),
                    "sku": d.get("sku"),
                    "qty_expected": d.get("qty_expected"),
                    "qty_received": d.get("qty_received"),
                    "expected_at_iso": d.get("expected_at_iso"),
                    "received_at_iso": d.get("received_at_iso"),
                    "supplier_id": d.get("supplier_id"),
                    "dock_zone": d.get("dock_zone"),
                    "extra": d.get("extra"),
                }
            )
        return out

    async def order_line_facts_insert(self, rows):
        if rows:
            await self.olnf.insert_many(rows)

    async def order_line_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        out: list[dict] = []
        async for d in self.olnf.find({"engagement_id": eid}):
            out.append(
                {
                    "engagement_id": d.get("engagement_id"),
                    "batch_id": d.get("batch_id"),
                    "order_external_id": d.get("order_external_id"),
                    "line_id": d.get("line_id"),
                    "sku": d.get("sku"),
                    "quantity": d.get("quantity"),
                    "ordered_at_iso": d.get("ordered_at_iso"),
                    "shipped_at_iso": d.get("shipped_at_iso"),
                    "ship_to_postal": d.get("ship_to_postal"),
                    "channel": d.get("channel"),
                    "extra": d.get("extra"),
                }
            )
        return out

    async def billing_line_facts_insert(self, rows):
        if rows:
            await self.blf.insert_many(rows)

    async def billing_line_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        out: list[dict] = []
        async for d in self.blf.find({"engagement_id": eid}):
            out.append(
                {
                    "engagement_id": d.get("engagement_id"),
                    "batch_id": d.get("batch_id"),
                    "invoice_id": d.get("invoice_id"),
                    "line_id": d.get("line_id"),
                    "fee_code": d.get("fee_code"),
                    "service_start_iso": d.get("service_start_iso"),
                    "service_end_iso": d.get("service_end_iso"),
                    "amount_usd": d.get("amount_usd"),
                    "currency": d.get("currency"),
                    "extra": d.get("extra"),
                }
            )
        return out

    async def employee_facts_insert(self, rows):
        if rows:
            await self.empf.insert_many(rows)

    async def employee_facts_list(self, engagement_id: str) -> list[dict]:
        eid = engagement_id.strip()
        if not eid:
            return []
        out: list[dict] = []
        async for d in self.empf.find({"engagement_id": eid}):
            out.append(
                {
                    "engagement_id": d.get("engagement_id"),
                    "batch_id": d.get("batch_id"),
                    "employee_id": d.get("employee_id"),
                    "role": d.get("role"),
                    "hire_date_iso": d.get("hire_date_iso"),
                    "shift_name": d.get("shift_name"),
                    "hourly_rate_usd": d.get("hourly_rate_usd"),
                    "extra": d.get("extra"),
                }
            )
        return out

    async def order_financial_facts_insert(self, rows):
        if rows:
            await self.ofact.insert_many(rows)

    async def order_financial_facts_list(self, engagement_id=None, tenant_id=None, warehouse_id=None):
        flt: dict = {}
        if engagement_id:
            flt["engagement_id"] = engagement_id
        else:
            if tenant_id is not None:
                flt["tenant_id"] = tenant_id
            if warehouse_id is not None:
                flt["warehouse_id"] = warehouse_id
            if tenant_id is not None or warehouse_id is not None:
                flt["engagement_id"] = None
        out = []
        async for d in self.ofact.find(flt):
            ex = d.get("extra") if isinstance(d.get("extra"), dict) else {}
            out.append(
                {
                    "engagement_id": d.get("engagement_id"),
                    "batch_id": d.get("batch_id"),
                    "tenant_id": d.get("tenant_id"),
                    "warehouse_id": d.get("warehouse_id"),
                    "order_external_id": d.get("order_external_id"),
                    "order_date_iso": d.get("order_date_iso"),
                    "email": d.get("email"),
                    "asin": d.get("asin"),
                    "sku": d.get("sku"),
                    "line_title": d.get("line_title"),
                    "revenue_usd": d.get("revenue_usd"),
                    "marketplace_fees_usd": d.get("marketplace_fees_usd"),
                    "amazon_seller_fees_usd": d.get("amazon_seller_fees_usd") if d.get("amazon_seller_fees_usd") is not None else ex.get("amazon_seller_fees_usd"),
                    "amazon_fba_fulfillment_fees_usd": d.get("amazon_fba_fulfillment_fees_usd")
                    if d.get("amazon_fba_fulfillment_fees_usd") is not None
                    else ex.get("amazon_fba_fulfillment_fees_usd"),
                    "fba_fulfillment_fee_audit_line_total_usd": d.get("fba_fulfillment_fee_audit_line_total_usd")
                    if d.get("fba_fulfillment_fee_audit_line_total_usd") is not None
                    else ex.get("fba_fulfillment_fee_audit_line_total_usd"),
                    "fba_fulfillment_fee_audit_per_unit_usd": d.get("fba_fulfillment_fee_audit_per_unit_usd")
                    if d.get("fba_fulfillment_fee_audit_per_unit_usd") is not None
                    else ex.get("fba_fulfillment_fee_audit_per_unit_usd"),
                    "product_cogs_usd": d.get("product_cogs_usd"),
                    "prep_cost_usd": d.get("prep_cost_usd"),
                    "inbound_cost_usd": d.get("inbound_cost_usd"),
                    "total_fees_usd": d.get("total_fees_usd"),
                    "profit_usd": d.get("profit_usd"),
                    "quantity": d.get("quantity"),
                    "other_expenses_usd": d.get("other_expenses_usd"),
                    "ship_to_city": d.get("ship_to_city"),
                    "ship_to_state": d.get("ship_to_state"),
                    "ship_to_postal": d.get("ship_to_postal"),
                    "ship_to_country": d.get("ship_to_country"),
                    "marketplace_fees_2026_csv_usd": d.get("marketplace_fees_2026_csv_usd"),
                    "total_fees_2026_csv_usd": d.get("total_fees_2026_csv_usd"),
                    "profit_2026_csv_usd": d.get("profit_2026_csv_usd"),
                    "marketplace_fees_2026_synthetic_usd": d.get("marketplace_fees_2026_synthetic_usd"),
                    "total_fees_2026_synthetic_usd": d.get("total_fees_2026_synthetic_usd"),
                    "profit_2026_synthetic_usd": d.get("profit_2026_synthetic_usd"),
                    "inflation_source": d.get("inflation_source"),
                    "assumptions_version": d.get("assumptions_version"),
                    "inflation_components": d.get("inflation_components"),
                    "referral_fees_modeled_usd": d.get("referral_fees_modeled_usd"),
                    "referral_fee_bucket": d.get("referral_fee_bucket"),
                    "referral_fee_source": d.get("referral_fee_source"),
                    "extra": d.get("extra"),
                }
            )
        return out

    async def audit_run_insert(self, doc):
        await self.run.insert_one(
            {
                "_id": doc["id"],
                "engagement_id": doc.get("engagement_id"),
                "tenant_id": doc.get("tenant_id"),
                "warehouse_id": doc.get("warehouse_id"),
                "mode": doc.get("mode", "assessment"),
                "status": doc.get("status", "complete"),
                "artifact_json": doc["artifact_json"],
                "narrative_text": doc.get("narrative_text"),
                "created_at": _utc(),
            }
        )

    async def spapi_catalog_snapshot_get(
        self,
        tenant_id: str,
        asin: str,
        marketplace_id: str,
        max_age_days: int = 30,
    ):
        cutoff = _utc() - timedelta(days=max_age_days)
        mp = marketplace_id.strip()
        a = asin.strip()
        d = await self.spapi_cat.find_one(
            {
                "tenant_id": tenant_id,
                "asin": a,
                "marketplace_id": mp,
                "refreshed_at": {"$gte": cutoff},
            }
        )
        if not d:
            return None
        payload = d.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        ra = d.get("refreshed_at")
        return {
            "payload": payload,
            "referral_bucket": d.get("referral_bucket"),
            "refreshed_at": ra.isoformat() if hasattr(ra, "isoformat") else str(ra),
        }

    async def spapi_catalog_snapshot_upsert(
        self,
        tenant_id: str,
        asin: str,
        marketplace_id: str,
        payload: dict[str, Any],
        referral_bucket: str | None,
    ):
        mp = marketplace_id.strip()
        a = asin.strip()
        now = _utc()
        await self.spapi_cat.update_one(
            {"tenant_id": tenant_id, "asin": a, "marketplace_id": mp},
            {
                "$set": {
                    "tenant_id": tenant_id,
                    "asin": a,
                    "marketplace_id": mp,
                    "payload": payload,
                    "referral_bucket": referral_bucket,
                    "refreshed_at": now,
                }
            },
            upsert=True,
        )

    async def audit_run_get(self, run_id):
        d = await self.run.find_one({"_id": run_id})
        if not d:
            return None
        return {
            "id": d["_id"],
            "engagement_id": d.get("engagement_id"),
            "tenant_id": d.get("tenant_id"),
            "warehouse_id": d.get("warehouse_id"),
            "artifact_json": d["artifact_json"],
            "narrative_text": d.get("narrative_text"),
        }

    async def audit_run_set_narrative(self, run_id, text):
        await self.run.update_one({"_id": run_id}, {"$set": {"narrative_text": text}})

    async def audit_run_latest_assessment(self, engagement_id: str):
        d = await self.run.find_one(
            {"engagement_id": engagement_id, "mode": "assessment"},
            sort=[("created_at", -1)],
        )
        if not d:
            return None
        return {
            "id": d["_id"],
            "engagement_id": d.get("engagement_id"),
            "tenant_id": d.get("tenant_id"),
            "warehouse_id": d.get("warehouse_id"),
            "artifact_json": d["artifact_json"],
            "narrative_text": d.get("narrative_text"),
        }

    async def audit_run_latest_operational(self, tenant_id: str, warehouse_id: str):
        d = await self.run.find_one(
            {
                "tenant_id": tenant_id,
                "warehouse_id": warehouse_id,
                "mode": "operational",
            },
            sort=[("created_at", -1)],
        )
        if not d:
            return None
        return {
            "id": d["_id"],
            "engagement_id": d.get("engagement_id"),
            "tenant_id": d.get("tenant_id"),
            "warehouse_id": d.get("warehouse_id"),
            "artifact_json": d["artifact_json"],
            "narrative_text": d.get("narrative_text"),
        }

    async def recommendations_for_warehouse(self, tenant_id: str, warehouse_id: str, limit: int = 15):
        cur = (
            self.rec.find({"tenant_id": tenant_id, "warehouse_id": warehouse_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        out = []
        async for d in cur:
            ps = d.get("proposed_summary") or ""
            out.append(
                {
                    "id": d["_id"],
                    "status": d["status"],
                    "original_summary": d.get("original_summary"),
                    "proposed_summary": ps[:2000],
                    "diff_json": (d.get("diff_json") or [])[:20],
                }
            )
        return out

    async def recommendation_insert(self, doc):
        await self.rec.insert_one(
            {
                "_id": doc["id"],
                "tenant_id": doc["tenant_id"],
                "warehouse_id": doc["warehouse_id"],
                "original_summary": doc["original_summary"],
                "proposed_summary": doc["proposed_summary"],
                "diff_json": doc.get("diff_json", []),
                "status": doc.get("status", "pending"),
                "created_at": _utc(),
            }
        )

    async def recommendation_get(self, rid):
        d = await self.rec.find_one({"_id": rid})
        if not d:
            return None
        return {
            "id": d["_id"],
            "tenant_id": d["tenant_id"],
            "warehouse_id": d["warehouse_id"],
            "original_summary": d["original_summary"],
            "proposed_summary": d["proposed_summary"],
            "diff_json": d.get("diff_json", []),
            "status": d["status"],
        }

    async def recommendation_set_status(self, rid, status, approve_note=None, deny_reason=None):
        upd = {"status": status, "approve_note": approve_note, "deny_reason": deny_reason}
        await self.rec.update_one({"_id": rid}, {"$set": {k: v for k, v in upd.items() if v is not None}})

    async def maiw_proposal_insert(self, doc):
        b = json.loads(doc["before_json"]) if isinstance(doc["before_json"], str) else doc["before_json"]
        a = json.loads(doc["after_json"]) if isinstance(doc["after_json"], str) else doc["after_json"]
        await self.maiw_p.insert_one(
            {
                "_id": doc["id"],
                "tenant_id": doc["tenant_id"],
                "warehouse_id": doc["warehouse_id"],
                "engagement_id": doc.get("engagement_id"),
                "run_id": doc.get("run_id"),
                "title": doc["title"],
                "before": b,
                "after": a,
                "diff_lines": doc.get("diff_lines") or [],
                "status": doc.get("status", "pending"),
                "source": doc.get("source", "deterministic"),
                "nim_rationale": doc.get("nim_rationale"),
                "created_at": _utc(),
            }
        )

    async def maiw_proposal_get(self, pid):
        d = await self.maiw_p.find_one({"_id": pid})
        if not d:
            return None
        ca = d.get("created_at")
        return {
            "id": d["_id"],
            "tenant_id": d["tenant_id"],
            "warehouse_id": d["warehouse_id"],
            "engagement_id": d.get("engagement_id"),
            "run_id": d.get("run_id"),
            "title": d["title"],
            "before": d.get("before"),
            "after": d.get("after"),
            "diff_lines": d.get("diff_lines") or [],
            "status": d["status"],
            "source": d.get("source"),
            "nim_rationale": d.get("nim_rationale"),
            "approve_note": d.get("approve_note"),
            "deny_reason": d.get("deny_reason"),
            "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
        }

    async def maiw_proposal_list(self, tenant_id: str, warehouse_id: str, limit: int = 30):
        cur = (
            self.maiw_p.find({"tenant_id": tenant_id, "warehouse_id": warehouse_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        out = []
        async for d in cur:
            out.append(
                {
                    "id": d["_id"],
                    "title": d["title"],
                    "status": d["status"],
                    "source": d.get("source"),
                    "created_at": d.get("created_at"),
                }
            )
        return out

    async def maiw_proposal_set_status(self, pid, status, approve_note=None, deny_reason=None):
        upd = {"status": status}
        if approve_note is not None:
            upd["approve_note"] = approve_note
        if deny_reason is not None:
            upd["deny_reason"] = deny_reason
        await self.maiw_p.update_one({"_id": pid}, {"$set": upd})

    async def maiw_wh_proposal_insert(self, doc: dict[str, Any]) -> None:
        await self.maiw_wh_p.insert_one(
            {
                "_id": doc["id"],
                "tenant_id": doc["tenant_id"],
                "warehouse_id": doc["warehouse_id"],
                "capability": doc["capability"],
                "correlation_id": doc.get("correlation_id"),
                "payload_hash": doc.get("payload_hash"),
                "payload": json.loads(doc["payload_json"]) if isinstance(doc["payload_json"], str) else doc["payload_json"],
                "four_variants": json.loads(doc["response_json"])
                if isinstance(doc["response_json"], str)
                else doc["response_json"],
                "status": doc.get("status", "pending"),
                "value_score_snapshot": json.loads(doc["value_score_snapshot_json"])
                if doc.get("value_score_snapshot_json")
                else None,
                "chosen_variant": None,
                "approve_note": None,
                "deny_reason": None,
                "created_at": _utc(),
            }
        )

    async def maiw_wh_proposal_get(self, pid: str) -> dict[str, Any] | None:
        d = await self.maiw_wh_p.find_one({"_id": pid})
        if not d:
            return None
        ca = d.get("created_at")
        return {
            "id": d["_id"],
            "tenant_id": d["tenant_id"],
            "warehouse_id": d["warehouse_id"],
            "capability": d["capability"],
            "correlation_id": d.get("correlation_id"),
            "payload_hash": d.get("payload_hash"),
            "payload": d.get("payload") or {},
            "four_variants": d.get("four_variants") or {},
            "status": d["status"],
            "chosen_variant": d.get("chosen_variant"),
            "approve_note": d.get("approve_note"),
            "deny_reason": d.get("deny_reason"),
            "value_score_snapshot": d.get("value_score_snapshot"),
            "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
        }

    async def maiw_wh_proposal_set_decision(
        self,
        pid: str,
        status: str,
        chosen_variant: str | None = None,
        approve_note: str | None = None,
        deny_reason: str | None = None,
    ) -> None:
        upd: dict[str, Any] = {"status": status}
        if chosen_variant is not None:
            upd["chosen_variant"] = chosen_variant
        if approve_note is not None:
            upd["approve_note"] = approve_note
        if deny_reason is not None:
            upd["deny_reason"] = deny_reason
        await self.maiw_wh_p.update_one({"_id": pid}, {"$set": upd})

    async def maiw_wh_proposals_for_metrics(
        self,
        tenant_id: str | None,
        capability: str | None,
        from_iso: str | None,
        to_iso: str | None,
    ) -> list[dict[str, Any]]:
        filt: dict[str, Any] = {}
        if tenant_id:
            filt["tenant_id"] = tenant_id
        if capability:
            filt["capability"] = capability
        if from_iso or to_iso:
            filt["created_at"] = {}
            if from_iso:
                try:
                    filt["created_at"]["$gte"] = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if to_iso:
                try:
                    filt["created_at"]["$lte"] = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if not filt["created_at"]:
                del filt["created_at"]
        out = []
        async for d in self.maiw_wh_p.find(filt):
            ca = d.get("created_at")
            out.append(
                {
                    "status": d["status"],
                    "capability": d["capability"],
                    "tenant_id": d["tenant_id"],
                    "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                }
            )
        return out

    async def maiw_wh_outcome_insert(self, doc: dict[str, Any]) -> None:
        await self.maiw_wh_o.insert_one(
            {
                "_id": doc["id"],
                "proposal_id": doc["proposal_id"],
                "body": json.loads(doc["body_json"]) if isinstance(doc["body_json"], str) else doc["body_json"],
                "created_at": _utc(),
            }
        )

    async def ai_invocation_insert(self, doc: dict[str, Any]) -> None:
        await self.ai_inv.insert_one(
            {
                "_id": doc["id"],
                "created_at": _utc(),
                "capability": doc["capability"],
                "tenant_id": doc.get("tenant_id"),
                "engagement_id": doc.get("engagement_id"),
                "run_id": doc.get("run_id"),
                "proposal_id": doc.get("proposal_id"),
                "correlation_id": doc.get("correlation_id"),
                "model": doc["model"],
                "http_status": doc.get("http_status"),
                "latency_ms": int(doc.get("latency_ms") or 0),
                "source": doc["source"],
                "prompt_sha256": doc["prompt_sha256"],
                "response_sha256": doc.get("response_sha256"),
                "prompt_preview": doc.get("prompt_preview"),
                "response_preview": doc.get("response_preview"),
                "extra_json": doc.get("extra_json"),
            }
        )

    async def ai_invocations_list(
        self, *, tenant_id: str, capability: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        filt: dict[str, Any] = {"tenant_id": tenant_id}
        if capability:
            filt["capability"] = capability
        cur = self.ai_inv.find(filt).sort("created_at", -1).limit(min(max(limit, 1), 500))
        out: list[dict[str, Any]] = []
        async for d in cur:
            ca = d.get("created_at")
            out.append(
                {
                    "id": d["_id"],
                    "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                    "capability": d.get("capability"),
                    "tenant_id": d.get("tenant_id"),
                    "engagement_id": d.get("engagement_id"),
                    "run_id": d.get("run_id"),
                    "proposal_id": d.get("proposal_id"),
                    "correlation_id": d.get("correlation_id"),
                    "model": d.get("model"),
                    "http_status": d.get("http_status"),
                    "latency_ms": d.get("latency_ms"),
                    "source": d.get("source"),
                    "prompt_sha256": d.get("prompt_sha256"),
                    "response_sha256": d.get("response_sha256"),
                    "prompt_preview": d.get("prompt_preview"),
                    "response_preview": d.get("response_preview"),
                    "extra_json": d.get("extra_json"),
                }
            )
        return out

    async def templates_list(self):
        out = []
        async for d in self.tpl.find():
            out.append({"vendor_key": d["vendor_key"], "label": d["label"], "mappings": d["mappings"]})
        return out

    async def keepa_snapshot_get(
        self, tenant_id: str, asin: str, domain: int = 1, max_age_days: int = 15
    ):
        cutoff = _utc() - timedelta(days=max_age_days)
        d = await self.keepa.find_one(
            {
                "tenant_id": tenant_id,
                "asin": asin,
                "domain": domain,
                "refreshed_at": {"$gte": cutoff},
            }
        )
        if not d:
            return None
        data = d.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        return {"data": data, "refreshed_at": d["refreshed_at"].isoformat()}

    async def keepa_snapshot_upsert(
        self, tenant_id: str, asin: str, data: dict, domain: int = 1
    ):
        await self.keepa.update_one(
            {"tenant_id": tenant_id, "asin": asin, "domain": domain},
            {
                "$set": {
                    "data": data,
                    "refreshed_at": _utc(),
                }
            },
            upsert=True,
        )

    async def sku_catalog_upsert(self, tenant_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        sku = (doc.get("sku") or "").strip()
        if not sku:
            raise ValueError("sku required")
        _id = f"{tenant_id}::{sku}"
        now = _utc()
        existing = await self.sku_cat.find_one({"_id": _id})
        created = existing.get("created_at") if existing else now
        asin = doc.get("asin")
        if asin is not None and str(asin).strip() == "":
            asin = None
        elif asin is not None:
            asin = str(asin).strip()
        payload = {
            "_id": _id,
            "tenant_id": tenant_id,
            "sku": sku,
            "asin": asin,
            "weight_lb": doc.get("weight_lb"),
            "length_in": doc.get("length_in"),
            "width_in": doc.get("width_in"),
            "height_in": doc.get("height_in"),
            "extra": doc.get("extra"),
            "created_at": created,
            "updated_at": now,
        }
        await self.sku_cat.update_one({"_id": _id}, {"$set": payload}, upsert=True)
        return await self.sku_catalog_get(tenant_id, sku)  # type: ignore[no-any-return]

    async def sku_catalog_get(self, tenant_id: str, sku: str) -> dict[str, Any] | None:
        d = await self.sku_cat.find_one({"_id": f"{tenant_id}::{sku.strip()}"})
        if not d:
            return None
        ca, ua = d.get("created_at"), d.get("updated_at")
        return {
            "tenant_id": d["tenant_id"],
            "sku": d["sku"],
            "asin": d.get("asin"),
            "weight_lb": d.get("weight_lb"),
            "length_in": d.get("length_in"),
            "width_in": d.get("width_in"),
            "height_in": d.get("height_in"),
            "extra": d.get("extra"),
            "physical_signature": None,
            "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
            "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else str(ua),
        }

    async def sku_catalog_list(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        cur = self.sku_cat.find({"tenant_id": tenant_id}).sort("updated_at", -1).limit(limit)
        out = []
        async for d in cur:
            ca, ua = d.get("created_at"), d.get("updated_at")
            out.append(
                {
                    "tenant_id": d["tenant_id"],
                    "sku": d["sku"],
                    "asin": d.get("asin"),
                    "weight_lb": d.get("weight_lb"),
                    "length_in": d.get("length_in"),
                    "width_in": d.get("width_in"),
                    "height_in": d.get("height_in"),
                    "extra": d.get("extra"),
                    "created_at": ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                    "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else str(ua),
                }
            )
        return out

    async def sku_catalog_find_by_asin(self, tenant_id: str, asin: str) -> list[dict[str, Any]]:
        cur = self.sku_cat.find({"tenant_id": tenant_id, "asin": asin.strip()})
        out = []
        async for d in cur:
            g = await self.sku_catalog_get(tenant_id, d["sku"])
            if g:
                out.append(g)
        return out

    async def sku_demand_upsert(
        self,
        tenant_id: str,
        asin: str,
        domain: int,
        derived: dict[str, Any],
        sku: str | None = None,
        method: str = "keepa_v1",
    ) -> None:
        asin = asin.strip()
        _id = f"{tenant_id}::{asin}::{domain}"
        now = _utc()
        await self.sku_dem.update_one(
            {"_id": _id},
            {
                "$set": {
                    "_id": _id,
                    "tenant_id": tenant_id,
                    "asin": asin,
                    "domain": domain,
                    "sku": sku.strip() if sku else None,
                    "derived": derived,
                    "method": method,
                    "refreshed_at": now,
                }
            },
            upsert=True,
        )

    async def sku_demand_get(
        self, tenant_id: str, asin: str, domain: int = 1
    ) -> dict[str, Any] | None:
        d = await self.sku_dem.find_one({"_id": f"{tenant_id}::{asin.strip()}::{domain}"})
        if not d:
            return None
        ra = d.get("refreshed_at")
        return {
            "tenant_id": d["tenant_id"],
            "asin": d["asin"],
            "domain": d["domain"],
            "sku": d.get("sku"),
            "derived": d.get("derived") or {},
            "method": d.get("method"),
            "refreshed_at": ra.isoformat() if hasattr(ra, "isoformat") else str(ra),
        }

    async def sku_demand_list_for_tenant(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        cur = self.sku_dem.find({"tenant_id": tenant_id}).sort("refreshed_at", -1).limit(limit)
        out = []
        async for d in cur:
            ra = d.get("refreshed_at")
            out.append(
                {
                    "tenant_id": d["tenant_id"],
                    "asin": d["asin"],
                    "domain": d["domain"],
                    "sku": d.get("sku"),
                    "derived": d.get("derived") or {},
                    "method": d.get("method"),
                    "refreshed_at": ra.isoformat() if hasattr(ra, "isoformat") else str(ra),
                }
            )
        return out

    async def rate_shop_cache_get(
        self, tenant_id: str, cache_key: str, max_age_days: int = 30
    ) -> dict[str, Any] | None:
        cutoff = _utc() - timedelta(days=max_age_days)
        d = await self.rate_shop.find_one(
            {
                "_id": f"{tenant_id}::{cache_key}",
                "refreshed_at": {"$gte": cutoff},
            }
        )
        if not d:
            return None
        q = d.get("quote")
        if isinstance(q, str):
            q = json.loads(q)
        ra = d.get("refreshed_at")
        return {
            "quote": q,
            "refreshed_at": ra.isoformat() if hasattr(ra, "isoformat") else str(ra),
            "bucket": d.get("bucket"),
            "origin_postal_norm": d.get("origin_postal_norm"),
            "dest_postal_norm": d.get("dest_postal_norm"),
            "service_code": d.get("service_code"),
        }

    async def rate_shop_cache_put(
        self,
        tenant_id: str,
        cache_key: str,
        bucket: str,
        origin_postal: str,
        dest_postal: str,
        service_code: str,
        quote: dict[str, Any],
    ) -> None:
        from unie_cortex.network.rate_bucket import normalize_postal_5

        on = normalize_postal_5(origin_postal)
        dn = normalize_postal_5(dest_postal)
        svc = (service_code or "GROUND").strip().upper() or "GROUND"
        now = _utc()
        await self.rate_shop.update_one(
            {"_id": f"{tenant_id}::{cache_key}"},
            {
                "$set": {
                    "_id": f"{tenant_id}::{cache_key}",
                    "tenant_id": tenant_id,
                    "cache_key": cache_key,
                    "bucket": bucket,
                    "origin_postal_norm": on,
                    "dest_postal_norm": dn,
                    "service_code": svc,
                    "quote": quote,
                    "refreshed_at": now,
                }
            },
            upsert=True,
        )

    async def parcel_quote_observations_insert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        now = _utc()
        docs = []
        for d in rows:
            docs.append(
                {
                    "tenant_id": d["tenant_id"],
                    "origin_postal_norm": d["origin_postal_norm"],
                    "dest_postal_norm": d["dest_postal_norm"],
                    "physical_bucket": d["physical_bucket"],
                    "length_in": d.get("length_in"),
                    "width_in": d.get("width_in"),
                    "height_in": d.get("height_in"),
                    "weight_lb": d.get("weight_lb"),
                    "carrier": d.get("carrier"),
                    "service_code": d.get("service_code"),
                    "amount_usd": float(d.get("amount_usd") or 0.0),
                    "source": d.get("source") or "unknown",
                    "created_at": now,
                }
            )
        await self.pqo.insert_many(docs)

    async def tax_jurisdiction_replace_scope_provider(
        self,
        scope_tenant_id: str,
        provider: str,
        rows: list[dict[str, Any]],
    ) -> int:
        sc = scope_tenant_id.strip() or "__system__"
        pv = provider.strip() or "unknown"
        await self.tax_snap.delete_many({"scope_tenant_id": sc, "provider": pv})
        now = _utc()
        docs = []
        for d in rows:
            cc = str(d.get("country_code") or "US").upper()
            rc = str(d.get("region_code") or "").upper()[:16]
            docs.append(
                {
                    "_id": f"{sc}::{pv}::{cc}::{rc}",
                    "scope_tenant_id": sc,
                    "provider": pv,
                    "country_code": cc,
                    "region_code": rc,
                    "raw_json": str(d.get("raw_json") or "{}"),
                    "average_rate": d.get("average_rate"),
                    "minimum_rate": d.get("minimum_rate"),
                    "refreshed_at": now,
                }
            )
        if docs:
            await self.tax_snap.insert_many(docs)
        return len(docs)

    async def tax_jurisdiction_get(
        self,
        scope_tenant_id: str,
        provider: str,
        country_code: str,
        region_code: str,
    ) -> dict[str, Any] | None:
        sc = scope_tenant_id.strip() or "__system__"
        cc = country_code.strip().upper()
        rc = region_code.strip().upper()
        d = await self.tax_snap.find_one(
            {"scope_tenant_id": sc, "provider": provider.strip(), "country_code": cc, "region_code": rc}
        )
        if not d:
            return None
        raw = d.get("raw_json") or "{}"
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            parsed = {}
        ra = d.get("refreshed_at")
        return {
            "scope_tenant_id": d.get("scope_tenant_id"),
            "provider": d.get("provider"),
            "country_code": d.get("country_code"),
            "region_code": d.get("region_code"),
            "raw": parsed if isinstance(parsed, dict) else {},
            "average_rate": d.get("average_rate"),
            "minimum_rate": d.get("minimum_rate"),
            "refreshed_at": ra.isoformat() if hasattr(ra, "isoformat") else str(ra),
        }

    async def tax_jurisdiction_list_us_system(self, provider: str = "taxjar") -> list[dict[str, Any]]:
        cursor = self.tax_snap.find(
            {"scope_tenant_id": "__system__", "provider": provider.strip(), "country_code": "US"},
        )
        docs = await cursor.to_list(length=500)
        docs.sort(key=lambda x: str(x.get("region_code") or ""))
        out: list[dict[str, Any]] = []
        for d in docs:
            ra = d.get("refreshed_at")
            out.append(
                {
                    "region_code": d.get("region_code"),
                    "average_rate": d.get("average_rate"),
                    "minimum_rate": d.get("minimum_rate"),
                    "refreshed_at": ra.isoformat() if hasattr(ra, "isoformat") else str(ra),
                }
            )
        return out

    async def tax_sync_run_insert(self, run_id: str, provider: str) -> None:
        now = _utc()
        await self.tax_sync.insert_one(
            {
                "_id": run_id,
                "id": run_id,
                "provider": provider,
                "status": "running",
                "regions_count": 0,
                "error_message": None,
                "started_at": now,
                "finished_at": None,
            }
        )

    async def tax_sync_run_finish(
        self,
        run_id: str,
        *,
        status: str,
        regions_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        now = _utc()
        await self.tax_sync.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": status,
                    "regions_count": regions_count,
                    "error_message": error_message,
                    "finished_at": now,
                }
            },
        )

    async def tenant_sales_tax_nexus_set(self, tenant_id: str, state_codes: list[str]) -> None:
        tid = tenant_id.strip()
        await self.tenant_nexus.delete_many({"tenant_id": tid})
        now = _utc()
        docs = []
        for s in state_codes:
            code = str(s or "").strip().upper()[:8]
            if len(code) == 2:
                docs.append({"_id": f"{tid}::{code}", "tenant_id": tid, "state_code": code, "updated_at": now})
        if docs:
            await self.tenant_nexus.insert_many(docs)

    async def tenant_sales_tax_nexus_list(self, tenant_id: str) -> list[str]:
        out: list[str] = []
        cur = self.tenant_nexus.find({"tenant_id": tenant_id.strip()})
        async for d in cur:
            sc = d.get("state_code")
            if sc:
                out.append(str(sc))
        return sorted(set(out))

    async def facility_freight_profile_upsert(
        self, tenant_id: str, location_id: str, profile: dict[str, Any]
    ) -> dict[str, Any]:
        from unie_cortex.network.facility_freight_profile import to_broker_card

        tid, lid = tenant_id.strip(), location_id.strip()
        if not tid or not lid:
            raise ValueError("tenant_id and location_id required")
        prof = dict(profile or {})
        now = _utc()
        _id = f"{tid}::{lid}"
        await self.ffp.update_one(
            {"_id": _id},
            {
                "$set": {
                    "_id": _id,
                    "tenant_id": tid,
                    "location_id": lid,
                    "profile": prof,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        return {
            "tenant_id": tid,
            "location_id": lid,
            "profile": prof,
            "broker_card": to_broker_card(prof),
            "updated_at": now.isoformat(),
        }

    async def facility_freight_profile_get(
        self, tenant_id: str, location_id: str
    ) -> dict[str, Any] | None:
        from unie_cortex.network.facility_freight_profile import to_broker_card

        tid, lid = tenant_id.strip(), location_id.strip()
        if not tid or not lid:
            return None
        d = await self.ffp.find_one({"_id": f"{tid}::{lid}"})
        if not d:
            return None
        prof = d.get("profile") or {}
        ua = d.get("updated_at")
        ua_str = ua.isoformat() if hasattr(ua, "isoformat") else (str(ua) if ua else _utc().isoformat())
        return {
            "tenant_id": tid,
            "location_id": lid,
            "profile": prof,
            "broker_card": to_broker_card(prof),
            "updated_at": ua_str,
        }

    async def facility_freight_profiles_list(
        self, tenant_id: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        from unie_cortex.network.facility_freight_profile import to_broker_card

        tid = tenant_id.strip()
        if not tid:
            return []
        lim = max(1, min(5000, int(limit)))
        out: list[dict[str, Any]] = []
        cur = self.ffp.find({"tenant_id": tid}).sort("updated_at", -1).limit(lim)
        async for d in cur:
            prof = d.get("profile") or {}
            ua = d.get("updated_at")
            ua_str = ua.isoformat() if hasattr(ua, "isoformat") else (str(ua) if ua else "")
            out.append(
                {
                    "tenant_id": d.get("tenant_id"),
                    "location_id": d.get("location_id"),
                    "profile": prof,
                    "broker_card": to_broker_card(prof),
                    "updated_at": ua_str,
                }
            )
        return out

    async def templates_seed_default(self):
        n = await self.tpl.count_documents({})
        if n:
            return
        await self.tpl.insert_one(
            {
                "vendor_key": "generic_labels_v1",
                "label": "Generic shipping labels CSV",
                "mappings": {
                    "labels": {
                        "tracking_number": "tracking_number",
                        "Tracking": "tracking_number",
                        "carrier": "carrier",
                        "Carrier": "carrier",
                        "service": "service_code",
                        "amount": "label_amount_usd",
                        "Amount": "label_amount_usd",
                        "cost": "label_amount_usd",
                        "weight": "weight_lb",
                        "Weight": "weight_lb",
                        "origin_zip": "origin_postal",
                        "dest_zip": "dest_postal",
                        "ship_date": "ship_date",
                        "sku": "sku",
                        "SKU": "sku",
                        "qty": "qty",
                        "Qty": "qty",
                        "line_amount": "line_amount_usd",
                    },
                    "tasks": {
                        "completed_at": "completed_at",
                        "timestamp": "completed_at",
                        "zone": "zone",
                        "Zone": "zone",
                        "operator": "operator_id",
                        "task_type": "task_type",
                        "duration_sec": "duration_sec",
                        "sku": "sku",
                        "SKU": "sku",
                    },
                },
                "created_at": _utc(),
            }
        )


async def ensure_mongo_indexes(db: Any) -> None:
    await db["cortex_audit_runs"].create_index([("engagement_id", 1), ("created_at", -1)])
    await db["cortex_audit_runs"].create_index(
        [("tenant_id", 1), ("warehouse_id", 1), ("mode", 1), ("created_at", -1)]
    )
    await db["cortex_recommendations"].create_index(
        [("tenant_id", 1), ("warehouse_id", 1), ("created_at", -1)]
    )
    await db["cortex_maiw_proposals"].create_index(
        [("tenant_id", 1), ("warehouse_id", 1), ("created_at", -1)]
    )
    await db["cortex_maiw_wh_proposals"].create_index(
        [("tenant_id", 1), ("warehouse_id", 1), ("created_at", -1)]
    )
    await db["cortex_maiw_wh_proposals"].create_index([("capability", 1), ("created_at", -1)])
    await db["cortex_maiw_wh_proposals"].create_index("correlation_id")
    await db["cortex_maiw_wh_outcomes"].create_index([("proposal_id", 1), ("created_at", -1)])
    await db["cortex_mappings"].create_index([("engagement_id", 1), ("version", -1)])
    await db["cortex_label_facts"].create_index("engagement_id")
    await db["cortex_label_facts"].create_index([("tenant_id", 1), ("warehouse_id", 1)])
    await db["cortex_task_facts"].create_index("engagement_id")
    await db["cortex_task_facts"].create_index([("tenant_id", 1), ("warehouse_id", 1)])
    await db["cortex_mapping_templates"].create_index("vendor_key", unique=True)
    await db["cortex_keepa_snapshots"].create_index(
        [("tenant_id", 1), ("asin", 1), ("domain", 1)],
        unique=True,
    )
    await db["cortex_keepa_snapshots"].create_index([("tenant_id", 1), ("refreshed_at", -1)])
    await db["cortex_sku_catalog"].create_index([("tenant_id", 1), ("sku", 1)], unique=True)
    await db["cortex_sku_catalog"].create_index([("tenant_id", 1), ("asin", 1)])
    await db["cortex_sku_demand"].create_index([("tenant_id", 1), ("asin", 1), ("domain", 1)], unique=True)
    await db["cortex_rate_shop_cache"].create_index([("tenant_id", 1), ("refreshed_at", -1)])
    await db["cortex_parcel_quote_observations"].create_index(
        [("tenant_id", 1), ("created_at", -1)]
    )
    await db["cortex_parcel_quote_observations"].create_index(
        [("tenant_id", 1), ("physical_bucket", 1), ("origin_postal_norm", 1), ("dest_postal_norm", 1)]
    )
    await db["cortex_order_financial_facts"].create_index("engagement_id")
    await db["cortex_order_financial_facts"].create_index([("engagement_id", 1), ("asin", 1)])
    await db["cortex_asn_facts"].create_index("engagement_id")
    await db["cortex_order_line_facts"].create_index("engagement_id")
    await db["cortex_billing_line_facts"].create_index("engagement_id")
    await db["cortex_employee_facts"].create_index("engagement_id")
    await db["cortex_spapi_catalog_snapshots"].create_index(
        [("tenant_id", 1), ("asin", 1), ("marketplace_id", 1)],
        unique=True,
    )
    await db["cortex_spapi_catalog_snapshots"].create_index([("tenant_id", 1), ("refreshed_at", -1)])
    await db["cortex_tax_jurisdiction_snapshots"].create_index(
        [("scope_tenant_id", 1), ("provider", 1), ("region_code", 1)]
    )
    await db["cortex_tax_sync_runs"].create_index([("provider", 1), ("started_at", -1)])
    await db["cortex_tenant_sales_tax_nexus"].create_index([("tenant_id", 1)], unique=False)
    await db["cortex_ai_invocations"].create_index([("tenant_id", 1), ("created_at", -1)])
    await db["cortex_ai_invocations"].create_index([("capability", 1), ("created_at", -1)])
