# WorldLife 2.0 — 可运行的自主虚拟人物系统

**本地小规模正式版（单世界、Python 3.11+、SQLite；远程 LLM 可选）**

这是一个**实际可安装、可独立推进时间、可接受外部消息、可管理项目、可多人物交互、可存档/备份的虚拟人物运行内核**。无需云服务就能运行世界；启用兼容的语言模型后，可以生成自然语言回复和受控的自主反思/目标建议。

本工程沿袭 [world-preview](https://github.com/Caffeine-co/25-01/tree/world-preview) 的世界→生命→行动构想，并在上一轮独立 v1.0 工程包基础上迭代；v2.0 是独立后继工程包，**不直接替换旧版 SQLite 存档**。

> 能力边界：正式可用**限定为本地/单机、小规模、规则可定义世界**。不是通用人工生命、意识模型、医学模拟器，也没有声称已完成心理真实性研究或公网高可用部署。远程 LLM 的 HTTP 协议已用本地伪服务测通；实际第三方密钥和外网调用尚未现场验收。

## 1. 十分钟内实际使用

在 Windows PowerShell 或 Linux 终端进入工程根目录：

```bash
# 核心只用 Python 标准库。下面安装命令用于得到完整 CLI 命令。
python -m pip install --no-deps .

# 完整复验：单测、旧基准、新基准、扰动、编译；结果存 results/
python scripts/verify.py

# 不启动服务，直接模拟有 4 步目标的角色 7 天
worldlife examples/scenarios/art_project.json --hours 168 --db data/my_art.db

# 或通过脚本直接运行（无需 pip 安装）
python -m simlife examples/scenarios/art_project.json --hours 168 --db data/my_art2.db
```

### 持续运行的本地 HTTP 服务

必须设置鉴权令牌（示例只做演示，请生成自己的随机令牌）：

**PowerShell：**

```powershell
$env:WORLDLIFE_SERVER_TOKEN = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
worldlife-server examples/scenarios/roommates.json --db data/live_world.db
```

**Linux / macOS：**

```bash
export WORLDLIFE_SERVER_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
worldlife-server examples/scenarios/roommates.json --db data/live_world.db
```

打开第二个终端，在那里使用同一个令牌：

```bash
worldlife-client status
worldlife-client actor resident_01
worldlife-client chat resident_01 "今天有什么安排？"
worldlife-client events --limit 10
worldlife-client advance 120
```

默认 `worldlife-server` 每 5 秒检查时钟，**1 分钟现实时间推进 1 分钟模拟时间**，关闭服务期间的现实时间不会补算。可以 `--no-auto-time` 关闭自动推进，或使用 `--sim-minutes-per-second 1` 加速到 1 现实秒=1 模拟分钟。

默认聊天是 **offline 回退回复**，不进行真实语言生成；启用远程模型后才具有开放语言交互能力。详见 [部署与运维](docs/OPERATIONS.md)。

### 配置可选 LLM

```text
WORLDLIFE_LLM_API_KEY=（自行配置真实密钥，切勿写入仓库）
WORLDLIFE_LLM_BASE_URL=https://api.openai.com/v1
WORLDLIFE_LLM_MODEL=（账户有权限且支持 JSON 输出的模型名称）
```

服务启动增加 `--provider remote --max-calls 4 --reflect-daily`。最后一个参数使人物**在服务检测到跨越模拟日时**主动进行反思；反思提出的项目仍会经过程序校验。对话和反思共享每人物每日调用预算，失败也计数，避免请求风暴。`--max-calls 0` 可禁用模型。

## 2. 你得到的机制

| 范围 | v2.0 实现 | 明确边界 |
|---|---|---|
| 世界 | 定时事件、地点、路网、资源、设施 | 静态小地图、无自由物理模拟 |
| 人物 | 需求、生理行动能力、人格、兴趣、目标、情绪 | 参数是工程抽象、非医学或心理学数据 |
| 决策 | 需求优先、习惯活动、承诺、项目多步执行 | 无一般化无限状态规划器 |
| 行动 | 前置条件、延时结算、资源验证、打断、多主体占用 | 行动类型需要显式实现 |
| 认知 | 当前地点观察、个人已知路网、带来源的信念与情景记忆 | 无自动语言语义抽取/复杂因果推理 |
| LLM | 对话、可选每日反思、受限项目建议、调用预算 | 外部真实模型尚需按提供商验收 |
| 运行 | 本地 HTTP 鉴权、幂等 ID、版本冲突保护、SQLite 备份 | 单机单世界单写者，不是集群服务 |

## 3. 项目布局

```text
simlife/
  model.py       数据类型：世界、人物、记忆、关系、项目容器
  config.py      worlds/personas/scenarios 三层 JSON 装配、校验与规则指纹
  engine.py      世界唯一状态写入者：时钟、事件、动作、项目、信念
  actions.py     行动注册与执行（移动/设施/练习/协助/交谈）
  policy.py      需求、兴趣、承诺和基础社交决策
  planning.py    多步骤项目、路线/动作衔接、项目验证
  knowledge.py   来源可追溯的主观信念与冲突修正
  memory.py      简单的情景记忆检索
  systems.py     连续状态与资源结算
  perception.py  局部观察与认知更新
  cognition.py   可选语言模型：聊天 + 反思；预算、解析、回退
  projection.py  人物可见状态视图
  store.py       事务快照、事件记录、并发版本、请求幂等、备份
  service.py     串行世界操作的可嵌入服务层
  server.py      认证 HTTP API 和自动时钟
  client.py      连接服务的命令行客户端
  admin.py       数据库查看/备份
  cli.py         离线批量模拟
examples/         世界、人设、场景和多步骤项目示例
scripts/          基准生成、一键验收、可复现 LLM 演示和日志工具
tests/            核心、认知、存储、HTTP 与生产边界测试
results/          真实运行产生的 SQLite、CSV、JSON 和测试报告
  v2/            v2.0 独立的长期/扰动项目数据
 docs/            架构、伪代码、完整运行流、API、部署、迁移、实验
```

## 4. 建议按这个顺序学习源码

1. [EXECUTION_FLOW.md](docs/EXECUTION_FLOW.md)：从命令到完整事件流的**实际处理顺序**。
2. [PSEUDOCODE.md](docs/PSEUDOCODE.md)：全部重要分支的伪代码，独立于 Python 细节。
3. [ARCHITECTURE.md](docs/ARCHITECTURE.md)：事实权限、模型边界及系统不变量。
4. `simlife/engine.py` → `actions.py` → `planning.py` → `policy.py`。
5. [EXPERIMENTS.md](docs/EXPERIMENTS.md)：实际跑过什么、怎么量化、发现什么问题。
6. [API.md](docs/API.md) 与 [OPERATIONS.md](docs/OPERATIONS.md)：开始正式使用。

## 5. 最重要的事实与安全规则

**LLM、用户消息、人物记忆、主观信念都不能直接改世界库存或位置。** 行动只有经过世界校验、时间推进、完成结算后才真正生效；项目也只能由已完成的动作提供进度证据。外部请求必须提交认证令牌；写操作使用不重复的 Idempotency-Key，断线重试不会重复执行。

**本工程不是完整事件溯源**：`events` 表是审计日志，恢复依赖 `checkpoint`。更改世界、Persona、项目配置或规则版本会改变存档指纹，因此旧存档必须备份并显式迁移，不能强制复用。

> 代码和数据是已在本地 Python 3.13 环境运行的结果；跨操作系统服务管理和远程 LLM 的实际可用性应在部署机器上再次检查。
