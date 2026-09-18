import csv
import io
import json
from typing import Dict, Any
from backend.app.models.quiz import Quiz

class QuizExporter:
    @staticmethod
    def to_json(quiz: Quiz) -> str:
        data = {
            "quiz_id": quiz.id,
            "title": quiz.title,
            "topic": quiz.topic,
            "subtopic": quiz.subtopic,
            "grade_min": quiz.grade_min,
            "grade_max": quiz.grade_max,
            "difficulty": quiz.difficulty,
            "generation_mode": quiz.generation_mode,
            "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
            "questions": [
                {
                    "order": q.order_index,
                    "question": q.question_text,
                    "options": q.options,
                    "answer": q.answer,
                    "explanation": q.explanation,
                    "difficulty": q.difficulty,
                    "grade_range": f"{q.grade_min}-{q.grade_max}",
                    "validation_status": q.validation_status,
                    "sources": [
                        {
                            "document_title": src.document_title,
                            "slide_number": src.slide_number,
                            "quote": src.source_quote
                        }
                        for src in q.retrieval_sources
                    ]
                }
                for q in quiz.questions
                if q.is_approved
            ]
        }
        return json.dumps(data, indent=2)

    @staticmethod
    def to_csv(quiz: Quiz) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Order",
            "Question",
            "Option A",
            "Option B",
            "Option C",
            "Option D",
            "Correct Answer",
            "Explanation",
            "Difficulty",
            "Topic",
            "Primary Source"
        ])

        for q in quiz.questions:
            if not q.is_approved:
                continue
            opts = q.options or []
            opt_a = opts[0] if len(opts) > 0 else ""
            opt_b = opts[1] if len(opts) > 1 else ""
            opt_c = opts[2] if len(opts) > 2 else ""
            opt_d = opts[3] if len(opts) > 3 else ""

            primary_src = ""
            if q.retrieval_sources:
                s = q.retrieval_sources[0]
                primary_src = f"{s.document_title or 'Doc'} (Slide {s.slide_number or 'N/A'})"

            writer.writerow([
                q.order_index,
                q.question_text,
                opt_a,
                opt_b,
                opt_c,
                opt_d,
                q.answer,
                q.explanation or "",
                q.difficulty,
                q.topic or quiz.topic,
                primary_src
            ])

        return output.getvalue()
