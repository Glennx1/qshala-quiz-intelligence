import hashlib
import re
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
import numpy as np
from sqlalchemy.orm import Session
from backend.app.models.question import Question
from backend.app.services.retrieval.vector_search import batch_cosine_similarities
from backend.app.config import settings

logger = logging.getLogger(__name__)

class Deduplicator:
    """
    Two-Tier High-Scale Deduplication Engine:
    - Tier 1: O(1) Canonical Normalized SHA-256 Hash
    - Tier 2: Semantic Vector Cosine Similarity (against DB and intra-batch)
    - Batched provenance tracking across presentations
    """

    DEFAULT_SEMANTIC_THRESHOLD = getattr(settings, "DUPLICATE_SIMILARITY_THRESHOLD", 0.88)

    @staticmethod
    def canonicalize_text(text: str) -> str:
        if not text:
            return ""
        t = text.lower().strip()
        t = re.sub(r"[^\w\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @classmethod
    def compute_hash(cls, question_text: str, answer_text: str) -> str:
        q_norm = cls.canonicalize_text(question_text)
        a_norm = cls.canonicalize_text(answer_text)
        payload = f"{q_norm}|||{a_norm}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def deduplicate_batch(
        self,
        db: Session,
        candidates: List[Dict[str, Any]],
        candidate_embeddings: List[List[float]],
        doc_id: str,
        threshold: Optional[float] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Deduplicates candidate questions against both existing DB records and intra-batch items.
        """
        if not candidates:
            return [], []

        thresh = threshold or self.DEFAULT_SEMANTIC_THRESHOLD

        # 1. Compute canonical hashes
        for c in candidates:
            c["content_hash"] = self.compute_hash(c["question_text"], c["answer"])

        candidate_hashes = [c["content_hash"] for c in candidates]

        # 2. Tier 1: Exact Hash Batch Lookup
        existing_hash_map: Dict[str, Question] = {}
        matched_records = db.query(Question).filter(Question.content_hash.in_(candidate_hashes)).all()
        for rec in matched_records:
            existing_hash_map[rec.content_hash] = rec

        tier1_unique: List[Dict[str, Any]] = []
        tier1_unique_embeddings: List[List[float]] = []
        duplicates: List[Dict[str, Any]] = []
        provenance_updates: List[Tuple[Question, Optional[str]]] = []

        for i, c in enumerate(candidates):
            chash = c["content_hash"]
            if chash in existing_hash_map:
                existing = existing_hash_map[chash]
                provenance_updates.append((existing, c.get("slide_id")))
                duplicates.append({
                    "candidate_question": c["question_text"],
                    "matched_id": existing.id,
                    "duplicate_type": "EXACT_HASH",
                    "similarity": 1.0
                })
            else:
                tier1_unique.append(c)
                if i < len(candidate_embeddings):
                    tier1_unique_embeddings.append(candidate_embeddings[i])
                else:
                    tier1_unique_embeddings.append([])

        if not tier1_unique:
            self._batch_commit_provenance(db, provenance_updates, doc_id)
            return [], duplicates

        # 3. Tier 2: Vector Semantic Deduplication
        # Topic-scoped candidate loading to keep comparison fast and scalable
        batch_topics = set()
        for c in tier1_unique:
            pt = c.get("primary_topic")
            if pt:
                batch_topics.add(pt)

        query = db.query(Question.id, Question.embedding).filter(Question.embedding.isnot(None))
        if batch_topics and len(batch_topics) <= 4:
            query = query.filter(Question.topic.in_(list(batch_topics)))

        existing_vec_records = query.all()
        # Fallback to general pool if topic pool is empty
        if not existing_vec_records:
            existing_vec_records = db.query(Question.id, Question.embedding).filter(Question.embedding.isnot(None)).limit(1000).all()

        existing_ids = [q_id for q_id, q_emb in existing_vec_records if q_emb and len(q_emb) > 0]
        existing_matrix = [q_emb for q_id, q_emb in existing_vec_records if q_emb and len(q_emb) > 0]

        final_unique: List[Dict[str, Any]] = []
        final_unique_embeddings: List[List[float]] = []
        seen_in_batch_hashes: Set[str] = set()

        for idx, item in enumerate(tier1_unique):
            chash = item["content_hash"]
            # Intra-batch exact check
            if chash in seen_in_batch_hashes:
                duplicates.append({
                    "candidate_question": item["question_text"],
                    "duplicate_type": "INTRA_BATCH_EXACT",
                    "similarity": 1.0
                })
                continue

            item_emb = tier1_unique_embeddings[idx] if idx < len(tier1_unique_embeddings) else None
            is_semantic_dup = False

            # Check against existing DB embeddings
            if item_emb and existing_matrix:
                sims = batch_cosine_similarities(item_emb, existing_matrix)
                if len(sims) > 0:
                    best_idx = int(np.argmax(sims))
                    best_sim = float(sims[best_idx])
                    if best_sim >= thresh:
                        matched_id = existing_ids[best_idx]
                        existing_q = db.query(Question).filter(Question.id == matched_id).first()
                        if existing_q:
                            provenance_updates.append((existing_q, item.get("slide_id")))
                        duplicates.append({
                            "candidate_question": item["question_text"],
                            "matched_id": matched_id,
                            "duplicate_type": "SEMANTIC_SIMILARITY",
                            "similarity": round(best_sim, 3)
                        })
                        is_semantic_dup = True

            # Intra-batch semantic check against already accepted unique items
            if not is_semantic_dup and item_emb and final_unique_embeddings:
                intra_sims = batch_cosine_similarities(item_emb, final_unique_embeddings)
                if len(intra_sims) > 0:
                    best_intra_idx = int(np.argmax(intra_sims))
                    best_intra_sim = float(intra_sims[best_intra_idx])
                    if best_intra_sim >= thresh:
                        duplicates.append({
                            "candidate_question": item["question_text"],
                            "matched_id": final_unique[best_intra_idx].get("content_hash"),
                            "duplicate_type": "INTRA_BATCH_SEMANTIC",
                            "similarity": round(best_intra_sim, 3)
                        })
                        is_semantic_dup = True

            if not is_semantic_dup:
                seen_in_batch_hashes.add(chash)
                final_unique.append(item)
                if item_emb:
                    final_unique_embeddings.append(item_emb)

        # Batch commit all provenance records
        self._batch_commit_provenance(db, provenance_updates, doc_id)

        return final_unique, duplicates

    def _batch_commit_provenance(
        self,
        db: Session,
        updates: List[Tuple[Question, Optional[str]]],
        doc_id: str
    ):
        """Batch records duplicate occurrences and provenance links."""
        if not updates:
            return
        try:
            for existing, slide_id in updates:
                provenance = list(existing.provenance_decks or [])
                if not any(p.get("document_id") == doc_id for p in provenance):
                    provenance.append({"document_id": doc_id, "slide_id": slide_id})
                    existing.provenance_decks = provenance
                existing.occurrence_count = (existing.occurrence_count or 1) + 1
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to batch record duplicate provenance: {e}")
            db.rollback()
