# 从程序启动到第一次行动：逐函数追踪

请先在工程根目录准备一个新的数据库：

```powershell
python -m simlife examples/scenarios/apartment.json --hours 3 --db data/walkthrough.db --tail 30
```

所有时间都是 **模拟开始后的绝对分钟**，不是东京时区的实际钟点。

## 第 1 步：CLI 组装世界

`simlife/__main__.py` 调用 `cli.main()`，读取 `scenario`、`--hours` 和 `--db`。`config.load_scenario()` 依次读取：

1. `examples/scenarios/apartment.json`：一个 `resident_01` 角色，起始在 `bedroom`，预先知道四个设施位置。
2. `examples/worlds/apartment.json`：卧室、走廊、厨房、画室的连接；水库存 18、食物 10；水龙头可减少 `thirst`。
3. `examples/personas/artist.json`：口渴初始 32，每小时 +4.5，行动评分阈值 40。

返回 `Scenario`，此时还没有发生行动。

`store.load_or_create()` 读取 SQLite。没有存档就调用 `WorldRuntime(scenario)`；有存档就恢复上次的世界分钟、角色、资源、事件队列与进行中的动作。

## 第 2 步：生成未来事件

新的 `WorldRuntime` 初始化 `minute=0`，克隆角色状态，并安排：

```text
t=0      decide(resident_01)
t=1440   resource_add(water, +4)
t=2880   resource_add(food, +4)
```

`_schedule()` 只把任务放入优先队列，不会立即执行。

## 第 3 步：WorldRuntime.run_until(180)

核心循环只做三件事情：

```python
item = heapq.heappop(self.queue)  # 取下一个待处理事件
self.dynamics.advance(...)        # 先推进到该时刻的自然变化
self._dispatch(item)              # 然后执行到期事件
```

第 0 分钟的事件是 `decide`，会调用 `_decide()`。

`_decide()` 先向 `perception.observe()` 请求**当前地点可以看到什么**。因为角色位于卧室，所以只能实际观察卧室的 `bed`；它虽然记得水龙头的位置，但**不知道世界此刻的实时水库存**。

`remember_observation()` 更新设施知识。`policy.choose()` 随后查看需求是否值得采取行动。此时口渴 32，小于阈值 40，其他需求也未达到行动条件，于是返回不行动。

World 安排第 30 分钟重新决策。

## 第 4 步：时间使需求产生变化

`Dynamics.advance()` 按模型规定推进：

```text
t=0    thirst=32
t=30   thirst=34.25
t=60   thirst=36.5
t=90   thirst=38.75
t=120  thirst=41
```

因此到了 **t=120**，口渴已经成为可执行目标。

`policy.choose()` 返回“为解决 `thirst`，去使用已知的 `tap`”。它并没有直接改变库存或口渴值，而只是返回一个 `ActionIntent(kind='move',target='hall')`。

## 第 5 步：先移动，再使用

```text
t=120  目标 = thirst；开始从 bedroom 移动到 hall
t=122  move_finished → World 实际把位置改为 hall
t=122  再决策；继续朝 kitchen 移动
t=125  move_finished → 实际到达 kitchen
t=125  再决策；开始使用 tap（需要 4 分钟）
t=129  use_finished → 结算资源与效果
```

注意 `busy`：行动开始时只记录“正在执行什么、哪一分钟完成”。位置变化要等 `move_finished`，饮水效果要等 `use_finished`。

结算在 `StandardFacilityResolver.resolve()` 中：

- 如果不在厨房，返回 `wrong_location`；
- 如果水库存不足，返回 `resource_unavailable`，**不减少口渴**；
- 如果检查通过，水库存 `18 -> 17`；
- t=129 口渴自然增长到 41.675，饮水效果最多 -60，所以实际口渴 `41.675 -> 0`；
- 对应需求的 `anchors` 记录 t=129 和新值 0。后面的自然增长从此刻重新计算。

行动完成后再执行 `decide`。角色不再口渴，当前目标 `thirst` 被清除，继续等待下次需求出现。

## 第 6 步：资源失败与更换方案（v0.2 / v0.3）

运行：

```powershell
python -m simlife examples/scenarios/resilience.json --hours 1 --db data/resilience_walk.db --tail 40
```

真实执行序列：

```text
t=0   traveler 决定满足 thirst
t=2   到 hall
t=4   到 kitchen，开始尝试 tap
t=6   tap 使用失败：resource_unavailable
      Life 记下 last_result 和失败冷却时间
      但 thirst 目标没有消失
t=8   到 hall
t=12  到 storage，使用另一种已知设施 bottle
t=14  bottle 成功，降低 thirst，清除目标
```

**决策器知道自己以前失败过，但它不能改写 World 的真实库存。** 如果所有设施都没有资源，就继续保持未满足的目标，等待世界变化或延迟重试，而不是凭空生成水。

另一个 `discovery.json` 场景最初不知道任何设施。它会沿着已知地点图探索，到达新房间才能把当地设施加入 `beliefs`。

## 第 7 步：身体能力与 NPC 支援（v0.4 / v0.5）

运行：

```powershell
python -m simlife examples/scenarios/care.json --hours 1 --db data/care_walk.db --tail 30
```

`patient` 的初始 `vitality=7`，低于一般移动的最低值 12；它不能像正常角色一样行走。`caretaker` 从同一间卧室开始，观察到另一角色需要协助，会执行 `assist` 行动：

```text
t=0   caretaker 开始 assist(patient)
t=15  assist_finished：World 结算一次 +22 vitality
t=15  如果仍低于协助判断阈值，再安排一次 assist
t=30  第二次协助完成；patient 之后恢复基础行动能力
```

这只是**示例性支援规则**，不是真正的医疗行为。它被明确定义在 Persona 里，且必须满足同处一地、行动时间和能力门槛，不能被叙述凭空触发。

## 第 8 步：保存与重启

CLI 最后执行 `store.save(runtime)`，一次 SQLite 事务保存两类数据：

- `checkpoint`：当前时间、生命状态、认知、目标、动作、库存、待处理事件；
- `events`：此前已完成的行为与世界事件，方便审计。

**队列与 busy 都必须保存**，否则在喝水或睡觉中途重启就会丢失原定完成事件。

`run_until()` 本身只在内存中工作，CLI 在一次命令结束时保存。连续线上服务还需要增加周期性存档和外部副作用可靠投递机制。
