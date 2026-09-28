import mimetypes

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.source import EvidenceItem, Source
from app.models.media import MediaItem
from app.models.user import User
from app.schemas.source import EvidenceItemOut
from app.services import file_storage
from app.routers.incidents import _get_owned_incident

router = APIRouter(prefix="/incidents", tags=["evidence"])


@router.get("/{incident_id}/evidence", response_model=list[EvidenceItemOut])
def list_evidence(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    return (
        db.query(EvidenceItem)
        .filter(EvidenceItem.incident_id == incident.id)
        .order_by(EvidenceItem.captured_at)
        .all()
    )


@router.post("/{incident_id}/evidence", response_model=EvidenceItemOut, status_code=201)
async def upload_evidence(
    incident_id: str,
    item_type: str = Form(...),
    source_id: str | None = Form(None),
    notes: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Real persistence for the Evidence Locker (TRD §6): a screenshot or other
    file is encrypted and stored the same way MediaItem uploads are, and the
    resulting EvidenceItem row is what the Evidence Locker screen lists.
    `file` is optional so a purely textual evidence note (e.g. an account
    metadata snapshot with no image) can still be recorded.
    """
    incident = _get_owned_incident(incident_id, db, current_user)

    if source_id:
        source = db.query(Source).filter(Source.id == source_id, Source.incident_id == incident.id).first()
        if not source:
            raise HTTPException(status_code=400, detail="source_id does not belong to this incident.")

    storage_path = None
    if file is not None:
        raw = await file.read()
        storage_path, _ = file_storage.save_encrypted(raw, file.filename or "evidence")

    evidence = EvidenceItem(
        incident_id=incident.id,
        source_id=source_id,
        item_type=item_type,
        storage_path=storage_path,
        notes=notes,
    )
    db.add(evidence)
    if incident.status in ("created", "analyzing", "fingerprinted"):
        incident.status = "evidence_building"
    db.commit()
    db.refresh(evidence)
    return evidence


@router.get("/{incident_id}/evidence/{evidence_id}/file")
def download_evidence_file(
    incident_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Decrypts and returns the raw bytes of a preserved evidence file.
    Requires the same auth as everything else here — evidence access should
    be audited in a real deployment (see TRD §8); that audit log is not yet
    implemented (tracked in the backend README's known-gaps list)."""
    incident = _get_owned_incident(incident_id, db, current_user)
    evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == evidence_id, EvidenceItem.incident_id == incident.id)
        .first()
    )
    if not evidence or not evidence.storage_path:
        raise HTTPException(status_code=404, detail="No file attached to this evidence item.")

    raw = file_storage.read_decrypted(evidence.storage_path)
    media = (
        db.query(MediaItem)
        .filter(
            MediaItem.incident_id == incident.id,
            MediaItem.storage_path == evidence.storage_path,
        )
        .first()
    )
    media_type = mimetypes.guess_type(media.original_filename)[0] if media else None
    return Response(content=raw, media_type=media_type or "application/octet-stream")
