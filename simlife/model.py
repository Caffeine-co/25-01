"""纯数据结构：世界事实、人物内部状态与主观知识严格区分。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .planning import Project
    from .knowledge import BeliefRecord


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return round(max(low, min(high, value)), 8)


@dataclass(frozen=True)
class DriveSpec:
    """需求缺口：0 已满足、100 极紧迫（不是医学指标）。"""
    initial: float
    rise_per_hour: float
    threshold: float
    priority: float


@dataclass(frozen=True)
class BodySpec:
    initial_vitality: float = 100.0
    idle_recovery_per_hour: float = 0.15
    move_cost_per_hour: float = 1.0
    use_cost_per_hour: float = 0.35
    rest_recovery_per_hour: float = 2.0
    min_move_vitality: float = 12.0
    min_use_vitality: float = 6.0
    critical_drives: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Persona:
    id: str
    drives: dict[str, DriveSpec]
    body: BodySpec = field(default_factory=BodySpec)
    move_multiplier: float = 1.0
    assist_amount: float = 0.0
    assist_duration: int = 15
    assist_threshold: float = 30.0
    # 原有参数保持兼容。以下字段可选：不同人格对非生存目标的偏好不同。
    traits: dict[str, float] = field(default_factory=dict)
    interests: dict[str, float] = field(default_factory=dict)
    name: str = ""
    biography: str = ""
    ambitions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Facility:
    id: str
    location: str
    duration: int
    effects: dict[str, float]
    resource: str | None = None
    units: float = 0.0
    restorative: bool = False
    # 附加标签让活动可以与设施关联，而不是与 WorldRuntime 硬编码绑定。
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorldDefinition:
    id: str
    connections: dict[str, dict[str, int]]
    facilities: dict[str, Facility]
    initial_resources: dict[str, tuple[float, float]]
    external_events: list[dict[str, Any]]


@dataclass
class FacilityBelief:
    location: str
    duration: int
    effects: dict[str, float]
    last_seen: int | None = None
    last_result: str | None = None
    last_used: int | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Memory:
    """情景记忆来自已发生事件，不能代替世界事实。"""
    minute: int
    kind: str
    text: str
    actors: list[str] = field(default_factory=list)
    salience: float = 0.5
    source: str = "world_event"


@dataclass
class LongGoal:
    """长期成长目标；数值代表可测量的技能/进度，而不是一段模糊描述。"""
    id: str
    target: float
    progress: float = 0.0
    status: str = "active"
    created_at: int = 0
    completed_at: int | None = None


@dataclass
class Relationship:
    trust: float = 0.5
    closeness: float = 0.1
    interactions: int = 0
    last_interaction: int = -1


@dataclass
class Emotion:
    """短时情绪，只有外部事件施加冲击；时间经过会衰减至基线。"""
    valence: float = 0.0  # -1 到 1
    arousal: float = 0.0  # 0 到 1


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
    goal: str | None = None
    failed_until: dict[str, int] = field(default_factory=dict)
    failure_counts: dict[str, int] = field(default_factory=dict)
    blocked_reason: str | None = None
    decision_ticket: int = 0
    # v0.6+ 新增，旧结构字段全部保留。
    action_ticket: int = 0
    skills: dict[str, float] = field(default_factory=dict)
    emotion: Emotion = field(default_factory=Emotion)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    memories: list[Memory] = field(default_factory=list)
    # 已有任务计划与承诺，日程粒度为分钟；不混同于身体需求。
    commitments: list[dict[str, Any]] = field(default_factory=list)
    completed_goals: int = 0
    goal_since: int = 0
    last_creative: int = -1440
    last_social: int = -1440
    # 结构化信念：只记住观察或事件带来的信息，带有来源与时间。
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    known_edges: dict[str, dict[str, int]] = field(default_factory=dict)
    long_goals: dict[str, LongGoal] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    propositions: dict[str, BeliefRecord] = field(default_factory=dict)

    def set_drive(self, name: str, value: float, minute: int) -> None:
        self.drives[name] = clamp(value)
        self.anchors[name] = {"minute": minute, "value": self.drives[name]}

    def add_memory(self, memory: Memory, limit: int = 256) -> None:
        self.memories.append(memory)
        if len(self.memories) > limit:
            # 人物工作记忆只保留最近记录；历史审计事件仍在 SQLite。
            self.memories = self.memories[-limit:]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LifeState":
        value = dict(data)
        value["beliefs"] = {k: FacilityBelief(**{**v, "tags": tuple(v.get("tags", ()))})
                            for k, v in value.get("beliefs", {}).items()}
        value["emotion"] = Emotion(**value.get("emotion", {}))
        value["relationships"] = {k: Relationship(**v) for k, v in value.get("relationships", {}).items()}
        value["memories"] = [Memory(**m) for m in value.get("memories", [])]
        value["long_goals"] = {k: LongGoal(**v) for k, v in value.get("long_goals", {}).items()}
        from .planning import Project, ProjectStep
        value["projects"] = {k: Project(**{**v, "steps": [ProjectStep(**step) for step in v["steps"]]})
                             for k, v in value.get("projects", {}).items()}
        from .knowledge import BeliefRecord
        value["propositions"] = {k: BeliefRecord(**v) for k, v in value.get("propositions", {}).items()}
        return cls(**value)


@dataclass
class Scenario:
    world: WorldDefinition
    personas: dict[str, Persona]
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
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueuedEvent":
        return cls(**data)


@dataclass(frozen=True)
class NearbyActor:
    id: str
    needs_assistance: bool
    available: bool = True


@dataclass(frozen=True)
class Observation:
    minute: int
    location: str
    facilities: tuple[Facility, ...]
    nearby_actors: tuple[NearbyActor, ...]


@dataclass(frozen=True)
class ActionIntent:
    kind: str
    target: str


@dataclass(frozen=True)
class Decision:
    goal: str | None
    action: ActionIntent | None
