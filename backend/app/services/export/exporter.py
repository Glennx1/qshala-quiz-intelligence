import csv
import io
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from PIL import Image

logger = logging.getLogger(__name__)

def _resolve_image_path(rel_url: Optional[str]) -> Optional[Path]:
    if not rel_url or not isinstance(rel_url, str):
        return None
    from backend.app.config import settings
    clean_url = rel_url.strip()
    
    # 1. Slide extracts directory
    if clean_url.startswith("/static/slides/"):
        sub = clean_url[len("/static/slides/"):]
        p = settings.SLIDES_DIR / sub
        if p.exists() and p.is_file():
            return p
    # 2. Storage directory general
    elif clean_url.startswith("/static/"):
        sub = clean_url.lstrip("/static/")
        p = settings.STORAGE_DIR / sub
        if p.exists() and p.is_file():
            return p
    
    # 3. Direct path
    p_direct = Path(clean_url)
    if p_direct.exists() and p_direct.is_file():
        return p_direct
        
    # 4. Storage uploads directory check
    p_upload = settings.STORAGE_DIR / "uploads" / Path(clean_url).name
    if p_upload.exists() and p_upload.is_file():
        return p_upload
        
    return None

def _add_scaled_picture(slide, img_path: Path, max_left, max_top, max_w, max_h):
    """Adds an image keeping exact aspect ratio without distortion or borders."""
    try:
        with Image.open(img_path) as pil_img:
            img_w, img_h = pil_img.size
        if img_w <= 0 or img_h <= 0:
            return None
        scale = min(float(max_w) / img_w, float(max_h) / img_h)
        scaled_w = int(img_w * scale)
        scaled_h = int(img_h * scale)
        final_left = int(max_left + (max_w - scaled_w) / 2)
        final_top = int(max_top + (max_h - scaled_h) / 2)
        return slide.shapes.add_picture(str(img_path), final_left, final_top, width=scaled_w, height=scaled_h)
    except Exception as img_err:
        logger.warning(f"Error adding picture {img_path} to slide: {img_err}")
        return None

def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Helper to extract attribute from dict or object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

class QuizExporter:
    @staticmethod
    def to_json(quiz: Any) -> str:
        quiz_id = _get_val(quiz, "id", "generated_quiz")
        title = _get_val(quiz, "title", "Tournament Quiz")
        topic = _get_val(quiz, "topic", "General")
        subtopic = _get_val(quiz, "subtopic")
        grade_min = _get_val(quiz, "grade_min")
        grade_max = _get_val(quiz, "grade_max")
        difficulty = _get_val(quiz, "difficulty", "Balanced")
        difficulty_distribution = _get_val(quiz, "difficulty_distribution", {})
        generation_mode = _get_val(quiz, "generation_mode", "NEW")
        created_at = _get_val(quiz, "created_at")
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()

        questions_raw = _get_val(quiz, "questions", [])
        questions_list = []
        for q in questions_raw:
            is_approved = _get_val(q, "is_approved", True)
            if not is_approved:
                continue

            sources = _get_val(q, "retrieval_sources", []) or _get_val(q, "sources", [])
            sources_list = []
            for src in sources:
                sources_list.append({
                    "document_title": _get_val(src, "document_title"),
                    "slide_number": _get_val(src, "slide_number"),
                    "quote": _get_val(src, "source_quote") or _get_val(src, "quote"),
                    "rationale": _get_val(src, "rationale")
                })

            q_min = _get_val(q, "grade_min")
            q_max = _get_val(q, "grade_max")
            grade_range = f"{q_min}-{q_max}" if q_min and q_max else "General"

            questions_list.append({
                "order": _get_val(q, "order_index") or _get_val(q, "order", 1),
                "question": _get_val(q, "question_text") or _get_val(q, "question", ""),
                "options": _get_val(q, "options", []),
                "answer": _get_val(q, "answer", ""),
                "explanation": _get_val(q, "explanation", ""),
                "difficulty": _get_val(q, "difficulty", "Medium"),
                "grade_range": grade_range,
                "question_type": _get_val(q, "question_type", "SLIDE_QA"),
                "image_refs": _get_val(q, "image_refs", []) or [],
                "question_images": _get_val(q, "question_images", []) or [],
                "answer_images": _get_val(q, "answer_images", []) or [],
                "visual_clues": _get_val(q, "visual_clues"),
                "audio_refs": _get_val(q, "audio_refs", []) or [],
                "question_audio": _get_val(q, "question_audio", []) or [],
                "answer_audio": _get_val(q, "answer_audio", []) or [],
                "validation_status": _get_val(q, "validation_status", "PASSED"),
                "sources": sources_list
            })

        data = {
            "quiz_id": quiz_id,
            "title": title,
            "topic": topic,
            "subtopic": subtopic,
            "grade_min": grade_min,
            "grade_max": grade_max,
            "difficulty": difficulty,
            "difficulty_distribution": difficulty_distribution,
            "generation_mode": generation_mode,
            "created_at": created_at,
            "questions": questions_list
        }
        return json.dumps(data, indent=2)

    @staticmethod
    def to_csv(quiz: Any) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Order",
            "Question",
            "Options",
            "Answer",
            "Explanation",
            "Difficulty",
            "Topic",
            "Primary Source"
        ])

        quiz_topic = _get_val(quiz, "topic", "General")
        questions_raw = _get_val(quiz, "questions", [])
        for q in questions_raw:
            if not _get_val(q, "is_approved", True):
                continue

            sources = _get_val(q, "retrieval_sources", []) or _get_val(q, "sources", [])
            primary_src = ""
            if sources:
                s = sources[0]
                doc_title = _get_val(s, "document_title", "Deck")
                slide_num = _get_val(s, "slide_number", "N/A")
                primary_src = f"{doc_title} (Slide {slide_num})"

            opts = _get_val(q, "options", [])
            options_str = " | ".join(opts) if opts else "N/A"

            writer.writerow([
                _get_val(q, "order_index") or _get_val(q, "order", 1),
                _get_val(q, "question_text") or _get_val(q, "question", ""),
                options_str,
                _get_val(q, "answer", ""),
                _get_val(q, "explanation", ""),
                _get_val(q, "difficulty", "Medium"),
                _get_val(q, "topic") or quiz_topic,
                primary_src
            ])

        return output.getvalue()

    @staticmethod
    def to_pptx(quiz: Any) -> bytes:
        """
        Exports the quiz into a crisp, minimalist, high-typography presentation deck (16:9 widescreen).
        
        Designed to be clean, to the point, and free of unnecessary fluff:
        1. Minimalist Title Slide (Dark architectural canvas, crisp typography)
        2. Direct Question -> Answer Slide sequence (No filler slides, 1 slide per question followed immediately by its answer)
        3. High legibility fonts (28-34pt questions, 38-44pt answers, 18-20pt context/options)
        4. Generous whitespace, clean natural image scaling without clunky frames or heavy borders
        5. Comprehensive host notes in Speaker Notes
        """
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        prs = Presentation()
        # 16:9 Widescreen standard
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank_layout = prs.slide_layouts[6]

        # -------------------------------------------------------------
        # Minimalist Color Palette & Typography
        # -------------------------------------------------------------
        C_WHITE = RGBColor(255, 255, 255)
        C_DARK_BG = RGBColor(15, 23, 42)          # #0F172A Slate 900
        C_TEXT_DARK = RGBColor(15, 23, 42)        # #0F172A Deep Charcoal
        C_TEXT_BODY = RGBColor(51, 65, 85)        # #334155 Slate 700
        C_TEXT_MUTED = RGBColor(100, 116, 139)    # #64748B Slate 500
        C_ACCENT_BLUE = RGBColor(37, 99, 235)     # #2563EB Blue 600
        C_ACCENT_GREEN = RGBColor(5, 150, 105)    # #059669 Emerald 600
        C_ACCENT_GOLD = RGBColor(217, 119, 6)     # #D97706 Amber 600

        FONT_HEAD = "Trebuchet MS"
        FONT_BODY = "Calibri"

        title_text = _get_val(quiz, "title", "QShala Tournament Quiz")
        topic_text = _get_val(quiz, "topic", "General Knowledge")
        personality = _get_val(quiz, "personality")
        difficulty = _get_val(quiz, "difficulty", "Balanced")

        questions_raw = _get_val(quiz, "questions", [])
        approved_questions = [q for q in questions_raw if _get_val(q, "is_approved", True)]
        total_q = len(approved_questions)

        # -------------------------------------------------------------
        # 1. Clean Minimalist Title Slide
        # -------------------------------------------------------------
        s_title = prs.slides.add_slide(blank_layout)
        bg_title = s_title.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg_title.fill.solid()
        bg_title.fill.fore_color.rgb = C_DARK_BG
        bg_title.line.fill.background()

        tb_title = s_title.shapes.add_textbox(Inches(1.2), Inches(2.1), Inches(10.9), Inches(3.6))
        tf_title = tb_title.text_frame
        tf_title.word_wrap = True

        p_super = tf_title.paragraphs[0]
        p_super.text = "QSHALA TOURNAMENT DECK"
        p_super.font.name = FONT_HEAD
        p_super.font.size = Pt(13)
        p_super.font.bold = True
        p_super.font.color.rgb = C_ACCENT_GOLD

        p_h1 = tf_title.add_paragraph()
        p_h1.space_before = Pt(10)
        p_h1.text = title_text
        p_h1.font.name = FONT_HEAD
        p_h1.font.size = Pt(46)
        p_h1.font.bold = True
        p_h1.font.color.rgb = C_WHITE

        p_sub = tf_title.add_paragraph()
        p_sub.space_before = Pt(16)
        p_sub.text = f"{topic_text}   •   {total_q} Questions   •   Difficulty: {difficulty}"
        p_sub.font.name = FONT_BODY
        p_sub.font.size = Pt(19)
        p_sub.font.color.rgb = RGBColor(148, 163, 184)

        s_title.notes_slide.notes_text_frame.text = (
            f"Host Welcome Note:\n"
            f"Tournament: {title_text}\n"
            f"Topic: {topic_text} | Total Questions: {total_q}\n"
            f"Welcome teams and ensure score sheets are ready."
        )

        # -------------------------------------------------------------
        # 2. Sequential Question & Answer Slides (Direct & To The Point)
        # -------------------------------------------------------------
        for idx, q in enumerate(approved_questions, start=1):
            is_starred = (idx % 5 == 0)
            star_tag = " *" if is_starred else ""

            # Resolve Question Media
            q_imgs = _get_val(q, "question_images", []) or _get_val(q, "image_refs", []) or []
            resolved_q_imgs = [_resolve_image_path(img) for img in q_imgs]
            valid_q_imgs = [p for p in resolved_q_imgs if p is not None]

            q_text = (_get_val(q, "question_text") or _get_val(q, "question", "")).strip()
            options = _get_val(q, "options", []) or []
            cat_text = (_get_val(q, "topic") or topic_text).upper()

            # Dynamic font sizing calibrated for maximum readability
            q_font_size = Pt(30) if len(q_text) < 140 else (Pt(26) if len(q_text) < 220 else Pt(22))

            # ---------------------------------------------------------
            # (A) QUESTION SLIDE
            # ---------------------------------------------------------
            sq = prs.slides.add_slide(blank_layout)
            bg_q = sq.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
            bg_q.fill.solid()
            bg_q.fill.fore_color.rgb = C_WHITE
            bg_q.line.fill.background()

            # Top Clean Tag (Category & Question Number)
            tb_qtag = sq.shapes.add_textbox(Inches(1.0), Inches(0.6), Inches(11.3), Inches(0.5))
            pq_tag = tb_qtag.text_frame.paragraphs[0]
            aud_tag = "   [AUDIO CLUE]" if (_get_val(q, "question_audio", []) or _get_val(q, "audio_refs", [])) else ""
            pq_tag.text = f"QUESTION {idx:02d}{star_tag}   /   {cat_text}{aud_tag}"
            pq_tag.font.name = FONT_HEAD
            pq_tag.font.size = Pt(13)
            pq_tag.font.bold = True
            pq_tag.font.color.rgb = C_ACCENT_BLUE

            if len(valid_q_imgs) == 1:
                # 60/40 Minimalist Split: Left Text & Options, Right Image
                tb_q = sq.shapes.add_textbox(Inches(1.0), Inches(1.3), Inches(6.8), Inches(5.2))
                tf_q = tb_q.text_frame
                tf_q.word_wrap = True

                pq_main = tf_q.paragraphs[0]
                pq_main.text = q_text
                pq_main.font.name = FONT_HEAD
                pq_main.font.size = q_font_size
                pq_main.font.bold = True
                pq_main.font.color.rgb = C_TEXT_DARK

                if options:
                    for opt_idx, opt in enumerate(options):
                        po = tf_q.add_paragraph()
                        po.space_before = Pt(8)
                        prefix = f"{chr(65 + opt_idx)}.  " if opt_idx < 26 and not opt.startswith(('A.', 'B.', 'C.', 'D.')) else ""
                        po.text = f"{prefix}{opt}"
                        po.font.name = FONT_BODY
                        po.font.size = Pt(17)
                        po.font.color.rgb = C_TEXT_BODY

                _add_scaled_picture(sq, valid_q_imgs[0], Inches(8.1), Inches(1.3), Inches(4.2), Inches(5.1))

            elif len(valid_q_imgs) >= 2:
                # 2 Images: Question on Top, Side-by-side Images Below
                tb_q = sq.shapes.add_textbox(Inches(1.0), Inches(1.2), Inches(11.3), Inches(1.8))
                tf_q = tb_q.text_frame
                tf_q.word_wrap = True

                pq_main = tf_q.paragraphs[0]
                pq_main.text = q_text
                pq_main.font.name = FONT_HEAD
                pq_main.font.size = Pt(24)
                pq_main.font.bold = True
                pq_main.font.color.rgb = C_TEXT_DARK

                _add_scaled_picture(sq, valid_q_imgs[0], Inches(1.0), Inches(3.1), Inches(5.4), Inches(3.6))
                _add_scaled_picture(sq, valid_q_imgs[1], Inches(6.8), Inches(3.1), Inches(5.4), Inches(3.6))

            else:
                # Full Width Layout with Generous Breathing Room
                tb_q = sq.shapes.add_textbox(Inches(1.2), Inches(1.6), Inches(10.9), Inches(5.0))
                tf_q = tb_q.text_frame
                tf_q.word_wrap = True

                pq_main = tf_q.paragraphs[0]
                pq_main.text = q_text
                pq_main.font.name = FONT_HEAD
                pq_main.font.size = Pt(32) if len(q_text) < 160 else Pt(26)
                pq_main.font.bold = True
                pq_main.font.color.rgb = C_TEXT_DARK

                if options:
                    for opt_idx, opt in enumerate(options):
                        po = tf_q.add_paragraph()
                        po.space_before = Pt(12)
                        prefix = f"{chr(65 + opt_idx)}.  " if opt_idx < 26 and not opt.startswith(('A.', 'B.', 'C.', 'D.')) else ""
                        po.text = f"{prefix}{opt}"
                        po.font.name = FONT_BODY
                        po.font.size = Pt(19)
                        po.font.color.rgb = C_TEXT_BODY

            # Minimalist Footer
            tb_qfoot = sq.shapes.add_textbox(Inches(1.0), Inches(6.8), Inches(11.3), Inches(0.4))
            pq_foot = tb_qfoot.text_frame.paragraphs[0]
            star_note = "   •   [★ TIE-BREAKER QUESTION]" if is_starred else ""
            pq_foot.text = f"QShala Quiz Intelligence   •   Question {idx} of {total_q}{star_note}"
            pq_foot.font.name = FONT_BODY
            pq_foot.font.size = Pt(10)
            pq_foot.font.color.rgb = C_TEXT_MUTED

            # Speaker Notes
            host_notes = []
            if is_starred:
                host_notes.append("★ Important: Star tie-breaker question!")
            ans_val = (_get_val(q, "answer") or "N/A").strip()
            host_notes.append(f"Official Answer: {ans_val}")
            aud_clips = _get_val(q, "question_audio", []) or _get_val(q, "audio_refs", [])
            if aud_clips:
                host_notes.append(f"Audio clue clip: {aud_clips[0]}")
            sq.notes_slide.notes_text_frame.text = "\n".join(host_notes)

            # ---------------------------------------------------------
            # (B) ANSWER REVEAL SLIDE (Immediately follows the question!)
            # ---------------------------------------------------------
            sa = prs.slides.add_slide(blank_layout)
            bg_a = sa.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
            bg_a.fill.solid()
            bg_a.fill.fore_color.rgb = C_WHITE
            bg_a.line.fill.background()

            # Top Tag
            tb_atag = sa.shapes.add_textbox(Inches(1.0), Inches(0.6), Inches(11.3), Inches(0.5))
            pa_tag = tb_atag.text_frame.paragraphs[0]
            pa_tag.text = f"ANSWER {idx:02d}   /   SOLUTION"
            pa_tag.font.name = FONT_HEAD
            pa_tag.font.size = Pt(13)
            pa_tag.font.bold = True
            pa_tag.font.color.rgb = C_ACCENT_GREEN

            # Resolve Answer Media
            ans_imgs = _get_val(q, "answer_images", []) or []
            resolved_ans_imgs = [_resolve_image_path(img) for img in ans_imgs]
            valid_ans_imgs = [p for p in resolved_ans_imgs if p is not None]
            if not valid_ans_imgs and valid_q_imgs:
                valid_ans_imgs = valid_q_imgs

            ans_size = Pt(40) if len(ans_val) < 35 else (Pt(32) if len(ans_val) < 70 else Pt(26))
            explanation = (_get_val(q, "explanation") or "").strip()

            if valid_ans_imgs:
                # Answer & Story Left, Solution Image Right
                tb_a = sa.shapes.add_textbox(Inches(1.0), Inches(1.3), Inches(6.8), Inches(5.2))
                tf_a = tb_a.text_frame
                tf_a.word_wrap = True

                pa_head = tf_a.paragraphs[0]
                pa_head.text = ans_val
                pa_head.font.name = FONT_HEAD
                pa_head.font.size = ans_size
                pa_head.font.bold = True
                pa_head.font.color.rgb = C_ACCENT_GREEN

                if explanation:
                    pa_exp = tf_a.add_paragraph()
                    pa_exp.space_before = Pt(16)
                    pa_exp.text = explanation
                    pa_exp.font.name = FONT_BODY
                    pa_exp.font.size = Pt(18)
                    pa_exp.font.color.rgb = C_TEXT_BODY

                _add_scaled_picture(sa, valid_ans_imgs[0], Inches(8.1), Inches(1.3), Inches(4.2), Inches(5.1))

            else:
                # Full Width Answer & Explanation
                tb_a = sa.shapes.add_textbox(Inches(1.2), Inches(1.6), Inches(10.9), Inches(5.0))
                tf_a = tb_a.text_frame
                tf_a.word_wrap = True

                pa_head = tf_a.paragraphs[0]
                pa_head.text = ans_val
                pa_head.font.name = FONT_HEAD
                pa_head.font.size = Pt(44) if len(ans_val) < 35 else Pt(34)
                pa_head.font.bold = True
                pa_head.font.color.rgb = C_ACCENT_GREEN

                if explanation:
                    pa_exp = tf_a.add_paragraph()
                    pa_exp.space_before = Pt(20)
                    pa_exp.text = explanation
                    pa_exp.font.name = FONT_BODY
                    pa_exp.font.size = Pt(20)
                    pa_exp.font.color.rgb = C_TEXT_BODY

            # Minimalist Provenance Citation Footer
            sources = _get_val(q, "retrieval_sources", []) or _get_val(q, "sources", [])
            src_note = ""
            if sources:
                s = sources[0]
                doc_title = _get_val(s, "document_title") or "Tournament Archive"
                slide_num = _get_val(s, "slide_number") or "N/A"
                src_note = f"   •   Source: {doc_title} (Slide {slide_num})"

            tb_afoot = sa.shapes.add_textbox(Inches(1.0), Inches(6.8), Inches(11.3), Inches(0.4))
            pa_foot = tb_afoot.text_frame.paragraphs[0]
            pa_foot.text = f"QShala Quiz Intelligence   •   Scoring: +10 Points{src_note}"
            pa_foot.font.name = FONT_BODY
            pa_foot.font.size = Pt(10)
            pa_foot.font.color.rgb = C_TEXT_MUTED

            # Speaker Notes for Answer Slide
            sa.notes_slide.notes_text_frame.text = (
                f"Presenter Talking Points:\n"
                f"Official Answer: {ans_val}\n"
                f"Award +10 points to any team with the correct answer or verified synonym.\n"
                f"Trivia Context: {explanation}"
            )

        buffer = io.BytesIO()
        prs.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
