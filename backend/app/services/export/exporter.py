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

def _add_scaled_picture(slide, img_path: Path, max_left, max_top, max_w, max_h, border_color=None):
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
        pic = slide.shapes.add_picture(str(img_path), final_left, final_top, width=scaled_w, height=scaled_h)
        if border_color:
            from pptx.util import Pt
            pic.line.color.rgb = border_color
            pic.line.width = Pt(1.5)
        return pic
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
        Exports the quiz into an authentic QShala tournament presentation deck (16:9 widescreen),
        matching the visual hierarchy and pacing of DSU Business Quiz Prelims and Quizzards Prelims:
        
        1. Master Tournament Title Slide (Midnight Navy, Gold accent, Pill badges, Host persona)
        2. Rules & Guidelines Preamble (4 tournament pillars in 2x2 grid)
        3. Question Round (Authoritative number, Theme pill in top-right, adaptive media layout, options)
        4. Intermission Divider ("PLEASE HAND IN YOUR SHEETS / PRELIM ANSWERS WILL BE ANNOUNCED SOON!")
        5. Answer Walkthrough:
           - Suspense / dramatic pause slide ("ANSWER" 54pt bold)
           - Answer Reveal slide (Huge answer headline, "The Story Behind The Answer" card, solution media)
        6. Speaker Notes on every slide for live host guidance and scoring rules.
        """
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        prs = Presentation()
        # Authentic 16:9 Widescreen standard
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank_layout = prs.slide_layouts[6]

        # -------------------------------------------------------------
        # Curated QShala Tournament Palette
        # -------------------------------------------------------------
        C_NAVY_DARK = RGBColor(10, 25, 47)       # #0A192F Tournament Midnight Navy
        C_NAVY_SLATE = RGBColor(15, 23, 42)      # #0F172A Deep Studio Canvas
        C_SLATE_800 = RGBColor(30, 41, 59)       # #1E293B Rule Card Dark
        C_SLATE_700 = RGBColor(51, 65, 85)       # #334155 Body Charcoal
        C_SLATE_500 = RGBColor(100, 116, 139)    # #64748B Secondary / Citation
        C_SLATE_400 = RGBColor(148, 163, 184)    # #94A3B8 Muted Subtext
        C_SLATE_200 = RGBColor(226, 232, 240)    # #E2E8F0 Card Border
        C_SLATE_100 = RGBColor(241, 245, 249)    # #F1F5F9 Option / Card Light
        C_SLATE_50 = RGBColor(248, 250, 252)     # #F8FAFC Story Card Background
        C_WHITE = RGBColor(255, 255, 255)        # Pure White
        C_BLUE_600 = RGBColor(37, 99, 235)       # #2563EB Royal Accent
        C_BLUE_100 = RGBColor(219, 234, 254)     # #DBEAFE
        C_EMERALD_600 = RGBColor(5, 150, 105)    # #059669 Reveal Green
        C_EMERALD_500 = RGBColor(16, 185, 129)   # #10B981 Accent Green
        C_EMERALD_50 = RGBColor(236, 253, 245)   # #ECFDF5 Pill Light
        C_AMBER_500 = RGBColor(245, 158, 11)     # #F59E0B Tournament Gold
        C_AMBER_100 = RGBColor(254, 243, 199)    # #FEF3C7
        C_ROSE_600 = RGBColor(225, 29, 72)       # #E11D48 Crimson

        FONT_PRIMARY = "Calibri"
        FONT_HEADING = "Trebuchet MS"

        title_text = _get_val(quiz, "title", "QShala Tournament Quiz")
        topic_text = _get_val(quiz, "topic", "General Knowledge")
        personality = _get_val(quiz, "personality")
        difficulty = _get_val(quiz, "difficulty", "Balanced")
        grade_min = _get_val(quiz, "grade_min")
        grade_max = _get_val(quiz, "grade_max")
        grade_str = f"Grades {grade_min}–{grade_max}" if grade_min and grade_max else "Open Championship"

        questions_raw = _get_val(quiz, "questions", [])
        approved_questions = [q for q in questions_raw if _get_val(q, "is_approved", True)]
        total_q = len(approved_questions)

        persona_label = {
            "CURIOSITY_STORYTELLER": "The Storyteller / Curiosity Coach",
            "DETECTIVE_PUZZLER": "The Detective / Lateral Puzzle Master",
            "TOURNAMENT_PRO": "Tournament Pro (Official Buzzer)",
            "SOCRATIC_EXPLORER": "Socratic Discussion Host"
        }.get(personality, "QShala Master Quizmaster")

        # -------------------------------------------------------------
        # SLIDE 1: Master Tournament Title Slide
        # -------------------------------------------------------------
        s1 = prs.slides.add_slide(blank_layout)
        bg1 = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg1.fill.solid()
        bg1.fill.fore_color.rgb = C_NAVY_DARK
        bg1.line.fill.background()

        # Top Gold Accent Ribbon
        top_strip = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.7), Inches(11.733), Inches(0.06))
        top_strip.fill.solid()
        top_strip.fill.fore_color.rgb = C_AMBER_500
        top_strip.line.fill.background()

        # Pill Tag: TOURNAMENT PRELIMS
        badge_cover = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.1), Inches(3.2), Inches(0.48))
        badge_cover.fill.solid()
        badge_cover.fill.fore_color.rgb = C_BLUE_600
        badge_cover.line.fill.background()
        p_b = badge_cover.text_frame.paragraphs[0]
        p_b.text = "TOURNAMENT PRELIMS"
        p_b.font.name = FONT_HEADING
        p_b.font.size = Pt(13)
        p_b.font.bold = True
        p_b.font.color.rgb = C_WHITE
        p_b.alignment = PP_ALIGN.CENTER

        # Tournament Title Box
        tb_title = s1.shapes.add_textbox(Inches(0.8), Inches(1.9), Inches(11.733), Inches(2.2))
        tf_t = tb_title.text_frame
        tf_t.word_wrap = True
        p_t1 = tf_t.paragraphs[0]
        p_t1.text = title_text
        p_t1.font.name = FONT_HEADING
        p_t1.font.size = Pt(44)
        p_t1.font.bold = True
        p_t1.font.color.rgb = C_WHITE

        p_t2 = tf_t.add_paragraph()
        p_t2.space_before = Pt(14)
        p_t2.text = f"{topic_text}  •  {grade_str}  •  Difficulty: {difficulty}"
        p_t2.font.name = FONT_PRIMARY
        p_t2.font.size = Pt(20)
        p_t2.font.color.rgb = C_SLATE_400

        # Host Persona & Competition Box
        meta_box = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(4.5), Inches(11.733), Inches(1.0))
        meta_box.fill.solid()
        meta_box.fill.fore_color.rgb = C_NAVY_SLATE
        meta_box.line.color.rgb = C_SLATE_700
        meta_box.line.width = Pt(1)

        tf_m = meta_box.text_frame
        tf_m.word_wrap = True
        p_m = tf_m.paragraphs[0]
        p_m.text = f"Official Competition Deck  |  Host Persona: {persona_label}  |  Total Questions: {total_q}"
        p_m.font.name = FONT_PRIMARY
        p_m.font.size = Pt(14)
        p_m.font.color.rgb = C_AMBER_500
        p_m.font.bold = True
        p_m.alignment = PP_ALIGN.CENTER

        # Footer
        tb_foot = s1.shapes.add_textbox(Inches(0.8), Inches(6.5), Inches(11.733), Inches(0.5))
        p_foot = tb_foot.text_frame.paragraphs[0]
        p_foot.text = "Presented by QShala  •  Curiosity Partner  •  Intelligence Powered by Advanced Search & Ingestion"
        p_foot.font.name = FONT_PRIMARY
        p_foot.font.size = Pt(12)
        p_foot.font.color.rgb = C_SLATE_500

        s1.notes_slide.notes_text_frame.text = (
            f"Host Welcome Note:\n"
            f"Welcome teams to {title_text}!\n"
            f"Host Style: {persona_label}\n"
            f"Total questions: {total_q}. Ensure all teams have score sheets and pens ready."
        )

        # -------------------------------------------------------------
        # SLIDE 2: Tournament Rules & Scoring Guidelines (Preamble)
        # -------------------------------------------------------------
        s2 = prs.slides.add_slide(blank_layout)
        bg2 = s2.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg2.fill.solid()
        bg2.fill.fore_color.rgb = C_NAVY_SLATE
        bg2.line.fill.background()

        tb_rh = s2.shapes.add_textbox(Inches(0.8), Inches(0.6), Inches(11.733), Inches(0.8))
        p_rh = tb_rh.text_frame.paragraphs[0]
        p_rh.text = "RULES & GUIDELINES"
        p_rh.font.name = FONT_HEADING
        p_rh.font.size = Pt(36)
        p_rh.font.bold = True
        p_rh.font.color.rgb = C_WHITE

        rules = [
            ("1. SCORING SYSTEM", "+10 Points for each correct direct answer. No negative marks in this prelim round.", C_EMERALD_500),
            ("2. STAR QUESTIONS (*)", "Questions marked with an asterisk (*) carry tie-break weightage in case of level scores.", C_AMBER_500),
            ("3. ANSWER SUBMISSION", "Teams must write final answers legibly on official sheets before the intermission timer ends.", C_BLUE_600),
            ("4. QUIZMASTER'S DISCRETION", "The Quizmaster's call on acceptable spellings, alternate names, and points is final.", C_ROSE_600),
        ]

        card_coords = [
            (Inches(0.8), Inches(1.6)),
            (Inches(6.8), Inches(1.6)),
            (Inches(0.8), Inches(4.0)),
            (Inches(6.8), Inches(4.0)),
        ]

        for (r_title, r_desc, r_col), (c_left, c_top) in zip(rules, card_coords):
            card = s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, c_left, c_top, Inches(5.7), Inches(2.0))
            card.fill.solid()
            card.fill.fore_color.rgb = C_SLATE_800
            card.line.color.rgb = C_SLATE_700
            card.line.width = Pt(1)

            tf_c = card.text_frame
            tf_c.word_wrap = True
            tf_c.margin_left = Inches(0.3)
            tf_c.margin_top = Inches(0.25)
            tf_c.margin_right = Inches(0.3)

            p1 = tf_c.paragraphs[0]
            p1.text = r_title
            p1.font.name = FONT_HEADING
            p1.font.size = Pt(16)
            p1.font.bold = True
            p1.font.color.rgb = r_col

            p2 = tf_c.add_paragraph()
            p2.space_before = Pt(8)
            p2.text = r_desc
            p2.font.name = FONT_PRIMARY
            p2.font.size = Pt(14)
            p2.font.color.rgb = C_SLATE_200

        s2.notes_slide.notes_text_frame.text = (
            "Host Script: Read out the 4 tournament pillars clearly before starting Question 1. "
            "Remind teams that Star questions count for tie-breaks."
        )

        # -------------------------------------------------------------
        # PHASE 1: Questions Round (Slides 3 ... N+2)
        # -------------------------------------------------------------
        for idx, q in enumerate(approved_questions, start=1):
            s_q = prs.slides.add_slide(blank_layout)

            # High-contrast Pure White Canvas
            bg_q = s_q.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
            bg_q.fill.solid()
            bg_q.fill.fore_color.rgb = C_WHITE
            bg_q.line.fill.background()

            # Top Accent Line
            top_acc = s_q.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.08))
            top_acc.fill.solid()
            top_acc.fill.fore_color.rgb = C_NAVY_DARK
            top_acc.line.fill.background()

            # Star question determination (every 5th question is marked for tie-breaker)
            is_starred = (idx % 5 == 0)
            q_num_str = f"{idx}.*" if is_starred else f"{idx}."

            # Question Number
            tb_qnum = s_q.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(2.5), Inches(0.8))
            p_qn = tb_qnum.text_frame.paragraphs[0]
            p_qn.text = q_num_str
            p_qn.font.name = FONT_HEADING
            p_qn.font.size = Pt(36)
            p_qn.font.bold = True
            p_qn.font.color.rgb = C_NAVY_DARK

            # Category / Theme Badge Pill (Top Right)
            cat_text = _get_val(q, "topic") or topic_text
            if len(cat_text) > 24:
                cat_text = cat_text[:22] + ".."

            pill_w = Inches(3.2)
            pill_left = Inches(13.333 - 0.8 - 3.2)
            cat_pill = s_q.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, pill_left, Inches(0.45), pill_w, Inches(0.52))
            cat_pill.fill.solid()
            cat_pill.fill.fore_color.rgb = C_BLUE_100
            cat_pill.line.color.rgb = C_BLUE_600
            cat_pill.line.width = Pt(1.5)

            p_cp = cat_pill.text_frame.paragraphs[0]
            p_cp.text = cat_text.upper()
            p_cp.font.name = FONT_HEADING
            p_cp.font.size = Pt(13)
            p_cp.font.bold = True
            p_cp.font.color.rgb = C_BLUE_600
            p_cp.alignment = PP_ALIGN.CENTER

            # Audio Clue Indicator Pill if present
            q_aud = _get_val(q, "question_audio", []) or _get_val(q, "audio_refs", []) or []
            if q_aud:
                aud_pill = s_q.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, pill_left - Inches(2.2), Inches(0.45), Inches(2.0), Inches(0.52))
                aud_pill.fill.solid()
                aud_pill.fill.fore_color.rgb = C_AMBER_100
                aud_pill.line.color.rgb = C_AMBER_500
                aud_pill.line.width = Pt(1.5)
                p_ap = aud_pill.text_frame.paragraphs[0]
                p_ap.text = "[AUDIO CLUE]"
                p_ap.font.name = FONT_HEADING
                p_ap.font.size = Pt(11)
                p_ap.font.bold = True
                p_ap.font.color.rgb = C_AMBER_500
                p_ap.alignment = PP_ALIGN.CENTER

            # Resolve Clue Images
            q_imgs = _get_val(q, "question_images", []) or _get_val(q, "image_refs", []) or []
            resolved_imgs = [_resolve_image_path(img) for img in q_imgs]
            valid_imgs = [p for p in resolved_imgs if p is not None]

            q_text = _get_val(q, "question_text") or _get_val(q, "question", "")
            options = _get_val(q, "options", []) or []

            # Dynamic font sizing
            q_font_size = Pt(28) if len(q_text) < 160 else (Pt(24) if len(q_text) < 260 else Pt(20))

            if len(valid_imgs) == 1:
                # Layout A: Split 60/40 (Text on Left, Clue Image on Right)
                tb_qtext = s_q.shapes.add_textbox(Inches(0.8), Inches(1.5), Inches(6.8), Inches(3.2))
                tf_qt = tb_qtext.text_frame
                tf_qt.word_wrap = True
                p_qt = tf_qt.paragraphs[0]
                p_qt.text = q_text
                p_qt.font.name = FONT_PRIMARY
                p_qt.font.size = q_font_size
                p_qt.font.bold = True
                p_qt.font.color.rgb = C_NAVY_DARK

                if options and len(options) >= 2:
                    opt_top = Inches(4.8)
                    for opt_idx, opt in enumerate(options[:4]):
                        opt_y = opt_top + Inches(opt_idx * 0.45)
                        opt_card = s_q.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), opt_y, Inches(6.8), Inches(0.38))
                        opt_card.fill.solid()
                        opt_card.fill.fore_color.rgb = C_SLATE_100
                        opt_card.line.color.rgb = C_SLATE_200
                        opt_card.line.width = Pt(1)
                        p_opt = opt_card.text_frame.paragraphs[0]
                        p_opt.text = opt
                        p_opt.font.name = FONT_PRIMARY
                        p_opt.font.size = Pt(13)
                        p_opt.font.color.rgb = C_SLATE_800
                        opt_card.text_frame.margin_left = Inches(0.15)
                        opt_card.text_frame.margin_top = Inches(0.05)

                _add_scaled_picture(s_q, valid_imgs[0], Inches(8.0), Inches(1.5), Inches(4.5), Inches(5.0), border_color=C_SLATE_200)

            elif len(valid_imgs) >= 2:
                # Layout B: Multi-Image Question (2 Images side-by-side)
                tb_qtext = s_q.shapes.add_textbox(Inches(0.8), Inches(1.4), Inches(11.733), Inches(1.6))
                tf_qt = tb_qtext.text_frame
                tf_qt.word_wrap = True
                p_qt = tf_qt.paragraphs[0]
                p_qt.text = q_text
                p_qt.font.name = FONT_PRIMARY
                p_qt.font.size = Pt(24)
                p_qt.font.bold = True
                p_qt.font.color.rgb = C_NAVY_DARK

                _add_scaled_picture(s_q, valid_imgs[0], Inches(0.8), Inches(3.2), Inches(5.6), Inches(3.3), border_color=C_SLATE_200)
                _add_scaled_picture(s_q, valid_imgs[1], Inches(6.8), Inches(3.2), Inches(5.6), Inches(3.3), border_color=C_SLATE_200)

            else:
                # Layout C: Full-Width Text & 2x2 Option Grid
                tb_qtext = s_q.shapes.add_textbox(Inches(0.8), Inches(1.6), Inches(11.733), Inches(2.6))
                tf_qt = tb_qtext.text_frame
                tf_qt.word_wrap = True
                p_qt = tf_qt.paragraphs[0]
                p_qt.text = q_text
                p_qt.font.name = FONT_PRIMARY
                p_qt.font.size = Pt(30) if len(q_text) < 180 else Pt(25)
                p_qt.font.bold = True
                p_qt.font.color.rgb = C_NAVY_DARK

                if options and len(options) >= 2:
                    grid_coords = [
                        (Inches(0.8), Inches(4.5)),
                        (Inches(6.8), Inches(4.5)),
                        (Inches(0.8), Inches(5.4)),
                        (Inches(6.8), Inches(5.4)),
                    ]
                    for opt_idx, opt in enumerate(options[:4]):
                        gx, gy = grid_coords[opt_idx]
                        opt_card = s_q.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, gx, gy, Inches(5.7), Inches(0.7))
                        opt_card.fill.solid()
                        opt_card.fill.fore_color.rgb = C_SLATE_50
                        opt_card.line.color.rgb = C_SLATE_200
                        opt_card.line.width = Pt(1)
                        p_opt = opt_card.text_frame.paragraphs[0]
                        p_opt.text = opt
                        p_opt.font.name = FONT_PRIMARY
                        p_opt.font.size = Pt(15)
                        p_opt.font.color.rgb = C_SLATE_800
                        opt_card.text_frame.margin_left = Inches(0.2)
                        opt_card.text_frame.margin_top = Inches(0.12)

            # Footer
            tb_qfoot = s_q.shapes.add_textbox(Inches(0.8), Inches(6.8), Inches(11.733), Inches(0.4))
            p_qf = tb_qfoot.text_frame.paragraphs[0]
            star_foot = "  [★ STAR TIE-BREAKER QUESTION]" if is_starred else ""
            p_qf.text = f"QShala Tournament Intelligence  •  Question {idx} of {total_q}{star_foot}"
            p_qf.font.name = FONT_PRIMARY
            p_qf.font.size = Pt(10)
            p_qf.font.color.rgb = C_SLATE_500

            # Speaker Notes
            host_clues = []
            if is_starred:
                host_clues.append("★ IMPORTANT: Announce to teams that this is a Star tie-breaker question!")
            if q_aud:
                host_clues.append(f"🎧 AUDIO CLUE: Play audio clip '{q_aud[0]}' before taking submissions.")
            ans_str = _get_val(q, "answer", "N/A")
            host_clues.append(f"Answer: {ans_str}")
            s_q.notes_slide.notes_text_frame.text = "\n".join(host_clues)

        # -------------------------------------------------------------
        # PHASE 2: Intermission / Transition Divider Slide
        # -------------------------------------------------------------
        s_pause = prs.slides.add_slide(blank_layout)
        bg_p = s_pause.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg_p.fill.solid()
        bg_p.fill.fore_color.rgb = C_NAVY_DARK
        bg_p.line.fill.background()

        p_ribbon = s_pause.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4.666), Inches(1.8), Inches(4.0), Inches(0.08))
        p_ribbon.fill.solid()
        p_ribbon.fill.fore_color.rgb = C_AMBER_500
        p_ribbon.line.fill.background()

        tb_pause = s_pause.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.333), Inches(3.2))
        tf_p = tb_pause.text_frame
        tf_p.word_wrap = True

        p_p1 = tf_p.paragraphs[0]
        p_p1.text = "PLEASE HAND IN YOUR SHEETS"
        p_p1.font.name = FONT_HEADING
        p_p1.font.size = Pt(46)
        p_p1.font.bold = True
        p_p1.font.color.rgb = C_WHITE
        p_p1.alignment = PP_ALIGN.CENTER

        p_p2 = tf_p.add_paragraph()
        p_p2.space_before = Pt(20)
        p_p2.text = "PRELIM ANSWERS WILL BE ANNOUNCED SOON!"
        p_p2.font.name = FONT_HEADING
        p_p2.font.size = Pt(32)
        p_p2.font.bold = True
        p_p2.font.color.rgb = C_AMBER_500
        p_p2.alignment = PP_ALIGN.CENTER

        p_p3 = tf_p.add_paragraph()
        p_p3.space_before = Pt(16)
        p_p3.text = "LET'S DISCUSS THE ANSWERS & REVEAL THE SOLUTIONS"
        p_p3.font.name = FONT_PRIMARY
        p_p3.font.size = Pt(18)
        p_p3.font.color.rgb = C_SLATE_400
        p_p3.alignment = PP_ALIGN.CENTER

        s_pause.notes_slide.notes_text_frame.text = (
            "Host Script: Instruct proctors to collect answer sheets from all teams. "
            "Allow 2 minutes for score collection, then proceed to the answers walkthrough."
        )

        # -------------------------------------------------------------
        # PHASE 3: Answer Reveal Walkthrough
        # -------------------------------------------------------------
        for idx, q in enumerate(approved_questions, start=1):
            # 1. Suspense / Dramatic Pause Slide ("ANSWER")
            s_ans_suspense = prs.slides.add_slide(blank_layout)
            bg_as = s_ans_suspense.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
            bg_as.fill.solid()
            bg_as.fill.fore_color.rgb = C_NAVY_DARK
            bg_as.line.fill.background()

            tb_sus_tag = s_ans_suspense.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.333), Inches(0.6))
            p_stag = tb_sus_tag.text_frame.paragraphs[0]
            p_stag.text = f"QUESTION {idx} OF {total_q}"
            p_stag.font.name = FONT_HEADING
            p_stag.font.size = Pt(16)
            p_stag.font.bold = True
            p_stag.font.color.rgb = C_AMBER_500
            p_stag.alignment = PP_ALIGN.CENTER

            tb_sus = s_ans_suspense.shapes.add_textbox(Inches(1.0), Inches(2.8), Inches(11.333), Inches(1.8))
            p_sus = tb_sus.text_frame.paragraphs[0]
            p_sus.text = "ANSWER"
            p_sus.font.name = FONT_HEADING
            p_sus.font.size = Pt(54)
            p_sus.font.bold = True
            p_sus.font.color.rgb = C_WHITE
            p_sus.alignment = PP_ALIGN.CENTER

            # 2. Answer Reveal Slide
            s_a = prs.slides.add_slide(blank_layout)
            bg_a = s_a.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
            bg_a.fill.solid()
            bg_a.fill.fore_color.rgb = C_WHITE
            bg_a.line.fill.background()

            acc_a = s_a.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.12))
            acc_a.fill.solid()
            acc_a.fill.fore_color.rgb = C_EMERALD_600
            acc_a.line.fill.background()

            badge_a = s_a.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.4), Inches(2.4), Inches(0.48))
            badge_a.fill.solid()
            badge_a.fill.fore_color.rgb = C_EMERALD_50
            badge_a.line.color.rgb = C_EMERALD_600
            badge_a.line.width = Pt(1.5)
            p_ba = badge_a.text_frame.paragraphs[0]
            p_ba.text = f"ANSWER {idx}"
            p_ba.font.name = FONT_HEADING
            p_ba.font.size = Pt(13)
            p_ba.font.bold = True
            p_ba.font.color.rgb = C_EMERALD_600
            p_ba.alignment = PP_ALIGN.CENTER

            ans_imgs = _get_val(q, "answer_images", []) or []
            ans_resolved = [_resolve_image_path(img) for img in ans_imgs]
            valid_ans_imgs = [p for p in ans_resolved if p is not None]
            if not valid_ans_imgs and valid_imgs:
                valid_ans_imgs = valid_imgs

            ans_val = _get_val(q, "answer", "N/A")
            explanation = _get_val(q, "explanation", "")

            if personality == "DETECTIVE_PUZZLER":
                exp_header = "THE DEDUCTION & SOLUTION"
            elif personality == "TOURNAMENT_PRO":
                exp_header = "OFFICIAL TOURNAMENT RATIONALE"
            elif personality == "SOCRATIC_EXPLORER":
                exp_header = "CONCEPT BREAKDOWN & DISCUSSION"
            else:
                exp_header = "THE STORY BEHIND THE ANSWER"

            if valid_ans_imgs:
                # Answer + Story Card on Left, Confirmation Media on Right
                tb_ans = s_a.shapes.add_textbox(Inches(0.8), Inches(1.05), Inches(6.8), Inches(1.3))
                tf_ans = tb_ans.text_frame
                tf_ans.word_wrap = True
                p_av = tf_ans.paragraphs[0]
                p_av.text = ans_val
                p_av.font.name = FONT_HEADING
                p_av.font.size = Pt(36) if len(ans_val) < 40 else Pt(28)
                p_av.font.bold = True
                p_av.font.color.rgb = C_EMERALD_600

                if explanation:
                    exp_card = s_a.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(2.45), Inches(6.8), Inches(3.9))
                    exp_card.fill.solid()
                    exp_card.fill.fore_color.rgb = C_SLATE_50
                    exp_card.line.color.rgb = C_SLATE_200
                    exp_card.line.width = Pt(1)

                    tf_ec = exp_card.text_frame
                    tf_ec.word_wrap = True
                    tf_ec.margin_left = Inches(0.3)
                    tf_ec.margin_top = Inches(0.25)
                    tf_ec.margin_right = Inches(0.3)

                    p_eh = tf_ec.paragraphs[0]
                    p_eh.text = exp_header
                    p_eh.font.name = FONT_HEADING
                    p_eh.font.size = Pt(13)
                    p_eh.font.bold = True
                    p_eh.font.color.rgb = C_BLUE_600

                    p_eb = tf_ec.add_paragraph()
                    p_eb.space_before = Pt(8)
                    p_eb.text = explanation
                    p_eb.font.name = FONT_PRIMARY
                    p_eb.font.size = Pt(14)
                    p_eb.font.color.rgb = C_SLATE_700

                _add_scaled_picture(s_a, valid_ans_imgs[0], Inches(8.0), Inches(1.3), Inches(4.5), Inches(5.1), border_color=C_SLATE_200)

            else:
                # Full Width Answer & Story Card
                tb_ans = s_a.shapes.add_textbox(Inches(0.8), Inches(1.1), Inches(11.733), Inches(1.4))
                tf_ans = tb_ans.text_frame
                tf_ans.word_wrap = True
                p_av = tf_ans.paragraphs[0]
                p_av.text = ans_val
                p_av.font.name = FONT_HEADING
                p_av.font.size = Pt(40) if len(ans_val) < 40 else Pt(32)
                p_av.font.bold = True
                p_av.font.color.rgb = C_EMERALD_600

                if explanation:
                    exp_card = s_a.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(2.6), Inches(11.733), Inches(3.8))
                    exp_card.fill.solid()
                    exp_card.fill.fore_color.rgb = C_SLATE_50
                    exp_card.line.color.rgb = C_SLATE_200
                    exp_card.line.width = Pt(1)

                    tf_ec = exp_card.text_frame
                    tf_ec.word_wrap = True
                    tf_ec.margin_left = Inches(0.35)
                    tf_ec.margin_top = Inches(0.3)
                    tf_ec.margin_right = Inches(0.35)

                    p_eh = tf_ec.paragraphs[0]
                    p_eh.text = exp_header
                    p_eh.font.name = FONT_HEADING
                    p_eh.font.size = Pt(14)
                    p_eh.font.bold = True
                    p_eh.font.color.rgb = C_BLUE_600

                    p_eb = tf_ec.add_paragraph()
                    p_eb.space_before = Pt(10)
                    p_eb.text = explanation
                    p_eb.font.name = FONT_PRIMARY
                    p_eb.font.size = Pt(16)
                    p_eb.font.color.rgb = C_SLATE_700

            # Footer Provenance Note
            sources = _get_val(q, "retrieval_sources", []) or _get_val(q, "sources", [])
            src_info = "QShala Curated Vault"
            if sources:
                src = sources[0]
                doc_title = _get_val(src, "document_title") or "Tournament Archive"
                slide_num = _get_val(src, "slide_number") or "N/A"
                src_info = f"{doc_title} (Slide {slide_num})"

            tb_afoot = s_a.shapes.add_textbox(Inches(0.8), Inches(6.8), Inches(11.733), Inches(0.4))
            p_af = tb_afoot.text_frame.paragraphs[0]
            p_af.text = f"Source Provenance: {src_info}  •  Scoring: +10 Points"
            p_af.font.name = FONT_PRIMARY
            p_af.font.size = Pt(10)
            p_af.font.color.rgb = C_SLATE_500

            s_a.notes_slide.notes_text_frame.text = (
                f"Host Talking Points:\n"
                f"Official Answer: {ans_val}\n"
                f"Award +10 points to any team with the correct answer (or verified equivalent).\n"
                f"Story/Trivia: {explanation}"
            )

        # -------------------------------------------------------------
        # SLIDE FINAL: Tournament Culmination
        # -------------------------------------------------------------
        s_end = prs.slides.add_slide(blank_layout)
        bg_end = s_end.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg_end.fill.solid()
        bg_end.fill.fore_color.rgb = C_NAVY_DARK
        bg_end.line.fill.background()

        tb_end = s_end.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.333), Inches(3.0))
        tf_e = tb_end.text_frame
        tf_e.word_wrap = True

        p_e1 = tf_e.paragraphs[0]
        p_e1.text = "Quiz Complete!"
        p_e1.font.name = FONT_HEADING
        p_e1.font.size = Pt(48)
        p_e1.font.bold = True
        p_e1.font.color.rgb = C_WHITE
        p_e1.alignment = PP_ALIGN.CENTER

        p_e2 = tf_e.add_paragraph()
        p_e2.space_before = Pt(14)
        p_e2.text = f"Compiled {total_q} questions across {topic_text}"
        p_e2.font.name = FONT_PRIMARY
        p_e2.font.size = Pt(22)
        p_e2.font.color.rgb = C_SLATE_400
        p_e2.alignment = PP_ALIGN.CENTER

        p_e3 = tf_e.add_paragraph()
        p_e3.space_before = Pt(24)
        p_e3.text = "Curiosity • Learning • Intelligence — Powered by QShala"
        p_e3.font.name = FONT_HEADING
        p_e3.font.size = Pt(15)
        p_e3.font.bold = True
        p_e3.font.color.rgb = C_EMERALD_500
        p_e3.alignment = PP_ALIGN.CENTER

        buffer = io.BytesIO()
        prs.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
