import logging
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from backend.app.models.question import Question
from backend.app.services.ai.factory import get_embedding_provider
from backend.app.services.retrieval.vector_search import batch_cosine_similarities
from backend.app.config import settings
from backend.app.database import is_postgres, PG_VECTOR_AVAILABLE

logger = logging.getLogger(__name__)

_ANN_POOL = 50

class DuplicateDetector:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_provider = get_embedding_provider()
        self.threshold = settings.DUPLICATE_SIMILARITY_THRESHOLD

    async def check_duplicate(self, question_text: str) -> Tuple[float, Optional[str], bool]:
        """
        Calculates cosine similarity of question_text against historical questions.
        Uses pgvector ANN index when available, falling back to in-memory scan with a limit.
        Returns: (highest_similarity_score, most_similar_question_text, is_duplicate)
        """
        try:
            q_emb = await self.embedding_provider.get_embedding(question_text)
        except Exception:
            return 0.0, None, False

        if is_postgres and PG_VECTOR_AVAILABLE:
            distance_col = Question.embedding.cosine_distance(q_emb)
            row = (self.db.query(Question.question_text, distance_col.label("dist"))
                   .filter(Question.embedding.isnot(None))
                   .order_by(distance_col)
                   .limit(1)
                   .first())
            if row is None:
                return 0.0, None, False
            sim = round(1.0 - float(row.dist), 3)
            return sim, row.question_text, sim >= self.threshold

        candidates = (self.db.query(Question)
                      .filter(Question.embedding.isnot(None))
                      .limit(5000)
                      .all())
        if not candidates:
            return 0.0, None, False

        candidate_embs = []
        valid_questions = []
        for q in candidates:
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
