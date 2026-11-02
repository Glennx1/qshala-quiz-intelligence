import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, JSON
from backend.app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    total_expected = Column(Integer, nullable=False)
    items = Column(JSON, default=list)  # list of {client_item_id, filename, size_bytes}
