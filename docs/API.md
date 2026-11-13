# HTTP API v1（WorldLife 2.0）

本地启动：`worldlife-server examples/scenarios/roommates.json --db data/roommates_live.db`。所有路径统一位于 `/v1`；默认仅监听 `127.0.0.1:8765`。

## 鉴权、幂等、错误码

所有请求必须带：`Authorization: Bearer <WORLDLIFE_SERVER_TOKEN>`。服务启动拒绝长度少于 24 字符的令牌。**所有 POST 必须带一个稳定且唯一的 `Idempotency-Key`**（只允许 ASCII 字母数字、`-_.:`，最长 128）。客户端断线重试时必须继续使用**相同 ID 与相同 JSON 内容**；不同业务请求必须使用新的 ID。

响应为 JSON。常见状态：`200` 成功/返回已提交回执，`400` 参数错误，`401` 认证失败，`404` 路由不存在，`409` 幂等冲突或存档版本冲突，`413` 超过 20 KB 的请求体，`500` 内部错误。`GET` 不需要幂等 ID。

不要把密钥写入 URL，也不要把密钥与数据库中的用户消息上传到公共仓库。服务不发送浏览器 CORS 允许头；建议使用随包 CLI 客户端或可信服务器端应用。

## 读取接口

| 方法 | 路径 | 返回内容 |
|---|---|---|
| GET | `/v1/health` | 版本、模拟分钟、运行进程是否响应 |
| GET | `/v1/state` | 世界名、当前分钟、角色 ID、真实资源、事件汇总（管理员视图） |
| GET | `/v1/state?actor=resident_01` | 指定角色的局部视图、需求、技能、项目、情绪、记忆和主观信念 |
| GET | `/v1/events?limit=20` | 最近事件日志（最多 1000 条） |

`/v1/state` 的管理员响应含世界资源；**该数据不应直接作为 LLM 的上下文**。模型必须使用 `actor_view()` 这样的角色可见信息。

## 修改接口

下述请求都需要 `Authorization` 和 `Idempotency-Key`：

| 方法 | 路径 | JSON 正文示例 | 说明 |
|---|---|---|---|
| POST | `/v1/advance` | `{"minutes":120}` | 推进 0～10080 模拟分钟 |
| POST | `/v1/chat` | `{"actor":"resident_01","author":"user","message":"你好"}` | 获得语言回复；可建议动作但不瞬间执行 |
| POST | `/v1/reflect` | `{"actor":"resident_01"}` | 根据已有认知反思，可能添加校验后的项目 |
| POST | `/v1/project` | `{"actor":"resident_01","project":{...}}` | 创建多步骤项目 |
| POST | `/v1/project/cancel` | `{"actor":"resident_01","project_id":"project1"}` | 取消项目 |
| POST | `/v1/claim` | `{"actor":"resident_01","key":"appointment","value":"Monday","confidence":0.4,"evidence_id":"msg-99"}` | 输入来源可信度不超过 0.7 的外部声称；不改变客观事实 |
| POST | `/v1/intent` | `{"actor":"resident_01","kind":"move","target":"hall"}` | 提交人工/插件指定的受控动作；检查个人已知路网和能力 |

`/v1/project` 使用的项目格式见 `examples/projects/sketch.json`。动作种类目前只允许 `move`、`use`、`practice`、`assist`、`socialize`，并且目标地点、设施或人物必须存在于该世界。行动将逐步执行，项目可能成功、失败或取消。

### 直接 HTTP 请求例子（PowerShell）

```powershell
$headers = @{
  Authorization = "Bearer $env:WORLDLIFE_SERVER_TOKEN"
  'Idempotency-Key' = [guid]::NewGuid().ToString('N')
}
$body = @{ actor='resident_01'; author='user'; message='今天想画什么？' } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8765/v1/chat' -Method Post `
  -Headers $headers -ContentType 'application/json' -Body $body
```

### Python 客户端示例

```python
import os, uuid, json
from urllib.request import Request, urlopen

payload = json.dumps({"minutes": 30}).encode("utf-8")
req = Request("http://127.0.0.1:8765/v1/advance", payload, method="POST", headers={
    "Authorization": "Bearer " + os.environ["WORLDLIFE_SERVER_TOKEN"],
    "Idempotency-Key": str(uuid.uuid4()),
    "Content-Type": "application/json",
})
with urlopen(req, timeout=10) as response:
    print(json.loads(response.read()))
```

**重要：本 HTTP 接口目前只有单一管理员令牌。** 没有多租户用户权限、流量限速、HTTPS 证书管理或第三方登录。对外接入 QQ/网页/游戏时，应在适配层对每个用户的操作设置单独授权，不能把服务端管理员令牌交给普通用户。
