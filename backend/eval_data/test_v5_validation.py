import json
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
tax_v5_path = ROOT / "backend" / "app" / "services" / "tagging" / "qshala_taxonomy_v5.json"
gold_path = ROOT / "backend" / "eval_data" / "gold_labels_145.csv"

with open(tax_v5_path, encoding='utf-8') as f:
    tax = json.load(f)

l2_to_l1 = {}
codes = set()
names = set()
amp_names = []
empty_descs = []

for grp in tax['level1']:
    for sub in grp['level2']:
        c = sub.get('code')
        n = sub.get('name')
        d = sub.get('description', '')
        if c in codes:
            print(f"Duplicate code: {c}")
        codes.add(c)
        if n in names:
            print(f"Duplicate name: {n}")
        names.add(n)
        if '&' in n:
            amp_names.append(n)
        if not d.strip():
            empty_descs.append(n)
        l2_to_l1[n] = grp['name']

print(f"Taxonomy v5: {len(tax['level1'])} L1s, {len(names)} L2s, {len(codes)} unique codes")
print(f"Ampersands in L2: {amp_names}")
print(f"Empty descriptions: {empty_descs}")

with open(gold_path, encoding='utf-8-sig') as f:
    gold = list(csv.DictReader(f))

errors = []
for r in gold:
    l2 = r['gold_l2']
    if l2 not in l2_to_l1:
        errors.append(f"[{r['id']}] gold_l2 '{l2}' not in v5")
    else:
        exp_l1 = l2_to_l1[l2]
        if r['gold_l1'] != exp_l1:
            errors.append(f"[{r['id']}] L1 mismatch: got '{r['gold_l1']}', expected '{exp_l1}'")
    alt = r.get('alt_l2', '')
    if alt:
        for a in alt.split('|'):
            a = a.strip()
            if a and a not in l2_to_l1:
                errors.append(f"[{r['id']}] alt_l2 '{a}' not in v5")

print(f"Gold validation against v5 errors count: {len(errors)}")
if errors:
    for e in errors[:10]:
        print(" ", e)
else:
    print("SUCCESS: 0 errors validating gold_labels_145.csv against taxonomy v5!")
