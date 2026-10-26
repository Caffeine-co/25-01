"""无依赖的回归测试：跨 IP、资源约束、存档恢复、时间守恒。"""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "examples/scenarios/apartment.json"
ORBIT = ROOT / "examples/scenarios/orbital.json"


class TestWorldLife(unittest.TestCase):
    def test_both_worlds_run_without_llm(self):
        for config in [HOME, ORBIT]:
            with self.subTest(config=config.name):
                scenario = load_scenario(config)
                runtime = WorldRuntime(scenario)
                runtime.run_until(3 * 1440)
                self.assertEqual(runtime.minute, 4320)
                self.assertTrue(all(0 <= value <= 100 for life in runtime.lives.values()
                                    for value in life.drives.values()))
                self.assertTrue(any(e["type"] == "action_completed"
                                    for e in runtime.pending_log))
                self.assertTrue(any(e["type"] == "actor_moved"
                                    for e in runtime.pending_log))
                self.assertTrue(any(e["type"] == "world_resource_added"
                                    for e in runtime.pending_log))

    def test_restore_matches_one_pass(self):
        scenario = load_scenario(HOME)
        full = WorldRuntime(scenario)
        full.run_until(4320)
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "life.db"
            with SQLiteStore(db) as store:
                part = store.load_or_create(scenario)
                part.run_until(1234)
                store.save(part)
            with SQLiteStore(db) as store:
                resumed = store.load_or_create(scenario)
                resumed.run_until(4320)
                store.save(resumed)
                count = store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self.assertEqual(full.snapshot(), resumed.snapshot())
            self.assertEqual(len(full.pending_log), count)

    def test_resource_not_created_by_description(self):
        scenario = load_scenario(HOME)
        run = WorldRuntime(scenario)
        run.run_until(1440)
        # 资源只可能由使用或定义好的世界资源事件变动，不由 Life 状态文本生成。
        consumed = sum(1 for e in run.pending_log
                       if e["type"] == "action_completed"
                       and e["details"]["facility"] == "tap")
        refill = sum(e["details"]["amount"] for e in run.pending_log
                     if e["type"] == "world_resource_added"
                     and e["details"]["resource"] == "water")
        self.assertAlmostEqual(run.resources["water"], min(24, 18 + 4) - consumed)
        self.assertGreaterEqual(refill, 0)

    def test_reject_conflicting_configuration_on_resume(self):
        scenario_a = load_scenario(HOME)
        scenario_b = load_scenario(ORBIT)
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "life.db"
            with SQLiteStore(db) as store:
                store.save(WorldRuntime(scenario_a))
            with SQLiteStore(db) as store:
                with self.assertRaisesRegex(ValueError, "配置发生变化"):
                    store.load_or_create(scenario_b)

    def test_resume_in_the_middle_of_an_action(self):
        scenario = load_scenario(HOME)
        full = WorldRuntime(scenario)
        full.run_until(1500)
        paused = WorldRuntime(scenario)
        for minute in range(1, 900):
            paused.run_until(minute)
            if any(life.busy is not None for life in paused.lives.values()):
                break
        else:
            self.fail("测试场景未安排任何行动")
        self.assertIsNotNone(next(iter(paused.lives.values())).busy)
        with tempfile.TemporaryDirectory() as temp:
            with SQLiteStore(Path(temp) / "paused.db") as store:
                store.save(paused)
                resumed = store.load_or_create(scenario)
                resumed.run_until(1500)
                self.assertEqual(full.snapshot(), resumed.snapshot())

    def test_multiple_lives_are_independent_but_share_resources(self):
        scenario = load_scenario(HOME)
        first = scenario.initial_lives["resident_01"]
        other = copy.deepcopy(first)
        other.id = "resident_02"
        other.drives["thirst"] = 90
        scenario.initial_lives[other.id] = other
        scenario.personas[other.id] = scenario.personas["resident_01"]
        run = WorldRuntime(scenario)
        run.run_until(800)
        self.assertEqual(set(run.lives), {"resident_01", "resident_02"})
        self.assertLess(run.resources["water"], 18)
        self.assertGreaterEqual(run.resources["water"], 0)
        self.assertTrue(any(e["actor"] == "resident_02" for e in run.pending_log))

    def test_determinism(self):
        scenario = load_scenario(HOME)
        a = WorldRuntime(scenario)
        b = WorldRuntime(scenario)
        a.run_until(1200)
        b.run_until(1200)
        self.assertEqual(a.snapshot(), b.snapshot())
        self.assertEqual(a.pending_log, b.pending_log)


if __name__ == "__main__":
    unittest.main()
