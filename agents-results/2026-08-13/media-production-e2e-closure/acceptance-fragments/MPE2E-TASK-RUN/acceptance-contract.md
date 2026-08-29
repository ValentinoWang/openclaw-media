# Acceptance Contract: MPE2E-TASK-RUN

- Task ID: MPE2E-TASK-RUN
- Contract version: 2
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: 产品负责人和运行验收负责人
- Approval evidence: 用户于 2026-08-13 采纳 OP02 第 2 版推荐方案；D4 v2 机器记录为 `decision_state: ACCEPTED`、`decision_version: 2`，批准只读咨询 `selfmedia_creation_consultation` 和写入创作 `selfmedia_creation`。
- Request source: OP02 第 2 版已接受决定及 B2 `media.context-task-e2e-contract` 验收设计节点
- SSOT node: B2
- SSOT path: agents-results/2026-08-13/media-production-e2e-closure/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.no-inference-completion-boundary@1, media.same-receipt-proof@1, media.release-capability-samples@2
- Assumption IDs: none
- Invalidation keys: contract.context-task-e2e, decision.release-capability-samples
- Baseline identity: D4 v2 SHA-256 `8879cea622a6be53484b6d6b85ed96f10db86b5a8c70b903360735408021f580`; B2 SHA-256 `79847d2c006515237e4561df86e507444a510e961ebdff5dd504bfeaf979c708`; B3 schema `media_e2e_receipt_v1`; protected test `scripts/acceptance/test-mpe2e-task-run.sh`
- Human acceptance workspace: acceptance/human/MPE2E-TASK-RUN

## User and scenario

已认证普通用户从真实素材上下文分别发起一个创作咨询任务和一个自媒体创作任务，并等待各自独立账号聚合执行器产生终态结果。创作咨询（`selfmedia_creation_consultation`）代表只读咨询链：可以产生结构化咨询产物和数据库任务记录，但不得新建飞书对象，且外部写入集合必须为空。自媒体创作（`selfmedia_creation`）代表数据库与飞书写入链：必须产生本次任务的飞书创作对象并由声明身份读回。运行验收只使用脱敏稳定引用和摘要，不能保存凭据、Cookie、令牌、密码或私人正文。

## Problem

现有入口证据只能证明能力能够正确打开并带入上下文，不能证明后续真实任务、独立执行尝试、结构化产物和多端读回完成。正式验收必须把任务、账号与租户、来源上下文、执行器、产物、数据库、外部适用性和网页读回绑定到同一份当次生产收据，并且在收据缺失或结算未知时失败关闭。

## Expected outcome

两个代表能力各有一份不同的当天生产收据。每份收据都关联认证账号与租户、来源上下文、任务、独立执行尝试、独立账号聚合执行器、结构化产物、数据库读回和网页读回。创作咨询收据必须证明未新建飞书对象且外部写入集合为空；自媒体创作收据必须证明本次任务创建的飞书对象可由声明应用身份强制读回。所有标识、时间、状态、恢复证据和产物集合必须自洽，不能使用固定样例、模拟数据或历史收据拼接。

## Non-goals

不在本合同中实现 C2，不生成或伪造生产收据，不发起真实生产任务，不写入远程主机、生产数据库、飞书或其他远程系统，不保存生产凭据或私人正文，不以入口打开、HTTP 200、任务已提交或界面成功文案推导端到端完成。

## Normal path

```gherkin
Given 已认证的生产 QA 身份、真实租户和一个可脱敏引用的真实来源上下文
When 分别执行 selfmedia_creation_consultation 与 selfmedia_creation，并等待各自独立账号聚合执行器结束
Then 每项能力都拥有一份当天生产收据，收据同一性贯穿身份、上下文、任务、独立执行尝试、产物、数据库和网页读回
And selfmedia_creation_consultation 证明没有新建飞书对象且外部写入集合为空
And selfmedia_creation 的飞书对象由声明应用身份强制读回，并与同一任务和产物集合一致
```

## Exception paths

- 权限不足、账号与租户不一致或绑定不唯一时，任务不能完成，保护性测试必须非零退出，且不得以页面成功状态代替拒绝结论。
- 重复提交必须复用同一幂等键，不得创建第二个业务结果、第二份产物、第二个飞书对象或伪造完成声明。
- 网络失败、超时、数据库短暂不可用或外部服务无响应时，必须保留可关联的未完成、失败或待人工结论；恢复后才可重新对账。
- 缺少来源上下文、任务、独立执行尝试、结构化产物、数据库读回或网页读回时，收据不合格，不能标记为完成。
- 外部部分失败或结算未知时必须保持未完成，进入待人工、失败或有界对账路径，不能以界面成功文案代替结算。
- 重试必须说明是否复用幂等键、关联哪一份原收据，并证明没有复制结果；恢复必须继续绑定同一收据和明确尝试标识。
- 创作咨询只有在收据同时明确 `noNewFeishuObject: true` 和 `externalWriteSet: []` 时，才允许将外部读回标记为不适用；数据库任务记录和网页读回仍然强制。
- 自媒体创作缺少本次任务的飞书对象、声明身份读回或强制外部读回时，保护性测试必须非零退出。

## Invariants

- 正确打开入口、带入上下文、存在任务记录、HTTP 200、`succeeded` 状态或界面成功文案均不等于端到端完成。
- 每份收据的收据编号、账号、租户、来源编号、上下文摘要、任务编号、能力、变体、幂等键、执行器编号、尝试编号、产物编号、数据库记录、外部对象和网页读回必须一致。
- 两项代表能力必须使用不同的收据、任务和执行尝试标识；任何历史不同任务的拼接都失败关闭，两个能力的产物公开编号也不得重复。
- 所有收据时间必须是当天协调世界时日期且不晚于测试执行时刻；任务和结果必须处于一致的终态。
- 生产收据必须明确来源为 production、不是 fixture、不是 mock、不是 historical composite；输入只包含脱敏稳定引用和摘要。
- 任一强制读回缺失、未知结算、待人工但声称完成、执行器标识缺失、账号聚合执行器与任务执行器相同或产物复制均阻止通过。
- 证据必须区分源码、测试、模拟、本地和生产层级；本保护脚本不得把固定样例证据升级为生产证据。
- 收据和绑定证据不得包含凭据、Cookie、令牌、密码或私人正文字段。

## Data impact

保护脚本只读两份约定路径的生产收据，不创建业务数据。收据允许保存收据编号、公开编号、脱敏账号与租户引用、摘要校验值、运行时间、状态、结果摘要、读回引用和证据引用；创作咨询的外部适用性证据还必须保存“未新建飞书对象”和空外部写入集合的布尔/集合声明。不得保存凭据、Cookie、令牌、密码或私人正文。生产任务、尝试、产物、外部对象、幂等键、重试次数和清理责任由 C2 实现合同承接。

## Permissions

普通用户只能在自身租户内产生和读取任务；账号绑定必须唯一并与收据中的认证账号和租户一致。任务执行器使用受限服务身份，账号聚合执行器必须是独立且可识别的身份。自媒体创作的飞书对象必须由声明的应用身份读回；创作咨询必须证明没有创建新飞书对象。运行验收负责人只读取脱敏证据，产品负责人批准业务语义；本合同不授予生产写权限。

## Performance and reliability

收据必须包含当天的观察时间、执行器开始与结束时间、数据库、外部适用性和网页读回时间，且这些时间不晚于测试执行时刻。任务状态必须是终态且与结果状态一致。执行器中断、外部部分失败和重试必须可解释、可关联且不复制结果。保护性测试在缺少 Node、jq、B3 检查器、收据或任何强制字段时失败关闭；真实收据缺失必须以退出码 3 形成预实现红灯。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 两项代表能力各有不同的当天生产收据，来源上下文、任务能力、变体和幂等键在同一收据内一致 | Integration | Automatic | Yes |
| AC-02 | 每份收据均绑定唯一认证账号与租户、独立执行尝试和独立账号聚合执行器身份 | Integration | Automatic | Yes |
| AC-03 | 两项能力均有同一收据关联的结构化结果、非空产物编号和结果摘要，并且两份收据的产物不重复 | Integration | Automatic | Yes |
| AC-04 | 两项能力的数据库记录均按同一任务编号、产物集合和读回时间从本次任务读回 | Production | Automatic | Yes |
| AC-05 | 创作咨询证明未新建飞书对象且外部写入集合为空；自媒体创作必须有本次任务的飞书对象和强制读回 | External sandbox | Automatic | Yes |
| AC-06 | 两项能力刷新网页后均按同一任务编号读回全部产物，且网页读回与收据一致 | E2E | Automatic | Yes |
| AC-07 | 收据明确为生产、非固定样例、非模拟、非历史拼接，且全部当次时间有效 | Production | Automatic | Yes |
| AC-08 | 重复提交、执行器中断、外部部分失败和重试均不伪装完成或复制结果 | Integration | Automatic | Yes |
| AC-09 | 缺少唯一账号绑定、独立账号聚合执行器、数据库/Web 强制读回或适用的外部读回时保护性测试非零退出 | Static | Automatic | Yes |
| AC-10 | 测试只接受脱敏稳定引用和摘要，禁止敏感字段，并复用 B3 的 `media_e2e_receipt_v1` 结构检查器 | Security | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 产品负责人能分别理解两个代表能力的任务状态、产物来源、失败恢复、数据库/Web 读回和外部适用性，不把“已提交”当作完成 | acceptance/human/MPE2E-TASK-RUN/checklist.md#h-01 | Product owner | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| scripts/acceptance/test-mpe2e-task-run.sh | 334d2393059e54980a8434a99d59bef1b1f82d1466549f540aa40e4f5f0e50d0 | 第 2 版两能力生产同收据门禁、B3 结构复用、账号/租户绑定、独立执行器、数据库/Web 读回、咨询外部写入为空、创作强制飞书读回、恢复矩阵、去重、敏感字段禁入和缺收据退出码 3 |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 两份收据能力、来源、任务和标识一致性检查 | scripts/acceptance/test-mpe2e-task-run.sh；两份生产收据 | Automatic | Yes |
| AC-02 | 认证账号、租户、唯一绑定、独立执行尝试与账号聚合执行器检查 | scripts/acceptance/test-mpe2e-task-run.sh | Automatic | Yes |
| AC-03 | 结果摘要、产物编号、同收据绑定和跨收据去重检查 | scripts/acceptance/test-mpe2e-task-run.sh；scripts/check-media-e2e-receipt.mjs | Automatic | Yes |
| AC-04 | 数据库读回引用、任务关联和时间检查 | scripts/acceptance/test-mpe2e-task-run.sh；两份生产收据 | Automatic | Yes |
| AC-05 | 创作咨询无新飞书对象/空写入集合及自媒体创作飞书强制读回检查 | scripts/acceptance/test-mpe2e-task-run.sh | Automatic | Yes |
| AC-06 | 网页任务编号、产物集合和读回时间检查 | scripts/acceptance/test-mpe2e-task-run.sh；scripts/check-media-e2e-receipt.mjs | Automatic | Yes |
| AC-07 | production 来源、非 fixture、非 mock、非 historical composite 和当天时间检查 | scripts/acceptance/test-mpe2e-task-run.sh | Automatic | Yes |
| AC-08 | 重复提交、中断、外部部分失败和重试恢复矩阵检查 | scripts/acceptance/test-mpe2e-task-run.sh | Automatic | Yes |
| AC-09 | 缺字段失败关闭、B3 复用和缺生产收据退出码 3 红灯 | scripts/acceptance/test-mpe2e-task-run.sh；scripts/check-media-e2e-receipt.mjs | Automatic | Yes |
| AC-10 | 敏感字段扫描与 B3 `media_e2e_receipt_v1` 检查器复用 | scripts/acceptance/test-mpe2e-task-run.sh；scripts/check-media-e2e-receipt.mjs | Automatic | Yes |
| H-01 | 产品负责人双能力人工验收 | acceptance/human/MPE2E-TASK-RUN/checklist.md#h-01 | Human | Yes |

## Exploratory testing

正式生产运行获批后，探查不同来源类型、空上下文、大附件、多平台链接、重复点击、页面关闭后重进、执行器重启、数据库短暂失败、外部服务限流、外部对象延迟可见和结果产生后来源对象变化。探查结果只能作为补充证据，不能绕过双收据门禁，也不能把创作咨询的外部读回不适用误扩展到数据库或网页读回。

## Production monitoring and rollback

监控代表能力的收据缺失率、账号与租户不一致、执行器领取延迟、中断率、待人工比例、创作咨询意外外部写入、自媒体创作应有飞书写入失败、数据库读回缺失、网页读回缺失、重复产物和门禁失败。出现跨租户、重复结果、成功状态缺读回、创作咨询意外创建外部对象或自媒体创作飞书对象不一致时，立即停止相关能力入口，保留任务供对账；回滚只切换到已验证发布。

## Risks and open decisions

当前没有未决产品选择：D4 v2 已接受两个代表能力及其外部副作用边界。历史失效说明：第 1 版曾把 `viral_deconstruction` 当成只读样本，但远程权威源码证明其存在写入副作用；该历史语义已由 D4 v2 失效，不得出现在当前能力集合、收据路径、正式验收语义或保护测试中。当前唯一未验证事项是 C2 尚未生成两份真实生产同收据及人工运行结果；这正是实现和运行阶段的发布阻断项，不降低本合同的验收要求。
