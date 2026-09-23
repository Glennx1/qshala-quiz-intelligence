import re
from typing import List, Dict, Any, Optional, Tuple

class QuestionExtractor:
    """
    Extracts structured question-answer pairs from classified slides.
    Supports:
    - Pattern A: Consecutive Slide Pair (Slide i = QUESTION, Slide i+1 = ANSWER)
    - Pattern C: Lookahead Triplet (Slide i = QUESTION, Slide i+1 = CLUE/CONTENT, Slide i+2 = ANSWER)
    - Pattern B: Self-contained Slide (Answer in speaker notes or body text)
    - Section/Round Tracking: Captures round number and round subtopic
    """

    MCQ_PATTERN = re.compile(
        r"(?:^|\n)\s*([A-D1-4][\.\)]\s*|\([A-D1-4]\)\s*)(.+?)(?=(?:\n\s*(?:[A-D1-4][\.\)]|\([A-D1-4]\))|$))",
        re.DOTALL | re.IGNORECASE
    )

    ANSWER_REGEX = re.compile(
        r"(?:Correct Answer|Solution|Answer|Ans)\s*[:\-]?\s*(.+?)(?:\n|$)",
        re.IGNORECASE
    )

    ROUND_REGEX = re.compile(
        r"Round\s*(\d+)(?:\s*[:\-]?\s*(.*))?",
        re.IGNORECASE
    )

    def extract_from_slides(self, slides: List[Dict[str, Any]], doc_title: str, doc_year: Optional[int]) -> List[Dict[str, Any]]:
        extracted_questions = []
        i = 0
        n = len(slides)

        current_round_num: Optional[int] = None
        current_subtopic: Optional[str] = None

        while i < n:
            current = slides[i]
            slide_type = current.get("slide_type", "CONTENT")
            title = current.get("title", "")
            text = current.get("extracted_text", "")
            notes = current.get("speaker_notes", "")

            # Check if this slide is a Section / Round Marker
            if slide_type == "SECTION_MARKER" or re.search(r"\bround\s*\d+", title, re.IGNORECASE):
                round_match = self.ROUND_REGEX.search(f"{title} {text}")
                if round_match:
                    try:
                        current_round_num = int(round_match.group(1))
                    except Exception:
                        pass
                    sub = round_match.group(2)
                    if sub and len(sub.strip()) > 2:
                        current_subtopic = sub.strip()
                i += 1
                continue

            # Pattern A: Question on Slide i, Answer on Slide i + 1
            if slide_type == "QUESTION" and i + 1 < n and slides[i+1].get("slide_type") == "ANSWER":
                ans_slide = slides[i+1]
                q_text, options = self._parse_question_and_options(text)
                ans_text, explanation = self._parse_answer_and_explanation(ans_slide.get("extracted_text", ""))

                # If answer text is still empty, check speaker notes of the answer slide
                if not ans_text and ans_slide.get("speaker_notes"):
                    ans_text, explanation = self._parse_answer_and_explanation(ans_slide.get("speaker_notes", ""))

                if ans_text:
                    q_imgs = list(current.get("image_paths") or []) + list(ans_slide.get("image_paths") or [])
                    q_media = list(current.get("all_media_items") or []) + list(ans_slide.get("all_media_items") or [])
                    extracted_questions.append({
                        "slide_id": current.get("id"),
                        "answer_slide_id": ans_slide.get("id"),
                        "question_text": q_text,
                        "answer": ans_text,
                        "options": options,
                        "explanation": explanation or ans_slide.get("extracted_text", ""),
                        "subtopic": current_subtopic,
                        "round_number": current_round_num,
                        "question_type": "MULTIPLE_CHOICE" if options else "SLIDE_QA",
                        "source_year": doc_year or 2024,
                        "slide_number": current.get("slide_number"),
                        "answer_slide_number": ans_slide.get("slide_number"),
                        "source_slide_range": f"Slide {current.get('slide_number')}-{ans_slide.get('slide_number')}",
                        "image_refs": q_imgs,
                        "media_items": q_media,
                        "speaker_notes": f"{notes}\n{ans_slide.get('speaker_notes', '')}".strip()
                    })
                    i += 2
                    continue

            # Pattern C: Question on Slide i, Clue/Image on Slide i + 1, Answer on Slide i + 2
            if slide_type == "QUESTION" and i + 2 < n and slides[i+2].get("slide_type") == "ANSWER":
                middle_slide = slides[i+1]
                ans_slide = slides[i+2]
                q_text, options = self._parse_question_and_options(text)
                ans_text, explanation = self._parse_answer_and_explanation(ans_slide.get("extracted_text", ""))

                if ans_text:
                    mid_text = middle_slide.get("extracted_text", "")
                    combined_exp = f"{explanation}\nClue: {mid_text}".strip() if mid_text else explanation
                    q_imgs = list(current.get("image_paths") or []) + list(middle_slide.get("image_paths") or []) + list(ans_slide.get("image_paths") or [])
                    q_media = list(current.get("all_media_items") or []) + list(middle_slide.get("all_media_items") or []) + list(ans_slide.get("all_media_items") or [])
                    extracted_questions.append({
                        "slide_id": current.get("id"),
                        "answer_slide_id": ans_slide.get("id"),
                        "question_text": q_text,
                        "answer": ans_text,
                        "options": options,
                        "explanation": combined_exp,
                        "subtopic": current_subtopic,
                        "round_number": current_round_num,
                        "question_type": "MULTIPLE_CHOICE" if options else "SLIDE_QA",
                        "source_year": doc_year or 2024,
                        "slide_number": current.get("slide_number"),
                        "answer_slide_number": ans_slide.get("slide_number"),
                        "source_slide_range": f"Slide {current.get('slide_number')}-{ans_slide.get('slide_number')}",
                        "image_refs": q_imgs,
                        "media_items": q_media,
                        "speaker_notes": f"{notes}\n{ans_slide.get('speaker_notes', '')}".strip()
                    })
                    i += 3
                    continue

            # Pattern B: Question and Answer on same slide (notes or trailing text)
            if slide_type == "QUESTION":
                q_text, options = self._parse_question_and_options(text)
                ans_text = ""
                explanation = ""

                # Look in notes first
                if notes:
                    ans_text, explanation = self._parse_answer_and_explanation(notes)

                # Look in body text if not found in notes
                if not ans_text:
                    ans_text, explanation = self._parse_answer_and_explanation(text)

                # Only include if a real answer was resolved
                if ans_text and ans_text.lower() not in ["see explanation", "answer indicated on slide", ""]:
                    q_imgs = list(current.get("image_paths") or [])
                    q_media = list(current.get("all_media_items") or [])
                    extracted_questions.append({
                        "slide_id": current.get("id"),
                        "answer_slide_id": None,
                        "question_text": q_text,
                        "answer": ans_text,
                        "options": options,
                        "explanation": explanation,
                        "subtopic": current_subtopic,
                        "round_number": current_round_num,
                        "question_type": "MULTIPLE_CHOICE" if options else "SLIDE_QA",
                        "source_year": doc_year or 2024,
                        "slide_number": current.get("slide_number"),
                        "answer_slide_number": None,
                        "source_slide_range": f"Slide {current.get('slide_number')}",
                        "image_refs": q_imgs,
                        "media_items": q_media,
                        "speaker_notes": notes
                    })
                i += 1
                continue

            i += 1

        return extracted_questions

    def _parse_question_and_options(self, text: str) -> Tuple[str, Optional[List[str]]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return text, None

        q_lines = []
        options = []

        for line in lines:
            if re.match(r"^QUESTION\s*\d*[:\.\-]?$", line, re.IGNORECASE):
                continue
            # Check if this line is an option: (A), A., A), [A], 1., 1)
            if re.match(r"^(\([A-D1-4]\)|\[[A-D1-4]\]|[A-D1-4][\.\)])\s+", line, re.IGNORECASE):
                options.append(line)
            else:
                if not options:
                    q_lines.append(line)

        question_text = " ".join(q_lines) if q_lines else lines[0]
        question_text = re.sub(r"^(?:QUESTION\s*\d*[:\.\-]?|Q\d*[:\.\-]?|\d+[\.\)])\s*", "", question_text, flags=re.IGNORECASE)

        return question_text.strip(), options if len(options) >= 2 else None

    def _parse_answer_and_explanation(self, text: str) -> Tuple[str, str]:
        if not text:
            return "", ""
        cleaned_text = re.sub(r"^ANSWER\s*\d*[:\.\-]?\s*", "", text, flags=re.IGNORECASE).strip()
        match = self.ANSWER_REGEX.search(cleaned_text)
        if match:
            ans = match.group(1).strip()
            explanation = cleaned_text.replace(match.group(0), "").strip()
            explanation = re.sub(r"^(?:Explanation\s*(?:&\s*Context)?|Context)\s*[:\-]?\s*", "", explanation, flags=re.IGNORECASE).strip()
            return ans, explanation

        lines = [l.strip() for l in cleaned_text.splitlines() if l.strip()]
        if lines:
            # First line is answer if concise (< 80 chars), remaining is explanation
            first = lines[0]
            if len(first) < 120 and not first.endswith("?"):
                return first, " ".join(lines[1:]) if len(lines) > 1 else ""
            return lines[0], " ".join(lines[1:])

        return "", ""
