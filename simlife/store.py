"""SQLite 适配器：检查点和新增事件在同一个事务内提交。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .engine import WorldRuntime
from .model import Scenario
from .systems import DecisionPolicy, Dynamics, FacilityResolver


class SQLiteStore:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint (
                slot INTEGER PRIMARY KEY CHECK (slot = 1),
                scenario_hash TEXT NOT NULL,
                state_json TEXT NOT NULL
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minute INTEGER NOT NULL,
                type TEXT NOT NULL,
                actor TEXT,
                details_json TEXT NOT NULL
            )
        """)
        self.connection.commit()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.connection.close()

    def load_or_create(self, scenario: Scenario, *,
                       dynamics: Dynamics | None = None,
                       decision_policy: DecisionPolicy | None = None,
                       facility_resolver: FacilityResolver | None = None) -> WorldRuntime:
        row = self.connection.execute(
            "SELECT scenario_hash, state_json FROM checkpoint WHERE slot = 1"
        ).fetchone()
        if row is None:
            return WorldRuntime(
                scenario, dynamics=dynamics, decision_policy=decision_policy,
                facility_resolver=facility_resolver
            )
        if row[0] != scenario.fingerprint:
            raise ValueError("世界/人设配置发生变化；请使用新的 --db 路径开始新模拟")
        return WorldRuntime.from_snapshot(
            scenario, json.loads(row[1]), dynamics=dynamics, decision_policy=decision_policy,
            facility_resolver=facility_resolver
        )

    def save(self, runtime: WorldRuntime) -> None:
        """同时保存世界状态和未提交事件，防止两者前后不一致。"""
        state_json = json.dumps(runtime.snapshot(), ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute("""
                INSERT INTO checkpoint(slot, scenario_hash, state_json)
                VALUES (1, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                  scenario_hash = excluded.scenario_hash,
                  state_json = excluded.state_json
            """, (runtime.scenario.fingerprint, state_json))
            self.connection.executemany("""
                INSERT INTO events(minute, type, actor, details_json)
                VALUES (?, ?, ?, ?)
            """, [
                (event["minute"], event["type"], event["actor"],
                 json.dumps(event["details"], ensure_ascii=False))
                for event in runtime.pending_log
            ])
        runtime.pending_log.clear()

    def recent_events(self, limit: int = 12) -> list[tuple]:
        rows = self.connection.execute("""
            SELECT minute, type, actor, details_json
            FROM events ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return list(reversed(rows))
