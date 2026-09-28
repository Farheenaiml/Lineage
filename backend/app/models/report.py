from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.user import gen_uuid


class IncidentReport(Base):
    """
    The final, exportable report. `report_json` holds the full structured
    payload (summary, confidence breakdown, recommended actions) so the
    report always has the same required sections regardless of how the
    prose inside them was generated (TRD §5.4) — the schema is deterministic
    even when an LLM writes the sentences.
    """
    __tablename__ = "incident_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), unique=True, nullable=False)

    report_json = Column(Text, nullable=False)  # serialized structured report
    generated_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="report")


class AttributionGapEntry(Base):
    """
    One row of the Attribution Gap Report — always tagged as known,
    unresolved, or evidence_needed so the UI can render the three-column
    honesty layout directly from these rows (TRD §5.5).
    """
    __tablename__ = "attribution_gap_entries"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)

    category = Column(String, nullable=False)  # "known" | "unresolved" | "evidence_needed"
    statement = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="attribution_entries")
