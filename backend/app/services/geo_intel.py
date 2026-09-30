"""
Geographic Intelligence (Phase 2) — aggregation, hotspot rules and activity scoring.

Pure Python (stdlib only) so it can be unit-tested without a database or web framework.
The router (`app/routers/geo.py`) loads stored Phase 1 records and hands them to `analyze()`.

DATA INTEGRITY
  * Nothing here creates coordinates, timestamps, platforms or relationships. Every number is
    aggregated from the records passed in.
  * Inferred locations are never promoted: the location tier of each observation is carried through
    untouched, and the `tier` filter selects on it.
  * Propagation events are only STORED source relationships. Two places being close together never
    creates one.

DEFINITIONS (kept separate everywhere in the UI)
  observation         one located source record, timestamped by Source.observed_at.
  unique source       a distinct source identity: platform + (account | url | source id).
                      Several observations can come from the same identity, so
                      unique_sources <= observations.
  propagation event   one stored SourceRelationship whose two endpoints are both located and both
                      pass the active filters. A location counts an event when either endpoint is there.

ACTIVITY SCORE (NOT a risk / crime / person score)
  points = observations*w_obs + unique_sources*w_src + propagation_events*w_evt, capped at 100.
  Weights and level thresholds are configurable (env vars GEO_WEIGHT_*, GEO_HIGH_SCORE,
  GEO_MEDIUM_SCORE, or query parameters) and are returned with every response so the UI can
  show the exact rule.
"""
from __future__ import annotations

import os
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable

TIERS = ("verified", "investigator", "inferred")
METRICS = ("observations", "unique_sources", "propagation_events")
UNDIRECTED_TYPES = {"same content", "related", "similar", "match", "duplicate", "same media"}

DEFAULT_CONFIG: dict[str, Any] = {
    "weights": {"observations": 3.0, "unique_sources": 5.0, "propagation_events": 6.0},
    "score_cap": 100,
    "thresholds": {"high": 60.0, "medium": 25.0},
}

LEVEL_LABEL = {"high": "High Activity", "medium": "Medium Activity", "low": "Low Activity"}
FACTOR_LABEL = {"observations": "observations", "unique_sources": "unique sources", "propagation_events": "propagation events"}


# --------------------------------------------------------------------------- config
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def load_config(high: float | None = None, medium: float | None = None) -> dict[str, Any]:
    """Defaults <- environment <- explicit (query) overrides. Invalid combinations fall back safely."""
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["weights"]["observations"] = _env_float("GEO_WEIGHT_OBSERVATIONS", cfg["weights"]["observations"])
    cfg["weights"]["unique_sources"] = _env_float("GEO_WEIGHT_UNIQUE_SOURCES", cfg["weights"]["unique_sources"])
    cfg["weights"]["propagation_events"] = _env_float("GEO_WEIGHT_PROPAGATION_EVENTS", cfg["weights"]["propagation_events"])
    cfg["thresholds"]["high"] = _env_float("GEO_HIGH_SCORE", cfg["thresholds"]["high"])
    cfg["thresholds"]["medium"] = _env_float("GEO_MEDIUM_SCORE", cfg["thresholds"]["medium"])
    if high is not None:
        cfg["thresholds"]["high"] = float(high)
    if medium is not None:
        cfg["thresholds"]["medium"] = float(medium)
    t = cfg["thresholds"]
    if not (0 < t["medium"] < t["high"] <= cfg["score_cap"]):
        cfg["thresholds"] = dict(DEFAULT_CONFIG["thresholds"])
    return cfg


# --------------------------------------------------------------------------- helpers
def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def node_key(lat: float, lon: float) -> str:
    """Same ~1 km grouping Phase 1 used, so node ids stay stable between /geo and /geo-stats."""
    return f"{round(lat, 2):.2f},{round(lon, 2):.2f}"


def node_id(key: str) -> str:
    return "LOC-" + key.replace(",", "_").replace("-", "m").replace(".", "p")


def confidence_label(c: float) -> str:
    return "High" if c >= 80 else "Medium" if c >= 55 else "Low"


def source_identity(o: dict) -> str:
    """Distinct-source key. Never invents identity: falls back to the source's own id."""
    ident = (o.get("account") or o.get("url") or o.get("source_id") or "").strip().lower()
    return f"{(o.get('platform') or '').strip().lower()}|{ident}"


def score_location(observations: int, unique_sources: int, events: int, cfg: dict) -> dict:
    w, cap, th = cfg["weights"], cfg["score_cap"], cfg["thresholds"]
    values = {"observations": observations, "unique_sources": unique_sources, "propagation_events": events}
    factors = [
        {"key": k, "label": FACTOR_LABEL[k], "value": values[k], "weight": w[k], "points": round(values[k] * w[k], 2)}
        for k in METRICS
    ]
    raw = round(sum(f["points"] for f in factors), 2)
    score = int(round(min(cap, raw)))
    level = "high" if score >= th["high"] else "medium" if score >= th["medium"] else "low"
    return {"score": score, "raw": raw, "capped": raw > cap, "cap": cap, "level": level,
            "level_label": LEVEL_LABEL[level], "factors": factors}


def edge_direction(sa: dict, sb: dict, rtype: str, confirmed: bool) -> tuple[str, str]:
    """Identical rules to Phase 1: never assert a direction that the data does not support."""
    if rtype in UNDIRECTED_TYPES:
        return "undirected", "Relationship type does not imply a direction."
    if confirmed:
        return "confirmed", "Direction confirmed by investigator."
    if sa["observed_at"] < sb["observed_at"]:
        return "inferred", (
            f"Inferred propagation direction: {sa['label']} observed {sa['observed_at']:%d %b %Y %H:%M} "
            f"before {sb['label']} observed {sb['observed_at']:%d %b %Y %H:%M}. Not confirmed."
        )
    return "undirected", "Recorded link conflicts with or cannot be ordered by observation timestamps; direction is not asserted."


# --------------------------------------------------------------------------- filtering
def _in_window(o: dict, start: datetime | None, end: datetime | None) -> bool:
    t = o["observed_at"]
    return (start is None or t >= start) and (end is None or t <= end)


def _select(observations: Iterable[dict], *, start=None, end=None, platform=None, tier=None) -> list[dict]:
    out = []
    for o in observations:
        if platform and o["platform"] != platform:
            continue
        if tier and o["tier"] != tier:
            continue
        if not _in_window(o, start, end):
            continue
        out.append(o)
    return out


# --------------------------------------------------------------------------- main entry
def analyze(
    observations: list[dict],
    relationships: list[dict],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    platform: str | None = None,
    tier: str | None = None,
    metric: str = "observations",
    config: dict | None = None,
    total_sources: int | None = None,
    relationships_without_locations: int = 0,
) -> dict:
    """
    observations   one dict per located source:
        source_id, label, platform, account, url, similarity, observed_at(datetime), tier, provenance, confidence, basis,
        latitude, longitude, place_name, city, region, country, location_id, created_at(datetime|None),
        evidence_ids[], evidence_labels[]
    relationships  stored source relationships:
        id, from_source_id, to_source_id, type, confidence, direction_confirmed(bool)
    """
    cfg = config or load_config()
    metric = metric if metric in METRICS else "observations"
    tier = tier if tier in TIERS else None
    platform = platform or None

    # ---- what exists at all (independent of any filter) ----
    available_platforms: dict[str, int] = defaultdict(int)
    tier_totals = {t: 0 for t in TIERS}
    for o in observations:
        available_platforms[o["platform"]] += 1
        tier_totals[o["tier"]] += 1
    all_times = [o["observed_at"] for o in observations]

    # ---- filtered set ----
    sel = _select(observations, start=start, end=end, platform=platform, tier=tier)
    sel_by_source = {o["source_id"]: o for o in sel}

    # timeline events ignore the time window (so the timeline can show what a wider range would include)
    no_time = _select(observations, platform=platform, tier=tier)
    timeline_events = sorted(
        ({"t": iso(o["observed_at"]), "source_id": o["source_id"], "label": o["label"], "platform": o["platform"],
          "tier": o["tier"], "node_id": node_id(node_key(o["latitude"], o["longitude"]))} for o in no_time),
        key=lambda e: (e["t"], e["label"]),
    )
    time_index = sorted({e["t"] for e in timeline_events})

    # ---- propagation events: stored relationships with both endpoints located + passing filters ----
    events: list[dict] = []
    for r in relationships:
        sa, sb = sel_by_source.get(r["from_source_id"]), sel_by_source.get(r["to_source_id"])
        if sa and sb:
            events.append({"rel": r, "sa": sa, "sb": sb,
                           "a": node_id(node_key(sa["latitude"], sa["longitude"])),
                           "b": node_id(node_key(sb["latitude"], sb["longitude"]))})
    events_by_node: dict[str, int] = defaultdict(int)
    for ev in events:
        events_by_node[ev["a"]] += 1
        if ev["b"] != ev["a"]:
            events_by_node[ev["b"]] += 1

    # ---- nodes ----
    groups: dict[str, list[dict]] = defaultdict(list)
    for o in sel:
        groups[node_key(o["latitude"], o["longitude"])].append(o)

    nodes: list[dict] = []
    for key, members in groups.items():
        members = sorted(members, key=lambda m: (m["observed_at"], m["label"]))
        nid = node_id(key)
        first = members[0]
        tiers_here = {m["tier"] for m in members}
        ntier = next(iter(tiers_here)) if len(tiers_here) == 1 else "mixed"
        conf = round(sum(m["confidence"] for m in members) / len(members), 1)
        identities = {source_identity(m) for m in members}
        ev_ids = sorted({e for m in members for e in m["evidence_ids"]})
        ev_labels = sorted({e for m in members for e in m["evidence_labels"]})
        place = next((m["place_name"] for m in members if m.get("place_name")), None)
        city = next((m["city"] for m in members if m.get("city")), None)
        region = next((m["region"] for m in members if m.get("region")), None)
        name = place or city or f"{first['latitude']:.3f}, {first['longitude']:.3f}"
        n_events = events_by_node.get(nid, 0)
        activity = score_location(len(members), len(identities), n_events, cfg)
        nodes.append({
            "id": nid, "name": name, "has_name": bool(place or city),
            "city": city, "region": region,
            "country": next((m["country"] for m in members if m.get("country")), None),
            "latitude": first["latitude"], "longitude": first["longitude"],
            "observation_count": len(members),
            "unique_sources": len(identities),
            "propagation_events": n_events,
            "verified_observation_count": sum(1 for m in members if m["tier"] == "verified"),
            "tier_counts": {t: sum(1 for m in members if m["tier"] == t) for t in TIERS},
            "platforms": sorted({m["platform"] for m in members}),
            "first_observed": iso(members[0]["observed_at"]),
            "last_observed": iso(members[-1]["observed_at"]),
            "tier": ntier, "confidence": conf, "confidence_label": confidence_label(conf),
            "source_ids": [m["source_id"] for m in members],
            "source_labels": [m["label"] for m in members],
            "evidence_ids": ev_ids, "evidence_labels": ev_labels,
            "activity": activity,
            "observations": [
                {
                    "source_id": m["source_id"], "label": m["label"], "platform": m["platform"], "account": m.get("account"),
                    "observed_at": iso(m["observed_at"]), "tier": m["tier"], "provenance": m["provenance"],
                    "confidence": m["confidence"], "basis": m.get("basis"),
                    "evidence_ids": m["evidence_ids"], "evidence_labels": m["evidence_labels"],
                    "location_id": m.get("location_id"), "city": m.get("city"), "region": m.get("region"),
                    "country": m.get("country"), "place_name": m.get("place_name"),
                    "latitude": m["latitude"], "longitude": m["longitude"],
                    "location_recorded_at": iso(m.get("created_at")),
                }
                for m in members
            ],
        })
    nodes.sort(key=lambda n: (-n["activity"]["score"], -n["observation_count"], n["id"]))

    # ---- edges (arcs) ----
    edge_bins: dict[tuple, dict] = {}
    for ev in events:
        if ev["a"] == ev["b"]:
            continue
        r, sa, sb = ev["rel"], ev["sa"], ev["sb"]
        rtype = (r["type"] or "").lower()
        mode, basis = edge_direction(sa, sb, rtype, bool(r.get("direction_confirmed")))
        s_n, d_n = ev["a"], ev["b"]
        key = (s_n, d_n, mode) if mode != "undirected" else (*sorted([s_n, d_n]), mode)
        e = edge_bins.setdefault(key, {"source": key[0], "target": key[1], "mode": mode, "basis": basis,
                                       "rels": [], "platforms": set(), "types": set(), "ts": [], "sims": [], "confs": []})
        e["rels"].append({
            "relationship_id": r["id"], "from_label": sa["label"], "to_label": sb["label"],
            "from_platform": sa["platform"], "to_platform": sb["platform"], "type": r["type"], "confidence": r.get("confidence"),
            "from_observed": iso(sa["observed_at"]), "to_observed": iso(sb["observed_at"]),
            "similarity": sb.get("similarity"),
            "evidence_labels": sa["evidence_labels"] + sb["evidence_labels"],
        })
        e["platforms"].update([sa["platform"], sb["platform"]])
        e["types"].add(r["type"])
        e["ts"].append(sb["observed_at"])
        if sb.get("similarity") is not None:
            e["sims"].append(sb["similarity"])
        if r.get("confidence") is not None:
            e["confs"].append(r["confidence"])
    edges = []
    for (s_n, d_n, mode), e in edge_bins.items():
        ts = sorted(e["ts"])
        edges.append({
            "id": f"EDGE-{s_n}>{d_n}:{mode}", "source": e["source"], "target": e["target"], "mode": mode, "basis": e["basis"],
            "count": len(e["rels"]), "platforms": sorted(e["platforms"]), "types": sorted(e["types"]),
            "first_timestamp": iso(ts[0]), "last_timestamp": iso(ts[-1]),
            "similarity": round(sum(e["sims"]) / len(e["sims"]), 1) if e["sims"] else None,
            "confidence": round(sum(e["confs"]) / len(e["confs"]), 1) if e["confs"] else None,
            "relationships": e["rels"],
        })
    edges.sort(key=lambda x: x["id"])

    # ---- hotspots (transparent rule: score thresholds) ----
    hotspots = [
        {"rank": i + 1, "id": n["id"], "name": n["name"], "level": n["activity"]["level"],
         "level_label": n["activity"]["level_label"], "score": n["activity"]["score"],
         "observations": n["observation_count"], "unique_sources": n["unique_sources"],
         "propagation_events": n["propagation_events"]}
        for i, n in enumerate(nodes)
    ]

    # ---- earliest observed (an upload/observation timestamp — NOT proof of origin) ----
    earliest = None
    if sel:
        e0 = min(sel, key=lambda o: (o["observed_at"], o["label"]))
        nid0 = node_id(node_key(e0["latitude"], e0["longitude"]))
        n0 = next(n for n in nodes if n["id"] == nid0)
        earliest = {"node_id": nid0, "name": n0["name"], "observed_at": iso(e0["observed_at"]), "source_id": e0["source_id"],
                    "source_label": e0["label"], "platform": e0["platform"], "tier": e0["tier"]}

    heat_max = {
        "observations": max((n["observation_count"] for n in nodes), default=0),
        "unique_sources": max((n["unique_sources"] for n in nodes), default=0),
        "propagation_events": max((n["propagation_events"] for n in nodes), default=0),
    }
    heat_key = {"observations": "observation_count", "unique_sources": "unique_sources", "propagation_events": "propagation_events"}[metric]
    heat_points = [
        {"id": n["id"], "latitude": n["latitude"], "longitude": n["longitude"], "value": n[heat_key],
         "weight": round(n[heat_key] / heat_max[metric], 4) if heat_max[metric] else 0.0, "level": n["activity"]["level"]}
        for n in nodes if n[heat_key] > 0
    ]

    all_identities = {source_identity(o) for o in sel}
    summary = {
        "observations": len(sel), "unique_sources": len(all_identities),
        "platforms": sorted({o["platform"] for o in sel}), "unique_platforms": len({o["platform"] for o in sel}),
        "propagation_events": len(events), "cross_location_events": sum(1 for ev in events if ev["a"] != ev["b"]),
        "locations": len(nodes),
        "verified_observations": sum(1 for o in sel if o["tier"] == "verified"),
        "investigator_observations": sum(1 for o in sel if o["tier"] == "investigator"),
        "inferred_observations": sum(1 for o in sel if o["tier"] == "inferred"),
        "first_observed": iso(min((o["observed_at"] for o in sel), default=None)),
        "last_observed": iso(max((o["observed_at"] for o in sel), default=None)),
        "total_sources": total_sources, "located_sources": len(observations),
        "relationships_without_locations": relationships_without_locations,
        "high_activity": sum(1 for n in nodes if n["activity"]["level"] == "high"),
        "medium_activity": sum(1 for n in nodes if n["activity"]["level"] == "medium"),
        "low_activity": sum(1 for n in nodes if n["activity"]["level"] == "low"),
    }

    return {
        "filters": {"start": iso(start), "end": iso(end), "platform": platform, "tier": tier, "metric": metric},
        "config": cfg,
        "summary": summary,
        "available": {
            "platforms": [{"platform": p, "observations": c} for p, c in sorted(available_platforms.items())],
            "tiers": tier_totals,
            "time_range": {"start": iso(min(all_times, default=None)), "end": iso(max(all_times, default=None))},
            "total_observations": len(observations),
        },
        "nodes": nodes, "edges": edges, "hotspots": hotspots, "earliest_observed": earliest,
        "heat": {"metric": metric, "max": heat_max, "points": heat_points},
        "time_index": time_index, "timeline_events": timeline_events,
        "empty_reason": _empty_reason(observations, sel, platform, tier),
    }


def _empty_reason(all_obs: list[dict], sel: list[dict], platform: str | None, tier: str | None) -> str | None:
    if sel:
        return None
    if not all_obs:
        return "no_locations"
    if platform and not any(o["platform"] == platform for o in all_obs):
        return "no_platform"
    pool = [o for o in all_obs if not platform or o["platform"] == platform]
    if tier and not any(o["tier"] == tier for o in pool):
        return f"no_{tier}"
    return "no_time_range"


def flat_observations(observations: list[dict], *, platform: str | None = None, tier: str | None = None,
                      start: datetime | None = None, end: datetime | None = None) -> list[dict]:
    """Provenance-preserving flat list (location_id, lat/lon, city/region/country, type, confidence,
    source_id, evidence_id(s), observed_at, created_at) — one row per stored SourceLocation."""
    rows = _select(observations, start=start, end=end, platform=platform, tier=tier)
    return [
        {
            "location_id": o.get("location_id"), "latitude": o["latitude"], "longitude": o["longitude"],
            "city": o.get("city"), "region": o.get("region"), "country": o.get("country"), "place_name": o.get("place_name"),
            "location_type": o["tier"], "provenance": o["provenance"], "confidence": o["confidence"],
            "source_id": o["source_id"], "source_label": o["label"], "platform": o["platform"],
            "evidence_ids": o["evidence_ids"], "evidence_labels": o["evidence_labels"],
            "observed_at": iso(o["observed_at"]), "created_at": iso(o.get("created_at")),
        }
        for o in sorted(rows, key=lambda r: (r["observed_at"], r["label"]))
    ]
