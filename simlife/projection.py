"""供聊天适配器/LLM 阅读的只读视图：绝不暴露全局库存与远处人物私有状态。"""
from __future__ import annotations
from .engine import WorldRuntime
from .perception import observe


def actor_view(world: WorldRuntime, actor: str) -> dict:
    life = world.lives[actor]
    seen = observe(world.scenario.world, world.lives, world.scenario.personas,
                   actor, world.minute, world.enabled)
    return {
        "minute": world.minute,
        "id": actor,
        "name": world.scenario.personas[actor].name,
        "location": life.location,
        "vitality": life.vitality,
        "drives": life.drives.copy(),
        "goal": life.goal,
        "busy": life.busy.copy() if life.busy else None,
        "visible_facilities": [f.id for f in seen.facilities],
        "known_facilities": {fid: {"location": b.location, "last_result": b.last_result,
                                   "last_seen": b.last_seen} for fid, b in life.beliefs.items()},
        "visible_actors": [other.id for other in seen.nearby_actors],
        "skills": life.skills.copy(),
        "long_goals": {k: {"target": v.target, "progress": v.progress, "status": v.status}
                       for k, v in life.long_goals.items()},
        "emotion": {"valence": life.emotion.valence, "arousal": life.emotion.arousal},
        "relationships": {k: {"trust": v.trust, "closeness": v.closeness}
                          for k, v in life.relationships.items()},
        "memories": [{"minute": m.minute, "kind": m.kind, "text": m.text}
                     for m in life.memories[-8:]],
    }
