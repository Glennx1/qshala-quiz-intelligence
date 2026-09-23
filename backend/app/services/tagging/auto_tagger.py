import os
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

TAXONOMY_FILE = Path(__file__).resolve().parent / "taxonomy.json"

class AutoTagger:
    """
    Intelligent multi-topic classifier, entity tagger, and pedagogical hook analyzer
    for the QShala Quiz Intelligence Platform.
    Loads taxonomy dynamically from taxonomy.json, applies weighted position scoring,
    and extracts multi-word named entities.
    """

    DEFAULT_TAXONOMY = {
        "Australian History & Culture": ["australia", "aboriginal", "first fleet", "cook", "barton", "canberra", "sydney", "ned kelly", "dreamtime", "koala", "kangaroo"],
        "World History": ["history", "ancient", "medieval", "century", "dynasty", "empire", "emperor", "pharaoh", "civilization", "revolution", "battle", "war"],
        "Science & Nature": ["science", "biology", "physics", "chemistry", "species", "animal", "plant", "molecule", "energy", "gravity", "cell", "dinosaur"],
        "World Geography": ["geography", "country", "capital", "continent", "mountain", "ocean", "river", "desert", "island", "lake", "border", "glacier"],
        "Politics & Governance": ["politics", "government", "parliament", "president", "prime minister", "democracy", "treaty", "constitution", "election", "united nations"],
        "Literature & Language": ["literature", "author", "poet", "poem", "novel", "playwright", "shakespeare", "mythology", "character", "book"],
        "Arts & Music": ["art", "artist", "painting", "painter", "sculpture", "music", "composer", "symphony", "instrument", "piano", "orchestra"],
        "Inventions & Technology": ["invention", "inventor", "technology", "computer", "internet", "patent", "discovery", "satellite", "airplane", "machine"],
        "Sports & Games": ["sport", "sports", "olympics", "game", "tournament", "cricket", "football", "tennis", "world cup", "medal", "athlete", "chess"],
        "Food & Cuisine": ["food", "cuisine", "dish", "recipe", "cooking", "spice", "culinary", "ingredient", "bread", "harvest"],
        "Movies & Entertainment": ["movie", "film", "cinema", "director", "actor", "hollywood", "oscar", "theatre", "animation"],
        "Mathematics & Logic": ["mathematics", "math", "equation", "theorem", "geometry", "algebra", "number", "formula", "logic", "puzzle"],
        "Culture & Traditions": ["culture", "traditional", "tradition", "festival", "heritage", "folklore", "ceremony", "celebration"],
        "Space & Astronomy": ["space", "astronomy", "planet", "galaxy", "solar system", "orbit", "star", "telescope", "nasa", "moon", "asteroid"],
        "Current Affairs & People": ["leader", "contemporary", "international", "nobel prize", "pioneer", "global", "summit"]
    }

    def __init__(self, taxonomy_path: Optional[Path] = None):
        self.taxonomy_path = taxonomy_path or TAXONOMY_FILE
        self.taxonomy = self._load_taxonomy()

    def _load_taxonomy(self) -> Dict[str, List[str]]:
        if self.taxonomy_path.exists():
            try:
                with open(self.taxonomy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("categories", self.DEFAULT_TAXONOMY)
            except Exception:
                pass
        return self.DEFAULT_TAXONOMY

    def tag_question(
        self,
        question_text: str,
        answer_text: str,
        explanation: str = "",
        doc_title: str = ""
    ) -> Dict[str, Any]:
        """
        Extracts primary topic, multi-topic array, named entity tags,
        question hook style, curiosity quotient, and temporal nature.
        Uses position-weighted scoring: Question (2.5x) > Answer (2.0x) > Title (1.5x) > Explanation (1.0x).
        """
        q_clean = question_text.lower()
        a_clean = answer_text.lower()
        exp_clean = explanation.lower()
        title_clean = doc_title.lower()

        # 1. Multi-Topic Weighted Scoring
        topic_scores: Dict[str, float] = {}

        for topic, keywords in self.taxonomy.items():
            score = 0.0
            for kw in keywords:
                pattern = rf"\b{re.escape(kw)}\b"
                if re.search(pattern, q_clean):
                    score += 2.5
                if re.search(pattern, a_clean):
                    score += 2.0
                if re.search(pattern, title_clean):
                    score += 1.5
                if re.search(pattern, exp_clean):
                    score += 1.0

            if score > 0:
                topic_scores[topic] = score

        # Rank topics descending
        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)

        if sorted_topics:
            primary_topic = sorted_topics[0][0]
            # Include all topics with at least 2.0 points or >= 30% of top score
            top_score = sorted_topics[0][1]
            multi_topics = [t[0] for t in sorted_topics if t[1] >= 2.0 or t[1] >= (top_score * 0.35)]
        else:
            primary_topic = "General Knowledge"
            multi_topics = ["General Knowledge"]

        # Subtopic heuristic: if secondary topic exists with high score, or extract from doc_title
        subtopic = None
        if len(sorted_topics) > 1 and sorted_topics[1][1] >= 2.5:
            subtopic = sorted_topics[1][0]

        # 2. Entity & Key Concepts Extraction
        entities = self._extract_entities(f"{question_text} {answer_text} {explanation[:150]}")

        # 3. Pedagogical Hook & Style
        hook = self._classify_hook(question_text, explanation)

        # 4. Curiosity Quotient (4 - 10)
        curiosity_score = self._compute_curiosity_score(question_text, explanation, hook)

        # 5. Temporal Nature (Evergreen vs Time-Sensitive)
        temporal_nature = self._classify_temporal_nature(question_text, answer_text)

        return {
            "primary_topic": primary_topic,
            "topics": multi_topics,
            "subtopic": subtopic,
            "tags": entities,
            "question_hook": hook,
            "curiosity_score": curiosity_score,
            "temporal_nature": temporal_nature
        }

    def _extract_entities(self, text: str) -> List[str]:
        """Extracts significant proper nouns, capitalized entities, and key multi-word phrases."""
        found_entities = set()

        # Multi-word capitalized entities (e.g. "Great Barrier Reef", "Sir Edmund Barton", "World War II")
        multi_cap = re.findall(r"\b([A-Z][a-zA-Z]+(?:\s+(?:of|the|and|de|von|la)?\s*[A-Z][a-zA-Z]+)+)\b", text)
        for mc in multi_cap:
            mc_clean = mc.strip()
            if len(mc_clean) > 4 and mc_clean.lower() not in {"what is", "which of", "name the", "question number", "identify the"}:
                found_entities.add(mc_clean)

        # Quoted entities
        quotes = re.findall(r"['\"]([^'\"]{3,40})['\"]", text)
        for q in quotes:
            q_clean = q.strip()
            if not any(stop in q_clean.lower() for stop in ["click here", "read more"]):
                found_entities.add(q_clean)

        # Single capitalized proper nouns (>= 4 letters)
        singles = re.findall(r"\b([A-Z][a-z]{3,})\b", text)
        stop_singles = {
            "this", "which", "what", "where", "when", "name", "identify", "answer", "question",
            "these", "those", "their", "there", "about", "after", "before", "during", "while",
            "select", "choose", "correct", "false", "following"
        }
        for s in singles:
            if s.lower() not in stop_singles:
                if not any(s in m for m in multi_cap):
                    found_entities.add(s)

        # Sort by specificity (multi-word first, then length) and take top 6
        cleaned = [e for e in found_entities if len(e.split()) <= 5]
        cleaned.sort(key=lambda x: (len(x.split()), len(x)), reverse=True)
        return cleaned[:6]

    def _classify_hook(self, question: str, explanation: str) -> str:
        q_lower = question.lower()
        exp_lower = explanation.lower()

        # Narrative Story
        if re.search(r"\b(in \d{4}|on [a-z]+ \d{1,2}|returned from|discovered when|after years of|legend has it)\b", q_lower):
            return "STORY_NARRATIVE"

        # Extraordinary Extremes / Did You Know
        if re.search(r"\b(tallest|deepest|driest|largest living|highest number|only mammal|fastest|slowest|heaviest|smallest)\b", q_lower):
            return "DID_YOU_KNOW"

        # Lateral Connection
        if re.search(r"\b(connect|connection|in common|shared|originally named|pivoted|what links)\b", q_lower):
            return "LATERAL_CONNECT"

        # Visual Clue
        if re.search(r"\b(pictured|image|photo|flag|logo|diagram|silhouette|map|monument)\b", q_lower):
            return "VISUAL_CLUE"

        return "DIRECT_TRIVIA"

    def _compute_curiosity_score(self, question: str, explanation: str, hook: str) -> int:
        score = 6

        if hook == "DID_YOU_KNOW":
            score += 2
        elif hook in ["STORY_NARRATIVE", "LATERAL_CONNECT"]:
            score += 2
        elif hook == "VISUAL_CLUE":
            score += 1

        if len(explanation.split()) > 25:
            score += 1

        if re.search(r"\b(fascinating|accidental|surprising|unusual|first ever|secret|coincidence|ironically|bizarre)\b", f"{question} {explanation}".lower()):
            score += 1

        return min(10, max(4, score))

    def _classify_temporal_nature(self, question: str, answer: str) -> str:
        combined = f"{question} {answer}".lower()
        if re.search(r"\b(current|present|latest|currently|as of \d{4}|recent|now|today)\b", combined):
            return "TIME_SENSITIVE"
        return "EVERGREEN"
