"""无 LLM 的最小决策层：需求评分 + 设施路径规划。"""
from __future__ import annotations

import heapq

from .model import Facility, LifeState, Persona, WorldDefinition


def find_route(
    connections: dict[str, dict[str, int]], origin: str, target: str,
    known: set[str]
) -> tuple[int, list[str]] | None:
    """Dijkstra：返回全程花费（分钟）与地点路径。只允许经过已知地点。"""
    if origin == target:
        return (0, [origin])
    queue: list[tuple[int, str, list[str]]] = [(0, origin, [origin])]
    best: dict[str, int] = {origin: 0}
    while queue:
        distance, loc, path = heapq.heappop(queue)
        if distance != best[loc]:
            continue
        if loc == target:
            return (distance, path)
        for dest, minutes in connections[loc].items():
            nxt = distance + minutes
            if dest in known and nxt < best.get(dest, 10**18):
                best[dest] = nxt
                heapq.heappush(queue, (nxt, dest, [*path, dest]))
    return None


def select_facility(
    life: LifeState, persona: Persona, world: WorldDefinition,
    resources: dict[str, float]
) -> tuple[Facility, list[str], float] | None:
    """按当前驱动力选择可达设施。分数是工程启发式，不是心理学定律。"""
    options: list[tuple[float, str, Facility, list[str]]] = []
    for facility in world.facilities.values():
        if facility.resource and resources[facility.resource] < facility.units:
            continue
        route = find_route(world.connections, life.location,
                           facility.location, set(life.known_locations))
        if route is None:
            continue
        travel_minutes, path = route
        benefit = 0.0
        for name, effect in facility.effects.items():
            if effect >= 0 or name not in persona.drives:
                continue
            spec = persona.drives[name]
            level = life.drives[name]
            if level <= spec.threshold:
                continue
            # 越紧迫的需求优先，但只有真正可缓解时才产生收益。
            urgency = (level - spec.threshold) / (100 - spec.threshold)
            relief = min(level, -effect) / 100.0
            benefit += spec.priority * urgency * relief
        # 偏向近期可完成的活动；代价不应压倒急迫的生存需求。
        cost = 0.004 * (travel_minutes * persona.move_multiplier + facility.duration) / 10.0
        score = benefit - cost
        if score > 0:
            options.append((score, facility.id, facility, path))
    if not options:
        return None
    # 分数相同按 ID 排序，保障重放结果完全一致。
    options.sort(key=lambda x: (-x[0], x[1]))
    score, _, facility, path = options[0]
    return facility, path, score
