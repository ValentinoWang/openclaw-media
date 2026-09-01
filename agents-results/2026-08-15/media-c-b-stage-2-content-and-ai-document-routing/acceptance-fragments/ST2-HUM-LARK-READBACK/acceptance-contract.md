# Acceptance Contract: ST2-HUM-LARK-READBACK

- Task ID: ST2-HUM-LARK-READBACK
- Contract version: 2
- Contract status: DRAFT
- Test baseline: PLANNED
- Acceptance owner: runtime acceptance owner
- Approval evidence: 本轮用户指令批准 L2 治理修订，但未批准执行人工验收、发布或节点接受。
- Request source: 2026-09-01 用户对第二阶段 40 验收视图与人工验收工作区的明确指令
- SSOT node: O5
- SSOT path: agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.stage2.product-decisions@5
- Assumption IDs: none
- Invalidation keys: consumer.organization-edit-readback.lark-document, consumer.organization-edit-readback.remote-version, file-summary.acceptance.lark-readback
- Baseline identity: ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5; docs/frontend/prototype/stage2-acceptance-execution.html
- Human acceptance workspace: acceptance/human/2026-W36/2026-09-01-ST2-HUM-LARK-READBACK
- UI Change declaration: none

## User and scenario

真实组织成员在飞书编辑已有 Docx 正文后，回到 Web 的组织只读镜像确认远端版本、修改时间和只读边界。

## Problem

注入式 Lark writer、mock 和本地浏览器不能证明真实远端版本的写后回读，因此不能替代 O5 外部系统验收。

## Expected outcome

真实飞书保存后，Web 镜像显示新的远端版本和更新时间，且 Web 侧没有绕过飞书权威的编辑入口。

## Non-goals

不以人工操作替代幂等、批次、错误码、映射或服务端授权的机器测试；不新增飞书文档、绑定或权限。

## Normal path

```gherkin
Given 组织成员已通过真实组织登录并可编辑现有飞书 Docx
When 成员在飞书修改正文并保存后刷新 Web 组织镜像
Then 镜像读回新的远端版本和修改时间，并保持只读
```

## Exception paths

飞书保存失败、读回超时、版本不变或 Web 出现编辑入口时，验收人记录阻塞性结果，不以本地 mock 或手改页面状态代替。

## Invariants

飞书是组织正文唯一编辑权威；成功必须包含外部写入、成果登记和读回，不得以单一写入响应代替。

## Data impact

验收人只修改指定的真实测试 Docx 正文。除该受控文档外不得修改 Binding、租户资料或生产配置。

## Permissions

验收人需要受控真实组织成员权限与该 Docx 编辑权限；Web 侧仅以组织成员身份访问。

## Performance and reliability

读回结果需来自同一受控文档和本次保存后的远端版本；延迟或失败必须记录时间和可见提示，不能以刷新偶然成功掩盖。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 文档绑定、保存、批次和读回合同继续由自动化与集成证据分别覆盖。 | Integration and contract | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 真实飞书编辑后的 Web 镜像读回具备可理解的版本更新和只读边界。 | acceptance/human/2026-W36/2026-09-01-ST2-HUM-LARK-READBACK/checklist.md#h-01 | 组织成员验收负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| none | none | Test baseline is PLANNED; this fragment does not lock an executable test. |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 既有保存、批次和读回合同测试 | 40 验收视图的自动化映射 | Automatic | Yes |
| H-01 | 真实飞书编辑和 Web 读回闭环 | acceptance/human/2026-W36/2026-09-01-ST2-HUM-LARK-READBACK/checklist.md#h-01 | Human | Yes |

## Exploratory testing

在不改变受控文档范围的前提下，观察刷新、延迟和远端冲突提示的可理解性。

## Production monitoring and rollback

本项不部署或回滚系统。发现读回不一致时保留页面和飞书版本证据，阻止 O5 签署并交由运行时验收负责人处置。

## Risks and open decisions

真实租户、组织成员和飞书连接是外部前置条件；缺任一条件时结果为 BLOCKED，不转述为通过。
