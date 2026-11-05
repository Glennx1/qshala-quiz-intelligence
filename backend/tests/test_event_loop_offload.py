"""Blocking work stays off the event loop (audit M8)."""
import asyncio
import inspect
import threading

from backend.app.database import SessionLocal
from backend.app.routers import jobs, questions


def test_batch_status_poll_is_a_plain_handler_so_fastapi_runs_it_in_the_threadpool():
    assert not inspect.iscoroutinefunction(jobs.get_upload_batch_status)


def test_search_queries_run_in_a_worker_thread(monkeypatch):
    threads = []
    real_enrich = questions._enrich

    def spy(db, items):
        threads.append(threading.get_ident())
        return real_enrich(db, items)

    monkeypatch.setattr(questions, "_enrich", spy)
    db = SessionLocal()
    try:
        async def go():
            loop_thread = threading.get_ident()
            filtered = await questions.search_questions(db=db)                 # metadata-filter branch
            assert isinstance(filtered, list)
            return loop_thread

        loop_thread = asyncio.run(go())
    finally:
        db.close()
    assert threads and all(t != loop_thread for t in threads)
