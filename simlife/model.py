"""数据模型：规范的事实来源与可变运行状态分离。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DriveSpec:
    """需求的缺口值：0 表示已满足，100 表示非常迫切。不是医学测量。"""
    initial: float
    rise_per_hour: float
    threshold: float
    priority: float


@dataclass(frozen=True)
class Persona:
    id: str
    drives: dict[str, DriveSpec]
    move_multiplier: float = 1.0


@dataclass(frozen=True)
class Facility:
    id: str
    location: str
    duration: int  # 分钟
    effects: dict[str, float]  # 对需求缺口的变化，例如 -40 表示缓解
    resource: str | None = None
    units: float = 0.0


@dataclass(frozen=True)
class WorldDefinition:
    id: str
    connections: dict[str, dict[str, int]]
    facilities: dict[str, Facility]
    initial_resources: dict[str, tuple[float, float]]  # 当前库存、容量
    external_events: list[dict[str, Any]]


@dataclass
class LifeState:
    id: str
    persona_id: str
    location: str
    known_locations: list[str]
    drives: dict[str, float]
    # 每个需求最后一次被离散事件改变时的锚点；保证任意切分时间推进后结果一致。
    anchors: dict[str, dict[str, float | int]] = field(default_factory=dict)
    busy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "persona_id": self.persona_id,
            "location": self.location, "known_locations": self.known_locations,
            "drives": self.drives, "anchors": self.anchors, "busy": self.busy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifeState:
        return cls(**data)


@dataclass
class Scenario:
    world: WorldDefinition
    personas: dict[str, Persona]  # actor_id -> Persona
    initial_lives: dict[str, LifeState]
    fingerprint: str


@dataclass(order=True)
class QueuedEvent:
    """事件只按 time/sequence 排序，其余元数据不是排序字段。"""
    minute: int
    priority: int
    sequence: int
    kind: str = field(compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {"minute": self.minute, "priority": self.priority,
                "sequence": self.sequence, "kind": self.kind, "payload": self.payload}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedEvent:
        return cls(**data)
