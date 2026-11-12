# 跨 IP 扩展与后续接入建议

## 1. 优先通过 JSON 换世界与生命

配置分三层：

- `worlds/*.json`：地点、地点连边（耗时分钟）、设施、资源和外部事件；
- `personas/*.json`：需求增长规则、行动能力模型、可选协助能力；
- `scenarios/*.json`：把具体 actor 放入某世界、指定出生位置、已知地点、已知设施。

**不要把“人类必须吃饭”之类的规则写进 WorldRuntime。** 比如轨道设施示例使用 `power_deficit` 和 `thermal_load`，无需新增人类逻辑的条件判断。

## 2. 替换规则接口

```python
from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.model import Decision

class MyDecisionPolicy:
    def choose(self, life, persona, observation, known_map) -> Decision:
        # 这里只接收 Observation 和个人 Belief，拿不到世界真实库存。
        # 可以调用默认 policy.choose_action，也可自定义目标选择。
        from simlife.policy import choose_action
        return choose_action(life, persona, observation, known_map)

scenario = load_scenario("examples/scenarios/apartment.json")
world = WorldRuntime(scenario, decision_policy=MyDecisionPolicy())
world.run_until(120)
```

同样支持通过 `dynamics=` 替换 `HomeostasisDynamics`，通过 `facility_resolver=` 替换 `StandardFacilityResolver`。接口位于 `simlife/systems.py`。

如需模拟魔法、机械能、变形种族或非人类身体，首先考虑新建 `Dynamics` 实现或 Body 规则；不要让自定义规则绕过 World 去直接改写外部库存或事件事实。

## 3. 与旧 25:01 系统共存

建议初期依旧保留为独立实验分支，不直接替换 `living` 插件的状态更新函数。后续可将 `WorldRuntime` 作为状态权威来源，让 LLM 只看到 `actor_view()` 产生的角色状态视图。LLM 可以提出语言行动或行动意图，但**不能直接写数据库中的 World 状态**。

外部 QQ 消息必须保留来自真实平台的原始事件；真实用户说“我给你送了水”并不代表 World 的客观库存已经增加。需要明确的世界事件转换、授权与确认层。

要真正发送 QQ 消息，请另做 Outbox、重试去重与补偿；SQLite 与远端 QQ 服务无法进行一体化事务。

## 4. 长期路线

1. **下一阶段**：引入 `ActionDefinition`、执行中的行为中断和目标完成条件，进一步从“选择设施”发展到“多步骤实现目标”。
2. 再加入行为能力与可用资源的细粒度前置条件，避免所有设施效果都是一次性数值调整。
3. 增加可更新地图知识、物品所有权与有限可感知事件；对重要事实记录来源。
4. 增加 NPC 的日程、不同目标、社交关系与协作，而不是全员使用 `assist`。
5. 在有独立因果事件来源之后，再加入复杂心理状态与 LLM 语言表达。
