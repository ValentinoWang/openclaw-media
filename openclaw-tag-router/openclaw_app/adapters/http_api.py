from __future__ import annotations

import hashlib
import hmac
import importlib.util
import inspect
import ipaddress
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

LOGGER = logging.getLogger(__name__)


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("request body contains duplicate fields")
        payload[key] = value
    return payload


def _stage2_authentication_error(exc: Stage2ServerContextError) -> Stage2GatewayError:
    return Stage2GatewayError(exc.code, exc.message, status=exc.status)

from ..account import (
    AccountAuthService,
    AccountError,
    AccountContractError,
    AccountRegistrationService,
    AccountSession,
    MediaFeishuLoginService,
    OrganizationAuthIntentService,
    PersonalAuthService,
)
from ..account.workspace_resolution import WorkspaceResolver
if TYPE_CHECKING:
    from ..app import OpenClawApp
    from ..services.device_job_service import DeviceJobService
    from ..services.media_archive_service import MediaArchiveService
    from ..services.tenant_model_transport import TenantModelGateway
from ..services.guidance_plan import GuidancePlanError, GuidancePlanService
from ..services.device_job_errors import DeviceJobError
from ..services.media_web_tasks import MediaWebTaskError, MediaWebTaskService, TERMINAL_STATES
from ..services.stage1_writer_gate import WRITER_CLOSED_ERROR_CODE
from ..services.stage2_gateway import Stage2GatewayError
from ..services.stage2_runtime import Stage2RuntimeError, runtime_status as _stage2_runtime_status
from ..services.stage2_server_context import (
    Stage2ServerContextError,
    extract_session_token,
    stage2_request_context,
)
from ..services.stage1_organization_provisioning import ProvisioningError
from ..services.stage1_provisioning_runtime import (
    Stage1ProvisioningRuntime,
    deprovision_json,
    provision_run_json,
    provision_status_json,
)
from ..services.media_business.assets import AssetInternalError, AssetsError, AssetPreviewService, AssetsService
from ..services.media_business.document_resources import DocumentResourceService
from ..services.tenant_projection import ProjectionResponse, TenantProjectionError, TenantProjectionService
from ..services.tenant_activity_access import TenantActivityAccessError, TenantActivityAccessService
from ..services.resource_access import ResourceAccessService
from ..services.retail_admin import RetailAdminService
from ..services.retail_fulfillment import RetailFulfillmentService
from ..services.upstream_gateway_credentials import UpstreamCredentialError
from ..services.cloud_media_task_receiver import CloudMediaTaskReceiver, CloudMediaTaskReceiverError
from .audit_reason_header import AuditReasonHeaderError, decode_audit_reason_header
from .media_business_context import (
    AdminAuditInput,
    AdminPermissionRequiredError,
    CsrfRejectedError,
    CsrfAssessment,
    ExternalRequestAuthority,
    IdempotencyInput,
    If2RequestContext,
    RequestAuthenticationError,
    RequestAuthorizationError,
    RequestContextError,
    SessionPrincipal,
)
from .media_business_dispatcher import (
    CANONICAL_PREFIX,
    MEDIA_BUSINESS_ROUTE_BINDINGS,
    MediaBusinessDispatcher,
    RouteMatch,
    is_legacy_if2_business_request,
    resolve_media_business_operation,
)
from ..services.media_business.foundation import MediaBusinessError, TenantContext


_AUTH_ENV_KEYS = frozenset(
    {
        "OPENCLAW_ACCOUNT_DATABASE_URL",
        "OPENCLAW_ACCOUNT_SESSION_SECRET",
        "OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS",
        "OPENCLAW_BOT_CENTER_COOKIE_PATH",
        "OPENCLAW_BOT_CENTER_COOKIE_SECURE",
    }
)
SESSION_COOKIE_NAME = "openclaw_session"
_ENTRY_STATE_SCHEMA_VERSION = "media_auth_entry_state_v1"
_ENTRY_STATE_WORKSPACE_MODES = {
    "personal": "personal_web",
    "organization": "organization_lark",
}
_ENTRY_STATE_FALLBACKS = {
    "personal": "password",
    "organization": "feishu_oauth",
}
_NUMERIC_VERSION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+")
_R2_OPERATION_IDS = frozenset(
    {
        "archive_commit",
        "archive_list",
        "archive_detail",
        "archive_delete_plan",
        "archive_delete",
        "archive_readback",
    }
)


def if2_public_error(exc: RequestContextError | AuditReasonHeaderError) -> tuple[HTTPStatus, str, str]:
    """Keep IF2 implementation diagnostics out of creator-facing API responses."""
    if isinstance(exc, RequestAuthenticationError):
        return HTTPStatus.UNAUTHORIZED, "authentication_required", "请先登录后再继续操作。"
    if isinstance(exc, CsrfRejectedError):
        return HTTPStatus.FORBIDDEN, "csrf_rejected", "安全校验未通过，请刷新页面后重试。"
    if isinstance(exc, AdminPermissionRequiredError):
        return HTTPStatus.FORBIDDEN, "admin_required", "当前账号没有此操作权限。"
    if isinstance(exc, RequestAuthorizationError):
        return HTTPStatus.FORBIDDEN, "forbidden", "当前账号没有此操作权限。"
    return HTTPStatus.BAD_REQUEST, "invalid_request", "请求信息不完整或格式不正确，请检查后重试。"


def _first_contract_path(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    raise RuntimeError(f"media product contract is missing: {', '.join(map(str, paths))}")


@lru_cache(maxsize=1)
def _http_product_operations() -> Mapping[str, Mapping[str, Any]]:
    # parents[2] is the Router root; parents[3] is this repository's root,
    # which owns the checked-in `media-agent-cli/` client mirror. Deferred
    # import matches the lazy-loading of media_device_job_contract elsewhere
    # in this module (see _device_job_contract()).
    from ..services.media_device_job_contract import resolve_contract_path

    repository_root = Path(__file__).resolve().parents[3]
    path = resolve_contract_path(
        "OPENCLAW_MEDIA_GENERATED_CONTRACT",
        repository_root / "media-agent-cli/generated_product_contract.py",
    )
    if not path.is_file():
        raise RuntimeError(f"media product contract is missing: {path}")
    spec = importlib.util.spec_from_file_location("openclaw_http_product_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("media product contract cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = getattr(module, "OPERATIONS", None)
    if not isinstance(operations, Mapping):
        raise RuntimeError("media product contract operations are invalid")
    return operations


@lru_cache(maxsize=1)
def _http_frozen_contract() -> Mapping[str, Any]:
    repository_root = Path(__file__).resolve().parents[3]
    override = os.getenv("OPENCLAW_MEDIA_FROZEN_CONTRACT")
    path = _first_contract_path(*(
        (Path(override),)
        if override
        else (
            repository_root / "docs/ai-harness/openclaw-media-product-contract.json",
            Path("/home/ubuntu/docs/ai-harness/openclaw-media-product-contract.json"),
        )
    ))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("frozen media product contract is invalid")
    return value


def _resolve_product_operation(
    relative_path: str,
    method: str,
    *,
    archive: bool,
) -> tuple[str, dict[str, str]] | None:
    for operation_id, operation in _http_product_operations().items():
        if (operation_id in _R2_OPERATION_IDS) != archive:
            continue
        if str(operation["method"]).upper() != method.upper():
            continue
        path = str(operation["relative_path"])
        cursor = 0
        pieces: list[str] = []
        for match in re.finditer(r"\{([a-z_]+)\}", path):
            pieces.append(re.escape(path[cursor : match.start()]))
            pieces.append(r"(?P<" + match.group(1) + r">[A-Za-z0-9_-]+)")
            cursor = match.end()
        pieces.append(re.escape(path[cursor:]))
        matched = re.fullmatch("".join(pieces), relative_path)
        if matched is not None:
            return str(operation_id), matched.groupdict()
    return None


@lru_cache(maxsize=1)
def _device_job_contract() -> Any:
    from ..services import media_device_job_contract

    return media_device_job_contract


@lru_cache(maxsize=1)
def _media_archive_contract() -> Any:
    from ..services import media_archive_service

    return media_archive_service


@dataclass(frozen=True)
class HttpAuthorityConfig:
    public_origin: str
    trusted_proxy_cidrs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        origin = urlsplit(self.public_origin)
        if origin.scheme not in {"http", "https"} or not origin.hostname or origin.path not in {"", "/"}:
            raise ValueError("public origin must be an absolute HTTP origin")
        if origin.query or origin.fragment or origin.username or origin.password:
            raise ValueError("public origin must not contain credentials, query, or fragment")
        for value in self.trusted_proxy_cidrs:
            ipaddress.ip_network(value, strict=False)

    @property
    def origin_tuple(self) -> tuple[str, str, int]:
        parsed = urlsplit(self.public_origin)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, str(parsed.hostname).lower(), port

    def peer_is_trusted(self, peer_ip: str) -> bool:
        address = ipaddress.ip_address(peer_ip)
        return any(address in ipaddress.ip_network(value, strict=False) for value in self.trusted_proxy_cidrs)


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _authority_for_bound_server(
    host: str,
    requested_port: int,
    bound_port: int,
    authority_config: HttpAuthorityConfig | None,
) -> tuple[HttpAuthorityConfig | None, HttpAuthorityConfig | None]:
    if authority_config is None or requested_port != 0 or not _is_loopback_host(host):
        return authority_config, None
    parsed = urlsplit(authority_config.public_origin)
    if parsed.port is not None or parsed.hostname is None or not _is_loopback_host(parsed.hostname):
        return authority_config, None
    return (
        HttpAuthorityConfig(
            urlunsplit((parsed.scheme, f"{parsed.netloc}:{bound_port}", "", "", "")),
            authority_config.trusted_proxy_cidrs,
        ),
        authority_config,
    )


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _coerce_if2_value(name: str, value: Any) -> Any:
    if name in {"page", "page_size", "limit", "revision", "expected_revision", "code_count", "count"}:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RequestContextError(f"invalid integer IF2 input: {name}") from exc
    return value


def _operation_map(service: str, operation_ids: set[str]) -> dict[str, str]:
    return {operation_id: service for operation_id in operation_ids}


_IF2_OPERATION_SERVICE = {
    **_operation_map("overview", {"getDashboard", "listContentProjects", "listProjectArtifacts", "createProjectSummary"}),
    **_operation_map("tracks", {"listTracks", "getTrack", "listCreators", "getCreator", "listTrackRelationships", "updateTrackRelationshipStatus", "listOwnedAccounts", "getOwnedAccount", "getAccountTrackStrategy", "getAccountMonitor", "updateAccountMonitor", "pollAccountMonitor"}),
    **_operation_map("assets", {"listAssets", "getAsset"}),
    **_operation_map("decisions", {"listDecisions", "getDecision", "listDecisionSignals", "confirmDecision"}),
    **_operation_map("runs", {"listRuns", "getRun", "getRunSources", "getRunDecisions", "getRunOutputs", "listBusinessOpportunities", "createArtifactRevision"}),
    **_operation_map("publishing", {"listPublishingPackages", "getPublishingPackage", "updatePublishingChecks", "createPublishedPost", "getPublishedPost", "getResourceDocxLink"}),
    **_operation_map("reviews", {"listReviews", "createReview", "getReviewsSummary", "listContentMetrics", "listAccountMetrics", "createMetricImport", "confirmReview"}),
    **_operation_map("usage_billing", {"getBillingBalance", "listBillingBalancePacks", "listBillingUsage", "getBillingUsageSummary", "redeemBillingCode"}),
    **_operation_map("invites", {"getAffiliateProfile", "listInvitees"}),
    **_operation_map("admin_overview", {"getAdminDashboard"}),
    **_operation_map("admin_access", {"listAdminAffiliateUsers", "updateAdminAffiliateUser", "listAdminAdmissionBatches", "createAdminAdmissionBatch", "disableAdminAdmissionBatch", "getAdminRegistrationPolicy", "updateAdminRegistrationPolicy", "revokeAdminUserSessions"}),
    **_operation_map("admin_tenants", {"listAdminTenants", "getAdminTenant", "listAdminTenantRuns"}),
    **_operation_map("admin_billing", {"getAdminBillingSummary", "createAdminProductMapping", "createAdminBillingGrant", "createAdminRedemptionBatch", "recoverAdminFulfillment", "refundAdminFulfillment"}),
    **_operation_map("admin_upstreams", {"getAdminUpstreams", "reconcileAdminBillingOperation", "rotateAdminUpstreamCredential", "revokeAdminUpstreamCredential"}),
    **_operation_map("admin_platform_cookies", {"getAdminPlatformCookies"}),
    **_operation_map("documents", {"getDocumentBody", "saveDocumentDraft", "getDocumentRevision", "createDocumentExport", "getDocumentExport", "getDocumentExportDownload", "listArtifactSyncBatches"}),
}
_IF2_METHOD_OVERRIDES = {
    "getAdminDashboard": "dashboard",
    "listArtifactSyncBatches": "list_sync_batches",
}
_IF2_SPECIAL_OPERATIONS = {
    "getMediaSession", "listMediaCapabilities", "matchMediaCapability", "createMediaUpload",
    "listMediaTasks", "createMediaTask", "getMediaTask", "listMediaTaskEvents",
    "cancelMediaTask", "confirmMediaTask", "getAssetPreview", "getDocumentResource",
}
if set(_IF2_OPERATION_SERVICE) | _IF2_SPECIAL_OPERATIONS != {
    route.operation_id for route in MEDIA_BUSINESS_ROUTE_BINDINGS
}:
    raise RuntimeError("IF2 HTTP composition does not cover exactly the accepted 87 operations")


def _parse_numeric_version(value: Any) -> tuple[int, ...] | None:
    if not isinstance(value, str) or _NUMERIC_VERSION.fullmatch(value) is None:
        return None
    return tuple(int(part) for part in value.split("."))


def _version_at_least(value: Any, minimum: str) -> bool:
    parsed_value = _parse_numeric_version(value)
    parsed_minimum = _parse_numeric_version(minimum)
    if parsed_value is None or parsed_minimum is None:
        return False
    width = max(len(parsed_value), len(parsed_minimum))
    return parsed_value + (0,) * (width - len(parsed_value)) >= parsed_minimum + (0,) * (width - len(parsed_minimum))


def _version_less_than(value: Any, maximum: str) -> bool:
    parsed_value = _parse_numeric_version(value)
    parsed_maximum = _parse_numeric_version(maximum)
    if parsed_value is None or parsed_maximum is None:
        return False
    width = max(len(parsed_value), len(parsed_maximum))
    return parsed_value + (0,) * (width - len(parsed_value)) < parsed_maximum + (0,) * (width - len(parsed_maximum))


def _release_compatibility_metadata() -> tuple[str, str, list[str]]:
    frozen = _http_frozen_contract()
    minimums = [str(item["min_cli_version"]) for item in frozen["pipeline_catalog"]]
    if not minimums or any(_parse_numeric_version(item) is None for item in minimums):
        raise RuntimeError("frozen pipeline catalog contains an invalid min_cli_version")
    minimum_cli = max(minimums, key=lambda item: _parse_numeric_version(item) or ())
    release = frozen["release"]
    supported_python = str(release["python_requires"])
    supported_platforms = [str(platform) for platform in release["platforms"]]
    return minimum_cli, supported_python, supported_platforms


def _python_version_compatible(value: Any, requirement: str) -> bool:
    match = re.fullmatch(r">=([0-9]+(?:\.[0-9]+)+),<([0-9]+(?:\.[0-9]+)+)", requirement)
    if match is None:
        return False
    minimum, maximum = match.groups()
    return _version_at_least(value, minimum) and _version_less_than(value, maximum)


class CapabilityMatcher(Protocol):
    def match(self, request: Mapping[str, Any]) -> dict[str, Any]: ...


class CapabilityMatcherFailure(Exception):
    """The public matcher contract exposes only a stable code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RateLimitRule:
    requests: int
    window_seconds: int


class SlidingWindowRateLimiter:
    def __init__(
        self,
        rules: Mapping[str, RateLimitRule] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rules = dict(
            rules
            or {
                "auth_login": RateLimitRule(requests=5, window_seconds=60),
                "auth_feishu_start": RateLimitRule(requests=10, window_seconds=60),
                "auth_feishu_status": RateLimitRule(requests=60, window_seconds=60),
                "auth_register": RateLimitRule(requests=5, window_seconds=60),
                "media_mutation": RateLimitRule(requests=20, window_seconds=60),
            }
        )
        self._clock = clock
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def consume(self, bucket: str, key: str) -> tuple[bool, int]:
        rule = self._rules[bucket]
        now = self._clock()
        cutoff = now - rule.window_seconds
        with self._lock:
            events = self._events[(bucket, key)]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= rule.requests:
                retry_after = max(1, int(rule.window_seconds - (now - events[0]) + 0.999))
                return False, retry_after
            events.append(now)
            return True, 0


class MutationIdempotencyBindings:
    """Bounded process-local guard against reusing a mutation key with another payload."""

    def __init__(
        self,
        *,
        maximum_entries: int = 10_000,
        ttl_seconds: int = 24 * 60 * 60,
        clock: Callable[[], float] = time.monotonic,
        fingerprint_key: bytes | None = None,
    ) -> None:
        if maximum_entries <= 0 or ttl_seconds <= 0:
            raise ValueError("mutation binding limits must be positive")
        self._maximum_entries = maximum_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._fingerprint_key = fingerprint_key or os.urandom(32)
        if len(self._fingerprint_key) < 32:
            raise ValueError("mutation fingerprint key must be at least 32 bytes")
        self._bindings: dict[tuple[str, str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def bind(self, actor_scope: str, operation_scope: str, key: str, payload: Mapping[str, Any]) -> bool:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hmac.new(self._fingerprint_key, canonical, hashlib.sha256).hexdigest()
        binding_key = (actor_scope, operation_scope, key)
        now = self._clock()
        with self._lock:
            cutoff = now - self._ttl_seconds
            expired = [item for item, (_, created_at) in self._bindings.items() if created_at <= cutoff]
            for item in expired:
                self._bindings.pop(item, None)
            existing = self._bindings.get(binding_key)
            if existing is not None:
                return hmac.compare_digest(existing[0], fingerprint)
            if len(self._bindings) >= self._maximum_entries:
                oldest = min(self._bindings, key=lambda item: self._bindings[item][1])
                self._bindings.pop(oldest, None)
            self._bindings[binding_key] = (fingerprint, now)
            return True


def load_auth_environment(path: str | Path | None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Load only declared auth settings, with process environment taking precedence."""

    values: dict[str, str] = {}
    if path:
        env_path = Path(path)
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as exc:
            raise ValueError(f"auth environment file does not exist: {env_path}") from exc
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            key, separator, value = line.partition("=")
            if not separator or key not in _AUTH_ENV_KEYS:
                raise ValueError("auth environment file contains an unsupported setting")
            if value[:1] in {"'", '"'}:
                quote = value[0]
                if len(value) < 2 or value[-1] != quote:
                    raise ValueError("auth environment file contains an unterminated value")
                value = value[1:-1]
            if key in _AUTH_ENV_KEYS:
                values[key] = value
    source = os.environ if environment is None else environment
    for key in _AUTH_ENV_KEYS:
        value = source.get(key)
        if value is not None:
            values[key] = value
    return values


@dataclass(frozen=True)
class AuthConfig:
    session_secret: bytes
    session_ttl_seconds: int = 28 * 24 * 60 * 60
    cookie_path: str = "/openclaw/"
    cookie_secure: bool = True

    @property
    def cookie_name(self) -> str:
        return SESSION_COOKIE_NAME

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "AuthConfig":
        required = ("OPENCLAW_ACCOUNT_DATABASE_URL", "OPENCLAW_ACCOUNT_SESSION_SECRET")
        missing = [key for key in required if not environment.get(key)]
        if missing:
            raise ValueError("auth environment is missing required credentials")
        session_secret = environment["OPENCLAW_ACCOUNT_SESSION_SECRET"].encode("utf-8")
        if len(session_secret) < 32:
            raise ValueError("auth session secret must be at least 32 bytes")
        ttl_value = environment.get("OPENCLAW_ACCOUNT_SESSION_TTL_SECONDS", str(28 * 24 * 60 * 60))
        try:
            session_ttl_seconds = int(ttl_value)
        except ValueError as exc:
            raise ValueError("auth session ttl must be an integer") from exc
        if not 60 <= session_ttl_seconds <= 28 * 24 * 60 * 60:
            raise ValueError("auth session ttl must be between 60 seconds and twenty-eight days")
        cookie_path = environment.get("OPENCLAW_BOT_CENTER_COOKIE_PATH", "/openclaw/")
        if not cookie_path.startswith("/") or any(character in cookie_path for character in "\r\n;"):
            raise ValueError("auth cookie path is invalid")
        cookie_secure = _parse_boolean(environment.get("OPENCLAW_BOT_CENTER_COOKIE_SECURE", "true"))
        return cls(
            session_secret=session_secret,
            session_ttl_seconds=session_ttl_seconds,
            cookie_path=cookie_path,
            cookie_secure=cookie_secure,
        )


def _parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError("auth cookie secure value must be boolean")


def _mask_entry_identity(value: Any) -> str:
    identity = str(value or "").strip()
    if "@" in identity:
        local, domain = identity.split("@", 1)
        if local and domain:
            return f"{local[0]}***@{domain}"
    return f"{identity[0]}***" if identity else "***"


class OpenClawHttpHandler(BaseHTTPRequestHandler):
    app: OpenClawApp | None = None
    auth_config: AuthConfig | None = None
    account_auth: AccountAuthService | None = None
    account_registration: AccountRegistrationService | None = None
    personal_auth: PersonalAuthService | None = None
    organization_auth_intent: OrganizationAuthIntentService | None = None
    media_feishu_login: MediaFeishuLoginService | None = None
    matcher: CapabilityMatcher | None = None
    guidance_plan_service: GuidancePlanService | None = None
    media_web_tasks: MediaWebTaskService | None = None
    rate_limiter: SlidingWindowRateLimiter | None = None
    tenant_model_gateway: TenantModelGateway | None = None
    retail_admin: RetailAdminService | None = None
    retail_fulfillment: RetailFulfillmentService | None = None
    device_job_service: DeviceJobService | None = None
    media_archive_service: MediaArchiveService | None = None
    tenant_projections: TenantProjectionService | None = None
    tenant_activity: TenantActivityAccessService | None = None
    assets_service: AssetsService | None = None
    asset_preview_service: AssetPreviewService | None = None
    document_resource_service: DocumentResourceService | None = None
    resource_access: ResourceAccessService | None = None
    media_business_dispatcher: MediaBusinessDispatcher | None = None
    media_business_services: Mapping[str, Any] | None = None
    authority_config: HttpAuthorityConfig | None = None
    ephemeral_default_authority: HttpAuthorityConfig | None = None
    mutation_bindings: MutationIdempotencyBindings | None = None
    workspace_resolver: WorkspaceResolver | None = None
    stage1_provisioning: Stage1ProvisioningRuntime | None = None

    def _send_json(
        self,
        status: HTTPStatus,
        payload: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if headers:
                for name, value in headers.items():
                    self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Polling clients may close before headers flush or while the body is written.
            return

    def _send_empty(self, status: HTTPStatus, *, headers: Mapping[str, str] | None = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            if headers:
                for name, value in headers.items():
                    self.send_header(name, value)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_binary(
        self,
        status: HTTPStatus,
        body: bytes,
        *,
        content_type: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if headers:
                for name, value in headers.items():
                    self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_api_error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if details:
            error["details"] = dict(details)
        response_headers = dict(headers or {})
        correlation_id = getattr(self, "_correlation_id", None)
        if callable(correlation_id):
            response_headers.setdefault("X-Request-ID", correlation_id())
        self._send_json(
            status,
            {"ok": False, "error": error},
            headers=response_headers or None,
        )

    def _correlation_id(self) -> str:
        request_id = getattr(self, "_request_id", None)
        if request_id is None:
            request_id = uuid.uuid4().hex
            self._request_id = request_id
        return request_id

    def _send_r1_json(self, operation_id: str, status: HTTPStatus, payload: Any) -> None:
        _device_job_contract().validate_r1_response(operation_id, payload)
        self._send_json(status, payload)

    def _request_path(self) -> str:
        return urlsplit(self.path).path

    def _dispatch_media_business(self, method: str) -> bool:
        request_target = self.path
        parsed_target = urlsplit(request_target)
        if method == "GET" and parsed_target.path == "/media/api/session":
            request_target = urlunsplit(("", "", "/openclaw/media/api/session", parsed_target.query, ""))
        path = urlsplit(request_target).path
        if method == "GET" and (
            path == "/media/api/assets"
            or re.fullmatch(r"/media/api/assets/[A-Za-z0-9_-]{8,160}(?:/preview)?", path)
        ):
            return False
        if is_legacy_if2_business_request(method, request_target):
            self._send_api_error(HTTPStatus.NOT_FOUND, "not_found", "未找到该接口。")
            return True
        match = resolve_media_business_operation(method, request_target)
        if match is None:
            return False
        if self.media_business_dispatcher is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "media_business_unavailable",
                "Media 业务服务暂时不可用。",
            )
            return True
        try:
            maximum_bytes = match.route.body_limit_bytes
            if method != "GET" and maximum_bytes is None:
                raise RuntimeError(f"IF2 mutation body limit is missing: {match.operation_id}")
            body = self._read_json_body(maximum_bytes=maximum_bytes) if method != "GET" else None
            context = self._build_if2_request_context(match, body, request_target)
            _handled, _response = self.media_business_dispatcher.dispatch(
                method,
                request_target,
                (self, context, body),
            )
        except (RequestContextError, AuditReasonHeaderError) as exc:
            status, code, message = if2_public_error(exc)
            self._send_api_error(status, code, message)
        except MediaBusinessError as exc:
            status = int(getattr(exc, "status", 400))
            details = None
            block_ids = getattr(exc, "block_ids", ())
            if status == HTTPStatus.UNPROCESSABLE_ENTITY and block_ids:
                details = {"blockIds": list(block_ids)}
            self._send_api_error(
                HTTPStatus(status),
                exc.code,
                getattr(exc, "message", str(exc)),
                details=details,
            )
        except MediaWebTaskError as exc:
            self._send_api_error(
                HTTPStatus(exc.status),
                exc.code,
                exc.message,
                details=exc.details,
            )
        except AccountError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except Exception as exc:
            status = getattr(exc, "status", None)
            code = getattr(exc, "code", None)
            message = getattr(exc, "message", getattr(exc, "detail", None))
            if (
                isinstance(status, int)
                and status in match.route.allowed_statuses
                and isinstance(code, str)
                and code
                and isinstance(message, str)
                and message
            ):
                self._send_api_error(HTTPStatus(status), code, message)
            else:
                raise
        return True

    def _dispatch_legacy_support(self, method: str) -> bool:
        if self.media_business_services:
            return False
        path = self._request_path()
        if method == "GET":
            handlers: dict[str, Callable[[], None]] = {
                "/openclaw/media/api/account/affiliate": self._handle_account_affiliate,
                "/openclaw/media/api/account/invitees": self._handle_account_invitees,
                "/openclaw/media/api/admin/registration-policy": self._handle_admin_registration_policy_get,
                "/openclaw/media/api/admin/admission-batches": self._handle_admin_admission_batches_get,
                "/media/api/admin/registration-policy": self._handle_admin_registration_policy_get,
                "/media/api/admin/admission-batches": self._handle_admin_admission_batches_get,
                "/openclaw/media/api/admin/affiliate-users": self._handle_admin_affiliate_users_get,
                "/openclaw/media/api/billing/plans": self._handle_billing_plans,
                "/openclaw/media/api/billing/balance": self._handle_billing_balance,
                "/openclaw/media/api/billing/usage": self._handle_billing_usage,
                "/openclaw/media/api/admin/billing/reconciliation": self._handle_admin_billing_reconciliation,
                "/openclaw/media/api/admin/billing/summary": self._handle_admin_billing_summary,
                "/openclaw/media/api/admin/upstream-credential/health": self._handle_admin_upstream_credential_health,
            }
            handler = handlers.get(path)
            if handler is None:
                return False
            handler()
            return True

        exact_handlers: dict[tuple[str, str], Callable[[Mapping[str, Any]], None]] = {
            ("POST", "/openclaw/media/api/billing/redeem"): self._handle_billing_redeem,
            ("POST", "/openclaw/media/api/admin/billing/redemption-batches"): self._handle_admin_redemption_batch_create,
            ("POST", "/openclaw/media/api/admin/billing/product-mappings"): self._handle_admin_product_mapping_create,
            ("POST", "/openclaw/media/api/admin/billing/grants"): self._handle_admin_grant_create,
            ("POST", "/openclaw/media/api/admin/upstream-credential/rotate"): self._handle_admin_upstream_credential_rotate,
            ("POST", "/openclaw/media/api/admin/upstream-credential/revoke"): self._handle_admin_upstream_credential_revoke,
            ("POST", "/openclaw/media/api/admin/admission-batches"): self._handle_admin_admission_batch_create,
            ("POST", "/media/api/admin/admission-batches"): self._handle_admin_admission_batch_create,
            ("PUT", "/openclaw/media/api/admin/registration-policy"): self._handle_admin_registration_policy_update,
            ("PUT", "/media/api/admin/registration-policy"): self._handle_admin_registration_policy_update,
        }
        exact_handler = exact_handlers.get((method, path))
        if exact_handler is not None:
            exact_handler(self._read_json_body(maximum_bytes=64 * 1024))
            return True

        if method == "POST":
            match = re.fullmatch(
                r"/openclaw/media/api/admin/billing/reconciliation/([A-Za-z0-9_-]+)",
                path,
            )
            if match is not None:
                self._handle_admin_billing_reconcile(
                    match.group(1), self._read_json_body(maximum_bytes=64 * 1024)
                )
                return True
            match = re.fullmatch(
                r"/openclaw/media/api/admin/billing/fulfillments/([A-Za-z0-9_-]+)/(recover|refund)",
                path,
            )
            if match is not None:
                self._handle_admin_fulfillment_action(
                    match.group(1),
                    match.group(2),
                    self._read_json_body(maximum_bytes=64 * 1024),
                )
                return True
            match = re.fullmatch(
                r"/openclaw/media/api/admin/admission-batches/([0-9a-fA-F-]{36})/disable",
                path,
            )
            if match is not None:
                self._handle_admin_admission_batch_disable(
                    uuid.UUID(match.group(1)),
                    self._read_json_body(maximum_bytes=64 * 1024),
                )
                return True
            match = re.fullmatch(
                r"/openclaw/media/api/admin/users/([0-9a-fA-F-]{36})/sessions/revoke-all",
                path,
            )
            if match is not None:
                self._handle_admin_session_revoke_all(
                    uuid.UUID(match.group(1)),
                    self._read_json_body(maximum_bytes=64 * 1024),
                )
                return True
        if method == "PUT":
            match = re.fullmatch(
                r"/openclaw/media/api/admin/affiliate-users/([0-9a-fA-F-]{36})",
                path,
            )
            if match is not None:
                self._handle_admin_affiliate_profile_update(
                    uuid.UUID(match.group(1)),
                    self._read_json_body(maximum_bytes=64 * 1024),
                )
                return True
        return False

    def _external_request_authority(self) -> ExternalRequestAuthority:
        if self.authority_config is None:
            raise RequestContextError("external request authority is not configured")
        peer_ip = str(self.client_address[0])
        scheme, host, port = self.authority_config.origin_tuple
        trusted = self.authority_config.peer_is_trusted(peer_ip)
        client_ip = peer_ip
        if trusted:
            forwarded_for = self.headers.get("X-Forwarded-For", "").strip()
            if forwarded_for:
                if "," in forwarded_for:
                    raise RequestContextError("forwarded client address chain is ambiguous")
                client_ip = str(ipaddress.ip_address(forwarded_for))
            forwarded_proto = self.headers.get("X-Forwarded-Proto", "").strip().lower()
            forwarded_host = self.headers.get("X-Forwarded-Host", "").strip().lower()
            expected_hosts = {host if port in {80, 443} else f"{host}:{port}"}
            expected_schemes = {scheme}
            fallback = self.ephemeral_default_authority
            if fallback is not None:
                # An ephemeral loopback bind rewrites the effective origin port;
                # a proxy forwarding the configured public origin stays valid.
                fallback_scheme, fallback_host, fallback_port = fallback.origin_tuple
                expected_schemes.add(fallback_scheme)
                expected_hosts.add(
                    fallback_host
                    if fallback_port in {80, 443}
                    else f"{fallback_host}:{fallback_port}"
                )
            if forwarded_proto and forwarded_proto not in expected_schemes:
                raise RequestContextError("forwarded scheme does not match the public origin")
            if forwarded_host and forwarded_host not in expected_hosts:
                raise RequestContextError("forwarded host does not match the public origin")
        return ExternalRequestAuthority(peer_ip, client_ip, scheme, host, port, trusted)

    def _origin_matches_authority(self, origin: Any, authority: ExternalRequestAuthority) -> bool:
        if origin.scheme not in {"http", "https"} or origin.hostname is None:
            return False
        origin_port = origin.port or (443 if origin.scheme == "https" else 80)
        if (
            hmac.compare_digest(origin.scheme, authority.scheme)
            and hmac.compare_digest(origin.hostname.lower(), authority.host)
            and origin_port == authority.port
        ):
            return True
        fallback = self.ephemeral_default_authority
        if fallback is None:
            return False
        fallback_scheme, fallback_host, fallback_port = fallback.origin_tuple
        return (
            hmac.compare_digest(origin.scheme, fallback_scheme)
            and hmac.compare_digest(origin.hostname.lower(), fallback_host)
            and origin_port == fallback_port
        )

    def _build_if2_request_context(
        self,
        match: RouteMatch,
        body: Mapping[str, Any] | None,
        request_target: str,
    ) -> If2RequestContext:
        resolved = self._resolved_session()
        if resolved is None:
            raise RequestAuthenticationError("authenticated IF2 session is required")
        token, session = resolved
        authority = self._external_request_authority()
        workspace_resolution = None
        if self.workspace_resolver is not None:
            workspace_resolution = self.workspace_resolver.resolve(
                session,
                authenticated_token=token,
            )
            if workspace_resolution.resolution_state != "RESOLVED":
                if workspace_resolution.failure_code in {
                    "internal_error",
                    "account_database_unavailable",
                }:
                    raise AccountContractError(
                        "account_database_unavailable",
                        "工作区解析服务暂时不可用。",
                    )
                if workspace_resolution.resolution_state == "INVALID_SESSION":
                    raise RequestAuthenticationError("workspace session is no longer valid")
                raise RequestAuthorizationError("workspace is not eligible for this request")
        resolved_principal = (
            workspace_resolution.principal
            if workspace_resolution is not None
            else None
        )
        if workspace_resolution is not None and resolved_principal is None:
            raise RequestAuthenticationError("workspace resolution returned no principal")
        fallback_public_id = str(getattr(session, "user_public_id", session.user_id))
        fallback_mode = getattr(session, "workspace_mode", "personal_web")
        principal = (
            SessionPrincipal(
                session_id=session.session_id,
                user_id=session.user_id,
                tenant_id=session.tenant_id,
                user_public_id=fallback_public_id,
                role=session.role,  # type: ignore[arg-type]
                is_maintainer=session.is_maintainer,
                expires_at=session.expires_at,
                workspace_mode=fallback_mode,
                body_authority=getattr(
                    session,
                    "body_authority",
                    "internal" if fallback_mode == "personal_web" else "lark",
                ),
                member_role=getattr(session, "member_role", "owner"),
                session_token_hash=hashlib.sha256(token.encode("ascii")).digest(),
                schema_version="media-stage1-shared-v1",
                principal_id=fallback_public_id,
                account_status=getattr(session, "account_status", "ACTIVE"),
                workspace_intent=fallback_mode,
                personal_workspace_id=getattr(session, "personal_workspace_id", None),
                tenant_membership_ids=tuple(getattr(session, "tenant_membership_ids", ())),
                active_binding_ids=tuple(getattr(session, "active_binding_ids", ())),
                identity_link_receipt_ids=tuple(getattr(session, "identity_link_receipt_ids", ())),
                authenticated_at=getattr(session, "authenticated_at", None),
                session_issued_at=getattr(session, "session_issued_at", None),
            )
            if resolved_principal is None
            else resolved_principal
        )
        route = match.route.context_route
        origin_tuple: tuple[str, str, int] | None = None
        same_origin = False
        token_valid = False
        if route.mutation:
            supplied_origin = urlsplit(self.headers.get("Origin", ""))
            if supplied_origin.scheme in {"http", "https"} and supplied_origin.hostname:
                origin_tuple = (
                    supplied_origin.scheme,
                    supplied_origin.hostname.lower(),
                    supplied_origin.port or (443 if supplied_origin.scheme == "https" else 80),
                )
            same_origin = self._origin_matches_authority(supplied_origin, authority)
            supplied_csrf = self.headers.get("X-OpenClaw-CSRF", "")
            token_valid = bool(self.account_auth and self.account_auth.verify_csrf(token, supplied_csrf))
        if self.account_auth is None:
            raise RequestAuthenticationError("account authentication is not configured")
        csrf = CsrfAssessment(
            route.mutation,
            origin_tuple,
            same_origin,
            token_valid,
            self.account_auth.csrf_token(token),
        )

        request_path = urlsplit(request_target).path
        query = parse_qs(urlsplit(request_target).query, keep_blank_values=True)
        canonical_query = tuple(sorted((key, tuple(values)) for key, values in query.items()))
        canonical_body = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        path_identity = json.dumps(
            [route.method, request_path, canonical_query],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        idempotency = None
        if route.mutation:
            key = self.headers.get("Idempotency-Key", "").strip()
            scope_kind = "admin_actor" if route.permission.startswith("admin-") else "tenant"
            scope_id = session.user_id if scope_kind == "admin_actor" else session.tenant_id
            idempotency = IdempotencyInput(
                key,
                scope_kind,  # type: ignore[arg-type]
                scope_id,
                hashlib.sha256(path_identity).digest(),
                hashlib.sha256(canonical_body).digest(),
            )
        expected_revision = body.get("expectedRevision") if body else None
        admin_audit = None
        if route.permission == "admin-cross-tenant-read":
            target = match.path_parameters.get("publicTenantId", "")
            admin_audit = AdminAuditInput(
                decode_audit_reason_header(self.headers.get("X-Audit-Reason")),
                target,
                None,
            )
        return If2RequestContext.build(
            request_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc),
            route=route,
            canonical_path=request_path,
            path_parameters=tuple(sorted(match.path_parameters.items())),
            query_parameters=canonical_query,
            headers=tuple(sorted((name.lower(), value) for name, value in self.headers.items())),
            authority=authority,
            principal=principal,
            csrf=csrf,
            idempotency=idempotency,
            expected_revision=expected_revision,
            admin_audit=admin_audit,
            body=body,
            workspace_resolution=workspace_resolution,
        )

    def _execute_media_business(
        self,
        match: RouteMatch,
        context: If2RequestContext,
        body: Mapping[str, Any] | None,
    ) -> None:
        operation = match.operation_id
        if operation == "getMediaSession":
            self._handle_media_session(context)
            return
        if operation == "listMediaCapabilities":
            self._handle_media_capabilities()
            return
        if operation == "matchMediaCapability":
            self._handle_capability_match(context, body or {})
            return
        if operation == "createMediaUpload":
            self._execute_media_upload(context, body or {})
            return
        if operation in {
            "listMediaTasks", "createMediaTask", "getMediaTask", "listMediaTaskEvents",
            "cancelMediaTask", "confirmMediaTask",
        }:
            self._execute_media_task_operation(operation, match, context, body or {})
            return
        if operation == "getAssetPreview":
            self._handle_tenant_asset_preview(match.path_parameters.get("publicAssetId", ""))
            return
        if operation == "getDocumentResource":
            self._handle_document_resource(context, match.path_parameters.get("publicResourceId", ""))
            return
        service_key = _IF2_OPERATION_SERVICE.get(operation)
        service = (self.media_business_services or {}).get(service_key or "")
        if service is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "media_business_unavailable", "Media 业务服务暂时不可用。")
            return
        method_name = _IF2_METHOD_OVERRIDES.get(operation, _camel_to_snake(operation))
        method = getattr(service, method_name, None)
        if method is None or not callable(method):
            raise RuntimeError(f"IF2 service method is missing: {operation}")
        if operation in {"updateAccountMonitor", "pollAccountMonitor"}:
            key = self._require_idempotency_key()
            if key is None:
                return
            if not self._bind_mutation_payload(
                str(context.principal.tenant_id),
                f"{operation}:{match.path_parameters.get('publicAccountId', '')}",
                key,
                body or {},
            ):
                return
        result = self._invoke_if2_service(method, context, match, body or {})
        success = sorted(status for status in context.route.allowed_statuses if 200 <= status < 300)
        if not success:
            raise RuntimeError(f"IF2 route has no success status: {operation}")
        self._send_json(HTTPStatus(success[0]), result)

    def _invoke_if2_service(
        self,
        method: Callable[..., Any],
        context: If2RequestContext,
        match: RouteMatch,
        body: Mapping[str, Any],
    ) -> Any:
        path_values = {_camel_to_snake(key): value for key, value in match.path_parameters.items()}
        query_values = {
            _camel_to_snake(key): values[0] if len(values) == 1 else list(values)
            for key, values in context.query_parameters
        }
        body_values = {_camel_to_snake(key): value for key, value in body.items()}
        tenant_context = TenantContext(
            str(context.principal.tenant_id),
            context.principal.user_public_id,
            context.principal.role == "admin",
            context.admin_audit.reason if context.admin_audit else None,
        )
        call_context: Any = context.principal if context.route.permission.startswith("admin-") else tenant_context
        kwargs: dict[str, Any] = {}
        for name, parameter in inspect.signature(method).parameters.items():
            if parameter.kind in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }:
                continue
            if name == "context":
                kwargs[name] = call_context
            elif name in path_values:
                kwargs[name] = _coerce_if2_value(name, path_values[name])
            elif name == "idempotency_key" and context.idempotency is not None:
                kwargs[name] = context.idempotency.key
            elif name == "audit_reason" and context.admin_audit is not None:
                kwargs[name] = context.admin_audit.reason
            elif name in {"request", "payload"}:
                kwargs[name] = body
            elif name in body_values:
                kwargs[name] = body_values[name]
            elif name in query_values:
                kwargs[name] = _coerce_if2_value(name, query_values[name])
            elif parameter.default is inspect.Parameter.empty:
                raise RequestContextError(f"missing IF2 input: {name}")
        return method(**kwargs)

    def _execute_media_upload(self, context: If2RequestContext, body: Mapping[str, Any]) -> None:
        if self.media_web_tasks is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "service_unavailable",
                "上传服务暂时不可用。",
            )
            return
        if context.idempotency is None:
            raise RequestContextError("上传请求缺少幂等键。")
        required_fields = {"schemaVersion", "filename", "contentBase64", "idempotencyKey"}
        optional_fields = {"mimeType"}
        if (
            not isinstance(body, Mapping)
            or not required_fields.issubset(body)
            or set(body) - required_fields - optional_fields
            or body.get("schemaVersion") != "3"
        ):
            raise MediaWebTaskError("invalid_request", "上传请求不符合结构化契约。")
        if body.get("idempotencyKey") != context.idempotency.key:
            raise RequestContextError("上传请求的幂等键不一致。")
        projection, created = self.media_web_tasks.create_upload(
            {
                "filename": body["filename"],
                "mimeType": body.get("mimeType", ""),
                "contentBase64": body["contentBase64"],
            },
            tenant_id=str(context.principal.tenant_id),
        )
        self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK, projection)

    def _execute_media_task_operation(
        self,
        operation: str,
        match: RouteMatch,
        context: If2RequestContext,
        body: Mapping[str, Any],
    ) -> None:
        if self.media_web_tasks is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "service_unavailable", "服务暂时不可用。")
            return
        tenant_id = str(context.principal.tenant_id)
        user_public_id = context.principal.user_public_id
        task_id = match.path_parameters.get("taskId", "")
        if operation == "listMediaTasks":
            query = dict(context.query_parameters)
            limit = int((query.get("pageSize") or ("20",))[0])
            self._send_json(
                HTTPStatus.OK,
                self.media_web_tasks.list_tasks(
                    tenant_id=tenant_id,
                    user_public_id=user_public_id,
                    limit=limit,
                ),
            )
        elif operation == "createMediaTask":
            if context.idempotency and body.get("idempotencyKey") != context.idempotency.key:
                raise RequestContextError("body and header idempotency keys differ")
            projection, created = self.media_web_tasks.create_task(
                body,
                tenant_id=tenant_id,
                user_public_id=context.principal.user_public_id,
                workspace_mode=context.principal.workspace_mode,
                role=context.principal.role,
                is_maintainer=context.principal.is_maintainer,
            )
            self._send_json(HTTPStatus.ACCEPTED if created else HTTPStatus.OK, projection)
        elif operation == "getMediaTask":
            self._send_json(
                HTTPStatus.OK,
                self.media_web_tasks.get_task(
                    task_id, tenant_id=tenant_id, user_public_id=user_public_id
                ),
            )
        elif operation == "listMediaTaskEvents":
            self._handle_media_task_events(
                task_id,
                tenant_id=tenant_id,
                user_public_id=user_public_id,
            )
        elif operation == "cancelMediaTask":
            self._send_json(
                HTTPStatus.OK,
                self.media_web_tasks.cancel_task(
                    task_id, tenant_id=tenant_id, user_public_id=user_public_id
                ),
            )
        else:
            self._send_json(
                HTTPStatus.OK,
                self.media_web_tasks.confirm_task(
                    task_id,
                    body,
                    tenant_id=tenant_id,
                    user_public_id=user_public_id,
                ),
            )

    def do_GET(self) -> None:
        try:
            self._do_GET()
        except MediaWebTaskError as exc:
            self._handle_media_service_error(exc)
        except AssetsError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.message)
        except TenantProjectionError as exc:
            self._handle_tenant_projection_error(exc)
        except TenantActivityAccessError as exc:
            status = HTTPStatus.NOT_FOUND if exc.code == "activity_not_found" else HTTPStatus.FORBIDDEN
            self._send_api_error(status, exc.code, str(exc))
        except CloudMediaTaskReceiverError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except DeviceJobError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except AccountError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except ProvisioningError as exc:
            self._send_stage1_provisioning_error(exc)
        except UpstreamCredentialError:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "upstream_credential_unavailable",
                "平台模型凭据不可用。",
            )
        except ValueError:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请求格式无效。")
        except Exception as exc:
            LOGGER.exception(
                "HTTP request failed",
                extra={
                    "method": "GET",
                    "path": self._request_path(),
                    "request_id": self._correlation_id(),
                    "error_type": type(exc).__name__,
                },
            )
            self._send_api_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "服务暂时不可用，请稍后重试。")

    def _do_GET(self) -> None:
        path = self._request_path()
        match = re.fullmatch(r"/internal/content-os/mac-result/(task_\d{8}_\d{3})", path)
        if match is not None:
            self._handle_content_os_mac_result_readback(match.group(1))
            return
        if path in {"/openclaw/media/oauth/callback", "/auth/feishu/callback"}:
            self._handle_auth_feishu_callback()
            return
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/readyz":
            payload = {
                "ok": True,
                "content_flow_base_url": self.app.settings.get("content_flow", {}).get("base_url", "") if self.app else "",
                "feishu_mode": self.app.settings.get("feishu", {}).get("mode", "") if self.app else "",
                "mac_agent_mode": self.app.settings.get("mac_agent", {}).get("mode", "") if self.app else "",
                "matcher_ready": self.matcher is not None,
                "auth_ready": self.auth_config is not None,
                "if2_ready": (
                    self.media_business_dispatcher is not None
                    and self.media_business_dispatcher.operation_ids
                    == frozenset(route.operation_id for route in MEDIA_BUSINESS_ROUTE_BINDINGS)
                    and set(self.media_business_services or {}) == set(_IF2_OPERATION_SERVICE.values())
                ),
            }
            self._send_json(HTTPStatus.OK, payload)
            return
        if path == "/auth/check":
            if self._is_authenticated():
                self._send_empty(HTTPStatus.NO_CONTENT)
            else:
                self._send_empty(HTTPStatus.UNAUTHORIZED)
            return
        if path == "/auth/status":
            self._send_json(HTTPStatus.OK, {"authenticated": self._is_authenticated()})
            return
        if path == "/openclaw/auth/entry-state":
            self._handle_auth_entry_state()
            return
        if path == "/openclaw/media/api/session":
            if self._dispatch_media_business("GET"):
                return
        if self._dispatch_stage1_provisioning("GET"):
            return
        if path == "/auth/registration-policy":
            self._handle_registration_policy()
            return
        if self.tenant_projections is not None:
            if path == "/media/api/dashboard":
                self._handle_tenant_dashboard()
                return
            if path == "/media/api/runs":
                self._handle_tenant_runs()
                return
            if path == "/media/api/admin/runs":
                self._handle_admin_tenant_runs()
                return
            match = re.fullmatch(
                r"/media/api/runs/([A-Za-z0-9_-]{1,160})(?:/(sources|decisions|outputs))?",
                path,
            )
            if match:
                self._handle_tenant_run(match.group(1), match.group(2))
                return
        if path in {"/media/api/recent-activity", "/openclaw/media/api/recent-activity"}:
            self._handle_recent_activity()
            return
        if self._dispatch_legacy_support("GET"):
            return
        if self._dispatch_media_business("GET"):
            return
        resolved = self._resolve_r1_operation("GET")
        if resolved is not None:
            self._handle_device_job_get(*resolved)
            return
        resolved = self._resolve_archive_operation("GET")
        if resolved is not None:
            self._handle_archive_get(*resolved)
            return
        if path in {"/media/api/assets", "/openclaw/media/api/assets"}:
            self._handle_tenant_assets()
            return
        match = re.fullmatch(r"/(?:openclaw/media/api|media/api)/assets/([A-Za-z0-9_-]{8,160})/preview", path)
        if match:
            self._handle_tenant_asset_preview(match.group(1))
            return
        match = re.fullmatch(r"/(?:openclaw/media/api|media/api)/assets/([A-Za-z0-9_-]{8,160})", path)
        if match:
            self._handle_tenant_asset_detail(match.group(1))
            return
        self._send_api_error(HTTPStatus.NOT_FOUND, "not_found", "未找到该接口。")

    def do_POST(self) -> None:
        path = self._request_path()
        try:
            if self.personal_auth is not None and self._dispatch_personal_auth_post(path):
                return
            if (
                path in {"/openclaw/auth/login", "/auth/login"}
                and self.personal_auth is None
                and self.media_feishu_login is None
            ):
                # Password login is retired once the Feishu media login flow is
                # the configured entrypoint; it must not become a fallback.
                self._handle_auth_login(self._read_json_body())
                return
            if path == "/auth/feishu/start":
                self._handle_auth_feishu_start(self._read_json_body(maximum_bytes=1024))
                return
            if path in {"/openclaw/auth/register", "/auth/register"} and self.personal_auth is None:
                self._handle_auth_register(self._read_json_body(maximum_bytes=16 * 1024))
                return
            if path == "/openclaw/auth/logout" and self.personal_auth is not None:
                self._handle_personal_logout()
                return
            if path in {"/openclaw/auth/logout", "/auth/logout"} and self.personal_auth is None:
                self._handle_auth_logout()
                return
            if self._dispatch_stage1_provisioning("POST"):
                return
            if self._dispatch_legacy_support("POST"):
                return
            if self._dispatch_media_business("POST"):
                return
            match = re.fullmatch(r"/internal/content-os/mac-result/(task_\d{8}_\d{3})/retry", path)
            if match is not None:
                self._handle_content_os_mac_result_retry(
                    match.group(1), self._read_json_body(maximum_bytes=8 * 1024)
                )
                return
            if path == "/internal/content-os/mac-result":
                self._handle_content_os_mac_result()
                return
            resolved = self._resolve_r1_operation("POST")
            if resolved is not None:
                self._handle_device_job_post(*resolved, payload=self._read_json_body(maximum_bytes=256 * 1024))
                return
            resolved = self._resolve_archive_operation("POST")
            if resolved is not None:
                if self._require_media_archive_service() is None:
                    return
                payload = (
                    {}
                    if resolved[0] == "archive_delete_plan"
                    else self._read_json_body(
                        maximum_bytes=_media_archive_contract().ARCHIVE_HTTP_BODY_MAXIMUM_BYTES
                    )
                )
                self._handle_archive_post(*resolved, payload=payload)
                return
            if path == "/qqbot/event":
                self._handle_qq_event(self._read_json_body())
                return
            if path == "/stage2/personal":
                self._handle_stage2("personal", self._read_json_body(maximum_bytes=1024 * 1024, reject_duplicates=True))
                return
            if path == "/stage2/organization":
                self._handle_stage2("organization", self._read_json_body(maximum_bytes=1024 * 1024, reject_duplicates=True))
                return
            self._send_api_error(HTTPStatus.NOT_FOUND, "not_found", "未找到该接口。")
        except MediaWebTaskError as exc:
            self._handle_media_service_error(exc)
        except AccountError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except ProvisioningError as exc:
            self._send_stage1_provisioning_error(exc)
        except CloudMediaTaskReceiverError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except DeviceJobError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except UpstreamCredentialError:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "upstream_credential_unavailable",
                "平台模型凭据不可用。",
            )
        except ValueError:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请求格式无效。")
        except Exception as exc:
            LOGGER.exception(
                "HTTP request failed",
                extra={
                    "method": "POST",
                    "path": self._request_path(),
                    "request_id": self._correlation_id(),
                    "error_type": type(exc).__name__,
                },
            )
            self._send_api_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "服务暂时不可用，请稍后重试。")

    def do_PUT(self) -> None:
        try:
            path = self._request_path()
            if (
                path in {"/openclaw/auth/password", "/auth/password"}
                and self.personal_auth is None
                and self.media_feishu_login is None
            ):
                # Retired with password login: Feishu-authenticated accounts
                # cannot mutate a password credential over this surface.
                self._handle_auth_password_change(self._read_json_body(maximum_bytes=16 * 1024))
                return
            if self._dispatch_legacy_support("PUT"):
                return
            if self._dispatch_media_business("PUT"):
                return
            self._send_api_error(HTTPStatus.NOT_FOUND, "not_found", "未找到该接口。")
        except MediaWebTaskError as exc:
            self._handle_media_service_error(exc)
        except AccountError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except ValueError:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请求格式无效。")
        except Exception as exc:
            LOGGER.exception(
                "HTTP request failed",
                extra={
                    "method": "PUT",
                    "path": self._request_path(),
                    "request_id": self._correlation_id(),
                    "error_type": type(exc).__name__,
                },
            )
            self._send_api_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "服务暂时不可用，请稍后重试。")

    def do_DELETE(self) -> None:
        try:
            resolved = self._resolve_archive_operation("DELETE")
            if resolved is not None:
                self._handle_archive_delete(*resolved, payload=self._read_json_body(maximum_bytes=16 * 1024))
                return
            self._send_api_error(HTTPStatus.NOT_FOUND, "not_found", "未找到该接口。")
        except MediaWebTaskError as exc:
            self._handle_media_service_error(exc)
        except AccountError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
        except ValueError:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请求格式无效。")
        except Exception as exc:
            LOGGER.exception(
                "HTTP request failed",
                extra={
                    "method": "DELETE",
                    "path": self._request_path(),
                    "request_id": self._correlation_id(),
                    "error_type": type(exc).__name__,
                },
            )
            self._send_api_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "服务暂时不可用，请稍后重试。")

    def _dispatch_stage1_provisioning(self, method: str) -> bool:
        """Handle the bounded 1B organization provision control plane."""
        runtime = self.stage1_provisioning
        if runtime is None:
            return False
        path = self._request_path()
        prefix = "/openclaw/media/api/organization/provision"
        if not (path == prefix or path.startswith(prefix + "/")):
            return False
        resolved = self._require_media_session()
        if resolved is None:
            return True
        token, session = resolved
        is_personal_confirm = (
            method == "POST"
            and path == prefix + "/confirm"
            and session.workspace_mode == "personal_web"
            and session.body_authority == "internal"
        )
        is_organization_session = (
            session.workspace_mode == "organization_lark" and session.body_authority == "lark"
        )
        if not is_personal_confirm and not is_organization_session:
            self._send_api_error(HTTPStatus.FORBIDDEN, "forbidden", "当前会话无权访问组织接入。")
            return True
        if method == "GET":
            match = re.fullmatch(prefix + r"/runs/([0-9a-fA-F-]{36})", path)
            if match is None:
                self._send_json(HTTPStatus.OK, {"schemaVersion": "media.stage1.provision.v1", "run": None})
                return True
            run = runtime.status_for_session(session, uuid.UUID(match.group(1)))
            self._send_json(HTTPStatus.OK, {"schemaVersion": "media.stage1.provision.v1", "run": provision_status_json(run)})
            return True
        if method != "POST":
            return False
        if not self._require_csrf(token):
            return True
        key = self._require_idempotency_key()
        if key is None:
            return True
        body = self._read_json_body(maximum_bytes=32 * 1024)
        if path == prefix + "/confirm":
            if body:
                self._send_api_error(HTTPStatus.FORBIDDEN, "forbidden", "请求包含不允许的字段。")
                return True
            receipt = runtime.confirm_for_session(session, idempotency_key=key)
            self._send_json(HTTPStatus.OK, {"schemaVersion": "media.stage1.provision.v1", "confirmation": {
                "confirmationId": str(receipt.confirmation_id), "installationId": str(receipt.installation_id),
                "tenantId": str(receipt.tenant_id), "bindingId": receipt.binding_id,
                "bindingGeneration": receipt.binding_generation, "state": "NEEDS_ATTENTION",
            }})
            return True
        if path == prefix + "/start":
            if body:
                self._send_api_error(HTTPStatus.FORBIDDEN, "forbidden", "请求包含不允许的字段。")
                return True
            run = runtime.start_for_session(session, idempotency_key=key)
            self._send_json(HTTPStatus.OK, {"schemaVersion": "media.stage1.provision.v1", "run": provision_run_json(run)})
            return True
        if path == prefix + "/deprovision":
            if set(body) - {"revoke"}:
                self._send_api_error(HTTPStatus.FORBIDDEN, "forbidden", "请求包含不允许的字段。")
                return True
            revoke = body.get("revoke", False)
            if not isinstance(revoke, bool):
                raise ValueError("revoke must be a boolean")
            receipt = runtime.deprovision_for_session(session, idempotency_key=key, revoke=revoke)
            self._send_json(HTTPStatus.OK, {"schemaVersion": "media.stage1.provision.v1", "receipt": deprovision_json(receipt)})
            return True
        self._send_api_error(HTTPStatus.NOT_FOUND, "not_found", "未找到该接口。")
        return True

    def _send_stage1_provisioning_error(self, error: ProvisioningError) -> None:
        if error.status == 403:
            status = HTTPStatus.FORBIDDEN
            public_code, message = "forbidden", "当前会话无权执行该操作。"
        elif error.status == 404:
            status = HTTPStatus.NOT_FOUND
            public_code, message = "not_found", "未找到请求的组织接入资源。"
        elif error.status == 409:
            status = HTTPStatus.CONFLICT
            public_code = (
                "binding_unavailable"
                if "binding" in error.code or "installation" in error.code
                else "provision_state_conflict"
            )
            message = "当前组织接入状态不允许该操作。"
        elif error.status == 429:
            status = HTTPStatus.TOO_MANY_REQUESTS
            public_code, message = "rate_limited", "请求过于频繁，请稍后重试。"
        elif 400 <= error.status < 500:
            status = HTTPStatus.BAD_REQUEST
            public_code, message = "validation_error", "请求格式无效。"
        else:
            status = (
                HTTPStatus.SERVICE_UNAVAILABLE
                if error.status == HTTPStatus.SERVICE_UNAVAILABLE
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            public_code, message = "internal_error", "服务暂时不可用，请稍后重试。"
        self._send_api_error(status, public_code, message)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(
        self,
        *,
        maximum_bytes: int = 2 * 1024 * 1024,
        reject_duplicates: bool = False,
    ) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("missing content length")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise ValueError("content length is invalid") from exc
        if length < 0:
            raise ValueError("content length is invalid")
        if length > maximum_bytes:
            raise MediaWebTaskError("payload_too_large", "输入或文件超过大小限制。")
        raw_payload = self.rfile.read(length)
        try:
            payload = json.loads(
                raw_payload or b"{}",
                object_pairs_hook=_reject_duplicate_json_fields if reject_duplicates else None,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body is not valid json") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return payload

    def _is_authenticated(self) -> bool:
        try:
            if self.personal_auth is not None:
                return self._resolved_personal_session() is not None
            return self._resolved_session() is not None
        except AccountError:
            return False

    def _legacy_session_cookie(self) -> str | None:
        if self.auth_config is None:
            return None
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookies.get(SESSION_COOKIE_NAME)
            token = morsel.value if morsel else None
        except (KeyError, ValueError):
            return None
        return token

    def _resolved_session(self) -> tuple[str, AccountSession] | None:
        token = self._legacy_session_cookie()
        if not token or self.account_auth is None:
            return None
        session = self.account_auth.resolve_session(token)
        return None if session is None else (token, session)

    def _resolved_personal_session(self) -> tuple[str, Any] | None:
        token = self._legacy_session_cookie()
        if not token or self.personal_auth is None:
            return None
        session = self.personal_auth.resolve_session(token)
        return None if session is None else (token, session)

    def _require_media_session(self, *, allow_password_change: bool = False) -> tuple[str, AccountSession] | None:
        try:
            resolved = self._resolved_session()
        except AccountError as exc:
            self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)
            return None
        if resolved is None:
            self._send_api_error(HTTPStatus.UNAUTHORIZED, "authentication_required", "登录后可使用 Media 执行能力。")
            return None
        return resolved

    def _require_media_auth(self) -> str | None:
        resolved = self._require_media_session()
        return str(resolved[1].tenant_id) if resolved is not None else None

    def _require_admin_session(self) -> tuple[str, AccountSession] | None:
        resolved = self._require_media_session()
        if resolved is None:
            return None
        session = resolved[1]
        if session.role != "admin":
            self._send_api_error(HTTPStatus.FORBIDDEN, "admin_required", "需要平台管理员权限。")
            return None
        return resolved

    def _require_csrf(self, token: str) -> bool:
        if self.account_auth is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "account_database_unavailable", "登录服务暂时不可用。")
            return False
        origin = urlsplit(self.headers.get("Origin", ""))
        try:
            authority = self._external_request_authority()
            same_origin = self._origin_matches_authority(origin, authority)
        except (RequestContextError, ValueError):
            same_origin = False
        supplied = self.headers.get("X-OpenClaw-CSRF", "")
        if not same_origin or not self.account_auth.verify_csrf(token, supplied):
            self._send_api_error(HTTPStatus.FORBIDDEN, "csrf_rejected", "请求来源校验失败，请刷新页面后重试。")
            return False
        return True

    def _require_media_mutation_auth(self) -> str | None:
        resolved = self._require_media_session()
        if resolved is None:
            return None
        token, session = resolved
        if not self._require_csrf(token):
            return None
        tenant_id = str(session.tenant_id)
        if not self._consume_rate_limit("media_mutation", f"{tenant_id}:{self._client_key()}"):
            return None
        return tenant_id

    def _require_idempotency_key(self, *, maximum_length: int = 128) -> str | None:
        key = self.headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > maximum_length or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            self._send_api_error(
                HTTPStatus.BAD_REQUEST,
                "idempotency_key_required",
                "请刷新页面后重试。",
            )
            return None
        return key

    def _bind_mutation_payload(
        self,
        actor_scope: str,
        operation_scope: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> bool:
        if self.mutation_bindings is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "idempotency_unavailable",
                "写入保护暂时不可用，请稍后重试。",
            )
            return False
        if not self.mutation_bindings.bind(actor_scope, operation_scope, idempotency_key, payload):
            self._send_api_error(
                HTTPStatus.CONFLICT,
                "idempotency_conflict",
                "幂等键已绑定其他请求内容。",
            )
            return False
        return True

    def _client_key(self) -> str:
        try:
            return self._external_request_authority().client_ip[:128]
        except (RequestContextError, ValueError):
            return str(self.client_address[0])[:128]

    def _require_device_job_service(self) -> DeviceJobService | None:
        if self.device_job_service is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "device_job_unavailable", "设备执行服务暂时不可用。")
            return None
        return self.device_job_service

    def _resolve_r1_operation(self, method: str) -> tuple[str, dict[str, str]] | None:
        path = self._request_path()
        if path.startswith(CANONICAL_PREFIX + "/"):
            return _resolve_product_operation(
                path[len(CANONICAL_PREFIX):], method, archive=False
            )
        return None

    def _resolve_archive_operation(self, method: str) -> tuple[str, dict[str, str]] | None:
        path = self._request_path()
        if path.startswith(CANONICAL_PREFIX + "/"):
            return _resolve_product_operation(
                path[len(CANONICAL_PREFIX):], method, archive=True
            )
        return None

    def _require_media_archive_service(self) -> MediaArchiveService | None:
        if self.media_archive_service is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "media_archive_unavailable", "归档服务暂时不可用。")
            return None
        return self.media_archive_service

    def _send_archive_json(self, operation_id: str, status: HTTPStatus, payload: Any) -> None:
        _device_job_contract().validate_r1_response(operation_id, payload)
        self._send_json(status, payload)

    def _send_archive_error(self, exc: Any) -> None:
        self._send_api_error(HTTPStatus(exc.status), exc.code, exc.detail)

    def _handle_archive_get(self, operation_id: str, path_parameters: Mapping[str, str]) -> None:
        service = self._require_media_archive_service()
        resolved = self._require_media_session()
        if service is None or resolved is None:
            return
        tenant_id = str(resolved[1].tenant_id)
        try:
            if operation_id == "archive_list":
                limit, state = self._r1_pagination(include_state=True)
                response = service.list(tenant_id, limit=limit, state=state)
            elif operation_id == "archive_detail":
                response = service.detail(tenant_id, path_parameters["archive_id"])
            else:
                raise ValueError("unsupported archive read operation")
        except _media_archive_contract().MediaArchiveError as exc:
            self._send_archive_error(exc)
            return
        self._send_archive_json(operation_id, HTTPStatus.OK, response)

    def _handle_archive_post(self, operation_id: str, path_parameters: Mapping[str, str], *, payload: Mapping[str, Any]) -> None:
        service = self._require_media_archive_service()
        if service is None:
            return
        key = self._require_idempotency_key()
        if key is None:
            return
        if operation_id == "archive_commit":
            tenant_id = self._require_media_mutation_auth()
            if tenant_id is None:
                return
            try:
                response = service.commit(tenant_id, payload, idempotency_key=key)
            except _media_archive_contract().MediaArchiveError as exc:
                self._send_archive_error(exc)
                return
            self._send_archive_json(operation_id, HTTPStatus.CREATED, response)
            return
        resolved = self._require_media_mutation_auth()
        if resolved is None:
            return
        tenant_id = resolved
        if operation_id == "archive_delete_plan":
            try:
                response = service.delete_plan(tenant_id, path_parameters["archive_id"], idempotency_key=key)
            except _media_archive_contract().MediaArchiveError as exc:
                self._send_archive_error(exc)
                return
            self._send_archive_json(operation_id, HTTPStatus.OK, response)
        elif operation_id == "archive_readback":
            try:
                response = service.readback(tenant_id, path_parameters["archive_id"], payload, idempotency_key=key)
            except _media_archive_contract().MediaArchiveError as exc:
                self._send_archive_error(exc)
                return
            self._send_archive_json(operation_id, HTTPStatus.OK, response)
        else:
            raise ValueError("unsupported archive write operation")

    def _handle_archive_delete(self, operation_id: str, path_parameters: Mapping[str, str], *, payload: Mapping[str, Any]) -> None:
        service = self._require_media_archive_service()
        if service is None:
            return
        key = self._require_idempotency_key()
        resolved = self._require_media_mutation_auth()
        if key is None or resolved is None:
            return
        try:
            response = service.delete(resolved, path_parameters["archive_id"], payload, idempotency_key=key)
        except _media_archive_contract().MediaArchiveError as exc:
            self._send_archive_error(exc)
            return
        self._send_archive_json(operation_id, HTTPStatus.OK, response)

    def _device_credential(self) -> str | None:
        authorization = self.headers.get("Authorization", "")
        scheme, separator, value = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not value.strip():
            self._send_api_error(HTTPStatus.UNAUTHORIZED, "invalid_device_credential", "设备凭据无效。")
            return None
        return value.strip()

    def _handle_content_os_mac_result(self) -> None:
        """Accept a Mac result and keep the legacy acknowledgement shape stable."""
        service = self._require_device_job_service()
        if service is None:
            return
        credential = self._device_credential()
        if credential is None:
            return
        payload = self._read_json_body(maximum_bytes=256 * 1024)
        accepted = self._content_os_cloud_receiver(service).receive(
            credential=credential,
            result=payload,
            idempotency_key=self.headers.get("Idempotency-Key"),
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "status": accepted["status"],
                "task_id": accepted["task"]["task_id"],
            },
        )

    def _handle_content_os_mac_result_readback(self, task_id: str) -> None:
        service = self._require_device_job_service()
        if service is None:
            return
        credential = self._device_credential()
        if credential is None:
            return
        receipt = self._content_os_cloud_receiver(service).readback(
            credential=credential,
            task_id=task_id,
        )
        self._send_json(HTTPStatus.OK, {"ok": True, "receipt": receipt})

    def _handle_content_os_mac_result_retry(self, task_id: str, payload: Mapping[str, Any]) -> None:
        service = self._require_device_job_service()
        if service is None:
            return
        credential = self._device_credential()
        if credential is None:
            return
        key = self._require_idempotency_key()
        if key is None:
            return
        if set(payload) != {"reason"}:
            raise CloudMediaTaskReceiverError(
                "invalid_request",
                "重试请求只能包含 reason。",
                status=HTTPStatus.BAD_REQUEST,
            )
        receipt = self._content_os_cloud_receiver(service).retry_blocked_change(
            credential=credential,
            task_id=task_id,
            idempotency_key=key,
            reason=payload["reason"],
        )
        self._send_json(HTTPStatus.CREATED, {"ok": True, "receipt": receipt})

    def _content_os_cloud_receiver(self, service: DeviceJobService) -> CloudMediaTaskReceiver:
        if self.app is None or not hasattr(self.app, "router"):
            raise CloudMediaTaskReceiverError(
                "content_os_unavailable",
                "Content OS 服务暂时不可用。",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return CloudMediaTaskReceiver(service, self.app.router)

    def _r1_pagination(self, *, include_state: bool = False) -> tuple[int, str | None]:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        try:
            limit = int(query.get("limit", ["30"])[0])
        except ValueError as exc:
            raise DeviceJobError("invalid_request", "limit is invalid") from exc
        if not 1 <= limit <= 100:
            raise DeviceJobError("invalid_request", "limit is invalid")
        cursor = query.get("cursor", [""])[0]
        if len(cursor) > 256:
            raise DeviceJobError("invalid_request", "cursor is invalid")
        state = query.get("state", [None])[0] if include_state else None
        return limit, state

    def _handle_device_job_get(self, operation_id: str, path_parameters: Mapping[str, str]) -> None:
        service = self._require_device_job_service()
        if service is None:
            return
        if operation_id == "pipeline_list":
            if self._require_media_session() is None:
                return
            limit, _ = self._r1_pagination()
            self._send_r1_json(
                operation_id,
                HTTPStatus.OK,
                {
                    "pipelines": _device_job_contract().pipeline_summaries()[:limit],
                    "next_cursor": None,
                },
            )
            return
        if operation_id == "device_list":
            resolved = self._require_media_session()
            if resolved is None:
                return
            limit, _ = self._r1_pagination()
            self._send_r1_json(operation_id, HTTPStatus.OK, {"devices": service.list_devices(str(resolved[1].tenant_id), limit=limit), "next_cursor": None})
            return
        if operation_id == "job_list":
            try:
                resolved = self._resolved_session()
            except AccountError as exc:
                raise DeviceJobError("unauthenticated", exc.detail) from exc
            limit, state = self._r1_pagination(include_state=True)
            if resolved is not None:
                jobs = service.list_jobs(str(resolved[1].tenant_id), state=state, limit=limit)
            else:
                credential = self._device_credential()
                if credential is None:
                    return
                jobs = service.list_jobs_for_device(credential, state=state, limit=limit)
            self._send_r1_json(operation_id, HTTPStatus.OK, {"jobs": jobs, "next_cursor": None})
            return
        if operation_id == "job_detail":
            resolved = self._require_media_session()
            if resolved is None:
                return
            self._send_r1_json(operation_id, HTTPStatus.OK, {"job": service.get_job(str(resolved[1].tenant_id), path_parameters["job_id"])})
            return
        raise DeviceJobError("invalid_request", "unsupported Device/Job read operation")

    def _handle_device_job_post(self, operation_id: str, path_parameters: Mapping[str, str], *, payload: Mapping[str, Any]) -> None:
        service = self._require_device_job_service()
        if service is None:
            return
        if operation_id == "cli_release_compatibility" and self._require_media_session() is None:
            return
        _device_job_contract().validate_r1_request(operation_id, payload)
        key = None if operation_id == "cli_release_compatibility" else self._require_idempotency_key()
        if key is None and operation_id != "cli_release_compatibility":
            return
        if operation_id == "pair_code_create":
            tenant_id = self._require_media_mutation_auth()
            if tenant_id is None:
                return
            if set(payload) != {"device_label", "expires_in_seconds"}:
                raise DeviceJobError("invalid_request", "pair code request fields are invalid")
            self._send_r1_json(operation_id, HTTPStatus.CREATED, service.create_pair_code(tenant_id, device_label=payload["device_label"], expires_in_seconds=payload["expires_in_seconds"], idempotency_key=key))
            return
        if operation_id == "device_pair":
            if set(payload) != {"pair_code", "device_label", "device_platform", "client_version"}:
                raise DeviceJobError("invalid_request", "device pair request fields are invalid")
            device, credential = service.pair_device(pair_code=payload["pair_code"], device_label=payload["device_label"], device_platform=payload["device_platform"], client_version=payload["client_version"], idempotency_key=key)
            self._send_r1_json(operation_id, HTTPStatus.OK, {"device": device, "device_credential": credential})
            return
        if operation_id == "device_heartbeat":
            credential = self._device_credential()
            if credential is None:
                return
            response = service.heartbeat(path_parameters["device_id"], credential, observed_at=payload["observed_at"], client_version=payload["client_version"], api_version=payload["api_version"], reported_catalog_digest=payload["catalog_digest"], capabilities=payload.get("capabilities"), idempotency_key=key, expected_revision=payload["expected_revision"])
            self._send_r1_json(operation_id, HTTPStatus.OK, response)
            return
        if operation_id == "device_revoke":
            tenant_id = self._require_media_mutation_auth()
            if tenant_id is None:
                return
            self._send_r1_json(operation_id, HTTPStatus.OK, service.revoke_device(tenant_id, path_parameters["device_id"], idempotency_key=key, expected_revision=payload["expected_revision"]))
            return
        if operation_id == "job_create":
            tenant_id = self._require_media_mutation_auth()
            if tenant_id is None:
                return
            allowed = {"pipeline_id", "pipeline_version", "catalog_digest", "device_id", "input_refs", "output_selection", "confirmation_ref"}
            required = allowed - {"confirmation_ref"}
            if not required.issubset(payload) or set(payload) - allowed:
                raise DeviceJobError("invalid_request", "job create request fields are invalid")
            self._send_r1_json(operation_id, HTTPStatus.CREATED, {"job": service.create_job(tenant_id, pipeline_id=payload["pipeline_id"], pipeline_version=payload["pipeline_version"], catalog_digest=payload["catalog_digest"], device_id=payload["device_id"], input_refs=payload["input_refs"], output_selection=payload["output_selection"], confirmation_ref=payload.get("confirmation_ref"), idempotency_key=key)})
            return
        if operation_id == "cli_release_compatibility":
            min_cli_version, supported_python, supported_platforms = _release_compatibility_metadata()
            compatible = (
                payload["platform"] in supported_platforms
                and payload["api_version"] == _device_job_contract().SERVER_API_VERSION
                and payload["catalog_digest"] == _device_job_contract().catalog_digest()
                and _version_at_least(payload["cli_version"], min_cli_version)
                and _python_version_compatible(payload["python_version"], supported_python)
            )
            self._send_r1_json(operation_id, HTTPStatus.OK, {"compatible": compatible, "min_cli_version": min_cli_version, "supported_python": supported_python, "supported_platforms": supported_platforms})
            return
        credential = self._device_credential()
        if credential is None:
            return
        revision = payload["expected_revision"]
        if operation_id == "job_lease":
            self._send_r1_json(operation_id, HTTPStatus.OK, {"job": service.lease_job(path_parameters["job_id"], credential, lease_seconds=payload["lease_seconds"], idempotency_key=key, expected_revision=revision)})
            return
        if operation_id == "job_ack":
            self._send_r1_json(operation_id, HTTPStatus.OK, {"job": service.ack_job(path_parameters["job_id"], credential, ack_ref=payload["ack_ref"], idempotency_key=key, expected_revision=revision)})
            return
        if operation_id == "job_start":
            self._send_r1_json(operation_id, HTTPStatus.OK, {"job": service.start_job(path_parameters["job_id"], credential, start_ref=payload["start_ref"], idempotency_key=key, expected_revision=revision)})
            return
        if operation_id == "job_result":
            self._send_r1_json(operation_id, HTTPStatus.OK, {"job": service.result_job(path_parameters["job_id"], credential, result_status=payload["result_status"], result_refs=payload["result_refs"], artifact_refs=payload.get("artifact_refs"), failure_code=payload.get("failure_code"), idempotency_key=key, expected_revision=revision)})
            return
        raise DeviceJobError("invalid_request", "unsupported Device/Job write operation")

    def _consume_rate_limit(self, bucket: str, key: str) -> bool:
        if self.rate_limiter is None:
            return True
        allowed, retry_after = self.rate_limiter.consume(bucket, key)
        if allowed:
            return True
        self._send_api_error(
            HTTPStatus.TOO_MANY_REQUESTS,
            "rate_limited",
            "提交过于频繁，请稍后重试。",
            headers={"Retry-After": str(retry_after)},
        )
        return False

    def _pagination(self) -> tuple[int, int, str]:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        try:
            page = int(query.get("page", ["1"])[0])
            page_size = int(query.get("page_size", ["30"])[0])
        except ValueError as exc:
            raise ValueError("pagination is invalid") from exc
        search = query.get("search", [""])[0]
        if page < 1 or not 1 <= page_size <= 100 or len(search) > 120:
            raise ValueError("pagination is invalid")
        return page, page_size, search

    def _session_cookie(self, token: str, maximum_age: int, *, force_secure: bool = False) -> str:
        if self.auth_config is None:
            raise RuntimeError("auth is not configured")
        parts = [
            f"{SESSION_COOKIE_NAME}={token}",
            f"Path={self.auth_config.cookie_path}",
            f"Max-Age={maximum_age}",
            "HttpOnly",
            "SameSite=Lax",
        ]
        if force_secure or self.auth_config.cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _personal_identifier(self, payload: Mapping[str, Any]) -> str | None:
        values = [payload.get("identifier")] if "identifier" in payload else []
        if len(values) != 1 or not isinstance(values[0], str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请输入有效的账号标识。")
            return None
        return values[0]

    def _personal_callback(self, payload: Mapping[str, Any]) -> str | None:
        values = [payload.get(name) for name in ("callbackUrl", "callbackDestination") if name in payload]
        if len(values) != 1 or not isinstance(values[0], str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请输入有效的回调地址。")
            return None
        return values[0]

    def _dispatch_personal_auth_post(self, path: str) -> bool:
        routes = {
            "/openclaw/auth/register": self._handle_personal_register,
            "/openclaw/auth/verify-email": self._handle_personal_verify,
            "/openclaw/auth/verify-email/resend": self._handle_personal_resend,
            "/openclaw/auth/login": self._handle_personal_login,
            "/openclaw/auth/recover": self._handle_personal_recovery_request,
            "/openclaw/auth/reset": self._handle_personal_recovery_reset,
        }
        handler = routes.get(path)
        if handler is None:
            return False
        handler(self._read_json_body(maximum_bytes=16 * 1024))
        return True

    def _handle_personal_register(self, payload: Mapping[str, Any]) -> None:
        if self.personal_auth is None:
            raise RuntimeError("personal authentication is not configured")
        if set(payload) != {"username", "email", "password"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "注册请求字段无效。")
            return
        username, email, password = payload.get("username"), payload.get("email"), payload.get("password")
        if not all(isinstance(value, str) for value in (username, email, password)):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "注册请求格式无效。")
            return
        result = self.personal_auth.register(username=username, email=email, password=password)
        self._send_json(
            HTTPStatus.CREATED,
            {"ok": True, "status": result.status, "message": result.public_message},
        )

    def _handle_personal_verify(self, payload: Mapping[str, Any]) -> None:
        if self.personal_auth is None:
            raise RuntimeError("personal authentication is not configured")
        if set(payload) != {"token"} or not isinstance(payload.get("token"), str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "验证请求格式无效。")
            return
        result = self.personal_auth.verify_email(str(payload["token"]))
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "status": "ACTIVE", "loginRequired": result.login_required},
        )

    def _handle_personal_resend(self, payload: Mapping[str, Any]) -> None:
        if self.personal_auth is None:
            raise RuntimeError("personal authentication is not configured")
        identifier = self._personal_identifier(payload)
        if identifier is None:
            return
        if set(payload) != {"identifier"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "验证请求字段无效。")
            return
        result = self.personal_auth.resend_verification(identifier, source_key=self._client_key())
        self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "message": result.public_message})

    def _handle_personal_login(self, payload: Mapping[str, Any]) -> None:
        if self.personal_auth is None or self.auth_config is None:
            raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")
        if set(payload) != {"identifier", "password"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "登录请求字段无效。")
            return
        identifier = self._personal_identifier(payload)
        password = payload.get("password")
        if identifier is None or not isinstance(password, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请输入账号标识和密码。")
            return
        result = self.personal_auth.login(
            identifier,
            password,
            source_key=self._client_key(),
            previous_session_token=self._legacy_session_cookie(),
        )
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "csrfToken": result.csrf_token},
            headers={
                "Set-Cookie": self._session_cookie(
                    result.token,
                    self.personal_auth.session_ttl_seconds,
                    force_secure=True,
                )
            },
        )

    def _handle_personal_recovery_request(self, payload: Mapping[str, Any]) -> None:
        if self.personal_auth is None:
            raise AccountContractError("account_database_unavailable", "找回服务暂时不可用。")
        identifier = self._personal_identifier(payload)
        if identifier is None:
            return
        if set(payload) != {"identifier"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "找回请求字段无效。")
            return
        result = self.personal_auth.request_password_recovery(
            identifier,
            source_key=self._client_key(),
        )
        self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "message": result.public_message})

    def _handle_personal_recovery_reset(self, payload: Mapping[str, Any]) -> None:
        if self.personal_auth is None:
            raise AccountContractError("account_database_unavailable", "重置服务暂时不可用。")
        if set(payload) != {"token", "newPassword"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "重置请求字段无效。")
            return
        token, password = payload.get("token"), payload.get("newPassword")
        if not isinstance(token, str) or not isinstance(password, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "重置请求格式无效。")
            return
        result = self.personal_auth.reset_password(token, password)
        self._send_json(HTTPStatus.OK, {"ok": True, "loginRequired": result.login_required})

    def _handle_organization_intent_start(self, payload: Mapping[str, Any]) -> None:
        if self.organization_auth_intent is None:
            raise AccountContractError("organization_auth_unavailable", "组织认证暂时不可用。")
        callback = self._personal_callback(payload)
        if callback is None:
            return
        if set(payload) - {"callbackUrl", "callbackDestination"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "组织认证请求字段无效。")
            return
        result = self.organization_auth_intent.start(callback)
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "state": result.state,
                "callbackDestination": result.callback_destination,
                "expiresAt": result.expires_at.isoformat(),
            },
        )

    def _handle_organization_intent_status(self, payload: Mapping[str, Any]) -> None:
        if self.organization_auth_intent is None:
            raise AccountContractError("organization_auth_unavailable", "组织认证暂时不可用。")
        if set(payload) - {"state", "callbackUrl", "callbackDestination"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "组织认证状态请求字段无效。")
            return
        state = payload.get("state")
        callback = self._personal_callback(payload)
        if not isinstance(state, str) or callback is None:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "组织认证状态请求格式无效。")
            return
        result = self.organization_auth_intent.status(state, callback)
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "status": result.status,
                "callbackDestination": result.callback_destination,
                "identityLinkCreated": result.identity_link_created,
            },
        )

    def _handle_personal_auth_session(self) -> None:
        if self.personal_auth is None:
            raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")
        resolved = self._resolved_personal_session()
        if resolved is None:
            self._send_json(HTTPStatus.OK, {"authenticated": False})
            return
        token, session = resolved
        self._send_json(
            HTTPStatus.OK,
            {
                "authenticated": True,
                "accountId": str(session.account_id),
                "username": session.username,
                "csrfToken": self.personal_auth.csrf_token_for_session(token),
                "sessionIssuedAt": session.issued_at.isoformat(),
                "sessionExpiresAt": session.expires_at.isoformat(),
            },
        )

    def _handle_personal_logout(self) -> None:
        if self.personal_auth is None or self.auth_config is None:
            raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")
        resolved = self._resolved_personal_session()
        if resolved is not None:
            token, _session = resolved
            if not self._require_personal_csrf(token):
                return
            self.personal_auth.revoke_session(token)
        self._send_json(
            HTTPStatus.OK,
            {"ok": True},
            headers={"Set-Cookie": self._session_cookie("", 0, force_secure=True)},
        )

    def _require_personal_csrf(self, token: str) -> bool:
        if self.personal_auth is None:
            return False
        supplied = self.headers.get("X-OpenClaw-CSRF", "")
        try:
            authority = self._external_request_authority()
            origin = urlsplit(self.headers.get("Origin", ""))
            same_origin = self._origin_matches_authority(origin, authority)
        except (RequestContextError, ValueError):
            same_origin = False
        if not same_origin or not self.personal_auth.verify_csrf(token, supplied):
            self._send_api_error(HTTPStatus.FORBIDDEN, "csrf_rejected", "请求来源校验失败，请刷新页面后重试。")
            return False
        return True

    def _handle_auth_login(self, payload: Mapping[str, Any]) -> None:
        if not self._consume_rate_limit("auth_login", self._client_key()):
            return
        if self.auth_config is None or self.account_auth is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "account_database_unavailable", "登录服务暂时不可用。")
            return
        if set(payload) - {"username", "email", "password"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "登录请求字段无效。")
            return
        identifier = payload.get("username", payload.get("email"))
        password = payload.get("password")
        if not isinstance(identifier, str) or not isinstance(password, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请输入用户名和密码。")
            return
        result = self.account_auth.login(identifier, password, previous_token=self._legacy_session_cookie())
        self._send_json(
            HTTPStatus.OK,
            {"ok": True},
            headers={"Set-Cookie": self._session_cookie(result.token, self.auth_config.session_ttl_seconds)},
        )

    def _handle_auth_feishu_start(self, payload: Mapping[str, Any]) -> None:
        if not self._consume_rate_limit("auth_feishu_start", self._client_key()):
            return
        if set(payload) - {"workspaceIntent"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "飞书登录请求字段无效。")
            return
        # The workspace is an explicit security boundary. Missing intent must
        # not silently select the personal workspace.
        workspace_intent = payload.get("workspaceIntent")
        if not isinstance(workspace_intent, str) or workspace_intent not in {"personal_web", "organization_lark"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "飞书登录工作区类型无效。")
            return
        if self.media_feishu_login is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "feishu_login_unavailable",
                "飞书登录暂时不可用，请稍后重试。",
            )
            return
        started = self.media_feishu_login.start(workspace_intent=workspace_intent)
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "authorizationUrl": started.authorization_url,
                "expiresAt": started.expires_at,
                "maximumAge": started.maximum_age,
            },
        )

    def _handle_auth_entry_state(self) -> None:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        mode_values = query.get("mode")
        if (
            set(query) != {"mode"}
            or mode_values is None
            or len(mode_values) != 1
            or mode_values[0] not in _ENTRY_STATE_WORKSPACE_MODES
        ):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请求格式无效。")
            return
        mode = mode_values[0]

        def send_state(state: str, session: Any | None = None) -> None:
            entry = None
            if state == "matched":
                if session is None:
                    raise AccountContractError("account_contract_invalid", "matched entry state is missing a session")
                identity = getattr(session, "email", None) or getattr(session, "username", None)
                entry = {
                    "entryId": "current",
                    "displayLabel": "当前个人工作区" if mode == "personal" else "当前组织工作区",
                    "maskedIdentity": _mask_entry_identity(identity),
                    "expiresAt": session.expires_at.isoformat(),
                }
            self._send_json(
                HTTPStatus.OK,
                {
                    "schemaVersion": _ENTRY_STATE_SCHEMA_VERSION,
                    "mode": mode,
                    "state": state,
                    "entry": entry,
                    "fallback": _ENTRY_STATE_FALLBACKS[mode],
                },
            )

        if self.account_auth is None or self.auth_config is None:
            raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")
        inspect_session = getattr(self.account_auth, "inspect_session", None)
        if not callable(inspect_session):
            raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")
        inspection = inspect_session(self._legacy_session_cookie())
        if inspection is None:
            send_state("none")
            return
        if inspection.state == "expired":
            send_state("expired")
            return
        if inspection.state != "active":
            send_state("none")
            return
        if self.workspace_resolver is None:
            raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")

        session = inspection.session
        resolution = self.workspace_resolver.resolve(session, tenant_id=session.tenant_id)
        if resolution.resolution_state == "INVALID_SESSION":
            if resolution.failure_code in {"internal_error", "account_database_unavailable"}:
                raise AccountContractError("account_database_unavailable", "登录服务暂时不可用。")
            send_state("none")
            return
        selected = resolution.selected_workspace
        if (
            resolution.resolution_state != "RESOLVED"
            or selected is None
            or selected.resolution_eligibility != "ELIGIBLE"
            or selected.tenant_id != session.tenant_id
        ):
            send_state("none")
            return
        if selected.workspace_mode != _ENTRY_STATE_WORKSPACE_MODES[mode]:
            send_state("mismatched")
            return
        send_state("matched", session)

    def _handle_auth_feishu_callback(self) -> None:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        state_values = query.get("state") or []
        code_values = query.get("code") or []
        error_values = query.get("error") or []
        failure: AccountError | None = None
        if (
            self.media_feishu_login is None
            or self.account_auth is None
            or self.auth_config is None
            or len(state_values) != 1
            or len(code_values) > 1
            or len(error_values) > 1
        ):
            failure = AccountError(
                "feishu_login_invalid_callback",
                "MediaClaw 收到的飞书回调无效，请返回登录页重新发起登录。",
                status=400,
            )
        else:
            try:
                identity = self.media_feishu_login.complete_callback(
                    state=state_values[0],
                    code=code_values[0] if code_values else None,
                    error=error_values[0] if error_values else None,
                )
                result = self.account_auth.login_verified_feishu_identity(
                    tenant_key=identity.tenant_key,
                    open_id=identity.open_id,
                    union_id=identity.union_id,
                    previous_token=self._legacy_session_cookie(),
                    workspace_intent=identity.workspace_intent,
                )
                self._send_empty(
                    HTTPStatus.SEE_OTHER,
                    headers={
                        "Location": "/openclaw/media/overview",
                        "Set-Cookie": self._session_cookie(
                            result.token,
                            self.auth_config.session_ttl_seconds,
                        ),
                    },
                )
                return
            except AccountError as exc:
                failure = exc
        assert failure is not None
        title = "MediaClaw 登录失败"
        detail = escape(failure.detail)
        body = (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{title}</title></head><body><main><h1>{title}</h1>"
            f"<p>{detail}</p><p><small>技术参考码：{escape(failure.code)}</small></p>"
            "<p><a href=\"/openclaw/media/login\">返回 MediaClaw 登录页</a></p>"
            "</main></body></html>"
        ).encode("utf-8")
        self._send_binary(
            HTTPStatus(failure.status),
            body,
            content_type="text/html; charset=utf-8",
            headers={
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
                "Referrer-Policy": "no-referrer",
            },
        )

    def _handle_registration_policy(self) -> None:
        if self.account_registration is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "account_database_unavailable",
                "注册服务暂时不可用。",
            )
            return
        self._send_json(
            HTTPStatus.OK,
            {"registrationPolicyMode": self.account_registration.registration_mode()},
        )

    def _handle_auth_register(self, payload: Mapping[str, Any]) -> None:
        if not self._consume_rate_limit("auth_register", self._client_key()):
            return
        if self.account_registration is None or self.auth_config is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "account_database_unavailable",
                "注册服务暂时不可用。",
            )
            return
        allowed = {
            "username", "email", "password", "admissionCode", "affiliateCode",
            "tenantType", "workspaceMode", "bodyAuthority", "displayName", "organizationName",
        }
        if set(payload) - allowed:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "注册请求字段无效。")
            return
        username = payload.get("username")
        password = payload.get("password")
        email = payload.get("email")
        admission_code = payload.get("admissionCode")
        affiliate_code = payload.get("affiliateCode")
        tenant_type = payload.get("tenantType", "personal")
        workspace_mode = payload.get("workspaceMode")
        body_authority = payload.get("bodyAuthority")
        display_name = payload.get("displayName")
        organization_name = payload.get("organizationName")
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or (email is not None and not isinstance(email, str))
            or (admission_code is not None and not isinstance(admission_code, str))
            or (affiliate_code is not None and not isinstance(affiliate_code, str))
            or not isinstance(tenant_type, str)
            or (workspace_mode is not None and not isinstance(workspace_mode, str))
            or (body_authority is not None and not isinstance(body_authority, str))
            or (display_name is not None and not isinstance(display_name, str))
            or (organization_name is not None and not isinstance(organization_name, str))
        ):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "注册请求格式无效。")
            return
        result = self.account_registration.register(
            username=username,
            email=email,
            password=password,
            admission_code=admission_code,
            affiliate_code=affiliate_code,
            tenant_type=tenant_type,
            workspace_mode=workspace_mode,
            body_authority=body_authority,
            display_name=display_name,
            organization_name=organization_name,
        )
        self._send_json(
            HTTPStatus.CREATED,
            {
                "ok": True,
                "userId": str(result.user_id),
                "tenantId": str(result.tenant_id),
                "username": result.username,
                "inviterUserId": None if result.inviter_user_id is None else str(result.inviter_user_id),
            },
            headers={"Set-Cookie": self._session_cookie(result.login.token, self.auth_config.session_ttl_seconds)},
        )

    def _handle_auth_logout(self) -> None:
        if self.auth_config is None or self.account_auth is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "account_database_unavailable", "登录服务暂时不可用。")
            return
        idempotency_key = self._require_idempotency_key()
        if idempotency_key is None:
            return
        token = self._legacy_session_cookie()
        resolved = self._resolved_session()
        if resolved is not None:
            if not self._require_csrf(resolved[0]):
                return
            if not self._bind_mutation_payload(str(resolved[1].user_id), "auth.logout", idempotency_key, {}):
                return
        self.account_auth.revoke_session(token)
        cookie_header = {"Set-Cookie": self._session_cookie("", 0)}
        self._send_json(
            HTTPStatus.OK,
            {"ok": True},
            headers=cookie_header,
        )

    def _handle_auth_password_change(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_media_session()
        if resolved is None or self.account_auth is None:
            return
        token, session = resolved
        if not self._require_csrf(token):
            return
        idempotency_key = self._require_idempotency_key(maximum_length=96)
        if idempotency_key is None:
            return
        if set(payload) != {"oldPassword", "newPassword", "idempotencyKey"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "密码更新请求字段无效。")
            return
        if payload.get("idempotencyKey") != idempotency_key:
            self._send_api_error(HTTPStatus.CONFLICT, "idempotency_conflict", "幂等键与密码更新请求不一致。")
            return
        old_password = payload.get("oldPassword")
        new_password = payload.get("newPassword")
        if not isinstance(old_password, str) or not isinstance(new_password, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请输入当前密码和新密码。")
            return
        if not self._bind_mutation_payload(str(session.user_id), "auth.password", idempotency_key, payload):
            return
        self.account_auth.change_password(token, old_password, new_password)
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "reauthenticationRequired": True},
            headers={"Set-Cookie": self._session_cookie("", 0)},
        )

    def _require_registration_service(self) -> AccountRegistrationService | None:
        if self.account_registration is None:
            self._send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "account_database_unavailable",
                "账户服务暂时不可用。",
            )
            return None
        return self.account_registration

    def _handle_account_affiliate(self) -> None:
        resolved = self._require_media_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        self._send_json(
            HTTPStatus.OK,
            service.profile_projection(service.affiliate_profile(resolved[1].user_id)),
        )

    def _handle_account_invitees(self) -> None:
        resolved = self._require_media_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        page, page_size, _ = self._pagination()
        result = service.invitees(resolved[1].user_id, page=page, page_size=page_size)
        self._send_json(
            HTTPStatus.OK,
            {
                "items": [
                    {
                        "userId": str(item.user_id),
                        "username": item.username,
                        "createdAt": item.created_at.isoformat(),
                    }
                    for item in result.items
                ],
                "page": result.page,
                "pageSize": result.page_size,
                "total": result.total,
            },
        )

    def _handle_admin_registration_policy_get(self) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        self._send_json(HTTPStatus.OK, {"registrationPolicyMode": service.registration_mode()})

    def _upstream_gateway(self) -> TenantModelGateway:
        if self.tenant_model_gateway is None:
            raise UpstreamCredentialError("platform credential gateway is unavailable")
        return self.tenant_model_gateway

    def _fulfillment_service(self) -> RetailFulfillmentService:
        if self.retail_fulfillment is None:
            raise RuntimeError("retail fulfillment service is unavailable")
        return self.retail_fulfillment

    def _retail_admin_service(self) -> RetailAdminService:
        if self.retail_admin is None:
            raise RuntimeError("retail admin service is unavailable")
        return self.retail_admin

    def _handle_billing_plans(self) -> None:
        if self._require_media_session() is None:
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "items": self._retail_admin_service().plans()})

    def _handle_billing_redeem(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_media_session()
        if resolved is None or not self._require_csrf(resolved[0]):
            return
        session = resolved[1]
        if not self._consume_rate_limit("media_mutation", f"{session.tenant_id}:{self._client_key()}"):
            return
        if set(payload) != {"code"} or not isinstance(payload.get("code"), str):
            raise ValueError("redemption payload is invalid")
        result = self._fulfillment_service().redeem(
            tenant_id=str(session.tenant_id), user_id=str(session.user_id), code=payload["code"]
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "fulfillment": {
                    "fulfillmentId": str(result.fulfillment_id),
                    "planCode": result.plan_code,
                    "creditedAmount": str(result.credited_amount),
                    "affiliateAmount": str(result.affiliate_amount),
                    "status": result.status,
                },
            },
        )

    def _handle_admin_redemption_batch_create(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None or not self._require_csrf(resolved[0]):
            return
        key = self._require_idempotency_key()
        if key is None or not self._bind_mutation_payload(str(resolved[1].user_id), "billing.redemption_batch", key, payload):
            return
        if set(payload) != {"planCode", "count"}:
            raise ValueError("redemption batch payload is invalid")
        issue = self._fulfillment_service().create_batch(
            actor_user_id=resolved[1].user_id,
            plan_code=str(payload.get("planCode") or ""),
            count=payload.get("count") if isinstance(payload.get("count"), int) and not isinstance(payload.get("count"), bool) else 0,
            idempotency_key=key,
        )
        self._send_json(
            HTTPStatus.CREATED,
            {"ok": True, "batchId": str(issue.batch_id), "codeCount": issue.code_count},
        )

    def _handle_admin_product_mapping_create(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None or not self._require_csrf(resolved[0]):
            return
        key = self._require_idempotency_key()
        if key is None or not self._bind_mutation_payload(str(resolved[1].user_id), "billing.product_mapping", key, payload):
            return
        if set(payload) != {"planCode", "externalProductId", "purchaseUrl", "reason"} or not all(
            isinstance(payload.get(name), str) for name in payload
        ):
            raise ValueError("product mapping payload is invalid")
        result = self._retail_admin_service().create_mapping(
            actor_user_id=resolved[1].user_id,
            actor_session_id=resolved[1].session_id,
            plan_code=payload["planCode"],
            external_product_id=payload["externalProductId"],
            purchase_url=payload["purchaseUrl"],
            reason=payload["reason"],
            idempotency_key=key,
        )
        self._send_json(HTTPStatus.CREATED, {"ok": True, "mapping": result})

    def _handle_admin_grant_create(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None or not self._require_csrf(resolved[0]):
            return
        key = self._require_idempotency_key()
        if key is None or not self._bind_mutation_payload(str(resolved[1].user_id), "billing.admin_grant", key, payload):
            return
        if set(payload) != {"targetTenantId", "amount", "reason"} or not all(
            isinstance(payload.get(name), str) for name in payload
        ):
            raise ValueError("admin grant payload is invalid")
        result = self._retail_admin_service().grant(
            actor_user_id=resolved[1].user_id,
            actor_session_id=resolved[1].session_id,
            target_tenant_id=payload["targetTenantId"],
            amount=payload["amount"],
            reason=payload["reason"],
            idempotency_key=key,
        )
        self._send_json(HTTPStatus.CREATED, {"ok": True, "grant": result})

    def _handle_admin_fulfillment_action(self, fulfillment_id: str, action: str, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None or not self._require_csrf(resolved[0]):
            return
        if action == "recover":
            if payload:
                raise ValueError("recovery payload must be empty")
            result = self._fulfillment_service().recover(fulfillment_id)
            response: Any = {
                "fulfillmentId": str(result.fulfillment_id),
                "status": result.status,
                "creditedAmount": str(result.credited_amount),
                "affiliateAmount": str(result.affiliate_amount),
            }
        else:
            if set(payload) != {"reason"} or not isinstance(payload.get("reason"), str):
                raise ValueError("refund payload is invalid")
            response = self._fulfillment_service().refund(
                actor_user_id=resolved[1].user_id,
                fulfillment_id=fulfillment_id,
                reason=payload["reason"],
            )
        self._send_json(HTTPStatus.OK, {"ok": True, "result": response})

    def _handle_billing_balance(self) -> None:
        resolved = self._require_media_session()
        if resolved is None:
            return
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "balance": self._upstream_gateway().balance(str(resolved[1].tenant_id))},
        )

    def _handle_billing_usage(self) -> None:
        resolved = self._require_media_session()
        if resolved is None:
            return
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        try:
            limit = int((query.get("limit") or ["100"])[0])
        except ValueError as exc:
            raise ValueError("invalid usage limit") from exc
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "items": self._upstream_gateway().usage(str(resolved[1].tenant_id), limit=limit)},
        )

    def _handle_admin_billing_reconciliation(self) -> None:
        if self._require_admin_session() is None:
            return
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        try:
            limit = int((query.get("limit") or ["100"])[0])
        except ValueError as exc:
            raise ValueError("invalid reconciliation limit") from exc
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "items": self._upstream_gateway().reconciliation_queue(limit=limit)},
        )

    def _handle_admin_billing_summary(self) -> None:
        if self._require_admin_session() is None:
            return
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        try:
            limit = int((query.get("limit") or ["100"])[0])
        except ValueError as exc:
            raise ValueError("invalid billing summary limit") from exc
        self._send_json(HTTPStatus.OK, {"ok": True, **self._retail_admin_service().admin_summary(limit=limit)})

    def _handle_admin_billing_reconcile(self, operation_id: str, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None:
            return
        if payload:
            raise ValueError("reconciliation payload must be empty")
        if not self._require_csrf(resolved[0]):
            return
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "result": self._upstream_gateway().reconcile_operation(operation_id)},
        )

    def _handle_admin_upstream_credential_health(self) -> None:
        if self._require_admin_session() is None:
            return
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "credential": self._upstream_gateway().credential_health()},
        )

    def _handle_admin_upstream_credential_rotate(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None:
            return
        if payload:
            raise ValueError("rotation payload must be empty")
        if not self._require_csrf(resolved[0]):
            return
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "credential": self._upstream_gateway().rotate_credential()},
        )

    def _handle_admin_upstream_credential_revoke(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None:
            return
        if payload:
            raise ValueError("revoke payload must be empty")
        if not self._require_csrf(resolved[0]):
            return
        self._send_json(
            HTTPStatus.OK,
            {"ok": True, "credential": self._upstream_gateway().revoke_credential()},
        )

    def _handle_admin_registration_policy_update(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        token, session = resolved
        if not self._require_csrf(token):
            return
        idempotency_key = self._require_idempotency_key(maximum_length=96)
        if idempotency_key is None:
            return
        if set(payload) != {"registrationPolicyMode", "reason"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "注册策略请求字段无效。")
            return
        if not self._bind_mutation_payload(str(session.user_id), "registration.policy", idempotency_key, payload):
            return
        mode = payload.get("registrationPolicyMode")
        reason = payload.get("reason")
        if not isinstance(mode, str) or not isinstance(reason, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "注册策略请求格式无效。")
            return
        updated = service.admin_set_registration_policy(
            actor_user_id=session.user_id,
            actor_session_id=session.session_id,
            mode=mode,
            reason=reason,
        )
        self._send_json(HTTPStatus.OK, {"registrationPolicyMode": updated})

    def _handle_admin_admission_batches_get(self) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        page, page_size, _ = self._pagination()
        self._send_json(
            HTTPStatus.OK,
            service.admin_admission_batches(resolved[1].user_id, page=page, page_size=page_size),
        )

    def _handle_admin_admission_batch_create(self, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        token, session = resolved
        if not self._require_csrf(token):
            return
        idempotency_key = self._require_idempotency_key(maximum_length=96)
        if idempotency_key is None:
            return
        if set(payload) != {"name", "codeCount", "reason"}:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "准入码批次请求字段无效。")
            return
        if not self._bind_mutation_payload(str(session.user_id), "admission.batch.create", idempotency_key, payload):
            return
        name, count, reason = payload.get("name"), payload.get("codeCount"), payload.get("reason")
        if not isinstance(name, str) or not isinstance(count, int) or isinstance(count, bool) or not isinstance(reason, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "准入码批次请求格式无效。")
            return
        issue = service.admin_create_admission_batch(
            actor_user_id=session.user_id,
            actor_session_id=session.session_id,
            name=name,
            code_count=count,
            reason=reason,
        )
        self._send_json(
            HTTPStatus.CREATED,
            {"batchId": str(issue.batch_id), "codes": list(issue.codes)},
        )

    def _handle_admin_admission_batch_disable(self, batch_id: uuid.UUID, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        token, session = resolved
        if not self._require_csrf(token):
            return
        idempotency_key = self._require_idempotency_key(maximum_length=96)
        if idempotency_key is None:
            return
        reason = payload.get("reason")
        if set(payload) != {"reason"} or not isinstance(reason, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "禁用批次请求无效。")
            return
        if not self._bind_mutation_payload(
            str(session.user_id), f"admission.batch.disable:{batch_id}", idempotency_key, payload
        ):
            return
        service.admin_disable_admission_batch(
            actor_user_id=session.user_id,
            actor_session_id=session.session_id,
            batch_id=batch_id,
            reason=reason,
        )
        self._send_json(HTTPStatus.OK, {"ok": True})

    def _handle_admin_affiliate_users_get(self) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        page, page_size, search = self._pagination()
        self._send_json(
            HTTPStatus.OK,
            service.admin_affiliate_users(
                resolved[1].user_id,
                search=search,
                page=page,
                page_size=page_size,
            ),
        )

    def _handle_admin_affiliate_profile_update(
        self,
        target_user_id: uuid.UUID,
        payload: Mapping[str, Any],
    ) -> None:
        resolved = self._require_admin_session()
        service = self._require_registration_service()
        if resolved is None or service is None:
            return
        token, session = resolved
        if not self._require_csrf(token):
            return
        idempotency_key = self._require_idempotency_key(maximum_length=96)
        if idempotency_key is None:
            return
        allowed = {"signupEnabled", "signupQuota", "signupExpiresAt", "reason"}
        if set(payload) != allowed:
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "裂变权限请求字段无效。")
            return
        if not self._bind_mutation_payload(
            str(session.user_id), f"affiliate.profile:{target_user_id}", idempotency_key, payload
        ):
            return
        enabled = payload.get("signupEnabled")
        quota = payload.get("signupQuota")
        expires_value = payload.get("signupExpiresAt")
        reason = payload.get("reason")
        if (
            not isinstance(enabled, bool)
            or not isinstance(quota, int)
            or isinstance(quota, bool)
            or (expires_value is not None and not isinstance(expires_value, str))
            or not isinstance(reason, str)
        ):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "裂变权限请求格式无效。")
            return
        expires_at = None
        if expires_value is not None:
            try:
                expires_at = datetime.fromisoformat(expires_value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("affiliate expiry is invalid") from exc
        profile = service.admin_update_affiliate_profile(
            actor_user_id=session.user_id,
            actor_session_id=session.session_id,
            target_user_id=target_user_id,
            signup_enabled=enabled,
            signup_quota=quota,
            signup_expires_at=expires_at,
            reason=reason,
        )
        self._send_json(HTTPStatus.OK, service.profile_projection(profile))

    def _handle_admin_session_revoke_all(self, target_user_id: uuid.UUID, payload: Mapping[str, Any]) -> None:
        resolved = self._require_admin_session()
        if resolved is None or self.account_auth is None:
            return
        token, session = resolved
        if not self._require_csrf(token):
            return
        idempotency_key = self._require_idempotency_key(maximum_length=96)
        if idempotency_key is None:
            return
        reason = payload.get("reason")
        if set(payload) != {"reason"} or not isinstance(reason, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "管理员会话撤销请求无效。")
            return
        if not self._bind_mutation_payload(
            str(session.user_id), f"account.admin.sessions.revoke:{target_user_id}", idempotency_key, payload
        ):
            return
        revoked = self.account_auth.admin_revoke_user_sessions(token, target_user_id, reason)
        self._send_json(HTTPStatus.OK, {"ok": True, "revokedSessions": revoked})

    def _handle_capability_match(
        self,
        context: If2RequestContext,
        payload: Mapping[str, Any],
    ) -> None:
        tenant_id = str(context.principal.tenant_id)
        if not self._consume_rate_limit("media_mutation", f"{tenant_id}:{self._client_key()}"):
            return
        idempotency = context.idempotency
        assert idempotency is not None
        idempotency_key = idempotency.key
        expected_fields = {"query", "currentBot", "catalogVersion", "idempotencyKey"}
        if set(payload) != expected_fields or payload.get("idempotencyKey") != idempotency_key:
            self._send_api_error(HTTPStatus.CONFLICT, "idempotency_conflict", "幂等键与能力匹配请求不一致。")
            return
        query = payload.get("query")
        if not isinstance(query, str):
            self._send_api_error(HTTPStatus.BAD_REQUEST, "invalid_request", "能力匹配请求格式无效。")
            return
        match_payload = {
            "query": query.strip(),
            "currentBot": payload["currentBot"],
            "catalogVersion": payload["catalogVersion"],
        }
        if self.matcher is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "matcher_unavailable", "能力匹配服务暂时不可用。")
            return
        model_scope_id = "capability-match-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
        try:
            with self._upstream_gateway().bind(
                tenant_id,
                context.principal.user_public_id,
                model_scope_id,
                model_scope_id,
            ):
                result = self.matcher.match(match_payload)
                if result.get("pathStatus") == "matched":
                    if self.guidance_plan_service is None:
                        raise GuidancePlanError("matcher_unavailable", "能力引导服务暂时不可用。")
                    result = self.guidance_plan_service.register_match(
                        result,
                        query=str(match_payload.get("query") or ""),
                        current_bot=str(match_payload.get("currentBot") or ""),
                    )
        except CapabilityMatcherFailure as exc:
            self._send_api_error(HTTPStatus.BAD_REQUEST, exc.code, exc.message)
            return
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in {"invalid_request", "provider_unavailable", "invalid_model_response", "invalid_guidance_plan", "guidance_plan_conflict"}:
                status = HTTPStatus.BAD_REQUEST if code == "invalid_request" else HTTPStatus.SERVICE_UNAVAILABLE
                controlled_message = (
                    str(getattr(exc, "message", "") or "").strip()
                    if code == "invalid_request"
                    else "能力匹配调用未完成，底层详情未向当前接口公开。"
                )
                self._send_api_error(status, code, controlled_message)
                return
            raise
        self._send_json(HTTPStatus.OK, result)

    # The Media Web session schema is strict: binding/installation facts are
    # served as `organizationConnection` / `installationConnection` enums.
    _CONNECTION_PROJECTION = {
        "NOT_APPLICABLE": "not_applicable",
        "ACTIVE": "connected",
        "PENDING": "pending",
        "DISABLED": "disabled",
        "REVOKED": "revoked",
        "NEEDS_ATTENTION": "attention",
    }

    def _handle_media_session(self, context: If2RequestContext) -> None:
        if context.principal.role == "user":
            role = "ordinary"
        elif context.principal.role == "admin":
            role = "admin"
        else:
            raise RequestContextError("session principal role is invalid")
        binding_state, installation_state = self._binding_projection(context)
        is_personal = context.principal.workspace_mode == "personal_web"
        if role == "admin":
            route_grants = [
                "/admin/overview", "/admin/access", "/admin/tenants", "/admin/billing", "/admin/upstreams"
            ]
        elif context.principal.workspace_mode == "personal_web" and context.principal.body_authority == "internal":
            route_grants = [
                "/today", "/studio", "/campaigns", "/business", "/desk", "/overview", "/assets",
                "/tracks", "/decisions", "/publishing", "/reviews", "/media-agent", "/archives",
                "/usage-billing", "/invites", "/workspace",
            ]
        elif context.principal.workspace_mode == "organization_lark" and context.principal.body_authority == "lark":
            route_grants = ["/organization-workspace", "/tracks"]
        else:
            raise RequestContextError("session workspace authority is invalid")
        if is_personal:
            organization_name = None
        else:
            resolution = context.workspace_resolution
            candidate = getattr(resolution, "selected_workspace", None)
            organization_name = (
                getattr(candidate, "organization_name", None)
                or getattr(resolution, "organization_name", None)
                or "组织工作区"
            )
        self._send_json(
            HTTPStatus.OK,
            {
                "schemaVersion": "media_web_business_pages_v2",
                "revision": 1,
                "session": {
                    "publicUserId": context.principal.user_public_id,
                    "workspaceMode": context.principal.workspace_mode,
                    "editorMode": "web_edit" if is_personal else "lark_edit",
                    "bodyAuthority": context.principal.body_authority,
                    "organizationName": organization_name,
                    "memberRole": context.principal.member_role,
                    "organizationConnection": self._CONNECTION_PROJECTION.get(
                        binding_state, "attention"
                    ),
                    "installationConnection": self._CONNECTION_PROJECTION.get(
                        installation_state, "attention"
                    ),
                    "role": role,
                    "maintainer": context.principal.is_maintainer,
                    "csrfToken": context.csrf.response_token,
                    "expiresAt": context.principal.expires_at.isoformat(),
                    "routeGrants": route_grants,
                    "schemaVersion": "media_web_business_pages_v2",
                },
            },
        )

    @staticmethod
    def _binding_projection(context: If2RequestContext) -> tuple[str, str]:
        if context.principal.workspace_mode == "personal_web":
            return "NOT_APPLICABLE", "NOT_APPLICABLE"

        resolution = context.workspace_resolution
        candidate = None
        if resolution is not None:
            candidate = resolution.selected_workspace
            if candidate is None:
                candidate = next(
                    (
                        item
                        for item in resolution.candidates
                        if item.workspace_mode == "organization_lark"
                        and item.tenant_id == context.principal.tenant_id
                    ),
                    None,
                )
        raw_state = getattr(candidate, "binding_state", None)
        if raw_state is None:
            return "NEEDS_ATTENTION", "NEEDS_ATTENTION"
        normalized = str(raw_state).upper()
        if normalized == "ACTIVE":
            return "ACTIVE", "ACTIVE"
        if normalized == "PENDING":
            return "PENDING", "PENDING"
        if normalized in {"SUSPENDED", "DISABLED"}:
            return "DISABLED", "DISABLED"
        if normalized == "REVOKED":
            return "REVOKED", "REVOKED"
        return "NEEDS_ATTENTION", "NEEDS_ATTENTION"

    def _handle_media_capabilities(self) -> None:
        tenant_id = self._require_media_auth()
        if tenant_id is None:
            return
        if self.media_web_tasks is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "service_unavailable", "服务暂时不可用，请稍后重试。")
            return
        resolved = self._resolved_session()
        is_maintainer = resolved is not None and resolved[1].is_maintainer
        self._send_json(HTTPStatus.OK, self.media_web_tasks.capability_catalog(is_maintainer=is_maintainer))

    def _handle_media_task_events(
        self,
        task_id: str,
        *,
        tenant_id: str,
        user_public_id: str,
    ) -> None:
        if self.media_web_tasks is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "service_unavailable", "服务暂时不可用，请稍后重试。")
            return
        try:
            cursor = int(self.headers.get("Last-Event-ID", "0") or 0)
        except ValueError as exc:
            raise MediaWebTaskError("invalid_request", "事件游标无效。") from exc
        self.media_web_tasks.get_task(
            task_id, tenant_id=tenant_id, user_public_id=user_public_id
        )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        heartbeat_at = time.monotonic()
        try:
            while True:
                events = self.media_web_tasks.get_events(
                    task_id,
                    tenant_id=tenant_id,
                    user_public_id=user_public_id,
                    after=cursor,
                )
                for event in events:
                    cursor = int(event["eventId"])
                    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"id: {cursor}\nevent: {event['type']}\ndata: {encoded}\n\n".encode("utf-8"))
                if events:
                    self.wfile.flush()
                task = self.media_web_tasks.get_task(
                    task_id,
                    tenant_id=tenant_id,
                    user_public_id=user_public_id,
                )
                if task["status"] in TERMINAL_STATES and cursor >= int(task["eventCursor"]):
                    self.close_connection = True
                    return
                if time.monotonic() - heartbeat_at >= 15:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    heartbeat_at = time.monotonic()
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_media_service_error(self, exc: MediaWebTaskError) -> None:
        statuses = {
            "authentication_required": HTTPStatus.UNAUTHORIZED,
            "csrf_rejected": HTTPStatus.FORBIDDEN,
            "workspace_not_allowed": HTTPStatus.FORBIDDEN,
            "invalid_request": HTTPStatus.BAD_REQUEST,
            "required_input_missing": HTTPStatus.UNPROCESSABLE_ENTITY,
            "material_parsing_incomplete": HTTPStatus.UNPROCESSABLE_ENTITY,
            "capability_not_found": HTTPStatus.NOT_FOUND,
            "task_not_found": HTTPStatus.NOT_FOUND,
            "upload_not_found": HTTPStatus.NOT_FOUND,
            "account_relationship_unavailable": HTTPStatus.NOT_FOUND,
            "account_relationship_conflict": HTTPStatus.CONFLICT,
            "task_conflict": HTTPStatus.CONFLICT,
            "payload_too_large": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "rate_limited": HTTPStatus.TOO_MANY_REQUESTS,
            "identity_unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
            "model_transport_unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
            "model_quota_rejected": HTTPStatus.PAYMENT_REQUIRED,
            WRITER_CLOSED_ERROR_CODE: HTTPStatus.SERVICE_UNAVAILABLE,
        }
        self._send_api_error(
            statuses.get(exc.code, HTTPStatus.BAD_REQUEST),
            exc.code,
            exc.message,
            details=exc.details,
        )

    def _handle_tenant_assets(self) -> None:
        context = self._asset_context()
        if context is None:
            return
        if self.assets_service is None:
            raise AssetInternalError()
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        cursor_values = query.get("cursor") or []
        if len(cursor_values) > 1:
            raise AssetsError("invalid_request", "分页游标无效。", status=400)
        try:
            page_size = int((query.get("pageSize") or ["20"])[0])
        except ValueError as exc:
            raise AssetsError("invalid_request", "分页大小无效。", status=400) from exc
        search = (query.get("search") or [""])[0]
        self._send_json(
            HTTPStatus.OK,
            self.assets_service.list_assets(
                context,
                cursor=cursor_values[0] if cursor_values else None,
                page_size=page_size,
                search=search,
            ),
        )

    def _handle_tenant_asset_detail(self, public_asset_id: str) -> None:
        context = self._asset_context()
        if context is None:
            return
        if self.assets_service is None:
            raise AssetInternalError()
        self._send_json(HTTPStatus.OK, self.assets_service.get_asset(context, public_asset_id))

    def _handle_tenant_asset_preview(self, public_asset_id: str) -> None:
        context = self._asset_context()
        if context is None:
            return
        if self.asset_preview_service is None:
            raise AssetInternalError("asset preview is unavailable")
        preview = self.asset_preview_service.get_preview(context, public_asset_id)
        self._send_binary(HTTPStatus.OK, preview.body, content_type=preview.content_type)

    def _handle_document_resource(self, context: If2RequestContext, public_resource_id: str) -> None:
        if self.document_resource_service is None:
            raise RuntimeError("document resource service is unavailable")
        tenant_context = TenantContext(
            str(context.principal.tenant_id),
            context.principal.user_public_id,
            context.principal.role == "admin",
            context.admin_audit.reason if context.admin_audit else None,
        )
        resource = self.document_resource_service.get_resource(tenant_context, public_resource_id)
        disposition = "inline" if resource.content_type.startswith("image/") or resource.content_type == "application/pdf" else "attachment"
        self._send_binary(
            HTTPStatus.OK,
            resource.body,
            content_type=resource.content_type,
            headers={
                "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(resource.file_name)}",
                "X-Content-SHA256": resource.content_checksum,
            },
        )

    def _asset_context(self) -> TenantContext | None:
        resolved = self._require_media_session()
        if resolved is None:
            return None
        _token, session = resolved
        return TenantContext(
            tenant_id=str(session.tenant_id),
            user_public_id=str(session.user_id),
        )

    def _projection_page_query(self) -> tuple[str | None, int, str]:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        cursor_values = query.get("cursor") or []
        if len(cursor_values) > 1:
            raise TenantProjectionError("invalid_request", "分页游标无效。")
        try:
            page_size = int((query.get("pageSize") or ["20"])[0])
        except ValueError as exc:
            raise TenantProjectionError("invalid_request", "分页大小无效。") from exc
        return (cursor_values[0] if cursor_values else None), page_size, (query.get("search") or [""])[0]

    def _projection_service(self) -> TenantProjectionService:
        if self.tenant_projections is None:
            raise TenantProjectionError("projection_unavailable", "业务投影暂时不可用。")
        return self.tenant_projections

    def _send_projection(self, response: ProjectionResponse) -> None:
        headers = {
            "ETag": response.etag,
            "X-OpenClaw-Projection-Cache": "HIT" if response.cache_hit else "MISS",
            "X-OpenClaw-Projection-Queries": str(response.query_count),
            "X-OpenClaw-Projection-Gzip-Bytes": str(response.gzip_bytes),
        }
        if self.headers.get("If-None-Match") == response.etag:
            self._send_empty(HTTPStatus.NOT_MODIFIED, headers=headers)
            return
        self._send_json(HTTPStatus.OK, response.payload, headers=headers)

    def _tenant_projection_session(self) -> AccountSession | None:
        resolved = self._require_media_session()
        return None if resolved is None else resolved[1]

    def _handle_recent_activity(self) -> None:
        if self.tenant_activity is None:
            self._send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "activity_unavailable", "近期活动暂时不可用。")
            return
        session = self._tenant_projection_session()
        if session is None:
            return
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        requested = (query.get("tenantId") or [None])[0]
        try:
            limit = int((query.get("limit") or ["20"])[0])
        except ValueError as exc:
            raise TenantActivityAccessError("invalid_limit") from exc
        items = self.tenant_activity.list(
            session.tenant_id,
            requested_tenant_id=requested,
            limit=limit,
        )
        self._send_json(HTTPStatus.OK, {"schemaVersion": "media.stage1.recent-activity.v1", "items": items})

    def _handle_tenant_dashboard(self) -> None:
        session = self._tenant_projection_session()
        if session is None:
            return
        self._send_projection(
            self._projection_service().dashboard(str(session.tenant_id), scope="user")
        )

    def _handle_tenant_runs(self) -> None:
        session = self._tenant_projection_session()
        if session is None:
            return
        cursor, page_size, search = self._projection_page_query()
        self._send_projection(
            self._projection_service().runs(
                str(session.tenant_id),
                cursor=cursor,
                page_size=page_size,
                search=search,
                scope="user",
            )
        )

    def _handle_admin_tenant_runs(self) -> None:
        if self._require_admin_session() is None:
            return
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        targets = query.get("targetTenantId") or []
        if len(targets) != 1 or not targets[0].strip():
            self._send_api_error(
                HTTPStatus.BAD_REQUEST,
                "target_tenant_required",
                "必须明确指定目标租户。",
            )
            return
        cursor, page_size, search = self._projection_page_query()
        self._send_projection(
            self._projection_service().runs(
                targets[0],
                cursor=cursor,
                page_size=page_size,
                search=search,
                scope="admin",
            )
        )

    def _handle_tenant_run(self, public_run_id: str, section: str | None) -> None:
        session = self._tenant_projection_session()
        if session is None:
            return
        tenant_id = str(session.tenant_id)
        service = self._projection_service()
        response = (
            service.run_section(tenant_id, public_run_id, section, scope="user")
            if section is not None
            else service.run_base(tenant_id, public_run_id, scope="user")
        )
        self._send_projection(response)

    def _handle_tenant_projection_error(self, exc: TenantProjectionError) -> None:
        statuses = {
            "invalid_request": HTTPStatus.BAD_REQUEST,
            "invalid_tenant": HTTPStatus.BAD_REQUEST,
            "resource_not_found": HTTPStatus.NOT_FOUND,
            "projection_unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
        }
        self._send_api_error(statuses.get(exc.code, HTTPStatus.BAD_REQUEST), exc.code, exc.message)

    def _handle_stage2(self, mode: str, payload: dict[str, Any]) -> None:
        """Dispatch one Stage-2 write through the injected gateway.

        The transport only forwards operation data plus the opaque request
        credential; session, Binding, and trusted URLs stay server-resolved
        inside the gateway. Errors map to the locked stable-code contract.
        """

        try:
            if self.app is None:
                raise RuntimeError("stage2_unavailable")
            cookies: dict[str, str] = {}
            raw_cookie = self.headers.get("Cookie")
            if raw_cookie:
                session_values: list[str] = []
                for fragment in raw_cookie.split(";"):
                    name, separator, value = fragment.strip().partition("=")
                    if separator and name.casefold() == "openclaw_session":
                        session_values.append(value)
                if len(session_values) > 1:
                    raise Stage2GatewayError(
                        "authentication_invalid",
                        "检测到多个会话 Cookie，请只保留一个",
                        status=HTTPStatus.UNAUTHORIZED,
                    )
                if session_values:
                    cookies["openclaw_session"] = session_values[0]
            authorizations = self.headers.get_all("Authorization", failobj=[])
            if len(authorizations) > 1:
                raise Stage2GatewayError(
                    "authentication_invalid",
                    "multiple Authorization headers are not allowed",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            authorization = authorizations[0] if authorizations else None
            bearer_token = None
            if authorization is not None:
                try:
                    bearer_token = extract_session_token({"headers": {"Authorization": authorization}, "cookies": {}})
                except Stage2ServerContextError as exc:
                    raise _stage2_authentication_error(exc) from exc
            cookie_token = None
            if "openclaw_session" in cookies:
                try:
                    cookie_token = extract_session_token({"headers": {}, "cookies": cookies})
                except Stage2ServerContextError as exc:
                    raise _stage2_authentication_error(exc) from exc
            if bearer_token is not None and cookie_token is not None and bearer_token != cookie_token:
                raise Stage2GatewayError(
                    "authentication_invalid",
                    "conflicting request credentials are not allowed",
                    status=HTTPStatus.UNAUTHORIZED,
                )
            headers = {"Authorization": authorization} if authorization else {}
            with stage2_request_context({"headers": headers, "cookies": cookies}):
                receipt = self.app.process_stage2(mode, payload)
        except Stage2GatewayError as exc:
            self._send_json(
                HTTPStatus(exc.status),
                {"ok": False, "error": {"code": exc.code, "message": exc.message}},
            )
            return
        except Stage2RuntimeError as exc:
            status = _stage2_runtime_status(exc.code)
            self._send_json(status, {"ok": False, "error": {"code": exc.code, "message": exc.message}})
            return
        except RuntimeError as exc:
            if str(exc) == "stage2_unavailable":
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"ok": False, "error": {"code": "stage2_unavailable"}},
                )
                return
            raise
        self._send_json(HTTPStatus.OK, {"ok": True, "receipt": receipt})

    def _handle_qq_event(self, payload: dict[str, Any]) -> None:
        from .qq_bot_adapter import QQBotAdapter

        if self.app is None:
            raise RuntimeError("app not configured")
        adapter = QQBotAdapter(self.app)
        parsed = adapter.parse_event(payload)
        if not parsed.text.startswith("【"):
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "ignored": True,
                    "reason": "not_tag_protocol",
                    "text": parsed.text,
                    "chat_type": parsed.chat_type,
                },
            )
            return
        response = adapter.handle_event(parsed)
        response["ok"] = True
        response["ignored"] = False
        response["chat_type"] = parsed.chat_type
        response["user_id"] = parsed.user_id
        self._send_json(HTTPStatus.OK, response)


def make_server(
    host: str,
    port: int,
    app: OpenClawApp | None,
    *,
    auth_config: AuthConfig | None = None,
    account_auth: AccountAuthService | None = None,
    account_registration: AccountRegistrationService | None = None,
    personal_auth: PersonalAuthService | None = None,
    organization_auth_intent: OrganizationAuthIntentService | None = None,
    media_feishu_login: MediaFeishuLoginService | None = None,
    matcher: CapabilityMatcher | None = None,
    guidance_plan_service: GuidancePlanService | None = None,
    media_web_tasks: MediaWebTaskService | None = None,
    rate_limiter: SlidingWindowRateLimiter | None = None,
    tenant_model_gateway: TenantModelGateway | None = None,
    retail_admin_service: RetailAdminService | None = None,
    retail_fulfillment_service: RetailFulfillmentService | None = None,
    device_job_service: DeviceJobService | None = None,
    media_archive_service: MediaArchiveService | None = None,
    tenant_projection_service: TenantProjectionService | None = None,
    tenant_activity_service: TenantActivityAccessService | None = None,
    assets_service: AssetsService | None = None,
    asset_preview_service: AssetPreviewService | None = None,
    document_resource_service: DocumentResourceService | None = None,
    resource_access_service: ResourceAccessService | None = None,
    media_business_services: Mapping[str, Any] | None = None,
    media_business_dispatcher: MediaBusinessDispatcher | None = None,
    authority_config: HttpAuthorityConfig | None = None,
    workspace_resolver: WorkspaceResolver | None = None,
    stage1_provisioning: Stage1ProvisioningRuntime | None = None,
) -> ThreadingHTTPServer:
    if personal_auth is None and (auth_config is None) != (account_auth is None):
        raise ValueError("auth config and canonical account service must be configured together")
    if account_registration is not None and account_auth is None:
        raise ValueError("registration service requires canonical account authentication")
    if account_auth is not None and authority_config is None:
        raise ValueError("canonical account authentication requires explicit HTTP authority configuration")
    if personal_auth is not None and (auth_config is None or authority_config is None):
        raise ValueError("personal account authentication requires explicit auth and HTTP authority configuration")
    expected_service_keys = set(_IF2_OPERATION_SERVICE.values())
    if media_business_services is not None and set(media_business_services) != expected_service_keys:
        raise ValueError(
            "IF2 service composition mismatch: "
            f"missing={sorted(expected_service_keys - set(media_business_services))}, "
            f"extra={sorted(set(media_business_services) - expected_service_keys)}"
        )

    def execute_media_business(match: RouteMatch, request: Any) -> Any:
        request_handler, context, body = request
        return request_handler._execute_media_business(match, context, body)

    dispatcher = media_business_dispatcher or MediaBusinessDispatcher(
        {route.operation_id: execute_media_business for route in MEDIA_BUSINESS_ROUTE_BINDINGS}
    )
    if workspace_resolver is None and account_auth is not None:
        account_database = getattr(account_auth, "_database", None)
        if account_database is not None:
            workspace_resolver = WorkspaceResolver(account_auth, database=account_database)
    plan_service = guidance_plan_service or (getattr(app, "guidance_plan_service", None) if app is not None else None)
    task_service = media_web_tasks
    handler = type(
        "BoundOpenClawHttpHandler",
        (OpenClawHttpHandler,),
        {
            "app": app,
            "auth_config": auth_config,
            "account_auth": account_auth,
            "account_registration": account_registration,
            "personal_auth": personal_auth,
            "organization_auth_intent": organization_auth_intent,
            "media_feishu_login": media_feishu_login,
            "matcher": matcher,
            "guidance_plan_service": plan_service,
            "media_web_tasks": task_service,
            "tenant_model_gateway": tenant_model_gateway,
            "retail_admin": retail_admin_service,
            "retail_fulfillment": retail_fulfillment_service,
            "device_job_service": device_job_service,
            "media_archive_service": media_archive_service,
            "tenant_projections": tenant_projection_service,
            "tenant_activity": tenant_activity_service,
            "assets_service": assets_service,
            "asset_preview_service": asset_preview_service,
            "document_resource_service": document_resource_service,
            "resource_access": resource_access_service,
            "media_business_dispatcher": dispatcher,
            "media_business_services": dict(media_business_services or {}),
            "authority_config": authority_config,
            "ephemeral_default_authority": None,
            "rate_limiter": rate_limiter or SlidingWindowRateLimiter(),
            "mutation_bindings": MutationIdempotencyBindings(
                fingerprint_key=auth_config.session_secret if auth_config is not None else None
            ),
            "workspace_resolver": workspace_resolver,
            "stage1_provisioning": stage1_provisioning,
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    effective_authority, fallback_authority = _authority_for_bound_server(
        host,
        port,
        server.server_address[1],
        authority_config,
    )
    server.RequestHandlerClass.authority_config = effective_authority
    server.RequestHandlerClass.ephemeral_default_authority = fallback_authority
    server.media_web_tasks = task_service  # type: ignore[attr-defined]
    return server
