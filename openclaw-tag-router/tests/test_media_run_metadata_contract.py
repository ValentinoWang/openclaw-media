from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from openclaw_app.services.media_business.runs import RunsInternalError, _run_summary_from_row


def run_row(metadata: dict[str, object]) -> tuple[object, ...]:
    now = datetime(2026, 8, 7, tzinfo=timezone.utc)
    canonical = {
        "title": "天水麦积山石窟毕业旅行避坑提问",
        "entrypoint": "【创作】",
        "status": "success",
        "availableSections": [],
        "publicProjectId": None,
        **metadata,
    }
    return ("run_20260621_190713_57e1", 2, canonical, now, now)


def test_run_summary_projects_only_structured_metadata() -> None:
    summary = _run_summary_from_row(
        run_row({"platform": "抖音", "contentType": "视频", "trackName": "旅行"})
    )

    assert summary["title"] == "天水麦积山石窟毕业旅行避坑提问"
    assert summary["platform"] == "抖音"
    assert summary["contentType"] == "视频"
    assert summary["trackName"] == "旅行"


def test_run_summary_does_not_parse_legacy_title() -> None:
    row = list(run_row({}))
    row[2]["title"] = "抖音 / 视频 / 旅行 / 旧格式标题"

    summary = _run_summary_from_row(tuple(row))

    assert summary["title"] == "抖音 / 视频 / 旅行 / 旧格式标题"
    assert summary["platform"] is None
    assert summary["contentType"] is None
    assert summary["trackName"] is None


@pytest.mark.parametrize("metadata", [{"platform": 1}, {"contentType": False}, {"trackName": ""}])
def test_run_summary_rejects_invalid_metadata(metadata: dict[str, object]) -> None:
    with pytest.raises(RunsInternalError):
        _run_summary_from_row(run_row(metadata))


def test_openapi_requires_nullable_structured_metadata() -> None:
    contract_path = (
        Path(__file__).parents[1]
        / "openclaw_app"
        / "contracts"
        / "media_web_business_pages.openapi.yaml"
    )
    schema = yaml.safe_load(contract_path.read_text(encoding="utf-8"))["components"]["schemas"]["RunSummary"]

    for field in ("platform", "contentType", "trackName"):
        assert schema["properties"][field]["type"] == ["string", "null"]
        assert field in schema["required"]
