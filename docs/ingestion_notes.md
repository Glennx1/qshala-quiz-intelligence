# Ingestion, Batch Tagging, Search, and Review Architecture Notes (Phase 5)

This document satisfies the Phase 5 discovery requirement from `QSHALA_PLAN.md` (§Phase 5):
> "First **discover**: read the existing upload/ingestion code and the existing question search/list endpoints. Write `docs/ingestion_notes.md` describing where questions are created from a deck, how metadata is stored, and how migrations are handled (Alembic or `create_all`). Report this before building anything."

---

## 1. Where Questions are Created from Decks

The ingestion pipeline lives in `backend/app/services/ingestion/`:

1. **Upload & File Handling** (`backend/app/routers/documents.py`):
   - Accepts `.pptx`, `.ppt`, and `.pdf` files.
   - On Vercel Serverless, file size is capped at 4.5 MB (`MAX_FILE_SIZE_BYTES = 4.5 MB`); large files are streamed via `/upload-chunk` or uploaded locally (up to 1 GB).
   - Generates a UUID `doc_id`, saves to `backend/storage/uploads/<doc_id>.<ext>`, creates a `Document` record with status `PROCESSING`, and schedules `pipeline.run(doc_id)` via FastAPI `BackgroundTasks`.

2. **Slide Parsing** (`pptx_parser.py` / `pdf_parser.py`):
   - Extracts raw slide text, shapes, tables, speaker notes, and embedded visual media.
   - Images are extracted into `backend/storage/slides/<doc_id>/` and referenced as static paths `/static/slides/...`.

3. **Slide Classification** (`slide_classifier.py`):
   - Runs a 2-pass contextual deck classifier over all slides.
   - Classifies slides into types: `QUESTION`, `ANSWER`, `TITLE`, `ROUND_HEADER`, `RULES`, `SPONSOR`, `SCOREBOARD`, etc.

4. **Question Extraction** (`question_extractor.py`):
   - Pairs `QUESTION` slides with corresponding `ANSWER` slides based on slide sequence, title similarity, and round markers.
   - Extracts question text, answer, options (if MCQ), hints, and explanation.

5. **Legacy Pipeline Tagging vs. QShala Domain Tagging**:
   - In `pipeline.py` (lines 180–197), the legacy pipeline calls `AutoTagger.tag_question()` and `DifficultyEngine.evaluate()`. This is where generic labels like `"Maths & Logic"` and `"General Knowledge"` originated.
   - **QShala Integration**: For QShala/Zerodha Varsity decks, after questions are saved to the `questions` table, the ingestion pipeline triggers QShala tagging (`QshalaTagger`), populating `qshala_question_metadata` and `qshala_tags`.

---

## 2. Metadata Storage & Database Schema

### Existing Core Tables
- `documents`: Stores document ID, filename, clean title, year, file type, file size, slide count, question count, and processing status.
- `slides`: Stores slide number, slide type, title, extracted text, speaker notes, and image paths.
- `questions`: Stores core quiz attributes (`question_text`, `answer`, `options`, `explanation`, `topic`, `subtopic`, `difficulty`, `grade_min`, `grade_max`, `image_refs`, `video_refs`, `duplicate_status`).

### QShala Extension Tables (`backend/app/models/qshala_tag.py`)
Keyed on `questions.id` (`CASCADE` delete):

1. **`qshala_question_metadata`**:
   - Stores deck-level and tournament metadata that `questions` lacks:
     - `round_stage`: `Prelims` | `Finals` | `Theme` | `Warmup`
     - `question_format`: `QuestionAnswer` | `Written` | `Audio` | `Video` | `Visual`
     - `media_type`: `IMAGE` | `AUDIO` | `VIDEO` | `NONE`
     - `quiz_name`, `college_institution`, `source_presentation`, `source_date`
     - `primary_audience`, `secondary_audience`, `star_marked`

2. **`qshala_tags`** (Versioned Tagging History):
   - One row per tagging run (`source` = `LLM`, `RULE`, `NEIGHBOUR`, `HUMAN`).
   - Active tag is the latest row with `status = 'confirmed'`.
   - Captures: `topic_l1`, `subtopic_l2`, `keywords_l3` (JSON list), `secondary_l2` (JSON list), `entity_type`, `city_name`, `geo_region`, `india_international`, `shelf_life`, `sensitivity`, `fit`, `confidence`, `search_summary`.
   - Audit & Cost metadata: `model_version`, `taxonomy_version`, `tokens_in`, `tokens_out`, `thinking_tokens`, `latency_ms`, `verified_by`, `verified_at`.

3. **`qshala_tag_changes`** (Audit Trail):
   - Logs every status transition (`PROMOTED_TO_CONFIRMED`, `HUMAN_OVERRIDE`, `SUPERSEDED`) with `actor`, `reason`, `from_tag_id`, `to_tag_id`, and timestamp.

---

## 3. Database Migration Strategy

### Current Mechanism: `ensure_schema_columns()` in `database.py`
The project does **not** use Alembic. Instead, it relies on:
1. `Base.metadata.create_all(bind=engine)`: Creates any newly declared tables (`qshala_tags`, `qshala_question_metadata`, `qshala_tag_changes`).
2. `ensure_schema_columns()`: A lightweight schema migration function executed on application startup that inspects `sqlite_master` or PostgreSQL `information_schema` and issues idempotent `ALTER TABLE ... ADD COLUMN ...` statements if new columns were added to existing models.

### PostgreSQL & SQLite Compatibility
- Dialect checks normalize `postgres://` to `postgresql://`.
- Vector embeddings use `pgvector.sqlalchemy.Vector` on Postgres and fall back to `VectorType` (JSON-serialized text) on SQLite.
- All new QShala tables use standard ANSI SQL types (`VARCHAR`, `INTEGER`, `FLOAT`, `BOOLEAN`, `TEXT`, `JSON`, `TIMESTAMP WITH TIME ZONE`) with indexes on all filtered columns (`topic_l1`, `subtopic_l2`, `entity_type`, `india_international`, `shelf_life`, `sensitivity`, `status`).

---

## 4. Batch Tagging Under Serverless & Free-Tier Quota Limits

### Deployment & Runtime Constraints
1. **Vercel Serverless Timeouts**:
   - Vercel functions terminate after **10 seconds** (Hobby/Free) or **60–300 seconds** (Pro).
   - Tagging 100 questions via Gemini Flash-Lite takes ~200–250 seconds (each call takes 1.5–2.5s).
   - Therefore, a single monolithic request cannot tag an entire 100-question presentation in one HTTP call.

2. **Gemini API Rate Limits**:
   - Free Tier: 15 RPM, 500 requests per day.
   - Throttling: Must maintain at least 1.0s – 1.5s delay between sequential calls to prevent HTTP 429 rate limit errors.

### Batch Tagging Design: Chunked Ingestion & Status Tracking
To guarantee reliability across both local servers and serverless deployments:

- **Endpoint**: `POST /qshala/batch-tag`
  - Accepts `{ "document_id": "...", "chunk_size": 10, "offset": 0, "throttle_seconds": 1.0 }`
  - Returns `{ "document_id": "...", "processed": 10, "remaining": 25, "total": 35, "status": "IN_PROGRESS" }`
  - This allows the frontend (or background runner) to tag in incremental safe chunks (e.g., 5–10 questions per batch), displaying a live progress bar without hitting serverless timeouts.

- **Idempotency & Human Protection**:
  - If a question already has a tag with `status = 'confirmed'` where `source = 'HUMAN'`, batch tagging **skips** it completely.
  - If an LLM tag already exists for the same question with the same model version, it reuses or supersedes cleanly without creating duplicates.

- **Resilience**:
  - Wrapped with exponential backoff on HTTP 429 / 503 errors.
  - Per-question failure isolation: If question #14 fails, #15 continues tagging. Question #14 is flagged as `draft` with `fit = 'none'` and notes explaining the failure.

- **Per-Deck Token & Cost Totals**:
  - Aggregated via `GET /qshala/deck/{doc_id}/tag-summary`: returns total questions, count confirmed, count draft, total input tokens, output tokens, total latency, and estimated cost in INR.

---

## 5. Search, Filter, and Review API Specification

### 1. Question Search & Filter (`GET /qshala/questions`)
- Filter by `topic_l1`, `subtopic_l2`, `india_international`, `shelf_life`, `sensitivity`, `entity_type`, `status` (`confirmed` | `draft`).
- Full-text search across `question_text`, `answer`, and `search_summary`.
- Returns paginated results with question payload and current active tag.

### 2. Review Queue (`GET /qshala/review-queue`)
- Retrieves all questions with `status = 'draft'`, sorted by `confidence ASC` (hardest / lowest-confidence questions first).
- Returns candidate predictions, suggested alternative L2s (`secondary_l2`), and routing reason.

### 3. Review Actions:
- `POST /qshala/tag/{question_id}/human`:
  - Reviewer submits corrections or approves tag.
  - Inserts new row with `source = 'HUMAN'`, `status = 'confirmed'`, `verified_by = actor`.
  - Marks previous draft/confirmed rows as `superseded`.
  - Writes audit record to `qshala_tag_changes`.
- `POST /qshala/review/bulk-accept`:
  - Accepts multiple draft tags in one atomic transaction for fast batch review.
- `GET /qshala/taxonomy`:
  - Returns complete v4 taxonomy tree with 8 L1 domains, 38 L2 subtopics, and official definitions.

---

## 6. Frontend Integration Plan (Phase 6)

1. **Dedicated `/review` Page**:
   - Fast, distraction-free keyboard-driven review UI.
   - Shows Question text, Answer, primary predicted L1/L2, `secondary_l2` alternatives, confidence score, routing reason.
   - Hotkeys:
     - <kbd>A</kbd>: Accept recommended tag
     - <kbd>1</kbd>–<kbd>3</kbd>: Pick alternative subtopic
     - <kbd>J</kbd> / <kbd>K</kbd>: Next / Previous
     - <kbd>S</kbd>: Skip to next
   - Dropdown of all 38 L2 subtopics with on-hover descriptions for manual correction.

2. **Knowledge Base Explorer (`/knowledge-base`)**:
   - Adds QShala Domain taxonomy filters (Domain L1, Subtopic L2, Geographic Scope, Shelf Life, Sensitivity) to the existing vault search.
