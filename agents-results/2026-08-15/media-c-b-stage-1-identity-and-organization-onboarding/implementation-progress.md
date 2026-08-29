# 第一阶段实施进度

## 当前结论

针对阶段一真实 PostgreSQL 空库验证暴露的组织接入阻塞，候选代码已完成以下前向修复：

- 新增 `cm1-043-stage1-multi-tenant-primary-user`：移除 `tenants.primary_user_id` 的旧全局唯一约束，保留每个用户最多一个个人工作区的局部唯一索引，并移除只适用于旧 `lark_tenant_bindings` 的身份外键；Stage 1 当前绑定外键和 ACTIVE 状态检查仍然有效。
- 个人密码登录只选择 `personal_web / internal` 租户；组织会话不能修改个人密码，避免同一用户拥有多个组织租户后产生凭据歧义或越权修改。
- 真实空库已按 `001` 到 `043` 完整安装并通过迁移校验；同一用户同时拥有个人租户和组织租户时，组织属性、owner membership、Stage 1 binding、owner `open_id` 身份及确认幂等回执均可回读。个人密码登录命中个人租户，组织会话密码修改被拒绝。

本增量只产生本地候选和一次性 PostgreSQL 验证证据，不代表节点正式接受、飞书回读、浏览器验收、部署或生产发布。候选源清单和 `candidate-manifest.json` 已按修复后源码重新绑定；阶段一正式状态仍以节点级独立接受和全局门禁为准。

本 SSOT 已完成第 4 版结构修订。K1 到 K6 六项局部决定已经接受；K6 已在 2026-08-16 冻结个人账号注册、验证、登录、找回、会话、存量账号和客服边界。第 23 波共享本地候选证据已登记到 IL1、I3、C1，但只证明账号唯一关系和工作区失败关闭，不改变三个节点的阻塞状态（BLOCKED）。GA1 与 G1 已分别完成人工初始化和只读失败关闭验证并接受。B 的唯一 OpenAPI 合同和 7 项本地合同测试已经通过并正式接受；M1 的唯一补丁清单、双基线独立哈希绑定、逐文件文件归属、补丁顺序、冲突检测和两次确定性重建通过 32 项冻结测试，M1 正式接受。MA1 已完成发布增量（Release 1A）迁移静态验证（27 passed、3 subtests passed）；I1 的统一认证入口源质量检查（QA）与整合候选完整 build:media 已通过，且包含重新锁定后的个人工作区 deletion fixture 门禁，但 I1 仍只能保持本地 VERIFIED，真实浏览器、部署、邮件/飞书和生产验收仍待完成。I2 与 T1 的本地生命周期、公共路由和共享合同验证均已通过，共享路由验收合同（T1-AUTH-ROUTES）保护测试基线已锁定，二者仍标记为已验证（VERIFIED）。I4/I5 的 deletion fixture 变更已由用户和阶段一验收 owner 批准并重新锁定，三项聚焦测试和整合 build:media 均已通过；这只解除合同变更阻塞，不替代 I3 的正式接受，因此两节点仍保持 BLOCKED。以上均不是正式接受（ACCEPTED）：真实数据库回读、恢复、节点级独立接受、浏览器、邮件、飞书、部署、生产和设备验收仍未完成。本地机器、结构、复杂度、视图、中文可读性、运行时技能来源及带全局归档审计的统一 bundle validator 均已通过；本包快照 `--check` 与全局 Obsidian 归档审计也已通过。不调度第 11 次修订（Revision 11），也不把本地合同、验收运行或候选重建测试描述为外部或生产证据。

阶段百分比口径（2026-08-18）：代码实现与远端发布 `100%`；本轮远端认证入口稳定性修复与验证 `100%`。这里的 `100%` 只表示本轮已声明的代码、发布和运行守卫范围已经完成，不等同于第一阶段正式 SSOT 完成。阶段一正式 SSOT 当前仍为 `partial/blocked`：E11/D3A、节点级独立接受、真实邮件/飞书、认证浏览器/设备和完整外部验收仍未关闭。

2026-08-18 远端代码发布与稳定性回执：本地整合候选清单 `334b5133bd8e3cf03716757028bf584d03ff798b4d8dc69eb0de3edc267ed571` 绑定前端来源清单 `0d8a9aae1b9b178342d39059e5b167f191048e78f7c261ef0d1ee15b4f11066f` 与后端来源清单 `24a3e1aaf5b99663926f90f6bcbb3ff23729b2a8d8791da044893137c9872908`；阶段一测试 `208 passed`，前端 `npm run build:media` 和运行器配置门禁通过。`ubuntu@106.52.146.37` 当前激活前端 `20260818T-stage1-auth-entry-r10`，后端运行 `openclaw-tag-router-media-tenant-20260818T-stage1-auth-media-oauth-r9`，发布协调文件一致；公开索引哈希为 `6a9d49013b0888c83c6fe557ab96e68ed93bc60c4be03b1d6f7d87a059ea72d9`。20:08 的独立只读回读确认 `healthz=200`、`readyz=200`，登录入口和 `media.login.js` 为 `200`，未登录会话为 `401`，空认证请求为合同要求的 `400`，退役密码路径为 `404`，OAuth callback 无参数为 `400`；Nginx `-t` 通过且 canonical/已加载配置哈希均为 `9e0c8f99770fc9a825b43697b2b779abe53f29b073c83638486c17423fa14128`。定时 watchdog 本次 `Result=success`，状态 `failureCount=0`、`checks=70`、`repairs=[]`，其自测和登录面合同均通过。该证据仍只证明代码发布与运行稳定性，不前移节点级独立接受，也不证明生产数据库写入、真实邮件/飞书、认证浏览器或设备验收；完整回执见 `evidence-remote-release-20260818/remote-readback-20260818T2008.json`。

## 状态台账

| Task ID | Stage | Versions | State | Attempt | Owner | Guard ID | Blocking reason | Evidence | Unlocks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | A | 5/5/4/5 | ACCEPTED | 1 | user and planning authority | G-DOC | n/a | EV-A-CURRENT | A1 |
| A1 | A | 5/5/4/5 | ACCEPTED | 1 | main orchestrator | G-DOC | n/a | EV-A1-CURRENT | B, E11, GA1, K, K1, K2, K3, K4, K5, K6 |
| K | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K-CURRENT | B |
| K1 | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K1-CURRENT | I1, I2, IL1 |
| K2 | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K2-CURRENT | CA, CB |
| K3 | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K3-CURRENT | P9 |
| K4 | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K4-CURRENT | I6, MA1 |
| K5 | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K5-CURRENT | I7, I9 |
| K6 | A | 5/5/4/5 | ACCEPTED | 1 | user | G-DOC | n/a | EV-K6-CURRENT | I1, I2, IL1 |
| B | A | 5/5/4/5 | ACCEPTED | 1 | main orchestrator | G-DOC | n/a | EV-B-CURRENT | I1, I2, I9, M1, MA1, T1 |
| GA1 | A | 5/5/4/5 | ACCEPTED | 1 | execution environment owner | G-DOC | n/a | EV-GA1-CURRENT | G1 |
| G1 | A | 5/5/4/5 | ACCEPTED | 1 | execution environment owner | G-DOC | n/a | EV-G1-CURRENT | I1, I2, I9, M1, MA1, MB1, T1 |
| E11 | A | 5/5/4/5 | BLOCKED | 0 | canonical acceptance owner | G-DOC | canonical D3A 尚未 ACCEPTED | pending | CA, CB |
| M1 | B | 5/5/4/5 | ACCEPTED | 1 | main orchestrator | G-PHASE1 | n/a | EV-M1-CURRENT | CA, CB, I1, I2, I9, MA1, MB1, T1 |
| MA1 | B | 5/5/4/5 | VERIFIED | 1 | main orchestrator | G-PHASE1 | Release 1A 冻结迁移静态验证通过（27 passed, 3 subtests passed）；真实数据库回读、恢复和发布验收仍待完成 | EV-MA1-CURRENT | I3, I6 |
| T1 | B | 5/5/4/5 | VERIFIED | 1 | main orchestrator | G-PHASE1 | 本地共享合同与门禁验证通过（15 passed；路由一致性 GREEN）；保护测试基线已 LOCKED，正式接受与人工验收仍待完成 | EV-T1-CURRENT | CA, CB, I8, I9, P10, P6, P9 |
| I1 | B | 5/5/4/5 | VERIFIED | 1 | main orchestrator | G-PHASE1 | 统一认证入口源 QA 与整合候选完整 build:media 已通过（含个人工作区 deletion fixture 门禁）；真实浏览器、部署、邮件/飞书和生产验收仍待完成 | EV-I1-CURRENT | I3 |
| I2 | B | 5/5/4/5 | VERIFIED | 1 | main orchestrator | G-PHASE1 | 本地生命周期与公共路由验证通过（20 passed, 16 skipped；共享路由验收合同（T1-AUTH-ROUTES）保护基线已 LOCKED）；正式接受、真实邮件/飞书和生产验收仍待完成 | EV-I2-CURRENT | I3, IL1, P9 |
| IL1 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I2 ACCEPTED | related: EV-MPE2E-C5-R3-SHARED-LOCAL; node acceptance pending | C1, I3 |
| I3 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I1, I2, IL1, MA1 ACCEPTED | related: EV-MPE2E-C5-R3-SHARED-LOCAL; node acceptance pending | I4, I5, I6, I7, P10 |
| I4 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I3 ACCEPTED；个人工作区受保护 deletion fixture 合同已获批准并重新锁定，普通内容删除仍属于后续内容生产范围 | pending | C1 |
| I5 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I3 ACCEPTED | pending | C1, I7, I8 |
| I6 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I3, MA1 ACCEPTED | pending | C1, I7, I8 |
| I7 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I3, I5, I6 ACCEPTED | pending | I8, P5, P8 |
| I9 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 T1 ACCEPTED | pending | C1, I8 |
| I8 | B | 5/5/4/5 | BLOCKED | 0 | runtime acceptance owner | G-PHASE1 | 等待 I5, I6, I7, I9, T1 ACCEPTED | pending | C2 |
| C1 | C | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 IL1, I4, I5, I6, I9 ACCEPTED | related: EV-MPE2E-C5-R3-SHARED-LOCAL; node acceptance pending | CA |
| C2 | C | 5/5/4/5 | BLOCKED | 0 | independent acceptance owner | G-ZERO | 等待 I8 ACCEPTED | pending | CA, MB1 |
| CA | C | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 E11, C1, C2, T1 ACCEPTED | pending | DA1 |
| DA1 | D | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-STATIC | 等待 CA ACCEPTED | pending | DB1 |
| DB1 | D | 5/5/4/5 | BLOCKED | 0 | runtime acceptance owner | G-RELEASE | 等待 DA1 ACCEPTED | pending | DC1 |
| DC1 | D | 5/5/4/5 | BLOCKED | 0 | independent acceptance owner | G-ZERO | 等待 DB1 ACCEPTED | pending | CB, DA |
| MB1 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 C2 ACCEPTED | pending | P1, P3, P9 |
| P1 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 MB1 ACCEPTED | pending | P2, P6 |
| P2 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P1 ACCEPTED | pending | P3, P6 |
| P3 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P2, MB1 ACCEPTED | pending | P10, P5, P6, P9 |
| P5 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P3, I7 ACCEPTED | pending | P6 |
| P6 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P1, P2, P3, P5, T1 ACCEPTED | pending | P7, P8 |
| P7 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P6 ACCEPTED | pending | C3 |
| P8 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P6, I7 ACCEPTED | pending | C3 |
| P9 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I2, P3, MB1, T1 ACCEPTED | pending | C3, P10 |
| P10 | B | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 I3, P3, P9, T1 ACCEPTED | pending | C3 |
| C3 | C | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 P7, P8, P9, P10 ACCEPTED | pending | CB |
| CB | C | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-PHASE1 | 等待 E11, DC1, C3, T1 ACCEPTED | pending | DA2 |
| DA2 | D | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-STATIC | 等待 CB ACCEPTED | pending | DB2 |
| DB2 | D | 5/5/4/5 | BLOCKED | 0 | runtime acceptance owner | G-RELEASE | 等待 DA2 ACCEPTED | pending | DC2 |
| DC2 | D | 5/5/4/5 | BLOCKED | 0 | independent acceptance owner | G-ZERO | 等待 DB2 ACCEPTED | pending | DA |
| DA | D | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-DOC | 等待 DC1, DC2 ACCEPTED | pending | DB |
| DB | D | 5/5/4/5 | BLOCKED | 0 | main orchestrator | G-DOC | 等待 DA ACCEPTED | pending | DC |
| DC | D | 5/5/4/5 | BLOCKED | 0 | independent acceptance owner | G-DOC | 等待 DB ACCEPTED | pending | n/a |

## 当前就绪前沿

| Frontier | Task ID | Eligibility | Unsatisfied hard dependencies | Active assumptions | Resource decision |
| --- | --- | --- | --- | --- | --- |

## 波前指标

| Metric | Value | Basis |
| --- | --- | --- |
| ready-frontier-width | 0 | 机器源中的 READY 节点动态计算 |
| formal-ready | 0 | B 与 GA1 的 readiness_mode 均为 FORMAL |
| conditional-ready | 0 | 没有条件就绪节点或活动假设 |
| global-completeness-barriers | 10 | CA/CB 各自三段发布验收及 DC1->CB |
| critical-path-length | 27 | 按机器源硬依赖计算的最长节点路径 |

## 下一步执行前沿

当前没有新的就绪（READY）节点：MA1、I1、I2、T1 的本地实现/验证已登记，共享路由验收合同（T1-AUTH-ROUTES）的保护基线已锁定，但它们仍需节点级独立接受后才能解锁 IL1、I3、I6 及后续波次。I4/I5 的个人与组织工作区 deletion fixture 合同已获批准并重新锁定，三项聚焦测试已通过；这只解除合同变更阻塞，不替代 I3 的正式接受，因此不得提前推进 I4、I5 或 C1。I9、外部测试、生产发布和第 11 次修订（Revision 11）仍不在本轮启动范围；第 11 次修订继续只在原规范 SSOT 中推进。

## 第二阶段移交边界

C1 已接受（ACCEPTED）后第二阶段可启动个人内容支线；C3 已接受（ACCEPTED）后可启动组织内容与写入器（Writer）支线；DC2 已接受（ACCEPTED）后才可同步第一阶段最终发布投影。第二阶段拥有人工智能写入器（Writer），第一阶段 I7 只提供组织资源解析。
