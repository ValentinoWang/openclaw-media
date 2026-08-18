from __future__ import annotations

from pathlib import Path

from common.capability_execution import capability_execution_branch_contracts
from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES


def _capability(label: str):
    return next(item for item in TAG_CAPABILITIES if item.label == label)


def test_audio_transcription_declares_bot_specific_intake_paths() -> None:
    capability = _capability("转写")
    contracts = capability_execution_branch_contracts("转写")

    assert capability.execution_branches == contracts
    assert capability.requires_confirmation is True
    assert len(contracts) == 1
    assert contracts[0].decision_id == "transcription-intake-mode"
    assert {item.outcome_id for item in contracts[0].outcomes} == {
        "transcription-knowledge-auto-enqueue",
        "transcription-knowledge-idempotent-replay",
        "transcription-daily-confirmed-batch",
        "transcription-daily-await-confirmation",
    }
    assert "Knowledge Bot 收到每条裸音频" in capability.result
    assert "无需二次确认" in capability.result
    assert "Daily Bot 继续" in capability.result
    assert "严格 FIFO" in capability.result


def test_transcription_contract_keeps_sensitive_business_details_in_main_note() -> None:
    for label in ("转写", "转写-文字"):
        result = _capability(label).result
        assert "5 细节保全附录（受限）、6 关联文档" in result
        assert "任何有业务含义的敏感细节都不能删除、泛化或省略" in result
        assert "可见范围、核验状态和公开权限" in result


def test_transcription_sources_do_not_restore_retired_sensitive_deletion_directive() -> None:
    retired_directive = "_".join(("do", "not", "include", "in", "final", "note"))
    root = Path(__file__).parents[1]

    for path in (
        root / "openclaw_app/services/content_flow_client.py",
        root / "openclaw_app/router/transcription_formatters.py",
        root / "openclaw_app/router/tag_capabilities.py",
    ):
        assert retired_directive not in path.read_text(encoding="utf-8")
