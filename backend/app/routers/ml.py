"""
Phase 4 — ML Intelligence API (read-only analysis; never writes evidence, sources, locations or statuses).

GET /incidents/{id}/ml                 -> all three analyses          (?scope=owner|investigation)
GET /incidents/{id}/ml/similarity      -> visually similar media      (?scope= &threshold=)
GET /incidents/{id}/ml/anomalies       -> unusual patterns vs. this investigation's own baseline
GET /incidents/{id}/ml/clusters        -> single-linkage media clusters (?scope= &threshold=)

scope=owner compares against every investigation owned by the same investigator (default); scope=investigation stays
inside this one. Results are computed on request from stored records, with model name/version/timestamp provenance.
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models.user import User
from app.routers.incidents import _get_owned_incident
from app.services import ml_intelligence as ml

router = APIRouter(prefix="/incidents", tags=["ml"])
Scope = Literal["owner", "investigation"]


@router.get("/{incident_id}/ml")
def ml_all(incident_id: str, scope: Scope = "owner", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ml.run_all(_get_owned_incident(incident_id, db, current_user), db, scope=scope)


@router.get("/{incident_id}/ml/similarity")
def ml_similarity(
    incident_id: str, scope: Scope = "owner", threshold: float | None = Query(default=None, ge=0.5, le=1.0),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return ml.run_similarity(_get_owned_incident(incident_id, db, current_user), db, scope=scope, threshold=threshold)


@router.get("/{incident_id}/ml/anomalies")
def ml_anomalies(incident_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return ml.run_anomalies(_get_owned_incident(incident_id, db, current_user), db)


@router.get("/{incident_id}/ml/clusters")
def ml_clusters(
    incident_id: str, scope: Scope = "owner", threshold: float | None = Query(default=None, ge=0.5, le=1.0),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return ml.run_clusters(_get_owned_incident(incident_id, db, current_user), db, scope=scope, threshold=threshold)
