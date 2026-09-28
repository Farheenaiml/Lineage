from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Text, Integer
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.user import gen_uuid


class MediaItem(Base):
    """The original suspicious media a user uploaded for a given incident."""
    __tablename__ = "media_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)

    kind = Column(String, nullable=False)  # "image" | "video"
    original_filename = Column(String, nullable=False)
    # Path to the *encrypted* file on disk — never the plaintext path.
    storage_path = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("Incident", back_populates="media_items")
    detection_result = relationship("DetectionResult", back_populates="media_item", uselist=False, cascade="all, delete-orphan")
    fingerprint = relationship("Fingerprint", back_populates="media_item", uselist=False, cascade="all, delete-orphan")


class DetectionResult(Base):
    """
    Output of the Detection Module (TRD §5.1). In this phase this is populated
    by the same honest pixel-heuristic used in the frontend prototype, ported
    server-side — NOT a trained deepfake classifier. That swap is Phase 2.
    """
    __tablename__ = "detection_results"

    id = Column(String, primary_key=True, default=gen_uuid)
    media_item_id = Column(String, ForeignKey("media_items.id"), nullable=False)

    manipulation_likelihood = Column(Float, nullable=False)  # 0-100
    edge_irregularity = Column(Float, nullable=True)
    compression_density = Column(Float, nullable=True)
    detected_region = Column(String, nullable=True)
    likely_technique = Column(String, nullable=True)
    model_name = Column(String, default="pixel-heuristic-v1")  # honestly named, not "deepfake-detector"
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    media_item = relationship("MediaItem", back_populates="detection_result")


class Fingerprint(Base):
    """Output of the Fingerprinting Module (TRD §5.2) — real, computed values."""
    __tablename__ = "fingerprints"

    id = Column(String, primary_key=True, default=gen_uuid)
    media_item_id = Column(String, ForeignKey("media_items.id"), nullable=False)

    average_hash = Column(String, nullable=False)  # real 64-bit aHash, hex
    face_embedding_json = Column(Text, nullable=True)  # not populated until a real face model is added
    keyframe_hashes_json = Column(Text, nullable=True)
    audio_fingerprint = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    media_item = relationship("MediaItem", back_populates="fingerprint")
