from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openclaw_app.services.lark_resource_hydration import (
    HydrationTarget,
    LarkResourceHydrationRepository,
    LarkResourceHydrationService,
)
from openclaw_app.services.media_business.overview import (
    OverviewInternalError,
    OverviewService,
)
from openclaw_app.services.media_business.trusted_resources import (
    TrustedOrganizationResourceError,
    trusted_organization_resource,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)
B_SIDE_TRUSTED_RESOURCE_CONSUMERS = (
    ROOT / "openclaw_app/services/media_business/documents.py",
    ROOT / "openclaw_app/services/media_business/overview.py",
    ROOT / "openclaw_app/services/media_business/runs.py",
)


@pytest.mark.parametrize(
    "url",
    [
        "https://feishu.cn/docx/DoxcnTrusted123",
        "https://team.feishu.cn/doc/DoxcnTrusted123",
        "https://team.feishu.cn/docs/DoxcnTrusted123",
        "https://team.feishu.cn/docx/DoxcnTrusted123?view=1",
    ],
)
def test_overview_uses_the_strict_trusted_resource_contract(url: str) -> None:
    with pytest.raises(OverviewInternalError):
        OverviewService._organization_document_url(url, "lark")


def test_overview_does_not_keep_a_second_wider_feishu_url_policy() -> None:
    source = (ROOT / "openclaw_app/services/media_business/overview.py").read_text(encoding="utf-8")
    assert "trusted_organization_resource" in source
    assert "_FEISHU_DOCUMENT_HOST_SUFFIXES" not in source
    assert "_FEISHU_DOCUMENT_ROOT_HOSTS" not in source


def test_b_side_trusted_resource_consumers_use_expiry_and_retired_gate() -> None:
    for path in B_SIDE_TRUSTED_RESOURCE_CONSUMERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "trusted_organization_resource"
        ]
        assert len(calls) == 1, path
        call = calls[0]
        assert any(keyword.arg == "expires_at" for keyword in call.keywords), path
        assert any(keyword.arg == "retired" for keyword in call.keywords), path

def test_trusted_organization_resource_rejects_expired_links() -> None:
    with pytest.raises(TrustedOrganizationResourceError, match="expired"):
        trusted_organization_resource(
            "https://team.feishu.cn/docx/DoxcnTrusted123",
            NOW - timedelta(seconds=1),
            now=NOW,
        )

def test_trusted_organization_resource_rejects_retired_links() -> None:
    with pytest.raises(TrustedOrganizationResourceError, match="retired"):
        trusted_organization_resource(
            "https://team.feishu.cn/docx/DoxcnTrusted123",
            NOW + timedelta(hours=1),
            retired=True,
            now=NOW,
        )
class _FakeFeishu:
    web_base_url = "https://team.feishu.cn"

    def hydrate_docx_child_tree(self, _document_id: str) -> list[dict[str, object]]:
        return [{"block_id": "remote-block", "block_type": 2, "text": "正文"}]


def test_hydration_source_url_uses_the_configured_feishu_web_base() -> None:
    target = HydrationTarget(
        "tenant",
        "artifact_lark_123",
        1,
        "actor",
        {"nodeToken": "nodeToken123", "objToken": "object123", "objType": "docx", "title": "标题"},
    )
    service = LarkResourceHydrationService(
        _FakeFeishu(),
        LarkResourceHydrationRepository(lambda: None),
    )

    payload = service._payload(target)

    assert payload.source_url == "https://team.feishu.cn/wiki/nodeToken123"


@pytest.mark.parametrize(
    "relative_path",
    [
        "openclaw_app/services/lark_resource_hydration.py",
        "scripts/hydrate_lark_resources.py",
        "scripts/sync_lark_resources.py",
    ],
)
def test_lark_resource_paths_do_not_embed_a_tenant_host(relative_path: str) -> None:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "https://tcnwue" not in source
    if relative_path.startswith("scripts/"):
        assert "FEISHU_WEB_BASE_URL" in source
    else:
        assert "web_base_url" in source
