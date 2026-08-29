# C2-V3-INDEPENDENT-REVIEW

你是 C2 第 3 版候选的独立验收复核者。工作模式是 `zero-write`：除唯一结构化返回文件外，不得修改任何本地文件，也不得访问或修改任何远程系统。

## 任务身份

- 任务编号：`C2-V3-INDEPENDENT-REVIEW`
- 直接父节点：`C2`
- 语义键：`media.task-runner-receipt-implementation.review`
- 版本：`PLAN=3`、`DAG=3`、`INTERFACE_FREEZE=3`、`NODE_CONTRACT=3`、`SSOT_SCHEMA=1`
- 工作进程：一个独立 `codex exec`
- 包装器：`/Users/vsiyo/.codex/workers/run-l3.sh`
- 项目根：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent`
- 包装器合同：`codex exec -C /Users/vsiyo/Desktop/创业项目/自媒体创作Agent --skip-git-repo-check --sandbox danger-full-access`
- 沙箱能力：`writable sandbox`；任务权限仍为 `zero-write`
- 唯一允许写入：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-9/C2-V3-INDEPENDENT-REVIEW/returns/C2-V3-INDEPENDENT-REVIEW.json`
- 停止条件：写出合法结构化返回，或记录明确阻塞
- 重试：0
- 取消责任人：主编排责任人
- 幂等键：`3/C2-V3-INDEPENDENT-REVIEW/1`

## 冻结身份

- C2 源码清单：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-8/C2-V3-IMPLEMENT/postimplementation-source.sha256`
- 源码清单校验值：`f36330fc9dd994df878e2d4a37deb3bed8fe02ca32c75464a69c786e1691d337`
- 清单文件数：31
- 候选根：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/c2-main-takeover`
- 验收合同：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-TASK-RUN-V3/acceptance-contract.md`
- 合同校验值：`35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b`
- 保护测试：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/scripts/acceptance/test-mpe2e-task-run-v3.sh`
- 保护测试校验值：`dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d`
- 固定实现门禁：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-8/validation/C2-V3-IMPLEMENT.sh`
- 固定门禁校验值：`c4761038d60531b50bd0a1f13df8ed287833237172507bb6b1c37501a133248e`
- 已有本地运行日志：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-8/C2-V3-IMPLEMENT/logs/C2-V3-IMPLEMENT-main-thread.validation.log`
- 日志校验值：`97849f27db4084181b2370c2e9bdcacfb8525b3ed7279b219b99b255e53c9dba`
- 实现返回：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-8/C2-V3-IMPLEMENT/returns/C2-V3-IMPLEMENT-main-thread.json`
- 决策引用：`media.no-inference-completion-boundary@1`、`media.same-receipt-proof@1`、`media.release-capability-samples@2`、`media.representative-account-binding-input@1`
- 局部失效键：`integration.task-runner-receipt`、`decision.representative-account-binding-input`、`contract.context-task-e2e`

## 允许读取

1. 上述冻结身份中的文件。
2. 源码清单列出的 31 个候选文件。
3. `.ssot/nodes/C2.json`、其直接依赖 `B2.json`、`B3.json`、`B4.json`，以及 `E-017-B2-C2.json`、`E-018-B3-C2.json`、`E-019-B4-C2.json`。
4. `acceptance/human/MPE2E-TASK-RUN-V3/binding.md` 与 `checklist.md`，仅用于确认生产和人工验收边界。
5. 候选前端的 `AGENTS.md`，仅用于检查适用项目规则。

不得扩展为全仓审计，不得重读无关 Harness 材料，不得审查未列入源码清单的旁支问题。

## 禁止范围

- 不得修改候选源码、测试、合同、人工清单、SSOT 机器记录、生成视图、现有证据或日志。
- 不得运行会修改候选或依赖目录的命令，包括构建、安装依赖、格式化、生成、数据库迁移和测试套件。
- 不得运行 Docker，不得建立 SSH 或其他网络连接，不得访问生产数据库、飞书或浏览器会话。
- 不得提交、推送、发布、重启、切换软链接或执行任何破坏性操作。
- 不得读取、输出或保存密码、令牌、Cookie、连接串或私人正文。
- 不得自行把 C2、DA、DB、DC 标为 `ACCEPTED`。

允许使用的检查是只读命令，例如 `shasum -a 256`、`shasum -a 256 -c`、`rg`、`sed`、`nl`、`jq`、`stat` 和文件列表读取。

## 复核问题

请以代码审查方式独立判断下列内容；先写严重度排序的 finding，再给结论。每个判断必须引用具体文件和行号或冻结证据。

1. 冻结身份是否完整匹配，31 个源码文件、合同、保护测试、固定门禁和运行日志是否未漂移。
2. PostgreSQL 是否是活动任务、执行尝试、租约、结算与收据的唯一任务事实源；网页进程是否只入队和读回，没有文件任务队列、进程内执行器或第二事实源。
3. 两项代表能力是否都要求平台、客户自有账号和认证用户公开编号，并只通过当前租户、当前用户、规范化平台、规范化账号及预先存在的正式关系完成唯一绑定。
4. 缺失、不可见、跨租户、跨用户、不唯一和冲突关系是否在入队前以冻结的 422/404/409 语义失败关闭，且不泄露存在性、不产生任务或副作用。
5. 独立账号聚合执行器是否有稳定且彼此独立的执行器身份，是否正确实现领取、开始、心跳、租约过期恢复、幂等结算、失败结算和并发所有权检查。
6. 同一收据是否关联任务输入、账号关系、执行尝试、产物、数据库读回、适用的外部读回、网页读回和恢复信息，并避免凭据、Cookie、令牌、密码、私人正文或原始正文进入收据。
7. 前端是否真实传递必填输入和认证上下文，区分三类失败，并只把已结算状态显示为成功；界面入口不能被当作后台完成证明。
8. 保护测试和验收合同是否没有被修改、削弱、跳过或用固定样例分支绕过；实现是否没有为 fixture 硬编码生产逻辑。
9. 已有本地运行证据是否足以证明 C2 的本地实现边界，且是否清楚保留两份真实生产收据、数据库/飞书/Web 同次读回、H-01 至 H-05、生产发布和最终终验给后续节点。
10. 是否存在会阻止 C2 从 `VERIFIED` 由主编排责任人提升为实现输出 `ACCEPTED` 的代码、合同或证据 finding。

本次复核的目标不是证明生产完成。缺少两份真实生产收据和人工运行结果本身属于 DB 边界；但如果实现无法产生这些证据、存在绕过、丢失身份、错误结算或第二事实源，则属于 C2 阻断 finding。

## 返回格式

只写一个 JSON 文件到唯一允许路径。必须包含：

```json
{
  "task_id": "C2-V3-INDEPENDENT-REVIEW",
  "node_id": "C2",
  "review_scope": "frozen-31-file-c2-v3-candidate",
  "write_authority": "zero-write",
  "versions": {"plan": 3, "dag": 3, "interface_freeze": 3, "node_contract": 3, "ssot_schema": 1},
  "source_and_evidence_identity": {
    "source_manifest_sha256": "f36330fc9dd994df878e2d4a37deb3bed8fe02ca32c75464a69c786e1691d337",
    "source_file_count": 31,
    "contract_sha256": "35143a0fb22218ebdcf969ee3a137431c37f21f90781db15572909e1dba0ca8b",
    "protected_test_sha256": "dee8b55304a60b4284462310f68f03099369af15071efc2fe5f39dcc8f67b73d",
    "validation_command_sha256": "c4761038d60531b50bd0a1f13df8ed287833237172507bb6b1c37501a133248e",
    "validation_log_sha256": "97849f27db4084181b2370c2e9bdcacfb8525b3ed7279b219b99b255e53c9dba"
  },
  "review_completion": "done",
  "findings": [
    {"id": "F-01", "severity": "blocking|high|medium|low", "blocking": true, "title": "", "evidence": ["absolute-file:line"], "reason": ""}
  ],
  "criteria": [
    {"id": "frozen-identity", "status": "pass|finding|blocked", "evidence": ""}
  ],
  "commands": [{"command": "", "exit_code": 0, "result": ""}],
  "actual_write_scope": ["/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-13/media-production-e2e-closure/execution-wave-9/C2-V3-INDEPENDENT-REVIEW/returns/C2-V3-INDEPENDENT-REVIEW.json"],
  "forbidden_scope_touched": false,
  "unverified_items": [""],
  "acceptance_recommendation": "accept-c2-implementation|repair-c2|blocked",
  "proposed_state": "VERIFIED|FAILED|BLOCKED",
  "acceptance_self_check": "pass|fail|partial",
  "failure_class": "none|implementation|runtime|verification|transport|architecture-conflict|authority-conflict|interface-freeze|permission|product-decision|scope-conflict"
}
```

`criteria` 必须恰好覆盖以下编号：`frozen-identity`、`protected-test-integrity`、`postgres-task-ssot`、`pre-enqueue-binding`、`fail-closed-errors`、`independent-runner`、`lease-recovery-idempotency`、`same-receipt-projection`、`frontend-projection`、`legacy-path-removal`、`local-evidence-boundary`、`forbidden-scope`。

没有 finding 时返回空数组，不要制造占位 finding。若建议接受，所有 12 项标准必须为 `pass`，`review_completion` 必须为 `done`，`proposed_state` 仍只能为 `VERIFIED`，由主编排责任人决定是否设置 `ACCEPTED`。
