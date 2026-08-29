# A1 当前生产链路只读证据

观察时间：2026-08-13T17:55:56+08:00（Asia/Shanghai）

证据方式：在 `ubuntu@106.52.146.37` 上只读读取任务指定的 Media Web 源码、QA 合同、后端源码、当前运行进程、活动 release 与 `openclaw-media-deployment-guard.service` 状态。没有登录认证浏览器，没有创建任务，没有读取或写入业务数据库/飞书对象，没有修改远程或本地产品文件。

远程版本与活动发布：

- 后端源码 `/home/ubuntu/selfmedia-tools/openclaw-tag-router` HEAD：`dface1fb1773ac5b9dad18194738f6ded566d9e7`。
- 前端源目录 `/home/ubuntu/openclaw-bot-center` 位于 `/home/ubuntu` Git 工作树，但当前没有可解析的 HEAD；因此不把前端源码 HEAD 当作版本事实。
- 活动前端 release：`/mnt/openclaw-data/openclaw-media-frontend-releases/20260811T201753CST-media-cb-preview-cp1-r2`，`/var/www/openclaw/media` 直接指向该目录。
- 活动后端 release：`/home/ubuntu/.openclaw/releases/openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2`；协调元数据来自活动前端 release 的 `.release-coordination.json`。
- 活动前端 `.manifest.sha256` SHA-256：`8bba584e84fc338f7892ff2158d6715d922eb18afbffed2d6b254ad0e73b2a9c`；manifest 包含 `index.html`、`login.html`、`register.html`、两个构建 assets，以及三个 release 元数据文件。
- 8787 当前监听进程是 `/usr/bin/python3 -m openclaw_app.server_cli`，使用上述后端 release 的 `config/settings.yaml`，监听 `127.0.0.1:8787`；其工作目录为 `/mnt/openclaw-data/openclaw-media-release-stage/openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2`。

## AUTHENTICATION_CURRENT_STATE

当前认证连接点如下：

- 前端 `/home/ubuntu/openclaw-bot-center/src/media/mediaWebApi.ts:391-394` 读取 `GET /api/session`，严格要求 `media_web_business_pages_v2`、公开用户 ID、`ordinary|admin` 角色、CSRF 会话字段与过期时间。
- 前端同文件 `:594-607` 的登录入口生成 `/openclaw/media/login?next=...`；`scripts/qa/checkMediaLoginContract.ts:1-68` 验证普通用户落到 `/openclaw/media/overview`、管理员落到 `/openclaw/media/admin/overview`，并拒绝旧的用户/会话字段。
- 后端 `openclaw_app/adapters/http_api.py:1006-1035` 从 `openclaw_session` 会话解析账户，普通 Media 请求需要有效会话，管理员页面还需要 `session.role == "admin"`。
- 后端同文件 `:1038-1071` 对变更请求校验同源与 `X-OpenClaw-CSRF`，并要求 `Idempotency-Key`；`openclaw_app/account/auth.py:152-208` 负责登录、会话解析、过期/状态检查和 CSRF 绑定。
- 后端 `http_api.py:2059-2079` 将后端 `user/admin` 映射为前端 `ordinary/admin` 会话 envelope。

本次没有认证浏览器截图，也没有认证浏览器会话证明；只有源码、静态 QA 合同和未携带秘密的运行连接点。

## CONTEXT_LAUNCH_CURRENT_STATE

素材上下文目前只证明“打开并带入 task draft”：

- `src/media/pages/ordinary/AssetsPage.tsx:227-230` 通过 `openWorkspace(prefill)` 打开任务工作区；同页的素材动作把 `publicAssetId` 放入结构化参数，例如 `:1370-1410` 的选题/创作动作。
- `src/media/MediaWebWorkspace.tsx:204-214` 将结构化 prefill 放入侧边任务工作区，同时保留来源页面和选中记录可见；` :144-169` 在能力目录加载后应用待处理 prefill。
- `src/media/task-launch/workspacePrefill.ts:4-12` 将 prefill 分流为普通编辑或需要确认的 review；`taskDraft.ts:51-55,287-340` 将能力、变体、参数、来源标记和确认回执写入 draft，并重新校验字段。
- `taskDraft.ts:582-596` 将 draft 编译为版本 `3` 的任务请求，包含 capability、variant、params、uploadIds、catalogVersion、initiation、confirmationReceipt 和幂等键。

这些连接点只证明素材可以打开工作区并带入草稿；没有证明素材已被某个本次任务执行、写入数据库、投影到飞书或在网页读回。

## TASK_CREATION_CURRENT_STATE

任务 ID、幂等、终态和持久化的当前拥有者是 `MediaWebTaskService`，不是前端页面：

- 前端 `mediaWebApi.ts:517-536` 使用 `/api/tasks?limit=100`、`/api/tasks/{taskId}` 和 `POST /api/tasks`；创建请求由 schema 校验，CSRF 与同一幂等键同时放入请求头/请求体。
- 后端 `services/media_web_tasks.py:27-47` 定义 schema `media_web_task_v3`、终态 `succeeded|pending_manual|failed|cancelled` 和保留期限；`:342-448` 校验租户、能力目录、参数、上传引用、确认回执和幂等键，生成 `mwt_<uuid>` 任务 ID，初始为 `queued` 或 `awaiting_confirmation`，写入任务并提交执行。
- `media_web_tasks.py:286-314,654-713` 将任务、事件、上传和审计按租户哈希目录落在 `MEDIA_WEB_TASK_STATE_ROOT`（默认 `/home/ubuntu/.openclaw/state/media_web_channel`）；任务 JSON 使用原子替换写入，事件使用 JSONL 写入，并按租户隔离读取。
- `media_web_tasks.py:715-719` 按租户查找幂等键；同一请求指纹返回原任务，不同请求指纹返回 `idempotency_conflict`。HTTP 层在 `adapters/http_api.py:2092-2112` 新建任务返回 `202`，幂等复用返回 `200`。
- 前端 `MediaWebWorkspace.tsx:218-268` 先上传文件、组装请求、创建任务，然后把返回的 task ID 放入当前任务列表；`:185-202` 对非终态任务订阅事件并重新读取。

本次没有提交任务，因此没有可归属于本次的实际任务 ID、幂等回执、终态或持久化文件；这些属于 `not-proven-for-current-task`。

## RUNNER_CURRENT_STATE

当前不是独立 Media runner 服务，而是后端进程内的单 worker：

- `services/media_web_tasks.py:269-314` 明确声明 `Durable single-worker owner`，并创建 `ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-web-task")`；同一服务对象负责恢复与清理线程。
- `media_web_tasks.py:855-864` 由 `_submit` 提交到该 executor，并通过 `worker.lock` 获取单 worker lease 后进入 `_execute_with_lease`。
- `openclaw_app/server_cli.py:261-271` 在服务进程内构造唯一的 `MediaWebTaskService`，注入租户模型网关、网页投影刷新器和素材投影器；`:312-338` 把同一实例传给 HTTP server。
- 当前 8787 监听进程的命令行为 `python3 -m openclaw_app.server_cli ... --port 8787`，与上述进程内 wiring 相符。本次没有发现独立的 Media runner 进程连接点。

因此“任务已提交”只代表已落盘并排入该进程内单 worker；不等于 worker 已完成、业务写入已完成或网页投影已刷新。

## RESULT_AND_PROJECTION_CURRENT_STATE

结果形成、投影刷新和完成状态分为两层：

- `media_web_tasks.py:864-947` 从落盘任务读取能力和上传，构造 `media_web` canonical invocation metadata，绑定租户模型调用，并调用 `app.process_capability_invocation(...)`；这是真正的单 worker 执行连接点。
- `media_web_tasks.py:954-985` 将 canonical handler 原始结果转换为受控 public result；素材摄取还会调用注入的 source-asset projector。` :987-1005` 仅对规定的业务变更状态调用 `projection_refresher(tenant_id)`，刷新失败会把结果改为 `needs_attention`。
- `media_web_tasks.py:1006-1020` 将 `ok` 映射为内部 `succeeded`，需要人工处理映射为 `pending_manual`，其他失败映射为 `failed`，并最终追加 `task.result` 或 `task.error` 事件；取消为 `cancelled`。
- `media_web_tasks.py:1066-1145` 生成 public result 状态 `completed|needs_attention|failed`、受控回复、受限交付文档链接和确认回执；`:1180-1213` 将 task ID、状态、`terminal`、进度、result、error 和 event cursor 投影到 Web。
- `adapters/http_api.py:2186-2225` 以 SSE 读取事件并在任务进入内部终态且事件游标追平后关闭连接；前端 `mediaWebApi.ts:594-601` 监听 `task.created/status/confirmation/result/error/cancelled`。
- `media_web_tasks.py:1293-1327` 服务恢复时只重排尚未进入 canonical 执行边界的任务；已进入 `generating/persisting/rendering` 的任务转为 `pending_manual`，不自动重放。

当前代码能证明“结果形成”和“投影刷新触发条件”，不能证明本次有一个真实任务完成并完成同收据读回。

## FEISHU_AND_DATABASE_READBACK_CURRENT_STATE

当前可见的是代码连接点，不是本次真实任务读回：

- 数据库业务运行读模型由 `services/media_business/runs.py:462-525` 定义，读取 `media_product.creation_runs`、来源/决定/输出分区、`document_artifacts`，并左连接 `lark_document_bindings` 计算 artifact 的 `sync_status`。
- `RunsService:list_runs/get_run/get_run_sources/get_run_decisions/get_run_outputs` 位于 `runs.py:604-725`，按租户上下文从 PostgreSQL 读取并返回带 revision 的受控页面模型。
- 前端 `generatedBusinessPagesContract.ts:1476-1559,2073-2085` 声明 `/runs`、`/runs/{publicRunId}`、`sources`、`decisions`、`outputs` 业务读接口；`pages/ordinary/RunsPage.tsx:821-844` 和 `CreationRunDetailPage.tsx:75-93` 调用这些接口。
- `services/media_web_tasks.py:1130-1145` 只会从 handler 结果中提取并公开受控的 Feishu 文档链接；它没有把本次 task ID、`publicRunId`、artifact revision、Feishu binding revision 和数据库读回证据合并成一张收据。
- `services/media_business/lark_base_projection.py:256-324` 显示了 Bitable 解析、表枚举、记录读取和租户过滤连接；`:591-683` 显示 dry-run 校验或将来源记录投影到 `media_product` 的连接。`services/media_business/lark_sync.py:1-4` 明确其为旧的兼容辅助模块，生产发现/正文 hydration 使用其他模块，因此不把该辅助模块当作本次任务实际调用证据。

本次没有真实任务、没有同任务的 PostgreSQL 查询结果、没有同任务的 Feishu 记录/文档读回，也没有证明 `publicRunId`、artifact 或 Feishu binding 与某个 task ID 一一对应；必须标为 `not-proven-for-current-task`。

## WEB_READBACK_CURRENT_STATE

网页存在两条读回面，且必须区分“已提交”和“已完成”：

- 任务面：`mediaWebApi.ts:517-536,548-601` 读取 task 列表/详情、取消/确认并通过 SSE 更新；`MediaWebWorkspace.tsx:185-202,579-706` 以 `terminal`、`status`、`result`、`error` 展示最近任务。`202 Accepted` 仅表示任务已受理，`terminal=true` 且有受控 result 才表示任务执行链已到内部终态。
- 业务运行面：`RunsPage.tsx:821-844` 读取 `/runs`、`/runs/{publicRunId}/sources|decisions|outputs`；`CreationRunDetailPage.tsx:75-93` 读取 `/runs/{publicRunId}` 并显示运行状态、分区和 revision。该页面读取的是数据库业务运行模型，不是 task SSE 的替代品。
- 活动运行页面/API 的入口属于 `ordinary-session`；前端在未认证时显示登录门禁，在读取错误时区分 401/403/404。QA `checkMediaRunDetailRoute.ts:1-11` 还明确该详情页使用 `getRun`，不使用旧的 job detail/job ID 连接。

本次没有认证浏览器截图、没有打开活动页面进行交互、没有本次 task ID，也没有从 task 页面继续到同一 `publicRunId`、产物和 Feishu/数据库读回；因此只证明代码路径，不证明用户可见的同任务完成结果。

## DEPLOYMENT_GUARD_CURRENT_STATE

当前活动 release 与门禁状态如下：

- `/var/www/openclaw/media` 是受管 release symlink，目标为 `20260811T201753CST-media-cb-preview-cp1-r2`；`.release-coordination.json` 指向后端 release `openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2`。
- `openclaw-media-deployment-guard.service` 在观察时为 `failed (Result: exit-code)`，最近执行返回 `status=1`；实际错误为 `deployed Media contract label is missing: 账号与赛道`。
- `/usr/local/sbin/verify-openclaw-media:143-145` 起要求目标是受管 symlink；后续门禁还检查 release manifest、协调元数据、8787 进程参数、immutable 属性、部署标签、served hash 以及 `healthz/readyz`。本次只读取并记录失败，没有修复、重启或更换 release。

## GAPS_TO_IMPLEMENT

为了把同一张生产收据闭环，还需要在单一 canonical 链路上补齐：

1. 收据字段：将 `taskId`、canonical handler 执行结果、`publicRunId`、`publicProjectId`、`publicAssetId`/artifact ID、数据库 revision、Feishu document/binding 标识、projection/readback 状态和终态时间关联到同一受控响应；当前 Web task result 只有受控回复、链接和有限 receipt，业务运行读模型另行读取。
2. 持久化连接：在 canonical handler 成功后写入或确认同一任务对应的业务运行/产物关系，并在返回完成前完成数据库读回；不能只依赖任务状态或单独存在的业务页面列表。
3. Feishu 连接：对同一收据补充目标文档/多维表记录的版本或 revision、绑定状态和读回质量，明确 Feishu 写入完成、数据库投影完成、网页刷新完成的先后和失败状态。
4. Web UI：增加从“已受理/排队/执行中”到“终态/读回完成”的同一 task 收据视图，直接展示任务 ID 到运行/产物/Feishu/数据库读回的关联，并把“任务已提交”与“结果已完成”分开。
5. QA harness：增加认证浏览器 E2E，用真实同租户素材上下文创建一项任务，记录真实 task ID，等待单 worker 终态，校验数据库与 Feishu 的同任务引用和版本，再从 Web 读回同一运行/产物；同时保留失败、`pending_manual`、投影未刷新和门禁失败的可判定断言。当前静态 QA contract 不能替代这条 harness。
6. 发布门禁：活动 release 必须满足 guard 的标签、manifest、不可变属性、served hash 与后端协调检查后，才能声称发布链路可接受；当前门禁仍失败，不能被代码入口正确性替代。

以上是缺口清单，不引入兼容路径、双写或 fallback。

## CLAIM_BOUNDARY

已有生产后端源码、当前进程、数据库读模型代码、Feishu/Bitable 连接代码和活动 release 信息，只能证明当前连接点与静态/运行配置状态，不能替代：

- 本次认证浏览器截图或真实认证浏览器操作；本次明确没有该证据。
- 同一 task ID 从素材上下文、创建、单 worker 执行、终态、数据库/Feishu 引用到 Web 读回的真实 E2E 证据；本次没有提交任务，故为 `not-proven-for-current-task`。
- 活动 release 的可接受发布结论；当前 `openclaw-media-deployment-guard.service` 为失败状态。

入口正确、接口存在、任务可返回 `202`、或者已有数据库/飞书连接，都不能推导后续任务已完成、结果已投影、文档/记录已读回或用户已看到同一产物。

结论：本次只读证据已完成；代码连接点可核对，当前认证浏览器与同任务 E2E 收据闭环未证明，活动 release 门禁未通过。
