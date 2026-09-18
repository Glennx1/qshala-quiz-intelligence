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
from backend.app.services.ai.factory import get_embedding_provider

logger = logging.getLogger(__name__)

# Global tracker for real-time progress polling
INGESTION_STATUS_REGISTRY: Dict[str, Dict[str, Any]] = {}

class IngestionPipeline:
    def __init__(self, db: Session):
        self.db = db
        self.classifier = SlideClassifier()
        self.extractor = QuestionExtractor()
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

        doc = self.db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            INGESTION_STATUS_REGISTRY[document_id]["status"] = "FAILED"
            INGESTION_STATUS_REGISTRY[document_id]["error"] = "Document not found"
            return

        try:
            doc.processing_status = "PROCESSING"
            self.db.commit()

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
                self.db.add(slide_obj)
                slide_models.append(slide_obj)

            self.db.flush()  # Assign slide IDs
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

            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 75,
                "questions_extracted": len(raw_questions),
                "current_step": "5. Categorizing topics and estimating grade suitability"
            })

            # Step 6: Generate Embeddings
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 85,
                "current_step": "6. Generating semantic vector embeddings"
            })

            texts_to_embed = [
                f"{q['topic']} {q['question_text']} {q['answer']} {' '.join(q.get('options') or [])}"
                for q in raw_questions
            ]

            embeddings = []
            if texts_to_embed:
                try:
                    embeddings = await self.embedding_provider.get_embeddings(texts_to_embed)
                except Exception as e:
                    logger.warning(f"Embedding generation error ({e}), falling back to unit vectors")
                    embeddings = [[0.0] * 768 for _ in texts_to_embed]

            # Step 7: Indexing & Persistence
            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 95,
                "current_step": "7. Indexing structured records in knowledge base"
            })

            question_models = []
            for i, q_data in enumerate(raw_questions):
                emb = embeddings[i] if i < len(embeddings) else None
                q_obj = Question(
                    document_id=doc.id,
                    slide_id=q_data["slide_id"],
                    answer_slide_id=q_data.get("answer_slide_id"),
                    question_text=q_data["question_text"],
                    answer=q_data["answer"],
                    options=q_data.get("options"),
                    explanation=q_data.get("explanation"),
                    topic=q_data["topic"],
                    subtopic=q_data.get("subtopic"),
                    difficulty=q_data.get("difficulty", "Medium"),
                    grade_min=q_data.get("grade_min", 3),
                    grade_max=q_data.get("grade_max", 12),
                    question_type=q_data.get("question_type", "MULTIPLE_CHOICE"),
                    source_year=q_data.get("source_year", doc.year),
                    embedding=emb
                )
                self.db.add(q_obj)
                question_models.append(q_obj)

            doc.question_count = len(question_models)
            doc.processing_status = "COMPLETED"
            self.db.commit()

            INGESTION_STATUS_REGISTRY[document_id].update({
                "progress_percentage": 100,
                "status": "COMPLETED",
                "current_step": "Ingestion completed successfully",
                "slides_processed": len(slide_models),
                "questions_extracted": len(question_models)
            })

        except Exception as e:
            logger.exception(f"Error processing document {document_id}: {e}")
            self.db.rollback()
            doc.processing_status = "FAILED"
            doc.processing_error = str(e)
            self.db.commit()

            INGESTION_STATUS_REGISTRY[document_id].update({
                "status": "FAILED",
                "error": str(e),
                "current_step": f"Error: {str(e)}"
            })
