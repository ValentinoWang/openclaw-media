"""Guard that the D2 document projection is source-owned, not release-only."""

from __future__ import annotations

from pathlib import Path

from integrations.feishu.lark_document_gateway import ProductionLarkDocumentGateway
from openclaw_app.services.media_business.documents import DocumentsService


def test_source_has_the_full_document_projection_contract() -> None:
    required_service_methods = {
        "get_document_body",
        "save_document_draft",
        "get_document_revision",
        "create_document_export",
        "get_document_export",
        "get_document_export_download",
    }
    required_gateway_methods = {"read_revision", "save_draft", "reconcile_save"}

    assert required_service_methods <= set(vars(DocumentsService))
    assert required_gateway_methods <= set(vars(ProductionLarkDocumentGateway))


def test_source_gateway_proves_fixed_version_writes() -> None:
    source = ProductionLarkDocumentGateway._prove_write.__code__.co_names

    assert "_read_exact" in source


def test_source_startup_and_migration_keep_document_projection_owned() -> None:
    root = Path(__file__).resolve().parents[1]
    startup = (root / "openclaw_app/server_cli.py").read_text(encoding="utf-8")
    http_adapter = (root / "openclaw_app/adapters/http_api.py").read_text(encoding="utf-8")
    migration = (root / "openclaw_app/migrations/027_media_document_runtime.sql").read_text(
        encoding="utf-8"
    )

    assert "build_production_lark_document_gateway" in startup
    assert "DocumentsService(account_database.connect, lark_gateway=lark_gateway)" in startup
    assert "getDocumentBody" in http_adapter
    assert "saveDocumentDraft" in http_adapter
    assert "sync_batches_save_idempotency_uq" in migration
