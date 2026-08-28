from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from media_model.payloads import build_metric_snapshot_payload
from media_vault.vault import MediaVault, MediaVaultUriError
from selfmedia.review.data_review import (
    DataReviewRequest,
    _metric_snapshot_payloads,
    format_data_review_reply,
    review_metric_data_quality,
    validate_data_review_analysis,
    write_data_review_model_v2,
)


TENANT_ID = "00000000-0000-4000-8000-000000000601"
OTHER_TENANT_ID = "00000000-0000-4000-8000-000000000602"


def _analysis(*, quality_note: str = "截图可读") -> dict[str, object]:
    return {
        "platform": "小红书",
        "account": "跑步账号",
        "media_format": "image_text",
        "media_format_evidence": "截图显示图文笔记数据面板",
        "metrics": {"收藏": "12"},
        "format_specific_metrics": {},
        "trend_curves": {},
        "atomic_facts": [{"fact": "收藏为12", "evidence": "截图可见收藏12"}],
        "priority_metrics": [
            {
                "metric": "收藏",
                "value": "12",
                "evidence": "截图可见收藏12",
                "why_it_matters": "收藏反映内容的后续复用价值",
                "content_action": "保留训练清单结构",
            }
        ],
        "conclusion": "训练清单结构值得继续验证。",
        "performance_level": "高价值延续",
        "content_guidance": ["保留训练清单结构"],
        "publishing_guidance": ["在同一时段继续观察"],
        "metric_interpretation": ["收藏表现稳定"],
        "key_insights": ["用户会保存可执行的训练清单"],
        "problems": ["尚缺更多时间窗口证据"],
        "next_actions": ["24小时后复盘收藏"],
        "data_quality_notes": [quality_note],
    }


def _plan_comparison(*, validation_target: str = "") -> dict[str, str]:
    item = {
        "plan_item": "两小时后对照收藏",
        "status": "已兑现",
        "evidence": "截图可见收藏12",
        "next_step": "24小时后继续对照收藏",
    }
    if validation_target:
        item["validation_target"] = validation_target
    return item


def test_active_window_validation_targets_require_evidence_and_exact_coverage() -> None:
    context = {
        "creation_plan_loaded": True,
        "validation_targets": {"2h": ["收藏"]},
        "review_window": "two_hour",
    }
    missing_target = _analysis()
    missing_target["plan_comparison"] = [_plan_comparison()]
    with pytest.raises(ValueError, match="缺少本次验证指标对照: 2h:收藏"):
        validate_data_review_analysis(missing_target, context)

    missing_evidence = _analysis()
    target_without_evidence = _plan_comparison(validation_target="2h:收藏")
    target_without_evidence.pop("evidence")
    missing_evidence["plan_comparison"] = [target_without_evidence]
    with pytest.raises(ValueError, match="必须包含 evidence"):
        validate_data_review_analysis(missing_evidence, context)

    covered = _analysis()
    covered["plan_comparison"] = [_plan_comparison(validation_target="2h:收藏")]
    validated = validate_data_review_analysis(covered, context)
    assert validated["plan_comparison"][0]["validation_target"] == "2h:收藏"
    assert validated["metric_data_quality"] == "screenshot_only"

    invalid_quality = _analysis()
    invalid_quality["plan_comparison"] = [_plan_comparison(validation_target="2h:收藏")]
    invalid_quality["metric_data_quality"] = "unknown"
    with pytest.raises(ValueError, match="metric_data_quality 必须为"):
        validate_data_review_analysis(invalid_quality, context)


def test_metric_data_quality_is_canonical_persisted_value_with_chinese_reply_label() -> None:
    partial_analysis = _analysis(quality_note="截图部分看不清，数据不完整")
    partial_analysis["metric_data_quality"] = "数据不完整"
    assert review_metric_data_quality(partial_analysis) == "partial"

    snapshot = build_metric_snapshot_payload(
        snapshot_id="post_run_p6_2h_saves_1",
        post_id="post_run_p6",
        review_node="2h",
        metric_key="saves",
        raw_metric_name="收藏",
        metric_value=12,
        unit="count",
        evidence_uri="media://tenants/00000000-0000-4000-8000-000000000601/published_posts/post_run_p6/review/2h/metrics.json",
        data_quality="数据不完整",
    )
    assert snapshot["data_quality"] == "partial"
    assert "数据来源：数据不完整" in format_data_review_reply(
        {
            "ok": True,
            "analysis": {**partial_analysis, "performance_level": "建议重剪"},
            "media_model_v2": {"metric_snapshot_data_quality_label": "数据不完整"},
        }
    )
    assert "表现评级：值得重剪" in format_data_review_reply(
        {"ok": True, "analysis": {"performance_level": "建议重剪"}}
    )


def test_metric_snapshots_are_idempotent_for_same_post_and_review_node() -> None:
    analysis = _analysis()
    first = _metric_snapshot_payloads(
        "post_run_p6",
        "2h",
        analysis,
        "media://tenants/00000000-0000-4000-8000-000000000601/published_posts/post_run_p6/review/2h/metrics.json",
    )
    second = _metric_snapshot_payloads(
        "post_run_p6",
        "2h",
        analysis,
        "media://tenants/00000000-0000-4000-8000-000000000601/published_posts/post_run_p6/review/2h/metrics.json",
    )
    assert first == second
    assert first[0]["snapshot_id"] == "post_run_p6_2h_saves_1"
    assert first[0]["data_quality"] == "screenshot_only"


def test_review_write_records_tenant_creation_run_quality_and_readback(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def record(entity_name: str, _url: str, payload: dict[str, object], **kwargs: object) -> dict[str, str]:
        captured.append({"entity": entity_name, "payload": payload, **kwargs})
        return {"record_id": f"rec_{entity_name}"}

    request = DataReviewRequest(
        platform="小红书",
        account="跑步账号",
        creation_record_id="run_p6",
        data_window="2h",
    )
    env = {
        "OPENCLAW_MEDIA_VAULT_ROOT": str(tmp_path),
        "MEDIA_OS_POST_REVIEWS_URL": "https://example.invalid/post-reviews",
        "MEDIA_OS_METRIC_SNAPSHOT_URL": "https://example.invalid/metric-snapshots",
    }
    vault = MediaVault(tenant_id=TENANT_ID, root=tmp_path)
    vault.write_creation_run_artifacts(
        "run_p6",
        request={"tenant_id": TENANT_ID},
        draft_output={"title": "训练清单", "validation_targets": {"2h": ["收藏"]}},
    )
    with patch.dict(os.environ, env, clear=False), patch(
        "selfmedia.review.data_review.upsert_entity_record", side_effect=record
    ):
        result = write_data_review_model_v2(
            tenant_id=TENANT_ID,
            request=request,
            analysis=_analysis(),
            screenshots=["review.png"],
            reviewed_at="2026-08-29T12:00:00+08:00",
            doc_link="https://example.invalid/review-doc",
            source_record_id="run_p6",
        )

    assert result["post_id"] == "post_run_p6"
    assert result["metric_snapshot_data_quality"] == "screenshot_only"
    assert result["metric_snapshot_data_quality_label"] == "仅截图来源"
    assert [item["entity"] for item in captured] == ["PublishedPost", "MetricSnapshot"]
    assert captured[0]["session_tenant_id"] == TENANT_ID
    assert captured[0]["payload"]["creation_run_id"] == "run_p6"
    assert captured[0]["payload"]["performance_rating"] == "高价值延续"
    assert captured[1]["session_tenant_id"] == TENANT_ID
    assert captured[1]["payload"]["data_quality"] == "screenshot_only"
    artifact_payload = vault.read_json_artifact(result["review_artifact_uri"])
    assert artifact_payload["metrics"] == {"收藏": "12"}
    assert artifact_payload["metric_data_quality"] == "screenshot_only"


def test_tenant_vault_rejects_cross_tenant_artifact_readback(tmp_path: Path) -> None:
    own_vault = MediaVault(tenant_id=TENANT_ID, root=tmp_path)
    other_vault = MediaVault(tenant_id=OTHER_TENANT_ID, root=tmp_path)
    artifact = own_vault.write_json_artifact(
        own_vault.creation_run_dir("run_p6"),
        "draft_output.json",
        {"project_id": "run_p6"},
        owner_type="CreationRun",
        owner_id="run_p6",
        artifact_type="draft_output",
    )
    assert own_vault.read_json_artifact(artifact["uri"]) == {"project_id": "run_p6"}
    with pytest.raises(MediaVaultUriError, match="does not belong to the authenticated tenant"):
        other_vault.resolve_uri(artifact["uri"], require_exists=True)


def test_feishu_write_error_propagates_without_success_result(tmp_path: Path) -> None:
    request = DataReviewRequest(platform="小红书", account="跑步账号", data_window="2h")
    env = {
        "OPENCLAW_MEDIA_VAULT_ROOT": str(tmp_path),
        "MEDIA_OS_POST_REVIEWS_URL": "https://example.invalid/post-reviews",
        "MEDIA_OS_METRIC_SNAPSHOT_URL": "https://example.invalid/metric-snapshots",
    }
    with patch.dict(os.environ, env, clear=False), patch(
        "selfmedia.review.data_review.upsert_entity_record",
        side_effect=RuntimeError("feishu unavailable"),
    ):
        with pytest.raises(RuntimeError, match="feishu unavailable"):
            write_data_review_model_v2(
                tenant_id=TENANT_ID,
                request=request,
                analysis=_analysis(),
                screenshots=[],
                reviewed_at="2026-08-29T12:00:00+08:00",
                doc_link="https://example.invalid/review-doc",
                source_record_id="",
            )
