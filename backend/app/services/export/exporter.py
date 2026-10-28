import re
import csv
import io
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from PIL import Image

logger = logging.getLogger(__name__)

def _resolve_media_path(rel_url: Optional[str]) -> Optional[Path]:
    """Resolves local filesystem paths for images, audio, and video files."""
    if not rel_url or not isinstance(rel_url, str):
        return None
    from backend.app.config import settings
    clean_url = rel_url.strip()
    
    # 1. Slide extracts directory (/static/slides/...)
    if clean_url.startswith("/static/slides/"):
        sub = clean_url[len("/static/slides/"):]
        p = settings.SLIDES_DIR / sub
        if p.exists() and p.is_file():
            return p
    # 2. Storage directory general (/static/...)
    elif clean_url.startswith("/static/"):
        sub = clean_url.lstrip("/static/")
        p = settings.STORAGE_DIR / sub
        if p.exists() and p.is_file():
            return p
            
    # 3. Public media videos directory (/media/videos/...)
    if clean_url.startswith("/media/videos/") or clean_url.startswith("media/videos/"):
        name = Path(clean_url).name
        p = Path("frontend/public/media/videos") / name
        if p.exists() and p.is_file():
            return p
    elif clean_url.startswith("/media/") or clean_url.startswith("media/"):
        name = Path(clean_url).name
        p = Path("frontend/public/media") / name
        if p.exists() and p.is_file():
            return p

    # 4. Direct filesystem path
    p_direct = Path(clean_url)
    if p_direct.exists() and p_direct.is_file():
        return p_direct
        
    # 5. Storage uploads directory check
    p_upload = settings.STORAGE_DIR / "uploads" / Path(clean_url).name
    if p_upload.exists() and p_upload.is_file():
        return p_upload
        
    # 6. Check within slides directory recursively by filename if needed
    filename = Path(clean_url).name
    if filename:
        matches = list(settings.SLIDES_DIR.glob(f"**/{filename}"))
        if matches and matches[0].is_file():
            return matches[0]

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

def _get_hist_q_media(q: Any) -> Dict[str, Any]:
    """Helper to retrieve raw media, audio, and videos from the source vault question if available."""
    sources = _get_val(q, "retrieval_sources", []) or _get_val(q, "sources", [])
    if not sources:
        return {}
    hist_id = _get_val(sources[0], "historical_question_id")
    if not hist_id:
        return {}
    try:
        from backend.app.database import SessionLocal
        from backend.app.models.question import Question
        db = SessionLocal()
        hq = db.query(Question).filter(Question.id == hist_id).first()
        if not hq:
            db.close()
            return {}
        res = {
            "raw_media_refs": list(getattr(hq, "raw_media_refs", []) or []),
            "question_audio": list(getattr(hq, "question_audio", []) or []),
            "audio_refs": list(getattr(hq, "audio_refs", []) or []),
            "question_images": list(getattr(hq, "question_images", []) or []),
            "answer_images": list(getattr(hq, "answer_images", []) or []),
            "image_refs": list(getattr(hq, "image_refs", []) or []),
        }
        db.close()
        return res
    except Exception as e:
        logger.warning(f"Error fetching historical question media: {e}")
        return {}

def _clean_quiz_title(raw_title: str, topic: str) -> str:
    """Sanitizes raw prompt text into a clean presentation title."""
    if not raw_title or raw_title.lower() in ("qshala tournament quiz", "custom", "untitled quiz"):
        return f"{topic.title()} Quiz" if topic else "Bengaluru South Zone"
    t = raw_title.strip()
    prompt_patterns = [
        r"^(?:give\s+me|generate|create|make|pull)\s+\d*\s*",
        r"\s*(?:and\s+make\s+a\s+quiz|and\s+create\s+a\s+quiz|make\s+a\s+quiz|create\s+a\s+quiz|quiz\s+please|for\s+school|without\s+images?|text\s+only).*$",
        r"^questions?\s+(?:on|about|for)\s+",
    ]
    cleaned = t
    for pat in prompt_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned and len(cleaned) > 2 and cleaned.lower() != t.lower():
        return f"{cleaned.title()} Quiz"
    return t

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
                "video_refs": _get_val(q, "video_refs", []) or [],
                "question_video": _get_val(q, "question_video", []) or [],
                "raw_media_refs": _get_val(q, "raw_media_refs", []) or [],
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
    def to_pptx(
        quiz: Any,
        theme: str = "bengaluru_south",
        custom_title: Optional[str] = None,
        custom_subtitle: Optional[str] = None,
        include_social_slides: bool = True,
        show_answer_divider: bool = False,
    ) -> bytes:
        """
        Exports the quiz into a crisp, high-typography presentation deck (16:9 widescreen)
        modeled directly after the Bengaluru South Zone tournament deck.
        
        Properly embeds all media types:
        1. High-resolution images (proportional PIL scaling without distortion)
        2. Videos (embedded directly into PowerPoint slides via add_movie with poster frames)
        3. Audio clues (embedded into slides with clean interactive sound effect cards)
        4. Authentic Social Media & QR slides (Slides 2 & 3)
        5. Beautiful question & answer typography in Inter font with high contrast
        """
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank_layout = prs.slide_layouts[6]

        # -------------------------------------------------------------
        # Theme Assets & Color Palette (Bengaluru South or Minimalist)
        # -------------------------------------------------------------
        assets_dir = Path(__file__).resolve().parent / "templates" / "assets"
        title_bg = assets_dir / "title_bg.png"
        question_bg = assets_dir / "question_bg.png"
        answer_bg = assets_dir / "answer_bg.png"
        round_bg = assets_dir / "round_bg.png"
        answer_intro_bg = assets_dir / "answer_intro_bg.png"
        qr_varsity = assets_dir / "qr_varsity.png"
        qr_insta = assets_dir / "qr_instagram.jpg"
        qr_wa = assets_dir / "qr_whatsapp.jpg"

        use_bengaluru_theme = (theme == "bengaluru_south" and question_bg.exists())

        C_WHITE = RGBColor(255, 255, 255)
        if use_bengaluru_theme:
            # Bengaluru South Zone theme uses clean white interior card (255, 255, 255)
            C_DARK_BG = RGBColor(15, 23, 42)          # #0F172A Slate 900
            C_TEXT_DARK = RGBColor(15, 23, 42)        # #0F172A Deep Charcoal / Black
            C_TEXT_BODY = RGBColor(51, 65, 85)        # #334155 Slate 700
            C_TEXT_MUTED = RGBColor(100, 116, 139)    # #64748B Slate 500
            C_ACCENT_ORANGE = RGBColor(194, 65, 12)   # #C2410C Tournament Burnt Orange
            C_ACCENT_GREEN = RGBColor(5, 150, 105)    # #059669 Emerald 600
            C_ACCENT_GOLD = RGBColor(217, 119, 6)     # #D97706 Amber 600
            C_CARD_BG = RGBColor(248, 250, 252)       # Slate 50
            C_CARD_BORDER = RGBColor(226, 232, 240)   # Slate 200
        else:
            C_DARK_BG = RGBColor(15, 23, 42)          # #0F172A Slate 900
            C_TEXT_DARK = RGBColor(15, 23, 42)        # #0F172A Deep Charcoal
            C_TEXT_BODY = RGBColor(51, 65, 85)        # #334155 Slate 700
            C_TEXT_MUTED = RGBColor(100, 116, 139)    # #64748B Slate 500
            C_ACCENT_ORANGE = RGBColor(194, 65, 12)
            C_ACCENT_GREEN = RGBColor(5, 150, 105)    # #059669 Emerald 600
            C_ACCENT_GOLD = RGBColor(217, 119, 6)     # #D97706 Amber 600
            C_CARD_BG = RGBColor(241, 245, 249)       # #F1F5F9 Slate 100
            C_CARD_BORDER = RGBColor(203, 213, 225)   # #CBD5E1 Slate 300

        FONT_HEAD = "Inter"
        FONT_BODY = "Inter"

        raw_title = _get_val(quiz, "title", "")
        topic_text = _get_val(quiz, "topic", "General Knowledge")
        difficulty = _get_val(quiz, "difficulty", "Balanced")

        if custom_title and custom_title.strip():
            final_title = custom_title.strip()
        else:
            final_title = _clean_quiz_title(raw_title, topic_text)

        if custom_subtitle and custom_subtitle.strip():
            final_subtitle = custom_subtitle.strip()
        else:
            final_subtitle = "Preliminary Round Questions & Answers"

        questions_raw = _get_val(quiz, "questions", [])
        approved_questions = [q for q in questions_raw if _get_val(q, "is_approved", True)]
        total_q = len(approved_questions)

        # -------------------------------------------------------------
        # 1. Clean Title Slide (High Contrast, Centered in Lower Half)
        # -------------------------------------------------------------
        s_title = prs.slides.add_slide(blank_layout)
        if use_bengaluru_theme and title_bg.exists():
            s_title.shapes.add_picture(str(title_bg), 0, 0, Inches(13.333), Inches(7.5))
            tb_title = s_title.shapes.add_textbox(Inches(2.0), Inches(4.80), Inches(9.333), Inches(2.20))
            tf_title = tb_title.text_frame
            tf_title.word_wrap = True

            p_h1 = tf_title.paragraphs[0]
            p_h1.alignment = PP_ALIGN.CENTER
            p_h1.text = final_title
            p_h1.font.name = FONT_HEAD
            p_h1.font.size = Pt(38)
            p_h1.font.bold = True
            p_h1.font.color.rgb = C_TEXT_DARK

            p_sub = tf_title.add_paragraph()
            p_sub.alignment = PP_ALIGN.CENTER
            p_sub.space_before = Pt(8)
            p_sub.text = final_subtitle
            p_sub.font.name = FONT_HEAD
            p_sub.font.size = Pt(24)
            p_sub.font.bold = True
            p_sub.font.color.rgb = C_ACCENT_ORANGE
        else:
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
            p_h1.text = final_title
            p_h1.font.name = FONT_HEAD
            p_h1.font.size = Pt(46)
            p_h1.font.bold = True
            p_h1.font.color.rgb = C_WHITE

            p_sub = tf_title.add_paragraph()
            p_sub.space_before = Pt(16)
            p_sub.text = f"{final_subtitle}   •   {total_q} Questions   •   Difficulty: {difficulty}"
            p_sub.font.name = FONT_BODY
            p_sub.font.size = Pt(19)
            p_sub.font.color.rgb = RGBColor(148, 163, 184)

        s_title.notes_slide.notes_text_frame.text = (
            f"Host Welcome Note:\n"
            f"Tournament: {final_title}\n"
            f"Round: {final_subtitle}\n"
            f"Total Questions: {total_q}\n"
            f"Welcome teams and ensure score sheets are distributed."
        )

        # -------------------------------------------------------------
        # 2. Authentic Social Media & QR Slides (Slides 2 & 3)
        # -------------------------------------------------------------
        if use_bengaluru_theme and include_social_slides:
            # Slide 2: Social Media Guidelines
            s_soc = prs.slides.add_slide(blank_layout)
            s_soc.shapes.add_picture(str(question_bg), 0, 0, Inches(13.333), Inches(7.5))

            tb_stitle = s_soc.shapes.add_textbox(Inches(2.0), Inches(1.35), Inches(9.333), Inches(1.10))
            pst = tb_stitle.text_frame.paragraphs[0]
            pst.alignment = PP_ALIGN.CENTER
            pst.text = "Social Media"
            pst.font.name = FONT_HEAD
            pst.font.size = Pt(40)
            pst.font.bold = True
            pst.font.color.rgb = C_TEXT_DARK

            tb_sbody = s_soc.shapes.add_textbox(Inches(1.20), Inches(2.55), Inches(10.933), Inches(4.30))
            tf_sb = tb_sbody.text_frame
            tf_sb.word_wrap = True

            p1 = tf_sb.paragraphs[0]
            p1.alignment = PP_ALIGN.CENTER
            p1.text = "Share your experience of the quiz • Use #varsityquiz and tag @zerodhavarsity"
            p1.font.name = FONT_BODY
            p1.font.size = Pt(28)
            p1.font.bold = True
            p1.font.color.rgb = C_TEXT_DARK

            p2 = tf_sb.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            p2.space_before = Pt(24)
            p2.text = "And send the link of your post on the WhatsApp participants group"
            p2.font.name = FONT_BODY
            p2.font.size = Pt(28)
            p2.font.bold = True
            p2.font.color.rgb = C_TEXT_DARK

            p3 = tf_sb.add_paragraph()
            p3.alignment = PP_ALIGN.CENTER
            p3.space_before = Pt(24)
            p3.text = "Win goodie bags!"
            p3.font.name = FONT_BODY
            p3.font.size = Pt(28)
            p3.font.bold = True
            p3.font.color.rgb = C_TEXT_DARK

            # Slide 3: QR Codes (Follow @Zerodhavarsity)
            s_qr = prs.slides.add_slide(blank_layout)
            s_qr.shapes.add_picture(str(question_bg), 0, 0, Inches(13.333), Inches(7.5))

            tb_qrtitle = s_qr.shapes.add_textbox(Inches(1.0), Inches(1.30), Inches(11.333), Inches(1.30))
            pqt = tb_qrtitle.text_frame.paragraphs[0]
            pqt.alignment = PP_ALIGN.CENTER
            pqt.text = "Get Curious & Stay Curious\nFollow @Zerodhavarsity"
            pqt.font.name = FONT_HEAD
            pqt.font.size = Pt(32)
            pqt.font.bold = True
            pqt.font.color.rgb = C_TEXT_DARK

            if qr_varsity.exists():
                s_qr.shapes.add_picture(str(qr_varsity), Inches(1.50), Inches(2.95), Inches(3.30), Inches(3.30))
            if qr_insta.exists():
                s_qr.shapes.add_picture(str(qr_insta), Inches(5.05), Inches(2.95), Inches(3.30), Inches(3.30))
            if qr_wa.exists():
                s_qr.shapes.add_picture(str(qr_wa), Inches(8.60), Inches(2.95), Inches(3.30), Inches(3.30))

            # Slide 4: Round Divider
            if round_bg.exists():
                s_rnd = prs.slides.add_slide(blank_layout)
                s_rnd.shapes.add_picture(str(round_bg), 0, 0, Inches(13.333), Inches(7.5))
                tb_rnd = s_rnd.shapes.add_textbox(Inches(2.0), Inches(4.80), Inches(9.333), Inches(2.00))
                prt = tb_rnd.text_frame.paragraphs[0]
                prt.alignment = PP_ALIGN.CENTER
                prt.text = final_title
                prt.font.name = FONT_HEAD
                prt.font.size = Pt(38)
                prt.font.bold = True
                prt.font.color.rgb = C_TEXT_DARK

                prs_sub = tb_rnd.text_frame.add_paragraph()
                prs_sub.alignment = PP_ALIGN.CENTER
                prs_sub.space_before = Pt(8)
                prs_sub.text = final_subtitle
                prs_sub.font.name = FONT_HEAD
                prs_sub.font.size = Pt(24)
                prs_sub.font.bold = True
                prs_sub.font.color.rgb = C_ACCENT_ORANGE

        # -------------------------------------------------------------
        # 3. Question & Answer Slides
        # -------------------------------------------------------------
        for idx, q in enumerate(approved_questions, start=1):
            is_starred = (idx % 5 == 0)
            star_tag = " *" if is_starred else ""

            # Check historical source media fallback
            hist_media = _get_hist_q_media(q)

            # --- VIDEO DETECTION ---
            cand_videos = (
                list(_get_val(q, "question_video", []) or []) +
                list(_get_val(q, "video_refs", []) or []) +
                list(_get_val(q, "raw_media_refs", []) or []) +
                list(_get_val(q, "image_refs", []) or []) +
                list(hist_media.get("raw_media_refs", []) or [])
            )
            video_path = None
            for cv in cand_videos:
                if isinstance(cv, str) and cv.lower().endswith(('.mp4', '.m4v', '.mov', '.webm')):
                    p = _resolve_media_path(cv)
                    if p and p.exists():
                        video_path = p
                        break

            # --- AUDIO DETECTION ---
            cand_audios = (
                list(_get_val(q, "question_audio", []) or []) +
                list(_get_val(q, "audio_refs", []) or []) +
                list(_get_val(q, "raw_media_refs", []) or []) +
                list(hist_media.get("question_audio", []) or []) +
                list(hist_media.get("audio_refs", []) or []) +
                list(hist_media.get("raw_media_refs", []) or [])
            )
            audio_path = None
            for ca in cand_audios:
                if isinstance(ca, str) and ca.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg')):
                    p = _resolve_media_path(ca)
                    if p and p.exists():
                        audio_path = p
                        break

            # --- IMAGE DETECTION ---
            cand_q_imgs = (
                list(_get_val(q, "question_images", []) or []) +
                list(_get_val(q, "image_refs", []) or []) +
                list(hist_media.get("question_images", []) or []) +
                list(hist_media.get("image_refs", []) or [])
            )
            resolved_q_imgs = []
            for ci in cand_q_imgs:
                if isinstance(ci, str) and not ci.lower().endswith(('.mp4', '.m4v', '.mov', '.mp3', '.wav')):
                    p = _resolve_media_path(ci)
                    if p and p.exists() and p not in resolved_q_imgs:
                        resolved_q_imgs.append(p)

            poster_path = resolved_q_imgs[0] if resolved_q_imgs else None
            q_text = (_get_val(q, "question_text") or _get_val(q, "question", "")).strip()
            options = _get_val(q, "options", []) or []

            # ---------------------------------------------------------
            # (A) QUESTION SLIDE
            # ---------------------------------------------------------
            sq = prs.slides.add_slide(blank_layout)
            if use_bengaluru_theme and question_bg.exists():
                sq.shapes.add_picture(str(question_bg), 0, 0, Inches(13.333), Inches(7.5))
                # Top number badge slot matching the original template
                tb_num = sq.shapes.add_textbox(Inches(6.67), Inches(0.40), Inches(4.13), Inches(1.08))
                pn = tb_num.text_frame.paragraphs[0]
                pn.text = f"{idx}."
                pn.alignment = PP_ALIGN.CENTER
                pn.font.name = FONT_HEAD
                pn.font.size = Pt(40)
                pn.font.bold = True
                pn.font.color.rgb = C_TEXT_DARK
            else:
                bg_q = sq.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
                bg_q.fill.solid()
                bg_q.fill.fore_color.rgb = C_WHITE
                bg_q.line.fill.background()
                tb_num = sq.shapes.add_textbox(Inches(10.2), Inches(0.4), Inches(2.4), Inches(0.9))
                pn = tb_num.text_frame.paragraphs[0]
                pn.text = f"{idx}."
                pn.alignment = PP_ALIGN.RIGHT
                pn.font.name = FONT_HEAD
                pn.font.size = Pt(44)
                pn.font.bold = True
                pn.font.color.rgb = C_TEXT_DARK

            has_media = bool(video_path or audio_path or resolved_q_imgs)

            if has_media:
                # 2-Column Multimodal Layout: Question text left, Media right
                tb_q = sq.shapes.add_textbox(Inches(0.80), Inches(1.50), Inches(7.80), Inches(4.80))
                tf_q = tb_q.text_frame
                tf_q.word_wrap = True

                pq_main = tf_q.paragraphs[0]
                pq_main.text = q_text
                pq_main.font.name = FONT_HEAD
                pq_main.font.size = Pt(28) if len(q_text) < 160 else (Pt(24) if len(q_text) < 240 else Pt(20))
                pq_main.font.bold = True
                pq_main.font.color.rgb = C_TEXT_DARK

                if options:
                    for opt_idx, opt in enumerate(options):
                        po = tf_q.add_paragraph()
                        po.space_before = Pt(8)
                        prefix = f"{chr(65 + opt_idx)}.  " if opt_idx < 26 and not opt.startswith(('A.', 'B.', 'C.', 'D.')) else ""
                        po.text = f"{prefix}{opt}"
                        po.font.name = FONT_BODY
                        po.font.size = Pt(18)
                        po.font.color.rgb = C_TEXT_BODY

                # Media Placement on Right Side
                if video_path:
                    sq.shapes.add_movie(
                        str(video_path),
                        Inches(8.80), Inches(1.50), Inches(3.90), Inches(4.80),
                        poster_frame_image=str(poster_path) if poster_path else None,
                        mime_type="video/mp4"
                    )
                elif audio_path:
                    card = sq.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.80), Inches(1.80), Inches(3.80), Inches(3.60))
                    card.fill.solid()
                    card.fill.fore_color.rgb = C_CARD_BG
                    card.line.color.rgb = C_CARD_BORDER
                    card.line.width = Pt(1)

                    tf_c = card.text_frame
                    tf_c.word_wrap = True
                    p_c1 = tf_c.paragraphs[0]
                    p_c1.text = "🎧 AUDIO CLUE"
                    p_c1.font.name = FONT_HEAD
                    p_c1.font.size = Pt(16)
                    p_c1.font.bold = True
                    p_c1.font.color.rgb = C_ACCENT_GOLD
                    p_c1.alignment = PP_ALIGN.CENTER

                    p_c2 = tf_c.add_paragraph()
                    p_c2.space_before = Pt(14)
                    p_c2.text = "Click below to play audio sound clip:"
                    p_c2.font.name = FONT_BODY
                    p_c2.font.size = Pt(14)
                    p_c2.font.color.rgb = C_TEXT_MUTED
                    p_c2.alignment = PP_ALIGN.CENTER

                    sq.shapes.add_movie(
                        str(audio_path),
                        Inches(10.20), Inches(3.40), Inches(1.00), Inches(1.00),
                        poster_frame_image=str(poster_path) if poster_path else None,
                        mime_type="audio/mpeg"
                    )
                elif resolved_q_imgs:
                    _add_scaled_picture(sq, resolved_q_imgs[0], Inches(8.80), Inches(1.50), Inches(3.90), Inches(4.80))
            else:
                # Full Width Layout (Text Only)
                tb_q = sq.shapes.add_textbox(Inches(0.80), Inches(1.60), Inches(11.70), Inches(4.80))
                tf_q = tb_q.text_frame
                tf_q.word_wrap = True

                pq_main = tf_q.paragraphs[0]
                pq_main.text = q_text
                pq_main.font.name = FONT_HEAD
                pq_main.font.size = Pt(32) if len(q_text) < 160 else (Pt(26) if len(q_text) < 260 else Pt(22))
                pq_main.font.bold = True
                pq_main.font.color.rgb = C_TEXT_DARK

                if options:
                    for opt_idx, opt in enumerate(options):
                        po = tf_q.add_paragraph()
                        po.space_before = Pt(12)
                        prefix = f"{chr(65 + opt_idx)}.  " if opt_idx < 26 and not opt.startswith(('A.', 'B.', 'C.', 'D.')) else ""
                        po.text = f"{prefix}{opt}"
                        po.font.name = FONT_BODY
                        po.font.size = Pt(20)
                        po.font.color.rgb = C_TEXT_BODY

            # Speaker Notes
            host_notes = []
            if is_starred:
                host_notes.append("★ Important: Star tie-breaker question!")
            ans_val = (_get_val(q, "answer") or "N/A").strip()
            host_notes.append(f"Official Answer: {ans_val}")
            if video_path:
                host_notes.append(f"Video clue: {video_path.name}")
            elif audio_path:
                host_notes.append(f"Audio clue: {audio_path.name}")
            sq.notes_slide.notes_text_frame.text = "\n".join(host_notes)

            # ---------------------------------------------------------
            # (B) OPTIONAL ANSWER TRANSITION SLIDE
            # ---------------------------------------------------------
            if show_answer_divider and answer_intro_bg.exists():
                s_ai = prs.slides.add_slide(blank_layout)
                s_ai.shapes.add_picture(str(answer_intro_bg), 0, 0, Inches(13.333), Inches(7.5))
                tb_ai = s_ai.shapes.add_textbox(Inches(4.00), Inches(2.75), Inches(5.333), Inches(1.90))
                pai = tb_ai.text_frame.paragraphs[0]
                pai.alignment = PP_ALIGN.CENTER
                pai.text = "Answer"
                pai.font.name = FONT_HEAD
                pai.font.size = Pt(50)
                pai.font.bold = True
                pai.font.color.rgb = C_TEXT_DARK

            # ---------------------------------------------------------
            # (C) ANSWER REVEAL SLIDE
            # ---------------------------------------------------------
            sa = prs.slides.add_slide(blank_layout)
            if use_bengaluru_theme and answer_bg.exists():
                sa.shapes.add_picture(str(answer_bg), 0, 0, Inches(13.333), Inches(7.5))
            else:
                bg_a = sa.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
                bg_a.fill.solid()
                bg_a.fill.fore_color.rgb = C_WHITE
                bg_a.line.fill.background()

            # Resolve Answer Media
            cand_ans_imgs = (
                list(_get_val(q, "answer_images", []) or []) +
                list(hist_media.get("answer_images", []) or []) +
                list(_get_val(q, "image_refs", []) or []) +
                list(hist_media.get("raw_media_refs", []) or [])
            )
            ans_img_path = None
            for ai in cand_ans_imgs:
                if isinstance(ai, str) and not ai.lower().endswith(('.mp4', '.m4v', '.mov', '.mp3', '.wav')):
                    p = _resolve_media_path(ai)
                    if p and p.exists():
                        ans_img_path = p
                        break

            if not ans_img_path and poster_path:
                ans_img_path = poster_path

            explanation = (_get_val(q, "explanation") or "").strip()
            has_ans_img = bool(ans_img_path)

            if has_ans_img:
                if explanation and len(explanation) > 100:
                    # 2-Column Layout: Answer + detailed explanation on left, media right
                    tb_a = sa.shapes.add_textbox(Inches(0.80), Inches(1.50), Inches(6.80), Inches(5.00))
                    tf_a = tb_a.text_frame
                    tf_a.word_wrap = True

                    pa_head = tf_a.paragraphs[0]
                    pa_head.text = ans_val
                    pa_head.font.name = FONT_HEAD
                    pa_head.font.size = Pt(34) if len(ans_val) < 40 else (Pt(28) if len(ans_val) < 80 else Pt(22))
                    pa_head.font.bold = True
                    pa_head.font.color.rgb = C_ACCENT_GREEN

                    pa_exp = tf_a.add_paragraph()
                    pa_exp.space_before = Pt(16)
                    pa_exp.text = explanation
                    pa_exp.font.name = FONT_BODY
                    pa_exp.font.size = Pt(18)
                    pa_exp.font.color.rgb = C_TEXT_BODY

                    _add_scaled_picture(sa, ans_img_path, Inches(8.00), Inches(1.50), Inches(4.70), Inches(5.00))
                else:
                    # Centered Layout: Answer title on top, Image centered below
                    tb_a = sa.shapes.add_textbox(Inches(1.00), Inches(1.30), Inches(11.333), Inches(1.10))
                    tf_a = tb_a.text_frame
                    tf_a.word_wrap = True

                    pa_head = tf_a.paragraphs[0]
                    pa_head.alignment = PP_ALIGN.CENTER
                    pa_head.text = ans_val
                    pa_head.font.name = FONT_HEAD
                    pa_head.font.size = Pt(36) if len(ans_val) < 40 else (Pt(30) if len(ans_val) < 80 else Pt(24))
                    pa_head.font.bold = True
                    pa_head.font.color.rgb = C_ACCENT_GREEN

                    _add_scaled_picture(sa, ans_img_path, Inches(3.00), Inches(2.55), Inches(7.333), Inches(4.20))

                    if explanation:
                        tb_exp = sa.shapes.add_textbox(Inches(1.50), Inches(6.80), Inches(10.333), Inches(0.60))
                        pexp = tb_exp.text_frame.paragraphs[0]
                        pexp.alignment = PP_ALIGN.CENTER
                        pexp.text = explanation
                        pexp.font.name = FONT_BODY
                        pexp.font.size = Pt(14)
                        pexp.font.color.rgb = C_TEXT_MUTED
            else:
                # Text-Only Answer Slide: Large green reveal at top, trivia explanation card below
                tb_a = sa.shapes.add_textbox(Inches(1.00), Inches(1.60), Inches(11.333), Inches(1.20))
                tf_a = tb_a.text_frame
                tf_a.word_wrap = True

                pa_head = tf_a.paragraphs[0]
                pa_head.alignment = PP_ALIGN.CENTER
                pa_head.text = ans_val
                pa_head.font.name = FONT_HEAD
                pa_head.font.size = Pt(42) if len(ans_val) < 40 else (Pt(34) if len(ans_val) < 80 else Pt(26))
                pa_head.font.bold = True
                pa_head.font.color.rgb = C_ACCENT_GREEN

                if explanation:
                    tb_exp = sa.shapes.add_textbox(Inches(1.50), Inches(3.20), Inches(10.333), Inches(3.20))
                    tf_exp = tb_exp.text_frame
                    tf_exp.word_wrap = True

                    pexp = tf_exp.paragraphs[0]
                    pexp.alignment = PP_ALIGN.CENTER
                    pexp.text = explanation
                    pexp.font.name = FONT_BODY
                    pexp.font.size = Pt(22)
                    pexp.font.color.rgb = C_TEXT_BODY

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
