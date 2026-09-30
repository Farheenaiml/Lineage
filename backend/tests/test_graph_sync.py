"""Phase 3A — SQL -> KnowledgeGraph -> Neo4j sync, idempotency, metadata/status preservation, retrieval + fallback.
Sync logic runs against FakeGraphRepository (same MERGE/prune semantics as the Cypher). The Cypher itself is checked
statement-by-statement here and end-to-end against a live server in test_neo4j_integration.py."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph_fakes import FakeGraphRepository, make_db, seed_case

from app.db.session import get_db
from app.deps import get_current_user
from app.models.location import SourceLocation
from app.routers import graph as graph_router
from app.services import graph_sync
from app.services import knowledge_graph as kg
from app.services.graph_store import LABELS, REL_TYPES, Neo4jGraphRepository, schema_statements
from app.services.neo4j_service import Neo4jQueryError, Neo4jService, Neo4jUnavailable, set_neo4j_service


def _case(**kw):
    db = make_db()
    return db, seed_case(db, **kw)


def _strip(d):
    d = dict(d)
    d.pop("generated_at", None)
    return json.loads(json.dumps(d, sort_keys=True))


def _neo4j_types(repo, inv):
    return sorted(r["type"] for r in repo.rels.values() if r["props"]["investigation_id"] == inv)


# ------------------------------------------------------------------ node creation
def test_sync_creates_one_node_per_existing_entity_with_labels():
    db, c = _case()
    repo = FakeGraphRepository()
    rep = graph_sync.sync_investigation(c["incident"], db, repo)
    g = graph_sync.build_memory_graph(c["incident"], db)
    persisted = [n for n in g.nodes() if n["type"] != "propagation"]
    assert rep["nodes"] == len(persisted) == len(repo.nodes)
    labels = {lbl for n in repo.nodes.values() for lbl in n["labels"]}
    assert labels <= set(LABELS.values()) | {"LineageNode"}
    assert {"Investigation", "Media", "Source", "Evidence", "Platform", "Account", "Location", "Fingerprint", "Detection"} <= labels
    assert not any("Propagation" in n["labels"] for n in repo.nodes.values())
    assert repo.schema_calls == 1


def test_node_ids_are_stable_sql_ids():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    inv = c["incident"].id
    for s in c["sources"]:
        n = repo.nodes[f"{inv}|source:{s.id}"]["props"]
        assert n["record_id"] == s.id and n["investigation_id"] == inv and n["node_id"] == f"source:{s.id}"
    assert repo.nodes[f"{inv}|investigation:{inv}"]["props"]["record_id"] == inv
    assert repo.nodes[f"{inv}|media:{c['media'].id}"]["props"]["record_id"] == c["media"].id


def test_no_placeholder_entities_for_empty_investigation():
    db, c = _case(with_locations=False, with_relationships=False, with_evidence=False)
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    types = {n["props"]["type"] for n in repo.nodes.values()}
    assert "location" not in types and "evidence" not in types
    assert not any(r["type"] in ("LOCATED_AT", "PROPAGATES_TO", "RELATED_TO", "SUPPORTED_BY") for r in repo.rels.values())


# ------------------------------------------------------------------ idempotency / duplicates
def test_sync_twice_equals_sync_once():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    snap = json.dumps({"n": repo.nodes, "r": repo.rels}, sort_keys=True, default=sorted)
    second = graph_sync.sync_investigation(c["incident"], db, repo)
    assert second["write"]["nodes_removed"] == 0 and second["write"]["relationships_removed"] == 0
    # only synced_at changes between runs
    for n in repo.nodes.values():
        n["props"].pop("synced_at", None)
    first = json.loads(snap)
    for n in first["n"].values():
        n["props"].pop("synced_at", None)
    assert json.loads(json.dumps({"n": repo.nodes, "r": repo.rels}, sort_keys=True, default=sorted)) == first


def test_duplicate_prevention_uids_unique():
    db, c = _case()
    repo = FakeGraphRepository()
    for _ in range(3):
        graph_sync.sync_investigation(c["incident"], db, repo)
    g = graph_sync.build_memory_graph(c["incident"], db)
    assert len(repo.nodes) == sum(1 for n in g.nodes() if n["type"] != "propagation")
    assert len(repo.rels) == sum(1 for r in g.relationships() if r["type"] in REL_TYPES)
    assert len({(r["type"], r["src"], r["dst"], r["props"]["rel_id"]) for r in repo.rels.values()}) == len(repo.rels)


def test_resync_removes_entities_deleted_in_sql_only_for_that_investigation():
    db = make_db()
    a, b = seed_case(db, "Case A"), seed_case(db, "Case B")
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(a["incident"], db, repo)
    graph_sync.sync_investigation(b["incident"], db, repo)
    b_before = repo.counts(b["incident"].id)
    db.query(SourceLocation).filter(SourceLocation.source_id == a["sources"][1].id).delete()
    db.commit()
    rep = graph_sync.sync_investigation(a["incident"], db, repo)
    assert rep["write"]["nodes_removed"] == 1 and rep["write"]["relationships_removed"] >= 1   # Delhi location + its LOCATED_AT
    assert not any(n["props"].get("city") == "Delhi" and n["props"]["investigation_id"] == a["incident"].id for n in repo.nodes.values())
    assert repo.counts(b["incident"].id) == b_before                                             # other investigation untouched


def test_single_investigation_sync_and_rebuild_do_not_touch_others():
    db = make_db()
    a, b = seed_case(db, "Case A"), seed_case(db, "Case B")
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(a["incident"], db, repo)
    assert repo.investigation_ids() == [a["incident"].id]
    graph_sync.sync_investigation(b["incident"], db, repo)
    b_counts = repo.counts(b["incident"].id)
    rep = graph_sync.sync_investigation(a["incident"], db, repo, rebuild=True)
    assert rep["rebuild"] is True and rep["rebuild_removed"]["nodes_removed"] > 0
    assert repo.counts(b["incident"].id) == b_counts
    assert repo.counts(a["incident"].id)["nodes"] == rep["nodes"]


def test_same_platform_in_two_investigations_is_not_shared():
    db = make_db()
    a, b = seed_case(db, "Case A"), seed_case(db, "Case B")
    repo = FakeGraphRepository()
    graph_sync.sync_all(db, repo)
    insta = [n for n in repo.nodes.values() if "Platform" in n["labels"] and n["props"]["label"] == "Instagram"]
    assert len(insta) == 2 and len({n["props"]["investigation_id"] for n in insta}) == 2


# ------------------------------------------------------------------ relationships + metadata + status
def test_relationship_types_created():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    types = set(_neo4j_types(repo, c["incident"].id))
    assert {"CONTAINS", "APPEARS_IN", "HAS_FINGERPRINT", "ANALYZED_BY", "SUPPORTED_BY", "HOSTED_ON",
            "ASSOCIATED_WITH", "LOCATED_AT", "RELATED_TO", "PROPAGATES_TO"} == types


def test_confirmed_inferred_unknown_statuses_are_preserved_verbatim():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    by_rel = {r["props"]["rel_id"]: r for r in repo.rels.values()}
    assert by_rel[f"PROPAGATES_TO:{c['rels']['inferred'].id}"]["props"]["status"] == "inferred"
    assert by_rel[f"PROPAGATES_TO:{c['rels']['confirmed'].id}"]["props"]["status"] == "confirmed"
    unk = by_rel[f"RELATED_TO:{c['rels']['unknown'].id}"]
    assert unk["props"]["status"] == "unknown" and unk["type"] == "RELATED_TO" and unk["props"]["directed"] is False
    # no status was ever upgraded: every persisted status equals the in-memory one
    g = graph_sync.build_memory_graph(c["incident"], db)
    mem = {r["id"]: r["status"] for r in g.relationships()}
    assert all(r["props"]["status"] == mem[r["props"]["rel_id"]] for r in repo.rels.values())


def test_relationship_metadata_confidence_timestamp_evidence_preserved_and_nulls_not_fabricated():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    by_rel = {r["props"]["rel_id"]: r["props"] for r in repo.rels.values()}
    inf = by_rel[f"PROPAGATES_TO:{c['rels']['inferred'].id}"]
    assert inf["confidence"] == 0.8 and inf["timestamp"].startswith("2026-01-01T10:00") and inf["timestamp_kind"] == "target_observed_at"
    conf = by_rel[f"PROPAGATES_TO:{c['rels']['confirmed'].id}"]
    assert "confidence" not in conf                                   # SQL confidence is NULL -> no property, not 0
    assert json.loads(conf["payload_json"])["confidence"] is None
    assert conf["direction_note"] == "checked post timestamps"
    loc = next(p for p in by_rel.values() if p["rel_id"].startswith("LOCATED_AT") and p["provenance"] == "exif_gps")
    assert loc["status"] == "verified" and loc["confidence"] == 0.95 and loc["evidence_id"] == c["evidence"][0].id
    inv_loc = next(p for p in by_rel.values() if p["rel_id"].startswith("LOCATED_AT") and p["provenance"] == "investigator_supplied")
    assert inv_loc["status"] == "investigator_supplied" and "evidence_id" not in inv_loc


def test_location_nodes_keep_phase1_phase2_fields():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    mum = next(n["props"] for n in repo.nodes.values() if "Location" in n["labels"] and n["props"].get("city") == "Mumbai")
    assert mum["latitude"] == 19.076 and mum["longitude"] == 72.8777 and mum["region"] == "Maharashtra"
    assert mum["tier"] == "verified" and mum["confidence"] == 0.95 and mum["map_node_id"]
    delhi = next(n["props"] for n in repo.nodes.values() if "Location" in n["labels"] and n["props"].get("city") == "Delhi")
    assert "region" not in delhi and json.loads(delhi["metadata_json"])["region"] is None   # not recorded -> stays null


def test_no_storage_paths_are_persisted():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    blob = json.dumps({"n": repo.nodes, "r": repo.rels}, default=sorted)
    assert "enc/" not in blob


# ------------------------------------------------------------------ retrieval
def test_graph_read_back_from_store_is_identical_to_in_memory_graph():
    db, c = _case()
    repo = FakeGraphRepository()
    graph_sync.sync_investigation(c["incident"], db, repo)
    mem = graph_sync.build_memory_graph(c["incident"], db)
    back = graph_sync.records_to_graph(c["incident"].id, repo.fetch_investigation(c["incident"].id))
    assert _strip(back.to_dict()) == _strip(mem.to_dict())
    # propagation nodes + structural edges are re-derived with the same status
    assert {n["id"] for n in back.nodes(types=["propagation"])} == {n["id"] for n in mem.nodes(types=["propagation"])}
    assert all(r["status"] in ("inferred", "confirmed") for r in back.relationships(types=["HAS_ORIGIN", "HAS_DESTINATION"]))


def test_from_records_never_upgrades_status():
    g = kg.KnowledgeGraph.from_records("i", [
        {"id": "source:a", "type": "source", "label": "A", "metadata": {"code": "SRC-A"}},
        {"id": "source:b", "type": "source", "label": "B", "metadata": {"code": "SRC-B"}}],
        [{"id": "PROPAGATES_TO:r", "source": "source:a", "target": "source:b", "type": "PROPAGATES_TO", "confidence": None,
          "timestamp": None, "timestamp_kind": None, "evidence_id": None, "status": "inferred", "directed": True,
          "metadata": {"relationship_id": "r", "from_code": "SRC-A", "to_code": "SRC-B"}}])
    assert {r["status"] for r in g.relationships()} == {"inferred"}
    assert g.get_node("propagation:r")["metadata"]["status"] == "inferred"


class _Svc:
    """Neo4jService stand-in for load_graph policy tests."""
    def __init__(self, configured=True):
        self.configured = configured


def test_load_graph_uses_neo4j_when_available():
    db, c = _case()
    repo = FakeGraphRepository()
    g, src = graph_sync.load_graph(c["incident"], db, service=_Svc(), repo=repo, auto_sync=True)
    assert src["backend"] == "neo4j" and src["fallback"] is False and src["neo4j"] == "connected"
    assert repo.writes == 1 and g.stats()["node_count"] == graph_sync.build_memory_graph(c["incident"], db).stats()["node_count"]


def test_load_graph_without_auto_sync_serves_neo4j_copy_or_falls_back_if_never_synced():
    db, c = _case()
    repo = FakeGraphRepository()
    g, src = graph_sync.load_graph(c["incident"], db, service=_Svc(), repo=repo, auto_sync=False)
    assert src["backend"] == "memory" and "not been synced" in src["reason"] and repo.writes == 0
    graph_sync.sync_investigation(c["incident"], db, repo)
    g, src = graph_sync.load_graph(c["incident"], db, service=_Svc(), repo=repo, auto_sync=False)
    assert src["backend"] == "neo4j"


def test_fallback_when_not_configured():
    db, c = _case()
    g, src = graph_sync.load_graph(c["incident"], db, service=Neo4jService("", "neo4j", "", "neo4j"))
    assert src == {"backend": "memory", "neo4j": "not_configured", "fallback": True, "reason": src["reason"]}
    assert g.stats()["node_count"] > 1


class _BrokenRepo(FakeGraphRepository):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def ensure_schema(self):
        raise self.exc


def test_fallback_when_neo4j_unavailable_or_query_fails():
    db, c = _case()
    mem = _strip(graph_sync.build_memory_graph(c["incident"], db).to_dict())
    for exc, status in ((Neo4jUnavailable("Connection refused"), "unavailable"), (Neo4jQueryError("bad"), "connected")):
        g, src = graph_sync.load_graph(c["incident"], db, service=_Svc(), repo=_BrokenRepo(exc))
        assert src["backend"] == "memory" and src["fallback"] is True and src["neo4j"] == status
        assert _strip(g.to_dict()) == mem


def test_fallback_with_real_service_pointing_at_closed_port():
    db, c = _case()
    svc = Neo4jService("bolt://127.0.0.1:1", "neo4j", "x", "neo4j", connect_timeout=1, retry_seconds=60)
    g, src = graph_sync.load_graph(c["incident"], db, service=svc)
    assert src["backend"] == "memory" and src["neo4j"] == "unavailable"


# ------------------------------------------------------------------ Cypher shape (no server)
class _RecordingService:
    schema_ready = False

    def __init__(self):
        self.statements = []

    def write(self, cypher, **p):
        self.statements.append(cypher)
        return []

    def mark_schema_ready(self):
        self.schema_ready = True

    def write_transaction(self, work):
        class Tx:
            def run(tx, cypher, **p):   # noqa: N805
                self.statements.append(cypher)

                class R:
                    def single(self_inner):
                        return {"c": 0}
                return R()
        return work(Tx())


def test_cypher_uses_merge_constraints_and_whitelisted_labels():
    s = _RecordingService()
    repo = Neo4jGraphRepository(s)
    repo.ensure_schema()
    assert all("IF NOT EXISTS" in st for st in s.statements)
    assert sum("IS UNIQUE" in st for st in s.statements) == 1 + len(LABELS) + 6
    repo.ensure_schema()
    assert len(s.statements) == len(schema_statements())           # schema created once per connection
    db, c = _case()
    nodes, rels = graph_sync.graph_to_rows(graph_sync.build_memory_graph(c["incident"], db))
    s.statements.clear()
    repo.replace_investigation(c["incident"].id, nodes, rels)
    data = [st for st in s.statements if "UNWIND" in st]
    assert data and all("MERGE" in st and "CREATE" not in st for st in data)
    assert all("investigation_id: $inv" in st for st in s.statements if "DELETE" in st)
    try:
        repo.replace_investigation("x", [{"uid": "x|p", "label": "Propagation`) DETACH DELETE (n", "props": {}}], [])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# ------------------------------------------------------------------ API
def _client(db, user):
    app = FastAPI()
    app.include_router(graph_router.router)
    app.include_router(graph_router.health_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_graph_api_reports_source_and_falls_back_when_unconfigured():
    db, c = _case()
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    try:
        cl = _client(db, c["user"])
        r = cl.get(f"/incidents/{c['incident'].id}/graph")
        assert r.status_code == 200
        body = r.json()
        assert body["graph_source"]["backend"] == "memory" and body["nodes"] and body["relationships"]
        assert cl.get("/graph/health").json()["status"] == "fallback"
        assert cl.post(f"/incidents/{c['incident'].id}/graph/sync").status_code == 503
        assert cl.get(f"/incidents/{c['incident'].id}/graph/nodes?type=location").json()["count"] == 2
    finally:
        set_neo4j_service(None)


def test_graph_api_is_owner_scoped():
    db = make_db()
    a, b = seed_case(db, "Case A"), seed_case(db, "Case B")
    set_neo4j_service(Neo4jService("", "neo4j", "", "neo4j"))
    try:
        assert _client(db, a["user"]).get(f"/incidents/{b['incident'].id}/graph").status_code == 404
    finally:
        set_neo4j_service(None)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
