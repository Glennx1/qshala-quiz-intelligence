from backend.app.services.prompt_quiz.topic_normalize import dedupe_query, normalize_topics

L1 = ["Sports", "Technology", "Science", "Business"]
L2 = ["Cricket", "Football", "Artificial Intelligence", "Startups"]
MAP = {"Cricket": "Sports", "Football": "Sports", "Artificial Intelligence": "Technology", "Startups": "Business"}


def run(l1, l2):
    return normalize_topics(l1, l2, l1_names=L1, l2_names=L2, l2_to_l1=MAP)


def test_invented_l2_names_are_dropped_not_kept():
    l1, l2, dropped = run(["Technology", "Science"], ["engineering", "coding", "innovation"])
    assert l2 == [] and l1 == ["Technology", "Science"]
    assert set(dropped) == {"engineering", "coding", "innovation"}


def test_case_and_near_misses_snap_to_exact_names():
    l1, l2, dropped = run(["sports"], ["cricket", "Footbal"])
    assert l1 == ["Sports"] and l2 == ["Cricket", "Football"] and dropped == []


def test_valid_l2_supplies_its_own_l1():
    l1, l2, _ = run([], ["Artificial Intelligence"])
    assert l1 == ["Technology"] and l2 == ["Artificial Intelligence"]


def test_duplicates_collapse_and_empty_input_is_fine():
    assert run(["Sports", "sports"], ["Cricket", "cricket"]) == (["Sports"], ["Cricket"], [])
    assert run([], []) == ([], [], [])
    assert run(None, None) == ([], [], [])


def test_unknown_l1_is_reported():
    l1, _, dropped = run(["Underwater Basket Weaving"], [])
    assert l1 == [] and dropped == ["Underwater Basket Weaving"]


def test_real_v6_taxonomy_rejects_the_names_gemini_invented():
    from backend.app.services.tagging.qshala_tagger import _load_taxonomy
    t = _load_taxonomy()
    l1, l2, dropped = normalize_topics(["Technology", "Science"], ["engineering", "technology", "coding", "innovation"],
                                       l1_names=t["l1"], l2_names=t["l2"], l2_to_l1=t["l2_to_l1"])
    assert l2 == [] and l1 == ["Technology", "Science"] and len(dropped) == 4
    assert normalize_topics([], ["football"], l1_names=t["l1"], l2_names=t["l2"], l2_to_l1=t["l2_to_l1"])[:2] == (["Sports"], ["Football"])


def test_dedupe_query():
    assert dedupe_query("sports Sports") == "sports"
    assert dedupe_query("engineering technology Technology Science engineering technology coding innovation") \
        == "engineering technology Science coding innovation"
    assert dedupe_query("") == "" and dedupe_query(None) == ""
