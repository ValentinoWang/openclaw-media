# B4 生产发布门禁独立复核

版本：计划 1，依赖图 1，接口冻结 1，节点合同 1，SSOT schema 1。

## 任务性质

这是一次独立、只读、零写入复核。不得实现、修复、部署、回退、切换软链接、重启服务或修改任何源码、发布、数据库、飞书对象、SSOT、合同和门禁脚本。唯一允许写入的是指定的本地结构化返回文件；Codex 自身日志由外层调度者保存。

## 复核对象

- SSOT 节点：`B4`，语义键 `media.release-guard-repair`。
- 节点合同：`execution-wave-3/tasks/B4-R2.md`。
- 写入执行台账：`execution-wave-3/B4-R2/ledger/B4-R2.json`。
- 写入执行返回：`execution-wave-3/B4-R2/returns/B4-R2-luna.json` 和 `execution-wave-3/B4-R2/returns/B4-R2-l3.json`。
- 固定远程主机：`ubuntu@106.52.146.37`。
- 固定基础源快照：`/home/ubuntu/worktrees/openclaw-bot-center-a1-media-cb-preview-20260808`。
- 固定基础提交：`db13e39aa4914d2168efcab5e2d9d6c2b26a41d8`。
- 固定基础状态摘要：`a13fef62351d368256cee5361d11887a4fc53db800417c0304db73797ec5123d`。
- 固定输入文件清单摘要：`2c90c87838d89e1e90570174ffdd1b852d8752a0fd1262d383f458651967f0eb`。
- 旧前端发布：`20260811T201753CST-media-cb-preview-cp1-r2`。
- 候选新前端发布：`20260813T184753CST-media-e2e-b4-label-guard-r2`。
- 固定后端发布：`openclaw-tag-router-media-tenant-20260811T201753CST-media-cb-preview-cp1-r2`。
- 固定后端目录摘要：`d4f036a093cc3714d6f295b1e44db34dc3c10f0e684d7b8c64fcfdedba9b6c1b`。
- 部署脚本摘要：`007ce7ed6d2f3444cf94f9a08b6936f2ff5547163c4abadefd5338917c3358b0`。
- 生产门禁脚本摘要：`e7c4e3d31be27a64c551b2bfde6b08c88922d6bb207408b78d73aec64204428e`。
- 新发布入口摘要：`3ce9bbbde5656ee720fc2bb7d93761a7277c474b3d3308fec59849c9bc7ada64`。
- 新发布清单摘要：`775a801ed850241ca738afb69c6b7c7cc0d98c326a1bf1726c74acd07a1efea`。

## 复核范围

1. 读取节点合同、台账和两份结构化返回，逐条核对任务边界、执行身份、实际读写范围、固定身份、命令结果、清理和未验证项。
2. 只读登录远程主机，重新核对活动前端发布、新旧不可变发布、完整发布清单、入口文件经 Nginx 提供的内容摘要、固定后端进程身份、健康与就绪端点、生产门禁服务和定时器。
3. 运行固定只读验收命令 `bash agents-results/2026-08-13/media-production-e2e-closure/execution-wave-3/commands/B4-R2.sh`。该命令不得被修改。
4. 明确区分生产门禁修复是否完成，与认证页面、真实任务、数据库、飞书或完整端到端是否完成。后五项不属于 B4，不得据此把 B4 判为缺失，也不得把 B4 的完成外推为后五项完成。
5. 检查首次部署失败后的恢复、Luna 验收退出码、L3 返回、监督器最终 `stop` 判定之间是否存在足以否定 B4 生产结果的矛盾。若只是调度器/验收命令执行方式的证据问题，必须具体指出；若生产结果本身不满足合同，必须列出失败条件。

## 禁止范围

- 禁止写入远程主机任何路径，禁止执行 `sudo` 写操作、部署脚本、链接切换、服务重启、回退或清理。
- 禁止修改本地项目文件、SSOT、合同、执行证据、验收命令、Codex 配置或记忆。
- 禁止读取或输出密钥、令牌、Cookie、环境变量值和私人业务正文。
- 禁止扩展为全仓审计或审查 C1、C2、DA、DB、DC。

## 返回要求

把单个 JSON 对象写入外层调度者指定的绝对返回路径。必须包含：

- `task_id`: `B4-REVIEW`
- `review_scope`: `B4-only`
- `write_authority`: `zero-write`
- `versions`: 五项版本均为 1
- `source_and_evidence_identity`: 本任务列出的固定身份及实际重新观察时间
- `completion`: `done`、`partial`、`missing` 或 `blocked`
- `criteria`: 至少逐条覆盖固定源身份、新旧发布保留及不可变、新发布清单、活动链接、Nginx 内容读回、后端进程与健康、生产门禁、回退/恢复证据、临时目录清理、禁止范围未触碰
- `commands`: 实际命令、退出码和去敏结果
- `supervisor_stop_analysis`: 说明监督器停止是否否定生产结果
- `actual_write_scope`: 只能包含结构化返回文件
- `forbidden_scope_touched`: 布尔值
- `unverified_items`: 必须保留 B4 之外的认证页面、任务、数据库、飞书和完整端到端边界
- `acceptance_recommendation`: 只能为 `accept-B4` 或 `do-not-accept-B4`
- `acceptance_self_check`: `pass`、`partial` 或 `fail`
- `failure_class`: 成功时为 `none`；否则使用 `verification`、`runtime`、`transport`、`scope-conflict` 或 `authority-conflict`

只有全部 B4 合同条件有当前只读证据、没有禁止写入、完成结论为 `done` 时，才可推荐 `accept-B4`。不得自行修改节点状态或声称整个 SSOT 已完成。
