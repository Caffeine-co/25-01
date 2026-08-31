import asyncio
from nonebot.log import logger
from openai import AsyncOpenAI
from src.plugins.living.config import llm_cfg
from src.plugins.living.validate import GroupChatValidate, FriendChatValidate, MemoryValidate, StatusValidate, PreChatValidate
from typing import TypeVar
from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)

client = AsyncOpenAI(
    api_key=llm_cfg["api_key"],
    base_url=llm_cfg["base_url"],
)

async def request_llm(message: list, validate_model: type[T]) -> T:
    completion = await client.chat.completions.parse(
        model=llm_cfg["model_name"],
        messages=message,
        response_format=validate_model,
        reasoning_effort=llm_cfg["reasoning_effort"],
    )
    if not completion.choices[0].message.parsed:
        refusal = completion.choices[0].message.refusal
        raise ValueError(f"model didn't return resolvable content: {refusal!r}")
    return completion.choices[0].message.parsed

async def pre_chat_request(message: list) -> dict:
    for i in range(llm_cfg["retry_times"] + 1):
        try:
            parsed = await asyncio.wait_for(
                request_llm(message, PreChatValidate),
                timeout=llm_cfg["timeout"]
            )
        except Exception as e:
            if i < llm_cfg["retry_times"]:
                logger.error(f"pre_chat request llm api failed, retrying {i + 1} times: \n{e}")
            else:
                logger.error(f"pre_chat request llm api failed completely: \n{e}")
        else:
            return parsed.model_dump(mode="python")
    raise RuntimeError

async def chatting_request(message: list, current_session: dict) -> dict:
    for i in range(llm_cfg["retry_times"] + 1):
        try:
            if current_session["type"] == "group":
                parsed = await asyncio.wait_for(
                    request_llm(message, GroupChatValidate),
                    timeout=llm_cfg["timeout"]
                )
            else:
                parsed = await asyncio.wait_for(
                    request_llm(message, FriendChatValidate),
                    timeout=llm_cfg["timeout"]
                )
        except Exception as e:
            if i < llm_cfg["retry_times"]:
                logger.error(f"chatting request llm api failed, retrying {i + 1} times\n{e}")
            else:
                logger.error(f"chatting request llm api failed completely: \n{e}")
        else:
            return parsed.model_dump(mode="python")
    raise RuntimeError

async def memory_request(message: list) -> dict:
    for i in range(llm_cfg["retry_times"] + 1):
        try:
            parsed = await asyncio.wait_for(
                request_llm(message, MemoryValidate),
                timeout=llm_cfg["timeout"]
            )
        except Exception as e:
            if i < llm_cfg["retry_times"]:
                logger.error(f"memory request llm api failed, retrying {i + 1} times\n{e}")
            else:
                logger.error(f"memory request llm api failed completely: \n{e}")
        else:
            return parsed.model_dump(mode="python")
    raise RuntimeError

async def status_request(message: list) -> dict:
    for i in range(llm_cfg["retry_times"] + 1):
        try:
            parsed = await asyncio.wait_for(
                request_llm(message, StatusValidate),
                timeout=llm_cfg["timeout"]
            )
        except Exception as e:
            if i < llm_cfg["retry_times"]:
                logger.error(f"status request llm api failed, retrying {i + 1} times\n{e}")
            else:
                logger.error(f"status request llm api failed completely: \n{e}")
        else:
            return parsed.model_dump(mode="python")
    raise RuntimeError