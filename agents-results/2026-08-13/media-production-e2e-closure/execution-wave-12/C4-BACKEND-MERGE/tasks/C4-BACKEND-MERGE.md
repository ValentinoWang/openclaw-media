# C4 当前生产后端合并

## 身份与终点

- 任务编号：`C4-BACKEND-MERGE`
- 直接节点：C4（`media.production-baseline-backend-merge`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受前置：A1、B1、C2
- 目标：从当前生产后端 `20260814T062408Z-opc-feishu-login` 的只读快照建立独立候选，在保留飞书扫码、账号密码登录、飞书账号关联、租户角色会话和现行服务逻辑的前提下，合并 C2 已接受的 PostgreSQL 任务事实源、唯一客户账号绑定、独立账号聚合执行器和同一收据实现。不得发布或触碰远程生产。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`c6aca57fc2676e8a51704bb607c84245a0e55681bd4202270e659a8290ce9782`。
- `.ssot/nodes/B1.json` SHA-256：`cd561d9e4d8b2184b4932da81fc143ae105bf917fc0e520849b6547ca92fabbc`，必须为 `ACCEPTED`。
- `.ssot/nodes/C4.json` SHA-256：`e8d5102533b0597d7bff0a7d6469262fb48d6efe8e8a8c92b1561cab5f015b21`，必须为 `READY`、`FORMAL`。
- B1 第 2 版合同 SHA-256：`a0feedc825fff609f3cd72cbe7a0705ee0f0276fa18209a7f6192d4393984fdc`。
- 当前生产后端清单文件 SHA-256：`bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b`。
- C2 36 文件清单文件 SHA-256：`23d4017ba54422ba30f1aceb88ff34b2d0a034470d1bb70b9015e95613abe927`。其中后端部分共 25 个文件。
- C2 第 3 版合同 SHA-256：`35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b`；保护测试 SHA-256：`dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d`。
- 当前生产快照与 C2 候选都是只读输入；不得原地修改。

## 唯一允许写入

- `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4/backend/**`
- supervisor 指定的唯一结构化返回文件

除此以外全部只读。不得写 `.codex-work/merge-candidate-v4/frontend/**`、SSOT、合同、保护测试、当前生产快照、C2 候选、远程主机、数据库、飞书、账号、发布目录或服务配置。一次性本地 PostgreSQL 和 `/tmp` 验证环境仅用于冻结测试。不得启动子代理或其他 worker。

## 合并要求

1. 先从当前生产后端快照复制出完整、独立、无源目录符号链接的候选；不能把 C2 整棵旧后端当作新基线。
2. 消费 C2 清单中的 25 个后端实现文件。重叠的 `auth.py`、`http_api.py` 和 `server_cli.py` 必须做语义合并，不能整文件覆盖。
3. 必须保留当前生产的 `login_verified_email`、`OpcFeishuLoginClient`、`/auth/feishu/start`、`/auth/feishu/status`、受信飞书 HTTPS 主机检查、唯一账号和有效租户成员关联、角色、维护权限、会话到期与 CSRF 校验；同时把规范 `user_public_id` 传入任务创建和后续读取。
4. 两项代表能力只允许按当前租户、认证用户、规范化平台和规范化账号命中唯一正式关系；缺失、不存在/不可见/跨租户和冲突分别失败关闭，入队前零任务副作用。
5. PostgreSQL 是任务、事件、尝试、租约、产物、外部对象、读回和收据的唯一事实源。HTTP 进程只入队和读回；独立 runner 才能领取、心跳、恢复、执行和结算。不得恢复文件任务、内存队列、线程执行、双写或回退。
6. 检查生产已有迁移与 C2 规范迁移目录的编号和账本语义。若存在真实冲突，只能在候选内按现有迁移框架做单一确定性修复并同步清单和测试；不得重写已发布迁移或伪造已应用账本。
7. 创作咨询必须记录无外部写入，自媒体创作必须记录实际飞书对象读回；数据库、适用外部对象与网页读回全部一致前不得生成最终完成收据。
8. 生成 `.merge-provenance.json`，记录后端生产基线身份、C2 清单、B1/B2 合同哈希、实际合并文件、认证冲突处理、迁移处理和未验证事项；只写脱敏稳定引用。
9. 生成 `.candidate-source.sha256`，覆盖候选受管源码和配置，排除缓存、日志和该清单自身；不得包含指向输入目录的符号链接。

## 验收与停止条件

- 只运行 supervisor 冻结的 `C4-BACKEND-MERGE.sh`；固定验证必须通过认证回归、HTTP 和任务合同、独立 runner、迁移、一次性 PostgreSQL 集成及缺生产收据红灯。
- 固定验证通过时返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`；不得自行把 C4 标记为 `ACCEPTED`。
- 若当前认证与 C2 任务接口无法在冻结边界内兼容，返回 `BLOCKED` 和 `interface-freeze` 或 `architecture-conflict`，不得删除飞书登录或恢复旧任务路径。
- 结构化返回至少包含：冻结输入证明、实际读写范围、合并文件、认证保留项、PostgreSQL 和 runner 接线、迁移结论、命令与退出码、候选清单哈希、敏感信息边界、未验证事项、风险、偏差、`failure_class`、`acceptance_self_check` 和 proposed state。
