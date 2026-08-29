# Test Change Request: T1-AUTH-ROUTES / TCR-I2-PUBLIC-AUTH-ROUTES

- Acceptance contract: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md version 1
- Decision refs: media.stage1.stable-decisions@2, media.stage1.decision.personal-auth-contract@1
- Invalidation keys: media.stage1.acceptance-harness.v4, media.stage1.personal-auth-runtime.v1
- Request status: APPROVED
- Requested by: I2 implementation coordinator
- Required approver: main-orchestrator
- Affected protected tests: `.codex-work/stage1-i2/backend/tests/test_stage1_personal_auth_lifecycle.py` sha256:eb232753cc58e00401e6e697effec60681b7d392ae351dd9b11070304422b4e2
- Affected requirements: AC-02, AC-04, AC-05, AC-07

## Original rule

I2 生命周期测试要求 `/auth/register`、`/auth/verify`、`/auth/login`、`/auth/session`、`/auth/logout` 和 `/auth/organization/intent/*` 成功，并允许多个验证、找回和组织 intent 别名。

## Proposed rule

测试只调用十个冻结公共操作：六个 `/openclaw/auth/*` 个人认证 POST、`GET /openclaw/media/api/session`、`POST /openclaw/auth/logout` 及两个 `/openclaw/auth/feishu/*` POST。登录请求只允许 `identifier`，重置只允许 `newPassword`；旧 Stage 1 别名全部断言 404。增加邮件失败注入，证明注册、验证重发和找回在适配器失败时不会因账号存在性返回不同公开状态，同时失败被持久化或进入明确可观测的异步失败边界。

## Reason

真实 Nginx 不移除 `/openclaw/auth/` 前缀，旧测试会把不可到达的内部路径当作公共成功合同。独立 I2 复核还证明，已存在账号遇到邮件适配器失败时返回 503，而不存在账号返回 202，会泄露账号存在性。原测试既绑定错误路由，也缺少关键失败注入。

## Impact

只使 I2 个人认证与飞书扫码分派、请求字段、404 别名断言和邮件失败枚举安全基线失效并重锁。业务认证时效、密码策略、令牌摘要、会话撤销和无自动身份合并规则保持不变。I1 仅消费公开字段和错误码，不取得测试修改权。

## Alternatives considered

让 Nginx 隐式改写前缀会制造第二套路由权威；保留兼容别名违反已接受的单一路径硬切换；吞掉邮件异常会丢失可观测性并掩盖交付失败。这些方案都不能保留原测试。

## Approval

- Decision: APPROVED
- Approver: main-orchestrator
- Evidence: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/approvals/main-orchestrator-route-contract-v1.md
- Approved contract version: 1
- Relocked test hash: `.codex-work/stage1-i2/backend/tests/test_stage1_personal_auth_lifecycle.py` sha256 `d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d`

## Relock record

- Relock status: `LOCKED`
- Relock basis: current SSOT v4 manifest and I2 implementation source hashes were revalidated before the green baseline run.
- Green baseline command: `bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/I2.sh`
- Green baseline result: `20 passed, 16 skipped`
- Cross-root command: `python3 .codex-work/stage1-t1/backend/tests/check_stage1_auth_route_alignment.py --t1-root .codex-work/stage1-t1 --i1-root .codex-work/stage1-i1 --i2-root .codex-work/stage1-i2`
- Cross-root result: `STAGE1_AUTH_ROUTE_ALIGNMENT=GREEN`
- Scope note: this relock proves the local contract and current source alignment only; it does not prove real mail, Feishu, deployment, production, browser, device, or human acceptance.
