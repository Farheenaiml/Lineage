from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.report import AttributionGapEntry
from app.models.user import User
from app.schemas.report import AttributionGapEntryOut
from app.services.attribution import build_attribution_gap
from app.routers.incidents import _get_owned_incident

router = APIRouter(prefix="/incidents", tags=["attribution"])


@router.post("/{incident_id}/attribution-gap", response_model=list[AttributionGapEntryOut])
def generate_attribution_gap(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)

    db.query(AttributionGapEntry).filter(AttributionGapEntry.incident_id == incident.id).delete()
    entries = build_attribution_gap(incident, db)
    db.add_all(entries)

    incident.status = "gap_reviewed"
    db.commit()
    for e in entries:
        db.refresh(e)
    return entries


@router.get("/{incident_id}/attribution-gap", response_model=list[AttributionGapEntryOut])
def get_attribution_gap(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incident = _get_owned_incident(incident_id, db, current_user)
    return (
        db.query(AttributionGapEntry)
        .filter(AttributionGapEntry.incident_id == incident.id)
        .all()
    )
