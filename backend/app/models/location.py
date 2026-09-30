from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Text

from app.db.session import Base
from app.models.user import gen_uuid

# Provenance tiers. These are load-bearing for the forensic UI:
#   exif_gps              -> machine-extracted from preserved evidence metadata (VERIFIED tier)
#   public_metadata       -> read from a public source's own metadata (VERIFIED tier only if evidence-linked)
#   investigator_supplied -> typed/selected by a human investigator (NOT machine-verified)
#   inferred              -> derived heuristically (NEVER counted as a verified observation)
PROVENANCE_TIERS = ("exif_gps", "public_metadata", "investigator_supplied", "inferred")
VERIFIED_PROVENANCE = {"exif_gps", "public_metadata"}


class SourceLocation(Base):
    """
    Where a Source was observed / shared from. One row per source. Coordinates
    are NEVER invented: a row exists only when metadata or an investigator
    supplied it, and every row carries provenance + confidence + basis.
    """
    __tablename__ = "source_locations"

    id = Column(String, primary_key=True, default=gen_uuid)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False, unique=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    place_name = Column(String, nullable=True)
    city = Column(String, nullable=True)      # Phase 2: only ever filled from a geocoder result / investigator entry
    region = Column(String, nullable=True)    # Phase 2: state / province; NULL = not recorded (never guessed)
    country = Column(String, nullable=True)

    provenance = Column(String, nullable=False)          # one of PROVENANCE_TIERS
    confidence = Column(Float, nullable=False)           # 0-100
    basis = Column(Text, nullable=True)                  # human-readable "how do we know"
    evidence_item_id = Column(String, ForeignKey("evidence_items.id"), nullable=True)

    recorded_by = Column(String, nullable=True)          # user id or "system:exif"
    recorded_at = Column(DateTime, default=datetime.utcnow)


class RelationshipDirection(Base):
    """
    Investigator confirmation of a propagation direction. Absent row means the
    direction has NOT been confirmed: the map will then either show an
    explicitly-labelled 'inferred propagation direction' (timestamps agree)
    or an undirected relationship.
    """
    __tablename__ = "relationship_directions"

    id = Column(String, primary_key=True, default=gen_uuid)
    relationship_id = Column(String, ForeignKey("source_relationships.id"), nullable=False, unique=True)
    basis = Column(String, nullable=False, default="investigator_confirmed")
    note = Column(Text, nullable=True)
    confirmed_by = Column(String, nullable=True)
    confirmed_at = Column(DateTime, default=datetime.utcnow)
