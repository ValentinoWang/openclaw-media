# Acceptance Contract: ST2-HUM-SESSION-28D

- Task ID: ST2-HUM-SESSION-28D
- Contract version: 1
- Contract status: DRAFT
- Test baseline: PLANNED
- Acceptance owner: runtime acceptance owner
- Approval evidence: 本轮用户指令仅授权建立可审计草案，未批准执行、发布或节点接受。
- Request source: 2026-09-01 用户对第二阶段 40 验收视图与人工验收工作区的明确指令
- SSOT node: DB
- SSOT path: agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.stage2.product-decisions@4
- Assumption IDs: none
- Invalidation keys: media.stage2.external-system-acceptance.v5, media.stage2.external-system-acceptance.session-28d-readback
- Baseline identity: ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5; docs/frontend/prototype/stage2-acceptance-execution.html
- Human acceptance workspace: acceptance/human/ST2-HUM-SESSION-28D

## User and scenario

真实个人账号在受支持浏览器中登录后关闭浏览器，并在真实时间推进后重新打开产品，验证部署会话持续性。

## Problem

配置和回归测试只能证明 28 天值被设置，不能证明浏览器持久化、Cookie 和部署端 session 记录在真实环境共同保持。

## Expected outcome

次日重开浏览器并访问概览页时，用户无需再次登录；会话记录与 Cookie 的有效期均可由授权运行时读回确认。

## Non-goals

不把本地时间伪造、Cookie 编辑或测试环境 fixture 当作真实部署读回；不改变会话配置、数据库或账户数据。

## Normal path

```gherkin
Given 真实个人账号在部署环境中完成登录
When 关闭浏览器并在次日以同一浏览器重新访问概览页
Then 产品无需再次登录，并可由授权读回确认 28 天会话持续性
```

## Exception paths

再次登录、Cookie 缺失、服务端记录不一致或无法安全读回时，记录为阻塞；不得通过延长 Cookie、修改数据库或模拟时钟补救。

## Invariants

真实浏览器、真实时钟和部署环境是本项不可替代的证据层；本地测试成功不得升级为 DB 接受。

## Data impact

只使用受控个人测试账号的既有会话。禁止清理、延长或手动编辑会话记录。

## Permissions

验收人需要受控个人账号；会话记录读回只能由获授权的运行时验收负责人以脱敏方式完成。

## Performance and reliability

验收至少跨一次真实日期边界；浏览器清理策略、扩展或无痕模式必须记录，避免把环境清理误判为产品会话失败。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 默认值、环境变量回退和有效期上限继续由现有配置与回归测试覆盖。 | Configuration and regression | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 真实部署、真实时钟与真实浏览器会话能够共同证明 28 天持续性。 | acceptance/human/ST2-HUM-SESSION-28D/checklist.md#h-01 | 运行时验收负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| none | none | Test baseline is PLANNED; this fragment does not lock an executable test. |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- |
| AC-01 | 既有会话配置与回归测试 | 40 验收视图的自动化映射 | Automatic | Yes |
| H-01 | 跨日真实部署读回 | acceptance/human/ST2-HUM-SESSION-28D/checklist.md#h-01 | Human | Yes |

## Exploratory testing

记录不同受支持浏览器的会话恢复体验，但每次浏览器、账号和运行时身份必须进入独立 run。

## Production monitoring and rollback

本项不部署或回滚。发现会话丢失或读回不一致时阻止 DB 签署，由运行时验收负责人启动既有排障流程。

## Risks and open decisions

跨天验证尚未执行，真实账户和浏览器数据属于外部前置条件；没有已签署 run 前不得声明通过。
