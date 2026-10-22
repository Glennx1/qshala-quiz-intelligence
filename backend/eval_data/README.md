# QShala tagger — backend changes

This branch adds a QShala-domain tagger (business, finance, brands, Indian context) alongside the
existing world-knowledge auto-tagger. The existing tagger is untouched; nothing in production
behaviour changes until the new endpoints are called.

## What's new

| File | Purpose |
|---|---|
| `backend/app/services/tagging/qshala_taxonomy_v4.json` | Controlled vocabulary: 8 L1 topics, 38 L2 subtopics with descriptions |
| `backend/app/services/tagging/qshala_rules.py` | Free, deterministic signals — city dictionary, brand hints, year patterns, image-dependence detection |
| `backend/app/services/tagging/qshala_tagger.py` | The orchestrator: rules → duplicate check → Gemini call → routing → DB row |
| `backend/app/models/qshala_tag.py` | Three new tables (metadata, tags, change log) — see schema notes below |
| `backend/app/routers/qshala_tagging.py` | HTTP: POST tag, GET history, POST human override, GET review queue |
| `backend/eval_qshala_tagger.py` | Standalone eval. Runs the real tagger over 145 gold questions; writes report.md |
| `backend/eval_data/gold_labels_145.csv` | Reference tags (20 verified + 125 silver) |
| `backend/app/services/ai/gemini_provider.py` | Added `generate_json_schema()` — enum-constrained response, per-call model override, token usage |

## Schema (three new tables, nothing on `questions` changes)

```
qshala_question_metadata        -- 1:1 with questions, holds Excel ingestion fields
qshala_tags                     -- 1:N with questions, append-only tag runs
qshala_tag_changes              -- audit trail for every status transition
```

The current tag for a question is the newest `qshala_tags` row where `status = 'confirmed'`.
A human-confirmed row is never overwritten by the tagger — the pipeline sees it and returns
immediately.

## Env

```
QSHALA_TAGGER_MODEL=gemini-3.5-flash-lite   # defaults to this; override here if Google renames it
GEMINI_API_KEY=...                           # free tier is fine for the eval
```

## Running the eval

From the repo root:

```
# smoke test
python backend/eval_qshala_tagger.py --limit 10 --throttle 1.0

# full 145 questions
python backend/eval_qshala_tagger.py --throttle 1.0

# compare to 2.5 Flash as a ceiling check
python backend/eval_qshala_tagger.py --model gemini-2.5-flash --throttle 1.0
```

The eval uses an isolated temp SQLite file — it never touches the real dev or prod DB.
Output lands in `backend/eval_data/results/eval_<timestamp>/`:
- `report.md` — accuracy per slice (verified / silver / all), routing stats, cost, latency, every mistake
- `per_question.csv` — one row per question with gold/pred/match/status/confidence/tokens
- `raw.jsonl` — raw Gemini output for every call

## What the report tells you

- **VERIFIED (20)** rows are the real signal — these labels were reviewed by a quizmaster.
- **SILVER (125)** rows are directional only — labels are first-pass, differences of a few points are noise.
- **Auto-confirmed %** — what the pipeline would hand back without review.
- **L2 strict on auto-confirmed** — the number that matters most. If this falls below ~95%, tighten the routing thresholds in `qshala_tagger.py:_route`.

## Follow-up work (not in this branch)

- Frontend review page at `/review` listing the review queue; types + API helpers for it are in `frontend/src/lib/`.
- Ingestion-side change: populate `qshala_question_metadata` on upload (reading answer_type, round_stage etc. from the deck).
- Optional: add pgvector-backed kNN as a NEIGHBOUR signal once there are enough confirmed questions (≥500).
