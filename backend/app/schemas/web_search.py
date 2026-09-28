from datetime import datetime

from pydantic import BaseModel, HttpUrl


class WebSearchConsent(BaseModel):
    consent: bool


class WebSearchQueryOut(BaseModel):
    query: str
    google_url: HttpUrl
    bing_url: HttpUrl


class WebSearchRunOut(BaseModel):
    id: str
    image_description: str
    summary: str
    model_name: str
    created_at: datetime
    search_queries: list[WebSearchQueryOut]