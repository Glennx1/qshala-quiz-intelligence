import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
from backend.app.models.job import IngestionJob
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.services.jobs.job_queue import JobQueueService
from backend.app.services.storage.blob_storage import VercelBlobService

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def mock_storage(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir(parents=True, exist_ok=True)
    return VercelBlobService(token=None, local_dir=blob_dir)

@pytest.mark.anyio
async def test_job_queue_8_steps_lifecycle(test_db, mock_storage, tmp_path):
    """
    Tests the complete 8-step idempotent lifecycle of JobQueueService:
    DOWNLOAD -> EXTRACT_SLIDES -> EXTRACT_MEDIA -> TRANSCRIBE_OCR -> EMBED -> DEDUP_CHECK -> TAG -> INSERT -> COMPLETED.
    """
    service = JobQueueService(blob_service=mock_storage)
    service.tmp_dir = tmp_path / "scratch"
    service.tmp_dir.mkdir(parents=True, exist_ok=True)

    # Locate sample deck
    root_deck = Path(__file__).resolve().parent.parent.parent / "QShala_General_World_Quiz_20Q.pptx"
    assert root_deck.exists(), f"Sample deck not found at {root_deck}"

    # Stage deck into mock blob storage
    with open(root_deck, "rb") as f:
        deck_bytes = f.read()

    put_res = await mock_storage.put("sample_tournament.pptx", deck_bytes)
    blob_url = put_res["url"]

    # Create IngestionJob
    job = IngestionJob(
        source_type="SHAREPOINT",
        source_file_id="sp_test_file_999",
        filename="sample_tournament.pptx",
        blob_url=blob_url,
        status="PENDING",
        current_step="DOWNLOAD",
        step_data={}
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)

    # Step 1: DOWNLOAD
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "EXTRACT_SLIDES"
    assert "local_path" in job.step_data
    assert Path(job.step_data["local_path"]).exists()

    # Step 2: EXTRACT_SLIDES
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "EXTRACT_MEDIA"
    assert job.document_id is not None
    assert len(job.step_data.get("slides", [])) > 0
    doc = test_db.query(Document).filter_by(id=job.document_id).first()
    assert doc is not None
    assert doc.slide_count > 0

    # Step 3: EXTRACT_MEDIA
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "TRANSCRIBE_OCR"
    assert "media_manifest" in job.step_data

    # Step 4: TRANSCRIBE_OCR
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "EMBED"
    assert "canonical_questions" in job.step_data
    assert len(job.step_data["canonical_questions"]) > 0

    # Step 5: EMBED
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "DEDUP_CHECK"
    assert "embeddings" in job.step_data
    assert len(job.step_data["embeddings"]) == len(job.step_data["canonical_questions"])

    # Step 6: DEDUP_CHECK
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "TAG"
    assert "dedup_candidates" in job.step_data

    # Step 7: TAG
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "INSERT"
    assert "tagged_questions" in job.step_data

    # Step 8: INSERT
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "COMPLETED"
    assert job.status == "COMPLETED"
    assert job.completed_at is not None

    # Verify questions persisted in DB
    db_questions = test_db.query(Question).filter_by(document_id=job.document_id).all()
    assert len(db_questions) > 0
    for q in db_questions:
        assert q.question_text
        assert q.answer
        assert q.topic
        assert q.duplicate_status in ["UNIQUE", "POSSIBLE_DUPLICATE", "CONFIRMED_DUPLICATE"]
        assert q.content_hash is not None
        assert q.embedding is not None, f"Question '{q.question_text[:30]}' must have vector embedding persisted"
        assert len(q.embedding) == 768

@pytest.mark.anyio
async def test_job_queue_multimodal_deck_lifecycle(test_db, mock_storage, tmp_path, monkeypatch):
    """
    Tests JobQueueService processing a deck with multi-modal media:
    - Verifies step_extract_slides does NOT fail on raw_bytes JSON serialization
    - Verifies step_extract_media uploads extracted assets to Blob
    - Verifies step_transcribe_ocr generates Vision OCR description and attaches visual_clues
    - Verifies step_insert saves questions with visual_clues and embeddings into the DB
    """
    from unittest.mock import AsyncMock, MagicMock
    import backend.app.services.jobs.job_queue as jq

    service = JobQueueService(blob_service=mock_storage)
    service.tmp_dir = tmp_path / "scratch_mm"
    service.tmp_dir.mkdir(parents=True, exist_ok=True)

    # Stage fake deck in storage
    put_res = await mock_storage.put("multimodal_tourney.pptx", b"fake pptx zip header")
    job = IngestionJob(
        source_type="SHAREPOINT",
        source_file_id="sp_mm_123",
        filename="multimodal_tourney.pptx",
        blob_url=put_res["url"],
        status="PENDING",
        current_step="DOWNLOAD"
    )
    test_db.add(job)
    test_db.commit()

    # Step 1: DOWNLOAD
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "EXTRACT_SLIDES"

    # Mock PPTXParser to return slides with images and media items
    class MockMultimodalParser:
        def __init__(self, *args, **kwargs): pass
        def parse(self):
            return [
                {
                    "slide_number": 1,
                    "title": "Landmark Question",
                    "extracted_text": "Name the famous tower pictured in the next slide.",
                    "speaker_notes": "",
                    "image_paths": [],
                    "has_images": False,
                    "metadata_json": {}
                },
                {
                    "slide_number": 2,
                    "title": "Clue Slide",
                    "extracted_text": "Constructed in 1889 for the World's Fair.",
                    "speaker_notes": "",
                    "image_paths": ["/static/media/eiffel.jpg"],
                    "has_images": True,
                    "metadata_json": {}
                },
                {
                    "slide_number": 3,
                    "title": "Answer Slide",
                    "extracted_text": "Answer: Eiffel Tower",
                    "speaker_notes": "Located in Paris, France.",
                    "image_paths": [],
                    "has_images": False,
                    "metadata_json": {}
                }
            ]
        def extract_all_media(self):
            return [
                {
                    "filename": "eiffel.jpg",
                    "slide_number": 2,
                    "media_type": "image",
                    "raw_bytes": b"\xff\xd8\xff fake jpeg binary",
                    "mime_type": "image/jpeg"
                }
            ]

    monkeypatch.setattr(jq, "PPTXParser", MockMultimodalParser)

    # Step 2: EXTRACT_SLIDES (Must not crash with TypeError: bytes is not JSON serializable)
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "EXTRACT_MEDIA"

    # Step 3: EXTRACT_MEDIA
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "TRANSCRIBE_OCR"
    assert len(job.step_data.get("media_manifest", [])) == 1

    # Mock Gemini provider for Vision OCR
    mock_llm = MagicMock()
    mock_llm.describe_image = AsyncMock(return_value="Iron lattice tower in Paris, France with tourist crowds")
    monkeypatch.setattr(jq, "get_llm_provider", lambda: mock_llm)

    # Step 4: TRANSCRIBE_OCR
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "EMBED"
    c_qs = job.step_data.get("canonical_questions", [])
    assert len(c_qs) == 1
    assert "Paris" in (c_qs[0].get("visual_clues") or "")

    # Step 5: EMBED
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "DEDUP_CHECK"

    # Step 6: DEDUP_CHECK
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "TAG"

    # Step 7: TAG
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "INSERT"

    # Step 8: INSERT
    await service.execute_step(job, test_db)
    test_db.refresh(job)
    assert job.current_step == "COMPLETED"
    assert job.status == "COMPLETED"

    # Verify DB question record has visual_clues and embedding
    db_q = test_db.query(Question).filter_by(document_id=job.document_id).first()
    assert db_q is not None
    assert db_q.visual_clues is not None
    assert "Paris" in db_q.visual_clues
    assert db_q.embedding is not None
    assert len(db_q.embedding) == 768

