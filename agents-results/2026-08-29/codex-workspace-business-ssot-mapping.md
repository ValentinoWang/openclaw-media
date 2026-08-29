# Codex 工作空间容器业务修改与 SSOT 对照

更新时间：2026-08-29（中国标准时间）

## 结论

本次盘点的对象是 `.codex-work` 下除 `archived-worker-worktrees-20260829` 外的保留容器。判断依据依次为：Git 提交或候选元数据、实际修改文件、文件/提交时间，以及修改日期前后七天内的 SSOT 与证据文件。

需要特别区分两件事：

1. 当前权威源码仓库是 `production-reconciliation-20260825/.codex-work/p1-implementation-20260828/integration` 的 `main`，其工作树干净；`origin/main` 已同步到 `fa33bc2`，包含 H00 身份绑定、账号监控 API 合同边界、Stage-2 Feishu 原子加固、Stage-2 严格鉴权和 Stage-2 runtime 原子加固。
2. 某个容器里存在 Stage‑2 同名文件，不等于该容器的加固提交已经进入当前 `main`。四个 `stage2-hardening-*` 是独立仓库，提交对象不在当前 `main` 历史中。

## 时间窗口与权威文档

| 修改时间或候选时间 | 前后七天内匹配的 SSOT/证据 | 作用 |
|---|---|---|
| 2026-08-13 至 2026-08-20 | `agents-results/2026-08-13/media-production-e2e-closure/ssot-development-paths.md` | 第一阶段生产认证、任务、数据库、飞书、网页回读和验收边界 |
| 2026-08-15 | `agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/ssot-development-paths.md` | 第一阶段身份、组织接入、Binding 与跨阶段门禁 |
| 2026-08-15 | `agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md` | Stage‑2 个人正文、组织飞书正文、人工智能上下文、唯一写入路由和失败关闭 |
| 2026-08-19 至 2026-08-20 | `agents-results/2026-08-19/STAGE2-HANDOFF-20260819.md`；`agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/evidence-stage2-hardening-20260820.md` | Stage‑2 候选交接、加固范围和 172 项聚焦测试证据；明确未完成真实生产/飞书验收 |
| 2026-08-26 至 2026-08-29 | `agents-results/2026-08-29/media-p1-remaining-development-paths/ssot-development-paths.md` 与 `implementation-progress.md` | P1 遗留项、监控表 schema、身份预检、空轮询状态及生产证据边界 |

## 容器逐项映射

| 容器 | 实际身份/修改 | 对应业务含义 | 对应 SSOT 节点 | 与当前主线/SSOT 的矛盾点 | 结论 |
|---|---|---|---|---|
| `stage2-hardening-auth-20260820` | 独立仓库 `codex/stage2-handoff-final-20260819`，提交 `d0d399a`（2026-08-29）；修改 `stage2_server_context.py` 与鉴权测试，共 `579` 行新增/删除变更 | 服务端会话、请求凭据、Cookie/Bearer 冲突拒绝、别名冲突拒绝、令牌空白拒绝、租户/Binding/世代一致性校验 | Stage‑2 `S1`（服务端人工智能执行上下文）、`T1`（共享合同与验收）；部分涉及 `S5` 能力副作用授权 | 候选要求“Cookie 与 Bearer 同时出现即拒绝、令牌空白不再自动清理、别名冲突失败关闭”；当前主线已有“取值优先级”和部分租户校验。若直接合入，会改变兼容行为并重复实现；SSOT 还要求真实认证证据，候选测试不能替代。 | **有业务价值，但未合入当前 `main`**。当前主线已有部分租户/Binding 校验，不能整笔合并；应提取严格鉴权增量并重跑定向测试 |
| `stage2-hardening-feishu-20260820` | 独立仓库提交 `948b36b`（2026-08-29）；修改 Feishu 外部文档与生产组装，共 `473` 行变更 | 当前组织 Binding 下的飞书目标解析、可信 HTTPS 域名、空间/父节点、凭据世代、写后回读与 Binding 变化处理 | Stage‑2 `O2`（按组织 Binding 写入飞书）、`O3`（成果与远端文档绑定）、`O4`（写后回读）、`O5`（编辑后再回读） | 候选把可信飞书地址、Binding 解析和回读约束前移到生产组装；主线已有同名生产组装文件但实现版本不同。候选默认地址、字段别名和锁的来源若直接覆盖，可能改变租户目标；而 SSOT 禁止全局凭据回退，必须逐项证明没有引入回退。 | **有业务价值，但未合入当前 `main`**。这是组织正文唯一权威和错误 Binding 失败关闭的候选加固，需与主线现有实现去重后再决定 |
| `stage2-hardening-persistence-20260820` | 独立仓库提交 `ae0b614`（2026-08-29）；10 个文件，共 `1755` 行变更 | 重复 JSON 字段拒绝、外部文档幂等占用、并发进行中状态、SQLite schema/权限/路径失败关闭、个人成果和运行收据持久化 | Stage‑2 `S4`（成果登记与回读状态机）、`C5`（个人内部成果写入）、`O3`（组织成果绑定）、`S`（共享汇合） | 候选同时改 HTTP、Gateway、Runtime、Feishu、个人存储和生产工厂，和另外三个候选改同一入口；整笔合入会产生重复定义及相互覆盖。候选的 SQLite 持久化也不能被误写成 SSOT 要求的真实数据库验收。 | **有业务价值，但不能整体合并**。与 Feishu、运行时、鉴权候选严重重叠，且变更量最大；应拆出持久化合同、幂等 claim 和路径校验三个原子单元 |
| `stage2-hardening-runtime-20260820` | 独立仓库提交 `76f8725`（2026-08-29）；HTTP、Gateway、Runtime 与测试，共 `518` 行变更 | Stage‑2 HTTP 入口的错误码映射、重复字段拒绝、鉴权错误转译、个人/组织路由入口和租户路由边界 | Stage‑2 `S3`（唯一文档写入路由）、`T1`（共享 OpenAPI 与验收）、`C8/O6`（两条端到端汇合） | 候选把旧接口和 Stage‑2 接口的错误响应分成两套，并新增重复字段拒绝；主线已有 HTTP 入口和错误处理。若未按路径边界合并，可能把旧接口响应格式一并改掉，违反“仅 Stage‑2 收紧”的隐含兼容边界。 | **有业务价值，但未合入当前 `main`**。与 persistence/auth 候选共享相同入口文件，必须按错误码和解析逻辑去重后提取 |
| `mediaclaw-stylekit-publish` | 独立 Git 仓库；`2026-08-19` 有 MediaClaw runtime/试点默认值/部署同步提交，`2026-08-29` 有 `23ba056`（Content‑OS 验收证据门）和 `f533317`（账号监控 schema 校验）；另有未跟踪 `mediaclaw-style/` 许可与治理文件 | 一部分是 Stage‑2/MediaClaw 运行与试点工具，一部分是 P1 的 Content‑OS 证据门和账号监控 schema；未跟踪目录是独立样式包元数据 | 2026-08-15 Stage‑2 `S3/T1`；2026-08-29 P1 `BIZ-05/CD-13` 证据链、账号监控 schema 节点；试点/部署部分对应第一阶段生产闭环 | 同一分支混有 8 月 19 日 Stage‑2 运行提交和 8 月 29 日 P1 提交，时间与业务阶段不一致；`23ba056`/`f533317` 与当前主线同主题但提交对象不同，不能凭主题判为已合入；未跟踪样式包没有 SSOT 节点、测试或发布身份，不能当业务代码。 | **混合容器，不能整体迁移**。`23ba056`、`f533317` 属于当前 P1 主线同主题但该仓库提交不在主线；`mediaclaw-style/` 未跟踪，暂不能当业务实现 |
| `production-reconciliation-20260825` | 外层是 2026-08-25 生产复核快照，当前为 detached；真正权威源码在其嵌套 `integration/main`。外层新增的 `.codex-work/` 只是工作容器目录 | 生产候选复核、Stage‑2 遗留分支收口、P1 证据与集成工作树承载 | 2026-08-15 Stage‑1/Stage‑2 SSOT；2026-08-29 P1 SSOT | 外层 detached 快照、嵌套 `integration/main` 和外层工作容器不是同一 Git 身份；把外层 HEAD 当成主线会把复核文档和源码提交混在一起。 | **承载容器，不是独立业务改动源**。只应以嵌套 `integration/main` 的提交和证据归因 |
| `merge-candidate-v4` | 无 Git 根；前端候选元数据记录任务 `C3-FRONTEND-MERGE`，观测时间 2026-08-16，基线为 2026-08-14 发布快照；包含源清单、合并出处和保护文件哈希 | 前端认证、组织/个人工作区、结算状态、素材解析和页面合并候选 | 2026-08-13 生产 E2E SSOT 的 C3/C4；2026-08-15 Stage‑1 的身份/组织接入节点 | 候选元数据声明了受保护文件和合并方式，但没有 Git 提交可证明这些内容进入主线；候选时间早于后续主线变更，直接覆盖会回退认证/页面行为。 | **历史发布候选，不是当前未提交源码**。可作为前端验收证据和差异来源，不能直接当成当前 `main` 修改 |
| `production-baseline-20260814T084319Z` | 无 Git 根；生产基线快照，`RELEASE_ID=openclaw-tag-router-media-tenant-20260814T062408Z-opc-feishu-login` | 2026-08-14 生产登录/租户发布身份及前后端基线 | 2026-08-13 生产 E2E SSOT；2026-08-15 Stage‑1 身份与组织接入 SSOT | 发布编号、快照内容和当前 `main` 不是同一身份；用该快照证明当前部署会把 8 月 14 日发布状态错误延伸到 8 月 29 日。 | **只读生产基线**。它证明当时发布身份，不证明后续 Stage‑2 或 P1 代码已部署 |
| `reviews-inspector-layout-20260815` | 无 Git 根；构建元数据显示分支 `master`、提交 `e027ad10`、观测时间 2026-08-15，包含前端合同、脚本和截图验收材料 | 前端页面结构、布局、角色页、合同脚本和可视化检查 | 2026-08-13 生产 E2E SSOT 的前端/验收节点；2026-08-15 Stage‑1 前端身份与组织页面 | 构建记录引用 `master/e027ad10`，而当前权威仓库使用另一条 `main` 历史；页面合同/截图只能证明该构建候选，不能证明源码已同步或生产已接受。 | **历史验收快照**。可用于证明当时页面候选和检查范围，不能视为当前主线改动 |
| `agents-results` | SSOT、执行波次、验收、证据文件集合，不是源码工作树 | 提供业务范围、节点合同、证据等级和状态投影 | 上述三组 SSOT，按各自 artifact 日期归属 | 文档可能记录候选“已实现”或测试通过，但 SSOT 明确区分 source、test、fixture、deployed、production、device；把文档状态直接当源码/生产状态会越级。 | **权威文档/证据层**，不应作为业务代码合并来源 |
| `runtime` | PostgreSQL/运行数据目录（非 Git 源码仓库） | 运行态数据库与临时数据 | 生产 E2E 与 Stage‑2 数据库/恢复验收条款 | 运行态数据没有源码提交、候选哈希或变更说明；把数据库文件变化归因到某个业务容器会混淆运行证据与实现变更。 | **运行态数据，不是代码修改**；任何迁移或清理必须另行授权 |

## 当前主线关系

- 当前 `main` 已包含 `b87bf91`、`a1ab425`、`85f6608`、`4a41061`、`ada2963`、`7ed45ab`、`fa33bc2`；其中 `ada2963` 只提供明确的 `503 monitor_unavailable` 合同边界，尚未接入真实 Feishu H00 adapter，不能视为生产监控已可用。
- `7ed45ab` 将 Cookie/Bearer 冲突、空白令牌、重复会话 Cookie、服务端别名冲突限定在 Stage-2 请求上下文；旧端点兼容取值优先级和空白清理由回归测试锁定。`fa33bc2` 仅收 Stage-2 重复字段拒绝、幂等 claim 和 source 稳定化；均不代表真实认证或生产验收完成。
- `integration/main` 当前存在 `stage2_server_context.py`、`stage2_external_document.py`、`stage2_production_factory.py`、`stage2_runtime.py`、`stage2_gateway.py`、`stage2_personal_store.py` 等基础文件，但四个独立加固提交 `d0d399a`、`948b36b`、`ae0b614`、`76f8725` 都不是当前 `main` 的祖先提交，因此不能写成“已经合入 main”。
- `23ba056`、`f533317` 也不是当前 `main` 的祖先提交；`f533317` 与当前账号监控 schema 主题重叠，按 superseded/diff 处理，不整体迁移。
- 四个 `stage2-hardening-*` 候选仍然不能整体合并；如需提取，必须以当前 `main` 为基线逐文件、逐符号去重后形成原子提交。

## 远端候选分支

六个未合入主线的提交已按原提交对象分别推送到远端，仅用于审查和差异提取，不代表接受或发布：

| 提交 | 远端分支 | 处置边界 |
|---|---|---|
| `d0d399a` | `candidates/stage2-hardening-auth-d0d399a` | 候选；不可整体合并 |
| `948b36b` | `candidates/stage2-hardening-feishu-948b36b` | 候选；不可整体合并 |
| `ae0b614` | `candidates/stage2-hardening-persistence-ae0b614` | 候选；不可整体合并 |
| `76f8725` | `candidates/stage2-hardening-runtime-76f8725` | 候选；不可整体合并 |
| `23ba056` | `candidates/mediaclaw-stylekit-content-23ba056` | 仅作 diff 来源，不视为主线实现 |
| `f533317` | `candidates/mediaclaw-stylekit-monitor-f533317` | 与当前 schema 重叠，按 superseded/diff 处理 |

这些分支没有合并请求或主线发布含义；任何提取都必须以当前 `main` 为基线，拆成原子改动并单独通过定向测试。
- Stage‑2 SSOT 本身仍要求真实认证会话、真实数据库、真实人工智能任务、真实飞书写入/回读、浏览器/设备和独立终验；2026-08-20 加固证据只达到聚焦测试与浏览器夹具层级。
- P1 的 2026-08-29 主线进度仍把 `BIZ-05`、`CD-13` 的真实生产账号、近期作品链接和轮询回执列为非空生产证据缺口；容器中的测试或候选提交不能关闭这两项。

## 归因规则

1. 需要合并时，先以当前 `integration/main` 为基线，对独立仓库提交逐文件、逐符号去重，再形成原子提交并跑定向测试。
2. 仅有候选元数据、构建清单或截图的容器只能标为“候选/证据”，不能标为“源码已合入”。
3. 仅有目录修改时间不能证明业务修改日期；优先采用 Git author/commit date，其次采用元数据 `observed_at`，最后才使用目录 mtime，并在表中保留不确定性。
4. 本报告不改变任何 SSOT 节点状态，也不把静态测试、夹具测试或历史生产快照升级为真实外部系统验收。
