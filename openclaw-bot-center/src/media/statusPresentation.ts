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

export function runStatusTone(status: string): 'success' | 'warning' | 'info' | 'neutral' {
  const value = normalized(status)
  if (['success', 'succeeded', 'completed', 'done'].includes(value)) return 'success'
  if (['failed', 'error', 'blocked'].includes(value)) return 'warning'
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
