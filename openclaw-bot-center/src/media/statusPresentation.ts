const runStatusLabels: Record<string, string> = {
  queued: '排队中',
  validating: '校验中',
  retrieving: '读取来源',
  generating: '生成中',
  persisting: '写入中',
  rendering: '渲染中',
  success: '成功',
  succeeded: '已完成',
  completed: '已完成',
  done: '已完成',
  pending: '进行中',
  pending_manual: '待人工处理',
  failed: '失败',
  error: '失败',
  blocked: '已阻断',
  cancelled: '已取消',
  unknown: '状态待读取',
}

const writeStateLabels: Record<string, string> = {
  written: '已写入',
  not_attempted: '未执行写入',
  pending: '写入中',
  failed: '写入失败',
  unavailable: '写入状态不可用',
}

const readbackStateLabels: Record<string, string> = {
  matched: '已核对',
  not_attempted: '未核对',
  pending: '待核对',
  mismatched: '内容不一致',
  failed: '核对失败',
  unavailable: '暂时无法核对',
}

const artifactStateLabels: Record<string, string> = {
  available: '已生成',
  unavailable: '不可用',
  missing: '未生成',
  partial: '部分生成',
}

const generationSourceLabels: Record<string, string> = {
  llm: '模型生成',
  manual: '人工整理',
  hybrid: '模型与人工协作',
}

function normalized(value: string) {
  return value.trim().toLowerCase()
}

export function runStatusLabel(status: string) {
  return runStatusLabels[normalized(status)] ?? '状态待确认'
}

export function runStatusTone(status: string): 'success' | 'warning' | 'info' | 'neutral' | 'danger' {
  const value = normalized(status)
  if (['success', 'succeeded', 'completed', 'done'].includes(value)) return 'success'
  if (['failed', 'error'].includes(value)) return 'danger'
  if (['blocked', 'cancelled', 'pending_manual'].includes(value)) return 'warning'
  return value ? 'info' : 'neutral'
}

export function writeStateLabel(status: string) {
  return writeStateLabels[normalized(status)] ?? '写入状态待读取'
}

export function readbackStateLabel(status: string) {
  return readbackStateLabels[normalized(status)] ?? '核对状态待确认'
}

export function artifactStateLabel(status: string) {
  return artifactStateLabels[normalized(status)] ?? '产物状态待读取'
}

export function generationSourceLabel(source: string) {
  return generationSourceLabels[normalized(source)] ?? '生成方式待确认'
}

// -- Domain-specific tone mappings -----------------------------------------
// These were each defined locally inside their own page. They are relocated
// here so statusPresentation.ts stays the single place status/tone mapping
// logic lives, per the checkMediaOrdinaryPresentation.ts gate. Each mapping
// keeps its own bucket boundaries and return type deliberately - they are
// NOT folded into runStatusTone or into each other, because the underlying
// state machines are genuinely different (run status vs. sync status vs.
// decision status vs. publishing lifecycle vs. review quality vs. usage
// event outcome). Pages that render these tones keep their own CSS-module
// class lookup (tone -> styles.xxx), since CSS Modules are page-scoped.

// Moved from OverviewPage.tsx (was: artifactTone).
export function artifactSyncTone(
  status: 'not_applicable' | 'pending' | 'synced' | 'conflict' | 'failed',
): 'success' | 'warning' | 'info' | 'neutral' {
  if (status === 'synced' || status === 'not_applicable') return 'success'
  if (status === 'conflict' || status === 'failed') return 'warning'
  if (status === 'pending') return 'info'
  return 'neutral'
}

// Moved from OverviewPage.tsx (was: taskTone).
export function overviewTaskTone(status: string): 'success' | 'warning' | 'info' | 'neutral' {
  if (status === 'succeeded') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'warning'
  if (status === 'awaiting_confirmation' || status === 'pending_manual') return 'warning'
  return status ? 'info' : 'neutral'
}

// Moved from BusinessPage.tsx (was: statusTone).
export function businessStatusTone(status: string): 'success' | 'warning' | 'neutral' {
  if (['active', 'approved', 'confirmed', 'open', 'in_progress'].includes(status)) return 'success'
  if (['pending', 'draft', 'needs_review', 'awaiting_confirmation'].includes(status)) return 'warning'
  return 'neutral'
}

// Moved from TracksPage.tsx (was: operationalStatusTone).
export function ownedAccountOperationalTone(value: string | null): 'success' | 'warning' | 'neutral' {
  const status = normalized(value ?? '')
  if (status === 'active') return 'success'
  if (status === 'paused') return 'warning'
  return 'neutral'
}

// Moved from DecisionsPage.tsx (was: statusToneClass, which returned a CSS
// module class directly; the class lookup stays in DecisionsPage.tsx since
// it depends on that page's own CSS module).
export function decisionStatusTone(status: string): 'success' | 'warning' | 'info' | 'neutral' {
  if (status === 'confirmed') return 'success'
  if (status === 'rejected') return 'warning'
  if (status === 'recommended') return 'info'
  return 'neutral'
}

// Moved from PublishingPage.tsx (was: statusToneClass). Publishing status is
// a workflow stage, not a success/failure tone, so it keeps its own stage
// vocabulary instead of being forced into success/warning/info/neutral.
export function publishingStatusStage(status: string): 'ready' | 'published' | 'checking' | 'draft' {
  if (status === 'ready') return 'ready'
  if (status === 'published') return 'published'
  if (status === 'checking') return 'checking'
  return 'draft'
}

// Moved from ReviewsPage.tsx (was: qualityClass).
export function reviewQualityTone(value: string): 'verified' | 'partial' | 'unverified' | 'unavailable' {
  if (value === 'verified') return 'verified'
  if (value === 'partial') return 'partial'
  if (value === 'unverified') return 'unverified'
  return 'unavailable'
}

// Moved from UsageBillingPage.tsx (was: inline tone lookup inside its local
// StatusBadge component).
export function usageEventTone(value: string): 'success' | 'danger' | 'neutral' {
  const normalizedValue = normalized(value)
  if (['succeeded', 'success', 'completed'].includes(normalizedValue)) return 'success'
  if (['failed', 'error', 'cancelled'].includes(normalizedValue)) return 'danger'
  return 'neutral'
}
