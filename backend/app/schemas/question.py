from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict

class QuestionBase(BaseModel):
    question_text: str
    answer: str
    options: Optional[List[str]] = None
    explanation: Optional[str] = None
    topic: str
    subtopic: Optional[str] = None
    topics: List[str] = []
    tags: List[str] = []
    difficulty: str = "Medium"
    difficulty_score: float = 0.50
    cognitive_level: str = "Recall / Remember"
    grade_min: int = 3
    grade_max: int = 12
    audience_suitability: List[str] = []
    question_hook: str = "DIRECT_TRIVIA"
    curiosity_score: int = 7
    temporal_nature: str = "EVERGREEN"
    occurrence_count: int = 1
    provenance_decks: List[Dict[str, Any]] = []
    round_number: Optional[int] = None
    question_type: str = "SLIDE_QA"
    source_year: Optional[int] = None

class QuestionCreate(QuestionBase):
    document_id: str
    slide_id: Optional[str] = None
    answer_slide_id: Optional[str] = None

class QuestionResponse(QuestionBase):
    id: str
    content_hash: Optional[str] = None
    document_id: str
    slide_id: Optional[str] = None
    answer_slide_id: Optional[str] = None
    created_at: datetime
    document_title: Optional[str] = None
    slide_number: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class QuestionSearchParams(BaseModel):
    query: Optional[str] = None
    topic: Optional[str] = None
    grade_min: Optional[int] = None
    grade_max: Optional[int] = None
    difficulty: Optional[str] = None
    year: Optional[int] = None
    limit: int = 20
    offset: int = 0
