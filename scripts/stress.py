"""固定种子、带外部扰动的压力实验和回放一致性检查。"""
from __future__ import annotations
import json
from pathlib import Path
from random import Random
from collections import Counter
import sys
# 直接执行 scripts/*.py 时自动定位项目根目录，无需先 pip install。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simlife.config import load_scenario
from simlife.engine import WorldRuntime

ROOT = Path(__file__).resolve().parents[1]
DAYS = 7
SEEDS = 30


def run_seed(seed: int) -> dict:
    r = Random(seed)
    scenario_name = 'roommates' if seed % 2 else 'apartment_sustainable'
    scenario = load_scenario(ROOT/'examples/scenarios'/f'{scenario_name}.json')
    a, b = WorldRuntime(scenario), WorldRuntime(scenario)
    perturbations = []
    facilities = list(scenario.world.facilities)
    actors = list(scenario.initial_lives)
    for _ in range(9):
        minute = r.randint(10, DAYS * 1440 - 10)
        kind = r.choice(['vitality_change','facility_disable','facility_enable','message'])
        if kind == 'vitality_change':
            payload = dict(actor=r.choice(actors), amount=r.choice([-20,-10,+10,+20]))
        elif kind.startswith('facility_'):
            payload = dict(facility=r.choice(facilities))
        else:
            payload = dict(actor=r.choice(actors), text='随机测试消息', **{'from':'stress_test'})
        perturbations.append((minute,kind,payload))
    for minute, kind, payload in perturbations:
        a.schedule(minute,kind,payload.copy())
        b.schedule(minute,kind,payload.copy())
    a.run_until(DAYS * 1440)
    steps = sorted(set([0, DAYS * 1440] + [r.randint(0, DAYS * 1440) for _ in range(31)]))
    for t in steps:
        b.run_until(t)
    if a.snapshot() != b.snapshot() or a.pending_log != b.pending_log:
        raise AssertionError(f'seed={seed} checkpoint/split difference')
    for life in a.lives.values():
        if not 0 <= life.vitality <= 100 or any(not 0 <= x <= 100 for x in life.drives.values()):
            raise AssertionError(f'seed={seed} invalid life range')
    if any(n < 0 for n in a.resources.values()):
        raise AssertionError(f'seed={seed} negative inventory')
    events = Counter(x['type'] for x in a.pending_log)
    return {"seed": seed, "scene": scenario_name, "days": DAYS,
            "external_events": len(perturbations),
            "event_counts": dict(events), "end_resources": a.resources,
            "min_actor_vitality": min(x.vitality for x in a.lives.values())}


def main():
    data = [run_seed(seed) for seed in range(SEEDS)]
    out = {"seeds": SEEDS, "days_per_seed": DAYS, "all_passed": True,
           "totals": dict(sum((Counter(x['event_counts']) for x in data), Counter())),
           "cases": data}
    target = ROOT / 'results/stress_summary.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'PASS {SEEDS} deterministic replay stress tests, {DAYS} simulated days per seed')
    print('Events:',out['totals'])

if __name__ == '__main__':
    main()
