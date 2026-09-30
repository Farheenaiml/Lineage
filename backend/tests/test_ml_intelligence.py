"""Phase 4 — ML Intelligence: similarity, anomalies, clustering, provenance, non-mutation. TEST-ONLY fixture data."""
from datetime import datetime, timedelta

import numpy as np

from graph_fakes import make_db, seed_case

from app.models.incident import Incident
from app.models.location import SourceLocation
from app.models.media import Fingerprint
from app.models.source import EvidenceItem, Source, SourceRelationship
from app.services import ml_intelligence as ml

T0 = datetime(2026, 1, 1, 9, 0)
CFG = {"min_obs": 4, "min_rels": 3, "burst_ratio": 0.25, "geo_km": 500.0}
BANNED = ("same person", "same file", "same source", "is the same", "identical person", "responsible", "malicious")


def feat(mid, h, face=None, keyframes=None, inc="i1"):
    return {"media_id": mid, "incident_id": inc, "incident_title": inc, "filename": f"{mid}.png", "kind": "image",
            "fingerprint_id": f"f-{mid}", "fingerprint_created_at": None, "average_hash": h, "keyframes": keyframes or [],
            "face": None if face is None else np.asarray(face, dtype=float)}


def _clean_text(s: str) -> str:
    return s.replace(ml.SIMILARITY_DISCLAIMER, "").replace(ml.CLUSTER_DISCLAIMER, "").replace(ml.ANOMALY_DISCLAIMER, "").lower()


# ------------------------------------------------------------------ similarity (pure)
def test_ahash_similarity_scores():
    assert ml.ahash_similarity("ffffffffffffffff", "ffffffffffffffff") == (1.0, 0, 64)
    assert ml.ahash_similarity("ffffffffffffffff", "fffffffffffffffe") == (round(63 / 64, 4), 1, 64)
    assert ml.ahash_similarity("0000000000000000", "ffffffffffffffff")[0] == 0.0
    assert ml.ahash_similarity("ff", "ffff") is None and ml.ahash_similarity("zz", "ff") is None and ml.ahash_similarity("", "ff") is None


def test_compare_reports_face_separately_and_does_not_change_score():
    a, b = feat("a", "ffffffffffffffff", face=[1, 0, 0]), feat("b", "fffffffffffffff0", face=[0, 1, 0])
    c = ml.compare(a, b)
    assert c["score"] == round(60 / 64, 4)                               # visual only
    face = next(f for f in c["factors"] if f["name"] == "face_embedding_cosine")
    assert face["value"] == 0.0 and "not an identification" in face["detail"]
    nf = next(f for f in ml.compare(feat("x", "ff" * 8), feat("y", "ff" * 8))["factors"] if f["name"] == "face_embedding_cosine")
    assert nf["value"] is None


def test_keyframes_used_for_video():
    a = feat("a", "ffffffffffffffff", keyframes=["ffffffffffffffff", "0000000000000000"])
    b = feat("b", "0f0f0f0f0f0f0f0f", keyframes=["ffffffffffffffff", "0000000000000000"])
    c = ml.compare(a, b)
    assert c["score"] == 1.0 and c["factors"][0]["name"] == "keyframe_hash_similarity"


def test_similarity_labels_never_claim_identity():
    for s in (0.76, 0.9, 0.99, 1.0):
        lab = ml.similarity_label(s).lower()
        assert "visually similar" in lab and not any(b in lab for b in BANNED)


# ------------------------------------------------------------------ similarity (DB)
def _two_cases(hash2="ab12cd34"):
    db = make_db()
    a = seed_case(db, "Case A")
    b = seed_case(db, "Case B", owner=a["user"])
    db.query(Fingerprint).filter(Fingerprint.media_item_id == b["media"].id).update({"average_hash": hash2})
    db.commit()
    return db, a, b


def test_similarity_score_evidence_source_location_linkage_and_provenance():
    db, a, b = _two_cases()
    out = ml.run_similarity(a["incident"], db)
    assert out["status"] == "ok" and len(out["results"]) == 1
    r = out["results"][0]
    assert r["score"] == 1.0 and r["label"].startswith("Visually similar")
    assert r["match"]["incident_id"] == b["incident"].id and r["match"]["same_investigation"] is False
    # evidence linkage: the upload evidence of both media + fingerprints
    assert set(r["evidence_refs"]["evidence_ids"]) >= {a["evidence"][0].id, b["evidence"][0].id}
    assert set(r["evidence_refs"]["fingerprint_ids"]) == {
        db.query(Fingerprint).filter(Fingerprint.media_item_id == m.id).one().id for m in (a["media"], b["media"])}
    # sources / platforms / locations of the matching media (from the graph, statuses kept)
    assert {s["source_id"] for s in r["match"]["sources"]} == {s.id for s in b["sources"]}
    assert {s["appears_in_status"] for s in r["match"]["sources"]} == {"recorded", "incident_scoped"}
    assert set(r["match"]["platforms"]) == {"User upload", "Instagram", "Telegram"}
    assert {l["city"] for l in r["match"]["locations"]} == {"Mumbai", "Delhi"}
    p = r["provenance"]
    assert p["model_name"] == "lineage-visual-similarity" and p["model_version"] == "4.0.0" and p["computed_at"] and p["score"] == 1.0
    assert "not identity" in r["explanation"] and not any(x in _clean_text(r["explanation"]) for x in BANNED)


def test_similarity_below_threshold_is_not_reported():
    db, a, _ = _two_cases(hash2="54ed32cb")          # every bit differs
    out = ml.run_similarity(a["incident"], db)
    assert out["status"] == "ok" and out["results"] == [] and out["pairs_compared"] == 1 and "threshold" in out["message"]


def test_similarity_insufficient_data():
    db = make_db()
    a = seed_case(db, "Alone")
    out = ml.run_similarity(a["incident"], db)
    assert out["status"] == "insufficient_data" and out["message"].startswith("Insufficient data.")
    db.query(Fingerprint).delete()
    db.commit()
    out2 = ml.run_similarity(a["incident"], db)
    assert out2["status"] == "insufficient_data" and "fingerprint" in out2["message"]


def test_similarity_never_crosses_owners():
    db = make_db()
    a = seed_case(db, "Mine")
    seed_case(db, "Someone else")                    # different owner, identical hash
    assert ml.run_similarity(a["incident"], db)["status"] == "insufficient_data"


def test_investigation_scope_stays_inside_the_case():
    db, a, _ = _two_cases()
    assert ml.run_similarity(a["incident"], db, scope="investigation")["status"] == "insufficient_data"


# ------------------------------------------------------------------ anomalies (pure)
def obs(i, minutes, platform="Instagram", loc=None):
    return {"source_id": f"s{i}", "node_id": f"source:s{i}", "code": f"SRC-{i}", "platform": platform,
            "t": T0 + timedelta(minutes=minutes), "location": loc, "evidence_ids": [f"e{i}"]}


def loc(name, lat, lon, status="investigator_supplied"):
    return {"location_node_id": f"location:{name}", "map_node_id": name, "label": name, "latitude": lat, "longitude": lon, "status": status}


def test_anomaly_insufficient_data():
    res = ml.detect_anomalies([obs(1, 0), obs(2, 10), obs(3, 20)], [], CFG)
    assert res["anomalies"] == [] and all(d["status"] == "insufficient_data" for d in res["detectors"])
    assert all(d["reason"].startswith("Insufficient data.") for d in res["detectors"])


def test_burst_is_detected_with_explainable_factors():
    o = [obs(1, 0, "Instagram"), obs(2, 60, "X"), obs(3, 120, "Telegram"), obs(4, 180, "Instagram"),
         obs(5, 181, "X"), obs(6, 182, "Telegram"), obs(7, 183, "Reddit"), obs(8, 300, "Instagram")]
    res = ml.detect_anomalies(o, [], CFG)
    burst = [a for a in res["anomalies"] if a["type"] == "observation_burst"]
    assert len(burst) == 1
    b = burst[0]
    assert b["source_ids"] == ["s4", "s5", "s6", "s7"]
    f = {x["name"]: x for x in b["factors"]}
    assert f["observations_in_window"]["value"] == 4 and f["baseline_median_interval"]["seconds"] == 3600
    assert len(f["platforms"]["value"]) == 4 and "3 minutes" in b["explanation"] and "median observation interval of 60 minutes" in b["explanation"]
    assert b["evidence_ids"] == ["e4", "e5", "e6", "e7"] and 0 < b["score"] <= 1
    assert not any(x in _clean_text(b["explanation"]) for x in BANNED)


def test_regular_observations_are_not_flagged():
    res = ml.detect_anomalies([obs(i, i * 60) for i in range(8)], [], CFG)
    assert res["anomalies"] == [] and res["detectors"][0]["status"] == "ran"


def rel(i, gap_min, status="inferred", typ="PROPAGATES_TO"):
    return {"relationship_id": f"r{i}", "rel_graph_id": f"{typ}:r{i}", "type": typ, "status": status, "from_node": f"source:a{i}",
            "to_node": f"source:b{i}", "from_code": f"SRC-A{i}", "to_code": f"SRC-B{i}", "from_source_id": f"a{i}", "to_source_id": f"b{i}",
            "t_from": T0, "t_to": T0 + timedelta(minutes=gap_min), "evidence_ids": []}


def test_rapid_propagation_keeps_relationship_status():
    rels = [rel(1, 120), rel(2, 120), rel(3, 120, "confirmed"), rel(4, 5, "unknown", "RELATED_TO")]
    res = ml.detect_anomalies([], rels, CFG)
    rp = [a for a in res["anomalies"] if a["type"] == "rapid_propagation"]
    assert len(rp) == 1 and rp[0]["relationship_ids"] == ["RELATED_TO:r4"]
    assert {x["name"]: x["value"] for x in rp[0]["factors"]}["relationship_status"] == "unknown"
    assert "remains 'unknown'" in rp[0]["explanation"] and " and " in rp[0]["explanation"]     # no arrow for undirected
    assert ml.detect_anomalies([], rels[:2], CFG)["detectors"][1]["status"] == "insufficient_data"


def test_geographic_spread():
    o = [obs(1, 0, loc=loc("Mumbai", 19.07, 72.87)), obs(2, 60), obs(3, 120), obs(4, 180, loc=loc("Delhi", 28.61, 77.2)),
         obs(5, 190, loc=loc("London", 51.5, -0.12, "verified")), obs(6, 200, loc=loc("Tokyo", 35.68, 139.69)), obs(7, 400)]
    res = ml.detect_anomalies(o, [], CFG)
    geo = [a for a in res["anomalies"] if a["type"] == "geographic_spread"]
    assert geo and geo[0]["location_node_ids"] == ["location:Delhi", "location:London", "location:Tokyo"]
    f = {x["name"]: x["value"] for x in geo[0]["factors"]}
    assert f["distinct_locations"] == 3 and f["max_distance_km"] > 5000 and f["unverified_locations"] == 2
    assert "not verified" in geo[0]["explanation"]


def test_anomalies_on_real_records_insufficient_and_provenance():
    db = make_db()
    c = seed_case(db)                                   # 3 sources, 3 timed relationships
    out = ml.run_anomalies(c["incident"], db)
    det = {d["detector"]: d["status"] for d in out["detectors"]}
    assert det["observation_burst"] == "insufficient_data" and det["rapid_propagation"] == "ran"
    assert out["provenance"]["model_name"] == "lineage-anomaly-rules" and out["computed_at"]
    db2 = make_db()
    c2 = seed_case(db2, with_relationships=False)
    out2 = ml.run_anomalies(c2["incident"], db2)
    assert out2["status"] == "insufficient_data" and out2["message"] == "Insufficient data." and out2["results"] == []


# ------------------------------------------------------------------ clustering
def test_cluster_generation_and_chaining():
    f = [feat("a", "ffffffffffffffff"), feat("b", "fffffffffffffffe"), feat("c", "fffffffffffffff0"), feat("d", "0000000000000000")]
    cl = ml.cluster_media(f, 0.95)
    assert len(cl) == 1 and sorted(m["media_id"] for m in cl[0]["members"]) == ["a", "b", "c"]
    assert cl[0]["min"] == round(60 / 64, 4) and cl[0]["max"] == round(63 / 64, 4)   # single linkage: min may be below threshold
    assert ml.cluster_media([feat("a", "ff" * 8), feat("d", "00" * 8)], 0.85) == []


def test_clusters_link_sources_and_evidence_without_identity_inference():
    db, a, b = _two_cases()
    out = ml.run_clusters(a["incident"], db)
    assert out["status"] == "ok" and len(out["results"]) == 1
    c = out["results"][0]
    assert c["size"] == 2 and set(c["investigations"]) == {a["incident"].id, b["incident"].id}
    assert c["source_count"] == 6 and {s["source_id"] for s in c["sources"]} == {s.id for s in a["sources"] + b["sources"]}
    assert set(c["evidence_refs"]["evidence_ids"]) >= {a["evidence"][0].id, b["evidence"][0].id}
    assert c["similarity_range"] == {"min": 1.0, "max": 1.0} and {l["city"] for l in c["locations"]} == {"Mumbai", "Delhi"}
    assert c["provenance"]["model_name"] == "lineage-single-linkage-clustering"
    text = _clean_text(c["explanation"])
    assert not any(x in text for x in BANNED) and "owner" not in text and "identity" not in text
    assert "account" not in c and "owner" not in c and "responsible" not in str(c).lower().replace(ml.CLUSTER_DISCLAIMER.lower(), "")


def test_cluster_insufficient_data():
    db = make_db()
    a = seed_case(db)
    out = ml.run_clusters(a["incident"], db)
    assert out["status"] == "insufficient_data" and out["message"].startswith("Insufficient data.")


# ------------------------------------------------------------------ ML never writes
def _snapshot(db):
    return {
        "incidents": [(i.id, i.status) for i in db.query(Incident).order_by(Incident.id)],
        "sources": [(s.id, s.platform, s.observed_at) for s in db.query(Source).order_by(Source.id)],
        "evidence": [(e.id, e.storage_path, e.notes, e.captured_at) for e in db.query(EvidenceItem).order_by(EvidenceItem.id)],
        "locations": [(l.id, l.latitude, l.longitude, l.provenance, l.confidence) for l in db.query(SourceLocation).order_by(SourceLocation.id)],
        "rels": [(r.id, r.relationship_type, r.confidence) for r in db.query(SourceRelationship).order_by(SourceRelationship.id)],
        "fps": [(f.id, f.average_hash) for f in db.query(Fingerprint).order_by(Fingerprint.id)],
    }


def test_ml_does_not_modify_evidence_sources_or_status():
    db, a, _ = _two_cases()
    before = _snapshot(db)
    ml.run_all(a["incident"], db)
    db.expire_all()
    assert _snapshot(db) == before
