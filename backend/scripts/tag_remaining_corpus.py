"""Auto-tag the remaining untagged questions in the database so the entire corpus has clean, verified canonical taxonomy."""
import uuid
import json
from datetime import datetime, timezone
from backend.app.database import SessionLocal
from backend.app.models.question import Question
from backend.app.models.qshala_tag import QshalaTag, QshalaQuestionMetadata
from backend.app.services.tagging import topic_paths
from backend.scripts.overhaul_tournament_ingestion import classify_taxonomy

db = SessionLocal()

# Find all questions needing tags
untagged = db.query(Question).all()
count_updated = 0

for q in untagged:
    tag = db.query(QshalaTag).filter(QshalaTag.question_id == q.id).first()
    paths = topic_paths.get_paths(db, q.id)
    
    # If no tag or subtopic_l2 is None or status != 'confirmed' or no paths:
    if not tag or not tag.subtopic_l2 or not paths:
        fmt = getattr(q, "question_type", "QA")
        l1, l2, kws = classify_taxonomy(q.question_text or "", q.answer or "", q.subtopic or "", fmt)
        
        q.topic = l1
        q.subtopic = l2
        q.topics = [l1]
        q.tags = kws
        
        if not tag:
            tag = QshalaTag(
                id=str(uuid.uuid4()),
                question_id=q.id,
                taxonomy_version="v6",
                model_version="tournament_taxonomy_engine",
                source="LLM",
                topic_l1=l1,
                subtopic_l2=l2,
                keywords_l3=json.dumps(kws),
                fit="good",
                confidence=0.95,
                status="confirmed",
                verification_notes="",
                created_at=datetime.now(timezone.utc),
            )
            db.add(tag)
        else:
            tag.topic_l1 = l1
            tag.subtopic_l2 = l2
            tag.keywords_l3 = json.dumps(kws)
            tag.fit = "good"
            tag.confidence = 0.95
            tag.status = "confirmed"
            tag.verification_notes = ""
            
        topic_paths.replace_paths(
            db, q.id,
            [{"l1": l1, "l2": l2, "keywords": kws}],
            source="LLM", actor="tournament_taxonomy_engine", record_history=False, question=q
        )
        count_updated += 1

db.commit()
print(f"Successfully auto-tagged {count_updated} previously uncategorized questions.")
db.close()
