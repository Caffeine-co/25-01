import asyncio
import json
import time
from nonebot import get_bot
from nonebot.adapters.onebot.v11.message import MessageSegment, Message
from nonebot.log import logger
from src.plugins.living.database import record_self_msg, update_user_impression
from src.plugins.living.utils import meta_image_to_temp, temp_image_to_base64, get_meta_image_summary, add_space_after_at
from uuid import uuid5, NAMESPACE_OID


async def handle_and_send_msg(session: dict, message: list) -> None:
    bot = get_bot()
    for i, m in enumerate(message):
        msg_text = ""
        content = ""
        image_names = []
        msg = []
        for j, s in enumerate(m):
            match s["type"]:
                case "text":
                    msg_text += s["data"]["text"]
                    content += s["data"]["text"]
                    msg.append(MessageSegment(type="text", data=s["data"]))
                case "at":
                    at_object = "You" if str(s["data"]["qq"]) == bot.self_id else s["data"]["qq"]
                    content += f"[CQ:at,qq={at_object}]"
                    msg.append(MessageSegment(type=s["type"], data=s["data"]))
                case "reply":
                    content += f"[CQ:reply,id={s['data']['id']}]"
                    msg.append(MessageSegment(type=s["type"], data=s["data"]))
                case "image":
                    temp_name = str(uuid5(NAMESPACE_OID, f"{int(time.time())}_{i}_{j}"))
                    await meta_image_to_temp(s["data"]["image_id"], temp_name)
                    meta_summary = await get_meta_image_summary(s["data"]["image_id"])
                    image_b64 = await temp_image_to_base64(temp_name, True)
                    content += f"[CQ:image,summary={meta_summary}]"
                    image_names.append(temp_name)
                    msg.append(MessageSegment(
                        type="image",
                        data={
                            "file": image_b64,
                            "summary": meta_summary
                        }
                    ))
        await asyncio.sleep(max(len(msg_text)/4, 1))
        msg = add_space_after_at(Message(msg))
        try:
            if session["type"] == "group":
                send_data = await bot.send_group_msg(group_id=session["id"], message=msg)
            else:
                send_data = await bot.send_private_msg(user_id=session["id"], message=msg)
        except Exception as e:
            logger.error(e)
        else:
            await record_self_msg(session, {
                "time": int(time.time()),
                "message_id": send_data["message_id"],
                "content": content,
                "image_data": json.dumps(image_names, ensure_ascii=False)
            })

async def update_friend_impression_in_chat(session: dict, user_impression: list) -> None:
    match session["type"]:
        case "group":
            for user in user_impression:
                for i in user["impression"]:
                    i["type"] = "group"
                    i["group_id"] = session["id"]
                await update_user_impression(user["user_id"], user["impression"], False)
        case _:
            for i in user_impression:
                i["type"] = "friend"
            await update_user_impression(session["id"], user_impression, False)