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

async def request_llm(message: list, validate_model: type[T]) -> T:
    for attempt in range(llm_cfg["retry_times"] + 1):
        raw_content = ""
        try:
            async with client.chat.completions.stream(
                    model=llm_cfg["model_name"],
                    messages=message,
                    response_format=validate_model,
                    reasoning_effort=llm_cfg["reasoning_effort"],
            ) as stream:
                async for event in stream:
                    if event.type == "content.delta":
                        raw_content += event.delta
                completion = await stream.get_final_completion()
            parsed = completion.choices[0].message.parsed
            if parsed is None:
                raise ValueError("Parsing content error")
            return parsed
        except Exception as e:
            if raw_content:
                try:
                    return validate_model.model_validate_json(raw_content)
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