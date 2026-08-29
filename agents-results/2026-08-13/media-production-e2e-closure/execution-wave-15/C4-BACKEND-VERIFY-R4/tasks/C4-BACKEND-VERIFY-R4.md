# C4 后端候选验证修复（第 4 次）

## 身份与终点

- 任务编号：`C4-BACKEND-VERIFY-R4`
- 直接节点：C4（`media.production-baseline-backend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- finding 来源：Wave 14 已证明 550/236 基线拆分、562 条候选、固定 Python 环境和隔离容器能够启动；实际聚焦测试在收集阶段因候选依赖的外部 `reminder` 与 `setup_media_bitable_registry` 模块未挂载而出现 3 个导入错误。
- 目标：保持候选字节不变，修正镜像标签预检并提供无密钥、只读、仅用于导入的外部模块测试替身；完成认证、客户账号绑定、任务仓库、独立执行器、所有者投影、PostgreSQL 迁移和红灯门禁。不得发布或触碰远程生产。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782`。
- `.ssot/nodes/B1.json` SHA-256：`cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc`，状态必须为 `ACCEPTED`。
- `.ssot/nodes/C4.json` SHA-256：`e8d5102533b0597d7bff0a7d6469262fb48d6efe8e8a8c92b1561cab5f015b21`，状态必须为 `READY`、`FORMAL`。
- B1 第 2 版合同 SHA-256：`a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc`。
- C2 第 3 版合同 SHA-256：`35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b`。
- C2 保护测试 SHA-256：`dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d`。
- 当前生产后端清单文件 SHA-256：`bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b`；固定为 786 条，其中 550 条持久条目、236 条临时条目。
- C2 36 文件清单文件 SHA-256：`23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927`。
- 后端候选清单文件 SHA-256：`9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018`，必须包含 562 个受管条目。
- 派生验证镜像 ID：`sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3`，镜像声明和构建收据沿用 Wave 14 的冻结文件。

## 唯一允许写入

- 监督器指定的唯一结构化返回文件。
- `/tmp/c4-backend-verify-r4.*` 一次性候选副本、无密钥配置、外部模块测试替身、编译缓存和日志。
- 名称以 `c4-backend-verify-r4-` 开头的一次性验证容器、PostgreSQL 16 容器和内部 Docker network；退出时必须清除。

原后端候选、前端候选、生产快照、C2 候选、SSOT、合同、保护测试、远程主机、飞书、账号、发布目录与服务配置均禁止写入。不得启动子代理或其他 worker。不得在提示词、日志或返回中写入密钥、Cookie、令牌、密码或私人正文。

## 无密钥配置、测试替身与网络边界

- OpenClaw 配置只能包含 `knowledge` bot，以及 `knowledge_delegate`、`media_creation`、`media_analysis`、`content_cleaner` 四个 profiles。
- provider 必须使用 `http://127.0.0.1:9`、假 API key、1 秒超时和测试模型；`content_cleaner` 必须关闭。
- 配置只读挂载到 `/home/ubuntu/selfmedia-tools/config/openclaw_bots.json`，不得读取或复制真实生产配置。
- 在一次性目录创建空的 `reminder.py` 和 `setup_media_bitable_registry.py`，只读挂载到 `/home/ubuntu/openclaw-feishu-reminder`，用途仅为满足未被本轮调用的衣橱外部适配器导入。若聚焦测试调用其任何函数，测试必须自然失败；不得提供伪造成功实现。
- 验证容器与 PostgreSQL 只连接唯一 `--internal` Docker network，不发布宿主端口，不访问公网。

## 验证要求

1. 原样运行监督器冻结的 `C4-BACKEND-VERIFY-R4.sh`，不得改写验证脚本或候选。
2. 重查原生产清单校验值、550/236 拆分、550 条持久内容以及 562 条候选内容。
3. 使用镜像 JSON 和 `jq` 验证镜像标签；测试只在一次性候选副本中运行。
4. 固定 Python 环境通过版本和导入自检，Python 编译写入一次性路径，pytest 禁止字节码和缓存插件。
5. 运行认证、HTTP、客户账号绑定、任务、独立执行器、迁移与租户/所有者投影的聚焦测试。
6. 在一次性 PostgreSQL 16 上执行规范迁移 apply、数据库聚焦测试和 migration verify。
7. 三个生产收据门禁保持失败关闭，退出码依次为 `3`、`20`、`20`。
8. 容器、network 和临时目录必须清除，原候选清单校验值及 562 条内容保持不变。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 冻结输入漂移、候选越权写入、原清单被改写、网络外连或远程副作用发生时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 依赖、解释器、测试、Docker、fixture 或数据库验证失败时，返回 `FAILED` 或 `BLOCKED`、`failure_class: verification`；不得修改保护测试或降低断言。
- 不得自行把 C4 标记为 `ACCEPTED`。结构化返回必须列出 550/236 计数、实际读写范围、镜像与网络身份、测试替身摘要、命令退出码、候选清单、清理结果、红灯结果、未验证事项、风险和敏感信息边界。
