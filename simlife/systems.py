"""可替换系统接口：跨 IP 的特殊生理/决策/资源规则在这里挂接。"""
from __future__ import annotations

from typing import Protocol

from .model import Facility, LifeState, Persona, WorldDefinition
from .policy import select_facility


class Dynamics(Protocol):
    def advance(self, lives: dict[str, LifeState],
                personas: dict[str, Persona], delta_minutes: int,
                target_minute: int) -> None: ...


class DecisionPolicy(Protocol):
    def choose(self, life: LifeState, persona: Persona,
               world: WorldDefinition, resources: dict[str, float]
               ) -> tuple[Facility, list[str], float] | None: ...


class LinearDriveDynamics:
    """默认规则：各需求缺口按照配置线性增长。仅供 MVP 测试。"""

    def advance(self, lives: dict[str, LifeState],
                personas: dict[str, Persona], delta_minutes: int,
                target_minute: int) -> None:
        for aid, life in lives.items():
            for name, spec in personas[aid].drives.items():
                anchor = life.anchors[name]
                # 只由锚点与绝对时间计算，避免每次推进时反复 round 累积误差。
                updated = (float(anchor["value"]) +
                           (target_minute - int(anchor["minute"])) / 60.0
                           * spec.rise_per_hour)
                life.drives[name] = min(100.0, max(0.0, round(updated, 8)))


class UtilityDecisionPolicy:
    """默认规则：使用当前需求和设施效用进行确定性选择。"""

    def choose(self, life: LifeState, persona: Persona,
               world: WorldDefinition, resources: dict[str, float]
               ) -> tuple[Facility, list[str], float] | None:
        return select_facility(life, persona, world, resources)


class FacilityResolver(Protocol):
    def resolve(self, life: LifeState, facility: Facility,
                resources: dict[str, float], minute: int
                ) -> tuple[bool, str, dict[str, float]]: ...


class StandardFacilityResolver:
    """默认行动结算：地点和资源满足时扣除资源、施加需求变化。"""

    def resolve(self, life: LifeState, facility: Facility,
                resources: dict[str, float], minute: int
                ) -> tuple[bool, str, dict[str, float]]:
        if life.location != facility.location:
            return False, "wrong_location", {}
        if facility.resource is not None and resources[facility.resource] < facility.units:
            return False, "resource_unavailable", {}
        if facility.resource is not None:
            resources[facility.resource] -= facility.units
        applied: dict[str, float] = {}
        for name, change in facility.effects.items():
            if name not in life.drives:
                continue
            old = life.drives[name]
            life.drives[name] = min(100.0, max(0.0, round(old + change, 8)))
            applied[name] = round(life.drives[name] - old, 8)
            life.anchors[name] = {"minute": minute, "value": life.drives[name]}
        return True, "ok", applied
