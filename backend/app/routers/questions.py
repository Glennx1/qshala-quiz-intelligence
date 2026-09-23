from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, desc, asc, String
from backend.app.database import get_db
from backend.app.models.question import Question
from backend.app.models.document import Document, Slide
from backend.app.schemas.question import QuestionResponse, QuestionUpdate, DuplicateResolveRequest
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever

router = APIRouter(prefix="/questions", tags=["Knowledge Base Questions"])

def to_question_response(q: Question, doc: Optional[Document], slide: Optional[Slide]) -> QuestionResponse:
    dup_text = None
    dup_ans = None
    if getattr(q, "duplicate_of", None):
        dup_text = q.duplicate_of.question_text
        dup_ans = q.duplicate_of.answer

    return QuestionResponse(
        id=q.id,
        content_hash=getattr(q, "content_hash", None),
        document_id=q.document_id,
        slide_id=q.slide_id,
        answer_slide_id=q.answer_slide_id,
        question_text=q.question_text,
        answer=q.answer,
        options=q.options,
        explanation=q.explanation,
        topic=q.topic,
        subtopic=q.subtopic,
        topics=getattr(q, "topics", []) or [q.topic],
        tags=getattr(q, "tags", []) or [],
        difficulty=q.difficulty or "Medium",
        difficulty_score=getattr(q, "difficulty_score", 0.50) or 0.50,
        cognitive_level=getattr(q, "cognitive_level", "Recall / Remember") or "Recall / Remember",
        grade_min=q.grade_min or 3,
        grade_max=q.grade_max or 12,
        audience_suitability=getattr(q, "audience_suitability", []) or [],
        question_hook=getattr(q, "question_hook", "DIRECT_TRIVIA") or "DIRECT_TRIVIA",
        curiosity_score=getattr(q, "curiosity_score", 7) or 7,
        temporal_nature=getattr(q, "temporal_nature", "EVERGREEN") or "EVERGREEN",
        occurrence_count=getattr(q, "occurrence_count", 1) or 1,
        provenance_decks=getattr(q, "provenance_decks", []) or [],
        round_number=getattr(q, "round_number", None),
        question_type=q.question_type or "SLIDE_QA",
        source_year=q.source_year,
        image_refs=getattr(q, "image_refs", []) or [],
        visual_clues=getattr(q, "visual_clues", None),
        audio_transcript=getattr(q, "audio_transcript", None),
        video_transcript=getattr(q, "video_transcript", None),
        raw_media_refs=getattr(q, "raw_media_refs", []) or [],
        source_slide_range=getattr(q, "source_slide_range", None),
        duplicate_status=getattr(q, "duplicate_status", "UNIQUE") or "UNIQUE",
        duplicate_similarity=getattr(q, "duplicate_similarity", None),
        duplicate_of_id=getattr(q, "duplicate_of_id", None),
        duplicate_of_text=dup_text,
        duplicate_of_answer=dup_ans,
        created_at=q.created_at,
        document_title=doc.title if doc else None,
        slide_number=slide.slide_number if slide else None
    )

@router.get("/topics", response_model=List[Dict[str, Any]])
def list_vault_topics(db: Session = Depends(get_db)):
    """
    Returns all distinct topics currently stored in the Question Vault along with their counts.
    Used for predictive topic autocomplete and topic browsing.
    """
    results = (
        db.query(Question.topic, func.count(Question.id).label("count"))
        .filter(Question.topic.isnot(None))
        .group_by(Question.topic)
        .order_by(desc("count"))
        .all()
    )
    return [{"topic": r[0], "count": r[1]} for r in results]

@router.get("/topics/{topic}/summary", response_model=Dict[str, Any])
def get_topic_summary(topic: str, db: Session = Depends(get_db)):
    """
    Returns deep pedagogical metadata for a given topic in the vault:
    total questions, difficulty breakdown, subtopics, grade coverage, and previews.
    """
    questions = (
        db.query(Question)
        .filter(or_(Question.topic.ilike(f"%{topic}%"), Question.subtopic.ilike(f"%{topic}%")))
        .all()
    )

    if not questions:
        return {
            "topic": topic,
            "total_questions": 0,
            "difficulty_breakdown": {"Easy": 0, "Medium": 0, "Hard": 0},
            "subtopics": [],
            "grade_min": None,
            "grade_max": None,
            "sample_questions": []
        }

    diff_counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    subtopics = set()
    grade_mins = []
    grade_maxs = []

    for q in questions:
        d = q.difficulty or "Medium"
        diff_counts[d] = diff_counts.get(d, 0) + 1
        if q.subtopic:
            subtopics.add(q.subtopic)
        if q.grade_min:
            grade_mins.append(q.grade_min)
        if q.grade_max:
            grade_maxs.append(q.grade_max)

    samples = [
        {"question_text": q.question_text, "difficulty": q.difficulty, "answer": q.answer}
        for q in questions[:3]
    ]

    return {
        "topic": topic,
        "total_questions": len(questions),
        "difficulty_breakdown": diff_counts,
        "subtopics": sorted(list(subtopics)),
        "grade_min": min(grade_mins) if grade_mins else 3,
        "grade_max": max(grade_maxs) if grade_maxs else 12,
        "sample_questions": samples
    }

@router.get("/tags", response_model=List[Dict[str, Any]])
def list_vault_tags(
    topic: Optional[str] = Query(None, description="Optional topic filter"),
    db: Session = Depends(get_db)
):
    """
    Returns an inverted tag index of all unique entity tags in the Question Vault,
    their frequency counts, linked macro-topics, and co-occurring tags.
    """
    topic_str = topic if isinstance(topic, str) and topic.strip() else None
    q_query = db.query(Question)
    if topic_str:
        q_query = q_query.filter(Question.topic.ilike(f"%{topic_str}%"))
    questions = q_query.all()

    tag_counts: Dict[str, int] = {}
    tag_topics: Dict[str, Set[str]] = {}
    tag_co_occur: Dict[str, Dict[str, int]] = {}

    for q in questions:
        q_tags = [t.strip().lstrip("#").strip() for t in (q.tags or []) if isinstance(t, str) and t.strip()]
        for t in q_tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
            if q.topic:
                tag_topics.setdefault(t, set()).add(q.topic)
            if t not in tag_co_occur:
                tag_co_occur[t] = {}
            for other_t in q_tags:
                if other_t.lower() != t.lower():
                    tag_co_occur[t][other_t] = tag_co_occur[t].get(other_t, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    results = []
    for t_name, count in sorted_tags:
        co_sorted = sorted(tag_co_occur.get(t_name, {}).items(), key=lambda x: x[1], reverse=True)
        top_co = [c[0] for c in co_sorted[:3]]
        results.append({
            "tag": t_name,
            "count": count,
            "topics": sorted(list(tag_topics.get(t_name, set()))),
            "co_occurring_tags": top_co
        })
    return results

@router.get("/tag-preview", response_model=Dict[str, Any])
def preview_tag_quiz_availability(
    topic: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    grade_min: Optional[int] = Query(None),
    grade_max: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Returns live compilation preview based on selected topic and/or concept tags.
    Identifies exact topic+tag matches and cross-topic tag synthesis matches.
    """
    topic_str = topic if isinstance(topic, str) and topic.strip() else None
    tags_str = tags if isinstance(tags, str) and tags.strip() else None
    grade_min_val = grade_min if isinstance(grade_min, int) else None
    grade_max_val = grade_max if isinstance(grade_max, int) else None

    tag_list = [t.strip().lstrip("#").strip().lower() for t in (tags_str.split(",") if tags_str else []) if t.strip()]

    all_questions = db.query(Question).all()

    exact_matches = []
    cross_topic_tag_matches = []
    topic_only_matches = []

    for q in all_questions:
        if grade_min_val and q.grade_max and q.grade_max < grade_min_val:
            continue
        if grade_max_val and q.grade_min and q.grade_min > grade_max_val:
            continue

        q_tags_lower = [t.strip().lstrip("#").strip().lower() for t in (q.tags or []) if isinstance(t, str)]
        matches_topic = bool(topic_str and topic_str.lower() in (q.topic or "").lower())
        matches_tags = bool(
            tag_list and any(
                any(t == qt or t in qt or qt in t for t in tag_list)
                for qt in q_tags_lower
            )
        )

        if matches_topic and matches_tags:
            exact_matches.append(q)
        elif matches_tags:
            cross_topic_tag_matches.append(q)
        elif matches_topic:
            topic_only_matches.append(q)

    combined_pool = exact_matches + cross_topic_tag_matches
    if not tag_list:
        combined_pool = topic_only_matches

    diff_counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    for q in combined_pool:
        d = q.difficulty or "Medium"
        diff_counts[d] = diff_counts.get(d, 0) + 1

    sample_previews = [
        {
            "id": q.id,
            "question_text": q.question_text,
            "answer": q.answer,
            "difficulty": q.difficulty,
            "topic": q.topic,
            "tags": q.tags or []
        }
        for q in combined_pool[:3]
    ]

    total = len(combined_pool)
    suggested_mode = "HISTORICAL" if total >= 5 else "NEW"

    return {
        "topic": topic,
        "tags": tag_list,
        "total_available": total,
        "exact_matches_count": len(exact_matches),
        "cross_topic_tag_matches_count": len(cross_topic_tag_matches),
        "difficulty_breakdown": diff_counts,
        "suggested_mode": suggested_mode,
        "sample_questions": sample_previews
    }


@router.get("", response_model=List[QuestionResponse])
async def search_questions(
    query: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    subtopic: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    grade_min: Optional[int] = Query(None),
    grade_max: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    duplicate_status: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("created_at"),
    sort_order: Optional[str] = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    # Normalize inputs in case of direct Python function calls
    query_str = query if isinstance(query, str) and query.strip() else None
    topic_str = topic if isinstance(topic, str) and topic.strip() else None
    subtopic_str = subtopic if isinstance(subtopic, str) and subtopic.strip() else None
    tag_str = tag if isinstance(tag, str) and tag.strip() else None
    diff_str = difficulty if isinstance(difficulty, str) and difficulty.strip() else None
    dup_status_str = duplicate_status if isinstance(duplicate_status, str) and duplicate_status.strip() else None
    grade_min_val = grade_min if isinstance(grade_min, int) else None
    grade_max_val = grade_max if isinstance(grade_max, int) else None
    sort_by_str = sort_by if isinstance(sort_by, str) else "created_at"
    sort_order_str = sort_order if isinstance(sort_order, str) else "desc"
    limit_int = limit if isinstance(limit, int) else 50
    offset_int = offset if isinstance(offset, int) else 0

    if query_str:
        # Perform semantic/hybrid search
        retriever = HybridRetriever(db)
        results = await retriever.search(
            query=query_str,
            topic=topic_str,
            grade_min=grade_min_val,
            grade_max=grade_max_val,
            difficulty=diff_str,
            limit=limit_int
        )
        output = []
        for r in results:
            output.append(to_question_response(r["question"], r["document"], r["slide"]))
        return output

    # Direct query with rich metadata filters
    q_builder = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id)

    if dup_status_str:
        q_builder = q_builder.filter(Question.duplicate_status == dup_status_str)
    if topic_str:
        q_builder = q_builder.filter(
            or_(
                Question.topic.ilike(f"%{topic_str}%"),
                Question.subtopic.ilike(f"%{topic_str}%")
            )
        )
    if subtopic_str:
        q_builder = q_builder.filter(Question.subtopic.ilike(f"%{subtopic_str}%"))
    if tag_str:
        clean_tag = tag_str.strip().lstrip("#").strip()
        q_builder = q_builder.filter(func.cast(Question.tags, String).ilike(f"%{clean_tag}%"))
    if diff_str:
        q_builder = q_builder.filter(Question.difficulty.ilike(diff_str))
    if grade_min_val is not None:
        q_builder = q_builder.filter(Question.grade_min >= grade_min_val)
    if grade_max_val is not None:
        q_builder = q_builder.filter(Question.grade_max <= grade_max_val)

    # Sorting
    sort_col = getattr(Question, sort_by_str, Question.created_at)
    if sort_order_str == "asc":
        q_builder = q_builder.order_by(asc(sort_col))
    else:
        q_builder = q_builder.order_by(desc(sort_col))

    items = q_builder.offset(offset_int).limit(limit_int).all()

    output = []
    for q, doc, slide in items:
        output.append(to_question_response(q, doc, slide))
    return output

@router.get("/duplicates", response_model=List[QuestionResponse])
def list_duplicate_candidates(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Lists all questions flagged with duplicate_status == 'POSSIBLE_DUPLICATE' for human review.
    """
    items = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.duplicate_status == "POSSIBLE_DUPLICATE").\
        order_by(desc(Question.duplicate_similarity)).\
        offset(offset).limit(limit).all()

    return [to_question_response(q, doc, slide) for q, doc, slide in items]

@router.get("/{question_id}", response_model=QuestionResponse)
def get_question(question_id: str, db: Session = Depends(get_db)):
    item = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.id == question_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    q, doc, slide = item
    return to_question_response(q, doc, slide)

@router.post("/{question_id}/resolve-duplicate", response_model=QuestionResponse)
def resolve_question_duplicate(
    question_id: str,
    req: DuplicateResolveRequest,
    db: Session = Depends(get_db)
):
    """
    Resolves a question flagged as POSSIBLE_DUPLICATE:
    - CONFIRM_DUPLICATE: marks question as confirmed duplicate and merges provenance with original.
    - DISMISS_UNIQUE: marks question as verified UNIQUE / RESOLVED.
    - MERGE: updates occurrence count and merges source deck references.
    """
    item = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.id == question_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    q, doc, slide = item
    action = req.action.upper()

    if action in ["CONFIRM_DUPLICATE", "MERGE"]:
        q.duplicate_status = "CONFIRMED_DUPLICATE"
        if q.duplicate_of_id:
            original = db.query(Question).filter(Question.id == q.duplicate_of_id).first()
            if original:
                original.occurrence_count = (original.occurrence_count or 1) + 1
                prov = list(original.provenance_decks or [])
                if not any(p.get("document_id") == q.document_id for p in prov):
                    prov.append({"document_id": q.document_id, "slide_id": q.slide_id})
                    original.provenance_decks = prov
    elif action in ["DISMISS_UNIQUE", "RESOLVE"]:
        q.duplicate_status = "RESOLVED"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown resolution action: {req.action}")

    db.commit()
    db.refresh(q)
    return to_question_response(q, doc, slide)

@router.patch("/{question_id}", response_model=QuestionResponse)
def update_question(
    question_id: str,
    payload: QuestionUpdate,
    db: Session = Depends(get_db)
):
    """
    Update tags, topics, or content fields for a question in the Question Vault.
    Provides full curation control to teachers and quizmasters.
    """
    item = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.id == question_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    q, doc, slide = item

    if payload.tags is not None:
        # Clean, trim, strip leading '#', and deduplicate case-insensitively while preserving order
        cleaned_tags = []
        seen = set()
        for t in payload.tags:
            if not isinstance(t, str):
                continue
            clean = t.strip()
            if clean.startswith("#"):
                clean = clean[1:].strip()
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                cleaned_tags.append(clean)
        q.tags = cleaned_tags

    if payload.topics is not None:
        cleaned_topics = []
        seen_topics = set()
        for top in payload.topics:
            if not isinstance(top, str):
                continue
            c = top.strip()
            if c and c.lower() not in seen_topics:
                seen_topics.add(c.lower())
                cleaned_topics.append(c)
        q.topics = cleaned_topics
        if cleaned_topics and not payload.topic:
            q.topic = cleaned_topics[0]

    if payload.topic is not None:
        q.topic = payload.topic.strip()
    if payload.subtopic is not None:
        q.subtopic = payload.subtopic.strip()
    if payload.difficulty is not None:
        q.difficulty = payload.difficulty.strip()
    if payload.question_text is not None:
        q.question_text = payload.question_text.strip()
    if payload.answer is not None:
        q.answer = payload.answer.strip()
    if payload.explanation is not None:
        q.explanation = payload.explanation.strip()

    db.commit()
    db.refresh(q)
    return to_question_response(q, doc, slide)

@router.post("/{question_id}/tags", response_model=QuestionResponse)
def add_question_tag(
    question_id: str,
    tag: str = Query(..., description="Tag name to append"),
    db: Session = Depends(get_db)
):
    """
    Directly append a new tag to a question.
    """
    item = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.id == question_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    q, doc, slide = item
    current_tags = list(q.tags or [])
    clean_tag = tag.strip().lstrip("#").strip()
    if clean_tag and not any(clean_tag.lower() == t.lower() for t in current_tags):
        current_tags.append(clean_tag)
        q.tags = current_tags
        db.commit()
        db.refresh(q)

    return to_question_response(q, doc, slide)

@router.delete("/{question_id}/tags/{tag_name}", response_model=QuestionResponse)
def delete_question_tag(
    question_id: str,
    tag_name: str,
    db: Session = Depends(get_db)
):
    """
    Delete a specific tag from a question.
    """
    item = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.id == question_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    q, doc, slide = item
    current_tags = list(q.tags or [])
    clean_target = tag_name.strip().lstrip("#").strip().lower()
    updated_tags = [t for t in current_tags if t.strip().lstrip("#").strip().lower() != clean_target]
    q.tags = updated_tags
    db.commit()
    db.refresh(q)
    return to_question_response(q, doc, slide)

