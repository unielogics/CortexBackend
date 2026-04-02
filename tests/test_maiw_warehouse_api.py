"""Warehouse Intelligence API — four-variant proposals, persistence, metrics, outcomes."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from unie_cortex.main import app

_FIX = Path(__file__).resolve().parent / "fixtures" / "maiw_warehouse"


def _load(name: str) -> dict:
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def test_batch_optimize_returns_four_variants_and_persists():
    body = _load("batch_pick_layout_graph.json")
    with TestClient(app) as c:
        r = c.post("/v1/pick-pathing/batch-optimize", json=body)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("schemaVersion")
        pid = j["proposalId"]
        assert j["capability"] == "batch_pick_path"
        fv = j["fourVariants"]
        for k in ("original", "internal", "internalPlusNvidia", "nvidiaFromScratch"):
            assert k in fv
            assert "status" in fv[k]
        gr = c.get(f"/v1/proposals/{pid}")
        assert gr.status_code == 200
        assert gr.json()["proposalId"] == pid


def test_prioritize_fixture_rich_payload():
    body = _load("prioritize_queue_rich.json")
    with TestClient(app) as c:
        r = c.post("/v1/uniewms/execution/prioritize-queue", json=body)
        assert r.status_code == 200, r.text
        ordered = r.json()["fourVariants"]["internal"]["payload"]["orderedJobIds"]
        assert isinstance(ordered, list) and len(ordered) == 2


def test_approve_deny_metrics_outcomes_flow():
    body = {
        "meta": {"tenantId": "t-metrics", "warehouseId": "w1"},
        "nowIso": "2026-03-28T12:00:00Z",
        "employees": [
            {
                "employeeId": "e1",
                "tasksPerHourHistorical": 40,
                "checkInSessions": [{"platform": "dashboard", "sessionStartedAt": "2026-03-28T08:00:00Z"}],
            }
        ],
        "pendingTaskCount": 10,
    }
    with TestClient(app) as c:
        r = c.post("/v1/labor/capacity-forecast", json=body)
        assert r.status_code == 200
        pid = r.json()["proposalId"]
        r2 = c.post(
            f"/v1/proposals/{pid}/approve",
            json={"chosenVariant": "internal", "note": "use internal"},
        )
        assert r2.status_code == 200
        m = c.get("/v1/metrics/acceptance", params={"tenantId": "t-metrics"})
        assert m.status_code == 200
        mj = m.json()
        assert mj["approved"] >= 1
        out = c.post(
            "/v1/intelligence/outcomes",
            json={
                "proposalId": pid,
                "startedAt": "2026-03-28T08:00:00Z",
                "completedAt": "2026-03-28T09:00:00Z",
                "assigneeId": "e1",
            },
        )
        assert out.status_code == 200
        assert out.json().get("outcomeId")


def test_outcome_404_without_proposal():
    with TestClient(app) as c:
        r = c.post(
            "/v1/intelligence/outcomes",
            json={"proposalId": "00000000-0000-4000-8000-000000000000"},
        )
        assert r.status_code == 404


def test_labor_fixture_loads():
    body = _load("labor_capacity_rich.json")
    with TestClient(app) as c:
        r = c.post("/v1/labor/capacity-forecast", json=body)
        assert r.status_code == 200
        assert "expectedTasksRemainingShift" in r.json()["fourVariants"]["internal"]["payload"]
