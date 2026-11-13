"""多步骤项目规划。项目不直接改世界；只有行动执行成功才能推进步骤。

项目可以由 JSON 场景、管理员或经校验的 LLM 建议创建。所有 step 都
使用通用 ActionRegistry；设施类步骤自动经个人已知地图规划逐段移动。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .model import ActionIntent
from .policy import find_route

if TYPE_CHECKING:
    from .model import LifeState, Observation


ALLOWED_STEPS = frozenset({"move", "use", "practice", "socialize", "assist"})


@dataclass
class ProjectStep:
    kind: str
    target: str


@dataclass
class Project:
    id: str
    steps: list[ProjectStep]
    priority: float = 0.5
    start_minute: int = 0
    deadline: int | None = None
    index: int = 0
    status: str = "active"  # active/completed/failed/cancelled
    failures: int = 0
    retry_at: int = 0
    completed_at: int | None = None
    evidence: list[dict] = field(default_factory=list)

    def current(self) -> ProjectStep | None:
        if self.status == "active" and self.index < len(self.steps):
            return self.steps[self.index]
        return None


def validate_project(project: Project, actor: str, actors: set[str],
                     facilities: set[str], locations: set[str]) -> None:
    if not project.id or len(project.id) > 80 or not (1 <= len(project.steps) <= 40):
        raise ValueError("项目名称或步骤数非法（1..40）")
    if not 0 <= project.priority <= 1 or project.start_minute < 0:
        raise ValueError("项目优先级或开始时间非法")
    if project.deadline is not None and project.deadline < project.start_minute:
        raise ValueError("项目截止时间早于开始时间")
    for step in project.steps:
        if step.kind not in ALLOWED_STEPS:
            raise ValueError(f"项目动作不受支持：{step.kind}")
        if step.kind == "move" and step.target not in locations:
            raise ValueError(f"未知项目地点：{step.target}")
        if step.kind in {"use", "practice"} and step.target not in facilities:
            raise ValueError(f"未知项目设施：{step.target}")
        if step.kind in {"socialize", "assist"} and (step.target not in actors or step.target == actor):
            raise ValueError(f"未知社交对象：{step.target}")


def project_intent(life: "LifeState", obs: "Observation") -> tuple[Project | None, ActionIntent | None]:
    """项目的下一步可能是前往目的地，或实际执行该动作。未观察到的路不能用。"""
    candidates = sorted((p for p in life.projects.values()
                         if p.current() is not None and p.start_minute <= obs.minute
                         and p.retry_at <= obs.minute),
                        key=lambda p: (-p.priority, p.start_minute, p.id))
    if not candidates:
        return None, None
    for project in candidates:
        step = project.current()
        assert step is not None
        if step.kind in {"use", "practice"}:
            facility = life.beliefs.get(step.target)
            if facility is None or life.failed_until.get(step.target, 0) > obs.minute:
                continue
            route = find_route(life.known_edges, life.location, facility.location,
                               set(life.known_locations))
            if route is None:
                continue
            if len(route[1]) > 1:
                return project, ActionIntent("move", route[1][1])
            return project, ActionIntent(step.kind, step.target)
        if step.kind == "move":
            route = find_route(life.known_edges, life.location, step.target,
                               set(life.known_locations))
            if route is None:
                continue
            if len(route[1]) <= 1:
                return project, ActionIntent("arrived", step.target)
            return project, ActionIntent("move", route[1][1])
        if step.kind in {"socialize", "assist"}:
            if step.target in {x.id for x in obs.nearby_actors if x.available}:
                return project, ActionIntent(step.kind, step.target)
    return None, None


def project_from_dict(raw: dict) -> Project:
    steps = [ProjectStep(**x) for x in raw["steps"]]
    return Project(id=raw["id"], steps=steps, priority=float(raw.get("priority", 0.5)),
                   start_minute=int(raw.get("start_minute", 0)),
                   deadline=(int(raw["deadline"]) if raw.get("deadline") is not None else None))
