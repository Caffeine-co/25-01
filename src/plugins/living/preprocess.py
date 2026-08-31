import json
import time
from src.plugins.living.config import setting_cfg, chat_cfg
from src.plugins.living.database import get_group_info, get_group_msg_list, get_latest_group_msg, get_group_impression, get_friend_info, get_latest_friend_msg, get_friend_msg_list, get_user_portrait, get_user_impression, get_user_memory, get_user_all_memory
from src.plugins.living.utils import read_txt_async, ts_to_time, cap_weekday, temp_image_to_base64, level_text, read_json_async
from src.plugins.living.validate import CharacterStatus


prompt = setting_cfg["prompt"]

async def init_content_location() -> str:
    location_list = await read_json_async(chat_cfg["location_path"])
    content = [
        "# Location 补充",
        "- 以下为有限的`new_status.current_location`备选值，超出此备选范围时可自行拟定："
    ]
    for l in location_list:
        content.append(f"  - {l}")
    return "\n".join(content)

async def init_content_image() -> str:
    meta_image_list = await read_json_async(chat_cfg["image_metadata_path"])
    content = [
        "# Image 补充",
        "- 以下为消息段`\"type\": \"image\"`可选的图片列表："
    ]
    for i in meta_image_list:
        content.append(f"  - [image_id: {i['image_id']}] {i['type']}，{i['summary']}")
    return "\n".join(content)

async def init_content_status(status: CharacterStatus) -> str:
    content = [
        "# 历史角色状态",
        f"- 更新时间：{status.current_time}",

        "## 当前事件与情境",
        f"- 当前具体位置：{status.current_location}",
        f"- 当前正在进行的活动：{status.current_activity}",
        f"- 当前事件或情境：{status.current_situation}",

        "## 当前环境条件",
        f"- 当前环境舒适程度：{status.environmental_comfort}/100（{level_text(status.environmental_comfort)}）",
        f"- 当前隐私程度：{status.privacy_level}/100（{level_text(status.privacy_level)}）",
        f"- 环境噪声强度：{status.noise_level}/100（{level_text(status.noise_level)}）",
        f"- 周围人群密集程度：{status.crowd_density}/100（{level_text(status.crowd_density)}）",

        "## 当前基础生理状态",
        f"- 当前精力：{status.energy_level}/100（{level_text(status.energy_level)}）",
        f"- 体力与耐久度：{status.physical_stamina}/100（{level_text(status.physical_stamina)}）",
        f"- 身体疲劳程度：{status.fatigue_level}/100（{level_text(status.fatigue_level)}）",
        f"- 当前困倦程度：{status.sleepiness_level}/100（{level_text(status.sleepiness_level)}）",
        f"- 饥饿程度：{status.hunger_level}/100（{level_text(status.hunger_level)}）",
        f"- 口渴程度：{status.thirst_level}/100（{level_text(status.thirst_level)}）",
        f"- 进食欲望：{status.appetite_level}/100（{level_text(status.appetite_level)}）",
        f"- 疼痛程度：{status.pain_level}/100（{level_text(status.pain_level)}）",
        f"- 当前身体负担：{status.physical_strain}/100（{level_text(status.physical_strain)}）",

        "## 睡眠、恢复与生理节律",
        f"- 最近一次睡眠质量：{status.sleep_quality}/100（{level_text(status.sleep_quality)}）",
        f"- 累积睡眠不足程度：{status.sleep_debt}/100（{level_text(status.sleep_debt)}）",
        f"- 昼夜节律稳定程度：{status.circadian_stability}/100（{level_text(status.circadian_stability)}）",
        f"- 当前体温：{status.body_temperature_c}°C",
        f"- 身体恢复能力：{status.recovery_capacity}/100（{level_text(status.recovery_capacity)}）",
        f"- 营养充足与均衡程度：{status.nutrition_status}/100（{level_text(status.nutrition_status)}）",
        f"- 身体水分状态：{status.hydration_level}/100（{level_text(status.hydration_level)}）",
        f"- 身体兴奋与警觉程度：{status.physiological_arousal}/100（{level_text(status.physiological_arousal)}）",
        f"- 感官刺激过载程度：{status.sensory_overload}/100（{level_text(status.sensory_overload)}）",

        "## 当前情绪状态",
        f"- 快乐与愉悦感：{status.joy}/100（{level_text(status.joy)}）",
        f"- 平静程度：{status.calmness}/100（{level_text(status.calmness)}）",
        f"- 悲伤感：{status.sadness}/100（{level_text(status.sadness)}）",
        f"- 焦虑与不安：{status.anxiety}/100（{level_text(status.anxiety)}）",
        f"- 愤怒程度：{status.anger}/100（{level_text(status.anger)}）",
        f"- 恐惧程度：{status.fear}/100（{level_text(status.fear)}）",
        f"- 希望感：{status.hope}/100（{level_text(status.hope)}）",
        f"- 羞耻与难堪感：{status.shame}/100（{level_text(status.shame)}）",
        f"- 主观孤独感：{status.loneliness}/100（{level_text(status.loneliness)}）",
        f"- 主观归属感：{status.belongingness}/100（{level_text(status.belongingness)}）",
        f"- 当前情绪稳定程度：{status.emotional_stability}/100（{level_text(status.emotional_stability)}）",
        f"- 当前情绪整体强度：{status.emotional_intensity}/100（{level_text(status.emotional_intensity)}）",

        "## 当前认知状态",
        f"- 可分配的注意力：{status.attention_capacity}/100（{level_text(status.attention_capacity)}）",
        f"- 持续专注能力：{status.concentration}/100（{level_text(status.concentration)}）",
        f"- 思维清晰程度：{status.mental_clarity}/100（{level_text(status.mental_clarity)}）",
        f"- 当前工作记忆能力：{status.working_memory_capacity}/100（{level_text(status.working_memory_capacity)}）",
        f"- 思维切换与调整能力：{status.cognitive_flexibility}/100（{level_text(status.cognitive_flexibility)}）",
        f"- 计划和执行控制能力：{status.executive_function}/100（{level_text(status.executive_function)}）",
        f"- 做出决定的速度：{status.decision_speed}/100（{level_text(status.decision_speed)}）",
        f"- 对自身判断的信心：{status.judgment_confidence}/100（{level_text(status.judgment_confidence)}）",
        f"- 对自身状态的觉察程度：{status.self_awareness}/100（{level_text(status.self_awareness)}）",
        f"- 反复思考负面内容的程度：{status.rumination_level}/100（{level_text(status.rumination_level)}）",

        "## 自我认知状态",
        f"- 自我价值感：{status.self_esteem}/100（{level_text(status.self_esteem)}）",
        f"- 对自身能力的信心：{status.self_efficacy}/100（{level_text(status.self_efficacy)}）",
        f"- 对未来的信心与确定感：{status.future_confidence}/100（{level_text(status.future_confidence)}）",
        f"- 对生活和行动的意义感：{status.sense_of_meaning}/100（{level_text(status.sense_of_meaning)}）",

        "## 当前行为动机",
        f"- 内在动机：{status.intrinsic_motivation}/100（{level_text(status.intrinsic_motivation)}）",
        f"- 外部奖励驱动：{status.extrinsic_motivation}/100（{level_text(status.extrinsic_motivation)}）",
        f"- 成就需求：{status.achievement_motivation}/100（{level_text(status.achievement_motivation)}）",
        f"- 建立和维持关系的需求：{status.affiliation_need}/100（{level_text(status.affiliation_need)}）",
        f"- 获得认可的需求：{status.approval_need}/100（{level_text(status.approval_need)}）",
        f"- 自主决定的需求：{status.autonomy_need}/100（{level_text(status.autonomy_need)}）",
        f"- 创作与表达欲望：{status.creative_drive}/100（{level_text(status.creative_drive)}）",
        f"- 回避困难和压力的倾向：{status.avoidance_tendency}/100（{level_text(status.avoidance_tendency)}）",

        "## 稳定人格与行为倾向",
        f"- 开放性：{status.openness}/100（{level_text(status.openness)}）",
        f"- 尽责性：{status.conscientiousness}/100（{level_text(status.conscientiousness)}）",
        f"- 外向性：{status.extraversion}/100（{level_text(status.extraversion)}）",
        f"- 宜人性：{status.agreeableness}/100（{level_text(status.agreeableness)}）",
        f"- 情绪反应敏感程度：{status.emotional_reactivity}/100（{level_text(status.emotional_reactivity)}）",
        f"- 冲动倾向：{status.impulsivity}/100（{level_text(status.impulsivity)}）",
        f"- 耐心程度：{status.patience}/100（{level_text(status.patience)}）",
        f"- 面对挫折的恢复能力：{status.resilience}/100（{level_text(status.resilience)}）",
        f"- 对变化的适应能力：{status.adaptability}/100（{level_text(status.adaptability)}）",
        f"- 完美主义倾向：{status.perfectionism}/100（{level_text(status.perfectionism)}）",
        f"- 风险容忍程度：{status.risk_tolerance}/100（{level_text(status.risk_tolerance)}）",

        "## 心理负荷与调节能力",
        f"- 累积心理压力：{status.accumulated_stress}/100（{level_text(status.accumulated_stress)}）",
        f"- 情绪耗竭程度：{status.emotional_exhaustion}/100（{level_text(status.emotional_exhaustion)}）",
        f"- 倦怠风险：{status.burnout_risk}/100（{level_text(status.burnout_risk)}）",
        f"- 对负面刺激的敏感程度：{status.trigger_sensitivity}/100（{level_text(status.trigger_sensitivity)}）",
        f"- 调节压力和情绪的能力：{status.coping_capacity}/100（{level_text(status.coping_capacity)}）",
        f"- 人际依恋安全感：{status.attachment_security}/100（{level_text(status.attachment_security)}）",

        "## 当前人际关系状态",
        f"- 家庭关系亲密程度：{status.family_closeness}/100（{level_text(status.family_closeness)}）",
        f"- 友情关系总体亲密程度：{status.friendship_closeness}/100（{level_text(status.friendship_closeness)}）",
        f"- 对他人的总体信任程度：{status.interpersonal_trust}/100（{level_text(status.interpersonal_trust)}）",
        f"- 客观社会联系充足程度：{status.social_connectedness}/100（{level_text(status.social_connectedness)}）",
        f"- 对他人的依赖程度：{status.interpersonal_dependency}/100（{level_text(status.interpersonal_dependency)}）",
        f"- 当前人际紧张程度：{status.interpersonal_tension}/100（{level_text(status.interpersonal_tension)}）",
        f"- 当前可用于社交的精力：{status.social_energy}/100（{level_text(status.social_energy)}）",
        f"- 可获得的情感支持：{status.emotional_support}/100（{level_text(status.emotional_support)}）",

        "## 当前现实约束",
        f"- 当前可自由支配时间：{status.available_time}/100（{level_text(status.available_time)}）",
        f"- 日程紧张程度：{status.schedule_pressure}/100（{level_text(status.schedule_pressure)}）",
        f"- 当前责任和任务负担：{status.obligation_load}/100（{level_text(status.obligation_load)}）"
    ]
    return "\n".join(content)

async def init_content_preview() -> str:
    content = ["# 消息主页"]
    run_mode = chat_cfg["run_mode"]
    for session in chat_cfg[f"{run_mode}s"]:
        if session["type"] == "group":
            group_info = await get_group_info(session["id"])
            content.extend([
                f"## {group_info.get("group_name", "未知")}",
                "- 类型：群聊",
                f"- ID：{session['id']}",
                f"- 人数：{group_info.get("member_count", "未知")}"
            ])
            latest_msg = await get_latest_group_msg(session["id"])
            if latest_msg:
                if latest_msg["from_me"]:
                    content.append(f"- 消息预览：[{ts_to_time(latest_msg['time'])}]{latest_msg['content']}")
                else:
                    content.append(f"- 消息预览：[{ts_to_time(latest_msg['time'])}][{latest_msg['nickname']}]{latest_msg['content']}")
            else:
                content.append("- 消息预览：无")
            msg_list = await get_group_msg_list(session["id"])
            content.append(f"- 未读消息：{len(msg_list['unread_msg'])}")
            group_impression = await get_group_impression(session["id"])
            if group_impression:
                content.extend([
                    "- 群聊印象：\n",
                    "|时间|内容|",
                    "|-|-|"
                ])
                for i in group_impression:
                    content.append(f"|{i['time']}|{i['content']}|")
            else:
                content.append("- 群聊印象：无")
        else:
            friend_info = await get_friend_info(session["id"])
            content.extend([
                f"## {friend_info.get('nickname', '未知')}",
                "- 类型：好友",
                f"- ID：{session['id']}"
            ])
            latest_msg = await get_latest_friend_msg(session["id"])
            if latest_msg:
                content.append(f"- 消息预览：[{ts_to_time(latest_msg['time'])}]{latest_msg['content']}")
            else:
                content.append("- 消息预览：无")
            msg_list = await get_friend_msg_list(session["id"])
            content.append(f"- 未读消息：{len(msg_list['unread_msg'])}")
            user_portrait = await get_user_portrait(session["id"])
            if user_portrait:
                content.append(f"- 用户画像：{user_portrait}")
            else:
                content.append("- 用户画像：无")
    return "\n".join(content)

async def init_content_session(session: dict) -> tuple[list, list]:
    session_content = ["# 当前聊天"]
    if session["type"] == "group":
        group_info = await get_group_info(session["id"])
        session_content.extend([
            "## 信息",
            f"- 名称：{group_info.get('group_name', '未知')}",
            f"- ID：{session['id']}",
            "- 类型：群聊",
            f"- 人数：{group_info.get('member_count', '未知')}"
        ])
        group_impression = await get_group_impression(session["id"])
        if group_impression:
            session_content.extend([
                "## 群聊印象",
                "|时间|内容|",
                "|-|-|"
            ])
            for i in group_impression:
                session_content.append(f"|{i['time']}|{i['content']}|")
        else:
            session_content.extend([
                "## 群聊印象",
                "- 无"
            ])
        msg_list = await get_group_msg_list(session["id"])
        user_list = []
        for read_msg in msg_list["read_msg"]:
            if read_msg["user_id"]:
                user_list.append(read_msg["user_id"])
        for unread_msg in msg_list["unread_msg"]:
            if unread_msg["user_id"]:
                user_list.append(unread_msg["user_id"])
        user_list = list(dict.fromkeys(user_list))
        session_content.append("## 成员记忆")
        if user_list:
            for user_id in user_list:
                session_content.append(f"- ID：{user_id}")
                user_portrait = await get_user_portrait(user_id)
                if user_portrait:
                    session_content.append(f"  - 画像：{user_portrait}")
                else:
                    session_content.append("  - 画像：无")
                user_memory = await get_user_memory(user_id)
                if user_memory:
                    session_content.extend([
                        "  - 记忆：\n",
                        "  |时间|来源|群ID|内容|",
                        "  |-|-|-|-|"
                    ])
                    for memory in user_memory:
                        if memory["type"] == "group":
                            session_content.append(f"  |{memory['time']}|群聊|{memory['group_id']}|{memory['content']}|")
                        else:
                            session_content.append(f"  |{memory['time']}|私聊|/|{memory['content']}|")
                else:
                    session_content.append("  - 记忆：无")
                user_impression = await get_user_impression(user_id)
                if user_impression:
                    session_content.extend([
                        "  - 印象：\n",
                        "  |时间|来源|群ID|内容|",
                        "  |-|-|-|-|"
                    ])
                    for impression in user_impression:
                        if impression["type"] == "group":
                            session_content.append(f"  |{impression['time']}|群聊|{impression['group_id']}|{impression['content']}|")
                        else:
                            session_content.append(f"  |{impression['time']}|私聊|/|{impression['content']}|")
                else:
                    session_content.append("  - 印象：无")
        else:
            session_content.append("- 无")
    else:
        msg_list = await get_friend_msg_list(session["id"])
        friend_info = await get_friend_info(session["id"])
        session_content.extend([
            "## 信息",
            f"- 名称：{friend_info.get('nickname', '未知')}",
            f"- ID：{session['id']}",
            "- 类型：好友"
        ])
        session_content.append("## 用户记忆")
        user_portrait = await get_user_portrait(session["id"])
        if user_portrait:
            session_content.append(f"- 画像：{user_portrait}")
        else:
            session_content.append(f"- 画像：无")
        user_memory = await get_user_memory(session["id"])
        if user_memory:
            session_content.extend([
                "- 记忆：\n",
                "|时间|来源|群ID|内容|",
                "|-|-|-|-|"
            ])
            for memory in user_memory:
                if memory["type"] == "group":
                    session_content.append(f"|{memory['time']}|群聊|{memory['group_id']}|{memory['content']}|")
                else:
                    session_content.append(f"|{memory['time']}|私聊|/|{memory['content']}|")
        else:
            session_content.append("- 记忆：无")
        user_impression = await get_user_impression(session["id"])
        if user_impression:
            session_content.extend([
                "- 印象：\n",
                "|时间|来源|群ID|内容|",
                "|-|-|-|-|"
            ])
            for impression in user_impression:
                if impression["type"] == "group":
                    session_content.append(f"|{impression['time']}|群聊|{impression['group_id']}|{impression['content']}|")
                else:
                    session_content.append(f"|{impression['time']}|私聊|/|{impression['content']}|")
        else:
            session_content.append("- 印象：无")
    content = [
        {"type": "text", "text": "\n".join(session_content)},
        {"type": "text", "text": "## 消息列表"}
    ]
    unread_msg_id_list = []
    if session["type"] == "group":
        content.append({
            "type": "text",
            "text": "- 示例：[时间]|[消息ID]|[用户ID]|[用户昵称]|内容"
        })
        for read_msg in msg_list["read_msg"]:
            if read_msg["from_me"]:
                content.append({
                    "type": "text",
                    "text": f"- [{ts_to_time(read_msg['time'])}]|[{read_msg['message_id']}]|[SELF]|{read_msg['content']}"
                })
            else:
                content.append({
                    "type": "text",
                    "text": f"- [{ts_to_time(read_msg['time'])}]|[{read_msg['message_id']}]|[{read_msg['user_id']}]|[{read_msg['nickname']}]|{read_msg['content']}"
                })
            if chat_cfg["enable_vision"]:
                temp_image_list = json.loads(read_msg["image_data"])
                for image in temp_image_list:
                    try:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url":  f"data:image/jpeg;base64,{await temp_image_to_base64(image, False)}"
                            }
                        })
                    except:
                        pass
        content.append({"type": "text", "text": "=== 新消息 ==="})
        if msg_list["unread_msg"]:
            for unread_msg in msg_list["unread_msg"]:
                unread_msg_id_list.append(unread_msg["message_id"])
                content.append({
                    "type": "text",
                    "text": f"- [{ts_to_time(unread_msg['time'])}]|[{unread_msg['message_id']}]|[{unread_msg['user_id']}]|[{unread_msg['nickname']}]|{unread_msg['content']}"
                })
                if chat_cfg["enable_vision"]:
                    temp_image_list = json.loads(unread_msg["image_data"])
                    for image in temp_image_list:
                        try:
                            content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{await temp_image_to_base64(image, False)}"
                                }
                            })
                        except:
                            pass
        else:
            content.append({"type": "text", "text": "- 无"})
    else:
        content.append({
            "type": "text",
            "text": "- 示例：[时间]|[消息ID]|内容"
        })
        for read_msg in msg_list["read_msg"]:
            if read_msg["from_me"]:
                content.append({
                    "type": "text",
                    "text": f"- [{ts_to_time(read_msg['time'])}]|[{read_msg['message_id']}]|[SELF]|{read_msg['content']}"
                })
            else:
                content.append({
                    "type": "text",
                    "text": f"- [{ts_to_time(read_msg['time'])}]|[{read_msg['message_id']}]|{read_msg['content']}"
                })
            if chat_cfg["enable_vision"]:
                temp_image_list = json.loads(read_msg["image_data"])
                for image in temp_image_list:
                    try:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{await temp_image_to_base64(image, False)}"
                            }
                        })
                    except:
                        pass
        content.append({"type": "text", "text": "=== 新消息 ==="})
        if msg_list["unread_msg"]:
            for unread_msg in msg_list["unread_msg"]:
                unread_msg_id_list.append(unread_msg["message_id"])
                content.append({
                    "type": "text",
                    "text": f"- [{ts_to_time(unread_msg['time'])}]|[{unread_msg['message_id']}]|{unread_msg['content']}"
                })
                if chat_cfg["enable_vision"]:
                    temp_image_list = json.loads(unread_msg["image_data"])
                    for image in temp_image_list:
                        try:
                            content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{await temp_image_to_base64(image, False)}"
                                }
                            })
                        except:
                            pass
        else:
            content.append({"type": "text", "text": "- 无"})
    return content, unread_msg_id_list

async def init_content_memory(user_list: list[int]) -> str:
    content = ["# 用户记忆内容"]
    user_memory_list = await get_user_all_memory(user_list)
    for user in user_memory_list:
        content.append(f"## ID：{user['user_id']}")
        if user["portrait"]:
            content.append(f"- 画像：{user['portrait']}")
        else:
            content.append("- 画像：无")
        if user["memory"]:
            content.extend([
                "- 记忆：\n",
                "|时间|来源|群ID|内容|",
                "|-|-|-|-|"
            ])
            for memory in user["memory"]:
                if memory["type"] == "group":
                    content.append(f"|{memory['time']}|群聊|{memory['group_id']}|{memory['content']}|")
                else:
                    content.append(f"|{memory['time']}|私聊|/|{memory['content']}|")
        else:
            content.append("- 记忆：无")
        if user["impression"]:
            content.extend([
                "- 印象：\n",
                "|时间|来源|群ID|内容|",
                "|-|-|-|-|"
            ])
            for impression in user["impression"]:
                if impression["type"] == "group":
                    content.append(f"|{impression['time']}|群聊|{impression['group_id']}|{impression['content']}|")
                else:
                    content.append(f"|{impression['time']}|私聊|/|{impression['content']}|")
        else:
            content.append("- 印象：无")
    return "\n".join(content)

async def get_pre_chat_input(status: CharacterStatus) -> list:
    system_content_core = await read_txt_async(prompt["common"]["core"])
    system_content_preset = await read_txt_async(prompt["preset"])
    system_content_state = await read_txt_async(prompt["common"]["state"])
    system_content_pre_chat = await read_txt_async(prompt["task"]["pre_chat"])
    current_time = ts_to_time(int(time.time()))
    user_content_time = "\n".join([
        "# 目标时间",
        f"- {current_time.isoformat()}",
        f"- 星期{cap_weekday(current_time.isoweekday())}"
    ])
    user_content_status = await init_content_status(status)
    user_content_homepage = await init_content_preview()
    user_content_location = await init_content_location()
    system_content = [
        {"type": "text", "text": system_content_core},
        {"type": "text", "text": system_content_preset},
        {"type": "text", "text": system_content_state},
        {"type": "text", "text": system_content_pre_chat}
    ]
    user_content = [
        {"type": "text", "text": user_content_time},
        {"type": "text", "text": user_content_status},
        {"type": "text", "text": user_content_homepage},
        {"type": "text", "text": user_content_location}

    ]
    return [
        {
            "role": "system",
            "content": system_content
        },
        {
            "role": "user",
            "content": user_content
        }
    ]

async def get_chatting_input(status: CharacterStatus, session: dict) -> tuple[list, list]:
    system_content_core = await read_txt_async(prompt["common"]["core"])
    system_content_preset = await read_txt_async(prompt["preset"])
    system_content_state = await read_txt_async(prompt["common"]["state"])
    system_content_chat = await read_txt_async(prompt["common"]["chat"])
    if session["type"] == "group":
        task_chat = prompt["task"]["group_chat"]
    else:
        task_chat = prompt["task"]["friend_chat"]
    system_content_task_chat = await read_txt_async(task_chat)
    current_time = ts_to_time(int(time.time()))
    user_content_time = "\n".join([
        "# 目标时间",
        f"- {current_time.isoformat()}",
        f"- 星期{cap_weekday(current_time.isoweekday())}"
    ])
    user_content_status = await init_content_status(status)
    user_content_homepage = await init_content_preview()
    system_content = [
        {"type": "text", "text": system_content_core},
        {"type": "text", "text": system_content_preset},
        {"type": "text", "text": system_content_state},
        {"type": "text", "text": system_content_chat},
        {"type": "text", "text": system_content_task_chat}
    ]
    user_content = [
        {"type": "text", "text": user_content_time},
        {"type": "text", "text": user_content_status},
        {"type": "text", "text": user_content_homepage}
    ]
    user_content_msg, unread_msg_id_list = await init_content_session(session)
    user_content_location = await init_content_location()
    user_content_image = await init_content_image()
    user_content.extend(user_content_msg + [
        {"type": "text", "text": user_content_location},
        {"type": "text", "text": user_content_image}
    ])
    return [
        {
            "role": "system",
            "content": system_content
        },
        {
            "role": "user",
            "content": user_content
        }
    ], unread_msg_id_list

async def get_status_update_input(status: CharacterStatus) -> list:
    system_content_core = await read_txt_async(prompt["common"]["core"])
    system_content_preset = await read_txt_async(prompt["preset"])
    system_content_state = await read_txt_async(prompt["common"]["state"])
    system_content_status_update = await read_txt_async(prompt["task"]["status_update"])
    current_time = ts_to_time(int(time.time()))
    user_content_time = "\n".join([
        "# 目标时间",
        f"- {current_time.isoformat()}",
        f"- 星期{cap_weekday(current_time.isoweekday())}"
    ])
    user_content_status = await init_content_status(status)
    user_content_location = await init_content_location()
    return [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": system_content_core},
                {"type": "text", "text": system_content_preset},
                {"type": "text", "text": system_content_state},
                {"type": "text", "text": system_content_status_update}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_content_time},
                {"type": "text", "text": user_content_status},
                {"type": "text", "text": user_content_location}
            ]
        }
    ]

async def get_memory_archive_input(user_list: list[int]) -> list:
    system_content_core = await read_txt_async(prompt["common"]["core"])
    system_content_preset = await read_txt_async(prompt["preset"])
    system_content_memory = await read_txt_async(prompt["task"]["memory_archive"])
    user_content_time = f"# 归档时间\n- {ts_to_time(int(time.time())).isoformat()}"
    user_content_memory_list = await init_content_memory(user_list)
    return [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": system_content_core},
                {"type": "text", "text": system_content_preset},
                {"type": "text", "text": system_content_memory}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_content_time},
                {"type": "text", "text": user_content_memory_list}
            ]
        }
    ]