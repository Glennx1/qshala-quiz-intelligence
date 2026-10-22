# QShala Quiz Intelligence — Project Handoff

Written 2026-10-22 for continuing the work in a new IDE/agent (Antigravity). Read this top to bottom before touching code. Everything here is accurate as of the end of the previous session; items I could not verify are marked **(unverified)**.

---

## 1. What this is

**QShala Quiz Intelligence Platform**, built by GB (freelance, CS undergrad at PES University, Bengaluru) for **Walnut Knowledge Solutions**. It ingests quiz tournament decks (PPTX) into structured questions and **tags each question** (topic, subtopic, entity type, geography, shelf life, sensitivity, keywords) so quizmasters can search, reuse and review them.

The current focus is the **QShala tagger**: a domain-specific tagger for business / finance / brands / Indian-context quiz questions (Zerodha Varsity Quiz style). The pre-existing generic "world-knowledge" auto-tagger is untouched.

Repo (on GB's Windows machine): `C:\Users\aaksh\Downloads\qshala\qshala-quiz-intelligence`
Stack: FastAPI backend, Next.js frontend, SQLAlchemy, SQLite locally / Postgres in prod, deployed on Vercel.
Working branch name used in the sandbox: `claude/qshala-tagging-v1`.

---

## 2. Architecture of the tagger

Flow for one question (`backend/app/services/tagging/qshala_tagger.py`, class `QshalaTagger`):

1. **Rules** (`qshala_rules.py`): free deterministic signals — city dictionary, brand hints, year patterns (time-sensitivity), image-dependence detection.
2. **Duplicate check**: a confirmed/human tag on the same question text is inherited.
3. **LLM call**: one Gemini call, structured JSON output with **enum-constrained** fields (`GeminiLLMProvider.generate_json_schema()` in `backend/app/services/ai/gemini_provider.py`). Thinking config: `thinking_level` for 3.x models, `thinking_budget` for 2.5.
4. **Routing**: produces `status` = `confirmed` or `draft` with a reason.
   - `fit` = weak/none → draft
   - geography mismatch (rules vs LLM) → draft
   - rule signals present and no L1 conflict → confirmed
   - no rule signals → draft ("recommend quick review")
5. Writes a `QshalaTag` row with provenance (`source` = LLM/HUMAN/RULE, `model_version`, `taxonomy_version`).

Rules:
- A human-confirmed row is never overwritten by the tagger.
- **Shelf life**: a rule's `TIME_SENSITIVE` (year detected) overrides the LLM's value (Patch 2 fix).
- Config: `QSHALA_TAGGER_MODEL` (default `gemini-3.5-flash-lite`), `GEMINI_API_KEY`. The heavier generator model stays on `settings.GEMINI_MODEL`.
- `QshalaTagger(model=None, thinking_level="low")`; `thinking_level` is passed through to `_call_llm`.

### Files added/changed on the QShala branch

| File | Purpose |
|---|---|
| `backend/app/services/tagging/qshala_taxonomy_v4.json` | Controlled vocabulary (current). Loaded via `TAXONOMY_PATH`; `TAXONOMY_VERSION = "v4"` |
| `backend/app/services/tagging/qshala_taxonomy_v3.json` | Old taxonomy, no longer read by code. Safe to delete |
| `backend/app/services/tagging/v3_to_v4_mapping.json` | Old→new L1/L2 name map (for migrating stored tags) |
| `backend/app/services/tagging/qshala_rules.py` | Deterministic signals |
| `backend/app/services/tagging/qshala_tagger.py` | Orchestrator |
| `backend/app/models/qshala_tag.py` | Tables: `qshala_question_metadata` (1:1 with questions), `qshala_tags` (append-only runs), `qshala_tag_changes` (audit trail) |
| `backend/app/routers/qshala_tagging.py` | HTTP: POST tag, GET history, POST human override, GET review queue |
| `backend/app/config.py`, `backend/app/main.py` | Config + router registration |
| `backend/app/services/ai/gemini_provider.py` | Added `generate_json_schema()` (enum-constrained, per-call model override, token usage) |
| `backend/eval_qshala_tagger.py` | Eval harness (see §5) |
| `backend/eval_data/gold_labels_145.csv` | 145 gold questions (remapped to v4) |
| `backend/eval_data/README.md` | Branch notes |
| `frontend/src/lib/api.ts`, `types.ts` | Types + API helpers for the review queue |

The current tag for a question = newest `qshala_tags` row with `status = 'confirmed'`.

---

## 3. Taxonomy v4 (8 L1 / 38 L2)

Redesigned this session after GB's feedback: compound "X & Y" L2 names confused both users and the model; categories were too narrow. v4 rule: **each L2 is one clear concept**, and descriptions state tie-breaks against neighbours.

- **Markets & Investing**: Stock Markets, Quant Trading, Investment Funds, Commodities (gold, oil, forex, crypto), Market Concepts (Varsity-level terms), Finance Books
- **Banking & Money**: Banking, Central Banking (RBI/SEBI), Digital Payments (UPI, fintech), Insurance, Cyber Safety (fraud, scams), Money History (currencies, banknotes incl. imagery)
- **Economy & Policy**: Indian Economy, Global Trade (geopolitics, tariffs, OPEC, Belt & Road), Consumer Prices (inflation, shrinkflation), Government Policy (budgets, schemes)
- **Brands & Marketing**: Advertising, Brand Collabs, Brand Identity (logos, names, typefaces, mascot design — NOT founders/history), Consumer Brands (FMCG, fashion)
- **Companies & Business**: Startups, Company Origins (founding stories, brand histories, celebrity-founded ventures), Corporate Scandals (incl. trade-secret theft), Business Jargon, Business Leaders
- **Technology**: Artificial Intelligence (if AI is the core of the product, choose this), Internet Platforms (non-AI web), Tech Products
- **Sports & Entertainment**: Sports Leagues, Cricket Business, Entertainment (film, TV, OTT, music, newspapers, celebrities), Sponsorships
- **Culture & Society**: Heritage, Food Culture, Word Origins, Urban Life (transit, local business, civic), Social Impact, Environment

Other enums (unchanged): entity_type = COMPANY, PERSON, TERM, PRODUCT_OR_OBJECT, BOOK, ORGANISATION, POLICY, NUMBER, PLACE, EVENT; geography = IN, INTL, MIXED; shelf_life = EVERGREEN, REVIEW_YEARLY, TIME_SENSITIVE; sensitivity = NONE, POLITICAL, MATURE_REFERENCE; fit = good, weak, none.

Key merges from v3: Celebrities & Pop Culture + Media/Film/Streaming → Entertainment; three city categories → Urban Life; "Cities, Civic & Infrastructure" L1 folded into Culture & Society.

Description tweaks made after the first 10-question v4 run (to resolve overlaps): Brand Identity vs Company Origins (Keventers), Money History now covers banknote imagery (Gandhi photo), AI vs Internet Platforms tie-break (Grokipedia).

---

## 4. Gold set (145 questions)

`backend/eval_data/gold_labels_145.csv`, columns: `id, set, question_text, answer, gold_l2, gold_l1, alt_l2, ambiguous, entity_type, geography, shelf_life, sensitivity, image_hint, label_status`.

- **20 VERIFIED** (`zvq-blr-*`): Bangalore prelims, reviewed by a quizmaster. Real signal.
- **125 SILVER_UNVERIFIED** (`zvq-pre-*`, `zvq-fin-*`): first-pass labels by the AI assistant. Directional only.
- This session an independent audit re-checked all 145. Result: 8 L2 errors fixed (e.g. `zvq-blr-015` Coca-Cola formula theft → Corporate Scandals; two etymology questions → Word Origins; two celebrity-founded brands → Company Origins; Euro symbol → Money History; KBC×Stable Money → Advertising; Nandini name origin → Brand Identity) plus 7 field fixes (entity_type ×5, geography ×2, shelf_life ×1, sensitivity ×1). All labels then remapped v3→v4.
- Caveat: silver labels can still be wrong. Where the model disagrees with gold, check whether gold is the one at fault. `alt_l2` holds accepted alternatives and drives the "lenient" score.

---

## 5. Eval harness

`backend/eval_qshala_tagger.py` runs the real tagger over the gold set with an isolated temp SQLite DB (never touches dev/prod).

```
# from repo root, PowerShell
$env:GEMINI_API_KEY = "<key>"            # per-window; never commit or paste the key
python backend/eval_qshala_tagger.py --limit 10 --throttle 1.0     # smoke test
python backend/eval_qshala_tagger.py --throttle 1.0                # full 145 (~15-25 min)
python backend/eval_qshala_tagger.py --model gemini-2.5-flash --throttle 1.0
python backend/eval_qshala_tagger.py --thinking medium             # minimal|low|medium|high
```

Output: `backend/eval_data/results/eval_<timestamp>/{report.md, per_question.csv, raw.jsonl}`. Metrics: L1 strict, L2 strict, L2 lenient (gold + alts), entity, geo, shelf, sens, keyword format, answer-in-keywords, auto-confirmed %, **L2 strict on auto-confirmed** (the number that matters; target ≥ ~95%), tokens and latency. `results/` should probably be in `.gitignore`.

### Results so far (only 10-question smoke tests, so not conclusive)

- v3 taxonomy, gemini-3.5-flash-lite, low thinking: L1 80, L2 strict 60, lenient 80; 50% auto-confirmed, 60% strict accuracy on confirmed.
- v4 taxonomy (before the description tweaks), same model: L2 strict 6/10. Misses: pre-001 Gandhi photo → Brand Identity (gold Money History); pre-007 Grokipedia → Internet Platforms, auto-confirmed (gold AI; Internet Platforms was an accepted alt); pre-009 Keventers → Brand Identity, auto-confirmed (gold Company Origins; Brand Identity is an alt); pre-010 Blinkit×Tinder → Brand Collabs (gold Advertising; alt).
- **The full 145 run on v4 has not been done yet. That is the immediate next step.**

---

## 6. Known issues and open problems

1. **Auto-confirm precision is poor.** In both smoke runs about half of the confirmed rows were wrong at strict level. Routing confirms when rule signals fire and no L1 conflict, regardless of how confident the L2 is. Needs tightening once the full-run numbers exist (e.g. require fit=good AND agreement with a second signal, or lower the auto-confirm rate).
2. **User-reported misclassifications to re-verify on the full run:** a Zerodha question tagged "General Knowledge" and the Coca-Cola formula question tagged "Maths & Logic". Neither label exists in v3 or v4. The enum-constrained output should make this impossible, so these probably came from a different/older tagger or UI (the generic world-knowledge auto-tagger, which is untouched), not from the QShala tagger. **(unverified)** — find where the user saw them.
3. **Silver label quality** (see §4).
4. **Latency** varies 1.7–13 s per call on flash-lite; fine for batch, relevant for live use.
5. **Stale tags:** any tags stored with v3 names no longer match v4. Use `v3_to_v4_mapping.json` to migrate, or re-tag. **(unverified whether prod has any rows)**
6. In the repo, `qshala_taxonomy_v3.json` is still present and staged; harmless.

---

## 7. Repo / git state (important)

- All changes were made in an ephemeral cloud sandbox and **copied directly into GB's local repo files**. Nothing was committed or pushed by the assistant.
- GB's local `git status` shows the QShala work as staged additions/modifications (from an earlier base) with the v4 edits on top as unstaged changes, plus untracked `qshala_taxonomy_v4.json`, `v3_to_v4_mapping.json`, and `eval_data/results/`.
- `qshala-patch-2.patch` / `qshala-patch-3.patch` in the `qshala` folder are obsolete. Patch 3 fails to apply because the files are already in place. Ignore or delete them.
- **Standing rule from GB: do NOT push to GitHub or open a PR unless he explicitly says "push it".** Committing locally is a separate decision, so ask first.
- The deployed website is NOT running any of this yet. Going live needs: commit, push, merge, Vercel redeploy, and `GEMINI_API_KEY` / `QSHALA_TAGGER_MODEL` set in the prod environment. The new endpoints are opt-in, so nothing in production changes until they're called.

---

## 8. Security

- GB pasted a Gemini API key into chat earlier. **Do not repeat or store it anywhere; it should be rotated** in Google AI Studio. Use an env var only.
- Do not commit `.env` or result files containing question data unless intended.

---

## 9. Next steps (suggested order)

1. Run the **full 145 eval** on `gemini-3.5-flash-lite` (v4, low thinking), then on `gemini-2.5-flash` as a ceiling check. Review the "Every mistake" table; decide per miss whether gold or taxonomy or model is at fault.
2. Fix remaining description overlaps from that table; re-audit gold labels the model consistently disagrees with.
3. **Tighten routing** so L2-strict-on-confirmed reaches ~95% (see §6.1). Consider comparing `--thinking medium`.
4. Investigate where the "General Knowledge" / "Maths & Logic" tags came from (§6.2).
5. Build the **frontend review page** (`/review`) over the existing review-queue endpoint; types and API helpers already exist in `frontend/src/lib/`.
6. **Ingestion**: populate `qshala_question_metadata` on deck upload (answer_type, round_stage, etc.).
7. Optional: pgvector kNN as a NEIGHBOUR signal once ≥500 confirmed questions exist.
8. When GB says so: commit, push, open PR, deploy; migrate/re-tag any v3-era rows.

---

## 10. Working style notes for the next agent

GB communicates casually and prefers concise, warm answers. He cares most about tagging accuracy visible in real examples, clear single-concept category names, and not being surprised by pushes or deploys. Be candid when results don't show improvement (the 10-question runs did not).
