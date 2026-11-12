"""WorldLife 回归验收：同时检查能力边界和异常恢复。运行: python -m unittest discover -s tests -v"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.store import SQLiteStore
from simlife.projection import actor_view
from simlife.model import Decision

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples/scenarios"


def scenario(name: str):
    return load_scenario(CASES / f"{name}.json")


def events(run: WorldRuntime, kind: str):
    return [e for e in run.pending_log if e["type"] == kind]


class TestWorldLife(unittest.TestCase):
    def test_01_two_worlds_run_without_external_services(self):
        for name in ("apartment", "orbital"):
            with self.subTest(name=name):
                r = WorldRuntime(scenario(name))
                r.run_until(4320)
                self.assertEqual(r.minute, 4320)
                self.assertTrue(events(r, "action_completed"))
                self.assertTrue(events(r, "actor_moved"))
                self.assertTrue(events(r, "world_resource_added"))
                self.assertTrue(all(0 <= d <= 100 for life in r.lives.values()
                                    for d in life.drives.values()))
                self.assertTrue(all(0 <= life.vitality <= 100 for life in r.lives.values()))

    def test_02_deterministic_same_initial_state(self):
        a, b = WorldRuntime(scenario("apartment")), WorldRuntime(scenario("apartment"))
        a.run_until(1440)
        b.run_until(1440)
        self.assertEqual(a.snapshot(), b.snapshot())
        self.assertEqual(a.pending_log, b.pending_log)

    def test_03_persist_resume_matches_one_pass(self):
        s = scenario("resilience")
        full = WorldRuntime(s)
        full.run_until(1200)
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "world.db"
            with SQLiteStore(db) as store:
                partial = store.load_or_create(s)
                partial.run_until(363)
                store.save(partial)
            with SQLiteStore(db) as store:
                restored = store.load_or_create(s)
                restored.run_until(1200)
                store.save(restored)
                count = store.connection.execute("SELECT count(*) FROM events").fetchone()[0]
            self.assertEqual(full.snapshot(), restored.snapshot())
            self.assertEqual(len(full.pending_log), count)

    def test_04_restore_while_action_running(self):
        s = scenario("apartment")
        full = WorldRuntime(s)
        full.run_until(1500)
        partial = WorldRuntime(s)
        for minute in range(1, 500):
            partial.run_until(minute)
            if any(life.busy for life in partial.lives.values()):
                break
        self.assertTrue(any(life.busy for life in partial.lives.values()))
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteStore(Path(directory) / "test.db") as store:
                store.save(partial)
                restored = store.load_or_create(s)
                restored.run_until(1500)
            self.assertEqual(full.snapshot(), restored.snapshot())

    def test_05_reject_different_scenario_save(self):
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteStore(Path(directory) / "test.db") as store:
                store.save(WorldRuntime(scenario("apartment")))
                with self.assertRaisesRegex(ValueError, "规则版本发生变化"):
                    store.load_or_create(scenario("orbital"))

    def test_06_no_global_inventory_leak_in_life_knowledge(self):
        r = WorldRuntime(scenario("discovery"))
        life = r.lives["newcomer"]
        self.assertEqual(life.beliefs, {})
        r.run_until(0)
        self.assertNotIn("tap", life.beliefs)
        self.assertEqual(life.busy["kind"], "move")
        self.assertNotIn("resources", life.to_dict())

    def test_07_exploration_learns_local_facilities(self):
        r = WorldRuntime(scenario("discovery"))
        r.run_until(60)
        life = r.lives["newcomer"]
        self.assertGreater(len(life.visited), 1)
        self.assertTrue(events(r, "facility_discovered"))
        self.assertIn("tap", life.beliefs)
        self.assertIn("bottle", life.beliefs)

    def test_08_failed_attempt_produces_feedback_and_fallback(self):
        r = WorldRuntime(scenario("resilience"))
        r.run_until(20)
        life = r.lives["traveler"]
        failures = events(r, "action_failed")
        self.assertEqual(failures[0]["details"]["reason"], "resource_unavailable")
        self.assertEqual(life.beliefs["tap"].last_result, "resource_unavailable")
        self.assertEqual(life.beliefs["bottle"].last_result, "ok")
        self.assertEqual(events(r, "action_completed")[0]["details"]["facility"], "bottle")
        self.assertEqual(life.goal, None)
        self.assertGreater(life.failed_until["tap"], r.minute)

    def test_09_goal_survives_while_moving(self):
        r = WorldRuntime(scenario("resilience"))
        r.run_until(3)
        self.assertEqual(r.lives["traveler"].goal, "thirst")
        self.assertEqual(r.lives["traveler"].busy["kind"], "move")

    def test_10_recurring_resource_event_works_without_agents(self):
        r = WorldRuntime(scenario("resilience"))
        r.run_until(725)
        self.assertEqual([e["minute"] for e in events(r, "world_resource_added")], [240, 480, 720])
        self.assertEqual(r.resources["water"], 5)

    def test_11_facility_outage_and_recovery(self):
        r = WorldRuntime(scenario("resilience"))
        r.run_until(700)
        changes = events(r, "world_facility_changed")
        self.assertEqual([e["details"]["enabled"] for e in changes], [False, True])
        self.assertTrue(r.enabled["bottle"])

    def test_12_low_vitality_blocks_movement(self):
        s = scenario("resilience")
        s.initial_lives["traveler"].vitality = 5
        r = WorldRuntime(s)
        r.run_until(80)
        self.assertEqual(r.lives["traveler"].location, "bedroom")
        self.assertTrue(any(e["details"]["reason"] == "low_vitality_move"
                            for e in events(r, "action_blocked")))

    def test_13_unmet_critical_need_can_reduce_vitality(self):
        s = scenario("resilience")
        s.initial_lives["traveler"].set_drive("thirst", 100, 0)
        s.initial_lives["traveler"].vitality = 5
        r = WorldRuntime(s)
        r.run_until(120)
        self.assertLess(r.lives["traveler"].vitality, 5)

    def test_14_npc_can_assist_another_life(self):
        r = WorldRuntime(scenario("care"))
        r.run_until(75)
        aid = events(r, "assistance_completed")
        self.assertTrue(aid)
        self.assertEqual(aid[0]["actor"], "caretaker")
        self.assertEqual(aid[0]["details"]["target"], "patient")
        self.assertGreater(r.lives["patient"].vitality, 30)

    def test_15_multiple_actors_share_resources_without_negative_stock(self):
        s = scenario("apartment")
        original = s.initial_lives["resident_01"]
        other = copy.deepcopy(original)
        other.id = "resident_02"
        other.set_drive("thirst", 90, 0)
        s.initial_lives[other.id] = other
        s.personas[other.id] = s.personas["resident_01"]
        r = WorldRuntime(s)
        r.run_until(800)
        self.assertEqual(set(r.lives), {"resident_01", "resident_02"})
        self.assertGreater(len({e["actor"] for e in events(r, "action_completed")}), 1)
        self.assertTrue(all(v >= 0 for v in r.resources.values()))

    def test_16_modifying_drive_updates_anchor(self):
        r = WorldRuntime(scenario("apartment"))
        life = r.lives["resident_01"]
        life.set_drive("thirst", 99, 0)
        r.run_until(60)
        self.assertNotEqual(life.drives["thirst"], 36.5)
        self.assertLess(life.drives["thirst"], 99)

    def test_17_body_state_saves_and_restores(self):
        s = scenario("care")
        r = WorldRuntime(s)
        r.run_until(47)
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteStore(Path(directory) / "save.db") as store:
                store.save(r)
                resumed = store.load_or_create(s)
            self.assertEqual(r.snapshot(), resumed.snapshot())

    def test_18_invalid_references_rejected(self):
        s = scenario("resilience")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            p = base / "world.json"
            q = base / "actor.json"
            world = {"id": "bad", "locations": {"a": {"b": 1}},
                     "resources": {}, "facilities": []}
            p.write_text(json.dumps(world), encoding="utf-8")
            q.write_text(json.dumps({"world": "world.json", "actors": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "非法地点连接"):
                load_scenario(q)

    def test_19_cannot_move_time_backwards(self):
        r = WorldRuntime(scenario("apartment"))
        r.run_until(20)
        with self.assertRaisesRegex(ValueError, "不能倒退"):
            r.run_until(19)

    def test_20_resource_is_accounted_by_events(self):
        r = WorldRuntime(scenario("apartment"))
        r.run_until(4320)
        start = 18
        for event in r.pending_log:
            if event["type"] == "world_resource_added" and event["details"]["resource"] == "water":
                start += event["details"]["amount"]
            if event["type"] == "action_completed" and event["details"]["facility"] == "tap":
                start -= 1
        self.assertAlmostEqual(start, r.resources["water"])

    def test_21_failure_does_not_multiply_events_on_restart(self):
        s = scenario("resilience")
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteStore(Path(directory) / "test.db") as store:
                r = store.load_or_create(s)
                r.run_until(20)
                expected = len(r.pending_log)
                store.save(r)
                store.save(r)  # 第二次保存应当是幂等的
                count = store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                self.assertEqual(count, expected)
                self.assertEqual(r.pending_log, [])

    def test_22_repeat_failure_uses_backoff_not_fast_spam(self):
        s = scenario("resilience")
        # 食物库存设为零，并把饥饿作为当前最紧迫需求。
        s.world.initial_resources["food"] = (0, 8)
        s.initial_lives["traveler"].set_drive("thirst", 0, 0)
        s.initial_lives["traveler"].set_drive("hunger", 80, 0)
        r = WorldRuntime(s)
        r.run_until(900)
        fail = [e["minute"] for e in events(r, "action_failed")
                if e["details"].get("facility") == "meal"]
        self.assertGreaterEqual(len(fail), 2)
        gaps = [b - a for a, b in zip(fail, fail[1:])]
        self.assertGreaterEqual(max(gaps), 360)

    def test_23_sustainable_world_survives_30_days(self):
        for name in ("apartment_sustainable", "orbital_sustainable"):
            with self.subTest(name=name):
                r = WorldRuntime(scenario(name))
                r.run_until(720 * 60)
                self.assertFalse(events(r, "action_blocked"))
                self.assertFalse(events(r, "action_failed"))
                self.assertGreater(min(life.vitality for life in r.lives.values()), 70)

    def test_24_facility_can_be_disabled_before_action(self):
        r = WorldRuntime(scenario("resilience"))
        r._schedule(0, "facility_disable", {"facility": "tap"})
        r.run_until(20)
        self.assertTrue(any(e["details"].get("reason") == "facility_disabled"
                            for e in events(r, "action_failed")))
        self.assertTrue(any(e["details"]["facility"] == "bottle"
                            for e in events(r, "action_completed")))

    def test_25_restorative_facility_changes_vitality_during_use(self):
        s = scenario("apartment")
        life = s.initial_lives["resident_01"]
        life.set_drive("sleep_pressure", 90, 0)
        life.vitality = 30
        r = WorldRuntime(s)
        r.run_until(120)
        self.assertGreater(r.lives["resident_01"].vitality, 30)

    def test_26_npc_cannot_assist_someone_far_away(self):
        s = scenario("care")
        s.initial_lives["caretaker"].location = "studio"
        r = WorldRuntime(s)
        r.run_until(30)
        self.assertFalse(events(r, "assistance_completed"))

    def test_27_decision_policy_can_be_replaced(self):
        class QuietPolicy:
            def choose(self, life, persona, observation, known_map):
                return Decision(None, None)
        r = WorldRuntime(scenario("apartment"), decision_policy=QuietPolicy())
        r.run_until(180)
        self.assertFalse(events(r, "action_started"))
        self.assertGreater(r.lives["resident_01"].drives["thirst"], 32)

    def test_28_read_only_projection_cannot_expose_world_stock(self):
        r = WorldRuntime(scenario("discovery"))
        r.run_until(0)
        view = actor_view(r, "newcomer")
        self.assertNotIn("resources", view)
        self.assertNotIn("tap", view["known_facilities"])
        view["drives"]["thirst"] = 0
        self.assertNotEqual(r.lives["newcomer"].drives["thirst"], 0)

    def test_29_blocked_state_does_not_spam_logs(self):
        s = scenario("resilience")
        s.initial_lives["traveler"].vitality = 5
        r = WorldRuntime(s)
        r.run_until(1440)
        self.assertLessEqual(len(events(r, "action_blocked")), 1)

    def test_30_finite_supplies_are_not_magically_replenished(self):
        r = WorldRuntime(scenario("apartment"))
        r.run_until(720 * 60)
        self.assertEqual(r.resources["water"], 0)
        self.assertLess(r.lives["resident_01"].vitality, 10)
        self.assertTrue(events(r, "action_blocked"))


if __name__ == "__main__":
    unittest.main()
