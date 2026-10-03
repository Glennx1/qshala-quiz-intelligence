import re
from typing import Dict, Any, List, Tuple

class SlideClassifier:
    """
    Context-aware two-pass slide classifier for QShala presentation decks.
    Pass 1: Computes individual category confidence scores.
    Pass 2: Uses sequence context (e.g. Question -> Answer patterns, Section markers)
            to eliminate false positives and catch implicit answer slides.
    """

    QUESTION_INDICATORS = [
        r"\?",
        r"\b(who|what|where|when|why|which|how|identify|name the)\b",
        r"\b(q\d+|question\s*\d*)\b",
        r"^[0-9]+[\.\)]\s+",
        r"\(A\).*\(B\)",
        r"clue\s*\d*",
    ]

    ANSWER_INDICATORS = [
        r"\b(ans|answer|ans:)\b",
        r"\b(correct answer|solution)\b",
        r"\b(explanation|did you know|trivia)\b",
        r"\b(it is|the answer is|this was)\b",
    ]

    SECTION_INDICATORS = [
        r"\b(round\s*\d+|section\s*\d+|part\s*\d+|theme\s*\d+|finals|prelims|tie\s*breaker)\b",
        r"\b(answers\s+follow|hand\s+in\s+your\s+sheets|discuss\s+(?:the\s+)?answers|intermission|break|announcement|qshots)\b",
    ]

    TITLE_INDICATORS = [
        r"\b(welcome|rules|scores|scoreboard|guidelines|quiz master|qshala|instructions|thank you)\b",
    ]

    def score_slide(self, slide_data: Dict[str, Any]) -> Dict[str, float]:
        """Pass 1: Scores an individual slide across categories."""
        text = (slide_data.get("extracted_text") or "").strip()
        title = (slide_data.get("title") or "").strip()
        notes = (slide_data.get("speaker_notes") or "").strip()
        full_text = f"{title}\n{text}\n{notes}".lower()
        title_lower = title.lower()
        text_lower = text.lower()
        word_count = len(text.split())

        scores = {
            "TITLE": 0.1,
            "SECTION_MARKER": 0.0,
            "SCOREBOARD": 0.0,
            "RULES": 0.0,
            "QUESTION": 0.0,
            "ANSWER": 0.0,
            "CONTENT": 0.3
        }

        # Slide 1 is almost always TITLE
        slide_num = slide_data.get("slide_number", 1)
        if slide_num == 1:
            scores["TITLE"] += 0.7

        # Section markers (Round 1, Round 2)
        if any(re.search(pat, title_lower) for pat in self.SECTION_INDICATORS):
            scores["SECTION_MARKER"] += 0.85
        elif any(re.search(pat, text_lower) for pat in self.SECTION_INDICATORS) and word_count < 10:
            scores["SECTION_MARKER"] += 0.75

        # Scoreboards & Rules
        if any(re.search(pat, full_text) for pat in [r"scoreboard", r"scores", r"leaderboard", r"points"]):
            scores["SCOREBOARD"] += 0.85
        if any(re.search(pat, full_text) for pat in [r"rules", r"guidelines", r"instructions", r"marking scheme"]):
            scores["RULES"] += 0.85

        # Title indicators
        if any(re.search(pat, title_lower) for pat in self.TITLE_INDICATORS):
            scores["TITLE"] += 0.65

        # Explicit Answer prefixes (only if not a section/transition marker)
        if scores["SECTION_MARKER"] < 0.5:
            if re.search(r"^\s*(ans|answer|solution)\s*[:\-]", text_lower, re.MULTILINE):
                scores["ANSWER"] += 0.90
            elif any(re.search(pat, full_text) for pat in self.ANSWER_INDICATORS):
                scores["ANSWER"] += 0.60

        # Question signals
        q_hits = sum(1 for pat in self.QUESTION_INDICATORS if re.search(pat, full_text))
        if q_hits >= 2:
            scores["QUESTION"] += 0.80
        elif q_hits == 1:
            # Require text not to be purely rhetorical
            if "?" in full_text or re.search(r"\b(q\d+|question|name the|identify)\b", full_text):
                scores["QUESTION"] += 0.60
            else:
                scores["QUESTION"] += 0.35

        return scores

    def classify(self, slide_data: Dict[str, Any]) -> str:
        """Single-slide classification for backwards compatibility."""
        scores = self.score_slide(slide_data)
        best_type = max(scores.items(), key=lambda x: x[1])[0]
        return best_type

    def classify_deck(self, slides: List[Dict[str, Any]]) -> List[str]:
        """
        Pass 2: Contextual sequence classification across all slides in a deck.
        Corrects ambiguous slides based on preceding/following neighbors.
        """
        if not slides:
            return []

        # Pass 1: Raw scoring
        scored_slides = [self.score_slide(s) for s in slides]
        classified_types = [max(sc.items(), key=lambda x: x[1])[0] for sc in scored_slides]

        # Pass 2: Sequential context adjustments
        n = len(slides)
        for i in range(n):
            current_type = classified_types[i]
            prev_type = classified_types[i - 1] if i > 0 else None
            next_type = classified_types[i + 1] if i + 1 < n else None
            s_text = (slides[i].get("extracted_text") or "").strip()
            s_text_lower = s_text.lower()

            # Pattern 1: Interstitial "ANSWER" prompt slide
            # In tournament decks, quizmasters insert a slide with literally just the word "ANSWER"
            # before revealing the actual answer on the subsequent slide.
            is_answer_prompt = (
                s_text_lower in ["answer", "answers", "the answer", "solution", "solutions", "the answer is"]
                or (len(s_text.split()) <= 2 and "answer" in s_text_lower and "?" not in s_text)
            )

            if is_answer_prompt:
                classified_types[i] = "SECTION_MARKER"
                # Promote the NEXT slide to ANSWER if it exists
                if i + 1 < n:
                    classified_types[i + 1] = "ANSWER"
                continue

            # Pattern 2: If previous slide was a QUESTION, and current slide is CONTENT or ambiguous,
            # it is very likely an ANSWER slide (especially if short or has image).
            if prev_type == "QUESTION":
                if current_type in ["CONTENT", "TITLE"]:
                    # If it's not a section marker or scoreboard, promote to ANSWER
                    if scored_slides[i]["SECTION_MARKER"] < 0.5 and scored_slides[i]["SCOREBOARD"] < 0.5:
                        classified_types[i] = "ANSWER"

            # Pattern 3: If a slide was marked ANSWER but precedes a QUESTION and has question marks, recheck
            if current_type == "ANSWER" and "?" in s_text:
                if scored_slides[i]["QUESTION"] >= 0.5:
                    classified_types[i] = "QUESTION"

        return classified_types
