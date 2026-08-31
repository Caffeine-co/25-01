from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator
from src.plugins.living.config import chat_cfg, setting_cfg
from src.plugins.living.utils import read_json_async, write_json
from typing import Annotated, Literal, Self


class SchemaModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

StatusScore = Annotated[int, Field(ge=0, le=100)]

class Session(SchemaModel):
    type: Literal["group", "friend"] = Field(description="会话类型，group表示群聊，friend表示好友私聊")
    id: int = Field(description="会话ID，群聊时为群号，好友私聊时为好友QQ号")

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        run_mode = chat_cfg["run_mode"]
        if {"type": self.type, "id": self.id} not in chat_cfg[f"{run_mode}s"]:
            raise ValueError(f"session {self.type}:{self.id} 不在允许名单中")
        return self

class TextData(SchemaModel):
    text: str = Field(description="文字内容")

class AtData(SchemaModel):
    qq: int = Field(description="@的群成员QQ号")

class ReplyData(SchemaModel):
    id: int = Field(description="回复的消息ID")

class ImageData(SchemaModel):
    image_id: int = Field(description="选择发送的预设图片ID")

class TextSegment(SchemaModel):
    type: Literal["text"]
    data: TextData

class AtSegment(SchemaModel):
    type: Literal["at"]
    data: AtData

class ReplySegment(SchemaModel):
    type: Literal["reply"]
    data: ReplyData

class ImageSegment(SchemaModel):
    type: Literal["image"]
    data: ImageData

GroupMessageSegment = Annotated[
    AtSegment | TextSegment | ReplySegment | ImageSegment,
    Field(discriminator="type")
]

FriendMessageSegment = Annotated[
    TextSegment | ReplySegment | ImageSegment,
    Field(discriminator="type")
]

class ExitAction(SchemaModel):
    type: Literal["exit"] = Field(description="固定值，只能输出'exit'；表示结束本次社交媒体活动")

class StayAction(SchemaModel):
    type: Literal["stay"] = Field(description="固定值，只能输出'stay'；表示停留当前会话")

class SwitchAction(SchemaModel):
    type: Literal["switch"] = Field(description="固定值，只能输出'switch'；表示切换到其他会话")
    session: Session = Field(description="切换后进入的目标会话")

NextAction = Annotated[
    ExitAction | StayAction | SwitchAction,
    Field(discriminator="type"),
]

def validate_message_segments(message: list[list[BaseModel]] | None) -> None:
    if message is None:
        return
    for index, segments in enumerate(message):
        reply_count = sum(
            isinstance(segment, ReplySegment)
            for segment in segments
        )
        if reply_count > 1:
            raise ValueError(f"message[{index}] 中 reply 消息段数量不能超过 1")
        if reply_count == 1 and len(segments) == 1:
            raise ValueError(f"message[{index}] 中 reply 消息段不能单独存在")

class GeneralImpressionItem(SchemaModel):
    content: str = Field(description="事件印象内容，避免与已有记忆信息重复")
    time: str = Field(description="事件发生时间，使用ISO8601格式")

class GroupUserImpression(SchemaModel):
    user_id: int = Field(description="产生该印象的群成员QQ号")
    impression: list[GeneralImpressionItem] = Field(description="新的用户事件印象列表")

class CharacterStatus(SchemaModel):
    current_time: str = Field(description="当前时间，使用输入提供的ISO8601时间")

    current_location: str = Field(description="当前所在的具体位置")
    current_activity: str = Field(description="当前正在进行的活动")
    current_situation: str = Field(description="当前所处的事件或情境")

    environmental_comfort: StatusScore = Field(description="当前环境舒适程度，0-100")
    privacy_level: StatusScore = Field(description="当前隐私程度，0-100")
    noise_level: StatusScore = Field(description="环境噪声强度，0-100")
    crowd_density: StatusScore = Field(description="周围人群密集程度，0-100")

    energy_level: StatusScore = Field(description="当前精力，0-100")
    physical_stamina: StatusScore = Field(description="体力与耐久度，0-100")
    fatigue_level: StatusScore = Field(description="身体疲劳程度，0-100")
    sleepiness_level: StatusScore = Field(description="当前困倦程度，0-100")
    hunger_level: StatusScore = Field(description="饥饿程度，0-100")
    thirst_level: StatusScore = Field(description="口渴程度，0-100")
    appetite_level: StatusScore = Field(description="进食欲望，0-100")
    pain_level: StatusScore = Field(description="疼痛程度，0-100")
    physical_strain: StatusScore = Field(description="当前身体负担，0-100")

    sleep_quality: StatusScore = Field(description="最近一次睡眠质量，0-100")
    sleep_debt: StatusScore = Field(description="累积睡眠不足程度，0-100")
    circadian_stability: StatusScore = Field(description="昼夜节律稳定程度，0-100")
    body_temperature_c: float = Field(ge=34, le=43, description="当前体温，34-43，单位为℃")
    recovery_capacity: StatusScore = Field(description="身体恢复能力，0-100")
    nutrition_status: StatusScore = Field(description="营养充足与均衡程度，0-100")
    hydration_level: StatusScore = Field(description="身体水分状态，0-100")
    physiological_arousal: StatusScore = Field(description="身体兴奋与警觉程度，0-100")
    sensory_overload: StatusScore = Field(description="感官刺激过载程度，0-100")

    joy: StatusScore = Field(description="快乐与愉悦感，0-100")
    calmness: StatusScore = Field(description="平静程度，0-100")
    sadness: StatusScore = Field(description="悲伤感，0-100")
    anxiety: StatusScore = Field(description="焦虑与不安，0-100")
    anger: StatusScore = Field(description="愤怒程度，0-100")
    fear: StatusScore = Field(description="恐惧程度，0-100")
    hope: StatusScore = Field(description="希望感，0-100")
    shame: StatusScore = Field(description="羞耻与难堪感，0-100")
    loneliness: StatusScore = Field(description="主观孤独感，0-100")
    belongingness: StatusScore = Field(description="主观归属感，0-100")
    emotional_stability: StatusScore = Field(description="当前情绪稳定程度，0-100")
    emotional_intensity: StatusScore = Field(description="当前情绪整体强度，0-100")

    attention_capacity: StatusScore = Field(description="可分配的注意力，0-100")
    concentration: StatusScore = Field(description="持续专注能力，0-100")
    mental_clarity: StatusScore = Field(description="思维清晰程度，0-100")
    working_memory_capacity: StatusScore = Field(description="当前工作记忆能力，0-100")
    cognitive_flexibility: StatusScore = Field(description="思维切换与调整能力，0-100")
    executive_function: StatusScore = Field(description="计划和执行控制能力，0-100")
    decision_speed: StatusScore = Field(description="做出决定的速度，0-100")
    judgment_confidence: StatusScore = Field(description="对自身判断的信心，0-100")
    self_awareness: StatusScore = Field(description="对自身状态的觉察程度，0-100")
    rumination_level: StatusScore = Field(description="反复思考负面内容的程度，0-100")

    self_esteem: StatusScore = Field(description="自我价值感，0-100")
    self_efficacy: StatusScore = Field(description="对自身能力的信心，0-100")
    future_confidence: StatusScore = Field(description="对未来的信心与确定感，0-100")
    sense_of_meaning: StatusScore = Field(description="对生活和行动的意义感，0-100")

    intrinsic_motivation: StatusScore = Field(description="内在动机，0-100")
    extrinsic_motivation: StatusScore = Field(description="外部奖励驱动，0-100")
    achievement_motivation: StatusScore = Field(description="成就需求，0-100")
    affiliation_need: StatusScore = Field(description="建立和维持关系的需求，0-100")
    approval_need: StatusScore = Field(description="获得认可的需求，0-100")
    autonomy_need: StatusScore = Field(description="自主决定的需求，0-100")
    creative_drive: StatusScore = Field(description="创作与表达欲望，0-100")
    avoidance_tendency: StatusScore = Field(description="回避困难和压力的倾向，0-100")

    openness: StatusScore = Field(description="开放性，0-100")
    conscientiousness: StatusScore = Field(description="尽责性，0-100")
    extraversion: StatusScore = Field(description="外向性，0-100")
    agreeableness: StatusScore = Field(description="宜人性，0-100")
    emotional_reactivity: StatusScore = Field(description="情绪反应敏感程度，0-100")
    impulsivity: StatusScore = Field(description="冲动倾向，0-100")
    patience: StatusScore = Field(description="耐心程度，0-100")
    resilience: StatusScore = Field(description="面对挫折的恢复能力，0-100")
    adaptability: StatusScore = Field(description="对变化的适应能力，0-100")
    perfectionism: StatusScore = Field(description="完美主义倾向，0-100")
    risk_tolerance: StatusScore = Field(description="风险容忍程度，0-100")

    accumulated_stress: StatusScore = Field(description="累积心理压力，0-100")
    emotional_exhaustion: StatusScore = Field(description="情绪耗竭程度，0-100")
    burnout_risk: StatusScore = Field(description="倦怠风险，0-100")
    trigger_sensitivity: StatusScore = Field(description="对负面刺激的敏感程度，0-100")
    coping_capacity: StatusScore = Field(description="调节压力和情绪的能力，0-100")
    attachment_security: StatusScore = Field(description="人际依恋安全感，0-100")

    family_closeness: StatusScore = Field(description="家庭关系亲密程度，0-100")
    friendship_closeness: StatusScore = Field(description="友情关系总体亲密程度，0-100")
    interpersonal_trust: StatusScore = Field(description="对他人的总体信任程度，0-100")
    social_connectedness: StatusScore = Field(description="客观社会联系充足程度，0-100")
    interpersonal_dependency: StatusScore = Field(description="对他人的依赖程度，0-100")
    interpersonal_tension: StatusScore = Field(description="当前人际紧张程度，0-100")
    social_energy: StatusScore = Field(description="当前可用于社交的精力，0-100")
    emotional_support: StatusScore = Field(description="可获得的情感支持，0-100")

    available_time: StatusScore = Field(description="当前可自由支配时间，0-100")
    schedule_pressure: StatusScore = Field(description="日程紧张程度，0-100")
    obligation_load: StatusScore = Field(description="当前责任和任务负担，0-100")

    @classmethod
    def _default(cls) -> Self:
        return cls(**setting_cfg["default_status"])

    @classmethod
    async def load(cls) -> Self:
        try:
            content = await read_json_async(chat_cfg["status_path"])
            return cls(**content)
        except FileNotFoundError:
            return cls._default()
        except Exception:
            raise

    async def save(self) -> None:
        content = self.model_dump(mode="json")
        await write_json(chat_cfg["status_path"], content)

    async def update(self, content: dict) -> None:
        for key, value in content.items():
            setattr(self, key, value)
        await self.save()

class PreChatValidate(SchemaModel):
    new_status: CharacterStatus = Field(description="根据历史状态、当前时间推演出的完整新状态")
    session: Session

class GroupChatValidate(SchemaModel):
    new_status: CharacterStatus = Field(description="根据历史状态、当前时间和聊天内容推演出的完整新状态")
    chat: bool = Field(description="本次是否发送消息，为false时不得提供message")
    message: list[list[GroupMessageSegment]] | None = Field(
        default=None,
        description="消息列表，仅在chat=true时提供，每个message[i]中reply上限一个"
    )
    group_impression: list[GeneralImpressionItem] = Field(description="根据聊天记录重新总结的群聊印象列表")
    user_impression: list[GroupUserImpression] = Field(description="本次新形成的用户事件印象")
    next_action: NextAction = Field(description="完成当前会话处理后的下一步行为")

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: list[list[GroupMessageSegment]] | None):
        validate_message_segments(value)
        return value

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        if self.chat:
            if self.message is None:
                raise ValueError("chat=true 时必须输出 message")
        else:
            if self.message:
                raise ValueError("chat=false 时不得输出 message")
        return self

class FriendChatValidate(SchemaModel):
    new_status: CharacterStatus = Field(description="根据历史状态、当前时间和聊天内容推演出的完整新状态")
    chat: bool = Field(description="本次是否发送消息，为false时不得提供message")
    message: list[list[FriendMessageSegment]] | None = Field(
        default=None,
        description="消息列表，仅在chat=true时提供，每个message[i]中reply上限一个"
    )
    user_impression: list[GeneralImpressionItem] = Field(description="本次新形成的用户事件印象列表")
    next_action: NextAction = Field(description="完成当前会话处理后的下一步行为")

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: list[list[FriendMessageSegment]] | None):
        validate_message_segments(value)
        return value

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        if self.chat:
            if self.message is None:
                raise ValueError("chat=true 时必须输出 message")
        else:
            if self.message:
                raise ValueError("chat=false 时不得输出 message")
        return self

class GroupMemory(SchemaModel):
    type: Literal["group"]
    group_id: int = Field(description="该记忆来源群聊的群号")
    content: str = Field(description="来自群聊的值得长期保留的事件记忆")
    time: str = Field(description="事件发生时间，使用ISO8601格式")

class FriendMemory(SchemaModel):
    type: Literal["friend"]
    content: str = Field(description="来自好友私聊的值得长期保留的事件记忆")
    time: str = Field(description="事件发生时间，使用ISO8601格式")

Memory = Annotated[
    GroupMemory | FriendMemory,
    Field(discriminator="type"),
]

class UserMemory(SchemaModel):
    user_id: int = Field(description="记忆对应用户的QQ号")
    portrait: str = Field(description="根据记忆信息总结的简短用户画像")
    memory: list[Memory] = Field(description="该用户对应的长期事件记忆列表，按时间先后排序")

class MemoryValidate(RootModel[list[UserMemory]]):
    pass

class StatusValidate(SchemaModel):
    new_status: CharacterStatus