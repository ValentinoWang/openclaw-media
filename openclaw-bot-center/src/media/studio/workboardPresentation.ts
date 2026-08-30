import { projectStageDisplayLabel } from '../ui/displayLabels'

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
