import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { dashboardSchema, executionGraphSchema } from '../src/schemas/dashboardSchema'

const dataPath = resolve('public/data/openclaw-bot-center.generated.json')
const knowledgeAgentInstructionsPath = '/home/ubuntu/openclaw-agents/knowledge/AGENTS.md'
const raw = readFileSync(dataPath, 'utf-8')
const parsed = dashboardSchema.safeParse(JSON.parse(raw))

if (!parsed.success) {
  console.error(parsed.error.format())
  process.exit(1)
}

const data = parsed.data
const errors: string[] = []
const legacySensitiveDeletionDirective = ['do_not', 'include_in_final_note'].join('_')
if (raw.includes(legacySensitiveDeletionDirective)) {
  errors.push('generated Bot Center data must not contain the retired sensitive-detail deletion directive')
}
const commercialDeliveryTargetToken = 'HJ8awfpZAiiFofkOk6Ncw8NKnNM'
const commercialDeliveryOldToken = ['CJPRwwuF5iG91V', 'kqYAAct0Qanzb'].join('')
const normalViewTermTablePath = '/home/ubuntu/docs/ai-harness/bot-center-normal-view-term-translation-table.json'
const tagCapabilitiesPath = '/home/ubuntu/.openclaw/extensions/openclaw-tag-router/openclaw_app/router/tag_capabilities.py'
const misleadingPromptMetadataTerms = [
  '真实送入 LLM',
  '真实 LLM 提示词',
  '脱敏真实运行提示词',
  '按运行入口送入 LLM',
  '运行时实际送入模型的 prompt',
]

function checkExecutionGraphSchemaFixtures() {
  const template = data.capabilities[0]?.executionGraph.nodes[0]
  if (!template) {
    errors.push('execution graph fixture could not find a node template')
    return
  }
  const node = (id: string) => ({
    ...template,
    id,
    title: id,
    nodeType: 'supporting_contract' as const,
    promptContractId: undefined,
  })
  const base = {
    id: 'execution-graph-contract-fixture',
    title: 'fixture',
    summary: 'fixture',
    graphKind: 'manual' as const,
    nodes: [node('entry'), node('decision'), node('pass'), node('manual'), node('reply')],
  }
  const positive = executionGraphSchema.safeParse({
    ...base,
    edges: [
      { from: 'entry', to: 'decision' },
      { from: 'decision', to: 'pass', label: '通过' },
      { from: 'decision', to: 'manual', label: '待人工' },
      { from: 'pass', to: 'reply' },
      { from: 'manual', to: 'reply' },
    ],
  })
  if (!positive.success) errors.push(`valid execution graph branch fixture was rejected: ${positive.error.message}`)
  const negativeFixtures = [
    { name: 'unknown endpoint', edges: [{ from: 'entry', to: 'missing' }] },
    {
      name: 'unlabeled branch',
      edges: [
        { from: 'entry', to: 'decision' },
        { from: 'decision', to: 'pass' },
        { from: 'decision', to: 'manual', label: '待人工' },
        { from: 'pass', to: 'reply' },
        { from: 'manual', to: 'reply' },
      ],
    },
    {
      name: 'cycle',
      edges: [
        { from: 'entry', to: 'decision' },
        { from: 'decision', to: 'pass', label: '通过' },
        { from: 'decision', to: 'manual', label: '待人工' },
        { from: 'pass', to: 'reply' },
        { from: 'manual', to: 'reply' },
        { from: 'reply', to: 'decision' },
      ],
    },
  ]
  for (const fixture of negativeFixtures) {
    if (executionGraphSchema.safeParse({ ...base, edges: fixture.edges }).success) {
      errors.push(`invalid execution graph fixture was accepted: ${fixture.name}`)
    }
  }
}

checkExecutionGraphSchemaFixtures()

type CapabilityData = typeof data.capabilities[number]
type NormalViewTerm = {
  id: string
  pattern: RegExp
  replacementHint: string
}

function regexFlags(rawFlags: unknown, termId: string) {
  if (rawFlags === undefined || rawFlags === null) return ''
  if (!Array.isArray(rawFlags)) {
    throw new Error(`term ${termId} flags must be a list`)
  }
  let flags = ''
  for (const rawFlag of rawFlags) {
    if (rawFlag === 'IGNORECASE') flags += 'i'
    else if (rawFlag === 'MULTILINE') flags += 'm'
    else throw new Error(`term ${termId} has unsupported regex flag ${String(rawFlag)}`)
  }
  return flags
}

function loadNormalViewTerms(path: string): NormalViewTerm[] {
  const table = JSON.parse(readFileSync(path, 'utf-8')) as {
    scope?: string
    terms?: Array<{ id?: string; pattern?: string; flags?: unknown; normal_view?: string }>
  }
  if (table.scope !== 'bot_center_normal_view') {
    throw new Error(`${path}: scope must be bot_center_normal_view`)
  }
  if (!Array.isArray(table.terms) || table.terms.length === 0) {
    throw new Error(`${path}: terms must be a non-empty list`)
  }
  const seen = new Set<string>()
  return table.terms.map((term, index) => {
    const id = String(term.id ?? '').trim()
    const pattern = String(term.pattern ?? '')
    const replacementHint = String(term.normal_view ?? '').trim()
    if (!id || !pattern || !replacementHint) {
      throw new Error(`${path}: terms[${index}] requires id, pattern and normal_view`)
    }
    if (seen.has(id)) {
      throw new Error(`${path}: duplicate term id ${id}`)
    }
    seen.add(id)
    return {
      id,
      pattern: new RegExp(pattern, regexFlags(term.flags, id)),
      replacementHint,
    }
  })
}

function walkText(value: unknown, path: string): Array<{ path: string; text: string }> {
  if (typeof value === 'string') return [{ path, text: value }]
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => walkText(item, `${path}[${index}]`))
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) => walkText(item, path ? `${path}.${key}` : key))
  }
  return []
}

function normalViewTexts(capability: CapabilityData): Array<{ path: string; text: string }> {
  const display = capability.displayProjection
  const texts: Array<{ path: string; text: string }> = []
  for (const field of [
    'displayTitle',
    'displaySubtitle',
    'operatorSummary',
    'whenToUse',
    'whenNotToUse',
    'outputSummary',
    'nextActions',
    'evidenceSummary',
    'riskBadges',
    'savedAs',
    'operatorFlow',
  ] as const) {
    texts.push(...walkText(display[field], `displayProjection.${field}`))
  }
  if (capability.entryTree) {
    const nodes = [capability.entryTree.root, ...capability.entryTree.children]
    nodes.forEach((node, index) => {
      const prefix = index === 0 ? 'entryTree.root' : `entryTree.children[${index - 1}]`
      for (const field of [
        'displayName',
        'purpose',
        'outputContract',
        'supportedAttachments',
        'riskLevel',
        'visibility',
      ] as const) {
        texts.push(...walkText(node[field], `${prefix}.${field}`))
      }
    })
  }
  return texts
}

let normalViewTerms: NormalViewTerm[] = []
try {
  normalViewTerms = loadNormalViewTerms(normalViewTermTablePath)
} catch (error) {
  errors.push(`failed to load normal-view term translation table: ${error instanceof Error ? error.message : String(error)}`)
}
function extractMarkdownPromptBody(path: string, heading: string) {
  const text = readFileSync(path, 'utf-8')
  const marker = `### \`${heading}\` 送入 LLM 的提示词正文`
  const start = text.indexOf(marker)
  if (start < 0) {
    errors.push(`missing prompt heading in ${path}: ${marker}`)
    return ''
  }
  const bodyStart = text.indexOf('\n', start)
  if (bodyStart < 0) {
    errors.push(`empty prompt heading in ${path}: ${marker}`)
    return ''
  }
  const searchStart = bodyStart + 1
  const candidates = ['\n### ', '\n## ', '\n执行后用本地脚本写入：', '\n执行后用本地脚本写入:']
    .map((pattern) => text.indexOf(pattern, searchStart))
    .filter((index) => index >= 0)
  const bodyEnd = candidates.length ? Math.min(...candidates) : text.length
  return text.slice(searchStart, bodyEnd).trim()
}

function safeText(value: string) {
  return value
    .replace(/\/home\/ubuntu\/[^\s，；。)）]+/g, '内部沉淀区')
    .replace(/\/Users\/[^\s，；。)）]+/g, 'Mac 本地路径线索')
    .replace(/\btoken\b|\bsecret\b|\bcookie\b|\bapp[_ -]?key\b/gi, '敏感字段')
    .trim()
}

function knowledgeCapabilityPromptBody(label: string) {
  const rawLabel = `【${label}】`
  return safeText(extractMarkdownPromptBody(knowledgeAgentInstructionsPath, rawLabel))
}

function requireUnique(values: string[], label: string) {
  const seen = new Set<string>()
  for (const value of values) {
    if (seen.has(value)) {
      errors.push(`${label} is duplicated: ${value}`)
    }
    seen.add(value)
  }
}

requireUnique(
  data.capabilities.map((item) => item.id),
  'capability id',
)
requireUnique(
  data.bots.map((item) => item.id),
  'bot id',
)
requireUnique(
  data.tasks.map((item) => item.id),
  'task id',
)
requireUnique(
  data.links.map((item) => item.id),
  'link id',
)
requireUnique(
  data.flows.map((item) => item.id),
  'flow id',
)

const capabilityIds = new Set(data.capabilities.map((item) => item.id))
const botIds = new Set(data.bots.map((item) => item.id))
type ActiveTagCapability = {
  label: string
  source_system?: string
  implementation_status?: string
}
let activeTagCapabilities: ActiveTagCapability[] = []
const flowStageIds = new Set(data.flows.flatMap((flow) => flow.stages.map((stage) => stage.id)))
const contentProductionStageIds = new Set([
  'cloud-project-package',
  'local-binding-gate',
  'mac-intake',
  'mac-material-analysis',
  'creative-assembly',
  'editing-packaging',
  'output-review-writeback',
  'publish-archive',
])
const requiredUniversalDeleteBotIds = ['media', 'daily', 'knowledge', 'social'] as const
const contentOsPresentationForbiddenTerms = [
  'OTIO',
  'Kdenlive',
  'EDL',
  '剪映',
  'draft_content',
  '/Users/',
  '/home/',
  'task_',
  'change_request',
  'project_revision',
  'editor_backend',
  'Traceback',
  'error_code',
]

const contentFlow = data.flows.find((flow) => flow.id === 'cloud-mac-materials')
if (!contentFlow) {
  errors.push('Content OS flow is missing: cloud-mac-materials')
} else {
  const contentFlowText = JSON.stringify(contentFlow)
  for (const forbidden of contentOsPresentationForbiddenTerms) {
    if (contentFlowText.includes(forbidden)) {
      errors.push(`Content OS flow leaks forbidden operator text: ${forbidden}`)
    }
  }
  const planStage = contentFlow.stages.find((stage) => stage.id === 'creative-assembly')
  const editStage = contentFlow.stages.find((stage) => stage.id === 'editing-packaging')
  if (planStage?.title !== '生成剪辑方案') {
    errors.push('Content OS plan stage must be titled 生成剪辑方案')
  }
  if (editStage?.title !== '做包装和人工精剪') {
    errors.push('Content OS edit stage must be titled 做包装和人工精剪')
  }
  if (!planStage?.outputs.some((item) => item.includes('标准剪辑交接包或可编辑时间线'))) {
    errors.push('Content OS plan stage must expose 标准剪辑交接包或可编辑时间线')
  }
}

const contentOsProjectDashboard = data.contentOsProjectDashboard
if (
  contentOsProjectDashboard.modificationEntry.label !== '在 Media Bot 对话中提交修改'
  || contentOsProjectDashboard.modificationEntry.url !== '#/bots/media'
  || !contentOsProjectDashboard.modificationEntry.instruction.includes('【修改】修改项目')
) {
  errors.push('Content OS modification entry must point to the public Media Bot entry')
}
for (const project of contentOsProjectDashboard.projects) {
  if (!['标准剪辑', '可编辑时间线', '待选择'].includes(project.editingMethod)) {
    errors.push(`Content OS project has an invalid operator-facing editing method: ${project.editingMethod}`)
  }
  for (const [field, value] of Object.entries(project)) {
    if (field === 'id') continue
    for (const forbidden of contentOsPresentationForbiddenTerms) {
      if (value.includes(forbidden)) {
        errors.push(`Content OS project ${field} leaks forbidden operator text: ${forbidden}`)
      }
    }
  }
}

try {
  const active = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util
import json
import sys

sys.path.insert(0, '/home/ubuntu/selfmedia-tools')
path = ${JSON.stringify(tagCapabilitiesPath)}
spec = importlib.util.spec_from_file_location('openclaw_tag_capabilities_validation', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print(json.dumps([
    {
        "label": item.label,
        "source_system": item.source_system,
        "implementation_status": item.implementation_status,
    }
    for item in module.TAG_CAPABILITIES
], ensure_ascii=False))
`], { encoding: 'utf-8' })) as ActiveTagCapability[]
  activeTagCapabilities = active
  const expected = new Set(active.map((item) => item.label))
  const actual = new Set(data.capabilities.map((capability) => capability.rawLabel.replace(/^【|】$/g, '')))
  const missing = [...expected].filter((label) => !actual.has(label))
  const unexpected = [...actual].filter((label) => !expected.has(label))
  if (missing.length > 0 || unexpected.length > 0) {
    errors.push(`capability labels must match active tag-router labels after retired-label removal; missing=${missing.join(', ') || '<none>'}; unexpected=${unexpected.join(', ') || '<none>'}`)
  }
} catch (error) {
  errors.push(`failed to load active tag-router capability labels: ${error instanceof Error ? error.message : String(error)}`)
}

if (data.meta.capabilityCount !== data.capabilities.length) {
  errors.push(
    `meta.capabilityCount=${data.meta.capabilityCount} does not match capabilities.length=${data.capabilities.length}`,
  )
}

if (data.meta.triggerLabelCount !== undefined && data.meta.triggerLabelCount !== data.capabilities.length) {
  errors.push(
    `meta.triggerLabelCount=${data.meta.triggerLabelCount} does not match capabilities.length=${data.capabilities.length}`,
  )
}

const labelsByCanonical = new Map<string, string[]>()
for (const capability of data.capabilities) {
  const labels = labelsByCanonical.get(capability.canonicalCapabilityId) ?? []
  labels.push(capability.rawLabel)
  labelsByCanonical.set(capability.canonicalCapabilityId, labels)
}

if (data.meta.canonicalCapabilityCount !== undefined && data.meta.canonicalCapabilityCount !== labelsByCanonical.size) {
  errors.push(
    `meta.canonicalCapabilityCount=${data.meta.canonicalCapabilityCount} does not match canonicalCapabilityId count=${labelsByCanonical.size}`,
  )
}

const recommendedEntries = data.capabilities.filter((item) => item.recommendedEntry)
if (data.meta.recommendedEntryCount !== undefined && data.meta.recommendedEntryCount !== recommendedEntries.length) {
  errors.push(
    `meta.recommendedEntryCount=${data.meta.recommendedEntryCount} does not match recommended entry count=${recommendedEntries.length}`,
  )
}

const expectedRecommendedLabels = new Set([
  '【今日】',
  '【素材】',
  '【调研】',
  '【选题】',
  '【创作】',
  '【拍摄】',
  '【润色】',
  '【检查】',
  '【发布包】',
  '【复盘】',
  '【博主】',
  '【商单交付】',
  '【衣橱】',
])
const actualRecommendedLabels = new Set(recommendedEntries.map((item) => item.rawLabel))
for (const expected of expectedRecommendedLabels) {
  if (!actualRecommendedLabels.has(expected)) {
    errors.push(`recommended entry label is missing: ${expected}`)
  }
}
for (const actual of actualRecommendedLabels) {
  if (!expectedRecommendedLabels.has(actual)) {
    errors.push(`unexpected recommended entry label: ${actual}`)
  }
}
for (const capability of recommendedEntries) {
  if (capability.implementationStatus === 'not_implemented') {
    errors.push(`${capability.rawLabel} must not be a recommended entry while implementationStatus=not_implemented`)
  }
}

const expectedDisplayArchetypes: Record<string, CapabilityData['displayProjection']['displayArchetype']> = {
  'media-source-asset': 'Entry Hub',
  'media-topic-decision': 'Direct Action',
  'media-growth-review': 'Gate/Review',
  'creation-xiaohongshu': 'Creation Handoff',
  'creator-profile': 'Entity Store',
  delete: 'System/Maintenance',
}
for (const [capabilityId, expectedArchetype] of Object.entries(expectedDisplayArchetypes)) {
  const capability = data.capabilities.find((item) => item.id === capabilityId)
  if (!capability) {
    errors.push(`display archetype rule references missing capability=${capabilityId}`)
  } else if (capability.displayProjection.displayArchetype !== expectedArchetype) {
    errors.push(
      `${capability.id} displayProjection.displayArchetype must be ${expectedArchetype}; got ${capability.displayProjection.displayArchetype}`,
    )
  }
}

const creatorProfileRoot = data.capabilities.find((item) => item.rawLabel === '【博主】')
if (!creatorProfileRoot) {
  errors.push('creator profile unified entry is missing: 【博主】')
} else {
  if (!creatorProfileRoot.recommendedEntry) {
    errors.push('【博主】 must stay the unified recommended entry for creator profile inputs')
  }
  const childEntries = creatorProfileRoot.entryTree?.children ?? []
  const upsertEntry = childEntries.find((entry) => entry.capabilityId === 'creator-profile-upsert')
  if (!upsertEntry) {
    errors.push('【博主】 entryTree must expose creator-profile-upsert as a unified input option')
  } else {
    if (upsertEntry.trigger !== '【博主-入库】') {
      errors.push(`creator-profile-upsert entry trigger must use its canonical label 【博主-入库】; got ${upsertEntry.trigger}`)
    }
    const templateBodies = upsertEntry.inputContract.templates.map((template) => template.body).join('\n')
    if (!templateBodies.includes('【博主-入库】') || !templateBodies.includes('平台：')) {
      errors.push('creator-profile-upsert entry template must use the canonical 【博主-入库】 field contract')
    }
  }
  if (childEntries.some((entry) => entry.capabilityId === 'commercial-delivery-draft')) {
    errors.push('commercial-delivery-draft must not be nested under 【博主】; it belongs at Media bot capability level')
  }
}
for (const childLabel of ['【博主-入库】']) {
  const child = data.capabilities.find((item) => item.rawLabel === childLabel)
  if (!child) {
    errors.push(`creator profile child capability is missing: ${childLabel}`)
  } else if (child.recommendedEntry) {
    errors.push(`${childLabel} must not be a standalone recommended entry; it belongs under 【博主】 input options`)
  }
}
const commercialDeliveryEntry = data.capabilities.find((item) => item.rawLabel === '【商单交付】')
if (!commercialDeliveryEntry) {
  errors.push('commercial delivery capability is missing: 【商单交付】')
} else if (!commercialDeliveryEntry.recommendedEntry) {
  errors.push('【商单交付】 must stay a Media bot recommended entry, not a creator-profile child entry')
}

const wardrobeRoot = data.capabilities.find((item) => item.rawLabel === '【衣橱】')
const wardrobeRecommendation = data.capabilities.find((item) => item.rawLabel === '【穿搭】')
if (!wardrobeRoot) {
  errors.push('Wardrobe root capability is missing: 【衣橱】')
} else {
  const childLabels = new Set((wardrobeRoot.entryTree?.children ?? []).map((entry) => entry.trigger))
  if (!wardrobeRoot.entryTree) {
    errors.push('【衣橱】 must expose an entryTree that collects wardrobe child entries')
  }
  if (!childLabels.has('【穿搭】')) {
    errors.push('【穿搭】 must be collected under 【衣橱】 entryTree children')
  }
}
if (!wardrobeRecommendation) {
  errors.push('Wardrobe recommendation capability is missing: 【穿搭】')
} else {
  if (wardrobeRecommendation.recommendedEntry) {
    errors.push('【穿搭】 must not be a standalone recommended entry; it belongs under 【衣橱】')
  }
  if (wardrobeRecommendation.implementationStatus !== 'implemented') {
    errors.push(`【穿搭】 must stay implemented; got ${wardrobeRecommendation.implementationStatus}`)
  }
}

const mediaGrowthStableLabels = new Set([
  '【策略】',
  '【素材】',
  '【调研】',
  '【选题】',
  '【拍摄】',
  '【检查】',
  '【发布包】',
  '【复核】',
  '【复盘】',
  '【账号】',
  '【赛道】',
])
for (const label of mediaGrowthStableLabels) {
  const capability = data.capabilities.find((item) => item.rawLabel === label)
  if (!capability) {
    errors.push(`MediaClaw tracked label is missing from capability data: ${label}`)
    continue
  }
  if (capability.id.startsWith('capability-')) {
    errors.push(`${label} must use a stable capability id, got generated id=${capability.id}`)
  }
}

const forbiddenGenericCanonicalIds = new Set([
  'knowledge_delegate',
  'research_delegate',
  'system',
  'development_status_update',
])
for (const capability of data.capabilities) {
  if (forbiddenGenericCanonicalIds.has(capability.canonicalCapabilityId)) {
    errors.push(`${capability.id} must not use generic handler name as canonicalCapabilityId=${capability.canonicalCapabilityId}`)
  }
  if (!['implemented', 'not_implemented', 'external'].includes(capability.implementationStatus)) {
    errors.push(`${capability.id} has invalid implementationStatus=${capability.implementationStatus}`)
  }
}

const allowedCanonicalAliasGroups: Record<string, string[]> = {
  creation_checklist_lookup: ['【检查】', '【创作检查】'],
  external_research_brief: ['【调研】'],
  selfmedia_data_review: ['【数据复盘】'],
  post_review_signal: ['【复盘】'],
  selfmedia_creation: ['【创作】', '【创作>小红书】', '【创作>抖音】'],
  shooting_execution_plan: ['【拍摄】', '【创作-拍摄执行】'],
  source_asset_intake: ['【素材】'],
  style_polish_run: ['【润色】', '【网感】', '【文案优化】', '【改标题】', '【去AI味】', '【小红书文案】', '【抖音文案】'],
}
for (const [canonicalId, labels] of labelsByCanonical.entries()) {
  if (labels.length <= 1) continue
  const allowed = allowedCanonicalAliasGroups[canonicalId]
  const actual = [...labels].sort()
  if (!allowed || actual.join('|') !== [...allowed].sort().join('|')) {
    errors.push(`${canonicalId} has unexpected folded labels: ${actual.join(', ')}`)
  }
}

const universalDeleteCapabilities = data.capabilities.filter((item) => item.rawLabel === '【删除】')
if (universalDeleteCapabilities.length !== 1) {
  errors.push(`expected exactly one 【删除】 capability; got ${universalDeleteCapabilities.length}`)
} else {
  const universalDelete = universalDeleteCapabilities[0]
  if (universalDelete.id !== 'delete') {
    errors.push(`【删除】 must use stable capability id=delete; got ${universalDelete.id}`)
  }
  if (universalDelete.type !== 'common') {
    errors.push(`【删除】 must be type=common so 首页/通用入口 renders it; got ${universalDelete.type}`)
  }
  if (universalDelete.category !== 'system') {
    errors.push(`【删除】 must be category=system; got ${universalDelete.category}`)
  }
  for (const botId of requiredUniversalDeleteBotIds) {
    if (!universalDelete.visibleBots.includes(botId)) {
      errors.push(`【删除】 must be visible to ${botId} bot`)
    }
    const availability = universalDelete.botAvailability[botId]
    if (availability !== 'primary' && availability !== 'visible') {
      errors.push(`【删除】 botAvailability.${botId} must be primary or visible; got ${availability}`)
    }
  }
  const commonEntryCapabilityIds = data.capabilities
    .filter((capability) => capability.type === 'common')
    .slice(0, 8)
    .map((capability) => capability.id)
  if (!commonEntryCapabilityIds.includes('delete')) {
    errors.push(
      `首页/通用入口 only renders the first 8 common capabilities; expected delete in ${commonEntryCapabilityIds.join(', ')}`,
    )
  }
}

const mediaSourceAsset = data.capabilities.find((item) => item.id === 'media-source-asset')
if (!mediaSourceAsset) {
  errors.push('missing media-source-asset capability')
} else {
  for (const expected of ['deconstruction', 'media-topic-decision', 'creation', 'media-shooting']) {
    if (!mediaSourceAsset.relatedCapabilityIds.includes(expected)) {
      errors.push(`media-source-asset must surface ${expected} as a related capability for SourceAsset handoff discovery`)
    }
    if (!mediaSourceAsset.displayProjection.nextActions.some((action) => action.targetCapabilityId === expected)) {
      errors.push(`media-source-asset nextActions must link to ${expected} for SourceAsset handoff discovery`)
    }
  }
  if (!mediaSourceAsset.entryTree) {
    errors.push('media-source-asset must expose entryTree projection for Collect entry navigation')
  } else {
    if (mediaSourceAsset.entryTree.root.trigger !== '【素材】') {
      errors.push(`media-source-asset entryTree root trigger must be 【素材】; got ${mediaSourceAsset.entryTree.root.trigger}`)
    }
    if (mediaSourceAsset.entryTree.root.dispatchMode !== 'smart_dispatch') {
      errors.push('media-source-asset entryTree root must use smart_dispatch')
    }
    const childTriggers = new Set(mediaSourceAsset.entryTree.children.map((item) => item.trigger))
    if (childTriggers.size > 0) {
      errors.push(`media-source-asset entryTree must not expose legacy or professional child entries; got ${[...childTriggers].join(', ')}`)
    }
  }
}

for (const capability of data.capabilities) {
  if (capability.id === 'media-source-asset') {
    const nonCanonicalAliases = (capability.aliases ?? []).filter((alias) => alias !== '素材')
    if (nonCanonicalAliases.length > 0) {
      errors.push(`media-source-asset must not expose non-canonical aliases: ${nonCanonicalAliases.join(', ')}`)
    }
  }
}

for (const capability of data.capabilities) {
  if (!capability.rawLabel.trim()) {
    errors.push(`${capability.id} has empty rawLabel`)
  }

  if (capability.llmPromptContracts.length === 0) {
    errors.push(`${capability.id} has no runtime prompt or execution contract`)
  }

  const display = capability.displayProjection
  if (display.whenToUse.length === 0 || display.requiredInputs.length === 0 || display.outputSummary.length === 0) {
    errors.push(`${capability.id} displayProjection must include operator-facing use, input, and output sections`)
  }
  for (const { path, text } of normalViewTexts(capability)) {
    if (!text.trim()) continue
    for (const term of normalViewTerms) {
      if (!term.pattern.test(text)) continue
      term.pattern.lastIndex = 0
      const snippet = text.replace(/\n/g, '\\n').slice(0, 180)
      errors.push(
        `${capability.id} normal-view field ${path} leaks internal term ${term.id}; use ${term.replacementHint}. text=${snippet}`,
      )
    }
  }
  if (capability.entryTree) {
    const treeCapabilityIds = new Set([capability.entryTree.root.capabilityId, ...capability.entryTree.children.map((entry) => entry.capabilityId)])
    for (const entry of [capability.entryTree.root, ...capability.entryTree.children]) {
      if (!capabilityIds.has(entry.capabilityId)) {
        errors.push(`${capability.id} entryTree entry=${entry.trigger} references missing capabilityId=${entry.capabilityId}`)
      }
      if (entry.inputContract.requiredFields.length === 0 || entry.inputContract.templates.length === 0) {
        errors.push(`${capability.id} entryTree entry=${entry.trigger} must expose input fields and templates`)
      }
      if (entry.outputContract.userReplySections.length === 0 || entry.outputContract.writesTo.length === 0) {
        errors.push(`${capability.id} entryTree entry=${entry.trigger} must expose output sections and writesTo`)
      }
      for (const nextCapabilityId of entry.nextCapabilityIds) {
        if (!capabilityIds.has(nextCapabilityId)) {
          errors.push(`${capability.id} entryTree entry=${entry.trigger} references missing nextCapabilityId=${nextCapabilityId}`)
        }
      }
    }
    if (treeCapabilityIds.size !== 1 + capability.entryTree.children.length) {
      errors.push(`${capability.id} entryTree contains duplicate capability references`)
    }
  }
  for (const action of display.nextActions) {
    if (action.actionType === 'open_capability') {
      if (!action.targetCapabilityId) {
        errors.push(`${capability.id} displayProjection action=${action.label} must include targetCapabilityId`)
      } else if (!capabilityIds.has(action.targetCapabilityId)) {
        errors.push(`${capability.id} displayProjection action=${action.label} references missing targetCapabilityId=${action.targetCapabilityId}`)
      }
    }
  }
  const maintainerText = display.maintainerFields.map((item) => `${item.label}:${item.value}`).join('\n')
  if (!maintainerText.includes('canonical_capability_id')) {
    errors.push(`${capability.id} displayProjection maintainerFields must expose canonical_capability_id`)
  }

  const deletionContract = capability.deletionContract
  if (!deletionContract.previewRequired || !deletionContract.confirmationRequired) {
    errors.push(`${capability.id} deletionContract must require preview and confirmation`)
  }
  if (deletionContract.targetPatterns.length === 0) {
    errors.push(`${capability.id} deletionContract has no targetPatterns`)
  }
  if (deletionContract.deletableEntities.length === 0) {
    errors.push(`${capability.id} deletionContract has no deletableEntities`)
  }
  if (deletionContract.manualEntities.length === 0) {
    errors.push(`${capability.id} deletionContract has no manualEntities`)
  }
  if (capability.rawLabel === '【删除】') {
    const text = [
      deletionContract.adapterId,
      ...deletionContract.targetPatterns,
      ...deletionContract.deletableEntities,
      capability.description,
    ].join('\n')
    for (const expected of ['历史归档', 'json', 'markdown', '转写', 'run_router']) {
      if (!text.includes(expected)) {
        errors.push(`delete capability deletionContract must include ${expected}`)
      }
    }
    if (deletionContract.adapterId === 'creation_run' || deletionContract.targetPatterns.every((item) => item.includes('run_id'))) {
      errors.push('delete capability must not be limited to creation run_id deletion')
    }
  }
  if (capability.rawLabel === '【转写】' || capability.rawLabel === '【转写-文字】') {
    if (deletionContract.adapterId !== 'transcription') {
      errors.push(`${capability.id} deletionContract must use transcription adapter`)
    }
    const text = deletionContract.deletableEntities.join('\n')
    for (const expected of ['postprocess_artifacts', 'text_transcripts']) {
      if (!text.includes(expected)) {
        errors.push(`${capability.id} deletionContract must include ${expected}`)
      }
    }
  }

  requireUnique(
    capability.llmPromptContracts.map((contract) => contract.id),
    `${capability.id} prompt contract id`,
  )

  for (const contract of capability.llmPromptContracts) {
    const body = contract.promptBody.trim()
    if (body.length < 120) {
      errors.push(`${capability.id}/${contract.id} promptBody is too short for a maintainer-visible contract`)
    }
    if (body.includes('送入 LLM 的静态提示词模板')) {
      errors.push(`${capability.id}/${contract.id} must not use generated static prompt placeholder text`)
    }
    if (body.includes('Knowledge bot AGENTS.md') || body.includes('Knowledge bot TOOLS.md') || body.includes('Knowledge bot USER.md')) {
      errors.push(`${capability.id}/${contract.id} must not display unrelated Knowledge bot global files in promptBody`)
    }
    const promptMetadata = [
      contract.title,
      contract.promptKindLabel,
      contract.fullPromptPolicy,
      ...contract.publicSummary,
    ].join('\n')
    for (const term of misleadingPromptMetadataTerms) {
      if (promptMetadata.includes(term)) {
        errors.push(`${capability.id}/${contract.id} prompt metadata uses misleading wording: ${term}`)
      }
    }
    if (!contract.appliesTo.includes(capability.rawLabel)) {
      errors.push(`${capability.id}/${contract.id} appliesTo must include ${capability.rawLabel}`)
    }
    if (!contract.componentName.trim()) {
      errors.push(`${capability.id}/${contract.id} has empty componentName`)
    }
    if (contract.sourceType === 'execution_contract') {
      if (contract.promptKind !== 'generated_execution_contract') {
        errors.push(`${capability.id}/${contract.id} execution_contract must be marked generated_execution_contract`)
      }
      if (!contract.promptKindLabel.includes('非 LLM prompt')) {
        errors.push(`${capability.id}/${contract.id} generated execution contract label must state 非 LLM prompt`)
      }
    }
    if (contract.sourceType === 'runtime_prompt' && contract.promptKind !== 'actual_llm_prompt') {
      errors.push(`${capability.id}/${contract.id} runtime_prompt must be marked actual_llm_prompt`)
    }
    if (contract.inputBoundary.length === 0) {
      errors.push(`${capability.id}/${contract.id} has empty inputBoundary`)
    }
    if (contract.outputContract.length === 0) {
      errors.push(`${capability.id}/${contract.id} has empty outputContract`)
    }
    if (contract.writesTo.length === 0) {
      errors.push(`${capability.id}/${contract.id} has empty writesTo`)
    }
  }

  const graph = capability.executionGraph
  if (!graph.id.startsWith(`${capability.id}-`)) {
    errors.push(`${capability.id} executionGraph id must start with capability id`)
  }
  if (graph.nodes.length < 3) {
    errors.push(`${capability.id} executionGraph must have at least 3 nodes`)
  }
  requireUnique(
    graph.nodes.map((node) => node.id),
    `${capability.id} execution graph node id`,
  )
  const nodeIds = new Set(graph.nodes.map((node) => node.id))
  const edgeKeys = new Set<string>()
  const outgoingEdges = new Map<string, typeof graph.edges>()
  for (const edge of graph.edges) {
    if (!nodeIds.has(edge.from)) {
      errors.push(`${capability.id} executionGraph edge references missing from=${edge.from}`)
    }
    if (!nodeIds.has(edge.to)) {
      errors.push(`${capability.id} executionGraph edge references missing to=${edge.to}`)
    }
    if (edge.from === edge.to) {
      errors.push(`${capability.id} executionGraph edge cannot reference itself: ${edge.from}`)
    }
    const edgeKey = `${edge.from}\u0000${edge.to}`
    if (edgeKeys.has(edgeKey)) {
      errors.push(`${capability.id} executionGraph has duplicate edge ${edge.from} -> ${edge.to}`)
    }
    edgeKeys.add(edgeKey)
    outgoingEdges.set(edge.from, [...(outgoingEdges.get(edge.from) ?? []), edge])
  }
  for (const [sourceId, sourceEdges] of outgoingEdges) {
    if (sourceEdges.length > 1 && sourceEdges.some((edge) => !edge.label?.trim())) {
      errors.push(`${capability.id} executionGraph branch edges from ${sourceId} must all have labels`)
    }
  }
  const promptIds = new Set(capability.llmPromptContracts.map((contract) => contract.id))
  const referencedPromptIds = new Set(
    graph.nodes
      .map((node) => node.promptContractId)
      .filter((value): value is string => Boolean(value)),
  )
  for (const node of graph.nodes) {
    if (node.nodeType === 'actual_llm_prompt') {
      if (!node.promptContractId) {
        errors.push(`${capability.id}/${node.id} actual_llm_prompt node must bind promptContractId`)
      } else if (!promptIds.has(node.promptContractId)) {
        errors.push(`${capability.id}/${node.id} references missing promptContractId=${node.promptContractId}`)
      }
    }
    if (node.promptContractId && !promptIds.has(node.promptContractId)) {
      errors.push(`${capability.id}/${node.id} references missing promptContractId=${node.promptContractId}`)
    }
    if (node.nodeType !== 'actual_llm_prompt') {
      const combined = `${node.body}\n${node.summary}`
      if (!combined.includes('不是直接') && !combined.includes('非直接') && !combined.includes('不直接')) {
        errors.push(`${capability.id}/${node.id} non-LLM execution node must state it is not directly sent to LLM`)
      }
    }
    if (node.inputBoundary.length === 0 || node.outputContract.length === 0 || node.writesTo.length === 0 || node.completionSignals.length === 0) {
      errors.push(`${capability.id}/${node.id} executionGraph node has empty contract arrays`)
    }
  }
  for (const contract of capability.llmPromptContracts) {
    if (!referencedPromptIds.has(contract.id)) {
      errors.push(`${capability.id}/${contract.id} prompt contract is not referenced by executionGraph`)
    }
  }

  if (capability.relatedCapabilityIds.length === 0) {
    errors.push(`${capability.id} has no relatedCapabilityIds`)
  }

  for (const relatedId of capability.relatedCapabilityIds) {
    if (!capabilityIds.has(relatedId)) {
      errors.push(`${capability.id} references missing relatedCapabilityId=${relatedId}`)
    }
  }

  for (const flowStageId of capability.flowStageIds) {
    if (!flowStageIds.has(flowStageId)) {
      errors.push(`${capability.id} references missing flowStageId=${flowStageId}`)
    }
  }

  if (['knowledge', 'system'].includes(capability.category)) {
    const badStages = capability.flowStageIds.filter((flowStageId) => contentProductionStageIds.has(flowStageId))
    if (badStages.length > 0) {
      errors.push(`${capability.id} must not use content production flow stages: ${badStages.join(', ')}`)
    }
  }

  for (const botId of capability.visibleBots) {
    if (!botIds.has(botId)) {
      errors.push(`${capability.id} uses unknown visibleBot=${botId}`)
    }
  }
}

const graphRules: Array<{
  capabilityId?: string
  rawLabel?: string
  mustIncludeTypes: string[]
  mustIncludeNodeIds?: string[]
}> = [
  {
    capabilityId: 'deconstruction',
    mustIncludeTypes: ['entry', 'input_parse', 'data_fetch', 'vision_read', 'actual_llm_prompt', 'document_render', 'bitable_write', 'quality_check', 'reply'],
    mustIncludeNodeIds: ['download-evidence', 'vision-read', 'write-source-assets', 'write-material-deconstructions'],
  },
  {
    capabilityId: 'transcription',
    mustIncludeTypes: ['entry', 'input_parse', 'data_fetch', 'storage_write', 'actual_llm_prompt', 'document_render', 'quality_check', 'reply'],
    mustIncludeNodeIds: [
      'transcribe-source',
      'transcription-intake-mode',
      'transcription-knowledge-auto-enqueue',
      'transcription-knowledge-idempotent-replay',
      'transcription-daily-confirmed-batch',
      'transcription-daily-await-confirmation',
      'transcription-final-output',
    ],
  },
  {
    rawLabel: '【删除】',
    mustIncludeTypes: ['entry', 'input_parse', 'data_fetch', 'generated_execution_contract', 'supporting_contract', 'quality_check', 'storage_write', 'reply'],
    mustIncludeNodeIds: ['delete-target-resolution', 'delete-preview-plan', 'delete-confirmation-gate', 'delete-execution-boundary'],
  },
  {
    capabilityId: 'commercial-delivery-draft',
    mustIncludeTypes: ['entry', 'input_parse', 'actual_llm_prompt', 'document_render', 'quality_check', 'bitable_write', 'reply'],
    mustIncludeNodeIds: ['commercial-doc-render', 'commercial-public-permission', 'commercial-native-table-readback', 'commercial-delivery-bitable-write'],
  },
]

for (const rule of graphRules) {
  const capability = data.capabilities.find((item) => (
    rule.capabilityId ? item.id === rule.capabilityId : item.rawLabel === rule.rawLabel
  ))
  const ruleName = rule.capabilityId ?? rule.rawLabel
  if (!capability) {
    errors.push(`execution graph rule references missing capability=${ruleName}`)
    continue
  }
  const types = new Set(capability.executionGraph.nodes.map((node) => node.nodeType))
  for (const type of rule.mustIncludeTypes) {
    if (!types.has(type as (typeof capability.executionGraph.nodes)[number]['nodeType'])) {
      errors.push(`${capability.id} executionGraph must include nodeType=${type}`)
    }
  }
  const ids = new Set(capability.executionGraph.nodes.map((node) => node.id))
  for (const nodeId of rule.mustIncludeNodeIds ?? []) {
    if (!ids.has(nodeId)) {
      errors.push(`${capability.id} executionGraph must include node id=${nodeId}`)
    }
  }
}

const transcriptionCapability = data.capabilities.find((item) => item.id === 'transcription')
if (!transcriptionCapability) {
  errors.push('transcription capability is missing')
} else {
  const contractText = JSON.stringify({
    description: transcriptionCapability.description,
    outputDetail: transcriptionCapability.outputDetail,
    displayProjection: transcriptionCapability.displayProjection,
    executionGraph: transcriptionCapability.executionGraph,
  })
  const requiredContractTerms = [
    'Knowledge Bot',
    '裸音频',
    '无需二次确认',
    'Daily Bot',
    '批次确认',
    'message ID',
    'MediaPath',
    'enqueue_order',
    'FIFO',
    '5 细节保全附录（受限）',
    '6 关联文档',
    '任何有业务含义的敏感细节都不能删除、泛化或省略',
    '可见范围、核验状态和公开权限',
  ]
  for (const term of requiredContractTerms) {
    if (!contractText.includes(term)) {
      errors.push(`transcription capability contract must include ${term}`)
    }
  }
}

const transcriptionTextCapability = data.capabilities.find((item) => item.id === 'transcription-text')
if (!transcriptionTextCapability) {
  errors.push('transcription-text capability is missing')
} else {
  const contractText = JSON.stringify({
    description: transcriptionTextCapability.description,
    outputDetail: transcriptionTextCapability.outputDetail,
    executionGraph: transcriptionTextCapability.executionGraph,
  })
  for (const term of ['细节保全附录（受限）', '任何有业务含义的敏感细节都不能删除、泛化或省略', '可见范围、核验状态和公开权限']) {
    if (!contractText.includes(term)) {
      errors.push(`transcription-text capability contract must include ${term}`)
    }
  }
}

const promptContractByCapability: Record<string, { mustInclude?: string[]; mustNotInclude?: string[] }> = {
  'creation-xiaohongshu': {
    mustInclude: ['creation-main-editor'],
  },
  'complete-knowledge': {
    mustInclude: ['complete-knowledge-weekly-cognition-completion'],
  },
  cognition: {
    mustInclude: ['cognition-weekly-cognition-deposit'],
    mustNotInclude: ['data-review-analysis'],
  },
  'data-review': {
    mustInclude: ['data-review-analysis'],
  },
  transcription: {
    mustInclude: ['transcription-chunk-fact-extraction', 'transcription-global-note', 'transcription-consistency-revision'],
  },
  'transcription-text': {
    mustInclude: ['transcription-chunk-fact-extraction', 'transcription-global-note', 'transcription-consistency-revision'],
  },
  'selfmedia-cognition': {
    mustNotInclude: ['data-review-analysis'],
  },
  'commercial-delivery-draft': {
    mustInclude: ['commercial-delivery-draft-generation'],
  },
  retrospective: {
    mustNotInclude: ['data-review-analysis'],
  },
}

for (const [capabilityId, contract] of Object.entries(promptContractByCapability)) {
  const capability = data.capabilities.find((item) => item.id === capabilityId)
  if (!capability) {
    errors.push(`prompt contract rule references missing capability=${capabilityId}`)
    continue
  }
  const promptIds = capability.llmPromptContracts.map((item) => item.id)
  for (const expected of contract.mustInclude ?? []) {
    if (!promptIds.includes(expected)) {
      errors.push(`${capabilityId} prompt contracts must include ${expected}; got ${promptIds.join(', ') || '<none>'}`)
    }
  }
  for (const forbidden of contract.mustNotInclude ?? []) {
    if (promptIds.includes(forbidden)) {
      errors.push(`${capabilityId} prompt contracts must not include ${forbidden}`)
    }
  }
}

const cognition = data.capabilities.find((item) => item.id === 'cognition')
if (!cognition) {
  errors.push('cognition capability is missing')
} else {
  const cognitionPrompt = cognition.llmPromptContracts.find(
    (contract) => contract.id === 'cognition-weekly-cognition-deposit',
  )
  for (const expected of [
    '核心认知 / 可复用场景 / 行动提醒 / 反例边界',
    '沉淀文本',
    '处理说明',
  ]) {
    if (!cognition.outputDetail.contentForms.includes(expected)) {
      errors.push(`cognition contentForms must include ${expected}`)
    }
  }
  if (!cognitionPrompt) {
    errors.push('cognition must expose the weekly cognition deposit prompt')
  } else {
    const sourcePrompt = knowledgeCapabilityPromptBody('认知')
    if (sourcePrompt && cognitionPrompt.promptBody !== sourcePrompt) {
      errors.push('cognition promptBody must exactly match the Knowledge bot 【认知】 capability prompt body')
    }
    for (const expected of [
      '当消息以【认知】开头时，只执行“周记认知沉淀”。',
      '目标不是写鸡汤，也不是扩写成文章',
      '* 核心认知：',
      '* 可复用场景：',
      '* 行动提醒：',
      '* 反例 / 边界条件：',
      '如果缺少正文，直接返回“缺少待沉淀内容”。',
      '默认不写入飞书知识表。',
      '不处理原始音频/视频 ASR。',
      '如果无法确认日期范围或目标周记文件，只返回整理后的内容，不假设路径。',
    ]) {
      if (!cognitionPrompt.promptBody.includes(expected)) {
        errors.push(`cognition promptBody must include ${expected}`)
      }
    }
  }
}

const completeKnowledge = data.capabilities.find((item) => item.id === 'complete-knowledge')
if (!completeKnowledge) {
  errors.push('complete-knowledge capability is missing')
} else {
  const completePrompt = completeKnowledge.llmPromptContracts.find(
    (contract) => contract.id === 'complete-knowledge-weekly-cognition-completion',
  )
  if (!completePrompt) {
    errors.push('complete-knowledge must expose the weekly cognition completion prompt')
  } else {
    const sourcePrompt = knowledgeCapabilityPromptBody('补全')
    if (sourcePrompt && completePrompt.promptBody !== sourcePrompt) {
      errors.push('complete-knowledge promptBody must exactly match the Knowledge bot 【补全】 capability prompt body')
    }
    for (const expected of [
      '当消息以【补全】开头时，只执行“周记认知补全”。',
      '目标不是重写成报告',
      '如果缺少正文，直接返回“缺少待补全文字”。',
      '默认不写入飞书知识表。',
      '如果无法确认日期范围或目标周记文件，只返回整理后的内容，不假设路径。',
    ]) {
      if (!completePrompt.promptBody.includes(expected)) {
        errors.push(`complete-knowledge promptBody must include ${expected}`)
      }
    }
  }
}

for (const flow of data.flows) {
  requireUnique(
    flow.stages.map((stage) => stage.id),
    `${flow.id} stage id`,
  )
  for (const stage of flow.stages) {
    for (const capabilityId of stage.relatedCapabilityIds) {
      if (!capabilityIds.has(capabilityId)) {
        errors.push(`${flow.id}/${stage.id} references missing relatedCapabilityId=${capabilityId}`)
      }
    }
  }
}

for (const capability of data.capabilities) {
  for (const relatedId of capability.relatedCapabilityIds) {
    const related = data.capabilities.find((item) => item.id === relatedId)
    if (!related) continue
    if (!related.relatedCapabilityIds.includes(capability.id)) {
      errors.push(`${capability.id} relatedCapabilityId=${relatedId} is not bidirectional`)
    }
  }
}

for (const bot of data.bots) {
  for (const featuredId of bot.featuredCapabilityIds) {
    if (!capabilityIds.has(featuredId)) {
      errors.push(`${bot.id} references missing featuredCapabilityId=${featuredId}`)
    }
  }
}

const socialBot = data.bots.find((item) => item.id === 'social')
if (socialBot?.featuredCapabilityIds.includes('creator-profile-upsert')) {
  errors.push('social bot must feature creator-profile only; creator-profile-upsert belongs under 【博主】 input options')
}

for (const task of data.tasks) {
  for (const capabilityId of task.recommendedCapabilityIds) {
    if (!capabilityIds.has(capabilityId)) {
      errors.push(`${task.id} references missing recommendedCapabilityId=${capabilityId}`)
    }
  }
}

const socialTask = data.tasks.find((item) => item.id === 'social')
if (socialTask?.recommendedCapabilityIds.includes('creator-profile-upsert')) {
  errors.push('social task must recommend creator-profile only; creator-profile-upsert belongs under 【博主】 input options')
}

const knowledgeBot = data.bots.find((item) => item.id === 'knowledge')
if (!knowledgeBot?.featuredCapabilityIds.includes('cognition')) {
  errors.push('knowledge bot featuredCapabilityIds must include cognition')
}
const knowledgeTask = data.tasks.find((item) => item.id === 'knowledge')
if (!knowledgeTask?.recommendedCapabilityIds.includes('cognition')) {
  errors.push('knowledge task recommendedCapabilityIds must include cognition')
}

const flowStageContract: Record<string, { mustInclude?: string[]; mustNotInclude?: string[] }> = {
  archive: {
    mustInclude: ['knowledge-weekly-archive'],
    mustNotInclude: ['mac-intake', 'mac-material-analysis', 'publish-archive'],
  },
  'complete-knowledge': {
    mustInclude: ['knowledge-weekly-archive'],
    mustNotInclude: ['mac-intake', 'mac-material-analysis'],
  },
  cognition: {
    mustInclude: ['knowledge-weekly-archive'],
    mustNotInclude: ['mac-intake', 'mac-material-analysis'],
  },
  learning: {
    mustInclude: ['knowledge-weekly-archive'],
    mustNotInclude: ['mac-intake', 'mac-material-analysis'],
  },
  'learning-organize': {
    mustInclude: ['knowledge-weekly-archive'],
    mustNotInclude: ['mac-intake', 'mac-material-analysis'],
  },
  research: {
    mustInclude: ['media-growth-research'],
    mustNotInclude: ['mac-material-analysis'],
  },
  'selfmedia-knowledge': {
    mustInclude: ['knowledge-source-capture'],
    mustNotInclude: ['mac-material-analysis'],
  },
  transcription: {
    mustInclude: ['knowledge-source-capture'],
    mustNotInclude: ['mac-material-analysis'],
  },
  'transcription-text': {
    mustInclude: ['knowledge-source-capture'],
    mustNotInclude: ['mac-material-analysis'],
  },
  'commercial-delivery-draft': {
    mustInclude: ['cloud-project-package'],
    mustNotInclude: ['mac-material-analysis', 'knowledge-source-capture', 'publish-archive'],
  },
  'document-edit': {
    mustInclude: ['system-document-actions'],
    mustNotInclude: ['local-binding-gate', 'mac-intake'],
  },
  organize: {
    mustInclude: ['system-document-actions'],
    mustNotInclude: ['mac-intake'],
  },
  help: {
    mustInclude: ['system-document-actions'],
    mustNotInclude: ['local-binding-gate'],
  },
  recent: {
    mustInclude: ['system-document-actions'],
    mustNotInclude: ['publish-archive'],
  },
  sync: {
    mustInclude: ['system-document-actions'],
    mustNotInclude: ['local-binding-gate', 'publish-archive'],
  },
  status: {
    mustInclude: ['system-document-actions'],
    mustNotInclude: ['local-binding-gate', 'publish-archive'],
  },
}

for (const [capabilityId, contract] of Object.entries(flowStageContract)) {
  const capability = data.capabilities.find((item) => item.id === capabilityId)
  if (!capability) {
    errors.push(`flow stage contract references missing capability=${capabilityId}`)
    continue
  }
  for (const expected of contract.mustInclude ?? []) {
    if (!capability.flowStageIds.includes(expected)) {
      errors.push(`${capabilityId} flowStageIds must include ${expected}; got ${capability.flowStageIds.join(', ') || '<none>'}`)
    }
  }
  for (const forbidden of contract.mustNotInclude ?? []) {
    if (capability.flowStageIds.includes(forbidden)) {
      errors.push(`${capabilityId} flowStageIds must not include ${forbidden}`)
    }
  }
}

const destinationContract: Record<string, { mustInclude?: string[]; mustNotInclude?: string[] }> = {
  activity: {
    mustInclude: ['01_近期活动'],
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  'data-review': {
    mustInclude: ['04_PostReviews_发布复盘', 'H01_MetricSnapshot_作品指标快照'],
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  'commercial-delivery-draft': {
    mustInclude: ['COM01_CommercialDelivery_商单交付', 'Feishu Docx 子页面（互联网所有人可编辑）'],
    mustNotInclude: ['03_CreationRuns_创作运行', '05B_BusinessOpportunities_商务机会'],
  },
  'media-source-asset': {
    mustInclude: ['media_vault/source_assets'],
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  deconstruction: {
    mustInclude: ['02B_MaterialDeconstructions_素材拆解'],
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  'creation-consultation': {
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  'creation-check': {
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  'work-acceptance': {
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  'document-edit': {
    mustNotInclude: ['03_CreationRuns_创作运行'],
  },
  transcription: {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  'transcription-text': {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  'selfmedia-knowledge': {
    mustInclude: ['OpenClaw 自媒体知识'],
  },
  archive: {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  'complete-knowledge': {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  cognition: {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  learning: {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  'learning-organize': {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
  research: {
    mustNotInclude: ['OpenClaw 自媒体知识'],
  },
}

for (const [capabilityId, contract] of Object.entries(destinationContract)) {
  const capability = data.capabilities.find((item) => item.id === capabilityId)
  if (!capability) {
    errors.push(`destination contract references missing capability=${capabilityId}`)
    continue
  }
  const labels = capability.outputDetail.destinationLinks.map((item) => item.label)
  for (const expected of contract.mustInclude ?? []) {
    if (!labels.includes(expected)) {
      errors.push(`${capabilityId} destinationLinks must include ${expected}; got ${labels.join(', ') || '<none>'}`)
    }
  }
  for (const forbidden of contract.mustNotInclude ?? []) {
    if (labels.includes(forbidden)) {
      errors.push(`${capabilityId} destinationLinks must not include ${forbidden}`)
    }
  }
}

const outputDetailContract: Record<
  string,
  {
    titleMustInclude?: string[]
    descriptionMustInclude?: string[]
    contentFormsMustInclude?: string[]
    contentFormsMustNotInclude?: string[]
    destinationsMustInclude?: string[]
    destinationsMustNotInclude?: string[]
    boundariesMustInclude?: string[]
  }
> = {
  archive: {
    titleMustInclude: ['Obsidian'],
    descriptionMustInclude: ['周记', '默认不写飞书知识表'],
    contentFormsMustInclude: ['周记知识条目', '逻辑检查摘要'],
    destinationsMustInclude: ['Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 知识 小节'],
    destinationsMustNotInclude: ['Knowledge bot 知识归档', '飞书知识表'],
    boundariesMustInclude: ['默认不写飞书知识表'],
  },
  'commercial-delivery-draft': {
    contentFormsMustInclude: ['商单交付初稿', '完整可直接发布正文', '飞书云文档子页面', '图片脚本 / 分镜脚本原生表格', '多维表交付摘要'],
    destinationsMustInclude: ['Feishu Docx 子页面（互联网所有人可编辑）', '业务对象名称', '作品初稿链接、初稿时间、发布时间等摘要字段'],
    destinationsMustNotInclude: ['03_CreationRuns_创作运行', '05B_BusinessOpportunities_商务机会'],
    boundariesMustInclude: ['完整可直接发布正文', '互联网所有人可编辑', '飞书原生表格', '不写入 创作记录索引', '05B 商务机会表'],
  },
  'complete-knowledge': {
    titleMustInclude: ['Obsidian'],
    descriptionMustInclude: ['# 认知'],
    destinationsMustInclude: ['Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节'],
    destinationsMustNotInclude: ['Knowledge bot 知识归档', '飞书知识表'],
    boundariesMustInclude: ['默认不写飞书知识表'],
  },
  cognition: {
    titleMustInclude: ['Obsidian'],
    descriptionMustInclude: ['# 认知'],
    contentFormsMustInclude: ['周记认知条目'],
    destinationsMustInclude: ['Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节'],
    destinationsMustNotInclude: ['Knowledge bot 知识归档', '飞书知识表'],
    boundariesMustInclude: ['默认不写飞书知识表'],
  },
  learning: {
    descriptionMustInclude: ['Obsidian 学习/每日学习', '# 知识'],
    destinationsMustInclude: ['Obsidian 学习/每日学习', 'Obsidian 周记 # 知识 小节'],
    destinationsMustNotInclude: ['飞书知识表'],
  },
  'learning-organize': {
    descriptionMustInclude: ['Obsidian 学习/每日学习', '# 知识'],
    destinationsMustInclude: ['Obsidian 学习/每日学习', 'Obsidian 周记 # 知识 小节'],
    destinationsMustNotInclude: ['飞书知识表'],
  },
  research: {
    descriptionMustInclude: ['ExternalResearchBrief', 'pending_manual'],
    contentFormsMustInclude: ['ExternalResearchBrief', '证据摘要', '内容机会'],
    destinationsMustInclude: ['本地证据库/research_briefs'],
    destinationsMustNotInclude: ['Knowledge bot 知识归档', '飞书知识表'],
    boundariesMustInclude: ['不委托 Knowledge 深度研究'],
  },
  'document-edit': {
    contentFormsMustInclude: ['同一文档的分块文本 patch', '保护块和人工项', '读回校验证据'],
    contentFormsMustNotInclude: ['定向修改后的完整文档'],
    destinationsMustInclude: ['被回复或正文指定的同一个飞书文档'],
    destinationsMustNotInclude: ['必要时更新对应系统记录'],
    boundariesMustInclude: ['必须有明确目标文档'],
  },
  organize: {
    contentFormsMustInclude: ['最近记录摘要'],
    contentFormsMustNotInclude: ['能力说明', '状态或同步提示'],
    destinationsMustInclude: ['本地整理输出归档'],
    destinationsMustNotInclude: ['飞书多维表格'],
  },
  help: {
    contentFormsMustInclude: ['当前 Bot 能力说明', '标签索引'],
    destinationsMustInclude: ['当前 Bot 回复', '能力说明文档链接'],
    boundariesMustInclude: ['只返回说明'],
  },
  recent: {
    contentFormsMustInclude: ['最近记录摘要'],
    destinationsMustInclude: ['当前 Bot 回复', '本地归档读取结果'],
    boundariesMustInclude: ['只读本地归档'],
  },
  sync: {
    contentFormsMustInclude: ['同步候选摘要', '成功/失败结果'],
    destinationsMustInclude: ['目标系统由原记录规则决定', '当前 Bot 回复'],
    boundariesMustInclude: ['只补同步已有未同步记录'],
  },
  status: {
    contentFormsMustInclude: ['任务状态', '最近任务匹配结果'],
    destinationsMustInclude: ['当前 Bot 回复'],
    destinationsMustNotInclude: ['本地路径'],
    boundariesMustInclude: ['只读归档 frontmatter'],
  },
}

type OutputDetailContract = (typeof outputDetailContract)[string]

function checkOutputDetailContract(capabilityId: string, contract: OutputDetailContract, capability = data.capabilities.find((item) => item.id === capabilityId)) {
  if (!capability) {
    errors.push(`output detail contract references missing capability=${capabilityId}`)
    return
  }
  for (const expected of contract.titleMustInclude ?? []) {
    if (!capability.title.includes(expected)) {
      errors.push(`${capability.id} title must include ${expected}; got ${capability.title}`)
    }
  }
  for (const expected of contract.descriptionMustInclude ?? []) {
    if (!capability.description.includes(expected)) {
      errors.push(`${capability.id} description must include ${expected}; got ${capability.description}`)
    }
  }
  const contentForms = capability.outputDetail.contentForms
  for (const expected of contract.contentFormsMustInclude ?? []) {
    if (!contentForms.includes(expected)) {
      errors.push(`${capability.id} contentForms must include ${expected}; got ${contentForms.join(', ') || '<none>'}`)
    }
  }
  for (const forbidden of contract.contentFormsMustNotInclude ?? []) {
    if (contentForms.includes(forbidden)) {
      errors.push(`${capability.id} contentForms must not include ${forbidden}`)
    }
  }
  const destinations = capability.outputDetail.destinations
  for (const expected of contract.destinationsMustInclude ?? []) {
    if (!destinations.includes(expected)) {
      errors.push(`${capability.id} destinations must include ${expected}; got ${destinations.join(', ') || '<none>'}`)
    }
  }
  for (const forbidden of contract.destinationsMustNotInclude ?? []) {
    if (destinations.some((destination) => destination.includes(forbidden))) {
      errors.push(`${capability.id} destinations must not include ${forbidden}`)
    }
  }
  const boundaries = capability.outputDetail.boundaries
  for (const expected of contract.boundariesMustInclude ?? []) {
    if (!boundaries.some((boundary) => boundary.includes(expected))) {
      errors.push(`${capability.id} boundaries must include ${expected}; got ${boundaries.join(', ') || '<none>'}`)
    }
  }
}

for (const [capabilityId, contract] of Object.entries(outputDetailContract)) {
  checkOutputDetailContract(capabilityId, contract)
}

const outputDetailContractByLabel: Record<string, OutputDetailContract> = {
  '【修改】': {
    contentFormsMustInclude: ['同一文档的分块文本 patch', '保护块和人工项', '读回校验证据'],
    contentFormsMustNotInclude: ['能力说明', '状态或同步提示', '定向修改后的完整文档'],
  },
  '【删除】': {
    contentFormsMustInclude: ['删除预览或执行结果'],
    contentFormsMustNotInclude: ['创作建议', '初稿'],
    destinationsMustInclude: ['workspace archive/inbox、转写中间产物、创作记录索引 及关联文档/文件'],
  },
  '【复盘】': {
    contentFormsMustInclude: ['复盘结论'],
    contentFormsMustNotInclude: ['能力说明', '状态或同步提示'],
  },
  '【商单交付】': {
    contentFormsMustInclude: ['商单交付初稿', '完整可直接发布正文', '图片脚本 / 分镜脚本原生表格'],
    destinationsMustInclude: ['业务对象名称'],
    destinationsMustNotInclude: ['03_CreationRuns_创作运行', '05B_BusinessOpportunities_商务机会'],
  },
  '【认知】': {
    contentFormsMustInclude: ['周记认知条目'],
    destinationsMustInclude: ['Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节'],
    destinationsMustNotInclude: ['飞书知识表'],
  },
  '【说明】': {
    contentFormsMustInclude: ['当前 Bot 能力说明'],
    contentFormsMustNotInclude: ['状态或同步提示'],
  },
  '【最近】': {
    contentFormsMustInclude: ['最近记录摘要'],
    contentFormsMustNotInclude: ['能力说明', '状态或同步提示'],
  },
  '【同步】': {
    contentFormsMustInclude: ['同步候选摘要'],
    contentFormsMustNotInclude: ['能力说明', '状态或同步提示'],
  },
  '【状态】': {
    contentFormsMustInclude: ['任务状态'],
    contentFormsMustNotInclude: ['能力说明', '状态或同步提示'],
  },
}

for (const [rawLabel, contract] of Object.entries(outputDetailContractByLabel)) {
  const capability = data.capabilities.find((item) => item.rawLabel === rawLabel)
  if (!capability) {
    errors.push(`output detail contract references missing rawLabel=${rawLabel}`)
    continue
  }
  checkOutputDetailContract(rawLabel, contract, capability)
}

const commercialDeliveryCapability = data.capabilities.find((item) => item.id === 'commercial-delivery-draft')
if (!commercialDeliveryCapability) {
  errors.push('commercial-delivery-draft capability is missing')
} else {
  const requiredCommercialFields = ['创作方向', '产品卖点', 'Tags']
  const optionalCommercialFields = ['平台要求/禁区', '博主人设/语气', 'PR备注']
  const commercialTemplateText = [
    commercialDeliveryCapability.defaultInputTemplate,
    ...commercialDeliveryCapability.quickCopyTemplates.map((template) => template.body),
    commercialDeliveryCapability.displayProjection.examplePrompt,
  ].join('\n')

  for (const expected of requiredCommercialFields) {
    if (!commercialDeliveryCapability.commonInputs.some((input) => input.includes(expected))) {
      errors.push(`commercial-delivery-draft commonInputs must include required field ${expected}`)
    }
    if (!commercialDeliveryCapability.displayProjection.requiredInputs.includes(expected)) {
      errors.push(`commercial-delivery-draft display requiredInputs must include ${expected}`)
    }
    if (commercialDeliveryCapability.displayProjection.optionalInputs.includes(expected)) {
      errors.push(`commercial-delivery-draft display optionalInputs must not include required field ${expected}`)
    }
    if (!commercialTemplateText.includes(`${expected}：`)) {
      errors.push(`commercial-delivery-draft templates must include required field line ${expected}：`)
    }
  }

  for (const optional of optionalCommercialFields) {
    if (!commercialDeliveryCapability.displayProjection.optionalInputs.includes(optional)) {
      errors.push(`commercial-delivery-draft display optionalInputs must include ${optional}`)
    }
    if (commercialDeliveryCapability.displayProjection.requiredInputs.some((field) => field.includes(optional))) {
      errors.push(`commercial-delivery-draft display requiredInputs must not include optional field ${optional}`)
    }
    if (commercialTemplateText.includes(`${optional}：`)) {
      errors.push(`commercial-delivery-draft copy templates must omit optional field ${optional} until the user provides it`)
    }
  }

  const commercialEntryNodes = data.capabilities.flatMap((capability) => {
    if (!capability.entryTree) {
      return []
    }
    return [capability.entryTree.root, ...capability.entryTree.children].filter((entry) => entry.capabilityId === 'commercial-delivery-draft')
  })
  for (const entry of commercialEntryNodes) {
    for (const expected of requiredCommercialFields) {
      if (!entry.inputContract.requiredFields.includes(expected)) {
        errors.push(`commercial-delivery-draft entry inputContract.requiredFields must include ${expected}`)
      }
      if (entry.inputContract.optionalFields.includes(expected)) {
        errors.push(`commercial-delivery-draft entry inputContract.optionalFields must not include required field ${expected}`)
      }
    }
    for (const optional of optionalCommercialFields) {
      if (!entry.inputContract.optionalFields.includes(optional)) {
        errors.push(`commercial-delivery-draft entry inputContract.optionalFields must include ${optional}`)
      }
      if (entry.inputContract.requiredFields.some((field) => field.includes(optional))) {
        errors.push(`commercial-delivery-draft entry inputContract.requiredFields must not include optional field ${optional}`)
      }
    }
  }

  const commercialPromptContractsText = JSON.stringify(commercialDeliveryCapability.llmPromptContracts)
  if (commercialDeliveryCapability.displayProjection.requiredInputs.some((field) => field.includes('出稿时间'))) {
    errors.push('commercial-delivery-draft display requiredInputs must use 初稿时间, not 出稿时间')
  }
  if (!commercialDeliveryCapability.displayProjection.requiredInputs.includes('初稿时间')) {
    errors.push('commercial-delivery-draft display requiredInputs must include 初稿时间')
  }
  if (commercialTemplateText.includes('出稿时间：')) {
    errors.push('commercial-delivery-draft templates must use 初稿时间, not 出稿时间')
  }
  if (!commercialTemplateText.includes('初稿时间：')) {
    errors.push('commercial-delivery-draft templates must include 初稿时间：')
  }
  if (commercialTemplateText.includes('PR备注：')) {
    errors.push('commercial-delivery-draft templates must not expose unmarked PR备注 as required')
  }

  for (const expected of ['必填输入：创作方向、产品卖点、Tags。', '选填输入：PR备注、平台要求 / 禁区、博主人设 / 语气；PR备注和平台要求 / 禁区未填默认无特殊要求。']) {
    if (!commercialPromptContractsText.includes(expected)) {
      errors.push(`commercial-delivery-draft prompt contracts must include boundary: ${expected}`)
    }
  }
  if (!JSON.stringify(commercialDeliveryCapability).includes('完整可直接发布正文')) {
    errors.push('commercial-delivery-draft detail must state complete publish-ready copy contract')
  }

  const commercialUrls = commercialDeliveryCapability.outputDetail.destinationLinks.map((link) => link.url)
  if (commercialUrls.length === 0) {
    errors.push('commercial-delivery-draft destinationLinks must include Feishu target URLs')
  }
  for (const url of commercialUrls) {
    if (!url.includes(commercialDeliveryTargetToken)) {
      errors.push(`commercial-delivery-draft destination URL must point to ${commercialDeliveryTargetToken}; got ${url}`)
    }
    if (url.includes(commercialDeliveryOldToken)) {
      errors.push(`commercial-delivery-draft destination URL must not point to old token ${commercialDeliveryOldToken}`)
    }
  }

  const commercialCapabilityJson = JSON.stringify(commercialDeliveryCapability)
  for (const forbidden of [commercialDeliveryOldToken, 'fallback', 'compat', '兼容']) {
    if (commercialCapabilityJson.toLowerCase().includes(forbidden.toLowerCase())) {
      errors.push(`commercial-delivery-draft must not contain forbidden old-path marker: ${forbidden}`)
    }
  }
}

if (raw.includes(commercialDeliveryOldToken)) {
  errors.push(`public JSON must not contain old commercial delivery token ${commercialDeliveryOldToken}`)
}

for (const capability of data.capabilities) {
  const forms = capability.outputDetail.contentForms
  if (forms.length === 3 && forms[0] === '能力说明' && forms[1] === '查询结果' && forms[2] === '状态或同步提示') {
    errors.push(`${capability.id} still uses generic system contentForms`)
  }
  if (capability.suitableFor.includes('需要按该能力说明处理对应材料时使用。')) {
    errors.push(`${capability.id} still uses generic suitableFor copy`)
  }
  if (capability.suitableFor.includes('需要查看能力说明、最近记录、同步状态或系统辅助入口时使用。')) {
    errors.push(`${capability.id} still uses overloaded system suitableFor copy`)
  }
}

const sensitivePatterns = [
  /\btoken\b/i,
  /\bsecret\b/i,
  /\bcookie\b/i,
  /\bapp[_ -]?key\b/i,
  /\bauthorization\b/i,
  /\/home\/ubuntu\//i,
  /\/Users\//i,
]

for (const pattern of sensitivePatterns) {
  if (pattern.test(raw)) {
    errors.push(`public JSON contains sensitive-looking text: ${pattern}`)
  }
}

if (errors.length > 0) {
  console.error(errors.map((error) => `- ${error}`).join('\n'))
  process.exit(1)
}

console.log(`Validated ${data.capabilities.length} capabilities from ${data.meta.source}`)
