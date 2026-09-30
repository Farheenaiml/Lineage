"""Phase 5 — Investigation Automation: summary, gaps, timeline, report, alert draft, workflow, audit, export.
Exercised through the real routers with an in-memory SQLite database. TEST-ONLY fixture data."""
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph_fakes import make_db, seed_case

from app.db.session import get_db
from app.deps import get_current_user
from app.models.automation import AuditEvent
from app.models.source import EvidenceItem, Source
from app.routers import automation as automation_router
from app.routers import geo as geo_router
from app.routers import ml as ml_router
from app.routers import reports as reports_router
from app.services.neo4j_service import Neo4jService, set_neo4j_service

ACCUSATORY = ("responsible for", "perpetrator", "guilty", "culprit", "committed", "is the offender")


@pytest.fixture(autouse=True)
def no_neo4j():
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    yield
    set_neo4j_service(None)


def _client(db, user):
    app = FastAPI()
    for r in (automation_router.router, ml_router.router, geo_router.router, reports_router.router):
        app.include_router(r)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def case():
    db = make_db()
    c = seed_case(db, "Automation case")
    return db, c, _client(db, c["user"])


def _url(c, path):
    return f"/incidents/{c['incident'].id}{path}"


def _actions(db, c):
    return [e.action for e in db.query(AuditEvent).filter(AuditEvent.incident_id == c["incident"].id).order_by(AuditEvent.created_at)]


# ------------------------------------------------------------------ summary
def test_summary_sections_and_traceability(case):
    db, c, cl = case
    s = cl.get(_url(c, "/automation/summary")).json()
    for k in ("media", "detection_results", "sources", "platforms", "locations", "propagation", "ml_findings", "evidence",
              "verified_facts", "inferences", "unknowns", "evidence_gaps"):
        assert k in s, k
    ev_ids = {e.id for e in c["evidence"]}
    assert {e["evidence_id"] for e in s["evidence"]} == ev_ids
    assert {x["source_id"] for x in s["sources"]} == {x.id for x in c["sources"]}
    for bucket in ("verified_facts", "inferences", "unknowns"):
        for f in s[bucket]:
            assert set(f["evidence_ids"]) <= ev_ids and set(f["source_ids"]) <= {x.id for x in c["sources"]}
    statuses = {r["status"] for r in s["propagation"]["relationships"]}
    assert statuses == {"inferred", "confirmed", "unknown"}
    assert all(f["status"] != "inferred" for f in s["verified_facts"])
    assert s["detection_results"][0]["note"].startswith("A model score")
    assert s["ml_findings"]["similarity"]["status"] == "insufficient_data"     # only one fingerprinted media for this owner


# ------------------------------------------------------------------ gaps
def test_gap_detection(case):
    db, c, cl = case
    kinds = {g["kind"] for g in cl.get(_url(c, "/automation/gaps")).json()["gaps"]}
    assert {"original_source_not_established", "location_unverified", "direction_not_confirmed", "direction_unknown",
            "insufficient_corroboration", "source_without_location", "source_without_evidence", "ml_insufficient_data"} <= kinds


def test_timestamp_unavailable_gap_is_reported_not_filled(case):
    db, c, cl = case
    db.query(EvidenceItem).filter(EvidenceItem.id == c["evidence"][1].id).update({"captured_at": None})
    db.commit()
    gaps = cl.get(_url(c, "/automation/gaps")).json()["gaps"]
    assert any(g["kind"] == "timestamp_unavailable" for g in gaps)
    tl = cl.get(_url(c, "/automation/timeline")).json()
    assert any(u["record_id"] == c["evidence"][1].id for u in tl["undated"])
    assert all(e["timestamp"] for e in tl["events"])


# ------------------------------------------------------------------ timeline
def test_timeline_is_chronological_and_separates_observed_from_inferred(case):
    db, c, cl = case
    tl = cl.get(_url(c, "/automation/timeline")).json()
    ts = [e["timestamp"] for e in tl["events"]]
    assert ts == sorted(ts)
    bases = {e["basis"] for e in tl["events"]}
    assert {"OBSERVED", "RECORDED", "INFERRED", "CONFIRMED", "UNKNOWN"} <= bases
    inf = next(e for e in tl["events"] if e["basis"] == "INFERRED")
    assert "not confirmed" in inf["event"] and inf["status"] == "inferred"
    obs = [e for e in tl["events"] if e["basis"] == "OBSERVED" and e.get("source")]
    assert {e["source"]["source_id"] for e in obs} >= {x.id for x in c["sources"]}
    mum = next(e for e in obs if e["source"]["source_id"] == c["sources"][0].id and "observed" in e["event"])
    assert mum["location"]["label"] == "Mumbai" and mum["location"]["status"] == "verified" and mum["platform"] == "User upload"


# ------------------------------------------------------------------ report
def test_report_generation_versioning_audit_and_no_status_change(case):
    db, c, cl = case
    status_before = c["incident"].status
    r1 = cl.post(_url(c, "/automation/reports"))
    assert r1.status_code == 201
    rep = r1.json()["report"]
    for k in ("case_overview", "evidence_summary", "geographic_findings", "propagation_findings", "ml_findings",
              "evidence_gaps", "recommended_actions", "disclaimer"):
        assert k in rep
    assert rep["version"] == 1 and rep["generated_by"]["email"] == c["user"].email
    r2 = cl.post(_url(c, "/automation/reports")).json()
    assert r2["version"] == 2 and cl.get(_url(c, "/automation/reports/latest")).json()["version"] == 2
    assert len(cl.get(_url(c, "/automation/reports")).json()) == 2
    db.refresh(c["incident"])
    assert c["incident"].status == status_before
    assert _actions(db, c).count("report_generated") == 2
    pdf = cl.get(_url(c, f"/automation/reports/{r2['id']}/pdf"))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_report_recommendations_are_not_accusations_and_trace_to_gaps(case):
    db, c, cl = case
    rep = cl.post(_url(c, "/automation/reports")).json()["report"]
    gap_ids = {g["id"] for g in rep["evidence_gaps"]}
    assert rep["recommended_actions"]
    for a in rep["recommended_actions"]:
        assert set(a["basis_gap_ids"]) <= gap_ids
        assert not any(x in a["action"].lower() for x in ACCUSATORY)
    assert "Earliest observed is not the same as original source" in rep["propagation_findings"]["note"]
    assert "does not establish the identity" in rep["disclaimer"]


# ------------------------------------------------------------------ alert draft
def test_alert_draft_insufficient_evidence():
    db = make_db()
    c = seed_case(db, "Upload only")
    db.query(Source).filter(Source.platform != "User upload").delete()
    db.commit()
    r = _client(db, c["user"]).post(_url(c, "/automation/alert-drafts"))
    assert r.status_code == 422 and "external source" in json.dumps(r.json())


def test_alert_draft_edit_approve_export_never_sends(case):
    db, c, cl = case

    def forbid(*a, **k):
        raise AssertionError("No outbound network call is allowed")

    with patch.object(httpx.Client, "send", forbid), patch.object(httpx.AsyncClient, "send", forbid):
        d = cl.post(_url(c, "/automation/alert-drafts"))
        assert d.status_code == 201
        d = d.json()
        assert d["banner"] == "DRAFT — REQUIRES INVESTIGATOR REVIEW" and d["content"]["banner"] == d["banner"]
        assert d["status"] == "draft" and d["sent"] is False and "not_sent" in d["content"]["transmission"]
        assert set(d["content"]["observed_platforms"]) == {"Instagram", "Telegram"}
        assert {e["evidence_id"] for e in d["content"]["evidence_references"]} == {e.id for e in c["evidence"]}
        assert any(e["basis"] == "INFERRED" for e in d["content"]["timeline"])
        a = cl.post(_url(c, f"/automation/alert-drafts/{d['id']}/approve")).json()
        assert a["status"] == "approved" and a["approved_by_email"] == c["user"].email and a["sent"] is False
        e = cl.patch(_url(c, f"/automation/alert-drafts/{d['id']}"), json={"request_text": "Edited request."}).json()
        assert e["status"] == "draft" and e["approved_at"] is None and e["request_text"] == "Edited request."
        cl.post(_url(c, f"/automation/alert-drafts/{d['id']}/approve"))
        j = cl.get(_url(c, f"/automation/alert-drafts/{d['id']}/export?format=json"))
        assert j.status_code == 200 and j.json()["exported_at"] and j.json()["sent"] is False
        p = cl.get(_url(c, f"/automation/alert-drafts/{d['id']}/export?format=pdf"))
        assert p.content[:4] == b"%PDF"
    acts = _actions(db, c)
    for x in ("alert_draft_generated", "alert_draft_approved", "alert_draft_edited", "alert_draft_exported"):
        assert x in acts


# ------------------------------------------------------------------ workflow
def test_workflow_states_are_investigator_controlled(case):
    db, c, cl = case
    w = cl.get(_url(c, "/workflow")).json()
    assert [s["key"] for s in w["states"]] == ["new", "analyzing", "evidence_collected", "review_required", "report_ready", "closed"]
    assert w["state"] == "evidence_collected"                      # seed status evidence_building
    cl.get(_url(c, "/ml"))
    cl.get(_url(c, "/automation/summary"))
    assert cl.get(_url(c, "/workflow")).json()["state"] == "evidence_collected"   # ML/automation never move it
    r = cl.put(_url(c, "/workflow"), json={"state": "review_required", "note": "needs review"})
    assert r.json()["state"] == "review_required" and r.json()["stored_status"] == "gap_reviewed"
    assert cl.put(_url(c, "/workflow"), json={"state": "confirmed"}).status_code == 422
    assert cl.put(_url(c, "/workflow"), json={"state": "closed"}).json()["state"] == "closed"
    ev = [e for e in cl.get(_url(c, "/audit")).json()["events"] if e["action"] == "status_changed"]
    assert len(ev) == 2 and ev[0]["details"]["to"] == "gap_reviewed" and ev[0]["actor"]["email"] == c["user"].email


# ------------------------------------------------------------------ audit trail
def test_audit_trail_records_investigator_actions_with_actor(case):
    db, c, cl = case
    s3 = c["sources"][2]
    assert cl.put(f"/incidents/{c['incident'].id}/sources/{s3.id}/location",
                  json={"latitude": 51.5, "longitude": -0.12, "confidence": 40, "place_name": "London"}).status_code == 200
    cl.put(f"/incidents/{c['incident'].id}/sources/{s3.id}/location", json={"latitude": 51.51, "longitude": -0.13, "confidence": 45})
    cl.post(_url(c, "/reviews"), json={"target_type": "evidence", "target_id": c["evidence"][0].id, "decision": "accepted"})
    assert cl.post(_url(c, "/reviews"), json={"target_type": "evidence", "target_id": "nope"}).status_code == 404
    cl.post(_url(c, "/reviews"), json={"target_type": "ml_finding", "target_id": "anomaly:abc123", "decision": "dismissed"})
    cl.post(_url(c, "/report"))
    events = cl.get(_url(c, "/audit")).json()["events"]
    acts = [e["action"] for e in events]
    for a in ("location_added", "location_edited", "evidence_reviewed", "finding_reviewed", "legacy_report_generated"):
        assert a in acts, a
    assert all(e["actor"]["email"] == c["user"].email and e["created_at"] for e in events)
    rev = next(e for e in events if e["action"] == "evidence_reviewed")
    assert rev["target_id"] == c["evidence"][0].id and rev["details"]["decision"] == "accepted"
    ev = db.get(EvidenceItem, c["evidence"][0].id)
    assert ev.notes is None and ev.storage_path == c["media"].storage_path          # review never edits evidence


def test_reviewing_an_ml_finding_clears_its_unreviewed_gap():
    db = make_db()
    a = seed_case(db, "A")
    seed_case(db, "B", owner=a["user"])
    cl = _client(db, a["user"])
    fid = cl.get(_url(a, "/ml/similarity")).json()["results"][0]["id"]
    gaps = cl.get(_url(a, "/automation/gaps")).json()["gaps"]
    assert any(g.get("finding_id") == fid for g in gaps)
    cl.post(_url(a, "/reviews"), json={"target_type": "ml_finding", "target_id": fid, "decision": "reviewed"})
    assert not any(g.get("finding_id") == fid for g in cl.get(_url(a, "/automation/gaps")).json()["gaps"])
    s = cl.get(_url(a, "/automation/summary")).json()
    assert s["ml_findings"]["similarity"]["results"][0]["reviewed"]["by"] == a["user"].email


# ------------------------------------------------------------------ export
def test_json_export_preserves_ids_provenance_and_statuses(case):
    db, c, cl = case
    cl.post(_url(c, "/automation/reports"))
    r = cl.get(_url(c, "/automation/export?format=json"))
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    b = r.json()
    assert b["investigation_id"] == c["incident"].id and b["latest_report"]["version"] == 1
    blob = json.dumps(b)
    for e in c["evidence"]:
        assert e.id in blob
    for s in c["sources"]:
        assert s.id in blob
    rel_status = {x["status"] for x in b["summary"]["propagation"]["relationships"]}
    assert rel_status == {"inferred", "confirmed", "unknown"}
    assert b["summary"]["ml_findings"]["anomalies"]["model_name"] == "lineage-anomaly-rules"
    assert b["timeline"]["events"] and b["audit_trail"]
    assert "enc/" not in blob
    assert "investigation_exported" in _actions(db, c)
    pdf = cl.get(_url(c, "/automation/export?format=pdf"))
    assert pdf.content[:4] == b"%PDF"


def test_automation_is_owner_scoped():
    db = make_db()
    a, b = seed_case(db, "A"), seed_case(db, "B")
    cl = _client(db, a["user"])
    for path in ("/automation/summary", "/automation/timeline", "/workflow", "/audit", "/ml"):
        assert cl.get(_url(b, path)).status_code == 404
