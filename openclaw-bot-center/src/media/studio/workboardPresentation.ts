export type WorkboardStageProgress = {
  readonly label: string
  readonly progress: number | null
}

export type WorkboardTask = {
  readonly status: string
  readonly terminal: boolean
}

const stageProgressByStage: Readonly<Record<string, WorkboardStageProgress>> = {
  research: { label: '研究', progress: 12 },
  assets: { label: '素材整理', progress: 28 },
  decision: { label: '选题决策', progress: 46 },
  creation: { label: '内容创作', progress: 66 },
  creation_ready: { label: '内容创作', progress: 66 },
  publishing: { label: '发布准备', progress: 86 },
  review: { label: '复盘增长', progress: 100 },
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

const attentionTaskStatuses = new Set([
  'awaiting_confirmation',
  'pending_manual',
  'needs_attention',
  'failed',
])

export function workboardStageProgress(stage: string): WorkboardStageProgress {
  return stageProgressByStage[stage] ?? unknownStageProgress
}

export function filterWorkboardAttentionTasks<T extends WorkboardTask>(
  tasks: readonly T[],
): T[] {
  return tasks.filter((task) => attentionTaskStatuses.has(task.status))
}
