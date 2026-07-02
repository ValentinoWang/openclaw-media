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


class StylePolishTests(unittest.TestCase):
    def test_aliases_normalize_to_one_capability(self) -> None:
        for tag in ("【润色】", "【网感】", "【文案优化】", "【改标题】", "【去AI味】", "【小红书文案】", "【抖音文案】"):
            self.assertEqual(normalize_style_polish_tag(f"{tag} 原文"), STYLE_POLISH_CAPABILITY)

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
            result = run_style_polish(request, vault_root=tmp, run_id="style_polish_test")
            result_path = Path(tmp) / "style_polish_runs" / "style_polish_test" / "result.json"
            self.assertTrue(result_path.exists())
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_uri"], "media://style_polish_runs/style_polish_test/result.json")
            self.assertEqual(payload["feedback_record"]["creative_pattern_promotion"], "manual_only")
            self.assertFalse(payload["creation_run_binding"]["bound"])
            self.assertEqual(len(payload["versions"]), 3)
            self.assertTrue(any(item["source_type"] == "platform_mechanism" and item["loaded"] for item in payload["source_trace"]))
            self.assertTrue(any(item["source_type"] == "account_persona" for item in payload["source_trace"]))
            for version in payload["versions"]:
                self.assertIn("训练不是靠鸡血", version["text"])
                self.assertIn("复盘和稳定执行", version["text"])
                self.assertNotIn("保证爆款", version["text"])

    def test_creation_binding_only_when_explicit_id_exists(self) -> None:
        request = StylePolishRequest(raw_text="标题太平了，需要更短。", platform="小红书", creation_id="cr_001")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_style_polish(request, vault_root=tmp, run_id="style_polish_bound")
            self.assertTrue(result.creation_run_binding["bound"])
            self.assertEqual(result.creation_run_binding["feishu_write_policy"], "summary_and_link_only")

    def test_pattern_candidate_does_not_promote_creative_pattern(self) -> None:
        request = StylePolishRequest(raw_text="原文。", platform="抖音")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_style_polish(request, vault_root=tmp, run_id="style_polish_feedback")
            candidate = build_pattern_candidate(result, evidence_note="用户连续选择该表达形态")
            self.assertEqual(candidate["target_entity"], "CreativePattern")
            self.assertTrue(candidate["requires_manual_confirmation"])
            self.assertEqual(candidate["creative_pattern_promotion"], "manual_only")

    def test_style_layer_has_no_shadow_ssot_assets(self) -> None:
        failures = scan_forbidden_style_ssot(ROOT / "selfmedia" / "style")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
