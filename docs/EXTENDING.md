# 如何扩展这个工程（按最小改动原则）

以下是推荐的扩展顺序，避免为了加一个行为而修改所有核心文件。

## 1. 新增人物

复制 `examples/personas/artist.json`，调整以下字段：

- `drives`：需求缺口初始值、小时增长率、触发阈值、优先权重。
- `body`：抽象行动能力与活动消耗。
- `traits`：0~1 之间的人格倾向；目前主要使用 `extraversion` 与 `agreeableness`。
- `interests`：兴趣名称及权重，如 `drawing: 0.9`。
- `ambitions`：以技能名为键的长期目标阈值，如 `drawing: 50`。
- `name/biography`：供可选 LLM 语言表达使用，不直接代替状态机。

在 `examples/scenarios/*.json` 中增加 actor 条目即可让人物被同一世界引擎调度。**不要在 WorldRuntime 中硬编码某个角色姓名、作品 IP 或世界观。**

## 2. 新增世界、地点和设施

`worlds/*.json` 的 `locations` 是邻接表，每条边记录模拟移动分钟数。设施具有 `id/location/duration_minutes/effects`，可选 `resource/units/restorative/tags`。

用于练习的设施应该具有标签：

```json
{
  "id": "practice_drawing",
  "location": "studio",
  "duration_minutes": 90,
  "effects": {"fatigue": 5},
  "tags": ["practice", "skill:drawing"]
}
```

角色已知该设施时，`policy.choose_action()` 可以根据 `interests.drawing` 主动安排练习。设施的实际后果仍由行动执行层结算。

添加资源时，必须配置合法的初始库存和容量；添加世界事件应通过 `config.py` 的验证，不要让用户聊天直接写库存。

## 3. 新增行动，不改 `run_until()`

在独立模块中实现一个 `ActionHandler`：

```python
from simlife.actions import ActionPlan, ActionRejected, ActionRegistry

class ReadBook:
    def prepare(self, world, actor: str, target: str) -> int:
        if world.lives[actor].location != "library":
            raise ActionRejected("wrong_location")
        return 30  # 行动预期消耗 30 分钟，prepare 不修改世界

    def complete(self, world, actor: str, target: str) -> None:
        # 先检查真实世界条件，再结算状态；不要让 LLM 代替这一步。
        world.remember(actor, "read", f"阅读了 {target}", 0.5)
        world.log("read_completed", actor, book=target)

registry = ActionRegistry()
registry.register("read", ReadBook())
```

创建世界时注入 `WorldRuntime(scenario, actions=registry)`。对应的决策器要返回 `ActionIntent('read', 'book_id')`。若是多人行动，`prepare()` 可返回 `ActionPlan(duration=20, participants=('other_actor',))`，引擎统一占用参与者。

**注意**：扩展处理器是受信任的 Python 代码；本系统不会在运行时沙箱化任意第三方处理器。因此，处理器必须遵循 `prepare` 无副作用、`complete` 才结算后果的约定。

## 4. 自定义人物决策

实现与 `simlife.systems.DecisionPolicy` 相同的协议：

```python
from simlife.policy import StandardDecisionPolicy

class MyPolicy(StandardDecisionPolicy):
    def choose(self, life, persona, observation, known_map):
        decision = super().choose(life, persona, observation, known_map)
        # 可分析或改选某个合法 ActionIntent，但绝不修改世界库存。
        return decision
```

运行时 `WorldRuntime(scenario, decision_policy=MyPolicy())`。**传入 `known_map` 是个人已知连边，不是完整世界地图。**

如果需要高级规划，建议新增 `Goal` 和 `Plan` 的显式对象，保留初始动作的前置条件和执行检查；不要直接让 LLM 返回一个任意的 `LifeState` 补丁。

## 5. 接入真实 LLM

`cognition.OpenAICompatibleBackend` 用标准库 `urllib.request` 调用兼容 `/chat/completions` 的接口，要求模型输出 JSON：

```json
{
  "reply": "我想先去看看情况。",
  "action": {"kind": "move", "target": "hall"}
}
```

也可以返回 `"action": null`。模型只能建议 `move/use/practice/assist/socialize` 中的一项；非法字段、无效 JSON 或世界不可执行的动作会被回退或拒绝。

对于真实聊天平台，建议单独做 `adapter`：消息入口 → 验权 → `CognitionService.interact()` → 记录审计事件 → 可靠出站队列；网络调用不要阻塞模拟主循环，也不要把外部消息“我送来了东西”自动解释成已完成的世界交易。

## 6. 修改状态或规则后的版本控制

`simlife/config.py` 中 `RULESET` 是规则版本。改动连续动态、行动收益、状态含义或存档结构时，更新版本并为新实验创建数据库；旧存档不会自动迁移。小型工程更应该保证测试可复现，不应静默把旧规则的数值装进新规则的运行现场。

可以按下列顺序工作：修改一个模块 → 增加测试 → 跑 72 小时基准 → 跑 30 天基准 → 检查 `results/summary.json` 与 SQLite 事件 → 跑带扰动的分段一致性测试。异常必须找出对应行动/状态更新来源，而不是直接修改最终快照掩盖结果。
