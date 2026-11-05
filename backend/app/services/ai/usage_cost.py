"""Cost estimate and per-deck usage rows for Gemini calls (audit Q13)."""
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# gemini-3.5-flash-lite list prices, USD per million tokens. Thinking tokens are billed as output.
PRICE_IN_PER_M = float(os.getenv("GEMINI_PRICE_IN_PER_M", "0.075"))
PRICE_OUT_PER_M = float(os.getenv("GEMINI_PRICE_OUT_PER_M", "0.30"))
# Cached prompt tokens are billed at a fraction of the input price. 0.1 is an assumption - set the real ratio.
CACHED_INPUT_RATIO = float(os.getenv("GEMINI_CACHED_INPUT_RATIO", "0.1"))
USD_TO_INR = float(os.getenv("USD_TO_INR", "87.0"))


def estimate_cost_usd(tokens_in: int = 0, tokens_out: int = 0, thinking: int = 0, cached: int = 0) -> float:
    """`tokens_in` is Gemini's promptTokenCount, which already includes the cached tokens."""
    cached = min(max(cached or 0, 0), tokens_in or 0)
    fresh_in = (tokens_in or 0) - cached
    return (fresh_in / 1e6 * PRICE_IN_PER_M
            + cached / 1e6 * PRICE_IN_PER_M * CACHED_INPUT_RATIO
            + ((tokens_out or 0) + (thinking or 0)) / 1e6 * PRICE_OUT_PER_M)


def save_usage(db, document_id: str, stage: str, model: Optional[str], usage: Dict[str, Any]) -> None:
    """Add one usage row for a deck/stage to `db` (the caller commits). Never raises: cost bookkeeping must not
    break an ingestion."""
    try:
        if not document_id or not usage or not int(usage.get("calls", 0) or 0):
            return
        from backend.app.models.usage import IngestionUsage
        db.add(IngestionUsage(
            document_id=document_id, stage=stage, model=model, calls=int(usage.get("calls", 0) or 0),
            tokens_in=int(usage.get("in", 0) or 0), tokens_out=int(usage.get("out", 0) or 0),
            thinking_tokens=int(usage.get("think", 0) or 0), cached_tokens=int(usage.get("cached", 0) or 0)))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("could not record %s usage for %s: %s", stage, document_id, type(e).__name__)
