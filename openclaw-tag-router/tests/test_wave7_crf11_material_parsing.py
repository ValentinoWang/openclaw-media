from __future__ import annotations

import base64
from pathlib import Path

import pytest

from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY
from openclaw_app.services.media_web_tasks import MediaWebTaskError, MediaWebTaskService


TENANT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class FakeApp:
    def process_capability_invocation(self, **_kwargs):
        raise AssertionError("material parsing validation must run before task execution")


def source_asset_request(
    params: dict[str, str],
    *,
    upload_ids: list[str] | None = None,
    idempotency_key: str = "wave7_crf11_material_parse_0001",
) -> dict[str, object]:
    return {
        "schemaVersion": "3",
        "capabilityId": "source_asset_intake",
        "variantId": "default",
        "params": params,
        "uploadIds": upload_ids or [],
        "idempotencyKey": idempotency_key,
        "catalogVersion": CAPABILITY_REGISTRY.catalog_version,
        "initiation": "manual",
        "confirmationReceipt": None,
    }


def test_source_asset_parser_returns_structured_incomplete_error(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        with pytest.raises(MediaWebTaskError) as raised:
            service.create_task(
                source_asset_request(
                    {
                        "field_3be96f8eb83d": "图片",
                        "platform": "抖音",
                    }
                ),
                tenant_id=TENANT_ID,
            )

        assert raised.value.code == "material_parsing_incomplete"
        assert raised.value.status == 422
        assert raised.value.details == {
            "failure": "material_source_missing",
            "failurePrompt": "当前不支持自动解析抖音图片素材。",
            "missingFields": ["uploadIds", "remark"],
            "nextAction": "请先提供原始素材并填写人工补充后重新校验。",
        }
    finally:
        service.close()


def test_source_asset_parser_checks_url_syntax_and_allows_typed_text(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        with pytest.raises(MediaWebTaskError) as raised:
            service.create_task(
                source_asset_request(
                    {
                        "field_3be96f8eb83d": "链接",
                        "platform": "抖音",
                        "field_c675ffae69a2": "not-a-url",
                    },
                    idempotency_key="wave7_crf11_invalid_url_0001",
                ),
                tenant_id=TENANT_ID,
            )
        assert raised.value.code == "material_parsing_incomplete"
        assert raised.value.details["failure"] == "douyin_url_parse_failed"
        assert raised.value.details["missingFields"] == ["sourceUrl"]

        task, created = service.create_task(
            source_asset_request(
                {
                    "field_3be96f8eb83d": "文本",
                    "platform": "抖音",
                    "field_c675ffae69a2": "可解析的原始文本",
                },
                idempotency_key="wave7_crf11_valid_text_0001",
            ),
            tenant_id=TENANT_ID,
        )
        assert created is True
        assert task["status"] == "awaiting_confirmation"
    finally:
        service.close()


def test_repository_backed_source_asset_parser_rejects_incomplete_material(tmp_path: Path) -> None:
    service = MediaWebTaskService(
        FakeApp(),
        root=tmp_path,
        repository=object(),
        start_worker=False,
    )
    try:
        with pytest.raises(MediaWebTaskError) as raised:
            service.create_task(
                source_asset_request(
                    {
                        "field_3be96f8eb83d": "视频",
                        "platform": "抖音",
                    },
                    idempotency_key="wave7_crf11_repository_0001",
                ),
                tenant_id=TENANT_ID,
            )

        assert raised.value.code == "material_parsing_incomplete"
        assert raised.value.details["failure"] == "material_source_missing"
        assert raised.value.details["missingFields"] == ["uploadIds", "remark"]
    finally:
        service.close()


def test_upload_projection_exposes_verified_parsing_facts(tmp_path: Path) -> None:
    service = MediaWebTaskService(FakeApp(), root=tmp_path, start_worker=False)
    try:
        text_upload, text_created = service.create_upload(
            {
                "filename": "source.txt",
                "mimeType": "text/plain",
                "contentBase64": base64.b64encode("可验证的文本素材".encode()).decode(),
            },
            tenant_id=TENANT_ID,
        )
        image_upload, image_created = service.create_upload(
            {
                "filename": "source.png",
                "mimeType": "image/png",
                "contentBase64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
            },
            tenant_id=TENANT_ID,
        )

        assert text_created is True
        assert image_created is True
        assert text_upload["parsing"] == {
            "status": "completed_auto",
            "failureCode": "",
            "nextAction": "文本素材已完成自动解析校验。",
        }
        assert image_upload["parsing"] == {
            "status": "pending_manual",
            "failureCode": "material_context_required",
            "nextAction": "请在素材入池时选择平台、素材类型并填写补充说明后重新校验。",
        }
    finally:
        service.close()
