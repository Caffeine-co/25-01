# 构建产物部署

本文面向不准备修改 Python 源码、希望直接使用 GitHub Release 构建产物或 Docker 镜像部署 25:01 的用户

---

## 1. 可用构建产物

当前 Release Workflow 在推送 `v*` Tag 时自动构建：

| 平台 | 架构 | 产物格式 |
| --- | --- | --- |
| Windows | x64 | `.zip` |
| Linux | amd64 | `.tar.gz` |
| macOS | arm64 | `.tar.gz` |

Release 内的可执行文件由 Nuitka `--onefile` 构建

当前 Release 包同时包含：

```text
25-01(.exe)
configs.example.json
location.example.json
image_metadata.example.json
prompt/
```

> `meta_image/` 当前不会随 Release Workflow 一同打包。若启用角色预设图片，请自行准备该目录及对应资源

---

## 2. 准备运行目录

解压后建议整理为：
```text
25-01/
├─ 25-01.exe              # Windows
│  或 25-01               # Linux / macOS
├─ configs.json
├─ location.json
├─ image_metadata.json
├─ prompt/
├─ meta_image/            # 使用预设图片时需要
├─ data/                  # 数据库与角色状态
└─ logs/                  # 运行日志，程序运行后生成
```

`logs/` 用于保存持久化运行日志。日志文件按日期组织，并在每日 `00:00` 自动轮转；历史日志自动压缩，并保留最近 30 天


复制并重命名示例文件：

```text
configs.example.json        → configs.json
location.example.json       → location.json
image_metadata.example.json → image_metadata.json
```

---

## 3. 配置 LLM

编辑 `configs.json`：

```json
{
  "llm_config": {
    "api_key": "YOUR_API_KEY",
    "base_url": "YOUR_OPENAI_COMPATIBLE_ENDPOINT",
    "model_name": "YOUR_MODEL",
    "reasoning_effort": "medium",
    "timeout": 60,
    "retry_times": 3
  }
}
```

当前主代码通过 OpenAI-compatible Client 调用模型，并使用 Pydantic Structured Output 解析结果

建议模型至少具备：

- OpenAI Chat Completions 兼容接口
- Structured Output / parse 所需兼容能力
- 足够长的上下文窗口
- 若启用图片理解，则需要多模态输入能力

完整字段见 [Config_Tutorial.md](Config_Tutorial.md)

---

## 4. 配置 OneBot V11 会话

25:01 使用 NoneBot2 OneBot V11 Adapter

推荐使用反向 WebSocket：

```text
ws://127.0.0.1:2501/onebot/v11/ws
```

其中 `2501` 对应 `configs.json` 中的 `port`

若 OneBot 实现与 25:01 不在同一台机器，请把 `host` 修改为：

```json
"host": "0.0.0.0"
```

并将反向 WebSocket 地址中的主机改为 25:01 所在机器可访问的 IP / 主机名

如配置了 OneBot Access Token，还需要保证协议端与 NoneBot 侧 Token 一致

---

## 5. 配置允许会话

25:01 不会自动与所有 QQ 会话交互

例如白名单模式：

```json
"chat_config": {
  "run_mode": "whitelist",
  "whitelists": [
    {"type": "group", "id": 123456789},
    {"type": "friend", "id": 10001}
  ],
  "blacklists": []
}
```

`type` 仅支持：

- `group`
- `friend`

模型在 `pre_chat` 和 `switch` 中选择的会话同样会被 Schema 校验，不能跳出当前允许名单

---

## 6. 启动

### Windows

```powershell
.\25-01.exe
```

### Linux

```bash
chmod +x ./25-01
./25-01
```

### macOS

```bash
chmod +x ./25-01
./25-01
```

首次启动后，项目会按配置创建 SQLite 持久化文件

---

## 7. Docker / GHCR 部署

Tag 发布时项目也会构建：

```text
ghcr.io/caffeine-co/25-01:<version>
ghcr.io/caffeine-co/25-01:latest
```

示例：

```bash
docker pull ghcr.io/caffeine-co/25-01:latest
```

推荐在宿主机准备：

```text
runtime/
├─ configs.json
├─ location.json
├─ image_metadata.json
├─ prompt/
├─ meta_image/
├─ data/
└─ logs/
```

运行示意：

```bash
docker run -d \
  --name 25-01 \
  --restart unless-stopped \
  -p 2501:2501 \
  -v "$(pwd)/configs.json:/app/configs.json" \
  -v "$(pwd)/location.json:/app/location.json" \
  -v "$(pwd)/image_metadata.json:/app/image_metadata.json" \
  -v "$(pwd)/prompt:/app/prompt" \
  -v "$(pwd)/meta_image:/app/meta_image" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  ghcr.io/caffeine-co/25-01:latest
```

如果将数据库 / 状态文件放进 `data/`，请同步修改 `configs.json` 内各路径，例如：

```json
"session_info_db_path": "data/session_info.db",
"message_db_path": "data/message.db",
"memory_db_path": "data/memory.db",
"status_path": "data/status.json"
```

Docker 场景必须将：

```json
"host": "0.0.0.0"
```

否则容器外无法访问监听端口

---

## 8. 运行日志

25:01 启动时会同时初始化控制台日志与文件日志

文件日志默认写入当前工作目录：

```text
logs/
```

当前持久化策略为：

| 项目  | 行为  |
| --- | --- |
| 日志级别 | `DEBUG` 及以上 |
| 文件编码 | UTF-8 |
| 文件目录 | `logs/` |
| 轮转时间 | 每日 `00:00` |
| 保留时间 | 30 天 |
| 历史文件 | ZIP 压缩 |
| 写入方式 | 队列异步写入 |
| Exception diagnose | 关闭  |

日志格式与控制台保持统一：

```text
[MM-DD HH:mm:ss] [25:01] | LEVEL | message
```

### 日志目录与工作目录

日志路径使用相对路径：

```text
logs/{time:YYYY-MM-DD}.log
```

因此 `logs/` 实际创建在**程序当前工作目录**下，而不是强制绑定到可执行文件所在目录

例如在：

```text
C:\Bot\25-01\
```

目录中启动程序：

```powershell
.\25-01.exe
```

日志通常位于：

```text
C:\Bot\25-01\logs\
```

### Docker 日志持久化

Docker 容器本身不是持久化存储

如果希望容器删除或重新创建后仍然保留历史日志，应挂载：

```bash
-v "$(pwd)/logs:/app/logs"
```

否则日志虽然会正常写入容器中的：

```text
/app/logs
```

但删除容器后这些文件也会一并消失

### 故障排查

出现以下问题时建议优先检查 `logs/`：

```text
程序异常退出
LLM 请求持续重试
Scheduler Job 抛出异常
状态更新失败
消息发送异常
数据库操作失败
configs.json 加载失败
```

由于日志系统在读取 `configs.json` 前就已经初始化，因此配置文件读取失败等启动早期异常也会写入日志

---

## 9. NapCat 与 Docker 同机时

如果 NapCat 运行在宿主机，而 25:01 运行在 Docker：

```text
ws://127.0.0.1:2501/onebot/v11/ws
```

反之：

```text
ws://host.docker.internal:2501/onebot/v11/ws
```

前提是已经映射：

```text
2501:2501
```

如果二者都运行在同一个 Docker Network，可使用容器名：

```text
ws://25-01:2501/onebot/v11/ws
```

---

## 10. 启动前检查

- [ ] `configs.json` 已存在
- [ ] API Key 与模型端点正确
- [ ] `prompt/` 中配置指向的文件均存在
- [ ] `location.json` 已存在
- [ ] `image_metadata.json` 已存在
- [ ] 启用预设图片时 `meta_image/` 与 metadata 对应
- [ ] 白名单 / 黑名单中的会话 ID 正确
- [ ] OneBot V11 反向 WebSocket 地址正确
- [ ] Docker 部署时 `host=0.0.0.0`
- [ ] 数据库和状态文件所在目录具有写权限

---

## 11. 升级建议

升级 Release 前建议备份：

```text
configs.json
location.json
image_metadata.json
prompt/
meta_image/
status.json
*.db
```

尤其不要直接覆盖：

- `status.json`
- `memory.db`
- `message.db`
- `session_info.db`

它们保存了角色连续运行所形成的状态、消息和记忆