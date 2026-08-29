# Acceptance Run: 20260817T020000Z-local-current-a1b2c3

- Run ID: 20260817T020000Z-local-current-a1b2c3
- Task ID: T1-AUTH-ROUTES
- Lane: machine/integration-contract
- Status: PASS
- Acceptance contract: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: 2dc82a42e5f17b744bf9a34edb6a5c720393dbf7df5e5cf90b085c2c324c42d9
- Source identity: stage1-v4-current-20260817
- Runtime identity: openclaw-stage1-local-20260817
- Executor or reviewer: main-orchestrator
- Started at: 2026-08-16T17:53:40.002081Z
- Completed at: 2026-08-16T18:00:11Z
- Evidence directory: evidence/

## Scope

本次运行验证当前第 4 版隔离源码对 T1-AUTH-ROUTES 的合同闭合：T1 共享合同、I2 生命周期保护测试、三根路由一致性和既有源码哈希。执行仅使用本机确定性测试，不调用网络、邮件、飞书、生产数据库或部署环境。

## Procedure

```text
bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/I2.sh
bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/T1.sh
python3 .codex-work/stage1-t1/backend/tests/check_stage1_auth_route_alignment.py --t1-root .codex-work/stage1-t1 --i1-root .codex-work/stage1-i1 --i2-root .codex-work/stage1-i2
shasum -a 256 <protected tests and I2 implementation sources>
```
原始输出保存在 `evidence/`，没有修改保护测试或产品源码。

## Requirement disposition

| Requirement | Result | Evidence | Notes |
| --- | --- | --- | --- |
| AC-01 | PASS | evidence/t1.log | T1 protected suite passed. |
| AC-02 | PASS | evidence/route-alignment.log | Current public route set is aligned and legacy aliases are denied. |
| AC-03 | PASS | evidence/route-alignment.log | I1 fields and error vocabulary align with the frozen contract. |
| AC-04 | PASS | evidence/route-alignment.log, evidence/i2.log | I2 dispatcher, Feishu scan boundary, aliases, and mail-failure tests passed. |
| AC-05 | PASS | evidence/t1.log | Pre-authentication CSRF exception and logout CSRF boundary passed. |
| AC-06 | PASS | evidence/route-alignment.log | `STAGE1_AUTH_ROUTE_ALIGNMENT=GREEN`. |
| AC-07 | PASS | evidence/i2.log, evidence/t1.log | Token, session, enumeration, rate-limit, and legacy 404 assertions passed. |

## Findings

None. The historical expected-red lock attempt remains archived separately and is not reused as current evidence because its frozen manifest hash predates the current SSOT v4 rebuild.

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/i2.log | 2de8bd0de808e6350d58b8a9d7f3c70489818eb6f32311e3e3e4052ccf1ca402 | `20 passed, 16 skipped` |
| evidence/t1.log | 0d565b04f46d9474ad126c31a9f862cb0011ae5bdee4479fc49dffcc278107c0 | `15 passed` |
| evidence/route-alignment.log | 42e16ffcfd68ead3191978822eab01dbcb3ee790af2992eb6335a0f14352f77d | `STAGE1_AUTH_ROUTE_ALIGNMENT=GREEN` |
| evidence/source-hashes.txt | 3a998f0c6e6df499634dc69cead3dce9ae93fe1334da1b34df59500bee130640 | Protected tests and I2 implementation source identity. |

## Unverified items

不证明真实邮件、真实飞书授权、PostgreSQL 16 迁移回读、部署、生产、浏览器、设备、人工验收或任何节点的最终 `ACCEPTED` 状态。

## Conclusion

结论：T1-AUTH-ROUTES 的自动保护基线已锁定，当前 I1/I2/T1 源码与十个公共操作合同一致；I2 与 T1 本地保护套件通过，跨根门禁为 GREEN。本运行只把合同基线推进到可消费状态，不接受 IL1、I3、发布或生产。
