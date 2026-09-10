"""Shared APScheduler concurrency limits and precise skip diagnostics."""

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.base import MaxInstancesReachedError
from apscheduler.job import Job
from datetime import datetime
import logging
from typing import Any


class SharedLimitSkipFilter(logging.Filter):
    """Suppress only the native warning already reported by our shared executor.

    Attach to the scheduler's own logger: ancestor logger filters are not applied
    to propagated records. Keep the APScheduler 3.x template match narrow so
    unrelated warnings and exceptions remain visible.
    """
    def __init__(self, executor_aliases: set[str]) -> None:
        super().__init__()
        self.executor_aliases = frozenset(executor_aliases)

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.levelno != logging.WARNING
            or record.msg != (
                'Execution of job "%s" skipped: maximum number of running '
                'instances reached (%d)'
            )
        ):
            return True
        args = record.args
        if not isinstance(args, tuple) or len(args) != 2:
            return True
        job = args[0]
        if not isinstance(job, Job):
            return True
        return job.executor not in self.executor_aliases

class SharedLimitAsyncIOExecutor(AsyncIOExecutor):
    def __init__(self, max_instances: int = 1) -> None:
        if max_instances < 1:
            raise ValueError("max_instances 必须大于等于 1")
        super().__init__()
        self._shared_max_instances = max_instances
        self._shared_instances = 0

    def submit_job(self, job: Job, run_times: list[datetime]) -> None:
        assert self._lock is not None, "Executor 尚未启动"
        with self._lock:
            job_instances = self._instances.get(job.id, 0)
            reasons = []
            if job_instances >= job.max_instances:
                reasons.append("job_limit")
            if self._shared_instances >= self._shared_max_instances:
                reasons.append("shared_limit")
            if reasons:
                # Snapshot counts under the lock. run_times are the occurrences
                # being skipped; job.next_run_time has not yet been advanced.
                self._logger.warning(
                    "Job skipped: job_id=%s; executor=%s; scheduled_run_times=[%s]; "
                    "reason=%s; job_instances=%d/%d; shared_instances=%d/%d; "
                    "active_job_instances=%s",
                    job.id,
                    job.executor,
                    ", ".join(run_time.isoformat() for run_time in run_times),
                    "+".join(reasons),
                    job_instances,
                    job.max_instances,
                    self._shared_instances,
                    self._shared_max_instances,
                    {job_id: count for job_id, count in self._instances.items() if count},
                )
                # Preserve EVENT_JOB_MAX_INSTANCES and normal schedule advance.
                raise MaxInstancesReachedError(job)
            self._do_submit_job(job, run_times)
            self._instances[job.id] += 1
            self._shared_instances += 1

    def _release_instance(self, job_id: str) -> None:
        self._instances[job_id] -= 1
        if self._instances[job_id] == 0:
            del self._instances[job_id]
        self._shared_instances -= 1
        if self._shared_instances < 0:
            raise RuntimeError("Executor 共享运行计数小于 0")

    def _run_job_success(self, job_id: str, events: list[Any]) -> None:
        with self._lock:
            self._release_instance(job_id)
        for event in events:
            self._scheduler._dispatch_event(event)

    def _run_job_error(self, job_id: str, exc: BaseException, traceback: Any = None) -> None:
        with self._lock:
            self._release_instance(job_id)
        exc_info = (exc.__class__, exc, traceback)
        self._logger.error("Error running job %s", job_id, exc_info=exc_info)
