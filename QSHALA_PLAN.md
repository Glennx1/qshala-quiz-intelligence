# QShala — Execution Plan (Brain → Worker)

**Read `QSHALA_HANDOFF.md` first** for the architecture and current state. This file is the plan.

## 0. Roles and rules

- **Brain (Claude, in chat with GB):** sets targets, reviews worker reports at each gate, decides what to change, and says when a phase passes. Decisions about thresholds, taxonomy wording, gold-label disputes and routing design go to the brain.
- **Worker (Antigravity agent):** implements, runs commands, collects numbers, reports back in the format in §0.2. It does not decide whether a gate passed. It reports the numbers against the gate.
- **GB:** the only person who can say "push it", supply the API key, provide new decks, and get quizmaster time for verified labels.

### 0.1 Hard rules for the worker
1. No `git push`, no PR, no deploy unless GB has written "push it" in the current phase. Local commits only when GB agrees.
2. Never print, log, commit or store the Gemini API key. Read it from `GEMINI_API_KEY` only.
3. Never edit `gold_labels_145.csv` silently. Every label change goes in `backend/eval_data/gold_changelog.md` (id, old, new, reason).
4. Do not tune prompts or descriptions against the frozen test split (Phase 2). Use the dev split only.
5. Work one phase at a time **on the accuracy track** (Phases 1→2→3→4). At each GATE, stop and send a report; do not start the next accuracy phase until the brain replies "GATE n passed". **Exception (parallel track):** once the database schema and the API contract are frozen at GATE 1, the backend and frontend work (Phases 5 and 6) may proceed in parallel with Phases 2–4, because they do not depend on the accuracy number. Keep the two tracks in separate branches/commits so a stall on one never blocks the other. Phases 7 and 8 need both tracks done.
6. Every code change gets a test or a script that proves it, and the proof is included in the report.
7. If a number looks too good (for example 100%) or an assumption in this plan turns out to be false, stop and report. Do not paper over it.
8. **Cost budget.** Before any paid runs, GB sets a ceiling for (a) total eval/tuning spend and (b) acceptable cost per 1,000 questions tagged in production. Every design choice that multiplies calls (for example double-running in Phase 4) is measured against (b) and reported as a rupee figure, not just a multiplier. If a choice would exceed the budget, report it as a decision rather than shipping it.

### 0.2 Report format (send at every gate)
```
PHASE n REPORT
Done:        <checklist items completed, with file paths>
Not done:    <items skipped and why>
Numbers:     <the metrics this gate asks for, as a table>
Evidence:    <command run + output path, e.g. results/eval_.../report.md>
Surprises:   <anything unexpected, failing tests, assumptions that were wrong>
Questions:   <what the brain or GB must decide>
```

### 0.3 Metric definitions (use exactly these)
- **L1 strict / L2 strict:** predicted equals `gold_l1` / `gold_l2`.
- **L2 lenient:** predicted equals `gold_l2` or any value in `alt_l2`.
- **Coverage:** share of questions with `status = confirmed`.
- **Confirmed precision:** among `confirmed` questions, share where the prediction is correct. Report both strict and lenient. **This is the number the 95% target applies to.**
- **Wilson 95% lower bound** must be reported next to every precision figure, because small samples make raw percentages misleading.
- **Verified vs silver:** always report the 20 verified (`zvq-blr-*`) rows separately from silver.
- **Image-dependent questions:** questions with `image_hint = Y` cannot be fully judged from text alone (the tagger never sees the image). Always report these as a **separate slice**, excluded from the headline accuracy number. Do not let them silently lower or raise the score of the text-taggable set.
- **Ambiguous questions:** for rows with `ambiguous = Y`, strict L2 accuracy is unfair (more than one label is genuinely defensible). Report ambiguous and unambiguous slices separately; the 95% target is measured on the **unambiguous, non-image** confirmed set.
- **Human ceiling:** no accuracy target can exceed the rate at which two human quizmasters agree on the same questions (see Phase 2). Report every model number against that ceiling, not against 100%.

---

## Phase 1 — Clean baseline (no behaviour changes)

Goal: a trustworthy starting measurement.

- [ ] Confirm the repo runs locally: backend starts, existing tests pass. Record the commands used in `docs/dev_setup.md`.
- [ ] Add `backend/eval_data/results/` to `.gitignore`.
- [ ] Write `backend/tests/test_qshala_taxonomy.py`: taxonomy v4 loads, 38 L2s, every L2 has a non-empty description and unique name, no `&` in L2 names, every `gold_l2` and every `alt_l2` in the gold CSV exists in the taxonomy, every `gold_l1` matches its L2's parent.
- [ ] Add a validator `backend/eval_data/validate_gold.py` that checks the same things plus enum values for entity_type, geography, shelf_life, sensitivity, and flags duplicate question texts (known: `zvq-pre-011` and `zvq-pre-042` are near-duplicates, as are `zvq-pre-036` and `zvq-fin-016`).
- [ ] Decide with GB whether to delete `qshala_taxonomy_v3.json` (unused by code).
- [ ] Run the **full 145** eval, twice, on `gemini-3.5-flash-lite` (`--thinking low --throttle 1.0`). Two runs measure run-to-run noise.
- [ ] Run the full 145 once on `gemini-2.5-flash`.
- [ ] Extend the eval report to add: a confusion table (gold L2 × predicted L2, top 15 pairs), accuracy by `fit`, accuracy by `status`, and the Wilson lower bound on confirmed precision.
- [ ] Save the three baseline reports under `docs/baselines/` (copy `report.md` + `per_question.csv`).
- [ ] **Dumb baselines for comparison.** Also score two cheap/zero-cost baselines on the same 145: (a) rules-only, no LLM — whatever `qshala_rules.py` can assign on its own; (b) the existing generic world-knowledge tagger, if it can be pointed at these questions. This establishes the floor, so we can see how much the LLM is actually earning over free rules.
- [ ] **Resolve the "General Knowledge" / "Maths & Logic" mystery.** Those labels exist in neither v3 nor v4, so they came from some other code path. Trace where GB saw them (grep the frontend and all tagger/endpoint code for those strings; check the generic tagger's vocabulary). Report which component produced them and whether that path is currently live for users. This is cheap and must be answered at GATE 1, not parked.
- [ ] **Report the image slice separately.** Split the 145 into image-dependent (`image_hint = Y`) and text-taggable, and report accuracy for each (see §0.3). Note any question that is genuinely untaggable from text + answer alone.
- [ ] **Record cost.** For each full run, report total API cost and cost per 1,000 questions, against the budget from §0.1 rule 8.

**GATE 1 — report:** the table of L1/L2 strict+lenient, confirmed precision (+Wilson), coverage, for each run and each dumb baseline; the difference between the two flash-lite runs; the image slice vs text slice; the top 15 confusion pairs; the answer to the "General Knowledge" mystery; cost per 1,000; validator + test output; **the frozen DB schema and API contract** (so the parallel track in Phases 5–6 can start).
**Brain decides:** whether the noise between runs is small enough to trust differences of a few points; which model/thinking setting to carry forward; whether the parallel backend/frontend track may begin.

---

## Phase 2 — Make the ground truth trustworthy

Goal: labels good enough to measure 95% against, and a test set that is never tuned on.

- [ ] **Measure the human ceiling first.** Have two quizmasters independently label the same ~30 questions (unseen, stratified across L1) with no discussion. Compute how often they pick the same L2 (and L1). This inter-annotator agreement is the real upper bound — if two humans agree only ~85% on L2, a 95% model target on L2 is impossible and must be revised (or the target applies to L1, or to lenient L2). Report this number to the brain **before** the 95% target is treated as fixed.
- [ ] From the Phase 1 mistakes, produce `docs/gold_disputes.csv`: every row where the model disagrees with gold in both runs. Columns: id, question, answer, gold, predicted, model-notes. These are the rows most likely to have a wrong gold label.
- [ ] **GB / quizmaster task:** review `gold_disputes.csv` and the silver rows. Mark each as gold correct, model correct, or both acceptable (add to `alt_l2`). Target: all disputes resolved; ideally all 125 silver rows upgraded to VERIFIED.
- [ ] Worker applies the decisions, updates `label_status`, logs every change in `gold_changelog.md`, re-runs the validator.
- [ ] Create a frozen split: `split` column with values `dev` / `test`. Stratify by L2 so each L2 with ≥3 questions has at least one test row. Target about 40 test rows. Save the split file and never change it afterwards.
- [ ] Add to the eval script a `--split dev|test|all` flag. Tuning runs use `dev` only.
- [ ] **Grow the set.** The 145 questions are too few for the 95% claim (at 95% observed with n=60 confirmed the Wilson lower bound is only about 86%). Ask GB for additional decks. Target at least **300 verified questions**, with at least 8 per L2. Mark which L2s are under-represented.

**GATE 2 — report:** count of verified vs silver, the changelog, the split sizes per L2, list of under-represented L2s, a re-run of the baseline on the corrected gold (so the metric change from label fixes is separated from model changes later).
**Brain decides:** whether the set is large and clean enough to proceed, and which L2s need more data.

---

## Phase 3 — Raise accuracy (dev split only)

Goal: L1 strict ≥ 95%, L2 lenient ≥ 90% on dev. These are working targets and the brain may revise them after Phase 2.

Work through these one at a time, re-running the **dev** eval after each and recording the result in `docs/tuning_log.md` (change, before/after, kept or reverted):

- [ ] Description rewrites for the top confusion pairs from Phase 1. Each description should say what the category is and what it is NOT, with a tie-break against its nearest neighbour.
- [ ] Prompt: add a short decision procedure ("1. Identify the answer's entity. 2. Ask what the question is really about. 3. Apply the tie-break rules.") and look at the current prompt in `qshala_tagger.py` for places that conflict with it.
- [ ] Few-shot examples: 2–3 verified examples per frequently-confused pair, drawn from **dev only** and excluded from scoring.
- [ ] Use `secondary_l2`: check whether the model's secondary picks recover the gold label when primary misses. If so, consider showing it in the review UI.
- [ ] Compare `--thinking` levels (low, medium, high) and models on dev. Record accuracy, p50 latency, and tokens per question so cost can be estimated per 1,000 questions.
- [ ] Re-check the non-L2 fields: entity_type, geography, shelf_life, sensitivity, keywords. Targets: each ≥ 90% on dev. Fix systematic errors (known: shelf-life disagreements on year-dated questions; sensitivity is rare, so report precision/recall for non-NONE).
- [ ] Stop when two consecutive changes give less than 1 point of improvement. Do not keep tuning past that; it overfits dev.

**GATE 3 — report:** tuning log, final dev numbers vs Phase 1 baseline, the chosen model + thinking level + cost per 1,000 questions. **One single run on the frozen test split with the final config** (this run is allowed once; record it as the true accuracy).
**Brain decides:** whether accuracy is good enough to build routing on, or whether to go back and fix taxonomy structure.

---

## Phase 4 — Routing that earns "confirmed"

Goal: the confirmed bucket has **precision ≥ 95%** (Wilson lower bound reported, measured on the unambiguous non-image set) with **coverage as high as possible**, target ≥ 40%. If the Phase 2 human ceiling came in below 95%, the brain revises this target before the phase starts.

Current routing confirms whenever rule signals fire and there's no L1 conflict. In smoke tests about half of the confirmed answers were wrong, so this logic must change.

- [ ] Log, for every eval row, the candidate signals: `fit`, model confidence, whether rules and LLM agree on L1, whether `secondary_l2` is empty, whether geography/shelf-life agree with rules, answer-in-keywords, and agreement between two independent runs (see next item).
- [ ] Prototype **agreement-based confirmation**: run the tagger twice with different settings (for example different thinking levels, or two models) and confirm only when both agree on L2 and `fit = good`. Measure precision/coverage versus single-run routing.
- [ ] Prototype a threshold on the model's own confidence if it's informative. Plot or tabulate precision by confidence bucket to see if it's calibrated.
- [ ] Build a precision–coverage table for each candidate rule on dev, then evaluate the chosen rule once on test.
- [ ] **Always route image-dependent and ambiguous questions to review**, never auto-confirm them, regardless of model confidence — the tagger can't see the image, and ambiguous ones have no single right answer. Enforce this in the routing code, not just the eval.
- [ ] Anything not confirmed becomes `draft` with a one-line reason shown in the review UI (for example "two runs disagreed: Brand Identity vs Company Origins").
- [ ] Keep the human-override guarantee: a HUMAN-confirmed row is never overwritten.
- [ ] Unit tests for routing: each rule path, the tie cases, and the human-row protection.

**GATE 4 — report:** the precision–coverage table for every candidate, the chosen rule and why, test-split result with Wilson bound, cost multiplier if double-run is used.
**Brain decides:** the final routing rule. If no rule reaches 95% at acceptable coverage, the options are lowering coverage further, improving data, or lowering the target, and GB decides.

---

## Phase 5 — Backend: ingestion, batch tagging, search, review APIs

First **discover**: read the existing upload/ingestion code and the existing question search/list endpoints. Write `docs/ingestion_notes.md` describing where questions are created from a deck, how metadata is stored, and how migrations are handled (Alembic or `create_all`). Report this before building anything.

- [ ] **Migrations:** the three QShala tables must reach Postgres safely. Use the repo's existing migration approach. Test on a Postgres instance, not only SQLite.
- [ ] **Ingestion:** when a deck is parsed, create `qshala_question_metadata` rows (answer type, round stage and so on, from whatever the deck provides) and enqueue tagging.
- [ ] **Batch tagging with limits in mind.** Each call takes 2–13 s. The app is deployed on Vercel (serverless time limits); **verify the actual limit** and design for it: tag in small chunks per request, or use a background worker/queue. Include a status endpoint (`n tagged / n total / n failed`). Document the choice.
- [ ] Reliability: idempotent (re-running never duplicates or overwrites human rows), retries with backoff on 429/5xx, per-question failure isolation, throttle setting, a clear `failed` state surfaced in the UI.
- [ ] Cost/usage: record tokens and latency per call (already on `QshalaTag`) and expose a per-deck total.
- [ ] **Search/filter API:** current confirmed tag per question, filterable by L1, L2, geography, shelf_life, sensitivity, status, entity_type, free text; pagination and sorting; only the newest confirmed tag counts. Add DB indexes for the filtered columns.
- [ ] **Review API:** queue of drafts ordered by lowest confidence first; accept, change L2 (and other fields), skip; each action writes a HUMAN row and a `qshala_tag_changes` audit entry with the reviewer identity. Bulk accept.
- [ ] Auth: find out how the app identifies users and use it for the `actor` field. If there is none, report it as a decision for GB.
- [ ] Tests: API tests for each endpoint, including the human-row-never-overwritten case and a 100-question batch with injected failures.

**GATE 5 — report:** `ingestion_notes.md`, test output, a recorded end-to-end run on a sample deck (upload → tagged rows → status counts), the measured time per 100 questions, the chosen batching design.
**Brain decides:** architecture choices that affect cost or deployment.

---

## Phase 6 — Frontend: review screen and library

- [ ] `/review`: queue of draft questions. Each card shows question, answer, suggested L1/L2, why it was routed to draft, alternative suggestions (`secondary_l2`), other predicted fields. Actions: accept, change (dropdown of the 38 L2s with descriptions on hover), skip. Keyboard shortcuts (A accept, 1–9 pick alternative, J/K next/previous), bulk accept, progress counter. Target: under 10 seconds per easy item.
- [ ] Library/search page: filters for topic (L1/L2), geography, shelf life, sensitivity, status, plus text search; shows the current tag, and who confirmed it.
- [ ] Deck upload screen shows tagging progress and a summary (auto-confirmed, needs review, failed).
- [ ] Empty, loading and error states; mobile-width layout works; no horizontal scroll.
- [ ] Types/API helpers in `frontend/src/lib/` match the backend (already partly there).
- [ ] Frontend tests for the review actions, plus a manual walkthrough with screenshots of: upload, progress, review queue, accept, change, filter results.

**GATE 6 — report:** screenshots of each flow, test output, a list of any backend gaps found.
**Brain decides:** UX changes; GB tries it and gives feedback.

---

## Phase 7 — Feedback loop

Goal: corrections make the system better.

- [ ] Exporter: `scripts/export_verified.py` writes all HUMAN-confirmed tags to a CSV in the gold format (same columns), flagged `label_status = VERIFIED`.
- [ ] Few-shot retrieval from verified labels: for each new question, include the 2–3 most similar verified questions in the prompt (start with simple embedding similarity or keyword overlap; pgvector is optional once there are ≥500 confirmed). Measure on dev/test that this helps before enabling.
- [ ] Taxonomy change protocol: bump the version, supply a mapping file like `v3_to_v4_mapping.json`, write a migration script that remaps stored tags, and re-tag affected rows. Test this on a copy.
- [ ] Monthly (or per-deck) re-evaluation job that reruns the test split and alerts if confirmed precision drops below target.
- [ ] Dashboard or script output: precision of confirmed over time, human-override rate (how often reviewers change a confirmed tag), and review time.

**GATE 7 — report:** export output, before/after numbers for retrieval few-shots, migration dry-run results.

---

## Phase 8 — Release and final acceptance

- [ ] Staging deploy first (if no staging exists, report it). Set `GEMINI_API_KEY` and `QSHALA_TAGGER_MODEL` in the host's environment settings; confirm the key is the rotated one.
- [ ] Run migrations on staging, then the end-to-end rehearsal below.
- [ ] Rollback plan written down: how to disable the QShala endpoints, how to revert the migration.
- [ ] Only after GB writes "push it": commit, push, PR, review, merge, production deploy.

### Final acceptance test (the definition of done)
Use a **fresh deck that has never been used for tuning or gold labels**.

- [ ] Upload the deck through the real UI.
- [ ] All questions are tagged without manual steps, and failures (if any) are visible and retryable.
- [ ] A quizmaster blind-checks a random sample of **at least 100 auto-confirmed** questions (shown without the model's tag, then compared). **Confirmed precision ≥ 95%** and the Wilson lower bound is reported. If the deck has fewer confirmed questions, sample all of them and say the bound is wide.
- [ ] Coverage reported (target ≥ 40% confirmed).
- [ ] The remaining drafts can be cleared in the review screen at an average of ≤ 10 seconds per easy item.
- [ ] Search and filter by topic, geography, shelf life and sensitivity return correct results (spot-check 10 queries against the data).
- [ ] A reviewer correction on one question shows up as the new current tag, is recorded in the audit trail, and appears in the verified export.
- [ ] No secrets in the repo or logs; cost per 1,000 questions is documented.

**FINAL GATE — report:** all of the above with evidence. GB and the brain sign off.

---

## Quick reference: who does what

| Phase | Worker builds | GB provides | Brain decides |
|---|---|---|---|
| 1 Baseline | tests, validator, 3 runs, dumb baselines, GK-mystery trace | API key in env, cost budget | which model/setting, may parallel track start |
| 2 Ground truth | split, changelog, tooling | 2 quizmasters for agreement + review, more decks | is data sufficient, revise 95% vs human ceiling |
| 3 Accuracy | prompt/description tuning on dev | — | stop/continue, test-split run |
| 4 Routing | candidate rules, tests | — | final rule vs 95% target |
| 5 Backend | ingestion, batching, APIs | auth answer | architecture |
| 6 Frontend | review + library UI | feedback from using it | UX changes |
| 7 Feedback loop | exporter, retrieval, migration | — | whether retrieval stays on |
| 8 Release | staging, rollback, deploy | "push it", fresh deck, quizmaster | sign-off |
