import { authPageUrl, currentLocationForReturn } from './mediaNavigation'
import { capabilityCatalogSchema, type CapabilityCatalog, type CapabilityDefinition } from '../schemas/capabilityCatalogSchema'
import { capabilityMatchResponseSchema, type CapabilityMatchResponse } from '../schemas/capabilityMatchSchema'
import { mediaWebTaskCreateRequestSchema, mediaWebTaskErrorSchema, mediaWebTaskSchema, mediaWebUploadSchema, type MediaWebTask as GeneratedMediaWebTask, type MediaWebTaskCreateRequest, type MediaWebUpload } from '../schemas/mediaWebTaskSchema'
import { z } from 'zod'
import { newIdempotencyKey } from './idempotency'
import { stableTaskErrorMessage } from './recentTaskPresentation'
import {
  MediaProductClient,
  type ArchiveDeleteResponse,
  type ArchiveDeletePlanResponse,
  type ArchiveDetailResponse,
  type ArchiveListResponse,
  type ArchiveReadbackRequest,
  type ArchiveReadbackResponse,
  type PairCodeCreateResponse,
  type DeviceListResponse,
  type JobCreateRequest,
  type JobCreateResponse,
  type JobDetailResponse,
  type JobListRequest,
  type JobListResponse,
  type LocalAgentJob,
  type PipelineListResponse,
} from './generatedProductContract'
import { MediaProductHttpTransport } from './mediaProductHttpTransport'
import { materialParsingServerFailureMessage } from './task-launch/materialParsing'
import { mutationHeaders as buildMutationHeaders, MissingCsrfTokenError } from './requestHeaders'

export type MediaWebCapability = CapabilityDefinition

const mediaWebSessionBaseSchema = z.object({
  publicUserId: z.string().uuid(),
  organizationName: z.string().min(1).max(120).nullable(),
  memberRole: z.enum(['owner', 'member']),
  organizationConnection: z.enum(['not_applicable', 'connected', 'pending', 'disabled', 'revoked', 'attention']),
  installationConnection: z.enum(['not_applicable', 'connected', 'pending', 'disabled', 'revoked', 'attention']),
  role: z.enum(['ordinary', 'admin']),
  maintainer: z.boolean(),
  csrfToken: z.string(),
  expiresAt: z.string().datetime({ offset: true }),
  routeGrants: z.array(z.string().regex(/^\/[a-z0-9/_:-]*$/)).min(1),
  schemaVersion: z.literal('media_web_business_pages_v2'),
}).strict()

const mediaWebSessionWithWorkspaceSchema = z.discriminatedUnion('workspaceMode', [
  mediaWebSessionBaseSchema.extend({
    workspaceMode: z.literal('personal_web'),
    editorMode: z.literal('web_edit'),
    bodyAuthority: z.literal('internal'),
    organizationName: z.null(),
    organizationConnection: z.literal('not_applicable'),
    installationConnection: z.literal('not_applicable'),
  }).strict(),
  mediaWebSessionBaseSchema.extend({
    workspaceMode: z.literal('organization_lark'),
    editorMode: z.literal('lark_edit'),
    bodyAuthority: z.literal('lark'),
    organizationName: z.string().min(1).max(120),
    organizationConnection: z.enum(['connected', 'pending', 'disabled', 'revoked', 'attention']),
    installationConnection: z.enum(['connected', 'pending', 'disabled', 'revoked', 'attention']),
  }).strict(),
])

const exactRouteGrants = {
  admin: ['/admin/overview', '/admin/access', '/admin/tenants', '/admin/billing', '/admin/upstreams'],
  personal: ['/today', '/studio', '/campaigns', '/business', '/desk', '/overview', '/assets', '/tracks', '/decisions', '/publishing', '/reviews', '/media-agent', '/archives', '/usage-billing', '/invites', '/workspace'],
  organization: ['/organization-workspace', '/tracks'],
} as const

function hasExactRouteGrants(actual: readonly string[], expected: readonly string[]) {
  return actual.length === expected.length && actual.every((path, index) => path === expected[index])
}

const mediaWebSessionSchema = mediaWebSessionWithWorkspaceSchema.refine(
  (session) => !session.maintainer || session.role === 'admin',
  { message: 'maintainer authority requires an admin session' },
).superRefine((session, context) => {
  const expected = session.role === 'admin'
    ? exactRouteGrants.admin
    : session.workspaceMode === 'personal_web'
      ? exactRouteGrants.personal
      : exactRouteGrants.organization
  if (!hasExactRouteGrants(session.routeGrants, expected)) {
    context.addIssue({ code: 'custom', path: ['routeGrants'], message: 'route grants do not match session authority' })
  }
})

const mediaWebSessionResponseSchema = z.object({
  schemaVersion: z.literal('media_web_business_pages_v2'),
  revision: z.number().int().min(1),
  session: mediaWebSessionSchema,
}).strict()

export type MediaWebSession = z.infer<typeof mediaWebSessionSchema>

export type TenantDashboard = {
  schemaVersion: string
  revision: string
  summary: Record<string, unknown>
}

export type AdminRunSummary = {
  publicRunId: string
  title?: string
  status?: string
  entrypoint?: string
  createdAt?: string
  updatedAt?: string
}

export type AdminRunSummaryPage = {
  schemaVersion: string
  revision: string
  items: AdminRunSummary[]
  nextCursor: string | null
  pageSize: number
}

export type AssetSummary = {
  publicAssetId: string
  createdAt: string
}

export type AssetSummaryPage = {
  schemaVersion: string
  revision: string
  items: AssetSummary[]
  nextCursor: string | null
  pageSize: number
}

export type PageQuery = {
  page?: number
  pageSize?: number
  search?: string
  model?: string
  startTime?: string
  endTime?: string
  signal?: AbortSignal
}

export type BillingBalanceResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  balance: {
    available: string
    currency: string
    asOf: string
    revision: number
  }
}

export type RedemptionResult = {
  ok: true
  fulfillment: {
    fulfillmentId: string
    planCode: string
    creditedAmount: string
    affiliateAmount: string
    status: string
  }
}

export type BillingBalancePack = {
  balancePackCode: string
  name: string
  creditAmount: number
  priceCny: string
  currency: string
  audience: 'all' | 'personal' | 'organization'
  productKind: 'balance_pack'
  purchaseAvailable: boolean
  purchaseUrl: string | null
}

export type BillingBalancePackListResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  items: BillingBalancePack[]
  nextCursor: string | null
}

export type AdminBillingPlan = {
  code: string
  name: string
  priceCny: string
  creditAmount: string
  purchaseAvailable: boolean
  purchaseUrl: string | null
}

export type AdminBillingSummary = {
  ok: true
  plans: AdminBillingPlan[]
  mappings: Array<Record<string, unknown>>
  batches: Array<Record<string, unknown>>
  fulfillments: Array<Record<string, unknown>>
  grants: Array<Record<string, unknown>>
}

export type AdminUpstreamSummary = {
  credential: Record<string, unknown>
  reconciliation: Array<Record<string, unknown>>
}

export type ResourceDocxLink = {
  resourceType: string
  resourceId: string
  documentUrl: string
  sharingPolicy: 'org_link_edit' | 'anyone_editable'
  status: 'active'
}

export type MediaWebTask = GeneratedMediaWebTask

export type Stage1ProvisionRun = {
  provisionRunId: string
  installationId: string
  tenantId: string
  idempotencyKey?: string
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  state: 'ACTIVE' | 'NEEDS_ATTENTION' | 'DISABLED' | 'REVOKED'
  completedSteps: string[]
  failedStep: string | null
  retryAvailable: boolean
  retryAfter: string | null
}

export type Stage1ProvisionResponse = {
  schemaVersion: 'media.stage1.provision.v1'
  run: Stage1ProvisionRun | null
}

async function stage1ProvisionRequest<T>(
  session: MediaWebSession,
  path: string,
  method: 'GET' | 'POST',
  body?: Record<string, unknown>,
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/openclaw/media/api/organization/provision${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(method === 'POST' ? { 'Content-Type': 'application/json', 'X-OpenClaw-CSRF': session.csrfToken, Origin: window.location.origin } : {}),
      ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
    },
    body: method === 'POST' ? JSON.stringify(body ?? {}) : undefined,
    signal,
  })
  const payload = await response.json().catch(() => ({})) as T & { error?: { message?: string; code?: string } }
  if (!response.ok) throw new MediaWebApiError(response.status, payload.error?.code || 'stage1_provision_failed', payload.error?.message || payload.error?.code || '组织接入请求失败')
  return payload
}

export function loadStage1ProvisionStatus(session: MediaWebSession, runId: string, signal?: AbortSignal): Promise<Stage1ProvisionResponse> {
  return stage1ProvisionRequest<Stage1ProvisionResponse>(session, `/runs/${encodeURIComponent(runId)}`, 'GET', undefined, undefined, signal)
}

export function startStage1Provision(session: MediaWebSession, idempotencyKey: string): Promise<{ schemaVersion: string; run: Stage1ProvisionRun }> {
  return stage1ProvisionRequest(session, '/start', 'POST', {}, idempotencyKey)
}

export function confirmStage1Provision(session: MediaWebSession, idempotencyKey: string, credentialRef?: string): Promise<Record<string, unknown>> {
  return stage1ProvisionRequest(session, '/confirm', 'POST', credentialRef ? { credentialRef } : {}, idempotencyKey)
}

export function deprovisionStage1(session: MediaWebSession, idempotencyKey: string, revoke = false): Promise<Record<string, unknown>> {
  return stage1ProvisionRequest(session, '/deprovision', 'POST', { revoke }, idempotencyKey)
}

export type W1ApiClient = MediaProductClient
export type { JobDetailResponse, JobListRequest, JobListResponse, LocalAgentJob }

function w1Client(session: MediaWebSession): W1ApiClient {
  return new MediaProductClient(new MediaProductHttpTransport({
    getCsrfToken: () => session.csrfToken,
  }))
}

async function archiveReplayKey(
  operation: 'plan' | 'delete' | 'readback' | 'confirmation',
  parts: readonly (string | number)[],
): Promise<string> {
  const canonical = JSON.stringify([operation, ...parts.map(String)])
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(canonical),
  )
  const fingerprint = Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, '0'),
  ).join('')
  return `archive-${operation}-${fingerprint}`
}

export function archiveDeletePlanIdempotencyKey(archiveId: string): Promise<string> {
  return archiveReplayKey('plan', [archiveId])
}

export function archiveDeleteIdempotencyKey(
  archiveId: string,
  deletePlanId: string,
  expectedRevision: number,
): Promise<string> {
  return archiveReplayKey('delete', [archiveId, deletePlanId, expectedRevision])
}

export function archiveReadbackIdempotencyKey(
  archiveId: string,
  receiptRef: string,
): Promise<string> {
  return archiveReplayKey('readback', [archiveId, receiptRef])
}

export function archiveDeleteConfirmationRef(
  archiveId: string,
  deletePlanId: string,
): Promise<string> {
  return archiveReplayKey('confirmation', [archiveId, deletePlanId])
}

export function loadMediaPipelines(session: MediaWebSession, signal?: AbortSignal): Promise<PipelineListResponse> {
  return w1Client(session).pipeline_list({ limit: 100 }, { signal })
}

export function loadMediaDevices(session: MediaWebSession, signal?: AbortSignal): Promise<DeviceListResponse> {
  return w1Client(session).device_list({ limit: 100 }, { signal })
}

export function loadMediaJobs(
  session: MediaWebSession,
  request: JobListRequest = { limit: 100 },
  signal?: AbortSignal,
): Promise<JobListResponse> {
  return w1Client(session).job_list(request, { signal })
}

export function loadMediaJobDetail(
  session: MediaWebSession,
  jobId: string,
  signal?: AbortSignal,
): Promise<JobDetailResponse> {
  return w1Client(session).job_detail({ job_id: jobId }, { signal })
}

export function createMediaJob(
  session: MediaWebSession,
  request: JobCreateRequest,
  idempotencyKey = newIdempotencyKey('media-job'),
): Promise<JobCreateResponse> {
  return w1Client(session).job_create(request, { idempotencyKey })
}

export function createMediaPairCode(
  session: MediaWebSession,
  deviceLabel: string,
  idempotencyKey = newIdempotencyKey('pair-code'),
): Promise<PairCodeCreateResponse> {
  return w1Client(session).pair_code_create({ device_label: deviceLabel, expires_in_seconds: 600 }, { idempotencyKey })
}

export function loadArchiveList(session: MediaWebSession, request: { cursor?: string; limit?: number; state?: string } = {}, signal?: AbortSignal): Promise<ArchiveListResponse> {
  return w1Client(session).archive_list(request, { signal })
}

export function loadArchiveDetail(session: MediaWebSession, archiveId: string, signal?: AbortSignal): Promise<ArchiveDetailResponse> {
  return w1Client(session).archive_detail({ archive_id: archiveId }, { signal })
}

export async function planArchiveDelete(session: MediaWebSession, archiveId: string, idempotencyKey?: string, signal?: AbortSignal): Promise<ArchiveDeletePlanResponse> {
  return w1Client(session).archive_delete_plan(
    { archive_id: archiveId },
    { idempotencyKey: idempotencyKey ?? await archiveDeletePlanIdempotencyKey(archiveId), signal },
  )
}

export async function deleteArchive(
  session: MediaWebSession,
  archiveId: string,
  request: { delete_plan_id: string; confirmation_ref: string; expected_revision: number },
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<ArchiveDeleteResponse> {
  return w1Client(session).archive_delete(
    { archive_id: archiveId, ...request },
    {
      idempotencyKey: idempotencyKey ?? await archiveDeleteIdempotencyKey(
        archiveId,
        request.delete_plan_id,
        request.expected_revision,
      ),
      signal,
    },
  )
}

export async function readbackArchive(
  session: MediaWebSession,
  archiveId: string,
  request: Omit<ArchiveReadbackRequest, 'archive_id'>,
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<ArchiveReadbackResponse> {
  return w1Client(session).archive_readback(
    { archive_id: archiveId, ...request },
    {
      idempotencyKey: idempotencyKey ?? await archiveReadbackIdempotencyKey(
        archiveId,
        request.readback_receipt_ref,
      ),
      signal,
    },
  )
}

const API_BASE = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api`
const uploadIdempotencyKeys = new WeakMap<File, string>()

export class MediaWebApiError extends Error {
  code: string
  status: number
  details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'MediaWebApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const target = path.startsWith('/openclaw/') ? path : `${API_BASE}${path}`
  const response = await fetch(target, {
    credentials: 'same-origin',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const parsedError = mediaWebTaskErrorSchema.safeParse(payload)
    if (!parsedError.success) {
      throw new MediaWebApiError(response.status, 'invalid_error_response', '服务返回了无法识别的错误。')
    }
    const { code, message, details = null } = parsedError.data.error
    throw new MediaWebApiError(
      response.status,
      code,
      code === 'material_parsing_incomplete'
        ? materialParsingServerFailureMessage(code, message, details)
        : stableTaskErrorMessage(code, message),
      details,
    )
  }
  if (response.status === 204) return undefined as T
  try {
    return await response.json() as T
  } catch {
    throw new MediaWebApiError(response.status, 'invalid_response', '服务返回了无法识别的响应。')
  }
}

export async function loadMediaWebSession(): Promise<MediaWebSession> {
  const response = await request<unknown>('/session')
  return mediaWebSessionResponseSchema.parse(response).session
}

export async function loadTenantDashboard(signal?: AbortSignal): Promise<TenantDashboard> {
  return request<TenantDashboard>('/dashboard', { signal })
}

export async function loadAssetSummaries(
  options: { cursor?: string; pageSize?: number; signal?: AbortSignal } = {},
): Promise<AssetSummaryPage> {
  const query = new URLSearchParams({ pageSize: String(options.pageSize ?? 30) })
  if (options.cursor) query.set('cursor', options.cursor)
  return request<AssetSummaryPage>(`/assets?${query}`, { signal: options.signal })
}

export async function loadResourceDocxLink(
  resourceType: string,
  resourceId: string,
  signal?: AbortSignal,
): Promise<ResourceDocxLink> {
  const query = new URLSearchParams({ resourceType, resourceId })
  return request<ResourceDocxLink>(`/resources/docx-link?${query}`, { signal })
}

export async function loadAffiliateSummary(signal?: AbortSignal): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>('/account/affiliate', { signal })
}

function pageQuery(options: PageQuery): URLSearchParams {
  const query = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 30),
  })
  if (options.search) query.set('search', options.search)
  if (options.model) query.set('model', options.model)
  if (options.startTime) query.set('start_time', options.startTime)
  if (options.endTime) query.set('end_time', options.endTime)
  return query
}

export async function loadAffiliateInvitees(options: PageQuery = {}): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/account/invitees?${pageQuery(options)}`, { signal: options.signal })
}

export async function loadUsage(options: PageQuery = {}): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>('/billing/usage?limit=100', { signal: options.signal })
}

export async function loadBillingBalance(signal?: AbortSignal): Promise<BillingBalanceResponse> {
  return request<BillingBalanceResponse>('/billing/balance', { signal })
}

export async function listBillingBalancePacks(signal?: AbortSignal): Promise<BillingBalancePackListResponse> {
  return request<BillingBalancePackListResponse>('/billing/balance-packs', { signal })
}

export async function loadAdminBillingSummary(signal?: AbortSignal): Promise<AdminBillingSummary> {
  return request<AdminBillingSummary>('/admin/billing/summary?limit=100', { signal })
}

export async function loadAdminUpstreamSummary(signal?: AbortSignal): Promise<AdminUpstreamSummary> {
  const [health, reconciliation] = await Promise.all([
    request<{ ok: true; credential: Record<string, unknown> }>('/admin/upstream-credential/health', { signal }),
    request<{ ok: true; items: Array<Record<string, unknown>> }>('/admin/billing/reconciliation?limit=100', { signal }),
  ])
  return { credential: health.credential, reconciliation: reconciliation.items }
}

function mutationHeaders(session: MediaWebSession, idempotencyKey: string): Record<string, string> {
  try {
    return buildMutationHeaders({
      csrfToken: session.csrfToken,
      idempotencyKey,
      isMutation: true,
      authSource: 'session',
    })
  } catch (error) {
    if (error instanceof MissingCsrfTokenError) throw new MediaWebApiError(0, 'missing_csrf_token', error.message)
    throw error
  }
}

export async function redeemCode(session: MediaWebSession, code: string, idempotencyKey: string): Promise<RedemptionResult> {
  return request<RedemptionResult>('/billing/redeem', {
    method: 'POST', headers: mutationHeaders(session, idempotencyKey), body: JSON.stringify({ code }),
  })
}

export async function changeInitialPassword(
  session: MediaWebSession,
  oldPassword: string,
  newPassword: string,
  idempotencyKey: string,
): Promise<{ ok: true; reauthenticationRequired: true }> {
  return request<{ ok: true; reauthenticationRequired: true }>('/openclaw/auth/password', {
    method: 'PUT',
    headers: mutationHeaders(session, idempotencyKey),
    body: JSON.stringify({ oldPassword, newPassword, idempotencyKey }),
  })
}

export async function logoutMediaSession(session: MediaWebSession): Promise<{ ok: true }> {
  return request<{ ok: true }>('/openclaw/auth/logout', {
    method: 'POST',
    headers: mutationHeaders(session, newIdempotencyKey('logout')),
    body: '{}',
  })
}

export async function adminGet<T = Record<string, unknown>>(path: string, signal?: AbortSignal): Promise<T> {
  if (!path.startsWith('/admin/')) throw new Error('Invalid admin path')
  return request<T>(path, { signal })
}

export async function adminMutate<T = Record<string, unknown>>(
  session: MediaWebSession,
  path: string,
  method: 'POST' | 'PUT' | 'DELETE',
  payload: Record<string, unknown>,
  idempotencyKey: string,
): Promise<T> {
  if (!path.startsWith('/admin/')) throw new Error('Invalid admin path')
  return request<T>(path, {
    method, headers: mutationHeaders(session, idempotencyKey), body: JSON.stringify(payload),
  })
}

export async function loadMediaCapabilities(): Promise<CapabilityCatalog> {
  return capabilityCatalogSchema.parse(await request<unknown>('/capabilities'))
}

export async function loadMediaTasks(): Promise<MediaWebTask[]> {
  const result = await request<{ tasks: MediaWebTask[] }>('/tasks?limit=100')
  return result.tasks.map((item) => mediaWebTaskSchema.parse(item) as MediaWebTask)
}

export async function loadMediaTask(taskId: string): Promise<MediaWebTask> {
  return mediaWebTaskSchema.parse(await request<unknown>(`/tasks/${encodeURIComponent(taskId)}`)) as MediaWebTask
}

export async function createMediaTask(
  session: MediaWebSession,
  payload: MediaWebTaskCreateRequest,
): Promise<MediaWebTask> {
  const requestPayload = mediaWebTaskCreateRequestSchema.parse(payload)
  return mediaWebTaskSchema.parse(await request<unknown>('/tasks', {
    method: 'POST',
    headers: mutationHeaders(session, requestPayload.idempotencyKey),
    body: JSON.stringify(requestPayload),
  })) as MediaWebTask
}

export async function matchMediaCapabilities(
  session: MediaWebSession,
  payload: { query: string; currentBot: 'media'; catalogVersion: string; idempotencyKey: string },
  signal?: AbortSignal,
): Promise<CapabilityMatchResponse> {
  return capabilityMatchResponseSchema.parse(await request<unknown>('/capability-match', {
    method: 'POST', headers: mutationHeaders(session, payload.idempotencyKey), body: JSON.stringify(payload), signal,
  }))
}

export async function cancelMediaTask(session: MediaWebSession, taskId: string): Promise<MediaWebTask> {
  return mediaWebTaskSchema.parse(await request<unknown>(`/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
    headers: mutationHeaders(session, `task-cancel-${taskId}`),
    body: '{}',
  }))
}

export async function confirmMediaTask(
  session: MediaWebSession,
  taskId: string,
  decision: 'approve' | 'reject',
): Promise<MediaWebTask> {
  return mediaWebTaskSchema.parse(await request<unknown>(`/tasks/${encodeURIComponent(taskId)}/confirm`, {
    method: 'POST',
    headers: mutationHeaders(session, `task-confirm-${taskId}-${decision}`),
    body: JSON.stringify({ decision, note: '' }),
  }))
}

function fileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('文件读取失败。'))
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.readAsDataURL(file)
  })
}

export async function uploadMediaFile(session: MediaWebSession, file: File): Promise<MediaWebUpload> {
  let idempotencyKey = uploadIdempotencyKeys.get(file)
  if (!idempotencyKey) {
    idempotencyKey = newIdempotencyKey('upload')
    uploadIdempotencyKeys.set(file, idempotencyKey)
  }
  const response = await request<unknown>('/uploads', {
    method: 'POST',
    headers: mutationHeaders(session, idempotencyKey),
    body: JSON.stringify({
      schemaVersion: '3',
      filename: file.name,
      mimeType: file.type,
      contentBase64: await fileAsBase64(file),
      idempotencyKey: idempotencyKey,
    }),
  })
  return mediaWebUploadSchema.parse(response)
}

export function subscribeToMediaTask(taskId: string, onEvent: () => void): () => void {
  const source = new EventSource(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/events`, { withCredentials: true })
  const refresh = () => onEvent()
  for (const event of ['task.created', 'task.status', 'task.confirmation', 'task.result', 'task.error', 'task.cancelled']) {
    source.addEventListener(event, refresh)
  }
  source.onerror = () => onEvent()
  return () => source.close()
}

export function loginUrl(): string {
  return authPageUrl('login', currentLocationForReturn())
}
