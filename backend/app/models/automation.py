"""
Phase 5 — Investigation Automation tables. All additive (created by the existing create_all); no existing table changes.

None of these rows is evidence. They record what an investigator did (AuditEvent) and derived documents built from
evidence (InvestigationReport, AlertDraft), each keeping the ids of the records it was built from.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.db.session import Base
from app.models.user import gen_uuid


class AuditEvent(Base):
    """Append-only record of an investigator action. The actor is always the authenticated user (never inferred)."""
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False, index=True)
    actor_user_id = Column(String, ForeignKey("users.id"), nullable=True)   # null only for system-recorded events
    actor_email = Column(String, nullable=True)                           # copied from the session user at the time
    action = Column(String, nullable=False)          # e.g. report_generated, location_edited, alert_draft_approved
    target_type = Column(String, nullable=True)      # evidence | source | location | relationship | ml_finding | report | alert_draft | incident
    target_id = Column(String, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class InvestigationReport(Base):
    """Phase 5 investigation report. Versioned (every generation is kept); separate from the Phase 1 IncidentReport."""
    __tablename__ = "investigation_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    generated_by = Column(String, ForeignKey("users.id"), nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    report_json = Column(Text, nullable=False)


class AlertDraft(Base):
    """
    Reviewable cyber-department notification DRAFT. LINEAGE never transmits it: 'approved' and 'exported' only record
    the investigator's decision / download. The evidence sections are generated; only the free-text fields are editable.
    """
    __tablename__ = "alert_drafts"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="draft")   # draft | approved
    content_json = Column(Text, nullable=False)               # generated sections (evidence refs, timeline, findings)
    summary_text = Column(Text, nullable=True)                # investigator-editable
    request_text = Column(Text, nullable=True)                # investigator-editable
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    exported_at = Column(DateTime, nullable=True)
