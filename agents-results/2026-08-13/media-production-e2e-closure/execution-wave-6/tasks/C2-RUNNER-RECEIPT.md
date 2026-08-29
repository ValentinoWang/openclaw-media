# C2-RUNNER-RECEIPT 有界任务

## 身份与目标

- 任务编号：`C2-RUNNER-RECEIPT`
- 直接父节点：C2（`media.task-runner-receipt-implementation`）
- 版本元组：计划 2、依赖图 2、接口冻结 2、节点合同 2、SSOT schema 1
- 已接受前置：B2、B3、B4；决定引用为 `media.no-inference-completion-boundary@1`、`media.same-receipt-proof@1`、`media.release-capability-samples@2`
- 冻结合同：MPE2E-TASK-RUN v2，SHA-256 `f2f97099c514b8a9b5570c7626cc5e746ce99394370985000cdddd5094a18bf2`
- 保护测试：`scripts/acceptance/test-mpe2e-task-run.sh`，SHA-256 `334d2393059e54980a8434a99d59bef1b1f82d1466549f540aa40e4f5f0e50d0`
- 目标：在远程隔离副本中完成唯一客户账号绑定、持久执行尝试、独立账号聚合 runner、同一收据、多系统读回状态以及前端状态展示。不得发布、迁移生产数据库、写飞书或生成生产收据。

## 远程权威与隔离

- 主机：`ubuntu@106.52.146.37`
- 活动后端只读：`/home/ubuntu/selfmedia-tools/openclaw-tag-router`
- 活动前端只读：`/home/ubuntu/openclaw-bot-center`
- 唯一允许写入：`/home/ubuntu/worktrees/media-production-e2e-c2-op02-v2/backend/**` 与 `/home/ubuntu/worktrees/media-production-e2e-c2-op02-v2/frontend/**`
- 首次写入必须分别使用 `rsync -a` 创建隔离副本，排除 `.git`、`.venv`、`node_modules`、`dist*`、缓存、证据、日志和运行态状态。可在隔离前端建立指向活动 `node_modules` 的只读符号链接，但不得修改活动依赖。
- Node 路径：`/home/ubuntu/.nvm/versions/node/v22.22.2/bin`
- 后端项目没有更近的 `AGENTS.md`；前端必须遵守活动根目录 `AGENTS.md`，但本任务明确是隔离实现，不授权其中的默认发布动作。

## 冻结活动文件

### 后端

- `openclaw_app/services/media_web_tasks.py`：`0c272f9085a640f2ffc19543f2f01e91804b2b593ec6ea01561d6ad83846f1d6`
- `openclaw_app/adapters/http_api.py`：`1a03f08b71a4871346904c247462218ac805a4758ec7f273031b6b357167e83d`
- `openclaw_app/server_cli.py`：`18aa8ed7add4a4fcfcd726a95903acc5073d568d85cccba081273c99c40a6443`
- `openclaw_app/services/media_business/runs.py`：`8e1bd11a89e6353fd7b381f11f7a61bd6623eb43c3d722532910415ce8872c29`
- `openclaw_app/migrations/postgres_manifest.json`：`c81eafb9478119be87a9b713cc3479f40e85e557fc4840063b977e8c69e24960`
- `tests/test_media_web_tasks.py`：`f4c38a45e21d110188f3171a025b5b8892d1f14a2e2ce9b0d90e4817638abd2e`

### 前端

- `src/media/mediaWebApi.ts`：`7505c1fa803e02fa5d805758195e9e2f423a7e660c9b1b2dea62b94bacfe26a7`
- `src/media/MediaWebWorkspace.tsx`：`db5443b8538bb93026f5a769dd379e878fb40b9b23479fa82fa965827075deb5`
- `src/media/pages/ordinary/RunsPage.tsx`：`e200993baca156e12a7aa4d84aa69177c35718040fc646e135678aac824fd033`
- `src/media/pages/ordinary/OverviewPage.tsx`：`fcaf6d9bf8b39e9eb76cec60dcce413dbb2d2766501d09554a5de0d159b945f3`
- `package.json`：`dff0ce56f5e0c1f72a2d54869ebff4d36cf6a7498eb1c6184cf0f84a3b36c2aa`
- `AGENTS.md`：`2c1626033f500a00417a8276081264f7e1d46d975590d2f840b62d904debe92b`

## 唯一允许写入

- 远程隔离后端与前端目录下为完成本合同所必需的源码、迁移、测试和构建产物。
- 本地由 supervisor 指定的 `returns/C2-RUNNER-RECEIPT-<attempt>.json`。

## 禁止写入

- 活动后端、活动前端、`/var/www/**`、`/usr/local/sbin/**`、服务配置、活动 release/current 链接、生产数据库、生产队列、飞书、现有用户/租户/任务/会话和生产证据。
- 本地 SSOT、合同、保护测试、人工清单、固定样例和 B3 收据检查器。
- 不得 `reset`、`clean`、`checkout`、`stash` 活动后端约 293 条既有状态；不得 commit、push、deploy 或 restart。
- 不得保留旧进程内 `ThreadPoolExecutor` 作为回退，不得双写新旧 runner 状态，不得建立第二事实来源。

## 必须完成

### 1. 数据模型与唯一绑定

1. 新增规范迁移并更新 PostgreSQL manifest，至少持久化：客户自有账号与租户唯一绑定、任务执行尝试、runner 租约/心跳/恢复状态、任务收据、多系统读回结算状态。
2. 数据库约束必须拒绝同一平台账号跨租户绑定、同一任务同时存在两个活跃尝试、同一幂等键产生多个业务结果，以及同一外部对象归入不同任务。
3. 不把凭据、Cookie、令牌、密码或私人正文写入表、收据、日志或测试 fixture；只保存脱敏稳定引用、摘要校验值和必要的公开编号。

### 2. 单路径独立 runner

1. `MediaWebTaskService` 只负责校验、幂等创建、持久排队、查询、取消和确认，不再创建或提交 `ThreadPoolExecutor`，也不得直接在 Web 进程执行能力。
2. 新增独立、可由 CLI/服务管理器运行的账号聚合 runner。runner 必须使用与任务执行器不同的稳定身份，持久领取任务、创建尝试、续租/心跳、完成或失败，并能在进程中断和过期租约后恢复。
3. 删除旧进程内执行器路径及其恢复回退；Web 与 runner 只通过唯一持久任务/尝试状态协作，不允许内存队列、文件与数据库多套事实并存。
4. 测试必须证明 Web 进程提交后不会自行执行、独立 runner 才能推进、同一任务并发领取只有一个成功、过期尝试可恢复、未过期租约不可抢占、重启后可继续、重复提交不复制结果。

### 3. 同一收据与结算

1. 收据必须把脱敏账号与租户、来源上下文摘要、任务、能力/变体、幂等键、独立执行尝试、账号聚合 runner 身份、任务执行器身份、结构化结果、产物、数据库读回、适用的飞书读回和网页读回绑定为同一个不可拼接记录。
2. 账号聚合 runner 身份必须与任务执行器身份不同；缺任一身份或相同时失败关闭。
3. 创作咨询（`selfmedia_creation_consultation`）只有同时证明没有新飞书对象且外部写入集合为空时，飞书读回才可标记为不适用；数据库和网页读回仍强制。
4. 自媒体创作（`selfmedia_creation`）必须记录本次创建的飞书对象及声明应用身份的强制读回；外部部分失败或结算未知时不得进入完成态。
5. 收据生成器只能在任务、尝试、产物、数据库、外部适用性和网页读回全部一致后产生可验收终态。接口成功、任务已提交、能力执行成功或页面文案不能提前结算。
6. 测试覆盖中断、重试、数据库暂时失败、外部部分失败、网页读回缺失、重复产物、历史拼接、跨租户、敏感字段和恢复后的单结果不变量。

### 4. 接口与前端状态

1. API 投影明确区分“请求已提交/排队”“独立 runner 执行中”“等待数据库读回”“等待外部读回”“等待网页读回”“多系统读回完成”“失败/需人工处理”。
2. 任务详情暴露脱敏的执行尝试、runner 身份、结算检查与收据引用，不暴露秘密或私人正文。
3. `MediaWebWorkspace`、普通用户运行页和总览页不能把 `succeeded` 或 HTTP 成功直接显示为多系统完成；应显示当前结算阶段、缺失读回、失败恢复动作和最终收据状态。
4. 前端刷新后必须从服务端投影恢复状态，不以本地临时状态作为完成权威。

### 5. 验证与边界

1. 新增聚焦后端测试，运行现有 `test_media_web_tasks.py` 及 runner/收据测试；所有测试使用隔离临时数据库或可验证的仓储替身，不连接生产数据库。
2. 校验规范迁移/manifest，执行 Python 语法与聚焦测试；前端执行类型检查、构建及与改动相关的测试/静态检查。
3. 重算所有活动冻结文件哈希，必须完全不变。输出隔离副本实际变更清单、迁移标识、测试结果、旧执行器删除证据和未验证事项。
4. 本任务最多提议 `IMPLEMENTED` 或 `VERIFIED`；没有迁移/发布、真实 QA 身份、真实数据库/飞书/Web 同次读回与浏览器验收，不得声称 C2、DB 或整体目标已接受。

## 结构化返回

返回必须包含任务编号、attempt role、版本/合同身份、包装器、远程隔离路径、实际读写路径、数据模型与约束、runner/租约/恢复设计、旧路径清除、接口状态、前端状态、命令与退出码、活动源前后哈希、隔离变更、敏感信息边界、未验证事项、`failure_class`、`acceptance_self_check` 和 proposed state。
