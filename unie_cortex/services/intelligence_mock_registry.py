"""Aggregated mock entities + cost_fields for Intelligence Network hub UI."""

from __future__ import annotations

from typing import Any

from unie_cortex.config import Settings, settings as default_settings
from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.pallet_defaults import (
    REFERENCE_PALLET_HEIGHT_IN,
    REFERENCE_PALLET_LENGTH_IN,
    REFERENCE_PALLET_WIDTH_IN,
    reference_pallet_cuft,
)
from unie_cortex.network.tms_fleet_mocks import list_mock_tractors
from unie_cortex.network.warehouse_pricing_mock import get_pricing_profile
from unie_cortex.network.zones import list_supported_carriers
from unie_cortex.services.network_mock_registry import build_mock_network_reference


def _cf(
    *,
    key: str,
    label: str,
    value: Any,
    unit: str,
    applies_to_party: str,
    source: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "applies_to_party": applies_to_party,
        "source": source,
    }


def _infer_unit(parent_key: str, leaf_key: str) -> str:
    lk = leaf_key.lower()
    pk = parent_key.lower()
    if "percent" in lk or lk.endswith("_pct"):
        return "ratio"
    if "per_unit" in lk or lk.endswith("_per_unit_usd"):
        return "usd_per_unit"
    if "per_order" in lk or "per_asn" in lk or "per_return" in lk:
        return "usd_flat"
    if "per_pallet" in lk or "per_bin" in lk or "per_cuft" in lk or "per_item" in lk:
        return "usd_per_unit_or_space"
    if "flat" in lk and "usd" in lk:
        return "usd_flat"
    if pk == "shipping_labels_markup" or pk == "materials_markup":
        return "markup_component"
    return "usd"


def _flatten_rate_card_for_cost_fields(
    rc: dict[str, Any],
    *,
    applies_to_party: str,
    max_fields: int = 80,
) -> list[dict[str, Any]]:
    """Pull numeric leaves from mock rate_card for transparency (capped)."""
    skip_roots = {"smart_billing", "general", "prep_services"}
    out: list[dict[str, Any]] = []
    for section, body in rc.items():
        if section.startswith("_") or section in skip_roots:
            continue
        if not isinstance(body, dict):
            continue
        for leaf_key, val in body.items():
            if len(out) >= max_fields:
                return out
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                path = f"rate_card.{section}.{leaf_key}"
                out.append(
                    _cf(
                        key=path,
                        label=f"{section}.{leaf_key}",
                        value=round(float(val), 6) if isinstance(val, float) else val,
                        unit=_infer_unit(section, leaf_key),
                        applies_to_party=applies_to_party,
                        source=f"rate_card:{section}.{leaf_key}",
                    )
                )
            elif isinstance(val, dict) and section == "lab":
                for lk2, v2 in val.items():
                    if len(out) >= max_fields:
                        return out
                    if isinstance(v2, (int, float)) and not isinstance(v2, bool):
                        path = f"rate_card.lab.{lk2}"
                        out.append(
                            _cf(
                                key=path,
                                label=f"lab.{lk2}",
                                value=round(float(v2), 6) if isinstance(v2, float) else v2,
                                unit="usd_per_unit",
                                applies_to_party=applies_to_party,
                                source=f"rate_card:lab.{lk2}",
                            )
                        )
    return out


def _economics_defaults_cost_fields(cfg: Settings) -> list[dict[str, Any]]:
    return [
        _cf(
            key="economics_default_inbound_receiving_per_unit_usd",
            label="Default inbound receiving ($/unit)",
            value=float(cfg.economics_default_inbound_receiving_per_unit_usd),
            unit="usd_per_unit",
            applies_to_party="global_default",
            source="settings:ECONOMICS_DEFAULT_INBOUND_RECEIVING_PER_UNIT_USD",
        ),
        _cf(
            key="economics_default_outbound_handling_per_unit_usd",
            label="Default outbound handling ($/unit)",
            value=float(cfg.economics_default_outbound_handling_per_unit_usd),
            unit="usd_per_unit",
            applies_to_party="global_default",
            source="settings:ECONOMICS_DEFAULT_OUTBOUND_HANDLING_PER_UNIT_USD",
        ),
        _cf(
            key="economics_default_storage_per_unit_month_usd",
            label="Default storage ($/unit/month)",
            value=float(cfg.economics_default_storage_per_unit_month_usd),
            unit="usd_per_month",
            applies_to_party="global_default",
            source="settings:ECONOMICS_DEFAULT_STORAGE_PER_UNIT_MONTH_USD",
        ),
        _cf(
            key="smart_network_default_lane_cost_per_lb",
            label="Default inter-DC lane cost ($/lb)",
            value=float(cfg.smart_network_default_lane_cost_per_lb),
            unit="usd_per_lb",
            applies_to_party="global_default",
            source="settings:SMART_NETWORK_DEFAULT_LANE_COST_PER_LB",
        ),
        _cf(
            key="network_consolidated_linehaul_cost_multiplier",
            label="Consolidated linehaul cost multiplier",
            value=float(cfg.network_consolidated_linehaul_cost_multiplier),
            unit="multiplier",
            applies_to_party="global_default",
            source="settings:NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER",
        ),
        _cf(
            key="economics_default_pricing_profile_id",
            label="Default pricing profile id (hub-spoke rate card)",
            value=str(cfg.economics_default_pricing_profile_id),
            unit="string",
            applies_to_party="global_default",
            source="settings:ECONOMICS_DEFAULT_PRICING_PROFILE_ID",
        ),
    ]


def _default_profile_rate_cost_fields(cfg: Settings) -> list[dict[str, Any]]:
    pid = str(cfg.economics_default_pricing_profile_id or "profile_nj_v1").strip()
    prof = get_pricing_profile(pid) or {}
    rc = prof.get("rate_card") if isinstance(prof.get("rate_card"), dict) else {}
    if not rc:
        return []
    return _flatten_rate_card_for_cost_fields(rc, applies_to_party="warehouse")


def _shared_warehouse_cost_fields(cfg: Settings) -> list[dict[str, Any]]:
    """Economics defaults + default profile rate card (for mock warehouse rows)."""
    base = _economics_defaults_cost_fields(cfg)
    base.extend(_default_profile_rate_cost_fields(cfg))
    return base


def _parcel_carrier_row(carrier: str, cfg: Settings) -> dict[str, Any]:
    if carrier == "usps":
        base, per_lb, per_zone = 4.2, 0.55, 0.38
        zone_note = "mock_usps_zip3_step_40"
    elif carrier == "ups":
        base, per_lb, per_zone = 5.1, 0.48, 0.52
        zone_note = "mock_ups_zip3_step_45"
    else:
        base, per_lb, per_zone = 5.4, 0.50, 0.45
        zone_note = "mock_fedex_zip3_step_55"

    integrated_note = "mock_parcel_quote_usd"
    if cfg.shippo_configured and not cfg.shippo_mock_mode:
        integrated_note = "integrated: RateShoppingService (SHIPPO_API_KEY, shippo_mock_mode=false)"
    elif cfg.shippo_configured and cfg.shippo_mock_mode:
        integrated_note = "Shippo key set but SHIPPO_MOCK_MODE=true — fake quotes"
    elif (cfg.rate_shopping_url or "").strip():
        integrated_note = "RATE_SHOPPING_URL may supply live multi-carrier rates"

    cfs = [
        _cf(
            key=f"parcel_mock.{carrier}.base_usd",
            label="Mock base charge (USD)",
            value=base,
            unit="usd_flat",
            applies_to_party="parcel_carrier",
            source="code:unie_cortex.network.parcel_mock:mock_parcel_quote_usd",
        ),
        _cf(
            key=f"parcel_mock.{carrier}.per_lb_usd",
            label="Mock per-lb (USD)",
            value=per_lb,
            unit="usd_per_lb",
            applies_to_party="parcel_carrier",
            source="code:unie_cortex.network.parcel_mock:mock_parcel_quote_usd",
        ),
        _cf(
            key=f"parcel_mock.{carrier}.per_zone_usd",
            label="Mock per zone step (USD × zone index)",
            value=per_zone,
            unit="coefficient",
            applies_to_party="parcel_carrier",
            source="code:unie_cortex.network.parcel_mock:mock_parcel_quote_usd",
        ),
        _cf(
            key=f"parcel_mock.{carrier}.zone_model",
            label="Zone model",
            value=zone_note,
            unit="string",
            applies_to_party="parcel_carrier",
            source="code:unie_cortex.network.zones:mock_zone_id",
        ),
        _cf(
            key=f"parcel_mock.{carrier}.dim_surcharge_rule",
            label="Dim surcharge if cube cu ft > 1.5",
            value="(cu - 1.5) * 2.2 USD",
            unit="string",
            applies_to_party="parcel_carrier",
            source="code:unie_cortex.network.parcel_mock:mock_parcel_quote_usd",
        ),
        _cf(
            key=f"parcel_mock.{carrier}.floor_total_usd",
            label="Minimum mock total (USD)",
            value=3.5,
            unit="usd_flat",
            applies_to_party="parcel_carrier",
            source="code:unie_cortex.network.parcel_mock:mock_parcel_quote_usd",
        ),
        _cf(
            key=f"parcel_integrated.note",
            label="Integrated parcel path",
            value=integrated_note,
            unit="string",
            applies_to_party="parcel_carrier",
            source="settings:SHIPPO_API_KEY,RATE_SHOPPING_URL",
        ),
    ]
    return {"carrier_id": carrier, "cost_fields": cfs}


def _ltl_default_cost_fields(cfg: Settings, applies: str) -> list[dict[str, Any]]:
    kw = getattr(mock_ltl_quote_usd, "__kwdefaults__", None) or {}
    min_c = float(kw.get("min_charge_usd", 125.0))
    per_lb = float(kw.get("per_lb_usd", 0.06))
    per_slot = float(kw.get("per_pallet_slot_usd", 48.0))

    slot = reference_pallet_cuft()
    return [
        _cf(
            key="ltl_mock.min_charge_usd",
            label="LTL mock minimum charge (USD)",
            value=min_c,
            unit="usd_flat",
            applies_to_party=applies,
            source="code:unie_cortex.network.ltl_mock:mock_ltl_quote_usd",
        ),
        _cf(
            key="ltl_mock.per_lb_usd",
            label="LTL mock weight line ($/lb)",
            value=per_lb,
            unit="usd_per_lb",
            applies_to_party=applies,
            source="code:unie_cortex.network.ltl_mock:mock_ltl_quote_usd",
        ),
        _cf(
            key="ltl_mock.per_pallet_slot_usd",
            label="LTL mock space line ($/pallet slot)",
            value=per_slot,
            unit="usd_flat",
            applies_to_party=applies,
            source="code:unie_cortex.network.ltl_mock:mock_ltl_quote_usd",
        ),
        _cf(
            key="reference_pallet.dims_in",
            label="Reference pallet dims (L×W×H in)",
            value=f"{REFERENCE_PALLET_LENGTH_IN}×{REFERENCE_PALLET_WIDTH_IN}×{REFERENCE_PALLET_HEIGHT_IN}",
            unit="string",
            applies_to_party=applies,
            source="code:unie_cortex.network.pallet_defaults",
        ),
        _cf(
            key="reference_pallet.cuft",
            label="Reference pallet slot (cu ft)",
            value=round(slot, 4),
            unit="cuft",
            applies_to_party=applies,
            source="code:unie_cortex.network.pallet_defaults:reference_pallet_cuft",
        ),
        _cf(
            key="network_consolidated_linehaul_cost_multiplier",
            label="Consolidated path linehaul multiplier (settings)",
            value=float(cfg.network_consolidated_linehaul_cost_multiplier),
            unit="multiplier",
            applies_to_party=applies,
            source="settings:NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER",
        ),
    ]


def _freight_broker_seeds(cfg: Settings) -> list[dict[str, Any]]:
    shared = _ltl_default_cost_fields(cfg, "freight_broker")
    seeds = [
        {
            "id": "mock_broker_atlantic",
            "name": "Mock Broker — Atlantic Lanes",
            "notes": "Synthetic seed; uses Cortex LTL mock + consolidated multiplier until DB contracts exist.",
        },
        {
            "id": "mock_broker_central",
            "name": "Mock Broker — Central US",
            "notes": "Synthetic seed; same underlying mock_ltl_quote_usd parameters as other seeds in v1.",
        },
        {
            "id": "mock_broker_pacific",
            "name": "Mock Broker — Pacific",
            "notes": "Synthetic seed; scenario compare-v2 applies these mocks on consolidated legs.",
        },
        {
            "id": "mock_broker_crossborder",
            "name": "Mock Broker — Cross-border (planning)",
            "notes": "Placeholder narrative; dollar math still mock_ltl_quote_usd in this release.",
        },
    ]
    return [{**s, "cost_fields": list(shared)} for s in seeds]


def _linehaul_fleet_rows(cfg: Settings) -> list[dict[str, Any]]:
    shared_ltl = _ltl_default_cost_fields(cfg, "linehaul_fleet")
    ref_dollar = _cf(
        key="linehaul_dollar_model",
        label="Where linehaul USD is computed",
        value="mock_ltl_quote_usd + compare_scenario_v2 / order_financial_planning integrated compare",
        unit="string",
        applies_to_party="linehaul_fleet",
        source="code:unie_cortex.network.ltl_mock + unie_cortex.network.scenarios_v2",
    )
    out = []
    for t in list_mock_tractors():
        row = dict(t)
        cfs = list(shared_ltl)
        cfs.append(ref_dollar)
        cfs.extend(
            [
                _cf(
                    key="mock_trailer_max_weight_lb",
                    label="Trailer max weight (mock)",
                    value=row.get("mock_trailer_max_weight_lb"),
                    unit="capacity_lb",
                    applies_to_party="linehaul_fleet",
                    source="code:unie_cortex.network.tms_fleet_mocks:list_mock_tractors",
                ),
                _cf(
                    key="mock_available_weight_lb",
                    label="Available weight slack (mock)",
                    value=row.get("mock_available_weight_lb"),
                    unit="capacity_lb",
                    applies_to_party="linehaul_fleet",
                    source="code:unie_cortex.network.tms_fleet_mocks:list_mock_tractors",
                ),
                _cf(
                    key="mock_trailer_max_cube_cuft",
                    label="Trailer max cube (mock)",
                    value=row.get("mock_trailer_max_cube_cuft"),
                    unit="capacity_cuft",
                    applies_to_party="linehaul_fleet",
                    source="code:unie_cortex.network.tms_fleet_mocks:list_mock_tractors",
                ),
                _cf(
                    key="mock_available_cube_cuft",
                    label="Available cube slack (mock)",
                    value=row.get("mock_available_cube_cuft"),
                    unit="capacity_cuft",
                    applies_to_party="linehaul_fleet",
                    source="code:unie_cortex.network.tms_fleet_mocks:list_mock_tractors",
                ),
            ]
        )
        row["cost_fields"] = cfs
        out.append(row)
    return out


def _warehouse_rows(cfg: Settings) -> list[dict[str, Any]]:
    ref = build_mock_network_reference()
    shared = _shared_warehouse_cost_fields(cfg)
    rows: list[dict[str, Any]] = []

    baseline = ref.get("audit_baseline") or {}
    cands = baseline.get("candidate_warehouses")
    if isinstance(cands, list):
        for w in cands:
            if not isinstance(w, dict):
                continue
            wid = str(w.get("id") or "").strip() or "unknown"
            rows.append(
                {
                    "id": wid,
                    "postal": str(w.get("postal") or "").strip(),
                    "label": str(w.get("label") or wid),
                    "source": "audit_baseline",
                    "cost_fields": list(shared),
                }
            )

    blitz = (ref.get("blitz_script_defaults") or {}).get("multi_dc_preview") or {}
    whs = blitz.get("warehouses") if isinstance(blitz.get("warehouses"), list) else []
    for w in whs:
        if not isinstance(w, dict):
            continue
        wid = str(w.get("id") or "").strip()
        rows.append(
            {
                "id": wid,
                "postal": "",
                "label": f"Blitz multi-dc preview — {wid}",
                "source": "blitz_preview",
                "lat": w.get("lat"),
                "lon": w.get("lon"),
                "daily_outbound_cuft": w.get("daily_outbound_cuft"),
                "cost_fields": list(shared),
            }
        )

    cv2 = (ref.get("blitz_script_defaults") or {}).get("compare_v2_scenario") or {}
    for o in cv2.get("origins") or []:
        if not isinstance(o, dict):
            continue
        rows.append(
            {
                "id": str(o.get("warehouse_id") or "origin"),
                "postal": str(o.get("postal") or "").strip(),
                "label": "Blitz compare-v2 origin node",
                "source": "blitz_compare_origin",
                "cost_fields": list(shared),
            }
        )
    for r in cv2.get("receive_nodes") or []:
        if not isinstance(r, dict):
            continue
        rows.append(
            {
                "id": str(r.get("warehouse_id") or "receive"),
                "postal": str(r.get("postal") or "").strip(),
                "label": "Blitz compare-v2 receive node",
                "source": "blitz_compare_receive",
                "cost_fields": list(shared),
            }
        )

    return rows


def build_intelligence_mock_registry(cfg: Settings | None = None) -> dict[str, Any]:
    cfg = cfg or default_settings
    economics_block = {
        "cost_fields": _economics_defaults_cost_fields(cfg),
        "pricing_profile_rate_card_preview": _default_profile_rate_cost_fields(cfg),
    }
    return {
        "schema_version": "intelligence_mock_registry_v1",
        "cost_schema_version": "cost_fields_v1",
        "economics_defaults": economics_block,
        "warehouses": _warehouse_rows(cfg),
        "parcel_carriers": [_parcel_carrier_row(c, cfg) for c in list_supported_carriers()],
        "freight_brokers": _freight_broker_seeds(cfg),
        "linehaul_fleet": _linehaul_fleet_rows(cfg),
        "api_hints": {
            **(build_mock_network_reference().get("api_hints") or {}),
            "intelligence_mock_registry": "GET /v1/network/intelligence-mock-registry",
        },
    }
