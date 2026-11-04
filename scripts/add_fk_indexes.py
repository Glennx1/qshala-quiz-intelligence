"""
Adds the missing indexes on the large tables (audit Q9) to an EXISTING database.

New databases get these from the models; tables that already exist do not (SQLAlchemy's create_all never adds
indexes to an existing table), so the production database needs this once:

    questions.document_id      deck reads, deck delete, "questions in this deck" counts
    questions.slide_id         ON DELETE SET NULL scan when slides are deleted
    questions.duplicate_of_id  ON DELETE SET NULL scan + duplicate listing
    questions.created_at       the default sort of the question list
    slides.document_id         every per-deck slide read and the deck-delete cascade

DRY RUN by default: prints the indexes it would create and the table sizes, changes nothing.
  --apply     creates the missing ones (Postgres: CREATE INDEX CONCURRENTLY, so writes are not blocked)
  --rollback  drops exactly these indexes again (the undo for --apply)

Usage, from the repo root (it uses whatever DATABASE_URL points at, so check that first):
    REQUIRE_POSTGRES=1 PYTHONPATH=. python -m scripts.add_fk_indexes              # dry run
    REQUIRE_POSTGRES=1 PYTHONPATH=. python -m scripts.add_fk_indexes --apply
    REQUIRE_POSTGRES=1 PYTHONPATH=. python -m scripts.add_fk_indexes --rollback
"""
import argparse
import sys
from typing import List, Set, Tuple

from sqlalchemy import inspect, text

# (index name, table, column) -- names match what SQLAlchemy generates for index=True columns.
INDEXES: List[Tuple[str, str, str]] = [
    ("ix_questions_document_id", "questions", "document_id"),
    ("ix_questions_slide_id", "questions", "slide_id"),
    ("ix_questions_duplicate_of_id", "questions", "duplicate_of_id"),
    ("ix_questions_created_at", "questions", "created_at"),
    ("ix_slides_document_id", "slides", "document_id"),
]


def invalid_indexes(engine) -> Set[str]:
    """Postgres only: our indexes that exist but are INVALID, which is what an interrupted or failed
    CREATE INDEX CONCURRENTLY leaves behind. The planner ignores them, and IF NOT EXISTS would skip them."""
    if engine.dialect.name != "postgresql":
        return set()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                 "WHERE NOT i.indisvalid AND c.relname = ANY(:names)"),
            {"names": [name for name, _t, _c in INDEXES]},
        ).fetchall()
        conn.rollback()
    return {r[0] for r in rows}


def missing_indexes(engine) -> List[Tuple[str, str, str]]:
    """Indexes from INDEXES that are not usable on the database yet (table must exist). An index counts as present
    when a valid one with that name exists, or any other valid index already leads with that column."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    bad = invalid_indexes(engine)
    out = []
    for name, table, column in INDEXES:
        if table not in tables:
            continue
        valid = [ix for ix in insp.get_indexes(table) if ix["name"] not in bad]
        present = any(ix["name"] == name or (ix.get("column_names") or [])[:1] == [column] for ix in valid)
        if not present:
            out.append((name, table, column))
    return out


def create_sql(engine, name: str, table: str, column: str) -> str:
    concurrently = " CONCURRENTLY" if engine.dialect.name == "postgresql" else ""
    return f"CREATE INDEX{concurrently} IF NOT EXISTS {name} ON {table} ({column})"


def drop_sql(engine, name: str) -> str:
    concurrently = " CONCURRENTLY" if engine.dialect.name == "postgresql" else ""
    return f"DROP INDEX{concurrently} IF EXISTS {name}"


def statements(engine) -> List[str]:
    """What --apply would run: a broken (INVALID) index is dropped first, then every missing one is created."""
    bad = invalid_indexes(engine)
    out: List[str] = []
    for ix in missing_indexes(engine):
        if ix[0] in bad:
            out.append(drop_sql(engine, ix[0]))
        out.append(create_sql(engine, *ix))
    return out


def plan(engine) -> List[str]:
    return statements(engine)


def apply(engine) -> List[str]:
    """Create the missing indexes. CONCURRENTLY cannot run inside a transaction, hence AUTOCOMMIT."""
    done = []
    todo = statements(engine)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for sql in todo:
            conn.execute(text(sql))
            done.append(sql)
    return done


def rollback(engine) -> List[str]:
    done = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for name, _table, _column in INDEXES:
            sql = drop_sql(engine, name)
            conn.execute(text(sql))
            done.append(sql)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="create the missing indexes")
    ap.add_argument("--rollback", action="store_true", help="drop these indexes (undo of --apply)")
    ap.add_argument("--allow-sqlite", action="store_true", help="permit running against SQLite (local dev/tests)")
    args = ap.parse_args(argv)
    if args.apply and args.rollback:
        ap.error("choose one of --apply / --rollback")

    from backend.app.database import engine
    dialect = engine.dialect.name
    if dialect != "postgresql" and not args.allow_sqlite:
        print(f"Refusing to run: the connected database is {dialect}, not PostgreSQL. "
              "(The app silently falls back to SQLite when Neon is unreachable.) Use --allow-sqlite for local dev.")
        return 2
    print(f"database dialect: {dialect}")

    if args.rollback:
        for sql in rollback(engine):
            print("ran:", sql)
        return 0

    todo = missing_indexes(engine)
    if not todo:
        print("All indexes already exist. Nothing to do.")
        return 0
    with engine.connect() as conn:
        for name, table, _ in todo:
            try:
                size = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            except Exception:
                size = "?"
            print(f"missing: {name}  (table {table}, {size} rows)")
        conn.rollback()
    if not args.apply:
        print("\nDRY RUN: nothing changed. SQL that --apply would run:")
        for sql in plan(engine):
            print("  ", sql)
        print("\nUndo: re-run with --rollback.")
        return 0
    for sql in apply(engine):
        print("ran:", sql)
    return 0


if __name__ == "__main__":
    sys.exit(main())
