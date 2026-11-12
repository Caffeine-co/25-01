# 沿实际执行时间线逐函数讲解

本文使用打包中真实运行过的 `results/apartment_sustainable_720h.db`、`results/apartment_interrupt_72h.db` 进行追踪。示例数据中的 `t` 为**模拟启动后的绝对分钟**，不是现实世界时钟。建议一边阅读，一边打开 `simlife/engine.py` 和 `simlife/actions.py`。

## 一、从主命令开始

执行：

```bash
python -m simlife examples/scenarios/apartment_sustainable.json --hours 72 --db data/tutorial.db --tail 30
```

1. `simlife/__main__.py` 调用 `cli.main()`。
2. `config.load_scenario()` 加载 JSON：世界、人物、具体人物的起始位置与认知。
3. `SQLiteStore.load_or_create()` 没找到数据库快照，创建 `WorldRuntime`。
4. `WorldRuntime.__init__()` 克隆人物与世界资源，安排世界事件（t=1440 的水/食物补给，之后每隔 1440 分钟重复）和人物第 0 分钟的 `decide`。
5. `run_until(4320)` 不断取出下一条事件，先推进自然动态，再派发事件；时间最终达到 72 小时。
6. `store.save()` 在同一事务中持久化现场和已发生事件。

这时还没有调用任何 LLM。

## 二、t=0：人物刚启动，为什么什么都不做？

第 0 分钟从 `queue` 弹出 `decide`，执行 `_decide('resident_01')`。

人物位于 `bedroom`，`perception.observe()` 只看见卧室里的 `bed`。它先观察从卧室可通往 `hall` 的已知道路，并且保存到 `known_edges`。尽管人物“听说过”厨房和画室，不代表此刻知道远处所有道路的拓扑。

`policy.choose_action()` 检查需求阈值、到期承诺、是否有人可交流、是否到了主动练习时间。此刻需求不足，模拟时间相当于 00:00，没有合适的社交或练习条件，于是返回 `Decision(None, None)`。

引擎安排下一次 `decide(t=30)`。

## 三、t=240~249：第一次满足口渴

仓库中真实的事件记录：

```text
 t=240  goal_changed      None → thirst
 t=240  action_started    move → hall
 t=242  actor_moved       hall
 t=242  action_started    move → kitchen
 t=245  actor_moved       kitchen
 t=245  action_started    use → tap
 t=249  action_completed  use tap，thirst 实际降低 45.77
 t=249  goal_changed      thirst → None
```

这些事件对应实际函数：

- `HomeostasisDynamics.advance()` 使口渴需求达到阈值。
- `choose_action()` 选择 `thirst`，发现水龙头在厨房，规划第一段 `move(hall)`。
- `ActionRegistry.get('move')` 得到 `Move`，`Move.prepare()` 检查连边与能力，只计算时长，不修改位置。
- `WorldRuntime.schedule()` 安排未来的 `action_complete`。
- 直到 t=242，`Move.complete()` 才真正把位置设置为 `hall`，并立即重新决策。
- 到 t=245 才到达厨房，开始 `UseFacility.prepare('tap')`。
- 到 t=249，`UseFacility.complete()` 调用 `StandardFacilityResolver.resolve()` 检查真实资源，扣减库存、改变需求，并更新需求锚点。

注意：这一连串动作不是一次 LLM 生成的故事文本，而是几条独立结算的程序事件。

## 四、t=489~584：无需用户指令的主动练习

```text
 t=489  goal_changed       None → practice:drawing
 t=489  action_started     move → hall
 t=492  actor_moved        hall
 t=492  action_started     move → studio
 t=494  actor_moved        studio
 t=494  action_started     practice → practice_drawing
 t=584  practice_completed drawing: 4.0 → 4.96666667
 t=584  action_completed   practice
 t=584  goal_changed       practice:drawing → None
```

驱动这次练习的不是饿、渴或疲劳，而是 `Persona.interests['drawing']`、时间窗口、体力门槛和距离上次创作的间隔。这个例子说明人物已能在没有聊天输入的情况下产生非生存目标。

`t=494` 开始练习时**技能并不改变**；真正的提升出现在 `t=584` 行动结束时。接着 `progress_skill_goal()` 更新长期“绘画能力达到 40”的进度，未来达标才会写入 `long_goal_completed`。

## 五、t=720 的承诺，为什么直到 t=859 才完成？

`scenario` 为人物配置了第 720 分钟的绘画承诺。但是第 720 分钟没有强制直接让人物瞬移或取消所有事情。角色还在处理生存需求：

```text
 t=734  goal_changed       None → hunger
 t=739  action_started     use → meal
 t=764  action_completed   meal
 t=764  goal_changed       hunger → commitment:practice_drawing
 t=769  action_started     practice → practice_drawing
 t=859  commitment_completed
 t=859  practice_completed drawing: 4.9667 → 5.92527778
```

承诺有宽限期，且只有真正的练习完成才算兑现。若到期后一直没有可行行动，系统会把承诺标记为 `missed`，而不是假装完成。

## 六、另一条分支：t=550 的行动中断

`results/apartment_interrupt_72h.db` 与上面使用相同生活场景，但额外在 t=550 安排一次显著降低行动能力的世界事件。

```text
 t=494  action_started      practice → practice_drawing（计划 t=584 完成）
 t=550  world_vitality_changed  -95
 t=550  action_interrupted  practice，原因 low_vitality
 t=550  goal_changed        practice:drawing → None
```

引擎发现角色行动能力已经低于可用门槛，调用 `interrupt()`：

1. 清理当前 `busy`。
2. 增加 `action_ticket`。
3. 记录中断原因和经历。
4. 原有 t=584 的完成事件留在队列中，但处理时发现 `ticket` 不匹配，**不再产生练习成果**。
5. 调度重新决策，人物改为优先恢复可行动状态。

因此该 72 小时场景只有 4 次完整练习，而对照场景有 6 次。这个差别来自可追溯的行动中断，不是角色生成了不同描述文本。

## 七、失败也会变成经历

在 `apartment_scarce` 资源短缺世界中，前几次尝试饮水可能遇到设施停业，后续可能遇到水库存耗尽。

```text
 t=969  action_failed: use tap → facility_disabled
 t=1153 action_failed: use tap → facility_disabled
 t=2687 action_failed: use tap → resource_unavailable
```

`UseFacility.complete()` 检查失败，记录个人对该设施的上次使用结果，并设置重试冷却时间；没有扣减不存在的资源，也没有修改成“水已经喝到了”。当未来世界事件发生时，角色才可能再次尝试。

## 八、两个人物的交谈为什么不能随意结束？

在 `roommates.json` 中，若一名角色发起 `socialize(other)`：

- `Socialize.prepare()` 要求双方同地点且另一人空闲，返回 `ActionPlan(duration=20, participants=(other,))`。
- 引擎同时标记双方占用，记录一次 `action_started`。
- 两人无法在这 20 分钟里同时执行互斥行动。
- 完成后才更新彼此关系、短时情绪和情景记忆。
- 若任一方收到必须打断的世界事件，取消整项行动。

在初版实验中未占用另一方，30 天内发生了两次“谈话对象已经离开”。加入参与者占用后重新运行，社交次数从 28 变为 29，且没有 `target_left` 失败。详见 `EXPERIMENTS.md`。

## 九、恢复运行不会重复执行动作

```bash
python -m simlife examples/scenarios/apartment_sustainable.json --hours 24 --db data/resume.db
python -m simlife examples/scenarios/apartment_sustainable.json --hours 24 --db data/resume.db
```

第二次是在第 24 小时继续到第 48 小时，数据库中保留了 `queue`、`busy`、`ticket`、资源、已知地图、人物情绪、长期目标和认知调用预算。测试 `test_05_snapshot_resumes`、`test_06_in_flight_action_resumes` 验证了中途恢复与一次性运行的一致性。

## 十、如何自己检查原始日志？

直接使用 SQLite 查询：

```sql
SELECT minute, type, actor, details_json
FROM events
WHERE minute BETWEEN 480 AND 600
ORDER BY id;
```

或者执行：

```bash
python scripts/trace.py results/apartment_interrupt_72h.db --from-minute 480 --to-minute 600
```

**完整路线图**请配合 `PSEUDOCODE.md` 阅读。
