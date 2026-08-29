from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from media_vault.vault import MediaVault
from selfmedia.growth.service import capture_review_signal


TENANT_ID = "00000000-0000-4000-8000-000000000101"


def test_capture_review_signal_loads_owned_post_metrics() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": directory}, clear=False
    ):
        vault = MediaVault(tenant_id=TENANT_ID)
        vault.write_post_review(
            "post_123",
            "2h",
            metrics={"metrics": {"完播率": "31%", "播放": 1200}},
            review_markdown="复盘",
        )
        signal = capture_review_signal(
            "作品ID=post_123 单一事实=中段流失",
            account_id="训练小王",
            vault=vault,
        )

    assert signal.metrics_summary["完播率"] == "31%"
    assert signal.metrics_summary["播放"] == "1200"
    assert any(
        item.get("artifact_type") == "PublishedPostReviewEvidence"
        for trace in signal.source_trace
        for item in trace.get("artifacts", [])
    )
