/** 演示站假后端：在浏览器里拦截 fetch 与 EventSource，用生成的数据集回放业务响应。
 *
 *  这里没有身份校验，也没有任何真实服务调用：静态演示站只需要让真实页面组件跑起来。
 *  路由表直接复用生产合同 `generatedBusinessPagesContract` 的 operations，
 *  因此演示站不可能出现合同之外的接口。 */
import { operations as businessOperations } from '../media/generatedBusinessPagesContract'
import type {
  ArchiveArtifact,
  ArchiveRecord,
  Device,
  LocalAgentJob,
  PipelineSummary,
} from '../media/generatedProductContract'
import generatedDataset from './generatedDemoDataset.json'
import generatedCatalog from './generatedDemoCatalog.json'
import { activePersona } from './demoPersonas'

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
type JsonObject = { [key: string]: JsonValue }

type DatasetEntry = {
  method: string
  path: string
  payload: JsonObject
  parameter?: string
  payloads?: Record<string, JsonObject>
}

type DemoDataset = {
  schemaVersion: string
  contractSha256: string
  generatedAt: string
  operations: Record<string, DatasetEntry>
}

const dataset = generatedDataset as unknown as DemoDataset
const catalog = generatedCatalog as unknown as {
  schemaVersion: string
  catalogVersion: string
  capabilities: Array<{
    capabilityId: string
    displayName: string
    label: string
    hierarchy: { pathNames: string[] }
    requiresConfirmation: boolean
    confirmationPolicy: { stage: string; message: string }
    variants: Array<{ variantId: string; label: string }>
  }>
}

const SCHEMA_VERSION = 'media_web_business_pages_v2'
const TASK_SCHEMA_VERSION = 'media_web_task_v3'

/** 演示世界的“现在”与数据集保持一致，避免页面上出现未来时间。 */
const demoNow = () => new Date().toISOString()
const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60 * 1000).toISOString()

const store: Record<string, DatasetEntry> = structuredClone(dataset.operations)

/* ------------------------------------------------------------------ *
 * 任务状态机：演示站里唯一真正“会动”的部分
 * ------------------------------------------------------------------ */

type DemoTask = JsonObject & {
  taskId: string
  capabilityId: string
  status: string
  terminal: boolean
  progress: number
}

const tasks = new Map<string, DemoTask>()
const taskTimers = new Map<string, number>()

function digest(seed: string): string {
  let hash = 0x811c9dc5
  const parts: string[] = []
  for (let round = 0; round < 8; round += 1) {
    for (let index = 0; index < seed.length; index += 1) {
      hash ^= seed.charCodeAt(index) + round
      hash = Math.imul(hash, 0x01000193) >>> 0
    }
    parts.push(hash.toString(16).padStart(8, '0'))
  }
  return parts.join('')
}

function capability(capabilityId: string) {
  return catalog.capabilities.find((item) => item.capabilityId === capabilityId)
}

function capabilityPath(capabilityId: string): string[] {
  const names = capability(capabilityId)?.hierarchy.pathNames
  if (names && names.length >= 2) return names.slice(0, 3)
  return ['内容生产', '演示能力']
}

function taskSummary(capabilityId: string, params: JsonObject): string {
  const definition = capability(capabilityId)
  const firstValue = Object.values(params).find((value) => typeof value === 'string' && value.trim().length > 0)
  const detail = typeof firstValue === 'string' ? `：${firstValue.slice(0, 40)}` : ''
  return `${definition?.displayName ?? definition?.label ?? capabilityId}${detail}`
}

function requiresConfirmation(capabilityId: string, receipt: JsonValue): boolean {
  if (receipt && typeof receipt === 'object' && !Array.isArray(receipt)) return true
  return capability(capabilityId)?.requiresConfirmation ?? false
}

function newTask(capabilityId: string, variantId: string, params: JsonObject, receipt: JsonValue): DemoTask {
  const taskId = `demo_task_${Date.now().toString(36)}_${Math.floor(Math.random() * 4096).toString(36)}`
  return {
    schemaVersion: TASK_SCHEMA_VERSION,
    taskId,
    requestId: `demo_request_${taskId}`,
    modelCalls: [],
    capabilityId,
    capabilityPath: capabilityPath(capabilityId),
    variantId,
    params,
    status: 'queued',
    settlementStage: 'queued',
    terminal: false,
    progress: 5,
    summary: taskSummary(capabilityId, params),
    createdAt: demoNow(),
    updatedAt: demoNow(),
    confirmationReceipt: receipt,
    confirmation: {
      state: requiresConfirmation(capabilityId, receipt) ? 'required' : 'not_required',
      required: requiresConfirmation(capabilityId, receipt),
      note: '',
      decidedAt: '',
    },
    result: null,
    error: null,
    eventCursor: 1,
  }
}

function settleTask(
  task: DemoTask,
  status: 'succeeded' | 'cancelled' | 'pending_manual',
  resultReceipt: JsonValue = null,
): void {
  task.status = status
  task.settlementStage = status === 'succeeded' ? 'settled' : status
  task.terminal = true
  task.progress = 100
  task.updatedAt = demoNow()
  task.eventCursor = Number(task.eventCursor ?? 0) + 1
  task.result =
    status === 'succeeded'
      ? {
          ok: true,
          status: 'completed',
          reply: `${task.summary} 已在演示环境完成。真实环境会在这里返回产物链接与证据。`,
          links: [{ label: '查看演示产物', url: 'https://demo.mediaclaw.example/artifacts/demo' }],
          receipt: resultReceipt,
        }
      : {
          ok: false,
          status: 'needs_attention',
          reply: '任务已取消，演示数据未发生变化。',
          links: [],
          receipt: null,
        }
}

/** 推进任务：排队 → 执行 → （待确认 |已完成）。演示站用定时器模拟真实的流转节奏。 */
function scheduleTask(task: DemoTask): void {
  const advance = (stage: number) => {
    const current = tasks.get(task.taskId)
    if (!current || current.terminal) return
    if (stage === 1) {
      current.status = 'generating'
      current.settlementStage = 'running'
      current.progress = 45
      current.updatedAt = demoNow()
      current.eventCursor = Number(current.eventCursor ?? 0) + 1
      taskTimers.set(task.taskId, window.setTimeout(() => advance(2), 1400))
      return
    }
    const confirmation = current.confirmation as JsonObject | null
    if (confirmation && confirmation.required === true) {
      current.status = 'awaiting_confirmation'
      current.settlementStage = 'awaiting_confirmation'
      current.progress = 80
      current.updatedAt = demoNow()
      current.eventCursor = Number(current.eventCursor ?? 0) + 1
      return
    }
    settleTask(current, 'succeeded')
  }
  taskTimers.set(task.taskId, window.setTimeout(() => advance(1), 900))
}

function deletionReceipt(taskId: string, targetIds: string[]): JsonObject {
  return {
    kind: 'deletion_preview',
    previewTaskId: taskId,
    targetIds,
    targetCount: targetIds.length,
    entityCount: targetIds.length * 3,
    planDigest: `sha256:${digest(targetIds.join('|'))}`,
    expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
  }
}

function seedTasks(): void {
  if (tasks.size > 0) return
  const finished = newTask('selfmedia_creation', 'default', { topic: '秋日相机测评：X100VI 城市实拍' }, null)
  finished.createdAt = new Date(Date.now() - 3 * 3600 * 1000).toISOString()
  settleTask(finished, 'succeeded')

  const waiting = newTask('creation_decision_brief', 'default', { topic: '苏州河支线改为夜拍路线' }, null)
  waiting.createdAt = new Date(Date.now() - 40 * 60 * 1000).toISOString()
  waiting.status = 'awaiting_confirmation'
  waiting.settlementStage = 'awaiting_confirmation'
  waiting.progress = 80
  waiting.confirmation = { state: 'required', required: true, note: '', decidedAt: '' }

  const running = newTask('viral_deconstruction', 'default', { url: 'https://demo.mediaclaw.example/posts/hotpot' }, null)
  running.createdAt = new Date(Date.now() - 4 * 60 * 1000).toISOString()
  running.status = 'generating'
  running.settlementStage = 'running'
  running.progress = 45

  // 商单履约页只看 commercial_delivery_draft 任务，没有它整页都是空态。
  const deliveryDone = newTask(
    'commercial_delivery_draft',
    'default',
    { brand: '三顿半（演示）', topic: '秋季限定礼盒 · 小红书图文交付' },
    null,
  )
  deliveryDone.createdAt = new Date(Date.now() - 26 * 3600 * 1000).toISOString()
  settleTask(deliveryDone, 'succeeded')

  const deliveryWaiting = newTask(
    'commercial_delivery_draft',
    'default',
    { brand: '光影相机（演示）', topic: '随身相机长测 · B站长视频交付' },
    null,
  )
  deliveryWaiting.createdAt = new Date(Date.now() - 90 * 60 * 1000).toISOString()
  deliveryWaiting.status = 'awaiting_confirmation'
  deliveryWaiting.settlementStage = 'awaiting_confirmation'
  deliveryWaiting.progress = 80
  deliveryWaiting.confirmation = { state: 'required', required: true, note: '', decidedAt: '' }

  for (const task of [finished, waiting, running, deliveryDone, deliveryWaiting]) tasks.set(task.taskId, task)
}

/* ------------------------------------------------------------------ *
 * 本机 Agent / 云端归档（W1 产品合同，路径不在业务分页合同里）
 * ------------------------------------------------------------------ */

const catalogDigest = `sha256:${digest('demo-pipeline-catalog')}`

const demoPipelines: PipelineSummary[] = [
  { pipeline_id: 'project_preparation', version: '3.1.0', display_name: '项目准备', catalog_digest: catalogDigest },
  { pipeline_id: 'material_organization', version: '5.2.0', display_name: '素材整理', catalog_digest: catalogDigest },
  { pipeline_id: 'material_matching', version: '4.0.1', display_name: '素材匹配', catalog_digest: catalogDigest },
  { pipeline_id: 'edit_handoff', version: '6.3.0', display_name: '剪辑交接', catalog_digest: catalogDigest },
  { pipeline_id: 'editable_timeline', version: '2.4.0', display_name: '可编辑时间线', catalog_digest: catalogDigest },
  { pipeline_id: 'final_review', version: '3.0.2', display_name: '成片复核', catalog_digest: catalogDigest },
]

const demoDevices: Device[] = [
  {
    device_id: 'device_macbook_demo',
    state: 'online',
    device_label: '小满的 MacBook Pro',
    device_platform: 'macos',
    client_version: '2026.8.3',
    capabilities: ['material_organization', 'edit_handoff', 'editable_timeline'],
    revision: 12,
    last_seen_at: minutesAgo(1),
  },
  {
    device_id: 'device_studio_mini',
    state: 'paired',
    device_label: '工作室 Mac mini',
    device_platform: 'macos',
    client_version: '2026.7.1',
    capabilities: ['final_review'],
    revision: 9,
    last_seen_at: minutesAgo(6 * 60),
  },
]

function demoJob(overrides: Partial<LocalAgentJob> & Pick<LocalAgentJob, 'job_id' | 'state' | 'pipeline_id'>): LocalAgentJob {
  return {
    pipeline_version: demoPipelines.find((item) => item.pipeline_id === overrides.pipeline_id)?.version ?? '1.0.0',
    catalog_digest: catalogDigest,
    device_id: 'device_macbook_demo',
    input_refs: ['media://demo/source/autumn-camera'],
    output_selection: ['descriptor_only'],
    confirmation_ref: null,
    revision: 3,
    lease_id: null,
    lease_expires_at: null,
    ack_ref: null,
    acknowledged_at: null,
    start_ref: null,
    started_at: null,
    result_status: null,
    result_refs: [],
    artifact_refs: [],
    failure_code: null,
    created_at: minutesAgo(300),
    updated_at: minutesAgo(240),
    leased_at: null,
    completed_at: null,
    ...overrides,
  }
}

const demoJobs: LocalAgentJob[] = [
  demoJob({
    job_id: 'job_material_organization_01',
    state: 'succeeded',
    pipeline_id: 'material_organization',
    result_status: 'succeeded',
    result_refs: ['media://demo/result/material-index'],
    artifact_refs: ['artifact_asset_digest_autumn'],
    started_at: minutesAgo(290),
    completed_at: minutesAgo(240),
    updated_at: minutesAgo(240),
  }),
  demoJob({
    job_id: 'job_edit_handoff_02',
    state: 'running',
    pipeline_id: 'edit_handoff',
    lease_id: 'lease_demo_0002',
    lease_expires_at: minutesAgo(-20),
    ack_ref: 'ack_demo_0002',
    acknowledged_at: minutesAgo(28),
    start_ref: 'start_demo_0002',
    started_at: minutesAgo(26),
    leased_at: minutesAgo(30),
    created_at: minutesAgo(32),
    updated_at: minutesAgo(2),
    revision: 5,
  }),
  demoJob({
    job_id: 'job_final_review_03',
    state: 'blocked',
    pipeline_id: 'final_review',
    device_id: 'device_studio_mini',
    result_status: 'blocked',
    failure_code: 'awaiting_human_confirmation',
    created_at: minutesAgo(26 * 60),
    updated_at: minutesAgo(25 * 60),
    started_at: minutesAgo(25 * 60 + 30),
    revision: 4,
  }),
]

function demoArtifact(ref: string, mimeType: string, sizeBytes: number, descriptor: boolean): ArchiveArtifact {
  return {
    ref,
    mode: descriptor ? 'descriptor_only' : 'content',
    mime_type: mimeType,
    sha256: digest(ref).slice(0, 64),
    size_bytes: sizeBytes,
    descriptor,
    metadata: { 说明: descriptor ? '媒体本体留在本机设备，云端只保存描述符' : '轻量文本产物' },
    content: descriptor ? null : { encoding: 'utf8', value: '演示环境的示例产物内容。' },
  }
}

function demoArchive(
  archiveId: string,
  runId: string,
  pipelineId: string,
  cloudBytes: number,
  artifacts: ArchiveArtifact[],
): ArchiveRecord {
  return {
    archive_id: archiveId,
    state: 'active',
    commit_id: `commit_${archiveId}`,
    manifest_id: `manifest_${archiveId}`,
    run_id: runId,
    pipeline_id: pipelineId,
    pipeline_version: demoPipelines.find((item) => item.pipeline_id === pipelineId)?.version ?? '1.0.0',
    device_id: 'device_macbook_demo',
    artifacts,
    projections: [
      {
        projection_id: `projection_${archiveId}_db`,
        kind: 'db',
        ref: `db://demo/${archiveId}`,
        artifact_refs: artifacts.map((item) => item.ref),
        consistent: true,
      },
    ],
    cloud_bytes: cloudBytes,
    media_cloud_bytes: 0,
    revision: 4,
    created_at: minutesAgo(20 * 60),
    updated_at: minutesAgo(18 * 60),
  }
}

let demoArchives: ArchiveRecord[] = [
  demoArchive('archive_autumn_camera', 'run_autumn_camera_01', 'edit_handoff', 18422, [
    demoArtifact('media://demo/final/autumn-camera.mov', 'video/quicktime', 984_233_120, true),
    demoArtifact('media://demo/report/autumn-camera-handoff.md', 'text/markdown', 4_128, false),
  ]),
  demoArchive('archive_citywalk_suzhou', 'run_citywalk_suzhou_02', 'material_organization', 6_240, [
    demoArtifact('media://demo/index/citywalk-material.json', 'application/json', 6_240, false),
  ]),
]

/* ------------------------------------------------------------------ *
 * 路由
 * ------------------------------------------------------------------ */

type RouteMatch = { operationId: string; parameters: Record<string, string> }

const apiPrefixes = [
  `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api`,
  '/openclaw/media/api',
  '/media/api',
]

function apiPath(pathname: string): string | null {
  for (const prefix of apiPrefixes) {
    if (prefix && pathname.startsWith(prefix)) return pathname.slice(prefix.length) || '/'
  }
  return null
}

const routePatterns = Object.entries(businessOperations).map(([operationId, operation]) => ({
  operationId,
  method: operation.method,
  parameters: operation.pathParameters,
  pattern: new RegExp(`^${operation.path.replace(/\{[^{}]+\}/g, '([^/]+)')}$`),
}))

function matchRoute(method: string, path: string): RouteMatch | null {
  for (const route of routePatterns) {
    if (route.method !== method) continue
    const found = route.pattern.exec(path)
    if (!found) continue
    const parameters: Record<string, string> = {}
    route.parameters.forEach((name, index) => {
      parameters[name] = decodeURIComponent(found[index + 1] ?? '')
    })
    return { operationId: route.operationId, parameters }
  }
  return null
}

function json(payload: JsonValue, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  })
}

function failure(status: number, code: string, message: string): Response {
  return json({ error: { code, message, details: null } }, status)
}

/* ------------------------------------------------------------------ *
 * 列表查询：搜索、筛选与分页在演示站里也真实生效
 * ------------------------------------------------------------------ */

const filterKeys = [
  'status',
  'stage',
  'platform',
  'decisionStatus',
  'candidateType',
  'kind',
  'subjectType',
  'reviewWindow',
  'publicTrackId',
  'publicProjectId',
  'publicAccountId',
  'publicPostId',
  'publicRunId',
  'publicPackageId',
  'publicCreatorId',
  'artifactType',
  'mediaType',
]

function itemMatchesSearch(item: JsonValue, term: string): boolean {
  return JSON.stringify(item).toLowerCase().includes(term.toLowerCase())
}

function applyListQuery(payload: JsonObject, query: URLSearchParams): JsonObject {
  const items = payload.items
  if (!Array.isArray(items)) return payload
  let filtered = items as JsonValue[]

  const search = query.get('search') ?? query.get('q') ?? query.get('keyword')
  if (search && search.trim()) filtered = filtered.filter((item) => itemMatchesSearch(item, search.trim()))

  for (const key of filterKeys) {
    const value = query.get(key)
    if (!value) continue
    filtered = filtered.filter((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return true
      const field = (item as JsonObject)[key]
      if (field === undefined) return true
      if (Array.isArray(field)) return field.some((entry) => String(entry) === value)
      return String(field) === value
    })
  }

  const size = Number(query.get('pageSize') ?? query.get('limit') ?? 0)
  const cursor = Number(query.get('cursor') ?? 0)
  const start = Number.isFinite(cursor) && cursor > 0 ? cursor : 0
  if (size > 0) {
    const page = filtered.slice(start, start + size)
    const nextIndex = start + size
    return {
      ...payload,
      items: page,
      nextCursor: nextIndex < filtered.length ? String(nextIndex) : null,
    }
  }
  return { ...payload, items: filtered, nextCursor: null }
}

/** 组织身份下正文权威在飞书：数据集只存一份文档，读取时按当前身份改写权威字段，
 *  这样组织工作区拿到的就是 lark 正文投影，而不是个人内部正文。 */
function adaptToPersona(payload: JsonValue): JsonValue {
  if (activePersona().session.workspaceMode !== 'organization_lark') return payload
  if (Array.isArray(payload)) return payload.map(adaptToPersona)
  if (!payload || typeof payload !== 'object') return payload
  const adapted: JsonObject = {}
  for (const [key, value] of Object.entries(payload)) {
    if (key === 'bodyAuthority' && value === 'internal') adapted[key] = 'lark'
    else if (key === 'workspaceMode' && value === 'personal_web') adapted[key] = 'organization_lark'
    else if (key === 'syncStatus' && value === 'not_applicable') adapted[key] = 'synced'
    else adapted[key] = adaptToPersona(value)
  }
  return adapted
}

function entryPayload(entry: DatasetEntry, parameters: Record<string, string>): JsonObject {
  if (entry.parameter && entry.payloads) {
    const key = parameters[entry.parameter]
    const keyed = key ? entry.payloads[key] : undefined
    if (keyed) return keyed
  }
  return entry.payload
}

/* ------------------------------------------------------------------ *
 * 变更操作：演示站把写入落到内存里，页面刷新前保持一致
 * ------------------------------------------------------------------ */

function listItems(operationId: string): JsonObject[] {
  const entry = store[operationId]
  const items = entry?.payload?.items
  return Array.isArray(items) ? (items as JsonObject[]) : []
}

function receipt(): JsonObject {
  return { schemaVersion: SCHEMA_VERSION, revision: Math.floor(Date.now() / 1000) % 100000, ok: true, updatedAt: demoNow() }
}

function applyMutation(operationId: string, parameters: Record<string, string>, body: JsonObject): JsonValue | undefined {
  switch (operationId) {
    case 'confirmDecision': {
      const decision = String(body.decision ?? 'confirmed')
      const target = parameters.publicDecisionId
      for (const item of listItems('listDecisions')) {
        if (item.publicDecisionId !== target) continue
        item.decisionStatus = decision === 'rejected' ? 'rejected' : 'confirmed'
        item.humanConfirmedAt = demoNow()
        item.updatedAt = demoNow()
      }
      const updated = listItems('listDecisions').find((item) => item.publicDecisionId === target)
      const detail = store.getDecision
      if (detail && updated) {
        const keyed = detail.payloads?.[target] ?? detail.payload
        keyed.decision = { ...updated }
      }
      // 页面会读回 decision 字段做校验，只给通用回执会被判定为「字段未开放」。
      return {
        schemaVersion: SCHEMA_VERSION,
        revision: Number(updated?.evidenceCount ?? 1) + 1,
        decision: updated ?? null,
      }
    }
    case 'confirmReview': {
      const target = parameters.publicReviewId
      for (const item of listItems('listReviews')) {
        if (item.publicReviewId !== target) continue
        item.status = 'confirmed'
        item.humanDecision = String(body.humanDecision ?? '已确认复盘结论')
        item.revision = Number(item.revision ?? 1) + 1
      }
      return receipt()
    }
    case 'updatePublishingChecks': {
      const target = parameters.publicPackageId
      const updated = listItems('listPublishingPackages').find((item) => item.publicPackageId === target)
      if (!updated) return undefined
      if (Array.isArray(body.checks)) updated.humanChecks = body.checks as JsonValue[]
      const outstanding = Array.isArray(updated.humanChecks)
        ? (updated.humanChecks as JsonObject[]).some((check) => String(check.状态 ?? check.status ?? '') !== '已确认')
        : false
      updated.status = outstanding ? 'checking' : 'ready'
      updated.revision = Number(updated.revision ?? 1) + 1
      const detail = store.getPublishingPackage
      if (detail) {
        const keyed = detail.payloads?.[target] ?? detail.payload
        keyed.package = { ...updated }
      }
      // 发布页保存后直接读 response.package，缺字段会让整页崩掉。
      return { schemaVersion: SCHEMA_VERSION, revision: Number(updated.revision), package: updated }
    }
    case 'updateAccountMonitor': {
      const monitor = store.getAccountMonitor
      if (monitor) {
        const payload = monitor.payloads?.[parameters.publicAccountId] ?? monitor.payload
        if (typeof body.enabled === 'boolean') payload.enabled = body.enabled
        if (Array.isArray(body.recentPostUrls)) payload.recentPostUrls = body.recentPostUrls as JsonValue[]
        payload.checkedAt = demoNow()
      }
      return store.getAccountMonitor?.payload
    }
    case 'updateTrackRelationshipStatus': {
      const target = parameters.publicRelationshipId
      for (const item of listItems('listTrackRelationships')) {
        if (item.publicRelationshipId !== target) continue
        item.status = String(body.status ?? '已确认')
        item.revision = Number(item.revision ?? 1) + 1
        item.lastEvaluatedAt = demoNow()
      }
      return receipt()
    }
    case 'redeemBillingCode': {
      const balance = store.getBillingBalance?.payload.balance
      if (balance && typeof balance === 'object' && !Array.isArray(balance)) {
        balance.available = (Number(balance.available ?? 0) + 100).toFixed(2)
        balance.asOf = demoNow()
      }
      return {
        ok: true,
        fulfillment: {
          fulfillmentId: `demo_fulfillment_${Date.now().toString(36)}`,
          planCode: 'balance_starter',
          creditedAmount: '100.00',
          affiliateAmount: '0.00',
          status: 'succeeded',
        },
      }
    }
    case 'updateAdminRegistrationPolicy': {
      const policy = store.getAdminRegistrationPolicy?.payload.policy
      if (policy && typeof policy === 'object' && !Array.isArray(policy)) {
        policy.mode = String(body.mode ?? 'invite_only')
        policy.revision = Number(policy.revision ?? 1) + 1
        policy.updatedAt = demoNow()
      }
      return store.getAdminRegistrationPolicy?.payload
    }
    case 'updateAdminAffiliateUser': {
      const target = parameters.userId
      for (const item of listItems('listAdminAffiliateUsers')) {
        if (item.publicUserId !== target) continue
        if (typeof body.affiliateEnabled === 'boolean') item.affiliateEnabled = body.affiliateEnabled
        if (typeof body.invitationQuota === 'number') item.invitationQuota = body.invitationQuota
        item.updatedAt = demoNow()
        return { schemaVersion: SCHEMA_VERSION, revision: Number(item.invitationQuota ?? 0), user: item }
      }
      return undefined
    }
    case 'createAdminAdmissionBatch': {
      const created: JsonObject = {
        batchId: `batch_demo_${Date.now().toString(36)}`,
        name: String(body.name ?? '演示准入批次'),
        status: '生效中',
        codeCount: Number(body.codeCount ?? 10),
        usedCount: 0,
        expiresAt: new Date(Date.now() + 30 * 86400 * 1000).toISOString(),
        createdAt: demoNow(),
      }
      // 页面创建后会在列表里读回同一个批次，静态回执对不上就会报「未读到服务端返回的批次」。
      listItems('listAdminAdmissionBatches').unshift(created)
      return { schemaVersion: SCHEMA_VERSION, revision: 1, batch: created }
    }
    case 'disableAdminAdmissionBatch': {
      const target = parameters.batchId
      for (const item of listItems('listAdminAdmissionBatches')) {
        if (item.batchId !== target) continue
        item.status = '已停用'
        return { schemaVersion: SCHEMA_VERSION, revision: 1, batch: item }
      }
      return undefined
    }
    case 'rotateAdminUpstreamCredential':
    case 'revokeAdminUpstreamCredential':
    case 'reconcileAdminBillingOperation': {
      const entry = store.getAdminUpstreams
      const summary = entry?.payload.summary
      if (summary && typeof summary === 'object' && !Array.isArray(summary)) {
        // 运维动作必须真的改变随后读回的汇总，否则「成功」提示是误导。
        if (operationId === 'rotateAdminUpstreamCredential') {
          summary.credentialHealth = 'healthy'
          summary.unhealthyAccountCount = 0
        }
        if (operationId === 'revokeAdminUpstreamCredential') {
          summary.credentialHealth = 'revoked'
          summary.availableAccountCount = 0
        }
        if (operationId === 'reconcileAdminBillingOperation') summary.pendingReconciliationCount = 0
        summary.lastSyncedAt = demoNow()
        summary.revision = Number(summary.revision ?? 1) + 1
        if (entry) entry.payload.revision = Number(summary.revision)
      }
      // 对账走通用回执，凭证轮换/撤销则要求返回完整汇总，页面会当场校验。
      if (operationId === 'reconcileAdminBillingOperation') return receipt()
      if (!summary || !entry) return undefined
      return { schemaVersion: SCHEMA_VERSION, revision: Number(entry.payload.revision), summary }
    }
    case 'createAdminBillingGrant':
    case 'createAdminRedemptionBatch':
    case 'createAdminProductMapping':
    case 'recoverAdminFulfillment':
    case 'refundAdminFulfillment': {
      const summary = store.getAdminBillingSummary?.payload.summary
      if (summary && typeof summary === 'object' && !Array.isArray(summary)) {
        if (operationId === 'createAdminBillingGrant' && Array.isArray(summary.grants)) {
          summary.grants.unshift({
            赠款单号: `grant_demo_${Date.now().toString(36)}`,
            租户: String(body.publicTenantId ?? 'tenant_demo'),
            金额: String(body.amount ?? '0.00'),
            原因: String(body.reason ?? '演示环境补发'),
            处理时间: demoNow(),
          })
        }
        if (operationId === 'createAdminRedemptionBatch' && Array.isArray(summary.redemptionBatches)) {
          summary.redemptionBatches.unshift({
            batchId: `redemption_demo_${Date.now().toString(36)}`,
            planCode: String(body.planCode ?? 'balance_starter'),
            status: '已签发',
            codeCount: Number(body.count ?? 10),
            redeemedCount: 0,
            createdAt: demoNow(),
          })
        }
        if (operationId === 'createAdminProductMapping' && Array.isArray(summary.productMappings)) {
          summary.productMappings.unshift({
            套餐编码: String(body.planCode ?? 'balance_starter'),
            外部商品号: String(body.externalProductId ?? 'demo-product'),
            购买链接: String(body.purchaseUrl ?? 'https://demo.mediaclaw.example/purchase/demo'),
            更新时间: demoNow(),
          })
        }
        if (
          (operationId === 'recoverAdminFulfillment' || operationId === 'refundAdminFulfillment') &&
          Array.isArray(summary.fulfillments)
        ) {
          const fulfillments = summary.fulfillments as JsonObject[]
          const target = fulfillments.find((item) => String(item.履约单号 ?? item.fulfillmentId ?? '') === parameters.fulfillmentId)
          if (target) target.状态 = operationId === 'refundAdminFulfillment' ? '已退款' : '已补发'
        }
        summary.ledgerRevision = Number(summary.ledgerRevision ?? 1) + 1
      }
      return receipt()
    }
    case 'pollAccountMonitor': {
      // 轮询必须回到保存后的监控状态，不能用一份写死的「不可用」把结果覆盖掉。
      const monitor = store.getAccountMonitor
      if (!monitor) return undefined
      const payload = monitor.payloads?.[parameters.publicAccountId] ?? monitor.payload
      payload.checkedAt = demoNow()
      payload.recentStatus = '已回读'
      return payload
    }
    case 'saveDocumentDraft': {
      const entry = store.getDocumentBody
      if (!entry) return undefined
      const payload = entry.payloads?.[parameters.publicArtifactId] ?? entry.payload
      const data = payload.data
      if (!data || typeof data !== 'object' || Array.isArray(data)) return undefined
      const revision = data.revision
      const artifact = data.artifact
      if (revision && typeof revision === 'object' && !Array.isArray(revision) && body.body) {
        revision.body = body.body
        revision.revision = Number(revision.revision ?? 1) + 1
        revision.baseRevision = Number(revision.revision) - 1
        revision.state = 'ready'
        revision.bodyChecksum = digest(JSON.stringify(body.body))
        revision.updatedAt = demoNow()
        if (artifact && typeof artifact === 'object' && !Array.isArray(artifact)) {
          artifact.currentRevision = Number(revision.revision)
          artifact.updatedAt = demoNow()
        }
        return { schemaVersion: SCHEMA_VERSION, revision: Number(revision.revision), data: revision }
      }
      return undefined
    }
    default:
      return undefined
  }
}

/* ------------------------------------------------------------------ *
 * 有状态接口
 * ------------------------------------------------------------------ */

function handleStateful(operationId: string, parameters: Record<string, string>, body: JsonObject): Response | null {
  switch (operationId) {
    case 'getMediaSession':
      return json({ schemaVersion: SCHEMA_VERSION, revision: 1, session: activePersona().session as unknown as JsonValue })
    case 'listMediaCapabilities':
      return json(catalog as unknown as JsonValue)
    case 'getDocumentRevision': {
      // 保存后页面会立刻按版本号读回正文核对；返回静态样例会让核对永远失败。
      const entry = store.getDocumentBody
      if (!entry) return failure(404, 'resource_not_found', '未找到该文档。')
      const payload = entry.payloads?.[parameters.publicArtifactId] ?? entry.payload
      const data = payload.data
      if (!data || typeof data !== 'object' || Array.isArray(data)) return failure(404, 'resource_not_found', '未找到该文档。')
      const revision = data.revision
      if (!revision || typeof revision !== 'object' || Array.isArray(revision)) {
        return failure(404, 'resource_not_found', '未找到该版本。')
      }
      if (String(revision.revision) !== parameters.revision) {
        return failure(404, 'resource_not_found', '未找到该版本。')
      }
      return json(adaptToPersona({ schemaVersion: SCHEMA_VERSION, revision: Number(revision.revision), data: revision }))
    }
    case 'matchMediaCapability': {
      const query = String(body.query ?? '')
      const matched =
        catalog.capabilities.find((item) => query && `${item.displayName}${item.label}`.includes(query)) ??
        catalog.capabilities.find((item) => item.capabilityId === 'selfmedia_creation') ??
        catalog.capabilities[0]
      return json({
        schemaVersion: SCHEMA_VERSION,
        revision: 1,
        match: {
          capabilityId: matched.capabilityId,
          variantId: matched.variants[0]?.variantId ?? 'default',
          confidence: 0.82,
          reason: '演示环境按关键词匹配，真实环境由模型给出匹配理由。',
          catalogVersion: catalog.catalogVersion,
        },
      })
    }
    case 'listMediaTasks': {
      seedTasks()
      const ordered = [...tasks.values()].sort((left, right) => String(right.createdAt).localeCompare(String(left.createdAt)))
      return json({ schemaVersion: TASK_SCHEMA_VERSION, tasks: ordered as unknown as JsonValue })
    }
    case 'getMediaTask': {
      const task = tasks.get(parameters.taskId)
      if (!task) return failure(404, 'resource_not_found', '未找到该任务。')
      return json(task as unknown as JsonValue)
    }
    case 'createMediaTask': {
      seedTasks()
      const capabilityId = String(body.capabilityId ?? 'selfmedia_creation')
      const variantId = String(body.variantId ?? 'default')
      const params = (body.params ?? {}) as JsonObject
      const supplied = body.confirmationReceipt ?? null
      const task = newTask(capabilityId, variantId, params, supplied)
      if (capabilityId === 'universal_deletion') {
        // 删除分两步：预览任务把影响面放在 result.receipt 里，确认任务带着同一份
        // 回执停在待确认状态，等页面点「确认删除」再结算。
        const targets = String(params.id ?? '')
          .split(/[、,，]/)
          .map((value) => value.trim())
          .filter(Boolean)
        const targetIds = targets.length ? targets : ['demo_target_0001']
        if (variantId !== 'confirm') {
          task.confirmation = { state: 'not_required', required: false, note: '', decidedAt: '' }
          settleTask(task, 'succeeded', deletionReceipt(task.taskId, targetIds))
          tasks.set(task.taskId, task)
          return json(task as unknown as JsonValue)
        }
        task.confirmationReceipt = supplied ?? deletionReceipt(task.taskId, targetIds)
        task.confirmation = { state: 'required', required: true, note: '', decidedAt: '' }
        task.status = 'awaiting_confirmation'
        task.settlementStage = 'awaiting_confirmation'
        task.progress = 80
        tasks.set(task.taskId, task)
        return json(task as unknown as JsonValue)
      }
      tasks.set(task.taskId, task)
      scheduleTask(task)
      return json(task as unknown as JsonValue)
    }
    case 'confirmMediaTask': {
      const task = tasks.get(parameters.taskId)
      if (!task) return failure(404, 'resource_not_found', '未找到该任务。')
      const decision = String(body.decision ?? 'approve')
      task.confirmation = {
        state: decision === 'approve' ? 'approved' : 'rejected',
        required: true,
        note: String(body.note ?? ''),
        decidedAt: demoNow(),
      }
      settleTask(task, decision === 'approve' ? 'succeeded' : 'cancelled')
      return json(task as unknown as JsonValue)
    }
    case 'cancelMediaTask': {
      const task = tasks.get(parameters.taskId)
      if (!task) return failure(404, 'resource_not_found', '未找到该任务。')
      const timer = taskTimers.get(task.taskId)
      if (timer) window.clearTimeout(timer)
      settleTask(task, 'cancelled')
      task.status = 'cancelled'
      return json(task as unknown as JsonValue)
    }
    case 'listMediaTaskEvents': {
      const task = tasks.get(parameters.taskId)
      if (!task) return failure(404, 'resource_not_found', '未找到该任务。')
      return json({
        schemaVersion: SCHEMA_VERSION,
        revision: 1,
        items: [
          { eventId: 1, eventType: 'task.created', status: 'queued', summary: '任务已创建', createdAt: String(task.createdAt) },
          { eventId: 2, eventType: 'task.status', status: String(task.status), summary: String(task.summary), createdAt: String(task.updatedAt) },
        ],
        nextCursor: null,
      })
    }
    case 'createMediaUpload': {
      const filename = String(body.filename ?? '演示素材')
      return json({
        schemaVersion: SCHEMA_VERSION,
        revision: 1,
        upload: {
          uploadId: `demo_upload_${Date.now().toString(36)}`,
          filename,
          mediaType: String(body.mediaType ?? 'application/octet-stream'),
          sizeBytes: String(body.contentBase64 ?? '').length,
          expiresAt: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        },
      })
    }
    default:
      return null
  }
}

function handleProductApi(method: string, path: string): Response | null {
  if (path === '/pipelines' && method === 'GET') {
    return json({ pipelines: demoPipelines, next_cursor: null } as unknown as JsonValue)
  }
  if (path === '/devices' && method === 'GET') {
    return json({ devices: demoDevices, next_cursor: null } as unknown as JsonValue)
  }
  if (path === '/pair-codes' && method === 'POST') {
    return json({ pair_code: 'DEMO-PAIR-4821', expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString() })
  }
  if (path === '/jobs' && method === 'GET') {
    return json({ jobs: demoJobs, next_cursor: null } as unknown as JsonValue)
  }
  if (path === '/jobs' && method === 'POST') {
    const created = demoJob({ job_id: `job_demo_${Date.now().toString(36)}`, state: 'queued', pipeline_id: 'material_organization' })
    demoJobs.unshift(created)
    return json({ job: created } as unknown as JsonValue)
  }
  const jobDetail = /^\/jobs\/([^/]+)$/.exec(path)
  if (jobDetail && method === 'GET') {
    const job = demoJobs.find((item) => item.job_id === decodeURIComponent(jobDetail[1]))
    if (!job) return failure(404, 'not_found', '未找到该本机任务。')
    return json({ job } as unknown as JsonValue)
  }
  if (path === '/archives' && method === 'GET') {
    return json({ archives: demoArchives, next_cursor: null } as unknown as JsonValue)
  }
  const archiveDetail = /^\/archives\/([^/]+)$/.exec(path)
  if (archiveDetail && method === 'GET') {
    const archive = demoArchives.find((item) => item.archive_id === decodeURIComponent(archiveDetail[1]))
    if (!archive) return failure(404, 'not_found', '未找到该归档记录。')
    return json({ archive } as unknown as JsonValue)
  }
  const deletePlan = /^\/archives\/([^/]+)\/delete-plan$/.exec(path)
  if (deletePlan && method === 'POST') {
    const archiveId = decodeURIComponent(deletePlan[1])
    const archive = demoArchives.find((item) => item.archive_id === archiveId)
    if (!archive) return failure(404, 'not_found', '未找到该归档记录。')
    return json({
      delete_plan_id: `delete_plan_${archiveId}`,
      archive_id: archiveId,
      expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
      artifact_refs: archive.artifacts.map((item) => item.ref),
      projection_refs: archive.projections.map((item) => item.ref),
      cloud_bytes: archive.cloud_bytes,
      media_cloud_bytes: 0,
      revision: archive.revision,
    } as unknown as JsonValue)
  }
  if (archiveDetail && method === 'DELETE') {
    const archiveId = decodeURIComponent(archiveDetail[1])
    const archive = demoArchives.find((item) => item.archive_id === archiveId)
    if (!archive) return failure(404, 'not_found', '未找到该归档记录。')
    demoArchives = demoArchives.filter((item) => item.archive_id !== archiveId)
    return json({
      archive: { ...archive, state: 'deleting', revision: archive.revision + 1, updated_at: demoNow() },
      delete_receipt: {
        receipt_ref: `receipt_delete_${archiveId}`,
        archive_id: archiveId,
        deleted_artifact_refs: archive.artifacts.map((item) => item.ref),
        deleted_projection_refs: archive.projections.map((item) => item.ref),
        verified: true,
        hard_deleted: true,
        deleted_at: demoNow(),
      },
    } as unknown as JsonValue)
  }
  const readback = /^\/archives\/([^/]+)\/readback$/.exec(path)
  if (readback && method === 'POST') {
    const archiveId = decodeURIComponent(readback[1])
    return json({
      archive_id: archiveId,
      readback_receipt: {
        receipt_ref: `receipt_readback_${archiveId}`,
        archive_id: archiveId,
        verified: true,
        db_present: true,
        attachments_present: true,
        projections_present: true,
        checked_at: demoNow(),
      },
    } as unknown as JsonValue)
  }
  if (path === '/cli/releases/compatibility' && method === 'POST') {
    return json({ compatible: true, minimum_version: '2026.6.0', latest_version: '2026.8.3' })
  }
  if (path.startsWith('/organization/provision')) {
    if (method === 'GET') return json({ schemaVersion: 'media.stage1.provision.v1', run: null })
    return json({
      schemaVersion: 'media.stage1.provision.v1',
      run: {
        provisionRunId: `demo_provision_${Date.now().toString(36)}`,
        installationId: 'demo_installation_0001',
        tenantId: 'demo_tenant_0001',
        status: 'SUCCEEDED',
        state: 'ACTIVE',
        completedSteps: ['校验安装', '创建组织空间', '同步成员'],
        failedStep: null,
        retryAvailable: false,
        retryAfter: null,
      },
    })
  }
  return null
}

/* ------------------------------------------------------------------ *
 * fetch / EventSource 拦截
 * ------------------------------------------------------------------ */

async function readBody(init: RequestInit | undefined, input: RequestInfo | URL): Promise<JsonObject> {
  const raw = init?.body ?? (input instanceof Request ? await input.clone().text() : undefined)
  if (typeof raw !== 'string' || !raw.trim()) return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as JsonObject) : {}
  } catch {
    return {}
  }
}

async function demoFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const href = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(href, window.location.origin)
  const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()

  if (url.pathname.startsWith('/openclaw/auth/')) {
    return url.pathname.endsWith('/logout') ? new Response(null, { status: 204 }) : json({ ok: true })
  }

  const path = apiPath(url.pathname)
  if (path === null) return originalFetch(input, init)

  const body = await readBody(init, input)
  const product = handleProductApi(method, path)
  if (product) return product

  const route = matchRoute(method, path)
  if (!route) return failure(404, 'resource_not_found', `演示站未实现该接口：${method} ${path}`)

  const stateful = handleStateful(route.operationId, route.parameters, body)
  if (stateful) return stateful

  if (method !== 'GET') {
    const mutated = applyMutation(route.operationId, route.parameters, body)
    if (mutated !== undefined) return json(mutated)
  }

  const entry = store[route.operationId]
  if (!entry) return failure(404, 'resource_not_found', `演示数据集缺少 ${route.operationId} 的响应。`)
  const payload = entryPayload(entry, route.parameters)
  return json(adaptToPersona(method === 'GET' ? applyListQuery(payload, url.searchParams) : payload))
}

/** EventSource 在静态站点没有服务端可连；这里用定时器推动任务刷新，
 *  否则真实代码里的 `onerror -> onEvent` 会变成不断重试的空转。 */
class DemoEventSource extends EventTarget {
  readonly url: string
  readonly withCredentials = false
  readyState = 1
  onerror: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onopen: ((event: Event) => void) | null = null
  private timer: number

  constructor(url: string | URL) {
    super()
    this.url = String(url)
    let ticks = 0
    this.timer = window.setInterval(() => {
      ticks += 1
      this.dispatchEvent(new MessageEvent('task.status', { data: '{}' }))
      if (ticks >= 8) this.close()
    }, 1000)
  }

  close(): void {
    this.readyState = 2
    window.clearInterval(this.timer)
  }
}

const originalFetch = globalThis.fetch.bind(globalThis)
let installed = false

export function installDemoBackend(): void {
  if (installed) return
  installed = true
  seedTasks()
  globalThis.fetch = demoFetch as typeof fetch
  ;(globalThis as unknown as { EventSource: unknown }).EventSource = DemoEventSource
}

export const demoDatasetInfo = {
  contractSha256: dataset.contractSha256,
  generatedAt: dataset.generatedAt,
  operationCount: Object.keys(dataset.operations).length,
  capabilityCount: catalog.capabilities.length,
}
