import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base, get_vector_column_type
from backend.app.config import settings

def generate_uuid():
    return str(uuid.uuid4())

class Question(Base):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    content_hash = Column(String(64), index=True, nullable=True) # Canonical hash for O(1) deduplication
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    slide_id = Column(String(36), ForeignKey("slides.id", ondelete="SET NULL"), nullable=True)
    answer_slide_id = Column(String(36), ForeignKey("slides.id", ondelete="SET NULL"), nullable=True)
    
    question_text = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)  # List of strings for MCQs, e.g. ["A) ...", "B) ..."]
    explanation = Column(Text, nullable=True)
    
    topic = Column(String(100), nullable=False, index=True)
    subtopic = Column(String(100), nullable=True, index=True)
    topics = Column(JSON, default=list) # Multi-topic tags, e.g. ["History", "Science", "Politics"]
    tags = Column(JSON, default=list)   # Named entities and secondary keywords
    
    difficulty = Column(String(20), default="Medium")  # Easy, Medium, Hard
    difficulty_score = Column(Float, default=0.50)     # Continuous PDI 0.00 - 1.00
    cognitive_level = Column(String(50), default="Recall / Remember")
    grade_min = Column(Integer, default=3)
    grade_max = Column(Integer, default=12)
    audience_suitability = Column(JSON, default=list)  # ["primary", "middle_school", ...]
    
    question_hook = Column(String(50), default="DIRECT_TRIVIA")
    curiosity_score = Column(Integer, default=7)
    temporal_nature = Column(String(20), default="EVERGREEN")
    
    provenance_decks = Column(JSON, default=list)      # List of all document IDs where this appeared
    occurrence_count = Column(Integer, default=1)
    
    question_type = Column(String(50), default="SLIDE_QA")
    source_year = Column(Integer, nullable=True)
    round_number = Column(Integer, nullable=True)

    # Multi-modal media & canonical representations
    image_refs = Column(JSON, default=list)            # List of Blob URLs for images
    visual_clues = Column(Text, nullable=True)         # OCR text & Gemini vision description
    audio_transcript = Column(Text, nullable=True)     # Transcribed audio speech/clue
    video_transcript = Column(Text, nullable=True)     # Transcribed video speech
    raw_media_refs = Column(JSON, default=list)        # Original media files in Blob
    source_slide_range = Column(String(50), nullable=True) # e.g. "Slide 4-5"

    # Deduplication & Human Review
    duplicate_status = Column(String(50), default="UNIQUE", index=True) # UNIQUE, POSSIBLE_DUPLICATE, CONFIRMED_DUPLICATE, RESOLVED
    duplicate_similarity = Column(Float, nullable=True)
    duplicate_of_id = Column(String(36), ForeignKey("questions.id", ondelete="SET NULL"), nullable=True)
    
    embedding = Column(get_vector_column_type(settings.EMBEDDING_DIM), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    document = relationship("Document", back_populates="questions")
    slide = relationship("Slide", foreign_keys=[slide_id], back_populates="questions")
    answer_slide = relationship("Slide", foreign_keys=[answer_slide_id])
    duplicate_of = relationship("Question", remote_side=[id], foreign_keys=[duplicate_of_id])
