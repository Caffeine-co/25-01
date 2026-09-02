# 配置与 JSON 编写指南

25:01 的主要运行配置来自：

```text
configs.json
location.json
image_metadata.json
```

其中：

```text
configs.example.json        → configs.json
location.example.json       → location.json
image_metadata.example.json → image_metadata.json
```

---

# 1. configs.json

顶层结构：

```json
{
  "host": "127.0.0.1",
  "port": 2500,
  "llm_config": {},
  "setting_config": {},
  "chat_config": {},
  "scheduler_config": {}
}
```

---

## 1.1 host / port

```json
"host": "127.0.0.1",
"port": 2500
```

用于 NoneBot FastAPI Driver。

### 本机部署

```json
"host": "127.0.0.1"
```

### Docker / 跨主机

```json
"host": "0.0.0.0"
```

OneBot V11 反向 WS 常用地址：

```text
ws://<host>:2500/onebot/v11/ws
```

---

# 2. llm_config

```json
"llm_config": {
  "api_key": "",
  "base_url": "",
  "model_name": "",
  "thinking": "enabled",
  "temperature": 1,
  "reasoning_effort": "medium",
  "timeout": 60,
  "retry_times": 3
}
```

| 字段 | 含义 |
| --- | --- |
| `api_key` | API Key |
| `base_url` | OpenAI-compatible API Endpoint |
| `model_name` | 模型名称 |
| `reasoning_effort` | 当前请求实际传入模型的推理强度 |
| `timeout` | 单次请求超时秒数 |
| `retry_times` | 失败后的重试次数 |
| `thinking` | 当前示例保留字段 |
| `temperature` | 当前示例保留字段 |

> 当前 `client.py` 的 `request_llm()` 实际主要传入 `model`、`messages`、`response_format` 与 `reasoning_effort`，`thinking`、`temperature` 虽存在于示例配置中，但当前主调用链没有直接使用；不要仅修改这两个字段就预期模型行为一定改变

---

# 3. setting_config

```json
"setting_config": {
  "prompt": {},
  "tz_offset": 9,
  "active_model_args": {},
  "default_status": {}
}
```

---

## 3.1 prompt

```json
"prompt": {
  "preset": "prompt/preset.md",
  "common": {
    "core": "prompt/common/core.md",
    "state": "prompt/common/state.md",
    "chat": "prompt/common/chat.md"
  },
  "task": {
    "status_update": "prompt/task/status_update.md",
    "pre_chat": "prompt/task/pre_chat.md",
    "group_chat": "prompt/task/group_chat.md",
    "friend_chat": "prompt/task/friend_chat.md",
    "memory_archive": "prompt/task/memory_archive.md"
  }
}
```

职责建议：

| 文件 | 应放内容 |
| --- | --- |
| `core.md` | 全局身份边界、最高级通用原则 |
| `preset.md` | 角色设定、固定生活制度、人物关系、地点等 |
| `state.md` | 状态推演通用规则 |
| `chat.md` | 聊天行为通用规则 |
| `status_update.md` | 状态更新任务 |
| `pre_chat.md` | 浏览主页与选择会话任务 |
| `group_chat.md` | 群聊任务 |
| `friend_chat.md` | 私聊任务 |
| `memory_archive.md` | 长期记忆归档任务 |

不要把某个任务专用约束塞入所有 Prompt

---

## 3.2 tz_offset

```json
"tz_offset": 9
```

角色世界使用的 UTC Offset

例如日本标准时间：

```text
UTC+9
```

这里影响：

- 活动概率时间
- Prompt 当前时间
- 状态时间解释

---

# 4. active_model_args

见 [Active_Model.md](Active_Model.md)

---

# 5. default_status

见 [Default_Status.md](Default_Status.md)

---

# 6. chat_config

```json
"chat_config": {
  "stay_interval_range": {
    "max": 180,
    "min": 120
  },
  "enable_vision": true,
  "temp_image_dir": "temp_image",
  "meta_image_dir": "meta_image",
  "image_metadata_path": "image_metadata.json",
  "location_path": "location.json",
  "session_info_db_path": "session_info.db",
  "message_db_path": "message.db",
  "memory_db_path": "memory.db",
  "status_path": "status.json",
  "max_msg_reserve_num": 200,
  "max_msg_provide_num": 100,
  "max_session_rounds": 5,
  "max_memory_user_counts": 20,
  "run_mode": "whitelist",
  "blacklists": [],
  "whitelists": []
}
```

---

## 6.1 stay_interval_range

模型选择 `stay` 后的等待区间，单位秒

需要保证：

```text
min <= max
```

---

## 6.2 enable_vision

```json
true
```

时，收到的消息图片会下载并在模型上下文需要时作为图片输入提供

---

## 6.3 max_msg_reserve_num

每个会话本地保留的最大消息规模

用于控制数据库无限增长

---

## 6.4 max_msg_provide_num

单次提供给模型的消息数量上限

它直接影响：

- 上下文长度
- Token 成本
- 对话连续性

---

## 6.5 max_session_rounds

一次打开软件后最多处理多少轮会话

这是控制：

- 无限循环
- LLM 成本
- 单次活动持续时间

的重要安全阀

---

## 6.6 max_memory_user_counts

一次记忆归档请求最多处理多少用户

用户数量较多时会自动分批

---

## 6.7 run_mode

支持：

```text
whitelist
blacklist
```

### whitelist

只有名单中的会话可记录 / 进入

### blacklist

名单中的会话被排除，其余可使用

---

## 6.8 会话格式

```json
{
  "type": "group",
  "id": 123456789
}
```

或：

```json
{
  "type": "friend",
  "id": 10001
}
```

完整示例：

```json
"whitelists": [
  {"type": "group", "id": 123456789},
  {"type": "friend", "id": 10001}
]
```

---

# 7. scheduler_config

```json
"scheduler_config": {
  "chat_dispatch": {
    "minute": "*/10"
  },
  "status_update": {
    "minute": "25"
  },
  "memory_archive": {
    "hour": "4",
    "minute": "30"
  },
  "session_update": {
    "hour": "8",
    "minute": "30"
  }
}
```

字段直接作为 APScheduler Cron 参数展开

---

## 7.1 chat_dispatch

决定多久做一次“是否打开软件”的概率判定

若：

```json
"minute": "*/10"
```

则建议：

```json
"poll_interval_seconds": 600
```

二者一致

---

## 7.2 status_update

独立状态更新

---

## 7.3 memory_archive

长期记忆整理

---

## 7.4 session_update

同步群名称、群人数和好友昵称

---

# 8. location.json

格式：

```json
[
  "中央街",
  "购物中心",
  "音乐商店",
  "神山高校"
]
```

它提供 `new_status.current_location` 的候选范围，但 Prompt 当前明确允许模型在必要时自行拟定其他位置

建议只写：

- 角色高频活动地点
- 世界观中稳定存在的地点
- 对行为判断真正有帮助的位置

不要把所有可能地点都塞进去

---

# 9. image_metadata.json

格式：

```json
[
  {
    "image_id": 1,
    "file_name": "1.gif",
    "type": "动画表情",
    "summary": "[爱心]"
  }
]
```

| 字段 | 含义 |
| --- | --- |
| `image_id` | 模型选择图片时使用的唯一 ID |
| `file_name` | `meta_image_dir` 中的文件名 |
| `type` | 图片类别 |
| `summary` | 提供给模型和消息记录的语义摘要 |

要求：

```text
image_id 唯一
file_name 存在
summary 简洁且能区分语义
```

模型不会直接知道图片像素内容，而是主要通过 metadata 决定要不要选图，因此 `summary` 的质量非常重要

---

# 10. 推荐配置工作流

每创建一个新角色，建议按以下顺序：

```text
1. 写 preset.md
2. 确定时区
3. 设置 wake/sleep
4. 设置 weekday_multipliers
5. 建立 activity_peaks
6. 编写 default_status
7. 配置会话名单
8. 配置 location.json
9. 配置 image_metadata.json
10. 小规模运行并观察日志
11. 再调 global_rate_multiplier
```

不要一开始同时大幅修改所有概率参数，否则很难判断哪一项造成了行为偏移