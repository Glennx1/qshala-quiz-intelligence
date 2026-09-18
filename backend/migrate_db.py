import sqlite3
from pathlib import Path

db_path = Path("backend/qshala.db")
if not db_path.exists():
    print("Database file does not exist yet.")
    exit(0)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(quizzes)")
cols = [row[1] for row in cursor.fetchall()]
print("Existing columns in quizzes:", cols)

new_cols = [
    ("audience_type", "TEXT DEFAULT 'primary'"),
    ("grades", "TEXT DEFAULT '[]'"),
    ("age_range", "TEXT"),
    ("difficulty_distribution", "TEXT DEFAULT '{}'")
]

for col_name, col_type in new_cols:
    if col_name not in cols:
        print(f"Adding column {col_name}...")
        cursor.execute(f"ALTER TABLE quizzes ADD COLUMN {col_name} {col_type}")

conn.commit()
conn.close()
print("Migration completed successfully.")
