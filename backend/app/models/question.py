import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base, get_vector_column_type
from backend.app.config import settings

def generate_uuid():
    return str(uuid.uuid4())

class Question(Base):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    slide_id = Column(String(36), ForeignKey("slides.id", ondelete="SET NULL"), nullable=True)
    answer_slide_id = Column(String(36), ForeignKey("slides.id", ondelete="SET NULL"), nullable=True)
    
    question_text = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)  # List of strings for MCQs, e.g. ["A) ...", "B) ..."]
    explanation = Column(Text, nullable=True)
    
    topic = Column(String(100), nullable=False, index=True)
    subtopic = Column(String(100), nullable=True, index=True)
    difficulty = Column(String(20), default="Medium")  # Easy, Medium, Hard
    grade_min = Column(Integer, default=3)
    grade_max = Column(Integer, default=12)
    question_type = Column(String(50), default="MULTIPLE_CHOICE")  # MULTIPLE_CHOICE, TRIVIA_SHORT_ANSWER, TRUE_FALSE, VISUAL
    source_year = Column(Integer, nullable=True)
    
    embedding = Column(get_vector_column_type(settings.EMBEDDING_DIM), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    document = relationship("Document", back_populates="questions")
    slide = relationship("Slide", foreign_keys=[slide_id], back_populates="questions")
    answer_slide = relationship("Slide", foreign_keys=[answer_slide_id])
