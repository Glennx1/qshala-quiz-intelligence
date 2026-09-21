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
                    "answer": q.answer,
                    "explanation": q.explanation,
                    "difficulty": q.difficulty,
                    "grade_range": f"{q.grade_min}-{q.grade_max}" if q.grade_min else "General",
                    "question_type": q.question_type,
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
            "Answer",
            "Explanation",
            "Difficulty",
            "Topic",
            "Primary Source"
        ])

        for q in quiz.questions:
            if not q.is_approved:
                continue

            primary_src = ""
            if q.retrieval_sources:
                s = q.retrieval_sources[0]
                primary_src = f"{s.document_title or 'Doc'} (Slide {s.slide_number or 'N/A'})"

            writer.writerow([
                q.order_index,
                q.question_text,
                q.answer,
                q.explanation or "",
                q.difficulty,
                q.topic or quiz.topic,
                primary_src
            ])

        return output.getvalue()

    @staticmethod
    def to_pptx(quiz: Quiz) -> bytes:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor

        prs = Presentation()
        prs.slide_width = Inches(10)
        prs.slide_height = Inches(5.625)
        blank_layout = prs.slide_layouts[6]

        # Slide 1: Title Slide
        slide = prs.slides.add_slide(blank_layout)
        tb = slide.shapes.add_textbox(Inches(1), Inches(1.5), Inches(8), Inches(2.5))
        tf = tb.text_frame
        p = tf.paragraphs[0]
        p.text = quiz.title
        p.font.size = Pt(34)
        p.font.bold = True
        p.font.color.rgb = RGBColor(15, 23, 42)

        p2 = tf.add_paragraph()
        grade_info = f" · Grades {quiz.grade_min}–{quiz.grade_max}" if quiz.grade_min else ""
        p2.text = f"Topic: {quiz.topic}{grade_info} · Difficulty: {quiz.difficulty}"
        p2.font.size = Pt(18)
        p2.font.color.rgb = RGBColor(100, 116, 139)

        p3 = tf.add_paragraph()
        p3.text = "Powered by QShala Quiz Intelligence Platform"
        p3.font.size = Pt(14)
        p3.font.color.rgb = RGBColor(148, 163, 184)

        # Question Slides & Answer Slides
        approved_questions = [q for q in quiz.questions if q.is_approved]
        for idx, q in enumerate(approved_questions, start=1):
            # 1. Question Slide
            slide_q = prs.slides.add_slide(blank_layout)
            tb_q = slide_q.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8.4), Inches(4.0))
            tf_q = tb_q.text_frame
            tf_q.word_wrap = True

            p_qh = tf_q.paragraphs[0]
            p_qh.text = f"QUESTION {idx} / {len(approved_questions)} · {q.difficulty.upper()}"
            p_qh.font.size = Pt(13)
            p_qh.font.bold = True
            p_qh.font.color.rgb = RGBColor(100, 116, 139)

            p_q = tf_q.add_paragraph()
            p_q.text = q.question_text
            p_q.font.size = Pt(24)
            p_q.font.bold = True
            p_q.font.color.rgb = RGBColor(15, 23, 42)

            # 2. Answer & Explanation Slide
            slide_a = prs.slides.add_slide(blank_layout)
            tb_a = slide_a.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8.4), Inches(4.0))
            tf_a = tb_a.text_frame
            tf_a.word_wrap = True

            p_ah = tf_a.paragraphs[0]
            p_ah.text = f"ANSWER {idx}"
            p_ah.font.size = Pt(13)
            p_ah.font.bold = True
            p_ah.font.color.rgb = RGBColor(16, 185, 129)

            p_ans = tf_a.add_paragraph()
            p_ans.text = f"Answer: {q.answer}"
            p_ans.font.size = Pt(26)
            p_ans.font.bold = True
            p_ans.font.color.rgb = RGBColor(5, 150, 105)

            if q.explanation:
                p_gap = tf_a.add_paragraph()
                p_gap.text = ""

                p_etitle = tf_a.add_paragraph()
                p_etitle.text = "Explanation & Story:"
                p_etitle.font.size = Pt(15)
                p_etitle.font.bold = True
                p_etitle.font.color.rgb = RGBColor(71, 85, 105)

                p_e = tf_a.add_paragraph()
                p_e.text = q.explanation
                p_e.font.size = Pt(17)
                p_e.font.color.rgb = RGBColor(51, 65, 85)

        buffer = io.BytesIO()
        prs.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
