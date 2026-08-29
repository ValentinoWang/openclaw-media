# Acceptance Contract: MPE2E-AUTH-WEB

- Task ID: MPE2E-AUTH-WEB
- Contract version: 3
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: 产品负责人和安全负责人
- Approval evidence: 当前 OP `openproblem.md` 已记录 OP01 推荐方案已由用户采纳并关闭；D1 v1 `media.no-inference-completion-boundary@1` 和 D3 v1 `media.qa-identity@1` 均为 ACCEPTED。第一阶段身份 SSOT 的 K1 v1 `media.stage1.decision.personal-auth@1` 已接受“平台账号与飞书成员身份不得按邮箱或姓名自动合并”。用户于 2026-08-15 再次明确要求：外部身份和客户账号必须正式绑定，缺失、重复、跨租户或非目标工作区在入队或建会话前拒绝。本第 3 版据此重锁认证与会话边界。
- Request source: 用户于 2026-08-15 的身份绑定与工作区失败关闭指令、当前 OP 批准记录、K1 v1、D1 v1、D3 v1 和 B1 节点
- SSOT node: B1
- SSOT path: agents-results/2026-08-13/media-production-e2e-closure/ssot-development-paths.md
- Readiness mode: FORMAL
- Decision refs: media.stage1.decision.personal-auth@1, media.no-inference-completion-boundary@1, media.qa-identity@1
- Assumption IDs: none
- Invalidation keys: contract.authenticated-web, decision.qa-identity, media.stage1.auth-intent-binding.v4, media.stage1.session-workspace-resolution.v4
- Baseline identity: 当前生产前端 `20260814T084319Z-media-login-canonical`，本地只读源码清单 `.codex-work/production-baseline-20260814T084319Z/frontend/.source-manifest.sha256` SHA-256 `7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14`；当前生产后端 `20260814T062408Z-opc-feishu-login`，本地只读发布清单 `.codex-work/production-baseline-20260814T084319Z/backend/.manifest.sha256` SHA-256 `bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b`
- Human acceptance workspace: acceptance/human/MPE2E-AUTH-WEB

第 1、2 版合同、中文清单、绑定和保护测试是失效历史起点；本第 3 版在原路径替换其认证事实来源，不保留邮箱/姓名认领兼容路径，也不创建并行认证合同。真实 QA 身份和生产浏览器收据仍由 DB 负责；`local-candidate` 的通过不能提升为生产完成，也不提前阻塞 C3、C4、C5 或 C1。

## User and scenario

产品负责人、安全负责人和后续实现负责人需要一个覆盖现行认证边界的正式 Web 验收合同。用户可以选择飞书扫码登录或账号密码登录；两种方式都是一等入口，成功后都进入同一个规范租户会话。安全负责人提供的收据只能是脱敏稳定元数据，测试执行者不能接触密码、Cookie、令牌、密钥、授权码或私人正文。

验收分为两个互不混淆的层次。`local-candidate` 在 C1 的唯一候选上使用本地受控身份或 fixture/mocked external auth，验证认证语义、失败关闭、退出、会话恢复和桌面/移动布局；它必须明确标记为非生产、非真实 QA。`production` 由 DB 在当前实际发布上使用同一独立 QA 租户中的两个真实且隔离的身份，取得当次桌面和移动浏览器、角色隔离、恢复、发布读回和同运行证据。

## Problem

第 2 版虽要求“精确关联”，但仍允许实现把飞书返回邮箱交给平台账号查询，且公开会话缺少租户、工作区、正文权威和租户成员角色。该缺口会把同名、同邮箱、跨租户或错误工作区误认成可运营账号。页面存在、HTTP 200、静态截图、mock/fixture 或单次接口成功也无法证明用户、租户、成员角色、平台角色、维护权限和编辑权威属于同一规范会话。

## Expected outcome

1. 本合同编号保持 `MPE2E-AUTH-WEB`，版本为 3，状态为 `APPROVED`，测试基线为 `LOCKED`，就绪模式为 `FORMAL`，活动假设为 `none`，并绑定 OP01、K1 v1、D1 v1、D3 v1 的已接受记录和用户本次明确修复指令。
2. 当前生产基线只引用前端 `20260814T084319Z-media-login-canonical`、后端 `20260814T062408Z-opc-feishu-login` 及其本地只读清单，不再引用失效发布身份。
3. 飞书扫码和账号密码是并存的一等登录方式；两者成功后都必须由服务端返回并读回用户、`tenantId`、`workspaceMode`、`editorMode`、`bodyAuthority`、`memberRole`、平台 `role`、`maintainer`、会话到期和防跨站请求证明。前端拒绝缺字段、旧版或字段组合不一致的会话。
4. 飞书扫码绑定一次短时登录尝试和浏览器绑定值，只允许受信飞书 HTTPS 主机；过期、重放、绑定不匹配、跨尝试和状态未知均失败关闭。认证只消费服务端 OAuth/Broker 回读的 `tenant_key + open_id`，不得用邮箱、姓名、浏览器自报身份类型或默认租户认领内部账号。
5. 飞书身份必须唯一命中一个活跃组织 Binding、一个活跃外部成员身份、一个活跃租户成员关系、一个活跃内部用户和一个活跃组织租户。缺失、重复、停用、标识不匹配、跨租户、跨用户或非 `organization_lark/lark` 工作区不得创建会话。
6. 账号密码登录保持统一错误边界，并经过有效用户、有效租户、活跃成员关系和工作区组合校验。会话退出、过期、撤销、密码变更、用户停用、租户停用或成员关系停用后立即失效。
7. 普通用户、平台管理员、组织 owner/member 和维护权限按租户会话读回并在路由侧执行；跨租户、跨工作区、管理员能力不足、普通用户访问管理员入口、缺少防跨站请求证明或会话无效时拒绝。
8. 本地候选和生产收据有明确证据层次。生产收据必须拒绝 fixture/mock，要求当前活动发布、两个真实 QA 身份和当次桌面/移动浏览器证据；缺少真实 QA 身份只阻塞 DB。

## Non-goals

- 本合同不创建、读取、轮换、撤销或输出任何密码、Cookie、令牌、密钥、飞书授权码、私人正文或环境变量内容。
- 本合同不实现 C1，不修改 C2 候选、前后端源码、既有业务测试、数据库、远程主机、飞书对象、账号、发布或生产收据。
- 本合同不创建认证兼容层、旧发布回退、默认身份、跨租户查找、弱化门禁或第二份活动合同。
- 本合同不把页面存在、HTTP 200、静态截图、mock、fixture、未认证页面或单一 API 响应推断为认证后端能力完整。
- 本合同不把 `local-candidate` 证据提升为生产 QA 证据；真实 QA 身份、生产浏览器和人工运行结果由 DB 负责。

## Normal path

```gherkin
Given 唯一候选上有本地受控身份或 fixture/mocked external auth，且收据声明 local-candidate、非生产和非真实 QA
When 验收者分别走账号密码和飞书扫码入口，并读回稳定飞书身份、正式 Binding、租户成员、工作区、角色、失败关闭、退出、过期恢复和双视口字段
Then 两种登录均作为独立一等方式通过，且两者的租户、工作区、正文权威、成员角色、平台角色、维护权限、会话到期和防跨站请求字段属于同一规范会话契约
And 收据明确 mock_or_fixture，不能解锁或声明生产完成
```

```gherkin
Given 当前实际发布上有同一独立 QA 租户中的两个真实且隔离身份，且安全负责人提供当次脱敏生产收据
When DB 分别使用普通用户和管理员完成账号密码、飞书扫码、关联、路由权限和会话恢复验证，并读回当前发布与桌面/移动浏览器证据
Then 收据证明真实生产发布、两个真实 QA 身份、同运行 UI/API/后端读回和角色隔离
And production 收据拒绝 fixture/mock；缺少真实 QA 身份只保留 DB 阻断，不改变 C3、C4、C5 或 C1 的候选推进条件
```

## Exception paths

- 未设置 `MPE2E_AUTH_WEB_MODE`、模式不是 `local-candidate` 或 `production`、收据定位缺失、不是绝对 JSON 路径、文件不可读或 JSON 无效时，保护测试以固定非零状态失败关闭，不猜测身份，不读取其他路径。
- 账号密码和飞书扫码均不能通过页面存在或 HTTP 200 断言；任一成功缺少 `tenantId/workspaceMode/editorMode/bodyAuthority/memberRole/role/maintainer` 或字段组合不一致时失败关闭。
- 飞书扫码授权地址不是受信飞书 HTTPS 主机，登录尝试过期、重放、浏览器绑定不匹配、跨尝试或状态未知时失败关闭，不能创建会话，也不得泄露关联对象是否存在。
- 飞书 Broker/OAuth 缺少 `tenant_key` 或 `open_id`、返回邮箱/姓名但没有稳定标识、正式 Binding 缺失/停用、外部身份未关联/重复/停用、成员关系缺失/停用、内部用户或租户停用、标识不匹配、跨租户、跨用户或工作区不是 `organization_lark/lark` 时统一失败关闭；不可通过邮箱、姓名、共享账号、默认租户或跨租户查找恢复。
- 账号密码的用户、租户或角色校验失败时保持统一错误边界；不能用飞书扫码隐式回退，也不能因用户名存在与否改变跨租户可见性。
- 会话退出、过期、撤销、密码变更、用户停用、租户停用或成员关系停用后仍能读回受保护资源时失败关闭；个人会话进入组织专属路径、组织会话进入个人专属写入、普通用户进入管理员入口、管理员能力不足、维护路由权限不足、缺少防跨站请求证明或跨租户访问时拒绝。
- 缺少生产真实 QA 身份、当次生产浏览器、活动发布读回或真实同运行证据只阻塞 DB；不把缺失的 production 收据改写为 local-candidate 通过，也不提前阻塞 C3、C4、C5 或 C1。
- 保护测试缺少收据时保留稳定红灯；测试不联网、不登录、不执行收据内命令、不打印收据内容，只输出固定原因摘要。

## Invariants

- 账号密码和飞书扫码是两个独立的一等登录方式；任何一条不得成为另一条的隐式回退。
- 两种登录成功后的规范会话字段集合固定包含用户、租户、工作区、编辑模式、正文权威、租户成员角色、平台角色、维护权限、会话到期和防跨站请求证明，且必须由服务端会话读回，前端不得补默认值或猜测。
- 飞书扫码只能消费一次短时登录尝试和匹配的浏览器绑定值；过期、重放、绑定不匹配、跨尝试和未知状态不创建会话。
- 飞书身份只有 `tenant_key + open_id` 唯一命中活跃 Binding、外部身份、租户成员、内部用户和组织租户时才可发放会话；邮箱和姓名仅可展示，不具有认领权威。
- `personal_web/internal/web_edit` 与 `organization_lark/lark/lark_edit` 是仅有的有效组合；非目标工作区在业务写入或任务入队前拒绝，不能依赖前端隐藏。
- 普通用户、平台管理员、组织 owner/member 和维护权限按租户会话读回并在路由侧执行；HTTP 200、页面存在或静态截图不具有权限证明力。
- 会话退出、过期、撤销、密码变更、用户停用和租户停用后必须立即失效；失败重试不得产生未经授权的重复业务写入。
- `local-candidate` 必须是非生产、非真实 QA 并明确 `mock_or_fixture`；`production` 必须是实际活动发布、两个真实隔离 QA 身份和当次桌面/移动浏览器证据，不能把两层证据拼接。
- UI、API、后端资源、认证方式、租户、身份、角色、浏览器和发布证据必须属于同一脱敏运行引用；任一强制项缺失均非零退出。
- 收据字段名和值不得包含密码、Cookie、令牌、密钥、授权信息或私人正文；保护测试输出不含收据内容。

## Data impact

本合同的保护测试只读一份由安全负责人或候选负责人提供的脱敏 JSON 收据，不发起认证请求，不写业务数据，不改变生产状态。收据允许保存合同和 schema 版本、来源修订、候选或发布身份、脱敏稳定引用、角色/租户/会话布尔门禁、状态、计数和哈希格式字段；不允许保存密码、Cookie、令牌、密钥、授权码、私人正文或环境变量内容。真实 QA 账号的创建、续期、撤销、测试业务记录和清理由 DB 与安全负责人按独立租户策略负责，本合同不自动处理。

## Permissions

安全负责人负责生产 QA 租户、两个最小权限且可续期身份、凭据保管、续期、撤销和生产脱敏收据。候选负责人只能提供本地候选的受控身份或 fixture/mocked external auth 标记。普通用户只能验证自身租户范围；管理员只能验证明确的管理员用例；维护权限只能按会话读回执行。产品负责人判断登录方式可理解性、失败提示、角色边界和恢复路径；安全负责人判断飞书关联失败关闭、身份隔离和生产证据卫生。任何角色都不得把秘密写入命令、日志、合同、清单或返回。

## Performance and reliability

保护测试必须无网络副作用、无凭据依赖、可独立执行，并在缺少收据时立即失败。候选认证验证必须覆盖有限等待、一次性扫码尝试、绑定校验、统一会话、退出、过期、恢复、失败关闭和桌面/移动视口。生产运行必须覆盖两个真实身份、发布读回、后端资源读回、同运行关联、会话恢复和重复写入计数；无限加载、未处理前端异常、未知写入结果或无法关联运行均阻断 DB 验收。缺少真实生产身份或浏览器证据不能降低本合同要求，也不能把 DB 阻断前移为 C3、C4、C5 或 C1 阻断。

## Protected receipt interface

保护测试使用环境变量 `MPE2E_AUTH_WEB_SAFE_METADATA_FILE` 接收脱敏 JSON 定位，并使用 `MPE2E_AUTH_WEB_MODE=local-candidate|production` 选择证据层。收据不得含敏感键；因此账号密码登录在收据中使用 `auth_methods.account` 这个非秘密字段名表达，禁止写入密码值或以 `password` 作为 JSON 键。两种模式都必须提供以下字段和语义：

| Field group | Required proof |
| --- | --- |
| Contract and source | `schema_version: 3`、`contract_version: 3`、`evidence_level` 等于运行模式；`source_revision.frontend` 为 `20260814T084319Z-media-login-canonical`、`source_revision.backend` 为 `20260814T062408Z-opc-feishu-login`，并带两个本地清单的 `sha256:` 值 |
| First-class login | `auth_methods.account` 与 `auth_methods.feishu_qr` 都为 independent/pass/canonical session；两者共同读回 `user/tenant/tenant_id/workspace_mode/editor_mode/body_authority/member_role/role/maintenance_permission/session_expiry/csrf` |
| Feishu QR | 除一次性尝试、浏览器绑定和受信 HTTPS 外，`identity_source` 固定为 `tenant_key+open_id`，`email_or_name_claiming` 为 false；过期、重放、绑定不匹配、跨尝试和未知状态均拒绝且失败不创建会话 |
| Account linkage | `account_linkage` 证明一个活跃 Binding、一个有效内部账号、一个有效外部身份和一个有效租户成员关系；邮箱/姓名认领、跨租户和角色不一致均拒绝；`unlinked` 证明缺失/不唯一/停用失败关闭且不创建会话 |
| Tenant session and role | `tenant_session` 读回同一租户中的工作区、成员角色、平台角色、维护权限、会话到期和防跨站请求字段；`wrong_workspace` 证明个人/组织错工作区均在建会话或入队前拒绝；`cross_tenant` 和 `permission_denied` 证明跨租户及越权拒绝 |
| CSRF and lifecycle | `csrf` 证明防跨站请求证明读回、缺少证明拒绝、跨站拒绝；`session_lifecycle` 证明退出、过期、撤销、密码变更、用户停用和租户停用后立即失效 |
| Viewports | 顶层 `desktop` 与 `mobile` 各自 pass、有脱敏引用、认证和恢复证据、控制台错误计数为 0、无横向溢出 |
| Same-run guard | `correlation` 的 UI、API、backend resource 与 `run_ref` 相同且后端读回 pass；`completion_guard` 明确 HTTP 200、页面存在和静态截图均不能单独完成 |
| Hygiene | `metadata_only`、`no_sensitive_values`、`no_sensitive_keys` 均为 true；测试不执行收据命令、不访问收据之外路径、不打印 JSON |

`local-candidate` 还必须满足：`mock_or_fixture: true`、`metadata_origin: candidate-owner`、候选状态为 candidate、候选稳定引用为脱敏值、`evidence_boundary.production_claim/real_qa/promotable_to_production` 均为 false、身份模式为 controlled 且非真实 QA、候选发布身份为 candidate。该收据只证明候选语义。

`production` 还必须满足：`mock_or_fixture: false`、`metadata_origin: security-owner`、生产声明和真实 QA 标记为 true；同一独立租户内恰有两个不同稳定身份，分别是真实 ordinary-user 和 administrator；发布环境为 production、状态 active、读回 pass，前后端发布身份分别为当前生产基线；桌面和移动浏览器证据属于当次运行。fixture/mock、共享身份、历史发布、缺失活动发布或缺少真实身份均失败关闭。

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 合同为版本 3、APPROVED、LOCKED、FORMAL、无活动假设，并引用 OP01、K1 v1、D1 v1、D3 v1 和四个局部失效键 | Static | Automatic | Yes |
| AC-02 | 基线只引用当前前端/后端发布和本地只读清单，不引用失效发布或第二份认证事实来源 | Static | Automatic | Yes |
| AC-03 | 两条登录成功后都由服务端返回完整租户、工作区、正文权威、成员角色、平台角色和维护权限；前端拒绝缺字段、旧版和不一致组合 | Protected source and receipt gates | Automatic | Yes |
| AC-04 | 飞书扫码的一次性尝试、浏览器绑定、受信 HTTPS 主机、过期、重放、绑定不匹配、跨尝试和未知状态均按失败关闭执行 | Protected shell gate | Automatic | Yes |
| AC-05 | 飞书只用 `tenant_key + open_id` 唯一匹配活跃 Binding、外部身份、成员关系、内部用户和组织租户；邮箱/姓名、未关联、重复、停用、跨租户、跨用户和标识不匹配不发放会话 | Protected source and receipt gates | Automatic | Yes |
| AC-06 | 账号密码登录保持统一错误边界，并在会话退出、过期、撤销、密码变更、用户停用、租户停用或成员关系停用后立即失效 | Protected shell gate | Automatic | Yes |
| AC-07 | 仅允许两种工作区/正文权威/编辑模式组合；非目标工作区、跨租户、管理员能力不足、普通用户访问管理员入口、缺少防跨站请求证明或无效会话均拒绝 | Protected source and receipt gates | Automatic | Yes |
| AC-08 | local-candidate 验证两种登录、关联、角色、失败关闭、退出、过期恢复和桌面/移动布局，并明确为 mock/fixture、非生产、非真实 QA | Protected shell gate | local-candidate | Yes |
| AC-09 | production 验收拒绝 fixture/mock，要求当前实际活动发布、同一独立 QA 租户中的两个真实身份、当次桌面/移动浏览器和同运行读回；缺少真实身份只阻塞 DB | Protected shell gate | production | Yes |
| AC-10 | UI、API、后端资源、认证方式、租户、身份、角色、浏览器和发布证据属于同一脱敏运行引用，HTTP 200/页面存在/静态截图不能替代能力 | Protected shell gate | Both | Yes |
| AC-11 | 收据只含脱敏元数据，双模式均在缺收据、字段缺失、敏感键值或不安全证据时固定非零失败关闭且不打印收据 | Protected shell gate | Both | Yes |
| AC-12 | 中文人工清单只要求人工判断登录方式可理解性、飞书关联失败提示、角色隔离、恢复路径和生产证据卫生，不记录任何一次运行结果 | Human procedure | Human | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 产品负责人判断账号密码和飞书扫码两条入口是否都可理解且不会暗示隐式回退 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-01 | 产品负责人 | Yes |
| H-02 | 安全负责人判断飞书账号关联失败提示是否清楚、统一且不泄露关联或租户存在性 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-02 | 安全负责人 | Yes |
| H-03 | 产品负责人和安全负责人判断普通用户、管理员、维护权限和跨租户边界是否清楚且真实隔离 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-03 | 产品负责人和安全负责人 | Yes |
| H-04 | 产品负责人判断退出、过期、刷新、重新登录和失败恢复路径是否可理解，失败不被误认为完成 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-04 | 产品负责人 | Yes |
| H-05 | 安全负责人判断生产收据、双视口证据、发布读回和同运行引用是否保持脱敏、真实、可审计 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-05 | 安全负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| scripts/acceptance/test-mpe2e-auth-web.sh | 8bf6f33d0917948821f7a6ffbbd3e5f505002fb19d77c4f1d24b9c3261e6ab2e | AC-03 through AC-11; local-candidate/production receipt gates and stable missing-receipt red light |
| scripts/acceptance/test-mpe2e-auth-workspace-source.sh | 4e73a4b346095d2e9eea998c07562fb8066835dec644211f33afa6998a51430e | AC-03, AC-05, AC-07; source-level stable identity and canonical session gate |
| .codex-work/merge-candidate-v4/backend/tests/test_account_identity_workspace.py | cf5d382f065abeba8b6f21e4c01e8af68fe8137d3075910c2653e0f487cd314c | AC-03, AC-05, AC-07; backend stable identity, ambiguity and workspace tests |
| .codex-work/merge-candidate-v4/frontend/scripts/qa/checkMediaSessionContract.ts | 008f99af1d5eaa021a827e9a512edbc8d98c1cd328fdddbe9d43b8993a7f9eeb | AC-03, AC-07; strict complete session parsing |
| .codex-work/merge-candidate-v4/frontend/scripts/qa/checkMediaLoginContract.ts | 5b61cf52ae421e1dbe1d37d34c7c43ca3c492224aa28758c4ae40eb265d24206 | AC-03, AC-07; login landing consumes the complete session contract |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | 合同校验器与冻结验证命令 | acceptance-contract.md；MPE2E-AUTH-WEB v3 protected hashes | Automatic | Yes |
| AC-02 | 合同静态断言与冻结基线哈希 | acceptance-contract.md；candidate baseline manifest | Automatic | Yes |
| AC-03 | 两个独立登录分支和完整 canonical session 字段断言 | source gate；后端单测；两个前端 QA；safe receipt auth_methods | Automatic | Yes |
| AC-04 | 飞书尝试、浏览器绑定、受信 HTTPS 和失败关闭断言 | scripts/acceptance/test-mpe2e-auth-web.sh；safe receipt failure_closure | Automatic | Yes |
| AC-05 | `tenant_key + open_id`、Binding、外部身份、成员、工作区及邮箱/姓名禁用断言 | source gate；后端单测；safe receipt account_linkage/unlinked | Automatic | Yes |
| AC-06 | 统一账号密码错误边界和会话生命周期断言 | scripts/acceptance/test-mpe2e-auth-web.sh；safe receipt session_lifecycle | Automatic | Yes |
| AC-07 | 工作区组合、租户角色、维护权限、CSRF 和拒绝路径断言 | source gate；两个前端 QA；safe receipt tenant_session/wrong_workspace/role/csrf/permission_denied | Automatic | Yes |
| AC-08 | `MPE2E_AUTH_WEB_MODE=local-candidate` 收据模式、mock_or_fixture 和候选边界断言 | scripts/acceptance/test-mpe2e-auth-web.sh；local-candidate safe receipt | Automatic | Yes |
| AC-09 | `MPE2E_AUTH_WEB_MODE=production` 收据模式、真实身份、当前活动发布和双视口断言 | scripts/acceptance/test-mpe2e-auth-web.sh；production safe receipt | Automatic | Yes |
| AC-10 | 同运行 UI/API/backend resource、读回和完成边界断言 | scripts/acceptance/test-mpe2e-auth-web.sh；safe receipt correlation/completion_guard | Automatic | Yes |
| AC-11 | 缺收据、敏感卫生和固定非零失败关闭断言 | scripts/acceptance/test-mpe2e-auth-web.sh | Automatic | Yes |
| AC-12 | 五项人工判断 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-01；#h-02；#h-03；#h-04；#h-05 | Human | Yes |
| H-01 | 两条登录入口可理解性 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-01 | Human | Yes |
| H-02 | 飞书账号关联失败提示和信息卫生 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-02 | Human | Yes |
| H-03 | 租户角色、维护权限和跨租户隔离 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-03 | Human | Yes |
| H-04 | 退出、过期、恢复和失败不伪成功 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-04 | Human | Yes |
| H-05 | 生产证据卫生和同运行可审计性 | acceptance/human/MPE2E-AUTH-WEB/checklist.md#h-05 | Human | Yes |

## Exploratory testing

自动门禁通过后，产品负责人可以探查窄屏长标题、双登录入口切换、同邮箱不同飞书成员、同名成员、停用 Binding、错租户 `open_id`、个人/组织错工作区、扫码临界过期、重复扫码、慢网、刷新恢复和维护权限边界。探查只记录理解性和未预料行为，不替代保护测试，也不把候选结果改写为生产结果。

## Production monitoring and rollback

DB 监控账号密码登录失败率、飞书稳定身份匹配失败率、Binding/成员停用拒绝、跨租户与错工作区拒绝、角色混用、会话过期恢复失败、CSRF 拒绝、前端合同拒绝、生产收据缺失和发布身份漂移。出现邮箱/姓名认领、跨租户读回、错工作区写入、未关联身份建会话、敏感内容进入收据、未知后端结果或发布身份不一致时，立即阻止认证验收和相关发布。

## Risks and open decisions

当前没有未决产品选择。用户本次指令、K1 v1、D1 v1 和 D3 v1 是批准证据。当前未验证项是本地代码尚未由 v3 源码门禁验证，C1 尚未完成本地认证浏览器运行，DB 尚未取得两个真实 QA 身份和当次生产桌面/移动浏览器收据；这些是分层验收事项，不能互相替代。
