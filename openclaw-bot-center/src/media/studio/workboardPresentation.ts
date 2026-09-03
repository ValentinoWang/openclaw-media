import { artifactTypeDisplayLabel, projectStageDisplayLabel } from '../ui/displayLabels'

export type WorkboardStageProgress = {
  readonly label: string
  readonly progress: number | null
}

export type WorkboardTask = {
  readonly status: string
  readonly terminal: boolean
}

// The research/assets/decision/creation(_ready)/publishing/review project stages (cluster LE-11)
// used to carry their own copy of the Chinese label here, byte-identical to
// ui/displayLabels.ts's PROJECT_STAGE_LABELS. Only the progress percentage is genuinely local to
// this workboard view now; the label is derived from the shared table below. The Content OS
// stages (captured..published) are a *different* enum (see LE-09/LE-10) and keep their own
// label+progress pairs unchanged.
const projectStageProgress: Readonly<Record<string, number>> = {
  research: 12,
  assets: 28,
  decision: 46,
  creation: 66,
  creation_ready: 66,
  publishing: 86,
  review: 100,
}

const contentOsStageProgress: Readonly<Record<string, WorkboardStageProgress>> = {
  captured: { label: '已登记', progress: 12 },
  planned: { label: '已规划', progress: 28 },
  edit_ready: { label: '可开始剪辑', progress: 46 },
  editing: { label: '剪辑中', progress: 66 },
  final_ready: { label: '待发布', progress: 86 },
  published: { label: '已发布', progress: 100 },
}

const unknownStageProgress: WorkboardStageProgress = {
  label: '项目阶段待确认',
  progress: null,
}

export function workboardStageProgress(stage: string): WorkboardStageProgress {
  if (stage in projectStageProgress) {
    return { label: projectStageDisplayLabel(stage), progress: projectStageProgress[stage] }
  }
  return contentOsStageProgress[stage] ?? unknownStageProgress
}

export function filterWorkboardAttentionTasks<T extends WorkboardTask>(
  tasks: readonly T[],
): T[] {
  return tasks.filter((task) =>
    task.status === 'awaiting_confirmation' || (
      task.terminal && ['pending_manual', 'failed'].includes(task.status)
    ),
  )
}

// ---- 自媒体全流程（/today 流程图）----
// 每个节点都绑定真实数据源，而不是装饰性文案：
//   stage       = 合同 DashboardSummary.contentProjectStages[].stage 与 ContentProjectSummary.stage 的枚举值
//   artifactType= 该阶段产出的合同 ArtifactType（ordinaryDataLabels.ARTIFACT_TYPE_LABELS）
//   path        = 承接该阶段工作的生产路由（MediaStudioApp 路由表）
//   pending     = 该阶段在 DashboardSummary 里对应的待处理计数字段
// 顺序即后端 overview.STAGES 的顺序，复盘阶段回流到研究，形成闭环。
export type WorkboardFlowPendingField = 'pendingDecisions' | 'pendingPublishing' | 'pendingReviews'

export type WorkboardFlowStage = {
  readonly stage: string
  readonly label: string
  readonly path: string
  readonly pathLabel: string
  readonly artifactType: string
  readonly artifactLabel: string
  readonly action: string
  readonly outcome: string
  readonly pending: WorkboardFlowPendingField | null
  readonly pendingLabel: string | null
}

export const WORKBOARD_FLOW_STAGE_ORDER = ['research', 'assets', 'decision', 'creation', 'publishing', 'review'] as const

const flowStageDetails: Readonly<Record<(typeof WORKBOARD_FLOW_STAGE_ORDER)[number], Omit<WorkboardFlowStage, 'stage' | 'label' | 'artifactLabel'>>> = {
  research: {
    path: '/desk', pathLabel: 'Desk',
    artifactType: 'research_snapshot',
    action: '监控热榜、对标账号与活动信号，找出值得做的方向。',
    outcome: '沉淀研究摘要，作为选题的来源证据。',
    pending: null, pendingLabel: null,
  },
  assets: {
    path: '/assets', pathLabel: '素材库',
    artifactType: 'asset_digest',
    action: '登记原始素材、拆解参考作品，补齐拍摄所需的证据。',
    outcome: '生成素材摘要，供创作阶段直接引用。',
    pending: null, pendingLabel: null,
  },
  decision: {
    path: '/decisions', pathLabel: '选题与决策',
    artifactType: 'decision_brief',
    action: '从候选选题和来源信号中人工确认要做哪一条。',
    outcome: '形成决策简报，锁定平台、角度与交付要求。',
    pending: 'pendingDecisions', pendingLabel: '待决策',
  },
  creation: {
    path: '/studio', pathLabel: 'Studio',
    artifactType: 'creation_document',
    action: '维护可编辑的脚本、分镜、拍摄单与剪辑返修版本。',
    outcome: '产出创作文档，人工修改优先、AI 只提交局部变更。',
    pending: null, pendingLabel: null,
  },
  publishing: {
    path: '/publishing', pathLabel: '发布交付',
    artifactType: 'publishing_package',
    action: '组装标题、封面、正文与渠道设置，确认发布时间。',
    outcome: '形成发布包，等待人工确认后交付渠道。',
    pending: 'pendingPublishing', pendingLabel: '待发布',
  },
  review: {
    path: '/reviews', pathLabel: '复盘洞察',
    artifactType: 'review_report',
    action: '读取发布数据与账号表现，总结这一条的得失。',
    outcome: '形成复盘报告，回流到下一轮研究与选题。',
    pending: 'pendingReviews', pendingLabel: '待复盘',
  },
}

export const WORKBOARD_FLOW_STAGES: readonly WorkboardFlowStage[] = WORKBOARD_FLOW_STAGE_ORDER.map((stage) => ({
  stage,
  label: projectStageDisplayLabel(stage),
  artifactLabel: artifactTypeDisplayLabel(flowStageDetails[stage].artifactType),
  ...flowStageDetails[stage],
}))

/** 项目阶段在全流程中的位置（0 起），未知阶段返回 null。creation_ready 与 creation 同位。 */
export function workboardStageIndex(stage: string): number | null {
  const normalized = stage === 'creation_ready' ? 'creation' : stage
  const index = WORKBOARD_FLOW_STAGE_ORDER.indexOf(normalized as (typeof WORKBOARD_FLOW_STAGE_ORDER)[number])
  return index === -1 ? null : index
}
