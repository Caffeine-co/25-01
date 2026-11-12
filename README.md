# WorldLife v0.5 · 无 LLM 的世界与生命模拟实验

基于 `Caffeine-co/25-01` 的 `world-preview`（v0.1）继续开发。**核心仍是一个 Python 事件循环，不依赖 NoneBot、LLM、Pydantic 或第三方库。** 目标是验证角色在有限认知下可以做决定、遇到失败后调整行动，并且让世界独立结算实际后果。

> 这是**可运行、可重复测试的教学／研究原型**，不是通用的真实生命模拟器。`vitality` 与需求值都是 0–100 的游戏式抽象指标；不具备医学准确性，也不能据此推断人类健康状况。

## 1. 最快上手

Python **3.11+**，在工程根目录运行：

```powershell
# 自动化验收（30 项）
python -m unittest discover -s tests -v

# 一个熟悉住所的普通角色，运行 72 小时（必须使用一个新 db）
python -m simlife examples/scenarios/apartment.json --hours 72 --db data/my_apartment.db

# 资源不足：先碰到空水龙头，再改用另一种水源
python -m simlife examples/scenarios/resilience.json --hours 12 --db data/my_resilience.db

# 不认识设施的探索者
python -m simlife examples/scenarios/discovery.json --hours 12 --db data/my_discovery.db

# 一个 NPC 在同一地点帮助低行动能力的角色
python -m simlife examples/scenarios/care.json --hours 12 --db data/my_care.db

# 定期补给的公寓，在 30 天内持续运行
python -m simlife examples/scenarios/apartment_sustainable.json --hours 720 --db data/my_stable.db

# 从头重新生成 72 小时与 30 天实验报告、CSV 和 SQLite
python scripts/benchmark.py
```

**再次对同一个 `--db` 执行 `--hours 72`，是在原有世界时间上继续前进 72 小时。** 要从头运行，请换一个数据库文件。`results/` 内是已执行的实验输出，重新运行 `benchmark.py` 会覆盖这部分示例实验文件。

## 2. 按真实执行顺序理解代码

```text
cli.main()
  └─ config.load_scenario()           读取三个 JSON：世界/人设/角色装配
      └─ SQLiteStore.load_or_create() 恢复或创建 WorldRuntime
          └─ WorldRuntime.run_until()
              ├─ Dynamics.advance()   根据时间演化需求与行动能力
              ├─ _dispatch(decide)
              │   ├─ observe()         仅观察当前地点
              │   ├─ remember_observation() 更新设施记忆
              │   └─ policy.choose()   保持目标/探索/选行动
              ├─ _dispatch(move_finished) 移动成功才更新地点
              ├─ _dispatch(use_finished)  检查资源并结算实际效果
              └─ _dispatch(assist_finished) 简化 NPC 协助
          └─ SQLiteStore.save()       原子保存检查点与事件日志
```

**建议第一份阅读材料：[docs/RUN_THROUGH.md](docs/RUN_THROUGH.md)**。它沿着 t=0 到第一次喝水，以及资源失败和 NPC 帮助的运行轨迹逐步解释每个调用。

## 3. 文件与职责

```text
simlife/
  model.py       数据结构：世界定义、角色状态、个人认知、行动意图
  config.py      JSON 装配与输入校验
  engine.py      世界时间、事件队列、行动执行（核心）
  systems.py     可替换的自然演化、决策、行动结算规则
  perception.py  当前地点可见内容 → 个体设施认知
  policy.py      需求目标 → 已知设施/探索 → 下一步行动
  projection.py  只读角色视图（供日后外部交互使用）
  store.py       SQLite 存档与事件日志
  cli.py         命令行启动
examples/
  worlds/        各个世界的地理、设施、资源和预设事件
  personas/      个体需求、身体规则及简单协助能力
  scenarios/     某世界中放入哪些角色、角色已知什么
scripts/
  benchmark.py   运行多场景基准并生成数据
results/         已实际运行的 SQLite/CSV/JSON 结果
  summary.json
  *_72h.db
  *_72h_hourly.csv
  ...
tests/
  test_simulation.py
 docs/
  RUN_THROUGH.md
  ARCHITECTURE.md
  ITERATION_REPORT.md
  EXTENSIONS.md
```

## 4. 本版真实新增了什么

| 阶段 | 已实现的最小能力 | 未实现的部分 |
|---|---|---|
| v0.2 | 当前地点观察、有限设施知识、失败反馈、探索新地点 | 复杂感官、事实置信度和社会认知 |
| v0.3 | 持续维持一个需求目标、逐段移动、失败后换目标设施 | 通用 GOAP、多层长期计划 |
| v0.4 | `vitality`、持续风险损耗、行动阈值、休息中恢复 | 完整身体结构、疾病和医学模型 |
| v0.5 | 独立 NPC、同地点协助、定时设施变化、重复资源补给 | 完整 NPC 社会、自由生成世界事件 |
| 接口准备 | `actor_view()` 只读状态、可注入规则接口 | QQ/NoneBot/LLM 接入与真实外部消息 |

**不是 LLM 在写 World 状态。** Life 仅提交意图；资源、行动完成和跨角色协助必须由 `WorldRuntime` 实际执行并记录。角色的“知道”不等于世界客观存在。

## 5. 三件绝不能混淆的事情

1. `WorldDefinition` 描述世界客观可用的规则、设施与地点；`LifeState.beliefs` 保存角色**认为**有哪些设施，可能过时。
2. `goal` 是角色持续想解决的问题，例如 `thirst`；`busy` 是正在执行的具体动作，例如 `move`。一个动作失败不等于目标完成。
3. `queue` 保存**未来待执行事件**；SQLite `events` 表保存**过去已发生的事件记录**；`checkpoint` 保存重启需要的完整现场。

## 6. 验收结果（真实运行）

本版有 **30 项测试**。另跑过 7 个场景 × 72 小时，以及 6 个场景 × 30 天的实验。两种有明确周期补给的世界在 30 天内分别完成 168 与 119 次设施行动，**没有行动失败或行动能力阻断事件**；有限库存世界则会因为资源耗尽而出现真正的持续危机，系统不会凭空治愈或重置库存。具体见 [迭代报告](docs/ITERATION_REPORT.md) 与 [原始数据](results/summary.json)。

## 7. 接下来在哪里扩展？

- 增加新世界和新生命类型：先仿照 `examples/worlds/`、`personas/`、`scenarios/`。不同类型生命可用同一引擎。
- 增加自定义世界规律：扩展 `Dynamics`、`DecisionPolicy` 或 `FacilityResolver`，详见 [docs/EXTENSIONS.md](docs/EXTENSIONS.md)。
- 下一阶段真正有价值的改造：行动中断、目标进度与前置条件、可变空间知识、个体心理、动态 NPC 日程。不要急着重新加入旧版本的全部数值字段。

**注意：旧 v0.1 的 SQLite 存档与本版不兼容。** 本版配置指纹含规则版本；必须用新 `--db` 开始模拟。这个设计是为了防止默默按照新规则解释旧状态。
