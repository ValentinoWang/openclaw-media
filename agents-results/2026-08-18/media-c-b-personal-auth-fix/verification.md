# Media C/B 个人认证修复验证

日期：2026-08-18

候选目录：`.codex-work/stage1-integrated`

## 本轮变更

- 个人密码策略调整为 8-128 个字符，允许常见的字母、数字、符号和短语组合，同时拒绝明显常见/重复密码。
- 个人认证邮件接入 Resend 适配器，覆盖邮箱验证和密码找回；配置不完整或投递失败时 fail closed。
- 注册和重发验证邮件在投递失败时返回 HTTP 503 `email_delivery_unavailable`，前端显示可操作的错误，不再把失败注册显示为成功。
- 验证页重发邮件同样检查 HTTP 错误，避免 Resend 故障时显示“已发送”。

## 自动化证据

- `frontend`: `npm run build:media`，通过；包含登录合同、注册页合同、TypeScript 构建、Vite 产物和 release label 检查。
- `backend`: `.venv/bin/python -m pytest -q tests/test_personal_auth_mail_delivery_http.py tests/test_stage1_personal_auth_lifecycle.py tests/test_account_registration.py tests/test_account_auth.py tests/test_server_cli_stage1_composition.py`：`25 passed, 16 skipped`。
- `backend`: `.venv/bin/python -m pytest -q tests/test_personal_auth_postgres_composition.py tests/test_http_api.py`：`33 passed, 7 subtests passed`。
- 前后端源清单逐文件 `shasum -a 256 -c` 通过；候选 manifest 校验通过。

## 候选身份

- 前端清单：`4f4ae86b308fe6e906d5520eac579965f09acda28842b98bf49174358d821283`，216 个受管文件。
- 后端清单：`c679ce3407fe82d93d3e2bd7f5aceffa501e98a0957c8dc2377ead2f572bf7b4`，659 个受管文件。
- `candidate-manifest.json`：`ec276876dac46b76ca6aff287a0fe5456e0bb8af02d2c3bb7b33b2ef9cfc247a`。

## 边界

- 候选 `productionState` 仍为 `not_deployed`。
- 本轮未连接真实 Resend API、真实收件箱、生产数据库、飞书或远端生产环境；因此不代表生产接受。
