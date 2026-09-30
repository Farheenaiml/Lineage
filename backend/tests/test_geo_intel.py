"""Unit tests for Phase 2 geographic intelligence (pure logic — no DB / web framework needed).
Run:  python tests/test_geo_intel.py     (or: pytest tests/test_geo_intel.py)
Fixtures here are TEST-ONLY in-memory records; nothing is written to any investigation."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import geo_intel as G  # noqa: E402

T0 = datetime(2026, 1, 1, 9, 0)
MUM, DEL, LON = (19.076, 72.8777), (28.6139, 77.209), (51.5074, -0.1278)


def obs(i, plat, at, loc, tier="investigator", account=None, name=None, conf=60, ev=()):
    return {"source_id": f"s{i}", "label": f"SRC-{chr(65 + i)}", "platform": plat, "account": account if account is not None else f"acct{i}",
            "url": None, "similarity": 90.0, "observed_at": T0 + timedelta(minutes=at), "tier": tier,
            "provenance": {"verified": "exif_gps", "investigator": "investigator_supplied", "inferred": "inferred"}[tier],
            "confidence": conf, "basis": "test", "latitude": loc[0], "longitude": loc[1], "place_name": name, "city": None,
            "region": None, "country": None, "location_id": f"L{i}", "created_at": T0,
            "evidence_ids": [f"e{i}"] if i in ev else [], "evidence_labels": [f"EV-{i}"] if i in ev else []}


def rel(i, a, b, t="repost", confirmed=False):
    return {"id": f"r{i}", "from_source_id": f"s{a}", "to_source_id": f"s{b}", "type": t, "confidence": 70, "direction_confirmed": confirmed}


def node(res, nid_prefix):
    return next(n for n in res["nodes"] if n["latitude"] == nid_prefix[0])


def test_no_locations():
    r = G.analyze([], [])
    assert r["nodes"] == [] and r["empty_reason"] == "no_locations" and r["earliest_observed"] is None
    assert r["summary"]["observations"] == 0 and r["heat"]["points"] == []


def test_single_location_is_not_padded():
    r = G.analyze([obs(0, "Instagram", 0, MUM, name="Mumbai")], [])
    assert len(r["nodes"]) == 1 and r["nodes"][0]["name"] == "Mumbai"
    assert r["nodes"][0]["observation_count"] == 1 and r["empty_reason"] is None
    assert r["heat"]["points"][0]["weight"] == 1.0


def test_observations_vs_unique_sources_are_separate():
    # 4 observations at Mumbai from only 2 distinct source identities
    o = [obs(0, "Instagram", 0, MUM, account="@a"), obs(1, "Instagram", 10, MUM, account="@a"),
         obs(2, "Telegram", 20, MUM, account="@b"), obs(3, "Telegram", 30, MUM, account="@b")]
    n = G.analyze(o, [])["nodes"][0]
    assert n["observation_count"] == 4 and n["unique_sources"] == 2
    assert n["platforms"] == ["Instagram", "Telegram"]


def test_propagation_events_only_from_stored_relationships():
    o = [obs(0, "X", 0, MUM), obs(1, "X", 60, DEL)]
    none = G.analyze(o, [])
    assert none["summary"]["propagation_events"] == 0 and none["edges"] == []   # close/far places create nothing
    r = G.analyze(o, [rel(1, 0, 1)])
    assert r["summary"]["propagation_events"] == 1 and len(r["edges"]) == 1
    assert r["edges"][0]["mode"] == "inferred"          # timestamps order it, not confirmed
    assert all(n["propagation_events"] == 1 for n in r["nodes"])
    c = G.analyze(o, [rel(1, 0, 1, confirmed=True)])
    assert c["edges"][0]["mode"] == "confirmed"
    u = G.analyze(o, [rel(1, 0, 1, t="same content")])
    assert u["edges"][0]["mode"] == "undirected"
    rev = G.analyze(o, [rel(1, 1, 0)])                   # link runs against timestamps -> no direction asserted
    assert rev["edges"][0]["mode"] == "undirected"


def test_intra_location_relationship_counts_once_and_has_no_arc():
    o = [obs(0, "X", 0, MUM), obs(1, "Y", 5, MUM)]
    r = G.analyze(o, [rel(1, 0, 1)])
    assert r["nodes"][0]["propagation_events"] == 1 and r["edges"] == [] and r["summary"]["propagation_events"] == 1


def test_time_window_filters_everything_consistently():
    o = [obs(0, "X", 0, MUM), obs(1, "X", 120, DEL), obs(2, "X", 300, LON)]
    rels = [rel(1, 0, 1), rel(2, 1, 2)]
    early = G.analyze(o, rels, start=T0, end=T0 + timedelta(minutes=60))
    assert [n["latitude"] for n in early["nodes"]] == [MUM[0]] and early["edges"] == []
    mid = G.analyze(o, rels, start=T0, end=T0 + timedelta(minutes=180))
    assert len(mid["nodes"]) == 2 and len(mid["edges"]) == 1 and mid["summary"]["propagation_events"] == 1
    late = G.analyze(o, rels, start=T0 + timedelta(minutes=200), end=T0 + timedelta(minutes=400))
    assert len(late["nodes"]) == 1 and late["summary"]["propagation_events"] == 0   # relationship 2 needs DEL (outside)
    empty = G.analyze(o, rels, start=T0 + timedelta(days=5), end=T0 + timedelta(days=6))
    assert empty["nodes"] == [] and empty["empty_reason"] == "no_time_range"


def test_tier_filter_never_mixes_and_never_promotes():
    o = [obs(0, "X", 0, MUM, tier="verified"), obs(1, "X", 1, DEL, tier="investigator"), obs(2, "X", 2, LON, tier="inferred")]
    v = G.analyze(o, [], tier="verified")
    assert [n["tier"] for n in v["nodes"]] == ["verified"] and v["summary"]["verified_observations"] == 1
    assert G.analyze(o, [], tier="inferred")["summary"]["verified_observations"] == 0
    only_inv = [obs(0, "X", 0, MUM, tier="investigator")]
    e = G.analyze(only_inv, [], tier="verified")
    assert e["nodes"] == [] and e["empty_reason"] == "no_verified"          # inferred/supplied never shown as verified
    assert G.analyze(o, [])["available"]["tiers"] == {"verified": 1, "investigator": 1, "inferred": 1}


def test_mixed_tier_node():
    o = [obs(0, "X", 0, MUM, tier="verified"), obs(1, "X", 1, MUM, tier="investigator")]
    n = G.analyze(o, [])["nodes"][0]
    assert n["tier"] == "mixed" and n["tier_counts"] == {"verified": 1, "investigator": 1, "inferred": 0}


def test_platform_filter_and_no_invented_platforms():
    o = [obs(0, "Instagram", 0, MUM), obs(1, "Telegram", 1, DEL)]
    r = G.analyze(o, [], platform="Instagram")
    assert len(r["nodes"]) == 1 and r["nodes"][0]["platforms"] == ["Instagram"]
    assert [p["platform"] for p in r["available"]["platforms"]] == ["Instagram", "Telegram"]   # only real ones
    miss = G.analyze(o, [], platform="Facebook")
    assert miss["nodes"] == [] and miss["empty_reason"] == "no_platform"


def test_relationship_dropped_when_platform_filter_removes_endpoint():
    o = [obs(0, "Instagram", 0, MUM), obs(1, "Telegram", 60, DEL)]
    r = G.analyze(o, [rel(1, 0, 1)], platform="Instagram")
    assert r["summary"]["propagation_events"] == 0 and r["edges"] == []


def test_activity_score_is_transparent_and_matches_spec_examples():
    cfg = G.load_config()
    hi = G.score_location(14, 5, 3, cfg)          # 42 + 25 + 18 = 85
    assert hi["score"] == 85 and hi["level"] == "high"
    assert [f["points"] for f in hi["factors"]] == [42.0, 25.0, 18.0]
    assert G.score_location(7, 3, 0, cfg)["level"] == "medium"
    assert G.score_location(2, 1, 0, cfg)["level"] == "low"
    capped = G.score_location(40, 20, 10, cfg)
    assert capped["score"] == 100 and capped["capped"] and capped["raw"] > 100


def test_thresholds_configurable_and_invalid_falls_back():
    c = G.load_config(high=90, medium=50)
    assert G.score_location(14, 5, 3, c)["level"] == "medium"        # 85 < 90
    bad = G.load_config(high=10, medium=50)                            # medium >= high -> defaults
    assert bad["thresholds"] == G.DEFAULT_CONFIG["thresholds"]


def test_hotspots_sorted_and_no_risk_language():
    o = [obs(i, "X", i, MUM, account=f"a{i}") for i in range(6)] + [obs(6, "X", 7, DEL)]
    r = G.analyze(o, [])
    assert r["hotspots"][0]["name"].startswith("19.076") and r["hotspots"][0]["score"] >= r["hotspots"][1]["score"]
    assert {h["level_label"] for h in r["hotspots"]} <= {"High Activity", "Medium Activity", "Low Activity"}
    blob = str(r).lower()
    assert "dangerous" not in blob and "malicious" not in blob


def test_earliest_observed_never_called_origin():
    o = [obs(0, "X", 50, DEL, name="Delhi"), obs(1, "X", 10, MUM, name="Mumbai"), obs(2, "X", 90, LON)]
    e = G.analyze(o, [])["earliest_observed"]
    assert e["name"] == "Mumbai" and e["source_label"] == "SRC-B"
    assert "origin" not in " ".join(e.keys()).lower()


def test_heat_metric_weights():
    o = [obs(0, "X", 0, MUM, account="a"), obs(1, "X", 1, MUM, account="a"), obs(2, "X", 2, MUM, account="a"), obs(3, "X", 3, DEL, account="b")]
    r = G.analyze(o, [], metric="observations")
    w = {p["latitude"]: p["weight"] for p in r["heat"]["points"]}
    assert w[MUM[0]] == 1.0 and abs(w[DEL[0]] - 1 / 3) < 1e-3
    u = G.analyze(o, [], metric="unique_sources")            # 1 unique source each -> equal intensity
    assert {p["weight"] for p in u["heat"]["points"]} == {1.0}
    p = G.analyze(o, [rel(1, 0, 3)], metric="propagation_events")
    assert len(p["heat"]["points"]) == 2 and G.analyze(o, [], metric="propagation_events")["heat"]["points"] == []


def test_same_location_multiple_observations_single_node():
    o = [obs(i, "X", i, (19.0761, 72.8778)) for i in range(3)]          # within rounding of the same node
    assert len(G.analyze(o, [])["nodes"]) == 1


def test_stable_ids_across_filters():
    o = [obs(0, "X", 0, MUM), obs(1, "X", 60, DEL)]
    a = G.analyze(o, [rel(1, 0, 1)])
    b = G.analyze(o, [rel(1, 0, 1)], start=T0)
    assert a["edges"][0]["id"] == b["edges"][0]["id"] and a["nodes"][0]["id"] == b["nodes"][0]["id"]


def test_flat_observations_keep_provenance_fields():
    rows = G.flat_observations([obs(0, "X", 0, MUM, tier="verified", ev=(0,))])
    need = {"location_id", "latitude", "longitude", "city", "region", "country", "location_type", "confidence",
            "source_id", "evidence_ids", "observed_at", "created_at"}
    assert need <= set(rows[0]) and rows[0]["location_type"] == "verified" and rows[0]["evidence_ids"] == ["e0"]


def test_timeline_index_ignores_window_but_respects_filters():
    o = [obs(0, "X", 0, MUM), obs(1, "Y", 60, DEL)]
    r = G.analyze(o, [], start=T0 + timedelta(minutes=30), end=T0 + timedelta(minutes=90), platform="X")
    assert r["nodes"] == [] and len(r["time_index"]) == 1


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("FAIL", name, "->", repr(e))
    sys.exit(1 if fails else 0)
