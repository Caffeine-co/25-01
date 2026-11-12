"""时间演化与行动结算；世界可通过替换接口实现不同生命规律。"""
from __future__ import annotations

from typing import Protocol

from .model import Decision, Facility, LifeState, Observation, Persona


class Dynamics(Protocol):
    def advance(self, lives: dict[str, LifeState],
                personas: dict[str, Persona], start_minute: int,
                target_minute: int, facilities: dict[str, Facility]) -> None: ...


class HomeostasisDynamics:
    """小型可复现模型：需求按锚点变化，行动能力按分钟受负荷/风险影响。"""

    def advance(self, lives: dict[str, LifeState], personas: dict[str, Persona],
                start_minute: int, target_minute: int,
                facilities: dict[str, Facility]) -> None:
        # 固定每分钟积分，确保单次运行与任意切分/存档续跑具有相同结果。
        for minute in range(start_minute + 1, target_minute + 1):
            for aid in sorted(lives):
                life, persona = lives[aid], personas[aid]
                for name, spec in persona.drives.items():
                    anchor = life.anchors[name]
                    raw = float(anchor["value"]) + (minute - int(anchor["minute"])) / 60 * spec.rise_per_hour
                    life.drives[name] = round(min(100.0, max(0.0, raw)), 8)

                body = persona.body
                if life.busy and life.busy["kind"] == "move":
                    rate = -body.move_cost_per_hour
                elif life.busy and life.busy["kind"] == "use":
                    facility = facilities[life.busy["facility"]]
                    rate = (body.rest_recovery_per_hour if facility.restorative
                            else -body.use_cost_per_hour)
                elif life.busy and life.busy["kind"] == "assist":
                    rate = -body.use_cost_per_hour
                else:
                    rate = body.idle_recovery_per_hour

                # 严重且持续的未满足需求可造成行动能力下降。
                for drive, (threshold, damage) in body.critical_drives.items():
                    if life.drives[drive] > threshold:
                        rate -= damage
                life.vitality = round(min(100.0, max(0.0, life.vitality + rate / 60)), 8)


class DecisionPolicy(Protocol):
    def choose(self, life: LifeState, persona: Persona,
               observation: Observation, known_map: dict[str, dict[str, int]]) -> Decision: ...


class StandardDecisionPolicy:
    """默认通用决策器。IP 特定的决策规则可以替换这个类。"""
    def choose(self, life: LifeState, persona: Persona,
               observation: Observation, known_map: dict[str, dict[str, int]]) -> Decision:
        from .policy import choose_action
        return choose_action(life, persona, observation, known_map)


class FacilityResolver(Protocol):
    def resolve(self, life: LifeState, facility: Facility,
                resources: dict[str, float], minute: int) -> tuple[bool, str, dict[str, float]]: ...


class StandardFacilityResolver:
    """只允许确实在设施所在地且资源充足的角色获得效果。"""
    def resolve(self, life: LifeState, facility: Facility,
                resources: dict[str, float], minute: int) -> tuple[bool, str, dict[str, float]]:
        if life.location != facility.location:
            return False, "wrong_location", {}
        if facility.resource is not None and resources[facility.resource] < facility.units:
            return False, "resource_unavailable", {}
        if facility.resource is not None:
            resources[facility.resource] = round(resources[facility.resource] - facility.units, 8)
        effects: dict[str, float] = {}
        for name, effect in facility.effects.items():
            if name not in life.drives:
                continue
            old = life.drives[name]
            life.set_drive(name, old + effect, minute)
            effects[name] = round(life.drives[name] - old, 8)
        return True, "ok", effects
