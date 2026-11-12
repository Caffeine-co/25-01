"""简单可信的持久化：同一个 SQLite 事务写入快照与事件日志。

这不是完整事件溯源；回放依赖快照或新场景和记录下来的决策结果。
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from .engine import WorldRuntime
from .model import Scenario


class SQLiteStore:
    def __init__(self, path: str | Path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(target)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS checkpoint (
            slot INTEGER PRIMARY KEY CHECK(slot=1),
            scenario_hash TEXT NOT NULL, state_json TEXT NOT NULL)""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            minute INTEGER NOT NULL, type TEXT NOT NULL,
            actor TEXT, details_json TEXT NOT NULL)""")
        self.connection.commit()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.connection.close()

    def load_or_create(self, scenario: Scenario, **kwargs) -> WorldRuntime:
        row = self.connection.execute(
            "SELECT scenario_hash,state_json FROM checkpoint WHERE slot=1").fetchone()
        if row is None:
            return WorldRuntime(scenario, **kwargs)
        if row[0] != scenario.fingerprint:
            raise ValueError("规则/场景发生变化，请重新开档")
        return WorldRuntime.from_snapshot(scenario, json.loads(row[1]), **kwargs)

    def save(self, runtime: WorldRuntime) -> None:
        state = json.dumps(runtime.snapshot(), ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute("""INSERT INTO checkpoint(slot,scenario_hash,state_json)
                VALUES(1,?,?) ON CONFLICT(slot) DO UPDATE SET
                scenario_hash=excluded.scenario_hash,state_json=excluded.state_json""",
                (runtime.scenario.fingerprint, state))
            self.connection.executemany("""INSERT INTO events(minute,type,actor,details_json)
                VALUES(?,?,?,?)""", [
                (e["minute"], e["type"], e["actor"], json.dumps(e["details"], ensure_ascii=False))
                for e in runtime.pending_log])
        runtime.pending_log.clear()

    def recent_events(self, limit: int = 12) -> list[tuple]:
        return list(reversed(self.connection.execute("""
            SELECT minute,type,actor,details_json FROM events
            ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()))

    def count_events(self) -> dict[str, int]:
        return dict(self.connection.execute("SELECT type,COUNT(*) FROM events GROUP BY type"))
