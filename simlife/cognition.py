"""可选 LLM 认知服务。离线模拟不会自动调用模型。

设计边界：
- 只向模型提供 actor_view（角色可见信息），不传完整世界库存。
- 模型只能提出回复文本和 ActionIntent，不可提交世界状态补丁。
- 所有动作由引擎复核。超时/预算耗尽/非法 JSON 均回退，不破坏世界。
- 同一天（模拟分钟 // 1440）限制模型请求数。请求结果进入事件日志。
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from typing import Any, Protocol
from urllib import request

from .engine import WorldRuntime
from .projection import actor_view
from .memory import retrieve, summarize_known_facts


class Backend(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> str: ...


class OfflineBackend:
    """零成本、非 LLM 的可复现降级响应。"""
    def generate(self, messages: list[dict[str, str]]) -> str:
        return json.dumps({"reply": "我收到了，会再想想怎么处理。", "action": None},
                          ensure_ascii=False)


class ScriptedBackend:
    """用于自动测试：返回指定模型输出，不需要任何网络。"""
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return self.response


class OpenAICompatibleBackend:
    """OpenAI 兼容的 /chat/completions HTTP 调用。

    网络失败应在 CognitionService 层回退；不耦合 SDK 或某一厂商。
    HTTP 是同步的，因此推荐在外部适配层的工作线程中使用，
    不建议在 WorldRuntime.run_until 的模拟事件循环里直接调用。
    """
    def __init__(self, model: str, base_url: str, api_key: str,
                 timeout: float = 20.0):
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url 必须为 http(s) URL")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAICompatibleBackend":
        return cls(model=os.environ["WORLDLIFE_LLM_MODEL"],
                   base_url=os.environ.get("WORLDLIFE_LLM_BASE_URL", "https://api.openai.com/v1"),
                   api_key=os.environ["WORLDLIFE_LLM_API_KEY"])

    def generate(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({"model": self.model, "messages": messages,
                              "temperature": 0.3,
                              "response_format": {"type": "json_object"}}).encode()
        req = request.Request(self.url, data=payload, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        with request.urlopen(req, timeout=self.timeout) as response:
            result = json.loads(response.read(2_000_000))
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("模型未返回字符串内容")
        return content


@dataclass(frozen=True)
class Reply:
    text: str
    action_accepted: bool
    reason: str
    model_used: bool


def validate_response(raw: str) -> tuple[str, tuple[str, str] | None]:
    """结构化输出检查。宽松接受具体语言，严格检查动作形式。"""
    if len(raw) > 30_000:
        raise ValueError("模型输出长度超限")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) - {"reply", "action"}:
        raise ValueError("只允许 reply 和 action 两个字段")
    reply = value.get("reply")
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 2000:
        raise ValueError("reply 必须是长度 1~2000 的文本")
    action = value.get("action")
    if action is None:
        return reply, None
    if (not isinstance(action, dict) or set(action) != {"kind", "target"}
            or not isinstance(action["kind"], str)
            or not isinstance(action["target"], str)
            or len(action["target"]) > 128):
        raise ValueError("action 必须是 {kind,target} 或 null")
    if action["kind"] not in {"move", "use", "practice", "assist", "socialize"}:
        raise ValueError("action.kind 不在许可列表中")
    return reply, (action["kind"], action["target"])


class CognitionService:
    def __init__(self, backend: Backend | None = None, max_calls_per_day: int = 4):
        self.backend = backend or OfflineBackend()
        self.max_calls_per_day = max_calls_per_day
        if max_calls_per_day < 0:
            raise ValueError("max_calls_per_day 不能为负")

    def interact(self, world: WorldRuntime, actor: str, author: str, text: str) -> Reply:
        """由外部平台主动调用，不在自主模拟每轮运行时调用。"""
        if actor not in world.lives or not text or len(text) > 4000:
            raise ValueError("人物不存在或消息非法")
        world.receive_message(actor, author, text)
        persona = world.scenario.personas[actor]
        if isinstance(self.backend, OfflineBackend):
            answer, _ = validate_response(self.backend.generate([]))
            world.log("character_spoke", actor, text=answer, mode="offline")
            return Reply(answer, False, "offline", False)
        day = world.minute // 1440
        budget_key = f"{actor}:{day}"
        used = world.cognition_usage.get(budget_key, 0)
        if used >= self.max_calls_per_day:
            world.log("cognition_fallback", actor, reason="daily_budget")
            reply = OfflineBackend().generate([])
            answer, _ = validate_response(reply)
            world.log("character_spoke", actor, text=answer, mode="offline")
            return Reply(answer, False, "daily_budget", False)
        view = actor_view(world, actor)
        view["relevant_memories"] = [
            {"minute": m.minute, "kind": m.kind, "text": m.text,
             "source": m.source} for m in retrieve(world.lives[actor], text, world.minute)]
        view["known_facts"] = summarize_known_facts(world.lives[actor])
        system = ("你是虚拟人物的受约束认知模块。根据给定的可见信息与人物设定，"
                  "返回严格 JSON 对象 {reply:字符串, action:null或{kind:字符串,target:字符串}}。"
                  "不要臆造已经发生的行动，不要声称改变世界库存或位置。"
                  "仅可建议 move/use/practice/assist/socialize；也允许 action:null。"
                  "这些都是建议，程序会独立验证。人物个人设定：" + persona.biography)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(
                        {"visible_state": view, "incoming_message": {"from": author, "text": text}},
                        ensure_ascii=False)}]
        world.cognition_usage[budget_key] = used + 1  # 失败调用也计入次数，防止重试风暴。
        try:
            output = self.backend.generate(messages)
            answer, intent = validate_response(output)
        except (ValueError, KeyError, TypeError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            world.log("cognition_fallback", actor, reason=type(exc).__name__)
            answer, intent = validate_response(OfflineBackend().generate([]))
            world.log("character_spoke", actor, text=answer, mode="offline")
            return Reply(answer, False, "invalid_response_or_transport_error", False)
        accepted = False
        reason = "no_action"
        if intent is not None:
            accepted, reason = world.submit_intent(actor, intent[0], intent[1])
        world.log("cognition_proposal", actor, intent=intent, accepted=accepted, reason=reason)
        world.log("character_spoke", actor, text=answer, mode="model")
        return Reply(answer, accepted, reason, True)
