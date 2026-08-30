# 第二阶段执行治理

## 叶子交付清单

| Deliverable ID | Parallel batch | Deliverable | Authority write region | Dependencies | Isolation decision | Conflict class | Owning node | Grouping reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DL-A1 | source-baseline | 可复现的非 Git 来源基线 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/source-notes.md | A | independent | none | A1 | n/a |
| DL-F1 | cross-stage-projections | 身份汇合跨阶段收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/F1.json | A1 | independent | none | F1 | n/a |
| DL-F2 | cross-stage-projections | 组织开通跨阶段收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/F2.json | A1 | independent | none | F2 | n/a |
| DL-F3 | cross-stage-projections | 第一阶段必需交付跨阶段收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/F3.json | A1 | independent | none | F3 | n/a |
| DL-S1 | shared-context | AIExecutionContext 第 3 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-s1 | B | independent | none | S1 | n/a |
| DL-S2 | shared-context | ContextBuilder 路由和来源收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-s2 | S1 | independent | none | S2 | n/a |
| DL-S3 | shared-writer | WriterRouter 第 2 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-s3 | F2, S1 | independent | none | S3 | n/a |
| DL-S4 | shared-writer | ArtifactRecorder 和 ReadbackVerifier | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-s4 | S3 | independent | none | S4 | n/a |
| DL-S5 | shared-capability | 能力副作用注册表 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-s5 | S1, S3 | independent | none | S5 | n/a |
| DL-T1 | shared-contracts | 保护测试和验收矩阵 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-t1 | B | independent | none | T1 | n/a |
| DL-C1 | personal-foundation | 个人资料投影与范围合同 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c1 | B, F1 | independent | none | C1 | n/a |
| DL-C2 | personal-briefs | 个人研究简报成果 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c2 | C1 | independent | none | C2 | n/a |
| DL-C3 | personal-briefs | 个人决策简报成果 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c3 | C1 | independent | none | C3 | n/a |
| DL-C4 | personal-context | PersonalContextBuilder 结果 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c4 | C2, C3, S2 | independent | none | C4 | n/a |
| DL-C5 | personal-writer | InternalArtifactWriter 和个人成果收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c5 | C4, S3, S4, S5 | independent | none | C5 | n/a |
| DL-C6 | personal-editor | Web 编辑界面和修订链 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c6 | C5 | independent | none | C6 | n/a |
| DL-C7 | personal-publish | 平台版本和发布包成果 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-c7 | C6 | independent | none | C7 | n/a |
| DL-C8 | personal-convergence | 个人端到端候选 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C8.json | C7, S, T1 | independent | none | C8 | n/a |
| DL-O1 | organization-foundation | 组织资料和品牌约束收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-o1 | B, F2 | independent | none | O1 | n/a |
| DL-O2 | organization-writer | LarkArtifactWriter 和远端写入收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-o2 | O1, S2, S3, S5 | independent | none | O2 | n/a |
| DL-O3 | organization-artifact | 组织成果绑定收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-o3 | O2, S4 | independent | none | O3 | n/a |
| DL-O4 | organization-readback | 组织只读镜像和回读收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage2-o4 | O3 | independent | none | O4 | n/a |
| DL-O5 | organization-readback | 飞书编辑和再回读同收据证据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/evidence/O5 | O4 | independent | none | O5 | n/a |
| DL-O6 | organization-convergence | 组织端到端候选 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/O6.json | O5, S, T1 | independent | none | O6 | n/a |

每个独立叶子交付只归属于一个数字节点。共享合同、迁移、同一飞书文档、候选和活动发布通过资源矩阵串行；可用执行槽位只改变波次，不合并节点。

## 最大安全并行宽度

| Parallel batch | Leaf deliverables | Independent deliverables | Conflict-grouped deliverables | Logical lane target | Available worker slots | Wave count |
| --- | --- | --- | --- | --- | --- | --- |
| cross-stage-projections | 3 | 3 | 0 | 3 | 3 | 1 |
| organization-artifact | 1 | 1 | 0 | 1 | 1 | 1 |
| organization-convergence | 1 | 1 | 0 | 1 | 1 | 1 |
| organization-foundation | 1 | 1 | 0 | 1 | 1 | 1 |
| organization-readback | 2 | 2 | 0 | 2 | 2 | 1 |
| organization-writer | 1 | 1 | 0 | 1 | 1 | 1 |
| personal-briefs | 2 | 2 | 0 | 2 | 2 | 1 |
| personal-context | 1 | 1 | 0 | 1 | 1 | 1 |
| personal-convergence | 1 | 1 | 0 | 1 | 1 | 1 |
| personal-editor | 1 | 1 | 0 | 1 | 1 | 1 |
| personal-foundation | 1 | 1 | 0 | 1 | 1 | 1 |
| personal-publish | 1 | 1 | 0 | 1 | 1 | 1 |
| personal-writer | 1 | 1 | 0 | 1 | 1 | 1 |
| shared-capability | 1 | 1 | 0 | 1 | 1 | 1 |
| shared-context | 2 | 2 | 0 | 2 | 2 | 1 |
| shared-contracts | 1 | 1 | 0 | 1 | 1 | 1 |
| shared-writer | 2 | 2 | 0 | 2 | 2 | 1 |
| source-baseline | 1 | 1 | 0 | 1 | 1 | 1 |

## Worker 执行合同

真正需要独立实现进程的叶节点使用 `external-codex-exec`；历史节点、自动投影、确定性本地检查、人工外部验收和纯汇合节点均使用各自的零进程合同。Codex 注册命令包含 `codex exec -C <absolute-root> --skip-git-repo-check --sandbox danger-full-access`，注册的沙箱权威是 `writable sandbox`，包装器最终进入 `exec codex exec`。本计划禁止把 `spawn_agent`、聊天子代理或同进程协作接口登记为执行器。当前所有登记均为禁止启动，也没有启动任何外部 worker。

| Task ID | Transport | Wrapper | Project root | Literal codex exec contract | Sandbox authority | Dispatch state | Return path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | historical-unregistered | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no retroactive worker claim | n/a | EXITED | n/a |
| A1 | historical-unregistered | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no retroactive worker claim | n/a | EXITED | n/a |
| K | historical-unregistered | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no retroactive worker claim | n/a | EXITED | n/a |
| F1 | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/F1.json |
| F2 | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/F2.json |
| F3 | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/F3.json |
| B | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/B.json |
| S1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/S1.json |
| S2 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/S2.json |
| S3 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/S3.json |
| S4 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/S4.json |
| S5 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/S5.json |
| T1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/T1.json |
| C1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C1.json |
| C2 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C2.json |
| C3 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C3.json |
| C4 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C4.json |
| C5 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C5.json |
| C6 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C6.json |
| C7 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/C7.json |
| C8 | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/C8.json |
| O1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/O1.json |
| O2 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/O2.json |
| O3 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/O3.json |
| O4 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns/O4.json |
| O5 | external-manual | n/a | n/a | manual prerequisite; zero Codex processes | not applicable | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/manual-receipts/O5.json |
| O6 | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/O6.json |
| S | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/S.json |
| C | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/projections/C.json |
| DA | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes | bounded local process | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/deterministic-receipts/DA.json |
| DB | external-manual | n/a | n/a | manual prerequisite; zero Codex processes | not applicable | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/manual-receipts/DB.json |
| DC | external-manual | n/a | n/a | manual prerequisite; zero Codex processes | not applicable | BLOCKED | agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/manual-receipts/DC.json |

## 五类运行配置继承门

| Task ID | Required runtime profile | Profile available | Launch authorized | Profile authority | Merge protocol authority |
| --- | --- | --- | --- | --- | --- |
| F1 | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| F2 | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| F3 | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| B | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| S1 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| S2 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| S3 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| S4 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| S5 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| T1 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C1 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C2 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C3 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C4 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C5 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C6 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C7 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| C8 | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| O1 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| O2 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| O3 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| O4 | implementation-runner | False | False | stage1 G1 accepted capability receipt | stage1 M1 accepted deterministic patch protocol |
| O5 | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| O6 | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| S | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| C | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| DA | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| DB | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |
| DC | zero-process | n/a | not-authorized | transport-specific contract | not-applicable |

第二阶段不重新发明运行配置或无 Git 合并算法。第一阶段 G1 提供实现、静态验证、外部测试、生产发布和独立只读五类配置，M1 提供开发基线与晋升基线重建协议；F1/F2 未接受时，兼容 wrapper 不得启动。

## 无 Git 候选汇合协议

| Protocol element | Required record or behavior | Authority | Gate timing |
| --- | --- | --- | --- |
| 开发基线 | 允许提前开发的源码快照，以及每个文件的路径、大小与 SHA-256 | 第一阶段 M1 | 任何第二阶段补丁开始前复算 |
| 晋升基线 | F3 绑定的第一阶段 DC2 已接受候选，不得继续使用提前开发时的旧基线 | 第一阶段 M1、F3 与候选 C | 候选 C 重建前 |
| 节点补丁清单 | 节点、基线身份、补丁、文件归属、测试与结构化返回 | 每个第二阶段实现节点 | 外部工作进程退出前 |
| 固定应用顺序 | 按机器拓扑和迁移顺序应用补丁，禁止目录覆盖 | 第二阶段候选汇合负责人 | 候选 C 重建时 |
| 冲突检测 | 未声明的同文件重叠、过期开发基线、晋升基线冲突、漏补丁与顺序漂移均失败关闭 | 第一阶段 M1 协议 | 应用每个补丁前后 |
| 候选重建 | 从晋升基线重放全部已接受补丁；冲突使所属节点失效并复算唯一候选校验值 | 候选 C | 每次候选变化后 |

## 有限进程预算

| Task ID | Worker processes | Retry limit | Stop condition | Cancellation owner | Idempotency key | PID/session | Log path | Exit code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 0 | 0 | historical source or decision already accepted | n/a | historical-A | historical-unverified | historical-unverified | historical-unverified |
| A1 | 0 | 0 | historical source or decision already accepted | n/a | historical-A1 | historical-unverified | historical-unverified | historical-unverified |
| K | 0 | 0 | historical source or decision already accepted | n/a | historical-K | historical-unverified | historical-unverified | historical-unverified |
| F1 | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-F1 | not-applicable | n/a | not-applicable |
| F2 | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-F2 | not-applicable | n/a | not-applicable |
| F3 | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-F3 | not-applicable | n/a | not-applicable |
| B | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-B | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/B.log | pending |
| S1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-S1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/S1.log | pending |
| S2 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-S2 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/S2.log | pending |
| S3 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-S3 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/S3.log | pending |
| S4 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-S4 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/S4.log | pending |
| S5 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-S5 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/S5.log | pending |
| T1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-T1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/T1.log | pending |
| C1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C1.log | pending |
| C2 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C2 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C2.log | pending |
| C3 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C3 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C3.log | pending |
| C4 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C4 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C4.log | pending |
| C5 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C5 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C5.log | pending |
| C6 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C6 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C6.log | pending |
| C7 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-C7 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/C7.log | pending |
| C8 | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-C8 | not-applicable | n/a | not-applicable |
| O1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-O1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/O1.log | pending |
| O2 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-O2 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/O2.log | pending |
| O3 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-O3 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/O3.log | pending |
| O4 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage2-2-2-3-3-O4 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-logs/O4.log | pending |
| O5 | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | runtime acceptance owner | stage2-2-2-3-3-O5 | not-applicable | n/a | not-applicable |
| O6 | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-O6 | not-applicable | n/a | not-applicable |
| S | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-S | not-applicable | n/a | not-applicable |
| C | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | SSOT state projector | stage2-2-2-3-3-C | not-applicable | n/a | not-applicable |
| DA | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | outer orchestrator | stage2-2-2-3-3-DA | not-applicable | n/a | not-applicable |
| DB | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | runtime acceptance owner | stage2-2-2-3-3-DB | not-applicable | n/a | not-applicable |
| DC | 0 | 0 | structured receipt plus scoped acceptance or terminal failure | independent acceptance owner | stage2-2-2-3-3-DC | not-applicable | n/a | not-applicable |

## 临时提示与运行句柄清理

| Task ID | Prompt path | Prompt SHA-256 | Launch barrier | Prompt cleanup | Runtime handle cleanup | Codex transcript retention |
| --- | --- | --- | --- | --- | --- | --- |
| A | historical-unverified | historical-unverified | historical-unverified | historical-unverified | historical-unverified | historical-unverified; no retroactive worker claim |
| A1 | historical-unverified | historical-unverified | historical-unverified | historical-unverified | historical-unverified | historical-unverified; no retroactive worker claim |
| K | historical-unverified | historical-unverified | historical-unverified | historical-unverified | historical-unverified | historical-unverified; no retroactive worker claim |
| F1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| F2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| F3 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| B | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/B.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| S1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/S1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| S2 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/S2.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| S3 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/S3.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| S4 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/S4.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| S5 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/S5.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| T1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/T1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C2 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C2.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C3 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C3.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C4 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C4.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C5 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C5.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C6 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C6.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C7 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/C7.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C8 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| O1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/O1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| O2 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/O2.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| O3 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/O3.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| O4 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/prompts/O4.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| O5 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| O6 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| S | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| C | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DA | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DB | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DC | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |

## 执行门禁

| Guard ID | Authority basis | Allowed write roots | Forbidden paths | External targets | External side effects | Destructive actions | Secret handling | Baseline | Recovery | Postflight diff | Readback | Rollback condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-DOC | 用户明确授权创建第二阶段 SSOT | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing | 其他 agents-results、第一阶段包、项目代码、远程系统 | none | none | none | 不得读取凭据 | 十二项输入文件 SHA-256 已登记 | 重跑生成器并恢复上次通过校验的视图 | 只允许本 bundle 新增文件 | render/check/snapshot 哈希读回 | 任何来源哈希或生成视图漂移 |
| G-UPSTREAM | 第一阶段 C1/C3/DC2 正式节点合同 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/worker-returns | 第一阶段机器节点、第一阶段候选、项目源码、生产和飞书资源 | 第一阶段机器源只读入口 | none | none | 不读取明文凭据 | 第一阶段 manifest、节点状态和候选哈希复算 | 无修复；状态不成立时保持 BLOCKED | 仅新增零写入投影回执 | 上游节点与候选身份读回 | 发现任何上游写入、状态伪造或哈希漂移 |
| G-PHASE2 | K 第 4 版决定、第一阶段 G1 运行配置回执与 M1 汇合协议 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work | 第一阶段候选、活动发布、其他 agents-results、未授权租户、飞书真实组织 | 隔离数据库、隔离个人成果和节点声明的测试资源 | 仅节点合同列明的实现和测试 | 禁止跨租户迁移、复杂删除和生产切换 | 秘密用引用或受控输入；不得进入 argv、日志或截图 | 每节点先捕获源码、schema、合同和运行身份 | 隔离候选回退；失败进入所属状态机 | 只允许节点专属目录、明确共享合同和机器分片 | 服务端上下文、租户范围、成果和版本回读 | 越界写入、跨租户、错正文权威、凭据泄漏或候选身份变化 |
| G-FEISHU | 当前会话的活跃组织 Binding、F2 投影与 K 第 4 版正文决定 | 隔离候选、节点证据目录和获批飞书测试文档 | 其他组织、全局凭据、个人正文、生产未批准资源 | 批准的隔离飞书组织、Wiki 空间和父节点 | 仅 O2/O5 合同允许的创建、编辑和回读 | 禁止复杂删除、搬迁或影响非测试资源 | 按 Binding 解析密钥引用；明文不得进入 argv、日志或证据 | 先读回租户、Binding、凭据世代、空间、父节点和文档身份 | 幂等续接或隔离测试资源补偿；不得切换全局 Writer | 写前后远端版本、镜像、链接和数据库差异 | 同一 Binding 的飞书与 Web 镜像回读 | 错租户、错 Binding、回读失败、可信链接失败或未授权副作用 |
| G-RELEASE | C 候选身份与批准发布窗口 | 不可变候选和本 bundle 证据目录 | 第一阶段历史、第三阶段能力、其他项目栈和未列明租户 | 批准的生产栈及隔离个人/飞书验收身份 | DB 只原子切换代码发布身份，并执行声明的数据库与飞书外部步骤；DA 只读或本地测试 | 只允许声明的前向迁移、数据库恢复步骤和飞书幂等补偿 | 凭据由运行环境或秘密存储提供并全程脱敏 | 候选、生产、数据库、个人成果、飞书资源和回滚点前置读回 | 代码回指旧发布；数据库执行恢复合同；飞书执行补偿或转入 NEEDS_ATTENTION | 发布前后哈希、schema、活动进程和外部资源差异 | 真实浏览器、数据库、人工智能任务、个人成果、飞书和服务同收据读回 | 任何强制负例失败、外部读回缺失、旧 Writer 存活或观察期告警 |
| G-ZERO | 独立终验职责分离 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/evidence/DC | 源码、候选、数据库、远程服务、飞书资源和节点状态源 | 生产和飞书只读入口 | none | none | 不读取明文凭据；只用验收身份 | 读取 DB 接受的证据身份 | 无修复；失败返回 owning node | 仅新增独立证据结论 | 哈希、发布、账号、租户、Binding、成果、设备和时间读回 | 发现任何写入、第三阶段冒领或证据身份不一致 |

## 资源冲突矩阵

| Resource ID | Resource | Nodes | Mode | Isolation key | Serialization rule |
| --- | --- | --- | --- | --- | --- |
| RES-SSOT | 阶段二机器源与生成视图 | A, A1, K, C, DA, DB, DC | W/R | single-generated-artifact | 仅主调度者汇编 manifest 和视图；其他执行者写节点分片或返回 |
| RES-CONTRACT | 上下文、Writer、成果和 OpenAPI 合同 | B, S1, S3, S4, S5, T1 | W | write-write | B 冻结接口身份；各节点独占合同分片；S 汇合后统一生成 |
| RES-DB | 成果、修订、远端绑定和回读 schema | S4, C5, C6, O3, O4 | W | single-migration | S4 独占迁移编号；其他节点只消费已接受 schema |
| RES-PERSONAL | 隔离个人工作区和内部成果 | C1, C2, C3, C4, C5, C6, C7, C8 | W/R | workspace identity | 按个人租户和成果身份隔离；C8 只汇合已冻结子候选 |
| RES-FEISHU | 隔离组织 Binding、Wiki、父节点和 Docx | O1, O2, O3, O4, O5, O6 | W/R | external identity | O2/O5 的外部写动作按同一 Binding 和文档串行；O6 只汇合证据 |
| RES-CANDIDATE | 第二阶段唯一候选 | C8, O6, S, C, DA, DB, DC | W/R | release identity | C 独占组装；DA 后保持不可变；DB 推广；DC 零写入 |
| RES-PRODUCTION | 活动发布、数据库和外部系统 | DB, DC | W/R | release identity | DB 在批准窗口独占代码切换与分层外部步骤；DC 只读并与发布职责分离 |

## 横切关注项

| Concern | Decision | Owner | Required gate/evidence |
| --- | --- | --- | --- |
| security / authentication / secrets | required | S1/S2/S3/O2/T1 | 服务端上下文、防伪造、跨租户、Binding 凭据和秘密扫描 |
| privacy / compliance / retention | required | S2/C1/O1/S4 | 个人与组织资料隔离、最小收据和成果保留合同 |
| migration / backfill / rollback | required | S3/S4/C5/O2/C/DB | 旧 Writer 清除、成果绑定迁移、代码切换、数据库恢复和飞书补偿 |
| reliability / idempotency / recovery | required | S4/C5/C6/O2/O3/O4 | 写入、登记、回读、重放、并发和部分成功续接 |
| performance / scalability | required | S2/C4/O4/DA | 上下文资料上限、飞书回读时延、分页和并发配额 |
| observability / audit | required | S1/S4/O2/O4/DB | 租户、Binding、能力、成果、版本、时间和候选同收据 |
| accessibility / mobile | required | C6/C7/C8/DB | 个人 Web 编辑、平台版本和端到端移动浏览器回归 |
| internationalization | not-applicable | n/a | 本阶段没有新增多语言产品承诺；不得为填表制造节点 |
| cost / quota | required | S2/O2/O4/DA | 上下文预算、模型调用、飞书配额、重试上限和失败关闭 |
| deployment | required | C/DA/DB | 唯一候选、代码发布身份原子切换、旧路径清除和分层恢复 |
| operational / handoff | required | DB/DC | 活动版本、进程、外部资源、观察期、值守交接和独立读回 |

## 偏差与独立复核规则

L1 只修正文案、定位或非语义执行信息；L2 修改依赖、节点或验收；L3 修改租户授权、Binding、正文权威、数据迁移、外部生命周期或发布身份。L2/L3 必须更新机器分片并重建全部视图。每个发现最多做一次有界独立复核；复核不得修改候选。
