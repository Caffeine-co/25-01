"""世界事实 -> 局部可见信息 -> 个人认知，避免全知视角。"""
from __future__ import annotations
from .model import FacilityBelief, LifeState, NearbyActor, Observation, Persona, WorldDefinition


def observe(world: WorldDefinition, lives: dict[str, LifeState],
            personas: dict[str, Persona], actor: str, minute: int,
            enabled: dict[str, bool]) -> Observation:
    life = lives[actor]
    visible = tuple(f for f in world.facilities.values()
                    if f.location == life.location and enabled[f.id])
    peers = tuple(NearbyActor(other.id,
                             other.vitality < personas[actor].assist_threshold, other.busy is None)
                  for aid, other in sorted(lives.items())
                  if aid != actor and other.location == life.location)
    return Observation(minute, life.location, visible, peers)


def remember_observation(life: LifeState, obs: Observation) -> list[str]:
    if life.location not in life.visited:
        life.visited.append(life.location)
    discovered = []
    for f in obs.facilities:
        old = life.beliefs.get(f.id)
        if old is None:
            discovered.append(f.id)
        life.beliefs[f.id] = FacilityBelief(
            f.location, f.duration, f.effects.copy(), obs.minute,
            old.last_result if old else None, old.last_used if old else None,
            f.tags)
    return discovered
