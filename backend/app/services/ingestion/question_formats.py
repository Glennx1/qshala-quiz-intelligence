"""Question format detection, structuring, and payload management.

Handles specialized quiz formats:
1. CONNECT_4 / CONNECT: Multi-image or multi-clue common link questions.
2. STEPPED_CLUE / PORTFOLIO_BUILDER: 3-step progressive clues with decreasing buzzer points.
3. ARRANGE_ORDER / TICKER_TANGLE: 4 items to sort with graduated scoring.
4. VISUAL_CLUE, AUDIO_CLUE, VIDEO_CLUE, and STANDARD_QA.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# Format Constants
FMT_QA = "QA"
FMT_CONNECT_4 = "CONNECT_4"
FMT_STEPPED_CLUE = "STEPPED_CLUE"
FMT_ARRANGE_ORDER = "ARRANGE_ORDER"
FMT_VISUAL_CLUE = "VISUAL_CLUE"
FMT_AUDIO_CLUE = "AUDIO_CLUE"
FMT_VIDEO_CLUE = "VIDEO_CLUE"


# Regex detectors
_STEPPED_RE = re.compile(
    r"(?:clue\s*1\s*:\s*\+?20\s*/\s*-?15|clue\s*2\s*:\s*\+?15\s*/\s*-?10|clue\s*3\s*:\s*\+?10\s*/\s*-?5|"
    r"portfolio\s*builder|3\s*parts/clues?\s*to\s*each\s*question)",
    re.IGNORECASE
)

_ARRANGE_RE = re.compile(
    r"(?:\barrange\b|ticker\s*tangle|chronological(?:\s*order)?|lowest\s+to\s+highest|"
    r"highest\s+to\s+lowest|earliest\s+to\s+latest|from\s+1st\s+to\s+last|correct\s+order|"
    r"in\s+(?:the\s+)?order\s+of)",
    re.IGNORECASE
)

_CONNECT_RE = re.compile(
    r"(?:\bconnect(?:ion|ions|s)?\b|what\s+connects|common\s+link|find\s+the\s+link|"
    r"4\s*pics\s*1\s*word|four\s*images|connect\s*4)",
    re.IGNORECASE
)


def detect_and_structure_format(
    question_text: str,
    answer: str,
    options: Optional[List[str]] = None,
    image_refs: Optional[List[str]] = None,
    audio_refs: Optional[List[str]] = None,
    video_refs: Optional[List[str]] = None,
    raw_context: str = "",
    deck_round_format: str = "",
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Inspects question fields and returns (format_name, format_payload)."""
    q_text = question_text or ""
    combined = f"{q_text} {raw_context} {deck_round_format}".strip()
    imgs = image_refs or []
    vids = video_refs or []
    auds = audio_refs or []
    opts = options or []

    # 1. Stepped Clue (Portfolio Builder / 3 Clues buzzer round)
    if _STEPPED_RE.search(combined) or deck_round_format in ("THREE_CLUE", "BUZZER") and ("clue" in q_text.lower() or "clue 1" in combined.lower()):
        clues: List[Dict[str, Any]] = []
        # Attempt to parse progressive clues if embedded in text
        clue_matches = re.split(r"(?:^|\n)\s*(?:(?:\d+\.)?\s*Clue\s*(\d)\s*:\s*([+\-\d/]+))", q_text, flags=re.I)
        if len(clue_matches) > 1:
            # We have regex split: preamble, step_num, points, text...
            i = 1
            while i < len(clue_matches) - 2:
                step_num = clue_matches[i]
                points = clue_matches[i+1]
                body = clue_matches[i+2].strip()
                clues.append({
                    "step": int(step_num) if step_num and step_num.isdigit() else (len(clues) + 1),
                    "points": points,
                    "text": body,
                    "image": imgs[len(clues)] if len(clues) < len(imgs) else None,
                })
                i += 3
        if not clues:
            # Construct standard 3-tier structure
            clues = [
                {"step": 1, "points": "+20/-15", "text": q_text, "image": imgs[0] if imgs else None},
                {"step": 2, "points": "+15/-10", "text": "Additional context clue", "image": imgs[1] if len(imgs) > 1 else None},
                {"step": 3, "points": "+10/-5", "text": "Direct giveaway clue", "image": imgs[2] if len(imgs) > 2 else None},
            ]
        payload = {
            "type": FMT_STEPPED_CLUE,
            "badge": "Portfolio Builder • Stepped Clues",
            "clues": clues,
            "rules": "All on buzzer • 1 attempt per clue • Clue 1: +20/-15, Clue 2: +15/-10, Clue 3: +10/-5",
        }
        return FMT_STEPPED_CLUE, payload

    # 2. Arrange Order (Ticker Tangle / Chronology)
    if _ARRANGE_RE.search(combined) or deck_round_format == "ARRANGE_ORDER":
        items: List[Dict[str, Any]] = []
        # Check if options contain 4 items (A, B, C, D)
        if opts and len(opts) >= 4:
            for i, opt in enumerate(opts[:4]):
                key = chr(65 + i)  # A, B, C, D
                items.append({"key": key, "text": opt, "image": imgs[i] if i < len(imgs) else None})
        elif imgs and len(imgs) >= 4:
            for i in range(4):
                items.append({"key": chr(65 + i), "text": f"Item {chr(65 + i)}", "image": imgs[i]})
        else:
            # Extract lines from question text if separated
            lines = [l.strip(" 1234.ABCD)-") for l in q_text.split("\n") if l.strip()]
            if len(lines) >= 4:
                for i in range(4):
                    items.append({"key": chr(65 + i), "text": lines[i], "image": imgs[i] if i < len(imgs) else None})
            else:
                items = [
                    {"key": "A", "text": "Element A", "image": imgs[0] if len(imgs) > 0 else None},
                    {"key": "B", "text": "Element B", "image": imgs[1] if len(imgs) > 1 else None},
                    {"key": "C", "text": "Element C", "image": imgs[2] if len(imgs) > 2 else None},
                    {"key": "D", "text": "Element D", "image": imgs[3] if len(imgs) > 3 else None},
                ]

        payload = {
            "type": FMT_ARRANGE_ORDER,
            "badge": "Ticker Tangle • Arrange Order",
            "instruction": q_text,
            "items": items,
            "scoring": {"all_correct": "+20", "two_correct": "+10", "one_correct": "+5"},
            "time_limit_seconds": 60,
        }
        return FMT_ARRANGE_ORDER, payload

    # 3. Connect / Connect 4
    if _CONNECT_RE.search(combined) or deck_round_format == "CONNECT" or (imgs and len(imgs) >= 4 and not opts):
        elements: List[Dict[str, Any]] = []
        for i in range(min(4, len(imgs) if imgs else 4)):
            img = imgs[i] if i < len(imgs) else None
            elements.append({
                "index": i + 1,
                "label": f"Clue {i + 1}",
                "image": img,
            })
        payload = {
            "type": FMT_CONNECT_4,
            "badge": "Connect 4 • Common Link",
            "prompt": q_text or "What common thread or concept connects all of these?",
            "elements": elements,
            "connection_reveal": answer,
        }
        return FMT_CONNECT_4, payload

    # 4. Media-specific clues
    if vids:
        return FMT_VIDEO_CLUE, {"type": FMT_VIDEO_CLUE, "video_url": vids[0]}
    if auds:
        return FMT_AUDIO_CLUE, {"type": FMT_AUDIO_CLUE, "audio_url": auds[0]}
    if imgs:
        return FMT_VISUAL_CLUE, {"type": FMT_VISUAL_CLUE, "image_url": imgs[0]}

    # 5. Default QA
    return FMT_QA, {"type": FMT_QA}
