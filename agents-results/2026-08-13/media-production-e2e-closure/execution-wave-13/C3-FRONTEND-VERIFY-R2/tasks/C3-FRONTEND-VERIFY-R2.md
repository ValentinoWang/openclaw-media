# C3 前端候选验证修复（第 2 次）

## 身份与终点

- 任务编号：`C3-FRONTEND-VERIFY-R2`
- 直接节点：C3（`media.production-baseline-frontend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- finding 来源：Wave 12 已完成候选合并，但 macOS `/bin/bash` 3.2 无法执行 `scripts/qa/withChromiumSlot.sh` 使用的 Bash 5 文件描述符语法，且宿主机没有可用 `flock`。
- 目标：保持前端候选字节不变，使用固定 Playwright Linux/ARM64 镜像在一次性副本中完成全部冻结验证。不得发布或触碰远程生产。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782`。
- `.ssot/nodes/B1.json` SHA-256：`cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc`，状态必须为 `ACCEPTED`。
- `.ssot/nodes/C3.json` SHA-256：`eacf1c368b583ff4f512ec217fad6ed0110613e15107ec22b9842923aa3ec7f3`，状态必须为 `READY`、`FORMAL`。
- B1 第 2 版合同 SHA-256：`a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc`。
- 当前生产前端清单文件 SHA-256：`7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14`。
- C2 36 文件清单文件 SHA-256：`23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927`。
- 前端候选清单文件 SHA-256：`17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f`，必须包含 197 个受管条目。
- 固定容器镜像：`mcr.microsoft.com/playwright:v1.61.1-noble@sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321`，系统必须为 Linux/ARM64。

## 写入与执行护栏

- 候选 `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4/frontend/**` 为只读输入，不允许修改任何字节。
- 唯一持久写入是 supervisor 指定的结构化返回文件。
- 允许在 `/tmp/c3-frontend-verify-r2.*` 建立一次性候选副本、npm 缓存和浏览器锁目录；验证退出时必须清除。
- 允许创建并清除名称以 `c3-frontend-verify-r2-` 开头的一次性 Docker 容器。
- 禁止写后端候选、生产快照、C2 候选、SSOT、合同、保护测试、远程主机、数据库、飞书、账号、发布目录和服务配置。
- 不得启动子代理、其他 worker 或第二条验证路径；不得把密钥、Cookie、令牌、密码或私人正文写入提示词、日志或返回。

## 验证要求

1. 运行 supervisor 冻结的 `C3-FRONTEND-VERIFY-R2.sh`，不得改写验证脚本或候选。
2. 验证必须重新检查全部冻结哈希、生产基线清单、C2 清单、候选清单、候选无符号链接及无依赖/构建/缓存残留。
3. 验证必须把候选复制到独立临时目录，只把该副本挂载到固定容器；在容器内证明 Bash 主版本至少为 5 且 `flock` 可用。
4. 容器内运行 `npm ci --ignore-scripts --no-audit --no-fund`、登录合同、上下文启动、最近任务展示、TypeScript 编译和完整 `npm run build:media`。
5. 容器与临时目录必须清除，候选清单文件 SHA-256 及 197 条内容必须保持不变。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 任一冻结输入漂移、候选被改写、越权写入或远程副作用发生时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 依赖、Docker、Node、浏览器或验证命令失败时，返回 `FAILED` 或 `BLOCKED`、`failure_class: verification`；不得降低测试或修改保护行为。
- 不得自行把 C3 标记为 `ACCEPTED`。结构化返回必须列出实际读写范围、镜像身份、命令退出码、候选清单哈希、清理结果、未验证事项、风险和敏感信息边界。
