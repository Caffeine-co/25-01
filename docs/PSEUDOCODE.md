# WorldLife 2.0 — 全系统伪代码（与实际实现对应）

本文件按照**真实处理路径**写伪代码，不用概念性的“AI 思考”代替实际函数。字段和分支以 `simlife/` 下的 Python 实现为准。

## 0. 组装场景

```text
load_scenario(scenario.json):
    binding = read_json(scenario)
    raw_world = read_json(binding.world)
    validate all locations / directed road costs (>0)
    validate resource initial amount and capacity
    build each Facility (place, duration, effects, resource, tags)
    validate world external events and referenced facilities/actors
    for actor in binding.actors:
        load persona JSON
        validate drives, body rates, interests, personality
        build LifeState with location, drives, knowledge, skills, commitments
        build projects from list of explicit ordered steps
        build long_goals from ambitions and initial skill values
    validate project action kinds and referenced target IDs
    scenario_hash = sha256(canonical JSON(world + scenario + persona + RULESET))
    return Scenario(world, personas, lives, scenario_hash)
```

## 1. 世界初始化或断点恢复

```text
SQLiteStore.load_or_create(scenario):
    checkpoint = SELECT ... WHERE slot = 1
    if absent:
        return WorldRuntime(scenario, store_revision = 0)
    if checkpoint.scenario_hash != scenario.fingerprint:
        REJECT (needs explicit migration, never reinterpret old snapshot)
    world = WorldRuntime.from_snapshot(checkpoint.state_json)
    world.store_revision = checkpoint.revision
    return world

WorldRuntime.__init__(scenario):
    copy initial lives, world inventory, enabled facilities
    minute = 0; next_sequence = 0
    schedule all world external events
    schedule decide event for every actor at minute 0
```

## 2. 单步事件引擎

```text
WorldRuntime.run_until(target_minute):
    assert target_minute >= current_minute
    while event_queue has item with minute <= target_minute:
        event = priority_queue.pop()
        Dynamics.advance(all lives, current_minute, event.minute)
            for every minute gap:
                increase unmet drive values from time anchor
                update vitality according to current activity
                apply penalty for critical unresolved drives
                decay emotion toward neutral; no artificial new event
        current_minute = event.minute
        dispatch(event)
            world events: resource_add / facility_enable / facility_disable
                          vitality_change / message / knowledge_signal
            action_complete: call action handler and settle result
            decide: ignore stale ticket; otherwise choose action
        protect against excessive event count
    Dynamics.advance(current_minute, target_minute)
    current_minute = target_minute
```

同一分钟世界事件优先级 0、行动完成 1、决策 2。同一优先级按 `sequence` 确定顺序。

## 3. 世界事件的分发

```text
_dispatch(resource_add):
    inventory[resource] = min(capacity, old + amount)
    log actual resource delta
    if event repeat period is set: schedule next production
    wake characters near facilities using resource

_dispatch(facility_disable / facility_enable):
    set enabled flag
    log world fact
    wake nearby idle characters

_dispatch(message):
    remember exact incoming text as a message (NOT as verified world fact)
    log message_received
    if actor is idle: wake it
    if urgent and actor busy: interrupt old activity

_dispatch(knowledge_signal):
    learn(actor, key, value, source=world_observation,
          source_id=world event sequence)
    update subjective belief without changing inventory or positions
```

## 4. 人物感知与自主决策

```text
_decide(actor):
    if life.busy: return
    observation = observe(current location's visible facilities + nearby actors)
    remember_observation(life, observation)
    update known_edges for current location only
    mark overdue commitments as missed with audit event
    mark projects past deadline as failed

    decision = DecisionPolicy.choose(life, persona, observation, known_edges)
    if decision.goal is an urgent unmet bodily need:
        use need decision  (preempts ordinary project)
    else:
        project, action = project_intent(life, observation)
        if actionable project:
            decision = action with project ID
        else:
            retain normal social/interest/commitment decision

    if goal changed: log goal_changed
    if decision.action is None:
        schedule next decide after 30 simulated minutes
    else:
        _start_action(actor, kind, target, optional project ID)
```

**具体普通决策 `policy.choose_action`：**

```text
if able to assist nearby low-vitality character: choose assist
for each drive exceeding its threshold:
    urgency = normalized gap * priority
if any urgent drive:
    keep old drive goal unless new urgency is substantially greater
    search known facilities that can reduce it
    evaluate expected relief - time cost, excluding failed facility cooldown
    if facility at another known location:
        find_route on actor's KNOWN edges using Dijkstra
        choose move to next edge, not teleport to destination
    else choose use facility
    if no known facility: explore reachable unvisited location
    if still none: wait
if commitment is due: try to honor it
if nearby available person and social motivation threshold reached: socialize
if awake/active time and interest cooldown passed: practice at known facility
else: wait
```

**项目策略 `project_intent`：**

```text
collect active projects whose start minute has passed and retry cooldown expired
order by priority descending, then start time and ID
for each project:
    step = steps[index]
    if step needs facility:
        check personal facility belief; find route on personal known_edges
        if not there: move one road edge
        if there: return use/practice action
    if step is move:
        find route to target; return next edge
        if already at destination: mark move step complete (no bogus movement)
    if step is social:
        check target currently nearby and available
    if blocked: try next project or ordinary policy
```

## 5. 行动的两阶段执行

```text
_start_action(actor, kind, target):
    reject if actor already busy
    handler = registry.get(kind)
    plan = handler.prepare(world, actor, target)
        verify actor capability, location / road / participant availability
        calculate duration and participating actors
        DO NOT update world resources, skills or location
    reserve actor and all social participants; create action_ticket
    schedule action_complete at current_minute + duration
    record action_started

_finish_action(payload):
    if action ticket stale (interrupted): ignore
    handler.complete(world, actor, target)
        re-check current physical conditions at completion time
        if fail: record reason, cooldown and memory; return False
        if success: settle resource / position / skill / relationship; return True
    if action belongs to project:
        if success and action corresponds to pending project step:
            append evidence(time, action, target, step_index)
            advance project.index
            if project steps exhausted: mark completed, record memory
        else if failure: increment failures and defer next attempt
    release participants; wake actors
```

可注册新动作实现 `prepare` 与 `complete`，但必须保留**准备阶段不产生不可逆世界副作用**的约束。

## 6. 中断与失败处理

```text
interrupt(actor, reason):
    if actor is passive participant: interrupt primary activity instead
    if not busy: return False
    increment action ticket (old action_complete now stale)
    clear busy for actor and participants
    if project: log failed step and plan retry with exponential backoff
    log action_interrupted; remember interruption; wake actor
    return True

_project_failure(actor, project, reason):
    project.failures += 1
    retry_at = current_minute + min(1440, 60 * 2 ^ min(failures,4))
    log project_step_failed
    if failures >= 6: mark project failed and audit
```

项目进度**不会**由动作启动、模型文字、反思文字或未经验证的消息改变。

## 7. 情景记忆、带证据的信念

```text
remember(actor, event):
    append Memory(minute, kind, text, involved_actors, salience, source)
    retain bounded recent memory window (256 default)

learn(actor, key, claim, source, confidence, source_id):
    if source claims direct world observation, require world event source ID
    prevent forged world source ID on external claims
    old = proposition[key] if exists
    if source_id seen previously: return duplicate without amplifying certainty
    if direct observation with high confidence:
        use new observed value, retain old evidence in history
    else if independent evidence agrees:
        aggregate confidence with upper bound
    else if contradicts stronger previous evidence:
        record dispute, retain former value
    else:
        revise subjective belief, preserve evidence chain
    NEVER modify world inventory / objective entities
```

## 8. 模型对话与反思

```text
CognitionService.interact(world, actor, author, message):
    record incoming message as a message event and subjective memory
    if OfflineBackend: return safe fallback reply
    if daily budget exhausted: return fallback reply
    actor_view = local perceptual view + relevant memories + known facts
    send allowed schema and persona biography to LLM backend
    debit daily request budget BEFORE network call (failed calls also count)
    on network timeout/JSON error: fallback; do not change world
    validate {reply, action|null}
    if action present:
        world.submit_intent(...)
          reject unknown facility, unknown road, busy actor, invalid action
          on valid action: start action with normal duration; NOT instant completion
    log proposal, accepted flag, and actual spoken text

reflect(service, world, actor):
    allow <=1 reflection / simulated day, share chat's daily budget
    model sees only actor_view and retrieved personal memories
    validate {reflection, project|null} JSON
    project if proposed -> validate action list / all referenced IDs
    if valid -> world.add_project (still no project progress)
    add Memory(source=llm_inference), not objective truth
    log reflection outcome
```

Remote HTTP calls happen from the service layer, not inside `run_until`'s event queue.

## 9. HTTP/API/service and persistence

```text
HTTP request arrives:
    require Authorization: Bearer <server token>
    GET /v1/state or /v1/events:
        take service lock; return read-only JSON
    POST /v1/<command>:
        enforce body size and JSON object
        require Idempotency-Key
        RuntimeService.mutate(command, payload, request_id):
            digest = SHA256(canonical(command,payload))
            lock world
            if request_id exists and digest matches: return original committed response
            if request_id exists but digest differs: return 409 conflict
            try:
                execute domain operation (advance/chat/reflect/project/...)
                SQLiteStore.save(world, request=(request_id,digest,response))
            except:
                discard possibly modified in-memory world
                load last committed checkpoint from SQLite
                re-raise error
            return response

SQLiteStore.save(world, request):
    BEGIN IMMEDIATE
    read checkpoint revision (0 if new)
    if revision != world's loaded revision: ROLLBACK + RevisionConflict
    write checkpoint with revision+1
    append all pending audit events
    insert request digest and reply (if API mutation)
    COMMIT
    then clear pending events and update in-memory revision
```

This design prevents a client retry from causing the **same command** to run twice. It does **not** claim exactly-once delivery for a separate external platform sending side effects; such integrations must add their own outbox/delivery acknowledgements.

## 10. 实时自动推进

```text
AutoTicker:
    periodically compute monotonic clock elapsed seconds
    cap elapsed after long suspension (max 60 real seconds per tick)
    virtual_minutes += elapsed * configured_rate
    for whole virtual minutes:
        RuntimeService.advance_internal(minutes)
        persist checkpoint immediately
        if configured and simulated day changed:
            for each actor: request daily reflection using stable idempotency ID
    if any unrecoverable exception: stop ticker, log error

stop server -> stop ticker -> close HTTP -> close SQLite
```

停止期间**不补算**：这是明确的部署选择，避免断线数小时后同时产生海量外部行动。需要补算可用显式 `/v1/advance`，由应用决定上限。
