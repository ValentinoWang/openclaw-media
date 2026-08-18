from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from media_vault import MediaVault, MediaVaultError, MediaVaultUriError


class MediaVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "media_vault"
        self.vault = MediaVault(tenant_id="618ff8c4-cc5a-4034-a2c5-226e3ad6cd37", root=self.root)
        self.other = MediaVault(tenant_id="775e0c03-febc-4a39-8ad0-3e18bb8a6d45", root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_requires_positive_decimal_sub2api_user_id(self) -> None:
        for tenant_id in ("", "0", "01", "-1", "tenant-a", " 101 ", "１"):
            with self.subTest(tenant_id=tenant_id), self.assertRaises(MediaVaultError):
                MediaVault(tenant_id=tenant_id, root=self.root)

    def test_manifest_and_uri_round_trip_is_tenant_owned(self) -> None:
        manifest = self.vault.ensure_manifest()
        self.assertEqual(manifest["version"], "media_vault_v2")
        self.assertEqual(manifest["tenant_id"], "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        path = self.vault.creation_run_dir("run_20260730_abcd") / "request.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")

        uri = self.vault.to_uri(path)
        self.assertEqual(uri, "media://tenants/618ff8c4-cc5a-4034-a2c5-226e3ad6cd37/creation_runs/run_20260730_abcd/request.json")
        self.assertEqual(self.vault.resolve_uri(uri), path.resolve())
        with self.assertRaises(MediaVaultUriError):
            self.other.resolve_uri(uri)

    def test_rejects_path_traversal_and_legacy_shared_uri(self) -> None:
        with self.assertRaises(MediaVaultUriError):
            self.vault.to_uri(Path(self.tmp.name) / "outside.json")
        unsafe = (
            "media://tenants/101/creation_runs/../outside.json",
            "media://tenants/101/creation_runs/%2e%2e/outside.json",
            "media://tenants/101/creation_runs/%2Fetc/passwd",
            "media://tenants/202/creation_runs/run/request.json",
            "media://creation_runs/run/request.json",
        )
        for uri in unsafe:
            with self.subTest(uri=uri), self.assertRaises(MediaVaultUriError):
                self.vault.resolve_uri(uri)

    def test_write_creation_run_artifacts_and_read_json(self) -> None:
        artifacts = self.vault.write_creation_run_artifacts(
            "run_20260730_test",
            request={"entrypoint": "【创作】", "topic": "短跑比赛"},
            input_payload={"raw": "用户输入"},
            decision_trace=[{"candidate_id": "asset_1", "selected": True}],
        )
        request_manifest = artifacts["request"]
        self.assertEqual(request_manifest["tenant_id"], "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        self.assertEqual(request_manifest["owner_type"], "CreationRun")
        self.assertEqual(self.vault.read_json_artifact(request_manifest["uri"])["topic"], "短跑比赛")
        self.assertFalse(self.vault.validate_artifact_manifest(request_manifest))
        with self.assertRaises(MediaVaultUriError):
            self.other.read_json_artifact(request_manifest["uri"])

    def test_write_directory_must_be_inside_tenant_root(self) -> None:
        with self.assertRaises(MediaVaultUriError):
            self.vault.write_json_artifact(
                self.other.creation_run_dir("run_other"),
                "request.json",
                {},
                owner_type="CreationRun",
                owner_id="run_other",
                artifact_type="request",
            )

    def test_list_search_export_delete_remain_tenant_scoped(self) -> None:
        first = self.vault.write_quote_snapshot("opp_101", {"amount": 1499})
        self.other.write_quote_snapshot("opp_202", {"amount": 9999})

        listed = self.vault.list_artifacts(artifact_type="quote_snapshot")
        self.assertEqual([item["owner_id"] for item in listed], ["opp_101"])
        self.assertEqual([item["owner_id"] for item in self.vault.search_artifacts("opp_101")], ["opp_101"])
        self.assertFalse(self.vault.search_artifacts("opp_202"))

        exported = self.vault.export_artifact(
            first["uri"], self.vault.tenant_root / "exports" / "opp_101.json"
        )
        self.assertEqual(exported["tenant_id"], "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37")
        with self.assertRaises(MediaVaultUriError):
            self.vault.export_artifact(first["uri"], self.other.tenant_root / "exports" / "stolen.json")

        deleted = self.vault.delete_artifact(first["uri"])
        self.assertTrue(deleted["deleted"])
        with self.assertRaises(MediaVaultUriError):
            self.vault.resolve_uri(first["uri"], require_exists=True)

    def test_manifest_tenant_tampering_fails_closed(self) -> None:
        artifact = self.vault.write_post_review(
            "post_101", "24h", metrics={"impressions": 12000}, review_markdown="# 24h"
        )["metrics"]
        sidecar = self.vault.resolve_uri(artifact["uri"]).with_suffix(".json.manifest.json")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        payload["tenant_id"] = "775e0c03-febc-4a39-8ad0-3e18bb8a6d45"
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(MediaVaultError):
            self.vault.delete_artifact(artifact["uri"])

    def test_legacy_shared_files_are_not_visible(self) -> None:
        legacy = self.root / "creation_runs" / "run_legacy" / "request.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{}", encoding="utf-8")
        self.assertFalse(self.vault.list_artifacts())
        with self.assertRaises(MediaVaultUriError):
            self.vault.resolve_uri("media://creation_runs/run_legacy/request.json")


if __name__ == "__main__":
    unittest.main()
