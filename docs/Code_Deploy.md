# 源码部署

本文介绍 25:01 的 Python 源码部署方式，适合开发、调试 Prompt、修改概率模型或扩展业务逻辑

---

## 1. 环境要求

推荐：

- Python 3.11+
- Git
- 可用的 OpenAI-compatible LLM API
- OneBot V11 实现
- Windows / Linux / macOS

Dockerfile 当前以 `python:3.11-slim` 为基础镜像

---

## 2. 获取源码

```bash
git clone https://github.com/Caffeine-co/25-01.git
cd 25-01
```

---

## 3. 创建虚拟环境

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

升级 pip：

```bash
python -m pip install --upgrade pip
```

---

## 4. 安装依赖

```bash
pip install -r requirements.txt
```

---

## 5. 创建运行配置

复制示例：

### Windows

```powershell
Copy-Item configs.example.json configs.json
Copy-Item location.example.json location.json
Copy-Item image_metadata.example.json image_metadata.json
```

### Linux / macOS

```bash
cp configs.example.json configs.json
cp location.example.json location.json
cp image_metadata.example.json image_metadata.json
```

然后填写：

- LLM API Key
- Base URL
- Model Name
- 会话白 / 黑名单
- Prompt 路径
- 活动概率参数
- 定时任务
- 数据库与状态文件路径

见 [Config_Tutorial.md](Config_Tutorial.md)

---

## 6. 准备 Prompt

默认配置需要：

```text
prompt/
├─ preset.md
├─ common/
│  ├─ core.md
│  ├─ state.md
│  └─ chat.md
└─ task/
   ├─ status_update.md
   ├─ pre_chat.md
   ├─ group_chat.md
   ├─ friend_chat.md
   └─ memory_archive.md
```

不要随意改变文件名；如需调整目录结构，请同步修改 `configs.json > setting_config > prompt`

Prompt 实际拼接顺序见 [Workflow.md](Workflow.md)

---

## 7. 准备预设图片

如果希望角色能够主动发送预设图片：

1. 将资源放入 `meta_image/`
2. 在 `image_metadata.json` 注册
3. 保证 `image_id` 唯一
4. 保证 `file_name` 与真实文件一致

示例：

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

如果不需要此能力，也建议保留合法的空数组：

```json
[]
```

---

## 8. 配置 OneBot V11

程序入口通过：

```python
driver.register_adapter(ONEBOT_V11Adapter)
```

注册 OneBot V11 Adapter

推荐让 NapCat 等协议端以反向 WebSocket 连接：

```text
ws://127.0.0.1:2501/onebot/v11/ws
```

如果跨主机访问，将：

```json
"host": "0.0.0.0"
```

并开放相应端口

---

## 9. 启动

```bash
python bot.py
```

正常启动时会：

1. 初始化日志系统
2. 输出启动 Logo
3. 读取 configs.json
4. 初始化 NoneBot
5. 注册 OneBot V11 Adapter
6. 显式导入 src.plugins.living
7. 初始化数据库
8. 启动 APScheduler
9. 注册消息监听
10. 等待 OneBot 连接与定时任务

---

## 10. 开发模式建议

### 修改 Prompt

无需修改 Python，只需要编辑 `prompt/` 对应文件并重新触发下一次请求

### 修改角色活动节奏

优先调整：

```text
configs.json
└─ setting_config
   └─ active_model_args
```

不要首先修改 `probability.py`

### 修改状态结构

需要同步考虑：

- `validate.py`
- `configs.json > default_status`
- `preprocess.py`
- Prompt 中状态要求

### 修改输出协议

需要同步考虑：

- Pydantic Schema
- Prompt 输出要求
- `afterprocess.py`
- 消息发送逻辑

---

## 11. 数据文件

默认会使用：

```text
session_info.db
message.db
memory.db
status.json
temp_image/
logs/
```

`logs/` 保存程序运行日志，不属于角色业务状态，但生产环境同样建议纳入持久化目录和故障排查流程。日志自动按日轮转、压缩并保留 30 天

建议生产环境统一改为：

```text
data/
```

例如：

```json
"session_info_db_path": "data/session_info.db",
"message_db_path": "data/message.db",
"memory_db_path": "data/memory.db",
"status_path": "data/status.json",
"temp_image_dir": "data/temp_image"
```

并将 `data/` 加入备份策略

---

## 12. Docker 自行构建

```bash
docker build -t 25-01:local .
```

```bash
docker run --rm \
  -p 2500:2500 \
  -v "$(pwd)/configs.json:/app/configs.json" \
  -v "$(pwd)/prompt:/app/prompt" \
  25-01:local
```

Dockerfile 当前启动命令为：

```text
python bot.py
```

---

## 13. 常见问题

### 启动立即退出

检查当前工作目录下是否存在：

```text
configs.json
```

入口文件会直接读取该文件

### OneBot 无法连接

确认：

- `host`
- `port`
- 防火墙
- Docker 端口映射
- 反向 WS 地址
- Access Token

### 模型总是重试

检查：

- Endpoint 是否兼容当前 Structured Output 调用
- 模型是否支持当前 `reasoning_effort`
- API Key
- 请求超时
- Prompt 是否导致 Schema 校验失败

### 会话无法被模型选择

`Session` Schema 会检查目标会话是否存在于当前运行模式对应名单中

### 状态文件损坏

可备份后删除 `status.json`。下次加载时若文件不存在，会从 `setting_config.default_status` 冷启动

### 如何排查运行异常

除终端输出外，程序会将 `DEBUG` 及以上级别日志持久化到当前工作目录下的：

```text
logs/
```

如果问题无法稳定复现，建议保留问题发生日期附近的日志文件，用于检查：

Scheduler 调度过程
LLM 请求与重试
OneBot API 调用
数据库异常
状态更新异常
启动阶段错误

历史日志会自动压缩，因此排查较早问题时也需要检查 logs/ 中的 .zip 文件