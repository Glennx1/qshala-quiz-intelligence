"""Upgrade questions stored before the v6 tag system.

    python -m backend.backfill_v6            # structure + re-tag whatever is left
    python -m backend.backfill_v6 --no-retag # structure only (no Gemini calls)
"""
import asyncio
import sys

from backend.app.main import app  # noqa: F401  (registers every model)
from backend.app.database import ensure_schema_columns  # noqa: F401
from backend.app.services import backfill_v6


def main() -> None:
    retag = "--no-retag" not in sys.argv
    asyncio.run(backfill_v6.run_all(retag=retag))
    print(backfill_v6.STATUS["message"] or backfill_v6.STATUS["state"])


if __name__ == "__main__":
    main()
