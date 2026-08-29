# C3 当前生产前端合并

## 身份与终点

- 任务编号：`C3-FRONTEND-MERGE`
- 直接节点：C3（`media.production-baseline-frontend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- 目标：从当前生产前端 `20260814T084319Z-media-login-canonical` 的只读快照建立独立候选，在保留飞书扫码、账号密码登录和现行页面行为的前提下，合并 C2 已接受的任务输入、账号绑定、结算状态和收据展示。不得发布或触碰远程生产。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782`。
- `.ssot/nodes/B1.json` SHA-256：`cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc`，必须为 `ACCEPTED`。
- `.ssot/nodes/C3.json` SHA-256：`eacf1c368b583ff4f512ec217fad6ed0110613e15107ec22b9842923aa3ec7f3`，必须为 `READY`、`FORMAL`。
- B1 第 2 版合同 SHA-256：`a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc`。
- 当前生产前端清单文件 SHA-256：`7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14`。
- C2 36 文件清单文件 SHA-256：`23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927`。其中前端部分共 11 个文件。
- 当前生产快照与 C2 候选都是只读输入；不得原地修改。

## 唯一允许写入

- `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4/frontend/**`
- supervisor 指定的唯一结构化返回文件

除此以外全部只读。不得写 `.codex-work/merge-candidate-v4/backend/**`、SSOT、合同、保护测试、当前生产快照、C2 候选、远程主机、数据库、飞书、账号、发布目录或服务配置。不得启动子代理或其他 worker。

## 合并要求

1. 先从当前生产前端快照复制出完整、独立、无源目录符号链接的候选；不能把 C2 整棵旧前端当作新基线。
2. 仅消费 C2 清单中的 11 个前端实现文件；遇到重叠文件必须做语义合并，不能整文件覆盖后丢失当前生产认证和页面行为。
3. `media.login.html`、`media.login.js`、`checkMediaLoginContract.ts`、`checkMediaSessionContract.ts` 和当前 `package.json` 必须保持生产基线字节身份。
4. 两项代表能力继续要求平台和客户自有账号，前端必须显示 `required_input_missing`、`account_relationship_unavailable`、`account_relationship_conflict` 三类稳定失败以及排队、领取、执行、等待各类读回、完成、失败和人工处理状态。
5. `MediaWebWorkspace`、运行页和总览页必须保留现行认证上下文，并只从后端恢复任务、执行尝试、runner、executor、正式关系、结算检查与收据引用；不能以页面存在或本地乐观状态标记完成。
6. 保留桌面和移动布局，无横向溢出；不得写入真实身份、Cookie、令牌、密码或私人正文。
7. 生成 `.merge-provenance.json`，记录前端生产基线身份、C2 清单哈希、B1 合同哈希、实际合并文件、冲突处理和未验证事项；只写脱敏稳定引用。
8. 生成 `.candidate-source.sha256`，覆盖候选的受管源码和配置，排除 `node_modules`、`dist*`、缓存、日志和该清单自身；不得包含指向输入目录的符号链接。

## 验收与停止条件

- 只运行 supervisor 冻结的 `C3-FRONTEND-MERGE.sh`；固定验证必须通过现行登录合同、任务输入与最近任务展示检查、TypeScript 编译和 `build:media`。
- 固定验证通过时返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`；不得自行把 C3 标记为 `ACCEPTED`。
- 若发现 B1 与 C2 在前端公开语义上不可兼容，返回 `BLOCKED` 和 `interface-freeze` 或 `authority-conflict`，不得静默删除一侧能力。
- 结构化返回至少包含：冻结输入证明、实际读写范围、合并文件、保留的认证能力、任务能力、命令与退出码、候选清单哈希、敏感信息边界、未验证事项、风险、偏差、`failure_class`、`acceptance_self_check` 和 proposed state。
