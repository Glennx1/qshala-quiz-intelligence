import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_type = Column(String(50), default="SHAREPOINT")  # SHAREPOINT, MANUAL_UPLOAD
    source_file_id = Column(String(255), nullable=True)  # SharePoint file ID or upload ref
    filename = Column(String(255), nullable=False)
    blob_url = Column(Text, nullable=True)
    status = Column(String(50), default="PENDING")  # PENDING, PROCESSING, COMPLETED, FAILED
    current_step = Column(String(50), default="DOWNLOAD")
    step_data = Column(JSON, default=dict)  # State cursors and intermediate manifests
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    error_message = Column(Text, nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    document = relationship("Document", foreign_keys=[document_id])
