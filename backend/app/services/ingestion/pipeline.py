import os
import asyncio
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
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
from backend.app.services.tagging.auto_tagger import AutoTagger  # Kept for backward compatibility
from backend.app.services.tagging.qshala_tagger import QshalaTagger
from backend.app.services.tagging.difficulty_engine import DifficultyEngine

# Feature toggle: set to False to revert to legacy AutoTagger writing topic tags on upload
USE_QSHALA_TAGGER: bool = True
from backend.app.services.deduplication.deduplicator import Deduplicator
from backend.app.services.ai.factory import get_embedding_provider, get_llm_provider

logger = logging.getLogger(__name__)

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
            "error": None
        }

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

            file_ext = os.path.splitext(doc.filename)[1].lower()
            
            # Step 1 & 2: Extracting and Processing Slides
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 20,
                "current_step": "2. Processing slides and extracting visual assets"
            })

            if file_ext in [".pptx", ".ppt"]:
                parser = PPTXParser(doc.storage_path, doc.id)
                parser.should_cancel = lambda: doc_cancel_requested(document_id)
                # Parse in a worker thread: it is blocking, and on a big deck it would otherwise
                # freeze the event loop so a Cancel request couldn't even be received.
                raw_slides = await asyncio.to_thread(parser.parse)
            elif file_ext == ".pdf":
                parser = PDFParser(doc.storage_path, doc.id)
                raw_slides = await asyncio.to_thread(parser.parse)
            else:
                raise ValueError(f"Unsupported file format: {file_ext}")

            raise_if_cancelled(document_id)

            # Classify each slide using 2-pass contextual deck classifier
            classified_slides = []
            slide_models = []
            deck_types = self.classifier.classify_deck(raw_slides)

            for s, slide_type in zip(raw_slides, deck_types):
                s["slide_type"] = slide_type
                classified_slides.append(s)

                slide_obj = Slide(
                    document_id=doc.id,
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
            doc.slide_count = len(slide_models)
            
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 45,
                "slides_processed": len(slide_models),
                "current_step": "3. Detecting questions and quiz patterns"
            })

            # Map slide objects back to classified slides with IDs
            for i, s_model in enumerate(slide_models):
                classified_slides[i]["id"] = s_model.id

            # Step 3, 4, 5: Question Extraction & Classification
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 60,
                "current_step": "4. Detecting answers, options, and difficulty levels"
            })

            raw_questions = self.extractor.extract_from_slides(
                classified_slides,
                doc_title=doc.title,
                doc_year=doc.year
            )

            # Step 5: Multi-Topic Auto-Tagging & Pedagogical Difficulty Scoring
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 75,
                "questions_extracted": len(raw_questions),
                "current_step": "5. Multimodal visual inspection & intelligent tagging"
            })

            enriched_questions = []
            for q in raw_questions:
                raise_if_cancelled(document_id)
                # 0. Multimodal Visual Clues Inspection
                visual_clues_list = []
                # Inspect question images first (and clue images)
                target_imgs = list(q.get("question_images") or q.get("image_refs") or [])
                for rel_img_path in target_imgs:
                    disk_path = None
                    img_bytes = None
                    ext = None

                    if rel_img_path.startswith("http://") or rel_img_path.startswith("https://"):
                        # Media stored in Cloudflare R2 (or any other remote object store) --
                        # the local disk copy may not exist on this instance, so fetch over HTTP.
                        try:
                            import httpx as _httpx
                            async with _httpx.AsyncClient(timeout=30.0) as client:
                                resp = await client.get(rel_img_path)
                                resp.raise_for_status()
                                img_bytes = resp.content
                            ext = os.path.splitext(rel_img_path)[1].lower()
                        except Exception as fetch_err:
                            logger.warning(f"Failed to fetch remote image {rel_img_path}: {fetch_err}")
                            continue
                    elif rel_img_path.startswith("/static/slides/"):
                        sub = rel_img_path[len("/static/slides/"):]
                        cand = settings.SLIDES_DIR / sub
                        if cand.exists():
                            disk_path = cand
                    elif rel_img_path.startswith("/static/"):
                        cand = settings.STORAGE_DIR / rel_img_path.lstrip("/static/")
                        if cand.exists():
                            disk_path = cand

                    if img_bytes is None and disk_path and disk_path.exists():
                        try:
                            with open(disk_path, "rb") as f:
                                img_bytes = f.read()
                            ext = disk_path.suffix.lower()
                        except Exception as read_err:
                            logger.warning(f"Failed to read local image {rel_img_path}: {read_err}")
                            continue

                    if img_bytes:
                        try:
                            mime = "image/png" if ext == ".png" else ("image/jpeg" if ext in [".jpg", ".jpeg"] else "image/webp")
                            desc = await self.llm_provider.describe_image(img_bytes, mime_type=mime)
                            if desc and desc.strip():
                                visual_clues_list.append(desc.strip())
                        except Exception as vision_err:
                            logger.warning(f"Failed to describe image {rel_img_path}: {vision_err}")

                visual_clues_str = "\n".join(visual_clues_list) if visual_clues_list else None
                q["visual_clues"] = visual_clues_str

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
                        doc_title=doc.title,
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
                f"{q['primary_topic']} {' '.join(q.get('topics') or [])} {q['question_text']} {q['answer']} {q.get('visual_clues') or ''} {q.get('explanation') or ''}".strip()
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

            # Step 7: Deduplication Check (Tier 1 O(1) Hash + Tier 2 Semantic ANN)
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 92,
                "current_step": "7. Deduplicating questions against knowledge base"
            })

            unique_candidates, duplicates = self.deduplicator.deduplicate_batch(
                db=db,
                candidates=enriched_questions,
                candidate_embeddings=embeddings,
                doc_id=doc.id
            )

            raise_if_cancelled(document_id)

            # Step 8: Indexing Unique Records
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 96,
                "current_step": f"8. Storing {len(unique_candidates)} unique questions ({len(duplicates)} replicas linked)"
            })

            question_models = []
            for q_data in unique_candidates:
                # Find matching embedding
                orig_idx = q_data.get("_emb_idx")
                emb = embeddings[orig_idx] if orig_idx is not None and 0 <= orig_idx < len(embeddings) else None

                q_obj = Question(
                    content_hash=q_data["content_hash"],
                    document_id=doc.id,
                    slide_id=q_data.get("slide_id"),
                    answer_slide_id=q_data.get("answer_slide_id"),
                    question_text=q_data["question_text"],
                    answer=q_data["answer"],
                    options=q_data.get("options"),
                    explanation=q_data.get("explanation"),
                    topic=q_data["primary_topic"],
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
                    provenance_decks=[{"document_id": doc.id, "slide_id": q_data.get("slide_id")}],
                    occurrence_count=1,
                    question_type=q_data.get("question_type", "SLIDE_QA"),
                    source_year=q_data.get("source_year", doc.year),
                    round_number=q_data.get("round_number"),
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

            # Auto-tag newly ingested questions with QshalaTagger (v5.1 multi-tag)
            if USE_QSHALA_TAGGER:
                for q_m in question_models:
                    try:
                        q_tag = await self.qshala_tagger.tag(
                            db=db,
                            question_id=q_m.id,
                            question_text=q_m.question_text,
                            answer=q_m.answer,
                            actor="deck_upload",
                            commit=False
                        )
                        if q_tag and q_tag.topic_l1:
                            q_m.topic = q_tag.topic_l1
                            q_m.subtopic = q_tag.subtopic_l2
                            q_m.topics = [q_tag.topic_l1]
                        if q_tag and q_tag.keywords_l3:
                            q_m.tags = q_tag.keywords_l3
                    except Exception as q_tag_err:
                        logger.warning(f"QshalaTagger failed during ingestion for question {q_m.id}: {q_tag_err}")

            doc.question_count = len(question_models)
            doc.processing_status = "COMPLETED"
            db.commit()

            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 100,
                "status": "COMPLETED",
                "current_step": "Ingestion completed successfully",
                "slides_processed": len(slide_models),
                "questions_extracted": len(question_models),
                "duplicates_filtered": len(duplicates)
            })

        except IngestionCancelled:
            logger.info(f"[CANCEL] ingestion of {document_id} cancelled by user, cleaning up")
            try:
                db.rollback()
            except Exception:
                pass
            purge_document(db, document_id)
            clear_doc_cancel(document_id)
            INGESTION_STATUS_REGISTRY[document_id].update({
                "status": "CANCELLED",
                "error": None,
                "current_step": "Upload cancelled",
            })
        except Exception as e:
            logger.exception(f"Error processing document {document_id}: {e}")
            try:
                db.rollback()
                doc.processing_status = "FAILED"
                doc.processing_error = str(e)
                db.commit()
            except Exception:
                pass

            INGESTION_STATUS_REGISTRY[document_id].update({
                "status": "FAILED",
                "error": str(e),
                "current_step": f"Error: {str(e)}"
            })
        finally:
            if own_session:
                try:
                    db.close()
                except Exception:
                    pass
