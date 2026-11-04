"""
Rewrites stored R2 public URLs after moving media to a new bucket / public domain.

Slide media URLs are saved in the database as full absolute URLs (for example
https://pub-xxxx.r2.dev/slides/<doc>/media/<file>), so changing R2_PUBLIC_BASE_URL alone leaves
every existing row pointing at the old bucket. This scans every text and JSON column in the app's
tables and replaces the old base URL prefix with the new one.

DRY RUN by default: it only reports what it would change. Pass --apply to write the changes.
Take a database backup before using --apply.

Usage (from the repo root, with DATABASE_URL pointing at the target database):
    python -m scripts.rewrite_r2_urls --old https://pub-OLD.r2.dev --new https://pub-NEW.r2.dev
    python -m scripts.rewrite_r2_urls --old ... --new ... --apply
"""

import argparse
import sys

from sqlalchemy import JSON, String, Text, select, update

from backend.app.database import Base, SessionLocal
import backend.app.models  # noqa: F401  (registers every table on Base.metadata)


def rewrite(value, old, new):
    """Returns (new_value, number_of_replacements), walking nested JSON structures."""
    if isinstance(value, str):
        n = value.count(old)
        return (value.replace(old, new), n) if n else (value, 0)
    if isinstance(value, list):
        total, out = 0, []
        for item in value:
            v, n = rewrite(item, old, new)
            out.append(v)
            total += n
        return (out, total) if total else (value, 0)
    if isinstance(value, dict):
        total, out = 0, {}
        for k, item in value.items():
            v, n = rewrite(item, old, new)
            out[k] = v
            total += n
        return (out, total) if total else (value, 0)
    return value, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="Old public base URL, e.g. https://pub-OLD.r2.dev")
    ap.add_argument("--new", required=True, help="New public base URL, e.g. https://pub-NEW.r2.dev")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = ap.parse_args()

    old, new = args.old.rstrip("/"), args.new.rstrip("/")
    if old == new:
        print("Old and new URLs are identical; nothing to do.")
        return 0

    db = SessionLocal()
    grand_rows = grand_hits = 0
    try:
        for table in Base.metadata.sorted_tables:
            cols = [c for c in table.columns if isinstance(c.type, (JSON, Text, String))]
            if not cols or not list(table.primary_key.columns):
                continue
            pk = list(table.primary_key.columns)
            for col in cols:
                rows = db.execute(select(*pk, col)).all()
                changed_rows = hits = 0
                for row in rows:
                    value = row[-1]
                    if value is None:
                        continue
                    new_value, n = rewrite(value, old, new)
                    if not n:
                        continue
                    changed_rows += 1
                    hits += n
                    if args.apply:
                        cond = [c == row[i] for i, c in enumerate(pk)]
                        db.execute(update(table).where(*cond).values({col.name: new_value}))
                if changed_rows:
                    print(f"{table.name}.{col.name}: {changed_rows} rows, {hits} URLs")
                    grand_rows += changed_rows
                    grand_hits += hits
        if args.apply:
            db.commit()
            print(f"\nApplied: {grand_hits} URLs rewritten across {grand_rows} row/column pairs.")
        else:
            db.rollback()
            print(f"\nDRY RUN: {grand_hits} URLs would be rewritten across {grand_rows} row/column pairs. "
                  f"Re-run with --apply to write.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
