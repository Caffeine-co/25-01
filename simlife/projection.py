"""只读输出：为调试、后续 NoneBot/LLM 提供状态视图，不提供世界写权限。"""
from __future__ import annotations

from .engine import WorldRuntime
from .perception import observe


def actor_view(runtime: WorldRuntime, actor_id: str) -> dict:
    """返回角色可见状态；不包含全世界的资源库存或远处实体信息。"""
    life = runtime.lives[actor_id]
    seen = observe(runtime.scenario.world, runtime.lives,
                   runtime.scenario.personas, actor_id,
                   runtime.minute, runtime.enabled)
    return {
        "minute": runtime.minute,
        "actor": actor_id,
        "location": life.location,
        "vitality": life.vitality,
        "drives": life.drives.copy(),
        "goal": life.goal,
        "busy": life.busy.copy() if life.busy else None,
        "visible_facilities": [f.id for f in seen.facilities],
        "known_facilities": {
            fid: {"location": belief.location,
                  "last_result": belief.last_result,
                  "last_seen": belief.last_seen}
            for fid, belief in life.beliefs.items()
        },
        "visible_actors": [peer.id for peer in seen.nearby_actors],
    }
