import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, not_
from backend.app.models.question import Question
from backend.app.models.document import Document, Slide
from backend.app.services.ai.factory import get_embedding_provider
from backend.app.services.retrieval.vector_search import batch_cosine_similarities

logger = logging.getLogger(__name__)

TAXONOMY_FILE = Path(__file__).resolve().parent.parent / "tagging" / "taxonomy.json"

class HybridRetriever:
    """
    State-of-the-art hybrid retriever for the QShala Knowledge Vault.
    Combines:
    - Direct pedagogical metadata filtering (for exact topic/difficulty compilations)
    - Dense vector cosine semantic search
    - Sparse token lexical matching with dynamic taxonomy query expansions
    - Reciprocal Rank Fusion (RRF)
    """

    def __init__(self, db: Session):
        self.db = db
        self.embedding_provider = get_embedding_provider()
        self.expansions = self._load_synonym_expansions()

    def _load_synonym_expansions(self) -> Dict[str, List[str]]:
        expansions = {
            "indigenous": ["aboriginal", "first peoples", "early inhabitants", "dreamtime", "jukurrpa", "native"],
            "australian history": ["first fleet", "captain cook", "edmund barton", "canberra", "federation", "eureka", "ned kelly", "convicts"],
            "capital": ["canberra", "sydney", "melbourne", "city", "parliament"],
            "space": ["solar system", "planet", "astronomy", "moon", "galaxy", "orbit", "nasa"],
            "nature": ["wildlife", "animal", "flora", "fauna", "ecosystem", "species"]
        }
        if TAXONOMY_FILE.exists():
            try:
                with open(TAXONOMY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for cat, keywords in data.get("categories", {}).items():
                        expansions[cat.lower()] = keywords[:10]
            except Exception:
                pass
        return expansions

    def _expand_query(self, query: str) -> List[str]:
        tokens = re.sub(r"[^\w\s]", " ", query.lower()).split()
        expanded_terms = set(tokens)
        q_lower = query.lower()
        for term, synonyms in self.expansions.items():
            if term in q_lower:
                expanded_terms.update(synonyms)
            for tok in tokens:
                if tok in term:
                    expanded_terms.update(synonyms)
        return list(expanded_terms)

    def fetch_by_filters(
        self,
        topic: Optional[str] = None,
        difficulty: Optional[str] = None,
        grade_min: Optional[int] = None,
        grade_max: Optional[int] = None,
        subtopic: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_ids: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Direct SQL retrieval by pedagogical filters and tags for compiling quizzes straight from the vault.
        Prioritizes tag matches and exact topic alignments without vector fuzzy drift.
        """
        query_builder = self.db.query(Question, Document, Slide).\
            join(Document, Question.document_id == Document.id).\
            outerjoin(Slide, Question.slide_id == Slide.id)

        # Topic filter (if provided)
        if topic:
            query_builder = query_builder.filter(
                or_(
                    Question.topic.ilike(f"%{topic}%"),
                    Question.subtopic.ilike(f"%{topic}%")
                )
            )

        if subtopic:
            query_builder = query_builder.filter(Question.subtopic.ilike(f"%{subtopic}%"))

        if difficulty:
            query_builder = query_builder.filter(Question.difficulty.ilike(difficulty))

        if grade_min is not None and grade_max is not None:
            query_builder = query_builder.filter(
                and_(
                    Question.grade_min <= (grade_max + 1),
                    Question.grade_max >= (grade_min - 1)
                )
            )

        if exclude_ids:
            query_builder = query_builder.filter(not_(Question.id.in_(exclude_ids)))

        candidates = query_builder.all()
        if not candidates:
            return []

        clean_tags = [t.strip().lstrip("#").lower() for t in (tags or []) if isinstance(t, str) and t.strip()]

        # Score candidates with tag-overlap priority
        scored_candidates = []
        for q, doc, slide in candidates:
            q_tags_lower = [t.strip().lstrip("#").lower() for t in (q.tags or []) if isinstance(t, str)]
            tag_overlap = sum(1 for t in clean_tags if t in q_tags_lower)
            relevance = 100.0 + (tag_overlap * 50.0)
            scored_candidates.append((relevance, tag_overlap, q, doc, slide))

        # Sort by tag_overlap descending, then relevance
        scored_candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)

        results = []
        for relevance, tag_overlap, q, doc, slide in scored_candidates[:limit]:
            results.append({
                "question": q,
                "document": doc,
                "slide": slide,
                "relevance_score": relevance,
                "tag_overlap": tag_overlap,
                "dense_similarity": 1.0,
                "quote": slide.extracted_text if slide else q.question_text
            })

        return results

    async def search(
        self,
        query: str,
        topic: Optional[str] = None,
        tags: Optional[List[str]] = None,
        grade_min: Optional[int] = None,
        grade_max: Optional[int] = None,
        difficulty: Optional[str] = None,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid dense + sparse retrieval with Reciprocal Rank Fusion (RRF) and Tag-Overlap Boost.
        """
        # Step 1: Dense Query Embedding
        query_emb = await self.embedding_provider.get_embedding(query)

        # Step 2: Build candidate pool
        query_builder = self.db.query(Question, Document, Slide).\
            join(Document, Question.document_id == Document.id).\
            outerjoin(Slide, Question.slide_id == Slide.id)

        clean_tags = [t.strip().lstrip("#").lower() for t in (tags or []) if isinstance(t, str) and t.strip()]

        # If both topic and tags are provided, match questions matching topic OR any tag
        if topic and clean_tags:
            query_builder = query_builder.filter(
                or_(
                    Question.topic.ilike(f"%{topic}%"),
                    Question.subtopic.ilike(f"%{topic}%"),
                    Question.question_text.ilike(f"%{topic}%")
                )
            )
        elif topic:
            query_builder = query_builder.filter(
                or_(
                    Question.topic.ilike(f"%{topic}%"),
                    Question.subtopic.ilike(f"%{topic}%"),
                    Question.question_text.ilike(f"%{topic}%")
                )
            )

        if grade_min is not None and grade_max is not None:
            query_builder = query_builder.filter(
                and_(
                    Question.grade_min <= (grade_max + 1),
                    Question.grade_max >= (grade_min - 1)
                )
            )

        candidates = query_builder.all()

        # If strict search returned nothing, relax
        if not candidates:
            candidates = self.db.query(Question, Document, Slide).\
                join(Document, Question.document_id == Document.id).\
                outerjoin(Slide, Question.slide_id == Slide.id).\
                limit(60).all()

        if not candidates:
            return []

        tag_query_str = " ".join(clean_tags)
        expanded_keywords = self._expand_query(f"{query} {topic or ''} {tag_query_str}")

        # Path A: Dense Vector similarities
        candidate_embs = []
        for q, doc, slide in candidates:
            emb = q.embedding
            if isinstance(emb, list) and len(emb) == len(query_emb):
                candidate_embs.append(emb)
            else:
                candidate_embs.append([0.0] * len(query_emb))

        dense_scores = batch_cosine_similarities(query_emb, candidate_embs)
        dense_ranked_indices = list(np.argsort(-dense_scores))
        dense_rank_map = {idx: rank + 1 for rank, idx in enumerate(dense_ranked_indices)}

        # Path B: Sparse Lexical & Keyword Matching + Tag Overlap
        sparse_scores = []
        tag_overlaps = []
        for i, (q, doc, slide) in enumerate(candidates):
            content_text = f"{q.question_text} {q.answer} {q.topic} {q.subtopic or ''} {slide.extracted_text if slide else ''}".lower()
            q_tags_lower = [t.strip().lstrip("#").lower() for t in (q.tags or []) if isinstance(t, str)]
            tag_overlap = sum(1 for t in clean_tags if t in q_tags_lower)
            tag_overlaps.append(tag_overlap)

            score = 0.0
            for kw in expanded_keywords:
                if kw in content_text:
                    score += 1.0
            if difficulty and q.difficulty and q.difficulty.lower() == (difficulty or "").lower():
                score += 0.5
            # Heavy bonus for tag match
            score += tag_overlap * 5.0
            sparse_scores.append(score)

        sparse_ranked_indices = list(np.argsort(-np.array(sparse_scores)))
        sparse_rank_map = {idx: rank + 1 for rank, idx in enumerate(sparse_ranked_indices)}

        # Step 3: Reciprocal Rank Fusion (RRF) with Tag Multiplier
        rrf_scores = []
        k_rrf = 60.0
        for idx in range(len(candidates)):
            r_dense = dense_rank_map[idx]
            r_sparse = sparse_rank_map[idx]
            overlap_boost = 1.0 + (0.5 * tag_overlaps[idx])
            score = ((1.0 / (k_rrf + r_dense)) + (1.0 / (k_rrf + r_sparse))) * overlap_boost
            rrf_scores.append((score, idx))

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
                "tag_overlap": tag_overlaps[idx],
                "quote": slide.extracted_text if slide else q.question_text
            })

        return results

