"""Distribution impact rows from allocation output."""

from unie_cortex.services.distribution_impact import (
    SCHEMA_VERSION,
    build_distribution_envelope,
    build_distribution_impact_rows,
    write_distribution_local_file,
)


def test_build_distribution_impact_one_sku_two_warehouses_hub_leg():
    allocation = {
        "status": "complete",
        "lines": [
            {
                "sku": "A",
                "placement": [
                    {"warehouse_id": "H", "recommended_monthly_units": 220},
                    {"warehouse_id": "S", "recommended_monthly_units": 180},
                ],
                "transfer_from_hub": [
                    {
                        "from_warehouse_id": "H",
                        "to_warehouse_id": "S",
                        "units": 180,
                        "monthly_flow_units": 180,
                    }
                ],
            }
        ],
    }
    warehouses = [
        {"id": "H", "postal": "10001", "display_name": "Hub East"},
        {"id": "S", "postal": "90001"},
    ]
    rows = build_distribution_impact_rows(job_id="job-1", allocation=allocation, warehouses=warehouses)
    wh = {r["party_id"]: r for r in rows if r["party_type"] == "warehouse"}
    assert wh["H"]["estimate_monthly_units"] == 220
    assert wh["H"]["party_name"] == "Hub East"
    assert wh["S"]["party_name"] == "S"
    assert wh["S"]["estimate_monthly_units"] == 180
    fr = [r for r in rows if r["party_type"] == "freight"]
    assert len(fr) == 1
    assert fr[0]["party_id"] == "H→S"
    assert fr[0]["estimate_monthly_units"] == 180
    assert all(r["job_id"] == "job-1" for r in rows)


def test_build_distribution_skipped_empty_rows():
    rows = build_distribution_impact_rows(
        job_id="j2",
        allocation={"status": "skipped", "lines": []},
        warehouses=[{"id": "A"}],
    )
    assert rows == []


def test_build_distribution_envelope():
    env = build_distribution_envelope(
        job_id="x",
        tenant_id="t1",
        operational_warehouse_id="w0",
        engagement_id="e99",
        rows=[],
    )
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["job_id"] == "x"
    assert env["rows"] == []


def test_write_distribution_local_file_writes_json(tmp_path):
    env = build_distribution_envelope(
        job_id="abc-123",
        tenant_id="t",
        operational_warehouse_id="w",
        engagement_id=None,
        rows=[
            {
                "job_id": "abc-123",
                "party_type": "warehouse",
                "party_id": "W1",
                "party_name": "W1",
                "estimate_monthly_units": 10,
            }
        ],
    )
    path = write_distribution_local_file(str(tmp_path), env, saved_at_iso="2026-01-01T00:00:00+00:00")
    assert path is not None
    assert path.endswith(".json")
    text = __import__("pathlib").Path(path).read_text(encoding="utf-8")
    assert "abc-123" in text
    assert "estimate_monthly_units" in text
    assert "2026-01-01T00:00:00+00:00" in text


def test_write_distribution_local_file_empty_dir_returns_none():
    assert write_distribution_local_file("", build_distribution_envelope(job_id="j", tenant_id="t", operational_warehouse_id="w", engagement_id=None, rows=[])) is None
