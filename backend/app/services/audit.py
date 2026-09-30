"""Phase 5 audit trail helper. Records WHO (the authenticated user), WHAT and WHEN. Never touches evidence rows."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.automation import AuditEvent

ACTIONS = (
    "report_generated", "legacy_report_generated", "evidence_reviewed", "finding_reviewed",
    "location_added", "location_edited", "location_deleted", "direction_confirmed", "direction_revoked",
    "alert_draft_generated", "alert_draft_edited", "alert_draft_approved", "alert_draft_exported",
    "investigation_exported", "status_changed",
)


def record(db: Session, incident_id: str, user, action: str, *, target_type: str | None = None,
           target_id: str | None = None, details: dict | None = None, commit: bool = True) -> AuditEvent:
    """`user` is the authenticated User (or None for a system event, which is then stored with no actor)."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    ev = AuditEvent(
        incident_id=incident_id, actor_user_id=getattr(user, "id", None), actor_email=getattr(user, "email", None),
        action=action, target_type=target_type, target_id=target_id,
        details_json=json.dumps(details, default=str) if details else None, created_at=datetime.utcnow(),
    )
    db.add(ev)
    if commit:
        db.commit()
    return ev


def to_dict(ev: AuditEvent) -> dict:
    return {
        "id": ev.id, "incident_id": ev.incident_id, "action": ev.action, "target_type": ev.target_type,
        "target_id": ev.target_id, "actor": {"user_id": ev.actor_user_id, "email": ev.actor_email} if ev.actor_user_id else None,
        "details": json.loads(ev.details_json) if ev.details_json else None,
        "created_at": ev.created_at.isoformat() + "Z" if ev.created_at else None,
    }


def list_events(db: Session, incident_id: str) -> list[dict]:
    rows = db.query(AuditEvent).filter(AuditEvent.incident_id == incident_id).order_by(AuditEvent.created_at).all()
    return [to_dict(r) for r in rows]
