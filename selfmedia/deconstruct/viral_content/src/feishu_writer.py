from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

SELFMEDIA_ROOT = Path(__file__).resolve().parents[3]
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.social_runtime import load_default_env_files, load_env_file
from integrations.feishu.media_writer import SOURCE_ASSET_ATTACHMENT_MAX_BYTES, upsert_entity_record
from media_model.contract import MediaModelContract
from media_model.payloads import make_asset_id, normalize_source_url
from media_model.payloads import build_material_deconstruction_payload, build_source_asset_payload
from media_vault.vault import MediaVault

from .artifact_v2 import build_deconstruction_artifact


FEISHU_BASE = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")
MAX_BITABLE_SUMMARY_CHARS = 500
PROMPT_BUNDLE_VERSION = "viral_deconstruct_v2"
SKILL_VERSION = "selfmedia.deconstruct.viral_content:v2"
SOURCE_ASSET_ID_RE = re.compile(r"\bsource_asset[_-][A-Za-z0-9_.:-]+\b")


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


def source_asset_attachment_inputs(
    plan: list[AttachmentItem],
) -> tuple[dict[str, str], dict[str, str]]:
    selected: dict[str, str] = {}
    status = {
        "cover_attachment": "source_missing",
        "video_attachment": "source_missing",
    }
    field_kinds = {
        "cover_attachment": ("cover", "preview", "original_image"),
        "video_attachment": ("original_video",),
    }
    for field_name, accepted_kinds in field_kinds.items():
        candidate = next((item for kind in accepted_kinds for item in plan if item.kind == kind), None)
        if candidate is None:
            continue
        path = Path(candidate.path)
        if path.stat().st_size > SOURCE_ASSET_ATTACHMENT_MAX_BYTES:
            status[field_name] = "deferred_oversize"
            continue
        selected[field_name] = str(path)
        status[field_name] = "planned"
    return selected, status


def _attachment_backwash_pending(status: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        field_name: {"status": "pending" if value == "planned" else value}
        for field_name, value in status.items()
    }


def _attachment_backwash_failed(status: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        field_name: {"status": "failed" if value == "planned" else value}
        for field_name, value in status.items()
    }


def _attachment_backwash_completed(
    status: dict[str, str],
    write_receipt: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    fields = write_receipt.get("fields")
    if not isinstance(fields, dict):
        raise RuntimeError("SourceAsset 写入回执缺少附件字段")
    contract = MediaModelContract()
    backwash: dict[str, dict[str, Any]] = {}
    for field_name, value in status.items():
        if value != "planned":
            backwash[field_name] = {"status": value}
            continue
        display_name = contract.feishu_field_name("SourceAsset", field_name)
        attachments = fields.get(display_name)
        if not isinstance(attachments, list):
            raise RuntimeError(f"SourceAsset 写入回执缺少 {field_name} token")
        file_tokens = sorted(
            {
                str(item.get("file_token") or item.get("fileToken") or "").strip()
                for item in attachments
                if isinstance(item, dict)
                and str(item.get("file_token") or item.get("fileToken") or "").strip()
            }
        )
        if not file_tokens:
            raise RuntimeError(f"SourceAsset 写入回执缺少 {field_name} token")
        backwash[field_name] = {"status": "completed", "file_tokens": file_tokens}
    return backwash


def _artifact_uri(bundle: dict[str, Any], key: str) -> str:
    artifact = bundle.get(key)
    uri = artifact.get("uri") if isinstance(artifact, dict) else ""
    if not isinstance(uri, str) or not uri.startswith("media://"):
        raise RuntimeError(f"source bundle 缺少有效 {key} URI")
    return uri


def _feishu_readback_receipt(entity_name: str, receipt: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, dict) or not str(receipt.get("record_id") or "").strip():
        raise RuntimeError(f"{entity_name} 写入回执缺少 record_id")
    if not isinstance(receipt.get("fields"), dict):
        raise RuntimeError(f"{entity_name} 写入回执缺少 fields")
    return receipt


def _projection_attachments(attachment_plan: list[AttachmentItem]) -> tuple[Any, ...]:
    from openclaw_app.services.media_business.source_asset_projection import SourceAttachment

    attachments = []
    for item in attachment_plan:
        path = Path(item.path)
        attachments.append(
            SourceAttachment(
                attachment_id=f"{item.kind}:{path.name}",
                name=path.name,
                media_type=mimetypes.guess_type(path.name)[0],
            )
        )
    return tuple(attachments)


def _project_canonical_source_asset(
    *,
    tenant_id: str,
    asset_payload: dict[str, Any],
    source_bundle: dict[str, Any],
    attachment_plan: list[AttachmentItem],
    source_asset_record: dict[str, Any],
    deconstruction_record: dict[str, Any],
    result: dict[str, Any],
    captured_at: int,
) -> Any:
    """Project only after the vault and both Feishu readbacks are proven."""
    from openclaw_app.account.database import AccountDatabase, AccountDatabaseSettings
    from openclaw_app.services.media_business.source_asset_projection import (
        AuthenticatedTenantContext,
        SourceAssetInput,
        SourceAssetProjection,
    )

    manifest_uri = _artifact_uri(source_bundle, "manifest")
    evidence_uri = _artifact_uri(source_bundle, "evidence")
    source_receipt = _feishu_readback_receipt("SourceAsset", source_asset_record)
    deconstruction_receipt = _feishu_readback_receipt(
        "MaterialDeconstruction", deconstruction_record
    )
    source_identity = str(asset_payload.get("source_url") or asset_payload.get("asset_id") or "").strip()
    if not source_identity:
        raise RuntimeError("SourceAsset 投影缺少 source identity")
    media_type = str(
        result.get("media_type")
        or result.get("detected_media_type")
        or ("video" if any(item.kind == "original_video" for item in attachment_plan) else "image")
    ).strip()
    canonical_data = dict(asset_payload)
    canonical_data["artifacts"] = {
        "manifest_uri": manifest_uri,
        "evidence_uri": evidence_uri,
    }
    canonical_data["feishu_readbacks"] = {
        "source_asset_record_id": str(source_receipt["record_id"]),
        "material_deconstruction_record_id": str(deconstruction_receipt["record_id"]),
    }
    source = SourceAssetInput(
        source_identity=source_identity,
        title=str(asset_payload.get("title") or ""),
        media_type=media_type or "unknown",
        platform=str(asset_payload.get("platform") or "") or None,
        source_url=str(asset_payload.get("source_url") or "") or None,
        captured_at=captured_at,
        original_title=str(asset_payload.get("original_title") or asset_payload.get("title") or ""),
        source_kind="feishu_deconstruction",
        account_ref=str(asset_payload.get("account_name_snapshot") or "") or None,
        request_constraints=(
            result.get("request_constraints")
            if isinstance(result.get("request_constraints"), dict)
            else {}
        ),
        canonical_data=canonical_data,
        attachments=_projection_attachments(attachment_plan),
        evidence=(
            {"kind": "source_asset_manifest", "quality_status": "verified", "uri": manifest_uri},
            {"kind": "source_evidence", "quality_status": "verified", "uri": evidence_uri},
        ),
    )
    settings = AccountDatabaseSettings.from_environment()
    projector = SourceAssetProjection(lambda: AccountDatabase(settings).connect())
    return projector.project(AuthenticatedTenantContext(tenant_id=tenant_id), source)


def write_deconstruction(
    result: dict[str, Any],
    source_text: str,
    *,
    tenant_id: str,
) -> str:
    load_default_env_files()
    media_agent_root = Path(
        os.getenv("OPENCLAW_MEDIA_AGENT_ROOT")
        or Path.home() / ".openclaw" / "agents" / "media"
    ).expanduser()
    load_env_file(media_agent_root / ".env.local")
    source_assets_url = os.getenv("MEDIA_OS_SOURCE_ASSETS_URL", "").strip()
    material_deconstructions_url = os.getenv("MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL", "").strip()
    if not source_assets_url or not material_deconstructions_url:
        raise RuntimeError("缺少 MEDIA_OS_SOURCE_ASSETS_URL / MEDIA_OS_MATERIAL_DECONSTRUCTIONS_URL")

    source_url = normalize_source_url(result.get("source_url") or "")
    platform = str(result.get("platform") or _platform_from_url(source_url) or "未抓取").strip()
    title = _summary_text(result.get("source_title") or result.get("source_caption") or result.get("content_summary") or source_url or "未抓取")
    body = _normalize_text(result.get("source_caption") or source_text)
    source_asset_id = _source_asset_id_from_result(result, source_text)
    from openclaw_app.services.media_business.source_asset_projection import (
        normalize_source_identity,
        stable_public_id,
    )

    source_identity = source_url or source_asset_id or source_text
    asset_id = stable_public_id(tenant_id, normalize_source_identity(source_identity))
    deconstruction_id = _deconstruction_id(asset_id, result)

    vault = MediaVault(tenant_id=tenant_id)
    vault.ensure_manifest()
    attachment_plan = build_attachment_plan(result)
    attachment_paths, attachment_status = source_asset_attachment_inputs(attachment_plan)
    evidence_store = result.get("evidence_store") if isinstance(result.get("evidence_store"), dict) else {}
    source_evidence = {
        "schema_version": "source_evidence_from_evidence_store_v1",
        "evidence_store": evidence_store,
        "source_url": source_url,
        "attachments": [{"path": item.path, "kind": item.kind} for item in attachment_plan],
        "attachment_backwash": _attachment_backwash_pending(attachment_status),
        "stats": result.get("stats") or {},
        "evidence_assets": result.get("evidence_assets") or [],
        "deconstruct_doc_url": result.get("deconstruct_doc_url", ""),
        "recreate_doc_url": result.get("recreate_doc_url", ""),
    }
    if not evidence_store:
        raise RuntimeError("缺少 evidence_store，禁止写入半成品 source artifact")
    captured_at = int(time.time() * 1000)
    source_bundle = vault.write_source_asset_bundle(
        platform=platform,
        asset_id=asset_id,
        manifest={
            "asset_id": asset_id,
            "platform": platform,
            "source_url": source_url,
            "title": title,
            "source_asset_id": source_asset_id,
            "captured_at": captured_at,
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
        source_asset_id=source_asset_id,
        original_title=title,
        author_id=str((result.get("stats") or {}).get("author_id") or result.get("author_id") or ""),
        external_post_id=_external_post_id(result),
        account_name_snapshot=str(result.get("account_name") or result.get("author_name") or ""),
        source_doc_link=str(result.get("source_doc_url") or result.get("deconstruct_doc_url") or result.get("feishu_doc_url") or ""),
        body=body,
        status="已解析",
        enabled=True,
    )
    source_evidence_dir = vault.source_asset_dir(platform, asset_id) / "evidence"
    try:
        source_asset_record = upsert_entity_record(
            "SourceAsset",
            source_assets_url,
            asset_payload,
            key_field="asset_id",
            session_tenant_id=tenant_id,
            attachment_paths=attachment_paths,
        )
        source_evidence["attachment_backwash"] = _attachment_backwash_completed(
            attachment_status,
            source_asset_record,
        )
        vault.write_json_artifact(
            source_evidence_dir,
            "evidence.json",
            source_evidence,
            owner_type="SourceAsset",
            owner_id=asset_id,
            artifact_type="source_evidence",
        )
    except Exception:
        source_evidence["attachment_backwash"] = _attachment_backwash_failed(attachment_status)
        vault.write_json_artifact(
            source_evidence_dir,
            "evidence.json",
            source_evidence,
            owner_type="SourceAsset",
            owner_id=asset_id,
            artifact_type="source_evidence",
        )
        raise

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
        source_asset_id=source_asset_id,
        summary=_summary_text(result.get("content_summary") or result.get("source_summary") or result.get("viral_mechanism") or title),
        hook=_summary_text(result.get("hook_elements") or result.get("viral_mechanism")),
        transferable_points=_summary_text(result.get("production_checklist") or result.get("viral_mechanism")),
        non_transferable_points=_summary_text(result.get("avoid_copying") or result.get("uncertainty_notes") or ""),
        **_request_constraints_bitable_index(result),
        **_shot_adaptation_bitable_index(result, localized=False),
        cover_opening_hook=_summary_text(result.get("cover_opening_hook") or ""),
        core_data_summary=_summary_text(result.get("core_data_summary") or ""),
        top_comment_insight=_summary_text(result.get("top_comment_insight") or ""),
        target_audience=_summary_text(result.get("target_audience") or ""),
        pain_or_pleasure_points=_summary_text(result.get("pain_or_pleasure_points") or ""),
        attention_elements=_summary_text(result.get("attention_elements") or ""),
        viral_mechanism=_summary_text(result.get("viral_mechanism") or ""),
        viral_migration=_summary_text(result.get("viral_migration") or result.get("production_checklist") or ""),
        creative_upgrade_suggestion=_summary_text(result.get("creative_upgrade_suggestion") or ""),
        prompt_bundle_version=PROMPT_BUNDLE_VERSION,
        model=str(result.get("model") or os.getenv("OPENAI_MODEL") or "media_analysis"),
        skill_version=SKILL_VERSION,
        confidence=_confidence(result),
        evidence_uri=deconstruction_artifact["uri"],
        deconstruction_doc_link=str(result.get("deconstruct_doc_url") or result.get("feishu_doc_url") or ""),
        review_status="未复核",
    )
    deconstruction_record = upsert_entity_record(
        "MaterialDeconstruction",
        material_deconstructions_url,
        deconstruction_payload,
        key_field="deconstruction_id",
        session_tenant_id=tenant_id,
    )
    _project_canonical_source_asset(
        tenant_id=tenant_id,
        asset_payload=asset_payload,
        source_bundle=source_bundle,
        attachment_plan=attachment_plan,
        source_asset_record=source_asset_record,
        deconstruction_record=deconstruction_record,
        result=result,
        captured_at=captured_at,
    )
    return str(deconstruction_record.get("record_id") or deconstruction_id)


def _platform_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    if hostname == "douyin.com" or hostname.endswith(".douyin.com") or hostname == "iesdouyin.com" or hostname.endswith(".iesdouyin.com"):
        return "抖音"
    if hostname == "xiaohongshu.com" or hostname.endswith(".xiaohongshu.com") or hostname == "xhslink.com" or hostname.endswith(".xhslink.com"):
        return "小红书"
    return ""


def _external_post_id(result: dict[str, Any]) -> str:
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    for key in ("platform_asset_id", "video_id", "note_id", "item_id", "aweme_id"):
        value = str(stats.get(key) or result.get(key) or "").strip()
        if value:
            return value
    return ""


def _deconstruction_id(asset_id: str, result: dict[str, Any]) -> str:
    source = "|".join(
        [
            asset_id,
            PROMPT_BUNDLE_VERSION,
            str(result.get("model") or os.getenv("OPENAI_MODEL") or "media_analysis"),
            SKILL_VERSION,
            "default",
        ]
    )
    return "decon_" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def _source_asset_id_from_result(result: dict[str, Any], source_text: str) -> str:
    for candidate in (
        result.get("source_asset_id"),
        result.get("source_asset_uri"),
        result.get("source"),
        source_text,
    ):
        normalized = _normalize_source_asset_ref(str(candidate or ""))
        if normalized:
            return normalized
    return ""


def _normalize_source_asset_ref(value: str) -> str:
    text = str(value or "").strip().strip("`")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme == "media":
        parts = [unquote(part) for part in (parsed.netloc, *parsed.path.split("/")) if part]
        if parts and parts[0] == "source_assets" and len(parts) >= 2:
            return parts[1]
        return ""
    match = SOURCE_ASSET_ID_RE.search(text)
    return match.group(0) if match else ""


def _shot_adaptation_bitable_index(result: dict[str, Any], *, localized: bool = True) -> dict[str, Any]:
    contract = result.get("multi_signal_contract") if isinstance(result.get("multi_signal_contract"), dict) else {}
    notes = [item for item in contract.get("shot_adaptation_notes") or [] if isinstance(item, dict)]
    validation = contract.get("validation") if isinstance(contract.get("validation"), dict) else {}
    status = str(validation.get("multi_signal_contract_status") or "").strip()
    warnings = [str(item).strip() for item in validation.get("warnings") or [] if str(item).strip()]
    document_url = str(result.get("deconstruct_doc_url") or result.get("feishu_doc_url") or "").strip()
    return {
        "shot_adaptation_notes_status": _localized_multi_signal_status(status, warnings) if localized else status,
        "shot_adaptation_note_count": len(notes) if notes else None,
        "recommended_production_route": "",
        "motion_type_summary": "",
        "shot_adaptation_notes_summary": _shot_adaptation_notes_summary(
            notes,
            document_url=document_url,
            include_note_ids=not localized,
        ),
    }


def _request_constraints_bitable_index(result: dict[str, Any]) -> dict[str, str]:
    constraints = result.get("request_constraints") if isinstance(result.get("request_constraints"), dict) else {}
    focus = constraints.get("deconstruction_focus")
    output_types = constraints.get("output_types")
    return {
        "analysis_scope": _summary_text(constraints.get("analysis_scope") or "全片", 80),
        "analysis_time_range": _summary_text(constraints.get("analysis_time_range") or "全部", 80),
        "deconstruction_focus": _summary_text(focus if isinstance(focus, list) else focus or "常规拆解", 200),
        "output_types": _summary_text(output_types if isinstance(output_types, list) else output_types or "拆解摘要", 200),
    }


def _localized_multi_signal_status(status: str, warnings: list[str]) -> str:
    labels = {
        "available": "证据充分",
        "insufficient_evidence": "证据不足",
        "schema_failed": "解析失败",
        "llm_failed": "解析失败",
        "validated": "已验证",
        "validated_with_warnings": "已验证，存在待确认项",
    }
    label = labels.get(status, "状态待确认")
    if status in {"schema_failed", "llm_failed"}:
        reason = _summary_text(warnings, 200)
        return f"{label}；原因：{reason or '待确认'}"
    return label


def _shot_adaptation_notes_summary(
    notes: list[dict[str, Any]],
    *,
    document_url: str = "",
    limit: int = 500,
    include_note_ids: bool = False,
) -> str:
    lines: list[str] = []
    for item in notes[:8]:
        pattern = str(item.get("learnable_pattern") or "").strip()
        rule = str(item.get("adaptation_rule") or "").strip()
        avoid = _normalize_text(item.get("do_not_copy")).replace("\n", " ")
        line = "；".join(
            f"{label}：{value}"
            for label, value in (
                ("记录ID", str(item.get("note_id") or "").strip() if include_note_ids else ""),
                ("可学结构", pattern),
                ("适配方法", rule),
                ("避免照搬", avoid),
            )
            if value
        )
        if line:
            lines.append(line)
    if len(notes) > 8:
        link_suffix = f"：{document_url}" if document_url else "（文档链接待补）"
        lines.append(f"共 {len(notes)} 条，完整清单见拆解文档证据附录{link_suffix}")
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
