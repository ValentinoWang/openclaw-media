from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from media_vault import MediaVault, MediaVaultUriError


class MediaVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "media_vault"
        self.vault = MediaVault(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_manifest_and_uri_round_trip(self) -> None:
        manifest = self.vault.ensure_manifest()
        self.assertEqual(manifest["version"], "media_vault_v1")
        self.assertEqual(manifest["uri_scheme"], "media://")
        path = self.root / "creation_runs" / "run_20260620_abcd" / "request.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")

        uri = self.vault.to_uri(path)
        self.assertEqual(uri, "media://creation_runs/run_20260620_abcd/request.json")
        self.assertEqual(self.vault.resolve_uri(uri), path.resolve())

    def test_rejects_paths_outside_vault(self) -> None:
        with self.assertRaises(MediaVaultUriError):
            self.vault.to_uri(Path(self.tmp.name) / "outside.json")
        with self.assertRaises(MediaVaultUriError):
            self.vault.resolve_uri("media://creation_runs/../outside.json")

    def test_write_creation_run_artifacts(self) -> None:
        artifacts = self.vault.write_creation_run_artifacts(
            "run_20260620_test",
            request={"entrypoint": "【创作】", "topic": "短跑比赛"},
            input_payload={"raw": "用户输入"},
            retrieval_candidates={"materials": []},
            decision_trace=[{"candidate_id": "asset_1", "score": 91, "selected": True}],
            material_usage=[{"asset_id": "asset_1", "usage_type": "结构参考"}],
            draft_output={"title": "起跑前一秒"},
            validation_report={"ok": True},
        )

        self.assertIn("request", artifacts)
        self.assertIn("decision_trace", artifacts)
        request_manifest = artifacts["request"]
        self.assertEqual(request_manifest["owner_type"], "CreationRun")
        self.assertTrue(request_manifest["content_hash"].startswith("sha256:"))
        request_path = self.vault.resolve_uri(request_manifest["uri"])
        self.assertEqual(json.loads(request_path.read_text(encoding="utf-8"))["topic"], "短跑比赛")
        self.assertFalse(self.vault.validate_artifact_manifest(request_manifest))

    def test_source_asset_render_quote_and_review_artifacts(self) -> None:
        source = self.vault.write_source_asset_bundle(
            platform="xhs",
            asset_id="asset_xhs_20260620_test",
            manifest={"asset_id": "asset_xhs_20260620_test", "source_url": "https://example.com/a"},
            original_text="原文",
            extracted_text="归一化文本",
            evidence={"source": "screenshot"},
        )
        self.assertIn("manifest", source)
        self.assertIn("original_text", source)
        self.assertEqual(source["manifest"]["owner_type"], "SourceAsset")

        render = self.vault.write_render_artifacts(
            "render_20260620_test",
            render_spec={"render_id": "render_20260620_test", "run_id": "run_1", "template_version": "v1", "sections": []},
            html="<html></html>",
            feishu_doc_blocks=[{"text": {"elements": []}}],
        )
        self.assertIn("render_spec", render)
        self.assertEqual(render["render_spec"]["owner_type"], "RenderArtifact")

        quote = self.vault.write_quote_snapshot("opportunity_20260620_test", {"amount": 1499, "rebate_ratio": 0.2})
        self.assertEqual(quote["artifact_type"], "quote_snapshot")

        review = self.vault.write_post_review(
            "post_20260620_test",
            "24h",
            metrics={"impressions": 12000},
            review_markdown="# 24h 复盘\n表现稳定",
        )
        self.assertIn("metrics", review)
        self.assertIn("review", review)
        self.assertEqual(review["metrics"]["owner_type"], "PublishedPost")


if __name__ == "__main__":
    unittest.main()
