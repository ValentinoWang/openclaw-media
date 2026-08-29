# C4 后端候选验证修复（第 2 次）

## 身份与终点

- 任务编号：`C4-BACKEND-VERIFY-R2`
- 直接节点：C4（`media.production-baseline-backend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- finding 来源：Wave 12 已完成候选合并，但当前生产基线清单包含 236 条缓存或日志类条目；这些文件已从只读快照清理，导致整份清单内容检查在进入候选验证前失败。候选本身另有 8 个 `__pycache__` 目录、13 个 `.pyc` 文件需要清除。
- 目标：保留原生产基线清单文件及其哈希，只核验 550 条持久条目并精确确认 236 条临时条目；清除候选缓存后完成认证、任务、独立执行器、迁移、一次性 PostgreSQL 和生产收据红灯验证。不得发布或触碰远程生产。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782`。
- `.ssot/nodes/B1.json` SHA-256：`cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc`，状态必须为 `ACCEPTED`。
- `.ssot/nodes/C4.json` SHA-256：`e8d5102533b0597d7bff0a7d6469262fb48d6efe8e8a8c92b1561cab5f015b21`，状态必须为 `READY`、`FORMAL`。
- B1 第 2 版合同 SHA-256：`a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc`。
- C2 第 3 版合同 SHA-256：`35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b`。
- C2 保护测试 SHA-256：`dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d`。
- 当前生产后端清单文件 SHA-256：`bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b`；清单固定为 786 条，其中 550 条持久条目、236 条临时条目。
- C2 36 文件清单文件 SHA-256：`23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927`。
- 后端候选清单文件 SHA-256：`9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018`，必须包含 562 个受管条目。

## 唯一允许写入

- `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4/backend/**`：只允许删除 `__pycache__` 目录以及 `.pyc`、`.pyo`、`.pytest_cache`、`.DS_Store` 和 `.log` 临时残留；不允许修改源码、测试、迁移、合同、清单或来源记录。
- supervisor 指定的唯一结构化返回文件。
- `/tmp/c4-backend-verify-r2.*` 一次性虚拟环境、清单分片和日志，以及名称以 `c4-backend-verify-r2-` 开头的一次性 PostgreSQL 16 容器；退出时必须清除。

禁止写前端候选、生产快照、C2 候选、SSOT、合同、保护测试、远程主机、飞书、账号、发布目录或服务配置。不得启动子代理或其他 worker。不得把密钥、Cookie、令牌、密码或私人正文写入提示词、日志或返回。

## 验证要求

1. 先清除候选内声明的临时残留，再运行 supervisor 冻结的 `C4-BACKEND-VERIFY-R2.sh`。
2. 验证必须保留并重查原生产清单文件 SHA-256；只按以下正则划分临时条目，其他全部视为持久条目：`(^|/)__pycache__(/|$)|\.py[co]$|(^|/)\.DS_Store$|(^|/)\.pytest_cache(/|$)|\.log$`。
3. 必须精确得到 550 条持久条目和 236 条临时条目，并让 550 条持久条目全部通过内容校验；不得重写或缩减原清单。
4. 候选必须无符号链接和临时残留；候选 562 条受管清单必须全部通过。
5. Python 编译必须把字节码写到一次性目录；pytest 必须设置 `PYTHONDONTWRITEBYTECODE=1` 并禁用缓存插件。
6. 一次性虚拟环境至少安装 pytest、psycopg 二进制包、bcrypt 和 cryptography；运行认证、HTTP、任务、独立执行器和迁移的聚焦测试。
7. 使用一次性 PostgreSQL 16 执行规范迁移、认证与注册、客户账号绑定、任务仓库、独立执行器、工作区权限迁移和迁移核验。
8. 三个生产收据门禁必须保持失败关闭，退出码依次为 `3`、`20`、`20`。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 任一源码或冻结输入漂移、候选越权写入、原清单被改写或远程副作用发生时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 依赖、解释器、测试、Docker 或数据库验证失败时，返回 `FAILED` 或 `BLOCKED`、`failure_class: verification`；不得修改保护测试或降低断言。
- 不得自行把 C4 标记为 `ACCEPTED`。结构化返回必须列出临时残留清理、550/236 计数、实际读写范围、命令退出码、候选清单哈希、数据库容器清理、三项红灯结果、未验证事项、风险和敏感信息边界。
