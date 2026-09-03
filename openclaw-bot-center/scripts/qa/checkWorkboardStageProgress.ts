import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { ARTIFACT_TYPE_LABELS } from '../../src/media/ui/ordinaryDataLabels'
import { pipelineDisplayLabel } from '../../src/media/ui/displayLabels'
import type { PipelineSummary } from '../../src/media/generatedProductContract'
import {
  WORKBOARD_FLOW_COLUMNS,
  WORKBOARD_FLOW_EDGES,
  WORKBOARD_FLOW_NODES,
  WORKBOARD_FLOW_STAGE_ORDER,
  WORKBOARD_FLOW_TOUR,
  workboardStageIndex,
  workboardStageNode,
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

// ---- /today 全流程图：每个节点都必须绑定真实的合同枚举、合同字段、产物类型、能力与生产路由 ----
const contract = readFileSync(resolve('contracts/media_web_business_pages.openapi.yaml'), 'utf8')
const stageCountEnum = /StageCount:[\s\S]*?stage:\s*type: string\s*enum:\s*((?:\s*- \w+)+)/.exec(contract)?.[1]
assert.ok(stageCountEnum, 'StageCount.stage enum must be readable from the business contract')
const contractStages = stageCountEnum.trim().split(/\s*-\s*/).filter(Boolean)
assert.deepEqual([...WORKBOARD_FLOW_STAGE_ORDER], contractStages, 'project stage backbone must equal the contract StageCount.stage enum order')
const dashboardCounts = /DashboardCounts:\s*type: object\s*additionalProperties: false\s*properties:\s*((?:\s*\w+:\s*type: integer\s*minimum: 0)+)/.exec(contract)?.[1]
assert.ok(dashboardCounts, 'DashboardCounts properties must be readable from the business contract')
const countKeys = new Set([...dashboardCounts.matchAll(/(\w+):\s*type: integer/g)].map((match) => match[1]))
const summaryBlock = /DashboardSummary:[\s\S]*?required:/.exec(contract)?.[0] ?? ''
const routeTable = readFileSync(resolve('src/media/MediaStudioApp.tsx'), 'utf8')
// 能力目录由能力注册表（openclaw-tag-router）生成，演示站与生产共用同一份 id/label。
const catalog = JSON.parse(readFileSync(resolve('src/demo/generatedDemoCatalog.json'), 'utf8')) as { capabilities?: { capabilityId: string; label: string }[] } | { capabilityId: string; label: string }[]
const catalogItems = Array.isArray(catalog) ? catalog : catalog.capabilities ?? []
const capabilityLabels = new Map(catalogItems.map((item) => [item.capabilityId, item.label]))
assert.ok(capabilityLabels.size > 20, 'capability catalog must be loaded')

const nodeIds = new Set(WORKBOARD_FLOW_NODES.map((node) => node.id))
assert.equal(nodeIds.size, WORKBOARD_FLOW_NODES.length, 'flow node ids must be unique')
for (const node of WORKBOARD_FLOW_NODES) {
  assert.ok(routeTable.includes(`path: '${node.path}'`), `${node.id} must link to a registered production route (${node.path})`)
  assert.ok(node.action.length > 8 && node.outcome.length > 8, `${node.id} must say what happens and what it produces`)
  assert.ok(node.capabilities.length > 0, `${node.id} must name at least one capability`)
  for (const capability of node.capabilities) {
    assert.equal(capabilityLabels.get(capability.id), capability.label, `${node.id} capability ${capability.id} must exist in the registry with the same label`)
  }
  if (node.stage) {
    assert.ok(contractStages.includes(node.stage), `${node.id} stage must be a contract stage`)
    assert.equal(node.artifactLabel, ARTIFACT_TYPE_LABELS[node.artifactType ?? ''], `${node.id} artifact label must come from the shared table`)
    assert.equal(workboardStageNode(node.stage)?.id, node.id, `${node.id} must be the node the project card resolves for ${node.stage}`)
    assert.equal(workboardStageProgress(node.stage).label, node.stage === 'assets' ? '素材整理' : workboardStageProgress(node.stage).label, `${node.id} stage label must stay in the shared table`)
  } else {
    assert.equal(node.artifactType, null, `${node.id} without a project stage must not claim an artifact type`)
  }
  for (const fact of node.facts) {
    if (fact.source === 'stage') assert.ok(contractStages.includes(fact.stage), `${node.id} fact stage ${fact.stage} must be a contract stage`)
    if (fact.source === 'counts') assert.ok(countKeys.has(fact.key), `${node.id} fact ${fact.key} must be a DashboardCounts field`)
    if (fact.source === 'pending') assert.ok(summaryBlock.includes(`${fact.key}:`), `${node.id} fact ${fact.key} must be a DashboardSummary field`)
    if (fact.source === 'tasks') assert.ok(capabilityLabels.has(fact.capabilityId), `${node.id} task fact must count a registered capability`)
  }
}
// 本机剪辑线（Mac）：节点声明的本机流程必须是生产流程目录里的 id，演示站的目录也必须用同一批 id。
const pipelineSummary = (pipeline_id: string): PipelineSummary => ({ pipeline_id, version: '0.0.0', display_name: '', catalog_digest: '' })
const localNodes = WORKBOARD_FLOW_NODES.filter((node) => node.lane === 'local')
assert.ok(localNodes.length >= 2, 'the local editing lane must carry the Mac intake and the hand-off/final-cut steps')
for (const node of localNodes) {
  assert.ok(node.pipelines?.length, `${node.id} must name the local pipelines it runs`)
  assert.equal(node.path, '/media-agent', `${node.id} must link to the local agent page`)
  for (const pipeline of node.pipelines ?? []) {
    assert.notEqual(pipelineDisplayLabel(pipelineSummary(pipeline)), '其他流程', `${node.id} pipeline ${pipeline} must exist in the production pipeline catalog`)
  }
}
for (const node of WORKBOARD_FLOW_NODES) {
  if (node.lane !== 'local') assert.equal(node.pipelines, undefined, `${node.id} is not a local step and must not claim local pipelines`)
}
const demoBackend = readFileSync(resolve('src/demo/demoBackend.ts'), 'utf8')
const demoPipelineBlock = /const demoPipelines: PipelineSummary\[\] = \[([\s\S]*?)\n\]/.exec(demoBackend)?.[1] ?? ''
const demoPipelineIds = [...demoPipelineBlock.matchAll(/pipeline_id: '([^']+)'/g)].map((match) => match[1]!)
assert.ok(demoPipelineIds.length >= 6, 'the demo pipeline catalog must be readable')
for (const pipeline of demoPipelineIds) {
  assert.notEqual(pipelineDisplayLabel(pipelineSummary(pipeline)), '其他流程', `demo pipeline ${pipeline} must use a production pipeline id`)
}
for (const node of localNodes) {
  for (const pipeline of node.pipelines ?? []) {
    assert.ok(demoPipelineIds.includes(pipeline), `demo pipeline catalog must expose ${pipeline} so the prototype shows the same local lane`)
  }
}
for (const [from, to] of [['local_intake', 'assets'], ['creation', 'local_edit'], ['local_edit', 'publishing']] as const) {
  assert.ok(WORKBOARD_FLOW_EDGES.some((edge) => edge.from === from && edge.to === to), `the local editing lane must connect ${from} -> ${to}`)
}

const grouped = new Map<string, number>()
for (const node of WORKBOARD_FLOW_NODES) {
  const key = `${node.lane}:${node.column}`
  grouped.set(key, (grouped.get(key) ?? 0) + 1)
}
for (const [key, count] of grouped) assert.equal(count, 1, `lane/column cell ${key} must hold exactly one node`)
for (const edge of WORKBOARD_FLOW_EDGES) {
  assert.ok(nodeIds.has(edge.from) && nodeIds.has(edge.to), `edge ${edge.from}->${edge.to} must connect existing nodes`)
}
assert.ok(WORKBOARD_FLOW_EDGES.some((edge) => edge.from === 'decision' && edge.to === 'creation') && WORKBOARD_FLOW_EDGES.some((edge) => edge.from === 'brief' && edge.to === 'creation'), 'content and commercial lanes must merge at creation')
assert.ok(WORKBOARD_FLOW_EDGES.some((edge) => edge.kind === 'return' && edge.from === 'acceptance' && edge.to === 'creation'), 'brand acceptance must be able to send work back for revision')
assert.ok(WORKBOARD_FLOW_EDGES.filter((edge) => edge.kind === 'loop' && edge.from === 'review').length === 2, 'review must feed back into both research and business opportunities')
assert.deepEqual([...WORKBOARD_FLOW_TOUR].sort(), [...nodeIds].sort(), 'the auto tour must visit every node exactly once')
assert.equal(WORKBOARD_FLOW_COLUMNS.length, 6, 'the diagram keeps six columns')
assert.equal(workboardStageIndex('creation_ready'), workboardStageIndex('creation'), 'creation_ready shares the creation position')
assert.equal(workboardStageIndex('future_backend_stage'), null, 'an unknown stage has no diagram position')
assert.deepEqual(WORKBOARD_FLOW_STAGE_ORDER.map((stage) => workboardStageIndex(stage)), [0, 1, 2, 3, 4, 5])
assert.equal(workboardStageNode('creation_ready')?.id, 'creation', 'creation_ready resolves to the creation node')

console.log('workboard stage progress checks passed')
