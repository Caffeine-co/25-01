"""SQLite 可靠存储：原子检查点、追加日志、幂等回执、并发版本保护。

一个世界只有一个写入者。即使误启动两个进程，也不能默默覆盖彼此的状态。
这里是 checkpoint + audit log，不是可由日志完整重建的 Event Sourcing。
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
from contextlib import closing

from .engine import WorldRuntime
from .model import Scenario


class RevisionConflict(RuntimeError):
    """多个进程正在写同一世界，请停止旧进程并重新加载。"""


class RequestConflict(ValueError):
    """相同幂等请求 ID 被复用于不同内容。"""


class SQLiteStore:
    def __init__(self, path: str | Path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path = target
        self.connection = sqlite3.connect(target, timeout=5, check_same_thread=False)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS checkpoint (
            slot INTEGER PRIMARY KEY CHECK(slot=1),
            scenario_hash TEXT NOT NULL, state_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0)""")
        # 允许从 v1.0 单 slot 数据库读取列结构，但由于 RULESET 版本变化，
        # 不允许无迁移地复用旧规则快照。
        fields = {row[1] for row in self.connection.execute("PRAGMA table_info(checkpoint)")}
        if "revision" not in fields:
            self.connection.execute("ALTER TABLE checkpoint ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            minute INTEGER NOT NULL, type TEXT NOT NULL,
            actor TEXT, details_json TEXT NOT NULL)""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
            response_json TEXT NOT NULL)""")
        self.connection.commit()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.connection.close()

    def load_or_create(self, scenario: Scenario, **kwargs) -> WorldRuntime:
        row = self.connection.execute(
            "SELECT scenario_hash,state_json,revision FROM checkpoint WHERE slot=1").fetchone()
        if row is None:
            world = WorldRuntime(scenario, **kwargs)
            world._store_revision = 0
            return world
        if row[0] != scenario.fingerprint:
            raise ValueError("规则/场景与存档不匹配；备份并迁移旧数据或重新开档")
        world = WorldRuntime.from_snapshot(scenario, json.loads(row[1]), **kwargs)
        world._store_revision = int(row[2])
        return world

    def get_request(self, request_id: str, payload_hash: str) -> dict | None:
        row = self.connection.execute(
            "SELECT payload_hash,response_json FROM requests WHERE request_id=?",
            (request_id,)).fetchone()
        if row is None:
            return None
        if row[0] != payload_hash:
            raise RequestConflict("同一 request_id 不允许提交不同请求")
        return json.loads(row[1])

    def save(self, runtime: WorldRuntime, *, request: tuple[str, str, dict] | None = None) -> None:
        """事务提交。仅在成功后清除待写事件；失败后调用方应放弃内存世界并重读。"""
        state_json = json.dumps(runtime.snapshot(), ensure_ascii=False, sort_keys=True,
                                allow_nan=False)
        expected = int(getattr(runtime, "_store_revision", 0))
        # 显式抢占 SQLite 写锁，以使版本检查与更新不可交错。
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute("SELECT revision FROM checkpoint WHERE slot=1").fetchone()
            current = int(row[0]) if row is not None else 0
            if current != expected:
                raise RevisionConflict(f"存档并发修改：期待版本 {expected}，实际 {current}")
            self.connection.execute("""INSERT INTO checkpoint(slot,scenario_hash,state_json,revision)
                VALUES(1,?,?,?) ON CONFLICT(slot) DO UPDATE SET
                scenario_hash=excluded.scenario_hash, state_json=excluded.state_json,
                revision=excluded.revision""",
                (runtime.scenario.fingerprint, state_json, current + 1))
            self.connection.executemany("""INSERT INTO events(minute,type,actor,details_json)
                VALUES(?,?,?,?)""", [
                (event["minute"], event["type"], event["actor"],
                 json.dumps(event["details"], ensure_ascii=False, allow_nan=False))
                for event in runtime.pending_log])
            if request:
                request_id, payload_hash, response = request
                self.connection.execute("""INSERT INTO requests
                    (request_id,payload_hash,response_json) VALUES(?,?,?)""",
                    (request_id, payload_hash, json.dumps(response, ensure_ascii=False)))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        runtime._store_revision = current + 1
        runtime.pending_log.clear()

    def recent_events(self, limit: int = 12) -> list[tuple]:
        return list(reversed(self.connection.execute("""
            SELECT minute,type,actor,details_json FROM events
            ORDER BY id DESC LIMIT ?""", (max(0, min(limit, 1000)),)).fetchall()))

    def count_events(self) -> dict[str, int]:
        return dict(self.connection.execute("SELECT type,COUNT(*) FROM events GROUP BY type"))

    def backup(self, destination: str | Path) -> Path:
        """在线一致性备份，不直接复制仍在使用中的 WAL 文件。"""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == self.path.resolve():
            raise ValueError("备份不能覆盖正在使用的数据库")
        with closing(sqlite3.connect(destination)) as dst:
            self.connection.backup(dst)
        return destination


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()
