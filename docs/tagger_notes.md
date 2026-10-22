# QShala Tagger Notes — Taxonomy & Legacy Analysis

## 1. Resolution of the "Mathematics & Logic" and "General Knowledge" Mystery

### Background
During review of the legacy database and earlier tagging runs, questions appeared with topics such as **"Mathematics & Logic"** and **"General Knowledge"**. For example, `zvq-pre-001` (a question about the secret Coca-Cola formula) was tagged under "Mathematics & Logic".

### Root Cause Analysis
The source of these tags is **`backend/app/services/tagging/auto_tagger.py`**, specifically the `AutoTagger` class:

1. **Keyword-Regex Matching:**
   `AutoTagger` uses a hardcoded dictionary (`TOPIC_KEYWORDS`) of 10 generic school-quiz topics. In `auto_tagger.py` (lines 29–38):
   ```python
   "Mathematics & Logic": [
       "math", "logic", "number", "geometry", "puzzle", "algebra",
       "calculation", "formula", "theorem", "equation", "prime",
       "fraction", "probability"
   ],
   "General Knowledge": [
       "general", "miscellaneous", "trivia", "mixed", "various"
   ]
   ```
2. **Why Coca-Cola became "Maths":**
   The question text in `zvq-pre-001` reads:
   > *"The secret 7X **formula** of this beverage has been kept in a vault in Atlanta since 1925..."*
   `AutoTagger` scanned for the word `"formula"`, found a match in `Mathematics & Logic`, and classified the question as Maths!
3. **Why "General Knowledge":**
   When `AutoTagger` encountered questions where none of its 10 keyword lists matched, or where scores were tied, it defaulted to `"General Knowledge"`.

### Is this path live for users today?
* **Yes, on the legacy deck ingestion pipeline:**
  When a user uploads a PPTX deck via `POST /api/v1/documents/upload`, the backend background job (`backend/app/services/ingestion/pipeline.py`) calls `AutoTagger.tag_question()` to populate `questions.topic` and `questions.subtopic`.
* **No, on the QShala Tagging route:**
  The new domain-specific tagger (`backend/app/services/tagging/qshala_tagger.py`) uses **Taxonomy v4** (8 business/finance domains, 38 L2 subtopics) via `GeminiLLMProvider.generate_json_schema()`. It completely bypasses `auto_tagger.py`.
* **Action for Phase 5:**
  The ingestion worker in Phase 5 will wire `QshalaTagger` directly into the ingestion lifecycle for QShala decks, replacing `AutoTagger`.

---

## 2. Taxonomy v4 Structure & Philosophy

Taxonomy v4 eliminates compound "X & Y" names that caused model confusion and establishes 8 clear L1 domains with 38 single-concept L2 subtopics:
- **Markets & Investing (6 L2s):** Stock Markets, Quant Trading, Investment Funds, Commodities, Market Concepts, Finance Books.
- **Banking & Money (6 L2s):** Banking, Central Banking, Digital Payments, Insurance, Cyber Safety, Money History.
- **Economy & Policy (4 L2s):** Indian Economy, Global Trade, Consumer Prices, Government Policy.
- **Corporate & Governance (4 L2s):** Business Leaders, Corporate Scandals, Company Origins, Mergers & Acquisitions.
- **Consumer & Retail (6 L2s):** Consumer Brands, Food Culture, Advertising, Brand Identity, Sponsorships, Brand Collabs.
- **Tech & Modern Business (4 L2s):** Startups, Artificial Intelligence, Tech Products, Internet Platforms.
- **Society & Culture (5 L2s):** Urban Life, Sports Leagues, Entertainment, Heritage, Word Origins.
- **Development & Sustainability (3 L2s):** Social Impact, Environment, Business Jargon.

Every L2 has a distinct description and disambiguation rule to resolve neighboring edge-cases.
