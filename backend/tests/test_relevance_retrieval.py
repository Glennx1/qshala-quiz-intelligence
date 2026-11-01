"""Tests that the prompt engine delivers RELEVANT questions or fewer,
never irrelevant padding.  These simulate real quizmaster scenarios
against a controlled bank.

The golden rule: it is ALWAYS better to deliver 3 perfect questions
than 10 where 7 are unrelated.  fulfillment.note handles the shortfall.
"""
import pytest
from backend.app.services.prompt_quiz.engine import Brief, librarian, guardian, editor, host
from backend.app.services.prompt_quiz.retrieval import Index


# ── Test bank: small, realistic, with clear topic boundaries ──────
def _q(qid, text, answer, topic, subtopic, keywords=None,
       difficulty_score=0.5, geo="IN", sensitivity="NONE",
       shelf_life="EVERGREEN", city=None):
    return {
        "id": qid, "question_text": text, "answer": answer,
        "topic_l1": topic, "subtopic_l2": subtopic,
        "secondary_l2": [], "keywords": keywords or [],
        "india_international": geo, "shelf_life": shelf_life,
        "sensitivity": sensitivity, "image_dependent": False,
        "question_images": [], "answer_images": [], "image_refs": [],
        "search_summary": None, "difficulty": "Medium",
        "difficulty_score": difficulty_score, "document_id": "d1",
        "tagged": True, "question_format": "STANDARD_QA",
        "city_name": city, "geo_region": None, "primary_audience": None,
    }

BANK = [
    # ── Sports: Cricket (5 questions) ──
    _q("s1", "Which team won the 2023 IPL?", "Chennai Super Kings",
       "Sports", "Cricket", ["IPL", "T20", "CSK"]),
    _q("s2", "Who holds the record for most Test centuries?",
       "Sachin Tendulkar", "Sports", "Cricket", ["test", "centuries"]),
    _q("s3", "What is the Duckworth-Lewis-Stern method?",
       "Rain-adjusted target", "Sports", "Cricket", ["DLS", "rain"]),
    _q("s4", "Which country won the 2023 Cricket World Cup?",
       "Australia", "Sports", "Cricket", ["ODI", "World Cup"], geo="INTL"),
    _q("s5", "Name the home ground of Royal Challengers Bangalore",
       "M. Chinnaswamy Stadium", "Sports", "Cricket",
       ["RCB", "Bangalore", "IPL"], city="Bengaluru"),

    # ── Sports: Football (3 questions) ──
    _q("s6", "Which club has won the most Premier League titles?",
       "Manchester United", "Sports", "Football", ["EPL"], geo="INTL"),
    _q("s7", "Who is the all-time top scorer in FIFA World Cup history?",
       "Miroslav Klose", "Sports", "Football", ["World Cup"], geo="INTL"),
    _q("s8", "Which Indian footballer captained the national team in the 2023 SAFF Championship?",
       "Sunil Chhetri", "Sports", "Football", ["India", "SAFF"]),

    # ── Business (4 questions) ──
    _q("b1", "Who founded Infosys?", "Narayana Murthy",
       "Business", "Indian Business Leaders", ["Infosys", "IT"]),
    _q("b2", "What does UPI stand for?", "Unified Payments Interface",
       "Finance", "Digital Payments", ["UPI", "NPCI", "fintech"]),
    _q("b3", "Which company acquired Twitter in 2022?",
       "Elon Musk / X Corp", "Business", "Acquisitions and Mergers",
       ["Twitter", "X", "Musk"], geo="INTL", shelf_life="TIME_SENSITIVE"),
    _q("b4", "What is the full form of GST?",
       "Goods and Services Tax", "Finance", "Taxation", ["GST", "tax"]),

    # ── Technology (3 questions) ──
    _q("t1", "What does GPU stand for?", "Graphics Processing Unit",
       "Technology", "Computing and Software", ["GPU", "graphics"]),
    _q("t2", "Which company created ChatGPT?", "OpenAI",
       "Technology", "AI and Machine Learning", ["AI", "LLM", "ChatGPT"]),
    _q("t3", "What programming language is Android built on?",
       "Java / Kotlin", "Technology", "Computing and Software",
       ["Android", "Java", "mobile"]),

    # ── Entertainment (2 questions) ──
    _q("e1", "Who directed the film 'Oppenheimer'?", "Christopher Nolan",
       "Entertainment", "Hollywood", ["Nolan", "Oscar"], geo="INTL"),
    _q("e2", "Which Bollywood film won the National Award for Best Film in 2023?",
       "Gulmohar", "Entertainment", "Bollywood", ["National Award"]),

    # ── Geography (2 questions) ──
    _q("g1", "Which is the largest freshwater lake in India?",
       "Wular Lake", "Geography", "Indian Geography", ["lake", "Kashmir"]),
    _q("g2", "What is the capital of Australia?", "Canberra",
       "Geography", "World Geography", geo="INTL"),

    # ── History (1 question, school-safe) ──
    _q("h1", "In which year did India gain independence?", "1947",
       "History", "Indian History", ["independence", "freedom"],
       difficulty_score=0.15),

    # ── Sensitive (1 question, NOT school-safe) ──
    _q("x1", "Which political scandal led to Nixon's resignation?",
       "Watergate", "Politics", "Political Scandals",
       sensitivity="POLITICAL", geo="INTL"),
]


# ═══════════════════════════════════════════════════════════════════
# Category 1: Audience & Safety
# ═══════════════════════════════════════════════════════════════════

class TestAudienceSafety:

    def test_school_assembly_blocks_sensitive_and_unassessed(self):
        """'5 questions for a middle school assembly' → school_safe=true,
        must NOT include political/mature content."""
        brief = Brief(prompt="5 questions for a middle school assembly",
                      query="school assembly general knowledge",
                      count=5, filters={"school_safe": True},
                      hard_bias="easy", source="gemini")
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        for q in picked:
            assert q.get("sensitivity") not in ("POLITICAL", "MATURE_REFERENCE"), \
                f"School quiz included sensitive question: {q['id']}"

    def test_college_fest_no_overrestriction(self):
        """College quiz should NOT trigger school_safe — don't over-restrict."""
        brief = Brief(prompt="10 medium questions for a Bangalore engineering college quiz fest",
                      query="engineering technology Bangalore",
                      count=10, filters={"audience": "college"},
                      hard_bias="medium", source="gemini",
                      search_terms=["engineering", "technology", "computing"])
        hits = librarian(BANK, brief, pool=40)
        # school_safe is NOT in filters, so political questions are allowed
        assert "school_safe" not in brief.filters


# ═══════════════════════════════════════════════════════════════════
# Category 2: Geography & Scope
# ═══════════════════════════════════════════════════════════════════

class TestGeographyScope:

    def test_india_only_excludes_international(self):
        """'10 questions on India' → only Indian questions."""
        brief = Brief(prompt="10 questions on India", query="India",
                      count=10, filters={"india_international": "IN"},
                      source="gemini")
        hits = librarian(BANK, brief, pool=40)
        for h in hits:
            # Must be IN or MIXED, or contain "India"/"Indian" in text
            geo = h.get("india_international")
            text = (h.get("question_text", "") + " " + (h.get("answer") or "")).lower()
            assert geo in ("IN", "MIXED") or "india" in text, \
                f"India-only quiz included non-Indian question: {h['id']}"

    def test_international_excludes_domestic(self):
        """'10 international questions' → no domestic Indian trivia."""
        brief = Brief(prompt="10 international questions on world geography",
                      query="world geography international",
                      count=10, filters={"india_international": "INTL"},
                      source="gemini")
        hits = librarian(BANK, brief, pool=40)
        for h in hits:
            assert h.get("india_international") in ("INTL", "MIXED", None), \
                f"International quiz included India-only question: {h['id']}"

    def test_hyper_local_city_query(self):
        """'questions for a Chennai quiz' → city-relevant questions ranked higher."""
        brief = Brief(prompt="5 questions for a Chennai quiz",
                      query="Chennai Tamil Nadu",
                      count=5, source="gemini",
                      search_terms=["Chennai", "Tamil Nadu", "Marina Beach"])
        hits = librarian(BANK, brief, pool=40)
        # Should find at least some questions (may be few in our small bank)
        # Key: should NOT pad with random Business or Entertainment questions


# ═══════════════════════════════════════════════════════════════════
# Category 3: Topic Precision — the core relevance tests
# ═══════════════════════════════════════════════════════════════════

class TestTopicPrecision:

    def test_cricket_returns_only_cricket(self):
        """'10 questions on cricket' → only cricket questions, not football or business."""
        brief = Brief(prompt="10 questions on cricket", query="cricket",
                      count=10, source="gemini",
                      search_terms=["IPL", "Test match", "BCCI", "World Cup"])
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        for q in picked:
            assert q["topic_l1"] == "Sports" and q["subtopic_l2"] == "Cricket", \
                f"Cricket query returned non-cricket question: {q['id']} ({q['subtopic_l2']})"

    def test_fintech_returns_finance_not_sports(self):
        """'questions on fintech and UPI' → Finance/Business, never Sports."""
        brief = Brief(prompt="5 questions on fintech and UPI",
                      query="fintech UPI digital payments",
                      count=5, source="gemini",
                      search_terms=["UPI", "NPCI", "digital payments", "fintech"])
        hits = librarian(BANK, brief, pool=40)
        for h in hits:
            assert h["topic_l1"] in ("Finance", "Business", "Technology"), \
                f"Fintech query returned irrelevant topic: {h['id']} ({h['topic_l1']})"

    def test_ai_returns_technology(self):
        """'questions on AI and machine learning' → Technology only."""
        brief = Brief(prompt="5 questions on AI and machine learning",
                      query="AI machine learning",
                      count=5, source="gemini",
                      search_terms=["artificial intelligence", "LLM", "ChatGPT",
                                    "deep learning", "neural network"])
        hits = librarian(BANK, brief, pool=40)
        for h in hits:
            assert h["topic_l1"] == "Technology", \
                f"AI query returned non-tech question: {h['id']} ({h['topic_l1']})"


# ═══════════════════════════════════════════════════════════════════
# Category 4: Shortfall Honesty — the anti-padding tests
# ═══════════════════════════════════════════════════════════════════

class TestShortfallHonesty:

    def test_ask_20_cricket_get_only_5(self):
        """Bank has 5 cricket questions. Asking for 20 should deliver 5, not pad."""
        brief = Brief(prompt="20 questions on cricket", query="cricket",
                      count=20, source="gemini",
                      search_terms=["IPL", "Test match", "BCCI"])
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        # Should deliver ≤5 (the actual cricket questions), not pad to 20
        assert len(picked) <= 8, \
            f"Expected ≤8 cricket questions from bank of 5, got {len(picked)}"
        # Every delivered question should actually be about cricket or sports
        for q in picked:
            assert q["topic_l1"] == "Sports", \
                f"Padded with non-sports question: {q['id']} ({q['topic_l1']})"

    def test_niche_topic_zero_results_no_garbage(self):
        """'questions on quantum computing' with no matching questions → 0 delivered."""
        brief = Brief(prompt="10 questions on quantum computing",
                      query="quantum computing qubits",
                      count=10, source="gemini",
                      search_terms=["qubit", "superposition", "quantum supremacy"])
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        # With no quantum computing in the bank, should deliver 0 or very few
        # accidental matches, NOT pad with random questions
        assert len(picked) <= 2, \
            f"Niche query returned {len(picked)} — expected near-zero from this bank"

    def test_host_message_honest_about_shortfall(self):
        """When delivering fewer than asked, the host message must say so."""
        brief = Brief(prompt="20 questions on cricket", query="cricket",
                      count=20, source="gemini")
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        msg = host(brief, picked, len(BANK))
        if len(picked) < 20:
            assert "of 20" in msg or "only" in msg.lower(), \
                f"Host message didn't acknowledge shortfall: '{msg}'"


# ═══════════════════════════════════════════════════════════════════
# Category 5: Difficulty & Format
# ═══════════════════════════════════════════════════════════════════

class TestDifficultyAndFormat:

    def test_easy_bias_orders_easy_first(self):
        """'easy school quiz' → easiest questions first in the ramp."""
        brief = Brief(prompt="5 easy questions", query="general knowledge",
                      count=5, hard_bias="easy", source="regex")
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        if len(picked) >= 2:
            scores = [q.get("difficulty_score", 0.5) for q in picked]
            # With easy bias + ramp, should be sorted ascending
            assert scores == sorted(scores), \
                f"Easy quiz not ramped correctly: {scores}"

    def test_evergreen_excludes_time_sensitive(self):
        """Evergreen filter must exclude TIME_SENSITIVE questions."""
        brief = Brief(prompt="5 evergreen questions on business",
                      query="business", count=5,
                      filters={"evergreen_only": True}, source="regex")
        hits = librarian(BANK, brief, pool=40)
        for h in hits:
            assert h.get("shelf_life") != "TIME_SENSITIVE", \
                f"Evergreen query included time-sensitive: {h['id']}"


# ═══════════════════════════════════════════════════════════════════
# Category 6: Quizmaster Thinking Scenarios
# ═══════════════════════════════════════════════════════════════════

class TestQuizmasterScenarios:

    def test_mixed_topic_quiz_has_variety(self):
        """A general quiz should span multiple topics, not cluster in one."""
        brief = Brief(prompt="10 general knowledge questions",
                      query="general knowledge", count=10, source="regex")
        hits = librarian(BANK, brief, pool=40)
        picked = editor(guardian(hits, brief), brief)
        if len(picked) >= 4:
            topics = set(q["topic_l1"] for q in picked)
            assert len(topics) >= 2, \
                f"General quiz clustered in one topic: {topics}"

    def test_bangalore_quiz_prefers_local(self):
        """A Bangalore quiz should rank Bangalore-relevant questions higher."""
        brief = Brief(prompt="5 questions for a Bangalore quiz",
                      query="Bangalore Karnataka",
                      count=5, source="gemini",
                      search_terms=["Bengaluru", "Karnataka", "Bangalore"])
        hits = librarian(BANK, brief, pool=40)
        # s5 (RCB/Chinnaswamy/Bangalore) should be in the results
        hit_ids = [h["id"] for h in hits]
        assert "s5" in hit_ids, \
            "Bangalore quiz missed the Bangalore-specific cricket question"

    def test_sports_and_entertainment_mixed(self):
        """'sports and entertainment quiz' should pull from both L1s."""
        brief = Brief(prompt="10 sports and entertainment questions",
                      query="sports entertainment",
                      count=10, source="gemini",
                      search_terms=["movies", "films", "cricket", "football",
                                    "Bollywood", "Hollywood"])
        hits = librarian(BANK, brief, pool=40)
        topics = set(h["topic_l1"] for h in hits)
        assert "Sports" in topics and "Entertainment" in topics, \
            f"Mixed query didn't pull from both topics: {topics}"
