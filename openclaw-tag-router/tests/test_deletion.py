from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from openclaw_app.models.message import Message
from openclaw_app.router.deletion import DeletionMixin
from openclaw_app.router.deletion_adapters.base import DeletionContext
from openclaw_app.services.resource_owner_registry import ResourceOwnerConflict, ResourceOwnerRegistry
from openclaw_app.services.tenant_owned_resources import TenantOwnedResourceService


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
PROJECTION_TABLES = (
    "creation_run_sources",
    "creation_run_decisions",
    "creation_run_outputs",
    "creation_runs",
)


class FakeProjectionResult:
    def __init__(self, row: tuple[int, ...] | None = None):
        self.row = row

    def fetchone(self) -> tuple[int, ...] | None:
        return self.row


class FakeRunsConnection:
    def __init__(
        self,
        counts: dict[str, int] | None = None,
        *,
        preserve_table: str | None = None,
    ):
        self.counts = {table: int((counts or {}).get(table, 0)) for table in PROJECTION_TABLES}
        self.initial_counts = dict(self.counts)
        self.preserve_table = preserve_table
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeProjectionResult:
        compact = " ".join(query.split())
        self.calls.append((compact, params))
        if compact.startswith("SELECT"):
            return FakeProjectionResult(tuple(self.counts[table] for table in PROJECTION_TABLES))
        if compact.startswith("DELETE FROM media_product."):
            table = next((candidate for candidate in PROJECTION_TABLES if f"media_product.{candidate}" in compact), "")
            if not table:
                raise AssertionError(f"unexpected projection table in query: {compact}")
            if table != self.preserve_table:
                self.counts[table] = 0
            return FakeProjectionResult()
        raise AssertionError(f"unexpected database query: {compact}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        self.counts = dict(self.initial_counts)


class FakeAccountDatabase:
    def __init__(self, connection: FakeRunsConnection):
        self.connection = connection
        self.connect_calls = 0

    @contextmanager
    def connect(self):
        self.connect_calls += 1
        yield self.connection


class DeletionHarness(DeletionMixin):
    def __init__(
        self,
        workspace_root: Path,
        *,
        account_database: FakeAccountDatabase | None = None,
        tenant_id: str = TENANT_A,
    ):
        self.workspace_root = workspace_root
        self.account_database = account_database or FakeAccountDatabase(FakeRunsConnection())
        self.tenant_id = tenant_id
        self.tenant_owned_resources = TenantOwnedResourceService(
            ResourceOwnerRegistry(workspace_root / "resource_owners.sqlite3")
        )
        try:
            self.tenant_owned_resources.registry.create(
                "media.creation_run",
                "run_router_abc123",
                session_tenant_id=tenant_id,
            )
        except ResourceOwnerConflict:
            pass

    def _creation_cleanup_script_path(self) -> Path:
        return Path(__file__).resolve()

    def _deletion_allowed_roots(self, tenant_id: str | None = None) -> list[Path]:
        return [self.workspace_root]

    def _deletion_context(self) -> DeletionContext:
        return DeletionContext(
            workspace_root=self.workspace_root,
            allowed_roots=[self.workspace_root],
            creation_cleanup_script_path=self._creation_cleanup_script_path(),
            tenant_id=self.tenant_id,
            tenant_owned_resources=self.tenant_owned_resources,
            account_database=self.account_database,
        )


def deletion_message(body: str) -> Message:
    return Message(
        entry_tag="删除",
        raw_text=f"【删除】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime.now(),
        metadata={"account_id": "media"},
    )


def cleanup_stdout(mode: str = "dry_run") -> str:
    status = "deleted" if mode == "apply" else "planned"
    return json.dumps(
        {
            "mode": mode,
            "runs": [
                {
                    "run_id": "run_router_abc123",
                    "record_id": "rec1",
                    "warnings": [],
                    "actions": [
                        {"kind": "feishu_doc", "target": "https://example.feishu.cn/wiki/abc", "status": status, "detail": ""},
                        {"kind": "creation_run_record", "target": "rec1", "status": status, "detail": ""},
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )


def write_frontmatter(path: Path, frontmatter: dict[str, object], body: str = "") -> None:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", body])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_agent_results_contract(directory: Path) -> tuple[Path, Path]:
    repository_root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (repository_root / "docs" / "ai-harness" / "agent_result_vault_contract.json").read_text(encoding="utf-8")
    )
    diary_vault = directory / "diary-vault"
    payload["diary_vault"] = str(diary_vault)
    payload["physical_root"] = str(diary_vault / "公共开发集")
    contract_path = directory / "agent-results-contract.json"
    contract_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return contract_path, diary_vault / "公共开发集"


class DeletionMixinTest(unittest.TestCase):
    def test_allowed_roots_use_the_runtime_contract_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"OPENCLAW_MEDIA_VAULT_ROOT": str(Path(tmp) / "media_vault")},
            clear=False,
        ):
            contract_path, results_root = write_agent_results_contract(Path(tmp))
            with patch.dict(os.environ, {"OPENCLAW_AGENT_RESULTS_CONTRACT_PATH": str(contract_path)}, clear=False):
                mixin = DeletionMixin()
                mixin.workspace_root = Path(tmp) / "workspace"
                roots = mixin._deletion_allowed_roots(TENANT_A)

        self.assertTrue(
            all(results_root / folder in roots for folder in ("media", "daily", "social", "knowledge", "public"))
        )

    def test_default_allowed_roots_include_only_authenticated_tenant_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"OPENCLAW_MEDIA_VAULT_ROOT": str(Path(tmp) / "media_vault")},
        ):
            mixin = DeletionMixin()
            mixin.workspace_root = Path(tmp) / "workspace"
            roots = [path.resolve() for path in mixin._deletion_allowed_roots(TENANT_A)]

        tenant_root = (Path(tmp) / "media_vault" / "tenants" / TENANT_A).resolve()
        neighbor_root = (Path(tmp) / "media_vault" / "tenants" / "22222222-2222-4222-8222-222222222222").resolve()
        self.assertIn(tenant_root, roots)
        self.assertNotIn(neighbor_root, roots)
        self.assertNotIn((Path(tmp) / "media_vault").resolve(), roots)

    def test_missing_target_id_returns_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("帮我删一下"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "delete_missing_target_id")
        self.assertIn("20260412-030515-qq-灵感-0056", result.reply)
        self.assertIn("run_router_xxx", result.reply)

    def test_run_delete_is_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
        ) as run:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("run_router_abc123"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deletion_dry_run")
        self.assertNotIn("--apply", run.call_args.args[0])
        self.assertIn("删除预览", result.reply)

    def test_confirmed_run_delete_passes_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout("apply"), stderr=""),
        ) as run:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("确认删除 run_router_abc123"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deletion_applied")
        self.assertIn("--apply", run.call_args.args[0])
        self.assertIn("删除执行结果", result.reply)

    def test_run_preview_lists_postgres_projection_counts(self) -> None:
        connection = FakeRunsConnection({
            "creation_run_sources": 2,
            "creation_run_decisions": 1,
            "creation_run_outputs": 3,
            "creation_runs": 1,
        })
        database = FakeAccountDatabase(connection)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
        ):
            result = DeletionHarness(Path(tmp), account_database=database).handle_删除(
                deletion_message("run_router_abc123")
            )

        self.assertTrue(result.ok)
        self.assertIn("创作运行来源 2 条", result.reply)
        self.assertIn("创作运行决定 1 条", result.reply)
        self.assertIn("创作运行输出 3 条", result.reply)
        self.assertIn("创作运行主记录 1 条", result.reply)
        self.assertFalse(any(query.startswith("DELETE") for query, _ in connection.calls))
        self.assertEqual(connection.commits, 0)

    def test_run_delete_keeps_postgres_when_external_cleanup_fails(self) -> None:
        counts = {table: 1 for table in PROJECTION_TABLES}
        connection = FakeRunsConnection(counts)
        database = FakeAccountDatabase(connection)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            side_effect=[
                CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
                CompletedProcess(args=[], returncode=1, stdout="", stderr="external cleanup failed"),
            ],
        ):
            result = DeletionHarness(Path(tmp), account_database=database).handle_删除(
                deletion_message("确认删除 run_router_abc123")
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "deletion_failed")
        self.assertEqual(connection.counts, counts)
        self.assertFalse(any(query.startswith("DELETE") for query, _ in connection.calls))
        self.assertEqual(connection.commits, 0)

    def test_run_delete_removes_all_postgres_projections_and_commits(self) -> None:
        connection = FakeRunsConnection({
            "creation_run_sources": 2,
            "creation_run_decisions": 1,
            "creation_run_outputs": 1,
            "creation_runs": 1,
        })
        database = FakeAccountDatabase(connection)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            side_effect=[
                CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
                CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout("apply"), stderr=""),
            ],
        ):
            harness = DeletionHarness(Path(tmp), account_database=database)
            result = harness.handle_删除(deletion_message("确认删除 run_router_abc123"))
            owner = harness.tenant_owned_resources.registry.get("media.creation_run", "run_router_abc123")

        self.assertTrue(result.ok)
        self.assertEqual(connection.counts, {table: 0 for table in PROJECTION_TABLES})
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        delete_calls = [(query, params) for query, params in connection.calls if query.startswith("DELETE")]
        self.assertEqual(
            [next(table for table in PROJECTION_TABLES if f"media_product.{table}" in query) for query, _ in delete_calls],
            list(PROJECTION_TABLES),
        )
        self.assertTrue(all(params == (TENANT_A, "run_router_abc123") for _, params in delete_calls))
        self.assertEqual(owner.status, "archived")

    def test_run_delete_rolls_back_when_postgres_readback_has_residual_rows(self) -> None:
        counts = {table: 1 for table in PROJECTION_TABLES}
        connection = FakeRunsConnection(counts, preserve_table="creation_run_outputs")
        database = FakeAccountDatabase(connection)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            side_effect=[
                CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
                CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout("apply"), stderr=""),
            ],
        ):
            harness = DeletionHarness(Path(tmp), account_database=database)
            result = harness.handle_删除(deletion_message("确认删除 run_router_abc123"))
            owner = harness.tenant_owned_resources.registry.get("media.creation_run", "run_router_abc123")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "deletion_failed")
        self.assertIn("删除后仍有 PostgreSQL 残留", result.reply)
        self.assertEqual(connection.counts, counts)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(owner.status, "active")

    def test_run_projection_queries_are_tenant_scoped(self) -> None:
        connection = FakeRunsConnection({"creation_runs": 1})
        database = FakeAccountDatabase(connection)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
        ):
            result = DeletionHarness(
                Path(tmp),
                account_database=database,
                tenant_id=TENANT_B,
            ).handle_删除(deletion_message("run_router_abc123"))

        self.assertTrue(result.ok)
        select_params = [params for query, params in connection.calls if query.startswith("SELECT")]
        self.assertEqual(select_params, [(TENANT_B, "run_router_abc123") * 4])

    def test_retired_apply_alias_does_not_execute_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "openclaw_app.router.deletion_adapters.creation_run_adapter.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=cleanup_stdout(), stderr=""),
        ) as run:
            result = DeletionHarness(Path(tmp)).handle_删除(deletion_message("apply run_router_abc123"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "deletion_dry_run")
        self.assertNotIn("--apply", run.call_args.args[0])

    def test_archive_preview_keeps_files_and_lists_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-灵感-0056"
            inbox = root / "inbox" / "20260412-030515-qq-灵感-1566.json"
            archive = root / "archive" / "inspirations" / f"{target_id}.md"
            note = root / "obsidian" / "note.md"
            media_dir = root / "content_flow" / "asset-dir"
            inbox.parent.mkdir(parents=True)
            inbox.write_text(json.dumps({"tenant_id": TENANT_A}), encoding="utf-8")
            note.parent.mkdir(parents=True)
            note.write_text("note", encoding="utf-8")
            media_dir.mkdir(parents=True)
            (media_dir / "asset.json").write_text("{}", encoding="utf-8")
            write_frontmatter(
                archive,
                {"id": target_id, "entry_tag": "灵感", "tenant_id": TENANT_A, "obsidian_path": note, "media_dir": media_dir},
                "# test",
            )

            result = DeletionHarness(root).handle_删除(deletion_message(target_id))

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "deletion_dry_run")
            self.assertTrue(inbox.exists())
            self.assertTrue(archive.exists())
            self.assertTrue(note.exists())
            self.assertTrue(media_dir.exists())
            self.assertIn("删除预览", result.reply)
            self.assertIn("本地归档", result.reply)
            self.assertIn("Obsidian会议纪要", result.reply)

    def test_archive_confirm_deletes_fixture_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-灵感-0056"
            inbox = root / "inbox" / "20260412-030515-qq-灵感-1566.json"
            archive = root / "archive" / "inspirations" / f"{target_id}.md"
            note = root / "obsidian" / "note.md"
            inbox.parent.mkdir(parents=True)
            inbox.write_text(json.dumps({"tenant_id": TENANT_A}), encoding="utf-8")
            note.parent.mkdir(parents=True)
            note.write_text("note", encoding="utf-8")
            write_frontmatter(archive, {"id": target_id, "entry_tag": "灵感", "tenant_id": TENANT_A, "obsidian_path": note}, "# test")

            result = DeletionHarness(root).handle_删除(deletion_message(f"确认删除 {target_id}"))

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "deletion_applied")
            self.assertFalse(archive.exists())
            self.assertFalse(note.exists())
            self.assertIn("已删除", result.reply)

    def test_transcription_confirm_deletes_intermediate_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-转写-0056"
            archive = root / "archive" / "transcripts" / f"{target_id}.md"
            note = root / "obsidian" / "minutes.md"
            transcript = root / "obsidian" / "raw.md"
            topical = root / "obsidian" / "topical.md"
            text_json = root / "content_flow" / "text_transcripts" / "20260412-030515-qq-转写-abcd" / "task.json"
            post_json = root / "content_flow" / "postprocess" / "post.json"
            for path in (note, transcript, topical, text_json, post_json):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            write_frontmatter(
                archive,
                {
                    "id": target_id,
                    "entry_tag": "转写",
                    "tenant_id": TENANT_A,
                    "obsidian_path": note,
                    "obsidian_transcript_path": transcript,
                    "obsidian_topical_attachments_path": topical,
                    "postprocess_artifacts": [post_json],
                },
                "# transcript",
            )

            preview = DeletionHarness(root).handle_删除(deletion_message(target_id))

            self.assertTrue(preview.ok)
            self.assertTrue(note.exists())
            self.assertTrue(transcript.exists())
            self.assertTrue(topical.exists())
            self.assertTrue(text_json.exists())
            self.assertTrue(post_json.exists())

            applied = DeletionHarness(root).handle_删除(deletion_message(f"确认删除 {target_id}"))

            self.assertTrue(applied.ok)
            self.assertFalse(archive.exists())
            self.assertFalse(note.exists())
            self.assertFalse(transcript.exists())
            self.assertFalse(topical.exists())
            self.assertFalse(text_json.parent.exists())
            self.assertFalse(post_json.exists())
            self.assertIn("中间产物", applied.reply)

    def test_shared_archive_from_another_tenant_is_hidden_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_id = "20260412-030515-qq-灵感-cross-tenant"
            archive = root / "archive" / "inspirations" / f"{target_id}.md"
            write_frontmatter(
                archive,
                {
                    "id": target_id,
                    "entry_tag": "灵感",
                    "tenant_id": "22222222-2222-4222-8222-222222222222",
                    "obsidian_path": root / "other-tenant-secret.md",
                },
                "# other tenant secret",
            )

            preview = DeletionHarness(root).handle_删除(deletion_message(target_id))

            self.assertFalse(preview.ok)
            self.assertEqual(preview.status, "deletion_failed")
            self.assertIn("不属于当前租户", preview.reply)
            self.assertNotIn("other-tenant-secret", preview.reply)
            self.assertTrue(archive.exists())


if __name__ == "__main__":
    unittest.main()
