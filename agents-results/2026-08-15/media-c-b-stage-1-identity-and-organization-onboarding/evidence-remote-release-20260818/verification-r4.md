# r4 远端代码与传输层发布核验

核验时间：2026-08-18 07:52（中国标准时间）

目标主机：`ubuntu@106.52.146.37`

发布身份：

- 后端：`openclaw-tag-router-media-tenant-20260818T-stage1-account-http-r4`
- 前端：`20260818T-stage1-account-http-r4`
- 后端来源清单：`17cc26611275c04d110143d50c5a064b7c02cf77cfe9729efabc52a6c218343a`
- 前端来源清单：`92e0ced44f838fb6abbc8349dee927e3510237fdab90a0181debddab769d1eeb`
- 候选清单：`0eddea7f096dc0a65ba4b1336a9591baf702a6290cf4b8cc80696a4bebd9c4d1`

通过项：

- 候选前后端逐文件哈希、候选绑定和运行器失败关闭门禁通过。
- 后端用户级服务处于 `active`，PID `3037509` 使用 r4 `settings.yaml`。
- `healthz`、`readyz`、SessionPrincipal 组合守卫和官方部署守卫通过。
- 前后端协同元数据一致。
- 磁盘、loopback 和公开入口的 `index.html` 哈希一致：`6a9d49013b0888c83c6fe557ab96e68ed93bc60c4be03b1d6f7d87a059ea72d9`。
- 公网 canonical Session 与精确兼容别名均返回相同的 401 业务响应；错误方法、尾斜杠和邻近 legacy 路径均返回 404。
- 官方发布入口增加运行时工具预检；缺失工具链负例退出 2，受管 Node/npm 正例通过。
- 官方 verifier 增加 Session 别名正负自测；缺失别名、响应漂移和 legacy 路由放宽均被拒绝。

首次正式调用在前端源快照阶段因 `sudo secure_path` 无法解析裸 `node` 而失败关闭；前端未切换，后端自动恢复 r3。修复官方入口并完成红绿证明后，第二次调用成功发布 r4。

边界：这是代码与生产传输层发布回执，不代表阶段一节点已经 `ACCEPTED`，也不代表生产数据库迁移、真实邮件、飞书写入、认证浏览器、物理设备或正式终验已经完成。
