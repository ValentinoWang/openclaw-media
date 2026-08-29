# C4 后端候选验证修复（第 3 次）

## 身份与终点

- 任务编号：`C4-BACKEND-VERIFY-R3`
- 直接节点：C4（`media.production-baseline-backend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- finding 来源：Wave 13 已通过 550/236 基线拆分与 562 条候选校验，并清除 8 个 `__pycache__` 和 13 个 `.pyc`；后续测试收集因缺少 Python 依赖和硬编码的生产 bot 配置路径失败。
- 目标：保持后端候选字节不变，使用固定派生镜像、无密钥 fixture、隔离内部网络与一次性 PostgreSQL 16 完成认证、客户账号绑定、任务仓库、独立 runner、owner/workspace 权限迁移和红灯门禁。不得发布或触碰远程生产。

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
- 派生验证镜像 ID：`sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3`，内含固定的 pytest、psycopg、bcrypt、cryptography、PyYAML、requests 和 Python Playwright。

## 唯一允许写入

- supervisor 指定的唯一结构化返回文件。
- `/tmp/c4-backend-verify-r3.*` 一次性候选副本、无密钥 fixture、编译缓存和日志。
- 名称以 `c4-backend-verify-r3-` 开头的一次性验证容器、PostgreSQL 16 容器和内部 Docker network；退出时必须清除。

原后端候选、前端候选、生产快照、C2 候选、SSOT、合同、保护测试、远程主机、飞书、账号、发布目录与服务配置均禁止写入。不得启动子代理或其他 worker。不得把密钥、Cookie、令牌、密码或私人正文写入提示词、日志或返回。

## 无密钥配置与网络边界

- fixture 只能包含 `knowledge` bot，以及 `knowledge_delegate`、`media_creation`、`media_analysis`、`content_cleaner` profiles。
- provider 必须使用 `http://127.0.0.1:9`、假 API key、1 秒超时和测试模型；`content_cleaner` 必须关闭。
- fixture 只读挂载到 `/home/ubuntu/selfmedia-tools/config/openclaw_bots.json`，不得读取或复制真实生产配置。
- 验证容器与 PostgreSQL 只连接唯一 `--internal` Docker network，不得发布宿主端口，不得访问公网。

## 验证要求

1. 运行 supervisor 冻结的 `C4-BACKEND-VERIFY-R3.sh`，不得改写验证脚本或候选。
2. 必须重查原生产清单文件 SHA-256、550/236 拆分和 550 条持久内容；不得重写或缩减原清单。
3. 原候选必须无符号链接、无临时残留且 562 条受管内容全部通过；实际测试只在一次性副本中运行。
4. 容器内固定 Python 环境必须通过版本与 import 自检，Python 编译写入一次性路径，pytest 禁止字节码和缓存插件。
5. 运行认证、HTTP、客户账号绑定、任务、独立执行器、迁移与 tenant/owner 投影的聚焦测试。
6. 在一次性 PostgreSQL 16 上执行规范迁移 apply、数据库聚焦测试和迁移 verify。
7. 三个生产收据门禁必须在容器内保持失败关闭，退出码依次为 `3`、`20`、`20`。
8. 容器、network 和临时目录必须清除，原候选清单哈希及 562 条内容必须保持不变。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 任一源码或冻结输入漂移、候选越权写入、原清单被改写、网络外连或远程副作用发生时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 依赖、解释器、测试、Docker、fixture 或数据库验证失败时，返回 `FAILED` 或 `BLOCKED`、`failure_class: verification`；不得修改保护测试或降低断言。
- 不得自行把 C4 标记为 `ACCEPTED`。结构化返回必须列出 550/236 计数、实际读写范围、镜像与网络身份、fixture 摘要、命令退出码、候选清单哈希、容器/network 清理、三项红灯结果、未验证事项、风险和敏感信息边界。
