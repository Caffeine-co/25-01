# 实际运行流：从启动到角色完成项目、遇到故障、重启恢复

本文对应 `examples/scenarios/art_project_disrupted.json`。所有 `t=` 都是**模拟世界的分钟数**，不是墙上时钟；时间线在本地真实运行获取，并非概念编造。

## 一、程序启动

### 1. CLI / 服务层

离线批处理 `python -m simlife` → `simlife/cli.py:main()`；持续服务 `worldlife-server` → `simlife/server.py:main()` → `RuntimeService(...)`。两条路最终都调用：

```text
config.load_scenario(scenario.json)
     ↓
SQLiteStore.load_or_create(scenario)
     ↓
WorldRuntime(scenario) / WorldRuntime.from_snapshot(...)
```

读取场景时加载三类 JSON：世界（地图、设施、库存、外部事件）、人设（需求、人格、能力）、角色装配（角色位于哪里、知道什么、有什么长期项目）。

### 2. `WorldRuntime.__init__()`

初始库存从世界装载，人物复制到可修改状态。将角色 t=0 的 `decide` 放入未来事件队列；将 t=300 停用练习设施、t=900 恢复设施的事件放入相同队列。**此时没有任何行动已经完成。**

## 二、角色开始行动

```bash
worldlife examples/scenarios/art_project_disrupted.json --hours 24 --db data/run_trace.db
python scripts/trace.py data/run_trace.db --until 1120
```

以事件队列顺序为准：

| 模拟时间 | 发生什么 | 关键函数 |
|---|---|---|
| t=0 | 角色初次观察卧室，目标未紧迫，安排下次决策 | `_decide`、`perception.observe` |
| t=240 | 口渴达到阈值，目标改为 `thirst`；开始走到走廊 | `policy.choose_action`、`Move.prepare` |
| t=242 | 移动结算，到走廊；接着前往厨房 | `Move.complete`、`_finish_action` |
| t=245 | 到达厨房，开始使用水龙头 | `UseFacility.prepare` |
| t=249 | 饮水完成，库存和口渴才真正改变；项目重新被选中 | `StandardFacilityResolver.resolve`、`project_intent` |
| t=252 | 从厨房走回走廊 | `Move.complete` |
| t=254 | 到达画室，开始第一个 90 分钟的绘画项目步骤 | `UseFacility(practice=True)` |
| t=300 | 世界事件停用画室练习设施；正在执行的行动暂未立即结算 | `_dispatch(facility_disable)` |
| t=344 | 练习结束时重新检查，发现设施已停用。动作失败，项目 index 仍为 0，退避重试 | `UseFacility.complete`、`_project_failure` |
| t=524 | 再次尝试项目步骤 | `project_intent` |
| t=614 | 第二次失败；记录失败和重试时间 | `_project_failure` |
| t=734 | 饥饿需求紧迫，去厨房进食，项目不是永远最高优先级 | `DecisionPolicy` |
| t=900 | 世界事件重新启用练习设施 | `_dispatch(facility_enable)` |
| t=949 | 一次普通练习活动成功后，项目继续推进 | `UseFacility.complete` |
| 后续 | 项目每个步骤经成功结算追加证据，4 步全部完成 | `_complete_project_step` |

注意：世界停用事件与完成事件分离，所以人物不会在 t=300 因一句“设施不能用”就获得或失去已完成的技能。失败的动作不会让项目 index 增加。

## 三、计划中途重启

1. 选择时间点 `t=300`，此时人物 `busy` 包含当前动作、目标、完成时间和 `action_ticket`。
2. `SQLiteStore.save()` 保存 `WorldRuntime.snapshot()`：包括动作、待完成事件、人物目标、项目步骤、事件队列和库存。
3. 重启进程后 `load_or_create()` 从同一个数据库恢复，按既定的下一事件继续运行。
4. t=344 仍然会进行设施有效性检查。分段运行与一次性运行应得到完全相同的世界快照和后续事件序列。

配套自动测试：`tests/test_production.py::ProjectTests.test_project_resumes_while_busy`。

## 四、主观信念被修正的真实过程

场景 `apartment_with_knowledge`：

```text
t=0    外部传言：meeting_place = park，confidence = 0.6
       人物听到的是传言，世界空间不会因此增加 park

t=120  world event: meeting_place = studio
       source = world_observation, confidence = 1.0
       信念更新为 studio，历史保留 park

t=600  world event: meeting_place = kitchen
       第二次直接观察更正旧信息，历史仍可追溯
```

`knowledge.observe_belief()` 根据证据来源和置信度决定修正，不会去修改世界的地图或设施数据。

## 五、外部 API 的真实交互链路

客户端运行：

```bash
worldlife-client project resident_01 examples/projects/sketch.json
```

（请首先启动 `worldlife-server` 并配置相同的 `WORLDLIFE_SERVER_TOKEN`。）

```text
client.call:
  POST /v1/project + Bearer + unique Idempotency-Key
       ↓
server.Handler.do_POST:
  认证 token，检查 Content-Length，读取 JSON
       ↓
service.RuntimeService.mutate:
  按 request_id 查历史回执；检查 payload hash；加锁
       ↓
service._operate('project'):
  Project dataclass -> validate_project -> world.add_project
       ↓
store.SQLiteStore.save:
  BEGIN IMMEDIATE -> revision 校验 -> checkpoint/events/request 一次提交
       ↓
HTTP JSON: {"project":"...","status":"created"}
```

若客户端断线后以相同 ID 和相同 payload 重试，不会新增第二个项目；若同一 ID 发送了不同内容，返回 409。没有有效 Bearer Token 时，连人物状态都无法读取。

## 六、LLM 不是万能执行器

外部用户发送聊天消息：

```text
HTTP/chat -> CognitionService.interact
  -> 保存原始消息作为外部观察
  -> 根据人物可见状态、个人回忆、人物简介构造受限输入
  -> 网络模型返回 JSON {reply,action}
  -> validate_response 严格校验内容和动作类型
  -> world.submit_intent
       -> 如果路不在个人地图：拒绝瞬移
       -> 如果设施未知或人物忙碌：拒绝
       -> 如果动作有效：排队等待真实完成时间
  -> 事务保存回复与当前世界
```

反思走 `reflect()`，返回 `{reflection,project}`。项目提议只能添加经校验的未来行动，不能直接宣布项目成功。返回文本保存为 `llm_inference` 来源的主观记忆。

## 七、生产错误场景与恢复

- **模型超时/输出非法**：记录回退事件，返回离线保底回复，不执行模型拟议动作。
- **库存不足**：设施实际结算失败，库存不能变负，人物记录失败并降低重复尝试频率。
- **进程中断**：最近一次成功 `save()` 以前的事务保留，之后未提交的内存事件不会写入。
- **重复 POST**：`requests` 表返回原先的结果，防止重复扣库存和增加技能。
- **多进程同时使用同一数据库**：后写者遭 `RevisionConflict`；不能继续以旧内存状态写世界。
- **服务停止**：真实时间停止推进；重新启动会从最后提交的模拟分钟继续。

代码阅读顺序建议：`server.py` → `service.py` → `store.py` → `engine.py` → `planning.py` → `actions.py` → `systems.py` → `memory.py`。这条顺序和一次完整实际请求的执行路径一致。
