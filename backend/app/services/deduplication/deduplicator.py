import hashlib
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from sqlalchemy.orm import Session
from backend.app.models.question import Question
from backend.app.services.retrieval.vector_search import batch_cosine_similarities

logger = logging.getLogger(__name__)

class Deduplicator:
    """
    Two-Tier High-Scale Deduplication Engine:
    - Tier 1: O(1) Canonical Normalized SHA-256 Hash
    - Tier 2: Semantic Vector Cosine Similarity (>= threshold)
    """

    DEFAULT_SEMANTIC_THRESHOLD = 0.90

    @staticmethod
    def canonicalize_text(text: str) -> str:
        if not text:
            return ""
        # Lowercase
        t = text.lower().strip()
        # Remove punctuation
        t = re.sub(r"[^\w\s]", " ", t)
        # Collapse whitespace
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
        threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Deduplicates a batch of candidate questions against the database.
        Returns:
            (unique_candidates, duplicates_found)
        """
        if not candidates:
            return [], []

        # 1. Compute all candidate hashes
        for c in candidates:
            c["content_hash"] = self.compute_hash(c["question_text"], c["answer"])

        candidate_hashes = [c["content_hash"] for c in candidates]

        # 2. Tier 1: Single Batch Query for Exact Hashes
        existing_hash_map: Dict[str, Question] = {}
        matched_records = db.query(Question).filter(Question.content_hash.in_(candidate_hashes)).all()
        for rec in matched_records:
            existing_hash_map[rec.content_hash] = rec

        tier1_unique = []
        tier1_unique_embeddings = []
        duplicates = []

        for i, c in enumerate(candidates):
            chash = c["content_hash"]
            if chash in existing_hash_map:
                existing = existing_hash_map[chash]
                self._record_provenance(db, existing, doc_id, c.get("slide_id"))
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
            return [], duplicates

        # 3. Tier 2: Semantic Vector Cosine Check
        # Fetch existing vector embeddings from the DB
        existing_vec_records = db.query(Question.id, Question.embedding).filter(Question.embedding.isnot(None)).all()

        existing_ids = []
        existing_matrix = []
        for q_id, q_emb in existing_vec_records:
            if q_emb and len(q_emb) == 768:
                existing_ids.append(q_id)
                existing_matrix.append(q_emb)

        final_unique = []
        seen_in_batch_hashes = set()

        for idx, item in enumerate(tier1_unique):
            chash = item["content_hash"]
            # Intra-batch duplicate check
            if chash in seen_in_batch_hashes:
                duplicates.append({
                    "candidate_question": item["question_text"],
                    "duplicate_type": "INTRA_BATCH_EXACT",
                    "similarity": 1.0
                })
                continue

            item_emb = tier1_unique_embeddings[idx] if idx < len(tier1_unique_embeddings) else None

            is_semantic_dup = False
            if item_emb and existing_matrix:
                sims = batch_cosine_similarities(item_emb, existing_matrix)
                if len(sims) > 0:
                    best_idx = int(np.argmax(sims))
                    best_sim = float(sims[best_idx])
                    if best_sim >= threshold:
                        matched_id = existing_ids[best_idx]
                        existing_q = db.query(Question).filter(Question.id == matched_id).first()
                        if existing_q:
                            self._record_provenance(db, existing_q, doc_id, item.get("slide_id"))
                        duplicates.append({
                            "candidate_question": item["question_text"],
                            "matched_id": matched_id,
                            "duplicate_type": "SEMANTIC_SIMILARITY",
                            "similarity": round(best_sim, 3)
                        })
                        is_semantic_dup = True

            if not is_semantic_dup:
                seen_in_batch_hashes.add(chash)
                final_unique.append(item)

        return final_unique, duplicates

    def _record_provenance(self, db: Session, existing: Question, doc_id: str, slide_id: Optional[str]):
        """Records that this question also appeared in another deck."""
        try:
            provenance = list(existing.provenance_decks or [])
            entry = {"document_id": doc_id, "slide_id": slide_id}
            if not any(p.get("document_id") == doc_id for p in provenance):
                provenance.append(entry)
                existing.provenance_decks = provenance
            existing.occurrence_count = (existing.occurrence_count or 1) + 1
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to record duplicate provenance: {e}")
