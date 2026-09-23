import asyncio
import os
import sys
import shutil
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.models.quiz import Quiz
from backend.app.services.ingestion.pipeline import IngestionPipeline
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever
from backend.app.services.generator.quiz_generator import QuizGenerator
from backend.app.schemas.quiz import QuizGenerateRequest, QuestionActionRequest
from backend.app.services.export.exporter import QuizExporter
from backend.app.config import settings

async def main():
    print("=== STARTING END-TO-END VERIFICATION TEST ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Step 1: Ingest sample PPTX deck
    sample_file = Path(settings.STORAGE_DIR).parent / "sample_decks" / "Australian_History_Quiz_2022.pptx"
    assert sample_file.exists(), f"Sample deck not found at {sample_file}"

    doc_id = "test-doc-aust-hist-001"
    # Clean up previous test runs for a clean slate
    db.query(Question).delete()
    db.query(Slide).delete()
    db.query(Document).delete()
    db.commit()

    dest_file = settings.UPLOAD_DIR / f"{doc_id}.pptx"
    shutil.copyfile(sample_file, dest_file)

    doc = Document(
        id=doc_id,
        filename="Australian_History_Quiz_2022.pptx",
        title="Australian History & Explorers 2022",
        year=2022,
        file_type="pptx",
        storage_path=str(dest_file),
        file_size_bytes=dest_file.stat().st_size,
        processing_status="PROCESSING"
    )
    db.add(doc)
    db.commit()

    print("\n[1] Running Document Ingestion Pipeline...")
    pipeline = IngestionPipeline(db)
    await pipeline.run(doc_id)

    db.refresh(doc)
    print(f" -> Document Status: {doc.processing_status}")
    print(f" -> Slides Extracted: {doc.slide_count}")
    print(f" -> Questions Extracted: {doc.question_count}")
    assert doc.processing_status == "COMPLETED", "Ingestion failed!"
    assert doc.slide_count >= 20, f"Expected >= 20 slides, got {doc.slide_count}"
    assert doc.question_count >= 10, f"Expected >= 10 questions, got {doc.question_count}"

    # Step 2: Test Hybrid Retrieval
    print("\n[2] Testing Hybrid Semantic + Lexical Retrieval...")
    retriever = HybridRetriever(db)
    results = await retriever.search(
        query="Australian indigenous history and dreamtime",
        topic="Australian History",
        grade_min=3,
        grade_max=5,
        limit=5
    )
    print(f" -> Found {len(results)} relevant historical candidates:")
    for r in results:
        q = r["question"]
        print(f"    * [Score {r['relevance_score']}] {q.question_text[:70]}... (Answer: {q.answer})")
    assert len(results) > 0, "Retrieval returned 0 results"

    # Step 3: Test Quiz Generation (10 questions, Australian History, Grades 3-5, Medium)
    print("\n[3] Generating Quiz: '10-question Australian History for Grades 3-5, medium difficulty'...")
    req = QuizGenerateRequest(
        topic="Australian History",
        grade_min=3,
        grade_max=5,
        difficulty="Medium",
        question_count=10,
        question_types=["MULTIPLE_CHOICE"],
        generation_mode="NEW"
    )

    generator = QuizGenerator(db)
    quiz = await generator.generate_quiz(req)
    print(f" -> Created Quiz: '{quiz.title}' (ID: {quiz.id})")
    print(f" -> Total Questions in Quiz: {len(quiz.questions)}")
    assert len(quiz.questions) == 10, f"Expected 10 generated questions, got {len(quiz.questions)}"

    # Inspect question 1
    q1 = quiz.questions[0]
    print(f"\n[4] Inspecting Generated Question #1:")
    print(f"    Question: {q1.question_text}")
    print(f"    Options: {q1.options}")
    print(f"    Answer: {q1.answer}")
    print(f"    Explanation: {q1.explanation}")
    print(f"    Validation Status: {q1.validation_status}")
    print(f"    Validation Details: {q1.validation_details}")
    print(f"    Duplicate Risk Score: {q1.duplicate_score}")
    print(f"    Source Provenance Count: {len(q1.retrieval_sources)}")
    if q1.retrieval_sources:
        src = q1.retrieval_sources[0]
        print(f"    Primary Provenance: {src.document_title} (Slide {src.slide_number})")
        print(f"    Source Quote: {src.source_quote}")

    assert q1.validation_status in ["PASSED", "WARNING"]
    assert len(q1.retrieval_sources) > 0, "No provenance sources attached!"

    # Step 5: Test Question Action: Make Easier
    print("\n[5] Testing Question Action: 'make_easier'...")
    updated_q = await generator.execute_question_action(
        question_id=q1.id,
        action="make_easier"
    )
    print(f" -> Updated Question Difficulty: {updated_q.difficulty}")
    print(f" -> Revised Text: {updated_q.question_text}")
    assert updated_q.difficulty == "Easy"

    # Step 6: Test JSON and CSV Export
    print("\n[6] Testing Quiz Exports...")
    json_out = QuizExporter.to_json(quiz)
    csv_out = QuizExporter.to_csv(quiz)
    print(f" -> JSON export generated ({len(json_out)} bytes)")
    print(f" -> CSV export generated ({len(csv_out)} bytes)")
    assert "Australian History" in json_out
    assert "Question" in csv_out

    db.close()
    print("\n=== ALL END-TO-END VERIFICATION CHECKS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(main())
