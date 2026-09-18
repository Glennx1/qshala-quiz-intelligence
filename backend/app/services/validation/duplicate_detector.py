import logging
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from backend.app.models.question import Question
from backend.app.services.ai.factory import get_embedding_provider
from backend.app.services.retrieval.vector_search import batch_cosine_similarities
from backend.app.config import settings

logger = logging.getLogger(__name__)

class DuplicateDetector:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_provider = get_embedding_provider()
        self.threshold = settings.DUPLICATE_SIMILARITY_THRESHOLD

    async def check_duplicate(self, question_text: str) -> Tuple[float, Optional[str], bool]:
        """
        Calculates cosine similarity of question_text against all historical questions.
        Returns: (highest_similarity_score, most_similar_question_text, is_duplicate)
        """
        all_questions = self.db.query(Question).all()
        if not all_questions:
            return 0.0, None, False

        q_emb = await self.embedding_provider.get_embedding(question_text)

        candidate_embs = []
        valid_questions = []
        for q in all_questions:
            if isinstance(q.embedding, list) and len(q.embedding) == len(q_emb):
                candidate_embs.append(q.embedding)
                valid_questions.append(q)

        if not candidate_embs:
            return 0.0, None, False

        similarities = batch_cosine_similarities(q_emb, candidate_embs)
        max_idx = int(similarities.argmax())
        max_sim = float(similarities[max_idx])
        most_similar_q = valid_questions[max_idx].question_text

        is_dup = max_sim >= self.threshold
        return round(max_sim, 3), most_similar_q, is_dup
