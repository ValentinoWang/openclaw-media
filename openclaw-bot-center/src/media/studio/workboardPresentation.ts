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
// 真实的自媒体经营不是一条直线：内容线（账号定位 → 研究 → 选题）和商务线（档案报价 → 商机 →
// 商单 Brief）在「创作」合流，之后自制内容直接发布，商单先经品牌审核/返修再交付；复盘把经验
// 回流到研究，把结案数据回流到商机（复购）。素材库随时汇入创作。
// 每个节点都绑定真实数据源，而不是装饰性文案：
//   stage        = 合同 DashboardSummary.contentProjectStages[].stage / ContentProjectSummary.stage
//   artifactType = 该节点产出的合同 ArtifactType（ordinaryDataLabels.ARTIFACT_TYPE_LABELS）
//   path         = 承接该节点工作的生产路由（MediaStudioApp 路由表）
//   capabilities = 能力注册表里的真实 capabilityId（openclaw-tag-router）
//   facts        = 节点上展示的数字来自哪个合同字段 / 哪批业务记录
export type WorkboardFlowPendingField = 'pendingDecisions' | 'pendingPublishing' | 'pendingReviews'
export type WorkboardFlowCountKey = 'contentProjects' | 'runs' | 'assets' | 'tracks' | 'creators' | 'publishedPosts' | 'reviews'
export type WorkboardFlowLane = 'content' | 'shared' | 'local' | 'commercial'
export type WorkboardFlowAccent = 'studio' | 'campaign' | 'business' | 'desk' | 'agent' | 'archive'

export type WorkboardFlowFact =
  | { readonly source: 'stage'; readonly stage: string; readonly label: string }
  | { readonly source: 'counts'; readonly key: WorkboardFlowCountKey; readonly label: string }
  | { readonly source: 'pending'; readonly key: WorkboardFlowPendingField; readonly label: string }
  | { readonly source: 'opportunities'; readonly label: string }
  | { readonly source: 'tasks'; readonly capabilityId: string; readonly attention: boolean; readonly label: string }
  | { readonly source: 'devices'; readonly label: string }
  | { readonly source: 'localJobs'; readonly label: string }

export type WorkboardFlowNode = {
  readonly id: string
  readonly lane: WorkboardFlowLane
  readonly column: 1 | 2 | 3 | 4 | 5 | 6
  readonly accent: WorkboardFlowAccent
  readonly label: string
  readonly path: string
  readonly pathLabel: string
  readonly stage: string | null
  readonly artifactType: string | null
  readonly artifactLabel: string | null
  readonly capabilities: readonly { readonly id: string; readonly label: string }[]
  /** 本机流程 id（W1 流程目录）。只有本地剪辑线的节点有。 */
  readonly pipelines?: readonly string[]
  readonly action: string
  readonly outcome: string
  readonly facts: readonly WorkboardFlowFact[]
  /** 没有可统计数字的节点在图上显示的短提示（不编造数字）。 */
  readonly hint?: string
}

export type WorkboardFlowEdge = {
  readonly from: string
  readonly to: string
  readonly kind: 'forward' | 'return' | 'loop'
  readonly label?: string
}

export const WORKBOARD_FLOW_STAGE_ORDER = ['research', 'assets', 'decision', 'creation', 'publishing', 'review'] as const

export const WORKBOARD_FLOW_COLUMNS = ['定位', '研究 · 商机', '决策 · Brief', '创作合流', '审核 · 发布', '复盘 · 复购'] as const

export const WORKBOARD_FLOW_LANES: readonly { readonly id: WorkboardFlowLane; readonly label: string; readonly detail: string }[] = [
  { id: 'content', label: '内容线', detail: '账号成长：定位 → 研究 → 选题' },
  { id: 'shared', label: '合流', detail: '素材汇入创作，再到发布与复盘' },
  { id: 'local', label: '本机剪辑线', detail: 'Mac 本地：取证 → 交接包 → 人工精剪' },
  { id: 'commercial', label: '商务线', detail: '变现履约：报价 → 商机 → Brief → 审核' },
]

const flowNodeDefinitions: readonly Omit<WorkboardFlowNode, 'artifactLabel'>[] = [
  {
    id: 'accounts', lane: 'content', column: 1, accent: 'desk',
    label: '账号与赛道', path: '/tracks', pathLabel: '账号与赛道',
    stage: null, artifactType: null,
    capabilities: [
      { id: 'owned_media_account_lookup', label: '账号' },
      { id: 'track_registry_lookup', label: '赛道' },
      { id: 'account_track_strategy', label: '策略' },
      { id: 'creator_profile_lookup', label: '博主' },
    ],
    action: '维护自有账号的内容定位，登记赛道与对标博主，明确这一轮要打的方向。',
    outcome: '账号策略与赛道关系，作为研究和选题的边界。',
    facts: [
      { source: 'counts', key: 'tracks', label: '赛道' },
      { source: 'counts', key: 'creators', label: '对标博主' },
    ],
  },
  {
    id: 'research', lane: 'content', column: 2, accent: 'desk',
    label: '情报研究', path: '/desk', pathLabel: 'Desk',
    stage: 'research', artifactType: 'research_snapshot',
    capabilities: [
      { id: 'platform_hotlist', label: '热榜' },
      { id: 'viral_deconstruction', label: '拆解' },
      { id: 'external_research_brief', label: '调研' },
      { id: 'activity_archive', label: '活动' },
    ],
    action: '看热榜、拆解爆款、整理平台活动与外部调研，找出值得做的方向。',
    outcome: '研究摘要：来源可回查的证据，供选题判断。',
    facts: [{ source: 'stage', stage: 'research', label: '研究中项目' }],
  },
  {
    id: 'decision', lane: 'content', column: 3, accent: 'desk',
    label: '选题决策', path: '/decisions', pathLabel: '选题与决策',
    stage: 'decision', artifactType: 'decision_brief',
    capabilities: [
      { id: 'creation_decision_brief', label: '选题' },
      { id: 'inspiration_archive', label: '灵感' },
    ],
    action: '把证据和灵感整理成候选选题，人工确认要做哪一条、在哪个平台、用什么角度。',
    outcome: '决策简报，锁定选题与交付要求。',
    facts: [
      { source: 'stage', stage: 'decision', label: '决策中项目' },
      { source: 'pending', key: 'pendingDecisions', label: '待决策' },
    ],
  },
  {
    id: 'assets', lane: 'shared', column: 2, accent: 'archive',
    label: '素材库', path: '/assets', pathLabel: '素材库',
    stage: 'assets', artifactType: 'asset_digest',
    capabilities: [
      { id: 'source_asset_intake', label: '素材' },
      { id: 'recent_records_summary', label: '整理' },
    ],
    action: '收集原始素材、链接与现场记录，任何时候都可以汇入创作。',
    outcome: '素材摘要，供脚本、分镜与剪辑直接引用。',
    facts: [
      { source: 'counts', key: 'assets', label: '素材' },
      { source: 'stage', stage: 'assets', label: '整理中项目' },
    ],
  },
  {
    id: 'creation', lane: 'shared', column: 4, accent: 'studio',
    label: '创作 Studio', path: '/studio', pathLabel: 'Studio',
    stage: 'creation', artifactType: 'creation_document',
    capabilities: [
      { id: 'selfmedia_creation', label: '创作' },
      { id: 'shooting_execution_plan', label: '拍摄' },
      { id: 'style_polish_run', label: '润色' },
      { id: 'creation_checklist_lookup', label: '检查' },
    ],
    action: '内容线的选题和商务线的商单 Brief 在这里合流：脚本、分镜、拍摄单与剪辑返修版本都是可编辑活稿。',
    outcome: '创作文档：人工修改优先，AI 只提交局部变更。',
    facts: [
      { source: 'stage', stage: 'creation', label: '创作中项目' },
      { source: 'counts', key: 'runs', label: '创作运行' },
    ],
  },
  {
    id: 'publishing', lane: 'shared', column: 5, accent: 'studio',
    label: '发布交付', path: '/publishing', pathLabel: '发布交付',
    stage: 'publishing', artifactType: 'publishing_package',
    capabilities: [{ id: 'publishing_pack_build', label: '发布包' }],
    action: '组装标题、封面、正文与渠道设置。自制内容直接排期发布；商单在品牌验收后交付并发布。',
    outcome: '发布包与已发布作品记录。',
    facts: [
      { source: 'stage', stage: 'publishing', label: '发布准备中' },
      { source: 'pending', key: 'pendingPublishing', label: '待发布' },
      { source: 'counts', key: 'publishedPosts', label: '已发布' },
    ],
  },
  {
    id: 'review', lane: 'shared', column: 6, accent: 'desk',
    label: '复盘洞察', path: '/reviews', pathLabel: '复盘洞察',
    stage: 'review', artifactType: 'review_report',
    capabilities: [
      { id: 'selfmedia_data_review', label: '数据复盘' },
      { id: 'post_review_signal', label: '复盘' },
      { id: 'media_growth_review', label: '复核' },
    ],
    action: '读取作品数据与账号指标，总结这一条的得失；商单同时形成结案数据。',
    outcome: '复盘报告：经验回流到账号策略与研究，结案数据带来复购。',
    facts: [
      { source: 'stage', stage: 'review', label: '复盘中项目' },
      { source: 'pending', key: 'pendingReviews', label: '待复盘' },
      { source: 'counts', key: 'reviews', label: '复盘记录' },
    ],
  },
  {
    id: 'local_intake', lane: 'local', column: 2, accent: 'agent',
    label: '本机素材取证', path: '/media-agent', pathLabel: 'Agent 任务',
    stage: null, artifactType: null,
    capabilities: [{ id: 'source_asset_intake', label: '素材' }, { id: 'recent_records_summary', label: '整理' }],
    pipelines: ['media.project.prepare.v1', 'media.material.organize.v1'],
    action: '配对的 Mac 在本机扫描素材、读技术元数据、抽关键帧与转写，按 metadata / preview / deep 分层取证。',
    outcome: '只回传证据化摘要与素材描述符，原始媒体、工程文件和绝对路径都留在本机。',
    facts: [
      { source: 'localJobs', label: '本机任务' },
      { source: 'devices', label: '在线设备' },
    ],
  },
  {
    id: 'local_edit', lane: 'local', column: 5, accent: 'agent',
    label: '交接包与人工精剪', path: '/media-agent', pathLabel: 'Agent 任务',
    stage: null, artifactType: null,
    capabilities: [{ id: 'creation_checklist_lookup', label: '检查' }, { id: 'media_growth_review', label: '复核' }],
    pipelines: ['media.material.match.v1', 'media.edit.handoff.v1', 'media.edit.timeline.v1', 'media.edit.revise.v1', 'media.output.review.v1'],
    action: '按脚本与分镜在本机匹配素材，生成剪辑交接包或可编辑时间线，人工完成精剪后做成片复核。',
    outcome: '成片与剪辑日志回传云端，进入发布交付；返修意见回到创作产生新版本。',
    facts: [
      { source: 'localJobs', label: '剪辑任务' },
      { source: 'devices', label: '在线设备' },
    ],
  },
  {
    id: 'profile', lane: 'commercial', column: 1, accent: 'business',
    label: '达人档案与报价', path: '/business', pathLabel: 'Business',
    stage: null, artifactType: null,
    capabilities: [
      { id: 'id_business', label: '商务>ID' },
      { id: 'creator_profile_upsert', label: '博主-入库' },
    ],
    action: '维护达人账号事实、图文与视频的报价快照、权益和授权边界。',
    outcome: '账号级报价与权益边界，不绑定单一品牌。',
    facts: [],
    hint: '报价与权益',
  },
  {
    id: 'opportunity', lane: 'commercial', column: 2, accent: 'business',
    label: '商务机会', path: '/business', pathLabel: 'Business',
    stage: null, artifactType: null,
    capabilities: [{ id: 'id_business', label: '商务>ID' }],
    action: '登记品牌、产品、平台、档期与授权范围，跟进报价确认与排期。',
    outcome: '已授权的商务机会，作为商单履约入口。',
    facts: [{ source: 'opportunities', label: '商务机会' }],
  },
  {
    id: 'brief', lane: 'commercial', column: 3, accent: 'campaign',
    label: '活动与商单 Brief', path: '/campaigns', pathLabel: 'Campaigns',
    stage: null, artifactType: null,
    capabilities: [
      { id: 'commercial_brief', label: 'Brief' },
      { id: 'commercial_delivery_draft', label: '商单交付' },
      { id: 'activity_archive', label: '活动' },
    ],
    action: '把品牌要求、平台活动资料和禁区整理成可执行 Brief，启动商单交付项目。',
    outcome: '商单交付项目：原始 Brief 可回查，交付时间与禁区不靠猜。',
    facts: [{ source: 'tasks', capabilityId: 'commercial_delivery_draft', attention: false, label: '进行中商单' }],
  },
  {
    id: 'acceptance', lane: 'commercial', column: 4, accent: 'campaign',
    label: '品牌审核与返修', path: '/campaigns', pathLabel: 'Campaigns',
    stage: null, artifactType: null,
    capabilities: [{ id: 'work_acceptance_report', label: '作品验收' }],
    action: '初稿送品牌审核，审核意见记录改哪里、改成什么、由谁确认；返修回到创作产生新版本。',
    outcome: '验收通过的成片或成稿，进入交付。',
    facts: [{ source: 'tasks', capabilityId: 'commercial_delivery_draft', attention: true, label: '待人工确认' }],
  },
]

export const WORKBOARD_FLOW_NODES: readonly WorkboardFlowNode[] = flowNodeDefinitions.map((node) => ({
  ...node,
  artifactLabel: node.artifactType ? artifactTypeDisplayLabel(node.artifactType) : null,
}))

export const WORKBOARD_FLOW_EDGES: readonly WorkboardFlowEdge[] = [
  { from: 'accounts', to: 'research', kind: 'forward' },
  { from: 'research', to: 'decision', kind: 'forward' },
  { from: 'decision', to: 'creation', kind: 'forward', label: '选题进入创作' },
  { from: 'assets', to: 'creation', kind: 'forward', label: '素材汇入' },
  { from: 'profile', to: 'opportunity', kind: 'forward' },
  { from: 'opportunity', to: 'brief', kind: 'forward' },
  { from: 'brief', to: 'creation', kind: 'forward', label: '商单初稿' },
  { from: 'local_intake', to: 'assets', kind: 'forward', label: '素材摘要回传' },
  { from: 'creation', to: 'local_edit', kind: 'forward', label: '交接包' },
  { from: 'local_edit', to: 'publishing', kind: 'forward', label: '成片回传' },
  { from: 'creation', to: 'publishing', kind: 'forward', label: '自制内容' },
  { from: 'creation', to: 'acceptance', kind: 'forward', label: '送审' },
  { from: 'acceptance', to: 'creation', kind: 'return', label: '返修' },
  { from: 'acceptance', to: 'publishing', kind: 'forward', label: '交付' },
  { from: 'publishing', to: 'review', kind: 'forward' },
  { from: 'review', to: 'research', kind: 'loop', label: '经验回流到研究与选题' },
  { from: 'review', to: 'opportunity', kind: 'loop', label: '结案数据带来复购' },
]

/** 自动巡游顺序：先走内容线，再走商务线，最后在合流处汇合。 */
export const WORKBOARD_FLOW_TOUR = ['accounts', 'research', 'assets', 'local_intake', 'decision', 'profile', 'opportunity', 'brief', 'creation', 'local_edit', 'acceptance', 'publishing', 'review'] as const

export function workboardFlowNode(id: string): WorkboardFlowNode | undefined {
  return WORKBOARD_FLOW_NODES.find((node) => node.id === id)
}

/** 项目阶段在全流程主干中的位置（0 起），未知阶段返回 null。creation_ready 与 creation 同位。 */
export function workboardStageIndex(stage: string): number | null {
  const normalized = stage === 'creation_ready' ? 'creation' : stage
  const index = WORKBOARD_FLOW_STAGE_ORDER.indexOf(normalized as (typeof WORKBOARD_FLOW_STAGE_ORDER)[number])
  return index === -1 ? null : index
}

/** 主干阶段对应的流程节点：项目卡片用它跳到承接该阶段的页面。 */
export function workboardStageNode(stage: string): WorkboardFlowNode | undefined {
  const normalized = stage === 'creation_ready' ? 'creation' : stage
  return WORKBOARD_FLOW_NODES.find((node) => node.stage === normalized)
}
