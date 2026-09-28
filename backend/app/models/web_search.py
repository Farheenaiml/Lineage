from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.user import gen_uuid


class WebSearchRun(Base):
    __tablename__ = "web_search_runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)
    media_item_id = Column(String, ForeignKey("media_items.id"), nullable=False)
    image_description = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    search_queries_json = Column(Text, nullable=False, default="[]")
    model_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    search_queries = relationship("WebSearchQuery", back_populates="run", cascade="all, delete-orphan")


class WebSearchQuery(Base):
    __tablename__ = "web_search_queries"

    id = Column(String, primary_key=True, default=gen_uuid)
    run_id = Column(String, ForeignKey("web_search_runs.id"), nullable=False)
    query = Column(Text, nullable=False)
    google_url = Column(Text, nullable=False)
    bing_url = Column(Text, nullable=False)

    run = relationship("WebSearchRun", back_populates="search_queries")

