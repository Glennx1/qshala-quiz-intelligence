import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from backend.app.models.quiz import Quiz, GeneratedQuestion, RetrievalSource
from backend.app.models.question import Question
from backend.app.services.ai.factory import get_llm_provider
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever
from backend.app.services.retrieval.context_builder import ContextBuilder
from backend.app.services.validation.validator import QuestionValidator
from backend.app.schemas.quiz import QuizGenerateRequest

logger = logging.getLogger(__name__)

class QuizGenerator:
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_llm_provider()
        self.retriever = HybridRetriever(db)
        self.validator = QuestionValidator(db)

    async def generate_quiz(self, req: QuizGenerateRequest) -> Quiz:
        # Step 1: Hybrid Retrieval of historical context
        retrieved_items = await self.retriever.search(
            query=f"{req.topic} {req.subtopic or ''} {req.raw_prompt or ''}",
            topic=req.topic,
            grade_min=req.grade_min,
            grade_max=req.grade_max,
            difficulty=req.difficulty,
            limit=max(req.question_count * 2, 10)
        )

        # Check for insufficient evidence
        if not retrieved_items and req.generation_mode != "HISTORICAL":
            # If no items retrieved at all, check if database is empty
            total_q_count = self.db.query(Question).count()
            if total_q_count == 0:
                raise ValueError("Insufficient supporting material in the QShala knowledge base. Please upload historical quiz slides first.")

        # Step 2: Context Building & Exemplars
        context_data = ContextBuilder.build_prompt_context(retrieved_items)
        evidence_context = context_data["evidence_context"]
        source_mapping = context_data["source_mapping"]
        style_examples = context_data["style_examples"]

        # Step 3: Audience & Difficulty Distribution Resolution
        audience_map = {
            "primary": "Primary School",
            "middle_school": "Middle School",
            "high_school": "High School",
            "college": "College / University",
            "adult": "Adults",
            "general": "General Audience"
        }
        aud_type = (req.audience_type or "primary").lower()
        audience_label = audience_map.get(aud_type, aud_type.replace("_", " ").title())

        # Resolve grade range
        if aud_type in ["college", "adult", "general"]:
            grade_min = None
            grade_max = None
            grades_list = []
        elif req.grades and len(req.grades) > 0:
            grade_min = min(req.grades)
            grade_max = max(req.grades)
            grades_list = sorted(req.grades)
        else:
            grade_min = req.grade_min or 3
            grade_max = req.grade_max or 5
            grades_list = list(range(grade_min, grade_max + 1))

        # Title construction
        if aud_type == "college":
            quiz_title = f"{req.topic} Quiz (College / University)"
        elif aud_type == "adult":
            quiz_title = f"{req.topic} Quiz (Adults)"
        elif grade_min is not None and grade_max is not None:
            quiz_title = f"{req.topic} Quiz (Grades {grade_min}–{grade_max})"
        else:
            quiz_title = f"{req.topic} Quiz ({audience_label})"

        # Resolve difficulty distribution
        dist = req.difficulty_distribution or {}
        easy_count = dist.get("easy", 0)
        medium_count = dist.get("medium", 0)
        hard_count = dist.get("hard", 0)

        if (easy_count + medium_count + hard_count) != req.question_count:
            diff_lower = (req.difficulty or "balanced").lower()
            if "easy-heavy" in diff_lower:
                easy_count = max(1, round(req.question_count * 0.6))
                medium_count = max(1, round(req.question_count * 0.3))
                hard_count = req.question_count - easy_count - medium_count
            elif "hard-heavy" in diff_lower:
                hard_count = max(1, round(req.question_count * 0.6))
                medium_count = max(1, round(req.question_count * 0.3))
                easy_count = req.question_count - hard_count - medium_count
            elif diff_lower == "easy":
                easy_count, medium_count, hard_count = req.question_count, 0, 0
            elif diff_lower == "hard":
                easy_count, medium_count, hard_count = 0, 0, req.question_count
            else:  # Balanced
                if req.question_count == 10:
                    easy_count, medium_count, hard_count = 3, 5, 2
                elif req.question_count == 20:
                    easy_count, medium_count, hard_count = 5, 10, 5
                else:
                    easy_count = max(1, round(req.question_count * 0.25))
                    hard_count = max(1, round(req.question_count * 0.25))
                    medium_count = req.question_count - easy_count - hard_count
            dist = {"easy": easy_count, "medium": medium_count, "hard": hard_count}

        target_difficulties = (["Easy"] * easy_count) + (["Medium"] * medium_count) + (["Hard"] * hard_count)

        quiz_obj = Quiz(
            title=quiz_title,
            topic=req.topic,
            subtopic=req.subtopic,
            audience_type=aud_type,
            grades=grades_list,
            age_range=req.age_range,
            grade_min=grade_min,
            grade_max=grade_max,
            difficulty=req.difficulty or "Balanced",
            difficulty_distribution=dist,
            question_count=req.question_count,
            question_types=req.question_types,
            generation_mode=req.generation_mode,
            style=req.style,
            raw_prompt=req.raw_prompt,
            status="READY"
        )
        self.db.add(quiz_obj)
        self.db.flush()

        generated_raw_questions = []

        if req.generation_mode == "HISTORICAL":
            # Direct curation mode
            for i, item in enumerate(retrieved_items[:req.question_count], start=1):
                hist_q = item["question"]
                assigned_diff = target_difficulties[i - 1] if (i - 1) < len(target_difficulties) else hist_q.difficulty
                generated_raw_questions.append({
                    "question_text": hist_q.question_text,
                    "options": hist_q.options,
                    "answer": hist_q.answer,
                    "explanation": hist_q.explanation or "Historical QShala competition question.",
                    "difficulty": assigned_diff,
                    "grade_min": grade_min,
                    "grade_max": grade_max,
                    "topic": hist_q.topic,
                    "question_type": hist_q.question_type,
                    "provenance": {
                        "historical_question_id": hist_q.id,
                        "document_id": item["document"].id,
                        "slide_id": item["slide"].id if item["slide"] else None,
                        "document_title": item["document"].title,
                        "slide_number": item["slide"].slide_number if item["slide"] else None,
                        "relevance_score": item["relevance_score"],
                        "source_quote": item.get("quote")
                    }
                })
        else:
            # Construct Prompt for LLM
            mode_instructions = {
                "NEW": "Generate FRESH, NOVEL questions grounded in the retrieved historical knowledge base facts. Do NOT copy historical questions word for word.",
                "REMIX": "Take the concepts from the historical questions but create substantially different questions with novel framing, reverse clues, or perspective shifts.",
                "SIMILAR": "Generate questions that closely mirror the structure, intellectual depth, and topic angle of the retrieved historical examples."
            }.get(req.generation_mode, "Generate fresh, engaging questions.")

            system_instruction = (
                "You are the Lead Quiz Master at QShala. Your mission is to craft captivating, curiosity-inducing "
                f"quiz questions calibrated for {audience_label}"
                + (f" (Grades {grade_min}–{grade_max})" if grade_min else "")
                + ".\n"
                "CORE QSHALA FORMAT PRINCIPLE: QShala quiz questions operate on the basis of a Question Slide followed by a Next Slide Answer with Explanation. "
                "They are NOT multiple-choice questions (do NOT generate A, B, C, D distractor choices; set options to null).\n"
                "Slide 1 (Question Slide): An engaging, curiosity-driven question or narrative clue.\n"
                "Slide 2 (Answer Slide): The clear, unambiguous answer, followed by a rich educational explanation and backstory.\n"
                "Ground all questions strictly in the provided evidence. Always reference the source tag (e.g. [SRC-1]).\n"
                "You must return a valid JSON object matching the requested schema."
            )

            grade_clause = f"Grades {grade_min}–{grade_max}" if grade_min else audience_label
            user_prompt = f"""
Requirements:
- Topic: {req.topic}
- Target Audience: {audience_label} ({grade_clause})
- Format: QShala Question Slide + Next Slide Answer with Explanation (NO multiple choice options, options must be null)
- Difficulty Preset: {req.difficulty}
- Question Count: {req.question_count}
- Exact Difficulty Distribution:
  * Easy: {easy_count} questions
  * Medium: {medium_count} questions
  * Hard: {hard_count} questions
- Note on Difficulty Calibration:
  Difficulty is RELATIVE to the audience.
  * For Primary (Grades 1-5): Easy is direct recognition; Medium is associative comparison; Hard is multi-step deduction for children.
  * For High School (Grades 9-12): Easy is foundational recall; Medium is contextual cause-and-effect; Hard requires synthesis of complex historical themes.
  * For College / University and Adults: Questions should feature academic rigor and advanced conceptual connections.
- Question Types: {', '.join(req.question_types)}
- Generation Mode: {req.generation_mode} ({mode_instructions})

Available QShala Evidence from Historical Archives:
{evidence_context}

Few-shot Style Examples from QShala Archive:
{json.dumps(style_examples, indent=2)}

Please return a JSON object with this exact structure:
{{
  "title": "{quiz_title}",
  "questions": [
    {{
      "question_text": "...",
      "options": null,
      "answer": "...",
      "explanation": "...",
      "difficulty": "Easy",
      "grade_min": {grade_min if grade_min is not None else 'null'},
      "grade_max": {grade_max if grade_max is not None else 'null'},
      "topic": "{req.topic}",
      "question_type": "SLIDE_QA",
      "source_tag": "SRC-1",
      "provenance_quote": "...",
      "provenance_rationale": "..."
    }}
  ]
}}
"""
            try:
                llm_response = await self.llm.generate_json(user_prompt, system_instruction=system_instruction)
                raw_list = llm_response.get("questions", [])
                
                for item in raw_list:
                    src_tag = item.get("source_tag", "SRC-1")
                    src_meta = source_mapping.get(src_tag) or (list(source_mapping.values())[0] if source_mapping else {})
                    item["provenance"] = {
                        "historical_question_id": src_meta.get("historical_question_id"),
                        "document_id": src_meta.get("document_id"),
                        "slide_id": src_meta.get("slide_id"),
                        "document_title": src_meta.get("document_title"),
                        "slide_number": src_meta.get("slide_number"),
                        "relevance_score": src_meta.get("relevance_score", 0.9),
                        "source_quote": item.get("provenance_quote") or (retrieved_items[0].get("quote") if retrieved_items else None),
                        "rationale": item.get("provenance_rationale") or "Derived from QShala archive."
                    }
                    generated_raw_questions.append(item)
            except Exception as e:
                logger.exception(f"Error calling LLM for quiz generation: {e}")
                # Fallback to local mock if LLM call failed
                from backend.app.services.ai.local_provider import LocalLLMProvider
                fallback_llm = LocalLLMProvider()
                mock_res = await fallback_llm.generate_json(user_prompt)
                for item in mock_res.get("questions", []):
                    src_meta = list(source_mapping.values())[0] if source_mapping else {}
                    item["provenance"] = {
                        "historical_question_id": src_meta.get("historical_question_id"),
                        "document_id": src_meta.get("document_id"),
                        "slide_id": src_meta.get("slide_id"),
                        "document_title": src_meta.get("document_title", "Historical QShala Archive"),
                        "slide_number": src_meta.get("slide_number", 1),
                        "relevance_score": 0.95,
                        "source_quote": item.get("provenance", {}).get("source_quote"),
                        "rationale": item.get("provenance", {}).get("rationale")
                    }
                    generated_raw_questions.append(item)

        # Step 4: Validate and Persist Questions
        for idx, q_data in enumerate(generated_raw_questions, start=1):
            assigned_diff = target_difficulties[idx - 1] if (idx - 1) < len(target_difficulties) else q_data.get("difficulty", "Medium")
            q_data["difficulty"] = assigned_diff

            val_result = await self.validator.validate_question(
                question=q_data,
                target_grade_min=grade_min,
                target_grade_max=grade_max,
                target_difficulty=assigned_diff,
                evidence_context=evidence_context,
                audience_type=aud_type
            )

            gen_q = GeneratedQuestion(
                quiz_id=quiz_obj.id,
                order_index=idx,
                question_text=q_data["question_text"],
                options=q_data.get("options"),
                answer=q_data["answer"],
                explanation=q_data.get("explanation"),
                difficulty=assigned_diff,
                grade_min=grade_min,
                grade_max=grade_max,
                topic=q_data.get("topic", req.topic),
                question_type=q_data.get("question_type", "SLIDE_QA"),
                validation_status=val_result["overall_status"],
                validation_details=val_result["details"],
                duplicate_score=val_result["duplicate_score"],
                is_approved=True
            )
            self.db.add(gen_q)
            self.db.flush()

            # Add RetrievalSource
            prov = q_data.get("provenance") or {}
            retrieval_src = RetrievalSource(
                generated_question_id=gen_q.id,
                historical_question_id=prov.get("historical_question_id"),
                document_id=prov.get("document_id"),
                slide_id=prov.get("slide_id"),
                document_title=prov.get("document_title"),
                slide_number=prov.get("slide_number"),
                relevance_score=prov.get("relevance_score", 1.0),
                source_quote=prov.get("source_quote"),
                rationale=prov.get("rationale")
            )
            self.db.add(retrieval_src)

        self.db.commit()
        self.db.refresh(quiz_obj)
        return quiz_obj

    async def execute_question_action(
        self,
        question_id: str,
        action: str,
        custom_instruction: Optional[str] = None
    ) -> GeneratedQuestion:
        """
        Executes granular actions:
        - 'regenerate': generate replacement question for same slot
        - 'make_easier': simplify vocabulary and clues
        - 'make_harder': increase deduction difficulty
        - 'generate_similar': generate sibling question on same topic
        """
        gen_q = self.db.query(GeneratedQuestion).filter(GeneratedQuestion.id == question_id).first()
        if not gen_q:
            raise ValueError(f"Question with ID {question_id} not found")

        quiz = gen_q.quiz
        new_diff = gen_q.difficulty
        if action == "make_easier":
            new_diff = "Easy"
        elif action == "make_harder":
            new_diff = "Hard"

        prompt = f"""
Current Question: {gen_q.question_text}
Current Answer: {gen_q.answer}
Current Options: {gen_q.options}
Action requested: {action.upper()}
Target Difficulty: {new_diff}
Target Grade: Grades {gen_q.grade_min}–{gen_q.grade_max}
Custom instructions: {custom_instruction or 'None'}

Please construct a revised or newly regenerated question keeping QShala's engaging quiz style.
Return JSON:
{{
  "question_text": "...",
  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
  "answer": "...",
  "explanation": "...",
  "difficulty": "{new_diff}"
}}
"""
        res = await self.llm.generate_json(prompt)
        
        gen_q.question_text = res.get("question_text", gen_q.question_text)
        gen_q.options = res.get("options", gen_q.options)
        gen_q.answer = res.get("answer", gen_q.answer)
        gen_q.explanation = res.get("explanation", gen_q.explanation)
        gen_q.difficulty = new_diff

        # Revalidate
        val_result = await self.validator.validate_question(
            question={
                "question_text": gen_q.question_text,
                "answer": gen_q.answer,
                "options": gen_q.options,
                "difficulty": gen_q.difficulty,
                "provenance": {"source_quote": "Regenerated from user action."}
            },
            target_grade_min=gen_q.grade_min or 3,
            target_grade_max=gen_q.grade_max or 5,
            target_difficulty=gen_q.difficulty,
            evidence_context=""
        )
        gen_q.validation_status = val_result["overall_status"]
        gen_q.validation_details = val_result["details"]
        gen_q.duplicate_score = val_result["duplicate_score"]

        self.db.commit()
        self.db.refresh(gen_q)
        return gen_q
