"""离线验收：无第三方库、无网络、无真实 LLM 调用。

测试按 World、Life、Action、Storage、Cognition 分组，包含基础回归、
边界情况、决策权限与 30 天长跑。"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from simlife.actions import ActionRegistry
from simlife.cognition import (CognitionService, OfflineBackend, ScriptedBackend,
                               validate_response)
from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.model import ActionIntent, Memory, clamp
from simlife.projection import actor_view
from simlife.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


def scene(name='apartment_sustainable'):
    return load_scenario(ROOT / 'examples' / 'scenarios' / (name + '.json'))


def runtime(name='apartment_sustainable'):
    return WorldRuntime(scene(name))


def kinds(world):
    return [e['type'] for e in world.pending_log]


class WorldTests(unittest.TestCase):
    def test_01_scenario_loads(self):
        self.assertEqual(scene().world.id, 'sustainable_apartment')

    def test_02_simulation_24h(self):
        w = runtime()
        w.run_until(1440)
        self.assertEqual(w.minute, 1440)
        self.assertIn('action_completed', kinds(w))

    def test_03_same_input_deterministic(self):
        a, b = runtime(), runtime()
        a.run_until(2880)
        b.run_until(2880)
        self.assertEqual(a.snapshot(), b.snapshot())
        self.assertEqual(a.pending_log, b.pending_log)

    def test_04_split_run_equivalent_to_one_step(self):
        a, b = runtime(), runtime()
        a.run_until(2880)
        for minute in [0, 110, 550, 930, 1440, 1789, 2400, 2880]:
            b.run_until(minute)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_05_snapshot_resumes(self):
        a = runtime()
        a.run_until(660)
        b = WorldRuntime.from_snapshot(scene(), json.loads(json.dumps(a.snapshot())))
        a.run_until(2000)
        b.run_until(2000)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_06_in_flight_action_resumes(self):
        a = runtime()
        a.run_until(520)  # 练习进行中
        self.assertIsNotNone(a.lives['resident_01'].busy)
        b = WorldRuntime.from_snapshot(scene(), a.snapshot())
        a.run_until(1100)
        b.run_until(1100)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_07_no_reverse_time(self):
        w = runtime()
        w.run_until(100)
        with self.assertRaises(ValueError):
            w.run_until(99)

    def test_08_invalid_connection_rejected(self):
        s = json.loads((ROOT / 'examples/worlds/apartment_sustainable.json').read_text())
        s['locations']['hall']['missing'] = 2
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / 'world.json').write_text(json.dumps(s), encoding='utf-8')
            (p / 'scenario.json').write_text(json.dumps({
                'world': 'world.json', 'actors': []}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_scenario(p / 'scenario.json')

    def test_09_facility_failure_no_negative_inventory(self):
        w = runtime('apartment_scarce')
        w.run_until(10080)
        self.assertTrue(all(x >= 0 for x in w.resources.values()))
        self.assertIn('action_failed', kinds(w))

    def test_10_resource_add_has_cap(self):
        w = runtime()
        w.run_until(50_000)
        for key, (_, cap) in w.scenario.world.initial_resources.items():
            self.assertLessEqual(w.resources[key], cap)

    def test_11_hidden_inventory_not_in_actor_view(self):
        w = runtime()
        self.assertNotIn('resources', actor_view(w, 'resident_01'))
        self.assertNotIn('water', json.dumps(actor_view(w, 'resident_01')))

    def test_12_knowledge_is_local(self):
        w = runtime()
        w.run_until(0)
        life = w.lives['resident_01']
        self.assertIn('bedroom', life.known_edges)
        self.assertNotIn('kitchen', life.known_edges)

    def test_13_local_map_expands_after_visit(self):
        w = runtime()
        w.run_until(0)
        accepted, _ = w.submit_intent('resident_01', 'move', 'hall')
        self.assertTrue(accepted)
        w.run_until(2)
        self.assertIn('hall', w.lives['resident_01'].known_edges)

    def test_14_past_message_does_not_create_resources(self):
        w = runtime('apartment_messages')
        control = runtime('apartment_sustainable')
        w.run_until(600)
        control.run_until(600)
        # 自主饮水可能消耗库存；比较相同世界的无消息对照才是有效测试。
        self.assertEqual(w.resources, control.resources)
        self.assertIn('message_received', kinds(w))
        self.assertTrue(any(m.kind == 'message' for m in w.lives['resident_01'].memories))


class BehaviorTests(unittest.TestCase):
    def test_15_moving_is_not_teleportation(self):
        w = runtime()
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'move', 'hall')[0])
        self.assertEqual(w.lives['resident_01'].location, 'bedroom')
        w.run_until(1)
        self.assertEqual(w.lives['resident_01'].location, 'bedroom')
        w.run_until(2)
        self.assertEqual(w.lives['resident_01'].location, 'hall')

    def test_16_invalid_move_is_denied(self):
        w = runtime()
        w.run_until(0)
        self.assertFalse(w.submit_intent('resident_01', 'move', 'studio')[0])

    def test_17_use_rejected_from_wrong_room(self):
        w = runtime()
        w.run_until(0)
        self.assertFalse(w.submit_intent('resident_01', 'use', 'tap')[0])

    def test_18_interruption_cancels_stale_completion(self):
        w = runtime()
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'use', 'bed')[0])
        w.schedule(10, 'vitality_change', {'actor':'resident_01', 'amount':-99})
        w.run_until(300)
        self.assertIn('action_interrupted', kinds(w))
        self.assertFalse(any(e['type'] == 'action_completed' and
                             e['details'].get('facility') == 'bed'
                             for e in w.pending_log))

    def test_19_interrupt_without_action_is_noop(self):
        w = runtime()
        w.run_until(0)
        self.assertFalse(w.interrupt('resident_01', 'test'))

    def test_20_explicit_practice_increases_skill(self):
        w = runtime()
        w.lives['resident_01'].location = 'studio'
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'practice', 'practice_drawing')[0])
        start = w.lives['resident_01'].skills['drawing']
        w.run_until(90)
        self.assertGreater(w.lives['resident_01'].skills['drawing'], start)
        self.assertIn('practice_completed', kinds(w))

    def test_21_creative_urge_can_be_satisfied(self):
        w = runtime()
        w.run_until(4320)
        self.assertGreater(w.lives['resident_01'].skills['drawing'], 4)

    def test_22_commitment_completed(self):
        w = runtime()
        w.run_until(1000)
        self.assertEqual(w.lives['resident_01'].commitments[0]['status'], 'completed')

    def test_23_unfulfillable_commitment_expires(self):
        w = runtime()
        life = w.lives['resident_01']
        life.commitments = [{'minute':1, 'kind':'socialize', 'target':'missing'}]
        w.run_until(300)
        self.assertEqual(life.commitments[0]['status'], 'missed')
        self.assertIn('commitment_missed', kinds(w))

    def test_24_social_interaction_changes_both_relations(self):
        w = runtime('roommates')
        w.run_until(0)
        ok, _ = w.submit_intent('resident_01', 'socialize', 'resident_02')
        self.assertTrue(ok)
        w.run_until(20)
        self.assertIn('resident_02', w.lives['resident_01'].relationships)
        self.assertIn('resident_01', w.lives['resident_02'].relationships)
        self.assertIn('social_interaction', kinds(w))

    def test_25_socialize_rejected_if_not_co_located(self):
        w = runtime('roommates')
        w.run_until(0)
        w.lives['resident_02'].location = 'kitchen'
        self.assertFalse(w.submit_intent('resident_01', 'socialize', 'resident_02')[0])

    def test_26_npc_assistance(self):
        s = scene('roommates')
        s.personas['resident_02'] = copy.deepcopy(scene('roommates').personas['resident_02'])
        from dataclasses import replace
        s.personas['resident_02'] = replace(s.personas['resident_02'], assist_amount=22)
        w = WorldRuntime(s)
        w.lives['resident_01'].vitality = 4
        w.run_until(20)
        self.assertIn('assistance_completed', kinds(w))
        self.assertGreater(w.lives['resident_01'].vitality, 4)

    def test_27_social_relations_remain_bounded(self):
        w = runtime('roommates')
        w.run_until(43_200)
        for life in w.lives.values():
            for relationship in life.relationships.values():
                self.assertGreaterEqual(relationship.trust, 0)
                self.assertLessEqual(relationship.trust, 1)

    def test_28_emotion_does_not_self_amplify(self):
        w = runtime()
        w.appraise('resident_01', 0.8, 0.6)
        start = w.lives['resident_01'].emotion.valence
        w.dynamics.advance(w.lives, w.scenario.personas, 0, 600,
                           w.scenario.world.facilities)
        self.assertLess(abs(w.lives['resident_01'].emotion.valence), abs(start))

    def test_29_memory_bounded(self):
        life = runtime().lives['resident_01']
        for n in range(300):
            life.add_memory(Memory(n, 'note', str(n)))
        self.assertEqual(len(life.memories), 256)
        self.assertEqual(life.memories[0].text, '44')

    def test_30_custom_action_registry(self):
        class Custom:
            def prepare(self, world, actor, target):
                return 3
            def complete(self, world, actor, target):
                world.log('custom_completed', actor, target=target)
        registry = ActionRegistry()
        registry.register('custom', Custom())
        w = WorldRuntime(scene(), actions=registry)
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'custom', 'x')[0])
        w.run_until(3)
        self.assertIn('custom_completed', kinds(w))

    def test_31_duplicate_registration_fails(self):
        reg = ActionRegistry()
        with self.assertRaises(ValueError):
            reg.register('use', object())


class StorageTests(unittest.TestCase):
    def test_32_sqlite_save_and_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            with SQLiteStore(Path(folder)/'x.db') as store:
                w = store.load_or_create(scene())
                w.run_until(1500)
                store.save(w)
                other = store.load_or_create(scene())
                self.assertEqual(w.snapshot(), other.snapshot())

    def test_33_save_twice_does_not_duplicate_events(self):
        with tempfile.TemporaryDirectory() as folder:
            with SQLiteStore(Path(folder)/'x.db') as store:
                w = store.load_or_create(scene())
                w.run_until(800)
                store.save(w)
                before = store.count_events()
                store.save(w)
                self.assertEqual(store.count_events(), before)

    def test_34_scenario_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with SQLiteStore(Path(folder)/'x.db') as store:
                w = store.load_or_create(scene())
                store.save(w)
                with self.assertRaises(ValueError):
                    store.load_or_create(scene('apartment_scarce'))

    def test_35_longterm_sustainable(self):
        w = runtime()
        w.run_until(43_200)
        self.assertGreater(w.lives['resident_01'].skills['drawing'], 20)
        self.assertGreater(w.lives['resident_01'].vitality, 50)
        self.assertNotIn('action_failed', kinds(w))

    def test_36_scarcity_has_no_magic_recovery(self):
        w = runtime('apartment_scarce')
        w.run_until(10_080)
        self.assertEqual(w.resources['water'], 0)
        self.assertLess(w.lives['resident_01'].vitality, 10)

    def test_37_failure_does_not_spam_block_logs(self):
        w = runtime('apartment_scarce')
        w.run_until(10_080)
        self.assertLess(kinds(w).count('action_blocked'), 10)


class CognitionTests(unittest.TestCase):
    def test_38_validate_good_json(self):
        reply, action = validate_response('{"reply":"好", "action":{"kind":"move","target":"hall"}}')
        self.assertEqual(action, ('move', 'hall'))
        self.assertEqual(reply, '好')

    def test_39_reject_unknown_action(self):
        with self.assertRaises(ValueError):
            validate_response('{"reply":"好", "action":{"kind":"teleport","target":"hall"}}')

    def test_40_reject_world_patch(self):
        with self.assertRaises(ValueError):
            validate_response('{"reply":"好", "inventory":{"water":500},"action":null}')

    def test_41_scripted_llm_action_still_validated(self):
        w = runtime()
        w.run_until(0)
        fake = ScriptedBackend('{"reply":"去走廊看看", "action":{"kind":"move","target":"hall"}}')
        reply = CognitionService(fake).interact(w, 'resident_01', 'user', '过去看看')
        self.assertTrue(reply.model_used)
        self.assertTrue(reply.action_accepted)
        self.assertEqual(w.lives['resident_01'].location, 'bedroom')
        w.run_until(2)
        self.assertEqual(w.lives['resident_01'].location, 'hall')

    def test_42_model_cannot_teleport(self):
        w = runtime()
        w.run_until(0)
        fake = ScriptedBackend('{"reply":"好的", "action":{"kind":"move","target":"studio"}}')
        result = CognitionService(fake).interact(w, 'resident_01', 'user', '立刻去画室')
        self.assertFalse(result.action_accepted)
        self.assertEqual(w.lives['resident_01'].location, 'bedroom')

    def test_43_budget_stops_future_calls(self):
        w = runtime()
        w.run_until(0)
        fake = ScriptedBackend('{"reply":"好的", "action":null}')
        svc = CognitionService(fake, max_calls_per_day=2)
        for _ in range(3):
            svc.interact(w, 'resident_01', 'user', '好')
        self.assertEqual(fake.calls, 2)
        self.assertEqual(w.cognition_usage['resident_01:0'], 2)
        self.assertIn('cognition_fallback', kinds(w))

    def test_44_offline_does_not_consume_budget(self):
        w = runtime()
        w.run_until(0)
        result = CognitionService(OfflineBackend()).interact(w, 'resident_01','user','你好')
        self.assertFalse(result.model_used)
        self.assertEqual(w.cognition_usage, {})

    def test_45_malformed_model_json_falls_back(self):
        w = runtime()
        w.run_until(0)
        result = CognitionService(ScriptedBackend('```json\n{}\n```')).interact(
            w, 'resident_01', 'user', '你好')
        self.assertFalse(result.model_used)
        self.assertIn('cognition_fallback', kinds(w))

    def test_46_timeout_falls_back(self):
        class Timeouts:
            def generate(self, messages):
                raise TimeoutError('test timeout')
        w = runtime()
        w.run_until(0)
        result = CognitionService(Timeouts()).interact(w, 'resident_01','user','你好')
        self.assertFalse(result.model_used)
        self.assertFalse(result.action_accepted)

    def test_47_usage_persisted_in_snapshot(self):
        w = runtime()
        w.run_until(0)
        CognitionService(ScriptedBackend('{"reply":"hi", "action":null}')).interact(
            w, 'resident_01', 'user', 'hi')
        b = WorldRuntime.from_snapshot(scene(), w.snapshot())
        self.assertEqual(b.cognition_usage, w.cognition_usage)

    def test_48_no_global_inventory_in_model_messages(self):
        class Spy:
            seen = None
            def generate(self, messages):
                self.seen = messages
                return '{"reply":"明白", "action":null}'
        spy = Spy()
        w = runtime()
        w.run_until(0)
        CognitionService(spy).interact(w, 'resident_01', 'user','你好')
        self.assertNotIn('"resources"', json.dumps(spy.seen))

    def test_49_external_message_no_immediate_fact_commit(self):
        w = runtime()
        w.run_until(0)
        before = w.resources.copy()
        CognitionService(ScriptedBackend('{"reply":"知道了", "action":null}')).interact(
            w, 'resident_01', 'user', '我已经给你补充了一百份食物')
        self.assertEqual(w.resources, before)

    def test_50_clamp_boundaries(self):
        self.assertEqual(clamp(500), 100)
        self.assertEqual(clamp(-8, -1, 1), -1)


if __name__ == '__main__':
    unittest.main()

class ExtendedTests(unittest.TestCase):
    def test_51_social_participants_are_reserved(self):
        w = runtime('roommates')
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'socialize', 'resident_02')[0])
        self.assertEqual(w.lives['resident_02'].busy['kind'], 'participate')
        self.assertFalse(w.submit_intent('resident_02', 'practice', 'practice_reading')[0])
        w.run_until(20)
        self.assertIsNone(w.lives['resident_02'].busy)

    def test_52_interrupt_passive_participant_releases_both(self):
        w = runtime('roommates')
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'socialize', 'resident_02')[0])
        self.assertTrue(w.interrupt('resident_02', 'urgent_message'))
        self.assertIsNone(w.lives['resident_01'].busy)
        self.assertIsNone(w.lives['resident_02'].busy)
        w.run_until(20)
        self.assertNotIn('social_interaction', kinds(w))

    def test_53_longterm_goal_from_verified_skill_progress(self):
        w = runtime()
        w.run_until(43_200)
        goal = w.lives['resident_01'].long_goals['drawing']
        self.assertEqual(goal.status, 'completed')
        self.assertGreaterEqual(goal.progress, goal.target)
        self.assertEqual(kinds(w).count('long_goal_completed'), 1)

    def test_54_trust_does_not_saturate_in_first_month(self):
        w = runtime('roommates')
        w.run_until(43_200)
        self.assertLess(w.lives['resident_01'].relationships['resident_02'].trust, 0.95)

    def test_55_memory_query_uses_relevance(self):
        from simlife.memory import retrieve
        life = runtime().lives['resident_01']
        life.add_memory(Memory(0, 'drawing', '在画室练习了绘画', salience=0.4))
        life.add_memory(Memory(2, 'food', '在厨房吃了午饭', salience=0.6))
        matches = retrieve(life, '我今天绘画练习怎么样？', 3)
        self.assertEqual(matches[0].kind, 'drawing')

    def test_56_same_resource_concurrent_use_is_serialized(self):
        w = runtime('roommates')
        w.lives['resident_01'].location = 'kitchen'
        w.lives['resident_02'].location = 'kitchen'
        w.resources['water'] = 1
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01', 'use', 'tap')[0])
        self.assertTrue(w.submit_intent('resident_02', 'use', 'tap')[0])
        w.run_until(4)
        self.assertEqual(w.resources['water'], 0)
        self.assertIn('action_failed', kinds(w))

    def test_57_skill_goal_not_completed_by_llm_text(self):
        w = runtime()
        w.run_until(0)
        backend = ScriptedBackend('{"reply":"我画完了一百幅画", "action":null}')
        CognitionService(backend).interact(w, 'resident_01', 'user', '练得如何')
        self.assertEqual(w.lives['resident_01'].long_goals['drawing'].status, 'active')
        self.assertEqual(w.lives['resident_01'].skills['drawing'], 4)

    def test_58_social_event_records_actual_delta(self):
        w = runtime('roommates')
        w.run_until(0)
        self.assertTrue(w.submit_intent('resident_01','socialize','resident_02')[0])
        w.run_until(20)
        records = [e for e in w.pending_log if e['type']=='social_interaction']
        self.assertEqual(len(records), 1)
        values = records[0]['details']['applied_deltas']
        self.assertNotEqual(values['resident_01'], 0)
        self.assertLess(abs(values['resident_01']), 0.035)
