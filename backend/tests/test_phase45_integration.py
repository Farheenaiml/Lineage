"""Phase 4/5 integration: Neo4j -> ML, ML -> evidence/source/location, RAG -> evidence, report -> evidence.
The graph is served through the Phase 3 loader. Without a server, a FakeGraphRepository stands in for Neo4j; with
NEO4J_TEST_URI set, the same chain runs against a real Neo4j."""
import functools
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph_fakes import FakeGraphRepository, make_db, seed_case

from app.db.session import get_db
from app.deps import get_current_user
from app.models.location import SourceLocation
from app.models.source import EvidenceItem, Source
from app.routers import automation as automation_router, copilot as copilot_router, ml as ml_router
from app.services import graph_sync
from app.services.graph_store import Neo4jGraphRepository
from app.services.neo4j_service import Neo4jService, set_neo4j_service


class _Svc:
    configured = True


@pytest.fixture
def world(monkeypatch):
    """Two same-owner investigations with visually identical media; graph reads go through a Neo4j-shaped store."""
    db = make_db()
    a = seed_case(db, "Chain A")
    b = seed_case(db, "Chain B", owner=a["user"])
    repo = FakeGraphRepository()
    real = graph_sync.load_graph
    monkeypatch.setattr(graph_sync, "load_graph", functools.partial(real, service=_Svc(), repo=repo))
    app = FastAPI()
    for r in (ml_router.router, automation_router.router, copilot_router.router):
        app.include_router(r)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: a["user"]
    return db, a, b, repo, TestClient(app)


def test_neo4j_to_ml(world):
    db, a, b, repo, cl = world
    sim = cl.get(f"/incidents/{a['incident'].id}/ml/similarity").json()
    assert sim["results"] and set(sim["results"][0]["provenance"]["graph_source"].values()) == {"neo4j"}
    assert repo.investigation_ids() == sorted([a["incident"].id, b["incident"].id])   # both graphs came through the store
    an = cl.get(f"/incidents/{a['incident'].id}/ml/anomalies").json()
    assert an["graph_source"]["backend"] == "neo4j"


def test_ml_results_resolve_to_real_evidence_sources_and_locations(world):
    db, a, b, repo, cl = world
    out = cl.get(f"/incidents/{a['incident'].id}/ml").json()
    ev_ids = {e.id for e in db.query(EvidenceItem).all()}
    src_ids = {s.id for s in db.query(Source).all()}
    loc_sources = {l.source_id for l in db.query(SourceLocation).all()}
    for r in out["similarity"]["results"] + out["clusters"]["results"]:
        assert set(r["evidence_refs"]["evidence_ids"]) <= ev_ids and r["evidence_refs"]["evidence_ids"]
        sources = r.get("sources") or r["media"]["sources"] + r["match"]["sources"]
        assert {s["source_id"] for s in sources} <= src_ids
        for s in sources:
            if s["location"]:
                assert s["source_id"] in loc_sources and s["location"]["map_node_id"]
    for r in out["anomalies"]["results"]:
        assert set(r["source_ids"]) <= src_ids and set(r["evidence_ids"]) <= ev_ids


def test_rag_and_report_reference_only_real_evidence(world):
    db, a, b, repo, cl = world
    ev_ids = {e.id for e in db.query(EvidenceItem).filter(EvidenceItem.incident_id == a["incident"].id).all()}
    rag = cl.post(f"/incidents/{a['incident'].id}/copilot", json={"question": "What evidence supports this?"}).json()
    assert rag["graph_context"]["graph_source"]["backend"] == "neo4j"
    assert {e["id"] for e in rag["evidence_used"]} <= ev_ids and rag["evidence_used"]
    rep = cl.post(f"/incidents/{a['incident'].id}/automation/reports").json()["report"]
    report_ev = {e["evidence_id"] for e in rep["evidence_summary"]["evidence"]}
    assert report_ev == ev_ids
    for bucket in rep["facts"].values():
        for f in bucket:
            assert set(f["evidence_ids"]) <= ev_ids
    for key in ("similarity", "clusters"):
        for r in rep["ml_findings"][key]["results"]:
            assert set(r["evidence_ids"]) <= {e.id for e in db.query(EvidenceItem).all()}
            assert r["nature"].startswith("ML analysis")


def test_same_ids_through_the_chain(world):
    db, a, b, repo, cl = world
    s = cl.get(f"/incidents/{a['incident'].id}/automation/summary").json()
    tl = cl.get(f"/incidents/{a['incident'].id}/automation/timeline").json()
    graph_nodes = {n["props"]["node_id"] for n in repo.nodes.values() if n["props"]["investigation_id"] == a["incident"].id}
    assert {x["node_id"] for x in s["sources"]} <= graph_nodes
    assert {e["node_id"] for e in s["evidence"]} <= graph_nodes
    for e in tl["events"]:
        assert all(n in graph_nodes or n.startswith("detection:") for n in e["node_ids"])
    maps = {l["map_node_id"] for l in s["locations"]}
    assert maps and all(m for m in maps)


@pytest.mark.skipif(not os.environ.get("NEO4J_TEST_URI"), reason="NEO4J_TEST_URI not set — real-Neo4j chain test skipped.")
def test_real_neo4j_chain():
    svc = Neo4jService(os.environ["NEO4J_TEST_URI"], os.environ.get("NEO4J_TEST_USER", "neo4j"),
                       os.environ.get("NEO4J_TEST_PASSWORD", ""), "neo4j", connect_timeout=5, retry_seconds=0)
    if not svc.is_available():
        pytest.skip("Neo4j not reachable")
    db = make_db()
    a = seed_case(db, "Real chain A")
    b = seed_case(db, "Real chain B", owner=a["user"])
    set_neo4j_service(svc)
    try:
        app = FastAPI()
        for r in (ml_router.router, automation_router.router):
            app.include_router(r)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: a["user"]
        cl = TestClient(app)
        sim = cl.get(f"/incidents/{a['incident'].id}/ml/similarity").json()
        assert set(sim["results"][0]["provenance"]["graph_source"].values()) == {"neo4j"}
        s = cl.get(f"/incidents/{a['incident'].id}/automation/summary").json()
        assert s["graph_source"]["backend"] == "neo4j"
        exp = cl.get(f"/incidents/{a['incident'].id}/automation/export").json()
        assert json.dumps(exp).count(a["evidence"][0].id) >= 1
    finally:
        set_neo4j_service(None)
        repo = Neo4jGraphRepository(svc)
        for c in (a, b):
            repo.delete_investigation(c["incident"].id)
        svc.close()
