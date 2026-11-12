"""不用第三方依赖，复现实验数据并生成可检查的 JSON/CSV/SQLite。"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simlife.config import load_scenario  # noqa: E402
from simlife.engine import WorldRuntime  # noqa: E402
from simlife.store import SQLiteStore  # noqa: E402

SCENARIOS = ("apartment", "orbital", "resilience", "discovery", "care",
             "apartment_sustainable", "orbital_sustainable")
RESULTS = ROOT / "results"


def experiment(name: str, hours: int, *, save_db: bool = True) -> dict:
    world = load_scenario(ROOT / "examples" / "scenarios" / f"{name}.json")
    run = WorldRuntime(world)
    report_rows = []
    min_vitality = {k: 100.0 for k in run.lives}
    max_vitality = {k: 0.0 for k in run.lives}
    extreme_samples = Counter()
    for hour in range(1, hours + 1):
        run.run_until(hour * 60)
        for aid, life in run.lives.items():
            min_vitality[aid] = min(min_vitality[aid], life.vitality)
            max_vitality[aid] = max(max_vitality[aid], life.vitality)
            for drive, value in life.drives.items():
                if value >= 95:
                    extreme_samples[f"{aid}.{drive}"] += 1
            report_rows.append({
                "minute": run.minute, "actor": aid, "location": life.location,
                "vitality": life.vitality, "goal": life.goal or "",
                "busy": life.busy["kind"] if life.busy else "",
                "known_facilities": len(life.beliefs),
                **{f"drive.{key}": value for key, value in life.drives.items()},
            })

    kinds = Counter(event["type"] for event in run.pending_log)
    facilities = Counter(event["details"]["facility"] for event in run.pending_log
                         if event["type"] == "action_completed")
    fails = Counter(event["details"]["reason"] for event in run.pending_log
                    if event["type"] in {"action_failed", "action_blocked"})
    output = {
        "scenario": name, "hours": hours, "minute": run.minute,
        "world": world.world.id, "resources": run.resources,
        "event_count": len(run.pending_log), "event_types": dict(sorted(kinds.items())),
        "completed_facilities": dict(sorted(facilities.items())),
        "failure_reasons": dict(sorted(fails.items())),
        "min_vitality": min_vitality, "max_vitality": max_vitality,
        "extreme_samples_by_drive": dict(sorted(extreme_samples.items())),
        "end_lives": {aid: {
            "location": life.location, "vitality": life.vitality,
            "drives": life.drives, "goal": life.goal,
            "busy": life.busy, "visited": life.visited,
            "beliefs": {fid: {"last_result": fact.last_result, "last_seen": fact.last_seen}
                        for fid, fact in life.beliefs.items()},
        } for aid, life in run.lives.items()},
        "consistency": {
            "all_resources_nonnegative": all(value >= 0 for value in run.resources.values()),
            "all_vitalities_in_range": all(0 <= life.vitality <= 100 for life in run.lives.values()),
            "all_drive_values_in_range": all(0 <= v <= 100 for life in run.lives.values()
                                             for v in life.drives.values()),
        },
    }
    if save_db:
        database = RESULTS / f"{name}_{hours}h.db"
        # 每次基准测试都是全新世界；删除旧结果避免 events 表重复追加。
        database.unlink(missing_ok=True)
        with SQLiteStore(database) as store:
            store.save(run)
        if report_rows:
            with (RESULTS / f"{name}_{hours}h_hourly.csv").open("w", newline="", encoding="utf-8-sig") as f:
                fields = list(dict.fromkeys(k for row in report_rows for k in row))
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(report_rows)
    return output


def main() -> None:
    RESULTS.mkdir(exist_ok=True, parents=True)
    output: list[dict] = []
    for name in SCENARIOS:
        output.append(experiment(name, 72))
    # 30 天运行不附完整数据库，避免示例工程体积膨胀。
    for name in ("apartment", "orbital", "resilience", "care",
                 "apartment_sustainable", "orbital_sustainable"):
        output.append(experiment(name, 720, save_db=False))
    (RESULTS / "summary.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in output:
        print(f"{item['scenario']:10} {item['hours']:4}h | events={item['event_count']:4} "
              f"success={item['event_types'].get('action_completed', 0):3} "
              f"failure={item['event_types'].get('action_failed', 0):3} "
              f"blocked={item['event_types'].get('action_blocked', 0):3} "
              f"min_vitality={min(item['min_vitality'].values()):.1f} "
              f"resources={item['resources']}")


if __name__ == "__main__":
    main()
