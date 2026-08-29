# 第一阶段执行治理

## 叶子交付清单

| Deliverable ID | Parallel batch | Deliverable | Authority write region | Dependencies | Isolation decision | Conflict class | Owning node | Grouping reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DL-A1 | W-1A-1 | 可复现的来源与能力基线 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/A1.json | A | independent | none | A1 | n/a |
| DL-K1 | W-1A-2 | 个人认证决定第 1 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/K1.json | A1 | independent | none | K1 | n/a |
| DL-K2 | W-1A-2 | 发布控制决定第 1 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/K2.json | A1 | independent | none | K2 | n/a |
| DL-K3 | W-1B-2 | 成员接入决定第 1 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/K3.json | A1 | independent | none | K3 | n/a |
| DL-K4 | W-1A-2 | 数据归属决定第 2 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/K4.json | A1 | independent | none | K4 | n/a |
| DL-K5 | W-1A-2 | 阶段所有权决定第 2 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/K5.json | A1 | independent | none | K5 | n/a |
| DL-K6 | W-1A-2 | 个人认证具体决定第 1 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/K6.json | A1 | independent | none | K6 | n/a |
| DL-GA1 | W-1A-2 | 五类配置定位与权限声明回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/GA1.json | A1 | independent | none | GA1 | n/a |
| DL-G1 | W-1A-3 | 五类配置能力回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/G1.json | GA1 | independent | none | G1 | n/a |
| DL-E11 | W-1A-2 | E11 外部门回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/.ssot/nodes/E11.json | A1 | independent | none | E11 | n/a |
| DL-M1 | W-1A-4 | 可执行候选重建工具与清单 schema | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-m1 | B, G1 | independent | none | M1 | n/a |
| DL-MA1 | W-1A-5 | Release 1A 前向迁移与回读合同 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-ma1-migration | B, G1, K4, M1 | independent | none | MA1 | n/a |
| DL-T1 | W-1A-5 | 保护测试与人工验收矩阵 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-t1 | B, G1, M1 | independent | none | T1 | n/a |
| DL-I1 | W-1A-5 | 可访问且边界明确的统一认证界面 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i1 | B, G1, K1, K6, M1 | independent | none | I1 | n/a |
| DL-I2 | W-1A-5 | 个人认证生命周期与可验证的组织意图收据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i2 | B, G1, K1, K6, M1 | independent | none | I2 | n/a |
| DL-IL1 | W-1A-6 | ExplicitIdentityLink 与审计回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-il1 | I2, K1, K6 | independent | none | IL1 | n/a |
| DL-I3 | W-1A-7 | 可信会话和工作区候选集合 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i3 | I1, I2, IL1, MA1 | independent | none | I3 | n/a |
| DL-I4 | W-1A-8 | PersonalWorkspaceShell | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i4 | I3 | independent | none | I4 | n/a |
| DL-I5 | W-1A-8 | OrganizationWorkspaceShell | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i5 | I3 | independent | none | I5 | n/a |
| DL-I6 | W-1A-8 | 服务端授权与审计日志 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i6 | I3, K4, MA1 | independent | none | I6 | n/a |
| DL-I7 | W-1A-9 | BindingResourceResolver | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i7 | I3, I5, I6, K5 | independent | none | I7 | n/a |
| DL-I9 | W-1A-6 | 稳定关闭态与错误合同 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i9 | B, G1, K5, M1, T1 | independent | none | I9 | n/a |
| DL-I8 | W-1A-10 | 同收据 Pilot 外部证据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-i8 | I5, I6, I7, I9, T1 | independent | none | I8 | n/a |
| DL-C1 | W-1A-9 | 身份工作区子候选 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/C1.json | I4, I5, I6, I9, IL1 | independent | none | C1 | n/a |
| DL-C2 | W-1A-11 | Pilot 子候选 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/C2.json | I8 | independent | none | C2 | n/a |
| DL-DA1 | W-1A-13 | Release 1A 静态证据包 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/DA1.json | CA | independent | none | DA1 | n/a |
| DL-DB1 | W-1A-14 | Release 1A 生产同收据证据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/DB1.json | DA1 | independent | none | DB1 | n/a |
| DL-DC1 | W-1A-15 | Release 1A 独立结论 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/DC1.json | DB1 | independent | none | DC1 | n/a |
| DL-MB1 | W-1B-12 | Release 1B 前向迁移与回读合同 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-mb1-migration | C2, G1, M1 | independent | none | MB1 | n/a |
| DL-P1 | W-1B-13 | Provision 模型 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p1 | MB1 | independent | none | P1 | n/a |
| DL-P2 | W-1B-14 | 事件服务与幂等回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p2 | P1 | independent | none | P2 | n/a |
| DL-P3 | W-1B-15 | 管理员授权、owner 与外部身份回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p3 | MB1, P2 | independent | none | P3 | n/a |
| DL-P5 | W-1B-16 | 资源步骤和 Binding 更新 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p5 | I7, P3 | independent | none | P5 | n/a |
| DL-P6 | W-1B-17 | 持久化 Provision runner 与步骤回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p6 | P1, P2, P3, P5, T1 | independent | none | P6 | n/a |
| DL-P7 | W-1B-18 | 状态与恢复界面 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p7 | P6 | independent | none | P7 | n/a |
| DL-P8 | W-1B-18 | DISABLED 或 REVOKED 回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p8 | I7, P6 | independent | none | P8 | n/a |
| DL-P9 | W-1B-16 | 即时成员接入服务与回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p9 | I2, K3, MB1, P3, T1 | independent | none | P9 | n/a |
| DL-P10 | W-1B-17 | 成员停用服务与会话撤销回执 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-p10 | I3, P3, P9, T1 | independent | none | P10 | n/a |
| DL-C3 | W-1B-19 | Provision 子候选 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/C3.json | P10, P7, P8, P9 | independent | none | C3 | n/a |
| DL-DA2 | W-1B-21 | Release 1B 静态证据包 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/DA2.json | CB | independent | none | DA2 | n/a |
| DL-DB2 | W-1B-22 | Release 1B 生产同收据证据 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/DB2.json | DA2 | independent | none | DB2 | n/a |
| DL-DC2 | W-1B-23 | Release 1B 独立结论 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/DC2.json | DB2 | independent | none | DC2 | n/a |

每个独立叶子交付只归属于一个数字节点。候选、迁移、外部安装和生成视图等共享资源通过资源表串行，不因可用工作进程（worker）数量而强行并发。

## 最大安全并行宽度

| Parallel batch | Leaf deliverables | Independent deliverables | Conflict-grouped deliverables | Logical lane target | Available worker slots | Wave count | Graph ready width | Graph antichain width | Resource-verified width |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W-1A-1 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-10 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-11 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-13 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-14 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-15 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-2 | 7 | 7 | 0 | 7 | 7 | 1 | 0 | 9 | 0 |
| W-1A-3 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-4 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-5 | 4 | 4 | 0 | 4 | 4 | 1 | 0 | 9 | 0 |
| W-1A-6 | 2 | 2 | 0 | 2 | 2 | 1 | 0 | 9 | 0 |
| W-1A-7 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1A-8 | 3 | 3 | 0 | 3 | 3 | 1 | 0 | 9 | 0 |
| W-1A-9 | 2 | 2 | 0 | 2 | 2 | 1 | 0 | 9 | 0 |
| W-1B-12 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-13 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-14 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-15 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-16 | 2 | 2 | 0 | 2 | 2 | 1 | 0 | 9 | 0 |
| W-1B-17 | 2 | 2 | 0 | 2 | 2 | 1 | 0 | 9 | 0 |
| W-1B-18 | 2 | 2 | 0 | 2 | 2 | 1 | 0 | 9 | 0 |
| W-1B-19 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-2 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-21 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-22 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |
| W-1B-23 | 1 | 1 | 0 | 1 | 1 | 1 | 0 | 9 | 0 |

## 工作进程（Worker）执行合同

人工前置使用外部人工传输（`external-manual`），候选重建使用确定性本地传输（`deterministic-local`），状态汇总使用自动投影传输（`automatic-projection`），三者都登记零个 Codex 进程。真正的人工智能实施与审查节点才使用外部 Codex 执行传输（`external-codex-exec`）。合格封装脚本（wrapper）的最终调用必须保留最终调用命令（`exec codex exec`）；聊天内子代理接口（`spawn_agent`）、聊天内子代理和同进程协作接口均不得替代外部工作进程（worker）。登记不是启动授权，也不得由本包调度第 11 次修订（Revision 11）。

| Task ID | Transport | Wrapper | Project root | Literal codex exec contract | Sandbox authority | Dispatch state | Return path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| A1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K2 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K3 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K4 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K5 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| K6 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| B | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | EXITED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-executions/B-retry-2/returns/B-retry-2-luna.json |
| GA1 | external-manual | n/a | n/a | manual prerequisite; zero Codex processes | not applicable | EXITED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/manual-receipts/GA1.json |
| G1 | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes; command=python3 tools/verify_runner_profiles.py --all --fail-closed; determinism_key=runner-profile-registry-plus-negative-capability-probes | bounded local process | EXITED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/deterministic-receipts/G1.json |
| E11 | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes; rule=ACCEPTED iff canonical D3A is ACCEPTED and its candidate receipt is hash-bound | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/projections/E11.json |
| M1 | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes; command=./tools/rebuild_stage1_candidate --manifest PATH --base development/promotion --output FRESH_DIR --check-twice; determinism_key=stage1-manifest-plus-selected-base-bytes-plus-ordered-patch-bytes | bounded local process | EXITED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/deterministic-receipts/M1.json |
| MA1 | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes; command=bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/MA1.sh; determinism_key=stage1-ma1-source-plus-frozen-validation-command | bounded local process | EXITED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/deterministic-receipts/MA1-rerun-20260817.json |
| T1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| I1 | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes; command=bash agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/validation/I1.sh; determinism_key=stage1-i1-source-plus-frozen-validation-command | bounded local process | EXITED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/deterministic-receipts/I1-rerun-20260817.json |
| I2 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | EXITED | n/a |
| IL1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/IL1.json |
| I3 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I3.json |
| I4 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I4.json |
| I5 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I5.json |
| I6 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I6.json |
| I7 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I7.json |
| I9 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I9.json |
| I8 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/I8.json |
| C1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| C2 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| CA | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes; command=./tools/rebuild_stage1_candidate --manifest RELEASE_1A_PATCH_MANIFEST --base promotion --output FRESH_CA_DIR --check-twice; determinism_key=E11-candidate-plus-accepted-release1a-patch-manifests | bounded local process | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/deterministic-receipts/CA.json |
| DA1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| DB1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| DC1 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| MB1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/MB1.json |
| P1 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P1.json |
| P2 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P2.json |
| P3 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P3.json |
| P5 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P5.json |
| P6 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P6.json |
| P7 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P7.json |
| P8 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P8.json |
| P9 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P9.json |
| P10 | external-codex-exec | /Users/vsiyo/.codex/workers/run-lw-terra.sh | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' --skip-git-repo-check --sandbox danger-full-access | writable sandbox | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-returns/P10.json |
| C3 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| CB | deterministic-local | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | deterministic local execution; zero Codex processes; command=./tools/rebuild_stage1_candidate --manifest RELEASE_1B_PATCH_MANIFEST --base promotion --output FRESH_CB_DIR --check-twice; determinism_key=DC1-candidate-plus-accepted-release1b-patch-manifests | bounded local process | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/deterministic-receipts/CB.json |
| DA2 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| DB2 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| DC2 | none | n/a | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent | no worker registered; completed history or thin control node | n/a | BLOCKED | n/a |
| DA | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes; rule=ACCEPTED iff DC1 and DC2 are ACCEPTED; emit stage1-summary.json | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/projections/DA.json |
| DB | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes; rule=mirror DA acceptance and verify release identities without new execution | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/projections/DB.json |
| DC | automatic-projection | n/a | n/a | automatic state projection; zero Codex processes; rule=ACCEPTED iff DB projects accepted DC1 and DC2 evidence; no new release gate | generated state only | BLOCKED | agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/projections/DC.json |

## 五类运行配置前置

| Runtime profile | Owning nodes | Required capability | Forbidden capability | Current state | Blocking node |
| --- | --- | --- | --- | --- | --- |
| implementation-runner | T1/MA1/MB1/I1-I7/I9/P1-P3/P5-P10/C1/C3 | 隔离开发基线与节点最小写入根 | 生产凭据、活动发布、其他租户 | VERIFIED_LOCAL | GA1/G1 已接受；M1 可使用 |
| static-validation-runner | DA1/DA2 | 只读候选；可写临时目录和临时数据库 | 修改候选、生产数据库和外部系统 | VERIFIED_LOCAL | GA1/G1 已接受；候选节点另行绑定 |
| external-test-runner | I8 | 隔离测试组织与受限外部写身份 | 生产发布和其他组织 | VERIFIED_LOCAL_FIXTURE | 真实隔离组织身份由 I8 提供 |
| production-release-runner | DB1/DB2 | 批准窗口、单一候选和生产发布身份 | 未批准窗口与未列明外部资源 | FAIL_CLOSED_VERIFIED | 真实批准窗口由 DB1/DB2 提供 |
| independent-readonly-runner | C2/DC1/DC2 | 只读源码、候选、生产身份和外部回执 | 源码修复、数据库写入、外部写入和节点状态写入 | VERIFIED_LOCAL | 真实只读身份由各验收节点提供 |

## 无 Git 候选汇合协议

| Protocol element | Required record or behavior | Owner | Gate timing |
| --- | --- | --- | --- |
| development_base | 提前开发所用源码快照及每个文件的路径、大小与 SHA-256 | M1 | 开始任何节点 patch 前 |
| promotion_base | CA 使用 E11 绑定的 canonical D3A 候选；CB 使用 DC1 接受候选 | M1/CA/CB | 候选重建前 |
| node patch manifest | 节点、基线身份、patch、文件 ownership、测试和 return.json | 每个实现节点 | worker 退出前 |
| apply order | 固定拓扑序和数据库迁移序；禁止目录覆盖 | candidate assembly owner | CA/CB 重建时 |
| conflict detection | 同文件非声明重叠、过期基线、漏补丁和顺序漂移失败关闭 | M1 | 应用每个 patch 前后 |
| candidate rebuild | 从 promotion_base 重放全部已接受 patch；冲突使所属节点失效；重复两次得到同一候选哈希 | CA/CB deterministic-local | 每次候选变化后 |

## 有限进程预算

| Task ID | Worker processes | Retry limit | Stop condition | Cancellation owner | Idempotency key | PID/session | Log path | Exit code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-A | n/a | n/a | n/a |
| A1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-A1 | n/a | n/a | n/a |
| K | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K | n/a | n/a | n/a |
| K1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K1 | n/a | n/a | n/a |
| K2 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K2 | n/a | n/a | n/a |
| K3 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K3 | n/a | n/a | n/a |
| K4 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K4 | n/a | n/a | n/a |
| K5 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K5 | n/a | n/a | n/a |
| K6 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-K6 | n/a | n/a | n/a |
| B | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-B-retry-2 | PID 41334 / session 01a0098f-b6a1-7980-8a4b-a9359694e22b | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-executions/B-retry-2/logs/B-retry-2-luna.log | 0 |
| GA1 | 0 | 0 | named owner writes a complete receipt or records terminal refusal | main orchestrator | stage1-v4-GA1 | n/a | n/a | pending |
| G1 | 0 | 1 | two rebuilds emit the same candidate hash or fail closed | main orchestrator | stage1-v4-G1 | n/a | n/a | pending |
| E11 | 0 | 0 | projection receipt matches all named source states | main orchestrator | stage1-v4-E11 | n/a | n/a | pending |
| M1 | 0 | 1 | two rebuilds emit the same candidate hash or fail closed | main orchestrator | stage1-v4-M1 | n/a | n/a | pending |
| MA1 | 0 | 1 | two rebuilds emit the same candidate hash or fail closed | main orchestrator | stage1-v4-MA1 | n/a | n/a | pending |
| T1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-T1 | n/a | n/a | n/a |
| I1 | 0 | 1 | two rebuilds emit the same candidate hash or fail closed | main orchestrator | stage1-v4-I1 | n/a | n/a | pending |
| I2 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-I2 | n/a | n/a | n/a |
| IL1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-IL1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/IL1.log | pending |
| I3 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I3 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I3.log | pending |
| I4 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I4 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I4.log | pending |
| I5 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I5 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I5.log | pending |
| I6 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I6 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I6.log | pending |
| I7 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I7 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I7.log | pending |
| I9 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I9 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I9.log | pending |
| I8 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-I8 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/I8.log | pending |
| C1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-C1 | n/a | n/a | n/a |
| C2 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-C2 | n/a | n/a | n/a |
| CA | 0 | 1 | two rebuilds emit the same candidate hash or fail closed | main orchestrator | stage1-v4-CA | n/a | n/a | pending |
| DA1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-DA1 | n/a | n/a | n/a |
| DB1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-DB1 | n/a | n/a | n/a |
| DC1 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-DC1 | n/a | n/a | n/a |
| MB1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-MB1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/MB1.log | pending |
| P1 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P1 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P1.log | pending |
| P2 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P2 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P2.log | pending |
| P3 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P3 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P3.log | pending |
| P5 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P5 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P5.log | pending |
| P6 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P6 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P6.log | pending |
| P7 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P7 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P7.log | pending |
| P8 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P8 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P8.log | pending |
| P9 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P9 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P9.log | pending |
| P10 | 1 | 1 | structured return plus scoped acceptance or terminal failure | main orchestrator | stage1-v4-P10 | pending | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-logs/P10.log | pending |
| C3 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-C3 | n/a | n/a | n/a |
| CB | 0 | 1 | two rebuilds emit the same candidate hash or fail closed | main orchestrator | stage1-v4-CB | n/a | n/a | pending |
| DA2 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-DA2 | n/a | n/a | n/a |
| DB2 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-DB2 | n/a | n/a | n/a |
| DC2 | 0 | 0 | node-local owner or historical record; no Codex process | n/a | stage1-v5-DC2 | n/a | n/a | n/a |
| DA | 0 | 0 | projection receipt matches all named source states | main orchestrator | stage1-v4-DA | n/a | n/a | pending |
| DB | 0 | 0 | projection receipt matches all named source states | main orchestrator | stage1-v4-DB | n/a | n/a | pending |
| DC | 0 | 0 | projection receipt matches all named source states | main orchestrator | stage1-v4-DC | n/a | n/a | pending |

## 临时提示与运行句柄清理

| Task ID | Prompt path | Prompt SHA-256 | Launch barrier | Prompt cleanup | Runtime handle cleanup | Codex transcript retention |
| --- | --- | --- | --- | --- | --- | --- |
| A | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| A1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K3 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K4 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K5 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| K6 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| B | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/worker-executions/B-retry-2/prompts/B-retry-2-luna.txt | 15765b36988bd97f2665e5ed9dde674025a23820ca04fec82a21610d84c8e89e | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| GA1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| G1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| E11 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| M1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| MA1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| T1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| I1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| I2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| IL1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/IL1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I3 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I3.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I4 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I4.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I5 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I5.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I6 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I6.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I7 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I7.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I9 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I9.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| I8 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/I8.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| C2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| CA | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DA1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DB1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DC1 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| MB1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/MB1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P1.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P2 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P2.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P3 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P3.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P5 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P5.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P6 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P6.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P7 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P7.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P8 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P8.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P9 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P9.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| P10 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/prompts/P10.txt | capture-before-launch | all wave PIDs registered before first wait | delete after exit evidence registration | release after exit evidence registration | preserve ~/.codex/sessions and ~/.codex/archived_sessions |
| C3 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| CB | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DA2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DB2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DC2 | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DA | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DB | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |
| DC | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process | not-applicable; zero Codex process |

## 执行门禁

| Guard ID | Authority basis | Allowed write roots | Forbidden paths | External targets | External side effects | Destructive actions | Secret handling | Baseline | Recovery | Postflight diff | Readback | Rollback condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G-DOC | 用户授权与机器源第 4 版 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding | 其他 agents-results、canonical 包、项目代码和远程系统 | none | none | none | 不得读取凭据 | 六个输入校验值与六项已接受决定 | 重跑生成器恢复通过校验的视图 | 只允许本 bundle 任务自有文件 | render/check/snapshot 哈希读回 | 来源、决定记录或生成视图漂移 |
| G-PHASE1 | K 第 2 版稳定决定、K1-K6 已接受局部决定、GA1/G1 与 M1 | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work | Revision 11、活动发布、其他 agents-results 和未授权租户 | 只限节点声明的隔离数据库或测试组织 | 只执行节点合同列明动作 | 禁止跨租户迁移和复杂资源删除 | 秘密只通过受控输入，不进 argv、日志或截图 | 开发基线、schema 和运行身份 | 丢弃隔离候选；外部动作按回执补偿 | patch manifest 与基线差异 | Session、Membership、Binding 与节点输出 | 越界写、泄密、冲突或候选漂移 |
| G-STATIC | CA/CB 不可变候选与静态验证合同 | 隔离构建目录、临时目录和临时数据库 | 候选源、生产数据库、活动发布、凭据存储和外部系统 | none | none | 仅清理本次隔离临时资源 | 验证进程不得接收生产凭据 | 候选哈希、迁移拓扑和干净临时资源 | 删除临时目录和临时数据库后可重复执行 | 候选哈希不变且临时资源无越界写入 | 构建、合同、迁移与候选哈希回读 | 候选被修改、生产资源被访问或临时写入越界 |
| G-RELEASE | CA/CB 候选、K2、E11 和批准窗口 | 不可变候选与本 bundle 证据目录 | Revision 11 权威、其他项目栈和未列明租户 | 批准生产栈和隔离飞书组织 | 仅 DB1/DB2 切换代码身份、执行迁移合同和外部步骤 | 只允许前向迁移与已声明最小撤销 | 凭据由生产配置注入并脱敏 | 候选、数据库、飞书资源、停止开关和恢复点 | 代码回指旧身份；数据库按恢复合同；飞书补偿或 NEEDS_ATTENTION | 发布前后哈希、schema、进程与外部资源差异 | 真实浏览器、数据库、飞书与服务同收据 | 负例失败、读回缺失或观察告警 |
| G-ZERO | 职责分离与 independent-readonly-runner | /Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/evidence | 源码、候选、数据库、服务、飞书资源和节点状态源 | 生产与飞书只读入口 | none | none | 只用验收身份且无写凭据 | 读取所属 DB1/DB2 接受证据身份 | 无修复；失败返回 owning node | 仅新增独立证据结论 | 哈希、发布、租户、Binding、设备和时间 | 发现写入或证据身份不一致 |

## 资源冲突矩阵

| Resource ID | Resource | Nodes | Mode | Isolation key | Serialization rule |
| --- | --- | --- | --- | --- | --- |
| RES-R11-CANDIDATE | Revision 11 D3A 外部状态 | E11/CA/CB | R | external authority | E11 自动投影；本包不登记 canonical 执行器或写证据 |
| RES-MACHINE | 本 bundle 机器分片与 manifest | A/B/CA/CB | W | single-generated-artifact | 唯一汇编 owner 写 manifest 和视图索引 |
| RES-NOGIT | 基线、patch manifest 与候选重建 | M1/all implementation/CA/CB | W | baseline hash | 固定应用顺序；冲突失败关闭；禁止目录 overlay |
| RES-AUTH | Session/OAuth/OpenAPI 合同 | I2/I3/I6/T1 | W | write-write | T1 维护共享合同；业务节点写各自实现 |
| RES-DB-1A | 账号、会话、工作区与近期活动 schema | MA1/I3/I6 | W/R | single-migration | MA1 独占 Release 1A 迁移编号；I3/I6 只消费 |
| RES-DB-1B | 安装、接入回执与成员身份 schema | MB1/P1/P3/P6/P9/P10 | W/R | single-migration | MB1 独占 Release 1B 迁移编号；其余节点只消费 |
| RES-FEISHU-PILOT | 隔离 Pilot 组织 | I8/C2 | W/R | external identity | I8 独占写；C2 零写入复核 |
| RES-PROVISION | 隔离安装、资源、成员首次授权与失效 | P2-P10 | W | installation identity | 按安装身份、(binding_id, open_id) 和步骤租约串行外部动作 |
| RES-PRODUCTION | 活动发布与数据库 | DB1/DC1/DB2/DC2 | W/R | release identity | DB1/DB2 单写；DC1/DC2 真正只读 |

## 横切关注项

| Concern | Decision | Owner | Required gate/evidence |
| --- | --- | --- | --- |
| security / authentication / secrets | required | I2/I6/P2/P3 | OAuth 防篡改、服务端授权、秘密扫描和撤销负例 |
| privacy / compliance / retention | required | I6/P8/P9 | 租户隔离、open_id 最小使用、最小日志和审计保留合同 |
| migration / backup / recovery | required | MA1/MB1/P6 | 两套前向迁移编号、备份身份、检查点恢复和回读 |
| reliability / rollback / disaster | required | P6/DB1/DB2 | 代码原子切换、数据库恢复合同、外部幂等补偿和事故停止条件 |
| performance / capacity | required | P6/P9/P10 | 即时成员并发、队列与外部配额上限；完整目录转交 Stage 1C |
| observability / alerting | required | P6/P7/DB1/DB2 | 步骤回执、NEEDS_ATTENTION、告警和观察窗口 |
| accessibility / internationalization / i18n | required | I1/I4/I5/P7 | 键盘、移动端、中文错误和语义标签 |
| cost / external-service | required | P5/P9/DB2 | 飞书 API 配额、重试上限和资源创建计数 |
| deployment / readback / monitoring | required | DA1/DB1/DA2/DB2 | 候选身份、代码切换、生产读回和监控 |
| operational / handoff | required | C1/C3/DC2 | 第二阶段移交、支持处置和独立终验责任 |

## 偏差与独立复核规则

L1 只修正文案、定位或非语义执行信息；L2 修改依赖、节点或验收；L3 修改认证、权限、数据迁移、外部生命周期或发布身份。L2/L3 必须更新机器分片并重建全部视图。每个发现最多做一次有界独立复核；复核不得修改候选。
