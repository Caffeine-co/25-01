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
from .model import Memory


def bounded_view(world: WorldRuntime, actor: str) -> dict:
    """只取与人物有关的有界上下文，控制 Token 花费/泄露范围。"""
    view = actor_view(world, actor)
    recent_props = sorted(view.get("propositions", {}).items(),
                          key=lambda x: x[1].get("updated_at", 0), reverse=True)[:20]
    view["propositions"] = dict(recent_props)
    view["known_facilities"] = dict(list(view.get("known_facilities", {}).items())[:40])
    view["relationships"] = dict(list(view.get("relationships", {}).items())[:25])
    view["projects"] = dict(list(view.get("projects", {}).items())[:20])
    # 作为成本护栏，避免单次模型请求装载无界人物内容。
    if len(json.dumps(view, ensure_ascii=False)) > 15_000:
        view["propositions"] = dict(recent_props[:5])
        view["memories"] = view.get("memories", [])[-3:]
    return view


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
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("base_url 必须为 http(s) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("外部模型 API 必须使用 HTTPS；HTTP 仅允许本机")
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
        view = bounded_view(world, actor)
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


def validate_reflection(raw: str) -> dict:
    """反思只接受文本和可检查的项目提议；不会产生世界状态补丁。"""
    if len(raw) > 20_000:
        raise ValueError("反思内容过大")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) - {"reflection", "project"}:
        raise ValueError("反思 JSON 字段非法")
    thought = obj.get("reflection")
    if not isinstance(thought, str) or not 1 <= len(thought.strip()) <= 1200:
        raise ValueError("reflection 需要一段简短文本")
    proposal = obj.get("project")
    if proposal is not None:
        if not isinstance(proposal, dict) or set(proposal) - {
                "id", "steps", "priority", "start_minute", "deadline"}:
            raise ValueError("项目建议字段非法")
        if not isinstance(proposal.get("steps"), list) or len(proposal["steps"]) > 20:
            raise ValueError("项目建议必须包含可执行步骤")
    return obj


def reflect(service: CognitionService, world: WorldRuntime, actor: str) -> dict:
    """主动认知入口：每日最多一次，失败时不会产生可执行决定。

    不在 WorldRuntime.run_until 内同步请求 HTTP。由服务层显式调度，
    测试可用 ScriptedBackend 完全离线复现。
    """
    if actor not in world.lives:
        raise ValueError("人物不存在")
    if isinstance(service.backend, OfflineBackend):
        return {"status": "offline", "project_accepted": False}
    day = world.minute // 1440
    flag = f"reflection:{actor}:{day}"
    if world.cognition_usage.get(flag):
        return {"status": "already_reflected", "project_accepted": False}
    budget_key = f"{actor}:{day}"
    used = world.cognition_usage.get(budget_key, 0)
    if used >= service.max_calls_per_day:
        return {"status": "daily_budget", "project_accepted": False}
    world.cognition_usage[budget_key] = used + 1
    world.cognition_usage[flag] = 1
    view = bounded_view(world, actor)
    # 把记忆限定为角色自己的经历，避免向模型暴露其他角色的私有状态。
    view["relevant_memories"] = [m.text for m in retrieve(
        world.lives[actor], "目标 计划 最近经历", world.minute, limit=10)]
    messages = [
        {"role": "system", "content":
         "你是虚拟人物的受约束反思模块。请输出 JSON："
         "{reflection:简短的一人称主观反思,project:null或{id,steps:[{kind,target}],priority}}。"
         "只有列出的动作/设施可以用于项目：move,use,practice,assist,socialize。"
         "禁止宣称已经完成未执行的行动；反思只是假说，不是世界事实。"},
        {"role": "user", "content": json.dumps(view, ensure_ascii=False)},
    ]
    try:
        result = validate_reflection(service.backend.generate(messages))
    except (ValueError, KeyError, TypeError, OSError, TimeoutError) as exc:
        world.log("reflection_failed", actor, reason=type(exc).__name__)
        return {"status": "invalid_or_network_error", "project_accepted": False}
    from .planning import project_from_dict
    project_accepted = False
    project_reason = None
    if result.get("project") is not None:
        try:
            raw = dict(result["project"])
            raw.setdefault("start_minute", world.minute)
            project = project_from_dict(raw)
            world.add_project(actor, project)
            project_accepted = True
        except (KeyError, ValueError, TypeError) as exc:
            project_reason = str(exc)[:150]
            world.log("reflection_project_denied", actor, reason=project_reason)
    world.lives[actor].add_memory(Memory(
        world.minute, "reflection", result["reflection"], salience=0.65,
        source="llm_inference"))
    world.log("reflection_recorded", actor, project_accepted=project_accepted)
    return {"status": "reflected", "reflection": result["reflection"],
            "project_accepted": project_accepted, "project_reason": project_reason}
