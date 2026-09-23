import json
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Set, Optional

ANCHORS_FILE = Path(__file__).resolve().parent / "common_anchors.json"

class DifficultyEngine:
    """
    Calculates the Pedagogical Difficulty Index (PDI) for quiz questions
    based on Bloom's cognitive depth, entity obscurity, readability, and clue scaffolding.
    Features 200+ common elementary knowledge anchors, multi-step deduction indicators,
    and overlapping pedagogical grade bands.
    """

    DEFAULT_ANCHORS = {
        "sun", "moon", "earth", "star", "water", "tree", "plant", "dog", "cat", "lion",
        "tiger", "apple", "gold", "silver", "football", "cricket", "everest", "pacific",
        "paris", "london", "rome", "tokyo", "cairo", "delhi", "canberra", "sydney",
        "france", "england", "india", "australia", "america", "japan", "china", "egypt",
        "pyramid", "colosseum", "taj mahal", "eiffel tower", "red", "blue", "green"
    }

    LATERAL_SYNTHESIS_PATTERNS = [
        r"\b(connect|connection|in common|link|linked|shared|irony|paradox|coincidence)\b",
        r"\b(pivoted|reinvented|later became|originally named|formerly known|what connects)\b",
        r"\b(why did|how did|what prompted|inspired by|what was the connection)\b",
        r"\b(identify the connection|common thread|common link)\b"
    ]

    INFERENCE_PATTERNS = [
        r"\b(how|why|reason|because|lead to|result of|significance|purpose)\b",
        r"\b(derived|consequence|discovery|breakthrough|symbolizes|represents)\b",
        r"\b(which of the following caused|what made|what explains)\b"
    ]

    def __init__(self, anchors_path: Optional[Path] = None):
        self.anchors_path = anchors_path or ANCHORS_FILE
        self.common_anchors = self._load_anchors()

    def _load_anchors(self) -> Set[str]:
        if self.anchors_path.exists():
            try:
                with open(self.anchors_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data.get("anchors", self.DEFAULT_ANCHORS))
            except Exception:
                pass
        return self.DEFAULT_ANCHORS

    def evaluate(self, question_text: str, answer_text: str, explanation: str = "", notes: str = "") -> Dict[str, Any]:
        """
        Computes the continuous difficulty score (0.00 - 1.00), Bloom's level,
        calibrated grade range with overlap, and target audience suitabilities.
        """
        q_clean = question_text.strip()
        ans_clean = answer_text.strip()
        exp_clean = explanation.strip()

        # 1. Cognitive Depth (Bloom's Taxonomy / Multi-step deduction)
        cognitive_level, c_score = self._compute_cognitive_depth(q_clean, exp_clean)

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

        # Categorical mapping with overlapping grade ranges
        if pdi < 0.35:
            category = "Easy"
            grade_min, grade_max = 1, 5
            audiences = ["primary"]
        elif pdi <= 0.65:
            category = "Medium"
            grade_min, grade_max = 4, 9
            audiences = ["primary", "middle_school", "high_school"]
        else:
            category = "Hard"
            grade_min, grade_max = 8, 12
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

    def _compute_cognitive_depth(self, question: str, explanation: str) -> Tuple[str, float]:
        q_lower = question.lower()
        exp_lower = explanation.lower()

        # Check Level 3: Lateral Synthesis & Multi-domain connection
        for pat in self.LATERAL_SYNTHESIS_PATTERNS:
            if re.search(pat, q_lower):
                return "Analyze / Lateral", 0.85

        # Check for multi-step clues in question
        has_multi_step = bool(
            re.search(r"\b(which also|who later|although|despite|after being|before becoming)\b", q_lower)
            and len(re.findall(r"\b[A-Z][a-z]+", question)) >= 2
        )
        if has_multi_step:
            return "Analyze / Lateral", 0.80

        # Check Level 2: Inference & Relational understanding
        for pat in self.INFERENCE_PATTERNS:
            if re.search(pat, q_lower):
                return "Understand / Apply", 0.58

        # If explanation contains causal reasoning
        if re.search(r"\b(because|as a result|which caused|led to|discovered by accident|due to)\b", exp_lower):
            return "Understand / Apply", 0.50

        # Default Level 1: Recall & Identification
        return "Recall / Remember", 0.25

    def _compute_entity_obscurity(self, answer: str, question: str) -> float:
        ans_lower = answer.lower().strip()
        tokens = re.sub(r"[^\w\s]", "", ans_lower).split()
        if not tokens:
            return 0.40

        # If any token in the answer is in the 200+ common anchors set, it's familiar
        anchor_hits = sum(1 for tok in tokens if tok in self.common_anchors)
        if anchor_hits > 0:
            ratio = anchor_hits / len(tokens)
            return round(max(0.12, 0.35 - (ratio * 0.20)), 2)

        # Multi-word obscure entity / technical term
        syllable_count = sum(len(re.findall(r"[aeiouy]+", tok)) for tok in tokens)
        avg_syllables = syllable_count / max(len(tokens), 1)

        base = 0.45
        if avg_syllables >= 3.0:
            base += 0.22
        elif avg_syllables <= 1.5:
            base -= 0.12

        if re.search(r"\b(treaty|dynasty|syndrome|effect|phenomenon|nebula|trench|protocol|pact)\b", ans_lower):
            base += 0.18

        return max(0.10, min(0.95, round(base, 2)))

    def _compute_specificity(self, question: str) -> float:
        constraints = 0
        if re.search(r"\b(1\d{3}|20\d{2})\b", question):  # Specific year
            constraints += 1
        if len(re.findall(r"\b[A-Z][a-z]+", question)) >= 3:  # Multiple named entities
            constraints += 1
        if re.search(r"['\"][^'\"]+['\"]", question):  # Quoted name or phrase
            constraints += 1
        if re.search(r"\b(\d+(\.\d+)?\s*(km|miles|meters|percent|%|feet|years|light-years))\b", question, re.IGNORECASE):
            constraints += 1

        return min(1.0, round(0.28 + (constraints * 0.18), 2))

    def _compute_readability(self, question: str) -> float:
        words = question.split()
        word_count = len(words)
        if word_count == 0:
            return 0.30

        long_words = sum(1 for w in words if len(w) > 7)
        long_ratio = long_words / word_count

        score = (min(word_count, 40) / 40.0) * 0.5 + (long_ratio * 0.5)
        return max(0.10, min(1.0, round(score, 2)))

    def _compute_scaffolding(self, question: str, notes: str) -> float:
        scaffolding = 0.0
        q_lower = question.lower()
        if re.search(r"\b(clue|hint|note|tip)\b", q_lower):
            scaffolding += 0.4
        if notes and len(notes.strip()) > 10:
            scaffolding += 0.3
        if re.search(r"\(also known as|famously called|popularly known|nickname\)", q_lower):
            scaffolding += 0.3

        return min(1.0, round(scaffolding, 2))
