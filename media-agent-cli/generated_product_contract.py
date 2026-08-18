"""Generated from openclaw-media-product-contract.json. Do not edit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, Protocol, Required, TypedDict, cast
from urllib.parse import quote

class PipelineListRequest(TypedDict):
    cursor: NotRequired[str]
    limit: NotRequired[int]

class PipelineListResponse(TypedDict):
    pipelines: Required[list[PipelineSummary]]
    next_cursor: Required[str | None]

class PipelineSummary(TypedDict):
    pipeline_id: Required[str]
    version: Required[str]
    display_name: Required[str]
    catalog_digest: Required[str]

class PairCodeCreateRequest(TypedDict):
    device_label: Required[str]
    expires_in_seconds: Required[int]

class PairCodeCreateResponse(TypedDict):
    pair_code: Required[str]
    expires_at: Required[str]

class DevicePairRequest(TypedDict):
    pair_code: Required[str]
    device_label: Required[str]
    device_platform: Required[Literal['macos']]
    client_version: Required[str]

class DevicePairResponse(TypedDict):
    device: Required[Device]
    device_credential: Required[str]

class DeviceListRequest(TypedDict):
    cursor: NotRequired[str]
    limit: NotRequired[int]

class DeviceListResponse(TypedDict):
    devices: Required[list[Device]]
    next_cursor: Required[str | None]

class DeviceHeartbeatRequest(TypedDict):
    observed_at: Required[str]
    client_version: Required[str]
    api_version: Required[str]
    catalog_digest: Required[str]
    capabilities: NotRequired[list[str]]
    expected_revision: Required[int]

class DeviceHeartbeatResponse(TypedDict):
    device_id: Required[str]
    accepted_at: Required[str]
    revision: Required[int]
    state: Required[Literal['paired', 'online', 'revoked']]
    accepted_client_version: Required[str]
    catalog_digest: Required[str]
    api_compatible: Required[bool]
    catalog_compatible: Required[bool]
    claimable_job: Required[ClaimableJob | None]

class DeviceRevokeRequest(TypedDict):
    expected_revision: Required[int]

class DeviceRevokeResponse(TypedDict):
    device_id: Required[str]
    revoked_at: Required[str]

class JobCreateRequest(TypedDict):
    pipeline_id: Required[str]
    pipeline_version: Required[str]
    catalog_digest: Required[str]
    device_id: Required[str]
    input_refs: Required[list[str]]
    output_selection: Required[list[str]]
    confirmation_ref: NotRequired[str]

class JobCreateResponse(TypedDict):
    job: Required[LocalAgentJob]

class JobListRequest(TypedDict):
    cursor: NotRequired[str]
    limit: NotRequired[int]
    state: NotRequired[str]

class JobListResponse(TypedDict):
    jobs: Required[list[LocalAgentJob]]
    next_cursor: Required[str | None]

class JobDetailResponse(TypedDict):
    job: Required[LocalAgentJob]

class JobLeaseRequest(TypedDict):
    lease_seconds: Required[int]
    expected_revision: Required[int]

class JobLeaseResponse(TypedDict):
    job: Required[LocalAgentJob]

class JobAckRequest(TypedDict):
    ack_ref: Required[str]
    expected_revision: Required[int]

class JobAckResponse(TypedDict):
    job: Required[LocalAgentJob]

class JobStartRequest(TypedDict):
    start_ref: Required[str]
    expected_revision: Required[int]

class JobStartResponse(TypedDict):
    job: Required[LocalAgentJob]

class JobResultRequest(TypedDict):
    result_status: Required[Literal['succeeded', 'blocked', 'failed']]
    result_refs: Required[list[str]]
    artifact_refs: NotRequired[list[str]]
    failure_code: NotRequired[str | None]
    expected_revision: Required[int]

class JobResultResponse(TypedDict):
    job: Required[LocalAgentJob]

class ArchiveCommitRequest(TypedDict):
    run_id: Required[str]
    manifest: Required[ArchiveManifest]
    confirmation_ref: Required[str]

class ArchiveCommitResponse(TypedDict):
    archive: Required[ArchiveRecord]
    commit_receipt: Required[ArchiveCommitReceipt]
    readback_receipt: Required[ArchiveReadbackReceipt]

class ArchiveListRequest(TypedDict):
    cursor: NotRequired[str]
    limit: NotRequired[int]
    state: NotRequired[str]

class ArchiveListResponse(TypedDict):
    archives: Required[list[ArchiveRecord]]
    next_cursor: Required[str | None]

class ArchiveDetailResponse(TypedDict):
    archive: Required[ArchiveRecord]

class ArchiveDeletePlanResponse(TypedDict):
    delete_plan_id: Required[str]
    archive_id: Required[str]
    expires_at: Required[str]

class ArchiveDeleteRequest(TypedDict):
    delete_plan_id: Required[str]
    confirmation_ref: Required[str]
    expected_revision: Required[int]

class ArchiveDeleteResponse(TypedDict):
    archive_id: Required[str]
    state: Required[Literal['deleted', 'delete_failed']]
    delete_receipt: Required[ArchiveDeleteReceipt]
    hard_deleted: Required[Literal[True]]

class ArchiveReadbackRequest(TypedDict):
    readback_receipt_ref: Required[str]
    observed_refs: NotRequired[list[str]]

class ArchiveReadbackResponse(TypedDict):
    archive: Required[ArchiveRecord | None]
    verified: Required[bool]
    readback_receipt: Required[ArchiveReadbackReceipt]
    hard_deleted: Required[bool]

class CLIReleaseCompatibilityRequest(TypedDict):
    cli_version: Required[str]
    platform: Required[Literal['macos']]
    python_version: Required[str]
    catalog_digest: Required[str]
    api_version: Required[str]

class CLIReleaseCompatibilityResponse(TypedDict):
    compatible: Required[bool]
    min_cli_version: Required[str]
    supported_python: Required[str]
    supported_platforms: Required[list[str]]

class Device(TypedDict):
    device_id: Required[str]
    state: Required[Literal['paired', 'online', 'revoked']]
    device_label: Required[str]
    device_platform: Required[Literal['macos']]
    client_version: Required[str]
    capabilities: Required[list[str]]
    revision: Required[int]
    last_seen_at: Required[str | None]

class LocalAgentJob(TypedDict):
    job_id: Required[str]
    state: Required[Literal['queued', 'leased', 'acknowledged', 'running', 'succeeded', 'blocked', 'failed', 'expired', 'cancelled']]
    pipeline_id: Required[str]
    pipeline_version: Required[str]
    catalog_digest: Required[str]
    device_id: Required[str | None]
    input_refs: Required[list[str]]
    output_selection: Required[list[str]]
    confirmation_ref: Required[str | None]
    revision: Required[int]
    lease_id: Required[str | None]
    lease_expires_at: Required[str | None]
    ack_ref: Required[str | None]
    acknowledged_at: Required[str | None]
    start_ref: Required[str | None]
    started_at: Required[str | None]
    result_status: Required[Literal['succeeded', 'blocked', 'failed', None]]
    result_refs: Required[list[str]]
    artifact_refs: Required[list[str]]
    failure_code: Required[str | None]
    created_at: Required[str]
    updated_at: Required[str]
    leased_at: Required[str | None]
    completed_at: Required[str | None]

class ArchiveContent(TypedDict):
    encoding: Required[Literal['utf8', 'base64']]
    value: Required[str]

class ArchiveArtifact(TypedDict):
    ref: Required[str]
    mode: Required[Literal['content', 'descriptor_only', 'forbidden']]
    mime_type: Required[str]
    sha256: Required[str]
    size_bytes: Required[int]
    descriptor: Required[bool]
    metadata: Required[dict[str, Any]]
    content: Required[ArchiveContent | None]

class ClaimableJob(TypedDict):
    job_id: Required[str]
    state: Required[Literal['queued', 'leased', 'acknowledged', 'running', 'succeeded', 'blocked', 'failed', 'expired', 'cancelled']]

class ArchiveManifest(TypedDict):
    manifest_id: Required[str]
    run_id: Required[str]
    confirmation_ref: Required[str]
    items: Required[list[ArchiveArtifact]]
    created_at: Required[str]

class ArchiveProjection(TypedDict):
    projection_id: Required[str]
    kind: Required[Literal['db', 'attachment', 'web']]
    ref: Required[str]
    artifact_refs: Required[list[str]]
    consistent: Required[bool]

class ArchiveReadbackReceipt(TypedDict):
    receipt_ref: Required[str]
    archive_id: Required[str]
    verified: Required[bool]
    db_present: Required[bool]
    attachments_present: Required[bool]
    projections_present: Required[bool]
    checked_at: Required[str]

class ArchiveCommitReceipt(TypedDict):
    commit_id: Required[str]
    manifest_id: Required[str]
    archive_id: Required[str]
    artifact_refs: Required[list[str]]
    total_bytes: Required[int]
    cloud_bytes: Required[int]
    media_cloud_bytes: Required[Literal[0]]
    committed_at: Required[str]

class ArchiveDeleteReceipt(TypedDict):
    receipt_ref: Required[str]
    archive_id: Required[str]
    deleted_artifact_refs: Required[list[str]]
    deleted_projection_refs: Required[list[str]]
    verified: Required[bool]
    hard_deleted: Required[Literal[True]]
    deleted_at: Required[str]

class ArchiveRecord(TypedDict):
    archive_id: Required[str]
    state: Required[Literal['active', 'deleting', 'delete_failed']]
    commit_id: Required[str]
    manifest_id: Required[str]
    run_id: Required[str]
    pipeline_id: Required[str | None]
    pipeline_version: Required[str | None]
    device_id: Required[str | None]
    artifacts: Required[list[ArchiveArtifact]]
    projections: Required[list[ArchiveProjection]]
    cloud_bytes: Required[int]
    media_cloud_bytes: Required[Literal[0]]
    revision: Required[int]
    created_at: Required[str]
    updated_at: Required[str]

API_BASE = '/openclaw/media/api'
RELEASE_PLATFORMS = ('macos',)
OBJECT_IDS = {
    'PipelineDefinition': 'pipeline_id',
    'Device': 'device_id',
    'LocalAgentJob': 'job_id',
    'ArchiveRecord': 'archive_id',
    'CLIRelease': 'release_id',
    'ProviderConfig': 'provider_config_id',
    'LocalWorkspace': 'workspace_id',
    'LocalAnalysisRun': 'run_id',
    'LocalArtifact': 'artifact_id',
    'ArchiveManifest': 'manifest_id'
}
WEB_ROUTES = ('/overview', '/tracks', '/assets', '/runs', '/runs/:runId', '/publishing', '/reviews', '/media-agent', '/archives')
ROUTE_OBJECTS = {
    '/overview': 'ArchiveRecord',
    '/tracks': 'ArchiveRecord',
    '/assets': 'LocalArtifact',
    '/runs': 'LocalAgentJob',
    '/runs/:runId': 'LocalAgentJob',
    '/publishing': 'ArchiveRecord',
    '/reviews': 'ArchiveRecord',
    '/media-agent': 'LocalWorkspace',
    '/archives': 'ArchiveRecord'
}
LOCAL_COLLABORATION = {
    'surfaces': [
        '/media-agent',
        '/archives'
    ],
    'media_bytes': 'local_only',
    'api_consumption': 'generated_client_only'
}
STATE_MACHINES = {
    'MediaProject': [
        'captured',
        'planned',
        'edit_ready',
        'editing',
        'final_ready',
        'published'
    ],
    'MediaWebTask': [
        'queued',
        'awaiting_confirmation',
        'succeeded',
        'pending_manual',
        'failed',
        'cancelled'
    ],
    'LocalAgentJob': [
        'queued',
        'leased',
        'acknowledged',
        'running',
        'succeeded',
        'blocked',
        'failed',
        'expired',
        'cancelled'
    ],
    'LocalAnalysisRun': [
        'created',
        'validating',
        'preprocessing',
        'analyzing',
        'rendering',
        'reviewing',
        'ready_to_archive',
        'succeeded',
        'pending_manual',
        'failed',
        'cancelled'
    ],
    'ArchiveCommit': [
        'draft',
        'committing',
        'verifying',
        'archived',
        'failed',
        'cancelled'
    ],
    'ArchiveRecord': [
        'active',
        'deleting',
        'delete_failed'
    ]
}
OPERATION_IDS = ('pipeline_list', 'pair_code_create', 'device_pair', 'device_list', 'device_heartbeat', 'device_revoke', 'job_create', 'job_list', 'job_detail', 'job_lease', 'job_ack', 'job_start', 'job_result', 'archive_commit', 'archive_list', 'archive_detail', 'archive_delete_plan', 'archive_delete', 'archive_readback', 'cli_release_compatibility')
OperationId = Literal['pipeline_list', 'pair_code_create', 'device_pair', 'device_list', 'device_heartbeat', 'device_revoke', 'job_create', 'job_list', 'job_detail', 'job_lease', 'job_ack', 'job_start', 'job_result', 'archive_commit', 'archive_list', 'archive_detail', 'archive_delete_plan', 'archive_delete', 'archive_readback', 'cli_release_compatibility']
OPERATIONS: dict[str, dict[str, Any]] = {
    'pipeline_list': {
        'operation_id': 'pipeline_list',
        'method': 'GET',
        'relative_path': '/pipelines',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'not_applicable',
        'request_schema_ref': '#/api_schemas/PipelineListRequest',
        'response_schema_ref': '#/api_schemas/PipelineListResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'pair_code_create': {
        'operation_id': 'pair_code_create',
        'method': 'POST',
        'relative_path': '/pair-codes',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/PairCodeCreateRequest',
        'response_schema_ref': '#/api_schemas/PairCodeCreateResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'rate_limited'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'device_pair': {
        'operation_id': 'device_pair',
        'method': 'POST',
        'relative_path': '/devices/pair',
        'auth': 'pair_code',
        'owner_rule': 'pair_code_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/DevicePairRequest',
        'response_schema_ref': '#/api_schemas/DevicePairResponse',
        'error_codes': [
            'invalid_pair_code',
            'expired_pair_code',
            'platform_unsupported'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'device_list': {
        'operation_id': 'device_list',
        'method': 'GET',
        'relative_path': '/devices',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'not_applicable',
        'request_schema_ref': '#/api_schemas/DeviceListRequest',
        'response_schema_ref': '#/api_schemas/DeviceListResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'device_heartbeat': {
        'operation_id': 'device_heartbeat',
        'method': 'POST',
        'relative_path': '/devices/{device_id}/heartbeat',
        'auth': 'device_credential',
        'owner_rule': 'device_credential_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/DeviceHeartbeatRequest',
        'response_schema_ref': '#/api_schemas/DeviceHeartbeatResponse',
        'error_codes': [
            'invalid_device_credential',
            'device_revoked'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'device_revoke': {
        'operation_id': 'device_revoke',
        'method': 'POST',
        'relative_path': '/devices/{device_id}/revoke',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/DeviceRevokeRequest',
        'response_schema_ref': '#/api_schemas/DeviceRevokeResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'not_found'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'job_create': {
        'operation_id': 'job_create',
        'method': 'POST',
        'relative_path': '/jobs',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/JobCreateRequest',
        'response_schema_ref': '#/api_schemas/JobCreateResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'pipeline_unavailable',
            'device_unavailable'
        ],
        'state_machine': 'LocalAgentJob',
        'allowed_transitions': [
            {
                'from': None,
                'to': 'queued'
            }
        ]
    },
    'job_list': {
        'operation_id': 'job_list',
        'method': 'GET',
        'relative_path': '/jobs',
        'auth': 'session_or_device_credential',
        'owner_rule': 'verified_session_tenant_or_device_credential_bound_device_queued_or_claimable',
        'idempotency': 'not_applicable',
        'request_schema_ref': '#/api_schemas/JobListRequest',
        'response_schema_ref': '#/api_schemas/JobListResponse',
        'error_codes': [
            'unauthenticated',
            'invalid_device_credential',
            'device_revoked',
            'forbidden'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'job_detail': {
        'operation_id': 'job_detail',
        'method': 'GET',
        'relative_path': '/jobs/{job_id}',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'not_applicable',
        'request_schema_ref': None,
        'response_schema_ref': '#/api_schemas/JobDetailResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'not_found'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'job_lease': {
        'operation_id': 'job_lease',
        'method': 'POST',
        'relative_path': '/jobs/{job_id}/lease',
        'auth': 'device_credential',
        'owner_rule': 'device_credential_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/JobLeaseRequest',
        'response_schema_ref': '#/api_schemas/JobLeaseResponse',
        'error_codes': [
            'invalid_device_credential',
            'not_found',
            'invalid_state'
        ],
        'state_machine': 'LocalAgentJob',
        'allowed_transitions': [
            {
                'from': 'queued',
                'to': 'leased'
            }
        ]
    },
    'job_ack': {
        'operation_id': 'job_ack',
        'method': 'POST',
        'relative_path': '/jobs/{job_id}/ack',
        'auth': 'device_credential',
        'owner_rule': 'device_credential_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/JobAckRequest',
        'response_schema_ref': '#/api_schemas/JobAckResponse',
        'error_codes': [
            'invalid_device_credential',
            'not_found',
            'invalid_state'
        ],
        'state_machine': 'LocalAgentJob',
        'allowed_transitions': [
            {
                'from': 'leased',
                'to': 'acknowledged'
            }
        ]
    },
    'job_start': {
        'operation_id': 'job_start',
        'method': 'POST',
        'relative_path': '/jobs/{job_id}/start',
        'auth': 'device_credential',
        'owner_rule': 'device_credential_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/JobStartRequest',
        'response_schema_ref': '#/api_schemas/JobStartResponse',
        'error_codes': [
            'invalid_device_credential',
            'not_found',
            'invalid_state'
        ],
        'state_machine': 'LocalAgentJob',
        'allowed_transitions': [
            {
                'from': 'acknowledged',
                'to': 'running'
            }
        ]
    },
    'job_result': {
        'operation_id': 'job_result',
        'method': 'POST',
        'relative_path': '/jobs/{job_id}/result',
        'auth': 'device_credential',
        'owner_rule': 'device_credential_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/JobResultRequest',
        'response_schema_ref': '#/api_schemas/JobResultResponse',
        'error_codes': [
            'invalid_device_credential',
            'not_found',
            'invalid_state',
            'result_rejected'
        ],
        'state_machine': 'LocalAgentJob',
        'allowed_transitions': [
            {
                'from': 'running',
                'to': 'succeeded'
            },
            {
                'from': 'running',
                'to': 'blocked'
            },
            {
                'from': 'running',
                'to': 'failed'
            }
        ]
    },
    'archive_commit': {
        'operation_id': 'archive_commit',
        'method': 'POST',
        'relative_path': '/archives/commit',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/ArchiveCommitRequest',
        'response_schema_ref': '#/api_schemas/ArchiveCommitResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'invalid_mode',
            'commit_rejected'
        ],
        'state_machine': 'ArchiveCommit',
        'allowed_transitions': [
            {
                'from': 'draft',
                'to': 'committing'
            }
        ]
    },
    'archive_list': {
        'operation_id': 'archive_list',
        'method': 'GET',
        'relative_path': '/archives',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'not_applicable',
        'request_schema_ref': '#/api_schemas/ArchiveListRequest',
        'response_schema_ref': '#/api_schemas/ArchiveListResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'archive_detail': {
        'operation_id': 'archive_detail',
        'method': 'GET',
        'relative_path': '/archives/{archive_id}',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'not_applicable',
        'request_schema_ref': None,
        'response_schema_ref': '#/api_schemas/ArchiveDetailResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'not_found'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'archive_delete_plan': {
        'operation_id': 'archive_delete_plan',
        'method': 'POST',
        'relative_path': '/archives/{archive_id}/delete-plan',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': None,
        'response_schema_ref': '#/api_schemas/ArchiveDeletePlanResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'not_found',
            'delete_not_allowed'
        ],
        'state_machine': None,
        'allowed_transitions': []
    },
    'archive_delete': {
        'operation_id': 'archive_delete',
        'method': 'DELETE',
        'relative_path': '/archives/{archive_id}',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/ArchiveDeleteRequest',
        'response_schema_ref': '#/api_schemas/ArchiveDeleteResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'not_found',
            'invalid_delete_plan'
        ],
        'state_machine': 'ArchiveRecord',
        'allowed_transitions': [
            {
                'from': 'active',
                'to': 'deleting'
            }
        ]
    },
    'archive_readback': {
        'operation_id': 'archive_readback',
        'method': 'POST',
        'relative_path': '/archives/{archive_id}/readback',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'required',
        'request_schema_ref': '#/api_schemas/ArchiveReadbackRequest',
        'response_schema_ref': '#/api_schemas/ArchiveReadbackResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'not_found',
            'readback_failed'
        ],
        'state_machine': 'ArchiveCommit',
        'allowed_transitions': [
            {
                'from': 'verifying',
                'to': 'archived'
            },
            {
                'from': 'verifying',
                'to': 'failed'
            }
        ]
    },
    'cli_release_compatibility': {
        'operation_id': 'cli_release_compatibility',
        'method': 'POST',
        'relative_path': '/cli/releases/compatibility',
        'auth': 'session',
        'owner_rule': 'verified_session_tenant',
        'idempotency': 'not_applicable',
        'request_schema_ref': '#/api_schemas/CLIReleaseCompatibilityRequest',
        'response_schema_ref': '#/api_schemas/CLIReleaseCompatibilityResponse',
        'error_codes': [
            'unauthenticated',
            'forbidden',
            'unsupported_release'
        ],
        'state_machine': None,
        'allowed_transitions': []
    }
}
PATH_PARAMETERS: dict[str, tuple[str, ...]] = {
    'pipeline_list': (),
    'pair_code_create': (),
    'device_pair': (),
    'device_list': (),
    'device_heartbeat': ('device_id',),
    'device_revoke': ('device_id',),
    'job_create': (),
    'job_list': (),
    'job_detail': ('job_id',),
    'job_lease': ('job_id',),
    'job_ack': ('job_id',),
    'job_start': ('job_id',),
    'job_result': ('job_id',),
    'archive_commit': (),
    'archive_list': (),
    'archive_detail': ('archive_id',),
    'archive_delete_plan': ('archive_id',),
    'archive_delete': ('archive_id',),
    'archive_readback': ('archive_id',),
    'cli_release_compatibility': ()
}

class ProductTransport(Protocol):
    def request(
        self, *, operation_id: str, method: str, path: str, auth_source: str,
        owner_rule: str, idempotency: str, request: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


def objects_for_route(path: str) -> str:
    return ROUTE_OBJECTS[path]


def _interpolate_path(operation_id: str, request: Mapping[str, Any]) -> str:
    path = OPERATIONS[operation_id]["relative_path"]
    for parameter in PATH_PARAMETERS[operation_id]:
        value = request.get(parameter)
        if value is None:
            raise ValueError(f"missing path parameter: {parameter}")
        path = path.replace("{" + parameter + "}", quote(str(value), safe=""))
    return path


class MediaProductClient:
    def __init__(self, transport: ProductTransport) -> None:
        self._transport = transport

    def _call(self, operation_id: OperationId, request: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = OPERATIONS[operation_id]
        return self._transport.request(
            operation_id=operation_id, method=operation["method"],
            path=_interpolate_path(operation_id, request), auth_source=operation["auth"],
            owner_rule=operation["owner_rule"], idempotency=operation["idempotency"],
            request=request,
        )

    def pipeline_list(self, request: PipelineListRequest | None = None) -> PipelineListResponse:
        return cast(PipelineListResponse, self._call('pipeline_list', request or {}))

    def pair_code_create(self, request: PairCodeCreateRequest) -> PairCodeCreateResponse:
        return cast(PairCodeCreateResponse, self._call('pair_code_create', request))

    def device_pair(self, request: DevicePairRequest) -> DevicePairResponse:
        return cast(DevicePairResponse, self._call('device_pair', request))

    def device_list(self, request: DeviceListRequest | None = None) -> DeviceListResponse:
        return cast(DeviceListResponse, self._call('device_list', request or {}))

    def device_heartbeat(self, request: DeviceHeartbeatRequest) -> DeviceHeartbeatResponse:
        return cast(DeviceHeartbeatResponse, self._call('device_heartbeat', request))

    def device_revoke(self, request: DeviceRevokeRequest) -> DeviceRevokeResponse:
        return cast(DeviceRevokeResponse, self._call('device_revoke', request))

    def job_create(self, request: JobCreateRequest) -> JobCreateResponse:
        return cast(JobCreateResponse, self._call('job_create', request))

    def job_list(self, request: JobListRequest | None = None) -> JobListResponse:
        return cast(JobListResponse, self._call('job_list', request or {}))

    def job_detail(self, request: Mapping[str, Any] | None = None) -> JobDetailResponse:
        return cast(JobDetailResponse, self._call('job_detail', request or {}))

    def job_lease(self, request: JobLeaseRequest) -> JobLeaseResponse:
        return cast(JobLeaseResponse, self._call('job_lease', request))

    def job_ack(self, request: JobAckRequest) -> JobAckResponse:
        return cast(JobAckResponse, self._call('job_ack', request))

    def job_start(self, request: JobStartRequest) -> JobStartResponse:
        return cast(JobStartResponse, self._call('job_start', request))

    def job_result(self, request: JobResultRequest) -> JobResultResponse:
        return cast(JobResultResponse, self._call('job_result', request))

    def archive_commit(self, request: ArchiveCommitRequest) -> ArchiveCommitResponse:
        return cast(ArchiveCommitResponse, self._call('archive_commit', request))

    def archive_list(self, request: ArchiveListRequest | None = None) -> ArchiveListResponse:
        return cast(ArchiveListResponse, self._call('archive_list', request or {}))

    def archive_detail(self, request: Mapping[str, Any] | None = None) -> ArchiveDetailResponse:
        return cast(ArchiveDetailResponse, self._call('archive_detail', request or {}))

    def archive_delete_plan(self, request: Mapping[str, Any] | None = None) -> ArchiveDeletePlanResponse:
        return cast(ArchiveDeletePlanResponse, self._call('archive_delete_plan', request or {}))

    def archive_delete(self, request: ArchiveDeleteRequest) -> ArchiveDeleteResponse:
        return cast(ArchiveDeleteResponse, self._call('archive_delete', request))

    def archive_readback(self, request: ArchiveReadbackRequest) -> ArchiveReadbackResponse:
        return cast(ArchiveReadbackResponse, self._call('archive_readback', request))

    def cli_release_compatibility(self, request: CLIReleaseCompatibilityRequest) -> CLIReleaseCompatibilityResponse:
        return cast(CLIReleaseCompatibilityResponse, self._call('cli_release_compatibility', request))
