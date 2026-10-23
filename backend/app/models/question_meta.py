"""Tables behind the v6 tag system.

  deck_metadata          - one row per uploaded deck: what the file name tells us (quiz, college, city...).
  question_topic_paths   - Theme > Subtopic > keywords. A question can have several paths.
  question_repeats       - the "Repeated" tag: every later quiz in which the same question turned up.
  question_edit_history  - who changed which field, and when.

Per-question values that are not topic paths (question number, format, star, audience, geography,
relevant year...) live on `qshala_question_metadata` (see qshala_tag.py).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)

from backend.app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class DeckMetadata(Base):
    __tablename__ = "deck_metadata"

    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)

    quiz_name = Column(String(255), nullable=True)
    college = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    round_stage = Column(String(32), nullable=True)          # Prelims | Finals | Semi-finals ...
    deck_date = Column(String(10), nullable=True)            # ISO yyyy-mm-dd when the file name had a full date
    deck_year = Column(Integer, nullable=True)
    language = Column(String(32), nullable=True)
    primary_audience = Column(String(64), nullable=True)     # College | School | Corporate | ...
    is_varsity = Column(Boolean, default=False)              # ZVQ in the deck name
    source_presentation = Column(String(500), nullable=True)  # the original file name
    parsed_ok = Column(Boolean, default=False)
    manual_fields = Column(JSON, default=list)               # fields a human edited; never overwritten by re-parsing

    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class QuestionTopicPath(Base):
    __tablename__ = "question_topic_paths"

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, default=0)                    # 0 = primary path
    l1 = Column(String(100), nullable=False)                 # Theme
    l2 = Column(String(100), nullable=True)                  # Subtopic
    keywords = Column(JSON, default=list)                    # question-specific keywords, most specific first
    source = Column(String(16), default="LLM")               # LLM | HUMAN | BACKFILL
    is_custom = Column(Boolean, default=False)               # theme/subtopic not in the shipped taxonomy

    created_at = Column(DateTime(timezone=True), default=_now)


class QuestionRepeat(Base):
    """The same question found again in another quiz. `question_id` is the original, kept question."""
    __tablename__ = "question_repeats"
    __table_args__ = (
        UniqueConstraint("question_id", "document_id", "question_number", name="uq_question_repeat_once"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    deck_title = Column(String(255), nullable=True)
    quiz_name = Column(String(255), nullable=True)
    round_number = Column(Integer, nullable=True)
    question_in_round = Column(Integer, nullable=True)
    question_number = Column(Integer, nullable=True)
    slide_range = Column(String(50), nullable=True)
    match_type = Column(String(16), default="EXACT")         # EXACT | CONFIRMED (human-confirmed near match)

    found_at = Column(DateTime(timezone=True), default=_now)


class QuestionEditHistory(Base):
    __tablename__ = "question_edit_history"

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    field = Column(String(64), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    kind = Column(String(16), default="EDIT")                # EDIT | REPEAT | RETAG | SYSTEM
    actor = Column(String(255), nullable=True)
    changed_at = Column(DateTime(timezone=True), default=_now, index=True)


Index("ix_question_edit_history_q_time", QuestionEditHistory.question_id, QuestionEditHistory.changed_at)
