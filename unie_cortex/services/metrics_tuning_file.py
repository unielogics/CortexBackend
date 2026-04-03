"""Append-only local JSONL for AI / planning metrics while KPI schema is still tuning."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METRICS_TUNING_SCHEMA = "planning_run_metrics_tuning_v1"


def _default_jsonl_path() -> Path:
    # .../CortexBackend/unie_cortex/services/metrics_tuning_file.py -> repo root
    here = Path(__file__).resolve()
    cortex_backend = here.parent.parent.parent
    repo_root = cortex_backend.parent
    return repo_root / "data" / "metrics_tuning" / "planning_runs.jsonl"


def metrics_tuning_jsonl_path() -> Path:
    override = (os.environ.get("UNIE_METRICS_TUNING_PATH") or "").strip()
    if override:
        return Path(override)
    return _default_jsonl_path()


def metrics_tuning_enabled() -> bool:
    v = (os.environ.get("UNIE_METRICS_TUNING_FILE") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def append_metrics_tuning_record(
    *,
    engagement_id: str,
    payload: dict[str, Any],
    run_id: str | None = None,
) -> None:
    """
    Append one JSON line. No DB; safe for evolving ``payload`` (additive fields).
    Disabled when ``UNIE_METRICS_TUNING_FILE`` is 0/false/no/off.
    """
    if not metrics_tuning_enabled():
        return
    path = metrics_tuning_jsonl_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": METRICS_TUNING_SCHEMA,
        "engagement_id": engagement_id,
        "run_id": run_id,
        "payload": payload,
    }
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except OSError:
        pass
