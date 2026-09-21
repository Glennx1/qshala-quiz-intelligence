import os
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.services.ingestion.pptx_parser import PPTXParser
from backend.app.services.ingestion.pdf_parser import PDFParser
from backend.app.services.ingestion.slide_classifier import SlideClassifier
from backend.app.services.ingestion.question_extractor import QuestionExtractor
from backend.app.services.tagging.auto_tagger import AutoTagger
from backend.app.services.tagging.difficulty_engine import DifficultyEngine
from backend.app.services.deduplication.deduplicator import Deduplicator
from backend.app.services.ai.factory import get_embedding_provider

logger = logging.getLogger(__name__)

# Global tracker for real-time progress polling
INGESTION_STATUS_REGISTRY: Dict[str, Dict[str, Any]] = {}

class IngestionPipeline:
    def __init__(self, db: Optional[Session] = None):
        self._external_db = db
        self.classifier = SlideClassifier()
        self.extractor = QuestionExtractor()
        self.auto_tagger = AutoTagger()
        self.difficulty_engine = DifficultyEngine()
        self.deduplicator = Deduplicator()
        self.embedding_provider = get_embedding_provider()

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
                raw_slides = parser.parse()
            elif file_ext == ".pdf":
                parser = PDFParser(doc.storage_path, doc.id)
                raw_slides = parser.parse()
            else:
                raise ValueError(f"Unsupported file format: {file_ext}")

            # Classify each slide
            classified_slides = []
            slide_models = []
            for s in raw_slides:
                slide_type = self.classifier.classify(s)
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
                "current_step": "5. Intelligent multi-topic tagging & difficulty scoring"
            })

            enriched_questions = []
            for q in raw_questions:
                # 1. Multi-topic and entity tagging
                tags_data = self.auto_tagger.tag_question(
                    question_text=q["question_text"],
                    answer_text=q["answer"],
                    explanation=q.get("explanation", ""),
                    doc_title=doc.title
                )
                # 2. Difficulty & Grade evaluation
                diff_data = self.difficulty_engine.evaluate(
                    question_text=q["question_text"],
                    answer_text=q["answer"],
                    explanation=q.get("explanation", ""),
                    notes=q.get("speaker_notes", "")
                )

                q.update({
                    "primary_topic": tags_data["primary_topic"],
                    "topics": tags_data["topics"],
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

            # Step 6: Generate Semantic Embeddings
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 85,
                "current_step": "6. Generating semantic vector embeddings"
            })

            texts_to_embed = [
                f"{q['primary_topic']} {' '.join(q.get('topics') or [])} {q['question_text']} {q['answer']} {q.get('explanation') or ''}"
                for q in enriched_questions
            ]

            embeddings = []
            if texts_to_embed:
                try:
                    embeddings = await self.embedding_provider.get_embeddings(texts_to_embed)
                except Exception as e:
                    logger.warning(f"Embedding generation error ({e}), falling back to unit vectors")
                    embeddings = [[0.0] * 768 for _ in texts_to_embed]

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

            # Step 8: Indexing Unique Records
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 96,
                "current_step": f"8. Storing {len(unique_candidates)} unique questions ({len(duplicates)} replicas linked)"
            })

            question_models = []
            for q_data in unique_candidates:
                # Find matching embedding
                emb = None
                try:
                    orig_idx = enriched_questions.index(q_data)
                    emb = embeddings[orig_idx] if 0 <= orig_idx < len(embeddings) else None
                except Exception:
                    pass

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
                    embedding=emb
                )
                db.add(q_obj)
                question_models.append(q_obj)

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
