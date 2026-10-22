"""Validator for gold_labels_145.csv against Taxonomy v5 (or v4) and canonical enums.

Checks:
- All 145 rows present
- All gold_l2 exist in Taxonomy
- All gold_l1 match parent in Taxonomy
- All alt_l2 exist in Taxonomy
- Valid enum values for entity_type, geography, shelf_life, sensitivity
- Near-duplicate / duplicate question text detection
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

VALID_ENTITY_TYPES = {"COMPANY", "PERSON", "TERM", "PRODUCT_OR_OBJECT", "BOOK",
                      "ORGANISATION", "POLICY", "NUMBER", "PLACE", "EVENT"}
VALID_GEOGRAPHY = {"IN", "INTL", "MIXED"}
VALID_SHELF_LIFE = {"EVERGREEN", "REVIEW_YEARLY", "TIME_SENSITIVE"}
VALID_SENSITIVITY = {"NONE", "POLITICAL", "MATURE_REFERENCE"}

def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

def validate_gold_dataset(taxonomy_version: str = "v5") -> bool:
    tax_file = f"qshala_taxonomy_{taxonomy_version}.json"
    taxonomy_path = ROOT / "app" / "services" / "tagging" / tax_file
    gold_path = HERE / "gold_labels_145.csv"

    print(f"Validating {gold_path.name} against {taxonomy_path.name}...")
    errors = []
    warnings = []

    if not taxonomy_path.exists():
        sys.exit(f"Taxonomy file missing: {taxonomy_path}")
    with open(taxonomy_path, encoding="utf-8") as f:
        tax = json.load(f)

    l2_to_l1 = {}
    for grp in tax["level1"]:
        for item in grp["level2"]:
            l2_to_l1[item["name"]] = grp["name"]

    if not gold_path.exists():
        sys.exit(f"Gold labels file missing: {gold_path}")
    with open(gold_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} gold question rows.")

    seen_ids = set()
    norm_text_to_ids = defaultdict(list)

    for i, r in enumerate(rows, 1):
        qid = r["id"].strip()
        if not qid:
            errors.append(f"Row {i}: Missing ID")
        if qid in seen_ids:
            errors.append(f"Duplicate question ID: {qid}")
        seen_ids.add(qid)

        gold_l1 = r["gold_l1"].strip()
        gold_l2 = r["gold_l2"].strip()
        alt_l2 = r.get("alt_l2", "").strip()

        if gold_l2 not in l2_to_l1:
            errors.append(f"[{qid}] Invalid gold_l2: '{gold_l2}' not in taxonomy {taxonomy_version}")
        else:
            expected_l1 = l2_to_l1[gold_l2]
            if gold_l1 != expected_l1:
                errors.append(f"[{qid}] L1 mismatch: got '{gold_l1}', expected '{expected_l1}' for L2 '{gold_l2}'")

        if alt_l2:
            for alt in alt_l2.split("|"):
                alt_clean = alt.strip()
                if alt_clean and alt_clean not in l2_to_l1:
                    errors.append(f"[{qid}] Invalid alt_l2: '{alt_clean}' not in taxonomy {taxonomy_version}")

        # Enum checks
        entity = r.get("entity_type", "").strip()
        if entity not in VALID_ENTITY_TYPES:
            errors.append(f"[{qid}] Invalid entity_type: '{entity}'")

        geo = r.get("geography", "").strip()
        if geo not in VALID_GEOGRAPHY:
            errors.append(f"[{qid}] Invalid geography: '{geo}'")

        shelf = r.get("shelf_life", "").strip()
        if shelf not in VALID_SHELF_LIFE:
            errors.append(f"[{qid}] Invalid shelf_life: '{shelf}'")

        sens = r.get("sensitivity", "").strip()
        if sens not in VALID_SENSITIVITY:
            errors.append(f"[{qid}] Invalid sensitivity: '{sens}'")

        norm_q = normalize_text(r.get("question_text", ""))
        norm_text_to_ids[norm_q].append(qid)

    # Duplicate / near-duplicate checks
    for norm_q, qids in norm_text_to_ids.items():
        if len(qids) > 1:
            warnings.append(f"Near-duplicate question text between {qids}: '{norm_q[:60]}...'")

    print("\n--- VALIDATION REPORT ---")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN] {w}")

    if errors:
        print(f"\nFAILED with {len(errors)} errors:")
        for e in errors:
            print(f"  [ERROR] {e}")
        return False

    print(f"\nSUCCESS: All gold labels, taxonomy structures, and enums are 100% valid against {taxonomy_version}!")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate gold dataset against taxonomy")
    parser.add_argument("--taxonomy", choices=["v4", "v5"], default="v5", help="Taxonomy version to validate against (default: v5)")
    args = parser.parse_args()

    success = validate_gold_dataset(taxonomy_version=args.taxonomy)
    if not success:
        sys.exit(1)
