import json
import mimetypes
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.deps import get_current_user
from app.models.incident import Incident
from app.models.media import MediaItem, DetectionResult, Fingerprint
from app.models.source import EvidenceItem, Source, UPLOAD_SOURCE_PLATFORM
from app.models.user import User
from app.schemas.media import MediaItemOut, DetectionResultOut, FingerprintOut
from app.services import file_storage, pixel_analysis, deepfake_model, face_embedding, exif_gps, model_explainability
from app.models.location import SourceLocation
from app.routers.incidents import _get_owned_incident

router = APIRouter(prefix="/incidents", tags=["media"])
settings = get_settings()

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo"}
UPLOAD_RELATIONSHIP_LABEL = "Submitted media; original posting location is unverified."


def _ensure_upload_evidence(incident: Incident, media: MediaItem, db: Session) -> bool:
    item_type = f"uploaded_{media.kind}"
    evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.incident_id == incident.id,
            EvidenceItem.storage_path == media.storage_path,
            EvidenceItem.item_type == item_type,
        )
        .first()
    )
    if evidence:
        return False

    observed_at = media.uploaded_at or datetime.utcnow()
    source = Source(
        incident_id=incident.id,
        platform=UPLOAD_SOURCE_PLATFORM,
        observed_at=observed_at,
        relationship_label=UPLOAD_RELATIONSHIP_LABEL,
        is_seeded=False,
    )
    db.add(source)
    db.flush()

    db.add(
        EvidenceItem(
            incident_id=incident.id,
            source_id=source.id,
            item_type=item_type,
            storage_path=media.storage_path,
            notes=(
                f"Original uploaded file: {media.original_filename}. "
                "Stored encrypted; external posting location has not been established."
            ),
        )
    )
    return True


def _get_media_item(incident_id: str, media_id: str, db: Session, user: User) -> MediaItem:
    incident = _get_owned_incident(incident_id, db, user)
    media = (
        db.query(MediaItem)
        .filter(MediaItem.id == media_id, MediaItem.incident_id == incident.id)
        .first()
    )
    if not media:
        raise HTTPException(status_code=404, detail="Media item not found.")
    return media


@router.get("/{incident_id}/media", response_model=list[MediaItemOut])
def list_media(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    items = (
        db.query(MediaItem)
        .filter(MediaItem.incident_id == incident.id)
        .order_by(MediaItem.uploaded_at)
        .all()
    )
    changed = False
    for item in items:
        changed = _ensure_upload_evidence(incident, item, db) or changed
    if changed:
        db.commit()
    return items


@router.post("/{incident_id}/media", response_model=MediaItemOut, status_code=201)
async def upload_media(
    incident_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)

    content_type = file.content_type or ""
    if content_type in IMAGE_TYPES:
        kind = "image"
    elif content_type in VIDEO_TYPES:
        kind = "video"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type '{content_type}'. Upload an image or video.",
        )

    raw = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB limit.")

    storage_path, size = file_storage.save_encrypted(raw, file.filename or "upload")

    # Peek dimensions without keeping a second full decode around long-term —
    # cheap enough at hackathon-demo scale to just run the real analysis here.
    try:
        if kind == "image":
            result = pixel_analysis.analyze_image_bytes(raw)
        else:
            result = pixel_analysis.analyze_video_bytes(raw, suffix=Path(file.filename or "upload.mp4").suffix or ".mp4")
        width, height = result.width, result.height
    except Exception:
        width, height = None, None

    media = MediaItem(
        incident_id=incident.id,
        kind=kind,
        original_filename=file.filename or "upload",
        storage_path=storage_path,
        file_size_bytes=size,
        width=width,
        height=height,
    )
    db.add(media)
    db.flush()
    _ensure_upload_evidence(incident, media, db)

    # Real EXIF GPS -> verified-tier location on the upload source (Phase 1 map).
    # Only recorded when the file actually carries a GPS block; never guessed.
    if kind == "image":
        gps = exif_gps.extract_gps(raw)
        if gps:
            db.flush()
            ev = (
                db.query(EvidenceItem)
                .filter(EvidenceItem.incident_id == incident.id, EvidenceItem.storage_path == media.storage_path)
                .first()
            )
            if ev and ev.source_id:
                db.add(SourceLocation(
                    source_id=ev.source_id,
                    latitude=gps["latitude"],
                    longitude=gps["longitude"],
                    place_name=None,
                    provenance="exif_gps",
                    confidence=90.0,
                    basis=f"GPS block read from EXIF metadata of uploaded file '{media.original_filename}'. "
                          "EXIF can be edited or stripped; treat as metadata-derived, not proof of capture location.",
                    evidence_item_id=ev.id,
                    recorded_by="system:exif",
                ))

    if incident.status == "created":
        incident.status = "analyzing"

    db.commit()
    db.refresh(media)
    return media


@router.get("/{incident_id}/media/{media_id}/file")
def preview_media_file(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated original in an inline-safe media response."""
    media = _get_media_item(incident_id, media_id, db, current_user)
    raw = file_storage.read_decrypted(media.storage_path)
    media_type = mimetypes.guess_type(media.original_filename)[0]
    if not media_type:
        media_type = "video/mp4" if media.kind == "video" else "image/jpeg"
    return Response(
        content=raw,
        media_type=media_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{incident_id}/media/{media_id}/analysis-frame")
def preview_analysis_frame(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the same still image or video key frame used by detection."""
    media = _get_media_item(incident_id, media_id, db, current_user)
    raw = file_storage.read_decrypted(media.storage_path)
    if media.kind == "video":
        try:
            suffix = Path(media.original_filename).suffix or ".mp4"
            raw = pixel_analysis.extract_video_frame_jpeg(raw, suffix=suffix)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not extract the analysis frame: {e}")
        media_type = "image/jpeg"
    else:
        media_type = mimetypes.guess_type(media.original_filename)[0] or "image/jpeg"
    return Response(
        content=raw,
        media_type=media_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{incident_id}/media/{media_id}/detect", response_model=DetectionResultOut)
def run_detection(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    media = _get_media_item(incident_id, media_id, db, current_user)
    raw = file_storage.read_decrypted(media.storage_path)

    # Try the real pretrained model first (TRD §5.1). Only images are
    # supported by the classifier directly; for video we run it against the
    # same mid-clip frame the heuristic/fingerprint pipeline already uses.
    if media.kind == "image":
        frame_bytes = raw
    else:
        try:
            suffix = Path(media.original_filename).suffix or ".mp4"
            frame_bytes = pixel_analysis.extract_video_frame_jpeg(raw, suffix=suffix)
        except Exception:
            frame_bytes = None

    model_result = deepfake_model.classify_image(frame_bytes) if frame_bytes else None

    try:
        if media.kind == "image":
            heuristic = pixel_analysis.analyze_image_bytes(raw)
        else:
            heuristic = pixel_analysis.analyze_video_bytes(raw, suffix=Path(media.original_filename).suffix or ".mp4")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not analyze this file: {e}")

    if model_result and model_result.used_real_model and model_result.manipulation_likelihood is not None:
        manipulation_likelihood = model_result.manipulation_likelihood
        model_name = model_result.model_id
        explanation = (
            f"Real pretrained model ({model_result.model_id}) classified this media with a "
            f"{manipulation_likelihood}% manipulation likelihood. Full label scores: "
            f"{model_result.raw_labels}."
        )
    else:
        # Honest fallback — never presented as the real model's output.
        manipulation_likelihood = heuristic.signal_score
        model_name = "pixel-heuristic-v1 (fallback — real model unavailable)"
        reason = model_result.load_error if model_result else "media type not supported by the classifier"
        explanation = (
            f"Real detection model unavailable ({reason}); fell back to a pixel heuristic combining "
            f"edge-energy irregularity ({heuristic.edge_irregularity}%) and compression-density anomaly "
            f"({heuristic.compression_density}%). This heuristic is not a trained deepfake classifier — "
            f"see TRD §5.1."
        )

    explainability = None
    try:
        face_box = None
        face_confidence = None
        face_status = "not_detected"
        if frame_bytes:
            face_result = face_embedding.detect_face_region_from_bytes(frame_bytes)
            if face_result.found_face:
                face_status = "detected"
                face_box = face_result.box
                face_confidence = face_result.detection_confidence
            explainability = model_explainability.generate_occlusion_sensitivity(
                raw_bytes=frame_bytes,
                model_result=model_result,
                face_box=face_box,
                face_confidence=face_confidence,
                face_status=face_status,
                frame_timestamp_sec=getattr(heuristic, "frame_timestamp_sec", None),
            )
        else:
            explainability = model_explainability.generate_occlusion_sensitivity(
                raw_bytes=b"",
                model_result=model_result,
                face_box=None,
                face_confidence=None,
                face_status="not_detected",
                frame_timestamp_sec=getattr(heuristic, "frame_timestamp_sec", None),
            )
    except Exception as exc:
        explainability = {
            "status": "unavailable",
            "method": "blur-occlusion-sensitivity-v1",
            "message": f"Heatmap generation was unavailable ({type(exc).__name__}: {exc}).",
            "face_box": None,
            "face_confidence": None,
            "grid": None,
            "frame_timestamp_sec": getattr(heuristic, "frame_timestamp_sec", None),
        }

    if explainability and explainability.get("status") == "available":
        explanation = f"{explanation} Explainability: {explainability.get('message', 'Heatmap available.')}"

    existing = db.query(DetectionResult).filter(DetectionResult.media_item_id == media.id).first()
    if existing:
        db.delete(existing)
        db.flush()

    detection = DetectionResult(
        media_item_id=media.id,
        manipulation_likelihood=manipulation_likelihood,
        edge_irregularity=heuristic.edge_irregularity,
        compression_density=heuristic.compression_density,
        detected_region=None,
        likely_technique=None,
        model_name=model_name,
        explanation=explanation,
        explainability_json=json.dumps(explainability) if explainability is not None else None,
    )
    db.add(detection)
    db.commit()
    db.refresh(detection)
    return detection


@router.post("/{incident_id}/media/{media_id}/fingerprint", response_model=FingerprintOut)
def run_fingerprint(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    media = _get_media_item(incident_id, media_id, db, current_user)
    raw = file_storage.read_decrypted(media.storage_path)

    try:
        if media.kind == "image":
            analysis = pixel_analysis.analyze_image_bytes(raw)
            face_bytes = raw
        else:
            suffix = Path(media.original_filename).suffix or ".mp4"
            analysis = pixel_analysis.analyze_video_bytes(raw, suffix=suffix)
            face_bytes = pixel_analysis.extract_video_frame_jpeg(raw, suffix=suffix)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not analyze this file: {e}")

    # Real face embedding (TRD §5.2) — closes the gap the frontend prototype
    # explicitly could not: "computing a real face embedding needs a trained
    # model, which this no-backend prototype doesn't run."
    try:
        face_result = face_embedding.extract_face_embedding_from_bytes(face_bytes)
        face_embedding_json = face_embedding.embedding_to_json(face_result)
    except Exception as e:
        face_embedding_json = json.dumps({"found_face": False, "error": str(e)})

    existing = db.query(Fingerprint).filter(Fingerprint.media_item_id == media.id).first()
    if existing:
        db.delete(existing)
        db.flush()

    fingerprint = Fingerprint(
        media_item_id=media.id,
        average_hash=analysis.average_hash,
        face_embedding_json=face_embedding_json,
        keyframe_hashes_json=json.dumps(
            [{"frame_sec": analysis.frame_timestamp_sec, "hash": analysis.average_hash}]
        ) if analysis.frame_timestamp_sec is not None else None,
        audio_fingerprint=None,  # real audio fingerprinting is a further Phase 2 extension
    )
    db.add(fingerprint)
    incident.status = "fingerprinted"
    db.commit()
    db.refresh(fingerprint)
    return fingerprint


@router.get("/{incident_id}/media/{media_id}/detection", response_model=DetectionResultOut)
def get_detection(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    media = _get_media_item(incident_id, media_id, db, current_user)
    if not media.detection_result:
        raise HTTPException(status_code=404, detail="No detection result yet — run /detect first.")
    return media.detection_result


@router.get("/{incident_id}/media/{media_id}/fingerprint", response_model=FingerprintOut)
def get_fingerprint(
    incident_id: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    media = _get_media_item(incident_id, media_id, db, current_user)
    if not media.fingerprint:
        raise HTTPException(status_code=404, detail="No fingerprint yet — run /fingerprint first.")
    return media.fingerprint
