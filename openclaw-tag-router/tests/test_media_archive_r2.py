from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from openclaw_app.adapters.http_api import OpenClawHttpHandler
from openclaw_app.services.media_web_tasks import MediaWebTaskError
from openclaw_app.services.media_archive_service import (
    ARCHIVE_HTTP_BODY_MAXIMUM_BYTES,
    MediaArchiveError,
    MediaArchiveService,
    MediaArchiveStore,
    resolve_archive_operation,
)
from openclaw_app.services.media_device_job_contract import resolve_r1_operation, validate_r1_response


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


class MediaArchiveR2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Path(self.temp_dir.name) / "archives.sqlite3"
        self.now = [1_754_272_000.0]
        self.store = MediaArchiveStore(self.db, clock=lambda: self.now[0])
        self.service = MediaArchiveService(self.store, quota_bytes=32)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def item(
        ref: str = "artifact:text-1",
        *,
        value: str = '{"ok":true}',
        mode: str = "content",
        mime_type: str = "application/json",
        encoding: str = "utf8",
        sha256: str | None = None,
        size_bytes: int | None = None,
        descriptor: bool | None = None,
        content: Any = "__default__",
    ) -> dict[str, Any]:
        raw = value.encode("utf-8")
        if sha256 is None:
            sha256 = hashlib.sha256(raw).hexdigest()
        if size_bytes is None:
            size_bytes = len(raw)
        if content == "__default__":
            content = None if mode in {"descriptor_only", "forbidden"} else {"encoding": encoding, "value": value}
        return {
            "ref": ref,
            "mode": mode,
            "mime_type": mime_type,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "descriptor": mode == "descriptor_only" if descriptor is None else descriptor,
            "metadata": {"name": "note", "description": None, "source_ref": "asset:local-id"},
            "content": None if mode == "descriptor_only" else content,
        }

    def payload(self, *items: dict[str, Any], **overrides: Any) -> dict[str, Any]:
        manifest = {
            "manifest_id": overrides.pop("manifest_id", "manifest_test"),
            "run_id": overrides.pop("manifest_run_id", "run_test"),
            "confirmation_ref": overrides.pop("manifest_confirmation", "confirm_test"),
            "items": list(items) or [self.item()],
            "created_at": overrides.pop("created_at", "2026-08-04T00:00:00Z"),
        }
        return {
            "run_id": overrides.pop("run_id", manifest["run_id"]),
            "manifest": manifest,
            "confirmation_ref": overrides.pop("confirmation_ref", manifest["confirmation_ref"]),
            **overrides,
        }

    def commit(self, tenant: str = TENANT_A, *, key: str = "commit-1", item: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.service.commit(tenant, self.payload(item or self.item()), idempotency_key=key)

    def test_routes_and_successful_responses_are_frozen_schema_shaped(self) -> None:
        self.assertEqual(resolve_archive_operation("/archives/commit", "POST"), ("archive_commit", {}))
        self.assertEqual(resolve_archive_operation("/archives/arc_x/readback", "POST"), ("archive_readback", {"archive_id": "arc_x"}))
        result = self.commit()
        for operation_id, response in (("archive_commit", result),):
            validate_r1_response(operation_id, response)
        archive_id = str(result["archive"]["archive_id"])
        validate_r1_response("archive_detail", self.service.detail(TENANT_A, archive_id))
        validate_r1_response("archive_list", self.service.list(TENANT_A))
        validate_r1_response("archive_delete_plan", self.service.delete_plan(TENANT_A, archive_id, idempotency_key="plan"))

    def test_generated_contract_resolves_from_clean_checkout_and_explicit_override(self) -> None:
        checkout_root = Path(__file__).resolve().parents[2]
        router_root = checkout_root / "openclaw-tag-router"
        repository_contract = checkout_root / "media-agent-cli/generated_product_contract.py"
        clean_import = "\n".join(
            (
                "from pathlib import Path",
                "from openclaw_app.services import media_archive_service as archive",
                "expected = Path(archive.__file__).resolve().parents[3] / 'media-agent-cli/generated_product_contract.py'",
                "assert archive.CANONICAL_GENERATED_CONTRACT == expected",
                "assert archive.resolve_archive_operation('/archives/commit', 'POST') == ('archive_commit', {})",
                "archive.validate_r1_response('archive_list', {'archives': [], 'next_cursor': None})",
            )
        )
        clean = subprocess.run(
            [sys.executable, "-c", clean_import],
            cwd=router_root,
            env={},
            capture_output=True,
            text=True,
        )
        self.assertEqual(clean.returncode, 0, clean.stderr)

        with tempfile.TemporaryDirectory() as temporary_directory:
            override = Path(temporary_directory) / "generated_product_contract.py"
            shutil.copyfile(repository_contract, override)
            override_import = "\n".join(
                (
                    "import os",
                    "from pathlib import Path",
                    "from openclaw_app.services import media_archive_service as archive",
                    "assert archive.CANONICAL_GENERATED_CONTRACT == Path(os.environ['OPENCLAW_MEDIA_GENERATED_CONTRACT'])",
                    "assert archive.resolve_archive_operation('/archives/commit', 'POST') == ('archive_commit', {})",
                )
            )
            overridden = subprocess.run(
                [sys.executable, "-c", override_import],
                cwd=router_root,
                env={"OPENCLAW_MEDIA_GENERATED_CONTRACT": str(override)},
                capture_output=True,
                text=True,
            )
        self.assertEqual(overridden.returncode, 0, overridden.stderr)

    def test_full_manifest_persists_text_content_and_descriptor_without_media_bytes(self) -> None:
        descriptor = self.item("asset:video", mode="descriptor_only", mime_type="video/mp4", sha256=hashlib.sha256(b"").hexdigest(), size_bytes=0)
        result = self.commit(item=self.item())
        descriptor_result = self.service.commit(TENANT_A, self.payload(self.item(), descriptor, manifest_id="manifest_two"), idempotency_key="commit-2")
        self.assertEqual(result["archive"]["media_cloud_bytes"], 0)
        self.assertEqual(descriptor_result["archive"]["artifacts"][1]["content"], None)
        self.assertEqual(descriptor_result["archive"]["artifacts"][0]["content"]["value"], '{"ok":true}')
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT SUM(media_cloud_bytes) FROM archive_records").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM archive_attachments WHERE content IS NOT NULL").fetchone()[0], 2)

    def test_forbidden_mode_is_schema_valid_and_never_persists_bytes(self) -> None:
        raw = b"\x89PNG\r\n"
        item = self.item(
            ref="asset:video",
            mode="forbidden",
            mime_type="video/mp4",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            descriptor=True,
            content=None,
        )
        result = self.commit(key="forbidden", item=item)
        validate_r1_response("archive_commit", result)
        artifact = result["archive"]["artifacts"][0]
        self.assertEqual(artifact["mode"], "forbidden")
        self.assertIsNone(artifact["content"])
        self.assertEqual(result["archive"]["cloud_bytes"], 0)
        self.assertEqual(result["archive"]["media_cloud_bytes"], 0)
        with self.store.connect() as connection:
            attachment = connection.execute(
                "SELECT mode, encoding, content FROM archive_attachments WHERE archive_id = ?",
                (result["archive"]["archive_id"],),
            ).fetchone()
            self.assertEqual(tuple(attachment), ("forbidden", None, None))
            self.assertEqual(connection.execute("SELECT SUM(cloud_bytes) FROM archive_records").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT SUM(media_cloud_bytes) FROM archive_records").fetchone()[0], 0)

    def test_negative_content_fixtures_fail_closed(self) -> None:
        fixtures = (
            (self.item(content={"encoding": "base64", "value": "%%%"}), "content_decode_failed"),
            (self.item(mime_type="video/mp4"), "forbidden_media"),
            (self.item(value="not-json"), "content_magic_mismatch"),
            (self.item(sha256="0" * 64), "content_hash_mismatch"),
            (self.item(size_bytes=1), "content_size_mismatch"),
            (self.item(mode="forbidden", content={"encoding": "utf8", "value": "not uploaded"}), "invalid_mode"),
            (self.item(mode="descriptor_only", content=None, sha256="0" * 64, size_bytes=0), None),
        )
        for index, (item, expected) in enumerate(fixtures):
            if expected is None:
                continue
            with self.assertRaises(MediaArchiveError) as raised:
                self.commit(key=f"negative-{index}", item=item)
            self.assertEqual(raised.exception.code, expected)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM archive_records").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM archive_commits").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM archive_attachments").fetchone()[0], 0)

    def test_base64_content_is_verified_and_bad_magic_is_rejected(self) -> None:
        value = b"# markdown\nhello"
        item = self.item(
            value="ignored",
            mime_type="text/markdown",
            encoding="base64",
            sha256=hashlib.sha256(value).hexdigest(),
            size_bytes=len(value),
            content={"encoding": "base64", "value": base64.b64encode(value).decode("ascii")},
        )
        result = self.commit(item=item)
        self.assertEqual(result["archive"]["cloud_bytes"], len(value))
        png = self.item(
            value="ignored",
            mime_type="text/plain",
            encoding="base64",
            sha256=hashlib.sha256(b"\x89PNG\r\n").hexdigest(),
            size_bytes=6,
            content={"encoding": "base64", "value": base64.b64encode(b"\x89PNG\r\n").decode("ascii")},
        )
        with self.assertRaises(MediaArchiveError) as raised:
            self.commit(key="bad-magic", item=png)
        self.assertEqual(raised.exception.code, "forbidden_media")

    def test_manifest_owner_run_confirmation_refs_quota_and_item_limits_fail_closed(self) -> None:
        with self.assertRaises(MediaArchiveError):
            self.service.commit(TENANT_A, self.payload(self.item(), manifest_run_id="other-run", run_id="run_test"), idempotency_key="owner")
        with self.assertRaises(MediaArchiveError):
            self.service.commit(TENANT_A, self.payload(self.item(), confirmation_ref="wrong"), idempotency_key="confirmation")
        huge = self.item(value="x" * 33, mime_type="text/plain")
        with self.assertRaises(MediaArchiveError) as raised:
            self.commit(key="quota", item=huge)
        self.assertEqual(raised.exception.code, "commit_rejected")
        too_many = [self.item(f"a:{index}", value="x") for index in range(33)]
        with self.assertRaises(MediaArchiveError):
            self.service.commit(TENANT_A, self.payload(*too_many, manifest_id="manifest-many"), idempotency_key="many")

    def test_two_tenant_isolation_idempotency_and_restart_persistence(self) -> None:
        result = self.commit()
        archive_id = str(result["archive"]["archive_id"])
        with self.assertRaises(MediaArchiveError) as raised:
            self.service.detail(TENANT_B, archive_id)
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(self.commit()["archive"]["archive_id"], archive_id)
        with self.assertRaises(MediaArchiveError) as raised:
            self.service.commit(TENANT_A, self.payload(self.item(value="different", mime_type="text/plain")), idempotency_key="commit-1")
        self.assertEqual(raised.exception.code, "idempotency_conflict")
        other = self.commit(TENANT_B, key="commit-1")
        self.assertNotEqual(other["archive"]["archive_id"], archive_id)
        restarted = MediaArchiveService(MediaArchiveStore(self.db, clock=lambda: self.now[0]), quota_bytes=32)
        self.assertEqual(restarted.detail(TENANT_A, archive_id)["archive"]["archive_id"], archive_id)

    def test_delete_stale_revision_expiry_atomic_hard_delete_and_readback(self) -> None:
        archive_id = str(self.commit()["archive"]["archive_id"])
        plan = self.service.delete_plan(TENANT_A, archive_id, idempotency_key="plan")
        with self.assertRaises(MediaArchiveError) as raised:
            self.service.delete(TENANT_A, archive_id, {"delete_plan_id": plan["delete_plan_id"], "confirmation_ref": "confirm_delete", "expected_revision": 2}, idempotency_key="stale")
        self.assertEqual(raised.exception.code, "invalid_state")
        self.now[0] += 601
        with self.assertRaises(MediaArchiveError) as raised:
            self.service.delete(TENANT_A, archive_id, {"delete_plan_id": plan["delete_plan_id"], "confirmation_ref": "confirm_delete", "expected_revision": 1}, idempotency_key="expired")
        self.assertEqual(raised.exception.code, "invalid_delete_plan")
        self.now[0] = 1_754_272_000.0
        plan = self.service.delete_plan(TENANT_A, archive_id, idempotency_key="plan-2")
        original = self.service._idempotency_put
        self.service._idempotency_put = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected"))
        with self.assertRaises(RuntimeError):
            self.service.delete(TENANT_A, archive_id, {"delete_plan_id": plan["delete_plan_id"], "confirmation_ref": "confirm_delete", "expected_revision": 1}, idempotency_key="atomic-delete")
        self.service._idempotency_put = original
        self.assertEqual(self.service.detail(TENANT_A, archive_id)["archive"]["state"], "active")
        deleted = self.service.delete(TENANT_A, archive_id, {"delete_plan_id": plan["delete_plan_id"], "confirmation_ref": "confirm_delete", "expected_revision": 1}, idempotency_key="delete")
        self.assertEqual(deleted["state"], "deleted")
        validate_r1_response("archive_delete", deleted)
        receipt_ref = deleted["delete_receipt"]["receipt_ref"]
        readback = self.service.readback(TENANT_A, archive_id, {"readback_receipt_ref": receipt_ref}, idempotency_key="readback")
        self.assertEqual(readback["archive"], None)
        self.assertTrue(readback["verified"] and readback["hard_deleted"])
        validate_r1_response("archive_readback", readback)
        self.assertEqual(readback, self.service.readback(TENANT_A, archive_id, {"readback_receipt_ref": receipt_ref}, idempotency_key="readback"))
        with self.store.connect() as connection:
            for table in ("archive_records", "archive_commits", "archive_attachments", "archive_projections"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE archive_id = ?", (archive_id,)).fetchone()[0], 0, table)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM archive_readback_receipts WHERE archive_id = ? AND kind = 'delete'", (archive_id,)).fetchone()[0], 1)

    def test_delete_plan_idempotency_replays_until_expiry_then_renews(self) -> None:
        archive_id = str(self.commit()["archive"]["archive_id"])
        first = self.service.delete_plan(TENANT_A, archive_id, idempotency_key="stable-plan")
        self.assertEqual(
            first,
            self.service.delete_plan(TENANT_A, archive_id, idempotency_key="stable-plan"),
        )
        self.now[0] += 601
        renewed = self.service.delete_plan(TENANT_A, archive_id, idempotency_key="stable-plan")
        self.assertNotEqual(renewed["delete_plan_id"], first["delete_plan_id"])
        with self.store.connect() as connection:
            plans = connection.execute(
                "SELECT delete_plan_id FROM archive_delete_plans WHERE archive_id = ? AND tenant_id = ?",
                (archive_id, TENANT_A),
            ).fetchall()
        self.assertEqual([row["delete_plan_id"] for row in plans], [renewed["delete_plan_id"]])

    def test_delete_scrubs_idempotency_content_and_blocks_post_delete_commit_replay(self) -> None:
        marker = "r2-secret-20260804-x"
        payload = self.payload(self.item(value=marker, mime_type="text/plain"))
        committed = self.service.commit(TENANT_A, payload, idempotency_key="content-replay")
        self.assertEqual(
            committed,
            self.service.commit(TENANT_A, payload, idempotency_key="content-replay"),
        )
        archive_id = str(committed["archive"]["archive_id"])
        plan = self.service.delete_plan(TENANT_A, archive_id, idempotency_key="content-plan")
        deleted = self.service.delete(
            TENANT_A,
            archive_id,
            {
                "delete_plan_id": plan["delete_plan_id"],
                "confirmation_ref": "confirm_delete",
                "expected_revision": 1,
            },
            idempotency_key="content-delete",
        )
        validate_r1_response("archive_delete", deleted)
        readback = self.service.readback(
            TENANT_A,
            archive_id,
            {"readback_receipt_ref": deleted["delete_receipt"]["receipt_ref"]},
            idempotency_key="content-readback",
        )
        validate_r1_response("archive_readback", readback)

        with self.store.connect() as connection:
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                ).fetchall()
                if not str(row[0]).startswith("sqlite_")
            ]
            for table in tables:
                for values in connection.execute(f'SELECT * FROM "{table}"').fetchall():
                    for value in values:
                        if isinstance(value, bytes):
                            self.assertNotIn(marker.encode("utf-8"), value, table)
                        elif isinstance(value, str):
                            self.assertNotIn(marker, value, table)
            self.assertGreater(
                connection.execute(
                    "SELECT COUNT(*) FROM archive_idempotency WHERE operation_id = 'archive_commit'"
                ).fetchone()[0],
                0,
            )
            for operation_id, replay_kind, response_json in connection.execute(
                "SELECT operation_id, replay_kind, response_json FROM archive_idempotency WHERE operation_id IN ('archive_commit', 'archive_readback')"
            ).fetchall():
                self.assertIn(operation_id, {"archive_commit", "archive_readback"})
                self.assertEqual(replay_kind, operation_id)
                self.assertEqual(set(json.loads(response_json)), {"archive_id", "receipt_ref"})
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM archive_records WHERE archive_id = ?", (archive_id,)).fetchone()[0],
                0,
            )

        with self.assertRaises(MediaArchiveError) as raised:
            self.service.commit(TENANT_A, payload, idempotency_key="content-replay")
        self.assertEqual(raised.exception.code, "not_found")
        with self.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM archive_records WHERE archive_id = ?", (archive_id,)).fetchone()[0],
                0,
            )

    def test_archive_http_body_limit_covers_full_base64_manifest_and_rejects_one_byte_over(self) -> None:
        raw = b"x" * (1024 * 1024)
        encoded = base64.b64encode(raw).decode("ascii")
        items = [
            {
                "ref": f"artifact:{index}",
                "mode": "content",
                "mime_type": "text/plain",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "descriptor": False,
                "metadata": {"name": "note", "description": None, "source_ref": "asset:local-id"},
                "content": {"encoding": "base64", "value": encoded},
            }
            for index in range(32)
        ]
        body = json.dumps(
            {
                "run_id": "run_test",
                "manifest": {
                    "manifest_id": "manifest_http_max",
                    "run_id": "run_test",
                    "confirmation_ref": "confirm_test",
                    "items": items,
                    "created_at": "2026-08-04T00:00:00Z",
                },
                "confirmation_ref": "confirm_test",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertGreater(len(body), 40 * 1024 * 1024)
        self.assertLessEqual(len(body), ARCHIVE_HTTP_BODY_MAXIMUM_BYTES)

        class BodyProbe:
            def __init__(self, raw_body: bytes, declared_length: int) -> None:
                self.headers = {"Content-Length": str(declared_length)}
                self.rfile = io.BytesIO(raw_body)

        body_at_limit = body + b" " * (ARCHIVE_HTTP_BODY_MAXIMUM_BYTES - len(body))
        self.assertEqual(len(body_at_limit), ARCHIVE_HTTP_BODY_MAXIMUM_BYTES)
        parsed = OpenClawHttpHandler._read_json_body(
            BodyProbe(body_at_limit, ARCHIVE_HTTP_BODY_MAXIMUM_BYTES),
            maximum_bytes=ARCHIVE_HTTP_BODY_MAXIMUM_BYTES,
        )
        self.assertEqual(len(parsed["manifest"]["items"]), 32)

        class NoRead:
            def read(self, _length: int) -> bytes:
                raise AssertionError("oversized body was read")

        oversized = BodyProbe(b"{}", ARCHIVE_HTTP_BODY_MAXIMUM_BYTES + 1)
        oversized.rfile = NoRead()
        with self.assertRaises(MediaWebTaskError):
            OpenClawHttpHandler._read_json_body(oversized, maximum_bytes=ARCHIVE_HTTP_BODY_MAXIMUM_BYTES)

    def test_partial_archive_schema_fails_closed(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        try:
            database = Path(temporary.name) / "partial.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE archive_records (archive_id TEXT PRIMARY KEY)")
            with self.assertRaisesRegex(RuntimeError, "unsupported legacy schema"):
                MediaArchiveStore(database)
        finally:
            temporary.cleanup()

    def test_orphan_prevention_on_commit_failure(self) -> None:
        original = self.service._idempotency_put
        self.service._idempotency_put = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected"))
        with self.assertRaises(RuntimeError):
            self.commit(key="atomic")
        self.service._idempotency_put = original
        with self.store.connect() as connection:
            for table in ("archive_records", "archive_commits", "archive_attachments", "archive_projections", "archive_readback_receipts", "archive_idempotency"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_twenty_route_parity(self) -> None:
        expected = {
            ("GET", "/pipelines"), ("POST", "/pair-codes"), ("POST", "/devices/pair"), ("GET", "/devices"),
            ("POST", "/devices/dev_x/heartbeat"), ("POST", "/devices/dev_x/revoke"), ("POST", "/jobs"),
            ("GET", "/jobs"), ("GET", "/jobs/job_x"), ("POST", "/jobs/job_x/lease"), ("POST", "/jobs/job_x/ack"),
            ("POST", "/jobs/job_x/start"), ("POST", "/jobs/job_x/result"), ("POST", "/cli/releases/compatibility"),
            ("POST", "/archives/commit"), ("GET", "/archives"), ("GET", "/archives/arc_x"),
            ("POST", "/archives/arc_x/delete-plan"), ("DELETE", "/archives/arc_x"), ("POST", "/archives/arc_x/readback"),
        }
        actual = set()
        for method, path in expected:
            resolved = resolve_r1_operation(path, method) or resolve_archive_operation(path, method)
            self.assertIsNotNone(resolved, (method, path))
            actual.add((method, path))
        self.assertEqual(len(actual), 20)


if __name__ == "__main__":
    unittest.main()
