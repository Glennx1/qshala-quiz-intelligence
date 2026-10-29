"""Task 2: deterministic L2 disambiguation guards + soft-L2 matching.

Each case mirrors a row from the 22-question blind evaluation (ruling_sheet_22.csv). We assert
the guard asserts the FINAL ruling's v6 subtopic when the model proposed one of the confusable
siblings, and that it does NOT fire when the model already picked something unrelated/correct.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.services.tagging import qshala_rules as R


# (question_text, answer, proposed_l2, expected_target_l2)
CASES = [
    # blind-002 — Hong Kong private banks print currency
    ("Which country allows Standard Chartered, Bank of China and the Lion's Bank to print its "
     "currency, pegged to the US Dollar, despite having a central monetary authority?",
     "Hong Kong", "Economic History", "Central Banking"),
    # blind-024 — RBI CBDC
    ("The RBI launched CBDC. If CB stands for Central Bank, what does DC stand for?",
     "Digital Currency", "Banks and Banking", "Central Banking"),
    # blind-135 — HSBC first woman CFO
    ("Pam Kaur has been appointed the new Chief Financial Officer of this bank, the first woman "
     "to hold the role in its 160-year history. Which bank?",
     "HSBC", "Banks and Banking", "Business Leaders"),
    # blind-026 — American Eagle ad campaign moves share price
    ("Which company's share price with ticker symbol AEO rose 10% in a single day after the "
     "announcement of their latest ad campaign?",
     "American Eagle", "Stock Markets", "Advertising"),
    # blind-049 — Head & Shoulders chart pattern
    ("What is the name of this chart pattern in technical analysis, sharing its name with a "
     "shampoo brand because one peak is higher than the other two?",
     "Head & Shoulders", "Stock Markets", "Technical Analysis"),
    # blind-043 — Steinway ticker LVB origin
    ("From 1996 to 2013 Steinway traded on the NYSE with the stock ticker LVB. Why was its stock "
     "symbol LVB?",
     "In honour of Ludwig van Beethoven", "Stock Markets", "Etymology"),
    # blind-072 — Karnataka green-energy MoU
    ("____ Future Energies signed an Rs. 11,000 crore MoU with the Government of Karnataka to "
     "commission a 29 MWp solar project. Which group?",
     "Hero Group", "Brand Collaborations", "Indian Economy"),
    # blind-073 — Bisleri water credits
    ("This company is introducing water credits akin to carbon credits to make beverage makers "
     "accountable for water usage, partnering with TERI. Which company?",
     "Bisleri", "Consumer Brands", "Ecology and Environment"),
    # blind-058 — Wimbledon strawberry price freeze
    ("For the first time since 2010 the All-England Club raised the price of an iconic item, long "
     "priced at £2.50, by 20p, ending a 15-year price freeze at Wimbledon. Which item?",
     "Strawberries", "Archaeology and Heritage Sites", "Consumer Prices"),
    # blind-067 — longest railway platform / EMD loco shed
    ("Which place is home to the first EMD high-horsepower locomotive shed in India and the "
     "world's longest railway platform?",
     "Hubballi", "Maps and Travel", "Urban Life"),
    # blind-027 — Taj hotel named after its location
    ("What is the name of the Taj hotel coming up where the Searock Hotel is located? It is named "
     "after the specific location where it is situated.",
     "Taj Bandstand", "Real Estate", "Urban Life"),
    # blind-133 — Aston Martin luxury stroller
    ("Which maker of high-end vehicles has rolled out a luxury baby stroller priced at $3,000?",
     "Aston Martin", "Brand Identity and Logos", "Consumer Brands"),
]


def test_each_ruling_sheet_guard_fires():
    for qtext, ans, proposed, expected in CASES:
        hit = R.disambiguate_l2(qtext, ans, proposed, taxonomy_version="v6")
        assert hit is not None, f"no guard fired for expected {expected!r}: {qtext[:60]}"
        assert hit[0] == expected, f"got {hit[0]!r}, expected {expected!r} for: {qtext[:60]}"


def test_targets_carry_valid_l1():
    for qtext, ans, proposed, expected in CASES:
        target_l2, target_l1, rule_id = R.disambiguate_l2(qtext, ans, proposed, "v6")
        assert target_l1 and isinstance(target_l1, str)
        assert rule_id


def test_no_override_when_model_outside_confusable_set():
    # A chart-pattern question the model already tagged as, say, "Cricket" is left untouched:
    # the chart-pattern guard only overrides Finance-family siblings.
    hit = R.disambiguate_l2(
        "What is the name of this chart pattern, Head & Shoulders?", "Head & Shoulders",
        "Cricket", "v6")
    assert hit is None


def test_no_override_when_already_correct():
    hit = R.disambiguate_l2(
        "The RBI launched CBDC; what does DC stand for?", "Digital Currency",
        "Central Banking", "v6")
    assert hit is None


def test_noop_for_non_v6_taxonomy():
    hit = R.disambiguate_l2(
        "The RBI launched CBDC; what does DC stand for?", "Digital Currency",
        "Banks and Banking", "v5")
    assert hit is None


def test_apply_disambiguation_demotes_original_to_secondary():
    paths = [{"l1": "Finance", "l2": "Stock Markets", "keywords": ["AEO"]}]
    out = R.apply_disambiguation(
        paths,
        "Shares with ticker AEO rose 10% after the company's new ad campaign.", "American Eagle",
        taxonomy_version="v6")
    assert out[0]["l2"] == "Advertising"
    secondary = [p["l2"] for p in out[1:]]
    assert "Stock Markets" in secondary          # original primary preserved for soft-L2 credit


def test_apply_disambiguation_noop_returns_same_when_no_rule():
    paths = [{"l1": "Sports", "l2": "Cricket", "keywords": []}]
    out = R.apply_disambiguation(paths, "Who won the 2011 Cricket World Cup final?", "India", "v6")
    assert out == paths


def test_apply_disambiguation_handles_empty_paths():
    assert R.apply_disambiguation([], "anything", "answer", "v6") == []


def test_l2_match_soft_eval():
    assert R.l2_match("Advertising", "Advertising", [])
    assert R.l2_match("advertising", "Advertising", [])          # case-insensitive
    assert R.l2_match("Stock Markets", "Advertising", ["Stock Markets"])  # secondary credit
    assert not R.l2_match("Cricket", "Advertising", ["Stock Markets"])
    assert not R.l2_match(None, "Advertising", [])
    assert not R.l2_match("Advertising", None, None)
