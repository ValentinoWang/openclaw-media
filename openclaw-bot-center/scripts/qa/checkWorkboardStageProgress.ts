import assert from 'node:assert/strict'

import { workboardStageProgress } from '../../src/media/studio/workboardPresentation'

for (const [stage, label, progress] of [
  ['research', '研究', 12],
  ['assets', '素材整理', 28],
  ['decision', '选题决策', 46],
  ['creation', '内容创作', 66],
  ['creation_ready', '内容创作', 66],
  ['publishing', '发布准备', 86],
  ['review', '复盘增长', 100],
  ['captured', '已登记', 12],
  ['planned', '已规划', 28],
  ['edit_ready', '可开始剪辑', 46],
  ['editing', '剪辑中', 66],
  ['final_ready', '待发布', 86],
  ['published', '已发布', 100],
] as const) {
  assert.deepEqual(
    workboardStageProgress(stage),
    { label, progress },
    `${stage} must retain its user-visible production position`,
  )
}

assert.deepEqual(
  workboardStageProgress('future_backend_stage'),
  { label: '项目阶段待确认', progress: null },
  'an unknown stage must not invent a progress percentage',
)

console.log('workboard stage progress checks passed')
