import re
from typing import List, Dict, Any, Optional

class QuestionExtractor:
    """
    Extracts structured question-answer pairs from classified slides,
    linking cross-slide Q&A sequences and extracting options and metadata.
    """

    MCQ_PATTERN = re.compile(
        r"(?:^|\n)\s*([A-D1-4][\.\)]\s*|\([A-D1-4]\)\s*)(.+?)(?=(?:\n\s*(?:[A-D1-4][\.\)]|\([A-D1-4]\))|$))",
        re.DOTALL | re.IGNORECASE
    )

    ANSWER_REGEX = re.compile(
        r"(?:Ans|Answer|Correct Answer|Solution)\s*[:\-]?\s*(.+?)(?:\n|$)",
        re.IGNORECASE
    )

    TOPIC_KEYWORDS = {
        "Australian History": ["australia", "aboriginal", "first fleet", "cook", "barton", "canberra", "sydney", "melbourne", "eureka", "outback", "koala", "kangaroo"],
        "Science & Nature": ["planet", "gravity", "animal", "plant", "solar", "molecule", "energy", "dinosaur", "species", "biology", "physics"],
        "World Geography": ["capital", "river", "mountain", "ocean", "continent", "flag", "border", "desert", "country"],
        "Literature & Arts": ["author", "book", "character", "painting", "poem", "shakespeare", "mythology", "artist"],
        "Sports & Games": ["olympics", "cricket", "football", "tennis", "world cup", "player", "tournament"],
        "General Knowledge": []
    }

    def extract_from_slides(self, slides: List[Dict[str, Any]], doc_title: str, doc_year: Optional[int]) -> List[Dict[str, Any]]:
        extracted_questions = []
        i = 0
        n = len(slides)

        while i < n:
            current = slides[i]
            slide_type = current.get("slide_type", "CONTENT")
            text = current.get("extracted_text", "")
            notes = current.get("speaker_notes", "")
            full_text = f"{text}\n{notes}".strip()

            # Pattern A: Question on Slide i, Answer on Slide i + 1
            if slide_type == "QUESTION" and i + 1 < n and slides[i+1].get("slide_type") == "ANSWER":
                ans_slide = slides[i+1]
                q_text, options = self._parse_question_and_options(text)
                ans_text, explanation = self._parse_answer_and_explanation(ans_slide.get("extracted_text", ""))

                topic = self._infer_topic(f"{doc_title} {q_text} {ans_text}")
                diff = self._infer_difficulty(q_text, options)
                g_min, g_max = self._infer_grades(q_text, diff)

                extracted_questions.append({
                    "slide_id": current.get("id"),
                    "answer_slide_id": ans_slide.get("id"),
                    "question_text": q_text,
                    "answer": ans_text or "See explanation",
                    "options": options,
                    "explanation": explanation or ans_slide.get("extracted_text", ""),
                    "topic": topic,
                    "difficulty": diff,
                    "grade_min": g_min,
                    "grade_max": g_max,
                    "question_type": "MULTIPLE_CHOICE" if options else "TRIVIA_SHORT_ANSWER",
                    "source_year": doc_year or 2024,
                    "slide_number": current.get("slide_number"),
                    "answer_slide_number": ans_slide.get("slide_number")
                })
                i += 2
                continue

            # Pattern B: Question and Answer on same slide (notes or text)
            if slide_type == "QUESTION":
                q_text, options = self._parse_question_and_options(text)
                ans_text = ""
                explanation = ""

                # Look in notes first
                if notes:
                    ans_text, explanation = self._parse_answer_and_explanation(notes)

                # Look in text if not in notes
                if not ans_text:
                    ans_text, explanation = self._parse_answer_and_explanation(text)

                if not ans_text:
                    ans_text = "Historical reference: Consult slide notes."

                topic = self._infer_topic(f"{doc_title} {q_text} {ans_text}")
                diff = self._infer_difficulty(q_text, options)
                g_min, g_max = self._infer_grades(q_text, diff)

                extracted_questions.append({
                    "slide_id": current.get("id"),
                    "answer_slide_id": None,
                    "question_text": q_text,
                    "answer": ans_text,
                    "options": options,
                    "explanation": explanation,
                    "topic": topic,
                    "difficulty": diff,
                    "grade_min": g_min,
                    "grade_max": g_max,
                    "question_type": "MULTIPLE_CHOICE" if options else "TRIVIA_SHORT_ANSWER",
                    "source_year": doc_year or 2024,
                    "slide_number": current.get("slide_number"),
                    "answer_slide_number": None
                })
                i += 1
                continue

            i += 1

        return extracted_questions

    def _parse_question_and_options(self, text: str) -> (str, Optional[List[str]]):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return text, None

        q_lines = []
        options = []

        for line in lines:
            # Check if this line is an option
            if re.match(r"^(\([A-D1-4]\)|[A-D1-4][\.\)])\s+", line, re.IGNORECASE):
                options.append(line)
            else:
                if not options:
                    q_lines.append(line)

        question_text = " ".join(q_lines) if q_lines else lines[0]
        # Clean up leading numbers like "1. ", "Q1: "
        question_text = re.sub(r"^(?:Q\d*[:\.\-]?|\d+[\.\)])\s*", "", question_text)

        return question_text.strip(), options if len(options) >= 2 else None

    def _parse_answer_and_explanation(self, text: str) -> (str, str):
        match = self.ANSWER_REGEX.search(text)
        if match:
            ans = match.group(1).strip()
            explanation = text.replace(match.group(0), "").strip()
            return ans, explanation

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            return lines[0], " ".join(lines[1:]) if len(lines) > 1 else ""
        return "Answer indicated on slide", text

    def _infer_topic(self, text: str) -> str:
        text_lower = text.lower()
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return topic
        return "General Knowledge"

    def _infer_difficulty(self, question: str, options: Optional[List[str]]) -> str:
        words = len(question.split())
        if words < 12 and options:
            return "Easy"
        elif words > 25 or not options:
            return "Hard"
        return "Medium"

    def _infer_grades(self, question: str, difficulty: str) -> (int, int):
        if difficulty == "Easy":
            return 3, 5
        elif difficulty == "Medium":
            return 3, 6
        else:
            return 6, 8
