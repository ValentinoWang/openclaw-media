# Acceptance Contract: T1-AUTH-ROUTES

- Task ID: T1-AUTH-ROUTES
- Contract version: 1
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: main-orchestrator
- Approval evidence: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/approvals/main-orchestrator-route-contract-v1.md
- Request source: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/ssot-development-paths.md
- SSOT node: T1
- SSOT path: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.stage1.stable-decisions@2, media.stage1.decision.personal-auth-contract@1
- Assumption IDs: none
- Invalidation keys: media.stage1.acceptance-harness.v4
- Baseline identity: SSOT manifest sha256:54aecfee53d8bb462156866305a0ac870a224b973e64d12fffdfb6d16e359624
- Human acceptance workspace: acceptance/human/T1-AUTH-ROUTES

## User and scenario

个人创作者通过平台账号完成注册、邮箱验证、登录、找回、重置和退出；组织成员从同一入口使用飞书扫码登录。浏览器、反向代理和服务端必须使用同一组公开地址。

## Problem

旧 T1 候选、I1 前端和 I2 服务端分别声明了 `/identity/*`、`/openclaw/auth/*` 和 `/auth/*` 三套路由。真实 Nginx 不会移除 `/openclaw/auth/` 前缀，继续保留这些漂移会造成请求 404、错误字段不一致、组织扫码处理器冲突和兼容别名长期存在。

## Expected outcome

唯一公共合同是十个冻结操作：六个个人认证 POST、一个 Media 会话 GET、一个退出 POST、两个飞书扫码 POST。旧候选路径和 `/auth/*` 个人生命周期别名不可达；前端字段、服务端分派、错误码和 CSRF 边界均与同一合同一致。

## Non-goals

- 不实现真实邮件发送、真实飞书授权、生产发布或设备验收。
- 不实现平台账号与飞书身份显式关联；该能力仍由 `IL1` 拥有。
- 不恢复旧 Media 密码登录或改密接口。
- 不把 `GET /openclaw/media/api/session` 的业务会话汇合提前归到 T1；其最终运行实现仍由 `I3` 拥有。

## Normal path

```gherkin
Given T1、I1 和 I2 分别位于冻结的隔离根
When 跨根认证路由门禁以正常模式执行
Then 三个根只声明同一组十个公共操作
And 登录请求使用 identifier
And 重置请求使用 newPassword
And 所有公开错误码使用小写蛇形命名
And 门禁输出 STAGE1_AUTH_ROUTE_ALIGNMENT=GREEN
```

## Exception paths

- T1 自身缺少路径、存在重复承载、服务器前缀解析错误或错误码不闭合时，预期红模式也必须失败。
- I1 或 I2 尚未实现时，`--expect-red` 只有在 T1 内部为绿且至少存在一个实现漂移时才成功。
- 注册、验证、重发、登录、找回、重置和飞书扫码入口均为登录前操作，不要求会话 CSRF；退出必须要求当前会话绑定的 CSRF。
- 重发验证和请求找回的公开响应不得因账号存在性或邮件适配器结果而不同。
- 旧 `/identity/*`、`/session/logout`、`/organization/feishu/*` 和 Stage 1 `/auth/*` 别名出现时必须失败关闭。

## Invariants

- 唯一 OpenAPI 承载文件是 `backend/openclaw_app/contracts/media_web_business_pages.openapi.yaml`。
- 公共路径只能是 `/openclaw/auth/*` 和 `/openclaw/media/api/session` 的冻结集合。
- 平台个人认证不得调用飞书；飞书扫码不得注册或找回平台账号。
- 平台账号和飞书成员不得按邮箱或姓名自动合并。
- 注册、邮箱验证和密码重置成功都不得自动登录。
- 会话保持八小时、不透明、服务端绑定；登录成功轮换会话，重置撤销全部旧会话。
- 受保护测试只有在独立测试变更获批并重新锁定后才能由实现角色消费。

## Data impact

T1 只冻结接口与测试合同，不创建或迁移产品数据。I2 后续实现仍必须保持令牌摘要、单次使用、最新链接有效、会话撤销和邮件失败的持久化可观测边界。

## Permissions

未登录用户可调用注册、验证、重发、登录、找回、重置和飞书扫码入口。只有持有当前有效会话与匹配 CSRF 的用户可退出。T1 不授予租户、组织或后台权限。

## Performance and reliability

门禁必须是离线、确定性、无网络的结构化检查。它不得读取生产凭据或调用邮件、飞书和真实数据库。外部适配器失败的运行时可靠性由 I2 独立验收基线覆盖。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | T1 OpenAPI 与 JSON 候选逐项声明十个规范方法和公共路径，且每个绝对路径从 `/` 解析 | Contract | Automatic | Yes |
| AC-02 | T1 不暴露旧 `/identity/*`、`/session/logout`、`/organization/feishu/*` 或 Stage 1 `/auth/*` 别名 | Static | Automatic | Yes |
| AC-03 | I1 的端点、`identifier`、`newPassword` 和小写蛇形错误码与合同一致 | Static | Automatic | Yes |
| AC-04 | I2 的 GET/POST 分派、个人请求字段和飞书扫码处理器与合同一致，且别名不可达 | Static | Automatic | Yes |
| AC-05 | 登录前入口不要求 CSRF，退出要求当前会话绑定的 CSRF | Contract | Automatic | Yes |
| AC-06 | `--expect-red` 仅在 T1 内部为绿且 I1/I2 仍有漂移时返回成功；正常模式仅在三根一致时返回成功 | Integration | Automatic | Yes |
| AC-07 | 令牌、会话、枚举安全、限流和旧密码接口 404 的既有安全断言保持闭合 | Fixture | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 个人用户能理解登录、验证和找回流程，不会误以为成功后已经自动登录 | acceptance/human/T1-AUTH-ROUTES/checklist.md#h-01 | Product owner | Yes |
| H-02 | 组织用户能识别飞书扫码的等待、成功、过期和失败状态 | acceptance/human/T1-AUTH-ROUTES/checklist.md#h-02 | Product owner | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| `.codex-work/stage1-t1/backend/tests/test_media_stage1_shared_contract.py` | 80759c80b90339095a255c5c1d6a831e4fbcd74e3e598fcd7a1ec8fe57d64e8d | T1 OpenAPI carrier, ten public operations, root server resolution, forbidden OpenAPI aliases, and authenticated/pre-authentication CSRF boundary |
| `.codex-work/stage1-i2/backend/tests/test_stage1_personal_auth_lifecycle.py` | d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d | I2 public dispatcher, fields, Feishu scan, alias denial, and mail-failure enumeration boundary; locked after current-source green run |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01, AC-02, AC-05, AC-07 | T1 harness | `.codex-work/stage1-t1/backend/tests/test_stage1_acceptance_harness.py` | Automatic | Yes |
| AC-03, AC-04, AC-06 | Cross-root gate | `.codex-work/stage1-t1/backend/tests/check_stage1_auth_route_alignment.py` | Automatic | Yes |
| H-01 | Scripted product review | acceptance/human/T1-AUTH-ROUTES/checklist.md#h-01 | Human | Yes |
| H-02 | Scripted product review | acceptance/human/T1-AUTH-ROUTES/checklist.md#h-02 | Human | Yes |

## Exploratory testing

检查刷新、重复提交、过期链接、扫码轮询中断、同一浏览器在个人和组织入口之间切换，以及旧书签或旧请求重放时的失败表现。探索结果不能覆盖确定性门禁。

## Production monitoring and rollback

T1 不执行生产变更。后续发布必须监控各规范路由的 404/401/403/429/5xx、邮件 outbox 失败和飞书扫码失败率；异常时使用全局紧急停止或外部写入停止，不恢复长期兼容别名。

## Risks and open decisions

- `backend/tests/test_media_stage1_shared_contract.py` 已经由独立测试变更 lane 重锁为 sha256 `80759c80b90339095a255c5c1d6a831e4fbcd74e3e598fcd7a1ec8fe57d64e8d`；I2 生命周期测试现已绑定 sha256 `d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d`。
- 历史 I2 预实现锁定 lane 因其冻结的旧 manifest 哈希与当前第 4 版 SSOT 不一致而停止；本次绿色基线运行重新验证了相同合同下的当前实现，不复用该失败状态，也不删除历史记录。
- T1 不证明邮件适配器失败时的枚举安全；该项由 I2 专门失败注入测试证明。
