# WorldLife Starter v0.1 — 可运行的跨世界观 World → Life 骨架

这是一个 **无 LLM / 无 NoneBot / 无第三方运行时依赖** 的最小世界与生命模拟器。

它用于验证：World 独立保存地点、资源和事件；Life 按自己的需求选择行动；World 负责执行、结算；发生的事件可以记录和恢复。

**当前不是完整的虚拟生命系统，更不是生物学或心理学仿真。** 内置动态模型是可替换的玩具级“需求缺口”模型，目的是先做出可靠的因果闭环，再细化行为与心理机制。

## 1. 环境与快速运行

- Python 3.11+，无 pip 运行依赖。
- 在本目录执行（Windows PowerShell 也可以）：

```powershell
python -m simlife examples/scenarios/apartment.json --hours 72 --db data/apartment.db
python -m simlife examples/scenarios/orbital.json --hours 72 --db data/orbital.db
```

命令会打印最后时刻的角色需求值、位置、库存及最近事件。

**再次运行同一命令将从数据库中的世界时间继续推进 72 小时，而不是重新开始。** 想重跑实验应选择新 `--db` 文件。修改场景、World 或 Persona 后也需要新存档，否则会提示不匹配。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

可选安装为本地 Python 包：

```powershell
python -m pip install -e .
worldlife examples/scenarios/apartment.json --hours 72 --db data/apartment.db
```

所有文件均使用相对项目根目录的示例路径；命令应在项目根目录运行。

## 2. 目录和职责

```text
worldlife_starter/
├── pyproject.toml
├── simlife/
│   ├── model.py       # 世界、设施、角色、事件的数据类型
│   ├── config.py      # 拼装场景，并验证世界与角色兼容性
│   ├── systems.py     # 可替换的生理演化/决策/设施结算接口
│   ├── policy.py      # 寻路与不依赖 LLM 的效用决策
│   ├── engine.py      # 世界时间、事件队列、行为执行与结算
│   ├── store.py       # SQLite 检查点 + 已结算事件（事务写入）
│   ├── cli.py         # 运行入口
│   └── __main__.py    # python -m simlife
├── examples/
│   ├── worlds/        # 不同世界的地点、设施、资源与外部事件
│   ├── personas/      # 不依赖世界位置、剧情名词的生命需求配置
│   └── scenarios/     # 世界与角色的组装：角色在哪里开始、知道哪些地点
├── tests/
│   └── test_simulation.py
└── docs/
    ├── BUILD_GUIDE.md # 请求/事件/状态流的逐步讲解
    └── EXTENSIONS.md  # 如何接入 IP 特殊机制、NoneBot 和 LLM
```

## 3. 为什么这样才能跨 IP

- `World` 文件只声明地点、设施、物资、外部事件，不假定人类、学校、城市或日历。
- `Persona` 文件只定义内在需求及相对重要性，不写角色居住在哪个 IP 世界。
- `Scenario` 文件把某个角色放进某个 World，设置已知地点。**同一 Persona 可以绑定多个兼容 World；一个 World 可以容纳多种 Persona。** 不兼容的资源/能力需要另行实现，而不是静默假装兼容。
- 通用 `engine` 对 `actor_id`、`world_id`、`facility_id` 的名字没有业务假设。
- `systems.py` 的三个接口允许替换内在动态规律、决策策略、行为结算规则，而不用改核心事件循环。

随项目提供两个风格差异明显的配置：

| 文件 | 生命需求 | 世界设施 |
|---|---|---|
| apartment | thirst、hunger、sleep_pressure、fatigue、creative_urge | 水龙头、食物、床、工作台 |
| orbital | power_deficit、thermal_load、information_need | 充电端口、冷却站、终端 |

跨 IP **不是**意味着给非人角色换个名字就能复用人类全部规则。不同 IP 可能需要魔力循环、重力、寿命、种族能力等不同模拟规则；需要专用 `Dynamics` / `FacilityResolver`，但不必改 World-LIfe 的因果调度核心。

## 4. 一次最基本的状态循环

```text
t=0  World 发出 decide 事件
     ↓
Life 根据自身需求和“已知地点”评估行动效用
     ↓
选中合适设施；若不在同一地点，先安排一段 move
     ↓
World 推进所需时间，其间所有 Life 的需求按规则持续变化
     ↓
移动完成 → 新位置生效 → 重新决策
     ↓
使用设施开始 → 经过执行时间
     ↓
World 检查位置和资源，扣减库存、改变需求、记录结果
     ↓
Life 再决策；若没必要做什么，30 分钟后重新评估
```

世界外部事件（例如资源补给）也进入**同一个事件队列**，即使角色暂时不行动也会执行。

## 5. 数据语义

需求值统一定义为“需求缺口”：0=满足，100=非常迫切。它们没有医学单位。

- `initial`：初始缺口。
- `rise_per_hour`：基础规则每小时增加多少缺口点；**不是**实际生理定律。
- `threshold`：启动主动满足需求的参考阈值。
- `priority`：该角色对这种需求的相对权重。
- `effects`：设施使用成功后对各需求缺口施加的变化；负数意味着满足。

`model.py` 将角色当前状态与角色配置拆开；修改角色的“生理参数”不直接覆盖其运行时已形成的状态。

**不要**把派生出来的状态叙述反过来当作客观事实写入世界。后续 LLM 的文字只能成为表达或待验证的提案。

## 6. 存档与回放

SQLite 有两个表：

- `checkpoint`：唯一权威运行时快照，含当前分钟、所有角色的需求、所在位置、正在执行的动作、世界库存、待处理事件队列和事件顺序号。
- `events`：已经发生的动作与世界事件，用于调试和解释结果。

两者在同一事务里提交。`run_until()` 只推进内存，不会自动保存；CLI 会在一次运行结束后保存。应用进程中应设置可靠的周期性检查点。

当前引擎确定性运行，在相同配置和初始状态下，分段执行与一次性执行的世界状态一致。还没有引入随机源。

> 如需与 QQ、邮件、真实 API 等外部动作衔接，必须额外实现 outbox、幂等执行和失败补偿。模拟事务**不能**让外部副作用跟 SQLite 自动原子提交。本版故意不发送任何现实消息。

## 7. 当前已实现 / 未实现

**已实现**：场景装配；不同世界和需求配置；地点图与寻路；世界共享资源；简单需求积分；效用选择；移动与设施使用；动作持续时间；预定世界资源事件；多 Actor 数据容器；SQLite 原子检查点及事件记录；存档继续；基本回归测试。

**尚未实现**：完整人体生理、疾病、安全约束；真实生存损害和死亡判定；情绪、信念、记忆与主观感知；多步 GOAP 规划；被占用设施与复杂并发预留；NPC 对话与社会互动；复杂日历与世界时区；随机事件；NoneBot 桥接；LLM；真实外部动作 outbox；自动后台运行。

不要把当前基础需求模型的正常运行误解为已经获得合理的生命表现。它是**架构与因果闭环验证器**。

## 8. 推荐阅读顺序

1. `examples/scenarios/apartment.json`：角色和世界如何组合。
2. `examples/worlds/apartment.json`：World 如何声明“能做什么”。
3. `examples/personas/artist.json`：Life 的需求和差异来自哪里。
4. `simlife/model.py`：先理解类型，再看行为。
5. `simlife/policy.py`：Life 选行为。
6. `simlife/engine.py`：World 如何实际执行行为。
7. `simlife/store.py`：重启后如何延续因果过程。
8. `docs/BUILD_GUIDE.md`：逐步执行过程与测试。

**这份 Starter 不是对现有 25:01 或 TempVirtualLife 的直接替换，也不会自动修改你的 GitHub 仓库。** 建议先作为独立实验工程跑通后，再按 `docs/EXTENSIONS.md` 将生命周期接入 NoneBot。
