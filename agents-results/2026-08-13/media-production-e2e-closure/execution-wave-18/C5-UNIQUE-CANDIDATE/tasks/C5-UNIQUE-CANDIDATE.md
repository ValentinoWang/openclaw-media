# C5 唯一候选汇合

## 身份与终点

- 任务编号：`C5-UNIQUE-CANDIDATE`
- 直接节点：C5（`media.unique-release-candidate-convergence`）
- 版本元组：计划 5、依赖图 5、接口冻结 5、节点合同 4、SSOT schema 1
- 已接受前置：C3、C4
- 目标：把已经接受的前端与后端候选汇合成一个内容校验值绑定的唯一候选。只收敛候选清单、来源记录、发布协调身份和汇合证据；不得部署、重启或修改任何远程系统。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`ff38d36843e7170ec3a6126fd200c63a0c2f7eed9380ea44c20835d33673c1fc`。
- `.ssot/nodes/C3.json` SHA-256：`87f9b93556f99b8358540dc076bcdf9cf2fc496b7cad787d1aef8b5e611559d0`，必须为 `ACCEPTED`。
- `.ssot/nodes/C4.json` SHA-256：`340a85565ab50738163742f19e1cf5eb3a0e80400d4a6faedddcd167302599f8`，必须为 `ACCEPTED`。
- `.ssot/nodes/C5.json` SHA-256：`1fce14e05f8ce0fda991b16ecd2a5156e29d30f17c266f2ed7a61990db6ff0f4`，必须为 `READY`、`FORMAL`。
- 素材解析合同 SHA-256：`24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56`。
- Wave 17 结果 SHA-256：`27cfc24b13d7618127996a72f57c38608f4a0df2a32f213104823b6c97021dbf`。
- Wave 17 验证脚本 SHA-256：`fc2bec23ab69da35d18e269bb4cd1a0236eb3929c33c943ee4bff4e6da02de8b`。
- 当前前端候选源码身份：C3 节点记录的 `57b0b13ef179977d3b70c95caea660b2af54aa2859ec0f575f8db8d644a71edd`；旧受管清单文件 SHA-256 为 `17fa19526a96ff2c82df5cd57e162675511a1a9a36718ad186c4d4d619ffa51f`，缺少 3 个素材解析文件，必须重建为 200 项。
- 当前后端候选源码身份：C4 节点记录的 `b1bee01ea908f6296ecd7377ff15a5cbf42a166315135de0434a5674cecaf69a`；旧受管清单文件 SHA-256 为 `9519c707bb842bea97e46eb770300417467c10fc5f5c8ce6916182e1f7600018`，缺少 4 个素材解析文件，必须重建为 566 项。
- 当前生产基线身份：前端 `20260814T084319Z-media-login-canonical`，后端 `20260814T062408Z-opc-feishu-login`。

## 唯一允许写入

- `.codex-work/merge-candidate-v4/frontend/.candidate-source.sha256`
- `.codex-work/merge-candidate-v4/frontend/.merge-provenance.json`
- `.codex-work/merge-candidate-v4/backend/.release-coordination.json`
- `.codex-work/merge-candidate-v4/backend/.candidate-source.sha256`
- `.codex-work/merge-candidate-v4/backend/.merge-provenance.json`
- `.codex-work/merge-candidate-v4/candidate-manifest.json`
- `.codex-work/merge-candidate-v4/candidate-manifest.sha256`
- `agents-results/2026-08-13/media-production-e2e-closure/execution-wave-18/C5-UNIQUE-CANDIDATE/result.md`
- supervisor 指定的唯一结构化返回文件

除此以外全部只读。不得修改前后端实现、测试、合同、SSOT 机器源、生成视图、生产快照、C2 候选、远程主机、数据库、飞书、账号、凭据、发布目录或服务配置。不得启动子代理、其他 worker 或长期后台进程。

## 汇合要求

1. 先核对冻结输入和 C3/C4/C5 状态。发现来源或状态漂移时返回 `BLOCKED` 与 `scope-conflict`，不得继续写入。
2. 将后端候选的 `.release-coordination.json` 保持现有 schema，只把 `frontendRelease` 收敛为当前前端生产基线 `20260814T084319Z-media-login-canonical`；`backendRelease` 保持 `openclaw-tag-router-media-tenant-20260814T062408Z-opc-feishu-login`。不得把候选冒充已发布版本。
3. 按验证脚本中的同一排除规则重建两个 `.candidate-source.sha256`。前端必须精确覆盖 200 个受管文件，后端必须精确覆盖 566 个受管文件；清单必须排除自身、来源记录、依赖目录、构建目录、缓存、日志和临时文件。
4. 更新两份 `.merge-provenance.json` 的候选清单 SHA-256、文件数和素材解析记录。素材解析记录至少包含合同编号、合同 SHA-256、54 项覆盖数、Wave 17 结果 SHA-256，以及“仅本地候选、未生产验收”的边界。保留现有历史字段，不删除既有冲突处理或未验证事项。
5. 新建 `.codex-work/merge-candidate-v4/candidate-manifest.json`，使用 `openclaw-media-unique-candidate-v1` schema 和 `media-production-e2e-v4` 候选编号。内容必须包括五版本元组、前后端生产基线、两份受管清单路径/SHA-256/文件数、素材解析合同身份、Wave 17 证据身份、发布协调身份和 `not_deployed` 状态。
6. 新建 `candidate-manifest.sha256`，只校验 `candidate-manifest.json`。顶层候选身份是 `candidate-manifest.json` 的 SHA-256，不能由时间戳、目录名或自然语言替代。
7. 新建本轮 `result.md`，写清唯一候选校验值、两份组件清单校验值、合同校验值、验证命令结果和未验证边界。不得写凭据、真实身份、Cookie、令牌、密码、私人正文或生产数据。

## 验收与停止条件

- 运行 supervisor 冻结的 `C5-UNIQUE-CANDIDATE.sh`，不得修改该脚本或绕过其中任何检查。
- 固定验证必须通过状态和哈希预检、两个组件清单独立重建、发布协调身份、顶层候选清单、三份素材解析合同字节一致、54 组合完整性、无符号链接/临时残留，以及 Wave 17 综合门禁。
- 验证通过时返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`；不得自行把 C5 标记为 `ACCEPTED`。
- 结构化返回至少包含：任务编号、版本元组、wrapper、实际读写范围、命令和退出码、变更文件、两个组件清单 SHA-256、顶层候选 SHA-256、合同 SHA-256、证据身份、未验证事项、共享资源影响、偏差、剩余风险、`failure_class`、`acceptance_self_check` 和 proposed state。
