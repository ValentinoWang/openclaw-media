// Generated from openclaw-media-product-contract.json. Do not edit.

export interface PipelineListRequest {
  cursor?: string;
  limit?: number;
}

export interface PipelineListResponse {
  pipelines: Array<PipelineSummary>;
  next_cursor: string | null;
}

export interface PipelineSummary {
  pipeline_id: string;
  version: string;
  display_name: string;
  catalog_digest: string;
}

export interface PairCodeCreateRequest {
  device_label: string;
  expires_in_seconds: number;
}

export interface PairCodeCreateResponse {
  pair_code: string;
  expires_at: string;
}

export interface DevicePairRequest {
  pair_code: string;
  device_label: string;
  device_platform: "macos";
  client_version: string;
}

export interface DevicePairResponse {
  device: Device;
  device_credential: string;
}

export interface DeviceListRequest {
  cursor?: string;
  limit?: number;
}

export interface DeviceListResponse {
  devices: Array<Device>;
  next_cursor: string | null;
}

export interface DeviceHeartbeatRequest {
  observed_at: string;
  client_version: string;
  api_version: string;
  catalog_digest: string;
  capabilities?: Array<string>;
  expected_revision: number;
}

export interface DeviceHeartbeatResponse {
  device_id: string;
  accepted_at: string;
  revision: number;
  state: "paired" | "online" | "revoked";
  accepted_client_version: string;
  catalog_digest: string;
  api_compatible: boolean;
  catalog_compatible: boolean;
  claimable_job: ClaimableJob | null;
}

export interface DeviceRevokeRequest {
  expected_revision: number;
}

export interface DeviceRevokeResponse {
  device_id: string;
  revoked_at: string;
}

export interface JobCreateRequest {
  pipeline_id: string;
  pipeline_version: string;
  catalog_digest: string;
  device_id: string;
  input_refs: Array<string>;
  output_selection: Array<string>;
  confirmation_ref?: string;
}

export interface JobCreateResponse {
  job: LocalAgentJob;
}

export interface JobListRequest {
  cursor?: string;
  limit?: number;
  state?: string;
}

export interface JobListResponse {
  jobs: Array<LocalAgentJob>;
  next_cursor: string | null;
}

export interface JobDetailResponse {
  job: LocalAgentJob;
}

export interface JobLeaseRequest {
  lease_seconds: number;
  expected_revision: number;
}

export interface JobLeaseResponse {
  job: LocalAgentJob;
}

export interface JobAckRequest {
  ack_ref: string;
  expected_revision: number;
}

export interface JobAckResponse {
  job: LocalAgentJob;
}

export interface JobStartRequest {
  start_ref: string;
  expected_revision: number;
}

export interface JobStartResponse {
  job: LocalAgentJob;
}

export interface JobResultRequest {
  result_status: "succeeded" | "blocked" | "failed";
  result_refs: Array<string>;
  artifact_refs?: Array<string>;
  failure_code?: string | null;
  expected_revision: number;
}

export interface JobResultResponse {
  job: LocalAgentJob;
}

export interface ArchiveCommitRequest {
  run_id: string;
  manifest: ArchiveManifest;
  confirmation_ref: string;
}

export interface ArchiveCommitResponse {
  archive: ArchiveRecord;
  commit_receipt: ArchiveCommitReceipt;
  readback_receipt: ArchiveReadbackReceipt;
}

export interface ArchiveListRequest {
  cursor?: string;
  limit?: number;
  state?: string;
}

export interface ArchiveListResponse {
  archives: Array<ArchiveRecord>;
  next_cursor: string | null;
}

export interface ArchiveDetailResponse {
  archive: ArchiveRecord;
}

export interface ArchiveDeletePlanResponse {
  delete_plan_id: string;
  archive_id: string;
  expires_at: string;
}

export interface ArchiveDeleteRequest {
  delete_plan_id: string;
  confirmation_ref: string;
  expected_revision: number;
}

export interface ArchiveDeleteResponse {
  archive_id: string;
  state: "deleted" | "delete_failed";
  delete_receipt: ArchiveDeleteReceipt;
  hard_deleted: true;
}

export interface ArchiveReadbackRequest {
  readback_receipt_ref: string;
  observed_refs?: Array<string>;
}

export interface ArchiveReadbackResponse {
  archive: ArchiveRecord | null;
  verified: boolean;
  readback_receipt: ArchiveReadbackReceipt;
  hard_deleted: boolean;
}

export interface CLIReleaseCompatibilityRequest {
  cli_version: string;
  platform: "macos";
  python_version: string;
  catalog_digest: string;
  api_version: string;
}

export interface CLIReleaseCompatibilityResponse {
  compatible: boolean;
  min_cli_version: string;
  supported_python: string;
  supported_platforms: Array<string>;
}

export interface Device {
  device_id: string;
  state: "paired" | "online" | "revoked";
  device_label: string;
  device_platform: "macos";
  client_version: string;
  capabilities: Array<string>;
  revision: number;
  last_seen_at: string | null;
}

export interface LocalAgentJob {
  job_id: string;
  state: "queued" | "leased" | "acknowledged" | "running" | "succeeded" | "blocked" | "failed" | "expired" | "cancelled";
  pipeline_id: string;
  pipeline_version: string;
  catalog_digest: string;
  device_id: string | null;
  input_refs: Array<string>;
  output_selection: Array<string>;
  confirmation_ref: string | null;
  revision: number;
  lease_id: string | null;
  lease_expires_at: string | null;
  ack_ref: string | null;
  acknowledged_at: string | null;
  start_ref: string | null;
  started_at: string | null;
  result_status: "succeeded" | "blocked" | "failed" | null;
  result_refs: Array<string>;
  artifact_refs: Array<string>;
  failure_code: string | null;
  created_at: string;
  updated_at: string;
  leased_at: string | null;
  completed_at: string | null;
}

export interface ArchiveContent {
  encoding: "utf8" | "base64";
  value: string;
}

export interface ArchiveArtifact {
  ref: string;
  mode: "content" | "descriptor_only" | "forbidden";
  mime_type: string;
  sha256: string;
  size_bytes: number;
  descriptor: boolean;
  metadata: Record<string, unknown>;
  content: ArchiveContent | null;
}

export interface ClaimableJob {
  job_id: string;
  state: "queued" | "leased" | "acknowledged" | "running" | "succeeded" | "blocked" | "failed" | "expired" | "cancelled";
}

export interface ArchiveManifest {
  manifest_id: string;
  run_id: string;
  confirmation_ref: string;
  items: Array<ArchiveArtifact>;
  created_at: string;
}

export interface ArchiveProjection {
  projection_id: string;
  kind: "db" | "attachment" | "web";
  ref: string;
  artifact_refs: Array<string>;
  consistent: boolean;
}

export interface ArchiveReadbackReceipt {
  receipt_ref: string;
  archive_id: string;
  verified: boolean;
  db_present: boolean;
  attachments_present: boolean;
  projections_present: boolean;
  checked_at: string;
}

export interface ArchiveCommitReceipt {
  commit_id: string;
  manifest_id: string;
  archive_id: string;
  artifact_refs: Array<string>;
  total_bytes: number;
  cloud_bytes: number;
  media_cloud_bytes: 0;
  committed_at: string;
}

export interface ArchiveDeleteReceipt {
  receipt_ref: string;
  archive_id: string;
  deleted_artifact_refs: Array<string>;
  deleted_projection_refs: Array<string>;
  verified: boolean;
  hard_deleted: true;
  deleted_at: string;
}

export interface ArchiveRecord {
  archive_id: string;
  state: "active" | "deleting" | "delete_failed";
  commit_id: string;
  manifest_id: string;
  run_id: string;
  pipeline_id: string | null;
  pipeline_version: string | null;
  device_id: string | null;
  artifacts: Array<ArchiveArtifact>;
  projections: Array<ArchiveProjection>;
  cloud_bytes: number;
  media_cloud_bytes: 0;
  revision: number;
  created_at: string;
  updated_at: string;
}
export const apiBase = "/openclaw/media/api" as const;
export const releasePlatforms = ["macos"] as const;
export const objectIds = {"PipelineDefinition":"pipeline_id","Device":"device_id","LocalAgentJob":"job_id","ArchiveRecord":"archive_id","CLIRelease":"release_id","ProviderConfig":"provider_config_id","LocalWorkspace":"workspace_id","LocalAnalysisRun":"run_id","LocalArtifact":"artifact_id","ArchiveManifest":"manifest_id"} as const;
export const webRoutes = ["/overview","/tracks","/assets","/runs","/runs/:runId","/publishing","/reviews","/media-agent","/archives"] as const;
export const routeObjects = {"/overview":"ArchiveRecord","/tracks":"ArchiveRecord","/assets":"LocalArtifact","/runs":"LocalAgentJob","/runs/:runId":"LocalAgentJob","/publishing":"ArchiveRecord","/reviews":"ArchiveRecord","/media-agent":"LocalWorkspace","/archives":"ArchiveRecord"} as const;
export const localCollaboration = {"surfaces":["/media-agent","/archives"],"media_bytes":"local_only","api_consumption":"generated_client_only"} as const;
export const stateMachines = {"MediaProject":["captured","planned","edit_ready","editing","final_ready","published"],"MediaWebTask":["queued","awaiting_confirmation","succeeded","pending_manual","failed","cancelled"],"LocalAgentJob":["queued","leased","acknowledged","running","succeeded","blocked","failed","expired","cancelled"],"LocalAnalysisRun":["created","validating","preprocessing","analyzing","rendering","reviewing","ready_to_archive","succeeded","pending_manual","failed","cancelled"],"ArchiveCommit":["draft","committing","verifying","archived","failed","cancelled"],"ArchiveRecord":["active","deleting","delete_failed"]} as const;
export const operations = {"pipeline_list":{"operation_id":"pipeline_list","method":"GET","relative_path":"/pipelines","auth":"session","owner_rule":"verified_session_tenant","idempotency":"not_applicable","request_schema_ref":"#/api_schemas/PipelineListRequest","response_schema_ref":"#/api_schemas/PipelineListResponse","error_codes":["unauthenticated","forbidden"],"state_machine":null,"allowed_transitions":[]},"pair_code_create":{"operation_id":"pair_code_create","method":"POST","relative_path":"/pair-codes","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/PairCodeCreateRequest","response_schema_ref":"#/api_schemas/PairCodeCreateResponse","error_codes":["unauthenticated","forbidden","rate_limited"],"state_machine":null,"allowed_transitions":[]},"device_pair":{"operation_id":"device_pair","method":"POST","relative_path":"/devices/pair","auth":"pair_code","owner_rule":"pair_code_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/DevicePairRequest","response_schema_ref":"#/api_schemas/DevicePairResponse","error_codes":["invalid_pair_code","expired_pair_code","platform_unsupported"],"state_machine":null,"allowed_transitions":[]},"device_list":{"operation_id":"device_list","method":"GET","relative_path":"/devices","auth":"session","owner_rule":"verified_session_tenant","idempotency":"not_applicable","request_schema_ref":"#/api_schemas/DeviceListRequest","response_schema_ref":"#/api_schemas/DeviceListResponse","error_codes":["unauthenticated","forbidden"],"state_machine":null,"allowed_transitions":[]},"device_heartbeat":{"operation_id":"device_heartbeat","method":"POST","relative_path":"/devices/{device_id}/heartbeat","auth":"device_credential","owner_rule":"device_credential_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/DeviceHeartbeatRequest","response_schema_ref":"#/api_schemas/DeviceHeartbeatResponse","error_codes":["invalid_device_credential","device_revoked"],"state_machine":null,"allowed_transitions":[]},"device_revoke":{"operation_id":"device_revoke","method":"POST","relative_path":"/devices/{device_id}/revoke","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/DeviceRevokeRequest","response_schema_ref":"#/api_schemas/DeviceRevokeResponse","error_codes":["unauthenticated","forbidden","not_found"],"state_machine":null,"allowed_transitions":[]},"job_create":{"operation_id":"job_create","method":"POST","relative_path":"/jobs","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/JobCreateRequest","response_schema_ref":"#/api_schemas/JobCreateResponse","error_codes":["unauthenticated","forbidden","pipeline_unavailable","device_unavailable"],"state_machine":"LocalAgentJob","allowed_transitions":[{"from":null,"to":"queued"}]},"job_list":{"operation_id":"job_list","method":"GET","relative_path":"/jobs","auth":"session_or_device_credential","owner_rule":"verified_session_tenant_or_device_credential_bound_device_queued_or_claimable","idempotency":"not_applicable","request_schema_ref":"#/api_schemas/JobListRequest","response_schema_ref":"#/api_schemas/JobListResponse","error_codes":["unauthenticated","invalid_device_credential","device_revoked","forbidden"],"state_machine":null,"allowed_transitions":[]},"job_detail":{"operation_id":"job_detail","method":"GET","relative_path":"/jobs/{job_id}","auth":"session","owner_rule":"verified_session_tenant","idempotency":"not_applicable","request_schema_ref":null,"response_schema_ref":"#/api_schemas/JobDetailResponse","error_codes":["unauthenticated","forbidden","not_found"],"state_machine":null,"allowed_transitions":[]},"job_lease":{"operation_id":"job_lease","method":"POST","relative_path":"/jobs/{job_id}/lease","auth":"device_credential","owner_rule":"device_credential_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/JobLeaseRequest","response_schema_ref":"#/api_schemas/JobLeaseResponse","error_codes":["invalid_device_credential","not_found","invalid_state"],"state_machine":"LocalAgentJob","allowed_transitions":[{"from":"queued","to":"leased"}]},"job_ack":{"operation_id":"job_ack","method":"POST","relative_path":"/jobs/{job_id}/ack","auth":"device_credential","owner_rule":"device_credential_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/JobAckRequest","response_schema_ref":"#/api_schemas/JobAckResponse","error_codes":["invalid_device_credential","not_found","invalid_state"],"state_machine":"LocalAgentJob","allowed_transitions":[{"from":"leased","to":"acknowledged"}]},"job_start":{"operation_id":"job_start","method":"POST","relative_path":"/jobs/{job_id}/start","auth":"device_credential","owner_rule":"device_credential_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/JobStartRequest","response_schema_ref":"#/api_schemas/JobStartResponse","error_codes":["invalid_device_credential","not_found","invalid_state"],"state_machine":"LocalAgentJob","allowed_transitions":[{"from":"acknowledged","to":"running"}]},"job_result":{"operation_id":"job_result","method":"POST","relative_path":"/jobs/{job_id}/result","auth":"device_credential","owner_rule":"device_credential_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/JobResultRequest","response_schema_ref":"#/api_schemas/JobResultResponse","error_codes":["invalid_device_credential","not_found","invalid_state","result_rejected"],"state_machine":"LocalAgentJob","allowed_transitions":[{"from":"running","to":"succeeded"},{"from":"running","to":"blocked"},{"from":"running","to":"failed"}]},"archive_commit":{"operation_id":"archive_commit","method":"POST","relative_path":"/archives/commit","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/ArchiveCommitRequest","response_schema_ref":"#/api_schemas/ArchiveCommitResponse","error_codes":["unauthenticated","forbidden","invalid_mode","commit_rejected"],"state_machine":"ArchiveCommit","allowed_transitions":[{"from":"draft","to":"committing"}]},"archive_list":{"operation_id":"archive_list","method":"GET","relative_path":"/archives","auth":"session","owner_rule":"verified_session_tenant","idempotency":"not_applicable","request_schema_ref":"#/api_schemas/ArchiveListRequest","response_schema_ref":"#/api_schemas/ArchiveListResponse","error_codes":["unauthenticated","forbidden"],"state_machine":null,"allowed_transitions":[]},"archive_detail":{"operation_id":"archive_detail","method":"GET","relative_path":"/archives/{archive_id}","auth":"session","owner_rule":"verified_session_tenant","idempotency":"not_applicable","request_schema_ref":null,"response_schema_ref":"#/api_schemas/ArchiveDetailResponse","error_codes":["unauthenticated","forbidden","not_found"],"state_machine":null,"allowed_transitions":[]},"archive_delete_plan":{"operation_id":"archive_delete_plan","method":"POST","relative_path":"/archives/{archive_id}/delete-plan","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":null,"response_schema_ref":"#/api_schemas/ArchiveDeletePlanResponse","error_codes":["unauthenticated","forbidden","not_found","delete_not_allowed"],"state_machine":null,"allowed_transitions":[]},"archive_delete":{"operation_id":"archive_delete","method":"DELETE","relative_path":"/archives/{archive_id}","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/ArchiveDeleteRequest","response_schema_ref":"#/api_schemas/ArchiveDeleteResponse","error_codes":["unauthenticated","forbidden","not_found","invalid_delete_plan"],"state_machine":"ArchiveRecord","allowed_transitions":[{"from":"active","to":"deleting"}]},"archive_readback":{"operation_id":"archive_readback","method":"POST","relative_path":"/archives/{archive_id}/readback","auth":"session","owner_rule":"verified_session_tenant","idempotency":"required","request_schema_ref":"#/api_schemas/ArchiveReadbackRequest","response_schema_ref":"#/api_schemas/ArchiveReadbackResponse","error_codes":["unauthenticated","forbidden","not_found","readback_failed"],"state_machine":"ArchiveCommit","allowed_transitions":[{"from":"verifying","to":"archived"},{"from":"verifying","to":"failed"}]},"cli_release_compatibility":{"operation_id":"cli_release_compatibility","method":"POST","relative_path":"/cli/releases/compatibility","auth":"session","owner_rule":"verified_session_tenant","idempotency":"not_applicable","request_schema_ref":"#/api_schemas/CLIReleaseCompatibilityRequest","response_schema_ref":"#/api_schemas/CLIReleaseCompatibilityResponse","error_codes":["unauthenticated","forbidden","unsupported_release"],"state_machine":null,"allowed_transitions":[]}} as const;
export type OperationId = keyof typeof operations;

export type ProductRequestEnvelope = {
  method: string;
  path: string;
  query: Record<string, string>;
  body: Record<string, unknown> | undefined;
  authSource: string;
  ownerRule: string;
  idempotency: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export type ProductRequestOptions = {
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export interface ProductTransport {
  request<TResponse>(operationId: OperationId, envelope: ProductRequestEnvelope): Promise<TResponse>;
}

function interpolatePath(path: string, request: Record<string, unknown>): string {
  return path.replace(/\{([^{}]+)\}/g, (_match, parameter: string) => {
    const value = request[parameter];
    if (value === undefined || value === null) throw new Error(`missing path parameter: ${parameter}`);
    return encodeURIComponent(String(value));
  });
}

export class MediaProductClient {
  private readonly transport: ProductTransport;

  constructor(transport: ProductTransport) {
    this.transport = transport;
  }

  private invoke<TResponse>(
    operationId: OperationId,
    request: object,
    pathParameters: readonly string[] = [],
    options: ProductRequestOptions = {},
  ): Promise<TResponse> {
    const operation = operations[operationId];
    const requestRecord = request as Record<string, unknown>;
    const pathParameterSet = new Set(pathParameters);
    const pathRequest = Object.fromEntries(Object.entries(requestRecord).filter(([key]) => pathParameterSet.has(key)));
    const body = operation.method === 'GET'
      ? undefined
      : Object.fromEntries(Object.entries(requestRecord).filter(([key]) => !pathParameterSet.has(key)));
    const query = operation.method === 'GET'
      ? Object.fromEntries(Object.entries(requestRecord)
        .filter(([key, value]) => !pathParameterSet.has(key) && value !== undefined && value !== null)
        .map(([key, value]) => [key, String(value)]))
      : {};
    return this.transport.request<TResponse>(operationId, {
      method: operation.method,
      path: interpolatePath(operation.relative_path, pathRequest),
      query,
      body,
      authSource: operation.auth,
      ownerRule: operation.owner_rule,
      idempotency: operation.idempotency,
      idempotencyKey: options.idempotencyKey,
      signal: options.signal,
    });
  }

  pipeline_list(request: PipelineListRequest = {}, options?: ProductRequestOptions): Promise<PipelineListResponse> {
    return this.invoke<PipelineListResponse>('pipeline_list', request, [], options);
  }

  pair_code_create(request: PairCodeCreateRequest, options?: ProductRequestOptions): Promise<PairCodeCreateResponse> {
    return this.invoke<PairCodeCreateResponse>('pair_code_create', request, [], options);
  }

  device_pair(request: DevicePairRequest, options?: ProductRequestOptions): Promise<DevicePairResponse> {
    return this.invoke<DevicePairResponse>('device_pair', request, [], options);
  }

  device_list(request: DeviceListRequest = {}, options?: ProductRequestOptions): Promise<DeviceListResponse> {
    return this.invoke<DeviceListResponse>('device_list', request, [], options);
  }

  device_heartbeat(request: DeviceHeartbeatRequest & { device_id: string }, options?: ProductRequestOptions): Promise<DeviceHeartbeatResponse> {
    return this.invoke<DeviceHeartbeatResponse>('device_heartbeat', request, ["device_id"], options);
  }

  device_revoke(request: DeviceRevokeRequest & { device_id: string }, options?: ProductRequestOptions): Promise<DeviceRevokeResponse> {
    return this.invoke<DeviceRevokeResponse>('device_revoke', request, ["device_id"], options);
  }

  job_create(request: JobCreateRequest, options?: ProductRequestOptions): Promise<JobCreateResponse> {
    return this.invoke<JobCreateResponse>('job_create', request, [], options);
  }

  job_list(request: JobListRequest = {}, options?: ProductRequestOptions): Promise<JobListResponse> {
    return this.invoke<JobListResponse>('job_list', request, [], options);
  }

  job_detail(request: Record<string, unknown> & { job_id: string }, options?: ProductRequestOptions): Promise<JobDetailResponse> {
    return this.invoke<JobDetailResponse>('job_detail', request, ["job_id"], options);
  }

  job_lease(request: JobLeaseRequest & { job_id: string }, options?: ProductRequestOptions): Promise<JobLeaseResponse> {
    return this.invoke<JobLeaseResponse>('job_lease', request, ["job_id"], options);
  }

  job_ack(request: JobAckRequest & { job_id: string }, options?: ProductRequestOptions): Promise<JobAckResponse> {
    return this.invoke<JobAckResponse>('job_ack', request, ["job_id"], options);
  }

  job_start(request: JobStartRequest & { job_id: string }, options?: ProductRequestOptions): Promise<JobStartResponse> {
    return this.invoke<JobStartResponse>('job_start', request, ["job_id"], options);
  }

  job_result(request: JobResultRequest & { job_id: string }, options?: ProductRequestOptions): Promise<JobResultResponse> {
    return this.invoke<JobResultResponse>('job_result', request, ["job_id"], options);
  }

  archive_commit(request: ArchiveCommitRequest, options?: ProductRequestOptions): Promise<ArchiveCommitResponse> {
    return this.invoke<ArchiveCommitResponse>('archive_commit', request, [], options);
  }

  archive_list(request: ArchiveListRequest = {}, options?: ProductRequestOptions): Promise<ArchiveListResponse> {
    return this.invoke<ArchiveListResponse>('archive_list', request, [], options);
  }

  archive_detail(request: Record<string, unknown> & { archive_id: string }, options?: ProductRequestOptions): Promise<ArchiveDetailResponse> {
    return this.invoke<ArchiveDetailResponse>('archive_detail', request, ["archive_id"], options);
  }

  archive_delete_plan(request: Record<string, unknown> & { archive_id: string }, options?: ProductRequestOptions): Promise<ArchiveDeletePlanResponse> {
    return this.invoke<ArchiveDeletePlanResponse>('archive_delete_plan', request, ["archive_id"], options);
  }

  archive_delete(request: ArchiveDeleteRequest & { archive_id: string }, options?: ProductRequestOptions): Promise<ArchiveDeleteResponse> {
    return this.invoke<ArchiveDeleteResponse>('archive_delete', request, ["archive_id"], options);
  }

  archive_readback(request: ArchiveReadbackRequest & { archive_id: string }, options?: ProductRequestOptions): Promise<ArchiveReadbackResponse> {
    return this.invoke<ArchiveReadbackResponse>('archive_readback', request, ["archive_id"], options);
  }

  cli_release_compatibility(request: CLIReleaseCompatibilityRequest, options?: ProductRequestOptions): Promise<CLIReleaseCompatibilityResponse> {
    return this.invoke<CLIReleaseCompatibilityResponse>('cli_release_compatibility', request, [], options);
  }
}
