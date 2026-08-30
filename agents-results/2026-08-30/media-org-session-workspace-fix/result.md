# 组织 OAuth 会话工作区修复

## 结论

`AccountSession` 只承载认证身份，不携带 workspace 字段。修复前 `WorkspaceResolver` 将缺少 `workspace_mode`、`body_authority` 或 `member_role` 的 canonical 会话判为 `INVALID_SESSION`，HTTP 上下文随后使用 `personal_web` 默认值。修复后 workspace 模式、authority 和成员角色只从当前 workspace/membership 候选解析。

## 源码证据

- 提交：`3d868e42700c874d4082474786b864266668ac6a`
- 文件：`openclaw-tag-router/openclaw_app/account/workspace_resolution.py`
- 回归：`openclaw-tag-router/tests/test_workspace_resolution.py`
- 本地定向测试：`4 passed`（workspace resolver + account repository）
- 远端定向测试：`1 passed`（`tests/test_workspace_resolution.py`）

## 部署读回

- 主机：`ubuntu@106.52.146.37`
- release：`/home/ubuntu/.openclaw/releases/openclaw-tag-router-media-tenant-20260830-3d868e4`
- 用户级服务：`openclaw-bot-center-api.service`，状态 `active`
- 服务 cwd：上述 release 下的 `openclaw-tag-router`
- 组织 OAuth 启动：`POST /openclaw/media/auth/feishu/start` 携带 `workspaceIntent=organization_lark` 返回 `200`

## 未完成的真实验收

当前无法读取用户浏览器 Cookie，因此尚未取得本次重新登录后的 `/openclaw/media/api/session` 响应体。用户需退出旧会话并重新扫描组织二维码；验收字段必须是 `workspaceMode=organization_lark`、`bodyAuthority=lark`。
