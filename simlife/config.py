"""场景加载与输入校验。兼容 world-preview v0.5 的 world/persona/scenario JSON。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from dataclasses import asdict

from .planning import project_from_dict, validate_project
from .model import (BodySpec, DriveSpec, Facility, FacilityBelief,
                    LifeState, LongGoal, Persona, Scenario, WorldDefinition)

RULESET = "worldlife-next-2.0"  # 规则改变时拒绝用旧快照直接继续。


def _load(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return result


def check(x: float, low: float, high: float, label: str) -> None:
    if not low <= x <= high:
        raise ValueError(f"{label} 超出 {low}~{high} 范围：{x}")


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path).resolve()
    binding = _load(path)
    raw_world = _load((path.parent / binding["world"]).resolve())
    connections = {src: {dst: int(cost) for dst, cost in edges.items()}
                   for src, edges in raw_world["locations"].items()}
    if not connections:
        raise ValueError("世界至少包含一个地点")
    for src, edges in connections.items():
        for dst, cost in edges.items():
            if dst not in connections or cost <= 0:
                raise ValueError(f"地点连接非法：{src}->{dst}")
    resources = {}
    for name, item in raw_world.get("resources", {}).items():
        amount, capacity = float(item["amount"]), float(item["capacity"])
        check(amount, 0, capacity, f"resource.{name}")
        resources[name] = (amount, capacity)
    facilities = {}
    for item in raw_world.get("facilities", []):
        facility = Facility(
            id=item["id"], location=item["location"],
            duration=int(item["duration_minutes"]),
            effects={k: float(v) for k, v in item.get("effects", {}).items()},
            resource=item.get("resource"), units=float(item.get("units", 0)),
            restorative=bool(item.get("restorative", False)),
            tags=tuple(item.get("tags", ())))
        if facility.id in facilities or facility.location not in connections or facility.duration <= 0:
            raise ValueError(f"设施不合法：{facility.id}")
        if not any(x < 0 for x in facility.effects.values()) and not facility.tags:
            raise ValueError(f"设施必须改善需求或声明活动标签：{facility.id}")
        if facility.resource is not None and facility.resource not in resources:
            raise ValueError(f"未定义设施资源：{facility.id}")
        if facility.units < 0 or (facility.resource is None and facility.units != 0):
            raise ValueError(f"设施资源消耗非法：{facility.id}")
        facilities[facility.id] = facility
    events = raw_world.get("events", [])
    for event in events:
        kind = event["type"]
        if int(event["minute"]) < 0:
            raise ValueError("事件不能发生在负时间")
        if kind == "resource_add":
            if event["resource"] not in resources or float(event["amount"]) <= 0:
                raise ValueError(f"非法资源补给：{event}")
            if "repeat_every_minutes" in event and int(event["repeat_every_minutes"]) <= 0:
                raise ValueError("重复事件间隔必须为正数")
        elif kind in ("facility_disable", "facility_enable"):
            if event["facility"] not in facilities:
                raise ValueError(f"未知设施：{event}")
        elif kind in ("vitality_change", "message", "knowledge_signal"):
            if not isinstance(event.get("actor"), str):
                raise ValueError(f"事件缺少角色：{event}")
            if kind == "knowledge_signal" and (not isinstance(event.get("key"), str)
                                                    or "value" not in event):
                raise ValueError("知识事件缺少 key/value")
        else:
            raise ValueError(f"未知事件类型：{kind}")
    world = WorldDefinition(raw_world["id"], connections, facilities, resources, events)

    personas: dict[str, Persona] = {}
    lives: dict[str, LifeState] = {}
    for actor in binding["actors"]:
        aid = actor["id"]
        if aid in lives:
            raise ValueError(f"重复角色 {aid}")
        raw = _load((path.parent / actor["persona"]).resolve())
        drives = {key: DriveSpec(**value) for key, value in raw["drives"].items()}
        if not drives:
            raise ValueError(f"角色没有需求：{aid}")
        for key, spec in drives.items():
            check(spec.initial, 0, 100, f"{key}.initial")
            check(spec.threshold, 0, 99.99, f"{key}.threshold")
            if spec.rise_per_hour < 0 or spec.priority <= 0:
                raise ValueError(f"需求增长率或重要性非法：{key}")
        raw_body = raw.get("body", {})
        critical = {k: (float(v[0]), float(v[1]))
                    for k, v in raw_body.get("critical_drives", {}).items()}
        for key, (threshold, damage) in critical.items():
            if key not in drives or damage < 0:
                raise ValueError(f"严重需求风险非法：{key}")
            check(threshold, 0, 100, f"critical.{key}")
        body = BodySpec(**{k: v for k, v in raw_body.items() if k != "critical_drives"},
                        critical_drives=critical)
        for key in ("initial_vitality", "min_move_vitality", "min_use_vitality"):
            check(getattr(body, key), 0, 100, f"body.{key}")
        if min(body.idle_recovery_per_hour, body.move_cost_per_hour,
               body.use_cost_per_hour, body.rest_recovery_per_hour) < 0:
            raise ValueError("身体变化率不允许负数")
        traits = {k: float(v) for k, v in raw.get("traits", {}).items()}
        for key, value in traits.items():
            check(value, 0, 1, f"trait.{key}")
        interests = {k: float(v) for k, v in raw.get("interests", {}).items()}
        for key, value in interests.items():
            check(value, 0, 1, f"interest.{key}")
        ambitions = {k: float(v) for k, v in raw.get("ambitions", {}).items()}
        for key, target in ambitions.items():
            check(target, 0, 100, f"ambition.{key}")
        persona = Persona(id=raw["id"], drives=drives, body=body,
                          move_multiplier=float(raw.get("move_multiplier", 1)),
                          assist_amount=float(raw.get("assist_amount", 0)),
                          assist_duration=int(raw.get("assist_duration", 15)),
                          assist_threshold=float(raw.get("assist_threshold", 30)),
                          traits=traits, interests=interests,
                          name=str(raw.get("name", aid)),
                          biography=str(raw.get("biography", "")), ambitions=ambitions)
        if persona.move_multiplier <= 0 or persona.assist_amount < 0 or persona.assist_duration <= 0:
            raise ValueError("行动参数无效")
        start = actor["start_location"]
        known = list(actor.get("known_locations", [start]))
        if start not in connections or start not in known or any(loc not in connections for loc in known):
            raise ValueError(f"角色初始/已知位置非法：{aid}")
        memories = {}
        for fid in actor.get("known_facilities", []):
            if fid not in facilities:
                raise ValueError(f"角色认知里存在未知设施：{fid}")
            facility = facilities[fid]
            memories[fid] = FacilityBelief(facility.location, facility.duration,
                                           facility.effects.copy(), tags=facility.tags)
        if not any(set(f.effects) & set(drives) for f in facilities.values()) and not interests:
            raise ValueError(f"角色没有可满足需求的设施：{aid}")
        lives[aid] = LifeState(
            id=aid, persona_id=persona.id, location=start,
            known_locations=known, drives={k: spec.initial for k, spec in drives.items()},
            anchors={k: {"minute": 0, "value": spec.initial} for k, spec in drives.items()},
            vitality=float(actor.get("initial_vitality", body.initial_vitality)),
            beliefs=memories, commitments=[dict(x) for x in actor.get("commitments", [])],
            skills={k: float(v) for k, v in actor.get("skills", {}).items()},
            projects={p["id"]: project_from_dict(p) for p in actor.get("projects", [])},
            long_goals={k: LongGoal(id=k, target=v, progress=float(actor.get("skills", {}).get(k, 0)),
                                    status="completed" if float(actor.get("skills", {}).get(k, 0)) >= v else "active")
                        for k, v in ambitions.items()})
        check(lives[aid].vitality, 0, 100, f"{aid}.vitality")
        personas[aid] = persona
    if not lives:
        raise ValueError("场景至少包含一个角色")
    for event in events:
        if event.get("actor") and event["actor"] not in lives:
            raise ValueError(f"事件角色不存在：{event['actor']}")
    for life in lives.values():
        if len(life.projects) != len(next(x for x in binding["actors"] if x["id"] == life.id).get("projects", [])):
            raise ValueError("重复项目 id")
        for project in life.projects.values():
            validate_project(project, life.id, set(lives), set(facilities), set(connections))
        for commitment in life.commitments:
            if int(commitment["minute"]) < 0:
                raise ValueError("承诺时间不能为负数")
            if commitment["kind"] not in ("practice", "socialize"):
                raise ValueError("承诺类型仅支持 practice / socialize")
    normalized = json.dumps({"ruleset": RULESET, "world": raw_world,
                             "binding": binding,
                             "personas": {aid: asdict(p) for aid, p in sorted(personas.items())}},
                            sort_keys=True, ensure_ascii=False)
    return Scenario(world, personas, lives,
                    hashlib.sha256(normalized.encode("utf-8")).hexdigest())
