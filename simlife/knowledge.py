"""有证据来源的主观信念。事实由 World 保存；Belief 只表达人物相信什么。

规则有意简洁：同源重复证据不放大置信度；独立证据有上限；
新的直接观察优先于旧传闻。推断/传闻永远不会自动改变 World。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json
import math


@dataclass
class BeliefRecord:
    value: Any
    confidence: float
    source: str
    updated_at: int
    sources: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


def observe_belief(old: BeliefRecord | None, *, value: Any, source: str,
                   source_id: str, confidence: float, minute: int) -> tuple[BeliefRecord, str]:
    """添加一次外部证据；不从人物自己的文字创造新证据。"""
    if not (0 <= confidence <= 1 and math.isfinite(confidence)):
        raise ValueError("证据置信度必须介于 0..1")
    if not source_id or len(source_id) > 128 or len(source) > 80:
        raise ValueError("证据来源非法")
    if len(json.dumps(value, ensure_ascii=False)) > 4000:
        raise ValueError("信念内容过大")
    if old is None:
        return BeliefRecord(value, confidence, source, minute, [source_id],
                            [{"value": value, "confidence": confidence, "source": source,
                              "source_id": source_id, "minute": minute}]), "created"
    # 重复事件幂等，不因反复想起同一件事而将其强度放大。
    if source_id in old.sources:
        return old, "duplicate"
    history = (old.history + [{"value": value, "confidence": confidence,
                               "source": source, "source_id": source_id,
                               "minute": minute}])[-24:]
    sources = (old.sources + [source_id])[-128:]
    # 明确的本地观察优先；低质量传闻不能冲掉直接观察。
    if source == "world_observation" and confidence >= 0.9:
        return BeliefRecord(value, confidence, source, minute, sources, history), "observed"
    if value == old.value:
        # 仅独立来源增加确信度，最大 0.95（非直接观察）。
        combined = min(0.95, 1 - (1 - old.confidence) * (1 - confidence))
        return BeliefRecord(value, combined, old.source, minute, sources, history), "reinforced"
    if confidence > old.confidence and old.source != "world_observation":
        return BeliefRecord(value, confidence, source, minute, sources, history), "revised"
    return BeliefRecord(old.value, old.confidence, old.source, minute, sources, history), "contested"
