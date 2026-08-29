# C3 前端候选验证修复（第 4 次）

## 身份与终点

- 任务编号：`C3-FRONTEND-VERIFY-R4`
- 直接节点：C3（`media.production-baseline-frontend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- finding 来源：Wave 14 已确认前端候选 197 条、后端候选 562 条及固定镜像身份均未漂移，但冻结脚本在 Docker 标签查询时传入字面反斜杠，容器和前端门禁尚未启动。
- 目标：保持前后端候选字节不变，在固定 Linux/ARM64 镜像中断网完成登录合同、上下文启动、最近任务展示、TypeScript 和完整构建门禁。不得发布或触碰远程生产。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782`。
- `.ssot/nodes/B1.json` SHA-256：`cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc`，状态必须为 `ACCEPTED`。
- `.ssot/nodes/C3.json` SHA-256：`eacf1c368b583ff4f512ec217fad6ed0110613e15107ec22b9842923aa3ec7f3`，状态必须为 `READY`、`FORMAL`。
- B1 第 2 版合同 SHA-256：`a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc`。
- 当前生产前端清单文件 SHA-256：`7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14`。
- C2 36 文件清单文件 SHA-256：`23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927`。
- 前端候选清单文件 SHA-256：`17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f`，必须包含 197 个受管条目。
- 后端候选清单文件 SHA-256：`9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018`，必须包含 562 个受管条目。
- 派生验证镜像 ID：`sha256:edb4dc9c110bb4b0303d7e85d2f3e73e9dd1a777282c10c73fc664c6d6557db3`，镜像声明和构建收据沿用 Wave 14 的冻结文件。

## 写入与执行护栏

- 前端和后端候选均为只读输入，不允许修改任何字节。
- 唯一持久写入是监督器指定的结构化返回文件。
- 允许在 `/tmp/c3-frontend-verify-r4.*` 建立一次性前端候选副本，退出时必须清除。
- 允许创建并清除名称以 `c3-frontend-verify-r4-` 开头的一次性 Docker 容器。
- 容器必须使用 `--network none`；后端候选只读挂载到 `/work/backend`，并由 `OPENCLAW_TAG_ROUTER_ROOT` 指定。
- 禁止写后端候选、生产快照、C2 候选、SSOT、合同、保护测试、远程主机、数据库、飞书、账号、发布目录和服务配置。
- 不得启动子代理、其他 worker 或第二条验证路径；不得在提示词、日志或返回中写入密钥、Cookie、令牌、密码或私人正文。

## 验证要求

1. 原样运行监督器冻结的 `C3-FRONTEND-VERIFY-R4.sh`，不得改写验证脚本或候选。
2. 重新检查全部冻结哈希、生产基线、C2 清单、前后端候选清单、符号链接和临时残留。
3. 使用 `docker image inspect` 的 JSON 输出和 `jq` 验证镜像标签，不使用 Go template 字符串转义。
4. 前端候选只能复制到独立临时目录；容器必须断网，并只读挂载后端候选作为能力注册表来源。
5. 容器内从固定缓存运行 `npm ci --offline`，随后运行全部冻结前端门禁。
6. 容器和临时目录必须清除，前后端候选清单校验值及受管内容必须保持不变。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 冻结输入漂移、候选被改写、越权写入或远程副作用发生时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 依赖、Docker、Node、浏览器或验证命令失败时，返回 `FAILED` 或 `BLOCKED`、`failure_class: verification`；不得降低测试或修改保护行为。
- 不得自行把 C3 标记为 `ACCEPTED`。结构化返回必须列出实际读写范围、镜像身份、断网状态、命令退出码、候选清单、清理结果、未验证事项、风险和敏感信息边界。
