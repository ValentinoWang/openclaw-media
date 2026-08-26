# 非 HTTPS 范围验收执行记录 — 2026-08-26

- 分支：`claude/frontend-ui-interaction-polish-0lywkr`（基于 `main@d25c70a`）
- 执行环境：一次性 Linux 容器、Python 3.11 venv、Node 22 / npm 10、Playwright Chromium（预装 1194 版本，
  经本地符号链接适配 Playwright 1.61 期望的 1228 目录布局）
- 执行身份：仓库内自动化，非生产主机；未接触生产服务、数据库、Feishu 或任何外部系统

## 1. 范围声明

依据 `docs/production-reconciliation/20260826/main-consolidation.md` 的 Explicit non-claims，以下事项因为
**没有公网域名（HTTP 无法升级为 HTTPS）** 而被显式排除，本记录不对其作任何结论：

- HTTPS / TLS 证书与公网 origin；
- OAuth 回调（需要 https 回调地址）；
- Secure Cookie 与 HSTS；
- 公网浏览器最终证据（Playwright 生产登录态截图）；
- 正式 Stage-2 SSOT 验收比例的变更（保持 3/32 = 9.4%，由授权验收负责人另行处理）。

其余可以在源代码与本地运行时完成的验收全部执行并记录如下。

## 2. 修复后达成的门禁状态

### 2.1 Router 受保护发布套件（CI `main-integrity-gate` 所列 12 个套件）

```text
tests/test_production_reconciliation_planner.py
tests/test_production_reconciliation_regressions.py
tests/test_production_reconciliation_contract_boundary.py
tests/test_production_release_manifest.py
tests/test_stage2_release_gate.py
tests/test_stage2_gateway.py
tests/test_stage2_production.py
tests/test_stage2_server_context.py
tests/test_stage2_runtime.py
tests/test_stage2_runtime_hardening.py
tests/test_stage2_feishu_hardening.py
tests/test_stage2_main_integration.py
```

结果：**127 passed**（合并前 main 上 `test_stage2_gateway` 3 项、`test_stage2_production` 2 项失败——
`/stage2/*` HTTP 布线在主干合并时丢失，本分支恢复后全部通过）。

Planner 1.1 绑定哈希（CI 同款校验）：amendment 与冻结测试 SHA-256 均与
`.github/workflows/main-integrity-gate.yml` 中的期望一致。

### 2.2 仓库级 Python 测试（`python3 -m pytest tests`）

结果：**208 passed / 51 failed（全部失败均为部署主机独有资源缺失，见 §3）**，
另有 3 个测试模块因引用仓库中不存在的源文件而无法收集（见 §3 源缺口）。

### 2.3 Router 全量套件（`pytest openclaw-tag-router/tests`）

结果：**1276+ passed / 68 failed**（相对修复前 102 failed）。剩余失败属于合并前既有的业务逻辑漂移
（测试期望与合并进 main 的实现版本不一致，如 SocialArchive `forced_category`、商单交付 tenant UUID 校验、
DAILY_LLM 错误码文案等），以及 §3 所列部署主机资源缺失，不属于本轮 HTTPS 无关验收失败的新增项。

### 2.4 Web / Creator Studio 门禁

- `npm run lint`：exit 0（仅 warning）。
- `npm run build:media` 全链路（登录合同 → 注册 → 能力启动 → 设计系统合同 → ordinary 呈现 → 缩略图 →
  关系呈现 → 最近任务呈现 → 回执过期 → 删除恢复（Chromium）→ 确认合同 → 删除意图生命周期（Chromium）→
  tsc → vite build → release 标签）：**通过**。
  修复项：能力注册表根目录在仓库布局下的解析、任务结算投影 schema/服务端字段、
  `mediaWebUploadSchema` 缺失导出。

### 2.5 人工验收清单状态

`acceptance/human/PR-REL-{MANIFEST,PLANNER,READBACK}/checklist.md` 均为“已批准”，PLANNER 含 1.1 修正案；
其执行结果记录（runs/<run-id>/result.md）按合同须由指定人工角色签署，自动化不代签。项目级索引
`acceptance/index.md` 保持无 run（等待人工验收执行后由生成器更新）。

## 3. 已识别且已记录的缺口（不阻塞本记录范围，逐项列明）

### 3.1 部署主机独有资源（本仓库无法自包含）

| 资源 | 影响的测试 |
| --- | --- |
| `/home/ubuntu/docs/ai-harness/media-model-v2-contract.json`（冻结数据模型合同） | tests/test_media_model.py（17）、test_track_repository.py（7）、test_media_writer_tenant_ownership.py（3）、selfmedia 相关 5 项 |
| `/home/ubuntu/docs/ai-harness/media-creation-run-detail-contract.json` | tests/test_creation_run_detail.py（14） |
| `/home/ubuntu/docs/ai-harness/openclaw-media-product-contract.json`（产品合同 JSON 原件；仓库仅有生成镜像） | router tests/test_device_job_r1.py、test_media_archive_r2.py |
| `/home/ubuntu/.config/codex/openai.env` 等主机凭据/配置 | tests/test_sync_openclaw_agent_models.py（3）、test_id_business_llm.py 部分 |
| `/home/ubuntu/obsidian-*`、`openclaw-feishu-reminder/`、`reminder` 模块、person-profile-skill | router 7 个模块 + repo 2 项 |

### 3.2 主干合并时丢失、仓库中任何位置均不存在的源文件（源缺口）

- `selfmedia/creation/inspiration.py`（tests/test_creation_inspiration.py 引用）；
- `scripts/migrate_media_vault_v2_tenants.py`（tests/test_u13_media_vault_one_shot_contract.py 引用）；
- `scripts/qa/check_media_growth_visibility_backfill.py` 与 `check_media_growth_display_backfill.py`
  （tests/test_media_growth_v2.py 以上级目录相对路径引用）。

这三组文件无法凭空重建（会伪造合同/实现），列为后续 reconciliation 轮次的回收目标。

### 3.3 既有业务逻辑漂移（router 全量套件 68 项）

聚类：`test_llm_required_routes`（6）、`test_commercial_delivery`（5）、`test_track_router`（4）、
`test_deepmath_approval_core`（4）、`test_activity_daily_llm`（4）等。特征是测试断言与合并进主干的实现
版本（新旧混合）不一致，需要按能力逐条裁决“以测试为准还是以实现为准”，超出本轮验收范围，留待
capability owner 处理。

## 4. 本轮对源代码的验收性修复清单

1. 恢复 `/stage2/personal`、`/stage2/organization` HTTP 布线与 `OpenClawApp.process_stage2`（含请求域
   凭据上下文与稳定错误码映射）；
2. `SessionPrincipal` 恢复 Stage-1 共享会话事实字段；`If2RequestContext` 接受 workspace resolution；
3. 回退口令登录/改密路由在配置 Feishu 登录时按合同 404；
4. 信任代理转发 host/proto 在临时回环端口重写下接受配置的公网 origin；
5. `MediaWebTaskService` 接受 IF2 层转发的操作者身份参数；任务投影补齐结算字段；
6. 前端 `mediaWebTaskSchema` 补齐结算投影与 `mediaWebUploadSchema` 导出；
6a. `/openclaw/media/api/session` 服务端投影对齐前端严格 v2 契约：`bindingState/installationState`
    改为 `organizationConnection/installationConnection` 枚举投影并补充 `organizationName`
    （个人会话为 null；`qa:media-session-contract` 明确拒绝 `bindingState` 键，修复前服务端响应
    会被前端 schema 整体拒绝）；
7. 测试与 QA 可移植性：router `tests/conftest.py`、产品合同仓库内回退路径、`openclaw_bots.json`
   仓库 SSOT 解析、5 个仓库级测试的仓库相对路径、`selfmedia.py` 重复子命令修复、
   `checkContextualCapabilityLaunches` 注册表根目录解析。

以上均已随本分支提交；重跑入口见 §2 各小节命令。
