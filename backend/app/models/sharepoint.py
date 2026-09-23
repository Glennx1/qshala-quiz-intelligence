from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, BigInteger, Text, DateTime
from backend.app.database import Base

class SharePointSyncState(Base):
    __tablename__ = "sharepoint_sync_state"

    id = Column(String(50), primary_key=True)  # e.g., 'qshala_main_library'
    site_id = Column(String(255), nullable=True)
    drive_id = Column(String(255), nullable=True)
    delta_token = Column(Text, nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="IDLE")  # IDLE, SYNCING, FAILED
    total_files_tracked = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SharePointFile(Base):
    __tablename__ = "sharepoint_files"

    id = Column(String(255), primary_key=True)  # Microsoft Graph driveItem.id
    name = Column(String(255), nullable=False)
    web_url = Column(Text, nullable=True)
    etag = Column(String(100), nullable=True)
    c_tag = Column(String(100), nullable=True)
    file_size_bytes = Column(BigInteger, default=0)
    last_modified_date_time = Column(DateTime(timezone=True), nullable=True)
    blob_url = Column(Text, nullable=True)
    sync_status = Column(String(50), default="DISCOVERED")  # DISCOVERED, QUEUED, COMPLETED, FAILED, DELETED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
