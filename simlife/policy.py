"""Life 的最小规划器：需求 → 持续目标 → 已知设施 / 探索 → 行动意图。"""
from __future__ import annotations

import heapq

from .model import ActionIntent, Decision, LifeState, Observation, Persona


def find_route(connections: dict[str, dict[str, int]], origin: str,
               target: str, known: set[str]) -> tuple[int, list[str]] | None:
    """Dijkstra；只允许经过角色知道的地点。"""
    if origin == target:
        return 0, [origin]
    queue: list[tuple[int, str, list[str]]] = [(0, origin, [origin])]
    best: dict[str, int] = {origin: 0}
    while queue:
        distance, loc, path = heapq.heappop(queue)
        if distance != best[loc]:
            continue
        if loc == target:
            return distance, path
        for dest, cost in connections[loc].items():
            nd = distance + cost
            if dest in known and nd < best.get(dest, 10**18):
                best[dest] = nd
                heapq.heappush(queue, (nd, dest, [*path, dest]))
    return None


def choose_action(life: LifeState, persona: Persona, observation: Observation,
                  known_map: dict[str, dict[str, int]]) -> Decision:
    """只读 Life 的认知与已知地图。此函数拿不到世界资源库存。"""
    # 同地点的 NPC 可以用一个简单行动帮助身体行动能力严重不足的实体。
    if persona.assist_amount > 0 and life.vitality >= persona.body.min_use_vitality:
        for peer in observation.nearby_actors:
            if peer.needs_assistance:
                return Decision(life.goal, ActionIntent("assist", peer.id))

    # 优先完成尚未满足的旧目标；只有明显更紧迫的新需求才允许打断。
    candidates: list[tuple[float, str]] = []
    for name, spec in persona.drives.items():
        value = life.drives[name]
        if value > spec.threshold:
            urgency = (value - spec.threshold) / (100 - spec.threshold)
            candidates.append((urgency * spec.priority, name))
    candidates.sort(key=lambda x: (-x[0], x[1]))
    if not candidates:
        return Decision(None, None)

    best_score, best_drive = candidates[0]
    goal = life.goal
    if goal not in persona.drives or life.drives.get(goal, 0) <= persona.drives[goal].threshold:
        goal = best_drive
    else:
        old_score = next((s for s, name in candidates if name == goal), 0.0)
        if best_score > max(0.05, old_score * 1.8):
            goal = best_drive

    # 只评估已知设施；设施库存未知，失败后设置一段个人重试冷却时间。
    known = set(life.known_locations)
    options: list[tuple[float, str, list[str]]] = []
    for fid, fact in life.beliefs.items():
        effect = fact.effects.get(goal, 0)
        if effect >= 0 or life.failed_until.get(fid, 0) > observation.minute:
            continue
        route = find_route(known_map, life.location, fact.location, known)
        if route is None:
            continue
        travel, path = route
        relief = min(life.drives[goal], -effect) / 100
        cost = 0.004 * (travel * persona.move_multiplier + fact.duration) / 10
        score = relief * persona.drives[goal].priority - cost
        if score > 0:
            options.append((score, fid, path))
    if options:
        options.sort(key=lambda x: (-x[0], x[1]))
        _, fid, path = options[0]
        if len(path) > 1:
            return Decision(goal, ActionIntent("move", path[1]))
        return Decision(goal, ActionIntent("use", fid))

    # 对需求没有已知可用方案时，去未观察过的地点探索。
    destinations: list[tuple[int, str, list[str]]] = []
    for destination in known - set(life.visited):
        route = find_route(known_map, life.location, destination, known)
        if route is not None and len(route[1]) > 1:
            destinations.append((route[0], destination, route[1]))
    if destinations:
        destinations.sort()
        return Decision(goal, ActionIntent("move", destinations[0][2][1]))

    return Decision(goal, None)
