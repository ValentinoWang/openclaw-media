# Acceptance Contract: MPE2E-TASK-RUN-V3

- Task ID: MPE2E-TASK-RUN-V3
- Contract version: 3
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: 产品负责人和运行验收负责人
- Approval evidence: 用户于 2026-08-14 采纳 OP03 推荐方案；D5 v1 机器决定 `media.representative-account-binding-input@1` 已记录 `decision_state: ACCEPTED`、`decision_version: 1`，并明确两项代表能力的创建输入、精确关系绑定和入队前失败关闭。
- Request source: 2026-08-14 用户采纳 OP03 推荐方案、D5 v1 已接受机器决定及 B2 `media.context-task-e2e-contract` 验收设计节点
- SSOT node: B2
- SSOT path: agents-results/2026-08-13/media-production-e2e-closure/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.no-inference-completion-boundary@1, media.same-receipt-proof@1, media.release-capability-samples@2, media.representative-account-binding-input@1
- Assumption IDs: none
- Invalidation keys: contract.context-task-e2e, decision.release-capability-samples, decision.representative-account-binding-input
- Baseline identity: D5 v1 SHA-256 `c6bd807376561c25820938b1839f50b633a7e2f4911f3460fea9a6f5e1a0e12b`; B2 SHA-256 `bc03cff59c504da915380b0357550ff34eaa231a37c5cbd103170c1adb6bbf7d`; V2 contract `f2f97099c514b8a9b5570c7626cc5e746ce99394370985000cdddd5094a18bf2`; V2 checklist `45664f75ee37535b3e67242a4c0550735a131f50281d5fca34f0e6d1e095724f`; V2 binding `48b84499da08393953eec17fe7afc0fed209ed908e427522254ef20414c2fe9b`; V2 protected test `334d2393059e54980a8434a99d59bef1b1f82d1466549f540aa40e4f5f0e50d0`; B3 schema `media_e2e_receipt_v1`; B3 checker `scripts/check-media-e2e-receipt.mjs`
- Human acceptance workspace: acceptance/human/MPE2E-TASK-RUN-V3

V2 的合同、中文清单、绑定和保护测试是不可变历史基线。本合同新增 V3 语义，不覆盖、不重命名、不删除或修改 V2 资产。

## User and scenario

已认证普通用户在当前租户内从脱敏稳定来源上下文创建一个创作咨询任务或一个自媒体创作任务。用户必须在任务创建入口明确选择平台和客户自有账号；系统从当前认证会话取得认证用户公开编号，并在入队前验证该账号与当前租户、当前认证用户、规范化平台和规范化账号之间存在唯一正式关系。创作咨询（`selfmedia_creation_consultation`）还必须提供问题；自媒体创作（`selfmedia_creation`）保留既有必填内容。其他能力保持现有输入要求。

成功运行继续受 V2 同收据、独立执行器、数据库读回、网页读回、恢复和敏感字段边界约束。创作咨询不得新建飞书对象且外部写入集合为空；自媒体创作必须完成本次任务的飞书强制读回。

## Problem

V2 只证明任务执行后的同收据闭环，不能证明两项代表能力在创建前取得了明确的平台和客户自有账号，也不能证明账号文字相同之外存在当前租户和当前认证用户下的唯一正式关系。缺少、不可见、跨用户、跨租户、多义或冲突关系若延迟到执行阶段才失败，会产生悬空任务、不可结算收据或跨租户信息泄露。V3 必须把输入和关系校验锁定在入队前，并让 API 与前端使用稳定、可区分且不泄露关系存在性的错误语义。

## Expected outcome

1. 合同编号为 `MPE2E-TASK-RUN-V3`，版本为 3，状态为 `APPROVED`，测试基线为 `LOCKED`，就绪模式为 `FORMAL`，活动假设为 `none`，并绑定四项已接受决定。
2. `selfmedia_creation_consultation` 创建请求包含问题、平台和客户自有账号；`selfmedia_creation` 创建请求包含既有必填内容、平台和客户自有账号。其他能力的创建输入不因本合同增加账号要求。
3. 当前认证用户公开编号缺失、平台缺失、账号缺失、关系不存在或不可见、关系不唯一、跨租户、跨用户或关系冲突时，API/前端在入队前返回稳定错误，且不创建任务、执行尝试、租约、产物、数据库任务记录、飞书对象或成功收据。
4. 通过创建的任务公开记录和生产收据证明以下精确绑定键完全一致：当前租户公开编号、当前认证用户公开编号、规范化平台、规范化账号。证明必须包含正式关系引用和唯一性；账号文字相同不能替代正式关系记录。
5. 两项代表能力各自产生一份不同的当天生产同收据证据。V3 收据同时保留 V2 的来源、任务、执行器、产物、数据库/Web 读回、外部适用性、恢复和敏感字段门禁，并新增平台、客户账号、认证用户公开编号、租户和正式关系的一致性证明。

## Non-goals

不在本合同中实现 C2，不修改接口源码、前端源码、数据库或关系数据，不创建生产任务、租约、产物、飞书对象、真实生产收据或人工运行结果，不修改 B3 检查器、fixtures 或 V2 历史资产，不把账号文字相同推断成正式关系，不把任何静态、模拟、固定样例或历史拼接证据升级为生产证据，不改变其他 Media 能力的既有输入要求。

## Normal path

```gherkin
Given 已认证普通用户、当前租户、真实客户自有账号关系和脱敏稳定来源上下文
When 用户在 selfmedia_creation_consultation 入口填写问题、平台和客户自有账号并提交
Then 系统取得当前认证用户公开编号，规范化平台和账号，验证唯一正式关系，并在入队前接受任务
And 任务、执行尝试、结果、数据库读回、网页读回和收据使用同一租户、用户、平台、账号和关系绑定
And 创作咨询不新建飞书对象，外部写入集合为空
```

```gherkin
Given 已认证普通用户、当前租户、真实客户自有账号关系和自媒体创作既有必填内容
When 用户在 selfmedia_creation 入口填写既有必填内容、平台和客户自有账号并提交
Then 系统取得当前认证用户公开编号，规范化平台和账号，验证唯一正式关系，并在入队前接受任务
And 成功收据证明数据库结果和声明应用身份读回的飞书对象与同一任务、账号、用户、租户和关系一致
```

## Exception paths

- 平台、客户自有账号或当前认证用户公开编号缺失时，返回 `required_input_missing` 和可理解的必填提示，HTTP 状态为 422；在入队前关闭，不创建任何任务或副作用。
- 关系不存在或对当前用户不可见时，返回 `account_relationship_unavailable` 和“无法确认所选客户账号关系”，HTTP 状态为 404；跨租户和跨用户情形使用同一不可见语义，不泄露对象是否存在。
- 关系不唯一或关系冲突时，返回 `account_relationship_conflict` 和“所选客户账号关系存在冲突”，HTTP 状态为 409；不创建任何任务或副作用。
- 平台或账号文字相同但正式关系引用不匹配时，按关系不可用或关系冲突处理；不得直接接受文字匹配。
- 重复提交、网络失败、数据库短暂不可用、执行器中断、外部部分失败或重试必须继续遵守 V2 同收据和幂等恢复边界；未结算时保持未完成，不显示成功。
- 创作咨询若产生任何飞书对象或外部写入，收据失败关闭；自媒体创作若缺少声明应用身份的飞书强制读回，收据失败关闭。

## Invariants

- 只有 `selfmedia_creation_consultation` 和 `selfmedia_creation` 收紧平台与客户自有账号输入；其他能力的输入要求不被本合同扩大。
- 创建前有效输入必须同时有当前租户、当前认证用户公开编号、规范化平台、规范化账号和唯一正式关系记录；四元组顺序固定为 `[tenantPublicId, userPublicId, normalizedPlatform, normalizedAccount]`。
- 账号文字相同不等于关系成立。`relationshipRef` 必须来自正式关系记录，关系基数必须为 1，绑定摘要必须覆盖四元组和正式关系引用。
- 缺失输入、关系不可用、关系不唯一、跨租户、跨用户和关系冲突均在入队前失败关闭，不产生任务、执行尝试、租约、产物、数据库记录、飞书对象或成功收据。
- API 和前端必须区分 `required_input_missing`、`account_relationship_unavailable` 和 `account_relationship_conflict`，同时对跨租户和跨用户使用不可见语义。
- 每份成功收据中的平台、客户账号、认证用户公开编号、租户、正式关系、任务、结果、数据库读回、网页读回和外部适用性必须属于同一次任务；两项代表能力的收据、任务、执行尝试和产物必须彼此不同。
- V2 的“入口打开、任务已提交、HTTP 200、界面成功文案”均不等于完成；生产同收据和适用读回仍是完成边界。
- 收据和人工结果不得保存或输出凭据、Cookie、令牌、密码、私人正文或原始正文。

## Data impact

本合同的保护测试只读两份约定路径的生产收据，不写业务数据。成功收据可以保存脱敏稳定引用、公开编号、规范化平台、规范化账号、正式关系公开引用、绑定摘要、任务和读回摘要；不得保存私人正文或敏感认证字段。失败关闭证据只保存错误码、HTTP 状态、公开提示、验证阶段和布尔副作用计数，不保存跨租户对象详情。C2 负责关系查询、入队事务、幂等、租约、执行尝试、结果、读回和清理的实际实现；本合同不授权这些写入。

## Permissions

普通用户只能选择当前租户且当前认证用户可见的客户自有账号关系，并只能读取自己的任务和收据。关系不可见时，API 与前端不得通过错误差异透露跨租户或跨用户对象。受限执行器只能领取已经通过创建前绑定的任务；账号聚合执行器必须独立且可识别。产品负责人判断账号选择、错误可理解性、不可见性、失败不入队和成功收据一致性；运行验收负责人只读取脱敏证据。本合同不授予生产写权限。

## Performance and reliability

平台、账号、当前用户公开编号和正式关系校验必须在入队前完成；失败请求不应留下异步待处理任务。稳定错误必须由 API 和前端一致呈现，不能依赖事后执行器失败。成功收据仍须满足 V2 的当天 UTC 时间、终态、数据库读回、网页读回、外部适用性和恢复矩阵要求。保护测试在缺少 Node、jq、B3 检查器、收据或任何 V3 字段时失败关闭；缺少真实生产收据必须以退出码 3 形成预实现红灯。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | V3 合同元数据为版本 3、APPROVED、LOCKED、FORMAL、无活动假设，并完整引用四项已接受决定和三项失效键 | Static | Automatic | Yes |
| AC-02 | 两项代表能力分别要求平台和客户自有账号；创作咨询保留问题必填，自媒体创作保留既有必填内容，其他能力输入保持不变 | Contract | Automatic | Yes |
| AC-03 | 每份成功生产收据公开证明当前租户、当前认证用户公开编号、规范化平台、规范化账号和唯一正式关系的精确绑定 | Production | Automatic | Yes |
| AC-04 | 缺少平台、账号或认证用户公开编号时，入队前返回 `required_input_missing`/422 并证明零副作用 | Contract | Automatic | Yes |
| AC-05 | 关系不存在、不可见、跨租户或跨用户时，入队前返回 `account_relationship_unavailable`/404，不泄露存在性并证明零副作用 | Contract | Automatic | Yes |
| AC-06 | 关系不唯一或冲突时，入队前返回 `account_relationship_conflict`/409 并证明零副作用 | Contract | Automatic | Yes |
| AC-07 | V2 两项代表能力的同收据、数据库/Web 读回、创作咨询无飞书写入、自媒体创作飞书强制读回、恢复和敏感字段门禁全部继续通过 | Production | Automatic | Yes |
| AC-08 | 两份收据、任务、执行尝试、用户绑定和产物彼此区分，且不是固定样例、模拟或历史拼接 | Production | Automatic | Yes |
| AC-09 | 独立 V3 保护测试复用 B3 检查器，缺真实收据退出码为 3，固定样例和不完整 V3 字段不能通过生产门禁 | Static | Automatic | Yes |
| AC-10 | 中文人工清单只记录账号选择、错误可理解性、跨租户不可见性、失败不入队和成功收据一致性，不记录运行结果 | Human procedure | Human | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 产品负责人判断用户能否选择正确的客户自有账号并理解其正式关系 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-01 | Product owner | Yes |
| H-02 | 产品负责人判断必填、关系不可用和关系冲突提示是否稳定且可理解 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-02 | Product owner | Yes |
| H-03 | 产品负责人判断跨租户或跨用户账号是否不可见且不泄露存在性 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-03 | Product owner | Yes |
| H-04 | 产品负责人判断失败是否发生在入队前且没有用户可见的悬空任务 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-04 | Product owner | Yes |
| H-05 | 产品负责人判断成功收据中的平台、账号、用户、租户和正式关系是否与任务一致 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-05 | Product owner | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| scripts/acceptance/test-mpe2e-task-run-v3.sh | dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d | V3 两能力生产同收据门禁、创建前必填与精确关系绑定、错误语义、失败关闭、V2 同收据继承、B3 复用、非样例证据、去重和敏感字段禁入 |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 合同校验器与冻结验证命令 | agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md；B2-V3-LOCK.sh | Automatic | Yes |
| AC-02 | 合同静态断言和 V3 收据输入断言 | 合同；scripts/acceptance/test-mpe2e-task-run-v3.sh | Automatic | Yes |
| AC-03 | 两份 V3 生产收据的任务输入与 accountBinding 断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh；两份生产收据 | Automatic | Yes |
| AC-04 | missing_platform、missing_account、missing_user_public_id 失败关闭断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh | Automatic | Yes |
| AC-05 | relationship_not_found_or_invisible、cross_tenant、cross_user 失败关闭断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh | Automatic | Yes |
| AC-06 | relationship_not_unique、relationship_conflict 失败关闭断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh | Automatic | Yes |
| AC-07 | V2 b2Evidence 同收据与能力副作用断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh；scripts/check-media-e2e-receipt.mjs | Automatic | Yes |
| AC-08 | 双收据去重、生产来源、非 fixture、非 mock、非历史拼接断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh | Automatic | Yes |
| AC-09 | B3 检查器复用、缺收据退出码 3 和独立文件断言 | scripts/acceptance/test-mpe2e-task-run-v3.sh；B2-V3-LOCK.sh | Automatic | Yes |
| AC-10 | 产品负责人五项人工判断 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-01；#h-02；#h-03；#h-04；#h-05 | Human | Yes |
| H-01 | 账号选择和正式关系理解 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-01 | Human | Yes |
| H-02 | 错误提示可理解性 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-02 | Human | Yes |
| H-03 | 跨租户/跨用户不可见性 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-03 | Human | Yes |
| H-04 | 失败不入队 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-04 | Human | Yes |
| H-05 | 成功收据一致性 | acceptance/human/MPE2E-TASK-RUN-V3/checklist.md#h-05 | Human | Yes |

## Exploratory testing

正式生产运行获批后，产品负责人可探查同一账号的不同平台规范化写法、账号名称空白、关系刚失效、跨租户和跨用户选择、重复点击、页面刷新、网络中断、关系查询超时、执行器重启、数据库短暂失败、外部写入延迟和收据读回延迟。探查只记录理解性和未预料行为，不替代自动化失败关闭、同收据或读回门禁。

## Production monitoring and rollback

监控两项代表能力的必填输入缺失率、关系不可用率、关系冲突率、跨租户/跨用户不可见性错误、入队前副作用计数、账号与租户不一致、正式关系引用缺失、V3 收据缺失、数据库/Web 读回缺失、创作咨询意外飞书写入、自媒体创作飞书读回失败和重复产物。出现跨租户泄露、入队前产生任务、关系绑定不一致、成功收据缺少公开编号或强制读回缺失时，立即停止相关入口并保留对账所需的脱敏引用；回滚只切换到已验证发布，不恢复未验证输入路径。

## Risks and open decisions

当前没有未决产品选择。OP03 推荐方案已于 2026-08-14 被用户采纳，D5 v1 已接受并将两项代表能力、四元组精确绑定和失败关闭写入机器决定。V2 四项资产仅作为不可变历史基线。C2 尚未以真实生产收据证明 V3 实现，人工运行结果也尚未产生；这是实现和运行阶段的发布阻断项，不降低本合同的验收要求。
