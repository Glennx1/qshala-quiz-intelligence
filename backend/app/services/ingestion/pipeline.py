import os
import re
import time
import asyncio
import logging
import gc
from pathlib import Path
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

def _log_mem(stage: str):
    rss_mb = 0.0
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_mb = float(line.split()[1]) / 1024.0
                    break
    except Exception:
        try:
            import resource
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            pass
    counts = gc.get_count()
    msg = f"[MEM] {stage:45s} | RSS: {rss_mb:6.1f} MB | GC: {counts}"
    logging.getLogger(__name__).info(msg)
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.config import settings
from backend.app.services.ingestion.pptx_parser import PPTXParser
from backend.app.services.ingestion.pdf_parser import PDFParser
from backend.app.services.ingestion.cancellation import (
    IngestionCancelled,
    doc_cancel_requested,
    raise_if_cancelled,
    clear_doc_cancel,
    purge_document,
)
from backend.app.services.ingestion.slide_classifier import SlideClassifier
from backend.app.services.ingestion.question_extractor import QuestionExtractor
from backend.app.services.ingestion.deck_metadata import annotate_questions
from backend.app.models.question_meta import DeckMetadata, QuestionEditHistory
from backend.app.services.ingestion import progress
from backend.app.services.ingestion.vision_resize import shrink_for_vision, shrink_for_vision_subprocess, is_significant_visual_image, is_significant_file
from backend.app.services.tagging.qshala_tagger import safe_error
from backend.app.services.question_meta_service import (
    upsert_deck_metadata, deck_row_to_info, ensure_question_metadata, apply_tag_to_meta,
)
from backend.app.services.tagging import topic_paths
from backend.app.services.tagging.auto_tagger import AutoTagger  # Kept for backward compatibility
from backend.app.services.tagging.qshala_tagger import QshalaTagger
from backend.app.services.tagging.qshala_batch import tag_deck_batched
from backend.app.services.tagging.difficulty_engine import DifficultyEngine
import ctypes

def _trim_memory():
    gc.collect()
    if hasattr(ctypes, "CDLL"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

# Feature toggle: set to False to revert to legacy AutoTagger writing topic tags on upload
USE_QSHALA_TAGGER: bool = True
VISION_CONCURRENCY: int = int(os.getenv("VISION_CONCURRENCY", "3"))   # parallel image-description calls (fast 3x concurrency)
TAG_CONCURRENCY: int = int(os.getenv("TAG_CONCURRENCY", "6"))   # parallel Gemini tagging calls per deck
ENABLE_VISION_INGESTION: bool = os.getenv("ENABLE_VISION_INGESTION", "true").strip().lower() in ("1", "true", "yes", "on")

VISUAL_TRIGGER_PATTERNS = [
    r"\b(this|the)\s+(photo|picture|image|logo|diagram|painting|sculpture|caricature|portrait|flag|map|sign|banner|stamp|poster)\b",
    r"\b(in|on)\s+the\s+(picture|photo|image|screen|slide)\b",
    r"\b(seen|shown|pictured|depicted|displayed)\s+(here|below|above|on\s+the\s+screen)\b",
    r"\bidentify\s+(this|the|whom|who|what)\b",
    r"\bwhose\s+(logo|photo|portrait|picture|flag|face|signature|shadow|silhouette)\b",
    r"\bwhat\s+(is\s+this|brand|company|person|monument|landmark|animal|logo)\b",
    r"\bconnect\s+these\b",
    r"\bvisual\s+clue\b",
    r"\blook\s+at\s+the\b",
]
_VISUAL_TRIGGER_REGEX = re.compile("|".join(VISUAL_TRIGGER_PATTERNS), re.IGNORECASE)

def is_image_dependent_question(q: Dict[str, Any]) -> bool:
    """Returns True only if the question's text references visual assets or lacks enough context without them."""
    has_slide_images = bool(q.get("image_paths") or q.get("question_images") or q.get("image_refs"))
    if not has_slide_images:
        return False
    combined_text = ((q.get("question_text") or "") + " " + (q.get("explanation") or "")).strip()
    words = combined_text.split()
    if len(words) < 15:
        return True
    if _VISUAL_TRIGGER_REGEX.search(combined_text):
        return True
    return False
from backend.app.services.deduplication.deduplicator import Deduplicator
from backend.app.services.ai.factory import get_embedding_provider, get_llm_provider

logger = logging.getLogger(__name__)


def _ensure_clean(db, where: str) -> None:
    """Enforce the invariant: no open transaction may cross a slow AI stage.
    If one is open, commit it (ending the idle window) and log where it happened so a
    regression is visible instead of silently re-introducing the idle-timeout bug."""
    try:
        if db.in_transaction():
            logger.info("ingestion: committing open transaction before %s", where)
            db.commit()
    except Exception:
        db.rollback()

# Global tracker for real-time progress polling
INGESTION_STATUS_REGISTRY: Dict[str, Dict[str, Any]] = {}

class IngestionPipeline:
    def __init__(self, db: Optional[Session] = None):
        self._external_db = db
        self.classifier = SlideClassifier()
        self.extractor = QuestionExtractor()
        self.auto_tagger = AutoTagger()
        self.qshala_tagger = QshalaTagger()
        self.difficulty_engine = DifficultyEngine()
        self.deduplicator = Deduplicator()
        self.embedding_provider = get_embedding_provider()
        self.llm_provider = get_llm_provider()

    async def run(self, document_id: str):
        INGESTION_STATUS_REGISTRY[document_id] = {
            "document_id": document_id,
            "status": "PROCESSING",
            "progress_percentage": 5,
            "current_step": "1. Extracting content from presentation",
            "slides_processed": 0,
            "questions_extracted": 0,
            "error": None,
            "detail": "Upload received. Starting to process the deck.",
            "events": [],
        }
        progress.event(INGESTION_STATUS_REGISTRY[document_id], "Upload received, starting to process the deck")

        own_session = False
        db = self._external_db
        if db is None:
            from backend.app.database import SessionLocal
            db = SessionLocal()
            own_session = True

        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if not doc:
                INGESTION_STATUS_REGISTRY[document_id]["status"] = "FAILED"
                INGESTION_STATUS_REGISTRY[document_id]["error"] = "Document not found"
                return

            doc.processing_status = "PROCESSING"
            db.commit()

            doc_id = doc.id
            doc_storage_path = doc.storage_path
            doc_filename = doc.filename
            doc_title = doc.title
            doc_year = doc.year

            file_ext = os.path.splitext(doc_filename)[1].lower()
            
            # Step 1 & 2: Extracting and Processing Slides
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 20,
                "current_step": "2. Processing slides and extracting visual assets"
            })

            if file_ext in [".pptx", ".ppt"]:
                parser = PPTXParser(doc_storage_path, doc_id)
                parser.should_cancel = lambda: doc_cancel_requested(document_id)
                parser.on_progress = lambda detail, pct=None: progress.update(
                    INGESTION_STATUS_REGISTRY[document_id], detail=detail, pct=pct)
                try:
                    _mb = os.path.getsize(doc_storage_path) / 1048576.0
                    progress.event(INGESTION_STATUS_REGISTRY[document_id], f"Opening the deck ({_mb:.0f} MB). Large decks take a while to load.")
                except Exception:
                    pass
                # Make sure DB transaction is committed/clean before slow parse
                db.commit()
                raw_slides = await asyncio.to_thread(parser.parse)
            elif file_ext == ".pdf":
                parser = PDFParser(doc_storage_path, doc_id)
                db.commit()
                raw_slides = await asyncio.to_thread(parser.parse)
            else:
                raise ValueError(f"Unsupported file format: {file_ext}")

            raise_if_cancelled(document_id)
            progress.event(INGESTION_STATUS_REGISTRY[document_id], f"Read {len(raw_slides)} slides and saved their pictures")
            try:
                del parser
            except NameError:
                pass
            _trim_memory()
            _log_mem("after parse")

            # Classify each slide using 2-pass contextual deck classifier
            classified_slides = []
            slide_models = []
            deck_types = self.classifier.classify_deck(raw_slides)

            for s, slide_type in zip(raw_slides, deck_types):
                s["slide_type"] = slide_type
                classified_slides.append(s)

                slide_obj = Slide(
                    document_id=doc_id,
                    slide_number=s["slide_number"],
                    slide_type=slide_type,
                    title=s["title"],
                    extracted_text=s["extracted_text"],
                    speaker_notes=s["speaker_notes"],
                    image_paths=s["image_paths"],
                    has_images=s["has_images"],
                    metadata_json=s["metadata_json"]
                )
                db.add(slide_obj)
                slide_models.append(slide_obj)

            db.flush()  # Assign slide IDs
            _kinds: Dict[str, int] = {}
            for _t in deck_types:
                _kinds[_t] = _kinds.get(_t, 0) + 1
            _other = len(deck_types) - _kinds.get("QUESTION", 0) - _kinds.get("ANSWER", 0)
            progress.event(INGESTION_STATUS_REGISTRY[document_id],
                           f"Sorted slides: {_kinds.get('QUESTION', 0)} question, {_kinds.get('ANSWER', 0)} answer, "
                           f"{_other} other (titles, rounds, scoreboards: not sent to the AI)")
            doc.slide_count = len(slide_models)
            try:
                del deck_types
            except NameError:
                pass
            _trim_memory()
            _log_mem("after classify")
            
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 45,
                "slides_processed": len(slide_models),
                "current_step": "3. Detecting questions and quiz patterns"
            })

            # Map slide objects back to classified slides with IDs, then CLOSE phase A.
            for i, s_model in enumerate(slide_models):
                classified_slides[i]["id"] = s_model.id
            db.commit()                         # Phase A done: slides durable, no open transaction.

            # Step 3, 4, 5: Question Extraction & Classification
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 60,
                "current_step": "4. Detecting answers, options, and difficulty levels"
            })

            raw_questions = self.extractor.extract_from_slides(
                classified_slides,
                doc_title=doc_title,
                doc_year=doc_year
            )

            progress.event(INGESTION_STATUS_REGISTRY[document_id], f"Found {len(raw_questions)} questions")

            # Deck details from the file name, then the no-AI per-question fields
            # (question number, format, star, answer type, language).
            deck_row = upsert_deck_metadata(db, doc)
            deck_info = deck_row_to_info(deck_row)
            annotate_questions(raw_questions, classified_slides, deck_info)
            deck_year = deck_row.deck_year or doc.year    # capture BEFORE commit expires the row
            db.commit()                                   # nothing below until dedup touches the DB
            _ensure_clean(db, "vision/embedding stage")   # assert the invariant at the phase boundary
            _trim_memory()
            _log_mem("after question extraction")

            # Step 5: Multi-Topic Auto-Tagging & Pedagogical Difficulty Scoring
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 75,
                "questions_extracted": len(raw_questions),
                "current_step": "5. Multimodal visual inspection & intelligent tagging"
            })

            # Describe question images in parallel (each is a separate vision call; they used to run one by one).
            # A picture reused across several questions (a round's title image, a repeated
            # logo or answer slide) is only described once: callers for the same path share
            # one in-flight future rather than each firing their own Gemini call.
            _vision_cache: Dict[str, asyncio.Future] = {}
            _vision_cache_lock = asyncio.Lock()
            _vision_reused = {"n": 0}

            async def _describe_one_image(rel_img_path: str) -> Optional[str]:
                img_name = os.path.basename(rel_img_path)
                _log_mem(f"before image desc [{img_name}]")
                async with _vision_cache_lock:
                    fut = _vision_cache.get(rel_img_path)
                    if fut is not None:
                        _vision_reused["n"] += 1
                        return await fut
                    fut = asyncio.get_event_loop().create_future()
                    _vision_cache[rel_img_path] = fut

                desc: Optional[str] = None
                try:
                    disk_path: Optional[Path] = None
                    img_bytes: Optional[bytes] = None
                    ext = os.path.splitext(rel_img_path)[1].lower()

                    # 1. First look for local copy at settings.SLIDES_DIR / doc_id / "media" / img_name
                    cand_local = settings.SLIDES_DIR / doc_id / "media" / img_name
                    if cand_local.exists():
                        disk_path = cand_local
                    elif rel_img_path.startswith("/static/slides/"):
                        sub = rel_img_path[len("/static/slides/"):]
                        cand = settings.SLIDES_DIR / sub
                        if cand.exists():
                            disk_path = cand
                    elif rel_img_path.startswith("/static/"):
                        cand = settings.STORAGE_DIR / rel_img_path.lstrip("/static/")
                        if cand.exists():
                            disk_path = cand

                    # 2. Only fall back to httpx download if local file not found
                    if disk_path is None and (rel_img_path.startswith("http://") or rel_img_path.startswith("https://")):
                        try:
                            import httpx as _httpx
                            async with _httpx.AsyncClient(timeout=30.0) as client:
                                resp = await client.get(rel_img_path)
                                resp.raise_for_status()
                                img_bytes = resp.content
                                del resp
                        except Exception as fetch_err:
                            logger.warning(f"Failed to fetch remote image {rel_img_path}: {fetch_err}")

                    if disk_path and not is_significant_file(str(disk_path)):
                        return None
                    if img_bytes and not is_significant_visual_image(img_bytes):
                        return None

                    if disk_path or img_bytes:
                        try:
                            mime = "image/png" if ext == ".png" else ("image/jpeg" if ext in [".jpg", ".jpeg"] else "image/webp")
                            vision_bytes, mime = await shrink_for_vision_subprocess(
                                file_path=str(disk_path) if disk_path else None,
                                data=img_bytes,
                                mime_type=mime
                            )
                            if img_bytes is not None:
                                del img_bytes
                                img_bytes = None

                            if vision_bytes:
                                raw_desc = await self.llm_provider.describe_image(vision_bytes, mime_type=mime)
                                del vision_bytes
                                if raw_desc and raw_desc.strip():
                                    desc = raw_desc.strip()
                        except Exception as vision_err:
                            logger.warning(f"Failed to describe image {rel_img_path}: {vision_err}")
                finally:
                    if not fut.done():
                        fut.set_result(desc)
                    _trim_memory()
                    _log_mem(f"after image desc [{img_name}]")
                return desc

            async def _describe_images(q):
                if not ENABLE_VISION_INGESTION or not is_image_dependent_question(q):
                    q["visual_clues"] = None
                    return None

                visual_clues_list = []
                # Prioritize question_images over broad image_refs, capped at 4
                target_imgs = list(q.get("question_images") or q.get("image_refs") or [])[:4]
                for rel_img_path in target_imgs:
                    desc = await _describe_one_image(rel_img_path)
                    if desc:
                        visual_clues_list.append(desc)

                visual_clues_str = "\n".join(visual_clues_list) if visual_clues_list else None
                q["visual_clues"] = visual_clues_str
                return visual_clues_str

            vision_sem = asyncio.Semaphore(VISION_CONCURRENCY)
            candidate_questions = [
                q for q in raw_questions
                if (q.get("question_images") or q.get("image_refs")) and is_image_dependent_question(q)
            ] if ENABLE_VISION_INGESTION else []
            _img_total = len(candidate_questions)
            _img_done = {"n": 0}
            logger.info(f"Vision: {_img_total}/{len(raw_questions)} questions flagged as image-dependent (was 27)")

            async def _describe_guarded(q):
                if not ENABLE_VISION_INGESTION or not is_image_dependent_question(q) or not (q.get("question_images") or q.get("image_refs")):
                    q["visual_clues"] = None
                    return None
                async with vision_sem:
                    raise_if_cancelled(document_id)
                    out = await _describe_images(q)
                    _img_done["n"] += 1
                    progress.update(INGESTION_STATUS_REGISTRY[document_id],
                                    detail=f"Describing question images with AI ({_img_done['n']}/{_img_total})")
                    return out

            INGESTION_STATUS_REGISTRY[document_id]["current_step"] = "5. Reading question images"
            if _img_total:
                progress.event(INGESTION_STATUS_REGISTRY[document_id], f"Describing images for {_img_total} visual questions with AI")
            else:
                progress.event(INGESTION_STATUS_REGISTRY[document_id], "Questions have self-contained text (skipped AI image reading)")
            await asyncio.gather(*[_describe_guarded(q) for q in raw_questions])
            _vision_cache.clear()
            _trim_memory()
            if _vision_reused["n"]:
                progress.event(INGESTION_STATUS_REGISTRY[document_id],
                               f"{_vision_reused['n']} repeated pictures reused their earlier description (skipped the AI call)")

            enriched_questions = []
            for q in raw_questions:
                raise_if_cancelled(document_id)
                visual_clues_str = q.get("visual_clues")

                # 1. Multi-topic and entity tagging (including visual clues)
                is_multimodal = bool(
                    q.get("image_refs") or
                    q.get("question_images") or
                    q.get("audio_refs") or
                    q.get("question_audio") or
                    q.get("video_refs") or
                    q.get("question_videos") or
                    q.get("media_items") or
                    q.get("audio_transcript") or
                    q.get("video_transcript") or
                    q.get("raw_media_refs")
                )

                if not USE_QSHALA_TAGGER:
                    tags_data = await self.auto_tagger.tag_question_with_ai(
                        question_text=q["question_text"],
                        answer_text=q["answer"],
                        explanation=q.get("explanation", ""),
                        doc_title=doc_title,
                        visual_clues=visual_clues_str or q.get("visual_clues", "") or "",
                        audio_transcript=q.get("audio_transcript", ""),
                        video_transcript=q.get("video_transcript", ""),
                        subtopic=q.get("subtopic")
                    )
                else:
                    # Legacy AutoTagger bypassed: QshalaTagger tags will be populated below
                    tags_data = {
                        "primary_topic": None,
                        "topics": [],
                        "subtopic": q.get("subtopic"),
                        "tags": [],
                        "question_hook": "DIRECT_TRIVIA",
                        "curiosity_score": 7,
                        "temporal_nature": "EVERGREEN"
                    }
                # 2. Difficulty & Grade evaluation (multimodal questions set to 'Unrated')
                diff_data = self.difficulty_engine.evaluate(
                    question_text=q["question_text"],
                    answer_text=q["answer"],
                    explanation=q.get("explanation", ""),
                    notes=q.get("speaker_notes", ""),
                    is_multimodal=is_multimodal
                )

                q.update({
                    "primary_topic": tags_data["primary_topic"],
                    "topics": tags_data["topics"],
                    "subtopic": q.get("subtopic") or tags_data.get("subtopic"),
                    "tags": tags_data["tags"],
                    "question_hook": tags_data["question_hook"],
                    "curiosity_score": tags_data["curiosity_score"],
                    "temporal_nature": tags_data["temporal_nature"],
                    "difficulty": diff_data["difficulty"],
                    "difficulty_score": diff_data["difficulty_score"],
                    "cognitive_level": diff_data["cognitive_level"],
                    "grade_min": diff_data["grade_min"],
                    "grade_max": diff_data["grade_max"],
                    "audience_suitability": diff_data["audience_suitability"],
                    "topic": tags_data["primary_topic"]
                })
                enriched_questions.append(q)

            raise_if_cancelled(document_id)

            # Step 6: Generate Semantic Embeddings
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 85,
                "current_step": "6. Generating semantic vector embeddings"
            })

            for idx, q in enumerate(enriched_questions):
                q["_emb_idx"] = idx

            texts_to_embed = [
                f"{q.get('primary_topic') or ''} {' '.join(q.get('topics') or [])} {q['question_text']} {q['answer']} {q.get('visual_clues') or ''} {q.get('explanation') or ''}".strip()
                for q in enriched_questions
            ]

            embeddings = []
            if texts_to_embed:
                try:
                    embeddings = await self.embedding_provider.get_embeddings(texts_to_embed)
                except Exception as e:
                    logger.warning(f"Embedding generation error ({e}), falling back to unit vectors")
                    embeddings = [[0.0] * 768 for _ in texts_to_embed]

            raise_if_cancelled(document_id)

            # Step 7: Deduplication Check & Step 8: Indexing Unique Records
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 92,
                "current_step": "7. Deduplicating questions against knowledge base"
            })

            _ensure_clean(db, "dedup")              # fresh, pre-pinged connection for phase C
            from sqlalchemy.exc import OperationalError, DBAPIError
            try:
                unique_candidates, duplicates = self.deduplicator.deduplicate_batch(
                    db=db, candidates=enriched_questions,
                    candidate_embeddings=embeddings, doc_id=doc.id)
            except (OperationalError, DBAPIError) as db_err:
                logger.warning("dedup hit a stale connection, retrying once: %s", safe_error(db_err))
                db.rollback()                        # drop the dead transaction; pre_ping gives a live conn
                unique_candidates, duplicates = self.deduplicator.deduplicate_batch(
                    db=db, candidates=enriched_questions,
                    candidate_embeddings=embeddings, doc_id=doc.id)

            raise_if_cancelled(document_id)

            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 96,
                "current_step": f"8. Storing {len(unique_candidates)} unique questions ({len(duplicates)} replicas linked)"
            })

            question_models = []
            for q_data in unique_candidates:
                orig_idx = q_data.get("_emb_idx")
                emb = embeddings[orig_idx] if orig_idx is not None and 0 <= orig_idx < len(embeddings) else None

                q_obj = Question(
                    content_hash=q_data["content_hash"],
                    document_id=document_id,
                    slide_id=q_data.get("slide_id"),
                    answer_slide_id=q_data.get("answer_slide_id"),
                    question_text=q_data["question_text"],
                    answer=q_data["answer"],
                    options=q_data.get("options"),
                    explanation=q_data.get("explanation"),
                    topic=q_data["primary_topic"] or topic_paths.UNCATEGORISED,
                    subtopic=q_data.get("subtopic"),
                    topics=q_data.get("topics", []),
                    tags=q_data.get("tags", []),
                    difficulty=q_data.get("difficulty", "Medium"),
                    difficulty_score=q_data.get("difficulty_score", 0.50),
                    cognitive_level=q_data.get("cognitive_level", "Recall / Remember"),
                    grade_min=q_data.get("grade_min", 3),
                    grade_max=q_data.get("grade_max", 12),
                    audience_suitability=q_data.get("audience_suitability", []),
                    question_hook=q_data.get("question_hook", "DIRECT_TRIVIA"),
                    curiosity_score=q_data.get("curiosity_score", 7),
                    temporal_nature=q_data.get("temporal_nature", "EVERGREEN"),
                    provenance_decks=[{"document_id": document_id, "slide_id": q_data.get("slide_id")}],
                    occurrence_count=1,
                    question_type=q_data.get("question_type", "SLIDE_QA"),
                    source_year=q_data.get("source_year", doc.year if doc else doc_year),
                    round_number=(q_data.get("_meta") or {}).get("round_number"),
                    image_refs=q_data.get("image_refs", []),
                    question_images=q_data.get("question_images", []),
                    answer_images=q_data.get("answer_images", []),
                    audio_refs=q_data.get("audio_refs", []),
                    question_audio=q_data.get("question_audio", []),
                    answer_audio=q_data.get("answer_audio", []),
                    video_refs=q_data.get("video_refs", []),
                    question_videos=q_data.get("question_videos", []),
                    answer_videos=q_data.get("answer_videos", []),
                    visual_clues=q_data.get("visual_clues"),
                    audio_transcript=q_data.get("audio_transcript"),
                    video_transcript=q_data.get("video_transcript"),
                    raw_media_refs=q_data.get("raw_media_refs", []),
                    source_slide_range=q_data.get("source_slide_range"),
                    duplicate_status=q_data.get("duplicate_status", "UNIQUE"),
                    duplicate_similarity=q_data.get("duplicate_similarity"),
                    duplicate_of_id=q_data.get("duplicate_of_id"),
                    embedding=emb
                )
                db.add(q_obj)
                question_models.append(q_obj)

            # Assign question ids now: the metadata rows and the tagger both key on questions.id.
            db.flush()

            for q_m, q_data in zip(question_models, unique_candidates):
                ensure_question_metadata(db, q_m, q_data.get("_meta"), deck_row, doc)
            db.commit()                             # questions + metadata durable; tagging is its own phase
            saved_question_ids = [q_m.id for q_m in question_models]

            # Auto-tag newly ingested questions with chunked, review-gated batch tagger (v6: topic paths, geography, year).
            done = {"n": 0, "failed": 0, "first_error": None}
            if USE_QSHALA_TAGGER and question_models:
                total = len(question_models)
                INGESTION_STATUS_REGISTRY[document_id]["current_step"] = f"8. Tagging questions (chunked batch {total})"
                progress.update(INGESTION_STATUS_REGISTRY[document_id],
                                detail=f"AI tagging: Classifying {total} questions in chunked batches...")

                t_tag_start = time.perf_counter()
                try:
                    raise_if_cancelled(document_id)
                    tag_stats = await tag_deck_batched(
                        db,
                        question_models,
                        provider=self.qshala_tagger.provider,
                        model=self.qshala_tagger.model,
                        actor="deck_upload",
                        rpm=getattr(self.qshala_tagger, "rpm", 0.0),
                    )
                    t_tag_elapsed = time.perf_counter() - t_tag_start
                    logger.info("Tagging: %d questions in %.1fs: %s", len(question_models), t_tag_elapsed, tag_stats)
                    done["n"] = len(question_models)
                    progress.update(INGESTION_STATUS_REGISTRY[document_id],
                                    detail=f"AI tagging: {total} questions processed in {t_tag_elapsed:.1f}s ({tag_stats.get('confirmed', 0)} confirmed, {tag_stats.get('draft', 0)} in review queue).")
                except IngestionCancelled:
                    raise
                except Exception as q_tag_err:
                    logger.warning(f"Batch tagging failed: {safe_error(q_tag_err)}")
                    done["failed"] = total
                    done["first_error"] = safe_error(q_tag_err)[:300]
                    progress.event(INGESTION_STATUS_REGISTRY[document_id],
                                   f"AI tagging error: {safe_error(q_tag_err)[:160]}")
                    for q_m in question_models:
                        db.add(QuestionEditHistory(
                            question_id=q_m.id, field="tagging", old_value=None,
                            new_value=f"Tagging failed: {safe_error(q_tag_err)[:300]}",
                            kind="TAG_ERROR", actor="deck_upload"
                        ))

            _trim_memory()
            _log_mem("after tagging")

            doc.question_count = len(question_models)
            doc.processing_status = "COMPLETED"
            db.commit()

            _log_mem("end of pipeline")

            progress.event(INGESTION_STATUS_REGISTRY[document_id], f"Saved {len(saved_question_ids)} questions", detail="Finishing up")
            _tag_note = ""
            if USE_QSHALA_TAGGER and saved_question_ids and done.get("failed"):
                _tag_note = f" (AI tagging failed for {done['failed']} of {len(saved_question_ids)}: {done['first_error']})"
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 100,
                "status": "COMPLETED",
                "current_step": "Ingestion completed successfully" + _tag_note,
                "slides_processed": len(slide_models),
                "questions_extracted": len(saved_question_ids),
                "duplicates_filtered": len(duplicates)
            })

        except IngestionCancelled:
            logger.info(f"[CANCEL] ingestion of {document_id} cancelled by user, cleaning up")
            try:
                db.rollback()
            except Exception:
                pass
            with SessionLocal() as cancel_db:
                purge_document(cancel_db, document_id)
            clear_doc_cancel(document_id)
            INGESTION_STATUS_REGISTRY[document_id].update({
                "status": "CANCELLED",
                "error": None,
                "current_step": "Upload cancelled",
            })
        except Exception as e:
            logger.exception(f"Error processing document {document_id}: {e}")
            try:
                with SessionLocal() as err_db:
                    err_doc = err_db.query(Document).filter(Document.id == document_id).first()
                    if err_doc:
                        err_doc.processing_status = "FAILED"
                        err_doc.processing_error = str(e)
                        err_db.commit()
            except Exception as mark_err:
                logger.warning(f"Failed to record FAILED status on document {document_id}: {mark_err}")

            INGESTION_STATUS_REGISTRY[document_id].update({
                "status": "FAILED",
                "error": str(e),
                "current_step": f"Error: {str(e)}"
            })
        finally:
            if own_session and db is not None:
                try:
                    db.close()
                except Exception:
                    pass
