# 架构说明：World / Life / Action / Cognition

## 设计目标

让一个或多个虚拟人物即使没有聊天输入，仍能随模拟时间推进、形成目标、执行行动、接受失败和形成经历。规则提供**稳定、可验证的世界因果**；LLM 只在明确需要语言或开放式解释时参与，不能绕过引擎篡改状态。

## 模块依赖与数据流

```text
  world.json ──┐
  persona.json ├────> config.load_scenario ─────> Scenario
  scenario.json┘                                  │
                                                ▼
                                  engine.WorldRuntime.run_until()
                                                │
                            ┌───────────────────┴───────────────────┐
                            │                                       │
                 systems.Dynamics.advance()                engine._dispatch()
                   （时间自然演化）                            │
                                      ┌───────────────────────┼────────────────────┐
                                      ▼                       ▼                    ▼
                             外部世界事件             decide(actor)         action_complete
                                      │                       │                    │
                                      │        perception.observe()                │
                                      │                  ↓                          │
                                      │           remember_observation             │
                                      │                  ↓                          │
                                      │            policy.choose()                  │
                                      │                  ↓                          │
                                      │           ActionIntent（只读建议）            │
                                      │                  ↓                          │
                                      │        actions.prepare() ──排队─> actions.complete()
                                      │                                       │
                                      └────────── 世界裁决与事件日志  <─────────┘
                                                             │
                                                store.SQLiteStore.save()
                                                   （快照+日志原子事务）
```

独立的 `cognition.CognitionService` 在外部聊天适配器收到消息时调用。它使用 `projection.actor_view()` + `memory.retrieve()` 形成**角色可见**的上下文，取得 JSON 回复及动作建议。通过 `WorldRuntime.submit_intent()` 二次验证，执行仍归 `actions` 和 `WorldRuntime`。

## 核心对象与所有权

| 数据类型 | 保存在哪里 | 谁可以修改 |
|---|---|---|
| 世界拓扑与设施定义 | `WorldDefinition` | 场景构造时固定 |
| 资源库存、设施启停 | `WorldRuntime` | 世界事件与行动完成结算 |
| 角色地点、行动占用 | `LifeState` | 引擎与行动完成结算 |
| 需求、行动能力、短时情绪 | `LifeState` | `Dynamics` 与合法事件更新 |
| 设施认知与已探索道路 | `LifeState.beliefs/known_edges` | 感知行为写入 |
| 记忆/关系/技能/长期目标 | `LifeState` | 真实行动或收到的观察更新 |
| 模型请求预算 | `WorldRuntime.cognition_usage` | `CognitionService` 增计数 |
| LLM 文本 | `character_spoke` 事件 | 由认知服务提出；不等于世界变化 |
| 过去事件 | SQLite `events` | `SQLiteStore.save()` 追加 |
| 未来事件 | `WorldRuntime.queue` | 世界调度方法 |

## 两条不变量

### A. 角色主观认知不是全知视角

`WorldDefinition.connections` 是真实道路。`LifeState.known_edges` 只在人物实际处于某地点观察时建立该地点的边；`DecisionPolicy` 看到的只是它自己的 `known_edges`。角色可能认识地点名称，但尚不知道如何去到那里。

`WorldRuntime.resources` 只在动作结算或预设世界事件中使用。决策器只看到设施的作用、估计耗时和上次失败反馈，不读其他地点的实时库存。

来自外部用户的话（如“我已经给你水”）作为消息进入角色经历，不会直接将世界水库存增加。

### B. 行动意图不是结果

`ActionRegistry` 中的每种行动有两段：`prepare()` 验证可行性，返回时长；`complete()` 在到期时复核实际情况并写入后果。行动执行中断依靠 `ticket`：旧 `action_complete` 事件仍可能位于队列，但其票据已失效，不会产生重复的世界状态变化。

多人动作可返回 `ActionPlan(duration, participants=(...))`：所有参与者在同一时段标记为占用。任一参与者被打断时，整个多人行动解除占用；只有完成事件成功执行，才结算社会关系。

## 决策策略

`policy.choose_action()` 是一个不修改世界的可解释规则决策器，优先级：

1. 有能力时协助眼前陷入困境的 NPC。
2. 如果需求达到阈值，寻找已知、可达的设施；持续追逐目标，只有更紧急的需求才改变目标。
3. 如果需求没有可行方案，探索已知但尚未到访的地点。
4. 如有到期承诺，优先尝试兑现。
5. 白天在有社交对象且空闲时，视性格与上次社交时间主动交流。
6. 在兴趣活动可行、时间和体力满足条件时，主动练习。
7. 其他情况下等待 30 模拟分钟，再评估。

这是一套规则式、确定性的最小人物决策器。**没有声称实现真实人类的全领域自主推理**。长期目标通过 `LongGoal` 记录实际技能进度，但不含通用 GOAP 或复杂任务依赖图。

## 关系、情绪、记忆的更新

- 短时 `Emotion` 每分钟向中性衰减；只有外部事件或真实行动结果会对其施加冲击，不将上次情绪重复当成新事件。
- 关系信任使用趋近饱和的增量：正面事件变动 `delta*(1-trust)`，负面事件变动 `delta*trust`，避免普通社交快速叠加到极值。
- `Memory` 使用固定上限保存最近重要经历，完整已发生事件保存在 SQLite `events`；简单记忆检索结合 Unicode 字符片段匹配、显著度、新近度。
- 技能仅在合法 `practice` 的实际结算后发生变化，达到长期目标阈值才发出 `long_goal_completed`。

## 事件顺序与持久化

同一模拟分钟先执行**世界外部事件**，再执行**行动完成**，最后执行**人物决策**。同优先级由自增序号决定顺序。这样设施启停能在同一分钟的行动结算之前生效。

存档保存完整现场：世界时间、资源、启停状态、角色状态、未来队列、模型预算；日志保存发生过的行为。两者在一个 SQLite 事务里提交。**这不是完整 Event Sourcing**，不能只靠日志在任意旧版本重建状态；跨规则版本的旧快照一律拒绝自动恢复。

## 技术边界

- Python 3.11+；核心无第三方依赖；单进程、单线程、内存事件队列。
- 模拟每分钟积分需求和身体变化，成本与模拟分钟数 × 人物数相关；适合小规模研究，不是万人级分布式仿真。
- 一个世界的资源由全局库存字典抽象表示，没有物品产权、交易、真实身体组织或经济系统。
- 网络模型调用属于 CLI 的外部交互过程，不能放在每分钟时间推进的循环里；将来接真实平台需额外实现异步工作队列、Outbox、鉴权、幂等和持久化重试。
