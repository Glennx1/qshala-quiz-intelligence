import re
import math
from typing import Dict, Any, List, Tuple

class DifficultyEngine:
    """
    Calculates the Pedagogical Difficulty Index (PDI) for quiz questions
    based on Bloom's cognitive depth, entity obscurity, readability, and clue scaffolding.
    """

    # High frequency / easily recognizable elementary entities
    COMMON_ELEMENTARY_ANCHORS = {
        "sun", "moon", "earth", "france", "paris", "india", "london", "america",
        "water", "dog", "cat", "lion", "tiger", "apple", "gold", "silver",
        "football", "cricket", "everest", "pacific", "atlantic", "pyramid",
        "red", "blue", "green", "winter", "summer", "tree", "plant", "canada"
    }

    # Cognitive level markers
    LATERAL_SYNTHESIS_PATTERNS = [
        r"\b(connect|connection|in common|link|linked|shared|irony|paradox|coincidence)\b",
        r"\b(pivoted|reinvented|later became|originally named|formerly known)\b",
        r"\b(why did|how did|what prompted|inspired by)\b",
        r"\b(identify the connection|what connects)\b"
    ]

    INFERENCE_PATTERNS = [
        r"\b(how|why|reason|because|lead to|result of|significance|purpose)\b",
        r"\b(derived|consequence|discovery|breakthrough|symbolizes|represents)\b",
        r"\b(which of the following caused|what made)\b"
    ]

    def evaluate(self, question_text: str, answer_text: str, explanation: str = "", notes: str = "") -> Dict[str, Any]:
        """
        Computes the continuous difficulty score (0.00 - 1.00), Bloom's level,
        calibrated grade range, and target audience suitabilities.
        """
        q_clean = question_text.strip()
        ans_clean = answer_text.strip()
        full_context = f"{q_clean} {ans_clean} {explanation} {notes}".lower()

        # 1. Cognitive Depth (Bloom's Taxonomy / Webb's DOK)
        cognitive_level, c_score = self._compute_cognitive_depth(q_clean)

        # 2. Entity & Answer Obscurity
        e_score = self._compute_entity_obscurity(ans_clean, q_clean)

        # 3. Clue Specificity / Constraint Density
        s_score = self._compute_specificity(q_clean)

        # 4. Reading Complexity & Lexical Diversity
        r_score = self._compute_readability(q_clean)

        # 5. Clue Scaffolding / In-question Hints
        h_score = self._compute_scaffolding(q_clean, notes)

        # Pedagogical Difficulty Index (PDI) Weighted Formula
        # Weights: 0.35 Cognitive + 0.25 Obscurity + 0.15 Specificity + 0.15 Readability - 0.10 Scaffolding
        raw_pdi = (
            0.35 * c_score +
            0.25 * e_score +
            0.15 * s_score +
            0.15 * r_score -
            0.10 * h_score
        )

        pdi = max(0.08, min(0.96, round(raw_pdi, 2)))

        # Categorical mapping
        if pdi < 0.40:
            category = "Easy"
            grade_min, grade_max = 1, 5
            audiences = ["primary"]
        elif pdi <= 0.70:
            category = "Medium"
            grade_min, grade_max = 5, 9
            audiences = ["primary", "middle_school", "high_school"]
        else:
            category = "Hard"
            grade_min, grade_max = 9, 12
            audiences = ["high_school", "college", "adult"]

        return {
            "difficulty": category,
            "difficulty_score": pdi,
            "cognitive_level": cognitive_level,
            "grade_min": grade_min,
            "grade_max": grade_max,
            "audience_suitability": audiences,
            "breakdown": {
                "cognitive_depth": round(c_score, 2),
                "entity_obscurity": round(e_score, 2),
                "specificity": round(s_score, 2),
                "readability": round(r_score, 2),
                "scaffolding_help": round(h_score, 2)
            }
        }

    def _compute_cognitive_depth(self, question: str) -> Tuple[str, float]:
        q_lower = question.lower()

        # Check Level 3: Lateral Synthesis & Multi-domain connection
        for pat in self.LATERAL_SYNTHESIS_PATTERNS:
            if re.search(pat, q_lower):
                return "Analyze / Lateral", 0.85

        # Check Level 2: Inference & Relational understanding
        for pat in self.INFERENCE_PATTERNS:
            if re.search(pat, q_lower):
                return "Understand / Apply", 0.55

        # Default Level 1: Recall & Identification
        return "Recall / Remember", 0.25

    def _compute_entity_obscurity(self, answer: str, question: str) -> float:
        ans_lower = answer.lower().strip()
        tokens = re.sub(r"[^\w\s]", "", ans_lower).split()
        if not tokens:
            return 0.5

        # If answer words are in elementary anchors, it's widely recognizable
        if any(tok in self.COMMON_ELEMENTARY_ANCHORS for tok in tokens):
            return 0.20

        # Multi-word obscure entity / latin / technical term
        syllable_count = sum(len(re.findall(r"[aeiouy]+", tok)) for tok in tokens)
        avg_syllables = syllable_count / max(len(tokens), 1)

        base = 0.45
        if avg_syllables >= 3.0:
            base += 0.25
        elif avg_syllables <= 1.5:
            base -= 0.15

        if re.search(r"\b(treaty|dynasty|syndrome|effect|phenomenon|nebula|trench)\b", ans_lower):
            base += 0.20

        return max(0.10, min(0.95, base))

    def _compute_specificity(self, question: str) -> float:
        constraints = 0
        if re.search(r"\b(1\d{3}|20\d{2})\b", question):  # Specific year
            constraints += 1
        if len(re.findall(r"\b[A-Z][a-z]+", question)) >= 3:  # Multiple named entities
            constraints += 1
        if re.search(r"['\"][^'\"]+['\"]", question):  # Quoted name or phrase
            constraints += 1
        if re.search(r"\b(\d+(\.\d+)?\s*(km|miles|meters|percent|%|feet|years))\b", question, re.IGNORECASE):
            constraints += 1

        return min(1.0, 0.3 + (constraints * 0.18))

    def _compute_readability(self, question: str) -> float:
        words = question.split()
        word_count = len(words)
        if word_count == 0:
            return 0.3

        long_words = sum(1 for w in words if len(w) > 7)
        long_ratio = long_words / word_count

        score = (min(word_count, 40) / 40.0) * 0.5 + (long_ratio * 0.5)
        return max(0.1, min(1.0, score))

    def _compute_scaffolding(self, question: str, notes: str) -> float:
        scaffolding = 0.0
        q_lower = question.lower()
        if re.search(r"\b(clue|hint|note|tip)\b", q_lower):
            scaffolding += 0.4
        if notes and len(notes.strip()) > 10:
            scaffolding += 0.3
        if re.search(r"\(also known as|famously called|popularly known\)", q_lower):
            scaffolding += 0.3

        return min(1.0, scaffolding)
