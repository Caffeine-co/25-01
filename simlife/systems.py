"""连续动态与基本设施规则。只改变可审计的数值，不产生叙事事实。"""
from __future__ import annotations
from typing import Protocol
from .model import Decision, Facility, LifeState, Observation, Persona, clamp

class Dynamics(Protocol):
    def advance(self, lives: dict[str, LifeState], personas: dict[str, Persona],
                start_minute: int, target_minute: int,
                facilities: dict[str, Facility]) -> None: ...

class HomeostasisDynamics:
    def advance(self, lives: dict[str, LifeState], personas: dict[str, Persona],
                start_minute: int, target_minute: int,
                facilities: dict[str, Facility]) -> None:
        # 每分钟固定积分：同一模拟在随机暂停/恢复后得到一致结果。
        for minute in range(start_minute + 1, target_minute + 1):
            for aid in sorted(lives):
                life, persona = lives[aid], personas[aid]
                for name, spec in persona.drives.items():
                    anchor = life.anchors[name]
                    raw = float(anchor["value"]) + (minute - int(anchor["minute"])) / 60 * spec.rise_per_hour
                    life.drives[name] = clamp(raw)
                body = persona.body
                busy = life.busy
                if busy and busy["kind"] == "move":
                    rate = -body.move_cost_per_hour
                elif busy and busy["kind"] in ("use", "practice", "socialize", "assist", "participate"):
                    if busy["kind"] == "use" and facilities[busy["target"]].restorative:
                        rate = body.rest_recovery_per_hour
                    else:
                        rate = -body.use_cost_per_hour
                else:
                    rate = body.idle_recovery_per_hour
                for need, (threshold, penalty) in body.critical_drives.items():
                    if life.drives[need] > threshold:
                        rate -= penalty
                life.vitality = clamp(life.vitality + rate / 60)
                # 心情随时间趋于中性，不能把上次心情重新当作事件重复评价。
                life.emotion.valence = round(life.emotion.valence * 0.9992, 8)
                life.emotion.arousal = round(life.emotion.arousal * 0.9988, 8)

class DecisionPolicy(Protocol):
    def choose(self, life: LifeState, persona: Persona, observation: Observation,
               known_map: dict[str, dict[str, int]]) -> Decision: ...

class FacilityResolver(Protocol):
    def resolve(self, life: LifeState, facility: Facility,
                resources: dict[str, float], minute: int) -> tuple[bool, str, dict[str, float]]: ...

class StandardFacilityResolver:
    def resolve(self, life: LifeState, facility: Facility,
                resources: dict[str, float], minute: int) -> tuple[bool, str, dict[str, float]]:
        if life.location != facility.location:
            return False, "wrong_location", {}
        if facility.resource is not None and resources[facility.resource] < facility.units:
            return False, "resource_unavailable", {}
        if facility.resource is not None:
            resources[facility.resource] = round(resources[facility.resource] - facility.units, 8)
        effects = {}
        for key, delta in facility.effects.items():
            if key in life.drives:
                old = life.drives[key]
                life.set_drive(key, old + delta, minute)
                effects[key] = round(life.drives[key] - old, 8)
        return True, "ok", effects
