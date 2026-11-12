"""查看已经发生的事件；不修改数据库。例：python scripts/trace.py results/resilience_72h.db --until 30"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="逐条打印 WorldLife 事件")
    parser.add_argument("database", type=Path)
    parser.add_argument("--until", type=int, default=240, help="只看该模拟分钟之前的事件")
    args = parser.parse_args()
    with sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True) as db:
        for minute, kind, actor, raw in db.execute("""
            SELECT minute, type, actor, details_json FROM events
            WHERE minute <= ? ORDER BY id
        """, (args.until,)):
            details = json.loads(raw)
            print(f"t={minute:>5} | {kind:<23} | {actor or '-':<12} | "
                  f"{json.dumps(details, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
