# WorldLife Next v1.0 — 可运行的虚拟人物研究工程

> 在 [`Caffeine-co/25-01` 的 `world-preview` 分支](https://github.com/Caffeine-co/25-01/tree/world-preview) 所采用的 **World → Life → Action → World** 思路上扩展。此工程为**独立可运行的后继实验包**，不是原分支的逐字镜像。
>
> **定位**：可审计、可复现的角色行为模拟研究原型；**不是**经过心理学或医学验证的真实人类模型。

本工程已实现：离散事件世界、有限感知、需求调节、主动兴趣活动、行动中断、多人社交占用、长期技能目标、基础情绪、关系、情景记忆、SQLite 续跑、可选 OpenAI 兼容 LLM 语言/行动建议接口、离线基准测试。

## 1. 立即运行

需要 **Python 3.11+**。**核心模拟不需要安装第三方库，也不需要网络。** 在本目录执行：

```bash
# 1) 全套自动化测试：58 项
python -m unittest discover -s tests -v

# 2) 运行 72 小时单人模拟，生成自有存档
python -m simlife examples/scenarios/apartment_sustainable.json --hours 72 --db data/my_run.db

# 3) 接着运行 72 小时（不会重置到零）
python -m simlife examples/scenarios/apartment_sustainable.json --hours 72 --db data/my_run.db

# 4) 双人物 7 天，自主练习及社交
python -m simlife examples/scenarios/roommates.json --hours 168 --db data/roommates.db

# 5) 重新生成各场景的数据（会覆盖 results/ 中对应输出）
python scripts/benchmark.py

# 6) 30 组固定种子、每组 7 天的扰动与回放一致性测试
python scripts/stress.py

# 7) 不联网，演示“模型建议被拒绝/接受”的权限边界
python scripts/llm_mock_demo.py
```

`results/` 已附带实际生成的 SQLite、CSV、汇总 JSON、测试和压力实验输出。直接查看 `results/summary.json` 或 `docs/EXPERIMENTS.md`。

## 2. 可选 LLM：只做建议，绝不直接改世界

离线示例不调用任何网络：

```bash
python -m simlife.chat examples/scenarios/apartment_sustainable.json \
  --db data/chat.db --actor resident_01 --message "今天想画什么？" --provider offline
```

如需**真实模型**，将以下环境变量配置为一个支持 OpenAI `/chat/completions`、`response_format=json_object` 的 API：

```text
WORLDLIFE_LLM_API_KEY=<你的密钥>
WORLDLIFE_LLM_BASE_URL=https://api.openai.com/v1
WORLDLIFE_LLM_MODEL=<实际可用模型名称>
```

运行时把 `--provider offline` 改为 `--provider remote`。如果提供商不支持 JSON Object 输出模式，请修改 `simlife/cognition.py` 的请求配置。默认每位角色每模拟日**最多四次模型调用**，可通过 `--max-calls` 调整。失败请求也计入额度；超时、解析错误、非法行动会回退或拒绝，不会修改世界。

**注意**：由于当前构建环境无法访问公网，真实远程 API 未进行在线端到端验证；已通过 ScriptedBackend 完成接口、权限、预算、回退测试。这一部分属于可用集成接口，而非经过生产压力测试的聊天服务。

## 3. 主要目录

```text
simlife/
  model.py        # 世界、人物、记忆、关系、目标等纯数据类
  config.py       # 世界/persona/scenario 三层装配与校验
  engine.py       # 模拟时间、事件队列、World 状态唯一写入入口
  systems.py      # 需求与身体状态自然演化；设施资源结算
  perception.py   # 当前地点观察、更新个人设施认知
  policy.py       # 需求目标 + 承诺 + 主动兴趣 + 社交选择
  actions.py      # 通用行动注册器，支持多人占用和中断
  memory.py       # 无外部依赖的轻量情景记忆检索
  projection.py   # 不包含世界私密信息的角色视图
  cognition.py    # 可选 LLM JSON 建议、预算、回退
  chat.py         # CLI 单轮消息交互（不发送第三方平台消息）
  store.py        # SQLite 快照与已发生事件日志
  cli.py          # 主模拟 CLI
examples/
  personas/       # 人物需求、兴趣、人设、长期目标
  worlds/         # 地点、设施、世界资源、事件
  scenarios/      # 具体把哪些角色放进哪个世界
scripts/
  build_examples.py  # 重建示例数据
  benchmark.py       # 5 个场景长期实验，CSV + SQLite + JSON
  stress.py          # 随机扰动与分段运行一致性检查
  trace.py           # 查询 SQLite 事件审计日志
  llm_mock_demo.py   # 模拟 LLM 的合法/非法意图演示
  verify.py          # 一键验收
results/             # 已实际运行的实验结果
  summary.json
  stress_summary.json
  *_hourly.csv
  *.db
  tests_console.txt
  benchmark_console.txt
  stress_console.txt
tests/
  test_simulation.py # 自动化回归

docs/
  ARCHITECTURE.md    # 架构与不变量
  PSEUDOCODE.md      # 完整执行伪代码
  RUN_THROUGH.md     # 按真实数据逐函数追踪
  EXPERIMENTS.md     # 实验设置、结果、缺陷与迭代
  EXTENDING.md       # 扩展人物/世界/动作/认知方法
  LIMITATIONS.md     # 未实现和未验证的能力
```

## 4. 最重要的三个边界

1. **人物提出意图，不产生现实后果。** 例如 `ActionIntent('move','hall')` 只启动移动；直到 `action_complete`，引擎才改变位置。
2. **人物知道的不等于客观事实。** `FacilityBelief` 与 `known_edges` 属于个体认知；程序不向决策器暴露其他房间的实时库存或未探索的地图连边。
3. **LLM 的语言不是执行证明。** 模型声称“我已经画完了”不会推进技能；只有世界实际结算 `practice` 才会改变 `skills` 和长期目标。

## 5. 与 world-preview v0.5 的关系

保留的核心概念：`WorldRuntime` / `LifeState` / `Persona` / `Facility` / `Observation` / `DecisionPolicy` / `HomeostasisDynamics` / `SQLiteStore`，以及 `worlds + personas + scenarios` 三层 JSON 装配。

新增：`ActionRegistry`、多人参与者预约、可中断动作、人格倾向、主动兴趣、长期技能目标、承诺、事件记忆检索、关系动态、受限 LLM 桥接、58 项新测试和扰动实验。

**兼容性声明**：无法直接读取旧版的 SQLite 快照；新版本指纹不同。并未将原分支所有原始场景与测试逐字复制进包；本包附带的是新场景和新测试，并与 v0.5 所公开的配置结构保持主要字段兼容。原始 v0.5 的所有外部定制规则未逐项验收。

详细依据、代码入口和限制见文档。
