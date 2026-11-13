"""WorldLife 2.0 正式版基准：保存 CSV、SQLite、事件指标和压力对照。

重复执行会覆盖 results/v2/ 自动生成的数据。无网络、无外部依赖。
"""
from __future__ import annotations
import csv
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'results' / 'v2'
DATA.mkdir(parents=True, exist_ok=True)

SITUATIONS = {
    'art_project': 7,
    'art_project_disrupted': 7,
    'apartment_with_knowledge': 7,
    'apartment_sustainable': 30,
    'roommates': 30,
    'apartment_scarce': 7,
}


def assert_invariants(world: WorldRuntime) -> None:
    for name, amount in world.resources.items():
        cap = world.scenario.world.initial_resources[name][1]
        assert 0 <= amount <= cap, (name, amount)
    for life in world.lives.values():
        assert 0 <= life.vitality <= 100
        assert all(0 <= drive <= 100 for drive in life.drives.values())
        assert -1 <= life.emotion.valence <= 1
        assert 0 <= life.emotion.arousal <= 1
        assert all(0 <= r.trust <= 1 for r in life.relationships.values())
        for project in life.projects.values():
            assert project.index == len(project.evidence)
            assert 0 <= project.index <= len(project.steps)
            if project.status == 'completed':
                assert project.index == len(project.steps)


def short_actor(life):
    return {'vitality':life.vitality,'location':life.location,'goal':life.goal,
            'drives':life.drives.copy(),'skills':life.skills.copy(),
            'emotion':{'valence':life.emotion.valence,'arousal':life.emotion.arousal},
            'memory_count':len(life.memories),
            'projects':{k:{'status':p.status,'step':p.index,'failures':p.failures,
                           'completed_at':p.completed_at,'evidence':p.evidence}
                        for k,p in life.projects.items()},
            'beliefs':{k:{'value':b.value,'confidence':b.confidence,'source':b.source,
                          'history':b.history} for k,b in life.propositions.items()},
            'relations':{k:{'trust':v.trust,'interactions':v.interactions}
                         for k,v in life.relationships.items()}}


def measure_scene(name: str, days: int):
    scenario = load_scenario(ROOT / 'examples' / 'scenarios' / (name + '.json'))
    end = days * 1440
    t0 = perf_counter()
    record_path = DATA / f'{name}_{days}d.db'
    if record_path.exists():
        record_path.unlink()
    with SQLiteStore(record_path) as store:
        world = store.load_or_create(scenario)
        hourly = []
        for minute in range(0, end + 1, 360):
            world.run_until(minute)
            assert_invariants(world)
            for actor, life in sorted(world.lives.items()):
                hourly.append({'minute': minute, 'actor': actor, 'location': life.location,
                               'vitality':life.vitality,'goal':life.goal or '',
                               'skill_drawing':life.skills.get('drawing',0),
                               'memory_count':len(life.memories),
                               'projects_completed':sum(p.status == 'completed' for p in life.projects.values()),
                               'thirst':life.drives.get('thirst',0),
                               'hunger':life.drives.get('hunger',0)})
        counts = Counter(e['type'] for e in world.pending_log)
        store.save(world)
        assert store.load_or_create(scenario).snapshot() == world.snapshot()
        csv_path = DATA / f'{name}_{days}d_6hour.csv'
        with csv_path.open('w',encoding='utf-8',newline='') as fp:
            writer = csv.DictWriter(fp,fieldnames=list(hourly[0]));writer.writeheader();writer.writerows(hourly)
        return {'days':days, 'event_counts':dict(counts),
                'event_total':sum(counts.values()),
                'resources':world.resources,
                'actors':{k:short_actor(v) for k,v in sorted(world.lives.items())},
                'elapsed_seconds':round(perf_counter()-t0,4)}


def split_stress(seeds=60,days=7):
    """不同初始需求、技能和假设下检查切分推进是否与一次性推进相同。"""
    base = load_scenario(ROOT / 'examples/scenarios/art_project_disrupted.json')
    rows = []
    for seed in range(seeds):
        rng = random.Random(seed)
        s = deepcopy(base)
        for life in s.initial_lives.values():
            for key in life.drives:
                life.set_drive(key, round(rng.uniform(10,70),4),0)
            life.vitality = round(rng.uniform(60,99),4)
        a, b = WorldRuntime(s), WorldRuntime(s)
        end = days*1440
        a.run_until(end)
        boundaries = sorted(set([0,end] + [rng.randint(0,end) for _ in range(18)]))
        for minute in boundaries:
            b.run_until(minute)
            assert_invariants(b)
        assert a.snapshot() == b.snapshot(), f'seed {seed} state mismatch'
        assert a.pending_log == b.pending_log, f'seed {seed} events mismatch'
        p=a.lives['resident_01'].projects['art_portfolio']
        rows.append({'seed':seed,'status':p.status,'steps_completed':p.index,
                     'total_events':len(a.pending_log),'action_failures':sum(
                         e['type']=='action_failed' for e in a.pending_log),
                     'project_failures':sum(e['type']=='project_step_failed' for e in a.pending_log),
                     'final_vitality':a.lives['resident_01'].vitality})
    path=DATA/'stress_60seeds.csv'
    with path.open('w',encoding='utf-8',newline='') as fp:
        writer=csv.DictWriter(fp,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return {'seeds':seeds,'days_per_seed':days,'split_equal':seeds,
            'completed':sum(row['status']=='completed' for row in rows),
            'failed':sum(row['status']=='failed' for row in rows),
            'event_range':[min(r['total_events'] for r in rows),max(r['total_events'] for r in rows)],
            'project_failure_range':[min(r['project_failures'] for r in rows),
                                     max(r['project_failures'] for r in rows)]}


def main():
    records={}
    for name,days in SITUATIONS.items():
        records[name]=measure_scene(name,days)
        r=records[name]
        print(f'{name:<28} {days:>2}d {r["event_total"]:>5} events '
              f'{r["elapsed_seconds"]:>5}s / {r["event_counts"].get("project_completed",0)} projects')
    stress=split_stress()
    report={'version':'2.0','scenarios':records,'stress':stress}
    (DATA/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('STRESS',stress)
    print('wrote',DATA/'metrics.json')

if __name__=='__main__':
    main()
