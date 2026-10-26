"""场景装配：World、Persona、Actor 绑定独立，拒绝不兼容配置。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .model import DriveSpec, Facility, LifeState, Persona, Scenario, WorldDefinition


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 根节点必须是对象: {path}")
    return data


def _between(x: float, lo: float, hi: float, label: str) -> None:
    if not lo <= x <= hi:
        raise ValueError(f"{label} 必须处于 {lo} ~ {hi}: {x}")


def load_scenario(path: str | Path) -> Scenario:
    """只在此处处理文件路径；模拟核心只见到通用实体/组件。"""
    path = Path(path).resolve()
    binding = _load_json(path)
    world_raw = _load_json((path.parent / binding["world"]).resolve())

    connections = {
        str(loc): {str(dest): int(cost) for dest, cost in neighbors.items()}
        for loc, neighbors in world_raw["locations"].items()
    }
    if not connections:
        raise ValueError("World 至少需要一个地点")
    for loc, neighbors in connections.items():
        for dest, cost in neighbors.items():
            if dest not in connections or cost <= 0:
                raise ValueError(f"非法连接: {loc} -> {dest} ({cost})")
    # 允许有向连接。例如单向道路、单程传送门。
    facilities: dict[str, Facility] = {}
    for item in world_raw["facilities"]:
        f = Facility(
            id=item["id"], location=item["location"],
            duration=int(item["duration_minutes"]),
            effects={k: float(v) for k, v in item["effects"].items()},
            resource=item.get("resource"), units=float(item.get("units", 0)),
        )
        if f.id in facilities or f.location not in connections or f.duration <= 0:
            raise ValueError(f"设施配置不合法: {f.id}")
        if not f.effects or not any(effect < 0 for effect in f.effects.values()):
            raise ValueError(f"设施必须能够缓解至少一个需求: {f.id}")
        if f.units < 0 or (f.resource is None and f.units != 0):
            raise ValueError(f"设施资源用量不合法: {f.id}")
        facilities[f.id] = f

    resources: dict[str, tuple[float, float]] = {}
    for rid, spec in world_raw.get("resources", {}).items():
        amount, cap = float(spec["amount"]), float(spec["capacity"])
        if cap < 0 or not 0 <= amount <= cap:
            raise ValueError(f"库存不合法: {rid}")
        resources[rid] = (amount, cap)
    for f in facilities.values():
        if f.resource and f.resource not in resources:
            raise ValueError(f"未知资源 {f.resource}（设施 {f.id}）")

    ext = world_raw.get("events", [])
    for e in ext:
        if e["type"] != "resource_add" or e["resource"] not in resources:
            raise ValueError(f"尚不支持的世界事件: {e}")
        if int(e["minute"]) < 0 or float(e["amount"]) <= 0:
            raise ValueError(f"事件时间/数量不合法: {e}")

    world = WorldDefinition(
        id=world_raw["id"], connections=connections,
        facilities=facilities, initial_resources=resources,
        external_events=ext,
    )

    personas: dict[str, Persona] = {}
    lives: dict[str, LifeState] = {}
    for actor in binding["actors"]:
        aid = actor["id"]
        if aid in lives:
            raise ValueError(f"重复角色 ID: {aid}")
        raw = _load_json((path.parent / actor["persona"]).resolve())
        drives = {name: DriveSpec(**entry) for name, entry in raw["drives"].items()}
        if not drives:
            raise ValueError(f"角色 {aid} 没有需求")
        for name, d in drives.items():
            _between(d.initial, 0, 100, name + ".initial")
            _between(d.threshold, 0, 99.999, name + ".threshold")
            if d.rise_per_hour < 0 or d.priority <= 0:
                raise ValueError(f"需求速率和权重非法: {name}")
        persona = Persona(id=raw["id"], drives=drives,
                          move_multiplier=float(raw.get("move_multiplier", 1.0)))
        if persona.move_multiplier <= 0:
            raise ValueError("move_multiplier 必须大于 0")
        start = actor["start_location"]
        known = list(actor.get("known_locations", connections.keys()))
        if start not in connections or start not in known or any(x not in connections for x in known):
            raise ValueError(f"角色初始位置/已知地点无效: {aid}")
        if not any(set(f.effects) & set(drives) for f in facilities.values()):
            raise ValueError(f"角色 {aid} 的需求与 World 设施完全不匹配")
        personas[aid] = persona
        lives[aid] = LifeState(
            id=aid, persona_id=persona.id, location=start,
            known_locations=known,
            drives={k: float(v.initial) for k, v in drives.items()},
            anchors={k: {"minute": 0, "value": float(v.initial)}
                     for k, v in drives.items()},
        )
    if not lives:
        raise ValueError("场景需要至少一个 Life")

    # 修改任何一个参与组装的文件，存档即失去兼容性；需显式新建存档。
    normalized = json.dumps({"binding": binding, "world": world_raw,
                             "personas": {a: {"id": personas[a].id,
                                  "move_multiplier": personas[a].move_multiplier,
                                  "drives": {k: vars(v) for k, v in personas[a].drives.items()}}
                                  for a in sorted(personas)}},
                            ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return Scenario(world, personas, lives, fingerprint)
