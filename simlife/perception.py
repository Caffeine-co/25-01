"""Perception：从客观 World 生成局部观察，并更新 Life 的事实认知。"""
from __future__ import annotations

from .model import FacilityBelief, LifeState, NearbyActor, Observation, Persona, WorldDefinition


def observe(world: WorldDefinition, lives: dict[str, LifeState],
            personas: dict[str, Persona], actor: str, minute: int,
            enabled: dict[str, bool]) -> Observation:
    life = lives[actor]
    visible = tuple(f for f in world.facilities.values()
                    if f.location == life.location and enabled[f.id])
    peers = tuple(NearbyActor(other.id,
                             other.vitality < personas[actor].assist_threshold)
                  for aid, other in sorted(lives.items())
                  if aid != actor and other.location == life.location)
    return Observation(minute, life.location, visible, peers)


def remember_observation(life: LifeState, observation: Observation) -> list[str]:
    """观察当前地点的设施，不伪造远处库存或资源状态。"""
    if life.location not in life.visited:
        life.visited.append(life.location)
    discovered: list[str] = []
    for facility in observation.facilities:
        if facility.id not in life.beliefs:
            discovered.append(facility.id)
        prior = life.beliefs.get(facility.id)
        life.beliefs[facility.id] = FacilityBelief(
            location=facility.location, duration=facility.duration,
            effects=facility.effects.copy(), last_seen=observation.minute,
            last_result=prior.last_result if prior else None,
            last_used=prior.last_used if prior else None,
        )
    return discovered
