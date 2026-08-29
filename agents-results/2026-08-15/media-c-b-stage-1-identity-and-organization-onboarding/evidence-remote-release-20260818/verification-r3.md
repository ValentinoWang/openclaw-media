# r3 远端代码发布核验

核验时间：2026-08-18 04:24（中国标准时间）

目标主机：`ubuntu@106.52.146.37`

发布身份：

- 后端：`openclaw-tag-router-media-tenant-20260818T-stage1-keyword-session-r3`
- 前端：`20260818T-stage1-keyword-session-r3`
- 后端来源清单：`0210aa094663a8a1b551b021ec55702050c5d72633db7e2825dfedd634f7a138`
- 前端来源清单：`92e0ced44f838fb6abbc8349dee927e3510237fdab90a0181debddab769d1eeb`
- 候选清单：`edda28759442676faa91ed6692f1fec8a703c730b8ad176cdc2c317e53f2b612`

通过项：

- 本地阶段一测试：`208 passed`。
- 本地 `npm run build:media`：通过。
- 本地运行器配置 `--all --fail-closed`：通过。
- 远端后端来源清单和前端来源清单：通过。
- 远端 `SessionPrincipal` 组合守卫：通过。
- 用户级 systemd 服务进程的 `--settings` 路径指向 r3 后端 release。
- `healthz`、`readyz`：通过。
- 官方 `/usr/local/sbin/verify-openclaw-media`：通过。
- 前后端协同元数据：通过。
- 磁盘、loopback 和公开入口的前端 `index.html` 哈希一致：`6a9d49013b0888c83c6fe557ab96e68ed93bc60c4be03b1d6f7d87a059ea72d`。
- 构建所需的临时 `/mnt/openclaw-data/openclaw-media-build-work/backend` 链接：已删除。

边界：这是一份代码发布与运行守卫回执，不代表阶段一节点已经 `ACCEPTED`，也不代表生产数据库迁移、数据库回读、真实邮件、飞书写入、认证浏览器、设备验收或正式终验已经完成。
