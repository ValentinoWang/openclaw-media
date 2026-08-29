# Acceptance Run: 20260817T030000Z-local-rebound-c3d4e5

- Run ID: 20260817T030000Z-local-rebound-c3d4e5
- Task ID: T1-AUTH-ROUTES
- Lane: machine/integration-contract
- Status: PASS
- Acceptance contract: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: d36aadb598a3e6480097e4a9d1ec4bd466d39d409f8950d64ac01480e89c9765
- Source identity: stage1-v4-current-20260817-rebound
- Runtime identity: openclaw-stage1-local-20260817
- Executor or reviewer: main-orchestrator
- Started at: 2026-08-16T18:04:06Z
- Completed at: 2026-08-16T18:06:30Z
- Evidence directory: evidence/

## Scope

本次运行在重新绑定当前 SSOT manifest 后，重新验证 T1-AUTH-ROUTES 合同：T1 共享合同、I2 生命周期保护测试、三根路由一致性和当前源码哈希。它取代运行 `20260817T020000Z-local-current-a1b2c3` 的旧 manifest 绑定，但保留旧运行作为历史证据。执行仅使用本机确定性测试，不调用网络、邮件、飞书、生产数据库或部署环境。

## Procedure

```text
bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/I2.sh > evidence/i2.log 2>&1
bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/T1.sh > evidence/t1.log 2>&1
python3 .codex-work/stage1-t1/backend/tests/check_stage1_auth_route_alignment.py --t1-root .codex-work/stage1-t1 --i1-root .codex-work/stage1-i1 --i2-root .codex-work/stage1-i2 > evidence/route-alignment.log 2>&1
```

原始输出保存在 `evidence/`；未修改保护测试或产品源码。`evidence/source-hashes.txt` 绑定当前 I2 测试与实现源码身份。

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

None. The prior run remains archived as historical evidence; this run is the current manifest-bound result.

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/i2.log | 9f38edcfda474306d086364c029ed04384fe8bc0a6ee417b44ea0e73bbb3468f | `20 passed, 16 skipped` |
| evidence/t1.log | 0d565b04f46d9474ad126c31a9f862cb0011ae5bdee4479fc49dffcc278107c0 | `15 passed` |
| evidence/route-alignment.log | 42e16ffcfd68ead3191978822eab01dbcb3ee790af2992eb6335a0f14352f77d | `STAGE1_AUTH_ROUTE_ALIGNMENT=GREEN` |
| evidence/source-hashes.txt | 3a998f0c6e6df499634dc69cead3dce9ae93fe1334da1b34df59500bee130640 | Protected tests and I2 implementation source identity. |

## Unverified items

不证明真实邮件、真实飞书授权、PostgreSQL 16 迁移回读、部署、生产、浏览器、设备、人工验收或任何节点的最终 `ACCEPTED` 状态。

## Conclusion

结论：当前 manifest 绑定的 T1-AUTH-ROUTES 自动保护基线已锁定，I2 与 T1 本地保护套件通过，跨根门禁为 GREEN。本运行只把合同基线推进到可消费状态，不接受 IL1、I3、发布或生产。
