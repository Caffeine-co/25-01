import asyncio
import importlib.util
import logging
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MAX_INSTANCES
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import STATE_RUNNING


# Load the scheduling helpers without booting the NoneBot plugin or databases.
module_path = Path(__file__).resolve().parents[1] / "src/plugins/living/scheduling.py"
spec = importlib.util.spec_from_file_location("living_scheduling", module_path)
scheduling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduling)


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = datetime(2026, 9, 10, 23, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.gate = asyncio.Event()
        self.executor = scheduling.SharedLimitAsyncIOExecutor(max_instances=1)
        self.scheduler_logger = logging.getLogger("apscheduler.test.scheduler")
        self.log_filter = scheduling.SharedLimitSkipFilter({"shared"})
        self.scheduler_logger.addFilter(self.log_filter)
        self.scheduler = AsyncIOScheduler(
            timezone="Asia/Shanghai",
            logger=self.scheduler_logger,
            executors={"shared": self.executor},
        )
        self.scheduler.start(paused=True)
        self.events = []
        self.scheduler.add_listener(self.events.append, EVENT_JOB_MAX_INSTANCES)

    async def asyncTearDown(self):
        self.gate.set()
        await self.finish_pending()
        self.scheduler.shutdown()
        await asyncio.sleep(0)
        self.scheduler_logger.removeFilter(self.log_filter)

    async def blocked_job(self):
        await self.gate.wait()

    async def finish_pending(self):
        futures = list(self.executor._pending_futures)
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)
        await asyncio.sleep(0)

    def add_job(self, job_id, max_instances=1):
        return self.scheduler.add_job(
            self.blocked_job,
            "cron",
            minute="*/10",
            id=job_id,
            executor="shared",
            max_instances=max_instances,
            misfire_grace_time=None,
            next_run_time=self.now,
        )

    def process_due_jobs(self):
        self.scheduler.state = STATE_RUNNING
        with patch("apscheduler.schedulers.base.datetime") as clock:
            clock.now.return_value = self.now
            self.scheduler._process_jobs()
        self.scheduler.pause()

    async def check_skip(self, shared_limit, same_job, expected_reason):
        self.executor._shared_max_instances = shared_limit
        active = self.add_job("active")
        self.executor.submit_job(active, [self.now])
        if same_job:
            skipped = active
        else:
            self.scheduler.pause_job(active.id)
            skipped = self.add_job("skipped")

        with self.assertLogs("apscheduler", level="WARNING") as captured:
            self.process_due_jobs()

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn(f"job_id={skipped.id};", message)
        self.assertIn(f"reason={expected_reason};", message)
        self.assertIn("scheduled_run_times=[2026-09-10T23:40:00+08:00]", message)
        self.assertNotIn("next run", message)
        self.assertIn(f"shared_instances=1/{shared_limit};", message)
        self.assertIn(f"job_instances={int(same_job)}/1;", message)
        self.assertIn("active_job_instances={'active': 1}", message)
        self.assertEqual(skipped.next_run_time, self.now.replace(minute=50))
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].job_id, skipped.id)
        self.assertEqual(self.events[0].scheduled_run_times, [self.now])
        self.assertEqual(self.executor._shared_instances, 1)

        self.gate.set()
        await self.finish_pending()
        self.assertEqual(self.executor._shared_instances, 0)
        self.assertEqual(dict(self.executor._instances), {})
        # The previously skipped job can be submitted once the slot is released.
        self.executor.submit_job(skipped, [self.now])
        await self.finish_pending()
        self.assertEqual(self.executor._shared_instances, 0)

    async def test_job_limit(self):
        await self.check_skip(2, True, "job_limit")

    async def test_shared_limit(self):
        await self.check_skip(1, False, "shared_limit")

    async def test_both_limits(self):
        await self.check_skip(1, True, "job_limit+shared_limit")

    async def test_unrelated_logs_are_preserved(self):
        job = self.add_job("ordinary")
        job.modify(executor="default")
        native_template = (
            'Execution of job "%s" skipped: maximum number of running '
            'instances reached (%d)'
        )
        with self.assertLogs("apscheduler", level="WARNING") as captured:
            self.scheduler_logger.warning(native_template, job, 1)
            self.scheduler_logger.warning("Unrelated warning")
            self.scheduler_logger.error("Submission failed")
        self.assertEqual(len(captured.records), 3)

    async def test_submission_failure_does_not_consume_slot(self):
        job = self.add_job("broken")
        with patch.object(self.executor, "_do_submit_job", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                self.executor.submit_job(job, [self.now])
        self.assertEqual(self.executor._shared_instances, 0)
        self.assertEqual(dict(self.executor._instances), {})

    async def test_failed_job_releases_slot(self):
        async def fail():
            raise ValueError("job failed")

        job = self.add_job("failed")
        job.modify(func=fail)
        with self.assertLogs("apscheduler", level="ERROR"):
            self.executor.submit_job(job, [self.now])
            await self.finish_pending()
        self.assertEqual(self.executor._shared_instances, 0)
        self.assertEqual(dict(self.executor._instances), {})


if __name__ == "__main__":
    unittest.main()
