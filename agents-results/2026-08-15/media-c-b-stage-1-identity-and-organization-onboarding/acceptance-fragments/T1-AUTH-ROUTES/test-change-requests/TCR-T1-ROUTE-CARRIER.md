# Test Change Request: T1-AUTH-ROUTES / TCR-T1-ROUTE-CARRIER

- Acceptance contract: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md version 1
- Decision refs: media.stage1.stable-decisions@2, media.stage1.decision.personal-auth-contract@1
- Invalidation keys: media.stage1.acceptance-harness.v4
- Request status: APPROVED
- Requested by: T1 contract integrator
- Required approver: main-orchestrator
- Affected protected tests: `.codex-work/stage1-t1/backend/tests/test_media_stage1_shared_contract.py` sha256:c1fbb5b6655ff2f4bb6f90152a8ab6705d77f6d2744744014f99e0d9dafa01a8
- Affected requirements: AC-01, AC-05, AC-06, AC-07

## Original rule

共享合同测试要求 OpenAPI `paths` 恰好为 82 个，并要求共享 CSRF 对象恰好包含 `requiredForMutations: true`。该规则来自认证公共路由尚未编入唯一 OpenAPI 承载文件时的候选。

## Proposed rule

把路径断言更新为原有 82 个业务路径加九个认证路径，共 91 个；原 `/session` 键替换为绝对的 `/openclaw/media/api/session`，因此净增九个。要求十个认证/会话路径都以 `servers: [{url: "/"}]` 解析，防止叠加 `/openclaw/media/api`。把 CSRF 断言改为 `requiredForAuthenticatedMutations: true` 和 `requiredForPreAuthenticationEntryOperations: false`，同时保留会话绑定与轮换断言。

## Reason

唯一公开合同已经硬切换到 `/openclaw/auth/*`，且真实 Nginx 不移除该前缀。登录前的注册、验证、登录、找回、重置和飞书扫码不存在可绑定的当前会话，要求其 CSRF 在语义上不可实现。旧测试验证的是已被接受决定替代的接口形态，而不是当前产品规则。

## Impact

只版本化 T1 共享合同的路径数量、绝对服务器解析和 CSRF 语义断言。既有 82 个业务操作的内容、会话安全、租户授权、数据模型和其他 SSOT 节点不失效。T1 候选、跨根门禁和后续 I1/I2 实现需重新绑定新测试哈希。

## Alternatives considered

只把认证路径写入扩展而不注册到 OpenAPI `paths` 会留下不可调用的伪合同；继续使用全 mutation CSRF 会迫使登录前接口伪造会话。删除九个无关业务路径来维持 82 会破坏既有接口。三者都不能保留原规则。

## Approval

- Decision: APPROVED
- Approver: main-orchestrator
- Evidence: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/approvals/main-orchestrator-route-contract-v1.md
- Approved contract version: 1
- Relocked test hash: `.codex-work/stage1-t1/backend/tests/test_media_stage1_shared_contract.py` sha256 `80759c80b90339095a255c5c1d6a831e4fbcd74e3e598fcd7a1ec8fe57d64e8d`
- I2 protected test remains pending under `TCR-I2-PUBLIC-AUTH-ROUTES`; this request alone does not lock the full T1 contract baseline.
