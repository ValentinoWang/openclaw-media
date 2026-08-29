# CPC-01/02/03/04 复核证据

复核时间：2026-08-29
复核仓库：`p1-implementation-20260828/integration`
复核基线：`fcd450da6387b5536f95cfa3358a37c8403e89ac`

## 结论

CPC-01、CPC-02、CPC-03、CPC-04 在当前 `main` 源码中均已关闭。本次没有真实源码缺口，因此没有修改创作实现、保护测试或 `implementation-progress.md`。

审计基线 `docs/production-reconciliation/20260827/pipeline-full-audit.md` 的对应条目仍保留历史状态“未修复”，以下以当前源码、原子提交和定向测试复核为准。

## 逐项证据

| 条目 | 当前源码证据 | 覆盖提交 | 定向测试证据 |
|---|---|---|---|
| CPC-01 | `selfmedia/creation/llm_generator.py:766-767` 仅接受七项分项并由程序 `sum()` 生成 `score`；`build_creation_prompt` 的 `llm_generator.py:236-238` 明确要求模型不输出总分。 | `8d3410c2bd590e1ff9f758b172f6250b2d013d65` (`fix(p1): derive scores and isolate creation roles`) | `tests/test_creation_prompt_evidence_contract.py::test_scores_are_derived_from_breakdowns_instead_of_model_arithmetic` |
| CPC-02 | `selfmedia/creation/llm_generator.py:845-846` 对 viral/inspiration 分项由程序求和，移除了模型总分等式门禁。 | `8d3410c2bd590e1ff9f758b172f6250b2d013d65` | 同上，断言候选匹配分由分项派生为 84，即使输入模型 `score=1` 也不被采用。 |
| CPC-03 | `config/openclaw_bots.json:97-100` 将 `media_creation` 配置为 tier B；`tests/test_media_profile_tier_ordering.py:12-28` 锁定配置和运行时解析结果。 | `aa776ba4239ac71fcbb95eab30baf6a900259c36` (`fix(media): enforce tier B profile policy`) | `tests/test_media_profile_tier_ordering.py::test_media_profiles_override_the_media_bot_default_with_tier_b`；`tests/test_bot_llm_config.py::test_all_profiles_use_canonical_openclaw_oauth_provider` |
| CPC-04 | `selfmedia/creation/backwash.py:216-228` 在叙事规划/修订验收失败后返回 `pending_manual` 和最后候选稿，不再抛出 RuntimeError 或写入原文档；`backwash.py:341-359`、`410-432` 保留两轮生成但把最终人工决策交给调用方。 | `c51fb43c29fab1ab609bb1530929b14e13efc019` (`fix(creation): harden prompt fallback contracts`) | `tests/test_shooting_backwash.py::ShootingBackwashPipelineTests::test_failed_coherence_review_returns_candidate_without_writing_or_persisting` |

## 验证

命令：

```text
/tmp/openclaw-media-p1-venv/bin/python -m pytest -q \
  tests/test_creation_prompt_evidence_contract.py \
  tests/test_shooting_backwash.py \
  tests/test_media_profile_tier_ordering.py \
  tests/test_bot_llm_config.py
```

结果：`34 passed`。仅出现既存 Pydantic 弃用警告，无失败。

## 工作区边界

本次复核新增本文件并提交；未改动 `selfmedia/creation/`、`config/`、已有测试或 `agents-results/2026-08-29/media-p1-remaining-development-paths/implementation-progress.md`。工作区原有未跟踪 `.codex-work/` 未处理。
