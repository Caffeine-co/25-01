# 扩展指南（v2.0）

1. **新世界**：参考 `examples/worlds/apartment_sustainable.json` 增加地点、道路、设施、库存和世界事件。`config.load_scenario()` 负责输入引用检查；核心模拟引擎只处理合法对象。
2. **新人设**：参考 `examples/personas/artist.json` 定义 `drives`、`body`、`traits`、`interests`、`ambitions`。不同类型生命可定义不同需求，不必默认一定是人类。
3. **新项目**：参考 `examples/projects/sketch.json` 和 `examples/scenarios/art_project.json`，通过 `projects` 提供有序步骤，或经 `/v1/project` 增加。项目只使用明确注册的动作，不能让 LLM 直接写库存。
4. **新动作**：实现 `ActionHandler.prepare(world,actor,target)` 和 `complete(world,actor,target)`；`prepare` 仅做条件验证及持续时间，`complete` 二次验证并结算实际后果，返回 `True/False`。用 `ActionRegistry.register()` 注册后再传给 `WorldRuntime(..., actions=registry)`。业务日志和个人记忆应分别写入 `world.log` 与 `world.remember`。
5. **新决策**：替换 `decision_policy`，只读取 `LifeState`、`Persona`、局部 `Observation` 和个人 `known_edges`，返回 `Decision(goal,ActionIntent)`。禁止直接更改其他实体的状态。
6. **新认知**：替换 `CognitionService` 的 `Backend`，实现 `generate(messages)->str`。输出必须通过 `validate_response` 或 `validate_reflection`，动作经 `WorldRuntime.submit_intent()` 校验。
7. **新适配器**：从 HTTP JSON 服务收发，使用稳定幂等 ID，保持平台敏感凭据在适配器中；不要把任何用户未经验证的陈述转换成世界事件。
8. **测试**：每次增加行动或世界机制都至少添加：合法完成、非法目标、库存不足、行动中断、一次性 vs 分段推进、存档恢复以及长时模拟测试。

如果开发者修改了 `HomeostasisDynamics`、`FacilityResolver`、默认计划器或动作语义，必须更新 `config.RULESET` 并重新生成配置指纹。不能让旧存档被新规则无提示解释。
