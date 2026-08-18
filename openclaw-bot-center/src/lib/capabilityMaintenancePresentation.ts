import type { Capability, DashboardData } from '../schemas/dashboardSchema'
import { botChineseNames, categoryNames, typeNames } from './labels'

export type CapabilityMaintenancePresentationRow =
  | { kind: 'text'; label: string; value: string }
  | { kind: 'status'; label: string; status: Capability['implementationStatus'] }

export type CapabilityMaintenancePresentation = {
  rows: CapabilityMaintenancePresentationRow[]
}

export type DeletionBoundaryPresentation = {
  scope: string[]
  safeguards: string[]
}

export function buildCapabilityMaintenancePresentation(
  capability: Capability,
  meta: DashboardData['meta'],
): CapabilityMaintenancePresentation {
  return {
    rows: [
      { kind: 'text', label: '触发标签', value: capability.rawLabel },
      { kind: 'status', label: '实装状态', status: capability.implementationStatus },
      { kind: 'text', label: '主归属', value: botChineseNames[capability.primaryBot] },
      { kind: 'text', label: '分类', value: `${typeNames[capability.type]} · ${categoryNames[capability.category]}` },
      { kind: 'text', label: '生成时间', value: formatGeneratedAt(meta.generatedAt) },
    ],
  }
}

export function executionNodeTypeLabel(type: Capability['executionGraph']['nodes'][number]['nodeType']) {
  const labels: Record<Capability['executionGraph']['nodes'][number]['nodeType'], string> = {
    entry: '入口',
    input_parse: '输入解析',
    data_fetch: '证据与数据',
    vision_read: '视觉读取',
    actual_llm_prompt: '大语言模型处理',
    document_render: '文档渲染',
    bitable_write: '多维表格写入',
    storage_write: '存储写入',
    quality_check: '完成校验',
    reply: '回复用户',
    supporting_contract: '辅助边界',
    generated_execution_contract: '执行边界',
  }
  return labels[type]
}

export function buildDeletionBoundaryPresentation(
  contract: Capability['deletionContract'],
): DeletionBoundaryPresentation {
  const scopeByCoverage: Record<Capability['deletionContract']['coverage'], string[]> = {
    automatic: ['该能力登记的对象可以在确认后自动处理。'],
    partial: ['仅处理归属明确且已登记的对象；其他对象需要人工确认。'],
    manual_required: ['该能力产生的对象目前需要人工确认和处理。'],
  }
  return {
    scope: scopeByCoverage[contract.coverage],
    safeguards: [
      contract.previewRequired ? '执行前必须先展示预览。' : '该边界允许直接进入处理。',
      contract.confirmationRequired ? '收到明确确认后才执行。' : '无需二次确认。',
    ],
  }
}

export function executionStateLabel(state: string) {
  const labels: Record<string, string> = {
    validated: '校验通过',
    pending_manual: '等待人工确认',
    manual_required: '需要人工处理',
    patch_apply_failed: '修改应用失败',
    patch_apply_manual: '转人工应用修改',
    'failed/blocked': '处理失败或受阻',
    unclear: '状态不明确',
  }
  if (labels[state]) return labels[state]
  if (/[㐀-鿿]/.test(state)) return state
  if (/manual|pending|review/i.test(state)) return '等待人工确认'
  if (/fail|block|error/i.test(state)) return '处理失败或受阻'
  return '流程已终止'
}

export function validationProfileLabel(
  profile: NonNullable<Capability['llmPromptContracts'][number]['postValidation']>['profile'],
) {
  return profile === 'strict_structured' ? '严格结构校验' : '开放输出边界校验'
}

export function executionEdgeLabelWidth(label: string, maximum = 172) {
  return Math.min(maximum, Math.max(56, Array.from(label).length * 12 + 24))
}

export function executionEdgeLabelText(label: string, maximumWidth: number) {
  const maximumCharacters = Math.max(2, Math.floor((maximumWidth - 30) / 12))
  const characters = Array.from(label)
  return characters.length <= maximumCharacters ? label : `${characters.slice(0, maximumCharacters).join('')}…`
}

function formatGeneratedAt(value: string) {
  const generatedAt = new Date(value)
  if (Number.isNaN(generatedAt.getTime())) return '生成时间不可用'
  return generatedAt.toLocaleString('zh-CN', { hour12: false })
}
