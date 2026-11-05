import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime
from backend.app.database import Base


class IngestionUsage(Base):
    """AI token usage per deck and stage (vision, tagging). Deliberately has no foreign key to documents, so the
    cost history survives deleting or cancelling a deck."""
    __tablename__ = "ingestion_usage"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), index=True, nullable=False)
    stage = Column(String(32), nullable=False)           # vision | tagging
    model = Column(String(64), nullable=True)
    calls = Column(Integer, default=0)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    thinking_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
