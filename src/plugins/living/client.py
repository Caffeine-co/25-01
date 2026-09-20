import httpx2
from nonebot.log import logger
from openai import AsyncOpenAI
from src.plugins.living.config import llm_cfg
from src.plugins.living.validate import GroupChatValidate, FriendChatValidate, MemoryValidate, StatusValidate, PreChatValidate
from typing import TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

client = AsyncOpenAI(
    api_key=llm_cfg["api_key"],
    base_url=llm_cfg["base_url"],
    max_retries=0,
    timeout=httpx2.Timeout(**llm_cfg["timeout"])
)

def _responses_schema(validate_model: type[BaseModel]) -> dict:
    """展开本项目非递归模型的引用，避免 anyOf 分支只有 $ref。"""
    schema = validate_model.model_json_schema()
    definitions = schema.get("$defs", {})
    def expand(node, seen: tuple[str, ...] = ()):
        if isinstance(node, list):
            return [expand(item, seen) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/") or ref in seen:
                raise ValueError(f"Unsupported or recursive schema reference: {ref}")
            name = ref.removeprefix("#/$defs/").replace("~1", "/").replace("~0", "~")
            node = {
                **definitions[name],
                **{key: value for key, value in node.items() if key != "$ref"},
            }
            return expand(node, (*seen, ref))
        result = {
            key: expand(value, seen)
            for key, value in node.items()
            if key != "$defs"
        }
        # 字符串 Literal 使用单值 enum，保持取值约束。
        if result.get("type") == "string" and "const" in result:
            result["enum"] = [result.pop("const")]
        return result
    return expand(schema)

async def _openai_chat_completions(message: list, validate_model: type[T], chunks: list[str]) -> T | None:
    async with client.chat.completions.stream(
        model = llm_cfg["model_name"],
        messages = message,
        response_format = validate_model,
        reasoning_effort = llm_cfg["reasoning_effort"]
    ) as stream:
        async for event in stream:
            if event.type == "content.delta":
                chunks.append(event.delta)
        completion = await stream.get_final_completion()
    return completion.choices[0].message.parsed

async def _openai_responses(message: list, validate_model: type[T], chunks: list[str]) -> T | None:
    async with client.responses.stream(
        model = llm_cfg["model_name"],
        input = message,
        # text_format = validate_model,
        text = {"format": {
            "type": "json_schema",
            "name": validate_model.__name__,
            "schema": _responses_schema(validate_model),
            "strict": True,
        }},
        reasoning = {"effort": llm_cfg["reasoning_effort"]},    # type: ignore
        store = False
    ) as stream:
        async for event in stream:
            if event.type == "response.output_text.delta":
                chunks.append(event.delta)
        response = await stream.get_final_response()
    # return response.output_parsed
    return validate_model.model_validate_json(response.output_text)

async def request_llm(message: list, validate_model: type[T]) -> T:
    match llm_cfg["interface_type"]:
        case "openai.responses":
            request_func = _openai_responses
        case "openai.chat.completions":
            request_func = _openai_chat_completions
        case _:
            raise ValueError(f"Unsupported interface type: {llm_cfg['interface_type']}")
    for attempt in range(llm_cfg["retry_times"] + 1):
        chunks: list[str] = []
        try:
            parsed = await request_func(message, validate_model, chunks)
            if parsed is None:
                raise ValueError("Parsing content error")
            return parsed
        except Exception as e:
            if chunks:
                try:
                    return validate_model.model_validate_json("".join(chunks))
                except ValidationError:
                    pass
            if attempt < llm_cfg["retry_times"]:
                logger.exception(f"llm request api failed, retrying {attempt + 1} times: \n{e}")
            else:
                logger.exception(f"llm request api all failed: \n{e}")
    raise RuntimeError("llm request failed")


async def pre_chat_request(message: list) -> dict:
    parsed = await request_llm(message, PreChatValidate)
    return parsed.model_dump(mode="python")

async def chatting_request(message: list, current_session: dict) -> dict:
    if current_session["type"] == "group":
        parsed = await request_llm(message, GroupChatValidate)
    else:
        parsed = await request_llm(message, FriendChatValidate)
    return parsed.model_dump(mode="python")

async def memory_request(message: list) -> dict:
    parsed = await request_llm(message, MemoryValidate)
    return parsed.model_dump(mode="python")

async def status_request(message: list) -> dict:
    parsed = await request_llm(message, StatusValidate)
    return parsed.model_dump(mode="python")