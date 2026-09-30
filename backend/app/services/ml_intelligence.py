"""
Phase 4 — ML Intelligence: media similarity, anomaly detection (unusual patterns), media/source clustering.

Local and deterministic (NumPy only). Inputs are records LINEAGE already stores:
  * Fingerprint.average_hash (64-bit aHash), keyframe_hashes_json (video), face_embedding_json (stored FaceNet vector)
  * the investigation graph from Phase 3 (`graph_sync.load_graph` — Neo4j when reachable, in-memory otherwise) for
    sources, platforms, locations, relationships, evidence and their stored statuses.

Integrity rules
  * Similarity is NOT identity. Results say "visually similar"; they never say two files / people / sources are the same.
  * Anomalies are UNUSUAL PATTERNS measured against the investigation's OWN baseline, with the factors that triggered
    them. They are not evidence of malicious activity. No external or invented baseline is used; too little data ->
    "Insufficient data."
  * Clusters group visually similar media; they do not indicate identity, ownership or responsibility.
  * Every result carries model name + version, computed_at, score, factors and evidence references.
  * Nothing here writes to evidence, sources, locations or relationship statuses. Results are analysis, not facts.
"""
from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from statistics import median
from typing import Iterable

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.incident import Incident
from app.models.media import Fingerprint, MediaItem
from app.services import graph_sync
from app.services import knowledge_graph as kg

SIMILARITY_MODEL = {"model_name": "lineage-visual-similarity", "model_version": "4.0.0",
                    "method": "Hamming similarity of stored 64-bit average hashes (keyframe hashes for video); cosine "
                              "similarity of stored face embeddings reported as a separate factor."}
ANOMALY_MODEL = {"model_name": "lineage-anomaly-rules", "model_version": "4.0.0",
                 "method": "Robust (median-based) thresholds computed from this investigation's own observation "
                           "intervals, relationship timings and recorded locations."}
CLUSTER_MODEL = {"model_name": "lineage-single-linkage-clustering", "model_version": "4.0.0",
                 "method": "Single-linkage grouping (connected components) of media whose visual similarity meets the "
                           "cluster threshold."}

SIMILARITY_DISCLAIMER = ("Similarity is not identity: a visual similarity score does not establish that two files, the "
                         "people depicted, or the sources are the same.")
ANOMALY_DISCLAIMER = ("An unusual pattern is a statistical observation relative to this investigation's own data. It is "
                      "not evidence of malicious activity or coordination.")
CLUSTER_DISCLAIMER = ("Clusters group visually similar media. They do not indicate who created, owns, posted or is "
                      "responsible for any item.")
INSUFFICIENT = "Insufficient data."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---- per-request graph memo (Phase 6 performance fix) ----
# One API request can need the same investigation graph several times (summary + ML + report). Each Phase 3
# `load_graph` call rebuilds the graph and re-syncs it to Neo4j, so inside a `graph_memo()` block the result is reused.
# The memo lives only for that block (one request) — nothing is cached across requests, so data is never stale.
_GRAPH_MEMO: ContextVar[dict | None] = ContextVar("lineage_graph_memo", default=None)


@contextmanager
def graph_memo():
    token = _GRAPH_MEMO.set({}) if _GRAPH_MEMO.get() is None else None
    try:
        yield
    finally:
        if token is not None:
            _GRAPH_MEMO.reset(token)


def load_graph(incident: Incident, db: Session):
    """Phase 3 `graph_sync.load_graph` (Neo4j or fallback), memoised per investigation inside a `graph_memo()` block."""
    memo = _GRAPH_MEMO.get()
    if memo is None:
        return graph_sync.load_graph(incident, db)
    if incident.id not in memo:
        memo[incident.id] = graph_sync.load_graph(incident, db)
    return memo[incident.id]


def _rid(prefix: str, *parts: str) -> str:
    return f"{prefix}:{hashlib.sha1('|'.join(sorted(parts)).encode()).hexdigest()[:12]}"


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def _human(seconds: float) -> str:
    s = abs(seconds)
    if s < 90:
        return f"{s:.0f} seconds"
    if s < 5400:
        return f"{s / 60:.0f} minutes"
    if s < 172800:
        return f"{s / 3600:.1f} hours"
    return f"{s / 86400:.1f} days"


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


# =========================================================================== features
def _hash_bits(h: str) -> int | None:
    try:
        return int(h, 16)
    except (TypeError, ValueError):
        return None


def ahash_similarity(a: str, b: str) -> tuple[float, int, int] | None:
    """(similarity 0-1, differing bits, total bits) for two hex perceptual hashes of equal length, else None."""
    if not a or not b or len(a) != len(b):
        return None
    x, y = _hash_bits(a), _hash_bits(b)
    if x is None or y is None:
        return None
    bits = len(a) * 4
    diff = bin(x ^ y).count("1")
    return round(1 - diff / bits, 4), diff, bits


def keyframe_similarity(a: list[str], b: list[str]) -> float | None:
    """Symmetric mean of best-match aHash similarity across keyframes."""
    if not a or not b:
        return None

    def best(xs, ys):
        vals = []
        for x in xs:
            sims = [s[0] for s in (ahash_similarity(x, y) for y in ys) if s]
            if sims:
                vals.append(max(sims))
        return sum(vals) / len(vals) if vals else None

    ab, ba = best(a, b), best(b, a)
    if ab is None or ba is None:
        return None
    return round((ab + ba) / 2, 4)


def cosine(a: np.ndarray, b: np.ndarray) -> float | None:
    if a is None or b is None or a.shape != b.shape:
        return None
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return None
    return round(float(np.dot(a, b) / (na * nb)), 4)


def parse_keyframes(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(v, dict):
        v = v.get("hashes") or list(v.values())
    out = []
    for item in v if isinstance(v, list) else []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("hash"), str):
            out.append(item["hash"])
    return out


def parse_face(raw: str | None) -> np.ndarray | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return None
    emb = v.get("embedding") if isinstance(v, dict) and v.get("found_face") else None
    if not emb:
        return None
    try:
        arr = np.asarray(emb, dtype=float)
    except (TypeError, ValueError):
        return None
    return arr if arr.ndim == 1 and arr.size > 0 else None


def media_features(db: Session, incident_ids: Iterable[str]) -> list[dict]:
    """One feature dict per media item that has a stored fingerprint (media without one cannot be compared)."""
    ids = list(incident_ids)
    if not ids:
        return []
    incidents = {i.id: i for i in db.query(Incident).filter(Incident.id.in_(ids)).all()}
    rows = (db.query(MediaItem, Fingerprint).join(Fingerprint, Fingerprint.media_item_id == MediaItem.id)
            .filter(MediaItem.incident_id.in_(ids)).order_by(MediaItem.uploaded_at).all())
    out = []
    for m, f in rows:
        out.append({
            "media_id": m.id, "incident_id": m.incident_id, "incident_title": incidents[m.incident_id].title,
            "filename": m.original_filename, "kind": m.kind, "fingerprint_id": f.id,
            "fingerprint_created_at": f.created_at.isoformat() + "Z" if f.created_at else None,
            "average_hash": f.average_hash, "keyframes": parse_keyframes(f.keyframe_hashes_json), "face": parse_face(f.face_embedding_json),
        })
    return out


def compare(a: dict, b: dict) -> dict | None:
    """Score one pair. `score` is VISUAL similarity; face-embedding cosine is an additional, separately labelled factor."""
    factors = []
    visual = None
    if a["keyframes"] and b["keyframes"]:
        visual = keyframe_similarity(a["keyframes"], b["keyframes"])
        if visual is not None:
            factors.append({"name": "keyframe_hash_similarity", "value": visual,
                            "detail": f"Mean best-match similarity across {len(a['keyframes'])} and {len(b['keyframes'])} stored keyframe hashes."})
    ah = ahash_similarity(a["average_hash"], b["average_hash"])
    if ah:
        factors.append({"name": "average_hash_similarity", "value": ah[0],
                        "detail": f"{ah[1]} of {ah[2]} perceptual-hash bits differ."})
        if visual is None:
            visual = ah[0]
    if visual is None:
        return None
    face = cosine(a["face"], b["face"])
    if face is not None:
        factors.append({"name": "face_embedding_cosine", "value": face,
                        "detail": "Cosine similarity of the stored face embeddings. Reported separately; it is a measure of "
                                  "visual resemblance of facial features, not an identification of a person, and does not "
                                  "change the visual score."})
    else:
        factors.append({"name": "face_embedding_cosine", "value": None,
                        "detail": "Not available: a stored face embedding is missing for at least one item."})
    return {"score": round(visual, 4), "factors": factors}


def similarity_label(score: float) -> str:
    if score >= 0.95:
        return "Visually similar (near-identical visual fingerprint)"
    if score >= 0.85:
        return "Visually similar"
    return "Somewhat visually similar"


# =========================================================================== graph linkage (read-only)
class _Graphs:
    """Per-request cache of investigation graphs, loaded through Phase 3 `graph_sync.load_graph` (Neo4j or fallback)."""

    def __init__(self, db: Session):
        self.db, self._g, self.sources = db, {}, {}

    def get(self, incident_id: str) -> kg.KnowledgeGraph | None:
        if incident_id not in self._g:
            inc = self.db.get(Incident, incident_id)
            if inc is None:
                self._g[incident_id] = None
            else:
                g, src = load_graph(inc, self.db)
                self._g[incident_id], self.sources[incident_id] = g, src
        return self._g[incident_id]


def _location_of(g: kg.KnowledgeGraph, source_node: str) -> dict | None:
    for r in g.connected(source_node)["relationships"]:
        if r["type"] == "LOCATED_AT" and r["source"] == source_node:
            loc = g.get_node(r["target"])
            m = loc["metadata"]
            return {"location_node_id": loc["id"], "map_node_id": m.get("map_node_id"), "label": loc["label"],
                    "latitude": m.get("latitude"), "longitude": m.get("longitude"), "city": m.get("city"),
                    "region": m.get("region"), "country": m.get("country"), "status": r["status"],
                    "confidence": r["confidence"], "evidence_id": r.get("evidence_id")}
    return None


def _evidence_of(g: kg.KnowledgeGraph, node_id: str) -> list[dict]:
    out = []
    for r in g.connected(node_id)["relationships"]:
        if r["type"] == "SUPPORTED_BY" and r["source"] == node_id:
            e = g.get_node(r["target"])
            out.append({"evidence_id": e["metadata"]["record_id"], "code": e["metadata"].get("code"),
                        "item_type": e["metadata"].get("item_type"), "captured_at": e["metadata"].get("captured_at")})
    return out


def source_context(g: kg.KnowledgeGraph, source_node: str, incident_id: str) -> dict:
    s = g.get_node(source_node)
    m = s["metadata"]
    return {"source_id": m["record_id"], "node_id": source_node, "incident_id": incident_id, "code": m.get("code"),
            "label": s["label"], "platform": m.get("platform"), "account": m.get("account"), "observed_at": m.get("observed_at"),
            "location": _location_of(g, source_node), "evidence": _evidence_of(g, source_node)}


def media_context(g: kg.KnowledgeGraph | None, media_id: str, incident_id: str) -> dict:
    """Sources the media APPEARS_IN (with that link's stored status), their platforms/locations, and evidence."""
    nid = f"media:{media_id}"
    if g is None or not g.has_node(nid):
        return {"sources": [], "platforms": [], "locations": [], "evidence": []}
    sources = []
    for r in g.connected(nid)["relationships"]:
        if r["type"] == "APPEARS_IN" and r["source"] == nid:
            sc = source_context(g, r["target"], incident_id)
            sc["appears_in_status"] = r["status"]          # "recorded" or "incident_scoped" — never upgraded
            sources.append(sc)
    evidence = _evidence_of(g, nid)
    for s in sources:
        evidence += [e for e in s["evidence"] if e not in evidence]
    locs = []
    for s in sources:
        if s["location"] and s["location"]["location_node_id"] not in {l["location_node_id"] for l in locs}:
            locs.append(s["location"])
    return {"sources": sources, "platforms": sorted({s["platform"] for s in sources if s["platform"]}),
            "locations": locs, "evidence": evidence}


def _scope_incidents(incident: Incident, db: Session, scope: str) -> list[str]:
    if scope == "investigation":
        return [incident.id]
    return [i.id for i in db.query(Incident).filter(Incident.owner_id == incident.owner_id).all()]


# =========================================================================== similarity
def run_similarity(incident: Incident, db: Session, *, scope: str = "owner", threshold: float | None = None) -> dict:
    """Compare this investigation's fingerprinted media with other fingerprinted media in scope
    ('investigation', or 'owner' = every investigation owned by the same investigator)."""
    s = get_settings()
    threshold = s.ML_SIMILARITY_THRESHOLD if threshold is None else threshold
    base = {"analysis": "similarity", "scope": scope, "threshold": threshold, "computed_at": _now(),
            "provenance": SIMILARITY_MODEL, "disclaimer": SIMILARITY_DISCLAIMER}
    feats = media_features(db, _scope_incidents(incident, db, scope))
    mine = [f for f in feats if f["incident_id"] == incident.id]
    if not mine:
        return {**base, "status": "insufficient_data", "message": f"{INSUFFICIENT} No media in this investigation has a stored fingerprint.",
                "results": [], "pairs_compared": 0}
    others = [f for f in feats if f["media_id"] not in {m["media_id"] for m in mine}]
    pool = [(a, b) for i, a in enumerate(mine) for b in mine[i + 1:]] + [(a, b) for a in mine for b in others]
    if not pool:
        return {**base, "status": "insufficient_data",
                "message": f"{INSUFFICIENT} There is no other fingerprinted media in scope to compare with.", "results": [], "pairs_compared": 0}
    graphs = _Graphs(db)
    results = []
    for a, b in pool:
        c = compare(a, b)
        if not c or c["score"] < threshold:
            continue
        ctx_a, ctx_b = media_context(graphs.get(a["incident_id"]), a["media_id"], a["incident_id"]), \
            media_context(graphs.get(b["incident_id"]), b["media_id"], b["incident_id"])
        diff = next((f for f in c["factors"] if f["name"] == "average_hash_similarity"), None)
        results.append({
            "id": _rid("similarity", a["media_id"], b["media_id"]), "kind": "similarity", "score": c["score"],
            "label": similarity_label(c["score"]),
            "media": {"media_id": a["media_id"], "filename": a["filename"], "incident_id": a["incident_id"], **ctx_a},
            "match": {"media_id": b["media_id"], "filename": b["filename"], "incident_id": b["incident_id"],
                      "incident_title": b["incident_title"], "same_investigation": b["incident_id"] == incident.id, **ctx_b},
            "factors": c["factors"],
            "explanation": f"{similarity_label(c['score'])}: '{a['filename']}' and '{b['filename']}' have a visual similarity of "
                           f"{c['score']:.2f}" + (f" ({diff['detail'].rstrip('.')})" if diff else "") + f". {SIMILARITY_DISCLAIMER}",
            "evidence_refs": {"fingerprint_ids": [a["fingerprint_id"], b["fingerprint_id"]],
                              "evidence_ids": sorted({e["evidence_id"] for e in ctx_a["evidence"] + ctx_b["evidence"]})},
            "provenance": {**SIMILARITY_MODEL, "computed_at": base["computed_at"], "score": c["score"],
                           "inputs": {"fingerprints": [{"id": a["fingerprint_id"], "created_at": a["fingerprint_created_at"]},
                                                       {"id": b["fingerprint_id"], "created_at": b["fingerprint_created_at"]}]},
                           "graph_source": {k: v.get("backend") for k, v in graphs.sources.items()}},
        })
    results.sort(key=lambda r: -r["score"])
    return {**base, "status": "ok", "results": results, "pairs_compared": len(pool),
            "message": None if results else f"No media pair reached the similarity threshold ({threshold:.2f})."}


# =========================================================================== anomalies (pure core)
def detect_anomalies(observations: list[dict], relationships: list[dict], cfg: dict) -> dict:
    """
    observations:  [{source_id, node_id, code, platform, t: datetime, location: {location_node_id, map_node_id, label, latitude, longitude, status}|None, evidence_ids}]
    relationships: [{relationship_id, rel_graph_id, type, status, from_node, to_node, from_code, to_code, t_from, t_to}]
    Returns {detectors: [...], anomalies: [...]} — baselines come only from these inputs.
    """
    detectors, anomalies = [], []
    obs = sorted([o for o in observations if o.get("t")], key=lambda o: o["t"])
    intervals = [(obs[i + 1]["t"] - obs[i]["t"]).total_seconds() for i in range(len(obs) - 1)]
    med = median(intervals) if intervals else None
    base_ok = len(obs) >= cfg["min_obs"] and med is not None and med > 0

    # ---- A. observation bursts (sudden increase / many sources in a short window) ----
    if not base_ok:
        detectors.append({"detector": "observation_burst", "status": "insufficient_data",
                          "reason": f"{INSUFFICIENT} Needs at least {cfg['min_obs']} timed observations with a non-zero median interval (have {len(obs)})."})
    else:
        detectors.append({"detector": "observation_burst", "status": "ran",
                          "baseline": {"observations": len(obs), "median_interval_seconds": med, "median_interval": _human(med)}})
        fast = [iv < med * cfg["burst_ratio"] for iv in intervals]
        i = 0
        while i < len(fast):
            if not fast[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(fast) and fast[j + 1]:
                j += 1
            members = obs[i:j + 2]
            if len(members) >= 3:
                span = (members[-1]["t"] - members[0]["t"]).total_seconds()
                mean_iv = span / (len(members) - 1)
                plats = sorted({m["platform"] for m in members if m["platform"]})
                expl = (f"Flagged because {len(members)} observations occurred across {len(plats)} platform(s) within {_human(span)}, "
                        f"an average of {_human(mean_iv)} apart, compared with this investigation's median observation interval of {_human(med)}.")
                anomalies.append({
                    "id": _rid("anomaly", "burst", *[m["source_id"] for m in members]), "kind": "anomaly", "type": "observation_burst",
                    "title": "Unusual pattern: many observations in a short window",
                    "score": round(min(1.0, max(0.0, 1 - mean_iv / med)), 4),
                    "factors": [
                        {"name": "observations_in_window", "value": len(members)},
                        {"name": "window", "value": _human(span), "seconds": span},
                        {"name": "platforms", "value": plats},
                        {"name": "mean_interval_in_window", "value": _human(mean_iv), "seconds": mean_iv},
                        {"name": "baseline_median_interval", "value": _human(med), "seconds": med},
                        {"name": "threshold", "value": f"each interval < {cfg['burst_ratio']} x median"},
                    ],
                    "explanation": expl,
                    "window": {"start": members[0]["t"].isoformat() + "Z", "end": members[-1]["t"].isoformat() + "Z"},
                    "source_ids": [m["source_id"] for m in members], "node_ids": [m["node_id"] for m in members],
                    "location_node_ids": sorted({m["location"]["location_node_id"] for m in members if m["location"]}),
                    "relationship_ids": [], "evidence_ids": sorted({e for m in members for e in m["evidence_ids"]}),
                })
            i = j + 1

    # ---- B. unusually rapid propagation (relationship timing) ----
    timed = [r for r in relationships if r.get("t_from") and r.get("t_to")]
    deltas = [abs((r["t_to"] - r["t_from"]).total_seconds()) for r in timed]
    rmed = median(deltas) if deltas else None
    if len(timed) < cfg["min_rels"] or not rmed:
        detectors.append({"detector": "rapid_propagation", "status": "insufficient_data",
                          "reason": f"{INSUFFICIENT} Needs at least {cfg['min_rels']} relationships whose two sources both have observation times, with a non-zero median gap (have {len(timed)})."})
    else:
        detectors.append({"detector": "rapid_propagation", "status": "ran",
                          "baseline": {"timed_relationships": len(timed), "median_gap_seconds": rmed, "median_gap": _human(rmed)}})
        for r, d in zip(timed, deltas):
            if d < rmed * cfg["burst_ratio"]:
                arrow = "→" if r["type"] == "PROPAGATES_TO" else "and"
                anomalies.append({
                    "id": _rid("anomaly", "rapid", r["relationship_id"]), "kind": "anomaly", "type": "rapid_propagation",
                    "title": "Unusual pattern: unusually rapid spread between two sources",
                    "score": round(min(1.0, max(0.0, 1 - d / rmed)), 4),
                    "factors": [
                        {"name": "gap_between_observations", "value": _human(d), "seconds": d},
                        {"name": "baseline_median_gap", "value": _human(rmed), "seconds": rmed},
                        {"name": "relationship_status", "value": r["status"]},
                        {"name": "threshold", "value": f"gap < {cfg['burst_ratio']} x median"},
                    ],
                    "explanation": f"Flagged because the recorded link {r['from_code']} {arrow} {r['to_code']} spans {_human(d)} between "
                                   f"observations, compared with a median of {_human(rmed)} across this investigation's {len(timed)} timed "
                                   f"relationships. The link's status remains '{r['status']}'.",
                    "window": {"start": min(r["t_from"], r["t_to"]).isoformat() + "Z", "end": max(r["t_from"], r["t_to"]).isoformat() + "Z"},
                    "source_ids": [r["from_source_id"], r["to_source_id"]], "node_ids": [r["from_node"], r["to_node"]],
                    "location_node_ids": [], "relationship_ids": [r["rel_graph_id"]], "evidence_ids": sorted(r.get("evidence_ids") or []),
                })

    # ---- C. unusual geographic spread ----
    located = [o for o in obs if o["location"] and o["location"].get("latitude") is not None]
    if not base_ok or len(located) < 3:
        detectors.append({"detector": "geographic_spread", "status": "insufficient_data",
                          "reason": f"{INSUFFICIENT} Needs a timing baseline and at least 3 located, timed observations (have {len(located)} located)."})
    else:
        detectors.append({"detector": "geographic_spread", "status": "ran",
                          "baseline": {"located_observations": len(located), "window": _human(med), "min_distance_km": cfg["geo_km"]}})
        seen: set[str] = set()
        for i, o in enumerate(located):
            win = [x for x in located[i:] if (x["t"] - o["t"]).total_seconds() <= med]
            cells = {x["location"]["location_node_id"]: x["location"] for x in win}
            if len(cells) < 3:
                continue
            pts = [(c["latitude"], c["longitude"]) for c in cells.values()]
            dmax = max(haversine_km(p, q) for p in pts for q in pts)
            key = "|".join(sorted(x["source_id"] for x in win))
            if dmax < cfg["geo_km"] or key in seen:
                continue
            seen.add(key)
            span = (win[-1]["t"] - win[0]["t"]).total_seconds()
            unverified = sum(1 for c in cells.values() if c["status"] != "verified")
            anomalies.append({
                "id": _rid("anomaly", "geo", *[x["source_id"] for x in win]), "kind": "anomaly", "type": "geographic_spread",
                "title": "Unusual pattern: wide geographic spread in a short window",
                "score": round(min(1.0, dmax / (cfg["geo_km"] * 4)), 4),
                "factors": [
                    {"name": "distinct_locations", "value": len(cells)},
                    {"name": "max_distance_km", "value": round(dmax, 1)},
                    {"name": "window", "value": _human(span), "seconds": span},
                    {"name": "baseline_median_interval", "value": _human(med), "seconds": med},
                    {"name": "unverified_locations", "value": unverified},
                ],
                "explanation": f"Flagged because {len(win)} observations at {len(cells)} distinct recorded locations up to {dmax:.0f} km apart "
                               f"occurred within {_human(span)}, which is within one median observation interval ({_human(med)})."
                               + (f" {unverified} of these locations are not verified." if unverified else ""),
                "window": {"start": win[0]["t"].isoformat() + "Z", "end": win[-1]["t"].isoformat() + "Z"},
                "source_ids": [x["source_id"] for x in win], "node_ids": [x["node_id"] for x in win],
                "location_node_ids": sorted(cells), "relationship_ids": [],
                "evidence_ids": sorted({e for x in win for e in x["evidence_ids"]}),
            })
    return {"detectors": detectors, "anomalies": anomalies}


def observations_from_graph(g: kg.KnowledgeGraph, incident_id: str) -> tuple[list[dict], list[dict]]:
    obs = []
    for n in g.nodes(types=["source"]):
        sc = source_context(g, n["id"], incident_id)
        obs.append({"source_id": sc["source_id"], "node_id": n["id"], "code": sc["code"], "platform": sc["platform"],
                    "t": _parse(sc["observed_at"]), "location": sc["location"],
                    "evidence_ids": [e["evidence_id"] for e in sc["evidence"]]})
    rels = []
    for r in g.relationships(types=["PROPAGATES_TO", "RELATED_TO"]):
        md = r["metadata"]
        rels.append({"relationship_id": md.get("relationship_id"), "rel_graph_id": r["id"], "type": r["type"], "status": r["status"],
                     "from_node": r["source"], "to_node": r["target"], "from_code": md.get("from_code"), "to_code": md.get("to_code"),
                     "from_source_id": md.get("from_source_id"), "to_source_id": md.get("to_source_id"),
                     "t_from": _parse(md.get("from_observed")), "t_to": _parse(md.get("to_observed")),
                     "evidence_ids": md.get("endpoint_evidence_ids") or []})
    return obs, rels


def run_anomalies(incident: Incident, db: Session) -> dict:
    s = get_settings()
    cfg = {"min_obs": s.ML_ANOMALY_MIN_OBSERVATIONS, "min_rels": s.ML_ANOMALY_MIN_RELATIONSHIPS,
           "burst_ratio": s.ML_BURST_RATIO, "geo_km": s.ML_GEO_SPREAD_KM}
    g, src = load_graph(incident, db)
    obs, rels = observations_from_graph(g, incident.id)
    res = detect_anomalies(obs, rels, cfg)
    computed_at = _now()
    for a in res["anomalies"]:
        a["provenance"] = {**ANOMALY_MODEL, "computed_at": computed_at, "score": a["score"], "config": cfg,
                           "graph_source": src.get("backend")}
        a["disclaimer"] = ANOMALY_DISCLAIMER
    ran = any(d["status"] == "ran" for d in res["detectors"])
    return {
        "analysis": "anomalies", "computed_at": computed_at, "provenance": ANOMALY_MODEL, "config": cfg,
        "disclaimer": ANOMALY_DISCLAIMER, "graph_source": src,
        "status": "ok" if ran else "insufficient_data",
        "message": (None if res["anomalies"] else "No unusual pattern relative to this investigation's own baseline.") if ran else INSUFFICIENT,
        "detectors": res["detectors"], "results": sorted(res["anomalies"], key=lambda a: -a["score"]),
    }


# =========================================================================== clustering
def cluster_media(feats: list[dict], threshold: float) -> list[dict]:
    """Single-linkage clusters (size >= 2). Returns [{members: [feat], pairs: [(i, j, score)]}] with member indices."""
    n = len(feats)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    scores = np.full((n, n), np.nan)
    for i in range(n):
        for j in range(i + 1, n):
            c = compare(feats[i], feats[j])
            if c:
                scores[i, j] = scores[j, i] = c["score"]
                if c["score"] >= threshold:
                    parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        if len(idx) < 2:
            continue
        pair_scores = [float(scores[i, j]) for k, i in enumerate(idx) for j in idx[k + 1:] if not np.isnan(scores[i, j])]
        out.append({"members": [feats[i] for i in idx], "min": min(pair_scores), "max": max(pair_scores), "pairs": len(pair_scores)})
    return out


def run_clusters(incident: Incident, db: Session, *, scope: str = "owner", threshold: float | None = None) -> dict:
    s = get_settings()
    threshold = s.ML_CLUSTER_THRESHOLD if threshold is None else threshold
    computed_at = _now()
    base = {"analysis": "clusters", "scope": scope, "threshold": threshold, "computed_at": computed_at,
            "provenance": CLUSTER_MODEL, "disclaimer": CLUSTER_DISCLAIMER}
    feats = media_features(db, _scope_incidents(incident, db, scope))
    if len(feats) < 2 or not any(f["incident_id"] == incident.id for f in feats):
        return {**base, "status": "insufficient_data", "results": [], "media_considered": len(feats),
                "message": f"{INSUFFICIENT} Clustering needs this investigation's fingerprinted media plus at least one other fingerprinted item in scope."}
    graphs = _Graphs(db)
    results = []
    for c in cluster_media(feats, threshold):
        if not any(m["incident_id"] == incident.id for m in c["members"]):
            continue                      # only clusters relevant to this investigation
        members, sources, locations, evidence = [], [], [], []
        for m in c["members"]:
            ctx = media_context(graphs.get(m["incident_id"]), m["media_id"], m["incident_id"])
            members.append({"media_id": m["media_id"], "filename": m["filename"], "incident_id": m["incident_id"],
                            "incident_title": m["incident_title"], "fingerprint_id": m["fingerprint_id"]})
            sources += [x for x in ctx["sources"] if x["source_id"] not in {y["source_id"] for y in sources}]
            locations += [x for x in ctx["locations"] if x["location_node_id"] not in {y["location_node_id"] for y in locations}]
            evidence += [x for x in ctx["evidence"] if x["evidence_id"] not in {y["evidence_id"] for y in evidence}]
        ids = [m["media_id"] for m in members]
        results.append({
            "id": _rid("cluster", *ids), "kind": "cluster", "score": round(c["min"], 4),
            "size": len(members), "members": members, "source_count": len(sources), "sources": sources,
            "platforms": sorted({x["platform"] for x in sources if x["platform"]}), "locations": locations,
            "similarity_range": {"min": round(c["min"], 4), "max": round(c["max"], 4)},
            "investigations": sorted({m["incident_id"] for m in members}),
            "factors": [{"name": "members", "value": len(members)}, {"name": "pairwise_similarity_min", "value": round(c["min"], 4)},
                        {"name": "pairwise_similarity_max", "value": round(c["max"], 4)}, {"name": "link_threshold", "value": threshold}],
            "explanation": f"Grouped because each of the {len(members)} media items is visually similar (>= {threshold:.2f}) to at least "
                           f"one other member; pairwise similarity ranges {c['min']:.2f}-{c['max']:.2f}. {CLUSTER_DISCLAIMER}",
            "evidence_refs": {"fingerprint_ids": [m["fingerprint_id"] for m in members], "evidence_ids": [e["evidence_id"] for e in evidence]},
            "provenance": {**CLUSTER_MODEL, "computed_at": computed_at, "score": round(c["min"], 4), "threshold": threshold,
                           "graph_source": {k: v.get("backend") for k, v in graphs.sources.items()}},
            "disclaimer": CLUSTER_DISCLAIMER,
        })
    return {**base, "status": "ok", "results": results, "media_considered": len(feats),
            "message": None if results else f"No cluster: no item of this investigation is visually similar (>= {threshold:.2f}) to another item in scope."}


def run_all(incident: Incident, db: Session, *, scope: str = "owner") -> dict:
    with graph_memo():
        return {"similarity": run_similarity(incident, db, scope=scope), "anomalies": run_anomalies(incident, db),
                "clusters": run_clusters(incident, db, scope=scope)}
