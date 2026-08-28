from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from common.llm_validation import LLMPostValidationError, validate_llm_payload
from selfmedia.creation import backwash


DOC_URL = "https://tcnwueberajc.feishu.cn/wiki/EN03w7cVciEnqWkfQhlcI9bfnEc"


def _beat(
    beat_id: str,
    order: int,
    subject_id: str,
    location: str,
    role: str,
    *,
    callback_to: str = "",
) -> dict[str, object]:
    return {
        "beat_id": beat_id,
        "order": order,
        "subject_id": subject_id,
        "chapter": f"chapter-{order}",
        "location": location,
        "narrative_role": role,
        "purpose": f"purpose-{order}",
        "transition_from_previous": "开场" if order == 1 else f"承接 beat-{order - 1} 的因果结果",
        "callback_to": callback_to,
    }


def _plan(beats: list[dict[str, object]]) -> dict[str, object]:
    return {
        "storyline": "先建立问题，再按连续章节推进并收束",
        "strategy": "result_hook_then_chronological",
        "beats": beats,
        "global_rules": ["每个主体只开启一个连续章节"],
    }


def _review(
    *,
    status: str = "passed",
    score: int = 95,
    transition_issues: list[str] | None = None,
    subject_reentry_issues: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "coherence_score": score,
        "storyline_summary": "连续推进",
        "critical_issues": [],
        "transition_issues": list(transition_issues or []),
        "subject_reentry_issues": list(subject_reentry_issues or []),
        "satisfied_requirements": ["顺序一致"],
        "missing_requirements": [],
        "reason": "相邻边界与主体顺序已审核",
    }


def _draft() -> dict[str, object]:
    return {
        "shooting_goal": {"platform": "抖音"},
        "route_map": [{}],
        "must_shot_list": [{}],
        "branch_plans": [{}],
        "storyboard": [{}],
        "onsite_checklist": ["check"],
        "publishing_pack": {},
        "evidence_appendix": [{}],
    }


class NarrativePlanContractTests(unittest.TestCase):
    def test_unjustified_subject_reentry_is_rejected(self) -> None:
        payload = _plan(
            [
                _beat("beat-1", 1, "睡眠仪", "FT-D019", "introduction"),
                _beat("beat-2", 2, "脑电耳机", "FT-D019", "development"),
                _beat("beat-3", 3, "睡眠仪", "FT-D019", "conclusion"),
            ]
        )

        with self.assertRaisesRegex(LLMPostValidationError, "re-enters without an explicit payoff callback"):
            validate_llm_payload(payload, backwash.NARRATIVE_PLAN_CONTRACT)

    def test_explicit_hook_setup_and_payoff_is_accepted(self) -> None:
        payload = _plan(
            [
                _beat("beat-1", 1, "机器狗结果", "TechJoy", "hook_setup"),
                _beat("beat-2", 2, "脑电因果链", "FT-D019", "development"),
                _beat("beat-3", 3, "机器狗结果", "TechJoy", "hook_payoff", callback_to="beat-1"),
            ]
        )

        result = validate_llm_payload(payload, backwash.NARRATIVE_PLAN_CONTRACT)

        self.assertEqual(result.state, "validated")
        self.assertEqual(result.payload, payload)

    def test_creator_facing_narrative_labels_are_accepted(self) -> None:
        payload = _plan(
            [
                _beat("beat-1", 1, "机器狗结果", "TechJoy", "悬念设置"),
                _beat("beat-2", 2, "脑电因果链", "FT-D019", "展开"),
                _beat("beat-3", 3, "机器狗结果", "TechJoy", "悬念回收", callback_to="beat-1"),
            ]
        )
        payload["strategy"] = "先给结果再回到过程"

        result = validate_llm_payload(payload, backwash.NARRATIVE_PLAN_CONTRACT)

        self.assertEqual(result.state, "validated")
        self.assertEqual(result.payload, payload)


class CoherenceReviewContractTests(unittest.TestCase):
    def test_passed_review_below_ninety_is_rejected(self) -> None:
        with self.assertRaisesRegex(LLMPostValidationError, "still contains coherence failures"):
            validate_llm_payload(_review(score=89), backwash.BACKWASH_REVIEW_CONTRACT)

    def test_passed_review_with_any_issue_is_rejected(self) -> None:
        with self.assertRaisesRegex(LLMPostValidationError, "still contains coherence failures"):
            validate_llm_payload(
                _review(subject_reentry_issues=["睡眠仪在结尾被重新介绍"]),
                backwash.BACKWASH_REVIEW_CONTRACT,
            )


class ShootingBackwashPipelineTests(unittest.TestCase):
    def test_plan_and_reviews_complete_before_same_document_write(self) -> None:
        order: list[str] = []
        current = _draft()
        revised = _draft()
        narrative_plan = _plan(
            [
                _beat("beat-1", 1, "睡眠仪", "FT-D019", "introduction"),
                _beat("beat-2", 2, "脑电耳机", "FT-D019", "development"),
                _beat("beat-3", 3, "机器狗", "TechJoy", "conclusion"),
            ]
        )

        def build(*_args: object, **_kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
            order.append("plan_review")
            return narrative_plan, _review()

        def generate(*_args: object, **_kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
            order.append("draft_review")
            return revised, _review()

        def write(*_args: object, **_kwargs: object) -> str:
            order.append("write")
            return DOC_URL

        def persist(*_args: object, **_kwargs: object) -> None:
            order.append("persist")

        with (
            patch.object(backwash, "_find_creation_run", return_value=("run-test", Path("/tmp/run-test"), {}, {}, current)),
            patch.object(backwash, "_restore_shooting_request", return_value=object()),
            patch.object(backwash, "_build_narrative_plan", side_effect=build),
            patch.object(backwash, "_generate_revised_draft", side_effect=generate),
            patch.object(backwash, "validate_shooting_execution_plan", return_value={"ok": True}),
            patch.object(backwash, "_validate_practical_shape"),
            patch.object(backwash, "rewrite_shooting_execution_doc", side_effect=write),
            patch.object(backwash, "_persist_backwash", side_effect=persist),
        ):
            result = backwash.handle_shooting_execution_backwash(DOC_URL, "按连续产品章节重写", tenant_id="00000000-0000-4000-8000-000000000101")

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["plan_review", "draft_review", "write", "persist"])

    def test_failed_coherence_review_retries_and_never_calls_writer(self) -> None:
        current = _draft()
        candidate = _draft()
        plan = _plan(
            [
                _beat("beat-1", 1, "睡眠仪", "FT-D019", "introduction"),
                _beat("beat-2", 2, "脑电耳机", "FT-D019", "development"),
                _beat("beat-3", 3, "机器狗", "TechJoy", "conclusion"),
            ]
        )
        failed_review = _review(
            status="needs_revision",
            score=72,
            subject_reentry_issues=["A→B→A 回跳"],
        )

        with (
            patch.object(backwash, "_find_creation_run", return_value=("run-test", Path("/tmp/run-test"), {}, {}, current)),
            patch.object(backwash, "_restore_shooting_request", return_value=object()),
            patch.object(backwash, "_build_narrative_plan", return_value=(plan, _review())),
            patch.object(
                backwash,
                "call_creation_json",
                side_effect=[candidate, failed_review, candidate, failed_review],
            ) as llm_call,
            patch.object(backwash, "rewrite_shooting_execution_doc") as writer,
        ):
            with self.assertRaisesRegex(RuntimeError, "A→B→A 回跳"):
                backwash.handle_shooting_execution_backwash(DOC_URL, "消除产品回跳", tenant_id="00000000-0000-4000-8000-000000000101")

        self.assertEqual(llm_call.call_count, 4)
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
