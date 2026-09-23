import sqlite3
import sys
from pathlib import Path

# Try to find qshala.db
candidate_paths = [
    Path("backend/qshala.db"),
    Path("qshala.db"),
    Path(__file__).resolve().parent / "qshala.db"
]

db_path = next((p for p in candidate_paths if p.exists()), None)
if not db_path:
    print("Database file does not exist yet.")
    sys.exit(0)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

def add_columns(table_name, columns):
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_cols = [row[1] for row in cursor.fetchall()]
    for col_name, col_type in columns:
        if col_name not in existing_cols:
            print(f"Adding column {col_name} to {table_name}...")
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Warning: could not add {col_name} to {table_name}: {e}")

# 1. Quizzes columns
add_columns("quizzes", [
    ("audience_type", "TEXT DEFAULT 'primary'"),
    ("grades", "TEXT DEFAULT '[]'"),
    ("age_range", "TEXT"),
    ("difficulty_distribution", "TEXT DEFAULT '{}'")
])

# 2. Documents columns
add_columns("documents", [
    ("blob_url", "TEXT"),
    ("source", "TEXT DEFAULT 'MANUAL'"),
    ("sharepoint_file_id", "TEXT")
])

# 3. Questions columns
add_columns("questions", [
    ("image_refs", "TEXT DEFAULT '[]'"),
    ("visual_clues", "TEXT"),
    ("audio_transcript", "TEXT"),
    ("video_transcript", "TEXT"),
    ("raw_media_refs", "TEXT DEFAULT '[]'"),
    ("source_slide_range", "TEXT"),
    ("duplicate_status", "TEXT DEFAULT 'UNIQUE'"),
    ("duplicate_similarity", "REAL"),
    ("duplicate_of_id", "TEXT")
])

# 4. Create SharePoint and Job queue tables if missing
cursor.execute("""
CREATE TABLE IF NOT EXISTS sharepoint_sync_state (
    id VARCHAR(50) PRIMARY KEY,
    site_id VARCHAR(255),
    drive_id VARCHAR(255),
    delta_token TEXT,
    last_sync_at TIMESTAMP,
    status VARCHAR(50) DEFAULT 'IDLE',
    total_files_tracked INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sharepoint_files (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    web_url TEXT,
    etag VARCHAR(100),
    c_tag VARCHAR(100),
    file_size_bytes BIGINT DEFAULT 0,
    last_modified_date_time TIMESTAMP,
    blob_url TEXT,
    sync_status VARCHAR(50) DEFAULT 'DISCOVERED',
    error_message TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id VARCHAR(36) PRIMARY KEY,
    source_type VARCHAR(50) DEFAULT 'SHAREPOINT',
    source_file_id VARCHAR(255),
    filename VARCHAR(255) NOT NULL,
    blob_url TEXT,
    status VARCHAR(50) DEFAULT 'PENDING',
    current_step VARCHAR(50) DEFAULT 'DOWNLOAD',
    step_data JSON DEFAULT '{}',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_message TEXT,
    document_id VARCHAR(36),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);
""")

conn.commit()
conn.close()
print("Migration completed successfully.")
