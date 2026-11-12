"""WorldRuntime：世界事实的唯一写入入口。事件队列驱动，模型只允许提供行动意图。"""
from __future__ import annotations
import heapq
from copy import deepcopy
from typing import Any

from .actions import ActionPlan, ActionRejected, ActionRegistry
from .model import LifeState, Memory, QueuedEvent, Scenario, clamp
from .perception import observe, remember_observation
from .systems import (DecisionPolicy, Dynamics, FacilityResolver, HomeostasisDynamics,
                      StandardFacilityResolver)
from .policy import StandardDecisionPolicy


class WorldRuntime:
    def __init__(self, scenario: Scenario, *, dynamics: Dynamics | None = None,
                 decision_policy: DecisionPolicy | None = None,
                 facility_resolver: FacilityResolver | None = None,
                 actions: ActionRegistry | None = None):
        self.scenario = scenario
        self.dynamics = dynamics or HomeostasisDynamics()
        self.decision_policy = decision_policy or StandardDecisionPolicy()
        self.facility_resolver = facility_resolver or StandardFacilityResolver()
        self.actions = actions or ActionRegistry()
        self.minute = 0
        self.sequence = 0
        self.cognition_usage: dict[str, int] = {}
        self.lives: dict[str, LifeState] = deepcopy(scenario.initial_lives)
        self.resources = {k: amount for k, (amount, _) in scenario.world.initial_resources.items()}
        self.enabled = {k: True for k in scenario.world.facilities}
        self.queue: list[QueuedEvent] = []
        self.pending_log: list[dict[str, Any]] = []
        for item in scenario.world.external_events:
            self.schedule(int(item["minute"]), item["type"],
                          {k: v for k, v in item.items() if k not in ("type", "minute")})
        for actor in sorted(self.lives):
            self.wake(actor)

    def schedule(self, minute: int, kind: str, payload: dict[str, Any]) -> None:
        if minute < self.minute:
            raise ValueError("不能安排发生在过去的事件")
        self.sequence += 1
        if kind == "decide":
            life = self.lives[payload["actor"]]
            life.decision_ticket += 1
            payload = {**payload, "ticket": life.decision_ticket}
        priority = (0 if kind in {"resource_add", "facility_disable", "facility_enable",
                                  "vitality_change", "message"}
                    else 1 if kind == "action_complete"
                    else 2 if kind == "decide" else -1)
        if priority == -1:
            raise ValueError(f"未知的事件类型：{kind}")
        heapq.heappush(self.queue, QueuedEvent(minute, priority, self.sequence, kind, payload))

    def wake(self, actor: str, minute: int | None = None) -> None:
        self.schedule(self.minute if minute is None else minute, "decide", {"actor": actor})

    def log(self, kind: str, actor: str | None = None, **details: Any) -> None:
        self.pending_log.append({"minute": self.minute, "type": kind,
                                 "actor": actor, "details": details})

    def remember(self, actor: str, kind: str, text: str, salience: float = 0.5,
                 actors: list[str] | None = None) -> None:
        self.lives[actor].add_memory(Memory(self.minute, kind, text, actors or [], salience))

    def appraise(self, actor: str, valence: float, arousal: float) -> None:
        emotion = self.lives[actor].emotion
        emotion.valence = clamp(emotion.valence + valence, -1, 1)
        emotion.arousal = clamp(emotion.arousal + arousal, 0, 1)

    def shift_relationship(self, actor: str, target: str, delta: float) -> float:
        """饱和度抑制：越接近极端，单次事件的有效变化越小。

        避免 20~30 次好感事件就把信任值永久推到最大。
        返回实际信任变化，日志不混淆原始冲击与结算结果。
        """
        from .model import Relationship
        rel = self.lives[actor].relationships.setdefault(target, Relationship())
        old = rel.trust
        rel.trust = clamp(old + (delta * (1 - old) if delta >= 0 else delta * old), 0, 1)
        rel.closeness = clamp(rel.closeness + (
            delta / 2 * (1 - rel.closeness) if delta >= 0 else delta / 2 * rel.closeness), 0, 1)
        rel.interactions += 1
        rel.last_interaction = self.minute
        return round(rel.trust - old, 8)

    def progress_skill_goal(self, actor: str, skill: str) -> None:
        """长期目标只能根据已经结算的真实技能变化推进。"""
        life = self.lives[actor]
        goal = life.long_goals.get(skill)
        if goal is None or goal.status != "active":
            return
        goal.progress = life.skills[skill]
        if goal.progress >= goal.target:
            goal.status = "completed"
            goal.completed_at = self.minute
            self.log("long_goal_completed", actor, skill=skill, target=goal.target)
            self.remember(actor, "achievement", f"达成长期目标：{skill} 达到 {goal.target}", 0.95)
            self.appraise(actor, 0.2, 0.3)

    def mark_commitment(self, actor: str, kind: str, target: str) -> None:
        for item in self.lives[actor].commitments:
            if item.get("status", "pending") == "pending" and item["kind"] == kind and item["target"] == target and int(item["minute"]) <= self.minute:
                item["status"] = "completed"
                self.log("commitment_completed", actor, commitment_kind=kind, target=target)
                return

    def run_until(self, target_minute: int, *, max_events: int = 500_000) -> None:
        """将模拟推进至绝对分钟；不依赖当前系统时间、外部网络或后台线程。"""
        if target_minute < self.minute:
            raise ValueError("世界时间不能倒流")
        count = 0
        while self.queue and self.queue[0].minute <= target_minute:
            event = heapq.heappop(self.queue)
            self.dynamics.advance(self.lives, self.scenario.personas,
                                  self.minute, event.minute, self.scenario.world.facilities)
            self.minute = event.minute
            self._dispatch(event)
            count += 1
            if count > max_events:
                raise RuntimeError("事件过多，疑似无限循环")
        self.dynamics.advance(self.lives, self.scenario.personas,
                              self.minute, target_minute, self.scenario.world.facilities)
        self.minute = target_minute

    def _dispatch(self, event: QueuedEvent) -> None:
        kind, payload = event.kind, event.payload
        if kind == "decide":
            life = self.lives[payload["actor"]]
            if payload["ticket"] == life.decision_ticket:
                self._decide(payload["actor"])
        elif kind == "action_complete":
            self._finish_action(payload)
        elif kind == "resource_add":
            self._resource_add(payload)
        elif kind in ("facility_disable", "facility_enable"):
            fid = payload["facility"]
            self.enabled[fid] = kind == "facility_enable"
            self.log("world_facility_changed", facility=fid, enabled=self.enabled[fid])
            self._wake_near({self.scenario.world.facilities[fid].location})
        elif kind == "vitality_change":
            life = self.lives[payload["actor"]]
            before = life.vitality
            life.vitality = clamp(life.vitality + float(payload["amount"]))
            self.log("world_vitality_changed", life.id,
                     amount=round(life.vitality - before, 5))
            if life.busy is None:
                self.wake(life.id)
            elif life.vitality < self.scenario.personas[life.id].body.min_use_vitality:
                self.interrupt(life.id, reason="low_vitality")
        elif kind == "message":
            actor, author, txt = payload["actor"], str(payload.get("from", "system")), str(payload["text"])
            self.remember(actor, "message", f"{author} 发来消息：{txt}", 0.8, [author])
            self.lives[actor].facts[f"message:{self.minute}:{len(self.lives[actor].facts)}"] = {
                "text": txt, "from": author, "seen": self.minute, "source": "external_message"}
            self.log("message_received", actor, author=author, text=txt)
            if self.lives[actor].busy is None:
                self.wake(actor)
            elif payload.get("urgent"):
                self.interrupt(actor, "urgent_message")
        else:
            raise ValueError(f"未处理的事件：{kind}")

    def _decide(self, actor: str) -> None:
        life = self.lives[actor]
        if life.busy:
            return
        observation = observe(self.scenario.world, self.lives,
                              self.scenario.personas, actor, self.minute, self.enabled)
        discovered = remember_observation(life, observation)
        # 只能学到当前位置向外的道路；远处地图连接不能直接泄露给决策器。
        life.known_edges[life.location] = {k: v for k, v in self.scenario.world.connections[life.location].items()
                                           if k in life.known_locations}
        for fid in discovered:
            life.facts["facility:" + fid] = {"location": life.location,
                                              "seen": self.minute, "source": "observation"}
        if discovered:
            self.log("facility_discovered", actor, facilities=discovered, location=life.location)
        for task in life.commitments:
            if task.get("status", "pending") == "pending" and self.minute > int(task["minute"]) + 180:
                task["status"] = "missed"
                self.remember(actor, "commitment_missed", f"未能完成约定：{task['kind']} {task['target']}", 0.7)
                self.log("commitment_missed", actor, commitment_kind=task["kind"], target=task["target"])
        decision = self.decision_policy.choose(life, self.scenario.personas[actor], observation,
                                               life.known_edges)
        if life.goal != decision.goal:
            self.log("goal_changed", actor, before=life.goal, after=decision.goal)
            life.goal, life.goal_since = decision.goal, self.minute
        if decision.action is None:
            self.wake(actor, self.minute + 30)
            return
        self._start_action(actor, decision.action.kind, decision.action.target)

    def _start_action(self, actor: str, kind: str, target: str) -> None:
        life = self.lives[actor]
        if life.busy:
            raise ValueError("角色已经在进行行动")
        try:
            handler = self.actions.get(kind)
            plan = handler.prepare(self, actor, target)
            duration = plan.duration if isinstance(plan, ActionPlan) else plan
            participants = plan.participants if isinstance(plan, ActionPlan) else ()
            if duration < 1:
                raise ActionRejected("invalid_duration")
            if (len(set(participants)) != len(participants) or actor in participants
                    or any(a not in self.lives or self.lives[a].busy is not None
                           for a in participants)):
                raise ActionRejected("participant_unavailable")
        except ActionRejected as ex:
            if life.blocked_reason != ex.reason:
                self.log("action_blocked", actor, action=kind, reason=ex.reason)
                life.blocked_reason = ex.reason
            self.wake(actor, self.minute + 180)
            return
        life.blocked_reason = None
        life.action_ticket += 1
        life.busy = {"kind": kind, "target": target,
                     "finish": self.minute + duration, "ticket": life.action_ticket,
                     "participants": list(participants)}
        # 多人行动统一占用参与者，避免对话中途一人突然跑去做别的事。
        for peer in participants:
            self.lives[peer].action_ticket += 1
            self.lives[peer].busy = {
                "kind": "participate", "target": actor,
                "finish": self.minute + duration,
                "ticket": self.lives[peer].action_ticket}
        self.schedule(self.minute + duration, "action_complete", {
            "actor": actor, "kind": kind, "target": target, "ticket": life.action_ticket})
        self.log("action_started", actor, action=kind, target=target, goal=life.goal, participants=list(participants))

    def _finish_action(self, payload: dict[str, Any]) -> None:
        actor = payload["actor"]
        life = self.lives[actor]
        if life.busy is None or life.busy.get("ticket") != payload["ticket"]:
            return  # 被中断的过期完成事件不产生副作用。
        if life.busy["kind"] != payload["kind"] or life.busy["target"] != payload["target"]:
            raise RuntimeError("动作结束事件与实际动作不匹配")
        handler = self.actions.get(payload["kind"])
        # 清除 busy 在结算之后；确保动作与结算时间形成原子逻辑段。
        participants = list(life.busy.get("participants", []))
        try:
            handler.complete(self, actor, payload["target"])
        finally:
            life.busy = None
            for peer in participants:
                other = self.lives[peer]
                if other.busy and other.busy.get("kind") == "participate" and other.busy.get("target") == actor:
                    other.busy = None
                    self.wake(peer)
        self.wake(actor)

    def interrupt(self, actor: str, reason: str) -> bool:
        """事件可打断活动；旧完成事件仍在队列中，但 token 校验会将其无效化。"""
        life = self.lives[actor]
        if life.busy is None:
            return False
        # 被占用的参与者终止整项多人行动，而不是只解除自己的状态。
        if life.busy.get("kind") == "participate":
            return self.interrupt(life.busy["target"], reason)
        old = life.busy.copy()
        life.action_ticket += 1
        life.busy = None
        for peer in old.get("participants", []):
            other = self.lives[peer]
            if other.busy and other.busy.get("kind") == "participate" and other.busy.get("target") == actor:
                other.busy = None
                other.action_ticket += 1
                self.wake(peer)
        self.log("action_interrupted", actor, action=old["kind"], target=old["target"], reason=reason)
        self.remember(actor, "interruption", f"{old['kind']} 被 {reason} 打断", 0.55)
        self.wake(actor)
        return True

    def on_action_failure(self, actor: str, target: str, reason: str) -> None:
        life = self.lives[actor]
        if reason in ("resource_unavailable", "facility_disabled"):
            n = life.failure_counts.get(target, 0) + 1
            life.failure_counts[target] = n
            life.failed_until[target] = self.minute + min(1440, 180 * 2 ** min(n - 1, 3))
        self.log("action_failed", actor, action="use", facility=target, reason=reason)
        if reason != "low_vitality":
            self.appraise(actor, -0.06, 0.12)
            self.remember(actor, "failure", f"使用 {target} 失败：{reason}", 0.7)

    def receive_message(self, actor: str, author: str, text: str) -> None:
        """由外部平台输入消息。消息是观察，不代表其中宣称的事实已经成立。"""
        self.remember(actor, "message", f"{author} 发来消息：{text}", 0.8, [author])
        self.log("message_received", actor, author=author, text=text)

    def submit_intent(self, actor: str, kind: str, target: str) -> tuple[bool, str]:
        """外部认知只能通过这个受控入口提出行动，不能直接改世界。"""
        if self.lives[actor].busy:
            self.log("cognition_action_denied", actor, reason="actor_busy")
            return False, "actor_busy"
        try:
            self.actions.get(kind).prepare(self, actor, target)
        except ActionRejected as error:
            self.log("cognition_action_denied", actor, reason=error.reason)
            return False, error.reason
        self._start_action(actor, kind, target)
        return True, "accepted"

    def _resource_add(self, payload: dict[str, Any]) -> None:
        name = payload["resource"]
        before, capacity = self.resources[name], self.scenario.world.initial_resources[name][1]
        self.resources[name] = min(capacity, round(before + float(payload["amount"]), 8))
        self.log("world_resource_added", resource=name,
                 amount=round(self.resources[name] - before, 8))
        period = payload.get("repeat_every_minutes")
        if period:
            self.schedule(self.minute + int(period), "resource_add", dict(payload))
        self._wake_near({f.location for f in self.scenario.world.facilities.values() if f.resource == name})

    def _wake_near(self, locations: set[str]) -> None:
        for actor, life in sorted(self.lives.items()):
            if life.location in locations and life.busy is None:
                self.wake(actor)

    def snapshot(self) -> dict[str, Any]:
        return {"minute": self.minute, "sequence": self.sequence,
                "cognition_usage": self.cognition_usage.copy(),
                "resources": self.resources, "enabled": self.enabled,
                "lives": {k: life.to_dict() for k, life in sorted(self.lives.items())},
                "queue": [item.to_dict() for item in sorted(self.queue)]}

    @classmethod
    def from_snapshot(cls, scenario: Scenario, data: dict[str, Any], *,
                      dynamics: Dynamics | None = None,
                      decision_policy: DecisionPolicy | None = None,
                      facility_resolver: FacilityResolver | None = None,
                      actions: ActionRegistry | None = None) -> "WorldRuntime":
        runtime = cls.__new__(cls)
        runtime.scenario = scenario
        runtime.dynamics = dynamics or HomeostasisDynamics()
        runtime.decision_policy = decision_policy or StandardDecisionPolicy()
        runtime.facility_resolver = facility_resolver or StandardFacilityResolver()
        runtime.actions = actions or ActionRegistry()
        runtime.minute = int(data["minute"])
        runtime.sequence = int(data["sequence"])
        runtime.cognition_usage = {k: int(v) for k, v in data.get("cognition_usage", {}).items()}
        runtime.resources = {k: float(v) for k, v in data["resources"].items()}
        runtime.enabled = {k: bool(v) for k, v in data["enabled"].items()}
        runtime.lives = {k: LifeState.from_dict(v) for k, v in data["lives"].items()}
        runtime.queue = [QueuedEvent.from_dict(x) for x in data["queue"]]
        heapq.heapify(runtime.queue)
        runtime.pending_log = []
        if set(runtime.lives) != set(scenario.personas):
            raise ValueError("存档人物与场景不一致")
        return runtime
