"""无需模型、网络或测试框架，自动运行多场景并导出原始数据。

所有曲线来自引擎运行时的小时快照，不用事后插值编造数据。
"""
from __future__ import annotations
import csv
import json
from collections import Counter
from pathlib import Path
import sys
# 直接执行 scripts/*.py 时自动定位项目根目录，无需先 pip install。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simlife.config import load_scenario
from simlife.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "apartment_sustainable": 720,
    "apartment_scarce": 168,
    "apartment_interrupt": 72,
    "apartment_messages": 72,
    "roommates": 720,
}


def benchmark(name: str, hours: int) -> dict:
    scenario = load_scenario(ROOT / "examples" / "scenarios" / f"{name}.json")
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    db = out / f"{name}_{hours}h.db"
    db.unlink(missing_ok=True)
    hourly = []
    with SQLiteStore(db) as store:
        world = store.load_or_create(scenario)
        for hour in range(hours + 1):
            world.run_until(hour * 60)
            for actor, life in sorted(world.lives.items()):
                hourly.append({"hour": hour, "actor": actor, "location": life.location,
                               "vitality": life.vitality, "goal": life.goal or "",
                               "valence": life.emotion.valence,
                               "arousal": life.emotion.arousal,
                               "memory_count": len(life.memories),
                               "skill_total": round(sum(life.skills.values()), 6),
                               **{f"need_{k}": life.drives[k] for k in life.drives}})
        store.save(world)
        counts = store.count_events()
    fields = sorted({key for row in hourly for key in row})
    with (out / f"{name}_{hours}h_hourly.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(hourly)
    life_info = {}
    for actor, life in sorted(world.lives.items()):
        rows = [row for row in hourly if row["actor"] == actor]
        life_info[actor] = {
            "end_vitality": life.vitality,
            "min_vitality_hourly": min(row["vitality"] for row in rows),
            "max_need_hourly": {k: max(row[f"need_{k}"] for row in rows)
                                for k in life.drives},
            "final_skills": life.skills,
            "memories": len(life.memories),
            "relationships": {k: {"trust": round(v.trust, 4), "interactions": v.interactions}
                              for k, v in life.relationships.items()},
            "commitments": life.commitments,
        }
    return {"scene": name, "hours": hours, "event_counts": counts,
            "actors": life_info, "end_inventory": world.resources,
            "hourly_rows": len(hourly)}


def main() -> None:
    summary = {name: benchmark(name, hours) for name, hours in CASES.items()}
    (ROOT / "results" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {"hours": v["hours"], "counts": v["event_counts"],
                                  "actors": {a: {"skills": item["final_skills"],
                                                 "min_vitality": item["min_vitality_hourly"]}
                                             for a, item in v["actors"].items()}}
                      for name, v in summary.items()}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
