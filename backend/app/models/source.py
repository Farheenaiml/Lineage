from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Boolean, Text
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.user import gen_uuid

UPLOAD_SOURCE_PLATFORM = "User upload"


class Source(Base):
    """
    A place related/matching content was observed — real or seeded. The
    `is_seeded` flag is load-bearing: it's what lets the frontend honestly
    label seeded vs. live data, and it's why this is a real column rather
    than something inferred client-side.
    """
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)

    platform = Column(String, nullable=False)
    account_identifier = Column(String, nullable=True)
    url = Column(String, nullable=True)
    observed_at = Column(DateTime, nullable=False)
    similarity_score = Column(Float, nullable=True)  # 0-100
    relationship_label = Column(String, nullable=True)  # e.g. "earliest observed source", "repost of SRC-A"
    is_seeded = Column(Boolean, default=True)  # False once real search (Phase 8) populates this
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="sources")
    evidence_items = relationship("EvidenceItem", back_populates="source", cascade="all, delete-orphan")


class SourceRelationship(Base):
    """An edge in the lineage graph — how two observed sources relate."""
    __tablename__ = "source_relationships"

    id = Column(String, primary_key=True, default=gen_uuid)
    from_source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    to_source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    relationship_type = Column(String, nullable=False)  # "repost" | "crop + re-share" | etc.
    confidence = Column(Float, nullable=True)  # 0-100
    created_at = Column(DateTime, default=datetime.utcnow)


class EvidenceItem(Base):
    """One preserved unit of evidence in the Evidence Locker."""
    __tablename__ = "evidence_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    source_id = Column(String, ForeignKey("sources.id"), nullable=True)

    item_type = Column(String, nullable=False)  # "screenshot", "metadata_snapshot", etc.
    storage_path = Column(String, nullable=True)  # encrypted, like MediaItem
    notes = Column(Text, nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="evidence_items")
    source = relationship("Source", back_populates="evidence_items")
