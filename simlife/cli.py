"""命令行运行与验收入口。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .config import load_scenario
from .store import SQLiteStore


def main() -> None:
    parser = argparse.ArgumentParser(description="WorldLife Next 可复现虚拟人物模拟")
    parser.add_argument("scenario", type=Path, help="场景文件路径")
    parser.add_argument("--hours", type=int, default=72, help="从快照继续模拟指定小时数")
    parser.add_argument("--db", type=Path, default=Path("data/worldlife.db"))
    parser.add_argument("--tail", type=int, default=12)
    args = parser.parse_args()
    if args.hours < 0 or args.tail < 0:
        parser.error("--hours / --tail 必须非负")
    scenario = load_scenario(args.scenario)
    with SQLiteStore(args.db) as store:
        world = store.load_or_create(scenario)
        start = world.minute
        world.run_until(start + 60 * args.hours)
        store.save(world)
        print(f"World: {scenario.world.id} | {start} -> {world.minute} minutes")
        print("Resources:", json.dumps(world.resources, ensure_ascii=False))
        for life in world.lives.values():
            print(f"Actor: {life.id} @ {life.location} | goal={life.goal} | busy={life.busy}")
            print("  drives:", json.dumps({k: round(v, 2) for k, v in life.drives.items()}))
            print("  vitality:", life.vitality, "skills:", life.skills,
                  "memories:", len(life.memories), "relations:", len(life.relationships))
        print("Events:", store.count_events())
        for minute, kind, actor, details in store.recent_events(args.tail):
            print(f"  t={minute:>6} | {kind:<22} | {actor or '-':<12} | {details}")


if __name__ == "__main__":
    main()
