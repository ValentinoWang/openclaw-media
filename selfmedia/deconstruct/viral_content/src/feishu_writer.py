from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

SELFMEDIA_ROOT = Path(__file__).resolve().parents[3]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import load_default_env_files, load_env_file
from integrations.feishu.media_writer import upsert_entity_record
from media_model.payloads import make_asset_id, normalize_source_url
from media_model.payloads import build_material_deconstruction_payload, build_source_asset_payload
from media_vault.vault import MediaVault

from .artifact_v2 import build_deconstruction_artifact


FEISHU_BASE = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")
MAX_BITABLE_SUMMARY_CHARS = 500
PROMPT_BUNDLE_VERSION = "viral_deconstruct_v2"
SKILL_VERSION = "selfmedia.deconstruct.viral_content:v2"


@dataclass(frozen=True)
class AttachmentItem:
    path: str
    kind: str


def tenant_access_token() -> str:
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
    resp = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败：{payload}")
    return payload["tenant_access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}


def resolve_wiki_bitable(wiki_token: str, token: str) -> str:
    resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": wiki_token}, headers=_headers(token), timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"解析飞书 wiki 节点失败：{payload}")
    node = payload.get("data", {}).get("node", {})
    if node.get("obj_type") != "bitable":
        raise RuntimeError(f"wiki 节点不是多维表格：{node.get('obj_type')}")
    return node["obj_token"]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _summary_text(value: Any, limit: int = MAX_BITABLE_SUMMARY_CHARS) -> str:
    text = _normalize_text(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def build_attachment_plan(result: dict[str, Any]) -> list[AttachmentItem]:
    plan: list[AttachmentItem] = []
    for key, kind in (
        ("cover_path", "cover"),
        ("source_preview_path", "preview"),
        ("source_video_path", "original_video"),
        ("source_audio_path", "original_audio"),
        ("interaction_screenshot_path", "interaction_screenshot"),
    ):
        value = result.get(key)
        if isinstance(value, str) and value:
            plan.append(AttachmentItem(value, kind))
    image_paths = result.get("source_image_paths")
    if isinstance(image_paths, list):
        for image_path in image_paths:
            if image_path:
                plan.append(AttachmentItem(str(image_path), "original_image"))
    for item in plan:
        path = Path(item.path)
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"证据文件不存在或为空: {item.path}")
    return plan


def write_deconstruction(result: dict[str, Any], source_text: str) -> str:
    load_default_env_files()
    load_env_file(Path("/home/ubuntu/openclaw-agents/media/.env.local"))
    source_assets_url = os.getenv("MEDIA_OS_SOURCE_ASSETS_URL", "").strip()
    material_deconstructions_url = os.getenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", "").strip()
    if not source_assets_url or not material_deconstructions_url:
        raise RuntimeError("缺少 MEDIA_OS_SOURCE_ASSETS_URL / MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL")

    source_url = normalize_source_url(result.get("source_url") or "")
    platform = str(result.get("platform") or _platform_from_url(source_url) or "未抓取").strip()
    title = _summary_text(result.get("source_title") or result.get("source_caption") or result.get("content_summary") or source_url or "未抓取")
    body = _normalize_text(result.get("source_caption") or source_text)
    asset_id = make_asset_id(platform, source_url)
    deconstruction_id = _deconstruction_id(asset_id, result)

    vault = MediaVault()
    vault.ensure_manifest()
    attachment_plan = build_attachment_plan(result)
    evidence_store = result.get("evidence_store") if isinstance(result.get("evidence_store"), dict) else {}
    source_evidence = {
        "schema_version": "source_evidence_from_evidence_store_v1",
        "evidence_store": evidence_store,
        "source_url": source_url,
        "attachments": [{"path": item.path, "kind": item.kind} for item in attachment_plan],
        "stats": result.get("stats") or {},
        "evidence_assets": result.get("evidence_assets") or [],
        "deconstruct_doc_url": result.get("deconstruct_doc_url", ""),
        "recreate_doc_url": result.get("recreate_doc_url", ""),
    }
    if not evidence_store:
        raise RuntimeError("缺少 evidence_store，禁止写入半成品 source artifact")
    source_bundle = vault.write_source_asset_bundle(
        platform=platform,
        asset_id=asset_id,
        manifest={
            "asset_id": asset_id,
            "platform": platform,
            "source_url": source_url,
            "title": title,
            "captured_at": int(time.time() * 1000),
            "deconstruct_doc_url": result.get("deconstruct_doc_url", ""),
        },
        original_text=body,
        extracted_text=_summary_text(result.get("source_summary") or result.get("content_summary")),
        evidence=source_evidence,
    )
    asset_evidence_uri = source_bundle.get("evidence", source_bundle["manifest"])["uri"]
    asset_payload = build_source_asset_payload(
        platform=platform,
        title=title,
        source_url=source_url,
        evidence_uri=asset_evidence_uri,
        asset_id=asset_id,
        original_title=title,
        author_id=str((result.get("stats") or {}).get("author_id") or result.get("author_id") or ""),
        account_name_snapshot=str(result.get("account_name") or result.get("author_name") or ""),
        source_doc_link=str(result.get("source_doc_url") or result.get("deconstruct_doc_url") or result.get("feishu_doc_url") or ""),
        body=body,
        status="已解析",
        enabled=True,
    )
    upsert_entity_record("SourceAsset", source_assets_url, asset_payload, key_field="asset_id")

    deconstruction_payload_artifact = build_deconstruction_artifact(
        result=result,
        deconstruction_id=deconstruction_id,
        source_asset_id=asset_id,
        source_asset_evidence_uri=asset_evidence_uri,
        source_text=source_text,
    )
    deconstruction_artifact = vault.write_json_artifact(
        vault.deconstruction_dir(deconstruction_id),
        "deconstruction.json",
        deconstruction_payload_artifact,
        owner_type="MaterialDeconstruction",
        owner_id=deconstruction_id,
        artifact_type="material_deconstruction",
    )
    deconstruction_payload = build_material_deconstruction_payload(
        deconstruction_id=deconstruction_id,
        asset_id=asset_id,
        summary=_summary_text(result.get("content_summary") or result.get("source_summary") or result.get("viral_mechanism") or title),
        hook=_summary_text(result.get("hook_elements") or result.get("viral_mechanism")),
        transferable_points=_summary_text(result.get("production_checklist") or result.get("viral_mechanism")),
        non_transferable_points=_summary_text(result.get("avoid_copying") or result.get("uncertainty_notes") or ""),
        **_shot_adaptation_bitable_index(result),
        cover_opening_hook=_summary_text(result.get("cover_opening_hook") or ""),
        core_data_summary=_summary_text(result.get("core_data_summary") or ""),
        top_comment_insight=_summary_text(result.get("top_comment_insight") or ""),
        target_audience_summary=_summary_text(result.get("target_audience_summary") or result.get("target_audience") or ""),
        pain_pleasure_summary=_summary_text(result.get("pain_pleasure_summary") or result.get("pain_or_pleasure_points") or ""),
        attention_elements=_summary_text(result.get("attention_elements") or ""),
        viral_breakdown=_summary_text(result.get("viral_breakdown") or result.get("viral_mechanism") or ""),
        viral_migration=_summary_text(result.get("viral_migration") or result.get("production_checklist") or ""),
        creative_upgrade_suggestion=_summary_text(result.get("creative_upgrade_suggestion") or ""),
        prompt_bundle_version=PROMPT_BUNDLE_VERSION,
        model=str(result.get("model") or os.getenv("OPENAI_MODEL") or "media_creation"),
        skill_version=SKILL_VERSION,
        confidence=_confidence(result),
        evidence_uri=deconstruction_artifact["uri"],
        deconstruction_doc_link=str(result.get("deconstruct_doc_url") or result.get("feishu_doc_url") or ""),
        review_status="未复核",
    )
    record = upsert_entity_record(
        "MaterialDeconstruction",
        material_deconstructions_url,
        deconstruction_payload,
        key_field="deconstruction_id",
    )
    return str(record.get("record_id") or deconstruction_id)


def _platform_from_url(url: str) -> str:
    lowered = url.lower()
    if "douyin" in lowered:
        return "抖音"
    if "xiaohongshu" in lowered or "xhs" in lowered:
        return "小红书"
    return ""


def _deconstruction_id(asset_id: str, result: dict[str, Any]) -> str:
    source = "|".join(
        [
            asset_id,
            PROMPT_BUNDLE_VERSION,
            str(result.get("model") or os.getenv("OPENAI_MODEL") or "media_creation"),
            SKILL_VERSION,
            "default",
        ]
    )
    return "decon_" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def _shot_adaptation_bitable_index(result: dict[str, Any]) -> dict[str, Any]:
    contract = result.get("multi_signal_contract") if isinstance(result.get("multi_signal_contract"), dict) else {}
    notes = [item for item in contract.get("shot_adaptation_notes") or [] if isinstance(item, dict)]
    validation = contract.get("validation") if isinstance(contract.get("validation"), dict) else {}
    status = str(validation.get("multi_signal_contract_status") or "").strip()
    return {
        "shot_adaptation_notes_status": status,
        "shot_adaptation_note_count": len(notes) if notes else None,
        "recommended_production_route": "",
        "motion_type_summary": "",
        "shot_adaptation_notes_summary": _shot_adaptation_notes_summary(notes),
    }


def _shot_adaptation_notes_summary(notes: list[dict[str, Any]], *, limit: int = 500) -> str:
    lines: list[str] = []
    for item in notes[:8]:
        note_id = str(item.get("note_id") or "").strip()
        pattern = str(item.get("learnable_pattern") or "").strip()
        rule = str(item.get("adaptation_rule") or "").strip()
        avoid = _normalize_text(item.get("do_not_copy")).replace("\n", " ")
        line = " | ".join(part for part in (note_id, pattern, rule, avoid) if part)
        if line:
            lines.append(line)
    if len(notes) > 8:
        lines.append(f"...共 {len(notes)} 条，完整结构见 multi_signal_contract")
    return _summary_text(lines, limit)


def _confidence(result: dict[str, Any]) -> float:
    value = result.get("confidence")
    if value in (None, "", []):
        return 0.72
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.72
    if number > 1:
        number = number / 100
    return min(1.0, max(0.0, number))
