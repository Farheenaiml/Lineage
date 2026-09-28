from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.session import Base, engine
import app.models  # noqa: F401 — ensures every model is registered on Base before create_all

from app.routers import auth, incidents, media, sources, evidence, attribution, reports, web_search

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Simple create_all for now — fine for a hackathon/portfolio build.
    # A real deployment should switch to Alembic migrations before this
    # schema needs to evolve without dropping data.
    Base.metadata.create_all(bind=engine)

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

    yield


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
    return {"status": "ok", "env": settings.ENV}


app.include_router(auth.router)
app.include_router(incidents.router)
app.include_router(media.router)
app.include_router(sources.router)
app.include_router(evidence.router)
app.include_router(attribution.router)
app.include_router(reports.router)
app.include_router(web_search.router)
