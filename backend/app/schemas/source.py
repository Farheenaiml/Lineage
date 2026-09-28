from datetime import datetime

from pydantic import BaseModel


class SourceCreate(BaseModel):
    platform: str
    account_identifier: str | None = None
    url: str | None = None
    observed_at: datetime
    similarity_score: float | None = None
    relationship_label: str | None = None
    is_seeded: bool = True


class SourceOut(BaseModel):
    id: str
    platform: str
    account_identifier: str | None
    url: str | None
    observed_at: datetime
    similarity_score: float | None
    relationship_label: str | None
    is_seeded: bool

    class Config:
        from_attributes = True


class SourceRelationshipCreate(BaseModel):
    from_source_id: str
    to_source_id: str
    relationship_type: str
    confidence: float | None = None


class SourceRelationshipOut(BaseModel):
    id: str
    from_source_id: str
    to_source_id: str
    relationship_type: str
    confidence: float | None

    class Config:
        from_attributes = True


class EvidenceItemOut(BaseModel):
    id: str
    source_id: str | None
    item_type: str
    notes: str | None
    captured_at: datetime

    class Config:
        from_attributes = True
