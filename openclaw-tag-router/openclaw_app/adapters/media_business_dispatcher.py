from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from .media_business_context import If2Route, Permission


CANONICAL_PREFIX = "/openclaw/media/api"
LEGACY_PREFIX = "/media/api"
EXPECTED_OPERATION_COUNT = 90
DEFAULT_MUTATION_BODY_LIMIT_BYTES = 2 * 1024 * 1024
UPLOAD_BODY_LIMIT_BYTES = 70 * 1024 * 1024
EXCLUDED_OPERATION_IDS = frozenset(
    {
        "pipeline_list",
        "pair_code_create",
        "device_pair",
        "device_list",
        "device_heartbeat",
        "device_revoke",
        "job_create",
        "job_list",
        "job_detail",
        "job_lease",
        "job_ack",
        "job_start",
        "job_result",
        "cli_release_compatibility",
        "archive_commit",
        "archive_list",
        "archive_detail",
        "archive_delete_plan",
        "archive_delete",
        "archive_readback",
    }
)


class DispatcherContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteSpec:
    method: str
    relative_path: str
    operation_id: str
    permission: Permission = "ordinary-session"
    body_limit_bytes: int | None = None
    request_schema: str | None = None
    allowed_statuses: frozenset[int] = frozenset({200, 401, 403, 500})

    @property
    def context_route(self) -> If2Route:
        return If2Route(
            operation_id=self.operation_id,
            method=self.method,  # type: ignore[arg-type]
            route_template=self.relative_path,
            permission=self.permission,
            mutation=self.method != "GET",
            body_limit_bytes=self.body_limit_bytes,
            request_schema=self.request_schema,
            allowed_statuses=self.allowed_statuses,
        )


@dataclass(frozen=True)
class RouteMatch:
    route: RouteSpec
    operation_id: str
    path_parameters: Mapping[str, str]


Handler = Callable[[RouteMatch, Any], Any]


# Direct transcription of accepted IF2 contract route bindings.
_DECLARED_MEDIA_BUSINESS_ROUTE_BINDINGS = (
    RouteSpec("GET", "/session", "getMediaSession"),
    RouteSpec("GET", "/capabilities", "listMediaCapabilities"),
    RouteSpec("POST", "/capability-match", "matchMediaCapability"),
    RouteSpec("POST", "/uploads", "createMediaUpload"),
    RouteSpec("GET", "/tasks", "listMediaTasks"),
    RouteSpec("POST", "/tasks", "createMediaTask"),
    RouteSpec("GET", "/tasks/{taskId}", "getMediaTask"),
    RouteSpec("GET", "/tasks/{taskId}/events", "listMediaTaskEvents"),
    RouteSpec("POST", "/tasks/{taskId}/cancel", "cancelMediaTask"),
    RouteSpec("POST", "/tasks/{taskId}/confirm", "confirmMediaTask"),
    RouteSpec("GET", "/dashboard", "getDashboard"),
    RouteSpec("GET", "/content-projects", "listContentProjects"),
    RouteSpec("GET", "/content-projects/{publicProjectId}/artifacts", "listProjectArtifacts"),
    RouteSpec("POST", "/content-projects/{publicProjectId}/summaries", "createProjectSummary"),
    RouteSpec("GET", "/tracks", "listTracks"),
    RouteSpec("GET", "/tracks/{publicTrackId}", "getTrack"),
    RouteSpec("GET", "/creators", "listCreators"),
    RouteSpec("GET", "/creators/{publicCreatorId}", "getCreator"),
    RouteSpec("GET", "/track-relationships", "listTrackRelationships"),
    RouteSpec("PUT", "/track-relationships/{publicRelationshipId}", "updateTrackRelationshipStatus"),
    RouteSpec("GET", "/owned-accounts", "listOwnedAccounts"),
    RouteSpec("GET", "/owned-accounts/{publicAccountId}", "getOwnedAccount"),
    RouteSpec("GET", "/owned-accounts/{publicAccountId}/track-strategy", "getAccountTrackStrategy"),
    RouteSpec("GET", "/owned-accounts/{publicAccountId}/monitor", "getAccountMonitor", allowed_statuses=frozenset({200, 401, 403, 404, 500, 503})),
    RouteSpec("PUT", "/owned-accounts/{publicAccountId}/monitor", "updateAccountMonitor", allowed_statuses=frozenset({200, 400, 401, 403, 404, 409, 500, 503})),
    RouteSpec("POST", "/owned-accounts/{publicAccountId}/monitor/poll", "pollAccountMonitor", allowed_statuses=frozenset({200, 400, 401, 403, 404, 409, 500, 503})),
    RouteSpec("GET", "/assets", "listAssets"),
    RouteSpec("GET", "/assets/{publicAssetId}", "getAsset"),
    RouteSpec("GET", "/assets/{publicAssetId}/preview", "getAssetPreview"),
    RouteSpec("GET", "/document-resources/{publicResourceId}", "getDocumentResource"),
    RouteSpec("GET", "/decisions", "listDecisions"),
    RouteSpec("GET", "/decisions/{publicDecisionId}", "getDecision"),
    RouteSpec("GET", "/decision-signals", "listDecisionSignals"),
    RouteSpec("POST", "/decisions/{publicDecisionId}/confirm", "confirmDecision"),
    RouteSpec("GET", "/runs", "listRuns"),
    RouteSpec("GET", "/runs/{publicRunId}", "getRun"),
    RouteSpec("GET", "/runs/{publicRunId}/sources", "getRunSources"),
    RouteSpec("GET", "/runs/{publicRunId}/decisions", "getRunDecisions"),
    RouteSpec("GET", "/runs/{publicRunId}/outputs", "getRunOutputs"),
    RouteSpec("GET", "/business-opportunities", "listBusinessOpportunities"),
    RouteSpec("POST", "/artifacts/{publicArtifactId}/revisions", "createArtifactRevision"),
    RouteSpec("GET", "/publishing/packages", "listPublishingPackages"),
    RouteSpec("GET", "/publishing/packages/{publicPackageId}", "getPublishingPackage"),
    RouteSpec("PUT", "/publishing/packages/{publicPackageId}/checks", "updatePublishingChecks"),
    RouteSpec("POST", "/published-posts", "createPublishedPost"),
    RouteSpec("GET", "/published-posts/{publicPostId}", "getPublishedPost"),
    RouteSpec("GET", "/resources/docx-link", "getResourceDocxLink"),
    RouteSpec("GET", "/reviews", "listReviews"),
    RouteSpec("POST", "/reviews", "createReview"),
    RouteSpec("GET", "/reviews/summary", "getReviewsSummary"),
    RouteSpec("GET", "/metrics/content", "listContentMetrics"),
    RouteSpec("GET", "/metrics/accounts", "listAccountMetrics"),
    RouteSpec("POST", "/metric-imports", "createMetricImport"),
    RouteSpec("POST", "/reviews/{publicReviewId}/confirm", "confirmReview"),
    RouteSpec("GET", "/billing/balance", "getBillingBalance"),
    RouteSpec("GET", "/billing/balance-packs", "listBillingBalancePacks"),
    RouteSpec("GET", "/billing/usage", "listBillingUsage"),
    RouteSpec("GET", "/billing/usage-summary", "getBillingUsageSummary"),
    RouteSpec("POST", "/billing/redeem", "redeemBillingCode"),
    RouteSpec("GET", "/account/affiliate", "getAffiliateProfile"),
    RouteSpec("GET", "/account/invitees", "listInvitees"),
    RouteSpec("GET", "/admin/dashboard", "getAdminDashboard"),
    RouteSpec("GET", "/admin/affiliate-users", "listAdminAffiliateUsers"),
    RouteSpec("PUT", "/admin/affiliate-users/{userId}", "updateAdminAffiliateUser"),
    RouteSpec("GET", "/admin/admission-batches", "listAdminAdmissionBatches"),
    RouteSpec("POST", "/admin/admission-batches", "createAdminAdmissionBatch"),
    RouteSpec("POST", "/admin/admission-batches/{batchId}/disable", "disableAdminAdmissionBatch"),
    RouteSpec("GET", "/admin/registration-policy", "getAdminRegistrationPolicy"),
    RouteSpec("PUT", "/admin/registration-policy", "updateAdminRegistrationPolicy"),
    RouteSpec("POST", "/admin/users/{userId}/sessions/revoke-all", "revokeAdminUserSessions"),
    RouteSpec("GET", "/admin/tenants", "listAdminTenants"),
    RouteSpec("GET", "/admin/tenants/{publicTenantId}", "getAdminTenant"),
    RouteSpec("GET", "/admin/tenants/{publicTenantId}/runs", "listAdminTenantRuns"),
    RouteSpec("GET", "/admin/billing/summary", "getAdminBillingSummary"),
    RouteSpec("POST", "/admin/billing/product-mappings", "createAdminProductMapping"),
    RouteSpec("POST", "/admin/billing/grants", "createAdminBillingGrant"),
    RouteSpec("POST", "/admin/billing/redemption-batches", "createAdminRedemptionBatch"),
    RouteSpec("POST", "/admin/billing/fulfillments/{fulfillmentId}/recover", "recoverAdminFulfillment"),
    RouteSpec("POST", "/admin/billing/fulfillments/{fulfillmentId}/refund", "refundAdminFulfillment"),
    RouteSpec("GET", "/admin/upstreams", "getAdminUpstreams"),
    RouteSpec("POST", "/admin/billing/reconciliation/{operationId}", "reconcileAdminBillingOperation"),
    RouteSpec("POST", "/admin/upstream-credential/rotate", "rotateAdminUpstreamCredential"),
    RouteSpec("POST", "/admin/upstream-credential/revoke", "revokeAdminUpstreamCredential"),
    RouteSpec("GET", "/admin/platform-cookies", "getAdminPlatformCookies"),
    RouteSpec("GET", "/documents/{publicArtifactId}/body", "getDocumentBody"),
    RouteSpec("PUT", "/documents/{publicArtifactId}/draft", "saveDocumentDraft"),
    RouteSpec("GET", "/documents/{publicArtifactId}/revisions/{revision}", "getDocumentRevision"),
    RouteSpec("POST", "/documents/{publicArtifactId}/exports", "createDocumentExport"),
    RouteSpec("GET", "/document-exports/{publicExportId}", "getDocumentExport"),
    RouteSpec("GET", "/document-exports/{publicExportId}/download", "getDocumentExportDownload"),
)


_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts/media_web_business_pages.openapi.yaml"


def _contract_route_bindings() -> tuple[RouteSpec, ...]:
    try:
        document = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DispatcherContractError(f"cannot load accepted IF2 OpenAPI contract: {exc}") from exc
    if document.get("servers") != [{"url": CANONICAL_PREFIX}]:
        raise DispatcherContractError("IF2 OpenAPI server prefix is not canonical")
    bindings: list[RouteSpec] = []
    for relative_path, path_item in (document.get("paths") or {}).items():
        for method in ("get", "post", "put"):
            operation = path_item.get(method)
            if operation is None:
                continue
            request_schema = None
            request_body = operation.get("requestBody") or {}
            schema = ((request_body.get("content") or {}).get("application/json") or {}).get("schema") or {}
            reference = schema.get("$ref")
            if isinstance(reference, str):
                request_schema = reference.rsplit("/", 1)[-1]
            try:
                statuses = frozenset(int(value) for value in operation["responses"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DispatcherContractError("IF2 operation response statuses are invalid") from exc
            bindings.append(
                RouteSpec(
                    method.upper(),
                    relative_path,
                    operation["operationId"],
                    operation["x-permission"],
                    (
                        None
                        if method == "get"
                        else UPLOAD_BODY_LIMIT_BYTES
                        if operation["operationId"] == "createMediaUpload"
                        else DEFAULT_MUTATION_BODY_LIMIT_BYTES
                    ),
                    request_schema,
                    statuses,
                )
            )
    declared = {
        (route.method, route.relative_path, route.operation_id)
        for route in _DECLARED_MEDIA_BUSINESS_ROUTE_BINDINGS
    }
    contracted = {(route.method, route.relative_path, route.operation_id) for route in bindings}
    if declared != contracted:
        raise DispatcherContractError(
            f"OpenAPI route drift: missing={sorted(contracted - declared)}, extra={sorted(declared - contracted)}"
        )
    return tuple(bindings)


MEDIA_BUSINESS_ROUTE_BINDINGS = _contract_route_bindings()


@dataclass(frozen=True)
class _CompiledRoute:
    spec: RouteSpec
    pattern: re.Pattern[str]


def _compile_template(relative_path: str) -> re.Pattern[str]:
    if not relative_path.startswith("/") or relative_path == "/":
        raise DispatcherContractError(f"invalid IF2 path template: {relative_path!r}")
    cursor = 0
    parts: list[str] = ["^"]
    names: set[str] = set()
    for match in re.finditer(r"\{([A-Za-z][A-Za-z0-9_]*)\}", relative_path):
        name = match.group(1)
        if name in names:
            raise DispatcherContractError(f"duplicate path parameter {name!r} in {relative_path!r}")
        names.add(name)
        parts.append(re.escape(relative_path[cursor : match.start()]))
        parts.append(f"(?P<{name}>[^/]+)")
        cursor = match.end()
    parts.append(re.escape(relative_path[cursor:]))
    parts.append("$")
    return re.compile("".join(parts))


def validate_media_business_route_bindings(
    bindings: Iterable[RouteSpec],
    expected: Iterable[tuple[str, str, str]] | None = None,
) -> tuple[RouteSpec, ...]:
    routes = tuple(bindings)
    operation_ids = [route.operation_id for route in routes]
    route_keys = [(route.method, route.relative_path) for route in routes]
    route_shapes = [
        (route.method, re.sub(r"\{[A-Za-z][A-Za-z0-9_]*\}", "{}", route.relative_path))
        for route in routes
    ]
    if len(routes) != EXPECTED_OPERATION_COUNT:
        raise DispatcherContractError(f"IF2 must register exactly 88 routes, found {len(routes)}")
    if len(set(operation_ids)) != len(operation_ids):
        raise DispatcherContractError("IF2 contains duplicate operationIds")
    if len(set(route_keys)) != len(route_keys):
        raise DispatcherContractError("IF2 contains duplicate method/path registrations")
    if len(set(route_shapes)) != len(route_shapes):
        raise DispatcherContractError("IF2 contains overlapping method/path templates")
    if any(route.method not in {"GET", "POST", "PUT"} for route in routes):
        raise DispatcherContractError("IF2 contains an unsupported HTTP method")
    if not set(operation_ids).isdisjoint(EXCLUDED_OPERATION_IDS):
        raise DispatcherContractError("IF2 contains an excluded R1 or archive operationId")
    if expected is not None:
        actual = {(route.operation_id, route.method, route.relative_path) for route in routes}
        frozen_expected = {(operation_id, method.upper(), path) for operation_id, method, path in expected}
        if actual != frozen_expected:
            raise DispatcherContractError(
                f"OpenAPI route drift: missing={sorted(frozen_expected - actual)}, extra={sorted(actual - frozen_expected)}"
            )
    return routes


_VALIDATED_BINDINGS = validate_media_business_route_bindings(MEDIA_BUSINESS_ROUTE_BINDINGS)
_COMPILED_BINDINGS = tuple(
    _CompiledRoute(route, _compile_template(route.relative_path)) for route in _VALIDATED_BINDINGS
)


def _relative_path(path: str, prefix: str) -> str | None:
    if path == prefix:
        return "/"
    if path.startswith(prefix + "/"):
        return path[len(prefix) :]
    return None


def _matching_routes(method: str, absolute_path: str) -> list[_CompiledRoute]:
    relative = _relative_path(urlsplit(absolute_path).path, CANONICAL_PREFIX)
    if relative is None:
        return []
    if re.search(r"%(?![0-9A-Fa-f]{2})", relative):
        raise ValueError("malformed percent encoding in IF2 request path")
    return [
        route
        for route in _COMPILED_BINDINGS
        if route.spec.method == method.upper() and route.pattern.fullmatch(relative)
    ]


def resolve_media_business_operation(method: str, absolute_path: str) -> RouteMatch | None:
    routes = _matching_routes(method, absolute_path)
    if not routes:
        return None
    if len(routes) != 1:
        raise DispatcherContractError("multiple IF2 routes matched one request")
    route = routes[0]
    relative = _relative_path(urlsplit(absolute_path).path, CANONICAL_PREFIX)
    assert relative is not None
    raw_match = route.pattern.fullmatch(relative)
    assert raw_match is not None
    parameters = {name: unquote(value) for name, value in raw_match.groupdict().items()}
    if any("/" in value or "\\" in value or "\x00" in value or value in {".", ".."} for value in parameters.values()):
        raise ValueError("encoded separators, dot segments, and NUL bytes are not valid IF2 path parameters")
    return RouteMatch(route.spec, route.spec.operation_id, parameters)


def is_legacy_if2_business_request(method: str, absolute_path: str) -> bool:
    path = urlsplit(absolute_path).path
    relative = _relative_path(path, LEGACY_PREFIX)
    if relative is None:
        return False
    canonical = CANONICAL_PREFIX + relative
    return resolve_media_business_operation(method, canonical) is not None


class MediaBusinessDispatcher:
    def __init__(self, handlers: Mapping[str, Handler]) -> None:
        expected = {route.operation_id for route in _VALIDATED_BINDINGS}
        provided = set(handlers)
        if expected != provided:
            raise DispatcherContractError(
                f"IF2 handler mismatch: missing={sorted(expected - provided)}, extra={sorted(provided - expected)}"
            )
        self._handlers = dict(handlers)

    @property
    def operation_ids(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def dispatch(self, method: str, absolute_path: str, request: Any) -> tuple[bool, Any]:
        match = resolve_media_business_operation(method, absolute_path)
        if match is None:
            return False, None
        return True, self._handlers[match.operation_id](match, request)
