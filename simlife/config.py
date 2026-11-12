"""场景装配：分别加载 World、Persona 和 Actor，并在运行前检查引用。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .model import (BodySpec, DriveSpec, Facility, FacilityBelief, LifeState,
                    Persona, Scenario, WorldDefinition)

RULESET = "worldlife-0.5"  # 默认演化规则变化后，更换此版本以拒绝旧存档。


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 根节点必须是对象: {path}")
    return data


def _range(x: float, lo: float, hi: float, label: str) -> None:
    if not lo <= x <= hi:
        raise ValueError(f"{label} 应在 {lo} ~ {hi} 之间，实际为 {x}")


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path).resolve()
    binding = _json(path)
    raw_world = _json((path.parent / binding["world"]).resolve())
    connections = {
        name: {dest: int(cost) for dest, cost in neighbors.items()}
        for name, neighbors in raw_world["locations"].items()
    }
    if not connections:
        raise ValueError("世界至少需要一个地点")
    for loc, neighbors in connections.items():
        for dest, cost in neighbors.items():
            if dest not in connections or cost <= 0:
                raise ValueError(f"非法地点连接：{loc} -> {dest}")

    resources: dict[str, tuple[float, float]] = {}
    for name, item in raw_world.get("resources", {}).items():
        current, cap = float(item["amount"]), float(item["capacity"])
        _range(current, 0, cap, f"resource.{name}")
        resources[name] = (current, cap)

    facilities: dict[str, Facility] = {}
    for item in raw_world.get("facilities", []):
        f = Facility(
            id=item["id"], location=item["location"],
            duration=int(item["duration_minutes"]),
            effects={key: float(value) for key, value in item["effects"].items()},
            resource=item.get("resource"), units=float(item.get("units", 0)),
            restorative=bool(item.get("restorative", False)),
        )
        if f.id in facilities or f.location not in connections or f.duration <= 0:
            raise ValueError(f"设施信息非法：{f.id}")
        if not f.effects or not any(value < 0 for value in f.effects.values()):
            raise ValueError(f"设施必须能缓解至少一种需求：{f.id}")
        if f.resource is not None and f.resource not in resources:
            raise ValueError(f"设施使用未知资源：{f.id} / {f.resource}")
        if f.units < 0 or (f.resource is None and f.units != 0):
            raise ValueError(f"设施的资源消耗非法：{f.id}")
        facilities[f.id] = f

    events = raw_world.get("events", [])
    for event in events:
        kind = event["type"]
        if int(event["minute"]) < 0:
            raise ValueError("世界事件时间不能为负数")
        if kind == "resource_add":
            if event["resource"] not in resources or float(event["amount"]) <= 0:
                raise ValueError(f"非法补给事件：{event}")
            if "repeat_every_minutes" in event and int(event["repeat_every_minutes"]) <= 0:
                raise ValueError("重复事件周期必须大于零")
        elif kind in ("facility_disable", "facility_enable"):
            if event["facility"] not in facilities:
                raise ValueError(f"事件引用未知设施：{event}")
        elif kind == "vitality_change":
            if not isinstance(event["actor"], str):
                raise ValueError(f"事件缺少角色：{event}")
        else:
            raise ValueError(f"暂不支持的世界事件：{kind}")
    world = WorldDefinition(raw_world["id"], connections, facilities, resources, events)

    personas: dict[str, Persona] = {}
    lives: dict[str, LifeState] = {}
    for actor in binding["actors"]:
        aid = actor["id"]
        if aid in lives:
            raise ValueError(f"重复 actor_id：{aid}")
        raw = _json((path.parent / actor["persona"]).resolve())
        drives = {name: DriveSpec(**values) for name, values in raw["drives"].items()}
        if not drives:
            raise ValueError(f"角色没有需求：{aid}")
        for name, spec in drives.items():
            _range(spec.initial, 0, 100, f"{name}.initial")
            _range(spec.threshold, 0, 99.999, f"{name}.threshold")
            if spec.rise_per_hour < 0 or spec.priority <= 0:
                raise ValueError(f"无效需求增长率或优先级：{name}")
        body_raw = raw.get("body", {})
        critical = {name: (float(pair[0]), float(pair[1]))
                    for name, pair in body_raw.get("critical_drives", {}).items()}
        for name, (threshold, damage) in critical.items():
            if name not in drives or damage < 0:
                raise ValueError(f"无效的身体风险需求：{name}")
            _range(threshold, 0, 100, f"body.{name}.threshold")
        body = BodySpec(
            **{k: v for k, v in body_raw.items() if k != "critical_drives"},
            critical_drives=critical,
        )
        _range(body.initial_vitality, 0, 100, "body.initial_vitality")
        _range(body.min_move_vitality, 0, 100, "body.min_move_vitality")
        _range(body.min_use_vitality, 0, 100, "body.min_use_vitality")
        rates = (body.idle_recovery_per_hour, body.move_cost_per_hour,
                 body.use_cost_per_hour, body.rest_recovery_per_hour)
        if any(rate < 0 for rate in rates):
            raise ValueError("身体变化速率不能为负数")
        persona = Persona(
            id=raw["id"], drives=drives, body=body,
            move_multiplier=float(raw.get("move_multiplier", 1)),
            assist_amount=float(raw.get("assist_amount", 0)),
            assist_duration=int(raw.get("assist_duration", 15)),
            assist_threshold=float(raw.get("assist_threshold", 30)),
        )
        if persona.move_multiplier <= 0 or persona.assist_amount < 0 or persona.assist_duration <= 0:
            raise ValueError("角色行动参数无效")
        start = actor["start_location"]
        known = list(actor.get("known_locations", [start]))
        if start not in connections or start not in known or any(l not in connections for l in known):
            raise ValueError(f"角色初始位置/已知地点无效：{aid}")
        if not any(set(f.effects) & set(drives) for f in facilities.values()):
            raise ValueError(f"没有任何设施能够满足 {aid} 的需求")
        memories: dict[str, FacilityBelief] = {}
        for fid in actor.get("known_facilities", []):
            if fid not in facilities:
                raise ValueError(f"角色记忆里有未知设施：{fid}")
            f = facilities[fid]
            memories[fid] = FacilityBelief(f.location, f.duration, f.effects.copy())
        personas[aid] = persona
        lives[aid] = LifeState(
            id=aid, persona_id=persona.id, location=start, known_locations=known,
            drives={k: float(v.initial) for k, v in drives.items()},
            anchors={k: {"minute": 0, "value": float(v.initial)} for k, v in drives.items()},
            vitality=float(actor.get("initial_vitality", body.initial_vitality)),
            beliefs=memories,
        )
        _range(lives[aid].vitality, 0, 100, f"{aid}.vitality")
    if not lives:
        raise ValueError("场景至少需要一个角色")
    for event in events:
        if event["type"] == "vitality_change" and event["actor"] not in lives:
            raise ValueError(f"事件引用未知角色：{event['actor']}")

    # 规则版本也是存档兼容性的一部分，避免配置没变但代码行为变了。
    normalized = json.dumps({
        "ruleset": RULESET, "world": raw_world, "binding": binding,
        "personas": {a: {
            "id": p.id, "drives": {k: vars(v) for k, v in p.drives.items()},
            "body": vars(p.body), "move_multiplier": p.move_multiplier,
            "assist_amount": p.assist_amount, "assist_duration": p.assist_duration,
            "assist_threshold": p.assist_threshold,
        } for a, p in sorted(personas.items())},
    }, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return Scenario(world, personas, lives, fingerprint)
