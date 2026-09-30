"""Phase 6 — final integration checks: per-request graph reuse, fallbacks, error handling, no credential leakage.
TEST-ONLY fixture data in an in-memory database."""
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph_fakes import make_db, seed_case

from app.db.session import get_db
from app.deps import get_current_user
from app.routers import automation as automation_router, copilot as copilot_router, graph as graph_router, ml as ml_router
from app.services import case_automation as ca, graph_sync, ml_intelligence as ml
from app.services.neo4j_service import Neo4jService, set_neo4j_service


def _client(db, user):
    app = FastAPI()
    for r in (automation_router.router, ml_router.router, copilot_router.router, graph_router.router, graph_router.health_router):
        app.include_router(r)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def two_cases():
    db = make_db()
    a = seed_case(db, "A")
    b = seed_case(db, "B", owner=a["user"])
    return db, a, b


def _count_loads(monkeypatch):
    calls = []
    real = graph_sync.load_graph

    def counting(incident, db, **kw):
        calls.append(incident.id)
        return real(incident, db, **kw)

    monkeypatch.setattr(graph_sync, "load_graph", counting)
    return calls


def test_graph_is_built_once_per_investigation_per_request(two_cases, monkeypatch):
    db, a, b = two_cases
    calls = _count_loads(monkeypatch)
    s = ca.build_summary(a["incident"], db)
    assert sorted(calls) == sorted([a["incident"].id, b["incident"].id])          # was 6 loads before the Phase 6 fix
    calls.clear()
    ml.run_all(a["incident"], db)
    assert sorted(calls) == sorted([a["incident"].id, b["incident"].id])
    calls.clear()
    ca.build_report(a["incident"], db, summary=s)
    assert calls == [a["incident"].id]


def test_memo_does_not_leak_between_requests(two_cases, monkeypatch):
    db, a, _ = two_cases
    calls = _count_loads(monkeypatch)
    ca.build_summary(a["incident"], db)
    ca.build_summary(a["incident"], db)
    assert calls.count(a["incident"].id) == 2                                    # fresh graph each request (never stale)
    assert ml._GRAPH_MEMO.get() is None


def test_export_and_alert_draft_build_the_graph_once(two_cases, monkeypatch):
    db, a, b = two_cases
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    try:
        calls = _count_loads(monkeypatch)
        cl = _client(db, a["user"])
        assert cl.get(f"/incidents/{a['incident'].id}/automation/export").status_code == 200
        assert calls.count(a["incident"].id) == 1
        calls.clear()
        assert cl.post(f"/incidents/{a['incident'].id}/automation/alert-drafts").status_code == 201
        assert calls.count(a["incident"].id) == 1
    finally:
        set_neo4j_service(None)


def test_everything_works_with_neo4j_unreachable(two_cases):
    db, a, _ = two_cases
    set_neo4j_service(Neo4jService("bolt://127.0.0.1:1", "neo4j", "wrong", "neo4j", connect_timeout=1, retry_seconds=60))
    try:
        cl = _client(db, a["user"])
        base = f"/incidents/{a['incident'].id}"
        assert cl.get("/graph/health").json()["status"] == "fallback"
        assert cl.get(f"{base}/graph").json()["graph_source"]["backend"] == "memory"
        assert cl.post(f"{base}/copilot", json={"question": "What is the propagation path and what evidence supports it?"}).status_code == 200
        for path in ("/ml", "/automation/summary", "/automation/timeline", "/automation/gaps"):
            assert cl.get(base + path).status_code == 200, path
        assert cl.post(f"{base}/automation/reports").status_code == 201
    finally:
        set_neo4j_service(None)


def test_no_credentials_in_health_or_graph_responses(two_cases):
    db, a, _ = two_cases
    set_neo4j_service(Neo4jService("bolt://neo4j:S3cretPw@127.0.0.1:1", "neo4j", "S3cretPw", "neo4j", connect_timeout=1, retry_seconds=60))
    try:
        cl = _client(db, a["user"])
        blob = json.dumps(cl.get("/graph/health").json()) + json.dumps(cl.get(f"/incidents/{a['incident'].id}/graph").json())
        assert "S3cretPw" not in blob
    finally:
        set_neo4j_service(None)


def test_pdf_failure_returns_a_clear_error_without_internals(two_cases):
    db, a, _ = two_cases
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    try:
        cl = _client(db, a["user"])
        rid = cl.post(f"/incidents/{a['incident'].id}/automation/reports").json()["id"]
        with patch.object(automation_router, "render_investigation_report_pdf", side_effect=RuntimeError("font table corrupt at /secret/path")):
            r = cl.get(f"/incidents/{a['incident'].id}/automation/reports/{rid}/pdf")
            e = cl.get(f"/incidents/{a['incident'].id}/automation/export?format=pdf")
        assert r.status_code == 500 and r.json()["detail"].startswith("PDF generation failed")
        assert "secret" not in r.text and "Traceback" not in r.text
        assert e.status_code == 500 and "JSON export is still available" in e.json()["detail"]
    finally:
        set_neo4j_service(None)


def test_copilot_propagation_question_keeps_categories(two_cases):
    db, a, _ = two_cases
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    try:
        out = _client(db, a["user"]).post(f"/incidents/{a['incident'].id}/copilot",
                                          json={"question": "What is the propagation path and what evidence supports it?"}).json()
        assert out["llm"]["used"] is False and out["answer_source"] == "deterministic"
        statuses = {f["status"] for f in out["verified_facts"]}
        assert "inferred" not in statuses and "unknown" not in statuses
        assert any(f["status"] == "inferred" for f in out["inferences"]) and any(f["status"] == "unknown" for f in out["unknowns"])
        assert out["evidence_used"] and all(e["code"].startswith("EV-") for e in out["evidence_used"])
    finally:
        set_neo4j_service(None)
