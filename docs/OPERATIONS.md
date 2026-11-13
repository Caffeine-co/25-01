# 正式运行与运维手册

## 1. 环境

- Python ≥ 3.11，核心无需额外依赖。
- 单机/单世界/单主写者。推荐本地磁盘上的 SQLite（不建议网络文件系统）。
- 在 Python 3.13 的 Linux 容器环境通过安装、API 测试和模拟测试。Windows 为支持的开发目标，但此版未逐一验证各 Windows 服务管理方式。

```bash
python -m pip install --no-deps .
python scripts/verify.py
```

## 2. 运行

**必须先设置强随机令牌**，参见 README。然后：

```bash
# 完全离线：规则世界运行，聊天为回退模板，时钟持续推进
worldlife-server examples/scenarios/roommates.json --db data/live.db

# 完全冻结世界时间，只允许 API 手动推进
worldlife-server examples/scenarios/roommates.json --db data/live.db --no-auto-time

# 可选远程 LLM + 跨日反思，必须配置 API_KEY/MODEL/BASE_URL
worldlife-server examples/scenarios/roommates.json --db data/live.db --provider remote --reflect-daily --max-calls 4
```

可设置 `--sim-minutes-per-second 1` 把 1 秒现实时间映射为 1 分钟模拟时间。服务一旦停止，不补算停机期间的世界时间。每次自动推进后都会立即持久化。模型调用与时钟推进由锁序列化，因此高延迟模型调用会短暂停止世界操作；有实时性要求应部署独立的异步认知队列。

## 3. 健康检查、审计、备份

```bash
worldlife-client status
worldlife-client events --limit 30
worldlife-client actor resident_01

# 一致性在线备份：即使服务没有停止，也通过 SQLite backup API 导出
worldlife-admin backup --db data/live.db --out backups/live-2026-11-13.db

# 核验数据库及规则指纹；应与服务使用同一份场景配置
worldlife-admin inspect examples/scenarios/roommates.json --db data/live.db
```

建议：按本地运营需求定期备份、加密保管包含真实聊天消息的存档，避免将 `data/`、`.env`、令牌或实际用户内容上传到公共 Git 仓库。恢复时先关闭服务，将有效备份复制成新的数据库文件，使用相同版本和场景配置启动。

## 4. 扩展到外部平台

建议新增独立的适配器（QQ、网页、游戏等），不修改 `WorldRuntime`：

```text
外部消息 → 平台鉴权及限流 → 生成稳定的原平台消息 id
         → POST /v1/chat (Idempotency-Key=platform-message-id)
         → 获取回复 → 平台实际发送
```

由于平台发送与 SQLite 提交不能共享数据库事务，**本版本不提供外部发送 exactly-once 保证**。适配器如果承担实际消息发送，应增加 outbox、发送状态回执和平台侧去重，不可将外部文本直接转化为世界的库存变动。

## 5. 故障处理

| 症状 | 原因/处理 |
|---|---|
| HTTP 401 | 检查服务端与客户端令牌是否一致 |
| HTTP 409（幂等） | 相同 ID 被用于不同业务内容；用新 ID 新建请求 |
| HTTP 409（revision） | 另一个进程正在写同一 DB；停止重复写入者并重新加载 |
| LLM 回复是保底文本 | Offline 模式、预算耗尽或远程 API/输出校验失败；检查事件日志 |
| 项目长时间不完成 | 目标设施未知、不可到达、资源不足或正在退避；查看项目状态、日志 |
| 服务时钟停止 | 检查服务 stdout/stderr 的 worldlife-clock 错误；保留 DB 后重启 |
| 升级后无法加载存档 | 规则指纹不同；先备份，使用显式版本迁移方案，不能强制载入 |

## 6. 生产安全注意

服务仅允许绑定本地环回地址（localhost）。**绝不能把当前明文 HTTP 服务直接暴露到公网**。要跨机访问，必须使用 TLS 反向代理、网络白名单和额外的应用层权限控制。管理员令牌允许操作整个世界，不能交给普通最终用户。远程模型内容是外部不可信输入；即使模型输出通过结构验证，也应保持世界规则和权限检查。

## 7. 部署/容量边界

- 这里的 Python 单进程和每分钟积分策略更适合有限数量的角色与小地图。
- 长期运行日志、幂等请求表和个人记忆需要按场景设置保留/归档策略。当前只有个人情景记忆保留最近 256 条；持久化审计事件无限追加。
- 尚无多进程分布式一致性、HA、自动迁移工具、内置 OAuth、动态插件沙箱、多租户隔离、指标告警集群。
- 远程模型只进行了本地 HTTP mock 测试，尚未验证任何厂商真实限额、鉴权、结算费用和跨地域延迟。
