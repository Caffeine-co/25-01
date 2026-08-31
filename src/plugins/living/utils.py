import aiofiles
import base64
import httpx
import json
import os
from datetime import datetime, timezone, timedelta
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.onebot.v11.utils import unescape
from nonebot.adapters.onebot.v11.message import Message, MessageSegment
from pathlib import Path
from src.plugins.living.config import setting_cfg, chat_cfg
from typing import Any


def level_text(value: int) -> str:
    match value:
        case value if value <= 10:
            return "极低"
        case value if value <= 30:
            return "较低"
        case value if value <= 50:
            return "中等偏低"
        case value if value <= 70:
            return "中等偏高"
        case value if value <= 90:
            return "较高"
        case _:
            return "极高"

def cap_weekday(weekday: int) -> str:
    match weekday:
        case 1:
            return "一"
        case 2:
            return "二"
        case 3:
            return "三"
        case 4:
            return "四"
        case 5:
            return "五"
        case 6:
            return "六"
        case _:
            return "日"

def ts_to_time(ts: int) -> datetime:
    tz = timezone(timedelta(hours=setting_cfg["tz_offset"]))
    dt = datetime.fromtimestamp(ts, tz=tz)
    return dt

def add_space_after_at(msg: Message) -> Message:
    for i, d in reversed(list(enumerate(msg))):
        if d.type == "at":
            msg.insert(i + 1, MessageSegment.text(" "))
    return msg

def check_null_msg(msg: Message) -> bool:
    null_text_num = sum(1 for seg in msg if seg.type == "text" and seg.data["text"] == "")
    seg_length = len(msg)
    return null_text_num == seg_length

def read_txt_sync(path: str | Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

async def read_txt_async(path: str | Path) -> str:
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        return await f.read()

async def write_txt_async(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.resolve().mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)

async def read_json_async(path: str | Path) -> Any:
    content = await read_txt_async(path)
    return json.loads(content)

async def write_json(path: str | Path, content: Any) -> None:
    path = Path(path)
    path.parent.resolve().mkdir(parents=True, exist_ok=True)
    content = json.dumps(content, ensure_ascii=False, indent=2)
    await write_txt_async(path, content)

async def download_image_to_temp(url: str, temp_name: str) -> None:
    Path(chat_cfg["temp_image_dir"]).mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        async with aiofiles.open(f"{chat_cfg['temp_image_dir']}/{temp_name}", "wb") as f:
            async for chunk in response.aiter_bytes(chunk_size=1024):
                await f.write(chunk)

async def get_meta_image_filename(meta_id: int) -> str:
    image_metadata = await read_json_async(chat_cfg["image_metadata_path"])
    return next(
        i["file_name"]
        for i in image_metadata
        if meta_id == i["image_id"]
    )

async def meta_image_to_temp(meta_id: int, temp_name: str) -> None:
    meta_name = await get_meta_image_filename(meta_id)
    async with aiofiles.open(f"{chat_cfg['meta_image_dir']}/{meta_name}", "rb") as f:
        image = await f.read()
    Path(chat_cfg["temp_image_dir"]).mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(f"{chat_cfg['temp_image_dir']}/{temp_name}", "wb") as f:
        await f.write(image)

async def delete_temp_image(temp_name: str) -> None:
    try:
        os.remove(f"{chat_cfg['temp_image_dir']}/{temp_name}")
    except:
        pass

async def temp_image_to_base64(temp_name: str, b64_mark: bool) -> str:
    async with aiofiles.open(f"{chat_cfg['temp_image_dir']}/{temp_name}", "rb") as f:
        data = await f.read()
        image = base64.b64encode(data).decode("utf-8")   # utf-8/ascii
    if b64_mark:
        return f"base64://{image}"
    else:
        return image

async def get_meta_image_summary(meta_id: int) -> str:
    image_metadata = await read_json_async(chat_cfg["image_metadata_path"])
    return next(
        (
            i["summary"]
            for i in image_metadata
            if meta_id == i["image_id"]
        ),
        "图片"
    )

async def format_received_msg(message: Message, self_id: int | str) -> tuple[str,list]:
    content = ""
    image_urls = []
    for seg in message:
        match seg.type:
            case "text":
                content += seg.data["text"]
            case "face":
                content += f"[CQ:face,id={seg.data.get('id')}]"
            case "image":
                if chat_cfg["enable_vision"]:
                    image_urls.append(seg.data.get("url"))
                if summary := seg.data.get("summary"):
                    if summary == "[动画表情]":
                        content += "[CQ:image,summary=[动画表情]]"
                    else:
                        content += f"[CQ:image,summary={summary}]"
                else:
                    content += "[CQ:image]"
            case "record":
                content += "[CQ:record]"
            case "video":
                content += "[CQ:video]"
            case "at":
                at_object = "You" if seg.data.get("qq") == str(self_id) else seg.data.get("qq")
                content += f"[CQ:at,qq={at_object}]"
            case "reply":
                content += f"[CQ:reply,id={seg.data.get('id')}]"
            case "forward":
                content += f"[CQ:forward,id={seg.data.get('id')}]"
            case "json":
                try:
                    json_data = seg.data.get("data", "{}")
                    json_str = unescape(json_data)
                    json_dict = json.loads(json_str)
                    app_val = json_dict.get("app", "unknown")
                    prompt_val = json_dict.get("prompt", "")
                    content += f'[CQ:json,data={{"app":"{app_val}","prompt":"{prompt_val}"}}]'
                except:
                    content += "[CQ:json,data=error]"
            case "file":
                content += f"[CQ:file,file={seg.data.get('file')}]"
            case _:
                content += f"[CQ:{seg.type}]"
    return content, image_urls

async def format_self_msg(message: list, self_id: int | str) -> str:
    content = ""
    for seg in message:
        match seg["type"]:
            case "text":
                content += seg["data"]["text"]
            case "at":
                at_object = "SELF" if seg["data"]["qq"] == str(self_id) else seg["data"]["qq"]
                content += f"[CQ:at,qq={at_object}]"
            case "reply":
                content += f"[CQ:reply,id={seg['data']['id']}]"
            case "image":
                summary = await get_meta_image_summary(seg["data"]["image_id"])
                content += f"[CQ:image,summary={summary}]"
    return content