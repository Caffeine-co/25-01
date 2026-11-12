"""决策层：旧版需求满足 + 新版主动目标与社会活动。

保持纯函数式 choose：不改世界、不改人物，方便测试和替换 LLM 策略。
"""
from __future__ import annotations
import heapq
from .model import ActionIntent, Decision, LifeState, Observation, Persona


def find_route(connections: dict[str, dict[str, int]], origin: str,
               destination: str, known: set[str]) -> tuple[int, list[str]] | None:
    """只允许经过角色已知的地点。未来可换为真正的个人地图图谱。"""
    if origin == destination:
        return (0, [origin])
    queue: list[tuple[int, str, list[str]]] = [(0, origin, [origin])]
    best = {origin: 0}
    while queue:
        dist, loc, path = heapq.heappop(queue)
        if dist != best[loc]:
            continue
        if loc == destination:
            return dist, path
        for other, cost in connections.get(loc, {}).items():
            length = dist + cost
            if other in known and length < best.get(other, 10**20):
                best[other] = length
                heapq.heappush(queue, (length, other, [*path, other]))
    return None


def move_or_use(life: LifeState, observation: Observation,
                connections: dict[str, dict[str, int]],
                facility_id: str, kind: str = "use") -> ActionIntent | None:
    fact = life.beliefs.get(facility_id)
    if fact is None:
        return None
    route = find_route(connections, life.location, fact.location, set(life.known_locations))
    if route is None:
        return None
    return ActionIntent("move", route[1][1]) if len(route[1]) > 1 else ActionIntent(kind, facility_id)


def choose_action(life: LifeState, persona: Persona, observation: Observation,
                  known_map: dict[str, dict[str, int]]) -> Decision:
    minute = observation.minute
    # 1. 真实需要支援的邻居优先；低行动能力时不能支援。
    if persona.assist_amount and life.vitality >= persona.body.min_use_vitality:
        for peer in observation.nearby_actors:
            if peer.needs_assistance:
                return Decision(life.goal, ActionIntent("assist", peer.id))

    # 2. 需求优先级与旧版本一致，持续目标仅在出现明显更紧急需求时被打断。
    candidate = []
    for name, spec in persona.drives.items():
        if life.drives[name] > spec.threshold:
            score = (life.drives[name] - spec.threshold) / (100 - spec.threshold) * spec.priority
            candidate.append((score, name))
    candidate.sort(key=lambda x: (-x[0], x[1]))
    old = life.goal
    old_need = old if old in persona.drives else None
    if old_need is not None and life.drives.get(old_need, 0) <= persona.drives[old_need].threshold:
        old_need = None
    if candidate:
        best_score, best_need = candidate[0]
        if old_need is None:
            goal = best_need
        else:
            score_old = next((s for s, name in candidate if name == old_need), 0)
            goal = best_need if best_score > max(0.05, score_old * 1.8) else old_need
        options = []
        for fid, belief in life.beliefs.items():
            relief = -belief.effects.get(goal, 0)
            if relief <= 0 or life.failed_until.get(fid, 0) > minute:
                continue
            route = find_route(known_map, life.location, belief.location, set(life.known_locations))
            if route is None:
                continue
            travel, path = route
            gain = min(life.drives[goal], relief) / 100 * persona.drives[goal].priority
            cost = 0.004 * (travel * persona.move_multiplier + belief.duration) / 10
            if gain > cost:
                options.append((gain - cost, fid, path))
        if options:
            options.sort(key=lambda x: (-x[0], x[1]))
            _, fid, path = options[0]
            action = ActionIntent("move", path[1]) if len(path) > 1 else ActionIntent("use", fid)
            return Decision(goal, action)
        # 3. 没有设施可用：只探索已经知道存在但没访问的地点。
        paths = []
        for dest in set(life.known_locations) - set(life.visited):
            route = find_route(known_map, life.location, dest, set(life.known_locations))
            if route and len(route[1]) > 1:
                paths.append((route[0], dest, route[1]))
        if paths:
            paths.sort()
            return Decision(goal, ActionIntent("move", paths[0][2][1]))
        return Decision(goal, None)

    # 4. 若有到期的承诺，优先兑现。不会凭空增加对应设施/人物。
    for task in life.commitments:
        due = int(task["minute"])
        if task.get("status", "pending") == "pending" and due <= minute < due + 180:
            kind, target = task["kind"], task["target"]
            if kind == "practice":
                action = move_or_use(life, observation, known_map, target, kind="practice")
                if action:
                    return Decision("commitment:" + target, action)
            elif kind == "socialize" and target in (p.id for p in observation.nearby_actors if p.available):
                return Decision("commitment:" + target, ActionIntent("socialize", target))

    # 5. 主动社交：同地点、对方空闲且间隔足够长。
    hour = (minute // 60) % 24
    extroversion = persona.traits.get("extraversion", 0.4)
    if 9 <= hour < 21 and minute - life.last_social >= int(1440 - extroversion * 840):
        peers = sorted((x.id for x in observation.nearby_actors if x.available))
        if peers and extroversion >= 0.25:
            return Decision("social:" + peers[0], ActionIntent("socialize", peers[0]))

    # 6. 主动创作：兴趣与当前精力影响行动。设施需已知且提供 practice 标签。
    if 8 <= hour < 22 and minute - life.last_creative >= 480 and life.vitality >= 25:
        for interest, weight in sorted(persona.interests.items(), key=lambda x: (-x[1], x[0])):
            if weight < 0.35:
                continue
            facilities = [fid for fid, belief in life.beliefs.items()
                          if "practice" in belief.tags and
                          (f"skill:{interest}" in belief.tags or fid == f"practice_{interest}")]
            if facilities:
                fid = sorted(facilities)[0]
                if life.failed_until.get(fid, 0) > minute:
                    continue
                action = move_or_use(life, observation, known_map, fid, kind="practice")
                if action:
                    return Decision("practice:" + interest, action)

    # 7. 无活动同样是合理结果；下个定时决策点再判断。
    return Decision(None, None)


class StandardDecisionPolicy:
    def choose(self, life: LifeState, persona: Persona, observation: Observation,
               known_map: dict[str, dict[str, int]]) -> Decision:
        return choose_action(life, persona, observation, known_map)
