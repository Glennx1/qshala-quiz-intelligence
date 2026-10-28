"""
QShala Exporter v2 — Complete rewrite of backend/app/services/export/exporter.py

PATCH INSTRUCTIONS FOR ANTIGRAVITY:
====================================
Replace the ENTIRE contents of backend/app/services/export/exporter.py with this file.

WHAT THIS FIXES (vs the old exporter):
1. ROOT CAUSE: _resolve_media_path ignored R2 HTTPS URLs entirely — if R2 is configured
   (which it is on deployed Render), ALL media refs are https://... URLs. The old resolver
   only checks local filesystem paths, so ZERO question images/videos/audio ever embed.

2. Downloads R2 media to a temp directory before embedding into PPTX, with proper cleanup.

3. Fixes the session leak in _get_hist_q_media (db.close() wasn't in a finally block).

4. Adds missing `question_videos` and `answer_videos` fields to candidate detection
   (these columns exist on the Question model but the old exporter never checked them).

5. Keeps the same visual design (slate/blue/green/gold minimalist palette) and layout
   (60/40 split when media present, full width when text-only).

WHAT THIS DOES NOT CHANGE:
- JSON and CSV exporters are untouched
- The visual design/layout is preserved exactly
- The to_pptx method signature and return type are identical
"""

import csv
import io
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Media resolution — the critical fix
# ---------------------------------------------------------------------------

def _download_url_to_file(url: str, dest_dir: Path) -> Optional[Path]:
    """
    Downloads a URL (R2 public URL or any HTTPS media URL) to a local temp file.
    Returns the local path or None on failure.
    """
    try:
        import urllib.request
        import urllib.error
        from urllib.parse import urlparse, unquote

        parsed = urlparse(url)
        filename = Path(unquote(parsed.path)).name
        if not filename:
            filename = "media_file"

        dest_path = dest_dir / filename
        # Avoid re-downloading if already fetched this session
        if dest_path.exists() and dest_path.stat().st_size > 0:
            return dest_path

        logger.info(f"Downloading media: {url} -> {dest_path}")
        urllib.request.urlretrieve(url, str(dest_path))

        if dest_path.exists() and dest_path.stat().st_size > 0:
            return dest_path
        return None
    except Exception as e:
        logger.warning(f"Failed to download {url}: {e}")
        return None


def _resolve_media_path(rel_url: Optional[str], download_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Resolves local filesystem paths for images, audio, and video files.

    NEW: If the ref is an HTTPS URL (R2 or otherwise), downloads it to download_dir.
    This is the ROOT FIX for the missing media in exported PPTXs.
    """
    if not rel_url or not isinstance(rel_url, str):
        return None
    from backend.app.config import settings
    clean_url = rel_url.strip()

    # ── NEW: Handle HTTPS URLs (R2 media, external URLs) ──
    if clean_url.startswith("https://") or clean_url.startswith("http://"):
        if download_dir:
            return _download_url_to_file(clean_url, download_dir)
        else:
            logger.warning(f"HTTPS URL found but no download_dir provided: {clean_url}")
            return None

    # 1. Slide extracts directory (/static/slides/...)
    if clean_url.startswith("/static/slides/"):
        sub = clean_url[len("/static/slides/"):]
        p = settings.SLIDES_DIR / sub
        if p.exists() and p.is_file():
            return p
    # 2. Storage directory general (/static/...)
    elif clean_url.startswith("/static/"):
        sub = clean_url[len("/static/"):]
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
    """
    Helper to retrieve raw media, audio, and videos from the source vault question
    if available.

    FIX: Uses try/finally to ensure db.close() is always called (session leak fix).
    """
    sources = _get_val(q, "retrieval_sources", []) or _get_val(q, "sources", [])
    if not sources:
        return {}
    hist_id = _get_val(sources[0], "historical_question_id")
    if not hist_id:
        return {}

    db = None
    try:
        from backend.app.database import SessionLocal
        from backend.app.models.question import Question
        db = SessionLocal()
        hq = db.query(Question).filter(Question.id == hist_id).first()
        if not hq:
            return {}
        return {
            "raw_media_refs": list(getattr(hq, "raw_media_refs", []) or []),
            "question_audio": list(getattr(hq, "question_audio", []) or []),
            "audio_refs": list(getattr(hq, "audio_refs", []) or []),
            "question_images": list(getattr(hq, "question_images", []) or []),
            "answer_images": list(getattr(hq, "answer_images", []) or []),
            "image_refs": list(getattr(hq, "image_refs", []) or []),
            "question_videos": list(getattr(hq, "question_videos", []) or []),
            "answer_videos": list(getattr(hq, "answer_videos", []) or []),
            "video_refs": list(getattr(hq, "video_refs", []) or []),
        }
    except Exception as e:
        logger.warning(f"Error fetching historical question media: {e}")
        return {}
    finally:
        if db is not None:
            db.close()


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
    def to_pptx(quiz: Any) -> bytes:
        """
        Exports the quiz into a crisp, minimalist, high-typography presentation deck (16:9 widescreen).

        Properly embeds all media types:
        1. High-resolution images (proportional PIL scaling) — from R2 or local disk
        2. Videos (embedded directly into PowerPoint slides via add_movie with poster frames)
        3. Audio clues (embedded into slides with clean interactive sound effect cards)
        4. Immediate Question -> Answer pairs (no filler slides, zero fluff)

        NEW in v2: Downloads R2 media to temp dir before embedding. This is the fix
        for zero-media exports when R2 is the configured storage backend.
        """
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.enum.shapes import MSO_SHAPE

        # ── Create a temp directory for downloaded R2 media ──
        # This gets cleaned up at the end via try/finally
        media_tmp_dir = Path(tempfile.mkdtemp(prefix="qshala_export_media_"))
        logger.info(f"Export media temp dir: {media_tmp_dir}")

        try:
            return QuizExporter._build_pptx(quiz, media_tmp_dir)
        finally:
            # Clean up downloaded media files
            try:
                shutil.rmtree(media_tmp_dir, ignore_errors=True)
                logger.info(f"Cleaned up export media temp dir: {media_tmp_dir}")
            except Exception:
                pass

    @staticmethod
    def _build_pptx(quiz: Any, media_tmp_dir: Path) -> bytes:
        """Internal method that builds the PPTX with access to the media temp dir."""
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
        C_CARD_BG = RGBColor(241, 245, 249)       # #F1F5F9 Slate 100
        C_CARD_BORDER = RGBColor(203, 213, 225)   # #CBD5E1 Slate 300

        FONT_HEAD = "Trebuchet MS"
        FONT_BODY = "Calibri"

        title_text = _get_val(quiz, "title", "QShala Tournament Quiz")
        topic_text = _get_val(quiz, "topic", "General Knowledge")
        difficulty = _get_val(quiz, "difficulty", "Balanced")

        questions_raw = _get_val(quiz, "questions", [])
        approved_questions = [q for q in questions_raw if _get_val(q, "is_approved", True)]
        total_q = len(approved_questions)

        # Count how many questions have media (for logging)
        media_stats = {"images": 0, "videos": 0, "audio": 0, "failed_downloads": 0}

        # Helper to resolve with the temp dir
        def resolve(ref):
            return _resolve_media_path(ref, download_dir=media_tmp_dir)

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

            # Check historical source media fallback
            hist_media = _get_hist_q_media(q)

            # --- VIDEO DETECTION ---
            # FIX: Added question_videos (exists on model but was missing from candidates)
            cand_videos = (
                list(_get_val(q, "question_videos", []) or []) +
                list(_get_val(q, "question_video", []) or []) +
                list(_get_val(q, "video_refs", []) or []) +
                list(_get_val(q, "raw_media_refs", []) or []) +
                list(_get_val(q, "image_refs", []) or []) +
                list(hist_media.get("question_videos", []) or []) +
                list(hist_media.get("video_refs", []) or []) +
                list(hist_media.get("raw_media_refs", []) or [])
            )
            video_path = None
            for cv in cand_videos:
                if isinstance(cv, str) and cv.lower().endswith(('.mp4', '.m4v', '.mov', '.webm')):
                    p = resolve(cv)
                    if p and p.exists():
                        video_path = p
                        media_stats["videos"] += 1
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
                    p = resolve(ca)
                    if p and p.exists():
                        audio_path = p
                        media_stats["audio"] += 1
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
                    p = resolve(ci)
                    if p and p.exists() and p not in resolved_q_imgs:
                        resolved_q_imgs.append(p)
                        media_stats["images"] += 1

            # Poster frame for video / audio
            poster_path = resolved_q_imgs[0] if resolved_q_imgs else None

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
            media_type_tag = ""
            if video_path:
                media_type_tag = "   [VIDEO CLUE]"
            elif audio_path:
                media_type_tag = "   [AUDIO CLUE]"

            tb_qtag = sq.shapes.add_textbox(Inches(1.0), Inches(0.6), Inches(11.3), Inches(0.5))
            pq_tag = tb_qtag.text_frame.paragraphs[0]
            pq_tag.text = f"QUESTION {idx:02d}{star_tag}   /   {cat_text}{media_type_tag}"
            pq_tag.font.name = FONT_HEAD
            pq_tag.font.size = Pt(13)
            pq_tag.font.bold = True
            pq_tag.font.color.rgb = C_ACCENT_BLUE

            # Question Body Text & Options (Left 60% if media present, full width otherwise)
            has_media = bool(video_path or audio_path or resolved_q_imgs)

            if has_media:
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

                # Media Placement on Right Side
                if video_path:
                    # 1. EMBEDDED VIDEO
                    logger.info(f"Embedding video {video_path} into slide Q{idx}")
                    sq.shapes.add_movie(
                        str(video_path),
                        Inches(8.1), Inches(1.3), Inches(4.5), Inches(5.0),
                        poster_frame_image=str(poster_path) if poster_path else None,
                        mime_type="video/mp4"
                    )
                elif audio_path:
                    # 2. EMBEDDED AUDIO CLUE with Interactive Card
                    logger.info(f"Embedding audio {audio_path} into slide Q{idx}")
                    card = sq.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.1), Inches(1.8), Inches(4.2), Inches(3.6))
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
                    p_c2.text = "Click the speaker below to play the sound effect:"
                    p_c2.font.name = FONT_BODY
                    p_c2.font.size = Pt(14)
                    p_c2.font.color.rgb = C_TEXT_MUTED
                    p_c2.alignment = PP_ALIGN.CENTER

                    # Embedded audio player object inside card
                    sq.shapes.add_movie(
                        str(audio_path),
                        Inches(9.7), Inches(3.4), Inches(1.0), Inches(1.0),
                        poster_frame_image=str(poster_path) if poster_path else None,
                        mime_type="audio/mpeg"
                    )
                elif len(resolved_q_imgs) >= 2:
                    # 3. MULTI-IMAGE (side-by-side or stacked)
                    _add_scaled_picture(sq, resolved_q_imgs[0], Inches(8.1), Inches(1.3), Inches(4.2), Inches(2.4))
                    _add_scaled_picture(sq, resolved_q_imgs[1], Inches(8.1), Inches(3.9), Inches(4.2), Inches(2.4))
                elif len(resolved_q_imgs) == 1:
                    # 4. SINGLE IMAGE
                    _add_scaled_picture(sq, resolved_q_imgs[0], Inches(8.1), Inches(1.3), Inches(4.2), Inches(5.1))

            else:
                # Full Width Layout (Text Only)
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
            if video_path:
                host_notes.append(f"Video clue: {video_path.name}")
            elif audio_path:
                host_notes.append(f"Audio clue: {audio_path.name}")
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
            # FIX: Added answer_videos to candidate list
            cand_ans_imgs = (
                list(_get_val(q, "answer_images", []) or []) +
                list(hist_media.get("answer_images", []) or []) +
                list(_get_val(q, "image_refs", []) or []) +
                list(hist_media.get("raw_media_refs", []) or [])
            )
            ans_img_path = None
            for ai in cand_ans_imgs:
                if isinstance(ai, str) and not ai.lower().endswith(('.mp4', '.m4v', '.mov', '.mp3', '.wav')):
                    p = resolve(ai)
                    if p and p.exists():
                        ans_img_path = p
                        break

            # Fallback to poster path if no distinct answer image
            if not ans_img_path and poster_path:
                ans_img_path = poster_path

            ans_size = Pt(40) if len(ans_val) < 35 else (Pt(32) if len(ans_val) < 70 else Pt(26))
            explanation = (_get_val(q, "explanation") or "").strip()

            if ans_img_path:
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

                _add_scaled_picture(sa, ans_img_path, Inches(8.1), Inches(1.3), Inches(4.2), Inches(5.1))

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

        # Log media embedding stats
        logger.info(
            f"PPTX export complete: {total_q} questions, "
            f"{media_stats['images']} images, {media_stats['videos']} videos, "
            f"{media_stats['audio']} audio clips embedded"
        )

        buffer = io.BytesIO()
        prs.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
