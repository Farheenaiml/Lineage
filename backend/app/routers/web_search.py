from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.deps import get_current_user
from app.models.media import MediaItem
from app.models.user import User
from app.models.web_search import WebSearchQuery, WebSearchRun
from app.routers.incidents import _get_owned_incident
from app.schemas.web_search import WebSearchConsent, WebSearchRunOut
from app.services import file_storage, web_discovery

router = APIRouter(prefix="/incidents", tags=["web discovery"])
settings = get_settings()


def _owned_media(incident_id: str, media_id: str, db: Session, user: User):
    incident = _get_owned_incident(incident_id, db, user)
    media = db.query(MediaItem).filter(
        MediaItem.id == media_id,
        MediaItem.incident_id == incident.id,
    ).first()
    if not media:
        raise HTTPException(status_code=404, detail="Media item not found.")
    return incident, media


@router.get("/web-search/status")
def web_search_status(current_user: User = Depends(get_current_user)):
    return {
        "configured": bool(settings.GEMINI_API_KEY),
        "provider": "Gemini query generator; manual Google/Bing search",
    }


@router.post("/{incident_id}/media/{media_id}/web-search", response_model=WebSearchRunOut, status_code=201)
def generate_image_search_links(
    incident_id: str,
    media_id: str,
    payload: WebSearchConsent,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.consent:
        raise HTTPException(status_code=400, detail="Consent is required before sending this image to Gemini.")
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Search-query generation is not configured. Add GEMINI_API_KEY to backend/.env, then restart the API.",
        )

    incident, media = _owned_media(incident_id, media_id, db, current_user)
    if media.kind != "image":
        raise HTTPException(status_code=415, detail="Public web search currently supports uploaded images only.")
    search_count = db.query(WebSearchRun).filter(
        WebSearchRun.incident_id == incident.id,
        WebSearchRun.media_item_id == media.id,
    ).count()
    if search_count >= settings.MAX_WEB_SEARCHES_PER_MEDIA:
        raise HTTPException(
            status_code=429,
            detail=f"Search limit reached for this upload ({settings.MAX_WEB_SEARCHES_PER_MEDIA} searches).",
        )

    if media.file_size_bytes > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="For web search, images must be 12 MB or smaller.")
    image_bytes = file_storage.read_decrypted(media.storage_path)
    if len(image_bytes) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="For web search, images must be 12 MB or smaller.")
    mime_type = "image/jpeg"
    filename = media.original_filename.lower()
    if filename.endswith(".png"):
        mime_type = "image/png"
    elif filename.endswith(".webp"):
        mime_type = "image/webp"
    elif filename.endswith(".gif"):
        mime_type = "image/gif"

    try:
        result = web_discovery.generate_manual_search_queries(
            gemini_api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEMINI_SEARCH_MODEL,
            image_bytes=image_bytes,
            mime_type=mime_type,
        )
    except Exception as exc:
        import logging
        logging.getLogger("uvicorn.error").exception("Image-led query generation failed")
        raise HTTPException(status_code=502, detail="Could not generate search queries. Check backend logs and Gemini configuration.") from exc

    run = WebSearchRun(
        incident_id=incident.id,
        media_item_id=media.id,
        image_description=result["image_description"],
        summary=result["summary"],
        model_name=settings.GEMINI_SEARCH_MODEL,
    )
    db.add(run)
    db.flush()
    db.add_all([WebSearchQuery(run_id=run.id, **query) for query in result["search_queries"]])
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


@router.get("/{incident_id}/media/{media_id}/web-search", response_model=WebSearchRunOut | None)
def get_latest_image_search(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident, media = _owned_media(incident_id, media_id, db, current_user)
    run = db.query(WebSearchRun).filter(
        WebSearchRun.incident_id == incident.id,
        WebSearchRun.media_item_id == media.id,
    ).order_by(WebSearchRun.created_at.desc()).first()
    return _serialize_run(run) if run else None


def _serialize_run(run: WebSearchRun) -> dict:
    return {
        "id": run.id,
        "image_description": run.image_description,
        "summary": run.summary,
        "model_name": run.model_name,
        "created_at": run.created_at,
        "search_queries": [
            {
                "query": item.query,
                "google_url": item.google_url,
                "bing_url": item.bing_url,
            }
            for item in run.search_queries
        ],
    }