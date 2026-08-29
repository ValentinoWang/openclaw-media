from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlparse

from common.model_transport_context import bind_model_transport
from common.platform_labels import PLATFORM_LABELS as _COMMON_PLATFORM_LABELS
from common.social_runtime import parse_iso_datetime

from .capability_registry import CAPABILITY_REGISTRY, CapabilityDefinition, CapabilityRegistryError


SCHEMA_VERSION = "media_web_task_v3"
TERMINAL_STATES = frozenset({"succeeded", "pending_manual", "failed", "cancelled"})
MAX_PARAMS_BYTES = 128 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOADS_PER_TASK = 8
_LOCAL_ONLY_INVOCATIONS = frozenset(
    {
        ("universal_deletion", "preview"),
        ("universal_deletion", "confirm"),
    }
)


def _requires_model_transport(capability_id: str, variant_id: str) -> bool:
    return (capability_id, variant_id) not in _LOCAL_ONLY_INVOCATIONS
TASK_RETENTION_SECONDS = 30 * 24 * 60 * 60
UPLOAD_RETENTION_SECONDS = 24 * 60 * 60
CLEANUP_INTERVAL_SECONDS = 60 * 60
DELETION_PREVIEW_TTL_SECONDS = 15 * 60
CONFIRMATION_RECEIPT_TTL_SECONDS = 15 * 60
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
RECEIPT_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
DELETION_TARGET_SEPARATOR = re.compile(r"[\s、,，;；]+")
FEISHU_DOC_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com", ".larkoffice.com")
FEISHU_DOC_ROOT_HOSTS = frozenset({"feishu.cn", "larksuite.com", "larkoffice.com"})
EICAR_TEST_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
FORBIDDEN_RESULT_TOKENS = (
    "/home/",
    "media://",
    "raw_prompt",
    "raw_response",
    "stack_trace",
    "traceback",
    "access_token",
    "refresh_token",
    "cookie",
    "record_id",
)
PUBLIC_RESULT_STATUSES = frozenset({"completed", "needs_attention", "failed"})
INTERNAL_RESULT_LINE = re.compile(r"^(?:状态|运行状态|阻塞来源|追溯\s*id)\s*[:：]", re.IGNORECASE)
INTERNAL_STORAGE_LINE = re.compile(
    r"^(?:本地(?:路径|归档|文件|记录)|暂存路径|素材目录|文字稿任务目录|逐字稿路径|"
    r"周记路径|obsidian(?:详情|原字稿)?|多维表格)\s*[:：]",
    re.IGNORECASE,
)
FORBIDDEN_RESULT_URL = re.compile(
    r"https://(?:[^\s/]+\.)?(?:feishu\.cn|larksuite\.com|larkoffice\.com)/(?:base|bitable|wiki)/",
    re.IGNORECASE,
)
INTERNAL_RESULT_IDENTIFIER = re.compile(
    r"\b(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)+|(?:holder|trace|run|record|task|job)[_-][a-z0-9_-]+)\b",
    re.IGNORECASE,
)
PROJECTION_MUTATION_STATUSES = {
    "creator_profile_upserted",
    "creator_profile_confirmed_written",
    "creator_profile_batch_upserted",
    "creator_profile_batch_partial",
    "deletion_applied",
    "track_registry_upserted",
    "track_creator_membership_confirmed",
}
SOURCE_ASSET_COMPLETION_STATUS = "media_growth_done"
MATERIAL_PARSING_CAPABILITY_ID = "source_asset_intake"
MATERIAL_TYPE_FIELD_KEY = "field_3be96f8eb83d"
MATERIAL_SOURCE_FIELD_KEY = "field_c675ffae69a2"
MATERIAL_MANUAL_SUPPLEMENT_FIELD_KEY = "remark"
MATERIAL_TYPE_ALIASES = {
    "text": "text",
    "文本": "text",
    "url": "url",
    "链接": "url",
    "image": "image",
    "图片": "image",
    "audio": "audio",
    "音频": "audio",
    "video": "video",
    "视频": "video",
    "pdf": "pdf",
    "PDF": "pdf",
}
# NOTE (H8 dedup): this alias table is deliberately NOT sourced from
# common/platform_labels.py's merged PLATFORM_ALIASES. That table
# recognizes many more alias spellings (tiktok, dy, 巨量, xhs, 视频号,
# b站, 哔哩哔哩, ...) than this module's 9-slug validation surface ever
# has. MATERIAL_PLATFORM_ALIASES.get(...) returning None here is a load-
# bearing signal in _validate_source_asset_material_parsing (it means "we
# could not confirm the platform" and drives the missing_fields /
# material_parsing_incomplete error path) -- silently widening what this
# table accepts would silently widen what that validation flow lets
# through. Only MATERIAL_PLATFORM_LABELS (pure "slug -> Chinese display
# text", no validation implications) is deduped against common below.
MATERIAL_PLATFORM_ALIASES = {
    "douyin": "douyin",
    "抖音": "douyin",
    "xiaohongshu": "xiaohongshu",
    "小红书": "xiaohongshu",
    "kuaishou": "kuaishou",
    "快手": "kuaishou",
    "bilibili": "bilibili",
    "哔哩哔哩": "bilibili",
    "wechat": "wechat",
    "微信": "wechat",
    "weibo": "weibo",
    "微博": "weibo",
    "zhihu": "zhihu",
    "知乎": "zhihu",
    "web": "web",
    "普通网页": "web",
    "unknown": "unknown",
    "其他或未知平台": "unknown",
}
# Consolidated into common/platform_labels.py (H8); byte-identical content,
# reused here rather than duplicated.
MATERIAL_PLATFORM_LABELS = dict(_COMMON_PLATFORM_LABELS)
MATERIAL_TYPE_LABELS = {
    "text": "文本",
    "url": "链接",
    "image": "图片",
    "audio": "音频",
    "video": "视频",
    "pdf": "PDF",
}
MATERIAL_AUTOMATIC_URL_PLATFORMS = frozenset({"douyin", "xiaohongshu", "wechat"})
RESERVED_TENANT_KEYS = frozenset(
    {
        "tenant",
        "tenant_id",
        "tenantId",
        "principal",
        "owner",
        "owner_id",
        "ownerId",
        "api_key",
        "apiKey",
        "secret_ref",
        "secretRef",
        "access_token",
        "accessToken",
        "refresh_token",
        "refreshToken",
        "authorization",
        "Authorization",
    }
)


class MediaWebTaskError(RuntimeError):
    _STATUS_BY_CODE = {
        "authentication_required": 401,
        "csrf_rejected": 403,
        "workspace_not_allowed": 403,
        "invalid_request": 400,
        "invalid_tenant": 400,
        "required_input_missing": 422,
        "material_parsing_incomplete": 422,
        "capability_not_found": 404,
        "task_not_found": 404,
        "upload_not_found": 404,
        "account_relationship_unavailable": 404,
        "payload_too_large": 413,
        "catalog_conflict": 409,
        "task_conflict": 409,
        "idempotency_conflict": 409,
        "account_relationship_conflict": 409,
        "confirmation_required": 409,
        "confirmation_expired": 409,
        "invalid_task_state": 409,
        "rate_limited": 429,
        "identity_unavailable": 503,
        "model_settlement_unknown": 503,
        "model_transport_unavailable": 503,
        "service_unavailable": 503,
    }

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status if status is not None else self._STATUS_BY_CODE.get(code, 400)
        self.details = dict(details or {})

    @property
    def issues(self) -> list[Any]:
        value = self.details.get("issues")
        return list(value) if isinstance(value, list) else []

    @issues.setter
    def issues(self, value: list[Any]) -> None:
        self.details["issues"] = list(value)


def _material_value(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    return value.strip() if isinstance(value, str) else ""


def _material_upload_kind(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type == "application/pdf":
        return "pdf"
    return "text"


def _material_failure_prompt(platform: str, material_type: str, *, automatic: bool) -> str:
    platform_label = MATERIAL_PLATFORM_LABELS[platform]
    if material_type == "text":
        return "文本未能解析为有效内容。"
    if material_type == "url":
        if automatic:
            if platform == "wechat":
                return "微信文章链接自动解析失败或返回内容不完整。"
            return f"{platform_label}链接自动解析失败或返回内容不完整。"
        if platform == "unknown":
            return "当前无法确认该平台并自动解析链接。"
        return f"当前未接入{platform_label}链接自动解析。"
    if platform == "unknown":
        if material_type == "video":
            return "当前无法确认该平台并自动解析视频文件。"
        if material_type == "pdf":
            return "当前无法确认该平台并自动解析 PDF 素材。"
        return f"当前无法确认该平台并自动解析{MATERIAL_TYPE_LABELS[material_type]}素材。"
    if material_type == "video":
        return f"当前不支持自动解析{platform_label}视频文件。"
    if material_type == "pdf":
        return f"当前不支持自动解析{platform_label} PDF 素材。"
    return f"当前不支持自动解析{platform_label}{MATERIAL_TYPE_LABELS[material_type]}素材。"


def _material_next_action(platform: str, material_type: str, *, source_missing: bool) -> str:
    if source_missing:
        if material_type in {"image", "audio", "video", "pdf"}:
            return "请先提供原始素材并填写人工补充后重新校验。"
        return "请补充原始文本或链接后重新校验。"
    if material_type == "text":
        return "请补充素材摘要后重新校验。"
    if material_type == "url":
        if platform in MATERIAL_AUTOMATIC_URL_PLATFORMS:
            if platform == "wechat":
                return "请确认文章可访问，或补充标题、正文摘要和用途后重新校验。"
            return "请确认链接可访问，或补充标题、正文摘要和用途后重新校验。"
        if platform == "unknown":
            return "请选择准确平台，或补充链接标题、正文摘要和用途后重新校验。"
        return "请补充链接标题、正文摘要和用途后重新校验。"
    prompts = {
        "image": "请补充图片主体、关键信息和用途后重新校验。",
        "audio": "请补充音频主题、关键内容和用途后重新校验。",
        "video": "请补充视频主题、关键画面或口播摘要和用途后重新校验。",
        "pdf": "请补充文档主题、关键结论和用途后重新校验。",
    }
    prompt = prompts[material_type]
    return f"请选择准确平台，并{prompt[1:]}" if platform == "unknown" else prompt


def _raise_material_parsing_incomplete(
    *,
    failure: str,
    failure_prompt: str,
    missing_fields: Sequence[str],
    next_action: str,
) -> None:
    raise MediaWebTaskError(
        "material_parsing_incomplete",
        "素材解析未完成。",
        details={
            "failure": failure,
            "failurePrompt": failure_prompt,
            "missingFields": list(missing_fields),
            "nextAction": next_action,
        },
    )


def _validate_source_asset_material_parsing(
    params: Mapping[str, Any],
    uploads: Sequence[Mapping[str, Any]],
) -> None:
    material_type_value = _material_value(params, MATERIAL_TYPE_FIELD_KEY)
    platform_value = _material_value(params, "platform")
    manual_supplement = _material_value(params, MATERIAL_MANUAL_SUPPLEMENT_FIELD_KEY)
    if not (material_type_value or platform_value or manual_supplement):
        return

    material_type = MATERIAL_TYPE_ALIASES.get(material_type_value)
    platform = MATERIAL_PLATFORM_ALIASES.get(platform_value)
    if material_type is None or platform is None:
        missing_fields = []
        if material_type is None:
            missing_fields.append(MATERIAL_TYPE_FIELD_KEY)
        if platform is None:
            missing_fields.append("platform")
        _raise_material_parsing_incomplete(
            failure="material_parsing_combination_missing",
            failure_prompt="当前素材类型和平台无法对应到唯一的解析合同。",
            missing_fields=missing_fields,
            next_action="请选择合同中的素材类型和平台后重新校验。",
        )

    automatic = material_type == "text" or (
        material_type == "url" and platform in MATERIAL_AUTOMATIC_URL_PLATFORMS
    )
    source_is_file = material_type in {"image", "audio", "video", "pdf"}
    source_value = _material_value(params, MATERIAL_SOURCE_FIELD_KEY)
    source_missing = not uploads if source_is_file else not source_value
    missing_fields: list[str] = []
    if source_missing:
        missing_fields.append("uploadIds" if source_is_file else MATERIAL_SOURCE_FIELD_KEY)
    if source_is_file and uploads and any(
        _material_upload_kind(str(upload.get("mime_type") or "")) != material_type
        for upload in uploads
    ):
        missing_fields.append("uploadIds.mimeType")
    if not automatic and not manual_supplement:
        missing_fields.append(MATERIAL_MANUAL_SUPPLEMENT_FIELD_KEY)

    if material_type == "url" and source_value and automatic:
        parsed = urlparse(source_value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            missing_fields.append("sourceUrl")

    if missing_fields:
        if source_missing:
            failure = "material_source_missing"
        elif material_type == "text":
            failure = "text_parse_failed"
        else:
            failure = f"{platform}_{material_type}_{'parse_failed' if automatic else 'unsupported'}"
        _raise_material_parsing_incomplete(
            failure=failure,
            failure_prompt=_material_failure_prompt(
                platform,
                material_type,
                automatic=automatic,
            ),
            missing_fields=tuple(dict.fromkeys(missing_fields)),
            next_action=_material_next_action(
                platform,
                material_type,
                source_missing=source_missing,
            ),
        )


def _upload_parsing_facts(content: bytes, mime_type: str, *, accepted: bool) -> dict[str, str]:
    if not accepted:
        return {
            "status": "failed",
            "failure_code": "upload_rejected",
            "next_action": "请更换符合要求的原始文件后重新上传。",
        }
    if mime_type in {"text/plain", "text/markdown"}:
        text = content.decode("utf-8")
        if text.strip():
            return {
                "status": "completed_auto",
                "failure_code": "",
                "next_action": "文本素材已完成自动解析校验。",
            }
        return {
            "status": "failed",
            "failure_code": "text_parse_failed",
            "next_action": "请补充有效文本后重新上传。",
        }
    return {
        "status": "pending_manual",
        "failure_code": "material_context_required",
        "next_action": "请在素材入池时选择平台、素材类型并填写补充说明后重新校验。",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any) -> float | None:
    # Consolidated into common/social_runtime.parse_iso_datetime (H9). The
    # old code called .timestamp() on a possibly-naive datetime.fromisoformat
    # result directly, which silently used this process's OS-local timezone
    # for a naive input; this environment (and this service's deployment)
    # runs with the OS timezone set to UTC, so assume_tz=UTC here is
    # numerically identical while no longer depending on that OS setting.
    dt = parse_iso_datetime(value, assume_tz=timezone.utc)
    return dt.timestamp() if dt is not None else None


def _task_request_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = {
        key: payload.get(key)
        for key in (
            "schemaVersion",
            "capabilityId",
            "variantId",
            "params",
            "uploadIds",
            "catalogVersion",
            "initiation",
            "confirmationReceipt",
        )
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _receipt_expiry(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock() + CONFIRMATION_RECEIPT_TTL_SECONDS, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _confirmation_fields_digest(params: Mapping[str, Any]) -> str:
    stable = {key: value for key, value in params.items() if key not in {"action", "confirmation"}}
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _confirmation_receipt_error(capability_id: str) -> str:
    return {
        "universal_deletion": "deletion_preview_required",
        "creator_profile_upsert": "creator_profile_candidate_required",
        "track_creator_membership_query": "track_creator_membership_preview_required",
    }[capability_id]

def _deletion_target_ids(params: Mapping[str, Any]) -> tuple[str, ...]:
    values = DELETION_TARGET_SEPARATOR.split(str(params.get("id") or "").strip())
    return tuple(sorted({value for value in values if value}))


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _require_tenant_id(value: str) -> str:
    tenant_id = str(value)
    try:
        canonical = str(uuid.UUID(tenant_id))
    except ValueError as exc:
        raise MediaWebTaskError("invalid_tenant", "租户身份无效。") from exc
    if canonical != tenant_id:
        raise MediaWebTaskError("invalid_tenant", "租户身份无效。")
    return canonical


def _tenant_storage_key(tenant_id: str) -> str:
    return hashlib.sha256(_require_tenant_id(tenant_id).encode("utf-8")).hexdigest()


def _contains_reserved_tenant_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key) in RESERVED_TENANT_KEYS or _contains_reserved_tenant_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_reserved_tenant_key(item) for item in value)
    return False


def _safe_filename(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name)[:120]
    return name or "upload.bin"


def _public_feishu_docx_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return ""
    host = str(parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    valid_host = host in FEISHU_DOC_ROOT_HOSTS or any(
        host.endswith(suffix) for suffix in FEISHU_DOC_HOST_SUFFIXES
    )
    if (
        parsed.scheme != "https"
        or not valid_host
        or host.startswith("open.")
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or len(path_parts) != 2
        or path_parts[0].lower() != "docx"
        or SAFE_ID.fullmatch(path_parts[1]) is None
    ):
        return ""
    return f"https://{host}/docx/{path_parts[1]}"


def _detect_mime(content: bytes, filename: str) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"ID3") or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return "audio/mpeg"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        return "video/quicktime" if brand in {b"qt  ", b"qt\x00\x00"} else "video/mp4"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or "application/octet-stream"
    return "text/markdown" if filename.lower().endswith((".md", ".markdown")) else "text/plain"


class MediaWebTaskService:
    """Durable single-worker owner for authenticated Media Web commands."""

    def __init__(
        self,
        app: Any,
        *,
        root: str | Path | None = None,
        clock: Callable[[], float] = time.time,
        start_worker: bool = True,
        start_cleanup_worker: bool | None = None,
        upload_scanner: Callable[[bytes], tuple[bool, str]] | None = None,
        projection_refresher: Callable[[str], None] | None = None,
        source_asset_projector: Callable[[str, Mapping[str, Any], Sequence[Mapping[str, Any]]], Any] | None = None,
        tenant_model_gateway: Any | None = None,
    ) -> None:
        self.app = app
        self.root = Path(root or os.getenv("MEDIA_WEB_TASK_STATE_ROOT", "/home/ubuntu/.openclaw/state/media_web_channel"))
        self.tasks_dir = self.root / "tasks"
        self.events_dir = self.root / "events"
        self.uploads_dir = self.root / "uploads"
        self.audit_dir = self.root / "audit"
        self.worker_lease_path = self.root / "worker.lock"
        self.reservation_lease_path = self.root / "reservation.lock"
        for directory in (self.tasks_dir, self.events_dir, self.uploads_dir, self.audit_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._upload_scanner = upload_scanner or self._scan_upload
        self._projection_refresher = projection_refresher
        self._source_asset_projector = source_asset_projector
        self._tenant_model_gateway = tenant_model_gateway
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-web-task") if start_worker else None
        self._cleanup_stop = threading.Event()
        self._cleanup_thread: threading.Thread | None = None
        self._registry = CAPABILITY_REGISTRY
        self.cleanup_retention()
        if self._executor is not None:
            self._recover_tasks()
        if start_cleanup_worker if start_cleanup_worker is not None else start_worker:
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                name="media-web-retention",
                daemon=True,
            )
            self._cleanup_thread.start()

    def close(self) -> None:
        self._cleanup_stop.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=2)
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)

    def capability_catalog(self, *, is_maintainer: bool = False) -> dict[str, Any]:
        catalog = CAPABILITY_REGISTRY.serialize(
            visibilities=frozenset({"public", "ops", "maintainer"} if is_maintainer else {"public", "ops"}),
            bots=frozenset({"Media bot", "任意 Bot"}),
        )
        return catalog

    def reconcile_model_calls(
        self,
        *,
        tenant_id: str,
        resolver: Callable[[dict[str, Any]], tuple[str, str | None]],
        limit: int = 100,
    ) -> dict[str, int]:
        tenant_id = _require_tenant_id(tenant_id)
        if self._tenant_model_gateway is None:
            raise MediaWebTaskError("service_unavailable", "模型对账服务暂时不可用。")
        return self._tenant_model_gateway.reconcile(tenant_id, resolver, limit=limit)

    def create_task(
        self,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        is_maintainer: bool = False,
        user_public_id: str | None = None,
        workspace_mode: str | None = None,
        role: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        # The IF2 surface forwards the acting principal; task storage remains
        # tenant-scoped, so the identity kwargs are accepted for attribution
        # without changing the tenant-level authorization model.
        del user_public_id, workspace_mode, role
        tenant_id = _require_tenant_id(tenant_id)
        expected_keys = {"schemaVersion", "capabilityId", "variantId", "params", "uploadIds", "idempotencyKey", "catalogVersion", "initiation", "confirmationReceipt"}
        if set(payload) != expected_keys or payload.get("schemaVersion") != "3" or _contains_reserved_tenant_key(payload):
            raise MediaWebTaskError("invalid_request", "任务请求不符合结构化契约。")
        capability_id, variant_id = str(payload.get("capabilityId") or "").strip(), str(payload.get("variantId") or "").strip()
        capability = self._registry.get(capability_id)
        if capability is None or not capability.enabled or not set(capability.bots) & {"Media bot", "任意 Bot"} or capability.visibility not in ({"public", "ops", "maintainer"} if is_maintainer else {"public", "ops"}):
            raise MediaWebTaskError("capability_not_found", "未找到可用的 Media 能力。")
        if payload.get("catalogVersion") != self._registry.catalog_version:
            raise MediaWebTaskError("catalog_conflict", "能力目录已更新，请刷新后重新确认任务。")
        params = payload.get("params")
        if not isinstance(params, Mapping):
            raise MediaWebTaskError("invalid_request", "任务参数必须是结构化对象。")
        params = dict(params)
        if len(json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_PARAMS_BYTES:
            raise MediaWebTaskError("payload_too_large", "输入或文件超过大小限制。")
        issues = self._registry.validation_issues(capability_id, variant_id, params)
        if issues:
            raise MediaWebTaskError(
                str(issues[0]["code"]),
                str(issues[0]["message"]),
                details={"issues": list(issues)},
            )
        upload_ids = payload.get("uploadIds") or []
        if not isinstance(upload_ids, list) or len(upload_ids) > MAX_UPLOADS_PER_TASK:
            raise MediaWebTaskError("invalid_request", "上传文件引用无效。")
        upload_ids = [str(value) for value in upload_ids]
        uploads = [self._load_upload(value, tenant_id=tenant_id) for value in upload_ids]
        if any(item["status"] != "ready" for item in uploads):
            raise MediaWebTaskError("task_conflict", "上传文件尚未准备完成。")
        if capability_id == MATERIAL_PARSING_CAPABILITY_ID:
            _validate_source_asset_material_parsing(params, uploads)
        self._validate_upload_contract(capability, uploads)
        if str(payload.get("initiation") or "") not in {"manual", "ai"}:
            raise MediaWebTaskError("invalid_request", "任务发起来源无效。")
        confirmation_receipt = payload.get("confirmationReceipt")
        requires_preview = (
            (capability_id == "universal_deletion" and variant_id == "confirm")
            or (capability_id == "creator_profile_upsert" and variant_id == "confirm")
            or (capability_id == "track_creator_membership_query" and variant_id == "confirm")
        )
        if not requires_preview and confirmation_receipt is not None:
            raise MediaWebTaskError("invalid_request", "此任务不接受确认回执。")
        if requires_preview and not isinstance(confirmation_receipt, Mapping):
            raise MediaWebTaskError(_confirmation_receipt_error(capability_id), "确认必须携带用户所见预览的完整回执。")
        idempotency_key = str(payload.get("idempotencyKey") or "").strip()
        if not idempotency_key or len(idempotency_key) > 128 or not SAFE_ID.fullmatch(idempotency_key):
            raise MediaWebTaskError("invalid_request", "幂等键无效。")
        request_fingerprint = _task_request_fingerprint(payload)
        def reserve_preview() -> tuple[dict[str, Any] | None, str]:
            if not requires_preview:
                return None, ""
            return self._load_confirmation_preview(
                tenant_id, capability_id, params, dict(confirmation_receipt or {}),
            ), _confirmation_receipt_error(capability_id)
        with self._lock:
            existing = self._find_by_idempotency(tenant_id, idempotency_key)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise MediaWebTaskError("idempotency_conflict", "幂等键已绑定其他任务请求。")
                return self._project(existing), False
            if capability_id == "universal_deletion" and variant_id == "preview":
                existing = self._find_reusable_deletion_preview(tenant_id, params)
                if existing is not None:
                    return self._project(existing), False
            preview, preview_error = reserve_preview()
            if preview_error and preview is None:
                raise MediaWebTaskError(preview_error, "确认所需预览不存在、已过期或不匹配。")
            if preview is not None and preview.get("confirmation_task_id"):
                return self._project(self._load_task(str(preview["confirmation_task_id"]), tenant_id=tenant_id)), False
        if self._tenant_model_gateway is not None and _requires_model_transport(capability_id, variant_id):
            try:
                self._tenant_model_gateway.prepare()
            except Exception as exc:
                raise MediaWebTaskError(str(getattr(exc, "code", "model_transport_unavailable")), "租户模型凭证不可用。") from exc
        with self._reservation_lease():
            with self._lock:
                existing = self._find_by_idempotency(tenant_id, idempotency_key)
                if existing is not None:
                    if existing.get("request_fingerprint") != request_fingerprint:
                        raise MediaWebTaskError("idempotency_conflict", "幂等键已绑定其他任务请求。")
                    return self._project(existing), False
                if capability_id == "universal_deletion" and variant_id == "preview":
                    existing = self._find_reusable_deletion_preview(tenant_id, params)
                    if existing is not None:
                        return self._project(existing), False
                preview, preview_error = reserve_preview()
                if preview_error and preview is None:
                    raise MediaWebTaskError(preview_error, "确认所需预览不存在、已过期或不匹配。")
                if preview is not None and preview.get("confirmation_task_id"):
                    return self._project(self._load_task(str(preview["confirmation_task_id"]), tenant_id=tenant_id)), False
                now, task_id = _utc_now(), f"mwt_{uuid.uuid4().hex}"
                confirmation_required = self._invocation_requires_confirmation(capability, variant_id)
                task = {"schema_version": SCHEMA_VERSION, "task_id": task_id, "tenant_id": tenant_id, "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint, "model_request_root": f"mreq_{uuid.uuid4().hex}", "invocation": {"capability_id": capability.capability_id, "variant_id": variant_id, "params": params, "upload_ids": upload_ids, "initiation": payload["initiation"], "catalog_version": self._registry.catalog_version, "confirmation_receipt": confirmation_receipt}, "capability_path": list(capability.hierarchy.path_names), "capability_label": capability.display_name, "authorization": {"is_maintainer": bool(is_maintainer)}, "summary": self._registry.summary(capability_id, params), "status": "awaiting_confirmation" if confirmation_required else "queued", "progress": 0, "confirmation": {"state": "required" if confirmation_required else "not_required", "required": confirmation_required, "note": "", "decided_at": ""}, "result": None, "error": None, "cancel_requested": False, "created_at": now, "updated_at": now, "event_cursor": 0}
                if preview is not None:
                    ref_key = {"universal_deletion": "deletion_preview_ref", "creator_profile_upsert": "creator_profile_candidate_ref", "track_creator_membership_query": "track_creator_membership_preview_ref"}[capability_id]
                    task[ref_key] = preview["task_id"]
                self._write_task(task)
                if preview is not None:
                    preview["confirmation_task_id"], preview["updated_at"] = task_id, now
                    self._write_task(preview)
                self._append_event(task, "task.created", "任务已受理。")
                if confirmation_required:
                    self._append_event(task, "task.confirmation", "任务等待确认。")
                self._audit(tenant_id, "task.create", task_id, "accepted")
                if not confirmation_required:
                    self._submit(task_id, tenant_id)
                return self._project(task), True
    def list_tasks(
        self, *, tenant_id: str, limit: int = 20, user_public_id: str | None = None
    ) -> dict[str, Any]:
        del user_public_id
        tenant_id = _require_tenant_id(tenant_id)
        tasks = self._iter_tenant_tasks(tenant_id)
        tasks.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"schemaVersion": SCHEMA_VERSION, "tasks": [self._project(item) for item in tasks[: max(1, min(limit, 100))]]}

    def get_task(
        self, task_id: str, *, tenant_id: str, user_public_id: str | None = None
    ) -> dict[str, Any]:
        del user_public_id
        return self._project(self._load_task(task_id, tenant_id=tenant_id))

    def get_events(
        self, task_id: str, *, tenant_id: str, after: int = 0, user_public_id: str | None = None
    ) -> list[dict[str, Any]]:
        del user_public_id
        tenant_id = _require_tenant_id(tenant_id)
        self._load_task(task_id, tenant_id=tenant_id)
        path = self._tenant_dir(self.events_dir, tenant_id) / f"{task_id}.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("tenant_id") != tenant_id:
                raise MediaWebTaskError("invalid_task_state", "任务状态版本无效，请由维护者处理。")
            if int(event.get("eventId") or 0) > after:
                events.append(event)
        return events

    def cancel_task(
        self, task_id: str, *, tenant_id: str, user_public_id: str | None = None
    ) -> dict[str, Any]:
        del user_public_id
        tenant_id = _require_tenant_id(tenant_id)
        with self._lock:
            task = self._load_task(task_id, tenant_id=tenant_id)
            if task["status"] in TERMINAL_STATES:
                return self._project(task)
            task["cancel_requested"] = True
            if task["status"] in {"queued", "awaiting_confirmation"}:
                self._transition(task, "cancelled", progress=100, event_type="task.cancelled", message="任务已取消。")
            else:
                self._write_task(task)
                self._append_event(task, "task.status", "取消请求已记录；已生成的内容会保留。")
            self._audit(tenant_id, "task.cancel", task_id, task["status"])
            return self._project(task)

    def confirm_task(
        self,
        task_id: str,
        payload: Mapping[str, Any],
        *,
        tenant_id: str,
        user_public_id: str | None = None,
    ) -> dict[str, Any]:
        del user_public_id
        tenant_id = _require_tenant_id(tenant_id)
        if set(payload) != {"decision", "note"} or _contains_reserved_tenant_key(payload):
            raise MediaWebTaskError("invalid_request", "确认信息无效。")
        decision = str(payload.get("decision") or "").strip()
        note = str(payload.get("note") or "").strip()
        if decision not in {"approve", "reject"} or len(note.encode("utf-8")) > 4096:
            raise MediaWebTaskError("invalid_request", "确认信息无效。")
        with self._lock:
            task = self._load_task(task_id, tenant_id=tenant_id)
            decided_state = "approved" if decision == "approve" else "rejected"
            if task.get("confirmation", {}).get("state") == decided_state:
                return self._project(task)
            if task["status"] != "awaiting_confirmation" or not task["confirmation"]["required"]:
                raise MediaWebTaskError("task_conflict", "任务当前状态不允许此操作。")
            invocation = task.get("invocation") or {}
            capability_id = str(invocation.get("capability_id") or "")
            if (
                decision == "approve"
                and invocation.get("variant_id") == "confirm"
                and capability_id
                in {
                    "universal_deletion",
                    "creator_profile_upsert",
                    "track_creator_membership_query",
                }
            ):
                receipt = invocation.get("confirmation_receipt")
                preview = (
                    self._load_confirmation_preview(
                        tenant_id,
                        capability_id,
                        invocation.get("params") or {},
                        receipt,
                    )
                    if isinstance(receipt, Mapping)
                    else None
                )
                if preview is None:
                    raise MediaWebTaskError(
                        _confirmation_receipt_error(capability_id),
                        "确认所需预览不存在、已过期或不匹配。",
                    )
            task["confirmation"].update(
                {"state": decided_state, "note": note, "decided_at": _utc_now()}
            )
            if decision == "reject":
                self._transition(task, "cancelled", progress=100, event_type="task.cancelled", message="任务确认已拒绝。")
            else:
                self._transition(task, "queued", progress=0, event_type="task.confirmation", message="任务确认已通过。")
                self._submit(task_id, tenant_id)
            self._audit(tenant_id, "task.confirm", task_id, decision)
            return self._project(task)

    def create_upload(self, payload: Mapping[str, Any], *, tenant_id: str) -> tuple[dict[str, Any], bool]:
        tenant_id = _require_tenant_id(tenant_id)
        expected_keys = {"filename", "mimeType", "contentBase64"}
        if set(payload) != expected_keys or _contains_reserved_tenant_key(payload):
            raise MediaWebTaskError("invalid_request", "上传请求不符合结构化契约。")
        filename = _safe_filename(str(payload.get("filename") or ""))
        declared_mime = str(payload.get("mimeType") or "").lower().strip()
        encoded = payload.get("contentBase64")
        if not isinstance(encoded, str):
            raise MediaWebTaskError("invalid_request", "上传内容无效。")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise MediaWebTaskError("invalid_request", "上传内容无效。") from exc
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise MediaWebTaskError("payload_too_large", "输入或文件超过大小限制。")
        detected_mime = _detect_mime(content, filename)
        allowed = {
            "image/jpeg", "image/png", "image/webp", "text/plain", "text/markdown", "application/pdf",
            "audio/mpeg", "audio/mp4", "video/mp4", "video/quicktime",
        }
        if detected_mime not in allowed or (declared_mime and declared_mime != detected_mime):
            raise MediaWebTaskError("invalid_request", "文件类型与内容不匹配或不受支持。")
        digest = hashlib.sha256(content).hexdigest()
        with self._lock:
            tenant_uploads_dir = self._tenant_dir(self.uploads_dir, tenant_id, create=True)
            for metadata_path in tenant_uploads_dir.glob("*.json"):
                item = json.loads(metadata_path.read_text(encoding="utf-8"))
                if item.get("tenant_id") == tenant_id and item.get("sha256") == digest and item.get("status") == "ready":
                    return self._project_upload(item), False
            upload_id = f"mwu_{uuid.uuid4().hex}"
            quarantine_path = tenant_uploads_dir / f"{upload_id}.quarantine"
            quarantine_path.write_bytes(content)
            now = _utc_now()
            item = {
                "schema_version": SCHEMA_VERSION,
                "upload_id": upload_id,
                "tenant_id": tenant_id,
                "filename": filename,
                "mime_type": detected_mime,
                "size": len(content),
                "sha256": digest,
                "status": "quarantined",
                "storage_path": str(quarantine_path),
                "scan": {"engine": "bounded_signature_v1", "state": "pending", "code": "", "checked_at": ""},
                "created_at": now,
                "updated_at": now,
            }
            _atomic_write_json(tenant_uploads_dir / f"{upload_id}.json", item)
            self._audit(tenant_id, "upload.create", upload_id, "quarantined")
            try:
                accepted, scan_code = self._upload_scanner(content)
            except Exception:
                accepted, scan_code = False, "scanner_error"
            item["scan"] = {
                "engine": "bounded_signature_v1",
                "state": "passed" if accepted else "rejected",
                "code": scan_code,
                "checked_at": _utc_now(),
            }
            item["parsing"] = _upload_parsing_facts(
                content,
                detected_mime,
                accepted=accepted,
            )
            if accepted:
                binary_path = tenant_uploads_dir / f"{upload_id}.bin"
                os.replace(quarantine_path, binary_path)
                item["status"] = "ready"
                item["storage_path"] = str(binary_path)
            else:
                quarantine_path.unlink(missing_ok=True)
                item["status"] = "rejected"
                item["storage_path"] = ""
            item["updated_at"] = _utc_now()
            _atomic_write_json(tenant_uploads_dir / f"{upload_id}.json", item)
            self._audit(tenant_id, "upload.scan", upload_id, item["status"])
            return self._project_upload(item), True

    @staticmethod
    def _scan_upload(content: bytes) -> tuple[bool, str]:
        if EICAR_TEST_SIGNATURE in content:
            return False, "eicar_test_signature"
        return True, "no_known_signature"

    @staticmethod
    def _invocation_requires_confirmation(capability: CapabilityDefinition, variant_id: str) -> bool:
        stage = capability.confirmation_policy.stage
        if stage == "none":
            return False
        if stage == "destructive_preview_apply":
            return variant_id == "confirm"
        if stage == "after_candidate":
            return variant_id in {"confirm", "batch"}
        if stage == "before_execute" and variant_id in {"query", "preview"}:
            return False
        return True

    @staticmethod
    def _validate_upload_contract(capability: CapabilityDefinition, uploads: list[Mapping[str, Any]]) -> None:
        if not uploads:
            return
        policy = capability.attachment_policy
        if len(uploads) > policy.max_count:
            raise MediaWebTaskError("too_many_uploads", "上传文件数量超过当前能力限制。")
        allowed = set(policy.types)
        for upload in uploads:
            if int(upload.get("size") or 0) > policy.max_bytes:
                raise MediaWebTaskError("upload_too_large", "上传文件超过当前能力大小限制。")
            mime = str(upload.get("mime_type") or "")
            kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else "document" if mime == "application/pdf" else "text"
            if kind not in allowed:
                raise MediaWebTaskError("invalid_upload_type", "上传文件类型不适用于当前能力。")

    @staticmethod
    def _tenant_dir(base: Path, tenant_id: str, *, create: bool = False) -> Path:
        path = base / _tenant_storage_key(tenant_id)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _task_path(self, task_id: str, *, tenant_id: str) -> Path:
        if not SAFE_ID.fullmatch(task_id):
            raise MediaWebTaskError("task_not_found", "未找到该任务。")
        return self._tenant_dir(self.tasks_dir, tenant_id) / f"{task_id}.json"

    def _load_task(self, task_id: str, *, tenant_id: str) -> dict[str, Any]:
        tenant_id = _require_tenant_id(tenant_id)
        path = self._task_path(task_id, tenant_id=tenant_id)
        if not path.exists():
            raise MediaWebTaskError("task_not_found", "未找到该任务。")
        task = json.loads(path.read_text(encoding="utf-8"))
        if task.get("schema_version") != SCHEMA_VERSION or not isinstance(task.get("invocation"), Mapping):
            raise MediaWebTaskError("invalid_task_state", "任务状态版本无效，请由维护者处理。")
        if task.get("tenant_id") != tenant_id:
            raise MediaWebTaskError("task_not_found", "未找到该任务。")
        return task

    def _write_task(self, task: dict[str, Any]) -> None:
        tenant_id = _require_tenant_id(str(task.get("tenant_id") or ""))
        task["updated_at"] = _utc_now()
        self._tenant_dir(self.tasks_dir, tenant_id, create=True)
        _atomic_write_json(self._task_path(str(task["task_id"]), tenant_id=tenant_id), task)

    def _iter_tasks(self) -> list[dict[str, Any]]:
        tasks = []
        for path in self.tasks_dir.glob("*/mwt_*.json"):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
                tenant_id = _require_tenant_id(str(task.get("tenant_id") or ""))
                if (
                    path.parent.name != _tenant_storage_key(tenant_id)
                    or task.get("schema_version") != SCHEMA_VERSION
                    or not isinstance(task.get("invocation"), Mapping)
                ):
                    continue
                tasks.append(task)
            except (OSError, json.JSONDecodeError, MediaWebTaskError):
                continue
        return tasks

    def _iter_tenant_tasks(self, tenant_id: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for path in self._tenant_dir(self.tasks_dir, tenant_id).glob("mwt_*.json"):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
                if (
                    task.get("tenant_id") == tenant_id
                    and task.get("schema_version") == SCHEMA_VERSION
                    and isinstance(task.get("invocation"), Mapping)
                ):
                    tasks.append(task)
            except (OSError, json.JSONDecodeError):
                continue
        return tasks

    def _find_by_idempotency(self, tenant_id: str, key: str) -> dict[str, Any] | None:
        for task in self._iter_tenant_tasks(tenant_id):
            if task.get("tenant_id") == tenant_id and task.get("idempotency_key") == key:
                return task
        return None

    def _find_reusable_deletion_preview(
        self,
        tenant_id: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        targets = _deletion_target_ids(params)
        if not targets:
            return None
        cutoff = self._clock() - DELETION_PREVIEW_TTL_SECONDS
        candidates = []
        for task in self._iter_tenant_tasks(tenant_id):
            invocation = task.get("invocation") or {}
            created_at = _timestamp(task.get("created_at"))
            if (
                invocation.get("capability_id") == "universal_deletion"
                and invocation.get("variant_id") == "preview"
                and _deletion_target_ids(invocation.get("params") or {}) == targets
                and created_at is not None
                and created_at >= cutoff
                and task.get("status") not in {"failed", "cancelled", "pending_manual"}
            ):
                if task.get("status") == "succeeded":
                    receipt = ((task.get("result") or {}).get("receipt") or {})
                    if receipt.get("kind") != "deletion_preview":
                        continue
                    confirmation_task_id = str(task.get("confirmation_task_id") or "")
                    if confirmation_task_id:
                        try:
                            confirmation_task = self._load_task(confirmation_task_id, tenant_id=tenant_id)
                        except MediaWebTaskError:
                            continue
                        if confirmation_task.get("status") in TERMINAL_STATES:
                            continue
                candidates.append(task)
        return max(candidates, key=lambda item: str(item.get("created_at") or ""), default=None)

    def _load_confirmation_preview(
        self,
        tenant_id: str,
        capability_id: str,
        params: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        preview_task_id = str(receipt.get("previewTaskId") or "")
        if not SAFE_ID.fullmatch(preview_task_id):
            return None
        try:
            preview = self._load_task(preview_task_id, tenant_id=tenant_id)
        except MediaWebTaskError:
            return None
        actual = ((preview.get("result") or {}).get("receipt") or {})
        expected_kind = {
            "universal_deletion": "deletion_preview",
            "creator_profile_upsert": "creator_profile_candidate",
            "track_creator_membership_query": "track_creator_membership_preview",
        }[capability_id]
        expected_statuses = (
            {"succeeded", "pending_manual"}
            if capability_id == "track_creator_membership_query"
            else {"succeeded"}
        )
        if preview.get("status") not in expected_statuses or actual.get("kind") != expected_kind:
            return None
        if (
            dict(receipt) != dict(actual)
            or actual.get("previewTaskId") != preview.get("task_id")
            or not RECEIPT_DIGEST.fullmatch(
                str(actual.get(
                    "planDigest" if capability_id == "universal_deletion"
                    else "candidateDigest" if capability_id == "creator_profile_upsert"
                    else "fieldsDigest"
                ) or "")
            )
            or _timestamp(actual.get("expiresAt")) is None
        ):
            return None
        if (_timestamp(actual.get("expiresAt")) or 0) <= self._clock():
            return None
        if capability_id == "universal_deletion":
            target_ids = actual.get("targetIds")
            if (
                not isinstance(target_ids, list)
                or not target_ids
                or any(not isinstance(value, str) or not SAFE_ID.fullmatch(value) for value in target_ids)
                or actual.get("targetCount") != len(target_ids)
                or not isinstance(actual.get("entityCount"), int)
                or actual["entityCount"] < 0
                or tuple(sorted(target_ids)) != _deletion_target_ids(params)
            ):
                return None
        elif capability_id == "creator_profile_upsert":
            if actual.get("runId") != str(params.get("run_id") or ""):
                return None
        elif actual.get("fieldsDigest") != _confirmation_fields_digest(params):
            return None
        return preview

    @staticmethod
    def _confirmation_fields_digest(params: Mapping[str, Any]) -> str:
        return _confirmation_fields_digest(params)

    def _append_event(self, task: dict[str, Any], event_type: str, message: str) -> None:
        task["event_cursor"] = int(task.get("event_cursor") or 0) + 1
        event = {
            "tenant_id": task["tenant_id"],
            "eventId": task["event_cursor"],
            "taskId": task["task_id"],
            "type": event_type,
            "status": task["status"],
            "progress": int(task.get("progress") or 0),
            "message": message,
            "createdAt": _utc_now(),
        }
        tenant_events_dir = self._tenant_dir(self.events_dir, str(task["tenant_id"]), create=True)
        path = tenant_events_dir / f"{task['task_id']}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._write_task(task)

    def _transition(
        self,
        task: dict[str, Any],
        status: str,
        *,
        progress: int,
        event_type: str = "task.status",
        message: str,
    ) -> None:
        if task.get("status") in TERMINAL_STATES and status != task.get("status"):
            raise MediaWebTaskError("task_conflict", "任务当前状态不允许此操作。")
        task["status"] = status
        task["progress"] = max(0, min(progress, 100))
        self._append_event(task, event_type, message)

    def _submit(self, task_id: str, tenant_id: str) -> None:
        if self._executor is not None:
            self._executor.submit(self._execute, task_id, tenant_id)

    def _execute(self, task_id: str, tenant_id: str) -> None:
        with self._worker_lease(blocking=True) as acquired:
            if acquired:
                self._execute_with_lease(task_id, tenant_id)

    def _execute_with_lease(self, task_id: str, tenant_id: str) -> None:
        try:
            with self._lock:
                task = self._load_task(task_id, tenant_id=tenant_id)
                if task["status"] in TERMINAL_STATES or task["status"] == "awaiting_confirmation":
                    return
                if task.get("cancel_requested"):
                    self._transition(task, "cancelled", progress=100, event_type="task.cancelled", message="任务已取消。")
                    return
                self._transition(task, "validating", progress=10, message="输入与能力契约校验完成。")
                invocation = task["invocation"]
                capability_id = str(invocation.get("capability_id") or "")
                variant_id = str(invocation.get("variant_id") or "")
                params = invocation.get("params")
                if invocation.get("catalog_version") != self._registry.catalog_version or not isinstance(params, Mapping):
                    raise MediaWebTaskError("catalog_conflict", "任务能力目录版本已过期。")
                capability = self._registry.require_valid_invocation(capability_id, variant_id, params)
                handler_callable = callable(getattr(getattr(self.app, "router", None), capability.handler, None))
                if not handler_callable or not callable(getattr(self.app, "process_capability_invocation", None)):
                    raise MediaWebTaskError("service_unavailable", "能力处理服务暂时不可用。")
                uploads = [self._load_upload(value, tenant_id=tenant_id) for value in invocation.get("upload_ids", [])]
                self._validate_upload_contract(capability, uploads)
                downloaded_paths = [str(item["storage_path"]) for item in uploads]
                attachments = [
                    {
                        "file_name": item["filename"],
                        "mime_type": item["mime_type"],
                        "local_path": item["storage_path"],
                        "sha256": item["sha256"],
                    }
                    for item in uploads
                ]
                metadata = {
                    "tenant_id": tenant_id,
                    "tenant_context": {"tenant_id": tenant_id},
                    "channel": "media_web",
                    "account_id": "media",
                    "bot": "Media bot",
                    "canonical_capability_id": capability_id,
                    "capability_variant_id": variant_id,
                    "media_web_task_id": task_id,
                    "downloaded_paths": downloaded_paths,
                    "attachments": attachments,
                    "is_maintainer": bool(
                        (task.get("authorization") or {}).get("is_maintainer")
                    ),
                    "media_web_uploads": [
                        {
                            "upload_id": item["upload_id"],
                            "filename": item["filename"],
                            "mime_type": item["mime_type"],
                            "path": item["storage_path"],
                            "sha256": item["sha256"],
                        }
                        for item in uploads
                    ],
                }
                operator_id = os.getenv("OPENCLAW_MEDIA_WEB_OPERATOR_ID", "").strip()
                if operator_id:
                    metadata["operator_id"] = operator_id
                task["canonical_execution_started_at"] = _utc_now()
                task["canonical_execution_owner_pid"] = os.getpid()
                self._transition(task, "generating", progress=40, message="开始生成内容。")
            model_request_root = str(task.get("model_request_root") or "")
            requires_model_transport = _requires_model_transport(capability_id, variant_id)
            if self._tenant_model_gateway is not None and requires_model_transport:
                if not model_request_root:
                    raise MediaWebTaskError("invalid_task_state", "任务缺少模型调用引用。")
                model_scope = self._tenant_model_gateway.bind(
                    tenant_id,
                    task_id,
                    model_request_root,
                )
            else:
                # Test/internal executors may not call a model; any attempted model call fails closed.
                model_scope = bind_model_transport(None, required=True)
            with model_scope:
                result = self.app.process_capability_invocation(
                    capability_id=capability_id,
                    variant_id=variant_id,
                    params=dict(params),
                    source="web",
                    chat_type="private",
                    metadata=metadata,
                )
            if requires_model_transport and self._model_settlement_unknown(tenant_id, task_id):
                raise MediaWebTaskError(
                    "model_settlement_unknown",
                    "模型调用结果需要对账。",
                )
            raw_result = asdict(result) if is_dataclass(result) else dict(result or {})
            original_status = str(raw_result.get("status") or "")
            source_projection_failed = False
            if (
                capability_id == "source_asset_intake"
                and original_status == SOURCE_ASSET_COMPLETION_STATUS
                and bool(raw_result.get("ok"))
                and self._source_asset_projector is not None
            ):
                extra = raw_result.get("extra") if isinstance(raw_result.get("extra"), Mapping) else {}
                artifact = extra.get("artifact") if isinstance(extra, Mapping) else None
                try:
                    if not isinstance(artifact, Mapping):
                        raise MediaWebTaskError("source_asset_projection_missing", "SourceAsset 投影缺少已落盘 artifact。")
                    self._source_asset_projector(tenant_id, artifact, attachments)
                except Exception:
                    source_projection_failed = True
            with self._lock:
                task = self._load_task(task_id, tenant_id=tenant_id)
                if task.get("cancel_requested"):
                    self._transition(task, "cancelled", progress=100, event_type="task.cancelled", message="任务已取消；已发生的写入保留审计记录。")
                    return
                safe_result = self._safe_result(raw_result, task=task)
                if source_projection_failed:
                    safe_result = {
                        "ok": False,
                        "status": "needs_attention",
                        "reply": "素材已保存，但暂未显示在网页素材库。请稍后刷新查看。",
                        "links": [],
                        "receipt": safe_result.get("receipt"),
                    }
                invocation = task.get("invocation") if isinstance(task.get("invocation"), Mapping) else {}
                capability_id = str(invocation.get("capability_id") or "")
                projection_refresh_required = original_status in PROJECTION_MUTATION_STATUSES or (
                    capability_id == "source_asset_intake"
                    and original_status == SOURCE_ASSET_COMPLETION_STATUS
                )
                if (
                    bool(safe_result.get("ok"))
                    and projection_refresh_required
                    and self._projection_refresher is not None
                ):
                    try:
                        self._projection_refresher(tenant_id)
                    except Exception:
                        safe_result = {
                            "ok": False,
                            "status": "needs_attention",
                            "reply": "业务写入已完成，但网页数据暂未刷新，请稍后重试或联系维护者。",
                            "links": [],
                            "receipt": safe_result.get("receipt"),
                        }
                task["result"] = safe_result
                result_status = str(safe_result.get("status") or "")
                if bool(safe_result.get("ok")):
                    terminal_status = "succeeded"
                    message = "任务已完成。"
                elif result_status == "needs_attention":
                    terminal_status = "pending_manual"
                    message = "任务需要人工补充或处理。"
                else:
                    terminal_status = "failed"
                    message = "任务执行未完成。"
                for upload_id in task["invocation"].get("upload_ids", []):
                    self._mark_upload_consumed(upload_id, tenant_id=tenant_id)
                self._transition(task, terminal_status, progress=100, event_type="task.result", message=message)
                self._audit(tenant_id, "task.execute", task_id, terminal_status)
        except Exception as exc:
            with self._lock:
                try:
                    task = self._load_task(task_id, tenant_id=tenant_id)
                except MediaWebTaskError:
                    return
                if task.get("status") in TERMINAL_STATES:
                    return
                code = (
                    "model_settlement_unknown"
                    if self._model_settlement_unknown(tenant_id, task_id)
                    else getattr(exc, "code", "task_execution_failed")
                )
                task["error"] = {
                    "code": str(code),
                    "message": "任务执行未完成，底层详情未向当前接口公开。",
                    "action": (
                        "本次模型调用结果待对账，请勿重复提交；由维护者完成用量核对。"
                        if str(code) == "model_settlement_unknown"
                        else "检查输入与来源状态后重试；仍失败时由维护者查看任务审计。"
                    ),
                }
                terminal_status = "pending_manual" if str(code) == "model_settlement_unknown" else "failed"
                self._transition(
                    task,
                    terminal_status,
                    progress=100,
                    event_type="task.error",
                    message="模型调用结果待对账。" if terminal_status == "pending_manual" else "任务执行未完成。",
                )
                self._audit(tenant_id, "task.execute", task_id, terminal_status)

    def _model_settlement_unknown(self, tenant_id: str, task_id: str) -> bool:
        if self._tenant_model_gateway is None:
            return False
        try:
            calls = self._tenant_model_gateway.task_calls(tenant_id, task_id)
        except Exception:
            return False
        return any(
            str(item.get("status") or "") == "unknown_reconcile"
            for item in calls
            if isinstance(item, Mapping)
        )

    def _safe_result(
        self,
        result: Any,
        *,
        task: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw = asdict(result) if is_dataclass(result) else dict(result or {})
        status = str(raw.get("status") or "unknown")
        receipt: dict[str, Any] | None = None
        extra = raw.get("extra") if isinstance(raw.get("extra"), Mapping) else {}
        if status == "creator_profile_candidate_ready":
            candidate = extra.get("creator_profile_candidate") if isinstance(extra, Mapping) else None
            run_id = str(candidate.get("run_id") or "") if isinstance(candidate, Mapping) else ""
            if SAFE_ID.fullmatch(run_id):
                encoded = json.dumps(candidate.get("candidate_payload") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                receipt = {"kind": "creator_profile_candidate", "previewTaskId": str((task or {}).get("task_id") or ""), "runId": run_id, "candidateDigest": f"sha256:{hashlib.sha256(encoded).hexdigest()}", "expiresAt": _receipt_expiry(self._clock)}
        elif status == "track_creator_membership_pending_manual" and task is not None:
            invocation = task.get("invocation") if isinstance(task.get("invocation"), Mapping) else {}
            if invocation.get("capability_id") == "track_creator_membership_query" and invocation.get("variant_id") == "preview":
                receipt = {"kind": "track_creator_membership_preview", "previewTaskId": str(task.get("task_id") or ""), "fieldsDigest": _confirmation_fields_digest(invocation.get("params") or {}), "expiresAt": _receipt_expiry(self._clock)}
        elif status == "creator_profile_confirmed_written":
            confirmation = extra.get("creator_profile_confirm") if isinstance(extra, Mapping) else None
            creator = confirmation.get("creator_profile") if isinstance(confirmation, Mapping) else None
            record_id = str(creator.get("record_id") or "") if isinstance(creator, Mapping) else ""
            if SAFE_ID.fullmatch(record_id):
                receipt = {"kind": "creator_profile_written", "recordId": record_id}
        elif status == "deletion_dry_run" and task is not None:
            deletion = extra.get("deletion") if isinstance(extra, Mapping) else None
            invocation = task.get("invocation") if isinstance(task.get("invocation"), Mapping) else {}
            target_ids = list(_deletion_target_ids(invocation.get("params") or {}))
            entity_count = 0
            digest_source: Any = {
                "target_ids": target_ids,
                "reply": str(raw.get("reply") or ""),
            }
            if isinstance(deletion, list):
                plan_target_ids = sorted({
                    str(plan.get("target_id") or "")
                    for plan in deletion
                    if isinstance(plan, Mapping) and str(plan.get("target_id") or "")
                })
                if plan_target_ids:
                    target_ids = plan_target_ids
                entity_count = sum(
                    len(plan.get("entities") or [])
                    for plan in deletion
                    if isinstance(plan, Mapping)
                )
                digest_source = deletion
            if target_ids:
                encoded = json.dumps(digest_source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                expires_at = datetime.fromtimestamp(
                    self._clock() + DELETION_PREVIEW_TTL_SECONDS,
                    tz=timezone.utc,
                ).isoformat().replace("+00:00", "Z")
                receipt = {
                    "kind": "deletion_preview",
                    "previewTaskId": str(task.get("task_id") or ""),
                    "targetIds": target_ids,
                    "targetCount": len(target_ids),
                    "entityCount": entity_count,
                    "planDigest": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                    "expiresAt": expires_at,
                }
        public_status = "completed" if bool(raw.get("ok")) else (
            "needs_attention" if any(token in status.lower() for token in ("pending", "manual", "not_implemented")) else "failed"
        )
        assert public_status in PUBLIC_RESULT_STATUSES
        reply = self._public_result_reply(str(raw.get("reply") or ""), receipt=receipt, public_status=public_status)
        invocation = task.get("invocation") if isinstance((task or {}).get("invocation"), Mapping) else {}
        if invocation.get("capability_id") == "universal_deletion" and public_status == "failed":
            reply = (
                "删除预览生成失败，本次未执行删除。请刷新后重试。"
                if invocation.get("variant_id") == "preview"
                else "删除执行未完成，请刷新资源状态后重试。"
            )
        links = []
        feishu_doc = _public_feishu_docx_url(raw.get("feishu_doc"))
        if feishu_doc:
            links.append({"label": "查看交付文档", "url": feishu_doc})
        return {
            "ok": bool(raw.get("ok")),
            "status": public_status,
            "reply": reply,
            "links": links,
            "receipt": receipt,
        }

    @staticmethod
    def _public_result_reply(reply: str, *, receipt: Mapping[str, Any] | None, public_status: str) -> str:
        if receipt and receipt.get("kind") == "creator_profile_candidate":
            return "候选已生成，请核对表单后确认写入达人档案。"
        if receipt and receipt.get("kind") == "track_creator_membership_preview":
            return "赛道-博主关系预览已生成，请核对后确认写入。"
        if receipt and receipt.get("kind") == "creator_profile_written":
            return "达人档案已写入并确认完成。"
        if receipt and receipt.get("kind") == "deletion_preview":
            return "删除影响范围已生成。"

        public_lines: list[str] = []
        for raw_line in reply.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if not line or INTERNAL_RESULT_LINE.search(line) or INTERNAL_STORAGE_LINE.search(line):
                continue
            if any(token in lowered for token in FORBIDDEN_RESULT_TOKENS):
                continue
            if FORBIDDEN_RESULT_URL.search(line):
                continue
            if INTERNAL_RESULT_IDENTIFIER.search(line):
                continue
            public_lines.append(line)

        if public_lines:
            return "\n".join(public_lines)
        if public_status == "completed":
            return "任务已完成，可从对应业务页面查看结果。"
        if public_status == "needs_attention":
            return "任务需要补充信息或外部来源暂不可用，请检查输入与来源状态后重试。"
        return "任务未完成，请检查输入后重试；仍失败时由维护者查看受控审计记录。"

    def _project(self, task: Mapping[str, Any]) -> dict[str, Any]:
        invocation = task["invocation"]
        confirmation = dict(task.get("confirmation") or {})
        confirmation["decidedAt"] = confirmation.pop("decided_at", "")
        model_calls: list[dict[str, Any]] = []
        if self._tenant_model_gateway is not None and _requires_model_transport(
            str(invocation.get("capability_id") or ""),
            str(invocation.get("variant_id") or ""),
        ):
            model_calls = self._tenant_model_gateway.task_calls(
                str(task["tenant_id"]),
                str(task["task_id"]),
            )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "taskId": task["task_id"],
            "requestId": task.get("model_request_root") or "",
            "modelCalls": model_calls,
            "capabilityId": invocation["capability_id"],
            "capabilityPath": list(task["capability_path"]),
            "variantId": invocation["variant_id"],
            "params": dict(invocation["params"]),
            "confirmationReceipt": invocation.get("confirmation_receipt"),
            "status": task["status"],
            "terminal": task["status"] in TERMINAL_STATES,
            "progress": int(task.get("progress") or 0),
            "summary": task.get("summary") or "",
            "createdAt": task["created_at"],
            "updatedAt": task["updated_at"],
            "confirmation": confirmation,
            "result": task.get("result"),
            "error": task.get("error"),
            "eventCursor": int(task.get("event_cursor") or 0),
            # Settlement projection consumed by the Media Web task feed. A task
            # without recorded settlement facts reports its lifecycle status as
            # the stage and leaves binding/attempt/readback facts empty rather
            # than fabricating them.
            "settlementStage": task.get("settlement_stage") or task["status"],
            "accountBinding": task.get("account_binding"),
            "attempt": task.get("attempt"),
            "readbacks": task.get("readbacks"),
            "missingReadbacks": list(task.get("missing_readbacks") or []),
            "receipt": task.get("receipt"),
        }

    def _load_upload(self, upload_id: str, *, tenant_id: str) -> dict[str, Any]:
        tenant_id = _require_tenant_id(tenant_id)
        if not SAFE_ID.fullmatch(upload_id):
            raise MediaWebTaskError("upload_not_found", "未找到该上传文件。")
        path = self._tenant_dir(self.uploads_dir, tenant_id) / f"{upload_id}.json"
        if not path.exists():
            raise MediaWebTaskError("upload_not_found", "未找到该上传文件。")
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("tenant_id") != tenant_id:
            raise MediaWebTaskError("upload_not_found", "未找到该上传文件。")
        return item

    def _mark_upload_consumed(self, upload_id: str, *, tenant_id: str) -> None:
        item = self._load_upload(upload_id, tenant_id=tenant_id)
        item["status"] = "consumed"
        item["updated_at"] = _utc_now()
        _atomic_write_json(self._tenant_dir(self.uploads_dir, tenant_id) / f"{upload_id}.json", item)

    def _project_upload(self, item: Mapping[str, Any]) -> dict[str, Any]:
        # The Media Web upload contract (media_web_task.schema.json /
        # checkMaterialParsing.ts) is frozen to schemaVersion "3" with a
        # sha256-prefixed digest; storage keeps the bare digest.
        projection = {
            "schemaVersion": "3",
            "uploadId": item["upload_id"],
            "filename": item["filename"],
            "mimeType": item["mime_type"],
            "size": item["size"],
            "sha256": f"sha256:{item['sha256']}",
            "status": item["status"],
            "createdAt": item["created_at"],
        }
        parsing = item.get("parsing")
        if isinstance(parsing, Mapping):
            projection["parsing"] = {
                "status": str(parsing.get("status") or "pending"),
                "failureCode": str(parsing.get("failure_code") or ""),
                "nextAction": str(parsing.get("next_action") or ""),
            }
        return projection

    @contextmanager
    def _reservation_lease(self) -> Iterator[None]:
        self.reservation_lease_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.reservation_lease_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

    @contextmanager
    def _worker_lease(self, *, blocking: bool) -> Iterator[bool]:
        self.worker_lease_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.worker_lease_path.open("a+")
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            try:
                fcntl.flock(handle.fileno(), flags)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

    def _audit(self, tenant_id: str, action: str, target: str, result: str) -> None:
        tenant_id = _require_tenant_id(tenant_id)
        entry = {
            "schemaVersion": SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "action": action,
            "target": target,
            "source": "media_web",
            "result": result,
            "createdAt": _utc_now(),
        }
        audit_path = self.audit_dir / f"{_tenant_storage_key(tenant_id)}.jsonl"
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _recover_tasks(self) -> None:
        resumable: list[tuple[str, str]] = []
        with self._worker_lease(blocking=False) as acquired:
            if not acquired:
                return
            for task in self._iter_tasks():
                tenant_id = _require_tenant_id(str(task.get("tenant_id") or ""))
                if task.get("status") in TERMINAL_STATES or task.get("status") == "awaiting_confirmation":
                    continue
                canonical_started = bool(task.get("canonical_execution_started_at")) or task.get("status") in {
                    "generating",
                    "persisting",
                    "rendering",
                }
                if canonical_started:
                    task["error"] = {
                        "code": "recovery_requires_manual_review",
                        "message": "服务中断时任务已开始处理，为避免重复处理，未自动重新开始。",
                        "action": "请确认已生成的内容后，再决定是否创建新任务。",
                    }
                    self._transition(
                        task,
                        "pending_manual",
                        progress=100,
                        event_type="task.error",
                        message="任务在执行边界中断，已转人工核对且不会自动重放。",
                    )
                    self._audit(tenant_id, "task.recover", str(task["task_id"]), "pending_manual")
                    continue
                task["status"] = "queued"
                task["progress"] = 0
                self._append_event(task, "task.status", "服务恢复后任务已重新排队。")
                resumable.append((str(task["task_id"]), tenant_id))
        for task_id, tenant_id in resumable:
            self._submit(task_id, tenant_id)

    def cleanup_retention(self) -> dict[str, int]:
        now = self._clock()
        removed_tasks = 0
        deleted_uploads = 0
        with self._lock:
            for task in self._iter_tasks():
                tenant_id = _require_tenant_id(str(task.get("tenant_id") or ""))
                if task.get("status") not in TERMINAL_STATES:
                    continue
                age_from = _timestamp(task.get("updated_at"))
                if age_from is None or now - age_from < TASK_RETENTION_SECONDS:
                    continue
                task_id = str(task.get("task_id") or "")
                if not SAFE_ID.fullmatch(task_id):
                    continue
                self._audit(tenant_id, "task.retention_delete", task_id, "deleted")
                self._task_path(task_id, tenant_id=tenant_id).unlink(missing_ok=True)
                (self._tenant_dir(self.events_dir, tenant_id) / f"{task_id}.jsonl").unlink(missing_ok=True)
                removed_tasks += 1
            uploads_root = self.uploads_dir.resolve()
            for metadata_path in self.uploads_dir.glob("*/mwu_*.json"):
                try:
                    item = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if item.get("status") == "deleted":
                    continue
                tenant_id = _require_tenant_id(str(item.get("tenant_id") or ""))
                tenant_uploads_root = self._tenant_dir(self.uploads_dir, tenant_id).resolve()
                if metadata_path.parent.resolve() != tenant_uploads_root:
                    continue
                age_from = _timestamp(item.get("created_at"))
                if age_from is None or now - age_from < UPLOAD_RETENTION_SECONDS:
                    continue
                storage_path = str(item.get("storage_path") or "")
                if storage_path:
                    candidate = Path(storage_path).resolve()
                    if candidate.parent == tenant_uploads_root and uploads_root in candidate.parents:
                        candidate.unlink(missing_ok=True)
                item["status"] = "deleted"
                item["storage_path"] = ""
                item["deleted_at"] = _utc_now()
                item["updated_at"] = item["deleted_at"]
                _atomic_write_json(metadata_path, item)
                self._audit(tenant_id, "upload.retention_delete", str(item.get("upload_id") or ""), "deleted")
                deleted_uploads += 1
        return {"tasks": removed_tasks, "uploads": deleted_uploads}

    def _cleanup_loop(self) -> None:
        while not self._cleanup_stop.wait(CLEANUP_INTERVAL_SECONDS):
            try:
                self.cleanup_retention()
            except Exception:
                continue
