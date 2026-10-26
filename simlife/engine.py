"""World Runtime。唯一能够执行动作、改变资源和提交客观事件的模块。"""
from __future__ import annotations

import heapq
import math
from copy import deepcopy
from typing import Any

from .model import LifeState, QueuedEvent, Scenario
from .systems import (
    DecisionPolicy, Dynamics, FacilityResolver, LinearDriveDynamics,
    StandardFacilityResolver, UtilityDecisionPolicy,
)


class WorldRuntime:
    """事件驱动模拟；时间单位分钟；可一次运行，也可从 SQLite 检查点继续。"""

    def __init__(self, scenario: Scenario, *, dynamics: Dynamics | None = None,
                 decision_policy: DecisionPolicy | None = None,
                 facility_resolver: FacilityResolver | None = None):
        self.scenario = scenario
        self.dynamics = dynamics or LinearDriveDynamics()
        self.decision_policy = decision_policy or UtilityDecisionPolicy()
        self.facility_resolver = facility_resolver or StandardFacilityResolver()
        self.minute = 0
        self.sequence = 0
        self.lives: dict[str, LifeState] = deepcopy(scenario.initial_lives)
        self.resources = {rid: amount for rid, (amount, _) in
                          scenario.world.initial_resources.items()}
        self.queue: list[QueuedEvent] = []
        self.pending_log: list[dict[str, Any]] = []

        for raw in scenario.world.external_events:
            self._schedule(int(raw["minute"]), "resource_add",
                           {"resource": raw["resource"], "amount": float(raw["amount"])})
        for aid in sorted(self.lives):
            self._schedule(0, "decide", {"actor": aid})

    def _schedule(self, minute: int, kind: str, payload: dict[str, Any]) -> None:
        if minute < self.minute:
            raise ValueError("禁止向过去排入事件")
        self.sequence += 1
        # 同一分钟：世界外部事件 -> 既有行动完成 -> 新决策。
        priority = {"resource_add": 0, "move_finished": 1,
                    "use_finished": 1, "decide": 2}[kind]
        heapq.heappush(self.queue, QueuedEvent(minute, priority, self.sequence, kind, payload))

    def _log(self, kind: str, actor: str | None = None, **details: Any) -> None:
        self.pending_log.append({"minute": self.minute, "type": kind,
                                 "actor": actor, "details": details})

    def _integrate(self, delta_minutes: int) -> None:
        """推进连续变化。核心只使用可配置的需求增长速率。"""
        if delta_minutes == 0:
            return
        self.dynamics.advance(self.lives, self.scenario.personas,
                              delta_minutes, self.minute + delta_minutes)

    def run_until(self, target_minute: int, *, max_events: int = 200_000) -> None:
        """推进到世界绝对分钟；从暂停点分段运行与一次性运行一致。"""
        if target_minute < self.minute:
            raise ValueError("世界时间不能倒退")
        processed = 0
        while self.queue and self.queue[0].minute <= target_minute:
            item = heapq.heappop(self.queue)
            self._integrate(item.minute - self.minute)
            self.minute = item.minute
            self._dispatch(item)
            processed += 1
            if processed > max_events:
                raise RuntimeError("事件上限触发：请检查零时间循环或频繁行动")
        self._integrate(target_minute - self.minute)
        self.minute = target_minute

    def _dispatch(self, event: QueuedEvent) -> None:
        match event.kind:
            case "decide":
                self._decide(event.payload["actor"])
            case "move_finished":
                self._complete_move(event.payload)
            case "use_finished":
                self._complete_use(event.payload)
            case "resource_add":
                self._add_resource(event.payload)
            case _:
                raise ValueError(f"未知事件: {event.kind}")

    def _decide(self, actor: str) -> None:
        life = self.lives[actor]
        if life.busy is not None:
            return
        choice = self.decision_policy.choose(life, self.scenario.personas[actor],
                                             self.scenario.world, self.resources)
        if choice is None:
            # 即使没有立即可做的事情，World 时间和外部事件仍照常推进。
            self._schedule(self.minute + 30, "decide", {"actor": actor})
            return
        facility, path, score = choice
        if len(path) > 1:
            # 移动只走下一段；完成后重新感知世界、评估目标。
            destination = path[1]
            edge = self.scenario.world.connections[life.location][destination]
            duration = max(1, math.ceil(edge * self.scenario.personas[actor].move_multiplier))
            life.busy = {"kind": "move", "to": destination, "finish": self.minute + duration}
            self._schedule(self.minute + duration, "move_finished",
                           {"actor": actor, "to": destination})
            self._log("action_started", actor, action="move", target=destination,
                      goal=facility.id, score=round(score, 4))
        else:
            life.busy = {"kind": "use", "facility": facility.id,
                         "finish": self.minute + facility.duration}
            self._schedule(self.minute + facility.duration, "use_finished",
                           {"actor": actor, "facility": facility.id})
            self._log("action_started", actor, action="use", target=facility.id,
                      score=round(score, 4))

    def _complete_move(self, payload: dict[str, Any]) -> None:
        aid, destination = payload["actor"], payload["to"]
        life = self.lives[aid]
        if life.busy is None or life.busy.get("to") != destination:
            raise RuntimeError("移动完成事件与角色任务不一致")
        if destination not in self.scenario.world.connections[life.location]:
            raise RuntimeError("移动目标不再可达")
        life.location, life.busy = destination, None
        self._log("actor_moved", aid, location=destination)
        self._schedule(self.minute, "decide", {"actor": aid})

    def _complete_use(self, payload: dict[str, Any]) -> None:
        aid, fid = payload["actor"], payload["facility"]
        life = self.lives[aid]
        facility = self.scenario.world.facilities[fid]
        if life.busy is None or life.busy.get("facility") != fid:
            raise RuntimeError("行动完成事件与角色任务不一致")
        # 真实可行性与效果由可替换的规则处理器决定，LLM 没有写权限。
        success, reason, applied = self.facility_resolver.resolve(
            life, facility, self.resources, self.minute
        )
        if success:
            self._log("action_completed", aid, facility=fid, effects=applied)
        else:
            self._log("action_failed", aid, facility=fid, reason=reason)
        life.busy = None
        self._schedule(self.minute, "decide", {"actor": aid})

    def _add_resource(self, payload: dict[str, Any]) -> None:
        rid = payload["resource"]
        cap = self.scenario.world.initial_resources[rid][1]
        before = self.resources[rid]
        self.resources[rid] = min(cap, before + payload["amount"])
        self._log("world_resource_added", resource=rid,
                  amount=round(self.resources[rid] - before, 8))

    def snapshot(self) -> dict[str, Any]:
        """检查点包含事件队列和进行中的动作，而不只是最终数值。"""
        return {
            "minute": self.minute,
            "sequence": self.sequence,
            "resources": self.resources,
            "lives": {aid: life.to_dict() for aid, life in self.lives.items()},
            "queue": [e.to_dict() for e in sorted(self.queue)],
        }

    @classmethod
    def from_snapshot(cls, scenario: Scenario, data: dict[str, Any], *,
                      dynamics: Dynamics | None = None,
                      decision_policy: DecisionPolicy | None = None,
                      facility_resolver: FacilityResolver | None = None) -> WorldRuntime:
        runtime = cls.__new__(cls)
        runtime.scenario = scenario
        runtime.dynamics = dynamics or LinearDriveDynamics()
        runtime.decision_policy = decision_policy or UtilityDecisionPolicy()
        runtime.facility_resolver = facility_resolver or StandardFacilityResolver()
        runtime.minute = int(data["minute"])
        runtime.sequence = int(data["sequence"])
        runtime.resources = {k: float(v) for k, v in data["resources"].items()}
        runtime.lives = {aid: LifeState.from_dict(v) for aid, v in data["lives"].items()}
        runtime.queue = [QueuedEvent.from_dict(e) for e in data["queue"]]
        heapq.heapify(runtime.queue)
        runtime.pending_log = []
        if set(runtime.lives) != set(scenario.personas):
            raise ValueError("存档 actor 与场景不匹配")
        return runtime
