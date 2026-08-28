# 审计后开发核验报告（2026-08-28）

> 核验对象：`pipeline-full-audit.md`（2026-08-27 全量审计，288 条）发布后合入 main 的新开发——openclaw-media `0138eff`（Media Web P0 修复）与两仓的分支合并清理、photo-content-os `11f832d`（独立性加固）。
> 验证方式：全部走本地 CI / 本地测试套件（不依赖 GitHub Actions），并与审计时留存的失败基线逐条比对。

## 一、结论

**基本按原文档开发，方向与修法正确；本地全量验证后发现并修复了 1 个新引入的测试回归；另有 4 处设计层改进空间与 31 个 P0 仍待路线图推进。**

- `0138eff` 精确对应审计 P0 条目 **CRF-01 / CRF-02 / CRF-03**，三条全部真实修复（逐条核验见下），并带 8 条新回归测试。
- 两仓均已把工作分支合入 main 并删除全部余支，符合既定的单 main 约定；`11f832d` 为合理的独立性加固（不对应审计具体条目，方向属工程健康）。
- 审计 P0 记分板：**34 条 → 3 条关闭、31 条开放**。路线图批次 1（商业闭环起搏）尚未动工，仍是最高优先。

## 二、`0138eff` 逐条核验（对照审计条目）

### CRF-01 · server_cli 启动 TypeError —— ✅ 已修复

组合方式：`media_web_tasks.py` 改为 facade（125 行）+ `media_web_tasks_core.py`（1433 行，唯一实现）。facade 的 `MediaWebTaskService` 子类吸收 `repository` / `content_flow_client` 两个组合期依赖，`tenant_model_gateway` 透传给 core（core 签名原生支持）。`server_cli.py:291` 的调用现与签名完全匹配，启动不再抛 TypeError。

### CRF-02 · MediaWebTaskError 缺 status/details —— ✅ 已修复

单一错误类型不变，facade 以 `property` 挂载 `status`（15 个错误码 → HTTP 状态映射表）与 `details`（透出 issues），HTTP 层读取的属性有了单一事实来源。

### CRF-03 · 上传路由永久 500 stub + 前端契约漂移 —— ✅ 已修复

永久 500 的英文 stub 被替换为真实隔离上传路径（`create_upload`，含幂等键 header/body 双重一致性校验、schemaVersion=3 强校验）。已逐键核对前端实际发送的 payload（`mediaWebApi.ts:652-657`：`schemaVersion:'3' / filename / contentBase64 / idempotencyKey`，幂等键同时置于 header）——与服务端契约完全对齐，`mimeType` 服务端设为可选与前端不发送的现状兼容。

### 新引入的回归（本次已修复）

v3 上传处理器的安装挂在 Service **构造时**全局 monkey-patch `OpenClawHttpHandler`，导致测试结果依赖用例执行顺序：全套件运行时 `test_media_business_http.py::test_upload_creation_fails_closed_without_durable_idempotency_receipts` 失败（其断言的是已退役 stub 的「恒 500」行为，单跑通过、跟在 compat 测试后必挂）。

本报告随附修复：该测试改为**显式安装 v3 处理器**（与生产启动路径一致，消除顺序依赖），断言更新为真实契约的 fail-closed 行为——非法 body → 400 `invalid_request`、header/body 幂等键不一致 → 400，两种情况均不落任何数据。改后单跑、随 compat 连跑、全套件三种顺序均通过。

## 三、`11f832d`（photo-content-os）核验 —— ✅ 合理

- 新增 AST 级独立性门禁：扫描 `99_System_OpenClaw` 全部 `.py` 保证零 `openclaw_media` 强制 import，`requirements-dev.txt` 无该包；可选包缺失时 `compatibility()` 优雅报告 `openclaw_media_not_installed` 而非崩溃。
- `runtime_paths.runtime_dir` 对显式传入的根不再 `resolve()`（尊重调用者语义），带新测试。
- 本地 CI 全绿（见下）。

## 四、本地验证记录（全部本地，未用 GitHub Actions）

| 门禁 | 结果 | 与审计基线比对 |
|---|---|---|
| `openclaw-tag-router/tests/test_media_web_task_compat.py`（0138eff 新增） | **8 passed** | 新增覆盖 |
| openclaw-tag-router 全套件（同一排除集） | 修复回归后 **49 failed / 1284+ passed** | **与既有失败基线逐条一致**（回归修复前为 50） |
| 仓库根 tests 全套件（同一排除集） | **51 failed / 208 passed** | **与既有失败基线逐条一致** |
| photo-content-os `42_run_local_ci.sh` | **Local CI passed.**（125 单测 + 契约 + doctor + demo 流水线） | 全绿 |

（49/51 个既有失败为审计条目 CT-A1 等记录的主干漂移，根因与修法已在审计文档测试债章节归类，不属本批开发引入。）

## 五、仍存的改进空间

### 5.1 本批提交自身（建议尽快做）

1. **上传处理器接线方式**：运行时 patch `OpenClawHttpHandler` 属过渡方案——建议把 v3 实现移入 `http_api` 正式路由/组合处，删除 patch-on-construct 机制（同时可清掉审计 CRF-17 的六个死 handler，其中含被替换前的旧上传实现）。
2. **facade 的 `dir()` 全量再导出**：把 core 的 stdlib import 一并导出进 facade 命名空间，静态分析与 IDE 不可见——建议改为显式 `from .media_web_tasks_core import (...)` 白名单。
3. **提交说明与实际不符的小偏差**：commit message 称 "reconcile frontend upload v3 payload" 但未改前端文件（实际是服务端向前端契约对齐）。结果正确，仅表述易误导后来者。
4. **photo-content-os 快照钉死**（审计 LB-09 相邻问题）：独立性加固未处理 `upstream_commit` 钉死旧提交 `f0460b4c` 的再生成路径，跨仓契约演进时仍会静默漂移。

### 5.2 审计 P0 记分板（34 条）

| 状态 | 条目 |
|---|---|
| ✅ 本批关闭（3） | CRF-01、CRF-02、CRF-03 |
| ⏳ 开放（31） | 商业闭环断链族（BIZ-01/02/03、CD-06/09/12、CPO-K14/K15/N14、RT-01/02/04、LB-01/02/05、LP-17）、注入面族（gap1-01/02/03）、档期族（SCHED-01/02/03、CC-01）、多维断链族（CD-03/04、CPO-K06）、工程族（CT-A1、CT-A6、LB-04、LH-01） |

### 5.3 建议的下一步（不变，摘自审计路线图）

**批次 1 · 商业闭环起搏**仍最优先：复盘加载创作稿归因（CD-06）、回链字段落表（CPO-N14）、daily_poll 评论原话回流（RT-04）、发布链生产者（CD-12）、过期档期治理（SCHED-01/02 + 解锁钉死行为的测试 SCHED-11）、热榜持久化进创作（CD-05）。批次 2-5 顺序见 `../20260827/pipeline-full-audit.md` 第四章。

## 六、文件与提交对照

- 审计原文档：`docs/production-reconciliation/20260827/pipeline-full-audit.md`（288 条，本报告不改写其状态字段——以本报告的记分板为最新状态）。
- 本批被核验提交：openclaw-media `0138eff`（含合并 `2d59bcc`/`e5350b1`）、photo-content-os `090b949`/`11f832d`。
- 本报告随附修复：`openclaw-tag-router/tests/test_media_business_http.py` 上传 fail-closed 测试更新（消除顺序依赖 + 对齐 v3 契约）。
