from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER_ROOT = ROOT / "openclaw-tag-router"
if str(ROUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ROUTER_ROOT))

from openclaw_app.services.media_business.lark_base_projection import (  # noqa: E402
    LarkBaseProjection,
    TABLE_SPECS,
)


def _review_spec():
    return next(spec for spec in TABLE_SPECS if spec.target_table == "review_records")


def test_ct_a9_review_projection_uses_stable_ids_and_drops_document_url() -> None:
    canonical = LarkBaseProjection._canonical_data(
        _review_spec(),
        {"table_id": "tbl_reviews", "name": "可变显示名称"},
        {
            "record_id": "rec_review_001",
            "fields": {
                "发布作品ID": "post_example",
                "复盘文档ID": "UkSMwA36fiZuBdkk63ncnm84n0e",
                "复盘文档链接": "https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e",
            },
        },
    )

    assert canonical["source"] == {
        "provider": "feishu",
        "table_id": "tbl_reviews",
        "record_id": "rec_review_001",
    }
    assert canonical["review_document_id"] == "UkSMwA36fiZuBdkk63ncnm84n0e"
    assert "document_url" not in canonical
    assert "复盘文档链接" not in canonical["fields"]


def test_ct_a9_review_projection_rejects_url_or_name_as_document_identity() -> None:
    canonical = LarkBaseProjection._canonical_data(
        _review_spec(),
        {"table_id": "tbl_reviews", "name": "可变显示名称"},
        {
            "record_id": "rec_review_002",
            "fields": {
                "发布作品ID": "post_example",
                "复盘文档ID": "复盘名称",
                "复盘文档链接": "https://tenant.feishu.cn/docx/UkSMwA36fiZuBdkk63ncnm84n0e",
            },
        },
    )

    assert canonical["review_document_id"] is None
    assert canonical["source"]["table_id"] == "tbl_reviews"
    assert canonical["source"]["record_id"] == "rec_review_002"
    assert "复盘文档链接" not in canonical["fields"]
