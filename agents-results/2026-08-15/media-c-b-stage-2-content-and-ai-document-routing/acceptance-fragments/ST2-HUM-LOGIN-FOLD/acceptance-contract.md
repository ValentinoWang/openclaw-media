# Acceptance Contract: ST2-HUM-LOGIN-FOLD

- Task ID: ST2-HUM-LOGIN-FOLD
- Contract version: 1
- Contract status: DRAFT
- Test baseline: PLANNED
- Acceptance owner: product decision authority
- Approval evidence: 本轮用户指令仅授权建立可审计草案，未批准执行、发布或节点接受。
- Request source: 2026-09-01 用户对第二阶段 40 验收视图与人工验收工作区的明确指令
- SSOT node: K
- SSOT path: agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.stage2.product-decisions@5
- Assumption IDs: none
- Invalidation keys: media.stage2.product-decisions.v5, media.stage2.product-decisions.login-fold-assert-auth-layout
- Baseline identity: ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5; docs/frontend/prototype/stage2-acceptance-execution.html
- Human acceptance workspace: acceptance/human/ST2-HUM-LOGIN-FOLD

## User and scenario

个人创作者在 1440x900 浏览器中进入登录回退态，判断主动作是否无需滚动即可理解和使用。

## Problem

验收材料记录 `assertAuthLayout` 只覆盖初始 P1；回退到密码登录的页面曾超过一屏，自动门禁未能覆盖该状态。

## Expected outcome

回退态中登录主动作无需页面滚动即可见；该临时人工项在自动断言扩展并通过后才能退役。

## Non-goals

不以目测替代自动布局、溢出、字体加载或路由断言；不改动登录文案、认证策略或会话时间。

## Normal path

```gherkin
Given 1440x900 的受支持浏览器和个人创作者入口
When 用户选择个人创作者并进入密码登录回退态
Then 不滚动页面即可看到并理解登录主动作
```

## Exception paths

若页面高度超过视口、主动作被遮挡或需滚动才能看到，验收结果为失败；不得用缩放、开发者工具或手改 CSS 规避。

## Invariants

此项只追踪 K 范围内的 `assertAuthLayout` 自动化缺口，不创建新 SSOT 节点，也不改变既有产品决定。

## Data impact

无数据读写。仅观察登录页面布局和导航状态。

## Permissions

验收人只需公开登录入口；不输入真实凭据，不创建会话，不访问个人或组织数据。

## Performance and reliability

浏览器缩放必须为 100%，窗口为 1440x900；网络错误应记录为环境阻塞，不能直接判作布局通过。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 运行时截图、布局和入口状态请求仍由现有自动化门禁覆盖。 | Runtime visual | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 个人创作者能在回退态无需滚动看到登录主动作；在自动化覆盖前保留为临时人工项。 | acceptance/human/ST2-HUM-LOGIN-FOLD/checklist.md#h-01 | 产品体验验收负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| none | none | Test baseline is PLANNED; this fragment does not lock an executable test. |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | qa:media-login-visual-runtime | 40 验收视图的自动化映射 | Automatic | Yes |
| H-01 | 1440x900 回退态人工观察 | acceptance/human/ST2-HUM-LOGIN-FOLD/checklist.md#h-01 | Human | Yes |

## Exploratory testing

观察组织登录回退态是否同样可理解，但该合同只签署个人回退态的已知折线缺口。

## Production monitoring and rollback

本项不修改运行时。失败时阻止该人工项签署并要求先补齐 `assertAuthLayout` 全状态自动断言。

## Risks and open decisions

自动化缺口未关闭前，本项保留；自动门禁扩展通过后应废止本合同并保留历史运行结果不改写。
