"""
Investigation Knowledge Graph API (Phase 3A).

GET /incidents/{id}/graph                                  -> { nodes, relationships, stats, notes, graph_source }   (optional ?types=&relationship_types=)
GET /incidents/{id}/graph/nodes                            -> nodes only                                (?type=a,b &q=search)
GET /incidents/{id}/graph/relationships                    -> relationships only                        (?type= &status=)
GET /incidents/{id}/graph/nodes/{node_id}                  -> one node
GET /incidents/{id}/graph/nodes/{node_id}/relationships    -> relationships connected to the node (+ neighbours)   (?type=)
GET /incidents/{id}/graph/paths?source=&target=            -> simple paths between two entities         (?max_depth= &max_paths=)
GET /incidents/{id}/graph/source                           -> which backend serves this graph (neo4j | memory) and why
POST /incidents/{id}/graph/sync                            -> idempotent sync of THIS investigation to Neo4j   (?rebuild=true)
GET /graph/health                                          -> Neo4j status: connected | fallback

The graph is derived from the rows Phase 1/2 already store by the pure service in app/services/knowledge_graph.py.
Phase 3A persistence: when Neo4j is configured and reachable the graph is read from Neo4j (after an idempotent sync
when NEO4J_AUTO_SYNC is on); otherwise the in-memory KnowledgeGraph is served automatically. Responses are the same
shape either way. Ownership rules are the same as every other incident route.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.routers.incidents import _get_owned_incident
from app.services import graph_sync
from app.services import knowledge_graph as kg
from app.services.graph_sync import load_graph_input  # noqa: F401 — kept importable from here (moved to graph_sync)
from app.services.neo4j_service import Neo4jQueryError, Neo4jUnavailable, get_neo4j_service

router = APIRouter(prefix="/incidents", tags=["graph"])
health_router = APIRouter(prefix="/graph", tags=["graph"])


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _graph_with_source(incident_id: str, db: Session, user: User) -> tuple[kg.KnowledgeGraph, dict]:
    incident = _get_owned_incident(incident_id, db, user)
    return graph_sync.load_graph(incident, db)


def _graph(incident_id: str, db: Session, user: User) -> kg.KnowledgeGraph:
    return _graph_with_source(incident_id, db, user)[0]


def _bad_types(values: list[str], allowed: tuple[str, ...], what: str, upper: bool = False) -> None:
    unknown = [v for v in values if (v.upper() if upper else v.lower()) not in allowed]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown {what}: {', '.join(unknown)}. Allowed: {', '.join(allowed)}.")


@router.get("/{incident_id}/graph")
def get_graph(
    incident_id: str,
    types: str | None = Query(default=None, description="Comma-separated entity types to include"),
    relationship_types: str | None = Query(default=None, description="Comma-separated relationship types to include"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    t, rt = [x.lower() for x in _csv(types)], [x.upper() for x in _csv(relationship_types)]
    _bad_types(t, kg.NODE_TYPES, "entity type")
    _bad_types(rt, kg.REL_TYPES, "relationship type", upper=True)
    g, source = _graph_with_source(incident_id, db, current_user)
    return {**g.to_dict(types=t or None, rel_types=rt or None), "graph_source": source}


@router.get("/{incident_id}/graph/source")
def get_graph_source(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _graph_with_source(incident_id, db, current_user)[1]


@router.post("/{incident_id}/graph/sync")
def sync_graph(
    incident_id: str, rebuild: bool = Query(default=False, description="Delete this investigation's Neo4j graph first, then re-sync"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    svc = get_neo4j_service()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="Neo4j is not configured (set NEO4J_URI). The in-memory graph is still served.")
    svc.reset_backoff()   # an explicit request deserves an immediate connection attempt
    try:
        return graph_sync.sync_investigation(incident, db, graph_sync.default_repository(svc), rebuild=rebuild)
    except Neo4jUnavailable as e:
        raise HTTPException(status_code=503, detail=f"Neo4j is unavailable: {e}")
    except Neo4jQueryError as e:
        raise HTTPException(status_code=502, detail=f"Neo4j sync failed: {e}")


@health_router.get("/health")
def graph_health():
    return graph_sync.graph_health()


@router.get("/{incident_id}/graph/nodes")
def get_graph_nodes(
    incident_id: str, type: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    t = [x.lower() for x in _csv(type)]
    _bad_types(t, kg.NODE_TYPES, "entity type")
    nodes = _graph(incident_id, db, current_user).nodes(types=t or None, q=q)
    return {"nodes": nodes, "count": len(nodes)}


@router.get("/{incident_id}/graph/relationships")
def get_graph_relationships(
    incident_id: str, type: str | None = None, status: str | None = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    t = [x.upper() for x in _csv(type)]
    _bad_types(t, kg.REL_TYPES, "relationship type", upper=True)
    rels = _graph(incident_id, db, current_user).relationships(types=t or None, statuses=_csv(status) or None)
    return {"relationships": rels, "count": len(rels)}


@router.get("/{incident_id}/graph/nodes/{node_id}")
def get_graph_node(incident_id: str, node_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return _graph(incident_id, db, current_user).get_node(node_id)
    except kg.NodeNotFound:
        raise HTTPException(status_code=404, detail="Node not found in this investigation's graph.")


@router.get("/{incident_id}/graph/nodes/{node_id}/relationships")
def get_node_relationships(
    incident_id: str, node_id: str, type: str | None = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    t = [x.upper() for x in _csv(type)]
    _bad_types(t, kg.REL_TYPES, "relationship type", upper=True)
    try:
        return _graph(incident_id, db, current_user).connected(node_id, types=t or None)
    except kg.NodeNotFound:
        raise HTTPException(status_code=404, detail="Node not found in this investigation's graph.")


@router.get("/{incident_id}/graph/paths")
def get_graph_paths(
    incident_id: str,
    source: str = Query(..., description="Start node id"),
    target: str = Query(..., description="End node id"),
    max_depth: int = Query(default=6, ge=1, le=12),
    max_paths: int = Query(default=5, ge=1, le=25),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    try:
        return _graph(incident_id, db, current_user).find_paths(source, target, max_depth=max_depth, max_paths=max_paths)
    except kg.NodeNotFound as e:
        raise HTTPException(status_code=404, detail=f"Node not found in this investigation's graph: {e.args[0]}")
