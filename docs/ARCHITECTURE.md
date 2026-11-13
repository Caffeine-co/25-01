# 架构与运行不变量（v2.0）

## 总体分层

```text
外部 CLI / HTTP / 插件
          |
  RuntimeService -- 鉴权由 HTTP 提供；服务级 RLock、幂等检查和事务
          |
     WorldRuntime <---- CognitionService（只提交建议和反思）
       |   |   |
       |   |   +-- LifeState: 身体/人格/主观知识/记忆/目标/关系
       |   +------ DecisionPolicy / Project planner
       +---------- ActionRegistry / FacilityResolver / Dynamics
          |
          v
  SQLite checkpoint + events + requests
```

**世界是唯一客观状态权威。** `world.resources`、地点与设施有效性只有世界事件和动作处理器可以修改。`LifeState.beliefs`、`facts`、`propositions` 与 `memories` 是主观信息，允许过时、冲突或误解。`actor_view()` 不能泄露其他房间的库存或其他人物完整私有状态。

## 时间与事件

`QueuedEvent` 排序键是 `(minute, priority, sequence)`。世界事件优先于动作完成，动作完成优先于新决策，所以同一分钟设施停用会先于设施操作的完成结算。`run_until()` 在两个事件之间推进生理与情绪。无事件时无需逐次生成模型内容，但 `HomeostasisDynamics` 为可重放性按分钟积分。

`decide` 事件使用 `decision_ticket` 去重，避免同一人物因世界补给等多重唤醒而积累冗余链。`action_complete` 使用 `action_ticket`，旧的中断完成事件不会产生副作用。多人社交在开始时占用双方，结束时释放。

## 目标层次

- `drive`：随时间增长的需求缺口，紧急时优先于普通项目。
- `goal`：当前意图标签，不等于行动，不等于世界状态。
- `commitments`：具备到期时间与完成/错过记录的简单约定。
- `long_goals`：已结算的技能水平达到阈值后完成。
- `projects`：明确的多步行动任务，具备开始时间、截止时间、失败退避、步骤证据与结果。

项目的 `project_intent()` 仅从人物已经知道的路网和设施推导下一步行动。移动只是到达下一地点；只有目标步骤实际完成才使 `index += 1`。如设施在使用期间停用，记录失败并重试；达到重试或截止条件则明确标记失败。

## 记忆与信念

`Memory` 有来源标记，例如 `world_event` 和 `llm_inference`。记忆检索是轻量词项相关、显著度和新近度排序，**不是语义级推理**。`BeliefRecord` 存储当前信念、置信度、来源、证据 ID 和有界历史：同源重复不增长，直接世界观察可以覆盖传闻，冲突传闻仍有历史保留。信念不会自动写回世界事实。

## 存储和并发

- SQLite `checkpoint`：一份完整世界状态和待执行事件队列；记录 revision。
- `events`：过去发生的事件日志；不能单独重建全部状态。
- `requests`：幂等请求的 ID、规范化 payload SHA-256、已提交的回执。
- 一次 `BEGIN IMMEDIATE` 事务保证快照、事件和请求回执同时提交。
- 若两个服务都载入旧版本，只允许一个成功写入；另一个抛出 `RevisionConflict`，不得静默覆盖。
- 线程级 `RLock` 串行所有 RuntimeService 修改。**不要同时从多个进程写同一数据库**；并发版本保护是失误防线，不是分布式调度器。

## 不变量与已知限制

1. 世界时间只向前，资源在 `[0, capacity]`，`vitality` 和需求在 `[0,100]`，关系信任在 `[0,1]`。
2. 行动开始不会提前结算资源和技能；结算时重新检查前置条件。
3. 中断令旧完成事件失效；项目仅推进有成功证据的步骤。
4. 新的人格/世界规则改变要升级指纹，不自动旧库兼容。
5. 网络远端调用发生在服务层，不阻塞模拟引擎内部的事件队列；服务处理一次聊天时会持锁，因而单机高并发吞吐受到限制。
6. 自动时钟只补算服务在运行时经历的时间，不追偿停机时间；禁止无界事件补算风暴。
7. 原始事件和消息可能包含真实用户输入，应当设置数据访问权限和合理保留策略。
