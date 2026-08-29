# 第一阶段来源笔记

## 固定输入

| Source | Path | SHA-256 | Use |
| --- | --- | --- | --- |
| 事实审计 | `/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/公共开发集/public/2026-08-15/media-c-b-product-fact-audit/media-c-b-login-document-organization-audit.md` | `d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98` | 当前产品、源码、发布与缺口事实 |
| 三阶段编排 | `/Users/vsiyo/.codex/attachments/63a93708-8bfe-43ce-8dc7-cb079775f3b0/pasted-text.txt` | `a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8` | 用户确认的阶段边界与工程并行思路 |
| 结构审查 | `/Users/vsiyo/.codex/attachments/61fef357-7ee9-4a1a-a348-06db749a7466/pasted-text.txt` | `3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5` | Release 1A/1B、开放决定、运行配置与恢复语义修正 |
| 第 4 版结构复核 | `/Users/vsiyo/.codex/attachments/7ebe320f-6551-4294-8d1c-2b452a9b6b2b/pasted-text.txt` | `97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471` | 自举死锁、E11 硬边、认证合同、迁移 owner、Writer 关闭、晋升基线和成员安全修正 |
| Revision 11 权威 | `/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/公共开发集/media/2026-08-07/media-visual-fix/agents-results/2026-08-07/media-cb-web-document-preview/ssot-development-paths.md` | `0f621ee97d66fb3ec4be7b8be7bc306fda4a269f81382ad232afb1187c16ac47` | D1-D3A 合同与正式节点状态 |
| Revision 11 进度 | `/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/公共开发集/media/2026-08-07/media-visual-fix/agents-results/2026-08-07/media-cb-web-document-preview/implementation-progress.md` | `a30bdf105e5b2b8367ff19603e19a28ad787e9743fef033e10a270a65d53d5db` | 最新实施进度交叉核对 |
| 账号与工作区共享本地候选 | `agents-results/2026-08-13/media-production-e2e-closure` | `f1ac786573e76aa40a0d69a10aab6dba5bd6a345596242d93f37773b59f45bcb` | 只读复用外部博主隔离、客户账号唯一正式关系和工作区失败关闭证据；不提升 IL1、I3、C1 状态 |

项目根目录不是 Git 仓库。本包以这些文件校验值作为规划基线；M1 已经建立逐文件基线快照、patch manifest、ownership、应用顺序、冲突检测和确定性重建。后续节点必须消费该协议，不能用目录覆盖代替合并。

## 用户决定

| 决定节点 | 批准日期 | 已接受选择 | 机器权威 |
| --- | --- | --- | --- |
| K1 | 2026-08-15 | 个人使用平台独立认证，不要求飞书；交付文档在云端保存和预览 | `.ssot/nodes/K1.json` |
| K2 | 2026-08-15 | 发布后向全部合格用户开放，使用单一路径硬切换 | `.ssot/nodes/K2.json` |
| K3 | 2026-08-15 | 普通成员首次服务端飞书授权时以 `open_id` 即时建立 | `.ssot/nodes/K3.json` |
| K4 | 2026-08-15 | 近期活动属于租户私有数据 | `.ssot/nodes/K4.json` |
| K5 | 2026-08-15 | 第一阶段排除人工智能文档写入，统一写入路由由第二阶段拥有 | `.ssot/nodes/K5.json` |
| K6 | 2026-08-16 | 用户名或已验证邮箱加密码登录；注册必须验证邮箱；找回链接三十分钟单次有效；八小时不透明会话；重置后撤销全部旧会话；飞书身份只允许主动授权并二次确认后绑定 | `.ssot/nodes/K6.json` |

用户决定来自当前 Codex 任务中的明确答复；独立文件输入仅提供问题背景。每个机器决定记录均保存批准日期、适用范围和存量处理，不把背景附件的推荐误写成用户批准。

## 决定集状态

六项局部产品决定已经全部接受，当前没有待拍板问题。`K6` 明确要求注册和验证不自动登录、找回不暴露账号是否存在、密码重置撤销全部旧会话和未使用找回令牌；旧 Media 密码登录和改密接口继续返回 `404`，并禁止按邮箱或姓名自动合并平台账号与飞书身份。

## 已确认事实

- Revision 11 当前是 `25/29 ACCEPTED`；唯一合法后缀是 `D1 -> D2 -> D3P -> D3A`。
- Revision 11 的节点、执行调度、状态和证据仍由 canonical SSOT 独占。本包没有 R1-R4 节点或 canonical 证据写入路径。
- Revision 11 候选已经包含统一正文结构、C Web/B 飞书编辑权威和服务端工作区模式，但未完成生产终验。
- 当前生产登录不等于个人/组织可信分流；当前会话缺少完整租户类型、正文权威、成员角色和 Binding 信息。
- 当前个人注册成功后直接签发 Media 会话；K6 已将目标合同改为先进入待验证状态，邮箱验证成功后仍需从新个人入口登录。该目标是已接受产品合同，不是当前运行态已实现事实。
- Binding schema 能表达组织凭据和资源落点，但主运行路径仍依赖部署级全局凭据。
- 当前 Pilot 脚本硬编码特定组织与账号，成员同步没有完整分页，并包含不可产品化的秘密处理；完整目录同步不再阻塞 Release 1A/1B。
- 已知租户边界问题包括近期活动全表读取；已知工作区数据问题包括旧 `ordinary` 写入与约束不一致。
- 自助安装、管理员确认、普通成员即时建立、资源初始化、可续接 Provision 和反向生命周期尚未形成真实产品闭环。
- `/Users/vsiyo/.codex/workers/` 只有通用 L1-L4 与 LW wrapper，尚无实现、静态验证、外部测试、生产发布和独立只读五类可验证运行配置。
- 第 23 波共享本地候选绑定前端 200 项与后端 609 项；非数据库、迁移和 PostgreSQL 门禁已通过。该证据不包含第一阶段显式身份关联、完整会话解析、部署或生产读回，因此 `IL1`、`I3`、`C1` 继续阻塞。

## 阶段拆分

- 第一阶段：Release 1A 身份与既有组织 Pilot；Release 1B 自助 Provision、普通成员即时建立与最小撤销；完整目录成熟化只保留 Stage 1C 交接，不进入本机器图。
- 第二阶段：个人内容生产、C/B 人工智能上下文与 Writer 分流；Writer 明确不属于 I7。
- 第三阶段：完整组织权限、审核、商业化、迁移、复杂删除和经营分析。仅记录排除边界，不生成 SSOT。
