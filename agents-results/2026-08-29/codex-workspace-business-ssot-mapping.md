# Codex 工作空间容器业务修改与 SSOT 对照

更新时间：2026-08-29（中国标准时间）

## 当前结论

- 权威源码：`production-reconciliation-20260825/.codex-work/p1-implementation-20260828/integration` 的 `main`。
- 当前本机 `main` 与 `origin/main` 均为 `f5e5bf6`，工作树干净。
- 已完成的候选提取、候选分支清理和历史快照搬迁不再作为当前待处置项记录。

## 当前保留目录

| 容器/提交 | SSOT 对应 | 与当前主线的矛盾 | 处置 |
|---|---|---|---|
| `production-reconciliation-20260825` | P1/Stage-2 复核承载容器 | 外层 detached 快照、嵌套 `integration/main`、工作容器不是同一 Git 身份。 | 只以嵌套 `integration/main` 归因；外层不作为源码主线。 |
| `.codex-work/archived/historical-snapshots-20260829/merge-candidate-v4` | 生产 E2E C3/C4、前端候选 | 无 Git 提交证明，且早于后续主线，覆盖会回退行为。 | 只读历史验收/差异证据，不作合并来源；证据索引见 `agents-results/2026-08-29/historical-snapshots-archive.md`。 |
| `.codex-work/archived/historical-snapshots-20260829/production-baseline-20260814T084319Z` | 2026-08-14 发布基线 | 发布身份和当前主线/部署不一致。 | 只证明当时发布，不证明当前状态。 |
| `.codex-work/archived/historical-snapshots-20260829/reviews-inspector-layout-20260815` | 前端合同、截图和构建检查 | 引用 `master/e027ad10`，与当前 `main` 无当前归因关系。 | 只读历史验收快照。 |
| `agents-results` | SSOT、测试和证据记录 | 文档状态不能越级为源码、部署或生产状态。 | 权威文档/证据层，不是代码合并来源。 |
| `runtime` | PostgreSQL/运行态数据 | 数据文件无源码提交、哈希或变更说明。 | 运行证据层；迁移/清理需单独授权。 |

## 当前未关闭的验收边界

- Stage-2 真实认证会话、真实数据库、真实人工智能任务、真实飞书写入/回读及浏览器/设备验收仍需独立证据。
- P1 `BIZ-05`、`CD-13` 仍需要真实账号、近期作品链接和非空轮询回执；测试或候选提交不能关闭它们。

## 归因规则

1. 候选只能以当前 `main` 为基线逐文件、逐符号去重，拆成原子提交并跑定向测试。
2. 提交对象、同名文件、候选元数据或截图不能互相替代；只有 Git 祖先关系才能证明“已合入”。
3. 文档、静态测试、夹具和历史快照不得升级为部署或生产验收证据。
4. 目录时间仅作辅助；优先 Git 提交时间，其次元数据 `observed_at`，并保留不确定性。
