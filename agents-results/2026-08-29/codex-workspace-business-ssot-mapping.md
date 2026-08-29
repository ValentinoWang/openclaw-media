# Codex 工作空间容器业务修改与 SSOT 对照

更新时间：2026-08-29（中国标准时间）

## 当前结论

- 权威源码：`production-reconciliation-20260825/.codex-work/p1-implementation-20260828/integration` 的 `main`。
- 当前本机 `main` 与 `origin/main` 均为 `8140669`，工作树干净。
- `d0d399a`、`948b36b`、`ae0b614`、`76f8725`、`23ba056`、`f533317` 均不是 `main` 的祖先提交。
- 部分能力已用新的原子提交进入 `main`：Feishu（`943e874`、`18a616a`、`109e8ff`）、身份 transport（`7ed45ab`）、身份 A1/A2（`828111e`、`5bf62d9`）、runtime（`fa33bc2`）、H00 绑定（`4a41061`）和监控 API 边界（`ada2963`）。这不等于原候选提交已合入，也不等于真实生产验收完成。
- 四个 `stage2-hardening-*` 候选均不得整体合并；auth 与 persistence 已完成原子提取，runtime 已确认 superseded。

## 容器处置矩阵

| 容器/提交 | SSOT 对应 | 与当前主线的矛盾 | 处置 |
|---|---|---|---|
| `stage2-hardening-auth-20260820` / `d0d399a` | Stage-2 S1/T1/S5：请求身份、租户与 Binding 校验 | 原候选把严格 fail-closed 与旧端点兼容逻辑混在一起；直接覆盖会改变旧端点行为。 | 不整体合并。transport 已由 `7ed45ab` 提取，A1/A2 已由 `828111e`、`5bf62d9` 提取；候选仍作差异来源，真实认证未验收。 |
| `stage2-hardening-feishu-20260820` / `948b36b` | Stage-2 O2-O5：Binding 目标、写入、写后回读 | 两个源文件与当前主线逐字节一致，diff=0。 | `fully-absorbed`；归档候选分支。 |
| `stage2-hardening-persistence-20260820` / `ae0b614` | Stage-2 S4/C5/O3：幂等、状态机、成果持久化 | 同时改 HTTP/Gateway/Runtime/Feishu/Store，和其余候选撞入口；SQLite 证据不能冒充真实数据库验收。 | 不整体合并。已提取 P1 `2514c7c`、P2 `d8763c8`、P3 `b0f9816` 三个原子单元；真实数据库仍未验收。 |
| `stage2-hardening-runtime-20260820` / `76f8725` | Stage-2 S3/T1/C8/O6：路由、错误码、租户边界 | 旧端点与 Stage-2 错误语义混杂，可能扩大收紧范围。 | `superseded`；收尾 diff 仅格式/注释差异，行为已由主线 `fa33bc2` 覆盖。 |
| `mediaclaw-stylekit-publish` / `23ba056`、`f533317` | Stage-2 运行工具；P1 Content-OS/账号监控 | `f533317` 已被 `a1ab425`/`85f6608`/`4a41061`/`ada2963` 完整覆盖；`23ba056` 的结构化验收收据要求已由 Content OS 生命周期合同拦截非结构化发布推进。 | 两者均 `superseded`；归档候选分支。样式目录仍不得进入业务主线。 |
| `production-reconciliation-20260825` | P1/Stage-2 复核承载容器 | 外层 detached 快照、嵌套 `integration/main`、工作容器不是同一 Git 身份。 | 只以嵌套 `integration/main` 归因；外层不作为源码主线。 |
| `.codex-work/archived/historical-snapshots-20260829/merge-candidate-v4` | 生产 E2E C3/C4、前端候选 | 无 Git 提交证明，且早于后续主线，覆盖会回退行为。 | 只读历史验收/差异证据，不作合并来源；证据索引见 `agents-results/2026-08-29/historical-snapshots-archive.md`。 |
| `.codex-work/archived/historical-snapshots-20260829/production-baseline-20260814T084319Z` | 2026-08-14 发布基线 | 发布身份和当前主线/部署不一致。 | 只证明当时发布，不证明当前状态。 |
| `.codex-work/archived/historical-snapshots-20260829/reviews-inspector-layout-20260815` | 前端合同、截图和构建检查 | 引用 `master/e027ad10`，与当前 `main` 无当前归因关系。 | 只读历史验收快照。 |
| `agents-results` | SSOT、测试和证据记录 | 文档状态不能越级为源码、部署或生产状态。 | 权威文档/证据层，不是代码合并来源。 |
| `runtime` | PostgreSQL/运行态数据 | 数据文件无源码提交、哈希或变更说明。 | 运行证据层；迁移/清理需单独授权。 |

## 远端候选分支

以下分支已推送到远端，仅供审查和差异提取，均未合并到 `main`：

| 提交 | 分支 | 状态 |
|---|---|---|
| `d0d399a` | `archived/candidates/stage2-hardening-auth-d0d399a` | A1/A2 已提取，归档；原候选引用保留供审计 |
| `948b36b` | `archived/candidates/stage2-hardening-feishu-948b36b` | fully-absorbed，归档 |
| `ae0b614` | `archived/candidates/stage2-hardening-persistence-ae0b614` | 已拆 P1/P2/P3，归档；原候选引用保留供审计 |
| `76f8725` | `archived/candidates/stage2-hardening-runtime-76f8725` | superseded，归档；原候选引用保留供审计 |
| `23ba056` | `archived/candidates/mediaclaw-stylekit-content-23ba056` | superseded，归档 |
| `f533317` | `archived/candidates/mediaclaw-stylekit-monitor-f533317` | superseded，归档 |

## 当前未关闭的验收边界

- Stage-2 真实认证会话、真实数据库、真实人工智能任务、真实飞书写入/回读及浏览器/设备验收仍需独立证据。
- P1 `BIZ-05`、`CD-13` 仍需要真实账号、近期作品链接和非空轮询回执；测试或候选提交不能关闭它们。

## 归因规则

1. 候选只能以当前 `main` 为基线逐文件、逐符号去重，拆成原子提交并跑定向测试。
2. 提交对象、同名文件、候选元数据或截图不能互相替代；只有 Git 祖先关系才能证明“已合入”。
3. 文档、静态测试、夹具和历史快照不得升级为部署或生产验收证据。
4. 目录时间仅作辅助；优先 Git 提交时间，其次元数据 `observed_at`，并保留不确定性。
