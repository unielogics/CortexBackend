"""NIM-assisted CSV column mapping with deterministic baseline and strict validation."""

from __future__ import annotations

import json
import re
from typing import Any


from unie_cortex.config import Settings
from unie_cortex.integrations.nim_chat import nim_post_chat_completions
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


def _extract_json_object(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    m2 = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", t)
    if m2:
        t = m2.group(1)
    else:
        m = re.search(r"\{[\s\S]*\}", t)
        if not m:
            return None
        t = m.group(0)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


async def call_nim_for_mapping(
    settings: Settings,
    *,
    kind: str,
    allowed: set[str],
    headers: list[str],
    sample_rows_redacted: list[dict[str, Any]],
    heuristic_block: dict[str, str],
    wms_hint: str | None,
    store=None,
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    key = settings.nvidia_api_key
    if not key:
        return {}
    system = (
        "You map CSV columns to canonical warehouse fields. Reply with JSON only: "
        '{"mappings":{"SourceHeader":"canonical_field",...}}. '
        "Use only canonical_field values from the allowed list. Do not invent fields. "
        "Do not echo PII; sample values are truncated."
    )
    user_obj = {
        "kind": kind,
        "allowed_canonical_fields": sorted(allowed),
        "headers": headers,
        "sample_rows": sample_rows_redacted,
        "heuristic_seed": heuristic_block,
        "wms_hint": (wms_hint or "").strip() or None,
    }
    user = json.dumps(user_obj, default=str)[:100000]
    out = await nim_post_chat_completions(
        settings,
        capability="csv_column_mapping",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=2048,
        store=store,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        run_id=run_id,
        extra={"kind": kind},
    )
    if out.source != "nim" or not out.content:
        return {}
    parsed = _extract_json_object(out.content)
    if not parsed:
        return {}
    block = parsed.get("mappings")
    if not isinstance(block, dict):
        return {}
    return {str(k): str(v) for k, v in block.items()}


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
    templates = templates or []
    allowed = _allowed_for_kind(kind)
    hset = {h for h in headers if h}
    heur_warnings: list[str] = []

    if kind == "labels":
        det = suggest_label_mapping_from_templates(headers, templates)
    elif kind == "tasks":
        det = infer_task_mapping(headers)
    else:
        inf = infer_order_financial_mapping(headers, sample_rows)
        det = dict(inf.get("proposed_mapping") or {})
        heur_warnings = list(inf.get("ambiguous_headers") or [])

    redacted = redact_sample_rows(sample_rows)
    nim_map: dict[str, str] = {}
    nim_on = bool(settings.nim_csv_mapping_enabled and settings.nvidia_api_key)
    if nim_on:
        nim_map = await call_nim_for_mapping(
            settings,
            kind=kind,
            allowed=allowed,
            headers=headers,
            sample_rows_redacted=redacted,
            heuristic_block=det,
            wms_hint=wms_hint,
            store=store,
            tenant_id=tenant_id,
            engagement_id=engagement_id,
            run_id=run_id,
        )

    merged, merge_warnings = merge_mappings(det, nim_map, allowed=allowed, headers=hset)

    if not nim_on or not nim_map:
        source = "heuristic"
    elif merged != det:
        source = "merged"
    else:
        source = "nim"

    mapped_sources = set(merged.keys())
    unmapped = [h for h in headers if h and h not in mapped_sources]

    return NimMappingResult(
        kind=kind,  # type: ignore[arg-type]
        mappings=merged,
        source=source,  # type: ignore[arg-type]
        warnings=heur_warnings + merge_warnings,
        unmapped_columns=unmapped,
    )
