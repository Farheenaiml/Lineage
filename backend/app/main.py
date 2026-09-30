from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.session import Base, engine
import app.models  # noqa: F401 — ensures every model is registered on Base before create_all

from app.routers import auth, incidents, media, sources, evidence, attribution, reports, web_search, geo, graph, copilot, ml, automation

settings = get_settings()


def _migrate_additive_columns() -> None:
    """
    Phase 2: add nullable city/region to source_locations on databases created by Phase 1.
    Purely additive (ALTER TABLE ADD COLUMN) so every existing investigation row is preserved.
    """
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        if "source_locations" in tables:
            have_locations = {c["name"] for c in insp.get_columns("source_locations")}
            for col in ("city", "region"):
                if col not in have_locations:
                    conn.execute(text(f"ALTER TABLE source_locations ADD COLUMN {col} VARCHAR"))
        if "detection_results" in tables:
            detection_columns = {c["name"] for c in insp.get_columns("detection_results")}
            if "explainability_json" not in detection_columns:
                conn.execute(text("ALTER TABLE detection_results ADD COLUMN explainability_json TEXT"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Simple create_all for now — fine for a hackathon/portfolio build.
    # A real deployment should switch to Alembic migrations before this
    # schema needs to evolve without dropping data.
    Base.metadata.create_all(bind=engine)
    _migrate_additive_columns()

    # Warm the ML models at startup rather than on the first user request.
    # Loading them lazily meant the first upload paid a multi-second penalty
    # (and two concurrent first-calls contended badly). Failures here are
    # non-fatal: the detect/fingerprint endpoints each fall back cleanly, so
    # the API still starts on a machine with no model access at all.
    if settings.PRELOAD_MODELS:
        import logging
        log = logging.getLogger("uvicorn.error")
        try:
            from app.services.face_embedding import _get_models
            _get_models()
            log.info("Face detection/embedding models loaded.")
        except Exception as e:
            log.warning("Face models unavailable (%s) — /fingerprint will report no face.", e)
        try:
            from app.services.deepfake_model import _get_pipeline
            _get_pipeline()
            log.info("Deepfake detection model loaded.")
        except Exception as e:
            log.warning(
                "Deepfake model unavailable (%s) — /detect will use the labelled pixel-heuristic fallback.", e
            )

    # Phase 3A: create the Neo4j constraints/indexes up front when Neo4j is reachable. Non-fatal —
    # without Neo4j every graph endpoint serves the in-memory KnowledgeGraph.
    import logging
    from app.services.graph_store import Neo4jGraphRepository
    from app.services.neo4j_service import Neo4jQueryError, Neo4jUnavailable, close_neo4j_service, get_neo4j_service
    neo = get_neo4j_service()
    if neo.configured:
        try:
            Neo4jGraphRepository(neo).ensure_schema()
            logging.getLogger("uvicorn.error").info("Neo4j connected; graph constraints ensured.")
        except (Neo4jUnavailable, Neo4jQueryError) as e:
            logging.getLogger("uvicorn.error").warning("Neo4j unavailable at startup (%s); using the in-memory graph.", e)

    yield

    close_neo4j_service()


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "LINEAGE — AI-powered synthetic identity abuse investigation platform. "
        "See the PRD/TRD/Project Flow docs for the full product spec; this API "
        "implements the Phase 1 backend foundations: auth, the real data model, "
        "encrypted file storage, and a genuine (heuristic, non-ML) detection + "
        "fingerprinting pipeline."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health():
    from app.services.graph_sync import graph_health
    g = graph_health()
    # "neo4j": connected | fallback (graph served from the in-memory KnowledgeGraph); detail at /graph/health
    return {"status": "ok", "env": settings.ENV, "neo4j": g["status"], "graph_backend": g["graph_backend"]}


app.include_router(auth.router)
app.include_router(incidents.router)
app.include_router(media.router)
app.include_router(sources.router)
app.include_router(evidence.router)
app.include_router(attribution.router)
app.include_router(reports.router)
app.include_router(web_search.router)
app.include_router(geo.router)
app.include_router(graph.router)  # Phase 3A: investigation knowledge graph (derived view; no new tables)
app.include_router(graph.health_router)  # Phase 3A: Neo4j status (connected | fallback)
app.include_router(copilot.router)  # Phase 3B: Investigation Copilot (Graph RAG)
app.include_router(ml.router)  # Phase 4: ML Intelligence (similarity, anomalies, clusters)
app.include_router(automation.router)  # Phase 5: summary, gaps, timeline, reports, alert drafts, export, workflow, audit
