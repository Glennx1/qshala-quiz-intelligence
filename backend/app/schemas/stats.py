from typing import List, Dict, Any
from pydantic import BaseModel

class DashboardStatsResponse(BaseModel):
    total_documents: int
    total_slides: int
    total_questions: int
    total_topics: int
    total_quizzes: int
    recent_documents: List[Dict[str, Any]]
    recent_quizzes: List[Dict[str, Any]]
    top_topics: List[Dict[str, Any]]
