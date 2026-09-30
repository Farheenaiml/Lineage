"""Unit tests for Phase 3A — Investigation Knowledge Graph (pure logic; no DB / web framework needed).
Run:  python tests/test_knowledge_graph.py     (or: pytest tests/test_knowledge_graph.py)
Fixtures are TEST-ONLY in-memory records; nothing is written to any investigation."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import geo_intel  # noqa: E402
from app.services import knowledge_graph as KG  # noqa: E402

T0 = datetime(2026, 1, 1, 9, 0)
MUM, DEL, LON = (19.076, 72.8777), (28.6139, 77.209), (51.5074, -0.1278)


# ------------------------------------------------------------------ fixtures
def incident(**kw):
    return {"id": "inc1", "title": "Riya's Case", "description": "d", "victim_ref": "V-1", "status": "created",
            "created_at": T0, "updated_at": T0, **kw}


def media(i=1, path="enc/m1.png", **kw):
    return {"id": f"m{i}", "kind": "image", "original_filename": f"photo{i}.png", "storage_path": path,
            "file_size_bytes": 10, "width": 1, "height": 1, "uploaded_at": T0, **kw}


def src(i, plat="Instagram", acct="AUTO", at=0, sim=90.0, **kw):
    return {"id": f"s{i}", "platform": plat, "account_identifier": f"@a{i}" if acct == "AUTO" else acct, "url": None,
            "observed_at": T0 + timedelta(minutes=at), "similarity_score": sim, "relationship_label": None,
            "is_seeded": False, "created_at": T0, **kw}


def loc(i, coords, prov="investigator_supplied", conf=60.0, place=None, ev=None, **kw):
    return {"id": f"l{i}", "source_id": f"s{i}", "latitude": coords[0], "longitude": coords[1], "place_name": place,
            "city": None, "region": None, "country": None, "provenance": prov, "confidence": conf, "basis": "test",
            "evidence_item_id": ev, "recorded_by": "u1", "recorded_at": T0, **kw}


def rel(i, a, b, t="repost", conf=70.0, confirmed=False):
    return {"id": f"r{i}", "from_source_id": f"s{a}", "to_source_id": f"s{b}", "relationship_type": t, "confidence": conf,
            "created_at": T0, "direction_confirmed": confirmed, "direction_note": "checked" if confirmed else None,
            "direction_confirmed_at": T0 if confirmed else None}


def ev(i, source=None, path=None, typ="screenshot", at=0):
    return {"id": f"e{i}", "source_id": source, "item_type": typ, "storage_path": path, "notes": None,
            "captured_at": T0 + timedelta(minutes=at)}


def build(**kw):
    d = {"incident": incident(), "media": [], "fingerprints": [], "detections": [], "sources": [], "locations": [],
         "relationships": [], "evidence": []}
    d.update(kw)
    return KG.build_graph(d)


def rels_of(g, t):
    return [r for r in g.relationships() if r["type"] == t]


def nodes_of(g, t):
    return [n for n in g.nodes() if n["type"] == t]


# ------------------------------------------------------------------ empty / small graphs
def test_investigation_with_no_sources():
    g = build()
    out = g.to_dict()
    assert [n["type"] for n in out["nodes"]] == ["investigation"] and out["relationships"] == []
    assert out["stats"]["is_empty"] is True and out["stats"]["relationship_count"] == 0
    assert out["nodes"][0]["label"] == "Riya's Case"


def test_investigation_with_media_but_no_sources():
    g = build(media=[media()], fingerprints=[{"id": "f1", "media_item_id": "m1", "average_hash": "ab12", "created_at": T0}],
              detections=[{"id": "d1", "media_item_id": "m1", "manipulation_likelihood": 71.4, "model_name": "pixel-heuristic-v1", "created_at": T0}])
    assert [r["type"] for r in g.relationships()] == ["CONTAINS", "HAS_FINGERPRINT", "ANALYZED_BY"]
    assert not nodes_of(g, "source") and not nodes_of(g, "platform") and not nodes_of(g, "location")
    assert not rels_of(g, "APPEARS_IN")            # nothing to appear in


def test_one_source_no_location_invents_nothing():
    g = build(sources=[src(1)])
    types = sorted({n["type"] for n in g.nodes()})
    assert types == ["account", "investigation", "platform", "source"]
    assert [r["type"] for r in g.relationships()] == ["HOSTED_ON", "ASSOCIATED_WITH"]
    assert not nodes_of(g, "location") and not rels_of(g, "LOCATED_AT")
    assert not rels_of(g, "PROPAGATES_TO") and not nodes_of(g, "propagation")
    assert any("no recorded location" in n for n in g.notes)
    s = nodes_of(g, "source")[0]
    assert s["metadata"]["located"] is False and s["metadata"]["code"] == "SRC-A" and "map_node_id" not in s["metadata"]


def test_multiple_sources_share_platform_and_accounts_are_per_platform():
    g = build(sources=[
        src(1, "Instagram", "@x", 0), src(2, "instagram ", "@x", 10),      # same platform (case/space), same account
        src(3, "Telegram", "@x", 20),                                     # same handle text on ANOTHER platform => distinct account
        src(4, "Telegram", "@y", 30)])
    plats = nodes_of(g, "platform")
    assert sorted(p["label"] for p in plats) == ["Instagram", "Telegram"]
    assert {p["label"]: p["metadata"]["source_count"] for p in plats} == {"Instagram": 2, "Telegram": 2}
    accts = nodes_of(g, "account")
    assert len(accts) == 3 and sum(a["metadata"]["source_count"] for a in accts) == 4
    assert len(rels_of(g, "HOSTED_ON")) == 4 and len(rels_of(g, "ASSOCIATED_WITH")) == 4
    assert [n["metadata"]["code"] for n in nodes_of(g, "source")] == ["SRC-A", "SRC-B", "SRC-C", "SRC-D"]


# ------------------------------------------------------------------ locations
def test_multiple_locations_group_like_the_map_and_share_ids():
    g = build(sources=[src(1, at=0), src(2, at=5), src(3, at=10)],
              locations=[loc(1, MUM, place="Mumbai"), loc(2, (19.0761, 72.8778)), loc(3, DEL, place="Delhi")])
    locs = nodes_of(g, "location")
    assert len(locs) == 2                                       # s1 and s2 round to the same ~1km cell
    mum = next(n for n in locs if n["label"] == "Mumbai")
    assert mum["metadata"]["observation_count"] == 2
    assert mum["metadata"]["map_node_id"] == geo_intel.node_id(geo_intel.node_key(*MUM))
    assert mum["metadata"]["map_link"] == {"kind": "node", "id": mum["metadata"]["map_node_id"]}
    assert len(rels_of(g, "LOCATED_AT")) == 3
    s1 = next(n for n in g.nodes() if n["id"] == "source:s1")
    assert s1["metadata"]["located"] and s1["metadata"]["map_node_id"] == mum["metadata"]["map_node_id"]


def test_verified_investigator_and_inferred_locations_keep_their_status():
    g = build(sources=[src(1), src(2, at=1), src(3, at=2), src(4, at=3)],
              locations=[loc(1, MUM, "exif_gps", 95), loc(2, DEL, "investigator_supplied", 60),
                         loc(3, LON, "inferred", 30), loc(4, (35.0, 139.0), "public_metadata", 88)])
    st = {r["source"]: r for r in rels_of(g, "LOCATED_AT")}
    assert st["source:s1"]["status"] == "verified" and st["source:s1"]["confidence"] == 0.95
    assert st["source:s2"]["status"] == "investigator_supplied" and st["source:s2"]["confidence"] == 0.6
    assert st["source:s3"]["status"] == "inferred" and st["source:s3"]["confidence"] == 0.3
    assert st["source:s4"]["status"] == "verified"
    assert st["source:s1"]["metadata"]["provenance"] == "exif_gps"


def test_mixed_tier_location_node_does_not_upgrade_members():
    g = build(sources=[src(1), src(2, at=1)], locations=[loc(1, MUM, "exif_gps", 95), loc(2, MUM, "inferred", 20)])
    n = nodes_of(g, "location")[0]
    assert n["metadata"]["tier"] == "mixed" and n["metadata"]["verified_count"] == 1
    assert sorted(r["status"] for r in rels_of(g, "LOCATED_AT")) == ["inferred", "verified"]


def test_location_evidence_id_is_preserved():
    g = build(sources=[src(1)], evidence=[ev(1, "s1")], locations=[loc(1, MUM, "exif_gps", 95, ev="e1")])
    assert rels_of(g, "LOCATED_AT")[0]["evidence_id"] == "e1"


def test_invalid_or_orphan_locations_are_skipped_with_a_note():
    g = build(sources=[src(1), src(2, at=1)], locations=[loc(1, (999, 5)), loc(2, MUM), {**loc(3, MUM), "source_id": "ghost"}])
    assert len(nodes_of(g, "location")) == 1 and len(rels_of(g, "LOCATED_AT")) == 1
    assert sum("coordinates" in n or "not in this investigation" in n for n in g.notes) == 2


# ------------------------------------------------------------------ evidence
def test_evidence_relationships_and_no_storage_paths_leak():
    g = build(media=[media(path="enc/SECRET.png")], sources=[src(1, "User upload", None, 0), src(2, at=5)],
              evidence=[ev(1, "s1", "enc/SECRET.png", "uploaded_image"), ev(2, "s2", "enc/shot.png"), ev(3)])
    sup = rels_of(g, "SUPPORTED_BY")
    pairs = {(r["source"], r["target"]) for r in sup}
    assert ("source:s1", "evidence:e1") in pairs and ("media:m1", "evidence:e1") in pairs and ("source:s2", "evidence:e2") in pairs
    assert all(r["evidence_id"] == r["target"].split(":")[1] for r in sup)
    assert not any(r["target"] == "evidence:e3" for r in sup)                       # unattached evidence stays unattached
    assert any("not attached" in n for n in g.notes)
    blob = json.dumps(g.to_dict())
    assert "SECRET" not in blob and "enc/shot.png" not in blob
    assert next(n for n in g.nodes() if n["id"] == "evidence:e1")["metadata"]["has_file"] is True
    assert next(n for n in g.nodes() if n["id"] == "source:s2")["metadata"]["evidence_count"] == 1


def test_evidence_referencing_unknown_source_is_not_linked():
    g = build(sources=[src(1)], evidence=[ev(1, "ghost")])
    assert not rels_of(g, "SUPPORTED_BY") and any("not in this investigation" in n for n in g.notes)


# ------------------------------------------------------------------ media <-> source
def test_upload_source_is_linked_by_the_evidence_file():
    g = build(media=[media(1, "p1"), media(2, "p2")], sources=[src(1, "User upload", None, 0), src(2, at=5)],
              evidence=[ev(1, "s1", "p1", "uploaded_image")])
    ap = rels_of(g, "APPEARS_IN")
    assert [(r["source"], r["target"], r["status"]) for r in ap] == [("media:m1", "source:s1", "recorded")]
    assert ap[0]["evidence_id"] == "e1"
    assert any("not linked to a specific media item" in n for n in g.notes)        # s2 NOT guessed with 2 media items


def test_single_media_scopes_sources_and_keeps_similarity_as_confidence():
    g = build(media=[media()], sources=[src(1, sim=88.0), src(2, at=5, sim=None)])
    ap = {r["target"]: r for r in rels_of(g, "APPEARS_IN")}
    assert ap["source:s1"]["status"] == "incident_scoped" and ap["source:s1"]["confidence"] == 0.88
    assert ap["source:s2"]["confidence"] is None                                     # missing stays missing


def test_upload_link_wins_over_incident_scope_without_duplicates():
    g = build(media=[media(path="p1")], sources=[src(1, "User upload", None, 0)], evidence=[ev(1, "s1", "p1", "uploaded_image")])
    ap = rels_of(g, "APPEARS_IN")
    assert len(ap) == 1 and ap[0]["status"] == "recorded"


def test_fingerprint_and_detection_only_attach_to_existing_media():
    g = build(media=[media()],
              fingerprints=[{"id": "f1", "media_item_id": "m1", "average_hash": "ff00", "face_embedding_json": None, "created_at": T0},
                            {"id": "f2", "media_item_id": "ghost", "average_hash": "aa", "created_at": T0}],
              detections=[{"id": "d1", "media_item_id": "m1", "manipulation_likelihood": 12.0, "model_name": "m", "created_at": T0}])
    assert len(nodes_of(g, "fingerprint")) == 1 and len(nodes_of(g, "detection")) == 1
    det = rels_of(g, "ANALYZED_BY")[0]
    assert det["confidence"] is None                          # likelihood is NOT reused as link confidence
    assert nodes_of(g, "detection")[0]["metadata"]["manipulation_likelihood"] == 12.0
    assert any("Fingerprint" in n for n in g.notes)


# ------------------------------------------------------------------ propagation
def _two_located(**relkw):
    return dict(sources=[src(1, at=0), src(2, "Telegram", at=60)], locations=[loc(1, MUM), loc(2, DEL)], **relkw)


def test_inferred_propagation_stays_inferred():
    g = build(**_two_located(relationships=[rel(1, 1, 2)]))
    p = rels_of(g, "PROPAGATES_TO")
    assert len(p) == 1 and p[0]["status"] == "inferred" and p[0]["directed"] is True
    assert p[0]["source"] == "source:s1" and p[0]["target"] == "source:s2" and p[0]["confidence"] == 0.7
    assert p[0]["timestamp"].startswith("2026-01-01T10:00") and p[0]["timestamp_kind"] == "target_observed_at"
    assert "Not confirmed" in p[0]["metadata"]["basis"]
    assert not any(r["status"] == "confirmed" for r in g.relationships())


def test_confirmed_propagation_remains_confirmed():
    g = build(**_two_located(relationships=[rel(1, 1, 2, confirmed=True)]))
    p = rels_of(g, "PROPAGATES_TO")[0]
    assert p["status"] == "confirmed" and p["metadata"]["direction_note"] == "checked"


def test_confirmed_direction_is_honoured_even_if_timestamps_disagree():
    g = build(sources=[src(1, at=60), src(2, at=0)], relationships=[rel(1, 1, 2, confirmed=True)])
    assert rels_of(g, "PROPAGATES_TO")[0]["status"] == "confirmed"       # investigator's call, same as the map


def test_unknown_relationships_are_never_promoted():
    # (a) type does not imply direction, (b) timestamps conflict with the stored link, (c) timestamps equal
    g = build(sources=[src(1, at=0), src(2, at=30), src(3, at=20), src(4, at=20)],
              relationships=[rel(1, 1, 2, "same content"), rel(2, 2, 3, "repost"), rel(3, 3, 4, "repost")])
    assert not rels_of(g, "PROPAGATES_TO") and not nodes_of(g, "propagation")
    rel_to = rels_of(g, "RELATED_TO")
    assert len(rel_to) == 3 and all(r["status"] == "unknown" and r["directed"] is False for r in rel_to)


def test_propagation_nodes_and_structural_edges():
    g = build(**_two_located(relationships=[rel(1, 1, 2)]))
    pn = nodes_of(g, "propagation")
    assert len(pn) == 1 and pn[0]["label"] == "SRC-A → SRC-B" and pn[0]["metadata"]["status"] == "inferred"
    assert {(r["type"], r["target"]) for r in g.relationships() if r["structural"]} == {("HAS_ORIGIN", "source:s1"), ("HAS_DESTINATION", "source:s2")}
    assert all(r["status"] == "inferred" for r in g.relationships() if r["structural"])
    # structural edges are excluded from degree
    assert next(n for n in g.nodes() if n["id"] == "source:s1")["degree"] == sum(
        1 for r in g.relationships() if "source:s1" in (r["source"], r["target"]) and not r["structural"])


def test_map_link_only_when_both_ends_are_on_the_map_in_different_nodes():
    g = build(**_two_located(relationships=[rel(1, 1, 2)]))
    assert rels_of(g, "PROPAGATES_TO")[0]["metadata"]["map_link"] == {"kind": "edge", "relationship_id": "r1"}
    assert rels_of(g, "PROPAGATES_TO")[0]["metadata"]["on_map"] is True
    # one end unlocated
    g2 = build(sources=[src(1, at=0), src(2, at=60)], locations=[loc(1, MUM)], relationships=[rel(1, 1, 2)])
    m = rels_of(g2, "PROPAGATES_TO")[0]["metadata"]
    assert m["on_map"] is False and m["map_link"] is None
    # both in the same cell -> no arc exists on the map
    g3 = build(sources=[src(1, at=0), src(2, at=60)], locations=[loc(1, MUM), loc(2, MUM)], relationships=[rel(1, 1, 2)])
    assert rels_of(g3, "PROPAGATES_TO")[0]["metadata"]["on_map"] is False


def test_same_decision_as_the_3d_map():
    a, b = {"label": "SRC-A", "observed_at": T0}, {"label": "SRC-B", "observed_at": T0 + timedelta(hours=1)}
    for t, conf in (("repost", False), ("repost", True), ("same content", False), ("related", True)):
        mode, _ = geo_intel.edge_direction(a, b, t, conf)
        g = build(sources=[src(1, at=0), src(2, at=60)], relationships=[rel(1, 1, 2, t, confirmed=conf)])
        expect = "PROPAGATES_TO" if mode in ("confirmed", "inferred") else "RELATED_TO"
        got = (rels_of(g, "PROPAGATES_TO") or rels_of(g, "RELATED_TO"))[0]
        assert got["type"] == expect and (mode if expect == "PROPAGATES_TO" else "unknown") == got["status"]


def test_self_and_orphan_relationships_are_skipped():
    g = build(sources=[src(1)], relationships=[rel(1, 1, 1), rel(2, 1, 9)])
    assert not rels_of(g, "PROPAGATES_TO") and not rels_of(g, "RELATED_TO") and len(g.notes) >= 2


# ------------------------------------------------------------------ missing metadata
def test_missing_metadata_is_null_never_fabricated():
    s = {"id": "s1", "platform": "  ", "account_identifier": "", "url": None, "observed_at": T0, "similarity_score": None,
         "relationship_label": None, "is_seeded": None, "created_at": None}
    g = build(sources=[s, src(2, "Web", None, 5, sim=None)], relationships=[rel(1, 1, 2, conf=None)],
              locations=[loc(2, MUM, conf=None, place=None)])
    n1 = next(n for n in g.nodes() if n["id"] == "source:s1")
    assert n1["label"] == "Unknown platform" and n1["metadata"]["account"] is None and n1["metadata"]["similarity"] is None
    assert not rels_of(g, "HOSTED_ON") or all(r["source"] != "source:s1" for r in rels_of(g, "HOSTED_ON"))
    p = rels_of(g, "PROPAGATES_TO")[0]
    assert p["confidence"] is None and p["evidence_id"] is None
    la = rels_of(g, "LOCATED_AT")[0]
    assert la["confidence"] is None and la["evidence_id"] is None
    assert nodes_of(g, "location")[0]["label"] == "19.076, 72.878"            # coordinates as the label, no made-up place name
    assert nodes_of(g, "location")[0]["metadata"]["confidence"] is None


def test_account_without_platform_is_not_linked():
    g = build(sources=[src(1, plat=None, acct="@ghost")])
    assert not nodes_of(g, "account") and any("no platform" in n for n in g.notes)


# ------------------------------------------------------------------ traversal
def _full_case():
    return build(
        media=[media(path="p1")], fingerprints=[{"id": "f1", "media_item_id": "m1", "average_hash": "ab", "created_at": T0}],
        sources=[src(1, "User upload", None, 0), src(2, "Instagram", "@a", 30), src(3, "Telegram", "@b", 60), src(4, "Web", None, 90)],
        locations=[loc(2, MUM, place="Mumbai"), loc(3, DEL, place="Delhi")],
        relationships=[rel(1, 2, 3), rel(2, 1, 2, "same content")],
        evidence=[ev(1, "s1", "p1", "uploaded_image"), ev(2, "s3")])


def test_connected_reports_direction_and_neighbours():
    g = _full_case()
    c = g.connected("source:s3")
    dirs = {(r["type"], r["direction"]) for r in c["relationships"]}
    assert ("PROPAGATES_TO", "incoming") in dirs and ("LOCATED_AT", "outgoing") in dirs and ("HOSTED_ON", "outgoing") in dirs
    assert {n["type"] for n in c["neighbors"]} >= {"source", "location", "platform", "evidence", "propagation"}
    only = g.connected("source:s3", types=["LOCATED_AT"])
    assert [r["type"] for r in only["relationships"]] == ["LOCATED_AT"]


def test_connected_unknown_node():
    try:
        _full_case().connected("source:nope")
        raise AssertionError("expected NodeNotFound")
    except KG.NodeNotFound:
        pass


def test_paths_shortest_first_and_direction_flags():
    g = _full_case()
    r = g.find_paths("media:m1", "location:" + geo_intel.node_id(geo_intel.node_key(*DEL)))
    assert r["found"] and r["paths"][0]["length"] <= r["paths"][-1]["length"]
    best = r["paths"][0]
    assert best["nodes"][0] == "media:m1" and best["nodes"][-1].startswith("location:")
    assert all(s["direction"] in ("forward", "backward", "undirected") for s in best["steps"])
    ids = {n["id"] for n in r["nodes"]}
    assert set(best["nodes"]) <= ids and all(x["id"] in {s["relationship_id"] for p in r["paths"] for s in p["steps"]} for x in r["relationships"])


def test_path_marks_walking_against_a_propagation_and_reports_weakest_status():
    g = _full_case()
    r = g.find_paths("source:s3", "source:s2", max_depth=2)
    direct = next(p for p in r["paths"] if p["length"] == 0 or all(s["type"] != "HOSTED_ON" for s in p["steps"]))
    assert direct["steps"][0]["type"] == "PROPAGATES_TO" and direct["steps"][0]["direction"] == "backward"
    assert direct["against_direction_steps"] == 1 and direct["weakest_status"] == "inferred"


def test_structural_edges_only_used_for_propagation_endpoints():
    g = _full_case()
    plain = g.find_paths("source:s2", "source:s3", max_depth=4, max_paths=25)
    assert all(s["type"] not in KG.STRUCTURAL_TYPES for p in plain["paths"] for s in p["steps"])
    viaprop = g.find_paths("propagation:r1", "source:s3", max_depth=3)
    assert viaprop["found"] and viaprop["paths"][0]["steps"][0]["type"] in KG.STRUCTURAL_TYPES


def test_no_path_between_disconnected_entities_and_depth_limit():
    g = build(sources=[src(1, "A", None, 0), src(2, "B", None, 5)])
    r = g.find_paths("source:s1", "source:s2")
    assert r["found"] is False and r["paths"] == [] and r["nodes"] == []
    g2 = _full_case()
    assert g2.find_paths("media:m1", "location:" + geo_intel.node_id(geo_intel.node_key(*DEL)), max_depth=1)["found"] is False


def test_path_same_node_and_unknown_node():
    g = _full_case()
    assert g.find_paths("source:s1", "source:s1")["paths"][0]["length"] == 0
    try:
        g.find_paths("source:s1", "nope")
        raise AssertionError("expected NodeNotFound")
    except KG.NodeNotFound:
        pass


# ------------------------------------------------------------------ search / filters / serialisation
def test_search_and_type_filters():
    g = _full_case()
    assert [n["id"] for n in g.nodes(q="mumbai")] == ["location:" + geo_intel.node_id(geo_intel.node_key(*MUM))]
    assert any(n["type"] == "source" for n in g.nodes(q="SRC-C"))
    assert {n["type"] for n in g.nodes(types=["platform", "account"])} == {"platform", "account"}
    out = g.to_dict(types=["source", "location"])
    ids = {n["id"] for n in out["nodes"]}
    assert all(r["source"] in ids and r["target"] in ids for r in out["relationships"])
    assert {r["type"] for r in out["relationships"]} <= {"LOCATED_AT", "RELATED_TO", "PROPAGATES_TO"}


def test_response_shape_matches_frontend_contract():
    out = _full_case().to_dict()
    for n in out["nodes"]:
        assert {"id", "type", "label", "metadata"} <= set(n) and n["type"] in KG.NODE_TYPES
    for r in out["relationships"]:
        assert {"id", "source", "target", "type", "confidence", "timestamp", "evidence_id", "status", "metadata"} <= set(r)
        assert r["type"] in KG.REL_TYPES
    ids = {n["id"] for n in out["nodes"]}
    assert all(r["source"] in ids and r["target"] in ids for r in out["relationships"])
    assert len({r["id"] for r in out["relationships"]}) == len(out["relationships"])
    json.dumps(out)                                                         # fully serialisable


def test_build_is_deterministic_and_stats_are_consistent():
    a, b = _full_case().to_dict(), _full_case().to_dict()
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b
    st = a["stats"]
    assert st["node_count"] == len(a["nodes"]) and st["relationship_count"] == len(a["relationships"])
    assert sum(st["nodes_by_type"].values()) == st["node_count"]
    assert st["propagation"] == {"confirmed": 0, "inferred": 1, "unknown": 1}


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
