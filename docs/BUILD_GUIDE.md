# 从 World 到 Life：代码执行过程逐步讲解

## 一、核心设计准则

- World 是权威状态：当前在哪里、资源剩余多少、是否完成了行动，都由 World Runtime 决定。
- Life 是自主决策者：它能选择“想做什么”，但不能凭文字宣称“已经成功”。
- Persona 是可配置的个体参数：只给出需求及权重，不携带真实 IP 的硬编码逻辑。
- Scenario 是装配文件：把一个或多个生命放进某个世界。
- Event 是改变世界的依据：发生过的事件可查，不依赖模型记住自己前几轮的故事。
- 时间由 World 单一维护：所有行为都是带持续时间的事件，避免独立任务各自想象时间。

## 二、启动时的数据流

调用命令：

```shell
python -m simlife examples/scenarios/apartment.json --hours 72 --db data/apartment.db
```

1. `cli.main()` 读取场景路径与持续时间。
2. `config.load_scenario()` 打开 Scenario，再加载 World JSON 与 Persona JSON。
3. 检查每条地图边是否指向已存在的地点，设施是否能使用世界资源，角色起点是否在世界地图中。
4. 返回 `Scenario(world, personas, initial_lives, fingerprint)`；`fingerprint` 防止改了配置还拿旧存档继续计算。
5. `SQLiteStore.load_or_create()` 尝试从数据库载入权威快照；没有就新建 `WorldRuntime`。
6. `WorldRuntime.__init__` 在时间 0 给每个角色安排一个 `decide` 事件，并把世界外部事件也排入队列。
7. `run_until(4320)` 开始推进三天。
8. `SQLiteStore.save()` 在同一个 SQLite 事务中提交事件日志与运行时快照。

## 三、为什么使用事件队列

假设第 150 分钟角色准备去厨房喝水，厨房在另一个地点：

```text
第 150 分钟：决策器选择水龙头
        ↓
第 150 分钟：World 接受移动到走廊的动作，预定第 152 分钟完成
        ↓
第 150~152 分钟：世界时间推进，各个角色需求持续积累
        ↓
第 152 分钟：移动完成；World 更新实际位置
        ↓
第 152 分钟：重新选择目标，计划下一段移动
        ↓
第 155 分钟：进入厨房
        ↓
第 155 分钟：开始使用水龙头，预定第 159 分钟完成
        ↓
第 159 分钟：World 检查资源、扣库存，更新缺水需求
```

注意：这些是**说明时序用的示例分钟数**，实际运行的事件时间由需求分数决定。

代码中：

- `_schedule()`：加入未来事件。
- `run_until()`：找到队列中的最近事件，并把所有状态推进到该时刻。
- `_dispatch()`：分派到具体事件处理器。
- `_decide()`：计算 Life 的行为意向，但不立即宣称结果。
- `_complete_move()`：世界修改角色位置。
- `_complete_use()`：世界调用 `FacilityResolver`，扣资源、结算影响。

角色处于行动期间时，仍然会受到持续的时间演化影响。不能因为“正在睡觉”就停止世界时钟。

## 四、为什么不能只使用 `if thirst > 80: drink()`

因为 `drink()` 是否可执行至少取决于：

- 角色是否知道水源在哪里；
- 角色能否通过世界地点图到达水源；
- 水源是否还有可用资源；
- 水源被使用是否需要一定时间；
- 世界规则是否允许本角色使用该设施。

这些都需要被 World 验证。当前 `UtilityDecisionPolicy` 负责选可达设施，并由 `StandardFacilityResolver` 检查结算时的地点和资源条件。

本版尚无完整 GOAP 规划器，但它已经有最基本的“需求 → 设施目标 → 最短路移动 → 使用 → 结算”规划链。新增更复杂的前置动作后，再引入多步骤规划更合适。

## 五、为什么不把所有数值都交给一个模型

假设在模拟中一名角色非常口渴：

1. `thirst` 随时间升高；
2. 角色选择到水源；
3. 如果取水失败，World 不记录饮水成功事件，也不会降低缺水需求；
4. 如果取水成功，World 在 `action_completed` 中记录其效果；
5. 之后 Life 的决策因实际状态变化而改变。

这个闭环可以避免“模型上一轮讲了自己喝水，下一轮又讲从未喝过水”的情况。

但这并不能保证世界模拟规则正确。需求变化速率与设施效果目前都是**人为的演示参数**，必须根据目标世界重新设计与校准。

## 六、存档恢复为什么要保存事件队列

只保存角色当前需求值还不够，因为一个角色可能已经开始一个耗时四小时的睡眠行动。

如果仅保存“当前睡眠压力”，重启后可能丢失行动，或重复执行同一行为。

本项目保存：

```json
{
  "minute": 300,
  "sequence": 16,
  "resources": {"water": 17},
  "lives": {
    "resident_01": {
      "id": "resident_01",
      "persona_id": "creative_humanlike",
      "location": "bedroom",
      "known_locations": ["bedroom", "hall", "kitchen", "studio"],
      "drives": {"thirst": 34},
      "anchors": {"thirst": {"minute": 240, "value": 29}},
      "busy": {"kind": "use", "facility": "bed", "finish": 480}
    }
  },
  "queue": [
    {"minute": 480, "sequence": 16, "kind": "use_finished",
     "payload": {"actor": "resident_01", "facility": "bed"}}
  ]
}
```

上方是**字段说明用的片段**，省略了实际角色的其他需求与事件，不是可以直接导入的完整存档。

只要动作、时间、事件顺序和数值都保存，才具备连续恢复的前提。

## 七、如何读 SQLite 日志

在 sqlite3、DB Browser for SQLite 或 Python 中执行：

```sql
SELECT minute, type, actor, details_json
FROM events
ORDER BY id DESC
LIMIT 30;
```

查看某个角色做过什么：

```sql
SELECT minute, type, details_json
FROM events
WHERE actor = 'resident_01'
ORDER BY id ASC;
```

查看资源补给：

```sql
SELECT minute, details_json
FROM events
WHERE type = 'world_resource_added';
```

注意 `events` 是结果日志，而不是应被再次执行的指令。重新载入的权威依据是 `checkpoint`。

## 八、验证跨世界观

```shell
python -m simlife examples/scenarios/apartment.json --hours 72 --db data/apartment.db
python -m simlife examples/scenarios/orbital.json --hours 72 --db data/orbital.db
```

核心代码 `engine.py`、`policy.py` 完全不需要更改。第一名 Life 吃饭睡觉，第二名 Life 充电、降温与读取知识终端；不同需求、资源、设施在装配阶段由 JSON 提供。

这证明同一**底层运行机制**能复用，不代表二者应当使用完全相同的生理、心理模型。专用世界规则参见 `EXTENSIONS.md`。

## 九、推荐的第一轮实验

1. 将公寓世界的 `water.amount` 改为 0，另存新 DB；观察角色是否停止凭空喝水。
2. 将 `thirst.rise_per_hour` 增大，观察决策顺序是否有变化。
3. 给世界加一个从工作室返回卧室需要 20 分钟的地图边，观察行动时间是否自然改变。
4. 只运行 12 小时，重新启动后再运行 60 小时，对比一次运行 72 小时的最终状态。
5. 将另一个角色装配入同一世界，共享资源；观察资源如何被实际消费（本版未实现高级竞争与排队机制）。

实验时修改了配置，务必使用新的存档文件路径；否则会触发场景指纹保护。
