# Acceptance Run: 20260817T013500Z-localpg-a1b2c3

- Run ID: 20260817T013500Z-localpg-a1b2c3
- Task ID: T1-AUTH-ROUTES
- Lane: machine/integration-contract
- Status: PARTIAL
- Acceptance contract: agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/acceptance-fragments/T1-AUTH-ROUTES/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: 447b7e4fedceb526f1b7093b4a6177cef6ad5ab460b342b1593634961f882f22
- Source identity: stage1-i2-source-current-20260817
- Runtime identity: openclaw_stage1_i2_verify_20260817
- Executor or reviewer: main orchestrator deterministic local execution
- Started at: 2026-08-16T17:34:07.929570Z
- Completed at: 2026-08-16T18:02:00Z
- Evidence directory: evidence/

## Scope

本次运行只补充 I2 的本地数据库回读证据，不执行发布接受，也不替产品负责人签署 H-01/H-02。环境为本机 PostgreSQL 18.3 的独立数据库 `openclaw_stage1_i2_verify_20260817`；由于受保护迁移运行器要求 PostgreSQL 16，数据库由当前隔离根按相关 canonical 账户迁移片段物化，不能作为正式迁移发布证据。

覆盖范围：个人认证生命周期、注册事务、准入码消费和账户安全回读。排除范围：真实邮件、飞书授权、部署、生产、设备、正式人工验收和节点 `ACCEPTED` 状态。

## Procedure

实际执行命令：

```text
createdb -h /tmp -U postgres openclaw_stage1_i2_verify_20260817
psql ... canonical/003_openclaw_account_billing.sql canonical/004_openclaw_authentication.sql canonical/005_openclaw_registration_affiliate.sql canonical/010_persistent_admission_codes.sql
psql ... canonical/028_tenant_foundation.sql
pytest -q -p no:cacheprovider tests/test_stage1_personal_auth_lifecycle.py tests/test_account_registration.py
pytest -q -p no:cacheprovider tests/test_account_auth.py
```

原始输出见 `evidence/`，未修改受保护测试或产品代码。

## Requirement disposition

| Requirement | Result | Evidence | Notes |
| --- | --- | --- | --- |
| AC-01 | NOT_RUN | evidence/database-schema.txt | 本运行不复核 T1 OpenAPI 十操作集合。 |
| AC-02 | NOT_RUN | evidence/database-schema.txt | 本运行不复核旧路由别名。 |
| AC-03 | PARTIAL | evidence/focused-pytest.log | I2 生命周期与注册路径被执行；旧数据库夹具存在失败，不能作为完整接受证据。 |
| AC-04 | PARTIAL | evidence/focused-pytest.log | I2 服务端行为被执行；完整 PostgreSQL 账户夹具未通过。 |
| AC-05 | NOT_RUN | evidence/database-schema.txt | 本运行不复核 T1 CSRF 路由合同。 |
| AC-06 | NOT_RUN | evidence/database-schema.txt | 未执行三根路由汇合门禁。 |
| AC-07 | PARTIAL | evidence/account-auth-fixture-mismatch.log | 账户安全测试暴露旧夹具与 `tenant_members`/会话状态契约不一致。 |

## Findings

1. 阻塞：完整 `test_account_auth.py` 最新运行 `6 failed, 3 passed`；失败集中在旧夹具没有建立与当前工作区成员契约一致的会话/成员状态，以及错误密码测试的残留会话断言。
2. 阻塞：注册数据库套件在当前物化 schema 上出现 `admin_audit.actor_session_id` 外键夹具不一致。
3. 执行阻塞：受保护迁移运行器拒绝 PostgreSQL 18（要求 PostgreSQL 16），因此本次数据库只属于局部回读实验。

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/focused-pytest.log | `24d90ef73d5ca1d3465599a52626a16a34deea816649d46b65c422f5472a17eb` | I2 生命周期与注册数据库运行输出 |
| evidence/account-auth-fixture-mismatch.log | `25ed9089128f6763ad936bf292975a08c80b1d59ddbe150f573181807d4abc47` | 账户 PostgreSQL 夹具失败输出 |
| evidence/database-schema.txt | `31c0af44d144a4c7971b1cd1c48e421fc97488a2a89e89aba9bf99de108a7f87` | 独立数据库版本和相关表回读 |

## Unverified items

本运行不证明真实数据库迁移、恢复、真实邮件、真实飞书、浏览器、部署、生产、设备、人工验收或任何节点的 `ACCEPTED` 状态。数据库夹具失败不能归因于 I2 业务实现，需单独修订并重新锁定测试基线。

## Conclusion

结论：本地 I2 认证代码仍有可重复的非数据库生命周期证据；数据库回读证据为 `PARTIAL`，并被旧夹具/迁移版本差异阻塞。本运行不解锁 `IL1`、`I3`，不改变 SSOT 节点状态，也不构成正式接受。
