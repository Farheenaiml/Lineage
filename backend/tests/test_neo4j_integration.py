"""Phase 3A — end-to-end against a REAL Neo4j server.

Skipped unless NEO4J_TEST_URI is set and reachable, e.g.:
    NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_PASSWORD=... pytest tests/test_neo4j_integration.py
Every test works inside investigation ids created here (fresh UUIDs) and deletes them afterwards; nothing else in the
database is touched."""
import json
import os

import pytest

from graph_fakes import make_db, seed_case

from app.models.location import SourceLocation
from app.services import graph_sync
from app.services.graph_store import Neo4jGraphRepository
from app.services.neo4j_service import Neo4jService, set_neo4j_service

URI = os.environ.get("NEO4J_TEST_URI", "")


@pytest.fixture(scope="module")
def service():
    if not URI:
        pytest.skip("NEO4J_TEST_URI not set — real-Neo4j integration tests skipped.")
    svc = Neo4jService(URI, os.environ.get("NEO4J_TEST_USER", "neo4j"), os.environ.get("NEO4J_TEST_PASSWORD", ""),
                       os.environ.get("NEO4J_TEST_DATABASE", "neo4j"), connect_timeout=5, retry_seconds=0)
    if not svc.is_available():
        pytest.skip(f"Neo4j at {URI} is not reachable: {svc.health()['error']}")
    yield svc
    svc.close()


@pytest.fixture
def world(service):
    db = make_db()
    cases = [seed_case(db, "Integration A"), seed_case(db, "Integration B")]
    repo = Neo4jGraphRepository(service)
    yield db, cases, repo
    for c in cases:
        repo.delete_investigation(c["incident"].id)


def _strip(d):
    d = dict(d)
    d.pop("generated_at", None)
    return json.loads(json.dumps(d, sort_keys=True))


def test_connectivity_and_health(service):
    h = service.health()
    assert h["status"] == "connected" and h["server"]["name"] == "Neo4j Kernel"


def test_constraints_exist(service):
    Neo4jGraphRepository(service).ensure_schema()
    names = {r["name"] for r in service.read("SHOW CONSTRAINTS YIELD name RETURN name")}
    assert {"lineage_node_uid", "lineage_source_uid", "lineage_source_record_id", "lineage_evidence_record_id"} <= names


def test_sync_is_idempotent_on_real_neo4j(world):
    db, (a, _), repo = world
    first = graph_sync.sync_investigation(a["incident"], db, repo)
    c1 = repo.counts(a["incident"].id)
    for _ in range(2):
        graph_sync.sync_investigation(a["incident"], db, repo)
    assert repo.counts(a["incident"].id) == c1 == {"nodes": first["nodes"], "relationships": first["relationships"]}
    dup = repo.service.read(
        "MATCH (n:LineageNode {investigation_id: $inv}) WITH n.uid AS u, count(*) AS c WHERE c > 1 RETURN u", inv=a["incident"].id)
    assert dup == []


def test_round_trip_matches_in_memory_graph_and_statuses(world):
    db, (a, _), repo = world
    graph_sync.sync_investigation(a["incident"], db, repo)
    back = graph_sync.records_to_graph(a["incident"].id, repo.fetch_investigation(a["incident"].id))
    mem = graph_sync.build_memory_graph(a["incident"], db)
    assert _strip(back.to_dict()) == _strip(mem.to_dict())
    rows = repo.service.read(
        "MATCH ()-[r]->() WHERE r.investigation_id = $inv AND type(r) IN ['PROPAGATES_TO','RELATED_TO'] "
        "RETURN type(r) AS t, r.status AS s, r.confidence AS c", inv=a["incident"].id)
    assert sorted((r["t"], r["s"]) for r in rows) == [("PROPAGATES_TO", "confirmed"), ("PROPAGATES_TO", "inferred"), ("RELATED_TO", "unknown")]
    assert next(r for r in rows if r["s"] == "confirmed")["c"] is None     # NULL confidence stays NULL


def test_single_investigation_sync_rebuild_and_prune_are_isolated(world):
    db, (a, b), repo = world
    graph_sync.sync_investigation(a["incident"], db, repo)
    graph_sync.sync_investigation(b["incident"], db, repo)
    b_counts = repo.counts(b["incident"].id)
    db.query(SourceLocation).filter(SourceLocation.source_id == a["sources"][1].id).delete()
    db.commit()
    rep = graph_sync.sync_investigation(a["incident"], db, repo)
    assert rep["write"]["nodes_removed"] == 1
    graph_sync.sync_investigation(a["incident"], db, repo, rebuild=True)
    assert repo.counts(b["incident"].id) == b_counts
    assert repo.counts(a["incident"].id) == {"nodes": rep["nodes"], "relationships": rep["relationships"]}


def test_load_graph_reads_neo4j_then_falls_back_when_unreachable(world, service):
    db, (a, _), repo = world
    g, src = graph_sync.load_graph(a["incident"], db, service=service, repo=repo)
    assert src["backend"] == "neo4j"
    down = Neo4jService("bolt://127.0.0.1:1", "neo4j", "x", "neo4j", connect_timeout=1)
    g2, src2 = graph_sync.load_graph(a["incident"], db, service=down)
    assert src2["backend"] == "memory" and src2["neo4j"] == "unavailable"
    assert _strip(g.to_dict())["nodes"] == _strip(g2.to_dict())["nodes"]


def test_api_serves_graph_from_neo4j(world, service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.deps import get_current_user
    from app.routers import copilot as copilot_router
    from app.routers import graph as graph_router

    db, (a, _), repo = world
    set_neo4j_service(service)
    try:
        app = FastAPI()
        app.include_router(graph_router.router)
        app.include_router(graph_router.health_router)
        app.include_router(copilot_router.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: a["user"]
        cl = TestClient(app)
        assert cl.get("/graph/health").json()["status"] == "connected"
        body = cl.get(f"/incidents/{a['incident'].id}/graph").json()
        assert body["graph_source"]["backend"] == "neo4j" and body["stats"]["propagation"] == {"confirmed": 1, "inferred": 1, "unknown": 1}
        assert cl.post(f"/incidents/{a['incident'].id}/graph/sync").json()["status"] == "synced"
        cop = cl.post(f"/incidents/{a['incident'].id}/copilot", json={"question": "What locations are involved?"}).json()
        assert cop["graph_context"]["graph_source"]["backend"] == "neo4j" and len(cop["locations_used"]) == 2
    finally:
        set_neo4j_service(None)
