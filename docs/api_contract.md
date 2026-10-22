# QShala Quiz Intelligence — Frozen API Contract & Database Schema

Locked at GATE 1 (2026-10-22). This document serves as the immutable contract between Backend and Frontend for Phases 5 and 6.

---

## 1. Database Schema

All tables are keyed onto the existing `questions.id` (`VARCHAR(36)` UUID).

### 1.1 `qshala_question_metadata`
Stores PPTX deck and round metadata captured during presentation ingestion.
```sql
CREATE TABLE qshala_question_metadata (
    question_id VARCHAR(36) PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    star_marked BOOLEAN DEFAULT FALSE,
    question_number INTEGER,
    answer_type VARCHAR(32),            -- Text | Image | Audio | Video
    media_type VARCHAR(32),             -- IMAGE | AUDIO | VIDEO | NONE
    clue_media_url TEXT,
    reveal_media_url TEXT,
    round_stage VARCHAR(32),            -- Prelims | Finals | Theme | Warmup
    question_format VARCHAR(32),        -- QuestionAnswer | Written | Audio | Video | Visual
    college_institution VARCHAR(255),
    quiz_name VARCHAR(255),
    source_date TIMESTAMP WITH TIME ZONE,
    source_presentation VARCHAR(500),
    primary_audience VARCHAR(64),       -- Inter-College | Intra-College | Corporate | School | Family
    secondary_audience VARCHAR(64),
    language VARCHAR(32) DEFAULT 'English',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 1.2 `qshala_tags`
Append-only log of every tagging run (model run, rule run, or human override).
```sql
CREATE TABLE qshala_tags (
    id VARCHAR(36) PRIMARY KEY,
    question_id VARCHAR(36) NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    taxonomy_version VARCHAR(16) NOT NULL DEFAULT 'v4',
    model_version VARCHAR(64),          -- e.g. 'gemini-3.5-flash-lite' / 'rule-v1' / 'human'
    source VARCHAR(16) NOT NULL,        -- RULE | LLM | NEIGHBOUR | HUMAN

    -- Classification payload
    topic_l1 VARCHAR(100),
    subtopic_l2 VARCHAR(100),
    keywords_l3 JSON,                   -- Array of 4-7 Title Case keywords
    secondary_l2 JSON,                  -- Array of up to 2 alternative L2 subtopics
    entity_type VARCHAR(32),            -- COMPANY | PERSON | TERM | PRODUCT_OR_OBJECT | ...

    city_name VARCHAR(100),
    geo_region VARCHAR(64),
    india_international VARCHAR(16),    -- IN | INTL | MIXED

    shelf_life VARCHAR(24),             -- EVERGREEN | REVIEW_YEARLY | TIME_SENSITIVE
    sensitivity VARCHAR(24),            -- NONE | POLITICAL | MATURE_REFERENCE
    fit VARCHAR(16),                    -- good | weak | none

    search_summary TEXT,                -- <=25 words for search / RAG
    confidence FLOAT,                   -- 0.0 to 1.0
    status VARCHAR(16) NOT NULL DEFAULT 'draft', -- draft | confirmed | superseded

    -- Verification provenance
    verified_by VARCHAR(255),
    verified_at TIMESTAMP WITH TIME ZONE,
    verification_notes TEXT,
    fact_check_url TEXT,

    -- Usage metrics
    tokens_in INTEGER,
    tokens_out INTEGER,
    thinking_tokens INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Essential Performance Indexes
CREATE INDEX ix_qshala_tags_qid ON qshala_tags(question_id);
CREATE INDEX ix_qshala_tags_status ON qshala_tags(status);
CREATE INDEX ix_qshala_tags_source ON qshala_tags(source);
CREATE INDEX ix_qshala_tags_l1 ON qshala_tags(topic_l1);
CREATE INDEX ix_qshala_tags_l2 ON qshala_tags(subtopic_l2);
CREATE INDEX ix_qshala_tags_entity ON qshala_tags(entity_type);
CREATE INDEX ix_qshala_tags_geo ON qshala_tags(india_international);
CREATE INDEX ix_qshala_tags_shelf ON qshala_tags(shelf_life);
CREATE INDEX ix_qshala_tags_sens ON qshala_tags(sensitivity);
CREATE INDEX ix_qshala_tags_created ON qshala_tags(created_at);
CREATE INDEX ix_qshala_tags_current ON qshala_tags(question_id, status, created_at DESC);
```

### 1.3 `qshala_tag_changes`
Append-only audit trail of every status transition.
```sql
CREATE TABLE qshala_tag_changes (
    id VARCHAR(36) PRIMARY KEY,
    question_id VARCHAR(36) NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    from_tag_id VARCHAR(36) REFERENCES qshala_tags(id) ON DELETE SET NULL,
    to_tag_id VARCHAR(36) REFERENCES qshala_tags(id) ON DELETE SET NULL,
    change_type VARCHAR(32) NOT NULL,   -- PROMOTE | SUPERSEDE | HUMAN_OVERRIDE | ROLLBACK
    actor VARCHAR(255),
    reason TEXT,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX ix_qshala_changes_qid ON qshala_tag_changes(question_id);
```

---

## 2. HTTP API Contract

Prefix: `/api/v1/qshala`

### 2.1 `GET /api/v1/qshala/taxonomy`
Returns active Taxonomy v4 hierarchy with descriptions for review dropdowns.
* **Response (200):**
```json
{
  "version": "v4",
  "domains": [
    {
      "l1": "Markets & Investing",
      "subtopics": [
        {"l2": "Stock Markets", "description": "Equities, indices, exchanges..."},
        {"l2": "Quant Trading", "description": "Algorithms, HFT, quant funds..."}
      ]
    }
  ],
  "l1": ["Markets & Investing", "Banking & Money", ...],
  "l2": ["Stock Markets", "Quant Trading", ...],
  "l2_to_l1": {"Stock Markets": "Markets & Investing", ...},
  "l2_descriptions": {"Stock Markets": "...", ...}
}
```

### 2.2 `POST /api/v1/qshala/tag/{question_id}?actor=system`
Runs tagger on one question and stores a new row in `qshala_tags`.
* **Response (200):** Full tag dictionary (see Tag Response Shape below).
* **Errors:** `404 Not Found` (question missing), `502 Bad Gateway` (LLM failure).

### 2.3 `GET /api/v1/qshala/tag/{question_id}`
Returns current confirmed tag, full tag run history, and audit trail.
* **Response (200):**
```json
{
  "current": { ...Tag Response Shape... },
  "history": [ { ...Tag Response Shape... } ],
  "changes": [
    {
      "id": "uuid",
      "change_type": "PROMOTE",
      "actor": "system",
      "reason": "rule signals present and no L1 conflict",
      "from_tag_id": null,
      "to_tag_id": "tag-uuid",
      "changed_at": "2026-10-22T12:00:00Z"
    }
  ]
}
```

### 2.4 `POST /api/v1/qshala/tag/{question_id}/human`
Submits a human review override. Supersedes previous confirmed tag and writes an audit row.
* **Request Body:**
```json
{
  "subtopic_l2": "Stock Markets",
  "secondary_l2": ["Investment Funds"],
  "keywords_l3": ["BSE", "Sensex", "Bombay Stock Exchange"],
  "entity_type": "ORGANISATION",
  "india_international": "IN",
  "city_name": "Mumbai",
  "geo_region": "West India",
  "shelf_life": "EVERGREEN",
  "sensitivity": "NONE",
  "fit": "good",
  "search_summary": "First stock exchange in Asia established under a banyan tree.",
  "fact_check_url": "https://bseindia.com",
  "actor": "quizmaster@walnut.com",
  "notes": "Verified against tournament deck"
}
```
* **Response (200):** Updated tag dictionary with `source = 'HUMAN'` and `status = 'confirmed'`.

### 2.5 `GET /api/v1/qshala/review-queue?limit=50`
Returns draft rows that need quizmaster review, sorted by lowest confidence first.
* **Response (200):** Array of Tag Response objects.

### 2.6 `GET /api/v1/qshala/questions`
Library search and filter API.
* **Query Params:** `topic_l1`, `subtopic_l2`, `india_international`, `shelf_life`, `sensitivity`, `entity_type`, `status` (default: `'confirmed'`), `search` (free-text across question, answer, search_summary), `limit` (default 50), `offset` (default 0).
* **Response (200):**
```json
{
  "total": 145,
  "items": [
    {
      "question": {
        "id": "zvq-blr-001",
        "question_text": "...",
        "answer": "...",
        "document_id": "doc-uuid"
      },
      "tag": { ...Tag Response Shape... }
    }
  ]
}
```

---

## 3. Database Migrations to Postgres

In local development, SQLite tables are auto-created by SQLAlchemy `Base.metadata.create_all(bind=engine)` during app lifespan startup.

For Postgres in staging and production:
1. **Idempotent DDL Migration Script:**
   The exact schema defined above is saved in `backend/migrations/001_qshala_tagging.sql` with `IF NOT EXISTS` guards.
2. **Execution Strategy:**
   - On deployment platforms (Vercel / Supabase), migrations run as a pre-deploy release hook (`python -m backend.run_migrations` or directly via Supabase SQL editor / CLI).
   - Serverless worker functions never run schema alterations at runtime; they connect to the pre-migrated Postgres pool.
