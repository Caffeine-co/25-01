# 跨 IP 扩展与接入现有 NoneBot 的边界

## 一、扩展首先改配置，而不是改内核

为新的 IP 提供至少三件文件：

1. `examples/worlds/my_world.json`：地点、路径、设施、物资、外部事件。
2. `examples/personas/my_persona.json`：生命的需求缺口和相对权重。
3. `examples/scenarios/my_story.json`：把一个或多个生命装配到那个世界。

内核**不要求**世界一定是东京、人类社会或昼夜 24 小时；当前只有单调递增的“世界分钟”概念。日历、时区与作息属于后续独立适配层。

不同 IP 的差异首先应该是世界定义、能力和生命需求不同，而不只是名称不同。装配成功不代表具有合理的生命表现；必须设计该世界的规则和测试。

## 二、自定义生理演化规则

默认 `LinearDriveDynamics` 只会让需求按照配置速率增长。如果需要“魔力恢复”“机器人休眠能耗”等特殊机制，可实现同一 `Dynamics` 接口。

以下示例只展示注入方法，不代表任何特定 IP 的真实机制：

```python
from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.systems import LinearDriveDynamics

class MyDynamics(LinearDriveDynamics):
    def advance(self, lives, personas, delta_minutes, target_minute):
        # 首先运行默认需求模型；真实系统可完全替换。
        super().advance(lives, personas, delta_minutes, target_minute)
        # 然后执行本 IP 的额外规律。
        # 注意：所有自定义的可变状态都必须纳入检查点存储。

scenario = load_scenario("examples/scenarios/orbital.json")
runtime = WorldRuntime(scenario, dynamics=MyDynamics())
runtime.run_until(180)
```

`DecisionPolicy` 和 `FacilityResolver` 也可以被替换：

```python
from simlife.systems import UtilityDecisionPolicy, StandardFacilityResolver

runtime = WorldRuntime(
    scenario,
    decision_policy=UtilityDecisionPolicy(),
    facility_resolver=StandardFacilityResolver(),
)
```

**存档恢复时必须注入相同的扩展系统**：

```python
with SQLiteStore("data/custom.db") as store:
    runtime = store.load_or_create(scenario, dynamics=MyDynamics())
    runtime.run_until(runtime.minute + 60)
    store.save(runtime)
```

当前的场景指纹只包含 JSON 配置，不包含 Python 自定义规则版本。未来引入自定义系统后，应另行保存 `simulation_rules_version`，避免用旧存档运行不兼容的新机制。

当前 `Dynamics` 接口只能直接访问 Life 及 Persona。如果一种 IP 的规则需要读取动态环境、月相、魔力场、温度等，下一步应该添加新的 WorldState 和受控的系统上下文，而不是读取自然语言情境摘要。

## 三、人设差异应放在哪一层

当前 MVP 通过 `Persona.drives` 和 `move_multiplier` 区分角色。正式版建议按以下层次增加：

- **种族/身体类型**：代谢规则、传感范围、可行动作、限制条件。
- **个体能力**：熟练度、移动能力、感官特点、已有知识。
- **价值与偏好**：效用评分权重、风险偏好、活动偏好。
- **习惯与日程**：周期性倾向，不等于无法打断的硬脚本。
- **长期记忆与信念**：知道什么、认为发生了什么，与 World 客观事实分开。
- **社会关系**：角色间的历史、信任和相互作用。

不要把“具体某 IP 主角的人生经历”写在 `engine.py` 或 `policy.py` 里。特定 IP 的独有逻辑通过扩展规则、事件和资料加载。

## 四、与 25:01 / NoneBot 集成时的正确边界

**不要**让核心模拟包 import NoneBot、OneBot、OpenAI SDK 或某个特定角色的 preset。

建议独立在适配层实现：

```text
NoneBot 生命周期 / APScheduler
                ↓
   WorldService.advance_to(now)
                ↓
     WorldRuntime.run_until(...)
                ↓
    SQLiteStore.save(...)
                ↓
  读取 Life/World 的派生投影
                ↓
       构造聊天 Prompt
                ↓
         LLM 生成文本
                ↓
    OneBot 发送（真实副作用）
                ↓
    真实消息结果 / 错误回流
```

这里 `WorldService`、真实时间转换和外部 I/O outbox 都是**未来适配层的设计目标**，本仓库没有实现，不能直接复制此流程假装已接入。

LLM 输出的文字或提议应视为候选意图或主观认知，不应直接覆盖 World 的位置、库存、行动完成结果及核心生命机制。

## 五、推荐的下一阶段

按影响优先级：

1. `Observation / Belief`：Life 只能观察自身附近与已知的信息，不再拥有 World 全知视角。当前路径规划使用 `known_locations`，只是最小限度的已知范围限制。
2. `Action Capability`：加入身体限制、权限、道具、物品占用、行动前置条件。当前仅验证地点和库存。
3. `More Dynamics`：睡眠状态持续影响、生理负债、环境效应、精神和情绪的不同时间尺度。
4. `Scheduler`：世界时钟与现实 UTC 时间映射、周期执行、停机补算限制。
5. `NPC & Relations`：独立人物的地点、日程、物品交互；当前多 Actor 只能各自使用设施。
6. `Narrative / LLM adapter`：将当前事实投影到语言，不再把自然语言摘要当作事实来源。

这套 Starter 的目标是稳定而可扩展的**最小因果核心**，不是一次性包含未来所有世界观模拟能力。
