import pytest

from backend.app.services.prompt_quiz.audience import (
    audience_score, defaults_for_audience, difficulty_penalty, passes_hard)
from backend.app.services.prompt_quiz.fulfillment import (
    blocked_counts, build_fulfillment, is_on_topic, split_pools)


def q(i, l1="Sports", l2="Cricket", score=1.0, **kw):
    base = dict(id=str(i), question_text=f"q{i}", answer="a", topic_l1=l1, subtopic_l2=l2, secondary_l2=[],
                keywords=[], india_international="NA", shelf_life="EVERGREEN", sensitivity="NONE",
                question_images=[], answer_images=[], image_refs=[], image_dependent=False, tagged=True,
                question_format="STANDARD_QA", difficulty="Medium", difficulty_score=0.5, score=score,
                search_summary="")
    base.update(kw)
    return base


# ---------------- hard filters
def test_format_filter_is_hard():
    assert passes_hard(q(1, question_format="CONNECT_4"), {}, "CONNECT_4")
    assert not passes_hard(q(1), {}, "CONNECT_4")


def test_no_images_uses_real_image_lists_not_the_short_question_heuristic():
    assert passes_hard(q(1, image_dependent=True), {"no_images": True})       # short text != has image
    assert not passes_hard(q(1, question_images=["a.png"]), {"no_images": True})
    assert not passes_hard(q(1, image_refs=["r.png"]), {"no_images": True})


def test_school_safe_blocks_sensitive_and_untagged():
    f = {"school_safe": True}
    assert passes_hard(q(1), f)
    assert not passes_hard(q(1, sensitivity="MATURE_REFERENCE"), f)
    assert not passes_hard(q(1, sensitivity="POLITICAL"), f)
    assert not passes_hard(q(1, tagged=False), f)


def test_school_safe_blocks_unassessed_sensitivity():
    """sensitivity=None (never assessed) must not pass a school audience, even if a tag row exists."""
    f = {"school_safe": True}
    assert not passes_hard(q(1, sensitivity=None), f)
    assert not passes_hard(q(1, sensitivity=""), f)
    assert passes_hard(q(1, sensitivity="NONE"), f)
    assert passes_hard(q(1, sensitivity=None), {})            # no school filter -> unaffected


def test_evergreen_blocks_time_sensitive_only():
    f = {"evergreen": True}
    assert not passes_hard(q(1, shelf_life="TIME_SENSITIVE"), f)
    assert passes_hard(q(1, shelf_life="REVIEW_YEARLY"), f)


# ---------------- difficulty
def test_difficulty_penalty():
    assert difficulty_penalty(q(1, difficulty_score=0.2, difficulty="Easy"), "easy") == 0
    assert difficulty_penalty(q(1, difficulty_score=0.9, difficulty="Hard"), "easy") == 1.0
    assert difficulty_penalty(q(1, difficulty="Unrated"), "hard") == pytest.approx(0.1)
    assert difficulty_penalty(q(1, difficulty_score=0.9, difficulty="Hard"), None) == 0
    assert difficulty_penalty(q(1, difficulty_score=0.9, difficulty="Hard"), "spicy") == 0


# ---------------- audience
def test_india_focus_prefers_in_over_intl():
    assert audience_score(q(1, india_international="IN"), india_focused=True) > \
           audience_score(q(2, india_international="INTL"), india_focused=True)


def test_city_match_beats_region_beats_none():
    city = q(1, city_name="Bengaluru", geo_region="Karnataka")
    region = q(2, geo_region="Karnataka")
    none = q(3)
    assert audience_score(city, locality="Bengaluru") > audience_score(region, locality="Karnataka") > 0
    assert audience_score(none, locality="Karnataka") == 0


def test_empty_region_does_not_false_match():
    assert audience_score(q(1, geo_region="", city_name=None), locality="Pune") == 0


def test_audience_defaults_never_override_user_choice():
    f, hb = defaults_for_audience("school", {"school_safe": False}, "hard")
    assert f["school_safe"] is False and hb == "hard" and f["evergreen"] is True
    f, hb = defaults_for_audience("school", {}, None)
    assert f["school_safe"] is True and hb == "easy"
    assert defaults_for_audience("college", {}, None)[1] == "medium"


# ---------------- pools
def test_l2_asked_means_only_that_l2_is_on_topic():
    pool = [q(1, l2="Cricket"), q(2, l2="Football"), q(3, l2="Cricket")]
    on_ok, adj, on_all, l2s = split_pools(pool, l1s=["Sports"], l2s=["Cricket"], filters={}, format_filter=None)
    assert {c["id"] for c in on_ok} == {"1", "3"}
    assert {c["id"] for c in adj} == {"2"}          # same L1, different L2 -> adjacent, never silent


def test_unknown_l2_from_llm_falls_back_to_l1():
    pool = [q(1, l2="Cricket"), q(2, l2="Football")]
    on_ok, adj, _, l2s = split_pools(pool, l1s=["Sports"], l2s=["Underwater Basket Weaving"], filters={}, format_filter=None)
    assert l2s == [] and len(on_ok) == 2


def test_no_topics_uses_bm25_hit():
    assert is_on_topic(q(1, score=2.0), [], [])
    assert not is_on_topic(q(1, score=0.0), [], [])


# ---------------- the headline case: ask 20, only 10 exist
def test_ask_20_only_10_exist():
    pool = [q(i, l1="Sports") for i in range(10)] + [q(100 + i, l1="Entertainment", l2="Movies") for i in range(30)]
    on_ok, adj, on_all, _ = split_pools(pool, l1s=["Sports"], l2s=[], filters={}, format_filter=None)
    assert len(on_ok) == 10 and len(adj) == 30
    f = build_fulfillment(requested=20, picked=on_ok, padded=0, adjacent_available=len(adj),
                          blocked={}, hard_bias=None, padding_allowed=False)
    assert f["short"] and f["delivered"] == 10
    assert {"action": "add_adjacent", "count": 10} in f["suggestions"]
    assert "10 of 20" in f["note"]


def test_padding_allowed_reports_padded_count():
    picked = [q(i) for i in range(20)]
    f = build_fulfillment(requested=20, picked=picked, padded=10, adjacent_available=20,
                          blocked={}, hard_bias=None, padding_allowed=True)
    assert not f["short"] and f["padded"] == 10


def test_exact_fill_is_quiet():
    f = build_fulfillment(requested=5, picked=[q(i) for i in range(5)], padded=0, adjacent_available=0,
                          blocked={}, hard_bias=None, padding_allowed=False)
    assert not f["short"] and f["suggestions"] == []


def test_blocked_counts_name_the_rule_and_never_offer_school_safe():
    pool = [q(1), q(2, question_images=["x.png"]), q(3, question_images=["y.png"]),
            q(4, sensitivity="MATURE_REFERENCE")]
    filters = {"no_images": True, "school_safe": True}
    _, _, on_all, _ = split_pools(pool, l1s=["Sports"], l2s=[], filters=filters, format_filter=None)
    b = blocked_counts(on_all, filters, None)
    assert b == {"no_images": 2}
    f = build_fulfillment(requested=10, picked=[pool[0]], padded=0, adjacent_available=0,
                          blocked=b, hard_bias=None, padding_allowed=False)
    assert {"action": "relax", "flag": "no_images", "count": 2} in f["suggestions"]
    assert all(s.get("flag") != "school_safe" for s in f["suggestions"])


def test_off_difficulty_is_reported():
    picked = [q(1, difficulty_score=0.9, difficulty="Hard"), q(2, difficulty_score=0.2, difficulty="Easy")]
    f = build_fulfillment(requested=2, picked=picked, padded=0, adjacent_available=0,
                          blocked={}, hard_bias="easy", padding_allowed=False)
    assert f["off_difficulty"] == 1 and "1 sit outside" in f["note"]
