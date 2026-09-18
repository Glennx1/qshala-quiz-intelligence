import re
import logging
from typing import List, Dict, Any, Optional
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from backend.app.models.question import Question
from backend.app.models.document import Document, Slide
from backend.app.services.ai.factory import get_embedding_provider
from backend.app.services.retrieval.vector_search import batch_cosine_similarities

logger = logging.getLogger(__name__)

# Domain synonym maps for intelligent query expansion
EXPANSIONS = {
    "indigenous": ["aboriginal", "first peoples", "early inhabitants", "dreamtime", "jukurrpa", "native"],
    "australian history": ["first fleet", "captain cook", "edmund barton", "canberra", "federation", "eureka", "ned kelly", "convicts"],
    "capital": ["canberra", "sydney", "melbourne", "city", "parliament"],
    "space": ["solar system", "planet", "astronomy", "moon", "galaxy", "orbit", "nasa"],
    "nature": ["wildlife", "animal", "flora", "fauna", "ecosystem", "species"]
}

class HybridRetriever:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_provider = get_embedding_provider()

    def _expand_query(self, query: str) -> List[str]:
        tokens = re.sub(r"[^\w\s]", " ", query.lower()).split()
        expanded_terms = set(tokens)
        for term, synonyms in EXPANSIONS.items():
            if term in query.lower():
                expanded_terms.update(synonyms)
            for tok in tokens:
                if tok in term:
                    expanded_terms.update(synonyms)
        return list(expanded_terms)

    async def search(
        self,
        query: str,
        topic: Optional[str] = None,
        grade_min: Optional[int] = None,
        grade_max: Optional[int] = None,
        difficulty: Optional[str] = None,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid dense + sparse retrieval with Reciprocal Rank Fusion (RRF).
        """
        # Step 1: Query Embedding for dense vector search
        query_emb = await self.embedding_provider.get_embedding(query)

        # Step 2: Fetch candidate pool with metadata filters
        query_builder = self.db.query(Question, Document, Slide).\
            join(Document, Question.document_id == Document.id).\
            outerjoin(Slide, Question.slide_id == Slide.id)

        # Metadata constraints (soft or hard)
        if topic:
            query_builder = query_builder.filter(
                or_(
                    Question.topic.ilike(f"%{topic}%"),
                    Question.subtopic.ilike(f"%{topic}%"),
                    Question.question_text.ilike(f"%{topic}%")
                )
            )

        if grade_min is not None and grade_max is not None:
            # Overlap in grade range
            query_builder = query_builder.filter(
                and_(
                    Question.grade_min <= (grade_max + 1),
                    Question.grade_max >= (grade_min - 1)
                )
            )

        candidates = query_builder.all()

        # If strict filter returned too few items, relax topic filter
        if len(candidates) < 5:
            candidates = self.db.query(Question, Document, Slide).\
                join(Document, Question.document_id == Document.id).\
                outerjoin(Slide, Question.slide_id == Slide.id).\
                all()

        if not candidates:
            return []

        expanded_keywords = self._expand_query(f"{query} {topic or ''}")

        # Path A: Vector similarities (Dense)
        candidate_embs = []
        for q, doc, slide in candidates:
            emb = q.embedding
            if isinstance(emb, list) and len(emb) == len(query_emb):
                candidate_embs.append(emb)
            else:
                candidate_embs.append([0.0] * len(query_emb))

        dense_scores = batch_cosine_similarities(query_emb, candidate_embs)
        # Rank indices descending
        dense_ranked_indices = list(np.argsort(-dense_scores))
        dense_rank_map = {idx: rank + 1 for rank, idx in enumerate(dense_ranked_indices)}

        # Path B: Lexical & Keyword Matching (Sparse)
        sparse_scores = []
        for i, (q, doc, slide) in enumerate(candidates):
            content_text = f"{q.question_text} {q.answer} {q.topic} {q.subtopic or ''} {slide.extracted_text if slide else ''}".lower()
            score = 0.0
            for kw in expanded_keywords:
                if kw in content_text:
                    score += 1.0
            if difficulty and q.difficulty.lower() == difficulty.lower():
                score += 0.5
            sparse_scores.append(score)

        sparse_ranked_indices = list(np.argsort(-np.array(sparse_scores)))
        sparse_rank_map = {idx: rank + 1 for rank, idx in enumerate(sparse_ranked_indices)}

        # Step 3: Reciprocal Rank Fusion (RRF)
        # RRF_Score = 1 / (60 + r_dense) + 1 / (60 + r_sparse)
        rrf_scores = []
        k_rrf = 60.0
        for idx in range(len(candidates)):
            r_dense = dense_rank_map[idx]
            r_sparse = sparse_rank_map[idx]
            score = (1.0 / (k_rrf + r_dense)) + (1.0 / (k_rrf + r_sparse))
            rrf_scores.append((score, idx))

        # Sort by RRF score descending
        rrf_scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, idx in rrf_scores[:limit]:
            q, doc, slide = candidates[idx]
            results.append({
                "question": q,
                "document": doc,
                "slide": slide,
                "relevance_score": round(score * 100, 3),
                "dense_similarity": round(float(dense_scores[idx]), 3),
                "quote": slide.extracted_text if slide else q.question_text
            })

        return results
