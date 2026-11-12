"""通用行动执行器（v0.6）。

每类行动只有两个职责：
  prepare: 检查前置条件，计算持续时间；不能改变世界状态。
  complete: 到期后二次验证，结算真实结果；世界状态只在此阶段改变。
新行动注册处理器即可，不必向 WorldRuntime.run_until 添加分支。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .model import Memory, clamp

if TYPE_CHECKING:
    from .engine import WorldRuntime


class ActionRejected(Exception):
    """预先拒绝不可执行的行动，而不是导致引擎崩溃。"""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ActionPlan:
    """执行计划，可声明多个参与者。由引擎统一占用和释放参与者。"""
    duration: int
    participants: tuple[str, ...] = ()


class ActionHandler(Protocol):
    def prepare(self, world: "WorldRuntime", actor: str, target: str) -> int | ActionPlan: ...
    def complete(self, world: "WorldRuntime", actor: str, target: str) -> None: ...


@dataclass
class Move:
    def prepare(self, world: "WorldRuntime", actor: str, target: str) -> int:
        life = world.lives[actor]
        body = world.scenario.personas[actor].body
        if life.vitality < body.min_move_vitality:
            raise ActionRejected("low_vitality_move")
        edge = world.scenario.world.connections[life.location].get(target)
        if edge is None or target not in life.known_locations:
            raise ActionRejected("route_unavailable")
        import math
        return max(1, math.ceil(edge * world.scenario.personas[actor].move_multiplier))

    def complete(self, world: "WorldRuntime", actor: str, target: str) -> None:
        life = world.lives[actor]
        body = world.scenario.personas[actor].body
        if life.vitality < body.min_move_vitality:
            world.log("action_failed", actor, action="move", reason="low_vitality")
        elif target not in world.scenario.world.connections[life.location]:
            world.log("action_failed", actor, action="move", reason="route_unavailable")
        else:
            life.location = target
            world.log("actor_moved", actor, location=target)


@dataclass
class UseFacility:
    """普通设施活动与练习共用世界资源结算，但练习额外增加技能。"""
    practice: bool = False

    def prepare(self, world: "WorldRuntime", actor: str, target: str) -> int:
        life = world.lives[actor]
        body = world.scenario.personas[actor].body
        if life.vitality < body.min_use_vitality:
            raise ActionRejected("low_vitality_use")
        facility = world.scenario.world.facilities.get(target)
        if facility is None or facility.location != life.location:
            raise ActionRejected("wrong_location")
        if self.practice and "practice" not in facility.tags:
            raise ActionRejected("not_practice_facility")
        # 不提前探知库存或设施是否停业。行动可以在到期结算时失败。
        return facility.duration

    def complete(self, world: "WorldRuntime", actor: str, target: str) -> None:
        life = world.lives[actor]
        facility = world.scenario.world.facilities[target]
        if life.vitality < world.scenario.personas[actor].body.min_use_vitality:
            ok, reason, effects = False, "low_vitality", {}
        elif not world.enabled[target]:
            ok, reason, effects = False, "facility_disabled", {}
        else:
            ok, reason, effects = world.facility_resolver.resolve(
                life, facility, world.resources, world.minute)
        if target in life.beliefs:
            life.beliefs[target].last_result = "ok" if ok else reason
            life.beliefs[target].last_used = world.minute
        if not ok:
            world.on_action_failure(actor, target, reason)
            return
        life.failed_until.pop(target, None)
        life.failure_counts.pop(target, None)
        if self.practice:
            skill = target.removeprefix("practice_")
            # 可解释的玩具技能模型：达到高等级时边际提升下降。
            before = life.skills.get(skill, 0.0)
            delta = max(0.08, 1.0 - before / 120)
            life.skills[skill] = clamp(before + delta)
            world.progress_skill_goal(actor, skill)
            life.last_creative = world.minute
            life.completed_goals += 1
            world.appraise(actor, +0.10, 0.15)
            world.remember(actor, "practiced", f"在 {life.location} 练习了 {skill}", 0.6)
            world.mark_commitment(actor, "practice", target)
            world.log("practice_completed", actor, skill=skill,
                      before=round(before, 4), after=life.skills[skill], facility=target)
        elif "practice" in facility.tags:
            # 旧需求模型选择创作设施，也能够留下对应成长记录。
            skill = target.removeprefix("practice_")
            before = life.skills.get(skill, 0.0)
            life.skills[skill] = clamp(before + max(0.08, 1.0 - before / 120))
            world.progress_skill_goal(actor, skill)
            life.last_creative = world.minute
            world.log("practice_completed", actor, skill=skill,
                      before=round(before, 4), after=life.skills[skill], facility=target)
        world.log("action_completed", actor, action="practice" if self.practice else "use",
                  facility=target, effects=effects)


@dataclass
class Assist:
    def prepare(self, world: "WorldRuntime", actor: str, target: str) -> int:
        life = world.lives[actor]
        persona = world.scenario.personas[actor]
        if life.vitality < persona.body.min_use_vitality:
            raise ActionRejected("low_vitality_assist")
        if target not in world.lives or world.lives[target].location != life.location:
            raise ActionRejected("target_not_here")
        if persona.assist_amount <= 0:
            raise ActionRejected("not_capable")
        return persona.assist_duration

    def complete(self, world: "WorldRuntime", actor: str, target: str) -> None:
        life, other = world.lives[actor], world.lives[target]
        if life.location != other.location:
            world.log("action_failed", actor, action="assist", reason="target_left")
        elif life.vitality < world.scenario.personas[actor].body.min_use_vitality:
            world.log("action_failed", actor, action="assist", reason="low_vitality")
        else:
            before = other.vitality
            other.vitality = clamp(other.vitality + world.scenario.personas[actor].assist_amount)
            world.log("assistance_completed", actor, target=target,
                      restored=round(other.vitality - before, 5))
            world.remember(actor, "helped", f"协助了 {target}", 0.7, [target])
            world.remember(target, "received_help", f"受到 {actor} 的帮助", 0.8, [actor])
            world.appraise(target, +0.12, 0.2)
            world.shift_relationship(target, actor, +0.07)
            if other.busy is None:
                world.wake(target)


@dataclass
class Socialize:
    def prepare(self, world: "WorldRuntime", actor: str, target: str) -> int:
        life = world.lives[actor]
        if target == actor or target not in world.lives:
            raise ActionRejected("invalid_person")
        other = world.lives[target]
        if life.location != other.location or other.busy is not None:
            raise ActionRejected("not_available")
        if life.vitality < world.scenario.personas[actor].body.min_use_vitality:
            raise ActionRejected("low_vitality_use")
        return ActionPlan(20, (target,))

    def complete(self, world: "WorldRuntime", actor: str, target: str) -> None:
        life, other = world.lives[actor], world.lives[target]
        if life.location != other.location:
            world.log("action_failed", actor, action="socialize", reason="target_left")
            return
        # 固定种子的可重放分歧。不是心理真实性模型；避免每次社交无条件增进好感。
        import hashlib
        key = f"{world.minute}:{actor}:{target}".encode()
        sample = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") / 2**32
        agreeable = world.scenario.personas[actor].traits.get("agreeableness", 0.5)
        success = sample < 0.70 + agreeable * 0.20
        delta = 0.035 if success else -0.025
        applied_deltas = {}
        for source, partner in ((actor, target), (target, actor)):
            applied_deltas[source] = world.shift_relationship(source, partner, delta)
            world.lives[source].last_social = world.minute
            world.appraise(source, 0.06 if success else -0.09, 0.15)
            world.remember(source, "conversation", f"与 {partner} 交流，结果：{'愉快' if success else '不愉快'}",
                           0.65, [partner])
            world.mark_commitment(source, "socialize", partner)
        world.lives[actor].completed_goals += 1
        world.log("social_interaction", actor, target=target,
                  outcome="positive" if success else "negative",
                  nominal_relation_delta=delta, applied_deltas=applied_deltas)
        if other.busy is None:
            world.wake(target)


class ActionRegistry:
    """开放封闭原则：外部行为可使用 register() 增加，无需改引擎。"""
    def __init__(self):
        self._handlers: dict[str, ActionHandler] = {
            "move": Move(), "use": UseFacility(), "assist": Assist(),
            "practice": UseFacility(practice=True), "socialize": Socialize(),
        }

    def register(self, name: str, handler: ActionHandler) -> None:
        if not name or name in self._handlers:
            raise ValueError(f"重复或非法行动名：{name}")
        self._handlers[name] = handler

    def get(self, name: str) -> ActionHandler:
        if name not in self._handlers:
            raise ActionRejected("unknown_action")
        return self._handlers[name]
