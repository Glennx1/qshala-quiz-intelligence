from typing import List, Dict, Any

class ContextBuilder:
    """
    Builds the retrieval-augmented context and QShala few-shot style exemplars
    for the LLM Question Generator.
    """

    @staticmethod
    def build_prompt_context(retrieved_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        evidence_blocks = []
        style_examples = []
        source_mapping = {}

        for idx, item in enumerate(retrieved_items, start=1):
            q = item["question"]
            doc = item["document"]
            slide = item["slide"]
            source_id = f"SRC-{idx}"

            source_mapping[source_id] = {
                "historical_question_id": q.id,
                "document_id": doc.id,
                "slide_id": slide.id if slide else None,
                "document_title": doc.title,
                "slide_number": slide.slide_number if slide else None,
                "relevance_score": item["relevance_score"]
            }

            evidence_text = (
                f"[{source_id}] Document: {doc.title} (Slide {slide.slide_number if slide else 'N/A'})\n"
                f"Topic: {q.topic} | Difficulty: {q.difficulty} | Grade: {q.grade_min}-{q.grade_max}\n"
                f"Question: {q.question_text}\n"
                f"Answer: {q.answer}\n"
                f"Options: {', '.join(q.options) if q.options else 'N/A'}\n"
                f"Slide Excerpt: {item.get('quote', '')[:300]}\n"
            )
            evidence_blocks.append(evidence_text)

            # Pick first 3 as style exemplars
            if idx <= 3:
                style_examples.append({
                    "question": q.question_text,
                    "answer": q.answer,
                    "options": q.options,
                    "explanation": q.explanation
                })

        return {
            "evidence_context": "\n".join(evidence_blocks),
            "style_examples": style_examples,
            "source_mapping": source_mapping
        }
