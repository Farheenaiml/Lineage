from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.source import Source, SourceRelationship
from app.models.user import User
from app.schemas.source import SourceCreate, SourceOut, SourceRelationshipCreate, SourceRelationshipOut
from app.routers.incidents import _get_owned_incident

router = APIRouter(prefix="/incidents", tags=["sources"])


@router.get("/{incident_id}/sources", response_model=list[SourceOut])
def list_sources(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    return db.query(Source).filter(Source.incident_id == incident.id).order_by(Source.observed_at).all()


@router.post("/{incident_id}/sources", response_model=SourceOut, status_code=201)
def add_source(
    incident_id: str,
    payload: SourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    source = Source(incident_id=incident.id, **payload.model_dump())
    db.add(source)
    if incident.status in ("created", "analyzing", "fingerprinted"):
        incident.status = "evidence_building"
    db.commit()
    db.refresh(source)
    return source


@router.post("/{incident_id}/sources/relationships", response_model=SourceRelationshipOut, status_code=201)
def add_relationship(
    incident_id: str,
    payload: SourceRelationshipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)

    valid_ids = {s.id for s in db.query(Source).filter(Source.incident_id == incident.id).all()}
    if payload.from_source_id not in valid_ids or payload.to_source_id not in valid_ids:
        raise HTTPException(status_code=400, detail="Both sources must belong to this incident.")

    rel = SourceRelationship(**payload.model_dump())
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


@router.get("/{incident_id}/sources/relationships", response_model=list[SourceRelationshipOut])
def list_relationships(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    source_ids = [s.id for s in db.query(Source).filter(Source.incident_id == incident.id).all()]
    if not source_ids:
        return []
    return (
        db.query(SourceRelationship)
        .filter(SourceRelationship.from_source_id.in_(source_ids))
        .all()
    )
