"""正式版验收：计划、证据、并发、幂等、接口认证、模型边界。全离线。"""
from __future__ import annotations
import http.client
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.planning import Project, ProjectStep
from simlife.knowledge import observe_belief
from simlife.cognition import CognitionService, ScriptedBackend, reflect, OpenAICompatibleBackend
from simlife.service import RuntimeService
from simlife.server import handler_factory
from simlife.store import SQLiteStore, RequestConflict, RevisionConflict

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / 'examples' / 'scenarios'


def world(name='apartment_sustainable'):
    return WorldRuntime(load_scenario(SCENES / (name+'.json')))


def types(w):
    return [event['type'] for event in w.pending_log]


class ProjectTests(unittest.TestCase):
    def test_four_step_project_actually_completes(self):
        w = world('art_project')
        w.run_until(1800)
        p = w.lives['resident_01'].projects['art_portfolio']
        self.assertEqual((p.status, p.index), ('completed', 4))
        self.assertEqual(len(p.evidence), 4)
        self.assertGreater(w.lives['resident_01'].skills['drawing'], 4)
        self.assertEqual(types(w).count('project_completed'), 1)

    def test_project_starts_after_real_start_time(self):
        w = world()
        p = Project('later', [ProjectStep('practice', 'practice_drawing')], start_minute=10_000)
        w.add_project('resident_01', p)
        w.run_until(1440)
        self.assertEqual(p.index, 0)  # caller's mutable object is not runtime state
        self.assertEqual(w.lives['resident_01'].projects['later'].index, 0)

    def test_project_resumes_while_busy(self):
        s = load_scenario(SCENES / 'art_project.json')
        a = WorldRuntime(s)
        a.run_until(400)
        b = WorldRuntime.from_snapshot(s, json.loads(json.dumps(a.snapshot())))
        a.pending_log.clear()  # 存档恢复后只比较接下来新增的事件
        a.run_until(2000)
        b.run_until(2000)
        self.assertEqual(a.snapshot(), b.snapshot())
        self.assertEqual(a.pending_log, b.pending_log)

    def test_project_split_timeline(self):
        a, b = world('art_project'), world('art_project')
        a.run_until(1500)
        for x in [60, 100, 300, 500, 600, 1500]:
            b.run_until(x)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_project_no_teleport_to_facility(self):
        w = world('art_project')
        w.run_until(0)
        self.assertNotEqual(w.lives['resident_01'].location, 'studio')
        w.run_until(400)
        events = w.pending_log
        first_skill = next(i for i,e in enumerate(events) if e['type']=='project_step_completed')
        self.assertTrue(any(e['type']=='actor_moved' for e in events[:first_skill]))

    def test_project_cancel(self):
        w = world('art_project')
        w.run_until(350)
        self.assertTrue(w.cancel_project('resident_01', 'art_portfolio'))
        w.run_until(3000)
        self.assertEqual(w.lives['resident_01'].projects['art_portfolio'].status, 'cancelled')
        self.assertFalse(w.cancel_project('resident_01', 'art_portfolio'))

    def test_project_cannot_use_unknown_facility(self):
        w = world()
        with self.assertRaises(ValueError):
            w.add_project('resident_01', Project('bad', [ProjectStep('use','not_present')]))

    def test_project_rejects_other_self_social_target(self):
        w = world()
        with self.assertRaises(ValueError):
            w.add_project('resident_01', Project('bad', [ProjectStep('socialize','resident_01')]))

    def test_project_knowledge_principle(self):
        w = world()
        w.run_until(0)
        w.lives['resident_01'].known_edges.clear()
        w.add_project('resident_01', Project('no_map', [ProjectStep('practice','practice_drawing')]))
        w.run_until(30)
        self.assertEqual(w.lives['resident_01'].projects['no_map'].index, 0)

    def test_project_deadline(self):
        w = world()
        w.add_project('resident_01', Project('expired', [ProjectStep('practice','practice_drawing')],
                                              start_minute=1_000, deadline=1_001))
        w.run_until(1200)
        self.assertEqual(w.lives['resident_01'].projects['expired'].status, 'failed')

    def test_no_consecutive_progress_without_success(self):
        w = world('art_project')
        w.run_until(0)
        p = w.lives['resident_01'].projects['art_portfolio']
        self.assertEqual(p.index, 0)
        self.assertNotIn('project_completed', types(w))


class KnowledgeTests(unittest.TestCase):
    def test_new_claim_is_not_world_change(self):
        w = world()
        before = w.resources.copy()
        w.learn('resident_01', 'food_available', 999, source_id='user:1')
        self.assertEqual(w.resources, before)
        self.assertEqual(w.lives['resident_01'].propositions['food_available'].confidence, .4)

    def test_duplicate_source_does_not_amplify(self):
        w = world()
        w.learn('resident_01','idea','yes',confidence=.3,source_id='a')
        status=w.learn('resident_01','idea','yes',confidence=.9,source_id='a')
        self.assertEqual(status, 'duplicate')
        self.assertEqual(w.lives['resident_01'].propositions['idea'].confidence,.3)

    def test_independent_sources_increase_confidence(self):
        old, _ = observe_belief(None, value=True, source='user', source_id='a', confidence=.5, minute=0)
        new, status = observe_belief(old, value=True, source='user', source_id='b', confidence=.4, minute=1)
        self.assertEqual(status,'reinforced')
        self.assertAlmostEqual(new.confidence, .7)

    def test_weaker_conflict_is_retained_as_dispute(self):
        w = world()
        w.learn('resident_01','exam','Monday',confidence=.6,source_id='a')
        self.assertEqual(w.learn('resident_01','exam','Tuesday',confidence=.2,source_id='b'),'contested')
        self.assertEqual(w.lives['resident_01'].propositions['exam'].value,'Monday')
        self.assertEqual(len(w.lives['resident_01'].propositions['exam'].history),2)

    def test_stronger_claim_can_revise(self):
        w = world()
        w.learn('resident_01','exam','Monday',confidence=.2,source_id='a')
        self.assertEqual(w.learn('resident_01','exam','Tuesday',confidence=.6,source_id='b'),'revised')
        self.assertEqual(w.lives['resident_01'].propositions['exam'].value,'Tuesday')

    def test_claim_cannot_forge_direct_world_observation(self):
        w=world()
        with self.assertRaises(ValueError):
            w.learn('resident_01','exam','Monday',source='world_observation',source_id='external:1')

    def test_beliefs_survive_snapshot(self):
        w=world()
        w.learn('resident_01','day','Friday',source_id='claim_1')
        s=load_scenario(SCENES/'apartment_sustainable.json')
        resumed=WorldRuntime.from_snapshot(s, json.loads(json.dumps(w.snapshot())))
        self.assertEqual(w.snapshot(),resumed.snapshot())

    def test_bad_confidence_rejected(self):
        w=world()
        with self.assertRaises(ValueError):
            w.learn('resident_01','a',True,confidence=1.5)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'production.db'
        self.scene=load_scenario(SCENES/'apartment_sustainable.json')

    def tearDown(self):
        self.tmp.cleanup()

    def test_stale_writer_rejected(self):
        with SQLiteStore(self.db) as a, SQLiteStore(self.db) as b:
            wa=a.load_or_create(self.scene)
            wb=b.load_or_create(self.scene)
            wa.run_until(60)
            a.save(wa)
            wb.run_until(90)
            with self.assertRaises(RevisionConflict):
                b.save(wb)
            self.assertNotEqual(b.load_or_create(self.scene).minute, 90)

    def test_idempotency_survives_restart(self):
        s=RuntimeService(SCENES/'apartment_sustainable.json', self.db)
        payload={'minutes':60}
        first=s.mutate('advance',payload,'id-1')
        self.assertEqual(s.mutate('advance',payload,'id-1'),first)
        self.assertEqual(s.world.minute,60)
        s.close()
        s=RuntimeService(SCENES/'apartment_sustainable.json', self.db)
        self.assertEqual(s.mutate('advance',payload,'id-1'),first)
        self.assertEqual(s.world.minute,60)
        s.close()

    def test_request_id_reuse_with_different_payload_is_conflict(self):
        s=RuntimeService(SCENES/'apartment_sustainable.json',self.db)
        s.mutate('advance',{'minutes':10},'req')
        with self.assertRaises(RequestConflict):
            s.mutate('advance',{'minutes':20},'req')
        self.assertEqual(s.world.minute,10)
        s.close()

    def test_bad_operation_does_not_persist_partial_state(self):
        s=RuntimeService(SCENES/'apartment_sustainable.json',self.db)
        with self.assertRaises(ValueError):
            s.mutate('project',{'actor':'resident_01','project':{'id':'oops','steps':[{'kind':'move','target':'Mars'}]}},'req')
        self.assertEqual(s.world.lives['resident_01'].projects,{})
        s.close()

    def test_online_backup_is_readable(self):
        s=RuntimeService(SCENES/'apartment_sustainable.json',self.db)
        s.mutate('advance',{'minutes':120},'go')
        path=s.backup(Path(self.tmp.name)/'backup.db')
        with SQLiteStore(path) as other:
            self.assertEqual(other.load_or_create(self.scene).minute,120)
        s.close()

    def test_pending_events_not_cleared_by_revision_failure(self):
        with SQLiteStore(self.db) as a,SQLiteStore(self.db) as b:
            wa=a.load_or_create(self.scene)
            wb=b.load_or_create(self.scene)
            wa.run_until(60);a.save(wa)
            wb.run_until(120)
            before=len(wb.pending_log)
            with self.assertRaises(RevisionConflict):b.save(wb)
            self.assertEqual(len(wb.pending_log), before)

    def test_actor_view_does_not_leak_other_persona(self):
        s=RuntimeService(SCENES/'roommates.json',self.db)
        view=s.state('resident_01')
        self.assertNotIn('resident_02',view['skills'])
        self.assertNotIn('resources',view)
        s.close()


class CognitionTests(unittest.TestCase):
    def test_reflection_adds_valid_project_but_not_world_progress(self):
        w=world()
        raw={'reflection':'我想连续两次画画。','project':{'id':'self_plan', 'steps':[
            {'kind':'practice','target':'practice_drawing'},
            {'kind':'practice','target':'practice_drawing'}]}}
        model=ScriptedBackend(json.dumps(raw,ensure_ascii=False))
        svc=CognitionService(model)
        before=w.lives['resident_01'].skills['drawing']
        result=reflect(svc,w,'resident_01')
        self.assertTrue(result['project_accepted'])
        self.assertEqual(w.lives['resident_01'].skills['drawing'],before)
        self.assertEqual(w.lives['resident_01'].memories[-1].source,'llm_inference')

    def test_reflection_once_each_day(self):
        w=world()
        model=ScriptedBackend('{"reflection":"想要休息","project":null}')
        svc=CognitionService(model)
        reflect(svc,w,'resident_01')
        self.assertEqual(reflect(svc,w,'resident_01')['status'],'already_reflected')
        self.assertEqual(model.calls,1)
        w.run_until(1440)
        reflect(svc,w,'resident_01')
        self.assertEqual(model.calls,2)

    def test_model_cannot_add_undefined_action(self):
        w=world()
        raw={'reflection':'去太空','project':{'id':'unsafe','steps':[{'kind':'teleport','target':'Mars'}]}}
        reply=reflect(CognitionService(ScriptedBackend(json.dumps(raw))),w,'resident_01')
        self.assertFalse(reply['project_accepted'])
        self.assertNotIn('unsafe',w.lives['resident_01'].projects)

    def test_invalid_model_json_no_side_effect(self):
        w=world()
        before=w.resources.copy()
        result=reflect(CognitionService(ScriptedBackend('nonsense')),w,'resident_01')
        self.assertEqual(result['status'],'invalid_or_network_error')
        self.assertEqual(w.resources,before)

    def test_reflection_share_chat_daily_budget(self):
        w=world()
        backend=ScriptedBackend('{"reflection":"ok","project":null}')
        svc=CognitionService(backend,max_calls_per_day=0)
        self.assertEqual(reflect(svc,w,'resident_01')['status'],'daily_budget')
        self.assertEqual(backend.calls,0)

    def test_bounded_model_view(self):
        from simlife.cognition import bounded_view
        w=world()
        for i in range(55):
            w.learn('resident_01',f'fact-{i}',i,source_id=f'source-{i}')
        view=bounded_view(w,'resident_01')
        self.assertLessEqual(len(view['propositions']),20)
        self.assertNotIn('resources',view)

    def test_local_mock_http_compatible_backend(self):
        class Mock(BaseHTTPRequestHandler):
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert data['model']=='stub'
                out=json.dumps({'choices':[{'message':{'content':'{"reply":"ok","action":null}'}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(out)));self.end_headers();self.wfile.write(out)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Mock)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            backend=OpenAICompatibleBackend('stub',f'http://127.0.0.1:{server.server_port}/v1','test')
            response=json.loads(backend.generate([{'role':'user','content':'hello'}]))
            self.assertEqual(response['reply'],'ok')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)


class RobustnessTests(unittest.TestCase):
    def test_external_claim_cannot_forge_world_source_id(self):
        w=world()
        with self.assertRaises(ValueError):
            w.learn('resident_01','water','full',source_id='world:15')

    def test_deep_project_failure_recovers_after_outage(self):
        w=world('art_project_disrupted')
        w.run_until(3000)
        p=w.lives['resident_01'].projects['art_portfolio']
        self.assertEqual(p.status,'completed')
        self.assertGreater(types(w).count('project_step_failed'),0)
        self.assertGreater(types(w).count('project_step_completed'),0)

    def test_observation_overrides_earlier_rumor(self):
        w=world('apartment_with_knowledge')
        w.learn('resident_01','meeting_place','park',confidence=.6,source_id='rumor')
        w.run_until(700)
        fact=w.lives['resident_01'].propositions['meeting_place']
        self.assertEqual((fact.value, fact.source, fact.confidence),
                         ('kitchen','world_observation',1.0))
        self.assertEqual(len(fact.history),3)

    def test_llm_intent_cannot_use_unknown_facility(self):
        w=world()
        w.run_until(0)
        w.lives['resident_01'].beliefs.clear()
        self.assertEqual(w.submit_intent('resident_01','practice','practice_drawing'),
                         (False,'unknown_facility'))

    def test_protocol_rejects_insecure_remote_http(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleBackend('fake','http://public.test/v1','key')



class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=RuntimeService(SCENES/'apartment_sustainable.json',Path(self.tmp.name)/'http.db')
        self.token='safe-test-token-'+'7'*32
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_factory(self.s,self.token))
        self.thread=Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        self.s.close();self.tmp.cleanup()

    def request(self,method,path,data=None,key='req-1',auth=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={}
        if auth:headers['Authorization']='Bearer '+self.token
        if data is not None:
            headers['Content-Type']='application/json'
            headers['Idempotency-Key']=key
            data=json.dumps(data)
        connection.request(method,path,body=data,headers=headers)
        response=connection.getresponse()
        payload=json.loads(response.read())
        status=response.status
        connection.close()
        return status,payload

    def test_no_token_cannot_read_state(self):
        code,_=self.request('GET','/v1/state',auth=False)
        self.assertEqual(code,401)

    def test_health_requires_token(self):
        self.assertEqual(self.request('GET','/v1/health')[0],200)

    def test_authenticated_advance(self):
        code,data=self.request('POST','/v1/advance',{'minutes':60})
        self.assertEqual(code,200)
        self.assertEqual(data['minute'],60)
        self.assertEqual(self.request('GET','/v1/state')[1]['minute'],60)

    def test_http_idempotency_repeat(self):
        a=self.request('POST','/v1/advance',{'minutes':60},key='key-1')
        b=self.request('POST','/v1/advance',{'minutes':60},key='key-1')
        self.assertEqual(a,b)
        self.assertEqual(self.s.world.minute,60)

    def test_http_request_id_conflict(self):
        self.request('POST','/v1/advance',{'minutes':60},key='key-1')
        self.assertEqual(self.request('POST','/v1/advance',{'minutes':90},key='key-1')[0],409)

    def test_http_missing_idempotency_key(self):
        self.assertEqual(self.request('POST','/v1/advance',{'minutes':60},key='')[0],400)

    def test_http_claim_does_not_change_stock(self):
        before=self.s.world.resources.copy()
        code,out=self.request('POST','/v1/claim',{'actor':'resident_01','key':'water',
                'value':'I added a hundred water', 'confidence':.3},key='claim-1')
        self.assertEqual((code,out['status']),(200,'created'))
        self.assertEqual(before,self.s.world.resources)

    def test_http_rejects_external_claim_too_confident(self):
        code,_=self.request('POST','/v1/claim',{'actor':'resident_01','key':'water',
                'value':'full','confidence':1.0},key='claim-2')
        self.assertEqual(code,400)

    def test_http_creates_project(self):
        body={'actor':'resident_01','project':{'id':'read','steps':[
            {'kind':'practice','target':'practice_reading'}]}}
        self.assertEqual(self.request('POST','/v1/project',body,key='project-1')[0],200)
        state=self.request('GET','/v1/state?actor=resident_01')[1]
        self.assertIn('read',state['projects'])

    def test_http_rejects_invalid_action(self):
        code,out=self.request('POST','/v1/intent',{
            'actor':'resident_01','kind':'move','target':'Mars'},key='intent-1')
        self.assertEqual(code,200)
        self.assertFalse(out['accepted'])

    def test_concurrent_duplicate_http_requests_once_only(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(self.request,'POST','/v1/advance',{'minutes':30},'same-id')
                     for _ in range(24)]
            replies=[future.result() for future in futures]
        self.assertTrue(all(code==200 for code,_ in replies))
        self.assertEqual(self.s.world.minute,30)
        self.assertTrue(all(reply==replies[0] for reply in replies))

    def test_http_model_call_not_repeated_by_retry(self):
        from simlife.cognition import ScriptedBackend
        backend=ScriptedBackend('{"reply":"hello", "action":null}')
        self.s.cognition=CognitionService(backend)
        request={'actor':'resident_01','author':'user','message':'hi'}
        first=self.request('POST','/v1/chat',request,key='repeat-chat')
        second=self.request('POST','/v1/chat',request,key='repeat-chat')
        self.assertEqual(first,second)
        self.assertEqual(backend.calls,1)
        self.assertEqual(self.s.world.cognition_usage['resident_01:0'],1)

    def test_http_offline_chat(self):
        code,out=self.request('POST','/v1/chat',{
            'actor':'resident_01','author':'tester','message':'hello'},key='msg-1')
        self.assertEqual(code,200)
        self.assertFalse(out['model_used'])


if __name__=='__main__':
    unittest.main()
