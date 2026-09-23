from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class QuizGenerateRequest(BaseModel):
    topic: str = Field(..., example="Australian History")
    subtopic: Optional[str] = None
    audience_type: str = Field(default="primary", example="primary")  # primary, middle_school, high_school, college, adult, general
    grades: Optional[List[int]] = Field(default=None)
    age_range: Optional[str] = None
    grade_min: Optional[int] = Field(default=None, ge=1, le=12)
    grade_max: Optional[int] = Field(default=None, ge=1, le=12)
    difficulty: Optional[str] = Field(default="Balanced", example="Balanced")
    difficulty_distribution: Optional[Dict[str, int]] = Field(
        default_factory=lambda: {"easy": 3, "medium": 5, "hard": 2}
    )
    question_count: int = Field(default=10, ge=1, le=50)
    question_types: List[str] = Field(default=["SLIDE_QA"])
    generation_mode: str = Field(default="NEW", example="NEW")  # NEW, REMIX, HISTORICAL, SIMILAR
    tags: Optional[List[str]] = Field(default=None, description="Focus concept tags")
    tag_match_mode: str = Field(default="ANY", description="ANY or ALL")
    personality: str = Field(default="CURIOSITY_STORYTELLER", description="CURIOSITY_STORYTELLER, DETECTIVE_PUZZLER, TOURNAMENT_PRO, SOCRATIC_EXPLORER")
    style: str = Field(default="QSHALA_HISTORICAL")
    raw_prompt: Optional[str] = None

class RetrievalSourceResponse(BaseModel):
    id: str
    historical_question_id: Optional[str] = None
    document_id: Optional[str] = None
    slide_id: Optional[str] = None
    document_title: Optional[str] = None
    slide_number: Optional[int] = None
    relevance_score: float = 1.0
    source_quote: Optional[str] = None
    rationale: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class GeneratedQuestionResponse(BaseModel):
    id: str
    quiz_id: str
    order_index: int
    question_text: str
    options: Optional[List[str]] = None
    answer: str
    explanation: Optional[str] = None
    difficulty: str
    grade_min: Optional[int] = None
    grade_max: Optional[int] = None
    topic: Optional[str] = None
    question_type: str
    validation_status: str
    validation_details: Optional[Dict[str, Any]] = None
    duplicate_score: float = 0.0
    is_approved: bool = True
    created_at: datetime
    retrieval_sources: List[RetrievalSourceResponse] = []
    model_config = ConfigDict(from_attributes=True)

class GeneratedQuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    options: Optional[List[str]] = None
    answer: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    grade_min: Optional[int] = None
    grade_max: Optional[int] = None
    is_approved: Optional[bool] = None
    order_index: Optional[int] = None

class QuestionActionRequest(BaseModel):
    action: str  # "regenerate", "make_easier", "make_harder", "generate_similar"
    custom_instruction: Optional[str] = None

class QuizResponse(BaseModel):
    id: str
    title: str
    topic: str
    subtopic: Optional[str] = None
    audience_type: Optional[str] = "primary"
    grades: Optional[List[int]] = None
    age_range: Optional[str] = None
    grade_min: Optional[int] = None
    grade_max: Optional[int] = None
    difficulty: Optional[str] = "Balanced"
    difficulty_distribution: Optional[Dict[str, int]] = None
    question_count: int
    question_types: List[str]
    generation_mode: str
    tags: Optional[List[str]] = []
    personality: Optional[str] = "CURIOSITY_STORYTELLER"
    style: str
    raw_prompt: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    questions: List[GeneratedQuestionResponse] = []
    model_config = ConfigDict(from_attributes=True)

class ExportRequest(BaseModel):
    format: str = "json"  # json, csv, printable_html
