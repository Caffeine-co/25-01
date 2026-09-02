<div align="center">
<img src="https://raw.githubusercontent.com/Caffeine-co/25-01/main/icon/icon.ico" alt="icon" width="100px"/>
<h1>25:01</h1>
<h3>>_ After 25:00, she keeps living.</h3>
<h3>对话窗口关闭之后，她的时间并不会停止。</h3>

[![python 3.13](https://img.shields.io/badge/Python-3.13-green)](https://docs.python.org/3.13)
[![nonebot v2.5.0](https://img.shields.io/badge/Nonebot-v2.5.0-red)](https://v2.nonebot.dev)
[![onebot v11](https://img.shields.io/badge/Onebot-v11-white)](https://11.onebot.dev)
[![License MIT](https://img.shields.io/badge/License-MIT-blue)](https://opensource.org/licenses/MIT)
[![プロセカ](https://img.shields.io/badge/Project-Sekai-884499)](https://pjsekai.sega.jp)
</div>

# Introduce

**25:01** 是一个基于 NoneBot2 / OneBot V11 与大语言模型构建的持续角色仿真项目。它不把角色限制在“收到消息后回答”的单轮 ChatBot 模式中，而是尝试让角色拥有自己的时间、状态、记忆和社交节奏：她会在一天中的某些时刻主动打开社交软件，浏览会话，决定进入哪个聊天，选择说话、停留、切换或离开；即使无人发言，角色自身的状态仍会随现实时间继续演化

`25:01` 关注的不是“让模型一直说话”，而是让角色在不说话的时候也仍然存在

---

## ✦ What is 25:01?

传统聊天机器人通常遵循：

```text
用户发送消息 → 模型生成回复 → 对话结束
```

**25:01** 更接近：

```text
现实时间持续推进
      ↓
角色状态持续演化
      ↓
活动概率模型判断是否打开社交软件
      ↓
浏览主页 / 选择会话
      ↓
阅读消息 / 形成印象 / 决定是否发言
      ↓
停留、切换或退出
      ↓
长期记忆定期归档
      ↓
下一次活动继续发生
```

它将“聊天”视作角色生活中的一个行为，而不是角色存在的全部

---

## ✦ Core Features

### Persistent Character State

角色维护一份持续状态，包括：

- 当前时间、位置、活动与情境
- 生理状态与睡眠节律
- 情绪、认知与心理负荷
- 社交能量与关系状态
- 动机、人格倾向与现实约束

状态被保存到本地 JSON，并由定时任务持续更新

---

### Human-like Activity Scheduling

项目使用基于时间的活动概率模型，而不是固定时间点强制上线

活动概率综合考虑：

- 起床 / 入睡时间
- 工作日与周末倍率
- 基础活动率
- 多个高斯活动峰
- 睡眠期最低活动水平
- 全局活动倍率
- 轮询间隔

因此角色每天的上线次数与时间具有随机性，但总体仍服从人物作息

---

### Autonomous Session Navigation

一次活动开始后，LLM 会先看到“消息主页”，再决定进入哪个允许的群聊或好友会话

进入会话后，角色可以：

- `exit`：退出本次活动
- `stay`：停留当前会话，稍后继续
- `switch`：切换至其他会话

一次活动最多执行 `max_session_rounds` 轮，从而控制调用成本与无限循环风险

---

### Layered Memory

项目区分：

- 消息记录
- 用户事件印象
- 群聊印象
- 用户长期记忆
- 用户画像
- 角色当前状态

长期记忆由独立定时任务分批归档，而不是每次聊天都无限累积上下文

---

### Structured LLM Output

LLM 输出由 Pydantic Schema 严格校验：

- 禁止额外字段
- 状态分值限制在 `0~100`
- 会话必须位于允许名单
- 消息段按类型校验
- `reply` 每条消息最多一个且不能单独存在
- `chat=false` 时禁止携带消息
- 下一步动作只能是 `exit / stay / switch`

模型异常输出不会直接进入消息发送链路

---

### Persistent Runtime Logs

运行日志不仅输出到终端，也会同步持久化到本地 `logs/` 目录

```text
logs/
├─ 2026-09-01.log
├─ 2026-09-02.log
└─ ...
```

日志系统具有：

* `DEBUG` 及以上级别文件记录
* 每日 `00:00` 自动轮转
* 历史日志自动 ZIP 压缩
* 自动保留最近 30 天
* UTF-8 编码
* 队列式异步写入，减少日志文件 I/O 对主运行流程的直接影响

日志系统在读取 `configs.json` 和初始化 NoneBot 之前启动，因此配置加载失败等早期启动异常同样能够被记录

---

### Vision & Preset Images

可记录用户发送的图片并在聊天时提供给多模态模型，同时支持通过 `image_metadata.json` 建立角色自己的预设图片 / 动画表情资源库

---

## ✦ Architecture

```text
NoneBot2 + OneBot V11
        ├── Logging
        │     ├── Console Sink
        │     └── Persistent File Sink
        ├── Message Recorder
        │     ├── Group Messages
        │     └── Friend Messages
        ├── APScheduler
        │     ├── chat_dispatch
        │     ├── status_update
        │     ├── memory_archive
        │     └── session_update
        ├── Activity Probability Model
        ├── Prompt Assembly
        │     ├── common
        │     ├── preset
        │     └── task
        ├── LLM Client
        ├── Pydantic Validation
        └── SQLite / JSON Persistence
```

详细流程见 [docs/Workflow.md](docs/Workflow.md)

---

## ✦ Project Structure

```text
.
├─ bot.py
├─ configs.example.json
├─ image_metadata.example.json
├─ location.example.json
├─ Dockerfile
├─ requirements.txt
├─ prompt/
├─ meta_image/
├─ src/plugins/living/
└─ docs/
```

核心模块：

| 模块 | 作用 |
| --- | --- |
| `__init__.py` | 调度器、消息监听与主业务流程 |
| `probability.py` | 活动概率模型 |
| `preprocess.py` | Prompt 与上下文拼装 |
| `client.py` | LLM 请求与重试 |
| `validate.py` | Pydantic 输出协议与角色状态模型 |
| `afterprocess.py` | 消息发送、图片处理、印象回写 |
| `database.py` | SQLite 持久化 |
| `utils.py` | 时间、文件、图片等通用工具 |

---

## ✦ Quick Start

[**使用 Release 构建产物**](docs/Build_Deploy.md)

[**从源码运行**](docs/Code_Deploy.md)

[**编写角色配置**](docs/Config_Tutorial.md)

---

## ✦ Documentation

| 文档 | 内容 |
| --- | --- |
| [Build_Deploy.md](docs/Build_Deploy.md) | Release / Docker 构建产物部署 |
| [Code_Deploy.md](docs/Code_Deploy.md) | Python 源码部署 |
| [Workflow.md](docs/Workflow.md) | 工作原理与数据流 |
| [Config_Tutorial.md](docs/Config_Tutorial.md) | JSON 配置、Prompt 路径与资源文件 |
| [Active_Model.md](docs/Active_Model.md) | 活跃函数模型配置 |
| [Default_Status.md](docs/Default_Status.md) | 冷启动角色参数配置 |

---

## ✦ Tech Stack

- Python
- NoneBot2
- OneBot V11
- FastAPI Driver
- APScheduler
- OpenAI-compatible API
- Pydantic
- aiosqlite
- SQLite
- Docker
- Nuitka

---

## ✦ Notes

25:01 本身不提供 QQ 协议实现，需要配合 NapCatQQ 等 OneBot V11 协议实现使用

本项目包含角色扮演与二次创作方向的使用场景。若使用第三方作品角色、名称、图像或其他素材，请自行确认相应版权与使用规则

本项目与相关 IP 官方无隶属或授权关系，除另有说明外，第三方作品相关权利归其各自权利人所有

---

>**\>_ 25:00 之后，仍然还有下一分钟。**