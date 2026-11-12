"""WorldLife 数据结构。Definition 是规则，State 是可变事实，Belief 是个人认知。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DriveSpec:
    """需求缺口：0=已满足，100=紧迫；不是医学数据。"""
    initial: float
    rise_per_hour: float
    threshold: float
    priority: float


@dataclass(frozen=True)
class BodySpec:
    """通用行动能力模型；不同生命类型通过配置调整。"""
    initial_vitality: float = 100.0
    idle_recovery_per_hour: float = 0.15
    move_cost_per_hour: float = 1.0
    use_cost_per_hour: float = 0.35
    rest_recovery_per_hour: float = 2.0
    min_move_vitality: float = 12.0
    min_use_vitality: float = 6.0
    # 需求超过阈值后，每小时损失多少行动能力。如 thirst:[90,2]。
    critical_drives: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Persona:
    id: str
    drives: dict[str, DriveSpec]
    body: BodySpec = field(default_factory=BodySpec)
    move_multiplier: float = 1.0
    # 简单 NPC 支援行为（0 表示不执行）；不是语言或情感系统。
    assist_amount: float = 0.0
    assist_duration: int = 15
    assist_threshold: float = 30.0


@dataclass(frozen=True)
class Facility:
    id: str
    location: str
    duration: int
    effects: dict[str, float]
    resource: str | None = None
    units: float = 0.0
    restorative: bool = False  # 行动期间是否促进 vitality 恢复


@dataclass(frozen=True)
class WorldDefinition:
    id: str
    connections: dict[str, dict[str, int]]
    facilities: dict[str, Facility]
    initial_resources: dict[str, tuple[float, float]]
    external_events: list[dict[str, Any]]


@dataclass
class FacilityBelief:
    """角色曾获知的设施用途；不包含世界实时库存。"""
    location: str
    duration: int
    effects: dict[str, float]
    last_seen: int | None = None  # None 表示仅来自初始常识/记忆
    last_result: str | None = None  # 上次尝试的实际反馈（不是客观库存）
    last_used: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return vars(self).copy()


@dataclass
class LifeState:
    id: str
    persona_id: str
    location: str
    known_locations: list[str]
    drives: dict[str, float]
    anchors: dict[str, dict[str, float | int]] = field(default_factory=dict)
    busy: dict[str, Any] | None = None
    vitality: float = 100.0
    beliefs: dict[str, FacilityBelief] = field(default_factory=dict)
    visited: list[str] = field(default_factory=list)
    goal: str | None = None  # 正在努力满足的需求；移动/失败后不自动消失
    failed_until: dict[str, int] = field(default_factory=dict)
    failure_counts: dict[str, int] = field(default_factory=dict)
    blocked_reason: str | None = None  # 同一障碍只记录一次，避免长期重复报错
    decision_ticket: int = 0  # 新的唤醒会使旧 decide 事件自动失效

    def set_drive(self, name: str, value: float, minute: int) -> None:
        """修改需求值时必须同步时间锚点，避免分段推进后状态回弹。"""
        value = round(max(0.0, min(100.0, value)), 8)
        self.drives[name] = value
        self.anchors[name] = {"minute": minute, "value": value}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "persona_id": self.persona_id,
            "location": self.location, "known_locations": self.known_locations,
            "drives": self.drives, "anchors": self.anchors, "busy": self.busy,
            "vitality": self.vitality,
            "beliefs": {k: v.to_dict() for k, v in self.beliefs.items()},
            "visited": self.visited, "goal": self.goal,
            "failed_until": self.failed_until, "failure_counts": self.failure_counts,
            "blocked_reason": self.blocked_reason,
            "decision_ticket": self.decision_ticket,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifeState:
        loaded = dict(data)
        loaded["beliefs"] = {k: FacilityBelief(**v) for k, v in data.get("beliefs", {}).items()}
        return cls(**loaded)


@dataclass
class Scenario:
    world: WorldDefinition
    personas: dict[str, Persona]  # actor_id -> 个体配置
    initial_lives: dict[str, LifeState]
    fingerprint: str


@dataclass(order=True)
class QueuedEvent:
    minute: int
    priority: int
    sequence: int
    kind: str = field(compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return vars(self).copy()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedEvent:
        return cls(**data)


@dataclass(frozen=True)
class NearbyActor:
    id: str
    needs_assistance: bool


@dataclass(frozen=True)
class Observation:
    """当前能观察到的事：不暴露远处设施、全局库存或其他角色完整状态。"""
    minute: int
    location: str
    facilities: tuple[Facility, ...]
    nearby_actors: tuple[NearbyActor, ...]


@dataclass(frozen=True)
class ActionIntent:
    kind: str  # move / use / assist
    target: str


@dataclass(frozen=True)
class Decision:
    goal: str | None
    action: ActionIntent | None
