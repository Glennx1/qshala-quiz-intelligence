import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, JSON
from backend.app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    upload_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), nullable=False)
    raw_key = Column(String(512), nullable=False)
    r2_upload_id = Column(String(256), nullable=False)
    parts = Column(JSON, default=dict)
    total_bytes = Column(BigInteger, default=0)
    filename = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    year = Column(Integer, nullable=True)
    batch_id = Column(String(64), index=True, nullable=True)
    client_item_id = Column(String(64), nullable=True)
    status = Column(String(32), index=True, default="OPEN")  # OPEN, COMPLETED, CANCELLED
    document_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
