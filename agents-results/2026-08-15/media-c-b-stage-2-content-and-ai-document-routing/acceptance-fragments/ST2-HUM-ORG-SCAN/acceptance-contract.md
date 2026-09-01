# Acceptance Contract: ST2-HUM-ORG-SCAN

- Task ID: ST2-HUM-ORG-SCAN
- Contract version: 1
- Contract status: DRAFT
- Test baseline: PLANNED
- Acceptance owner: runtime acceptance owner
- Approval evidence: 本轮用户指令仅授权建立可审计草案，未批准执行、发布或节点接受。
- Request source: 2026-09-01 用户对第二阶段 40 验收视图与人工验收工作区的明确指令
- SSOT node: O1
- SSOT path: agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.stage2.product-decisions@5
- Assumption IDs: none
- Invalidation keys: media.stage2.organization-source-scope.v5, media.stage2.organization-source-scope.manual-org-scan
- Baseline identity: ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5; docs/frontend/prototype/stage2-acceptance-execution.html
- Human acceptance workspace: acceptance/human/2026-W36/2026-09-01-ST2-HUM-ORG-SCAN
- UI Change declaration: none

## User and scenario

真实组织成员从受支持的媒体登录入口扫码进入组织工作区，并验证组织会话不会被错误地导向个人工作区。

## Problem

本地 fixture、接口测试和截图无法证明真实组织账号、活跃 Binding 与浏览器会话在部署环境中共同生效。

## Expected outcome

组织成员扫码后进入组织壳层；错误输入个人工作区深链时，产品保留组织身份而不泄漏个人云端成果。

## Non-goals

不替代路由、权限、会话字段或接口错误码的自动化测试；不执行生产写入、重启、迁移或账户配置变更。

## Normal path

```gherkin
Given 真实组织成员有可用的飞书登录身份和活跃 Binding
When 成员从媒体登录页选择组织成员并完成扫码
Then 产品在入口状态查询结束后显示组织工作区，并保持组织壳层
```

## Exception paths

当成员手动访问个人工作区深链时，产品必须给出与组织身份一致的恢复结果；任何静默落入个人成果页都是拒绝签署的发现。

## Invariants

组织身份、Binding 和正文权威只能由服务端会话投影；人工步骤不接受通过修改 URL、前端 mock 或临时授权绕过来证明成功。

## Data impact

只读验证登录、路由和会话投影。不得创建或修改正文、Binding、飞书文档、数据库记录或用户资料。

## Permissions

验收人必须使用真实组织成员身份；不需要管理员权限，也不得借用个人创作者身份替代。

## Performance and reliability

验收以入口状态完成和扫码回跳为准；网络或第三方认证失败必须被如实记录为阻塞，不能用 mock 重试覆盖。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 入口状态、路由矩阵和服务端权限语义继续由既有自动化门禁覆盖。 | Static and contract | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 真实组织成员能完成扫码进入，并确认组织壳层和错误深链恢复可理解且不泄漏个人成果。 | acceptance/human/2026-W36/2026-09-01-ST2-HUM-ORG-SCAN/checklist.md#h-01 | 组织成员验收负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| none | none | Test baseline is PLANNED; this fragment does not lock an executable test. |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 既有路由与入口状态合同门禁 | 40 验收视图的自动化映射 | Automatic | Yes |
| H-01 | 真实组织扫码闭环 | acceptance/human/2026-W36/2026-09-01-ST2-HUM-ORG-SCAN/checklist.md#h-01 | Human | Yes |

## Exploratory testing

记录扫码取消、已过期会话和错误深链恢复是否能被组织成员理解，但不把这些探索替代确定性路由测试。

## Production monitoring and rollback

本项不改变运行时；发现错误进入个人成果页时，停止签署并回报 O1，恢复由受控发布流程决定。

## Risks and open decisions

当前页面可能仍有 `workspaceIntent` 默认值导致错误深链恢复不符合预期。该发现是阻塞性人类观察，不改变 O1 的 SSOT 状态。
