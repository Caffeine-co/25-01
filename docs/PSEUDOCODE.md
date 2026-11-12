# 完整伪代码逻辑（WorldLife Next v1.0）

本文按真实调用路线提供关键程序的**逐层伪代码**。与源码 1:1 的函数名保持一致，以便从逻辑追踪到实际实现。这里的伪代码省略类型与异常提示，但不省略主要状态修改位置。

## 0. 入口、装配与恢复

```text
CLI.main(scenario_file, hours, db):
    scenario = config.load_scenario(scenario_file)
    with SQLiteStore(db) as store:
        world = store.load_or_create(scenario)
        start = world.minute
        world.run_until(start + 60 * hours)
        store.save(world)
        输出角色状态、资源和已发生事件

config.load_scenario(path):
    读取 scenario.json
    读取其中引用的 worlds/*.json
    校验所有地点、边、设施、资源和世界事件
    对 scenario 中的每个 actor:
        读取其 persona.json
        校验需求、身体约束、人格、兴趣和长期目标
        生成带初始需求锚点的 LifeState
        初始设施知识从 known_facilities 转成 FacilityBelief
        长期目标按 ambitions 初始化
    根据规则版本和原始配置生成 SHA256 fingerprint
    返回 Scenario(world, personas, lives, fingerprint)

SQLiteStore.load_or_create(scenario):
    若没有 checkpoint:
        return WorldRuntime(scenario)
    若存档 fingerprint != 当前 scenario fingerprint:
        拒绝加载，防止旧规则误解新状态
    否则:
        恢复世界时间、人物、资源、队列、预算
        return WorldRuntime.from_snapshot(...)
```

## 1. 世界启动（engine.WorldRuntime.__init__）

```text
WorldRuntime.__init__(scenario):
    分别持有可替换的 Dynamics、DecisionPolicy、FacilityResolver、ActionRegistry
    time = 0
    lives = 深拷贝 scenario.initial_lives
    resources = 世界的初始资源数
    enabled = 每个设施初始启用
    queue = 空优先队列
    pending_log = 空列表
    cognition_usage = 空字典

    对 world.external_events:
        schedule(事件时间, 类型, 参数)
    对每个角色:
        wake(角色)  # 安排第 0 分钟的 decide
```

## 2. 时间与事件引擎（run_until）

```text
run_until(target_minute):
    if target_minute < 当前时间:
        报错：时间不可倒流

    while 事件队列最早事件.time <= target_minute:
        e = queue.pop()             # 按时间/优先级/序号取最早事件
        Dynamics.advance(当前时间, e.time)
        当前时间 = e.time
        _dispatch(e)
        检查事件计数上限，避免无限循环

    Dynamics.advance(当前时间, target_minute)
    当前时间 = target_minute

schedule(time, kind, payload):
    validate(time >= now, kind in 已知事件类型)
    if kind == decide:
        对应角色.decision_ticket += 1
        payload.ticket = 新的 ticket
    依据事件类型设置优先级：
        世界事件 = 0
        行动完成 = 1
        角色决策 = 2
    作为 QueuedEvent 放入优先队列
```

**注意**：没有任何“每分钟调用 LLM”的步骤。分钟推进只运行确定性代码。

## 3. 连续状态演化（systems.HomeostasisDynamics.advance）

```text
for 每个经过的模拟分钟 t:
    for 每个角色 life:
        for 每项需求 drive:
            anchor = 上次主动修改此需求的时刻与数值
            drive.value = clamp(anchor.value + (t-anchor.time)*rise_per_hour/60)

        if 正在移动: vitality_rate = -move_cost
        else if 正在进行一般行动: vitality_rate = -use_cost
        else if 正在休息设施内: vitality_rate = +rest_recovery
        else: vitality_rate = +idle_recovery

        if 需求超过严重风险阈值:
            vitality_rate -= 风险损耗
        vitality = clamp(vitality + vitality_rate/60)

        emotion.valence *= 0.9992
        emotion.arousal *= 0.9988
```

### 为什么需要 `anchors`？

如果饮水在第 249 分钟将口渴改为 0，后面的自然增长必须从第 249 分钟开始计算，而不是从世界第 0 分钟重新增长。每次外部行动改变需求时调用 `set_drive` 同步时间锚点，因此模拟暂停、续跑或分段推进不改变结果。

## 4. 人物感知与决策（engine._decide + policy.choose_action）

```text
_decide(actor):
    if life.busy is not None: return
    observation = perceive.observe(世界, 人物当前位置, 当前有效设施, 附近 NPC)
    remember_observation(life, observation)
    life.known_edges[当前位置] = 当前地点真正观察到的连边
    对超过宽限期而未完成的承诺:
        标记 missed，写入记忆与审计日志
    decision = DecisionPolicy.choose(life, persona, observation, life.known_edges)
    if decision.goal != life.goal:
        记录 goal_changed，更新持续目标
    if decision.action is None:
        wake(actor, now + 30)
    else:
        _start_action(actor, decision.action.kind, decision.action.target)

choose_action(life, persona, observation, known_map):
    if 身边有人需要协助 AND 我有协助能力:
        return assist

    candidates = 超过阈值的需求 × 权重
    if 存在 candidates:
        保留旧需求目标，除非其他需求明显更紧急
        对认知中已知的每个设施:
            如果能缓解当前需求，且未在失败冷却期:
                在自己的 known_map 中求最短路
                用需求收益 - 时间成本评分
        if 可用设施存在:
            if 不在设施所在地: return move(下一节点)
            else: return use(设施)
        if 有未访问的已知地点:
            return move(去探索)
        return goal + None（保持目标等待）

    for 到期承诺:
        if 可以兑现: return 行动（含逐段移动）
    if 白天 AND 身边有空闲对象 AND 性格与社交间隔满足:
        return socialize(对象)
    if 白天 AND 有兴趣 AND 体力允许 AND 活动间隔已过:
        找到对应 practice 设施
        return move(设施) 或 practice(设施)
    return Decision(None, None)
```

## 5. 行动注册与执行（actions + engine）

```text
_start_action(actor, kind, target):
    if actor.busy: 拒绝
    handler = ActionRegistry.get(kind)
    try:
        plan = handler.prepare(world, actor, target)
        验证持续时间与参与者可用性
    except ActionRejected:
        如果与上次阻断原因不同：记录 action_blocked
        安排延迟重试
        return

    actor.action_ticket += 1
    actor.busy = {kind, target, finish, ticket, participants}
    对多人计划中每个参与者：
        partner.busy = {kind:"participate", target:actor, finish, ticket}
    schedule(finish, "action_complete", {actor, kind, target, ticket})
    log(action_started)

_finish_action(payload):
    if payload.ticket != actor.busy.ticket:
        return  # 旧事件，已经中断，禁止重复结算
    handler = ActionRegistry.get(payload.kind)
    handler.complete(world, actor, payload.target)
    清除执行者与参与者 busy
    为执行者与参与者安排下一次 decide

interrupt(actor, reason):
    if actor.busy is None: return False
    如果 actor 是多人行动被占用的一方:
        把中断转发给主动执行者
    让执行者与参与者的 busy 变为 None
    action_ticket += 1，使旧完成事件失效
    记录中断原因和经历
    安排新的 decide
```

### 5.1 常见行动后果

```text
Move.complete:
    再次核查身体能力和道路可用性
    若成功，修改位置；否则只写行动失败事件

UseFacility.complete:
    再次核查身体、设施是否启用、所处地点与真实资源库存
    若失败：不减需求、不加技能，记录原因与退避时间
    若成功：先从库存扣资源，再修改需求及锚点
    如果是 practice:
        skills[技能] = min(100, skills[技能]+递减的练习增益)
        progress_skill_goal()  # 只从已结算技能推进长期目标
        写人物练习记忆，施加一次积极情绪冲击

Socialize.complete:
    必须在同处一地，双方在行动过程中被统一占用
    根据固定 hash 抽样产生有限的积极/不愉快结果
    双方形成经历、社会关系、情绪改变
    信任变更乘以剩余变化空间，防止快速达到 0/1

Assist.complete:
    同地点且能力满足时，改善对方抽象 vitality
    双方形成帮助经历；不代表真实医学救助
```

## 6. 记忆与信念（perception + memory）

```text
remember_observation(life, observation):
    更新已访问地点
    对当前能看见的设施：
        建立或更新 FacilityBelief（功用、耗时、时间、最近反馈）
    不写远处库存、不自动传播其他 NPC 的内部状态

remember(actor, kind, text, salience):
    追加 Memory(当前模拟时间, kind, text, salience)
    个人近期记忆最多保留 256 条
    重要原始事件仍写在 SQLite 的 events 审计日志

memory.retrieve(life, query, now):
    将 query 和记忆转换为英文单词与中日韩字符片段
    评分 = 词项重合度 + 显著度权重 + 时间新近度
    返回最高分的前 k 条，给认知服务使用
```

这是一条透明、低成本的检索基线，不能替代跨语言语义向量检索或完整自传记忆系统。

## 7. 可选 LLM 交互（cognition.CognitionService）

```text
CognitionService.interact(world, actor, author, message):
    world.receive_message()  # 先把外部话语记录为观察
    if backend == OfflineBackend:
        用固定的离线回复，不消耗模型预算
        return Reply

    if 当日该角色模型调用次数达到上限:
        记录 daily_budget 回退；不调用模型
        return 离线 Reply

    view = actor_view(world, actor)  # 只读角色知道的内容
    view.relevant_memories = 检索与消息相关的个人经历
    view.known_facts = 角色个人已知事实
    按人物设定构造系统任务和输入视图
    在调用前消耗一次预算（防止故障重试风暴）

    try:
        raw = backend.generate(messages)
        (reply, action) = validate_response(raw JSON)
    except 网络错误、超时、非法 JSON、非法字段:
        记录 fallback，返回离线回复

    if action != null:
        accepted, reason = world.submit_intent(actor, kind, target)
        # 提议必须经过真实 World Action.prepare 检查。
    记录 LLM 建议、是否接受、最终回复
    return Reply(reply, accepted, reason, model_used=True)
```

当模型说“我马上去画室”，但人物实际上不在画室附近，`submit_intent()` 会拒绝非法跳跃。模型不会取得任意 `set_drive`、写库存、写目标达成状态的能力。

## 8. 存档与验证（store + scripts）

```text
SQLiteStore.save(world):
    JSON 序列化完整 world.snapshot()
    BEGIN TRANSACTION
        UPSERT checkpoint(slot=1, fingerprint, state_json)
        INSERT pending_log 中每个已发生事件到 events
    COMMIT
    清空内存 pending_log（避免重复写事件）

scripts/benchmark.py:
    for 场景 in [可持续、短缺、中断、消息、双人物]:
        建新 DB
        for hour in 0..总小时数:
            world.run_until(hour*60)
            采样角色状态到 hourly.csv
        store.save(world)
        统计事件计数、技能、最低行动能力、关系、承诺
    写 results/summary.json

scripts/stress.py:
    for seed in 0..29:
        使用固定种子生成 9 个世界扰动事件
        对同一场景创建 A、B 两个实例
        A：一次推进到第七天
        B：通过随机切分的时刻逐步推进到第七天
        assert A.snapshot == B.snapshot
        assert A.pending_log == B.pending_log
        assert 全部资源和角色状态在合法范围
    汇总所有结果到 stress_summary.json
```

## 9. 一句话总结完整闭环

**世界时间推进 → 人物有限感知 → 根据需求/目标/人格生成意图 → 行动处理器验证并排队 → 世界到期结算真实后果 → 事件产生新的记忆、关系和能力变化 → 下一轮决策。**
