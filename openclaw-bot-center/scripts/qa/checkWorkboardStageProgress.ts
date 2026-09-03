import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { ARTIFACT_TYPE_LABELS } from '../../src/media/ui/ordinaryDataLabels'
import {
  WORKBOARD_FLOW_STAGES,
  WORKBOARD_FLOW_STAGE_ORDER,
  workboardStageIndex,
  workboardStageProgress,
} from '../../src/media/studio/workboardPresentation'

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

// ---- /today 全流程图：每个节点都必须绑定真实的合同枚举、产物类型与生产路由 ----
const contract = readFileSync(resolve('contracts/media_web_business_pages.openapi.yaml'), 'utf8')
const stageCountEnum = /StageCount:[\s\S]*?stage:\s*type: string\s*enum:\s*((?:\s*- \w+)+)/.exec(contract)?.[1]
assert.ok(stageCountEnum, 'StageCount.stage enum must be readable from the business contract')
assert.deepEqual(
  [...WORKBOARD_FLOW_STAGE_ORDER],
  stageCountEnum.trim().split(/\s*-\s*/).filter(Boolean),
  'workflow diagram stage order must equal the contract StageCount.stage enum order',
)
const routeTable = readFileSync(resolve('src/media/MediaStudioApp.tsx'), 'utf8')
for (const stage of WORKBOARD_FLOW_STAGES) {
  assert.ok(stage.artifactType in ARTIFACT_TYPE_LABELS, `${stage.stage} must produce a contract artifact type`)
  assert.equal(stage.artifactLabel, ARTIFACT_TYPE_LABELS[stage.artifactType], `${stage.stage} artifact label must come from the shared table`)
  assert.ok(routeTable.includes(`path: '${stage.path}'`), `${stage.stage} must link to a registered production route (${stage.path})`)
  assert.equal(stage.label, workboardStageProgress(stage.stage).label, `${stage.stage} diagram label must match the project card label`)
  assert.ok(stage.action.length > 8 && stage.outcome.length > 8, `${stage.stage} must say what happens and what it produces`)
  if (stage.pending) assert.ok(['pendingDecisions', 'pendingPublishing', 'pendingReviews'].includes(stage.pending) && stage.pendingLabel, `${stage.stage} pending counter must be a DashboardSummary field`)
}
assert.equal(workboardStageIndex('creation_ready'), workboardStageIndex('creation'), 'creation_ready shares the creation position')
assert.equal(workboardStageIndex('future_backend_stage'), null, 'an unknown stage has no diagram position')
assert.deepEqual(WORKBOARD_FLOW_STAGE_ORDER.map((stage) => workboardStageIndex(stage)), [0, 1, 2, 3, 4, 5])

console.log('workboard stage progress checks passed')
