from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
from unittest.mock import patch

from openclaw_app.app import OpenClawApp
from openclaw_app.models.task import TaskResult
from openclaw_app.services.capability_matcher import CapabilityMatcherError
from openclaw_app.services.guidance_plan import GuidancePlanService, GuidancePlanStore


PLAN_ID = "capplan_abcdefghijklmnop"


def plan_response() -> dict:
    return {
        "schemaVersion": "3",
        "pathStatus": "matched",
        "needSummary": "整理资料后生成小红书稿。",
        "routeExplanation": "先保存素材，再生成稿件。",
        "guidancePlanId": PLAN_ID,
        "steps": [
            {"order": 1, "capabilityId": "source_asset_intake", "variantId": "default", "extractedParams": {"field_3be96f8eb83d": "链接", "field_05b36669c4ad": "拍摄"}, "confidence": 0.95, "evidence": [], "issues": []},
            {"order": 2, "capabilityId": "selfmedia_creation", "variantId": "default", "extractedParams": {}, "confidence": 0.8, "evidence": [], "issues": [], "dependsOn": {"stepOrder": 1, "requiredOutputs": ["source_asset_id"]}},
        ],
    }


class _ContinuationMatcher:
    def compose_continuation(self, plan, bindings):
        assert plan["step"]["capabilityId"] == "selfmedia_creation"
        assert bindings == {"source_asset_id": "source_asset_smoke_001"}
        return {
            "capabilityId": "selfmedia_creation", "variantId": "default",
            "extractedParams": {"platform": "小红书", "field_ba40014ff496": "图文", "track": "PR招募", "field_d6a7576b7962": "招募文案", "source_asset_id": "source_asset_smoke_001"},
            "confidence": 0.96,
            "evidence": [{"fieldKey": "source_asset_id", "quote": "source_asset_smoke_001", "source": "bound_result"}],
        }


class _InvalidContinuationMatcher:
    def compose_continuation(self, plan, bindings):
        raise CapabilityMatcherError(
            "invalid_model_response",
            "续接结构化参数包含未定义字段。",
        )


class _ProviderUnavailableMatcher:
    def compose_continuation(self, plan, bindings):
        raise CapabilityMatcherError("provider_unavailable", "temporary provider outage")


class _Router:
    def route(self, tag, body, **kwargs):
        assert tag == "素材"
        assert "素材类型：链接" in body
        return TaskResult(ok=True, status="created", reply="【素材】已保存", task_id="source_asset_smoke_001", extra={"artifact": {"artifact_id": "source_asset_smoke_001"}})


class _MustNotRunRouter:
    def route(self, tag, body, **kwargs):
        raise AssertionError("completed predecessor handler must not execute again")


def single_step_plan_response() -> dict:
    payload = plan_response()
    payload["steps"] = [
        {
            "order": 1,
            "capabilityId": "selfmedia_creation", "variantId": "default",
            "extractedParams": {"platform": "抖音", "field_ba40014ff496": "视频", "track": "AI", "field_d6a7576b7962": "WAIC"},
            "confidence": 0.95, "evidence": [], "issues": [],
        }
    ]
    return payload


class _CountingRouter:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def route(self, tag, body, **kwargs):
        with self._lock:
            self.calls += 1
        sleep(0.05)
        return TaskResult(ok=True, status="created", reply="【素材】已保存", task_id="source_asset_smoke_001", extra={"artifact": {"artifact_id": "source_asset_smoke_001"}})


class AppGuidanceContinuationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = OpenClawApp.__new__(OpenClawApp)
        self.app.guidance_plan_service = GuidancePlanService(store=GuidancePlanStore())
        self.app.guidance_plan_service.register_match(plan_response(), query="博主资料和合作诉求", current_bot="media")
        self.result = TaskResult(ok=True, status="created", reply="【素材】已保存", task_id="source_asset_smoke_001", extra={"artifact": {"artifact_id": "source_asset_smoke_001"}})

    def test_matching_tag_binds_real_result_and_returns_next_copy(self) -> None:
        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ContinuationMatcher()):
            result = self.app._append_guidance_continuation("素材", f"路径续接ID：{PLAN_ID}", self.result)
        self.assertTrue(result.extra["guidance_continuation"]["ok"])
        self.assertIn("下一步，直接复制发送：", result.reply)
        self.assertIn("source_asset_smoke_001", result.reply)

    def test_process_text_preflight_validates_original_copy_text_not_stripped_body(self) -> None:
        self.app.router = _Router()
        text = self.app.guidance_plan_service.get_public_response(PLAN_ID)["copyProjection"]
        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ContinuationMatcher()):
            result = self.app.process_text(text)
        self.assertTrue(result.ok)
        self.assertNotEqual(result.status, "invalid_guidance_plan")
        self.assertIn("下一步，直接复制发送：", result.reply)

    def test_process_text_recovers_current_copy_without_rerunning_completed_handler(self) -> None:
        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ContinuationMatcher()):
            self.app._append_guidance_continuation("素材", f"路径续接ID：{PLAN_ID}", self.result)
        self.app.router = _MustNotRunRouter()

        result = self.app.process_text(f"【素材】\n路径续接ID：{PLAN_ID}")

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "guidance_plan_recovered")
        self.assertIn("路径已推进，无需重复执行【素材】", result.reply)
        self.assertIn("当前步骤【创作】，直接复制发送：", result.reply)
        self.assertIn("source_asset_smoke_001", result.reply)
        self.assertTrue(result.extra["guidance_continuation"]["recovered"])
        self.assertEqual(self.app.guidance_plan_service.current_ready_step(PLAN_ID), 2)

    def test_process_text_retries_pending_continuation_without_rerunning_handler(self) -> None:
        self.app.guidance_plan_service.bind_step_result(PLAN_ID, step_order=1, task_result=self.result)
        self.app.router = _MustNotRunRouter()

        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ContinuationMatcher()):
            result = self.app.process_text(f"【素材】\n路径续接ID：{PLAN_ID}")

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "guidance_plan_recovered")
        self.assertIn("【素材】已完成，未重复执行；续接指令已重新生成", result.reply)
        self.assertIn("source_asset_smoke_001", result.reply)
        self.assertTrue(result.extra["guidance_continuation"]["retried"])

    def test_process_text_recovers_completed_plan_receipt_and_flags_changed_text(self) -> None:
        self.app.guidance_plan_service = GuidancePlanService(store=GuidancePlanStore())
        payload = single_step_plan_response()
        self.app.guidance_plan_service.register_match(payload, query="生成WAIC脚本", current_bot="media")
        current_copy = self.app.guidance_plan_service.get_public_response(PLAN_ID)["copyProjection"]
        self.app.guidance_plan_service.bind_step_result(
            PLAN_ID,
            step_order=1,
            task_result=TaskResult(
                ok=True,
                status="created",
                reply="脚本文档：https://example.com/script",
                task_id="run_real_001",
                feishu_doc="https://example.com/script",
            ),
        )
        self.app.router = _MustNotRunRouter()

        changed_text = current_copy.replace("主体：WAIC", "主体：WAIC单人双身份")
        result = self.app.process_text(changed_text)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "guidance_plan_completed_recovered")
        self.assertIn("https://example.com/script", result.reply)
        self.assertIn("删除旧路径续接ID后重新发送", result.reply)
        self.assertEqual(result.feishu_doc, "https://example.com/script")
        self.assertTrue(result.extra["guidance_continuation"]["submittedTextChanged"])

    def test_provider_failure_can_retry_continuation_without_rerunning_handler(self) -> None:
        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ProviderUnavailableMatcher()):
            failed = self.app._append_guidance_continuation("素材", f"路径续接ID：{PLAN_ID}", self.result)
        self.assertIn("错误代码：provider_unavailable", failed.reply)
        self.app.router = _MustNotRunRouter()

        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ContinuationMatcher()):
            recovered = self.app.process_text(f"【素材】\n路径续接ID：{PLAN_ID}")

        self.assertTrue(recovered.ok)
        self.assertEqual(recovered.status, "guidance_plan_recovered")
        self.assertIn("续接指令已重新生成", recovered.reply)
        self.assertIn("source_asset_smoke_001", recovered.reply)

    def test_concurrent_duplicate_submission_executes_handler_once(self) -> None:
        router = _CountingRouter()
        self.app.router = router
        text = self.app.guidance_plan_service.get_public_response(PLAN_ID)["copyProjection"]

        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_ContinuationMatcher()):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(self.app.process_text, (text, text)))

        self.assertEqual(router.calls, 1)
        self.assertTrue(all(result.ok for result in results))
        self.assertEqual({result.status for result in results}, {"created", "guidance_plan_recovered"})
        self.assertTrue(all("source_asset_smoke_001" in result.reply for result in results))

    def test_wrong_tag_cannot_advance_plan(self) -> None:
        result = self.app._append_guidance_continuation("拆解", f"路径续接ID：{PLAN_ID}", self.result)
        self.assertEqual(result.extra["guidance_continuation"]["code"], "guidance_plan_tag_mismatch")
        self.assertEqual(self.app.guidance_plan_service.current_ready_step(PLAN_ID), 1)

    def test_failed_handler_preserves_primary_error_and_keeps_step_retryable(self) -> None:
        failed = TaskResult(
            ok=False,
            status="deconstruct_incomplete",
            reply="【拆解】未确认完成。\n原因：未下载到真实视频或图片",
            task_id="",
        )

        result = self.app._append_guidance_continuation("素材", f"路径续接ID：{PLAN_ID}", failed)

        self.assertIs(result, failed)
        self.assertEqual(result.reply, "【拆解】未确认完成。\n原因：未下载到真实视频或图片")
        self.assertNotIn("guidance_continuation", result.extra)
        self.assertEqual(self.app.guidance_plan_service.current_ready_step(PLAN_ID), 1)

    def test_invalid_continuation_exposes_stable_error_surface_and_preserves_detail(self) -> None:
        detail = "续接结构化参数包含未定义字段。"
        with patch("openclaw_app.services.capability_matcher.CapabilityMatcher", return_value=_InvalidContinuationMatcher()):
            result = self.app._append_guidance_continuation("素材", f"路径续接ID：{PLAN_ID}", self.result)

        self.assertIn("错误代码：invalid_model_response", result.reply)
        self.assertIn("原因：能力匹配模型已返回结果，但续接指令未通过可执行指令契约校验。", result.reply)
        self.assertIn(f"详情：{detail}", result.reply)
        self.assertIn("建议：请重新发送同一条原指令", result.reply)
        self.assertIn("不会重复执行已完成步骤", result.reply)
        self.assertNotIn("后续可复制指令暂未生成（invalid_model_response）", result.reply)
        self.assertEqual(
            result.extra["guidance_continuation"],
            {
                "ok": False,
                "code": "invalid_model_response",
                "detail": detail,
            },
        )

    def test_preflight_rejects_modified_structured_projection(self) -> None:
        payload = plan_response()
        payload["steps"][0]["extractedParams"]["field_c675ffae69a2"] = "https://example.com/profile"
        self.app.guidance_plan_service = GuidancePlanService(store=GuidancePlanStore())
        self.app.guidance_plan_service.register_match(payload, query="主页：https://example.com/profile", current_bot="media")
        submitted = f"【素材】\n路径续接ID：{PLAN_ID}"
        blocked = self.app._guidance_plan_preflight("素材", f"路径续接ID：{PLAN_ID}", submitted_text=submitted)
        self.assertEqual(blocked.status, "invalid_guidance_plan")


if __name__ == "__main__":
    unittest.main()
