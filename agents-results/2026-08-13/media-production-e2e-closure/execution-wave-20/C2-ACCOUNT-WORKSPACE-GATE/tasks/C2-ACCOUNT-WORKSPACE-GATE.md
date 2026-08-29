# C2 账号与工作区入队门禁实现

## 身份与终点

- 任务编号：`C2-ACCOUNT-WORKSPACE-GATE`
- 直接节点：C2（`media.task-runner-receipt-implementation`）
- 直接父节点：B2（`media.context-task-e2e-contract`）
- 版本元组：计划 5、依赖图 5、接口冻结 5、节点合同 4、SSOT schema 1
- 锁定合同：`MPE2E-TASK-RUN-V3`，SHA-256 `35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b`
- 接受决定：D5 `media.representative-account-binding-input@1`，SHA-256 `c6bd807376561c25820938b1839f50b633a7e2f4911f3460fea9a6f5e1a0e12b`
- 失效键：`contract.context-task-e2e`、`decision.representative-account-binding-input`
- 保护测试：`scripts/acceptance/test-mpe2e-task-run-v3.sh`，SHA-256 `dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d`
- 候选基线：`.codex-work/merge-candidate-v4/backend/.candidate-source.sha256`，清单文件 SHA-256 `c67461000c4dd3cee5f5087d76880a402f2831c20ba365e6c4e719abf3a32b44`，566 个受管文件。
- 目标：在唯一候选后端中完成外部博主/客户自有账号隔离和工作区运行归属门禁；只形成本地候选实现及自动化证据，不部署、不生成生产收据。

## 唯一写入权限

仅允许修改下列范围：

- `.codex-work/merge-candidate-v4/backend/openclaw_app/services/media_web_tasks.py`
- `.codex-work/merge-candidate-v4/backend/openclaw_app/services/media_task_repository.py`
- `.codex-work/merge-candidate-v4/backend/openclaw_app/adapters/http_api.py`
- `.codex-work/merge-candidate-v4/backend/openclaw_app/migrations/canonical/038_*.sql`
- `.codex-work/merge-candidate-v4/backend/openclaw_app/migrations/postgres_manifest.json`
- `.codex-work/merge-candidate-v4/backend/scripts/run_postgres_migrations.py`，仅当关闭迁移清单需要把固定条目数从 32 提升为 33 时可改
- `.codex-work/merge-candidate-v4/backend/tests/test_media_web_tasks.py`
- `.codex-work/merge-candidate-v4/backend/tests/test_media_web_tasks_postgres.py`
- `.codex-work/merge-candidate-v4/backend/tests/test_media_task_repository_postgres.py`
- `.codex-work/merge-candidate-v4/backend/tests/test_media_task_v3_contract.py`
- `.codex-work/merge-candidate-v4/backend/tests/test_http_api.py`
- `.codex-work/merge-candidate-v4/backend/tests/test_media_business_http.py`
- `.codex-work/merge-candidate-v4/backend/tests/test_postgres_migration_runner.py`
- supervisor 指定的 `STRUCTURED_RETURN_PATH`

除上述路径外全部只读。特别禁止修改 SSOT、节点、边、合同、保护测试、人工清单、前端、`.candidate-source.sha256`、顶层候选 manifest、历史迁移、远程源码、生产数据库、飞书对象、服务配置和发布目录。不得提交、推送、部署、重启、连接 `106.52.146.37`、创建生产任务或调用其他执行者。

## 必须保持的业务不变量

1. `media_product.creator_profiles` 只表示外部博主研究对象，不能提供可运营资格，不能被账号关系解析或任务入队查询使用。
2. 可运营账号只能来自 `media_product.owned_media_accounts`，且数据库必须有明确、可验证的 `customer_owned` 类别或等价正式来源约束。新增规范迁移，不能改写历史迁移。
3. 代表能力必须按固定四元组 `[tenantPublicId, userPublicId, normalizedPlatform, normalizedAccount]` 命中唯一、活动、正式关系。不能按显示名称、作者编号或外部博主同名记录自动认领。
4. 缺失、不可见、跨租户、跨用户返回 `account_relationship_unavailable`/404；关系冲突返回 `account_relationship_conflict`/409；输入缺失保持 `required_input_missing`/422。
5. 会话必须向任务服务明确传入当前租户、认证用户、账号角色和 `workspace_mode`。两条 HTTP 创建路径都必须传入，客户端正文不能覆盖。
6. 只允许 `personal_web` 与 `organization_lark`；二者都是合法产品模式。会话工作区必须与数据库租户工作区一致，角色必须与活动用户/成员关系一致。缺失、非法、错配或非活动上下文稳定返回 `workspace_not_allowed`/403，不泄露目标对象是否存在。
7. 工作区/角色拒绝必须适用于所有任务创建能力，而不仅是两项代表能力；账号正式关系要求仍只收紧两项代表能力。
8. 幂等读回不能绕过当前会话工作区门禁。授权检查必须发生在返回既有任务之前。
9. 最终任务插入必须在同一数据库事务内复核租户工作区、活动用户/成员、角色、正式客户账号类别和活动绑定，关闭“先解析后撤销再入队”的竞态。拒绝时 `media_web_tasks`、事件、尝试、租约和产物均为零。
10. `authorization_projection` 只保存脱敏的角色和工作区，不保存凭据；账号绑定继续保存正式关系引用，不保存外部博主研究正文。

## 推荐实现边界

- 在 `MediaWebTaskService.create_task()` 的集中边界增加必填的 `workspace_mode` 与 `role`，先调用仓库的会话/租户上下文授权，再做幂等读回和入队。
- 仓库可以新增单一的 `authorize_task_context()`，查询租户、用户和成员关系；稳定失败为 `workspace_not_allowed`。
- `resolve_owned_account()` 只查询正式客户自有账号表和正式绑定表；不得出现 `creator_profiles`。
- `create_task()` 事务内根据 invocation/authorization 中的冻结绑定再次锁定并复核正式关系，再插入任务。不要用名称模糊匹配、回退查询或客户端声明替代关系记录。
- 新增 `038` 规范迁移，为 `owned_media_accounts` 增加显式客户自有类别约束，并更新关闭迁移 manifest、校验器和测试。迁移必须可在空库 apply/verify，也必须能为已有行安全回填。

## 实现自有测试

至少增加并通过以下行为测试：

- 仅存在同平台同名称的 `creator_profiles` 时，代表任务仍返回关系不可用，且零任务行。
- 客户自有账号类别不是 `customer_owned` 时不能建立或满足正式关系；数据库约束失败关闭。
- 当前用户、租户、平台、规范化账号唯一命中时可创建；跨租户、跨用户、禁用成员、禁用绑定、重复/冲突关系均失败关闭。
- `personal_web` 会话只进入对应 `personal_web` 租户；`organization_lark` 会话只进入对应 `organization_lark` 租户。两种合法路径均有正向测试。
- 会话工作区缺失、非法或与租户错配返回 `workspace_not_allowed`/403，且 `repository.create_task()` 未调用、数据库任务行数为零。
- 会话角色缺失、非法或与数据库用户角色不一致返回相同 403。
- 两条 HTTP 创建路径都从已认证会话传入 `workspace_mode` 和 `role`，错误码稳定映射为 403。
- 幂等重复请求在工作区被改成错配后不能读回旧任务。
- 关系在解析后、插入前被禁用时，事务复核拒绝入队。
- 账号查询源码与 SQL 不引用 `creator_profiles`，不按展示名跨表认领。

## 固定验证

只使用 supervisor 冻结的验证脚本：

```bash
bash agents-results/2026-08-13/media-production-e2e-closure/execution-wave-20/C2-ACCOUNT-WORKSPACE-GATE/validation/C2-ACCOUNT-WORKSPACE-GATE.sh
```

验证使用本机临时虚拟环境和一次性 PostgreSQL 16 容器。不得连接任何已有数据库。缺少真实生产收据的保护测试必须继续以退出码 3 红灯；不得伪造收据使其变绿。

## 停止条件与结构化返回

固定验证全部通过时返回 `proposed_state: IMPLEMENTED`、`acceptance_self_check: pass`、`failure_class: none`。这不是生产验收或发布接受。若验证未通过，如实返回 `FAILED` 或 `IMPLEMENTED` 加未通过项。若合同、决定、写入范围或架构发生冲突，立即停止并返回相应 closed-enum `failure_class`，不得扩大范围。

结构化 JSON 必须包含：任务编号、版本元组、合同/决定/保护测试哈希、wrapper 与 attempt role、实际读写路径、变更文件、新迁移身份、工作区门禁路径、正式账号类别与关系复核路径、所有验证命令及退出码、保护测试最终哈希、未验证事项、偏差级别、`proposed_state`、`failure_class` 和 `acceptance_self_check`。
