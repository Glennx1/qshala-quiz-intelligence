"""Index script and models for the missing foreign-key indexes (audit Q9)."""
from sqlalchemy import inspect, text

from backend.app.database import Base, engine
import backend.app.models  # noqa: F401
from scripts import add_fk_indexes as fk


def _have(table):
    return {ix["name"] for ix in inspect(engine).get_indexes(table)}


def test_models_declare_the_indexes_for_new_databases():
    for name, table, column in fk.INDEXES:
        declared = {ix.name for ix in Base.metadata.tables[table].indexes}
        assert name in declared, f"{name} missing from the {table} model"


def test_dry_run_plans_missing_indexes_without_creating_them():
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_slides_document_id"))
    assert [m[0] for m in fk.missing_indexes(engine)] == ["ix_slides_document_id"]
    sql = fk.plan(engine)
    assert sql == ["CREATE INDEX IF NOT EXISTS ix_slides_document_id ON slides (document_id)"]
    assert "ix_slides_document_id" not in _have("slides")          # planning changed nothing
    fk.apply(engine)                                                 # put the shared test database back
    assert fk.missing_indexes(engine) == []


def test_apply_is_idempotent_and_rollback_undoes_it():
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_questions_created_at"))
    assert fk.apply(engine) == ["CREATE INDEX IF NOT EXISTS ix_questions_created_at ON questions (created_at)"]
    assert "ix_questions_created_at" in _have("questions")
    assert fk.apply(engine) == []                                    # second run: nothing to do
    fk.rollback(engine)
    assert not (_have("questions") & {n for n, t, c in fk.INDEXES if t == "questions"})
    fk.apply(engine)                                                 # put the test database back
    assert fk.missing_indexes(engine) == []


def test_postgres_statements_are_concurrent():
    class PG:
        class dialect:
            name = "postgresql"
    assert fk.create_sql(PG, "ix_a", "t", "c").startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS")
    assert fk.drop_sql(PG, "ix_a").startswith("DROP INDEX CONCURRENTLY IF EXISTS")


def test_script_refuses_to_run_against_sqlite_without_the_flag(capsys):
    assert fk.main([]) == 2
    assert "Refusing" in capsys.readouterr().out
    assert fk.main(["--allow-sqlite"]) == 0                         # dry run on the test DB changes nothing
