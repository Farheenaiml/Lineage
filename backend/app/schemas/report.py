from datetime import datetime

from pydantic import BaseModel


class AttributionGapEntryOut(BaseModel):
    id: str
    category: str  # "known" | "unresolved" | "evidence_needed"
    statement: str

    class Config:
        from_attributes = True


class ConfidenceBreakdownItem(BaseModel):
    label: str
    value: float
    note: str | None = None


class RecommendedAction(BaseModel):
    title: str
    detail: str


class IncidentReportPayload(BaseModel):
    """The deterministic schema every generated report must satisfy —
    mirrors TRD §5.4: the structure never varies even though an LLM may
    write the prose inside `summary`."""
    summary: str
    confidence_breakdown: list[ConfidenceBreakdownItem]
    recommended_actions: list[RecommendedAction]
    source_count: int
    evidence_count: int


class IncidentReportOut(BaseModel):
    id: str
    incident_id: str
    generated_at: datetime
    payload: IncidentReportPayload

    class Config:
        from_attributes = True
