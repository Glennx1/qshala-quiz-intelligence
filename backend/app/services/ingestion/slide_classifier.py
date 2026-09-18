import re
from typing import Dict, Any

class SlideClassifier:
    """
    Classifies slide type based on textual heuristics, layout cues, and semantic patterns.
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
        r"\b(it is|the answer is)\b",
    ]

    TITLE_INDICATORS = [
        r"\b(welcome|round\s*\d+|rules|scores|scoreboard|guidelines|quiz master|tie breaker)\b",
        r"\b(final round|prelims|finals|qshala)\b",
    ]

    def classify(self, slide_data: Dict[str, Any]) -> str:
        text = (slide_data.get("extracted_text") or "").lower()
        title = (slide_data.get("title") or "").lower()
        notes = (slide_data.get("speaker_notes") or "").lower()
        full_text = f"{title}\n{text}\n{notes}"

        # Check for title/rules/scoreboard first
        if len(text.split()) < 8 and any(re.search(pat, title) for pat in self.TITLE_INDICATORS):
            return "TITLE"
        if any(re.search(pat, title) for pat in [r"scoreboard", r"scores", r"points"]):
            return "SCOREBOARD"
        if any(re.search(pat, title) for pat in [r"rules", r"guidelines", r"instructions"]):
            return "RULES"

        # Check for Answer
        is_answer = any(re.search(pat, full_text) for pat in self.ANSWER_INDICATORS)
        is_question = any(re.search(pat, full_text) for pat in self.QUESTION_INDICATORS)

        # If it explicitly says "Answer:" or "Ans:" as primary header or first line
        if re.search(r"^\s*(ans|answer)\s*[:\-]", text, re.MULTILINE):
            return "ANSWER"

        if is_question and not is_answer:
            return "QUESTION"

        if is_answer and not is_question:
            return "ANSWER"

        if is_question and is_answer:
            # If both, likely a question slide with answer in notes or at bottom
            return "QUESTION"

        # Short text with a title
        if len(text.split()) < 12 and title:
            if any(re.search(pat, title) for pat in self.QUESTION_INDICATORS):
                return "QUESTION"
            return "TITLE"

        return "CONTENT"
