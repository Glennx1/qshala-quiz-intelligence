"""Polish ARRANGE_ORDER questions to have clear instructions, clean choice items, and sequenced answers."""
import sqlite3
import json
import re

conn = sqlite3.connect('backend/qshala.db')
c = conn.cursor()

c.execute("SELECT id, question_text, answer, explanation, format_payload FROM questions WHERE question_type = 'ARRANGE_ORDER'")
rows = c.fetchall()

print(f"Polishing {len(rows)} ARRANGE_ORDER questions...")

for q_id, q_text, ans, exp, payload_raw in rows:
    payload = json.loads(payload_raw) if payload_raw else {}
    
    # 1. Clean instruction
    lines = [l.strip() for l in (q_text or "").splitlines() if l.strip()]
    instruction = lines[0] if lines else "Arrange in the correct order:"
    if len(lines) > 1 and re.search(r"lowest\s+to|highest\s+to|earliest\s+to|latest|from\s+1st|chronological|order", lines[1], re.I):
        instruction += f" ({lines[1].strip('()')})"
    
    # Clean choice items from lines
    choice_items = []
    for l in lines[2:]:
        # Skip pure digits (slide numbers or position keys)
        if re.match(r"^\d+[\.]?$", l):
            continue
        if l not in choice_items and len(l) > 1:
            choice_items.append(l)

    # 2. Extract answer sequence from explanation / answer
    full_ans_text = f"{ans} {exp}".strip()
    
    # Check if we have items with positions
    # If GDP question:
    if "gdp" in instruction.lower():
        ordered_ans = "1. Taiwan ($976 billion) → 2. India ($4.15 trillion) → 3. Germany ($5.45 trillion) → 4. USA ($32.38 trillion)"
        payload_items = [
            {"key": "A", "text": "Germany ($5.45 trillion)", "order": 3},
            {"key": "B", "text": "Taiwan ($976 billion)", "order": 1},
            {"key": "C", "text": "India ($4.15 trillion)", "order": 2},
            {"key": "D", "text": "USA ($32.38 trillion)", "order": 4},
        ]
    elif "share price" in instruction.lower():
        ordered_ans = "Lowest to Highest: MRF, Page Industries, Honeywell Automation, Shree Cement"
        payload_items = [
            {"key": "A", "text": "MRF", "order": 4},
            {"key": "B", "text": "Page Industries", "order": 3},
            {"key": "C", "text": "Honeywell Automation", "order": 2},
            {"key": "D", "text": "Shree Cement", "order": 1},
        ]
    elif "market crash" in instruction.lower():
        ordered_ans = "Earliest to Latest: Tulip Mania (1637) → Great Depression (1929) → Black Monday (1987) → Dot Com Bubble (2000)"
        payload_items = [
            {"key": "A", "text": "Tulip Mania (1637)", "order": 1},
            {"key": "B", "text": "Great Depression (1929)", "order": 2},
            {"key": "C", "text": "Black Monday (1987)", "order": 3},
            {"key": "D", "text": "Dot Com Bubble (2000)", "order": 4},
        ]
    elif "wealthiest" in instruction.lower() and "women" in instruction.lower():
        ordered_ans = "Lowest to Highest: Kiran Mazumdar-Shaw ($3.4B) → Falguni Nayar ($2.8B) → Rekha Jhunjhunwala ($8B) → Savitri Jindal ($34.3B)"
        payload_items = [
            {"key": "A", "text": "Savitri Jindal ($34.3B)", "order": 4},
            {"key": "B", "text": "Kiran Mazumdar-Shaw ($3.4B)", "order": 2},
            {"key": "C", "text": "Rekha Jhunjhunwala ($8B)", "order": 3},
            {"key": "D", "text": "Falguni Nayar ($2.8B)", "order": 1},
        ]
    elif "unicorn" in instruction.lower():
        ordered_ans = "Earliest to Latest: InMobi (2011) → Flipkart (2012) → Mu Sigma (2013) → Snapdeal (2014)"
        payload_items = [
            {"key": "A", "text": "InMobi (2011)", "order": 1},
            {"key": "B", "text": "Flipkart (2012)", "order": 2},
            {"key": "C", "text": "Mu Sigma (2013)", "order": 3},
            {"key": "D", "text": "Snapdeal (2014)", "order": 4},
        ]
    elif "accounting cycle" in instruction.lower():
        ordered_ans = "1st to Last: Identifying Transactions → Journal Entry → General Ledger → Trial Balance"
        payload_items = [
            {"key": "A", "text": "Identifying Transactions", "order": 1},
            {"key": "B", "text": "Journal Entry", "order": 2},
            {"key": "C", "text": "General Ledger", "order": 3},
            {"key": "D", "text": "Trial Balance", "order": 4},
        ]
    elif "fundraising" in instruction.lower():
        ordered_ans = "1st to Last: Pre-seed Funding → Seed Funding → Series A Funding → IPO"
        payload_items = [
            {"key": "A", "text": "Pre-seed Funding", "order": 1},
            {"key": "B", "text": "Seed Funding", "order": 2},
            {"key": "C", "text": "Series A Funding", "order": 3},
            {"key": "D", "text": "IPO", "order": 4},
        ]
    else:
        # Generic clean
        ordered_ans = f"Correct Order: {full_ans_text[:120]}"
        payload_items = [{"key": chr(65+i), "text": choice_items[i] if i < len(choice_items) else f"Item {chr(65+i)}", "order": i+1} for i in range(4)]

    # Clean formatted question text
    clean_q_text = f"{instruction}"
    if choice_items:
        clean_q_text += "\n\n" + "\n".join(f"{chr(65+i)}. {item}" for i, item in enumerate(choice_items[:4]))

    payload["type"] = "ARRANGE_ORDER"
    payload["instruction"] = instruction
    payload["items"] = payload_items
    payload["has_timer"] = True
    payload["timer_seconds"] = 60
    payload["scoring"] = {"all_correct": "+20", "two_correct": "+10", "one_correct": "+5"}

    c.execute(
        "UPDATE questions SET question_text = ?, answer = ?, format_payload = ? WHERE id = ?",
        (clean_q_text, ordered_ans, json.dumps(payload), q_id)
    )

conn.commit()
print("Successfully polished all ARRANGE_ORDER questions in database.")
conn.close()
