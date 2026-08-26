# 人工验收清单：PR-REL-PLANNER v2

- 任务编号：PR-REL-PLANNER
- 合同：`docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance-contract-v2.md`
- 合同版本：2
- 清单状态：已批准
- 保护测试：`openclaw-tag-router/tests/test_production_reconciliation_planner.py`
- 保护测试 SHA-256：`b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898`
- 所需人工角色：Production Reconciliation owner

本清单只验收 v2 对 v1 排序冲突的治理修正，不批准部署或生产切流。

## H-01｜职责边界

确认能够清楚说明：

- `production_reconciliation_planner` 只做纯内存、source-only 计划；
- planner 本地夹具的文件列表顺序不是 planner 的验收条件；
- 真正 release manifest 的排序由 `production_release_manifest.build_manifest` / `validate_manifest` 负责；
- planner PASS 不等于 manifest PASS、deploy PASS 或 production acceptance。

通过条件：不会再把 planner 的非字典序测试夹具解释为可直接部署的 manifest，也不会在 planner 中复制 manifest validator 的全部规则。

## H-02｜单实现边界

确认仓库中：

- 只有 `openclaw_app/services/production_reconciliation_planner.py` 是 planner 实现；
- 不存在 `production_reconciliation_planner_legacy.py`；
- 不存在通过 facade、动态 `globals()`、monkey patch 或第二套 planner 实现来维持兼容的结构。

通过条件：维护者只需要修改和审计一个 planner 实现文件。

## H-03｜发布边界

确认真正候选在进入部署前仍必须独立通过：

1. clean full Git SHA；
2. immutable release manifest build + validate；
3. 保护 planner tests；
4. 完整 Router tests；
5. Stage-2 hardening tests；
6. branch convergence；
7. dependency/Binding/Feishu preflight；
8. rollback target validation。

通过条件：任何 source-only PASS 都不得提升 Stage-2 SSOT，也不得触发服务器 `git pull`、active release 覆盖或 systemd restart。
