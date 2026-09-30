"""
Graph sync + retrieval policy (Phase 3A).

    SQL rows --load_graph_input--> plain dicts --knowledge_graph.build_graph--> KnowledgeGraph
             --graph_to_rows--> Neo4j rows --graph_store.replace_investigation (MERGE)--> Neo4j

and back:  Neo4j --fetch_investigation--> rows --records_to_graph--> KnowledgeGraph (identical to the one built)

The existing KnowledgeGraph remains the single place where relationships, statuses and confidences are decided.
Sync only serialises its output, so Neo4j can never hold a relationship or a status the in-memory graph would not
produce. Nothing is invented, missing values stay missing, and statuses are copied verbatim (an "inferred"
PROPAGATES_TO is stored as "inferred"; an "unknown" RELATED_TO as "unknown").

`load_graph()` is what the API calls: Neo4j when it is reachable, otherwise the in-memory graph — automatically.

CLI (run from backend/):
    python -m app.services.graph_sync status
    python -m app.services.graph_sync sync <incident_id> [--rebuild]
    python -m app.services.graph_sync sync-all [--rebuild]
    python -m app.services.graph_sync counts <incident_id>
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.incident import Incident
from app.models.location import RelationshipDirection, SourceLocation
from app.models.media import DetectionResult, Fingerprint, MediaItem
from app.models.source import EvidenceItem, Source, SourceRelationship
from app.services import knowledge_graph as kg
from app.services.graph_store import LABELS, REL_TYPES, GraphRepository, Neo4jGraphRepository
from app.services.neo4j_service import (
    CONNECTED, NOT_CONFIGURED, UNAVAILABLE, Neo4jQueryError, Neo4jService, Neo4jUnavailable, get_neo4j_service,
)

log = logging.getLogger("uvicorn.error")

NODE_RESERVED = frozenset({"uid", "node_id", "investigation_id", "type", "label", "ord", "metadata_json", "notes_json", "synced_at"})
REL_RESERVED = frozenset({"uid", "rel_id", "investigation_id", "ord", "confidence", "timestamp", "timestamp_kind",
                          "evidence_id", "status", "directed", "payload_json"})


# --------------------------------------------------------------------------- SQL -> plain dicts
def _keyframe_count(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return len(v) if isinstance(v, (list, dict)) else None
    except (ValueError, TypeError):
        return None


def load_graph_input(incident: Incident, db: Session) -> dict:
    """Flatten stored rows into the plain dicts `knowledge_graph.build_graph` expects. Nothing is generated here."""
    media = db.query(MediaItem).filter(MediaItem.incident_id == incident.id).order_by(MediaItem.uploaded_at).all()
    media_ids = [m.id for m in media]
    fps = db.query(Fingerprint).filter(Fingerprint.media_item_id.in_(media_ids)).all() if media_ids else []
    dets = db.query(DetectionResult).filter(DetectionResult.media_item_id.in_(media_ids)).all() if media_ids else []

    sources = db.query(Source).filter(Source.incident_id == incident.id).order_by(Source.observed_at).all()
    source_ids = [s.id for s in sources]
    locs = db.query(SourceLocation).filter(SourceLocation.source_id.in_(source_ids)).all() if source_ids else []
    rels = db.query(SourceRelationship).filter(SourceRelationship.from_source_id.in_(source_ids)).all() if source_ids else []
    rel_ids = [r.id for r in rels]
    confirmed = (
        {d.relationship_id: d for d in db.query(RelationshipDirection).filter(RelationshipDirection.relationship_id.in_(rel_ids)).all()}
        if rel_ids else {}
    )
    evidence = db.query(EvidenceItem).filter(EvidenceItem.incident_id == incident.id).order_by(EvidenceItem.captured_at).all()

    return {
        "incident": {
            "id": incident.id, "title": incident.title, "description": incident.description, "victim_ref": incident.victim_ref,
            "status": incident.status, "created_at": incident.created_at, "updated_at": incident.updated_at,
        },
        "media": [
            {"id": m.id, "kind": m.kind, "original_filename": m.original_filename, "storage_path": m.storage_path,
             "file_size_bytes": m.file_size_bytes, "width": m.width, "height": m.height, "uploaded_at": m.uploaded_at}
            for m in media
        ],
        "fingerprints": [
            {"id": f.id, "media_item_id": f.media_item_id, "average_hash": f.average_hash,
             "has_face_embedding": bool(f.face_embedding_json), "keyframe_count": _keyframe_count(f.keyframe_hashes_json),
             "has_audio_fingerprint": bool(f.audio_fingerprint), "created_at": f.created_at}
            for f in fps
        ],
        "detections": [
            {"id": d.id, "media_item_id": d.media_item_id, "manipulation_likelihood": d.manipulation_likelihood,
             "edge_irregularity": d.edge_irregularity, "compression_density": d.compression_density,
             "detected_region": d.detected_region, "likely_technique": d.likely_technique, "model_name": d.model_name,
             "explanation": d.explanation, "created_at": d.created_at}
            for d in dets
        ],
        "sources": [
            {"id": s.id, "platform": s.platform, "account_identifier": s.account_identifier, "url": s.url,
             "observed_at": s.observed_at, "similarity_score": s.similarity_score, "relationship_label": s.relationship_label,
             "is_seeded": s.is_seeded, "created_at": s.created_at}
            for s in sources
        ],
        "locations": [
            {"id": l.id, "source_id": l.source_id, "latitude": l.latitude, "longitude": l.longitude, "place_name": l.place_name,
             "city": getattr(l, "city", None), "region": getattr(l, "region", None), "country": l.country,
             "provenance": l.provenance, "confidence": l.confidence, "basis": l.basis, "evidence_item_id": l.evidence_item_id,
             "recorded_by": l.recorded_by, "recorded_at": l.recorded_at}
            for l in locs
        ],
        "relationships": [
            {"id": r.id, "from_source_id": r.from_source_id, "to_source_id": r.to_source_id,
             "relationship_type": r.relationship_type, "confidence": r.confidence, "created_at": r.created_at,
             "direction_confirmed": r.id in confirmed,
             "direction_note": confirmed[r.id].note if r.id in confirmed else None,
             "direction_confirmed_at": confirmed[r.id].confirmed_at if r.id in confirmed else None}
            for r in rels
        ],
        "evidence": [
            {"id": e.id, "source_id": e.source_id, "item_type": e.item_type, "storage_path": e.storage_path,
             "notes": e.notes, "captured_at": e.captured_at}
            for e in evidence
        ],
    }


def build_memory_graph(incident: Incident, db: Session) -> kg.KnowledgeGraph:
    return kg.build_graph(load_graph_input(incident, db))


# --------------------------------------------------------------------------- KnowledgeGraph <-> Neo4j rows
def _primitive(v):
    if isinstance(v, (str, bool, int, float)):
        return True
    if isinstance(v, list) and v:
        kinds = {type(x) for x in v}
        return len(kinds) == 1 and kinds.pop() in (str, int, float, bool)
    return False


def _flatten(meta: dict, reserved: frozenset) -> dict:
    """Queryable copy of primitive metadata. Nulls and nested objects are left to the lossless JSON copy."""
    out = {}
    for k, v in meta.items():
        if v is None or not _primitive(v):
            continue
        out[f"meta_{k}" if k in reserved else k] = v
    return out


def node_uid(investigation_id: str, node_id: str) -> str:
    return f"{investigation_id}|{node_id}"


def graph_to_rows(g: kg.KnowledgeGraph, synced_at: str | None = None) -> tuple[list[dict], list[dict]]:
    """Serialise a KnowledgeGraph for Neo4j. Propagation nodes + structural edges are skipped (re-derived on read)."""
    inv = g.incident_id
    synced_at = synced_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    nodes, rels = [], []
    for i, n in enumerate(g.nodes()):
        label = LABELS.get(n["type"])
        if label is None:          # propagation
            continue
        props = {
            **_flatten(n["metadata"], NODE_RESERVED),
            "uid": node_uid(inv, n["id"]), "node_id": n["id"], "investigation_id": inv, "type": n["type"],
            "label": n["label"], "ord": i, "metadata_json": json.dumps(n["metadata"], sort_keys=True),
        }
        if n["type"] == "investigation":
            props["notes_json"] = json.dumps(g.notes)
            props["synced_at"] = synced_at
        nodes.append({"uid": props["uid"], "label": label, "props": props})
    for i, r in enumerate(g.relationships()):
        if r["type"] not in REL_TYPES:  # HAS_ORIGIN / HAS_DESTINATION
            continue
        payload = {k: r[k] for k in ("id", "source", "target", "type", "confidence", "timestamp", "timestamp_kind",
                                      "evidence_id", "status", "directed", "metadata")}
        props = {
            **_flatten(r["metadata"], REL_RESERVED),
            "uid": f"{inv}|{r['id']}", "rel_id": r["id"], "investigation_id": inv, "ord": i,
            "status": r["status"], "directed": r["directed"], "payload_json": json.dumps(payload, sort_keys=True),
        }
        for k in ("confidence", "timestamp", "timestamp_kind", "evidence_id"):   # only when a value exists
            if r[k] is not None:
                props[k] = r[k]
        rels.append({"uid": props["uid"], "type": r["type"], "src": node_uid(inv, r["source"]),
                     "dst": node_uid(inv, r["target"]), "props": props})
    return nodes, rels


def records_to_graph(investigation_id: str, fetched: dict) -> kg.KnowledgeGraph:
    """Rebuild the KnowledgeGraph from Neo4j. Endpoints, type, status, confidence, timestamp and evidence id are taken
    from the Neo4j relationship itself; absent properties are null (never defaulted)."""
    notes: list[str] = []
    nodes = []
    for p in fetched["nodes"]:
        if p.get("type") == "investigation" and p.get("notes_json"):
            notes = json.loads(p["notes_json"])
        nodes.append({"id": p["node_id"], "type": p["type"], "label": p["label"], "metadata": json.loads(p.get("metadata_json") or "{}")})
    rels = []
    for row in fetched["relationships"]:
        p = row["props"]
        payload = json.loads(p.get("payload_json") or "{}")
        rels.append({
            "id": p.get("rel_id") or payload.get("id"), "source": row["source"], "target": row["target"], "type": row["type"],
            "confidence": p.get("confidence"), "timestamp": p.get("timestamp"), "timestamp_kind": p.get("timestamp_kind"),
            "evidence_id": p.get("evidence_id"), "status": p["status"], "directed": p.get("directed", True),
            "metadata": payload.get("metadata") or {},
        })
    return kg.KnowledgeGraph.from_records(investigation_id, nodes, rels, notes)


# --------------------------------------------------------------------------- sync
def default_repository(service: Neo4jService | None = None) -> Neo4jGraphRepository:
    return Neo4jGraphRepository(service or get_neo4j_service())


def sync_graph(g: kg.KnowledgeGraph, repo: GraphRepository, *, rebuild: bool = False) -> dict:
    nodes, rels = graph_to_rows(g)
    repo.ensure_schema()
    removed_first = repo.delete_investigation(g.incident_id) if rebuild else None
    counts = repo.replace_investigation(g.incident_id, nodes, rels)
    return {
        "investigation_id": g.incident_id, "status": "synced", "rebuild": rebuild,
        "nodes": len(nodes), "relationships": len(rels), "write": counts,
        "rebuild_removed": removed_first, "synced_at": nodes[0]["props"].get("synced_at") if nodes else None,
        "not_persisted": {
            "propagation_nodes": sum(1 for n in g.nodes() if n["type"] == "propagation"),
            "structural_relationships": sum(1 for r in g.relationships() if r["structural"]),
            "reason": "Propagation nodes and HAS_ORIGIN/HAS_DESTINATION are a view of one PROPAGATES_TO relationship; "
                      "they are re-derived from it when the graph is read back.",
        },
    }


def sync_investigation(incident: Incident, db: Session, repo: GraphRepository | None = None, *, rebuild: bool = False) -> dict:
    """Sync ONE investigation (only its own nodes/relationships are written or pruned)."""
    return sync_graph(build_memory_graph(incident, db), repo or default_repository(), rebuild=rebuild)


def sync_all(db: Session, repo: GraphRepository | None = None, *, rebuild: bool = False) -> list[dict]:
    repo = repo or default_repository()
    return [sync_investigation(i, db, repo, rebuild=rebuild) for i in db.query(Incident).order_by(Incident.created_at).all()]


# --------------------------------------------------------------------------- retrieval with automatic fallback
def load_graph(incident: Incident, db: Session, *, service: Neo4jService | None = None,
               repo: GraphRepository | None = None, auto_sync: bool | None = None) -> tuple[kg.KnowledgeGraph, dict]:
    """
    Returns (graph, graph_source). Neo4j is used when configured AND reachable; any Neo4j problem (not configured,
    down, auth, query error) falls back to the in-memory graph built from SQL. `graph_source` says which was used.
    """
    svc = service or get_neo4j_service()
    auto_sync = get_settings().NEO4J_AUTO_SYNC if auto_sync is None else auto_sync
    memory = build_memory_graph(incident, db)

    def fallback(neo4j_status: str, reason: str) -> tuple[kg.KnowledgeGraph, dict]:
        return memory, {"backend": "memory", "neo4j": neo4j_status, "fallback": True, "reason": reason}

    if not svc.configured:
        return fallback(NOT_CONFIGURED, "Neo4j is not configured (NEO4J_URI is blank); serving the in-memory graph.")
    repo = repo or Neo4jGraphRepository(svc)
    try:
        synced = None
        if auto_sync:
            synced = sync_graph(memory, repo)
        fetched = repo.fetch_investigation(incident.id)
        if fetched is None:
            return fallback(CONNECTED, "This investigation has not been synced to Neo4j yet; serving the in-memory graph.")
        g = records_to_graph(incident.id, fetched)
        return g, {"backend": "neo4j", "neo4j": CONNECTED, "fallback": False, "auto_synced": bool(synced),
                   "reason": None, "synced_at": _synced_at(fetched)}
    except Neo4jUnavailable as e:
        log.warning("Neo4j unavailable (%s); serving the in-memory graph.", e)
        return fallback(UNAVAILABLE, f"Neo4j is unavailable ({e}); serving the in-memory graph.")
    except Neo4jQueryError as e:
        log.error("Neo4j query failed (%s); serving the in-memory graph.", e)
        return fallback(CONNECTED, f"A Neo4j query failed ({e}); serving the in-memory graph.")


def _synced_at(fetched: dict) -> str | None:
    return next((n.get("synced_at") for n in fetched["nodes"] if n.get("type") == "investigation"), None)


def graph_health(service: Neo4jService | None = None) -> dict:
    """connected -> graph APIs read Neo4j; fallback -> they serve the in-memory KnowledgeGraph."""
    svc = service or get_neo4j_service()
    h = svc.health()
    return {
        "status": "connected" if h["status"] == CONNECTED else "fallback",
        "neo4j": h["status"], "graph_backend": "neo4j" if h["status"] == CONNECTED else "memory",
        "auto_sync": get_settings().NEO4J_AUTO_SYNC, "uri": h["uri"], "database": h["database"],
        "server": h["server"], "error": h["error"],
    }


# --------------------------------------------------------------------------- CLI
def _main(argv: list[str] | None = None) -> int:
    import argparse

    import app.models  # noqa: F401 — register every model
    from app.db.session import SessionLocal

    p = argparse.ArgumentParser(prog="python -m app.services.graph_sync", description="LINEAGE Neo4j sync")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s1 = sub.add_parser("sync"); s1.add_argument("incident_id"); s1.add_argument("--rebuild", action="store_true")
    s2 = sub.add_parser("sync-all"); s2.add_argument("--rebuild", action="store_true")
    s3 = sub.add_parser("counts"); s3.add_argument("incident_id")
    args = p.parse_args(argv)

    if args.cmd == "status":
        print(json.dumps(graph_health(), indent=2))
        return 0
    db = SessionLocal()
    try:
        repo = default_repository()
        if args.cmd == "sync":
            inc = db.get(Incident, args.incident_id)
            if not inc:
                print(f"Investigation {args.incident_id} not found.")
                return 1
            print(json.dumps(sync_investigation(inc, db, repo, rebuild=args.rebuild), indent=2))
        elif args.cmd == "sync-all":
            print(json.dumps(sync_all(db, repo, rebuild=args.rebuild), indent=2))
        elif args.cmd == "counts":
            print(json.dumps(repo.counts(args.incident_id), indent=2))
        return 0
    except (Neo4jUnavailable, Neo4jQueryError) as e:
        print(f"Neo4j error: {e}")
        return 2
    finally:
        db.close()
        get_neo4j_service().close()


if __name__ == "__main__":
    raise SystemExit(_main())
