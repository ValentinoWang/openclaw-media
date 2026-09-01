import { isPublicId } from './identifiers'

const MEDIA_BUSINESS_SCHEMA_VERSION = 'media_web_business_pages_v2'
const MEDIA_DOCUMENT_BODY_SCHEMA_VERSION = 'media.document.body.v1'

export type SyncLoadState = 'idle' | 'loading' | 'ready' | 'error'
export type SyncState = 'loading' | 'synced' | 'running' | 'unknown' | 'conflict' | 'unsupported' | 'stale' | 'partial' | 'unavailable'
export type SyncBatchOperation = 'read' | 'save' | null
export type SyncBatchState = 'queued' | 'running' | 'succeeded' | 'failed' | 'conflict' | null
export type SyncDetailKey = 'blockIds' | 'applied' | 'manualActions' | 'protectedSkipped'

export type MirrorSyncBatch = {
  publicSyncId: string
  publicArtifactId: string
  revision: number | null
  operation: SyncBatchOperation
  state: SyncBatchState
  remoteDocumentVersion: string | null
  bodyChecksum: string | null
  blockCount: number | null
  protectedBlockCount: number | null
  createdAt: string | null
  updatedAt: string | null
  completedAt: string | null
  errorCode: string | null
  errorDetail: Record<string, unknown> | null
}

export type SyncBatchListProjection = {
  status: 'available' | 'unavailable'
  items: MirrorSyncBatch[]
  nextCursor: string | null
}

export type DetailPart = { available: boolean; values: unknown[] }
export type ExecutionReceiptProjection = {
  status: 'ready' | 'failed'
  applied: unknown[] | null
  appliedCount: number | null
  manualActions: unknown[] | null
  protectedSkipped: unknown[] | null
  errorCode: string | null
}

export type SyncPipelineState = 'complete' | 'running' | 'attention' | 'pending'
export type SyncPipelineStep = { title: string; detail: string; state: SyncPipelineState }

export const syncStateLabels: Record<SyncState, string> = {
  loading: '正在读取同步记录',
  synced: '镜像已同步',
  running: '正在写入飞书',
  unknown: '写入结果待对账',
  conflict: '远端版本需要处理',
  unsupported: '部分内容暂不能同步',
  stale: '飞书已有更新，等待回读',
  partial: '部分内容已应用',
  unavailable: '同步记录暂不可读',
}

const syncBatchStates = new Set<Exclude<SyncBatchState, null>>(['queued', 'running', 'succeeded', 'failed', 'conflict'])
const syncBatchOperations = new Set<Exclude<SyncBatchOperation, null>>(['read', 'save'])
const partialDetailKeys = ['applied', 'manualActions', 'protectedSkipped'] as const satisfies readonly SyncDetailKey[]
const appliedOperationLabels: Record<string, string> = { replace_text: '替换文本', insert_table_row: '新增表格行' }
const appliedOperations = new Set(['replace_text', 'insert_table_row'])
const manualReasonLabels: Record<string, string> = {
  intent_target_block_not_found: '目标正文块未找到',
  protected_block: '内容受到保护',
  rich_text_elements_without_style_run_proof: '复杂格式需要人工复核',
  replace_terms_no_exact_match: '没有找到精确匹配',
  manual_review_required: '需要人工复核',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function nullableDateTime(value: unknown): string | null {
  const candidate = nullableString(value)
  if (!candidate || Number.isNaN(new Date(candidate).getTime())) return null
  return candidate
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
}

function positiveInteger(value: unknown): number | null {
  const candidate = nonNegativeInteger(value)
  return candidate !== null && candidate > 0 ? candidate : null
}

function nullableChecksum(value: unknown): string | null {
  return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value) ? value : null
}

export function safeTechnicalCode(value: unknown): string | null {
  const candidate = typeof value === 'string' ? value.trim() : isRecord(value) && typeof value.code === 'string' ? value.code.trim() : null
  if (!candidate || !/^[a-z0-9][a-z0-9_.:-]{0,95}$/i.test(candidate) || /^http_\d{3}$/i.test(candidate)) return null
  return candidate
}

export function isOrganizationMirrorDocumentResponse(value: unknown, artifactId: string): boolean {
  if (!isPublicId(artifactId) || !isRecord(value)) return false
  const data = isRecord(value.data) ? value.data : null
  const artifact = data && isRecord(data.artifact) ? data.artifact : null
  const revision = data && isRecord(data.revision) ? data.revision : null
  const body = revision && isRecord(revision.body) ? revision.body : null
  return Boolean(
    value.schemaVersion === MEDIA_BUSINESS_SCHEMA_VERSION &&
      nonNegativeInteger(value.revision) !== null &&
      artifact &&
      revision &&
      body &&
      body.schemaVersion === MEDIA_DOCUMENT_BODY_SCHEMA_VERSION &&
      artifact.publicArtifactId === artifactId &&
      artifact.workspaceMode === 'organization_lark' &&
      artifact.bodyAuthority === 'lark' &&
      revision.publicArtifactId === artifactId &&
      revision.bodyAuthority === 'lark' &&
      positiveInteger(revision.revision) !== null &&
      nullableChecksum(revision.bodyChecksum) !== null &&
      Array.isArray(body.blocks),
  )
}

function projectBatch(value: unknown, artifactId: string): MirrorSyncBatch | null {
  if (!isRecord(value)) return null
  const publicSyncId = nullableString(value.publicSyncId)
  const publicArtifactId = nullableString(value.publicArtifactId)
  if (!publicSyncId || !isPublicId(publicSyncId) || publicArtifactId !== artifactId) return null
  const rawOperation = nullableString(value.operation)
  const rawState = nullableString(value.state)
  const errorDetail = value.errorDetail === undefined || value.errorDetail === null ? null : isRecord(value.errorDetail) ? value.errorDetail : null
  return {
    publicSyncId,
    publicArtifactId,
    revision: positiveInteger(value.revision),
    operation: rawOperation && syncBatchOperations.has(rawOperation as Exclude<SyncBatchOperation, null>) ? rawOperation as Exclude<SyncBatchOperation, null> : null,
    state: rawState && syncBatchStates.has(rawState as Exclude<SyncBatchState, null>) ? rawState as Exclude<SyncBatchState, null> : null,
    remoteDocumentVersion: nullableString(value.remoteDocumentVersion),
    bodyChecksum: nullableChecksum(value.bodyChecksum),
    blockCount: nonNegativeInteger(value.blockCount),
    protectedBlockCount: nonNegativeInteger(value.protectedBlockCount),
    createdAt: nullableDateTime(value.createdAt),
    updatedAt: nullableDateTime(value.updatedAt),
    completedAt: nullableDateTime(value.completedAt),
    errorCode: safeTechnicalCode(value.errorCode),
    errorDetail,
  }
}

export function projectSyncBatchList(value: unknown, artifactId: string): SyncBatchListProjection {
  if (
    !isPublicId(artifactId) ||
    !isRecord(value) ||
    value.schemaVersion !== MEDIA_BUSINESS_SCHEMA_VERSION ||
    nonNegativeInteger(value.revision) === null ||
    !Array.isArray(value.items) ||
    (value.nextCursor !== null && !nullableString(value.nextCursor))
  ) return { status: 'unavailable', items: [], nextCursor: null }
  const projected = value.items.map((item) => projectBatch(item, artifactId))
  if (projected.some((item): item is null => item === null)) return { status: 'unavailable', items: [], nextCursor: null }
  const ids = new Set<string>()
  for (const item of projected) {
    if (!item || ids.has(item.publicSyncId)) return { status: 'unavailable', items: [], nextCursor: null }
    ids.add(item.publicSyncId)
  }
  const nextCursor = value.nextCursor === null ? null : nullableString(value.nextCursor)
  return { status: 'available', items: projected as MirrorSyncBatch[], nextCursor }
}

export function readDetailPart(detail: Record<string, unknown> | null, key: SyncDetailKey): DetailPart {
  if (!detail || !Object.prototype.hasOwnProperty.call(detail, key) || !Array.isArray(detail[key])) return { available: false, values: [] }
  return { available: true, values: detail[key] as unknown[] }
}

export function readBlockIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const candidate = typeof item === 'string' ? item : isRecord(item) && typeof item.blockId === 'string' ? item.blockId : isRecord(item) && typeof item.block_id === 'string' ? item.block_id : null
    return candidate && isPublicId(candidate.trim()) ? [candidate.trim()] : []
  })
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key))
}

function hasOptionalPublicId(value: Record<string, unknown>, key: string): boolean {
  const candidate = value[key]
  return candidate === undefined || (typeof candidate === 'string' && isPublicId(candidate))
}

function isAppliedReceiptItem(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ['operation', 'blockId']) && appliedOperations.has(value.operation as string) && hasOptionalPublicId(value, 'blockId')
}

function isManualReceiptItem(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ['reason', 'blockId']) && typeof value.reason === 'string' && /^[A-Za-z0-9_.:-]{1,96}$/.test(value.reason) && hasOptionalPublicId(value, 'blockId')
}

export function projectExecutionReceipt(value: unknown): ExecutionReceiptProjection | null {
  const appliedCount = isRecord(value) ? nonNegativeInteger(value.appliedCount) : null
  if (
    !isRecord(value) ||
    (value.status !== 'ready' && value.status !== 'failed') ||
    !Array.isArray(value.applied) ||
    appliedCount === null ||
    !Array.isArray(value.manualActions) ||
    !Array.isArray(value.protectedSkipped) ||
    !hasOnlyKeys(value, ['status', 'applied', 'appliedCount', 'manualActions', 'protectedSkipped', 'errorCode']) ||
    !value.applied.every(isAppliedReceiptItem) ||
    !value.manualActions.every(isManualReceiptItem) ||
    !value.protectedSkipped.every((item) => typeof item === 'string' && isPublicId(item))
  ) return null
  return {
    status: value.status,
    applied: value.applied,
    appliedCount,
    manualActions: value.manualActions,
    protectedSkipped: value.protectedSkipped,
    errorCode: safeTechnicalCode(value.errorCode),
  }
}

function publicBlockId(value: unknown): string | null {
  if (typeof value === 'string' && isPublicId(value.trim())) return value.trim()
  if (!isRecord(value)) return null
  const candidate = typeof value.blockId === 'string' ? value.blockId : typeof value.block_id === 'string' ? value.block_id : null
  return candidate && isPublicId(candidate.trim()) ? candidate.trim() : null
}

export function syncDetailItemLabel(value: unknown, index: number, key: SyncDetailKey): string {
  const blockId = publicBlockId(value)
  if (key === 'blockIds') return blockId ? `相关正文块 ${index + 1}` : `正文块信息不可用 ${index + 1}`
  if (key === 'protectedSkipped') return blockId ? `相关正文块 ${index + 1}` : `受保护内容 ${index + 1}`
  if (key === 'manualActions') {
    const reason = isRecord(value) && typeof value.reason === 'string' ? manualReasonLabels[value.reason] : null
    const parts = [reason, blockId ? `相关正文块 ${index + 1}` : null].filter((part): part is string => Boolean(part))
    return parts.length ? parts.join(' · ') : `人工处理项目 ${index + 1}`
  }
  const operation = isRecord(value) && typeof value.operation === 'string' ? appliedOperationLabels[value.operation] : null
  if (operation && blockId) return `${operation} · 相关正文块 ${index + 1}`
  if (operation) return operation
  if (blockId) return `相关正文块 ${index + 1}`
  return `已应用项目 ${index + 1}`
}

export function isUnknownBatch(batch: MirrorSyncBatch): boolean {
  return batch.errorCode === 'lark_save_outcome_unknown'
}

export function isUnsupportedBatch(batch: MirrorSyncBatch): boolean {
  return batch.state === 'failed' && (batch.errorCode === 'lark_table_shape_unsupported' || batch.errorCode === 'unsupported_document_block')
}

function hasMalformedPartialDetails(detail: Record<string, unknown> | null): boolean {
  return partialDetailKeys.some((key) => Boolean(detail && Object.prototype.hasOwnProperty.call(detail, key) && !Array.isArray(detail[key])))
}

function hasPartialDetails(detail: Record<string, unknown> | null): boolean {
  return partialDetailKeys.some((key) => readDetailPart(detail, key).values.length > 0)
}

export function syncStateFor(batches: readonly MirrorSyncBatch[], mirrorVersion: unknown, loadState: SyncLoadState): SyncState {
  if (loadState === 'loading' || loadState === 'idle') return 'loading'
  if (loadState === 'error') return 'unavailable'
  const latest = batches[0]
  if (!latest || !latest.errorDetail || !latest.operation || !latest.state) return 'unavailable'
  if (isUnknownBatch(latest)) return 'unknown'
  if (latest.state === 'queued' || latest.state === 'running') return 'running'
  if (latest.state === 'conflict') return 'conflict'
  if (isUnsupportedBatch(latest)) return 'unsupported'
  if (latest.state !== 'succeeded') return 'unavailable'
  if (hasMalformedPartialDetails(latest.errorDetail)) return 'unavailable'
  if (hasPartialDetails(latest.errorDetail)) return 'partial'
  const knownMirrorVersion = nullableString(mirrorVersion)
  if (!latest.remoteDocumentVersion || !knownMirrorVersion) return 'unavailable'
  if (latest.remoteDocumentVersion !== knownMirrorVersion) return 'stale'
  return 'synced'
}

export function syncActionFor(state: SyncState): 'reread' | 'reconcile' | 'refresh' {
  if (state === 'unknown') return 'reconcile'
  if (state === 'running') return 'refresh'
  return 'reread'
}

export function syncActionLabel(state: SyncState): string {
  if (state === 'unknown') return '重新核对状态'
  if (state === 'running') return '检查处理进度'
  if (state === 'synced') return '重新读取'
  if (state === 'conflict') return '重新读取镜像'
  if (state === 'unsupported') return '处理后重新读取'
  if (state === 'stale') return '重新读取镜像'
  if (state === 'partial') return '重新读取结果'
  return '重新读取'
}

export function syncMessage(state: SyncState, batch: MirrorSyncBatch | null): string {
  if (state === 'running') return '飞书写入仍在进行。网页会在服务端完成回读后更新镜像版本。'
  if (state === 'unknown') return '飞书可能已经保存，但服务端尚未完成确认。请重新核对状态，避免重复写入。'
  if (state === 'conflict') return '飞书中的版本与本次同步基线不一致。请先在飞书确认内容，再重新读取镜像。'
  if (state === 'unsupported') return '检测到当前结构无法安全写入飞书。其余已确认的正文不会被自动改写。'
  if (state === 'stale') return '飞书中出现了更高版本，网页镜像正在等待下一次回读。'
  if (state === 'partial') return '部分内容已经应用；需要人工处理和受保护内容会保留原状。'
  if (state === 'unavailable') return batch ? '本次同步没有返回可确认的状态或必要信息。' : '服务端尚未返回可确认的同步记录。'
  return '网页镜像与最近一次服务端回读记录一致。'
}

export function syncBatchOperationLabel(operation: SyncBatchOperation): string {
  if (operation === 'read') return '回读镜像'
  if (operation === 'save') return '写入飞书'
  return '同步类型不可用'
}

export function syncBatchStateLabel(batch: MirrorSyncBatch): string {
  if (isUnknownBatch(batch)) return '写入结果待对账'
  if (batch.state === 'running' || batch.state === 'queued') return '正在处理'
  if (batch.state === 'succeeded') return '已完成'
  if (batch.state === 'conflict') return '需要处理冲突'
  if (isUnsupportedBatch(batch)) return '结构暂不支持'
  return '状态不可用'
}

export function syncPipelineFor(state: SyncState, batch: MirrorSyncBatch | null): SyncPipelineStep[] {
  const hasRevision = typeof batch?.revision === 'number' && batch.revision > 0
  const initial: SyncPipelineStep = { title: '生成正文', detail: hasRevision ? `修订 v${batch?.revision} 已产生` : '修订版本不可用', state: hasRevision ? 'complete' : 'pending' }
  if (state === 'synced') return [initial, { title: '写入飞书', detail: '最近一次批次已完成', state: 'complete' }, { title: '登记绑定', detail: '组织绑定已确认', state: 'complete' }, { title: '写后回读', detail: '镜像版本与回读记录一致', state: 'complete' }]
  if (state === 'running') return [initial, { title: '写入飞书', detail: '服务端正在处理写入批次', state: 'running' }, { title: '登记绑定', detail: '等待写入回执', state: 'pending' }, { title: '写后回读', detail: '等待远端版本读回', state: 'pending' }]
  if (state === 'unknown') return [initial, { title: '写入飞书', detail: '尚未取得可确认的写入结果', state: 'attention' }, { title: '登记绑定', detail: '等待对账结论', state: 'pending' }, { title: '写后回读', detail: '结果确认前不自动重发', state: 'pending' }]
  if (state === 'conflict') return [initial, { title: '写入飞书', detail: '远端版本与同步基线不一致', state: 'attention' }, { title: '登记绑定', detail: '等待在飞书确认正文', state: 'pending' }, { title: '写后回读', detail: '确认后重新读取', state: 'pending' }]
  if (state === 'unsupported') return [initial, { title: '写入飞书', detail: '检测到不能安全写入的正文结构', state: 'attention' }, { title: '登记绑定', detail: '未确认的内容不会自动登记', state: 'pending' }, { title: '写后回读', detail: '等待人工处理后回读', state: 'pending' }]
  if (state === 'stale') return [initial, { title: '写入飞书', detail: '最近一次批次已返回', state: 'complete' }, { title: '登记绑定', detail: '当前绑定仍被保留', state: 'complete' }, { title: '写后回读', detail: '发现更高远端版本，等待重新读取', state: 'attention' }]
  if (state === 'partial') return [initial, { title: '写入飞书', detail: '服务端返回部分应用结果', state: 'attention' }, { title: '登记绑定', detail: '仅已确认内容继续保留', state: 'complete' }, { title: '写后回读', detail: '受保护内容保持原状', state: 'attention' }]
  return [initial, { title: '写入飞书', detail: '尚无可确认的同步记录', state: 'pending' }, { title: '登记绑定', detail: '尚无可确认的同步记录', state: 'pending' }, { title: '写后回读', detail: '尚无可确认的同步记录', state: 'pending' }]
}
