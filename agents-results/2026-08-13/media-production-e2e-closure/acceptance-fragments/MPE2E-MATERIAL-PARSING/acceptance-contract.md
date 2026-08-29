# Acceptance Contract: MPE2E-MATERIAL-PARSING

- Task ID: MPE2E-MATERIAL-PARSING
- Contract version: 1
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: 产品负责人和运行验收负责人
- Approval evidence: 用户于 2026-08-15 明确要求建立素材类型、平台、解析方式和失败提示覆盖矩阵；支持组合自动解析；不支持或失败必须明确提示并进入人工补充，不能默默缺字段。
- Request source: D6 accepted decision `media.material-parsing-coverage@1` and the 2026-08-15 user instruction
- SSOT node: D6
- SSOT path: agents-results/2026-08-13/media-production-e2e-closure/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.material-parsing-coverage@1
- Assumption IDs: none
- Invalidation keys: decision.material-parsing-coverage, contract.material-parsing-coverage-v1
- Baseline identity: local candidate `media-production-e2e-v4`, candidate manifest SHA-256 `62f0fd2a23b614483482242ea6294e0bb3cf7edc0037a740a99f19690fecad4a`, frozen matrix SHA-256 `24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56`, Wave 17 result SHA-256 `27cfc24b13d7618127996a72f57c38608f4a0df2a32f213104823b6c97021dbf`
- Human acceptance workspace: acceptance/human/MPE2E-MATERIAL-PARSING

## User and scenario

产品负责人和运行验收负责人需要判断用户在 Web 素材输入流程中，能否清楚知道当前素材属于哪一种解析方式、自动解析是否完成、失败时需要补充什么，以及未完成请求是否真的没有提交。机器验收负责覆盖矩阵、字段完整性、失败关闭、状态和证据身份；人工只判断用户对这些含义的理解。

## Problem

素材类型与目标平台的支持范围并不相同。仅凭上传成功、得到一个上传编号、或页面出现结果，都不能证明素材已经解析完成。若解析不支持、解析失败、必填输出不完整、来源缺失或媒体类型不匹配却继续入队，系统会把未完成素材当作可执行任务，或者让用户误以为字段已经被系统补全。

## Expected outcome

冻结矩阵成为素材解析覆盖的唯一业务定义，包含 9 个平台与 6 种素材类型的 54 个唯一组合。每个组合都有解析方式、解析器身份与版本、自动输出要求、中文失败原因、人工补充字段和下一步动作。只有完整的自动结果或人工补充后再次校验通过的结果可以进入任务创建；其他结果必须清楚显示原因并在入队前失败关闭。

## Non-goals

- 不改变前端、后端、测试、QA、候选清单、接口或生产服务实现。
- 不扩展 D6 已批准的 9 个平台、6 种素材类型、人工字段或完成状态。
- 不把本地 fixture、隔离 Docker、Chromium 或 HTTP 证据解释为生产、设备、真实外部平台或真实附件验收。
- 不为未获批的性能目标、生产阈值、真实账号或外部平台接入作产品决策。
- 不把文件上传、上传编号、页面显示成功或手工填写本身视为解析完成。

## Normal path

```gherkin
Given 用户选择一个冻结矩阵中的平台和素材类型，并提供与该类型匹配的来源
When 系统按矩阵选择解析方式并校验解析结果
Then 若所有自动必填输出完整，状态为 completed_auto；否则显示明确原因、缺失字段、人工字段和下一步动作
```

```gherkin
Given 自动解析失败、不支持该组合或自动输出不完整
When 用户补充人工字段并重新校验
Then 只有补充结果完整且重新校验通过时状态才为 completed_manual，且页面不得将其标记为自动成功
```

```gherkin
Given 素材解析状态不是 completed_auto 或已重新校验的 completed_manual
When 用户确认创建任务
Then 请求以 material_parsing_incomplete 和 HTTP 422 失败关闭，不调用任务创建，不产生入队副作用
```

## Exception paths

- 不支持组合：按矩阵返回人工处理方式、中文原因、`remark` 人工字段和下一步动作，不静默删除素材或字段。
- 解析器失败：保留失败原因和缺失字段，进入人工补充；重试仍需重新校验，不能沿用上传成功状态。
- 自动输出不完整：即使部分字段存在，也只能是未完成状态；必须明确列出缺失字段。
- 来源缺失：没有文本、链接或上传来源时失败关闭；不以空值、上传记录或默认值冒充解析成功。
- MIME 不匹配：声明的素材类型与文件媒体类型不一致时失败关闭，并要求更换匹配文件或人工补充；不得继续入队。
- 人工补充缺失或为空：保持未完成状态，继续展示需要补充的字段和下一步动作。
- 网络或外部内容读取失败：按解析失败处理，不能把超时、空响应或部分响应当作完成。
- 重复确认或重试：只允许已完成状态进入任务创建；未完成的重复请求都必须保持同一失败关闭语义，不得因为重复点击绕过解析门槛。
- 权限或会话拒绝：沿用现有认证 Web 合同的拒绝语义；本契约不放宽权限，也不以人工字段绕过身份校验。

## Invariants

- 9 个平台与 6 种素材类型形成恰好 54 个唯一组合，前端、后端和 SSOT 矩阵副本字节一致。
- 每个组合都有非空解析方式、解析器身份与版本、失败代码、中文失败提示、人工字段和下一步动作；自动组合还必须声明非空自动输出集合。
- 只有 `completed_auto` 和重新校验通过的 `completed_manual` 具有入队资格。
- 上传成功、文件存在、上传编号存在、页面展示结果或部分自动输出都不能单独证明解析成功。
- 未完成解析不得调用任务创建；错误码为 `material_parsing_incomplete`，HTTP 状态为 422。
- 失败提示必须同时暴露可理解的失败原因、缺失字段（如有）和下一步动作；不允许静默丢弃字段。
- 人工完成必须在用户可见状态中保持人工语义，不能显示为自动成功。
- 本地 fixture、mock、隔离容器和浏览器测试只能证明其声明的本地证据等级。

## Data impact

上传记录只证明文件被接收和可供后续处理，不改变解析完成状态。解析结果必须携带冻结矩阵要求的状态、方法、失败详情、缺失字段和人工补充结果；人工字段使用 `remark`。未完成请求不创建任务、不入队、不产生任务执行副作用。完成状态的重复确认必须遵循既有幂等语义；本契约不批准数据库迁移、外部写入、保留期变化或清理策略变化。

## Permissions

用户只能查看和补充自己当前认证上下文允许的素材与任务草稿。产品负责人和运行验收负责人负责产品含义和运行证据判断。实现负责人可以消费已锁定的契约，但不得编辑、删除、跳过、弱化或重新生成本契约登记的保护性测试。任何角色都不得用人工补充绕过认证、租户或平台授权边界。

## Performance and reliability

D6 只冻结覆盖、状态和失败关闭语义，没有批准新的延迟、并发或吞吐目标；本契约不把本地运行时间推导为生产 SLO。适用的可靠性底线是：解析失败、超时、缺源、MIME 不匹配和字段不完整均可重复得到明确失败，并且在入队前没有任务创建副作用。生产观测阈值和回退条件见 `acceptance/production/monitoring-plan.md`，不构成生产已验收声明。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 冻结矩阵包含 9 个唯一平台、6 个唯一素材类型和恰好 54 个唯一组合 | Static | Automatic | Yes |
| AC-02 | 每个组合均声明解析方式、解析器身份与版本、必填自动输出、中文失败提示、人工字段和下一步动作；自动组合的输出集合非空 | Static | Automatic | Yes |
| AC-03 | 前端、后端和 SSOT 矩阵副本字节一致，且候选清单引用同一合同身份和 54 个组合 | Static | Automatic | Yes |
| AC-04 | 只有完整自动输出才产生 `completed_auto`；上传成功、上传编号或部分输出不能单独证明解析成功 | Unit / Integration | Automatic | Yes |
| AC-05 | 不支持组合、解析失败和自动输出不完整均显示明确原因、缺失字段、人工字段和下一步动作，并进入人工补充路径 | Unit / E2E | Automatic | Yes |
| AC-06 | 人工补充后只有重新校验通过的 `completed_manual` 才可完成，且不会被标记为自动成功 | Unit / E2E | Automatic | Yes |
| AC-07 | 缺少来源或 MIME 不匹配时失败关闭，不以文件上传成功作为解析成功 | Unit / Integration | Automatic | Yes |
| AC-08 | 非 `completed_auto` 或重新校验的 `completed_manual` 入队时返回 `material_parsing_incomplete` / HTTP 422，不调用任务创建 | Integration / Contract | Automatic | Yes |
| AC-09 | 前端确认界面呈现解析方式、预期状态、失败原因、缺失字段、人工结果和下一步动作，并清楚区分自动与人工完成 | E2E | Automatic | Yes |
| AC-10 | 保护性测试、QA 和 Wave 16/17 验证文件的登记哈希未漂移；本任务门禁使用绝对项目根并失败关闭 | Static | Automatic | Yes |
| AC-11 | Wave 17 既有材料解析复核通过，且其结果和候选清单明确声明本地证据不等于生产验收 | Local runtime | Automatic | Yes |

## Human acceptance

人工清单只判断机器断言无法替代的用户理解：自动与人工处理是否可区分、失败与补充要求是否可理解、用户是否理解未完成请求没有提交。确定性的矩阵、状态、HTTP、任务创建调用和哈希断言由自动门禁负责。

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 用户能区分自动解析和人工补充处理，不把人工完成理解为自动成功 | acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md#h-01 | 产品负责人和运行验收负责人 | Yes |
| H-02 | 用户能理解失败原因、缺失字段、需要补充的内容和下一步动作 | acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md#h-02 | 产品负责人和运行验收负责人 | Yes |
| H-03 | 用户能理解解析未完成的请求没有提交，且知道需要补充或修正后再试 | acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md#h-03 | 产品负责人和运行验收负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| scripts/acceptance/test-mpe2e-material-parsing.sh | 3d1e8b2cbcfe24c37876fb9ffaf30c36fdae3832a4aba7e635ee97f48b3c7a2f | This fail-closed matrix, copy, candidate, registered-hash, and Wave 17 gate |
| agents-results/2026-08-13/media-production-e2e-closure/execution-wave-19/MPE2E-MATERIAL-PARSING-DESIGN/validation/MPE2E-MATERIAL-PARSING-DESIGN.sh | b86d8c6924c0a7fa0603daa83b6f8ffdccda7f45bb228ebcfe9ac17a48a29d2d | Frozen task validation command |
| .codex-work/merge-candidate-v4/frontend/scripts/qa/checkMaterialParsing.ts | 251ecad97df5ecbff3a3925165d1a60020c0cf6cae7b0420b44ef21928e9f773 | Frontend material parsing QA |
| .codex-work/merge-candidate-v4/frontend/scripts/qa/checkTaskLaunchDraft.ts | a8ae1148331f6006ff89a1d150cc91e167fe95429f8b921770161a712bb00f3f | Frontend task-launch confirmation and submit gate QA |
| .codex-work/merge-candidate-v4/backend/tests/test_material_parsing.py | cf6417ae0fc2e7320880fff1a3e6ef11290d2afa6c1953ba4f596fcdd8a97ce0 | Backend parsing, failure detail, and revalidation tests |
| .codex-work/merge-candidate-v4/backend/tests/test_media_web_tasks.py | c265bee32f4a7726cfbc7060394027fafd17941700b6bcab30b02268b7945153 | Upload boundary and task creation failure-close tests |
| agents-results/2026-08-13/media-production-e2e-closure/execution-wave-16/C3-MATERIAL-PARSING-FRONTEND/validation/C3-MATERIAL-PARSING-FRONTEND.sh | 32397d19dddb92f06c06f5f28a5b995c0060a2ea61f36db53931601a3ab4d98d | Wave 16 frontend validation |
| agents-results/2026-08-13/media-production-e2e-closure/execution-wave-16/C4-MATERIAL-PARSING-BACKEND/validation/C4-MATERIAL-PARSING-BACKEND.sh | 301e62e40c9dbc68269d5b16395ea8b1dfcf1c042eac835514591a8a30a85bb9 | Wave 16 backend validation |
| agents-results/2026-08-13/media-production-e2e-closure/execution-wave-17/validation/material-parsing-main-thread-review.sh | fc2bec23ab69da35d18e269bb4cd1a0236eb3929c33c943ee4bff4e6da02de8b | Existing Wave 17 material parsing review |
| agents-results/2026-08-13/media-production-e2e-closure/execution-wave-18/C5-UNIQUE-CANDIDATE/validation/C5-UNIQUE-CANDIDATE.sh | 34b6451ec3644a0bf902fbb4f65ea66d92c6d38f5a7ce165d22cdbadc2fffcaf | Candidate identity and source-manifest validation |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | JSON matrix cardinality and uniqueness assertions | scripts/acceptance/test-mpe2e-material-parsing.sh | Automatic | Yes |
| AC-02 | JSON required-field and automatic-output assertions | scripts/acceptance/test-mpe2e-material-parsing.sh; `.codex-work/merge-candidate-v4/frontend/scripts/qa/checkMaterialParsing.ts` | Automatic | Yes |
| AC-03 | Byte comparison and candidate-manifest identity assertions | scripts/acceptance/test-mpe2e-material-parsing.sh; C5 validation | Automatic | Yes |
| AC-04 | Existing frontend QA and backend parsing tests | Wave 17 validation; C3/C4 validation scripts | Automatic | Yes |
| AC-05 | Failure matrix and browser-readable detail assertions | `.codex-work/merge-candidate-v4/frontend/scripts/qa/checkMaterialParsing.ts`; `backend/tests/test_material_parsing.py` | Automatic | Yes |
| AC-06 | Manual revalidation and automatic/manual presentation assertions | Wave 17 validation; C3/C4 validation scripts | Automatic | Yes |
| AC-07 | Missing source and file/upload boundary tests | `backend/tests/test_material_parsing.py`; `backend/tests/test_media_web_tasks.py` | Automatic | Yes |
| AC-08 | HTTP 422/error-code and no-task-creation assertions | Wave 17 validation; `backend/tests/test_media_web_tasks.py` | Automatic | Yes |
| AC-09 | Frontend material parsing and task-launch QA | `frontend/scripts/qa/checkMaterialParsing.ts`; `frontend/scripts/qa/checkTaskLaunchDraft.ts` | Automatic | Yes |
| AC-10 | Protected hash checks and absolute-root fail-closed shell execution | scripts/acceptance/test-mpe2e-material-parsing.sh | Automatic | Yes |
| AC-11 | Existing Wave 17 review and local-only candidate boundary | `execution-wave-17/result.md`; `scripts/acceptance/test-mpe2e-material-parsing.sh` | Automatic | Yes |
| H-01 | Product understanding of automatic versus manual handling | acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md#h-01 | Human | Yes |
| H-02 | Product understanding of failure and required supplementation | acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md#h-02 | Human | Yes |
| H-03 | Product understanding that incomplete requests were not submitted | acceptance/human/MPE2E-MATERIAL-PARSING/checklist.md#h-03 | Human | Yes |

## Exploratory testing

在获批构建上可由验收负责人探查边界组合：空文本、不可访问链接、部分返回链接内容、错误 MIME、上传后刷新、重复确认、网络中断后重试、人工字段只填一部分，以及自动失败后改为人工补充。探查只记录未预料的理解或交互问题；不得替代保护性矩阵、失败关闭、字节一致性和哈希门禁，也不得把本地探查写成生产证据。

## Production monitoring and rollback

生产观测计划位于 `agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-MATERIAL-PARSING/acceptance/production/monitoring-plan.md`。在真实生产部署、真实附件和真实质量验收证据出现前，不得以本契约或本地门禁标记生产接受。

## Risks and open decisions

当前没有未决产品选择：D6 的 `media.material-parsing-coverage@1` 已由用户于 2026-08-15 明确批准。实现、生产和人工运行仍是独立证据边界。本契约锁定本地候选的可执行验收定义，但不宣称已部署、已取得真实附件生产收据、已完成真实账号浏览器验收、已完成设备验收、已完成数据库或外部平台读回，亦不标记 D6、C3、C4、C5 或发布为 `ACCEPTED`。
