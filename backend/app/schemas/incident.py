from datetime import datetime

from pydantic import BaseModel


class IncidentCreate(BaseModel):
    title: str
    description: str | None = None
    victim_ref: str | None = None


class IncidentOut(BaseModel):
    id: str
    title: str
    description: str | None
    victim_ref: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
