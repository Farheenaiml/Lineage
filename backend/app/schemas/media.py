from datetime import datetime

from pydantic import BaseModel


class MediaItemOut(BaseModel):
    id: str
    kind: str
    original_filename: str
    file_size_bytes: int
    width: int | None
    height: int | None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class DetectionResultOut(BaseModel):
    id: str
    manipulation_likelihood: float
    edge_irregularity: float | None
    compression_density: float | None
    detected_region: str | None
    likely_technique: str | None
    model_name: str
    explanation: str | None
    explainability_json: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class FingerprintOut(BaseModel):
    id: str
    average_hash: str
    face_embedding_json: str | None
    keyframe_hashes_json: str | None
    audio_fingerprint: str | None
    created_at: datetime

    class Config:
        from_attributes = True
