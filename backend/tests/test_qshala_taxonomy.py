import csv
import json
import pathlib
import pytest

HERE = pathlib.Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
TAXONOMY_V4_PATH = BACKEND_DIR / "app" / "services" / "tagging" / "qshala_taxonomy_v4.json"
TAXONOMY_V5_PATH = BACKEND_DIR / "app" / "services" / "tagging" / "qshala_taxonomy_v5.json"
TAXONOMY_V5_1_PATH = BACKEND_DIR / "app" / "services" / "tagging" / "qshala_taxonomy_v5_1.json"
GOLD_PATH = BACKEND_DIR / "eval_data" / "gold_labels_145.csv"


def test_taxonomy_v5_1_structure_and_l2_rules():
    assert TAXONOMY_V5_1_PATH.exists(), f"Taxonomy file missing: {TAXONOMY_V5_1_PATH}"
    with open(TAXONOMY_V5_1_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("version") == "v5.1", f"Expected version 'v5.1', got '{data.get('version')}'"
    assert "level1" in data, "Taxonomy must have 'level1' key"
    level1_groups = data["level1"]
    assert len(level1_groups) == 8, f"Expected 8 L1 categories, found {len(level1_groups)}"

    l2_names = []
    l2_codes = []
    l2_to_l1 = {}

    for grp in level1_groups:
        l1_name = grp["name"]
        assert l1_name, "L1 category name must not be empty"
        for item in grp["level2"]:
            l2_name = item["name"]
            l2_code = item.get("code")
            assert l2_name, "L2 subtopic name must not be empty"
            assert l2_code, f"L2 subtopic '{l2_name}' must have a non-empty code"
            assert "&" not in l2_name, f"L2 name '{l2_name}' must not contain '&' (single-concept rule)"
            desc = item.get("description", "").strip()
            assert desc, f"L2 subtopic '{l2_name}' must have a non-empty description"

            l2_names.append(l2_name)
            l2_codes.append(l2_code)
            l2_to_l1[l2_name] = l1_name

    assert len(l2_names) == 78, f"Expected exactly 78 L2 subtopics in v5.1, found {len(l2_names)}"
    assert len(set(l2_names)) == len(l2_names), "L2 names must be strictly unique"
    assert len(set(l2_codes)) == len(l2_codes), "L2 codes must be strictly unique"


def test_gold_labels_align_with_taxonomy_v5_1():
    assert GOLD_PATH.exists(), f"Gold labels file missing: {GOLD_PATH}"
    with open(TAXONOMY_V5_1_PATH, encoding="utf-8") as f:
        tax = json.load(f)

    l2_to_l1 = {}
    for grp in tax["level1"]:
        for item in grp["level2"]:
            l2_to_l1[item["name"]] = grp["name"]

    with open(GOLD_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 145, f"Expected 145 gold rows, found {len(rows)}"

    for row in rows:
        qid = row["id"]
        gold_l1 = row["gold_l1"].strip()
        gold_l2 = row["gold_l2"].strip()
        alt_l2_raw = row.get("alt_l2", "").strip()

        # Check gold_l2 exists in taxonomy v5.1
        assert gold_l2 in l2_to_l1, f"[{qid}] gold_l2 '{gold_l2}' not found in taxonomy v5.1"

        # Check gold_l1 matches parent of gold_l2
        expected_l1 = l2_to_l1[gold_l2]
        assert gold_l1 == expected_l1, f"[{qid}] gold_l1 '{gold_l1}' does not match expected parent '{expected_l1}' for gold_l2 '{gold_l2}'"

        # Check all alt_l2 entries exist in taxonomy v5.1
        if alt_l2_raw:
            alts = [a.strip() for a in alt_l2_raw.split("|") if a.strip()]
            for alt in alts:
                assert alt in l2_to_l1, f"[{qid}] alt_l2 '{alt}' not found in taxonomy v5.1"


def test_taxonomy_additive_lineage_v4_v5_v5_1():
    """Verify v4 (38) and v5 (61) are strictly preserved in v5.1 (78)."""
    assert TAXONOMY_V4_PATH.exists(), f"Taxonomy file missing: {TAXONOMY_V4_PATH}"
    assert TAXONOMY_V5_PATH.exists(), f"Taxonomy file missing: {TAXONOMY_V5_PATH}"
    assert TAXONOMY_V5_1_PATH.exists(), f"Taxonomy file missing: {TAXONOMY_V5_1_PATH}"

    with open(TAXONOMY_V4_PATH, encoding="utf-8") as f:
        v4_data = json.load(f)
    v4_l2s = [item["name"] for grp in v4_data["level1"] for item in grp["level2"]]
    assert len(v4_l2s) == 38

    with open(TAXONOMY_V5_PATH, encoding="utf-8") as f:
        v5_data = json.load(f)
    v5_l2s = [item["name"] for grp in v5_data["level1"] for item in grp["level2"]]
    assert len(v5_l2s) == 61

    with open(TAXONOMY_V5_1_PATH, encoding="utf-8") as f:
        v5_1_data = json.load(f)
    v5_1_l2s = set(item["name"] for grp in v5_1_data["level1"] for item in grp["level2"])
    assert len(v5_1_l2s) == 78

    # All v4 and v5 L2s must exist in v5.1
    for l2 in v4_l2s:
        assert l2 in v5_1_l2s, f"v4 L2 '{l2}' missing in v5.1"
    for l2 in v5_l2s:
        assert l2 in v5_1_l2s, f"v5 L2 '{l2}' missing in v5.1"
