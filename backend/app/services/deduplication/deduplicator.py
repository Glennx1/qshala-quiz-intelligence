import uuid
import hashlib
import re
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
import numpy as np
from sqlalchemy.orm import Session
from backend.app.models.question import Question
from backend.app.services.retrieval.vector_search import batch_cosine_similarities
from backend.app.config import settings
from backend.app.database import is_postgres, PG_VECTOR_AVAILABLE

logger = logging.getLogger(__name__)

class Deduplicator:
    """
    Two-Tier High-Scale Deduplication Engine:
    - Tier 1: O(1) Canonical Normalized SHA-256 Hash Pre-Filter
    - Tier 2: Semantic Vector Cosine Similarity Nearest-Neighbor Lookup (0.92 Threshold)
    
    Candidates >= 0.92 similarity are flagged as 'POSSIBLE_DUPLICATE' for human review
    in the Questions UI (NOT auto-rejected or discarded).
    """

    DEFAULT_SEMANTIC_THRESHOLD = getattr(settings, "DUPLICATE_SIMILARITY_THRESHOLD", 0.92)

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
        Deduplicates candidate questions:
        - Tier 1: Exact hash match updates provenance on existing record and skips vector search.
        - Tier 2: Vector nearest-neighbor check. Candidates >= threshold (0.92) are flagged as
          'POSSIBLE_DUPLICATE' with matched ID and similarity score, but KEPT for insertion
          and human UI review.
        """
        if not candidates:
            return [], []

        thresh = threshold if threshold is not None else self.DEFAULT_SEMANTIC_THRESHOLD

        # 1. Compute canonical hashes
        for c in candidates:
            c["content_hash"] = self.compute_hash(c["question_text"], c["answer"])

        candidate_hashes = [c["content_hash"] for c in candidates]

        # 2. Tier 1: Exact Hash Pre-filter
        existing_hash_map: Dict[str, Question] = {}
        matched_records = db.query(Question).filter(Question.content_hash.in_(candidate_hashes)).all()
        for rec in matched_records:
            existing_hash_map[rec.content_hash] = rec

        tier1_passed: List[Dict[str, Any]] = []
        tier1_passed_embeddings: List[List[float]] = []
        exact_duplicates: List[Dict[str, Any]] = []
        provenance_updates: List[Tuple[Question, Optional[str]]] = []
        seen_in_batch_hashes: Set[str] = set()

        for i, c in enumerate(candidates):
            chash = c["content_hash"]
            if chash in existing_hash_map:
                existing = existing_hash_map[chash]
                provenance_updates.append((existing, c.get("slide_id")))
                exact_duplicates.append({
                    "candidate_question": c["question_text"],
                    "matched_id": existing.id,
                    "duplicate_type": "EXACT_HASH",
                    "similarity": 1.0
                })
            elif chash in seen_in_batch_hashes:
                exact_duplicates.append({
                    "candidate_question": c["question_text"],
                    "duplicate_type": "INTRA_BATCH_EXACT",
                    "similarity": 1.0
                })
            else:
                seen_in_batch_hashes.add(chash)
                tier1_passed.append(c)
                if i < len(candidate_embeddings):
                    tier1_passed_embeddings.append(candidate_embeddings[i])
                else:
                    tier1_passed_embeddings.append([])

        if not tier1_passed:
            self._batch_commit_provenance(db, provenance_updates, doc_id)
            return [], exact_duplicates

        # 3. Tier 2: Nearest-Neighbor Semantic Vector Similarity
        batch_topics = set()
        for c in tier1_passed:
            c["id"] = c.get("id") or str(uuid.uuid4())
            pt = c.get("primary_topic") or c.get("topic")
            if pt:
                batch_topics.add(pt)

        existing_ids = []
        existing_matrix = []

        # Only load in-memory matrix if not running on native pgvector
        if not (is_postgres and PG_VECTOR_AVAILABLE):
            query = db.query(Question.id, Question.embedding).filter(Question.embedding.isnot(None))
            if batch_topics and len(batch_topics) <= 4:
                query = query.filter(Question.topic.in_(list(batch_topics)))

            existing_vec_records = query.all()
            if not existing_vec_records:
                existing_vec_records = db.query(Question.id, Question.embedding).filter(Question.embedding.isnot(None)).limit(1000).all()

            existing_ids = [q_id for q_id, q_emb in existing_vec_records if q_emb and len(q_emb) > 0]
            existing_matrix = [q_emb for q_id, q_emb in existing_vec_records if q_emb and len(q_emb) > 0]

        final_candidates: List[Dict[str, Any]] = []
        final_candidates_embeddings: List[List[float]] = []

        for idx, item in enumerate(tier1_passed):
            item_emb = tier1_passed_embeddings[idx] if idx < len(tier1_passed_embeddings) else None
            best_sim = 0.0
            best_matched_id: Optional[str] = None
            is_possible_dup = False

            # Check against existing DB embeddings
            if item_emb:
                if is_postgres and PG_VECTOR_AVAILABLE:
                    try:
                        q_query = db.query(
                            Question.id,
                            Question.embedding.cosine_distance(item_emb).label("distance")
                        ).filter(Question.embedding.isnot(None))
                        if batch_topics and len(batch_topics) <= 4:
                            q_query = q_query.filter(Question.topic.in_(list(batch_topics)))
                        nn_rec = q_query.order_by("distance").first()
                        if nn_rec and nn_rec.distance is not None:
                            pg_sim = float(1.0 - nn_rec.distance)
                            if pg_sim >= thresh and pg_sim > best_sim:
                                best_sim = pg_sim
                                best_matched_id = nn_rec.id
                                is_possible_dup = True
                    except Exception as e:
                        logger.warning(f"pgvector query error ({e}), falling back")

                if not is_possible_dup and existing_matrix:
                    sims = batch_cosine_similarities(item_emb, existing_matrix)
                    if len(sims) > 0:
                        best_idx = int(np.argmax(sims))
                        sim = float(sims[best_idx])
                        if sim >= thresh and sim > best_sim:
                            best_sim = sim
                            best_matched_id = existing_ids[best_idx]
                            is_possible_dup = True

            # Intra-batch comparison against previously accepted items in this batch
            if not is_possible_dup and item_emb and final_candidates_embeddings:
                intra_sims = batch_cosine_similarities(item_emb, final_candidates_embeddings)
                if len(intra_sims) > 0:
                    best_intra_idx = int(np.argmax(intra_sims))
                    best_intra_sim = float(intra_sims[best_intra_idx])
                    if best_intra_sim >= thresh:
                        best_sim = best_intra_sim
                        matched_cand = final_candidates[best_intra_idx]
                        if not matched_cand.get("id"):
                            matched_cand["id"] = str(uuid.uuid4())
                        best_matched_id = matched_cand["id"]
                        is_possible_dup = True

            if is_possible_dup:
                item["duplicate_status"] = "POSSIBLE_DUPLICATE"
                item["duplicate_similarity"] = round(best_sim, 4)
                item["duplicate_of_id"] = best_matched_id
            else:
                item["duplicate_status"] = "UNIQUE"
                item["duplicate_similarity"] = round(best_sim, 4) if best_sim > 0 else None
                item["duplicate_of_id"] = None

            final_candidates.append(item)
            if item_emb:
                final_candidates_embeddings.append(item_emb)

        # Commit provenance for exact hash matches
        self._batch_commit_provenance(db, provenance_updates, doc_id)

        return final_candidates, exact_duplicates

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
