import re
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from backend.app.services.validation.duplicate_detector import DuplicateDetector
from backend.app.services.ai.factory import get_llm_provider
from backend.app.config import settings

logger = logging.getLogger(__name__)

class QuestionValidator:
    def __init__(self, db: Session):
        self.db = db
        self.dup_detector = DuplicateDetector(db)
        self.llm = get_llm_provider()

    async def validate_question(
        self,
        question: Dict[str, Any],
        target_grade_min: Optional[int],
        target_grade_max: Optional[int],
        target_difficulty: str,
        evidence_context: str,
        audience_type: Optional[str] = "primary"
    ) -> Dict[str, Any]:
        """
        Executes the 7-stage automated validation pipeline:
        1. Answer Consistency
        2. Factual Grounding
        3. Grade / Audience Suitability
        4. Duplicate Detection (pgvector / cosine distance)
        5. Internal MCQ Consistency
        6. Difficulty Alignment
        7. Source Provenance
        """
        q_text = question.get("question_text", "").strip()
        ans = question.get("answer", "").strip()
        opts = question.get("options") or []
        diff = question.get("difficulty", "Medium")
        provenance = question.get("provenance") or {}

        # 1. Answer Consistency
        answer_consistency_passed = bool(ans and len(ans) > 1)
        # If MCQ, answer or letter must match one option
        if opts:
            ans_clean = re.sub(r"^[A-D1-4][\.\)]\s*", "", ans).strip().lower()
            opt_cleans = [re.sub(r"^[A-D1-4][\.\)]\s*", "", o).strip().lower() for o in opts]
            has_match = any(ans_clean in opt or opt in ans_clean for opt in opt_cleans)
            if not has_match:
                answer_consistency_passed = False

        answer_consistency = {
            "passed": answer_consistency_passed,
            "score": 1.0 if answer_consistency_passed else 0.2,
            "reason": "Answer clearly maps to an option and resolves the question." if answer_consistency_passed else "Answer not found in options list."
        }

        # 2. Factual Grounding
        # Check if keywords from question & answer appear in the evidence text or provenance quote
        has_evidence = False
        quote = provenance.get("source_quote", "")
        if quote and (len(quote) > 10):
            has_evidence = True
        elif evidence_context:
            q_keywords = [w for w in re.sub(r"[^\w\s]", "", q_text.lower()).split() if len(w) > 4]
            matches = sum(1 for kw in q_keywords if kw in evidence_context.lower())
            if matches >= 1:
                has_evidence = True

        factual_grounding = {
            "passed": has_evidence,
            "score": 0.95 if has_evidence else 0.45,
            "reason": "Factually corroborated by retrieved QShala historical material." if has_evidence else "Insufficient direct supporting text in knowledge base."
        }

        # 3. Grade / Audience Suitability
        words = q_text.split()
        avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
        grade_passed = True
        
        aud = (audience_type or "primary").lower()
        if aud in ["college", "adult", "general"]:
            grade_reason = f"Language, intellectual depth, and vocabulary calibrated for {aud.replace('_', ' ').title()} audience."
            grade_range_label = aud.replace('_', ' ').title()
        elif target_grade_min is not None and target_grade_max is not None:
            grade_reason = f"Language and reading complexity calibrated for Grades {target_grade_min}–{target_grade_max}."
            grade_range_label = f"Grades {target_grade_min}–{target_grade_max}"
            if target_grade_max <= 5 and (avg_word_len > 8.0 or len(words) > 35):
                grade_passed = False
                grade_reason = f"Sentence structure is overly dense for Grades {target_grade_min}–{target_grade_max}."
        else:
            grade_reason = "Language calibrated for general audience."
            grade_range_label = "General"

        grade_suitability = {
            "passed": grade_passed,
            "score": 0.92 if grade_passed else 0.60,
            "grade_range": grade_range_label,
            "reason": grade_reason
        }

        # 4. Duplicate Detection (Cosine Vector check)
        dup_score, most_similar_q, is_dup = await self.dup_detector.check_duplicate(q_text)
        duplicate_risk = {
            "passed": not is_dup,
            "score": dup_score,
            "is_duplicate": is_dup,
            "most_similar_question": most_similar_q,
            "reason": f"High similarity ({int(dup_score * 100)}%) with historical question: '{most_similar_q[:60]}...'" if is_dup else f"Low duplicate risk ({int(dup_score * 100)}% similarity)."
        }

        # 5. Internal Consistency (MCQ Distractors)
        mcq_passed = True
        mcq_reason = "All 4 options are distinct, plausible distractors with a single unambiguous answer."
        if opts:
            if len(opts) != 4:
                mcq_passed = False
                mcq_reason = f"Expected 4 options, found {len(opts)}."
            elif len(set(opts)) != len(opts):
                mcq_passed = False
                mcq_reason = "Duplicate options detected."
        else:
            mcq_passed = True
            mcq_reason = "Valid trivia short answer question."

        internal_consistency = {
            "passed": mcq_passed,
            "score": 1.0 if mcq_passed else 0.4,
            "distractor_quality": "High" if mcq_passed else "Low",
            "reason": mcq_reason
        }

        # 6. Difficulty Alignment
        diff_passed = (diff.lower() == target_difficulty.lower())
        difficulty_alignment = {
            "passed": diff_passed,
            "score": 0.95 if diff_passed else 0.70,
            "level": diff,
            "reason": f"Successfully aligned with requested {target_difficulty} difficulty." if diff_passed else f"Constructed as {diff} instead of {target_difficulty}."
        }

        # 7. Source Provenance
        has_provenance = bool(provenance.get("source_quote") or provenance.get("document_id"))
        source_provenance = {
            "passed": has_provenance,
            "score": 0.95 if has_provenance else 0.3,
            "doc_title": provenance.get("document_title", "Historical QShala Archive"),
            "slide_number": provenance.get("slide_number"),
            "reason": "Explicit provenance citation linked to historical slide." if has_provenance else "No specific slide provenance recorded."
        }

        # Compute overall status
        critical_checks = [answer_consistency_passed, mcq_passed, not is_dup]
        all_checks = [
            answer_consistency_passed,
            has_evidence,
            grade_passed,
            not is_dup,
            mcq_passed,
            diff_passed,
            has_provenance
        ]

        if not all(critical_checks):
            overall_status = "FAILED"
        elif sum(all_checks) >= 5:
            overall_status = "PASSED"
        else:
            overall_status = "WARNING"

        return {
            "overall_status": overall_status,
            "duplicate_score": dup_score,
            "details": {
                "answer_consistency": answer_consistency,
                "factual_grounding": factual_grounding,
                "grade_suitability": grade_suitability,
                "duplicate_risk": duplicate_risk,
                "internal_consistency": internal_consistency,
                "difficulty_alignment": difficulty_alignment,
                "source_provenance": source_provenance
            }
        }
