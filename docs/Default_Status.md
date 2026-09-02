# Default Status 配置指南

`default_status` 是 25:01 的**角色状态冷启动模板**

配置位置：

```text
configs.json
└─ setting_config
   └─ default_status
```

对应 Schema：

```text
src/plugins/living/validate.py
└─ CharacterStatus
```

它只在状态文件不存在时用于创建初始状态

运行后状态会保存到：

```text
chat_config.status_path
```

默认通常为：

```text
status.json
```

因此应将 `default_status` 理解为：

> **第一次启动角色时，她在现实时间轴上的初始状态快照。**

而不是永久不变的人物设定

---

## 1. 加载逻辑

当前逻辑：

```text
status.json 存在
    ↓
读取 status.json
    ↓
CharacterStatus 校验

status.json 不存在
    ↓
读取 default_status
    ↓
CharacterStatus 校验
```

因此修改：

```text
configs.json > default_status
```

不会覆盖已有 `status.json`

如需重新冷启动，应先备份并删除旧状态文件

---

## 2. Schema 基本要求

`CharacterStatus` 使用：

```python
ConfigDict(
    extra="forbid",
    validate_assignment=True
)
```

因此：

```text
未知字段 → 拒绝
缺失字段 → 拒绝
类型不正确 → 拒绝
范围错误 → 拒绝
```

除 `body_temperature_c` 外，大部分数值字段使用：

```text
整数，0 ~ 100
```

体温要求：

```text
34.0 ~ 43.0 ℃
```

---

## 3. 如何理解 0 ~ 100

这些数值不是医学量表，也不是心理测试结果

建议统一理解：

```text
0   = 此维度极低
25  = 较低
50  = 中等
75  = 较高
100 = 极高
```

不同字段方向不同

例如：

```text
energy_level = 80
```

通常表示精力较好；

但：

```text
fatigue_level = 80
```

表示明显疲劳

不要把所有“好状态”字段都简单设高

---

## 4. 推荐字段分组

当前状态可按语义分为：

```text
A. 时间、位置与现实情境
B. 环境
C. 即时身体状态
D. 睡眠与生理恢复
E. 即时情绪
F. 认知状态
G. 自我认知与动机
H. 人格与行为倾向
I. 压力与恢复
J. 社会关系
K. 时间与责任负荷
```

这只是配置文档中的分组，代码本身仍是一个扁平 `CharacterStatus`

---

## 5. 时间、位置与现实情境

字段：

```text
current_time
current_location
current_activity
current_situation
```

### `current_time`

当前时间，使用 ISO8601：

```json
"current_time": "2026-08-25T20:00:00+09:00"
```

推荐显式携带时区

该字段在 `default_status` 中只表示**冷启动初始时间**

后续状态更新会根据输入的新时间继续推进

### `current_location`

角色当前所在具体地点

推荐：

```text
神山高校
家中自己的房间
车站附近
咖啡店
```

避免：

```text
外面
某处
附近
```

地点必须与：

```text
current_time
current_activity
角色固定日程
```

一致

### `current_activity`

角色当前正在进行的活动

推荐写成：

```text
在晚间课程间隙整理课业，并偶尔查看手机
```

而不是简单的：

```text
学习
```

应提供足够信息让模型推演：

- 精力
- 注意力
- 社交条件
- 时间压力

### `current_situation`

描述角色所处的事件与外部上下文

区分：

```text
current_activity
= 她正在做什么

current_situation
= 她现在处于什么情境
```

例如：

```json
"current_activity": "在晚间课程间隙完成课业",
"current_situation": "课程已进入后半段，校内人数逐渐减少，今天还有尚未完成的绘画任务"
```

---

## 6. 环境状态

```text
environmental_comfort
privacy_level
noise_level
crowd_density
```

### `environmental_comfort`

环境整体舒适程度

考虑：

- 温度
- 光线
- 空间
- 座位
- 熟悉感

### `privacy_level`

当前环境能避免他人注意、打扰或观察的程度

例如：

```text
自己的房间 → 高
拥挤教室 → 低
安静咖啡店角落 → 中等
```

### `noise_level`

环境噪声强度

```text
0   几乎安静
100 极度嘈杂
```

### `crowd_density`

周围人群密集程度

不要把它与 `noise_level` 机械绑定

例如：

```text
图书馆
crowd_density 高
noise_level 低
```

完全合理

---

## 7. 即时身体状态

```text
energy_level
physical_stamina
fatigue_level
sleepiness_level
hunger_level
thirst_level
appetite_level
pain_level
physical_strain
```

### `energy_level`

当前主观可用精力

### `physical_stamina`

当前身体耐力与持续活动能力

它通常比 `energy_level` 变化更慢

### `fatigue_level`

身体累计疲劳

不要强制：

```text
energy_level + fatigue_level = 100
```

角色可能已经很累，但因为兴奋仍保持较高精力

### `sleepiness_level`

即时困意

与疲劳、睡眠债相关，但不是同一个量

### `hunger_level`

饥饿程度

### `thirst_level`

口渴程度

### `appetite_level`

进食欲望

不要简单设置：

```text
appetite_level = hunger_level
```

例如压力大时可以：

```text
hunger_level = 70
appetite_level = 35
```

### `pain_level`

疼痛程度

普通日常冷启动一般应该较低

### `physical_strain`

当前活动给身体造成的即时负荷

例如：

```text
坐着画画 → 低~中
长时间站立 → 中
剧烈运动 → 高
```

---

## 8. 睡眠与生理恢复

```text
sleep_quality
sleep_debt
circadian_stability
body_temperature_c
recovery_capacity
nutrition_status
hydration_level
physiological_arousal
sensory_overload
```

### `sleep_quality`

最近一次主要睡眠质量

通常不应在短时间内剧烈改变

### `sleep_debt`

近期累计睡眠不足程度

例如：

```text
昨晚睡得不错
但前几天持续欠睡
```

可以：

```text
sleep_quality 高
sleep_debt 仍中高
```

### `circadian_stability`

昼夜节律稳定程度

高：

```text
作息规律
```

低：

```text
频繁熬夜
起床时间漂移
```

### `body_temperature_c`

当前体温

普通日常一般建议：

```text
36.5 ~ 37.0
```

除非当前情境明确需要，否则不要使用极端值

### `recovery_capacity`

当前身体从疲劳中恢复的能力

它不是：

```text
现在恢复了多少
```

而是：

```text
当前恢复起来有多容易
```

### `nutrition_status`

当前营养充足与均衡程度

变化通常慢于 `hunger_level`

### `hydration_level`

身体水分状态

与 `thirst_level` 相关，但不严格互补

### `physiological_arousal`

身体警觉、兴奋和唤醒程度

可因：

- 激动
- 焦虑
- 运动
- 紧张

上升

它不等于快乐

### `sensory_overload`

感官刺激过载程度

可受：

- 噪声
- 人群
- 疲劳
- 情绪敏感度

影响

---

## 9. 即时情绪

```text
joy
calmness
sadness
anxiety
anger
fear
hope
shame
loneliness
belongingness
emotional_stability
emotional_intensity
```

这些字段不是互斥分类

不要要求：

```text
joy + sadness + anxiety + ... = 100
```

角色可以同时：

```text
开心
+
紧张
```

### `joy`

愉悦程度

### `calmness`

内在平静程度

### `sadness`

悲伤与低落

### `anxiety`

焦虑与不安

### `anger`

愤怒与烦躁

### `fear`

恐惧与威胁感

### `hope`

对未来结果的积极期待

### `shame`

羞耻、难堪、自我否定的即时程度

### `loneliness`

主观孤独感

即使：

```text
social_connectedness 高
```

也可能：

```text
loneliness 高
```

### `belongingness`

主观归属感

### `emotional_stability`

当前情绪稳定程度

### `emotional_intensity`

当前总体情绪强度

它描述的是：

```text
情绪有多强
```

而不是：

```text
情绪有多好
```

---

## 10. 认知状态

```text
attention_capacity
concentration
mental_clarity
working_memory_capacity
cognitive_flexibility
executive_function
decision_speed
judgment_confidence
self_awareness
rumination_level
```

### `attention_capacity`

当前可分配注意力资源

### `concentration`

持续把注意力放在当前任务上的能力

可以出现：

```text
attention_capacity 高
concentration 低
```

表示脑子并不很累，但当前容易分心

### `mental_clarity`

思维清晰程度

### `working_memory_capacity`

当前短时间保持和处理信息的能力

它不是角色永久智力

### `cognitive_flexibility`

当前切换思路、任务和适应新信息的能力

### `executive_function`

计划、控制和执行行为的当前能力

### `decision_speed`

做决定的速度

高不代表判断质量一定高

### `judgment_confidence`

对自身当前判断的信心

### `self_awareness`

对自身状态的觉察程度

### `rumination_level`

反复围绕负面或未解决内容思考的程度

---

## 11. 自我认知与动机

```text
self_esteem
self_efficacy
future_confidence
sense_of_meaning
intrinsic_motivation
extrinsic_motivation
achievement_motivation
affiliation_need
approval_need
autonomy_need
creative_drive
avoidance_tendency
```

### `self_esteem`

总体自我价值感

### `self_efficacy`

对“自己有能力完成事情”的信心

### `future_confidence`

对未来发展和结果的信心

### `sense_of_meaning`

对当前生活、行动和关系的意义感

### `intrinsic_motivation`

因为事情本身有兴趣或价值而行动的动力

### `extrinsic_motivation`

由外部评价、奖励和要求驱动的程度

### `achievement_motivation`

追求目标、成果与提升的动力

### `affiliation_need`

建立和维持关系的需求

### `approval_need`

希望得到他人认可的需求

### `autonomy_need`

希望自己决定行为和方向的需求

### `creative_drive`

创作与表达欲望

### `avoidance_tendency`

面对压力、困难和冲突时倾向回避的程度

---

## 12. 人格与行为倾向

```text
openness
conscientiousness
extraversion
agreeableness
emotional_reactivity
impulsivity
patience
resilience
adaptability
perfectionism
risk_tolerance
```

这一组通常应该**相对稳定**，不要让模型在几分钟内大幅改变

### `openness`

对新体验、观念和创造性内容的开放程度

### `conscientiousness`

尽责、计划性和自我约束倾向

### `extraversion`

主动寻求社交刺激和互动的倾向

它不是 `social_energy`

例如：

```text
extraversion = 70
social_energy = 20
```

表示平时偏外向，但今天已经社交耗尽

### `agreeableness`

合作、体谅和维持和谐的倾向

### `emotional_reactivity`

受外界刺激后产生明显情绪变化的敏感程度

### `impulsivity`

未经充分思考就行动的倾向

### `patience`

等待、延迟满足和持续处理问题的耐心程度

### `resilience`

经历压力或挫折后的恢复韧性

### `adaptability`

面对变化时调整行为的能力

### `perfectionism`

对结果标准、完整度和评价要求较高的倾向

### `risk_tolerance`

接受不确定性和潜在失败的程度

---

## 13. 压力与恢复

```text
accumulated_stress
emotional_exhaustion
burnout_risk
trigger_sensitivity
coping_capacity
```

### `accumulated_stress`

近期累计心理压力

通常变化慢于即时 `anxiety`

### `emotional_exhaustion`

情绪资源被持续消耗的程度

### `burnout_risk`

在当前长期状态下继续发展为明显倦怠的风险

可综合受到：

```text
accumulated_stress
emotional_exhaustion
sleep_debt
schedule_pressure
recovery_capacity
```

影响

### `trigger_sensitivity`

受到负面刺激后出现明显情绪反应的敏感程度

### `coping_capacity`

当前调节压力、情绪并解决困难的能力

---

## 14. 社会关系

```text
attachment_security
family_closeness
friendship_closeness
interpersonal_trust
social_connectedness
interpersonal_dependency
interpersonal_tension
social_energy
emotional_support
```

### `attachment_security`

总体人际依恋安全感

### `family_closeness`

家庭关系总体亲密程度

### `friendship_closeness`

友情关系总体亲密程度

### `interpersonal_trust`

对他人的总体信任程度

### `social_connectedness`

客观或半客观社会联系充足程度

### `interpersonal_dependency`

情绪与决策上依赖他人的程度

### `interpersonal_tension`

当前或近期人际关系紧张程度

### `social_energy`

当前可用于社交的精力

这是聊天行为层很重要的即时状态

### `emotional_support`

当前可以获得的情感支持程度

---

## 15. 时间与责任负荷

```text
available_time
schedule_pressure
obligation_load
```

### `available_time`

当前可自由支配时间

高：

```text
比较空闲
```

低：

```text
正在上课 / 工作 / 赶任务
```

### `schedule_pressure`

当前日程紧迫程度

例如：

```text
即将迟到
临近 deadline
安排密集
```

会提高

### `obligation_load`

当前承担任务和责任的总体数量与重量

与 `schedule_pressure` 区分：

```text
obligation_load
= 有多少事情压在身上

schedule_pressure
= 这些事情此刻有多紧迫
```

---

## 16. 不要做机械互补

不建议写规则：

```text
energy = 100 - fatigue
calmness = 100 - anxiety
loneliness = 100 - belongingness
hydration = 100 - thirst
```

这些状态不是严格二元轴

更合理的是保持**相关性**

例如：

```text
sleep_debt ↑
→ fatigue 往往 ↑
→ sleepiness 往往 ↑
→ attention 往往 ↓
→ emotional_stability 可能 ↓
```

但实际幅度仍取决于人物、时间和环境

---

## 17. 快变量、中速变量与慢变量

为了避免状态更新产生不自然跳变，建议区分变化速度

### 快变量

几分钟到几小时内可明显变化：

```text
current_location
current_activity
current_situation

environmental_comfort
privacy_level
noise_level
crowd_density

energy_level
fatigue_level
sleepiness_level
hunger_level
thirst_level
pain_level
physical_strain

physiological_arousal
sensory_overload

joy
calmness
sadness
anxiety
anger
fear
shame
emotional_intensity

attention_capacity
concentration
mental_clarity
decision_speed

interpersonal_tension
social_energy

available_time
schedule_pressure
```

### 中速变量

数小时到数天：

```text
sleep_quality
sleep_debt
hydration_level
recovery_capacity

hope
loneliness
belongingness
rumination_level

self_efficacy
future_confidence
motivation fields

accumulated_stress
emotional_exhaustion
coping_capacity
emotional_support
```

### 慢变量

通常不应短时间剧烈变化：

```text
circadian_stability
nutrition_status

self_esteem

openness
conscientiousness
extraversion
agreeableness
emotional_reactivity
impulsivity
patience
resilience
adaptability
perfectionism
risk_tolerance

attachment_security
family_closeness
friendship_closeness
interpersonal_trust
interpersonal_dependency
```

这不是代码硬限制，而是为了保持角色连续性推荐的语义约束

---

## 18. 推荐冷启动编写顺序

不要从几十个字段开始随机猜数值

### Step 1：确定客观时间

例如：

```text
工作日
20:00
UTC+9
```

### Step 2：确定固定日程

先判断：

```text
这个星期几
这个时间
角色理论上在哪里
正在做什么
```

角色固定生活制度优先于泛化常识

### Step 3：写文本状态

先完成：

```text
current_time
current_location
current_activity
current_situation
```

### Step 4：填写环境

```text
comfort
privacy
noise
crowd
```

### Step 5：填写身体

重点：

```text
energy
fatigue
sleepiness
hunger
thirst
physical_strain
```

### Step 6：填写睡眠背景

```text
sleep_quality
sleep_debt
circadian_stability
```

### Step 7：填写当前情绪

根据今天发生的事情和角色态度填写

### Step 8：推导认知状态

根据：

```text
疲劳
情绪
环境
当前任务
```

设置：

```text
attention
concentration
clarity
executive_function
```

### Step 9：填写人格底座

主要依据角色长期设定

### Step 10：补充关系、压力与时间负荷

最后填写：

```text
stress
relationship
social_energy
available_time
schedule_pressure
obligation_load
```

---

## 19. 推荐一致性检查

配置完成后至少检查：

```text
这个时间她为什么在这里？
```

```text
当前活动和固定日程冲突吗？
```

```text
已经很疲劳，为什么精力仍然很高？
如果有原因，情境里是否能解释？
```

```text
周围非常拥挤，privacy_level 为什么仍然极高？
```

```text
严重欠睡时，sleepiness_level 为什么极低？
```

```text
当前压力明显很高，认知状态为什么完全不受影响？
```

```text
这个字段是即时状态，还是其实属于永久人设？
```

---

## 20. 不建议全部使用 50

`50` 是安全的中值，但如果所有字段都是 50，状态会失去人物区分度

尤其建议根据人设明确区分：

```text
self_esteem
approval_need
creative_drive
perfectionism
emotional_reactivity
social_energy
friendship_closeness
accumulated_stress
```

但也不要为了“鲜明”把大量字段设置为 `0` 或 `100`

极端值应有明确依据

---

## 21. `default_status` 与 `preset.md` 的职责区别

以下内容：

```text
喜欢绘画
固定就读夜间定时制
和某人是什么关系
习惯什么语气
长期生活习惯
```

更适合写在：

```text
preset.md
```

而不是 `default_status`

推荐职责：

```text
preset.md
→ 她是谁
→ 她长期怎样生活

default_status
→ 她现在处于什么状态
```

---

## 22. 与 `active_model_args` 的关系

两者属于不同层：

```text
active_model_args
→ 此刻是否开始一次社交媒体活动

default_status
→ 此刻角色处于什么状态
```

例如活动模型命中一次社交活动，并不意味着角色一定有精力长聊

如果当前：

```text
sleepiness_level 很高
energy_level 很低
available_time 很低
```

后续 LLM 行为层仍可能自然选择：

```text
打开
→ 看一眼
→ 不聊天
→ 退出
```

因此最终行为由：

```text
活动调度层
+
角色状态层
+
LLM 行为层
```

共同决定

---

## 23. 修改后为什么不生效

最常见原因是：

```text
status.json 已经存在
```

当前加载逻辑优先读取已有状态文件

若要重新使用新的 `default_status`：

```text
1. 停止程序
2. 备份 status.json
3. 删除 status.json
4. 修改 default_status
5. 重新启动
```

这样程序才会重新从冷启动模板建立状态

---

## 24. 最终原则

一个好的 `default_status` 应同时满足：

```text
时间正确
地点正确
固定日程正确
当前活动合理
身体状态能解释当前活动
情绪状态能解释当前事件
认知状态能解释身体 + 情绪
人格字段符合长期人物设定
关系状态符合关系网络
压力和时间负荷符合现实日程
```

重点不是让每个数字“非常精确”，而是让这些变量构成：

> **一个自洽、连续、可被下一次状态更新继续推演的角色状态起点。**
