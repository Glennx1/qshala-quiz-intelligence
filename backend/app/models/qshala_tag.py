"""QShala-domain tagging tables.

Three new tables, all keyed on the existing `questions.id`:
  qshala_question_metadata — ingestion fields the Excel captures that `questions` doesn't.
  qshala_tags              — one row per tagging run; never updated in place.
  qshala_tag_changes       — audit trail for every status transition.

The "current tags" for a question is the newest row in `qshala_tags` with status='confirmed'.
Re-tagging inserts a new row; it never mutates history.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship

from backend.app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class QshalaQuestionMetadata(Base):
    """Ingestion metadata — the Excel columns the base `questions` table doesn't carry.

    One row per question. Written by the ingestion pipeline after `questions` is populated,
    or back-filled from an uploaded dataset-review spreadsheet.
    """
    __tablename__ = "qshala_question_metadata"

    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)

    star_marked = Column(Boolean, default=False)
    question_number = Column(Integer, nullable=True)             # Position in the source deck.
    answer_type = Column(String(32), nullable=True)              # Text | Image | Audio | Video
    media_type = Column(String(32), nullable=True)               # IMAGE | AUDIO | VIDEO | NONE
    clue_media_url = Column(Text, nullable=True)
    reveal_media_url = Column(Text, nullable=True)

    round_stage = Column(String(32), nullable=True)              # Prelims | Finals | Theme | Warmup
    question_format = Column(String(32), nullable=True)          # QuestionAnswer | Written | Audio | Video | Visual
    college_institution = Column(String(255), nullable=True)
    quiz_name = Column(String(255), nullable=True)
    source_date = Column(DateTime(timezone=True), nullable=True)
    source_presentation = Column(String(500), nullable=True)
    primary_audience = Column(String(64), nullable=True)         # Inter-College | Intra-College | Corporate | School | Family
    secondary_audience = Column(String(64), nullable=True)
    language = Column(String(32), default="English")

    # v6 additions. These hold the *effective* value for the question: copied from the deck when the
    # question is ingested, overwritten by the tagger (geography, relevant year) or by a human.
    # `manual_fields` lists the fields a human edited so a deck edit or re-tag never overwrites them.
    round_number = Column(Integer, nullable=True)
    question_in_round = Column(Integer, nullable=True)           # "Round 3 Q4" -> round_number=3, question_in_round=4
    city_name = Column(String(100), nullable=True)               # where the quiz was held (from the deck name)
    deck_year = Column(Integer, nullable=True)
    is_varsity = Column(Boolean, default=False)                  # Zerodha Varsity Quiz (ZVQ in the deck name)
    relevant_year = Column(Integer, nullable=True)               # the year the question is about, e.g. 2016
    geo_region = Column(String(100), nullable=True)              # where the question is about
    india_international = Column(String(8), nullable=True)       # IN | INTL | NA
    manual_fields = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class QshalaTag(Base):
    """One tagging run for a question.

    Each call to the tagger (rule, LLM, or human) inserts a new row with status='draft'.
    Promoting it to 'confirmed' sets any previously confirmed row for the same question
    to 'superseded' and records the transition in qshala_tag_changes.
    """
    __tablename__ = "qshala_tags"

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)

    taxonomy_version = Column(String(16), nullable=False, default="v4")
    model_version = Column(String(64), nullable=True)             # e.g. "gemini-3.5-flash-lite" / "rule-v1" / "human"
    source = Column(String(16), nullable=False, index=True)       # RULE | LLM | NEIGHBOUR | HUMAN

    # The tag payload.
    topic_l1 = Column(String(100), nullable=True, index=True)
    subtopic_l2 = Column(String(100), nullable=True, index=True)
    keywords_l3 = Column(JSON, default=list)                      # 4–7 keywords, Title Case, most specific first.
    secondary_l2 = Column(JSON, default=list)                     # Up to 2 alternative subtopics.
    entity_type = Column(String(32), nullable=True, index=True)               # COMPANY | PERSON | TERM | PRODUCT_OR_OBJECT | BOOK | ORGANISATION | POLICY | NUMBER | PLACE | EVENT

    city_name = Column(String(100), nullable=True)
    geo_region = Column(String(64), nullable=True)                # South India | West India | North India | ...
    india_international = Column(String(16), nullable=True, index=True)       # IN | INTL | MIXED (v5.1) | NA (v6)
    relevant_year = Column(Integer, nullable=True)                # v6: the year the question is about

    shelf_life = Column(String(24), nullable=True, index=True)                # EVERGREEN | REVIEW_YEARLY | TIME_SENSITIVE
    sensitivity = Column(String(24), nullable=True, index=True)               # NONE | POLITICAL | MATURE_REFERENCE
    fit = Column(String(16), nullable=True)                       # good | weak | none  — model's own self-rating.

    search_summary = Column(Text, nullable=True)                  # ≤25 words, for the future RAG retrieval feature.

    confidence = Column(Float, nullable=True)                     # 0.0–1.0  — rule agreement rate OR explicit from caller.
    status = Column(String(16), nullable=False, default="draft", index=True)  # draft | confirmed | superseded

    verified_by = Column(String(255), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    verification_notes = Column(Text, nullable=True)
    fact_check_url = Column(Text, nullable=True)

    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    thinking_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_now, index=True)


# For the "current confirmed tag" lookup: `WHERE question_id = ? AND status = 'confirmed' ORDER BY created_at DESC LIMIT 1`
Index("ix_qshala_tags_current", QshalaTag.question_id, QshalaTag.status, QshalaTag.created_at.desc())


class QshalaTagChange(Base):
    """Audit trail for status transitions on qshala_tags.

    Every promotion from draft→confirmed, confirmed→superseded, or human override
    writes a row here. Nothing in this table is ever updated; it is append-only history.
    """
    __tablename__ = "qshala_tag_changes"

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    from_tag_id = Column(String(36), ForeignKey("qshala_tags.id", ondelete="SET NULL"), nullable=True)
    to_tag_id = Column(String(36), ForeignKey("qshala_tags.id", ondelete="SET NULL"), nullable=True)
    change_type = Column(String(32), nullable=False)              # PROMOTE | SUPERSEDE | HUMAN_OVERRIDE | ROLLBACK
    actor = Column(String(255), nullable=True)                    # Email or system identifier.
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime(timezone=True), default=_now, index=True)
