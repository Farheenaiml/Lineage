from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.user import gen_uuid

# Mirrors the state machine in the Project Flow doc. Kept as a plain string
# column (not a DB enum) so new states can be added without a migration.
INCIDENT_STATES = [
    "created",
    "analyzing",
    "fingerprinted",
    "evidence_building",
    "gap_reviewed",
    "report_generated",
    "closed",
]


class Incident(Base):
    """
    The top-level case record — one per investigation. Everything else
    (media, detection results, sources, evidence, the report) hangs off this.
    """
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=gen_uuid)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Pseudonymous by design (TRD §7.1) — this is never a real name field.
    victim_ref = Column(String, nullable=True)

    status = Column(String, default="created")  # one of INCIDENT_STATES
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="incidents")
    media_items = relationship("MediaItem", back_populates="incident", cascade="all, delete-orphan")
    sources = relationship("Source", back_populates="incident", cascade="all, delete-orphan")
    evidence_items = relationship("EvidenceItem", back_populates="incident", cascade="all, delete-orphan")
    attribution_entries = relationship("AttributionGapEntry", back_populates="incident", cascade="all, delete-orphan")
    report = relationship("IncidentReport", back_populates="incident", uselist=False, cascade="all, delete-orphan")
