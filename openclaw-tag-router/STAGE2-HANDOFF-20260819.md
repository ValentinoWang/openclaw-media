# Stage-2 接力开发说明

更新时间：2026-08-19（Asia/Shanghai）

这份说明对应远端候选交接分支 `codex/stage2-handoff-20260819`，以及远端工作树：

`/tmp/openclaw-stage2-handoff-20260819/openclaw-tag-router`

该工作树是下一位开发者的唯一接力位置。原候选分支
`codex/stage2-release-20260818` 保持不变，生产 `main` 没有被修改。

交接提交以该分支远端 `HEAD` 为准；接力前请先回读分支哈希和工作树状态。

## 当前代码位置

所有第二阶段代码位于 `openclaw-tag-router/` 下：

| 目录或文件 | 作用 |
| --- | --- |
| `openclaw_app/services/stage2_context.py` | 服务端会话事实、可信人工智能执行上下文、能力副作用校验 |
| `openclaw_app/services/stage2_writer_router.py` | 个人/组织正文唯一写入路由与失败关闭边界 |
| `openclaw_app/services/stage2_personal_pipeline.py` | 个人资料、研究简报、决策简报、个人内部成果流程 |
| `openclaw_app/services/stage2_organization_pipeline.py` | 组织资料、当前 Binding、飞书文档写入与回读镜像流程 |
| `openclaw_app/services/stage2_external_document.py` | 注入式外部文档写入、注册、读回和幂等边界 |
| `openclaw_app/services/stage2_artifact_state.py` | 成果登记与回读状态机 |
| `openclaw_app/services/stage2_runtime.py` | 服务端拥有的个人/组织组合门面、幂等收据和失败关闭 |
| `openclaw_app/services/stage2_gateway.py` | HTTP 入口与服务端会话/Binding 提供器的组合边界 |
| `openclaw_app/services/stage2_release_gate.py` | 第一阶段 F1/F2/F3 上游收据的只读投影 |
| `openclaw_app/services/stage2_candidate_assembly.py` | 第二阶段候选组装、候选身份和全局凭据回退门禁 |
| `openclaw_app/services/stage2_contract_validator.py` | `stage2_writer_contract.json` 的无 I/O、失败关闭校验器 |
| `openclaw_app/contracts/stage2_writer_contract.json` | 个人/组织路由、能力、成果、注册和回读合同 |
| `tests/test_stage2_*.py` | 第二阶段聚焦测试；不得把测试替代生产或外部验收证据 |

HTTP 入口已接入：

- `POST /stage2/personal`
- `POST /stage2/organization`

未注入服务端 `Stage2Gateway` 时，入口必须返回 `503 stage2_unavailable`。

## 已完成并已验证

- 远端候选分支基线：`ed5dc3967dc2cea6447114c42c546725f9386c1d`。
- 本交接分支包含运行时门面、候选组装、Release Gate、HTTP Gateway 和合同验证器。
- 合同验证器已经纳入交接分支并有独立测试，但还没有接入生产启动流程或发布命令；接力者需要决定并实现它的正式调用位置。
- 个人路径固定为 `personal_web/internal`，不得携带 Binding 或远端文档引用。
- 组织路径固定为 `organization_lark/lark`，必须使用服务端当前 ACTIVE Binding。
- 浏览器提交的租户、Binding、能力、路由、凭据、容器和组织字段均失败关闭。
- 写入、成果登记或必要回读失败时，收据不可发布。
- 相同幂等请求可重放；不同请求复用幂等键必须返回冲突。
- 合同验证器不读取文件、不访问网络、不修改输入对象。

交接分支验证命令及结果：

```bash
cd /tmp/openclaw-stage2-handoff-20260819/openclaw-tag-router
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/pytest -q tests/test_stage2_*.py
# 117 passed

PYTHONDONTWRITEBYTECODE=1 \
  /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python \
  -m compileall -q openclaw_app tests
git diff --check
```

这些结果只证明候选代码和注入式测试边界，不证明真实数据库、真实人工智能服务、真实飞书、认证浏览器/设备或生产发布。

## 当前正式状态

第二阶段 SSOT 正式完成度仍为 **9.4%（3/32）**，正式接受节点只有 `A`、`A1`、`K`。`F1`、`F2`、`F3` 分别等待第一阶段 `C1`、`C3`、`DC2` 的正式接受，因此当前没有合法 READY 节点。不得把本分支的代码、117 个测试或候选收据写成 `ACCEPTED`。

第一阶段权威 SSOT：

`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/ssot-development-paths.md`

第二阶段权威 SSOT：

`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md`

## 还缺什么

### 上游硬门禁

1. 第一阶段 `C1` 身份与工作区汇合正式接受，随后生成并接受第二阶段 `F1`。
2. 第一阶段 `C3` 组织接入汇合正式接受，随后生成并接受第二阶段 `F2`。
3. 第一阶段 `DC2` Release 1B 独立终验正式接受，随后生成并接受第二阶段 `F3`。

### 第二阶段生产实现缺口

1. 生产服务端认证会话解析器，产出可信 `ServerSessionFacts`。
2. 生产当前组织 Binding 解析器，禁止客户端选择租户、Binding、凭据和文档容器。
3. 生产租户资料读取器、个人成果持久化 Writer 和成果登记存储。
4. 当前组织 Binding 下的真实飞书 Adapter，包括写入、注册、二次回读、版本核对和待处置状态。
5. 真实人工智能任务生成器和来源事实/语义标注/验证三层证据。
6. 数据库事务、前向恢复和跨服务幂等持久化；不能把数据库和飞书描述成跨系统原子回滚。
7. 认证浏览器与设备上的个人正例、组织正例、跨租户负例、错误关闭和刷新恢复。
8. 独立外部验收收据、候选哈希绑定、部署回读和完整发布/回滚证据。

另外，`stage2_contract_validator.py` 当前是独立的纯函数校验器；它不会自动替代应用启动门禁，也不会自行读取合同文件。接力时应由明确的发布/启动 owning workflow 载入合同并调用它，且保留失败关闭行为。

## 下一位开发者的接力顺序

1. 先进入上面的唯一工作树，确认分支、工作树和 `git status`，不要在 `main` 或原候选分支直接改。
2. 先读取两份 SSOT 的当前台账和节点合同；只有上游 `F1/F2/F3` 正式接受后，才推进对应第二阶段节点。
3. 优先实现服务端认证会话、当前 Binding 和租户资料读取器，所有外部依赖通过构造器注入。
4. 再接入个人持久化和真实组织飞书 Adapter；每个外部写入都必须有幂等键、回读、补偿/待处置状态。
5. 为每一条真实外部路径单独保存 source、test、mock、deployed、production、device 证据身份；不要混用。
6. 每个节点完成后更新第二阶段 `implementation-progress.md`、证据文件和生成视图；正式状态只由节点级独立接受推进。
7. 完成代码后运行 Stage-2 聚焦测试、编译、差异检查，再做真实部署回读和独立外部验收。
8. 只有 `DC` 正式接受后，第二阶段 SSOT 才能写成 100%（32/32）；随后刷新 Obsidian 快照并运行全局 `--audit-archive`。

## 100% 目标

100% 不是“测试全绿”或“候选分支已推送”。目标是第二阶段 `DC` 正式接受，并且同一不可变候选同时证明：个人资料到个人内部成果的完整闭环、组织资料到当前 Binding 下真实飞书文档的写入和二次回读闭环、人工智能文档分流、跨租户与错误 Binding 失败关闭、成果登记和发布条件、真实认证浏览器/设备证据、生产部署回读、独立外部验收，以及对应的恢复和待处置记录。

第三阶段的组织角色、审核、席位、采购、发票、迁移、复杂删除和经营分析不属于本 100% 目标。
