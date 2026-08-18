from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selfmedia.style import STYLE_POLISH_CAPABILITY, StylePolishRequest, normalize_style_polish_tag, run_style_polish
from selfmedia.style.feedback import build_pattern_candidate
from selfmedia.style.validators import scan_forbidden_style_ssot


def style_payload(*, recommended_text: str) -> dict[str, object]:
    return {
        "diagnosis": ["原文信息密度偏高，缺少第一人称停顿和主观判断。"],
        "style_strategy": "按口头转述的顺序重写，每段只保留一个意思。",
        "versions": [
            {
                "name": "自然表达版",
                "text": recommended_text,
                "target_use": "直接发布",
                "score_breakdown": {
                    "naturalness": 5,
                    "voice": 5,
                    "clarity": 5,
                    "fact_fidelity": 5,
                },
                "risk_notes": [],
            }
        ],
        "recommended_version": "自然表达版",
    }


class StylePolishTests(unittest.TestCase):
    def test_aliases_normalize_to_one_capability(self) -> None:
        for tag in ("【润色】", "【网感】", "【文案优化】", "【改标题】", "【去AI味】", "【小红书文案】", "【抖音文案】"):
            self.assertEqual(normalize_style_polish_tag(f"{tag} 原文"), STYLE_POLISH_CAPABILITY)

    def test_default_output_is_one_publishable_version(self) -> None:
        self.assertEqual(StylePolishRequest(raw_text="原文").variants, 1)

    def test_explicit_polish_writes_vault_artifacts_without_creation_binding(self) -> None:
        request = StylePolishRequest(
            raw_text="在当今时代，我想说明训练不是靠鸡血，而是靠复盘和稳定执行。",
            platform="抖音",
            content_type="标题/正文/封面文案",
            goal="更有网感，但不要编造事实",
            account="清华AI小王冲一级",
            must_keep=("训练不是靠鸡血", "复盘和稳定执行"),
            avoid=("保证爆款",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_style_polish(
                request,
                tenant_id="00000000-0000-4000-8000-000000000101",
                vault_root=tmp,
                run_id="style_polish_test",
                provider=lambda _prompt: style_payload(
                    recommended_text="训练不是靠鸡血。对我来说，真正有用的是复盘和稳定执行：每次练完回头看一遍，再把该做的事做下去。"
                ),
            )
            result_path = Path(tmp) / "tenants" / "00000000-0000-4000-8000-000000000101" / "style_polish_runs" / "style_polish_test" / "result.json"
            self.assertTrue(result_path.exists())
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_uri"], "media://tenants/00000000-0000-4000-8000-000000000101/style_polish_runs/style_polish_test/result.json")
            self.assertEqual(payload["feedback_record"]["creative_pattern_promotion"], "manual_only")
            self.assertFalse(payload["creation_run_binding"]["bound"])
            self.assertEqual(len(payload["versions"]), 1)
            self.assertTrue(any(item["source_type"] == "platform_mechanism" and item["loaded"] for item in payload["source_trace"]))
            self.assertTrue(any(item["source_type"] == "account_persona" for item in payload["source_trace"]))
            for version in payload["versions"]:
                self.assertIn("训练不是靠鸡血", version["text"])
                self.assertIn("复盘和稳定执行", version["text"])
                self.assertNotIn("保证爆款", version["text"])

    def test_creation_binding_only_when_explicit_id_exists(self) -> None:
        request = StylePolishRequest(raw_text="标题太平了，需要更短。", platform="小红书", creation_id="cr_001")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_style_polish(
                request,
                tenant_id="00000000-0000-4000-8000-000000000101",
                vault_root=tmp,
                run_id="style_polish_bound",
                provider=lambda _prompt: style_payload(recommended_text="标题别写平，先把人为什么要点开说清楚。"),
            )
            self.assertTrue(result.creation_run_binding["bound"])
            self.assertEqual(result.creation_run_binding["feishu_write_policy"], "summary_and_link_only")

    def test_pattern_candidate_does_not_promote_creative_pattern(self) -> None:
        request = StylePolishRequest(raw_text="原文。", platform="抖音")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_style_polish(
                request,
                tenant_id="00000000-0000-4000-8000-000000000101",
                vault_root=tmp,
                run_id="style_polish_feedback",
                provider=lambda _prompt: style_payload(recommended_text="原文。"),
            )
            candidate = build_pattern_candidate(result, evidence_note="用户连续选择该表达形态")
            self.assertEqual(candidate["target_entity"], "CreativePattern")
            self.assertTrue(candidate["requires_manual_confirmation"])
            self.assertEqual(candidate["creative_pattern_promotion"], "manual_only")

    def test_style_layer_has_no_shadow_ssot_assets(self) -> None:
        failures = scan_forbidden_style_ssot(ROOT / "selfmedia" / "style")
        self.assertEqual(failures, [])

    def test_long_xiaohongshu_copy_is_semantically_rewritten_by_the_style_editor(self) -> None:
        original = (
            "连续体验沉境睡眠仪的脑电采集与状态反馈，再完成 MindBCI 脑电耳机的佩戴、采集和"
            "专注度兴趣状态参考，最后回到机器狗真实演示，形成采集、反馈、指令形成与执行响应的完整链路。"
        )
        rewritten = (
            "我先戴上睡眠仪，又试了 MindBCI 脑电耳机。屏幕开始出数据以后，我才慢慢看懂："
            "机器狗动起来之前，脑电信号还要经过采集、识别，再变成设备能执行的指令。"
        )
        prompts: list[str] = []

        def provider(prompt: str) -> dict[str, object]:
            prompts.append(prompt)
            return style_payload(recommended_text=rewritten)

        request = StylePolishRequest(
            raw_text=original,
            platform="小红书",
            content_type="正文",
            goal="去AI味，更像真人博主",
            must_keep=("MindBCI", "机器狗"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_style_polish(request, tenant_id="00000000-0000-4000-8000-000000000101", vault_root=tmp, run_id="style_polish_natural", provider=provider)

        self.assertEqual(result.versions[0].text, rewritten)
        self.assertNotEqual(result.versions[0].text, original)
        self.assertIn(original, prompts[0])
        self.assertIn("像给朋友发一段 30 秒语音", prompts[0])
        self.assertNotIn("完整链路", result.versions[0].text)

    def test_style_editor_rejects_a_version_that_drops_must_keep_facts(self) -> None:
        request = StylePolishRequest(raw_text="我在 WAIC 看到了 MindBCI。", must_keep=("MindBCI",))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "MindBCI"):
                run_style_polish(
                    request,
                    tenant_id="00000000-0000-4000-8000-000000000101",
                    vault_root=tmp,
                    run_id="style_polish_missing_fact",
                    provider=lambda _prompt: style_payload(recommended_text="我在现场看到了脑电设备。"),
                )


if __name__ == "__main__":
    unittest.main()
