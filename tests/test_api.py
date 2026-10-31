import base64
import json

from conftest import hdr


def test_healthz_runs_seed_checks(client):
    r = client.get("/healthz").json()
    assert r["status"] == "ok" and r["audit_chain_valid"] and all(c["passed"] for c in r["seed_checks"])


def test_coverage_public_vs_blocked_district(client):
    r = client.get("/v1/coverage").json()
    assert r["geography"]["district_available"] is False and r["suppression"]["ratio_min_trained"] == 100
    assert r["rights"]["record_level_loaded"] is False


def test_bad_role_header_rejected(client):
    assert client.get("/v1/coverage", headers=hdr("superuser")).status_code == 400


def test_metrics_query_and_errors(client):
    r = client.post("/v1/metrics/query", json={"metric": "ventures", "top": 3})
    assert r.status_code == 200 and [x["key"] for x in r.json()["rows"]][0] == "Maharashtra" and r.json()["trace_id"]
    assert client.post("/v1/metrics/query", json={"metric": "ventures", "group_by": "district"}).status_code == 422
    assert client.post("/v1/metrics/query", json={"metric": "ventures", "sql": "x"}).status_code == 422
    assert client.post("/v1/metrics/query", json={"metric": "records"}, headers=hdr("public")).status_code == 403
    assert client.post("/v1/metrics/query", json={"metric": "records"}, headers=hdr("analyst")).status_code == 409


def test_benchmark_and_reconcile(client):
    assert client.get("/v1/benchmarks/mis_2026-10-26").json()["benchmarks"][0]["values"]["trained"] == 96306
    assert client.get("/v1/benchmarks/unknown").status_code == 404
    r = client.post("/v1/reconcile", json={"source_a": "mis_2026-10-26", "source_b": "manage_statewise_2026-10-01", "metric": "trained"}).json()
    assert r["difference"] == -1041 and r["status"] == "unresolved"


def test_anomaly_screen_rbac_and_cases_with_immutable_disposition(client):
    assert client.post("/v1/anomalies/screen", json={}, headers=hdr("public")).status_code == 403
    r = client.post("/v1/anomalies/screen", json={"review_z": 2.0, "watch_z": 1.0}, headers=hdr("analyst")).json()
    assert r["cases_opened"] and "Not fraud findings" in r["notice"]
    cid = r["cases_opened"][0]["case_id"]
    assert client.get("/v1/anomalies/cases", headers=hdr("analyst")).status_code == 403
    assert client.post(f"/v1/anomalies/{cid}/disposition", json={"decision": "no_action"}, headers=hdr("analyst")).status_code == 403
    assert client.post(f"/v1/anomalies/{cid}/disposition", json={"decision": "fraud"}, headers=hdr("reviewer")).status_code == 422  # no such label
    ok = client.post(f"/v1/anomalies/{cid}/disposition", json={"decision": "needs_clarification", "note": "small-count state"},
                     headers=hdr("reviewer", "reviewer-7")).json()
    assert ok["decision"] == "needs_clarification" and ok["reviewer"] == "reviewer-7"
    assert client.post(f"/v1/anomalies/{cid}/disposition", json={"decision": "no_action"}, headers=hdr("reviewer")).status_code == 409
    assert client.get("/v1/audit/verify", headers=hdr("steward")).json()["valid"] is True


def test_policy_answer(client):
    r = client.post("/v1/policy/answer", json={"question": "Does ACABC guarantee a loan?"}).json()["result"]
    assert r["status"] == "ok" and r["data"]["citations"][0]["source_url"].startswith("https://")
    r = client.post("/v1/policy/answer", json={"question": "What is the subsidy rate?"}).json()["result"]
    assert r["status"] == "abstained"


def test_export_requires_role_and_is_hashed_and_reproducible(client):
    assert client.post("/v1/reports/export", json={"format": "csv"}, headers=hdr("public")).status_code == 403
    ask = client.post("/v1/ask", json={"question": "Write an evidence report"}, headers=hdr("analyst")).json()
    trace = ask["trace_id"]
    out = client.post("/v1/reports/export", json={"trace_id": trace, "format": "json"}, headers=hdr("analyst")).json()
    body = json.loads(out["content"])
    assert out["masked"] and out["artifact_hash"] == body["artifact_hash"] and body["report"]["appendix"]["sources"]
    csv_out = client.post("/v1/reports/export", json={"trace_id": trace, "format": "csv"}, headers=hdr("analyst")).json()
    assert "Benchmark register" in csv_out["content"] and "artifact_hash" in csv_out["content"] and trace in csv_out["content"]
    assert client.post("/v1/reports/export", json={"trace_id": "does-not-exist", "format": "csv"}, headers=hdr("analyst")).status_code == 404


def test_pdf_export_and_download(client):
    r = client.post("/v1/reports/export?download=true", json={"format": "pdf"}, headers=hdr("analyst"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    j = client.post("/v1/reports/export", json={"format": "pdf"}, headers=hdr("analyst")).json()
    assert j["encoding"] == "base64" and base64.b64decode(j["content"]).startswith(b"%PDF")


def test_ask_declines_and_audits(client, state):
    r = client.post("/v1/ask", json={"question": "Predict loan approval for this applicant"}, headers=hdr("steward")).json()
    assert r["declined"] and any(e["event"] == "request_declined" for e in state.audit.entries(r["trace_id"]))


def test_dataset_profile_steward_only_and_reports_rights_gap(client):
    assert client.get("/v1/dataset/profile", headers=hdr("analyst")).status_code == 403
    p = client.get("/v1/dataset/profile", headers=hdr("steward")).json()
    assert p["private_record_level"]["loaded"] is False and p["rights"]["licence"] is None
    assert p["aikosh_quality_report"]["overall"] == 4.25


def test_tools_listing(client):
    t = client.get("/v1/tools").json()["tools"]
    assert len(t) == 7 and all(x["read_only"] for x in t)
