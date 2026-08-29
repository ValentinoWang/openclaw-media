# Acceptance Run: 20260817T031500Z-local-final-f4a5b6

- Run ID: 20260817T031500Z-local-final-f4a5b6
- Task ID: T1-AUTH-ROUTES
- Lane: machine/integration-contract
- Status: PASS
- Acceptance contract: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: e9ddd43a95249bf996cb9833b44cf436b745b81886f0020d7856bb45bc6e325b
- Source identity: stage1-v4-current-20260817-final
- Runtime identity: openclaw-stage1-local-20260817
- Executor or reviewer: main-orchestrator
- Started at: 2026-08-16T18:10:00Z
- Completed at: 2026-08-16T18:14:57Z
- Evidence directory: evidence/

## Scope

本次运行在最终 SSOT manifest 绑定后，验证 T1-AUTH-ROUTES 合同：T1 共享合同、I2 生命周期保护测试、三根路由一致性和当前源码哈希。它取代旧 manifest 绑定运行 `20260817T020000Z-local-current-a1b2c3` 与 `20260817T030000Z-local-rebound-c3d4e5`，但保留两者作为历史证据。执行仅使用本机确定性测试，不调用网络、邮件、飞书、生产数据库或部署环境。

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

None. Earlier runs remain archived as historical evidence; this run is the final manifest-bound result for the current contract.

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/i2.log | 2ac136213d1d621257adec5cdc9d38eaae0ca1548c972234752537da4687b0c4 | `20 passed, 16 skipped` |
| evidence/t1.log | 3948bc7fe891cdf9af6a4eac0e326916424e3ebf76f4b3251036ad81e933d2f1 | `15 passed` |
| evidence/route-alignment.log | 42e16ffcfd68ead3191978822eab01dbcb3ee790af2992eb6335a0f14352f77d | `STAGE1_AUTH_ROUTE_ALIGNMENT=GREEN` |
| evidence/source-hashes.txt | 3a998f0c6e6df499634dc69cead3dce9ae93fe1334da1b34df59500bee130640 | Protected tests and I2 implementation source identity. |

## Unverified items

不证明真实邮件、真实飞书授权、PostgreSQL 16 迁移回读、部署、生产、浏览器、设备、人工验收或任何节点的最终 `ACCEPTED` 状态。

## Conclusion

结论：最终 manifest 绑定的 T1-AUTH-ROUTES 自动保护基线已锁定，I2 与 T1 本地保护套件通过，跨根门禁为 GREEN。本运行只把合同基线推进到可消费状态，不接受 IL1、I3、发布或生产。
