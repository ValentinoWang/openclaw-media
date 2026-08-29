# P1 剩余问题进度投影

此文件是执行状态投影，不是编排权威。权威依赖、节点状态和发布边界以 `.ssot/manifest.json` 为准。

| 冻结基线 | 当前状态 | 说明 |
|---|---|---|
| P1 未修复 148 条 | 持续逐条复验与产品修复 | `148` 仍是冻结起点，不是当前实时剩余数；此前投影为 49 条已逐条复验（31 条已覆盖、7 条部分覆盖、11 条仍缺），另有 114 条尚未逐条复验；基于 `main@978c60a` 已新增 CPC-01、CPC-02、CPC-03、CPC-04 的独立源码复核与 34 项定向测试证据，并完成 CRF-04 英文错误隔离门禁；另已明确关闭 CPC-16、BIZ-01、BIZ-08、BIZ-10 以及数据复盘渲染批次 BIZ-03、CD-09、CR-07、CPO-K15，评论证据隔离门禁已由 `22292a7` 进入主线；待下一轮逐条汇总重算，不能用提交数量自动扣减 |
| 发布切片 | 5 个已建立 | `REL-P1-UX`、`REL-P1-PIPE`、`REL-P1-BIZ`、`REL-P1-PORT`、`REL-P1-QA` 均未组装候选 |
| 当前就绪交付包 | 14 个 | P1 至 P14 均可继续；本轮已处理用户可见渲染、Router 状态呈现和创作证据合同，尚未完成全部交付包验收 |
| 已接受发布验收 | 0 个 | C1 至 C5 均等待对应交付包 |
| P1 发布决定 | 未开始 | 仅在五个候选都完成独立验收后评估 |

本计划本身通过校验不等同于 P1 已完成。

## CPC-01 至 CPC-04 复核记录（2026-08-29）

`CPC-01`、`CPC-02` 的配分总分已由代码根据分项重新计算，`CPC-03` 的创作模型档位已提升到 tier B，`CPC-04` 的回洗验收失败已降级返回最后候选稿并标记待人工处理。独立复核证据见 `agents-results/2026-08-29/media-p1-cpc-review/CPC-01-04-review.md`，定向测试结果为 `34 passed`。这 4 条已从“仍缺”转为“已覆盖”，但不改变五个发布切片尚未正式验收的事实。

## Router 与前端错误隔离复核记录（2026-08-29）

`CRF-01`、`CRF-03`、`CRF-11`、`CRF-13` 的当前生产路径和回归测试已确认存在；`CRF-04` 增加了前端错误消息白名单，未知英文诊断只保留错误码，不再回显给创作者。主线提交为 `978c60a`，Router/CLI 定向集合各 `19 passed`，新增 `openclaw-bot-center/scripts/qa/checkMediaErrorIsolation.ts` 通过。该记录证明源码和静态门禁，不等同于远端部署或五个发布切片正式验收。

## 2026-08-29 实时复验

| 复验分片 | 已覆盖 | 部分覆盖 | 仍缺 | 合计 |
|---|---:|---:|---:|---:|
| 数据流断链与无消费产物 | 8 | 3 | 1 | 12 |
| 用户可见渲染面 | 15 | 3 | 3 | 21 |
| 创作主链 prompt | 8 | 1 | 7 | 16 |
| 已逐条复验合计 | 31 | 7 | 11 | 49 |

本轮新增关闭记录：BIZ-01（创作回执展示稳定创作记录编号并写入回链）、BIZ-10（首小时动作进入发布包必填校验和验证窗口调度）、BIZ-08（日报互动证据回流）、CPC-16（平台拟合候选证据优先压缩）。BIZ-05 仅记录为部分覆盖：代码具备到期任务消费，但尚无生产轮询运行证据。

补充确认：评论证据升级门禁已由 `22292a7` 进入 `main`（`d191e35` 为等价空提交），要求独立证据与人工复核后才可把评论支持的候选假设升级为事实；对应门禁测试 `4 passed`。

本地脚本领域边界：LP-01/02/03/04/10/11/12/13/15/16/18/19/20/21/22/23/24 全部指向当前 integration 仓库不存在且未被 Git 跟踪的 `photo-content-os/` 路径。该 17 项记录为 `PATH_MISSING`，未伪造实现或修改保护测试；其中旧审计标为“已修复”的 LP-20~24 也无法在本仓复验，暂不计入关闭。

本轮进入 `main` 的实现提交：

- `8f32429`：复盘文档中文化并隐藏本地截图路径；任务结算状态中文化，隐藏执行器与租约内部信息。
- `7209710`：保留拆解镜头与生产摘要证据；对齐小红书轮播图文合同；修复 insight-card 否定句误伤；使 platform-fit 截断显式可见。

本轮新增进入 `main` 的原子提交：

- `d2272b5`：增长链用户可见错误信息中文化，并隔离 provider 异常细节。
- `a248d8b`：注册完播率、跳出率、互动率等复盘指标，并保留复盘记忆回链字段。
- `9683c38`：入库 analyzer 与 CreatorProfile 中文 prompt/校验合同，失败不再静默吞掉。
- `dfa6a96`：创作交接显式接入多信号合同。
- `707fdb2`：商业排期闭环测试对齐。
- `6f95e92`：修复创作候选 payload 合并后语法错误。
- `72fa092`：保留创作归因并写入交付回执，补齐归因链回归测试。
- `18b3368`：Router 活动链接注册表优先解析、强制 `table` 参数；创作回执区分 Mac 素材已绑定与未绑定状态。
- `89b9940`：增长链拒绝非中文创作者可见文本，避免英文机器腔进入结果。
- `94c5e70`：补充选题候选英文标题的负例门禁测试。
- `35bba72`：Content OS 状态推进返回机器可判定布尔结果，业务回执由上层统一渲染。
- `a9f0942`、`b4b917e`：CPC-16 平台拟合候选改为证据优先压缩，保留镜头、迁移、制作摘要和活动约束，并显式标记省略字段。
- `1e145bd`：BIZ-08 将日报轮询的互动指标与评论原话写入租户隔离复盘记忆，创作上下文和数据复盘按发布链接消费该证据。

本轮验证证据：

- `/tmp/openclaw-media-p1-venv/bin/python -m pytest -q tests/test_media_growth_v2.py tests/test_media_model.py tests/test_review_memory_backflow.py selfmedia/ingest/content_flow/tests/test_analyzer_provider_order.py tests/selfmedia/creator_profiles/test_creator_profile_enrichment.py`
- 结果：`123 passed, 14 subtests passed`（Pydantic 兼容性弃用警告，不影响断言结果）。
- `python -m py_compile` 与 `git diff --check` 通过。
- `tests/test_creation_receipt.py tests/test_creation_v1.py tests/test_p0_review_loop.py`：`53 passed`。
- `openclaw-tag-router/tests/test_content_os_bridge_presentation.py tests/test_content_flow_client.py`：`98 passed`。
- `tests/test_media_growth_v2.py openclaw-tag-router/tests/test_content_os_bridge_presentation.py`：`75 passed, 18 subtests passed`。
- 配置、排期、不可信输入与可移植性定向集合：`26 passed`。
- CPC-16 与 BIZ-08 合并后定向回归：`tests/test_creation_prompt_evidence_contract.py tests/test_daily_poll_tenant_flow.py tests/test_review_memory_backflow.py tests/test_creation_v1.py`，结果 `65 passed`。
- 商业闭环回归：`tests/test_creation_receipt.py tests/test_p0_review_loop.py tests/test_validation_window_scheduler.py tests/test_p1_schedule_closure.py tests/test_commercial_loop.py tests/test_p7b_commercial_closure.py`，结果 `34 passed`。
- CT-A1 源码合同层复验：仓库现有 `docs/ai-harness/` 下 5 份合同，`media_model/contract.py` 默认解析仓内合同；合同路径、Media Model、Vault 和 Router 边界集合结果 `41 passed`。这只关闭“合同不在源码仓”的根因，不覆盖下述 SSOT runtime provenance 验证失败。
- Router 全套：`1515 passed, 24 failed, 39 skipped, 270 warnings, 271 subtests passed`；失败集中在既有删除能力、复盘投影和能力目录合同，未将其计为 P1 完成。
- SSOT bundle validator 在当前 Harness 工作树报告 `runtime-skill-provenance` 缺少项目侧 `.harness/manifest.yaml`；项目已有 `.harness/overlays/project-harness-adapter.yaml`，未擅自伪造 manifest，故该验证层保持未通过。
- 本轮 SSOT 快照已刷新并通过项目级 `--check`（Obsidian 管理文件 1 个）；全局 `--audit-archive` 被集合内既有 AthleteOS 快照的哈希漂移阻塞，未将该外部失败归因于本项目。

补充复验（2026-08-29 后续轮次）：

- P13/RT-11 可移植部署修复已确认在 `main` 的 `4899f9f`：月度报价提醒 systemd 模板不再写死 `/home/ubuntu`，部署器注入仓内 `id_business.py` 路径并拒绝未解析占位符；`tests/test_biz16_deploy_runtime.py tests/test_maintenance_portability.py tests/test_runtime_entrypoint_portability.py tests/test_p13_portability.py tests/test_portable_media_paths.py` 结果 `17 passed`。该项为已进入主线的既有提交，不重复计数。

- CR-20 咨询兜底已确认在 `main` 的 `42250af`：空模型回复不再渲染“依据/建议/下一步/缺口”报告分栏，而是输出连贯的中文聊天段落；`tests/test_cr20_consultation_fallback.py tests/test_consultation_fallback.py` 结果 `7 passed`。

- 修复 `selfmedia/creation/workflow.py` 中候选 payload 重复字典起始行后，原 P1 定向集合重新通过：`120 passed, 14 subtests passed`。
- 仓库根目录全量 `pytest` 当前不能作为整体绿灯：跨子项目收集时缺少 `openclaw_media` 安装包、`httpx`、`opentimelineio` 等独立依赖，收集阶段出现 71 个错误；这些错误不归因于本轮 P1 定向改动，后续按子项目依赖矩阵拆开验证。
- 本地验证环境使用隔离目录 `/tmp/openclaw-media-p1-venv`，未写入仓库依赖文件或全局 Python。

- `RT-02` 已在 `main@557bb1a` 收口：日报 CLI 在没有可消费产物或仅发生跳过时不再静默返回成功，改为报告失败/未完成状态；`tests/test_selfmedia_cli_smoke.py` 与相关日报回归共 `29 passed`，`git diff --check` 通过。该提交只关闭 RT-02 的静默成功缺口，不替代日报生产者、轮询运行证据或其余 RT 条目验收。

- Router 错误响应兼容性在 `main@d0180e9` 完成：`_send_api_error` 对轻量测试/适配器对象缺失 `_correlation_id` 时仍能按 `{ok,error:{code,message,details?}}` 合同返回；`test_api_error_matches_media_web_task_error_schema` 与兼容回归合计 `13 passed`。不改变 maintainer-only 删除能力的安全可见性边界。

- 数据复盘渲染批次在 `main@7226e02` 完成：字符串化 JSON 会先解析为中文字段，内部路径/记录标识不进入正文，表现评级与证据附录后置；`tests/test_data_review_p1_rendering.py tests/test_data_review_structured_rendering.py tests/test_p6_data_flow_closure.py tests/test_review_memory_backflow.py` 结果 `20 passed`。该同一渲染层批次覆盖 BIZ-03、CD-09、CR-07、CPO-K15。

验证：Python 定向集合分别为 `8 passed`、`44 passed`；Router 定向集合 `13 passed, 4 subtests passed`；前端定向 QA 与 `npm run build:media` 通过。尚未复验的 114 条不得自动记为已覆盖，部分覆盖条目也不得计入关闭数。
