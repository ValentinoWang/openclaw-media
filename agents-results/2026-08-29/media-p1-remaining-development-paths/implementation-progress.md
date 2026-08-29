# P1 剩余问题进度投影

此文件是执行状态投影，不是编排权威。权威依赖、节点状态和发布边界以 `.ssot/manifest.json` 为准。

| 冻结基线 | 当前状态 | 说明 |
|---|---|---|
| P1 去重后的实时状态 | 原始审计 `163` 条；固定别名规则实际命中 `7` 个跨域同根因组，折叠其中 `8` 条重复后得到 `155` 个独立问题组 | 以 integration `main` 与照片仓库 `/Users/vsiyo/Desktop/照片筛选` 的独立 `main` 证据映射出 `153` 组已修复、`2` 组部分覆盖、`0` 组未修复；尚未完全关闭为 `2` 个独立问题组。`CT-A7` 已由 `277b028` 将 destructive 删除能力强制限制为 maintainer-only，能力目录 public 序列化不再暴露该能力，定向测试 `24 passed`。照片仓库的 external evidence 仅在其本地 `main` 历史和定向测试均通过时计入，不把跨仓提交冒充 integration 源码。`BIZ-05`、`CD-13` 仍只有源码与定向测试提交 `ec8c88c`，缺生产轮询运行证据。机器清单见 `agents-results/2026-08-29/media-p1-dedup-audit/p1-dedup.json`，脚本可由 `dedup_p1.py --json` 重算。该数字替代旧投影，不把提交数直接当作关闭数。另有 `CT-B4`、`LP-05`、`LP-06`、`LP-07`、`LB-19` 五个历史基线已修复组当前没有显式提交映射，不能把该标签当作本轮提交证明 |
| 发布切片 | 5 个已建立 | `REL-P1-UX`、`REL-P1-PIPE`、`REL-P1-BIZ`、`REL-P1-PORT`、`REL-P1-QA` 均未组装候选 |
| 当前就绪交付包 | 14 个 | P1 至 P14 均可继续；本轮已处理用户可见渲染、Router 状态呈现和创作证据合同，尚未完成全部交付包验收 |
| 已接受发布验收 | 0 个 | C1 至 C5 均等待对应交付包 |
| P1 发布决定 | 未开始 | 仅在五个候选都完成独立验收后评估 |

本计划本身通过校验不等同于 P1 已完成。

## 2026-08-29 并行核对补充

CT-A4、CT-B1、CT-B2 已在当前 `main` 复核关闭，证据提交 `8b2b83e`：

- CT-A4 相关路由夹具统一使用 canonical tenant UUID，`require_tenant_id` 继续 fail-closed；商业交付、Business Vlog、Style Polish、Creation Inspiration 等定向集合通过。
- CT-B1 容量/LLM 异常回复仅输出中文可操作信息，内部 `error_code/detail` 保存在 `result.extra`；定向测试通过。
- CT-B2 商单失败回复仅输出中文失败原因与重试指引，不泄露 `commercial_delivery_failed` 或 `permission readback failed`；定向测试通过。

早期并行审计曾记录“剩余 28 个未修复组”，该结论已被后续逐项复验覆盖，不能继续作为当前状态。按 `dedup_p1.py --json` 对当前 integration `main` 和独立照片仓库 `main` 的实时证据重算，当前只有 `BIZ-05`、`CD-13` 两个独立问题组处于“部分修复”，没有“未修复”组；照片仓库相关条目已以外部仓库自身提交和定向测试计入，不冒充 integration 源码。两项剩余仅缺真实生产轮询运行证据，待远端网络恢复后验收。

## CPC-01 至 CPC-04 复核记录（2026-08-29）

`CPC-01`、`CPC-02` 的配分总分已由代码根据分项重新计算，`CPC-03` 的创作模型档位已提升到 tier B，`CPC-04` 的回洗验收失败已降级返回最后候选稿并标记待人工处理。独立复核证据见 `agents-results/2026-08-29/media-p1-cpc-review/CPC-01-04-review.md`，定向测试结果为 `34 passed`。这 4 条已从“仍缺”转为“已覆盖”，但不改变五个发布切片尚未正式验收的事实。

## Router 与前端错误隔离复核记录（2026-08-29）

`CRF-01`、`CRF-03`、`CRF-11`、`CRF-13` 的当前生产路径和回归测试已确认存在；`CRF-04` 增加了前端错误消息白名单，未知英文诊断只保留错误码，不再回显给创作者。主线提交为 `978c60a`，Router/CLI 定向集合各 `19 passed`，新增 `openclaw-bot-center/scripts/qa/checkMediaErrorIsolation.ts` 通过。该记录证明源码和静态门禁，不等同于远端部署或五个发布切片正式验收。

## 2026-08-29 历史分片复验（非当前总计）

| 复验分片 | 已覆盖 | 部分覆盖 | 仍缺 | 合计 |
|---|---:|---:|---:|---:|
| 数据流断链与无消费产物 | 8 | 3 | 1 | 12 |
| 用户可见渲染面 | 15 | 3 | 3 | 21 |
| 创作主链 prompt | 8 | 1 | 7 | 16 |
| 已逐条复验合计 | 31 | 7 | 11 | 49 |

本轮新增关闭记录：BIZ-01（创作回执展示稳定创作记录编号并写入回链）、BIZ-10（首小时动作进入发布包必填校验和验证窗口调度）、BIZ-08（日报互动证据回流）、CPC-16（平台拟合候选证据优先压缩）。BIZ-05 与 CD-13 记录为部分覆盖：代码具备到期任务消费与用户提醒，但尚无生产轮询运行证据。

补充确认：评论证据升级门禁已由 `22292a7` 进入 `main`（`d191e35` 为等价空提交），要求独立证据与人工复核后才可把评论支持的候选假设升级为事实；对应门禁测试 `4 passed`。

本地脚本领域边界（历史分片记录，已由后续跨仓 `EXTERNAL_CLOSED` 证据覆盖）：LP-01/02/03/04/10/11/12/13/15/16/18/19/20/21/22/23/24 曾指向当前 integration 仓库不存在且未被 Git 跟踪的 `photo-content-os/` 路径。该历史记录不应覆盖当前总计；照片仓库 `main@9864824` 的外部证据已由实时脚本按独立仓库规则计入。

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
- `RT-03` 已完成源码复验：`daily-poll` 解析器默认读取 `FEISHU_REQUIRED`，并在运行时再次通过 `feishu_required_default()` 合并环境配置；`tests/test_selfmedia_cli_smoke.py`、`tests/test_daily_poll_tenant_flow.py` 共 `26 passed`。该条已有实现和测试证据，本次未重复修改代码。
- `RT-01` 已完成源码复验：`install-cron` 使用当前 `selfmedia.py` 的 `__file__` 解析路径、当前 Python 和租户参数生成 systemd service，不再写死旧宿主路径；`tests/test_daily_poll_tenant_flow.py` 的安装路径/命令回归与上述 CLI 集合通过。该条不等同于远端 timer 已安装或实际轮询已运行。
- `RT-04` 已完成源码复验：`daily_poll` 将成功互动指标与评论原话写入租户隔离复盘记忆，并由创作上下文/数据复盘读取；`tests/test_daily_poll_tenant_flow.py` 已验证 `source= selfmedia:daily-poll`、发布链接、四类指标及前五条评论回链。该条不等同于生产 cron 已运行。
- `RT-12` 已完成源码复验：`daily-poll` CLI 在解析层要求 `--tenant-id`，并在读取监控表前调用 `require_tenant_id`；日报 JSON/复盘记忆写入租户隔离目录。对应租户边界回归包含在 `tests/test_daily_poll_tenant_flow.py` 集合中。
- `RT-08` 已完成源码复验：`install-cron` 生成的 service 直接执行当前仓内 Python 与 `runtime/cli/selfmedia.py daily-poll`，不再通过自然语言 agent 消息间接执行每日采集；安装命令回归已覆盖在 `tests/test_daily_poll_tenant_flow.py`。
- `RT-14` 已完成源码复验：`daily-poll` 与 `install-cron` 现有 CLI/租户/路径/失败分支测试覆盖，`tests/test_selfmedia_cli_smoke.py tests/test_daily_poll_tenant_flow.py` 共 `26 passed`。该证据覆盖入口回归，不代表生产 timer 已部署。
- `RT-13` 已完成源码复验：`docs/architecture.md`、`runtime/cli/selfmedia.env.example` 与 `selfmedia --help` 均使用仓库相对入口和可配置环境变量，不再出现 `/home/ubuntu/selfmedia-tools` 旧宿主路径；`tests/test_runtime_entrypoint_portability.py` 与日报 CLI 集合通过。
- `CPO-N21` 已实际修复：删除 `content_flow_client.py` 中 `_transcription_final_note_value_missing` 的重复 `@staticmethod` 装饰器，并新增源码门禁；`tests/test_content_flow_method_declarations.py` 与 `openclaw-tag-router/tests/test_content_flow_client.py` 共 `94 passed`。

- Router 错误响应兼容性在 `main@d0180e9` 完成：`_send_api_error` 对轻量测试/适配器对象缺失 `_correlation_id` 时仍能按 `{ok,error:{code,message,details?}}` 合同返回；`test_api_error_matches_media_web_task_error_schema` 与兼容回归合计 `13 passed`。不改变 maintainer-only 删除能力的安全可见性边界。

- 数据复盘渲染批次在 `main@7226e02` 完成：字符串化 JSON 会先解析为中文字段，内部路径/记录标识不进入正文，表现评级与证据附录后置；`tests/test_data_review_p1_rendering.py tests/test_data_review_structured_rendering.py tests/test_p6_data_flow_closure.py tests/test_review_memory_backflow.py` 结果 `20 passed`。该同一渲染层批次覆盖 BIZ-03、CD-09、CR-07、CPO-K15。

- 并行云桥修复：`LB-03`、`LB-05`、`LB-06` 已分别由 `343424e`、`808395f`、`7acaf97` 收口；`LB-07` 由 `9aa8607` 增加 done 结果的内容等价幂等回执，重复接收不再因共享 vault 路径冲突失败。云桥定向集合 `24 passed`。

- 并行运行时核对：`LB-10` 已由 `808395f` 使 frozen media contract 在仓内 clean checkout 可解析，`test_cloud_media_task_receiver.py` 相关集合 `4 passed`。`LB-13/LB-14/LH-01` 仍明确属于当前仓不存在的 `photo-content-os/` 脚本边界，未伪造关闭。

- 跨仓源码复核：原审计所指的 `photo-content-os/99_System_OpenClaw` 实际存在于独立仓库 `/Users/vsiyo/Desktop/照片筛选`；其本地 `main@9864824` 已包含 `b1f0376`（creator context）、`d690db0`（bridge contract）、`ae59c09`（模板路径可移植）及既有队列/脚本修复。由于该仓库与 integration 是不同 Git 根，不能把这些提交直接计入 integration 的 `main`；照片仓库 worker 中相对当前 main 的大规模删除分支已拒绝合并。后续将以照片仓库自身 `main`/远端 SHA 和定向测试作为 LP/LH/LB 的独立证据层。
- 跨仓源码复核更新：照片仓库 `main@9864824` 的 P1 回归集合已实测 `20 passed`（模板、creator context、bridge、平台/slot_map）及 `46 passed`（local prompts、frontmatter/围栏、storyboard、runner、桌面端、queue/cloud markdown）。`dedup_p1.py` 现以 external evidence 映射并校验照片仓库 `main` 历史；因此 LP/LH/LB 相关条目已从 PATH_MISSING 更正为已修复。该计数仍独立于 integration 源码提交，两个仓库不强行合并。
- 并行安全策略复核：`CT-A7` 在 `main@277b028` 已完成 maintainer-only 限制，`openclaw-tag-router/tests/test_capability_registry.py` 为 `24 passed`；剩余仅 BIZ-05/CD-13 的生产轮询运行证据缺口。

- 生产证据核对：对 SSH 别名 `103` 与 `106` 执行只读服务/timer 检查均返回 `No route to host`，未取得生产轮询回执。BIZ-05/CD-13 继续保持 `部分修复`，待远端网络恢复后以实际 timer 状态、日志和租户隔离产物完成验收。

- 远端实时复核（2026-08-29）：`106.52.146.37` 主机的 `openclaw-stage2.service` 正常运行，`openclaw-media-watchdog.timer` 持续执行；但用户级 timer 列表没有 `selfmedia-account-daily-poll.timer`，也没有发现日报轮询运行日志。当前仓内 `install-cron` 会在注册前强制要求租户编号和 `FEISHU_ACCOUNT_REPORT_URL`，因此不能在缺少这两个生产配置时盲目安装。`BIZ-05`、`CD-13` 的剩余性质确认为“生产安装与运行证据缺口”，不是源码缺失。
- 同一远端的 `/home/ubuntu/selfmedia-tools` 当前处于 `codex/media-semantic-20260819`，HEAD 为 `e0dfbf0`，且工作树存在未跟踪与备份文件；它不是当前 integration `main`，不能直接作为本次 P1 主线发布候选。远端安装前必须先完成独立的干净发布目录、明确租户编号与飞书日报地址，再安装并回读 timer、服务日志和租户隔离产物。
- 二次并行探测仍未在两台远端发现 `OPENCLAW_MEDIA_DAILY_POLL_TENANT_ID` 或 `FEISHU_ACCOUNT_REPORT_URL` 配置；计数与部分修复状态保持不变，未执行无租户或无日报地址的安装。
- 安装审计补充：远端旧版 `selfmedia.py` 仍使用 OpenClaw cron agent 方式，未要求租户编号；远端没有 `selfmedia-tools/.venv`，也没有当前主线所需的生产环境文件和 user systemd 持久化验证。直接安装会绕过当前租户隔离合同，因此本轮只记录证据，不在旧脏工作树执行安装。
- 远端准备进展（2026-08-29）：已将当前 `main` 以独立不可变目录 `/home/ubuntu/releases/openclaw-media-p1-1511254` 传至 `106.52.146.37`，创建该 release 的 `.venv` 并安装 `pydantic`、`python-dotenv`、`requests`；`selfmedia.py --help` 可正常启动。使用临时 systemd 目录和禁用模式预检生成了 tenant-scoped service/timer，确认入口、租户参数和 `Asia/Shanghai` 调度合同正确；未写入生产 user unit、未启动轮询，因此尚未产生 BIZ-05/CD-13 的生产运行证据。
- release 基线说明：上述远端 release 的源码基线为传输时的 `main`（`1511254`）；其后本地新增提交仅更新本进度文档和 SSOT 证据，不改变 `runtime/cli/selfmedia.py` 或日报轮询实现。当前环境再次连接远端时返回 `Operation not permitted`，因此暂不能回读该 release 的服务状态或完成生产安装。
- 本轮复核：对 `106.52.146.37` 的 SSH 连接仍被当前执行环境以 `Operation not permitted` 拒绝，无法执行远端安装或回读；本地 release 入口和依赖仍可做无副作用检查。该阻塞属于执行环境网络权限，不将其误记为代码失败。

- 远端连接恢复后的实时回读（2026-08-29）：`ubuntu@106.52.146.37` 可正常登录，release `/home/ubuntu/releases/openclaw-media-p1-1511254` 存在且包含 `.venv`。但 `OPENCLAW_MEDIA_DAILY_POLL_TENANT_ID`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_ACCOUNT_MONITOR_URL`、`FEISHU_ACCOUNT_REPORT_URL`、`FEISHU_REQUIRED` 均未设置；`selfmedia-account-daily-poll.service`、`selfmedia-account-daily-poll.timer` 均不存在，日报服务日志无记录。该回读证明网络阻塞已解除，但生产配置仍缺失，不能安全安装租户轮询。远端根分区使用率为 `98%`（约 `802M` 可用），安装前还需确认磁盘空间和清理边界。

验证：Python 定向集合分别为 `8 passed`、`44 passed`；Router 定向集合 `13 passed, 4 subtests passed`；前端定向 QA 与 `npm run build:media` 通过。上方 `31/7/11` 与“尚未复验 114 条”均为历史分片快照，不是当前实时总计；当前总计以 `dedup_p1.py --json` 输出的 `153/2/0` 为准。
