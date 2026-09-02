# Active Model 配置指南

`active_model_args` 用于控制 25:01 中角色**在一天内何时、以多高概率主动打开社交软件**

配置位置：

```text
configs.json
└─ setting_config
   └─ active_model_args
```

对应实现：

```text
src/plugins/living/probability.py
```

当前模型不是直接指定“某一时刻打开软件的概率”，而是先构造一个随时间变化的**每小时事件率** `λ(t)`，再根据实际轮询间隔转换为本轮触发概率：

$$
P(t)=1-e^{-\lambda(t)\Delta t}
$$

整体可以理解为：

```text
角色作息
× 星期差异
× 基础活跃度
× 若干时间活动峰
      ↓
瞬时每小时打开率 λ(t)
      ↓
结合轮询间隔 Δt
      ↓
本轮打开概率 P(t)
```

---

## 1. 默认配置

```json
"active_model_args": {
  "poll_interval_seconds": 600,
  "global_rate_multiplier": 1.65,
  "base_rate_per_hour": 0.32,
  "wake_hour": 11.0,
  "sleep_hour": 3.5,
  "sleep_floor": 0.035,
  "awake_edge_steepness": 3.2,
  "weekday_multipliers": {
    "0": 0.95,
    "1": 0.95,
    "2": 1.00,
    "3": 1.00,
    "4": 1.08,
    "5": 1.15,
    "6": 1.10
  },
  "activity_peaks": [
    {
      "name": "起床后查看通知",
      "center_hour": 11.5,
      "width_hour": 0.55,
      "rate_per_hour": 0.85
    }
  ]
}
```

---

## 2. 总体数学模型

当前代码最终计算：

$$
\lambda(t)=
M_g
\cdot
M_w(d)
\cdot
W_a(t)
\cdot
\left[
\lambda_0+\sum_{i=1}^{n} r_iG_i(t)
\right]
$$

其中：

| 符号 | 配置项 | 含义 |
| --- | --- | --- |
| $M_g$ | `global_rate_multiplier` | 全局活动倍率 |
| $M_w(d)$ | `weekday_multipliers` | 星期倍率 |
| $W_a(t)$ | `wake_hour` / `sleep_hour` 等 | 清醒权重 |
| $\lambda_0$ | `base_rate_per_hour` | 基础每小时打开率 |
| $r_i$ | `activity_peaks[i].rate_per_hour` | 第 i 个活动峰强度 |
| $G_i(t)$ | `center_hour` / `width_hour` | 第 i 个高斯时间峰 |

得到每小时事件率后：

$$
P(t)=1-e^{-\lambda(t)\Delta t}
$$

其中：

$$
\Delta t=
\frac{\text{poll\_interval\_seconds}}{3600}
$$

---

## 3. 时间表示

代码会将 Unix Timestamp 转为角色配置时区，再转换成十进制小时：

```python
hour = (
    local_datetime.hour
    + local_datetime.minute / 60.0
    + local_datetime.second / 3600.0
)
```

例如：

```text
11:30 → 11.5
17:12 → 17.2
00:42 → 0.7
02:36 → 2.6
```

因此：

```json
"center_hour": 14.3
```

表示约 `14:18`，而不是 `14:30`

若希望表示 `14:30`，应写：

```json
"center_hour": 14.5
```

---

## 4. 星期编号

代码使用 Python `datetime.weekday()`：

```text
0 = Monday
1 = Tuesday
2 = Wednesday
3 = Thursday
4 = Friday
5 = Saturday
6 = Sunday
```

JSON 中键为字符串：

```json
"weekday_multipliers": {
  "0": 0.95,
  "1": 0.95,
  "2": 1.00,
  "3": 1.00,
  "4": 1.08,
  "5": 1.15,
  "6": 1.10
}
```

未配置的星期默认倍率为 `1.0`

---

## 5. 环形时间距离

为了正确处理跨午夜活动峰，代码使用：

$$
d(t,c)=
\min\left(
|t-c|,
24-|t-c|
\right)
$$

例如：

```text
23:30 ↔ 00:30
```

实际时间距离应为 `1 小时`，而不是 `23 小时`

对应代码：

```python
def circular_hour_distance(current_hour, center_hour):
    direct_distance = abs(current_hour - center_hour)
    return min(
        direct_distance,
        24.0 - direct_distance
    )
```

---

## 6. 高斯活动峰

每个：

```json
{
  "name": "放学后集中查看",
  "center_hour": 21.8,
  "width_hour": 0.95,
  "rate_per_hour": 0.85
}
```

对应：

$$
G_i(t)=
\exp\left(
-\frac{1}{2}
\left[
\frac{d(t,c_i)}{\sigma_i}
\right]^2
\right)
$$

其中：

```text
c_i = center_hour
σ_i = width_hour
```

### `center_hour`

峰值中心

在：

```text
current_hour == center_hour
```

时：

$$
G_i(t)=1
$$

因此该峰完整贡献：

```text
rate_per_hour
```

### `width_hour`

控制峰宽度

当：

```text
distance = width_hour
```

时：

$$
G(t)=e^{-1/2}\approx0.6065
$$

粗略理解：

```text
±1 × width → 约 60.7% 峰值
±2 × width → 约 13.5% 峰值
±3 × width → 约 1.1% 峰值
```

因此：

```text
width_hour 小 → 峰更集中
width_hour 大 → 峰覆盖时段更宽
```

代码要求：

```text
width_hour > 0
```

### `rate_per_hour`

表示该活动峰增加的**每小时事件率**

例如：

```json
"rate_per_hour": 1.2
```

在峰中心意味着：

```text
额外 λ = 1.2 / hour
```

它不是 `120% 概率`

---

## 7. 多峰叠加

所有活动峰直接求和：

$$
\lambda_{\text{peak}}(t)=
\sum_i r_iG_i(t)
$$

代码：

```python
total_peak_rate = 0.0

for peak in activity_peaks:
    total_peak_rate += (
        peak["rate_per_hour"]
        * peak_weight
    )
```

因此多个行为时段可以自然重叠，例如：

```text
晚间本来就高频查看手机
+
Nightcord 活动期间额外活跃
```

---

## 8. 基础事件率

```json
"base_rate_per_hour": 0.32
```

表示即使当前不在任何明显活动峰附近，角色在清醒状态下仍存在基础打开倾向

模型先计算：

$$
\lambda_0+\lambda_{\text{peak}}(t)
$$

然后统一乘以清醒权重、星期倍率和全局倍率

---

## 9. 清醒权重模型

当前代码没有使用硬切换：

```text
wake_hour 到了 → 瞬间从 0 变 1
sleep_hour 到了 → 瞬间从 1 变 0
```

而是使用 Sigmoid 平滑过渡

Sigmoid：

$$
S(x)=\frac{1}{1+e^{-x}}
$$

---

## 10. 起床后的相对时间

```python
hours_after_wake = (
    current_hour - wake_hour
) % 24.0
```

清醒持续时间：

```python
awake_duration = (
    sleep_hour - wake_hour
) % 24.0
```

所以可以正确表示跨午夜作息，例如：

```text
wake_hour  = 11.0
sleep_hour = 3.5
```

意味着：

```text
11:00 起床
03:30 入睡
```

---

## 11. 起床边缘与入睡边缘

起床过渡：

$$
W_{\text{wake}}(t)=
S(kh)
$$

入睡过渡：

$$
W_{\text{sleep}}(t)=
S\left(k(D-h)\right)
$$

其中：

```text
k = awake_edge_steepness
h = hours_after_wake
D = awake_duration
```

代码最终：

```python
raw_awake_weight = (
    wake_transition
    * sleep_transition
)
```

即：

$$
W_{\text{raw}}(t)=
W_{\text{wake}}(t)
W_{\text{sleep}}(t)
$$

---

## 12. `sleep_floor`

如果完全使用 `raw_awake_weight`，睡眠阶段概率会非常接近 0

因此加入最低权重：

$$
W_a(t)=
f_s+
(1-f_s)W_{\text{raw}}(t)
$$

其中：

```text
f_s = sleep_floor
```

对应：

```python
return (
    sleep_floor
    + (1.0 - sleep_floor)
    * raw_awake_weight
)
```

例如：

```json
"sleep_floor": 0.035
```

表示睡眠期仍保留少量打开软件可能性

注意：它是**倍率**，不是直接概率

---

## 13. `awake_edge_steepness`

控制起床和入睡边缘的陡峭程度

```text
值小 → 过渡更平缓
值大 → 作息边缘更明显
```

粗略可参考：

```text
1 ~ 2   很平缓
2 ~ 4   比较自然
4 ~ 8   较明显的固定作息
```

不建议极端增大，因为本模型描述的是概率倾向，不是硬性日程判断

---

## 14. 星期倍率

例如：

```json
"5": 1.15
```

表示周六：

```text
整个 λ(t) × 1.15
```

因此会同时放大：

- 基础事件率
- 所有活动峰

---

## 15. `global_rate_multiplier`

最终全局倍率：

```json
"global_rate_multiplier": 1.65
```

即：

$$
\lambda(t)\times1.65
$$

它不改变一天内概率曲线的形状，只改变整体活动频率

因此实测后：

```text
时段分布合理，但全天次数整体偏少
→ 增大 global_rate_multiplier

时段分布合理，但全天次数整体偏多
→ 减小 global_rate_multiplier
```

它适合作为最终校准旋钮

---

## 16. 最终每小时事件率

代码：

```python
rate_per_hour = (
    global_multiplier
    * weekday_multiplier
    * current_awake_weight
    * (base_rate + peak_rate)
)
```

即：

$$
\boxed{
\lambda(t)=
M_g
M_w(d)
W_a(t)
\left[
\lambda_0+\sum_i r_iG_i(t)
\right]
}
$$

最后使用：

```python
max(0.0, rate_per_hour)
```

防止负事件率

---

## 17. 为什么 `λ` 可以大于 1

假设：

```text
λ(t) = 2.0 / hour
```

它不是：

```text
200% 概率
```

而是：

```text
事件发生率约为每小时 2 次
```

事件率没有必须小于等于 1 的限制

所以当前模型不需要 `max_probability` 去裁剪事件率

---

## 18. 从事件率转换为概率

代码：

```python
def rate_to_probability(
    rate_per_hour: float,
    interval_seconds: int
) -> float:
    interval_hours = interval_seconds / 3600.0
    return (
        1.0
        - math.exp(
            -rate_per_hour
            * interval_hours
        )
    )
```

即：

$$
\boxed{
P=1-e^{-\lambda\Delta t}
}
$$

这是泊松过程中，在长度为 `Δt` 的时间窗口内**至少发生一次事件**的概率

---

## 19. `poll_interval_seconds`

当前：

```json
"poll_interval_seconds": 600
```

表示：

$$
\Delta t=
\frac{600}{3600}=
\frac{1}{6}\ \text{hour}
$$

假设：

```text
λ = 1 / hour
```

那么每 10 分钟一轮时：

$$
P=
1-e^{-1/6}
\approx15.35\%
$$

不是简单的 `16.67%`。

当 `λΔt` 很小时，两者近似：

$$
1-e^{-x}\approx x
$$

同时泊松公式天然保证：

$$
0\le P<1
$$

---

## 20. `poll_interval_seconds` 必须与 Scheduler 对齐

例如：

```json
"poll_interval_seconds": 600
```

同时：

```json
"scheduler_config": {
  "chat_dispatch": {
    "minute": "*/10"
  }
}
```

两者都代表 10 分钟

若 Scheduler 实际每 10 分钟执行，但这里写成：

```json
"poll_interval_seconds": 60
```

代码会错误地认为本轮只覆盖 1 分钟，从而显著降低触发概率

因此：

```text
poll_interval_seconds
≈
chat_dispatch 的实际轮询间隔
```

必须保持一致

---

## 21. 外层触发逻辑

概念上：

```python
probability = active_probability(timestamp)

if random.random() < probability:
    # 开始一次社交媒体活动
```

当前项目使用的反向判断与之等价：

```python
if random.random() > probability:
    return
```

因为 `random.random()` 均匀分布于 `[0, 1)`

---

## 22. 各参数影响

| 参数 | 增大后的主要效果 |
| --- | --- |
| `global_rate_multiplier` | 全天整体活动次数提高 |
| `base_rate_per_hour` | 非峰值时间活动增加 |
| `wake_hour` | 清醒窗口起点后移 |
| `sleep_hour` | 清醒窗口终点后移 |
| `sleep_floor` | 睡眠时间活动增加 |
| `awake_edge_steepness` | 起床 / 入睡边缘更陡 |
| `weekday_multipliers[x]` | 指定星期整体活动增加 |
| `center_hour` | 移动活动峰位置 |
| `width_hour` | 扩宽活动峰 |
| `rate_per_hour` | 提高对应活动峰强度 |
| `poll_interval_seconds` | 改变每轮时间窗口，必须与调度同步 |

---

## 23. 推荐调参顺序

推荐：

```text
1. wake_hour / sleep_hour
2. activity_peaks.center_hour
3. activity_peaks.width_hour
4. weekday_multipliers
5. base_rate_per_hour
6. activity_peaks.rate_per_hour
7. sleep_floor
8. global_rate_multiplier
```

其中 `global_rate_multiplier` 最适合作为实测后的总量校准

---

## 24. 如何设计 Activity Peaks

先回答：

```text
角色什么情况下自然会拿起手机？
```

例如：

```text
起床后
通勤途中
午休
放学 / 下班后
固定线上娱乐活动
创作结束后
睡前
```

再映射为：

```json
{
  "name": "语义名称",
  "center_hour": 21.0,
  "width_hour": 1.0,
  "rate_per_hour": 0.6
}
```

`name` 当前不参与计算，但应保留用于维护配置

---

## 25. 活动模型不负责决定聊天行为

本模型只决定：

```text
是否开始一次社交媒体活动
```

不决定：

```text
打开后是否聊天
进入哪个会话
是否回复
停留多久
是否切换
```

因此：

```text
概率命中 ≠ 必须发言
```

自然结果可以是：

```text
打开软件
→ 浏览主页
→ 看了一些消息
→ 没有想说的话
→ 退出
```

如果这种情况比例过高，应优先检查 `pre_chat` / chat Prompt 和行为策略，而不是只继续提高活动概率

---

## 26. 期望次数与实际波动

模型是随机过程

假设一天中第 `k` 次轮询概率为：

$$
p_k
$$

一天总打开次数期望约为：

$$
E[N]=\sum_k p_k
$$

但实际单日结果可以明显高于或低于期望

因此调参时建议观察：

```text
至少 7 ~ 14 天
```

重点看：

```text
平均打开次数
时段分布
工作日 / 周末差异
睡眠期误触发
```

不要只根据某一天结果修改参数

---

## 27. 完整公式

当前 `probability.py` 最终可以写成：

$$
\boxed{
P(t)=
1-
\exp\left[-
M_g
M_w(d)
W_a(t)
\left(
\lambda_0+\sum_i r_iG_i(t)
\right)
\Delta t
\right]
}
$$

其中：

$$
G_i(t)=
\exp\left(
-\frac{1}{2}
\left[
\frac{
\min\left(|t-c_i|,24-|t-c_i|\right)
}{
\sigma_i
}
\right]^2
\right)
$$

以及：

$$
W_a(t)=
f_s+
(1-f_s)
S(kh)
S\left(k(D-h)\right)
$$

这就是当前 25:01 `active_model_args` 对应的完整数学计算模型