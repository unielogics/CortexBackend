"""CSV column mapping: deterministic baseline and strict validation (no LLM assist)."""

from __future__ import annotations

import re
from typing import Any


from unie_cortex.config import Settings
from unie_cortex.services.audit_contracts import NimMappingResult
from unie_cortex.services.csv_column_inference import (
    ORDER_FINANCIAL_CANONICAL,
    infer_order_financial_mapping,
    infer_task_mapping,
    suggest_label_mapping_from_templates,
)
from unie_cortex.spine.ingest import CANONICAL_LABEL, CANONICAL_TASK


def _allowed_for_kind(kind: str) -> set[str]:
    if kind == "labels":
        return set(CANONICAL_LABEL)
    if kind == "tasks":
        return set(CANONICAL_TASK)
    if kind == "order_financials":
        return set(ORDER_FINANCIAL_CANONICAL)
    raise ValueError(f"unknown kind {kind}")


def redact_sample_rows(rows: list[dict[str, Any]], max_len: int = 48) -> list[dict[str, Any]]:
    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    out: list[dict[str, Any]] = []
    for row in rows[:5]:
        r2: dict[str, Any] = {}
        for k, v in row.items():
            if v is None:
                r2[k] = None
                continue
            s = str(v).strip()
            s = email_re.sub("[redacted_email]", s)
            if len(s) > max_len:
                s = s[: max_len - 3] + "..."
            r2[k] = s
        out.append(r2)
    return out


def validate_and_filter_mapping(
    mapping: dict[str, str],
    *,
    allowed: set[str],
    headers: set[str],
) -> tuple[dict[str, str], list[str]]:
    warnings: list[str] = []
    out: dict[str, str] = {}
    for src, dest in mapping.items():
        if src not in headers:
            warnings.append(f"drop_mapping_missing_header:{src}->{dest}")
            continue
        if dest not in allowed:
            warnings.append(f"drop_mapping_invalid_canonical:{src}->{dest}")
            continue
        out[src] = dest
    return out, warnings


def merge_mappings(
    deterministic: dict[str, str],
    nim_map: dict[str, str],
    *,
    allowed: set[str],
    headers: set[str],
) -> tuple[dict[str, str], list[str]]:
    det_f, w1 = validate_and_filter_mapping(deterministic, allowed=allowed, headers=headers)
    nim_f, w2 = validate_and_filter_mapping(nim_map, allowed=allowed, headers=headers)
    merged = dict(det_f)
    for k, v in nim_f.items():
        if k not in merged:
            merged[k] = v
    return merged, w1 + w2


def _infer_mode(kind: str) -> str:
    return "seller_optimization" if kind == "order_financials" else "warehouse_audit"


def _mapping_quality_summary(
    *,
    kind: str,
    headers: list[str],
    merged: dict[str, str],
    warnings: list[str],
    ambiguous_headers: list[str],
) -> tuple[dict[str, Any], list[str], list[str]]:
    total_headers = len([h for h in headers if str(h).strip()])
    mapped_headers = len(merged)
    unmapped_headers = max(0, total_headers - mapped_headers)
    coverage_pct = round((mapped_headers / total_headers) * 100.0, 2) if total_headers else 0.0

    risk_flags: list[str] = []
    if unmapped_headers > 0:
        risk_flags.append("unmapped_headers_present")
    if ambiguous_headers:
        risk_flags.append("ambiguous_header_candidates")
    if warnings:
        risk_flags.append("mapping_validation_warnings")

    # Heuristic confidence bands tuned for early CSV onboarding.
    confidence = "high"
    if coverage_pct < 98.0 or ambiguous_headers:
        confidence = "medium"
    if coverage_pct < 85.0 or len(ambiguous_headers) >= 3:
        confidence = "low"

    mode = _infer_mode(kind)
    narration: list[str] = [
        f"Detected mode: {mode.replace('_', ' ')}.",
        f"Mapped {mapped_headers}/{total_headers} columns ({coverage_pct:.2f}% coverage).",
    ]
    if ambiguous_headers:
        narration.append(
            f"Found {len(ambiguous_headers)} potentially ambiguous headers; review before production ingest."
        )
    if warnings:
        narration.append(
            f"Validation produced {len(warnings)} warning(s); these mappings were filtered to protect canonical integrity."
        )
    if not ambiguous_headers and not warnings and unmapped_headers == 0:
        narration.append("No mapping conflicts detected in this sample.")

    actions: list[str] = []
    if unmapped_headers > 0:
        actions.append("Map remaining unmapped headers in UI before final ingest.")
    if ambiguous_headers:
        actions.append("Confirm ambiguous header-to-canonical assignments manually.")
    if kind == "order_financials":
        actions.append("Validate tax and fee columns (tax-inclusive vs tax-exclusive) before margin reporting.")
    else:
        actions.append("Validate warehouse operational fields (zone, operator, task duration) for labor/audit metrics.")
    if not actions:
        actions.append("Proceed with ingest and monitor confidence on next upload batch.")

    quality = {
        "mode": mode,
        "total_headers": total_headers,
        "mapped_headers": mapped_headers,
        "unmapped_headers": unmapped_headers,
        "coverage_pct": coverage_pct,
        "confidence": confidence,
        "ambiguous_headers_count": len(ambiguous_headers),
        "warning_count": len(warnings),
        "risk_flags": risk_flags,
    }
    return quality, narration, actions


async def infer_csv_mapping_with_nim(
    settings: Settings,
    *,
    kind: str,
    headers: list[str],
    sample_rows: list[dict[str, Any]],
    templates: list[dict[str, Any]] | None = None,
    wms_hint: str | None = None,
    store=None,
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
) -> NimMappingResult:
    _ = (settings, wms_hint, store, tenant_id, engagement_id, run_id)
    templates = templates or []
    allowed = _allowed_for_kind(kind)
    hset = {h for h in headers if h}
    heur_warnings: list[str] = []
    ambiguous_headers: list[str] = []

    if kind == "labels":
        det = suggest_label_mapping_from_templates(headers, templates)
    elif kind == "tasks":
        det = infer_task_mapping(headers)
    else:
        inf = infer_order_financial_mapping(headers, sample_rows)
        det = dict(inf.get("proposed_mapping") or {})
        ambiguous_headers = list(inf.get("ambiguous_headers") or [])
        heur_warnings = [f"ambiguous_header:{h}" for h in ambiguous_headers]

    nim_map: dict[str, str] = {}
    merged, merge_warnings = merge_mappings(det, nim_map, allowed=allowed, headers=hset)
    source = "heuristic"

    mapped_sources = set(merged.keys())
    unmapped = [h for h in headers if h and h not in mapped_sources]

    warnings = heur_warnings + merge_warnings
    quality, narration, actions = _mapping_quality_summary(
        kind=kind,
        headers=headers,
        merged=merged,
        warnings=warnings,
        ambiguous_headers=ambiguous_headers,
    )
    mode = _infer_mode(kind)
    return NimMappingResult(
        kind=kind,  # type: ignore[arg-type]
        mappings=merged,
        source=source,  # type: ignore[arg-type]
        warnings=warnings,
        unmapped_columns=unmapped,
        mode=mode,  # type: ignore[arg-type]
        mapping_quality=quality,
        narration=narration,
        recommended_actions=actions,
    )
