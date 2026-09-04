"""Recoverable single-process worker backed by the SQLite runs table."""

import asyncio
import logging

from database import get_run, recover_incomplete_runs
from pipeline import EmailDeliveryError, execute_pipeline

logger = logging.getLogger(__name__)


class AnalysisWorker:
    """Execute persisted analysis jobs outside the HTTP request lifecycle."""

    def __init__(self, config: dict, db_path: str) -> None:
        self.config = config
        self.db_path = db_path
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        recovered = recover_incomplete_runs(self.db_path, stale_after_minutes=0)
        self._task = asyncio.create_task(self._consume(), name="analysis-worker")
        for run in recovered:
            self.enqueue(int(run["id"]))
        if recovered:
            logger.warning("Recovered %d interrupted analysis job(s)", len(recovered))

    def enqueue(self, run_id: int) -> None:
        self.queue.put_nowait(run_id)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _consume(self) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                await asyncio.to_thread(self._execute_sync, run_id)
            finally:
                self.queue.task_done()

    def _execute_sync(self, run_id: int) -> None:
        run = get_run(self.db_path, run_id)
        if run is None or run["status"] != "queued":
            return
        try:
            asyncio.run(
                execute_pipeline(
                    self.config,
                    self.db_path,
                    run_id=run_id,
                    period=run["period"],
                    send_email=bool(run["email_requested"]),
                )
            )
        except EmailDeliveryError:
            logger.warning(
                "Run %d completed, but its email could not be delivered", run_id
            )
        except Exception:  # noqa: BLE001 - job boundary keeps worker alive
            # execute_pipeline persists fatal analysis failures.
            logger.error("Analysis job %d failed; state was persisted", run_id)
