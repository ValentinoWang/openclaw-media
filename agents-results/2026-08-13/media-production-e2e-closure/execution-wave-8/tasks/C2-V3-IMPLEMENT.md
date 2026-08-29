# C2 第 3 版任务闭环实现

## 身份与终点

- 任务编号：`C2-V3-IMPLEMENT`
- 直接节点：C2（`media.task-runner-receipt-implementation`）
- 版本元组：计划 3、依赖图 3、接口冻结 3、节点合同 3、SSOT schema 1
- 正式前置：B2、B3、B4 均已接受；C2 当前为正式就绪
- 冻结合同：`MPE2E-TASK-RUN-V3`，SHA-256 `35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b`
- 冻结保护测试：`scripts/acceptance/test-mpe2e-task-run-v3.sh`，SHA-256 `dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d`
- 冻结候选基线：805 个文件；清单 SHA-256 `37f383a3500775682f948ae4dda1aa9eaa5820f3b3b3ca12c1d91e602004b734`
- 目标：在唯一隔离候选中实现第 3 版合同的完整源码、迁移、独立执行器、状态投影和自动化验证；不得发布或写生产。

## 唯一写入权限

- `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/c2-main-takeover/**`
- supervisor 指定的 `STRUCTURED_RETURN_PATH`

除上述路径外全部只读。特别禁止修改 SSOT、节点、边、合同、保护测试、人工清单、绑定、验证脚本、远程活动源码、生产数据库、飞书对象、发布目录和服务配置。不得提交、推送、发布、重启、清理其他工作区或调用子执行者。

## 必须复用的已验证基础

- 规范迁移 `037_media_task_runner_receipts.sql`
- `PostgresMediaTaskRepository`
- 其已有精确绑定、`FOR UPDATE SKIP LOCKED`、租约恢复、幂等和收据实现
- `tests/test_media_task_repository_postgres.py`

先检查这些基础，不得为了方便恢复文件任务源、内存队列、双写或兼容回退。若现有基础确有错误，应在候选内修正并增加实现自有测试。

## 完整实现要求

### 一、两项代表能力的第 3 版输入

1. 仅对 `selfmedia_creation_consultation` 与 `selfmedia_creation` 强制平台和客户自有账号。
2. 创作咨询继续强制问题；自媒体创作继续保留原有必填内容；其他能力不得被扩大约束。
3. HTTP 创建路径必须从当前认证会话取得 `user_public_id` 并传至任务服务；不得接受客户端伪造用户编号。
4. 入队前按当前租户、认证用户、规范化平台和规范化账号解析唯一正式关系。文字相同不能替代正式关系。
5. 缺输入返回 `required_input_missing`/422；不存在、不可见、跨租户或跨用户返回 `account_relationship_unavailable`/404；不唯一或冲突返回 `account_relationship_conflict`/409。全部失败关闭且零任务副作用。

### 二、PostgreSQL 唯一任务事实源

1. `MediaWebTaskService` 必须真实注入并调用 `PostgresMediaTaskRepository`，负责校验、幂等入队、读取、取消和确认。
2. 删除活动源码中的文件任务、文件事件、文件审计、进程文件锁、`fcntl`、`ThreadPoolExecutor`、Web 内执行、Web 启动恢复及其回退路径。
3. 上传附件可以继续使用既有受控文件存储，但它不能保存任务、执行尝试、租约、事件、收据或结算事实。
4. 不允许数据库与文件、内存队列或线程执行器双轨；不允许读取旧文件任务作为回退。

### 三、独立账号聚合执行器

1. 新增 `openclaw_app/services/media_task_runner.py`，可作为独立进程运行。
2. `server_cli.py` 明确拆分 HTTP 与 runner 模式；HTTP 模式只提供请求服务，runner 模式不启动 HTTP 服务。
3. runner 使用稳定 `runner_public_id` 和不同的 `executor_public_id`，领取、开始、心跳、结算、失败与过期租约恢复全部通过 PostgreSQL 仓储。
4. 同一任务并发领取只有一个成功；未过期租约不可抢占；过期尝试可恢复；重启继续；重复提交不复制结果。
5. 能力执行复用现有真实处理路径，不在 runner 中复制另一套能力业务逻辑。

### 四、同一收据和结算

1. 收据同时绑定租户、认证用户、平台、账号、正式关系、来源上下文、任务、幂等键、runner、executor、尝试、结果、产物和读回。
2. 创作咨询证明无飞书对象且外部写入集合为空，数据库与网页读回仍为必填。
3. 自媒体创作必须记录本次飞书对象并完成声明应用身份读回；缺失或外部部分失败不得完成。
4. 只有数据库、外部适用性和网页读回全部一致时进入 `multi_system_readback_complete` 并产生最终收据。
5. HTTP 成功、已提交、能力执行成功、`succeeded` 或页面成功文案不得提前代表多系统完成。

### 五、API 与前端

1. API 投影稳定区分：已提交/排队、runner 已领取、执行中、等待数据库读回、等待外部读回、等待网页读回、多系统读回完成、失败和需人工处理。
2. 投影包含脱敏尝试、runner、executor、正式关系、结算检查与收据引用，不包含凭据、Cookie、令牌、密码或私人正文。
3. 前端任务创建和 schema 支持两项代表能力的必填平台与客户账号，并一致呈现三类稳定错误。
4. `MediaWebWorkspace`、普通用户运行页和总览页显示真实结算阶段、缺失读回、恢复信息和最终收据；刷新后只从服务端恢复权威状态。

### 六、实现自有测试

在候选内至少建立并通过：

- `tests/test_media_task_v3_contract.py`：两项能力输入、HTTP 用户编号、错误码、失败关闭和其他能力不变。
- `tests/test_media_web_tasks_postgres.py`：Web 只入队/读取、不自行执行、PostgreSQL 仓储接线、幂等、取消和确认。
- `tests/test_media_task_runner.py`：独立 runner 才执行、身份分离、领取并发、心跳、租约恢复、重启、失败和单结果。
- 现有 `tests/test_media_web_tasks.py`、`tests/test_media_task_repository_postgres.py` 和迁移测试继续通过。
- 前端增加或更新任务输入、稳定错误与结算状态相关测试，并通过 `build:media`。

## 固定验证

只使用 supervisor 已冻结的验证脚本：

```bash
bash agents-results/2026-08-13/media-production-e2e-closure/execution-wave-8/validation/C2-V3-IMPLEMENT.sh
```

验证使用一次性 PostgreSQL 16 容器和候选内前端依赖，严禁连接生产数据库。缺生产收据的保护测试继续以退出码 3 形成红灯是预期边界，不得伪造收据使其变绿。

## 停止条件和返回

只有固定验证全部通过时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。源码已写但验证未通过时只能返回 `IMPLEMENTED` 或 `FAILED`，并如实列出失败命令。遇到产品决定、权威、接口冻结、权限或架构冲突立即停止，不得扩大范围。

结构化 JSON 至少包含：任务编号、版本与合同哈希、包装器和 attempt role、实际读写路径、变更文件、PostgreSQL 接线、旧路径清除、runner/租约/恢复、V3 输入与错误语义、收据与前端投影、每条验证命令及退出码、保护哈希、敏感信息边界、未验证事项、偏差级别、`proposed_state`、`failure_class` 和 `acceptance_self_check`。
