import asyncio
from unittest.mock import AsyncMock

import worker
from database import create_run, finish_run, get_run, mark_run_started


def test_worker_executes_persisted_job_options(tmp_path, monkeypatch):
    db_path = str(tmp_path / "signals.db")
    run_id = create_run(
        db_path,
        "2026-09-03",
        "this week",
        email_requested=True,
    )
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_pipeline", execute)
    service = worker.AnalysisWorker({"users": ["test"]}, db_path)

    service._execute_sync(run_id)

    execute.assert_awaited_once_with(
        {"users": ["test"]},
        db_path,
        run_id=run_id,
        period="this week",
        send_email=True,
    )


def test_worker_skips_job_that_is_no_longer_queued(tmp_path, monkeypatch):
    db_path = str(tmp_path / "signals.db")
    run_id = create_run(db_path, "2026-09-03")
    mark_run_started(db_path, run_id)
    finish_run(db_path, run_id)
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_pipeline", execute)

    worker.AnalysisWorker({}, db_path)._execute_sync(run_id)

    execute.assert_not_awaited()
    assert get_run(db_path, run_id)["status"] == "completed"


def test_worker_recovers_and_consumes_queued_job(tmp_path, monkeypatch):
    db_path = str(tmp_path / "signals.db")
    run_id = create_run(db_path, "2026-09-03")
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_pipeline", execute)
    service = worker.AnalysisWorker({"users": ["test"]}, db_path)

    async def scenario():
        await service.start()
        await service.queue.join()
        await service.stop()

    asyncio.run(scenario())
    assert execute.await_count == 1
    assert execute.await_args.kwargs["run_id"] == run_id
