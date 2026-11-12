"""World Runtime：唯一执行现实行动/资源变动的入口；Life 只提出意图。"""
from __future__ import annotations

import heapq
import math
from copy import deepcopy
from typing import Any

from .model import LifeState, QueuedEvent, Scenario
from .perception import observe, remember_observation
from .systems import (DecisionPolicy, Dynamics, FacilityResolver, HomeostasisDynamics,
                      StandardDecisionPolicy, StandardFacilityResolver)


class WorldRuntime:
    """分钟级离散事件引擎；没有墙上时钟依赖、LLM 或平台调用。"""

    def __init__(self, scenario: Scenario, *, dynamics: Dynamics | None = None,
                 decision_policy: DecisionPolicy | None = None,
                 facility_resolver: FacilityResolver | None = None):
        self.scenario = scenario
        self.dynamics = dynamics or HomeostasisDynamics()
        self.decision_policy = decision_policy or StandardDecisionPolicy()
        self.facility_resolver = facility_resolver or StandardFacilityResolver()
        self.minute = 0
        self.sequence = 0
        self.lives: dict[str, LifeState] = deepcopy(scenario.initial_lives)
        self.resources = {name: count for name, (count, _) in
                          scenario.world.initial_resources.items()}
        self.enabled = {fid: True for fid in scenario.world.facilities}
        self.queue: list[QueuedEvent] = []
        self.pending_log: list[dict[str, Any]] = []
        for raw in scenario.world.external_events:
            kind = raw["type"]
            self._schedule(int(raw["minute"]), kind,
                           {k: v for k, v in raw.items() if k not in {"type", "minute"}})
        for aid in sorted(self.lives):
            self._schedule(0, "decide", {"actor": aid})

    def _schedule(self, minute: int, kind: str, payload: dict[str, Any]) -> None:
        if minute < self.minute:
            raise ValueError("不能安排过去时间的事件")
        self.sequence += 1
        if kind == "decide":
            # World 可能提前唤醒同一个角色。较早的定时检查应自动失效，
            # 否则每次补给都可能累积出多个重复决策链。
            life = self.lives[payload["actor"]]
            life.decision_ticket += 1
            payload = {**payload, "ticket": life.decision_ticket}
        priority = (0 if kind in {"resource_add", "facility_disable", "facility_enable",
                                  "vitality_change"}
                    else 1 if kind in {"move_finished", "use_finished", "assist_finished"}
                    else 2 if kind == "decide" else -1)
        if priority == -1:
            raise ValueError(f"未知事件种类：{kind}")
        heapq.heappush(self.queue, QueuedEvent(minute, priority, self.sequence, kind, payload))

    def _log(self, kind: str, actor: str | None = None, **details: Any) -> None:
        self.pending_log.append({"minute": self.minute, "type": kind,
                                 "actor": actor, "details": details})

    def run_until(self, target_minute: int, *, max_events: int = 200_000) -> None:
        """一次推进到绝对世界分钟；中途停止/恢复应得到同一结果。"""
        if target_minute < self.minute:
            raise ValueError("世界时间不能倒退")
        count = 0
        while self.queue and self.queue[0].minute <= target_minute:
            event = heapq.heappop(self.queue)
            self.dynamics.advance(self.lives, self.scenario.personas, self.minute,
                                  event.minute, self.scenario.world.facilities)
            self.minute = event.minute
            self._dispatch(event)
            count += 1
            if count > max_events:
                raise RuntimeError("事件过多：可能存在同一分钟无限循环")
        self.dynamics.advance(self.lives, self.scenario.personas, self.minute,
                              target_minute, self.scenario.world.facilities)
        self.minute = target_minute

    def _dispatch(self, event: QueuedEvent) -> None:
        match event.kind:
            case "decide":
                life = self.lives[event.payload["actor"]]
                if event.payload["ticket"] == life.decision_ticket:
                    self._decide(event.payload["actor"])
            case "move_finished":
                self._complete_move(event.payload)
            case "use_finished":
                self._complete_use(event.payload)
            case "assist_finished":
                self._complete_assist(event.payload)
            case "resource_add":
                self._resource_add(event.payload)
            case "facility_disable" | "facility_enable":
                self._toggle_facility(event.kind, event.payload)
            case "vitality_change":
                self._change_vitality(event.payload)
            case _:
                raise ValueError(f"未知事件：{event.kind}")

    def _decide(self, aid: str) -> None:
        life = self.lives[aid]
        if life.busy:
            return
        observation = observe(self.scenario.world, self.lives,
                              self.scenario.personas, aid, self.minute, self.enabled)
        discovered = remember_observation(life, observation)
        if discovered:
            self._log("facility_discovered", aid, facilities=discovered, location=life.location)
        decision = self.decision_policy.choose(
            life, self.scenario.personas[aid], observation,
            self.scenario.world.connections)
        if life.goal != decision.goal:
            self._log("goal_changed", aid, before=life.goal, after=decision.goal)
            life.goal = decision.goal
        action = decision.action
        if action is None:
            self._schedule(self.minute + 30, "decide", {"actor": aid})
            return

        body = self.scenario.personas[aid].body
        if action.kind == "move":
            if life.vitality < body.min_move_vitality:
                self._defer_blocked(life, "low_vitality_move")
                return
            edge = self.scenario.world.connections[life.location].get(action.target)
            if edge is None or action.target not in life.known_locations:
                raise RuntimeError("规划器提交非法移动意图")
            duration = max(1, math.ceil(edge * self.scenario.personas[aid].move_multiplier))
            life.busy = {"kind": "move", "to": action.target, "finish": self.minute + duration}
            self._schedule(self.minute + duration, "move_finished", {"actor": aid, "to": action.target})
        elif action.kind == "use":
            if life.vitality < body.min_use_vitality:
                self._defer_blocked(life, "low_vitality_use")
                return
            facility = self.scenario.world.facilities[action.target]
            if facility.location != life.location:
                raise RuntimeError("规划器提交非本地设施使用意图")
            life.busy = {"kind": "use", "facility": facility.id,
                         "finish": self.minute + facility.duration}
            self._schedule(self.minute + facility.duration, "use_finished",
                           {"actor": aid, "facility": facility.id})
        elif action.kind == "assist":
            persona = self.scenario.personas[aid]
            if life.vitality < body.min_use_vitality:
                self._defer_blocked(life, "low_vitality_assist")
                return
            life.busy = {"kind": "assist", "target": action.target,
                         "finish": self.minute + persona.assist_duration}
            self._schedule(self.minute + persona.assist_duration, "assist_finished",
                           {"actor": aid, "target": action.target})
        else:
            raise ValueError(f"未知行为意图：{action.kind}")
        life.blocked_reason = None
        self._log("action_started", aid, action=action.kind, target=action.target,
                  goal=life.goal)

    def _defer_blocked(self, life: LifeState, reason: str) -> None:
        """状态没有改变时不重复记录同一障碍；等待世界事件或延迟复查。"""
        if life.blocked_reason != reason:
            self._log("action_blocked", life.id, reason=reason)
            life.blocked_reason = reason
        self._schedule(self.minute + 180, "decide", {"actor": life.id})

    def _complete_move(self, payload: dict[str, Any]) -> None:
        aid, dest = payload["actor"], payload["to"]
        life = self.lives[aid]
        if not life.busy or life.busy.get("kind") != "move" or life.busy.get("to") != dest:
            raise RuntimeError("移动完成事件与角色忙碌状态不符")
        if life.vitality < self.scenario.personas[aid].body.min_move_vitality:
            self._log("action_failed", aid, action="move", reason="low_vitality")
        elif dest not in self.scenario.world.connections[life.location]:
            self._log("action_failed", aid, action="move", reason="route_unavailable")
        else:
            life.location = dest
            self._log("actor_moved", aid, location=dest)
        life.busy = None
        self._schedule(self.minute, "decide", {"actor": aid})

    def _complete_use(self, payload: dict[str, Any]) -> None:
        aid, fid = payload["actor"], payload["facility"]
        life, facility = self.lives[aid], self.scenario.world.facilities[fid]
        if not life.busy or life.busy.get("kind") != "use" or life.busy.get("facility") != fid:
            raise RuntimeError("设施完成事件与角色忙碌状态不符")
        if life.vitality < self.scenario.personas[aid].body.min_use_vitality:
            ok, reason, effects = False, "low_vitality", {}
        elif not self.enabled[fid]:
            ok, reason, effects = False, "facility_disabled", {}
        else:
            ok, reason, effects = self.facility_resolver.resolve(
                life, facility, self.resources, self.minute)
        # 行动反馈进入 Life 的个人认知，而非修改世界定义。
        if fid in life.beliefs:
            life.beliefs[fid].last_result = "ok" if ok else reason
            life.beliefs[fid].last_used = self.minute
        if ok:
            life.failed_until.pop(fid, None)
            life.failure_counts.pop(fid, None)
            self._log("action_completed", aid, facility=fid, effects=effects)
        else:
            # 失败不抹除需求，只暂停针对同一设施的重复尝试。
            if reason in {"resource_unavailable", "facility_disabled"}:
                n = life.failure_counts.get(fid, 0) + 1
                life.failure_counts[fid] = n
                # 多次失败延长重试间隔，上限 24 小时；不遗忘该目标。
                life.failed_until[fid] = self.minute + min(1440, 180 * 2 ** min(n - 1, 3))
            self._log("action_failed", aid, action="use", facility=fid, reason=reason)
        life.busy = None
        self._schedule(self.minute, "decide", {"actor": aid})

    def _complete_assist(self, payload: dict[str, Any]) -> None:
        aid, target_id = payload["actor"], payload["target"]
        life, other = self.lives[aid], self.lives[target_id]
        if not life.busy or life.busy.get("kind") != "assist" or life.busy.get("target") != target_id:
            raise RuntimeError("协助完成事件与忙碌状态不符")
        if life.location != other.location:
            self._log("action_failed", aid, action="assist", reason="target_left")
        elif life.vitality < self.scenario.personas[aid].body.min_use_vitality:
            self._log("action_failed", aid, action="assist", reason="low_vitality")
        else:
            before = other.vitality
            other.vitality = min(100.0, round(before + self.scenario.personas[aid].assist_amount, 8))
            self._log("assistance_completed", aid, target=target_id,
                      restored=round(other.vitality - before, 8))
            if other.busy is None:
                self._schedule(self.minute, "decide", {"actor": target_id})
        life.busy = None
        self._schedule(self.minute, "decide", {"actor": aid})

    def _resource_add(self, payload: dict[str, Any]) -> None:
        name = payload["resource"]
        amount, cap = self.resources[name], self.scenario.world.initial_resources[name][1]
        self.resources[name] = min(cap, round(amount + float(payload["amount"]), 8))
        self._log("world_resource_added", resource=name,
                  amount=round(self.resources[name] - amount, 8))
        # 周期性资源生产：World 无需等待 Life/LLM 才能独立发生变化。
        period = payload.get("repeat_every_minutes")
        if period:
            self._schedule(self.minute + int(period), "resource_add", payload.copy())
        self._wake_local_actors({f.location for f in self.scenario.world.facilities.values()
                                 if f.resource == name})

    def _toggle_facility(self, kind: str, payload: dict[str, Any]) -> None:
        fid = payload["facility"]
        self.enabled[fid] = kind == "facility_enable"
        self._log("world_facility_changed", facility=fid, enabled=self.enabled[fid])
        self._wake_local_actors({self.scenario.world.facilities[fid].location})

    def _change_vitality(self, payload: dict[str, Any]) -> None:
        life = self.lives[payload["actor"]]
        old = life.vitality
        life.vitality = round(max(0.0, min(100.0, old + float(payload["amount"]))), 8)
        self._log("world_vitality_changed", life.id, amount=round(life.vitality - old, 8))
        if life.busy is None:
            self._schedule(self.minute, "decide", {"actor": life.id})

    def _wake_local_actors(self, locations: set[str]) -> None:
        for aid, life in sorted(self.lives.items()):
            if life.location in locations and life.busy is None:
                self._schedule(self.minute, "decide", {"actor": aid})

    def snapshot(self) -> dict[str, Any]:
        return {"minute": self.minute, "sequence": self.sequence,
                "resources": self.resources, "enabled": self.enabled,
                "lives": {aid: life.to_dict() for aid, life in sorted(self.lives.items())},
                "queue": [e.to_dict() for e in sorted(self.queue)]}

    @classmethod
    def from_snapshot(cls, scenario: Scenario, data: dict[str, Any], *,
                      dynamics: Dynamics | None = None,
                      decision_policy: DecisionPolicy | None = None,
                      facility_resolver: FacilityResolver | None = None) -> WorldRuntime:
        runtime = cls.__new__(cls)
        runtime.scenario = scenario
        runtime.dynamics = dynamics or HomeostasisDynamics()
        runtime.decision_policy = decision_policy or StandardDecisionPolicy()
        runtime.facility_resolver = facility_resolver or StandardFacilityResolver()
        runtime.minute = int(data["minute"])
        runtime.sequence = int(data["sequence"])
        runtime.resources = {name: float(value) for name, value in data["resources"].items()}
        runtime.enabled = {name: bool(value) for name, value in data["enabled"].items()}
        runtime.lives = {aid: LifeState.from_dict(value) for aid, value in data["lives"].items()}
        runtime.queue = [QueuedEvent.from_dict(event) for event in data["queue"]]
        heapq.heapify(runtime.queue)
        runtime.pending_log = []
        if set(runtime.lives) != set(scenario.personas):
            raise ValueError("存档中的角色与场景不匹配")
        return runtime
