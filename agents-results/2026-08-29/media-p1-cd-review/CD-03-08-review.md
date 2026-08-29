# CD-03/04/06/07/08 复核证据

复核时间：2026-08-29
复核仓库：`p1-implementation-20260828/integration`
复核基线：`c0c5983a1607c233c5a68bad382ffadc41677da4`

## 结论

CD-03、CD-04、CD-06、CD-07、CD-08 在当前 `main` 源码中均已关闭。本次没有发现独立可修复的真实缺口，因此没有修改生产源码、既有测试或审计进度文件。

审计基线 `docs/production-reconciliation/20260827/pipeline-full-audit.md` 中对应条目仍保留历史状态“未修复”；以下以当前源码和定向测试复核为准。

## 逐项证据

| 条目 | 当前源码证据 | 覆盖提交 | 定向测试证据 |
|---|---|---|---|
| CD-03 | `selfmedia/ingest/content_flow/src/pipeline.py:34-100` 从分析结果读取 `action_plan`、`transferable_expression`、`hooks`，经 `build_pattern_payload` 构造 `candidate_pattern` 并以租户边界 `upsert_entity_record("CreativePattern", ...)` 写入；`pipeline.py:317`、`:369` 在缓存和新分析两条路径均调用该桥接。创作检索仍由 `selfmedia/creation/retrieval.py:110-112` 读取 `CreativePattern`。 | `808395f841a5643b5d9077e293717e891ddf5a6c` (`fix(p0): close media creation business feedback loops`) | `tests/test_p0_multidimensional_handoffs.py::P0MultidimensionalHandoffTests::test_content_analysis_persists_stable_candidate_pattern_only`；同时验证未配置租户时安全跳过。 |
| CD-04 | `selfmedia/creation/shooting_execution.py:110-160` 在拍摄执行入口解析并挂载 `deconstruction_evidence`；`:165-215` 只按规范化参考链接匹配素材并调用 `attach_deconstruction_artifact_brief`；`:297-336` 将证据附录注入执行计划 prompt，且 `:356-374` 传入 `reference_shots`、`pacing_notes`、`reuse_guardrails`。无有效 artifact 时明确降级为文字描述。 | `808395f841a5643b5d9077e293717e891ddf5a6c` | `tests/test_p0_multidimensional_handoffs.py::P0MultidimensionalHandoffTests::test_shooting_handoff_uses_only_matching_valid_artifact`、`...::test_shooting_handoff_degrades_when_artifact_is_invalid`；额外 prompt smoke check 确认镜头、节奏和复用边界实际进入 LLM 输入。 |
| CD-06 | `selfmedia/review/data_review.py:193-232` 在复盘分析前调用 `resolve_creation_plan_for_review` 并把计划传入 `analyze_data_screenshots`；`:352-405` 从同租户 `MediaVault.creation_run_dir(run_id)/draft_output.json` 投影标题、`hook_3s`、`validation_targets`、`review_plan` 和 `publishing_pack`；`:506-548` 将其放入复盘 prompt，并在已加载时要求结构化 `plan_comparison`。 | `808395f841a5643b5d9077e293717e891ddf5a6c`、`7fe94e459fe6e90dc39ad28e730ef96156f65c46` | `tests/test_p0_review_loop.py::P0ReviewLoopTests::test_load_creation_plan_projects_only_review_relevant_fields`、`...::test_review_prompt_receives_loaded_creation_plan`、`...::test_loaded_plan_requires_structured_comparison`；同文件还覆盖唯一精确匹配和歧义拒绝。 |
| CD-07 | `selfmedia/deconstruct/viral_content/src/evidence/modality_dag.py:427-473` 对无帧素材标记 `not_applicable`，对 LLM 异常/非法返回标记 `failed`，对有帧但规范化结果为空标记独立失败原因；`:476-502` 返回 `None` 表达生成失败，不再静默返回空列表。 | `a6a7a8479ae8bed459fafb406b9eb9b9359b8f21` (`fix(media): preserve keyframe failure truthfulness`) | `selfmedia/deconstruct/viral_content/tests/test_keyframe_observation_failure.py`：9 个测试场景覆盖无帧、选择不隐藏帧、异常、非法返回、evidence store 保留失败状态和空结果失败。 |
| CD-08 | `selfmedia/context/media_context.py:260-315` 将复盘置于上下文高优先级段；`:318-330` 默认预算为 10,000 字符、环境可配置且封顶 12,000；`:430-470` 注入复盘结论、表现评级、关键指标、洞察和下一步动作；`:367-417` 为各证据段保留预算。 | `4268bb058f93a936129b9c585d4192c84d232970` (`fix(media): close P1 content pipeline gaps`) | `tests/test_media_context_review_bandwidth.py`：4 个测试覆盖默认预算、环境配置/封顶、确定性截断和多证据维度预算；worker 追加的 `tests/test_media_context.py` 集合报告 9 passed。 |

## 验证

主聚焦命令（使用缓存的 CPython 3.12 环境）：

```text
/Users/vsiyo/.cache/uv/archive-v0/AOhaGJ7_Ens4HCPPNQVXk/bin/python -m pytest -q \
  tests/test_p0_multidimensional_handoffs.py \
  tests/test_p0_review_loop.py \
  selfmedia/deconstruct/viral_content/tests/test_keyframe_observation_failure.py \
  tests/test_media_context_review_bandwidth.py \
  tests/test_creation_v1.py
```

结果：`72 passed`。另一次缩小后的证据集合结果为 `59 passed`；CD-04 prompt smoke check 通过。仅有既存 Pydantic 弃用警告，无测试失败。

`pytest` 直接使用系统 Python 时因环境缺少依赖无法收集；该工具环境问题不影响上面的隔离缓存环境结果。

## 工作区边界

本次只新增本文件并提交；未修改受保护测试、生产源码或其他审计文件。工作区原有未跟踪 `.codex-work/` 保留不处理。
