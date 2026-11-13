"""可部署的单世界服务层：串行修改状态、事务存盘与请求幂等。

与 HTTP 分离，所以同一套操作既可由 CLI、HTTP，也可由其他平台适配器调用。
所有返回值都是 JSON 可序列化对象；未授权输入绝不直接改变世界资源。
"""
from __future__ import annotations
from pathlib import Path
from threading import RLock

from .cognition import CognitionService, Backend, OfflineBackend, reflect
from .config import load_scenario
from .planning import project_from_dict
from .projection import actor_view
from .store import SQLiteStore, payload_digest


class RuntimeService:
    def __init__(self, scenario: str | Path, database: str | Path,
                 backend: Backend | None = None, max_calls_per_day: int = 4):
        self.lock = RLock()
        self.scenario = load_scenario(scenario)
        self.store = SQLiteStore(database)
        self.world = self.store.load_or_create(self.scenario)
        self.cognition = CognitionService(backend or OfflineBackend(), max_calls_per_day)

    def close(self) -> None:
        with self.lock:
            self.store.connection.close()

    def state(self, actor: str | None = None) -> dict:
        with self.lock:
            if actor is None:
                return {"minute": self.world.minute, "world": self.scenario.world.id,
                        "actors": sorted(self.world.lives),
                        "resources": dict(self.world.resources),
                        "counts": self.store.count_events()}
            if actor not in self.world.lives:
                raise ValueError("人物不存在")
            return actor_view(self.world, actor)

    def events(self, limit: int = 20) -> list[dict]:
        import json
        with self.lock:
            return [{"minute": minute, "type": kind, "actor": actor,
                     "details": json.loads(details)}
                    for minute, kind, actor, details in self.store.recent_events(limit)]

    def _operate(self, command: str, payload: dict) -> dict:
        world = self.world
        actor = payload.get("actor")
        if command == "advance":
            minutes = payload.get("minutes")
            if type(minutes) is not int or not (0 <= minutes <= 10_080):
                raise ValueError("minutes 必须是 0..10080 的整数")
            world.run_until(world.minute + minutes)
            return {"minute": world.minute, "advanced": minutes}
        if actor not in world.lives:
            raise ValueError("actor 不存在")
        if command == "chat":
            author, text = payload.get("author", "user"), payload.get("message")
            if not isinstance(author, str) or not (1 <= len(author) <= 80):
                raise ValueError("author 非法")
            if not isinstance(text, str) or not (1 <= len(text) <= 4000):
                raise ValueError("message 非法")
            reply = self.cognition.interact(world, actor, author, text)
            return {"reply": reply.text, "model_used": reply.model_used,
                    "action_accepted": reply.action_accepted, "reason": reply.reason}
        if command == "reflect":
            return reflect(self.cognition, world, actor)
        if command == "project":
            raw = payload.get("project")
            if not isinstance(raw, dict):
                raise ValueError("project 必须是对象")
            project = project_from_dict(raw)
            world.add_project(actor, project)
            return {"project": project.id, "status": "created"}
        if command == "cancel_project":
            project_id = payload.get("project_id")
            if not isinstance(project_id, str):
                raise ValueError("project_id 非法")
            return {"cancelled": world.cancel_project(actor, project_id)}
        if command == "claim":
            key = payload.get("key")
            if not isinstance(key, str):
                raise ValueError("key 非法")
            confidence = payload.get("confidence", 0.4)
            if type(confidence) not in (float, int) or not (0 <= confidence <= 0.7):
                raise ValueError("外部声称的 confidence 不得超过 0.7")
            status = world.learn(actor, key, payload.get("value"),
                                 source="external_claim", confidence=float(confidence),
                                 source_id=payload.get("evidence_id"))
            return {"status": status}
        if command == "intent":
            kind, target = payload.get("kind"), payload.get("target")
            if not isinstance(kind, str) or not isinstance(target, str):
                raise ValueError("kind/target 非法")
            accepted, reason = world.submit_intent(actor, kind, target)
            return {"accepted": accepted, "reason": reason}
        raise ValueError("未知命令")

    def mutate(self, command: str, payload: dict, request_id: str) -> dict:
        """一次请求只生效一次；即使客户端断线重试也返回原回执。"""
        if not request_id or len(request_id) > 128 or not request_id.isascii() or not all(
                ch.isalnum() or ch in "-_:." for ch in request_id):
            raise ValueError("需要合法的 Idempotency-Key（1..128 ASCII 字符）")
        if not isinstance(payload, dict):
            raise ValueError("请求正文必须是 JSON 对象")
        digest = payload_digest({"command": command, "payload": payload})
        with self.lock:
            cached = self.store.get_request(request_id, digest)
            if cached is not None:
                return cached
            try:
                result = self._operate(command, payload)
                # 事务性保存状态、事件和回执。任何一步失败则全部回滚。
                self.store.save(self.world, request=(request_id, digest, result))
                return result
            except Exception:
                # 凡遇执行或写库异常，丢弃可能被部分修改的内存状态。
                self.world = self.store.load_or_create(self.scenario)
                raise

    def advance_internal(self, minutes: int) -> None:
        """时钟线程专用，持锁推进；不用请求幂等 ID。"""
        if minutes <= 0:
            return
        with self.lock:
            try:
                self.world.run_until(self.world.minute + minutes)
                self.store.save(self.world)
            except Exception:
                self.world = self.store.load_or_create(self.scenario)
                raise

    def backup(self, path: str | Path) -> Path:
        with self.lock:
            return self.store.backup(path)
