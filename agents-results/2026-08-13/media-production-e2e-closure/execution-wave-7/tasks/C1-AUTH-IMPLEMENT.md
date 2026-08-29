# C1-AUTH-IMPLEMENT: 当前活动基线上的认证网页实现

## 执行身份与版本

- SSOT 节点：`C1`（只能建议 `IMPLEMENTED` 或 `VERIFIED`，不得自行设为 `ACCEPTED`）
- 直接父节点：`B1`、`B4`
- 版本元组：计划 2 / 依赖图 2 / 接口冻结 2 / 节点合同 2 / SSOT schema 1
- 验收合同：`agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md`
- 当前合同版本：1；状态 `APPROVED`；测试基线 `LOCKED`
- 决定引用：`media.no-inference-completion-boundary@1`、`media.qa-identity@1`
- 失效键：`contract.authenticated-web`、`decision.qa-identity`、`integration.authenticated-web`
- 保护性测试：`scripts/acceptance/test-mpe2e-auth-web.sh`
- 保护性测试 SHA-256：`b52c61bbeaf71ad3db874a5493479d8d0d0ae5a53362cadc2ebe67cc1976c204`
- 当前活动前端基线：`20260814T0118CST-d1-remediation-attempt2-r2`
- 当前活动后端基线：`openclaw-tag-router-media-tenant-20260814T010229CST-d1-remediation-attempt2-r2`

## 目标

在当前活动前后端的隔离副本上完成 C1 认证网页代码，使同一独立质量验收租户中的普通用户和管理员可以分别真实登录、读回自身角色与租户、访问各自页面，并能够由生产 QA 工具证明加载、数据、真实空集合、拒绝、网络错误、恢复、会话失效和重新登录。工具必须生成只含脱敏稳定引用的收据，不能把 HTTP 200、页面存在或静态截图当作完整证明。

## 权威输入

- 前端候选根：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/c1-20260814T020215CST/frontend`
- 后端候选根：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/c1-20260814T020215CST/backend`
- 旧候选参考（只读）：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/c1-stage`
- 合同、人工清单、保护性测试及 `.ssot` 机器记录均为只读。

旧候选只可作为差异参考。必须逐项对照当前活动基线，保留仍满足当前代码契约的改动，修正不再适用的内容，不能把旧目录整体覆盖到新候选。

## 唯一允许写入范围

- `.codex-work/c1-20260814T020215CST/frontend/media.login.html`
- `.codex-work/c1-20260814T020215CST/frontend/scripts/qa/checkMediaAuthProduction.ts`
- `.codex-work/c1-20260814T020215CST/frontend/production-qa/**`
- `.codex-work/c1-20260814T020215CST/backend/openclaw_app/account/auth.py`
- `.codex-work/c1-20260814T020215CST/backend/openclaw_app/account/repository.py`
- `.codex-work/c1-20260814T020215CST/backend/tests/test_account_auth.py`
- 结构化返回文件。

修改现有文件或创建上述新文件时使用 `apply_patch`。不要修改候选清单、发布标识或协调元数据；这些由发布汇合负责人在代码冻结后生成。

## 禁止范围

- 不得修改 `scripts/acceptance/test-mpe2e-auth-web.sh`、验收合同、人工清单、绑定、索引、`.ssot/**`、主 SSOT 或实施进度。
- 不得修改 `.codex-work/c1-stage`、当前活动前端源快照、本地其他候选或远端任何文件。
- 不得连接、写入或迁移生产数据库，不得创建或修改 QA 身份，不得登录生产网页，不得发布、重启、切换或回滚服务。
- 不得读取、输出、记录或推测任何密码、Cookie、令牌、私钥、完整环境文件或私人正文。
- 不得新增兼容路径、旧身份回退、双写或测试绕过。
- 不得启动子代理、`spawn_agent` 或其他 worker。

## 必须实现的行为

1. 后端登录租户解析必须以活动的 `tenant_members` 关系为依据，使同租户内不是 `tenants.primary_user_id` 的管理员成员可登录；成员关系失效时登录失败关闭，已有会话在下次解析时撤销。
2. 多个活动租户关系不得被任意选择。只有唯一主租户关系可以消除歧义，否则失败关闭。
3. 保持原有主用户登录、密码校验、会话轮换、角色动态读回和租户隔离行为；补充实现自有单元测试。
4. QA 身份管理工具必须能够幂等建立或续期同一隔离租户中的普通用户和管理员，凭据只从权限为 `0600` 的私有环境文件或进程环境读取，所有正常输出均不得包含秘密。
5. 生产认证 QA 工具必须在运行前后从 PostgreSQL 读回身份关系和会话，并确认认证浏览器运行没有增加业务表写入；信息架构查询使用明确表别名，不能依赖歧义列名。
6. 浏览器脚本必须使用真实普通用户与管理员身份，覆盖桌面 `1440x1000` 和移动 `390x844`；逐页截图，统计控制台错误与横向溢出。
7. 空态必须由 QA 租户的真实 `/api/assets` 空集合证明；非空时失败，禁止通过路由伪造空集合。
8. 拒绝态必须同时证明普通用户页面被重定向且管理员 API 返回 403。
9. 错误态可以有界中止真实 dashboard API；恢复态必须解除故障后通过页面“重新读取”触发真实 200。故障注入自身不能导致未过滤的控制台错误计数。
10. 会话失效必须由后端辅助工具真实撤销当前会话，随后 API 返回 401，再重新登录并读回正常会话；不得只清浏览器存储模拟过期。
11. 收据必须符合锁定接口的全部字段、脱敏引用、同次运行关联、幂等和卫生约束；不得写入密码、会话值或完整响应正文。
12. 登录页需要的交互修复必须只基于当前 `media.login.html`，保持现有视觉系统、键盘可用性、错误反馈和响应式布局。

## 最低验证

按照冻结验证命令执行，并在结构化返回中逐项列出退出码。额外执行你认为必要且不涉及生产写入的聚焦检查。由于本机缺少真实 PostgreSQL 和生产 QA 身份，真实数据库测试、发布、生产浏览器与保护性收据门禁列为待主线程完成，不能伪造通过。

## 停止条件

- 当前合同、保护性测试哈希或活动基线不符：`scope-conflict` 或 `interface-freeze`，停止写入。
- 需要改合同或降低 AC：`authority-conflict`，停止写入。
- 需要生产凭据、数据库写入、服务切换或外部副作用才能继续：`permission`，停止并返回最小阻塞。
- 候选代码与本地可运行验证均通过：建议 `IMPLEMENTED`，`acceptance_self_check: pass`；明确列出尚未运行的生产验证。

## 结构化返回要求

除监督器要求字段外，返回：任务编号、版本元组、wrapper、实际读写路径、每个命令与退出码、逐项 AC 覆盖、保护性测试前后哈希、候选差异摘要、未验证项、共享资源影响、风险、偏差等级和停止条件。不得包含秘密。
