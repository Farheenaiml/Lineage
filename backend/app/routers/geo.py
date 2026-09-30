"""
Geo / propagation-map API (Phase 1).

GET  /incidents/{id}/geo                          -> nodes, edges, stats, time range (all derived from stored records)
PUT  /incidents/{id}/sources/{sid}/location       -> investigator-supplied location (provenance recorded)
DELETE /incidents/{id}/sources/{sid}/location
PUT  /incidents/{id}/sources/relationships/{rid}/direction -> investigator confirms propagation direction
GET  /geo/geocode?q=                              -> OpenStreetMap Nominatim search (free, no key)

Integrity rules enforced here:
  * No coordinates are ever generated. A node exists only for a SourceLocation row.
  * Direction is 'confirmed' only with an investigator confirmation row, 'inferred' only when
    timestamps agree with the recorded from->to link, otherwise the edge is 'undirected'.
  * Only exif_gps / public_metadata provenance counts as a verified observation.

Phase 2 (Geographic Intelligence) adds — reusing the same SourceLocation / Source / SourceRelationship tables:
GET  /incidents/{id}/geo-stats     -> filtered aggregation: nodes, arcs, heatmap points, hotspots, activity scores,
                                      earliest observed, timeline index. Query: start, end, platform, tier
                                      (verified|investigator|inferred), metric (observations|unique_sources|
                                      propagation_events), high_score, medium_score
GET  /incidents/{id}/geo-observations -> flat provenance-preserving location records (same filters)
Aggregation lives in app/services/geo_intel.py (pure, unit-tested).
"""
import math
from collections import defaultdict
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.location import SourceLocation, RelationshipDirection, VERIFIED_PROVENANCE
from app.models.source import EvidenceItem, Source, SourceRelationship
from app.models.user import User
from app.routers.incidents import _get_owned_incident
from app.services import audit, geo_intel

router = APIRouter(tags=["geo"])

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
UNDIRECTED_TYPES = {"same content", "related", "similar", "match", "duplicate", "same media"}


# ------------------------------------------------------------------ schemas
class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_name: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    confidence: float = Field(default=60, ge=0, le=100)
    basis: str | None = None
    provenance: str = "investigator_supplied"


class DirectionIn(BaseModel):
    note: str | None = None


# ------------------------------------------------------------------ helpers
def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _tier(provenance: str) -> str:
    if provenance in VERIFIED_PROVENANCE:
        return "verified"
    if provenance == "investigator_supplied":
        return "investigator"
    return "inferred"


def _node_key(lat: float, lon: float) -> str:
    return f"{round(lat, 2):.2f},{round(lon, 2):.2f}"


def _confidence_label(c: float) -> str:
    return "High" if c >= 80 else "Medium" if c >= 55 else "Low"


def _build_geo(incident_id: str, db: Session) -> dict:
    sources = db.query(Source).filter(Source.incident_id == incident_id).order_by(Source.observed_at).all()
    label = {s.id: f"SRC-{LETTERS[i] if i < 26 else i + 1}" for i, s in enumerate(sources)}
    by_id = {s.id: s for s in sources}
    source_ids = list(by_id)

    locs = (
        db.query(SourceLocation).filter(SourceLocation.source_id.in_(source_ids)).all() if source_ids else []
    )
    loc_by_source = {l.source_id: l for l in locs}

    evid = db.query(EvidenceItem).filter(EvidenceItem.incident_id == incident_id).order_by(EvidenceItem.captured_at).all()
    ev_label = {e.id: f"EV-{i + 1:02d}" for i, e in enumerate(evid)}
    ev_by_source: dict[str, list[EvidenceItem]] = defaultdict(list)
    for e in evid:
        if e.source_id:
            ev_by_source[e.source_id].append(e)

    # ---- nodes: group sources sharing (rounded) coordinates ----
    groups: dict[str, list[Source]] = defaultdict(list)
    for s in sources:
        l = loc_by_source.get(s.id)
        if l:
            groups[_node_key(l.latitude, l.longitude)].append(s)

    nodes, node_of_source = [], {}
    for key, members in groups.items():
        ls = [loc_by_source[m.id] for m in members]
        first = ls[0]
        tiers = {_tier(l.provenance) for l in ls}
        tier = next(iter(tiers)) if len(tiers) == 1 else "mixed"
        conf = round(sum(l.confidence for l in ls) / len(ls), 1)
        times = sorted(m.observed_at for m in members)
        nid = "LOC-" + key.replace(",", "_").replace("-", "m").replace(".", "p")
        names = [l.place_name for l in ls if l.place_name]
        obs = [
            {
                "source_id": m.id,
                "label": label[m.id],
                "platform": m.platform,
                "account": m.account_identifier,
                "observed_at": _iso(m.observed_at),
                "tier": _tier(loc_by_source[m.id].provenance),
                "provenance": loc_by_source[m.id].provenance,
                "confidence": loc_by_source[m.id].confidence,
                "basis": loc_by_source[m.id].basis,
                "evidence_ids": [e.id for e in ev_by_source.get(m.id, [])],
                "evidence_labels": [ev_label[e.id] for e in ev_by_source.get(m.id, [])],
            }
            for m in members
        ]
        nodes.append({
            "id": nid,
            "name": names[0] if names else f"{first.latitude:.3f}, {first.longitude:.3f}",
            "has_name": bool(names),
            "country": next((l.country for l in ls if l.country), None),
            "latitude": first.latitude,
            "longitude": first.longitude,
            "observation_count": len(members),
            "verified_observation_count": sum(1 for o in obs if o["tier"] == "verified"),
            "platforms": sorted({m.platform for m in members}),
            "first_observed": _iso(times[0]),
            "last_observed": _iso(times[-1]),
            "tier": tier,
            "confidence": conf,
            "confidence_label": _confidence_label(conf),
            "observations": obs,
        })
        for m in members:
            node_of_source[m.id] = nid

    # ---- edges: aggregate source relationships between distinct located nodes ----
    rels = (
        db.query(SourceRelationship).filter(SourceRelationship.from_source_id.in_(source_ids)).all() if source_ids else []
    )
    confirmed = {d.relationship_id: d for d in db.query(RelationshipDirection).all()} if rels else {}

    edge_bins: dict[tuple, dict] = {}
    unlocated_rel = 0
    for r in rels:
        a, b = node_of_source.get(r.from_source_id), node_of_source.get(r.to_source_id)
        if not a or not b:
            unlocated_rel += 1
            continue
        if a == b:
            continue
        sa, sb = by_id[r.from_source_id], by_id[r.to_source_id]
        rtype = (r.relationship_type or "").lower()
        conf_row = confirmed.get(r.id)
        if rtype in UNDIRECTED_TYPES:
            mode, basis = "undirected", "Relationship type does not imply a direction."
            src_n, dst_n = a, b
        elif conf_row:
            mode, basis = "confirmed", f"Direction confirmed by investigator{': ' + conf_row.note if conf_row.note else '.'}"
            src_n, dst_n = a, b
        elif sa.observed_at < sb.observed_at:
            mode = "inferred"
            basis = (f"Inferred propagation direction: {label[sa.id]} observed {sa.observed_at:%d %b %Y %H:%M} "
                     f"before {label[sb.id]} observed {sb.observed_at:%d %b %Y %H:%M}. Not confirmed.")
            src_n, dst_n = a, b
        else:
            mode = "undirected"
            basis = ("Recorded link conflicts with or cannot be ordered by observation timestamps; "
                     "direction is not asserted.")
            src_n, dst_n = a, b
        # bin per (unordered node pair + direction pair)
        key = (src_n, dst_n, mode) if mode != "undirected" else (*sorted([src_n, dst_n]), mode)
        e = edge_bins.setdefault(key, {
            "id": "EDGE-" + str(len(edge_bins) + 1),
            "source": key[0], "target": key[1], "mode": mode, "basis": basis,
            "relationships": [], "platforms": set(), "types": set(),
            "timestamps": [], "similarities": [], "confidences": [],
        })
        e["relationships"].append({
            "relationship_id": r.id,
            "from_label": label[sa.id], "to_label": label[sb.id],
            "from_platform": sa.platform, "to_platform": sb.platform,
            "type": r.relationship_type, "confidence": r.confidence,
            "from_observed": _iso(sa.observed_at), "to_observed": _iso(sb.observed_at),
            "similarity": sb.similarity_score,
            "evidence_labels": [ev_label[x.id] for x in ev_by_source.get(sa.id, []) + ev_by_source.get(sb.id, [])],
        })
        e["platforms"].update([sa.platform, sb.platform])
        e["types"].add(r.relationship_type)
        e["timestamps"].append(sb.observed_at)
        if sb.similarity_score is not None:
            e["similarities"].append(sb.similarity_score)
        if r.confidence is not None:
            e["confidences"].append(r.confidence)

    edges = []
    for e in edge_bins.values():
        ts = sorted(e["timestamps"])
        edges.append({
            "id": e["id"], "source": e["source"], "target": e["target"], "mode": e["mode"],
            "basis": e["basis"], "count": len(e["relationships"]),
            "platforms": sorted(e["platforms"]), "types": sorted(e["types"]),
            "first_timestamp": _iso(ts[0]), "last_timestamp": _iso(ts[-1]),
            "similarity": round(sum(e["similarities"]) / len(e["similarities"]), 1) if e["similarities"] else None,
            "confidence": round(sum(e["confidences"]) / len(e["confidences"]), 1) if e["confidences"] else None,
            "relationships": e["relationships"],
        })

    # ---- unlocated sources (so the UI can prompt for investigator-supplied locations) ----
    unlocated = [
        {"source_id": s.id, "label": label[s.id], "platform": s.platform, "account": s.account_identifier,
         "observed_at": _iso(s.observed_at)}
        for s in sources if s.id not in loc_by_source
    ]
    all_times = [s.observed_at for s in sources if s.id in loc_by_source]
    return {
        "nodes": nodes,
        "edges": edges,
        "unlocated_sources": unlocated,
        "stats": {
            "source_count": len(sources),
            "located_sources": len(loc_by_source),
            "unlocated_sources": len(unlocated),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "directed_edges": sum(1 for e in edges if e["mode"] in ("confirmed", "inferred")),
            "inferred_edges": sum(1 for e in edges if e["mode"] == "inferred"),
            "undirected_edges": sum(1 for e in edges if e["mode"] == "undirected"),
            "verified_locations": sum(1 for l in locs if _tier(l.provenance) == "verified"),
            "investigator_locations": sum(1 for l in locs if _tier(l.provenance) == "investigator"),
            "inferred_locations": sum(1 for l in locs if _tier(l.provenance) == "inferred"),
            "relationships_without_locations": unlocated_rel,
        },
        "time_range": {"start": _iso(min(all_times)) if all_times else None, "end": _iso(max(all_times)) if all_times else None},
    }


# ------------------------------------------------------------------ endpoints
@router.get("/incidents/{incident_id}/geo")
def get_geo(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = _get_owned_incident(incident_id, db, current_user)
    return _build_geo(incident.id, db)


@router.put("/incidents/{incident_id}/sources/{source_id}/location")
def set_location(
    incident_id: str, source_id: str, payload: LocationIn,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    source = db.query(Source).filter(Source.id == source_id, Source.incident_id == incident.id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found in this investigation.")
    # Humans can never mint a 'verified' tier location through this endpoint.
    prov = "inferred" if payload.provenance == "inferred" else "investigator_supplied"
    row = db.query(SourceLocation).filter(SourceLocation.source_id == source.id).first()
    if row and row.provenance == "exif_gps":
        raise HTTPException(status_code=409, detail="This source has an EXIF-derived location; it is preserved and cannot be overwritten.")
    action = "location_edited" if row else "location_added"
    if not row:
        row = SourceLocation(source_id=source.id, latitude=payload.latitude, longitude=payload.longitude,
                             provenance=prov, confidence=payload.confidence)
        db.add(row)
    row.latitude, row.longitude = payload.latitude, payload.longitude
    row.place_name, row.country = payload.place_name, payload.country
    row.city, row.region = payload.city, payload.region
    row.provenance, row.confidence = prov, payload.confidence
    row.basis = payload.basis or "Location entered by the investigator; not independently verified."
    row.recorded_by, row.recorded_at = current_user.id, datetime.utcnow()
    audit.record(db, incident.id, current_user, action, target_type="source", target_id=source.id,  # Phase 5 audit trail
                 details={"latitude": payload.latitude, "longitude": payload.longitude, "provenance": prov}, commit=False)
    db.commit()
    return _build_geo(incident.id, db)


@router.delete("/incidents/{incident_id}/sources/{source_id}/location")
def delete_location(incident_id: str, source_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = _get_owned_incident(incident_id, db, current_user)
    row = (db.query(SourceLocation).join(Source, Source.id == SourceLocation.source_id)
           .filter(Source.id == source_id, Source.incident_id == incident.id).first())
    if not row:
        raise HTTPException(status_code=404, detail="No location recorded for this source.")
    if row.provenance == "exif_gps":
        raise HTTPException(status_code=409, detail="EXIF-derived locations are preserved evidence and cannot be deleted.")
    db.delete(row)
    audit.record(db, incident.id, current_user, "location_deleted", target_type="source", target_id=source_id, commit=False)
    db.commit()
    return _build_geo(incident.id, db)


@router.put("/incidents/{incident_id}/sources/relationships/{relationship_id}/direction")
def confirm_direction(
    incident_id: str, relationship_id: str, payload: DirectionIn,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    ids = {s.id for s in db.query(Source).filter(Source.incident_id == incident.id).all()}
    rel = db.query(SourceRelationship).filter(SourceRelationship.id == relationship_id).first()
    if not rel or rel.from_source_id not in ids:
        raise HTTPException(status_code=404, detail="Relationship not found in this investigation.")
    row = db.query(RelationshipDirection).filter(RelationshipDirection.relationship_id == rel.id).first()
    if not row:
        row = RelationshipDirection(relationship_id=rel.id)
        db.add(row)
    row.note, row.confirmed_by, row.confirmed_at = payload.note, current_user.id, datetime.utcnow()
    audit.record(db, incident.id, current_user, "direction_confirmed", target_type="relationship", target_id=rel.id,
                 details={"note": payload.note}, commit=False)
    db.commit()
    return _build_geo(incident.id, db)


@router.delete("/incidents/{incident_id}/sources/relationships/{relationship_id}/direction")
def unconfirm_direction(incident_id: str, relationship_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = _get_owned_incident(incident_id, db, current_user)
    row = db.query(RelationshipDirection).filter(RelationshipDirection.relationship_id == relationship_id).first()
    if row:
        db.delete(row)
        audit.record(db, incident.id, current_user, "direction_revoked", target_type="relationship", target_id=relationship_id, commit=False)
        db.commit()
    return _build_geo(incident.id, db)


@router.get("/geo/geocode")
def geocode(q: str = Query(min_length=2, max_length=120), current_user: User = Depends(get_current_user)):
    """OpenStreetMap Nominatim proxy (free, keyless). Results are *candidates* only —
    selecting one stores it as 'investigator_supplied', never as verified."""
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "jsonv2", "limit": 6, "addressdetails": 1},
            headers={"User-Agent": "LINEAGE-forensics/1.0 (investigator geocoding)"},
            timeout=8,
        )
        r.raise_for_status()
    except Exception:
        raise HTTPException(status_code=502, detail="OpenStreetMap geocoder unreachable. Enter latitude/longitude manually.")
    out = []
    for it in r.json():
        addr = it.get("address", {})
        out.append({
            "display_name": it.get("display_name"),
            "name": it.get("name") or addr.get("city") or addr.get("town") or addr.get("state") or it.get("display_name", "").split(",")[0],
            "country": addr.get("country"),
            "city": addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality"),
            "region": addr.get("state") or addr.get("state_district") or addr.get("region") or addr.get("county"),
            "latitude": float(it["lat"]), "longitude": float(it["lon"]),
            "importance": it.get("importance"),
        })
    return {"results": out, "attribution": "© OpenStreetMap contributors (Nominatim)"}


# ------------------------------------------------------------------ Phase 2: geographic intelligence
def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _load_records(incident_id: str, db: Session) -> tuple[list[dict], list[dict], int, int]:
    """Flatten stored Phase 1 rows into the records geo_intel expects. Nothing is generated here."""
    sources = db.query(Source).filter(Source.incident_id == incident_id).order_by(Source.observed_at).all()
    label = {s.id: f"SRC-{LETTERS[i] if i < 26 else i + 1}" for i, s in enumerate(sources)}
    ids = list(label)
    locs = {l.source_id: l for l in db.query(SourceLocation).filter(SourceLocation.source_id.in_(ids)).all()} if ids else {}

    evid = db.query(EvidenceItem).filter(EvidenceItem.incident_id == incident_id).order_by(EvidenceItem.captured_at).all()
    ev_label = {e.id: f"EV-{i + 1:02d}" for i, e in enumerate(evid)}
    ev_by_source: dict[str, list[EvidenceItem]] = defaultdict(list)
    for e in evid:
        if e.source_id:
            ev_by_source[e.source_id].append(e)

    obs = []
    for s in sources:
        l = locs.get(s.id)
        if not l:
            continue
        obs.append({
            "source_id": s.id, "label": label[s.id], "platform": s.platform, "account": s.account_identifier, "url": s.url,
            "similarity": s.similarity_score, "observed_at": s.observed_at,
            "tier": _tier(l.provenance), "provenance": l.provenance, "confidence": l.confidence, "basis": l.basis,
            "latitude": l.latitude, "longitude": l.longitude, "place_name": l.place_name,
            "city": getattr(l, "city", None), "region": getattr(l, "region", None), "country": l.country,
            "location_id": l.id, "created_at": l.recorded_at,
            "evidence_ids": [e.id for e in ev_by_source.get(s.id, [])],
            "evidence_labels": [ev_label[e.id] for e in ev_by_source.get(s.id, [])],
        })

    rels = db.query(SourceRelationship).filter(SourceRelationship.from_source_id.in_(ids)).all() if ids else []
    confirmed = {d.relationship_id for d in db.query(RelationshipDirection).all()} if rels else set()
    located = set(locs)
    recs, unlocated = [], 0
    for r in rels:
        if r.from_source_id in located and r.to_source_id in located:
            recs.append({"id": r.id, "from_source_id": r.from_source_id, "to_source_id": r.to_source_id,
                         "type": r.relationship_type, "confidence": r.confidence, "direction_confirmed": r.id in confirmed})
        else:
            unlocated += 1
    return obs, recs, len(sources), unlocated


@router.get("/incidents/{incident_id}/geo-stats")
def get_geo_stats(
    incident_id: str,
    start: datetime | None = None, end: datetime | None = None,
    platform: str | None = None,
    tier: str | None = Query(default=None, pattern="^(all|verified|investigator|inferred)$"),
    metric: str = Query(default="observations", pattern="^(observations|unique_sources|propagation_events)$"),
    high_score: float | None = Query(default=None, gt=0, le=100),
    medium_score: float | None = Query(default=None, gt=0, le=100),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    obs, rels, n_sources, unlocated = _load_records(incident.id, db)
    return geo_intel.analyze(
        obs, rels, start=_naive_utc(start), end=_naive_utc(end),
        platform=None if platform in (None, "", "all") else platform,
        tier=None if tier in (None, "all") else tier, metric=metric,
        config=geo_intel.load_config(high_score, medium_score),
        total_sources=n_sources, relationships_without_locations=unlocated,
    )


@router.get("/incidents/{incident_id}/geo-observations")
def get_geo_observations(
    incident_id: str,
    start: datetime | None = None, end: datetime | None = None,
    platform: str | None = None,
    tier: str | None = Query(default=None, pattern="^(all|verified|investigator|inferred)$"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    obs, _, _, _ = _load_records(incident.id, db)
    rows = geo_intel.flat_observations(
        obs, platform=None if platform in (None, "", "all") else platform,
        tier=None if tier in (None, "all") else tier, start=_naive_utc(start), end=_naive_utc(end),
    )
    return {"observations": rows, "count": len(rows)}
