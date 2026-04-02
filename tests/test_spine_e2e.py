"""E2E against in-process app (uses ./unie_cortex.db or env DATABASE_URL)."""

from fastapi.testclient import TestClient

from unie_cortex.main import app


def test_health():
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.json()["status"] == "ok"


def test_assessment_upload_and_run():
    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "pytest"}).json()
        eid = e["engagement_id"]
        c.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={
                "mappings": {
                    "labels": {
                        "Track": "tracking_number",
                        "Amt": "label_amount_usd",
                        "Wt": "weight_lb",
                        "To": "dest_postal",
                        "Car": "carrier",
                    }
                }
            },
        )
        csv = "Track,Amt,Wt,To,Car\nT1,15.2,3.1,10001,UPS\nT2,8.0,1.0,90210,FedEx\n"
        up = c.post(
            f"/v1/assessment/engagements/{eid}/upload?kind=labels",
            files={"file": ("s.csv", csv, "text/csv")},
        )
        assert up.status_code == 200, up.text
        run = c.post(f"/v1/assessment/engagements/{eid}/runs").json()
        rep = c.get(
            f"/v1/assessment/engagements/{eid}/runs/{run['run_id']}/report"
        ).json()
        assert rep["label_cost"]["status"] == "complete"
        assert rep["label_cost"].get("row_count", 0) >= 1


def test_operational_facts_and_draft():
    with TestClient(app) as c:
        c.post(
            "/v1/operational/t1/w1/facts/labels",
            json={
                "facts": [
                    {
                        "tracking_number": "X",
                        "label_amount_usd": 20,
                        "weight_lb": 5,
                        "dest_postal": "33101",
                        "carrier": "UPS",
                    }
                ]
            },
        )
        rec = c.post(
            "/v1/operational/recommendations/draft",
            json={
                "tenant_id": "t1",
                "warehouse_id": "w1",
                "mappings_labels": {
                    "x": "tracking_number",
                    "a": "label_amount_usd",
                    "w": "weight_lb",
                    "d": "dest_postal",
                },
                "mappings_tasks": {},
            },
        )
        assert rec.status_code == 200
        assert rec.json()["status"] == "pending"


def test_maiw_query_assessment():
    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "maiw-test"}).json()
        eid = e["engagement_id"]
        c.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={
                "mappings": {
                    "labels": {
                        "Track": "tracking_number",
                        "Amt": "label_amount_usd",
                        "Wt": "weight_lb",
                        "To": "dest_postal",
                        "Car": "carrier",
                    }
                }
            },
        )
        csv = "Track,Amt,Wt,To,Car\nT1,15.2,3.1,10001,UPS\n"
        c.post(
            f"/v1/assessment/engagements/{eid}/upload?kind=labels",
            files={"file": ("s.csv", csv, "text/csv")},
        )
        c.post(f"/v1/assessment/engagements/{eid}/runs")
        r = c.post(
            "/v1/maiw/query",
            json={"question": "What are the main findings?", "engagement_id": eid},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["answer"]
        assert j["context_run_id"]
        assert j.get("integrations") and "tools_run" in j["integrations"]


def test_maiw_proposal_before_after_approve():
    with TestClient(app) as c:
        c.post(
            "/v1/operational/t1/w1/facts/labels",
            json={
                "facts": [
                    {
                        "tracking_number": "P1",
                        "label_amount_usd": 18,
                        "weight_lb": 4,
                        "dest_postal": "33101",
                        "carrier": "UPS",
                    }
                ]
            },
        )
        c.post(
            "/v1/operational/t1/w1/facts/tasks",
            json={"facts": [{"completed_at": "2025-01-01T10:00", "zone": "A"}]},
        )
        d = c.post(
            "/v1/maiw/proposals/draft",
            json={
                "tenant_id": "t1",
                "warehouse_id": "w1",
                "mappings_labels": {
                    "t": "tracking_number",
                    "a": "label_amount_usd",
                    "w": "weight_lb",
                    "d": "dest_postal",
                    "c": "carrier",
                },
                "mappings_tasks": {"ts": "completed_at", "z": "zone"},
            },
        )
        assert d.status_code == 200, d.text
        j = d.json()
        assert "before" in j and "after" in j
        assert j["after"].get("routing") and j["after"].get("auto_tasks")
        assert j["status"] == "pending"
        pid = j["proposal_id"]
        c.post(f"/v1/maiw/proposals/{pid}/approve", json={"note": "GM approved"})
        g = c.get(f"/v1/maiw/proposals/{pid}")
        assert g.json()["status"] == "approved"


def test_integrations_rate_quote():
    with TestClient(app) as c:
        r = c.post(
            "/v1/integrations/rate-quote",
            json={"weight_lb": 5, "origin_postal": "10001", "dest_postal": "90210"},
        )
        assert r.status_code == 200
        assert "primary_usd" in r.json()


def test_multi_dc_preview():
    with TestClient(app) as c:
        r = c.post(
            "/v1/assessment/multi-dc-preview",
            json={
                "warehouses": [{"id": "A", "lat": 40, "lon": -74}],
                "lanes": [{"from_id": "A", "to_id": "B", "utilization_pct": 40}],
            },
        ).json()
        assert r["status"] in ("heuristic", "complete", "skipped", "error")


def test_multi_dc_preview_allow_nvidia_false_is_internal_baseline():
    with TestClient(app) as c:
        r = c.post(
            "/v1/assessment/multi-dc-preview",
            json={
                "warehouses": [{"id": "A", "lat": 40, "lon": -74}],
                "lanes": [{"from_id": "A", "to_id": "B", "utilization_pct": 40}],
                "allow_nvidia_enhancements": False,
            },
        )
        assert r.status_code == 200
        j = r.json()
        assert j["status"] == "heuristic"
        assert j["source"] == "internal"


def test_integrations_capabilities():
    """Smoke: capabilities endpoint returns configured backends (no auth required)."""
    with TestClient(app) as c:
        r = c.get("/v1/integrations/capabilities")
        assert r.status_code == 200
        j = r.json()
        assert "geoapify" in j
        assert "keepa" in j
        assert "shippo" in j


def test_maiw_proposal_deny():
    """MAIW proposal deny flow."""
    with TestClient(app) as c:
        c.post(
            "/v1/operational/t1/w1/facts/labels",
            json={
                "facts": [
                    {
                        "tracking_number": "D1",
                        "label_amount_usd": 12,
                        "weight_lb": 2,
                        "dest_postal": "10001",
                        "carrier": "FedEx",
                    }
                ]
            },
        )
        d = c.post(
            "/v1/maiw/proposals/draft",
            json={
                "tenant_id": "t1",
                "warehouse_id": "w1",
                "mappings_labels": {
                    "t": "tracking_number",
                    "a": "label_amount_usd",
                    "w": "weight_lb",
                    "d": "dest_postal",
                    "c": "carrier",
                },
                "mappings_tasks": {},
            },
        )
        assert d.status_code == 200
        pid = d.json()["proposal_id"]
        deny = c.post(
            f"/v1/maiw/proposals/{pid}/deny",
            json={"reason": "Not approved for this cycle"},
        )
        assert deny.status_code == 200
        assert deny.json()["status"] == "denied"
        g = c.get(f"/v1/maiw/proposals/{pid}")
        assert g.json()["status"] == "denied"


def test_health_deps():
    """Health deps endpoint returns database status."""
    with TestClient(app) as c:
        r = c.get("/health/deps")
        assert r.status_code == 200
        j = r.json()
        assert "status" in j
        assert "dependencies" in j
        assert j["dependencies"]["database"] in ("sql", "mongodb")


def test_item_intelligence_catalog_and_run():
    """Catalog CRUD, label facts with SKU, item-intelligence artifact (Keepa may fail without key)."""
    with TestClient(app) as c:
        tid, wid = "it_t1", "it_w1"
        up = c.put(
            f"/v1/operational/{tid}/catalog/items",
            json={
                "sku": "SKU-A",
                "asin": "B012345678",
                "weight_lb": 2.0,
                "length_in": 10,
                "width_in": 8,
                "height_in": 6,
            },
        )
        assert up.status_code == 200
        sig_a = up.json()["physical_signature"]
        up2 = c.put(
            f"/v1/operational/{tid}/catalog/items",
            json={
                "sku": "SKU-B",
                "weight_lb": 2.0,
                "length_in": 10,
                "width_in": 8,
                "height_in": 6,
            },
        )
        assert up2.status_code == 200
        assert up2.json()["physical_signature"] == sig_a
        c.post(
            f"/v1/operational/{tid}/{wid}/facts/labels",
            json={
                "facts": [
                    {
                        "sku": "SKU-A",
                        "tracking_number": "IT1",
                        "label_amount_usd": 11.0,
                        "weight_lb": 2.0,
                        "dest_postal": "10001",
                        "carrier": "UPS",
                    }
                ]
            },
        )
        run = c.post(
            f"/v1/operational/{tid}/{wid}/item-intelligence/run",
            json={
                "warehouses": [{"id": wid, "target_share_pct": 60}, {"id": "it_w2", "target_share_pct": 40}],
                "lanes": [{"from_id": wid, "to_id": "it_w2", "cost_per_lb": 0.2}],
                "hub_warehouse_id": wid,
                "include_product_research_economics": True,
                "product_research_include_sp_api_fees": False,
                "product_research_outputs": [
                    "original",
                    "ours",
                    "ours_plus_nvidia_enhancements",
                    "nvidia_only",
                ],
            },
        )
        assert run.status_code == 200
        j = run.json()
        tri = j.get("multi_dc_placement_tri_modal")
        assert tri is not None
        assert tri.get("schema_version") == "item_intelligence_multi_dc_tri_modal_v1"
        assert "original_input" in tri
        assert "baseline_without_nvidia" in tri
        assert tri["baseline_without_nvidia"].get("source") == "internal"
        assert "nvidia_enhanced" in tri
        pre = j.get("product_research_economics")
        assert pre is not None
        assert pre.get("schema_version") == "product_research_economics_v1"
        po = pre["outputs"]
        assert po["original"] is not None
        assert po["ours"] is not None
        assert po["ours_plus_nvidia_enhancements"] is not None
        assert po["nvidia_only"] is not None
        assert "optimization_enrichment" not in po["ours"]
        assert po["ours_plus_nvidia_enhancements"].get("optimization_enrichment") is not None
        assert po["nvidia_only"].get("fingerprint_of_ours", "").startswith("sha256:")
        assert po["ours"].get("fba_prep_services_breakdown", {}).get("network_model") == "single_warehouse_operational"
        assert po["nvidia_only"].get("nvidia_parallel_narrative", {}).get("purpose") == "comparison_ui_only"
        assert j["velocity"]["sku_count"] >= 1
        assert "SKU-A" in j["sku_shipping_merged"]
        b_merge = j["sku_shipping_merged"]["SKU-B"]
        assert b_merge["provenance"]["source"] in ("blended_physical_twin", "own_only")
        lst = c.get(f"/v1/operational/{tid}/catalog/items")
        assert lst.status_code == 200
        assert len(lst.json()["items"]) >= 2


def test_sku_velocity_in_audit_spine():
    """Spine includes sku_velocity when label mapping includes sku."""
    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "skuvel"}).json()
        eid = e["engagement_id"]
        c.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={
                "mappings": {
                    "labels": {
                        "Track": "tracking_number",
                        "Amt": "label_amount_usd",
                        "Wt": "weight_lb",
                        "To": "dest_postal",
                        "Car": "carrier",
                        "SKU": "sku",
                    }
                }
            },
        )
        csv = "Track,Amt,Wt,To,Car,SKU\nT1,15.2,3.1,10001,UPS,SK1\n"
        c.post(
            f"/v1/assessment/engagements/{eid}/upload?kind=labels",
            files={"file": ("s.csv", csv, "text/csv")},
        )
        run = c.post(f"/v1/assessment/engagements/{eid}/runs").json()
        rep = c.get(f"/v1/assessment/engagements/{eid}/runs/{run['run_id']}/report").json()
        assert rep.get("sku_velocity", {}).get("status") == "complete"
        assert rep.get("sku_velocity", {}).get("sku_count", 0) >= 1

def test_assessment_audit_synthesis_endpoint():
    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "audit_syn"}).json()
        eid = e["engagement_id"]
        c.put(
            f"/v1/assessment/engagements/{eid}/column-mapping",
            json={
                "mappings": {
                    "labels": {
                        "Track": "tracking_number",
                        "Amt": "label_amount_usd",
                        "Wt": "weight_lb",
                        "To": "dest_postal",
                        "Car": "carrier",
                    }
                }
            },
        )
        csv = "Track,Amt,Wt,To,Car\nT1,15.2,3.1,10001,UPS\n"
        c.post(
            f"/v1/assessment/engagements/{eid}/upload?kind=labels",
            files={"file": ("s.csv", csv, "text/csv")},
        )
        r = c.post(f"/v1/assessment/engagements/{eid}/audit-synthesis", json={})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("schema_version") == "audit_outcome_v2"
        assert "backbone_completeness" in j
        assert "competitive_kpis" in j
        assert "data_quality" in j
        assert "grain" in j["data_quality"]


def test_infer_mapping_nim_labels_heuristic():
    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "nim_map"}).json()
        eid = e["engagement_id"]
        r = c.post(
            f"/v1/assessment/engagements/{eid}/infer-mapping-nim",
            json={
                "kind": "labels",
                "headers": ["Tracking", "ShipCost", "Lb", "Zip", "Carrier"],
                "sample_rows": [{"Tracking": "1", "ShipCost": "10", "Lb": "2", "Zip": "10001", "Carrier": "UPS"}],
            },
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("source") in ("heuristic", "nim", "merged")
        assert "mappings" in j
