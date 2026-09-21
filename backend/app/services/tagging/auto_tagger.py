import re
from typing import Dict, Any, List, Set

class AutoTagger:
    """
    Intelligent multi-topic classifier, entity tagger, and pedagogical hook analyzer
    for the QShala Quiz Intelligence Platform.
    """

    TAXONOMY_KEYWORDS = {
        "World History": [
            "history", "historical", "war", "battle", "century", "bc", "ad", "ancient",
            "dynasty", "treaty", "empire", "revolution", "colonial", "monarch", "king",
            "queen", "emperor", "pharaoh", "civilization", "renaissance", "titanic", "first fleet"
        ],
        "Science & Nature": [
            "science", "scientific", "planet", "solar", "volcano", "mountain", "species",
            "biology", "physics", "chemistry", "organism", "animal", "dinosaur", "molecule",
            "ocean", "marine", "reef", "earthquake", "trench", "mammal", "bat", "flight",
            "antibiotic", "bacteria", "fungus", "mold", "mars", "astronomy", "geology",
            "plate", "tectonic", "atmosphere"
        ],
        "Politics & Governance": [
            "treaty", "parliament", "union", "president", "prime minister", "sovereign",
            "border", "frontier", "democracy", "constitution", "government", "state", "nations",
            "international", "maastricht", "european union", "diplomat", "monarchy", "republic"
        ],
        "World Geography": [
            "geography", "country", "border", "continent", "desert", "mountain", "ocean",
            "river", "capital", "island", "lake", "trench", "athens", "chile", "canada",
            "china", "jordan", "greece", "atacama", "pacific", "mariana", "land area", "territory"
        ],
        "Literature & Arts": [
            "literature", "playwright", "poet", "author", "play", "sonnet", "novel", "theatre",
            "painting", "sculptor", "shakespeare", "monument", "pyramid", "petra", "art",
            "artist", "culture", "festival", "holi", "music", "instrument", "piano", "pianoforte"
        ],
        "Inventions & Technology": [
            "invention", "invented", "inventor", "discovery", "discoverer", "flight", "airplane",
            "wright brothers", "internet", "world wide web", "web", "computer", "cern", "code",
            "antibiotic", "penicillin", "instrument", "acoustic", "mechanic", "technology"
        ],
        "Sports & Games": [
            "olympic", "olympics", "games", "stadium", "tournament", "athlete", "championship",
            "cricket", "football", "tennis", "world cup", "medal", "panathenaic"
        ],
        "Culture & Traditions": [
            "festival", "culture", "cultural", "tradition", "traditional", "celebration",
            "holi", "spring", "folklore", "heritage", "community", "ceremony", "custom"
        ]
    }

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
        """
        combined = f"{doc_title} {question_text} {answer_text} {explanation}".lower()

        # 1. Multi-Topic Tagging
        topic_scores: Dict[str, int] = {}
        for topic, keywords in self.TAXONOMY_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", combined):
                    score += 1
            if score > 0:
                topic_scores[topic] = score

        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)

        if sorted_topics:
            primary_topic = sorted_topics[0][0]
            # Include all topics with significant signal (at least 1 keyword match)
            multi_topics = [t[0] for t in sorted_topics]
        else:
            primary_topic = "General Knowledge"
            multi_topics = ["General Knowledge"]

        # 2. Entity & Key Concepts Extraction
        entities = self._extract_entities(f"{question_text} {answer_text}")

        # 3. Pedagogical Hook & Style
        hook = self._classify_hook(question_text, explanation)

        # 4. Curiosity Quotient (1 - 10)
        curiosity_score = self._compute_curiosity_score(question_text, explanation, hook)

        # 5. Temporal Nature (Evergreen vs Time-Sensitive)
        temporal_nature = self._classify_temporal_nature(question_text, answer_text)

        return {
            "primary_topic": primary_topic,
            "topics": multi_topics,
            "tags": entities,
            "question_hook": hook,
            "curiosity_score": curiosity_score,
            "temporal_nature": temporal_nature
        }

    def _extract_entities(self, text: str) -> List[str]:
        """Extracts significant proper nouns, capitalized entities, and key noun phrases."""
        found_entities = set()

        # Capitalized multi-word phrases (e.g. "Mariana Trench", "Wright Brothers", "Great Barrier Reef")
        multi_cap = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
        for mc in multi_cap:
            if len(mc) > 4 and mc.lower() not in {"what is", "which of", "question number"}:
                found_entities.add(mc)

        # Quoted entities
        quotes = re.findall(r"['\"]([^'\"]{3,30})['\"]", text)
        for q in quotes:
            found_entities.add(q.strip())

        # Specific single named proper nouns
        singles = re.findall(r"\b([A-Z][a-z]{3,})\b", text)
        for s in singles:
            if s.lower() not in {"this", "which", "what", "where", "when", "name", "identify", "answer", "question"}:
                if not any(s in m for m in multi_cap):
                    found_entities.add(s)

        # Sort by relevance / length and limit to top 6 entities
        cleaned = [e for e in found_entities if len(e.split()) <= 4]
        cleaned.sort(key=lambda x: (len(x.split()), len(x)), reverse=True)
        return cleaned[:6]

    def _classify_hook(self, question: str, explanation: str) -> str:
        q_lower = question.lower()
        exp_lower = explanation.lower()

        # Narrative Story
        if re.search(r"\b(in \d{4}|on [a-z]+ \d{1,2}|returned from|discovered when|after years of)\b", q_lower):
            return "STORY_NARRATIVE"

        # Extraordinary Extremes / Did You Know
        if re.search(r"\b(tallest|deepest|driest|largest living|highest number|only mammal|intact today)\b", q_lower):
            return "DID_YOU_KNOW"

        # Lateral Connection
        if re.search(r"\b(connect|connection|in common|shared|originally named|pivoted)\b", q_lower):
            return "LATERAL_CONNECT"

        # Visual Clue
        if re.search(r"\b(pictured|image|photo|flag|logo|diagram|silhouette|map)\b", q_lower):
            return "VISUAL_CLUE"

        return "DIRECT_TRIVIA"

    def _compute_curiosity_score(self, question: str, explanation: str, hook: str) -> int:
        score = 6 # baseline

        # Hooks add curiosity value
        if hook == "DID_YOU_KNOW":
            score += 2
        elif hook in ["STORY_NARRATIVE", "LATERAL_CONNECT"]:
            score += 2

        # Rich explanations with surprising details
        if len(explanation.split()) > 25:
            score += 1

        # Superlatives and intriguing facts
        if re.search(r"\b(fascinating|accidental|surprising|unusual|first ever|secret|coincidence)\b", f"{question} {explanation}".lower()):
            score += 1

        return min(10, max(4, score))

    def _classify_temporal_nature(self, question: str, answer: str) -> str:
        combined = f"{question} {answer}".lower()
        if re.search(r"\b(current|present|latest|currently|as of \d{4}|recent|now)\b", combined):
            return "TIME_SENSITIVE"
        return "EVERGREEN"
