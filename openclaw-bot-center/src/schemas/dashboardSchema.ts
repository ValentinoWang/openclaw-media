import { z } from 'zod'

export const botIdSchema = z.enum(['media', 'daily', 'knowledge', 'social', 'deepmath'])
export const capabilityTypeSchema = z.enum(['main', 'collaboration', 'common', 'boundary'])
export const categorySchema = z.enum([
  'creation',
  'material',
  'review',
  'daily',
  'wardrobe',
  'development',
  'knowledge',
  'research',
  'social',
  'business',
  'entity',
  'system',
])
export const availabilitySchema = z.enum(['primary', 'visible', 'not_recommended', 'hidden'])
export const sensitivitySchema = z.enum(['public_description_only', 'maintainer_only', 'hidden'])
export const linkGroupSchema = z.enum([
  'bot_entry',
  'capability_doc',
  'collaboration_doc',
  'maintainer_doc',
])
export const linkVisibilitySchema = z.enum(['normal', 'maintainer'])
export const linkStatusSchema = z.enum(['active', 'disabled', 'unknown'])
export const linkSensitivitySchema = z.enum(['public', 'internal'])
export const promptSourceTypeSchema = z.enum([
  'runtime_prompt',
  'renderer_contract',
  'quality_contract',
  'prompt_doc',
  'execution_contract',
])
export const promptKindSchema = z.enum([
  'actual_llm_prompt',
  'generated_execution_contract',
  'supporting_contract',
])
export const promptExposureSchema = z.enum(['summary_only', 'requires_auth'])
export const validationProfileSchema = z.enum(['strict_structured', 'bounded_open'])
export const flowOwnerSchema = z.enum(['cloud', 'mac', 'human', 'mixed', 'storage'])
export const executionGraphKindSchema = z.enum(['manual', 'generated_from_prompts', 'generated_contract'])
export const deletionCoverageSchema = z.enum(['automatic', 'partial', 'manual_required'])
export const entryRoleSchema = z.enum(['root_entry', 'direct_entry', 'intent_entry', 'legacy_entry'])
export const dispatchModeSchema = z.enum(['smart_dispatch', 'direct'])
export const displayArchetypeSchema = z.enum([
  'Entry Hub',
  'Direct Action',
  'Gate/Review',
  'Creation Handoff',
  'Entity Store',
  'System/Maintenance',
])
export const executionGraphNodeTypeSchema = z.enum([
  'entry',
  'input_parse',
  'data_fetch',
  'vision_read',
  'actual_llm_prompt',
  'document_render',
  'bitable_write',
  'storage_write',
  'quality_check',
  'reply',
  'supporting_contract',
  'generated_execution_contract',
])

export const implementationStatusSchema = z.enum(['implemented', 'not_implemented', 'external'])

export const botHelpProjectionSchema = z.object({
  title: z.string().min(1),
  summary: z.string().min(1),
  statusSourceCapabilityId: z.string().min(1),
  implementationStatus: implementationStatusSchema,
  current: z.array(z.string().min(1)),
  notYet: z.array(z.string().min(1)),
  frozenTarget: z.array(z.string().min(1)),
})

export const botSchema = z.object({
  id: botIdSchema,
  name: z.string().min(1),
  title: z.string().min(1),
  description: z.string().min(1),
  primaryTaskGroups: z.array(z.string().min(1)),
  featuredCapabilityIds: z.array(z.string().min(1)),
  helpProjection: botHelpProjectionSchema.optional(),
  entryLinks: z.array(
    z.object({
      label: z.string().min(1),
      url: z.string().min(1),
      status: linkStatusSchema,
    }),
  ),
})

export const llmPromptContractSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  sourceType: promptSourceTypeSchema,
  source: z.string().min(1),
  promptKind: promptKindSchema,
  promptKindLabel: z.string().min(1),
  componentName: z.string().min(1),
  appliesTo: z.array(z.string().min(1)),
  purpose: z.string().min(1),
  promptBody: z.string().min(1),
  inputBoundary: z.array(z.string().min(1)),
  outputContract: z.array(z.string().min(1)),
  writesTo: z.array(z.string().min(1)),
  publicSummary: z.array(z.string().min(1)),
  fullPromptPolicy: z.string().min(1),
  exposure: promptExposureSchema,
  postValidation: z.object({
    contractId: z.string().min(1),
    profile: validationProfileSchema,
    states: z.tuple([z.literal('validated'), z.literal('pending_manual')]),
    source: z.string().min(1),
  }).optional(),
}).superRefine((contract, ctx) => {
  if (contract.postValidation && contract.promptKind !== 'actual_llm_prompt') {
    ctx.addIssue({ code: 'custom', path: ['postValidation'], message: 'postValidation requires an actual LLM prompt' })
  }
})

export const executionGraphNodeSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  componentName: z.string().min(1),
  nodeType: executionGraphNodeTypeSchema,
  promptContractId: z.string().min(1).optional(),
  source: z.string().min(1),
  summary: z.string().min(1),
  body: z.string().min(1),
  inputBoundary: z.array(z.string().min(1)),
  outputContract: z.array(z.string().min(1)),
  writesTo: z.array(z.string().min(1)),
  completionSignals: z.array(z.string().min(1)),
  publicSummary: z.array(z.string().min(1)),
  terminalState: z.string().min(1).optional(),
})

export const executionGraphEdgeSchema = z.object({
  from: z.string().min(1),
  to: z.string().min(1),
  label: z.string().min(1).optional(),
})

export const executionGraphSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  graphKind: executionGraphKindSchema,
  nodes: z.array(executionGraphNodeSchema).min(1),
  edges: z.array(executionGraphEdgeSchema),
}).superRefine((graph, ctx) => {
  const nodeIds = new Set(graph.nodes.map((node) => node.id))
  const seenEdges = new Set<string>()
  const outgoing = new Map<string, typeof graph.edges>()
  const indegree = new Map(graph.nodes.map((node) => [node.id, 0]))
  const reachable = new Set<string>()
  const rootId = graph.nodes[0]?.id

  graph.edges.forEach((edge, index) => {
    if (!nodeIds.has(edge.from)) {
      ctx.addIssue({ code: 'custom', path: ['edges', index, 'from'], message: `unknown edge source ${edge.from}` })
    }
    if (!nodeIds.has(edge.to)) {
      ctx.addIssue({ code: 'custom', path: ['edges', index, 'to'], message: `unknown edge target ${edge.to}` })
    }
    if (edge.from === edge.to) {
      ctx.addIssue({ code: 'custom', path: ['edges', index], message: 'execution graph edges cannot be self-referential' })
    }
    const edgeKey = `${edge.from}\u0000${edge.to}`
    if (seenEdges.has(edgeKey)) {
      ctx.addIssue({ code: 'custom', path: ['edges', index], message: `duplicate edge ${edge.from} -> ${edge.to}` })
    }
    seenEdges.add(edgeKey)
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge])
    if (nodeIds.has(edge.to)) indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1)
  })

  for (const [sourceId, edges] of outgoing) {
    if (edges.length > 1 && edges.some((edge) => !edge.label?.trim())) {
      ctx.addIssue({ code: 'custom', path: ['edges'], message: `branch edges from ${sourceId} must all have labels` })
    }
  }

  if (rootId) {
    const queue = [rootId]
    while (queue.length) {
      const nodeId = queue.shift()!
      if (reachable.has(nodeId)) continue
      reachable.add(nodeId)
      for (const edge of outgoing.get(nodeId) ?? []) queue.push(edge.to)
    }
    graph.nodes.forEach((node, index) => {
      if (!reachable.has(node.id)) {
        ctx.addIssue({ code: 'custom', path: ['nodes', index, 'id'], message: `node ${node.id} is unreachable from ${rootId}` })
      }
    })
  }

  const businessWriteTypes = new Set(['document_render', 'bitable_write', 'storage_write'])
  for (const terminal of graph.nodes.filter((node) => node.terminalState)) {
    const queue = [...(outgoing.get(terminal.id) ?? []).map((edge) => edge.to)]
    const visited = new Set<string>()
    while (queue.length) {
      const nodeId = queue.shift()!
      if (visited.has(nodeId)) continue
      visited.add(nodeId)
      const node = graph.nodes.find((candidate) => candidate.id === nodeId)
      if (node && businessWriteTypes.has(node.nodeType)) {
        ctx.addIssue({
          code: 'custom',
          path: ['nodes'],
          message: `terminal node ${terminal.id} reaches business write node ${node.id}`,
        })
      }
      for (const edge of outgoing.get(nodeId) ?? []) queue.push(edge.to)
    }
  }
  const acyclicQueue = [...indegree].filter(([, count]) => count === 0).map(([nodeId]) => nodeId)
  let acyclicCount = 0
  while (acyclicQueue.length) {
    const nodeId = acyclicQueue.shift()!
    acyclicCount += 1
    for (const edge of outgoing.get(nodeId) ?? []) {
      const nextCount = (indegree.get(edge.to) ?? 0) - 1
      indegree.set(edge.to, nextCount)
      if (nextCount === 0) acyclicQueue.push(edge.to)
    }
  }
  if (acyclicCount !== graph.nodes.length) {
    ctx.addIssue({ code: 'custom', path: ['edges'], message: 'execution graph must be acyclic' })
  }
})

export const deletionContractSchema = z.object({
  coverage: deletionCoverageSchema,
  adapterId: z.string().min(1),
  targetPatterns: z.array(z.string().min(1)),
  previewRequired: z.boolean(),
  confirmationRequired: z.boolean(),
  deletableEntities: z.array(z.string().min(1)),
  manualEntities: z.array(z.string().min(1)),
  source: z.string().min(1),
})

export const displayProjectionSchema = z.object({
  displayArchetype: displayArchetypeSchema,
  displayTitle: z.string().min(1),
  displaySubtitle: z.string().min(1),
  lifecycleLayer: z.string().min(1),
  operatorSummary: z.string().min(1),
  whenToUse: z.array(z.string().min(1)),
  whenNotToUse: z.array(z.string().min(1)),
  requiredInputs: z.array(z.string().min(1)),
  optionalInputs: z.array(z.string().min(1)),
  outputSummary: z.array(z.string().min(1)),
  nextActions: z.array(
    z.object({
      label: z.string().min(1),
      targetCapabilityId: z.string().min(1).optional(),
      actionType: z.enum(['copy_template', 'open_capability', 'reference']),
    }),
  ),
  examplePrompt: z.string().min(1),
  evidenceSummary: z.array(z.string().min(1)),
  riskBadges: z.array(z.string().min(1)),
  savedAs: z.string().min(1),
  operatorFlow: z.array(z.string().min(1)),
  maintainerFields: z.array(
    z.object({
      label: z.string().min(1),
      value: z.string().min(1),
    }),
  ),
})

export const entryTemplateSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string().min(1),
  body: z.string().min(1),
})

export const entryInputContractSchema = z.object({
  title: z.string().min(1),
  summary: z.string().min(1),
  requiredFields: z.array(z.string().min(1)),
  optionalFields: z.array(z.string().min(1)),
  templates: z.array(entryTemplateSchema).min(1),
})

export const entryOutputContractSchema = z.object({
  summary: z.string().min(1),
  userReplySections: z.array(z.string().min(1)),
  artifacts: z.array(z.string().min(1)),
  writesTo: z.array(z.string().min(1)),
  nextActions: z.array(z.string().min(1)),
})

export const entryTreeNodeSchema = z.object({
  id: z.string().min(1),
  capabilityId: z.string().min(1),
  trigger: z.string().min(1),
  displayName: z.string().min(1),
  purpose: z.string().min(1),
  entryRole: entryRoleSchema,
  dispatchMode: dispatchModeSchema,
  recommended: z.boolean(),
  canonicalCapabilityId: z.string().min(1),
  inputContract: entryInputContractSchema,
  outputContract: entryOutputContractSchema,
  nextCapabilityIds: z.array(z.string().min(1)),
  templateId: z.string().min(1),
  supportedAttachments: z.array(z.string().min(1)),
  riskLevel: z.string().min(1),
  visibility: z.string().min(1),
})

export const entryTreeSchema = z.object({
  lifecycleLayer: z.string().min(1),
  root: entryTreeNodeSchema,
  children: z.array(entryTreeNodeSchema),
})

export const capabilitySchema = z.object({
  id: z.string().min(1),
  canonicalCapabilityId: z.string().min(1),
  implementationStatus: implementationStatusSchema,
  recommendedEntry: z.boolean().optional(),
  label: z.string().min(1),
  rawLabel: z.string().min(1),
  title: z.string().min(1),
  description: z.string().min(1),
  primaryBot: botIdSchema,
  visibleBots: z.array(botIdSchema).min(1),
  type: capabilityTypeSchema,
  category: categorySchema,
  taskGroups: z.array(z.string().min(1)),
  aliases: z.array(z.string()),
  keywords: z.array(z.string()),
  commonInputs: z.array(z.string()),
  supportedAttachments: z.array(z.string().min(1)).min(1),
  commonOutputs: z.array(z.string()),
  outputDetail: z.object({
    contentForms: z.array(z.string()),
    destinations: z.array(z.string()),
    destinationLinks: z.array(
      z.object({
        label: z.string().min(1),
        url: z.string().min(1),
        storageType: z.string().min(1),
        description: z.string().min(1),
      }),
    ),
    nextActions: z.array(z.string()),
    boundaries: z.array(z.string()),
  }),
  displayProjection: displayProjectionSchema,
  entryTree: entryTreeSchema.optional(),
  deletionContract: deletionContractSchema,
  defaultInputTemplate: z.string().min(1),
  quickCopyTemplates: z.array(
    z.object({
      id: z.string().min(1),
      title: z.string().min(1),
      description: z.string().min(1),
      body: z.string().min(1),
    }),
  ),
  suitableFor: z.array(z.string()),
  notSuitableFor: z.array(z.string()),
  relatedCapabilityIds: z.array(z.string()),
  flowStageIds: z.array(z.string()),
  promptReferenceIds: z.array(z.string()),
  llmPromptContracts: z.array(llmPromptContractSchema),
  executionGraph: executionGraphSchema,
  sensitivity: sensitivitySchema,
  botAvailability: z.object({
    media: availabilitySchema,
    daily: availabilitySchema,
    knowledge: availabilitySchema,
    social: availabilitySchema,
    deepmath: availabilitySchema,
  }),
})

export const taskSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  group: z.enum(['content', 'daily', 'knowledge', 'social']),
  description: z.string().min(1),
  recommendedBot: botIdSchema,
  recommendedCapabilityIds: z.array(z.string().min(1)),
})

export const linkSchema = z.object({
  id: z.string().min(1),
  group: linkGroupSchema,
  title: z.string().min(1),
  description: z.string().min(1),
  url: z.string().min(1),
  visibility: linkVisibilitySchema,
  status: linkStatusSchema,
  sensitivity: linkSensitivitySchema,
})

export const flowStageSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  owner: flowOwnerSchema,
  inputs: z.array(z.string().min(1)),
  outputs: z.array(z.string().min(1)),
  entryConditions: z.array(z.string().min(1)),
  completionSignals: z.array(z.string().min(1)),
  blockers: z.array(z.string().min(1)),
  handoffArtifacts: z.array(z.string().min(1)),
  relatedCapabilityIds: z.array(z.string().min(1)),
  boundaries: z.array(z.string().min(1)),
  nextStep: z.string().min(1),
})

export const flowSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string().min(1),
  sourceDoc: z.string().min(1),
  visibility: linkVisibilitySchema,
  stages: z.array(flowStageSchema).min(1),
})

export const contentOsProjectSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  stage: z.string().min(1),
  revision: z.string().min(1),
  editingMethod: z.string().min(1),
  owner: z.string().min(1),
  nextAction: z.string().min(1),
  blockedReason: z.string().min(1),
})

export const contentOsProjectDashboardSchema = z.object({
  schemaVersion: z.literal('content_os_project_dashboard_v0.2'),
  title: z.literal('项目详情'),
  summary: z.string().min(1),
  emptyText: z.string().min(1),
  modificationEntry: z.object({
    label: z.literal('在 Media Bot 对话中提交修改'),
    url: z.literal('#/bots/media'),
    instruction: z.string().min(1),
  }),
  projects: z.array(contentOsProjectSchema),
})

export const dashboardSchema = z.object({
  meta: z.object({
    schemaVersion: z.string().min(1),
    contentVersion: z.string().min(1).optional(),
    releaseVersion: z.string().min(1).optional(),
    generatedAt: z.string().min(1),
    source: z.string().min(1),
    sourceCommit: z.string().optional(),
    generatorVersion: z.string().optional(),
    capabilityCount: z.number().int().nonnegative(),
    triggerLabelCount: z.number().int().nonnegative().optional(),
    canonicalCapabilityCount: z.number().int().nonnegative().optional(),
    recommendedEntryCount: z.number().int().nonnegative().optional(),
    warningCount: z.number().int().nonnegative().optional(),
  }),
  bots: z.array(botSchema),
  capabilities: z.array(capabilitySchema),
  tasks: z.array(taskSchema),
  flows: z.array(flowSchema),
  contentOsProjectDashboard: contentOsProjectDashboardSchema,
  links: z.array(linkSchema),
})

export type BotId = z.infer<typeof botIdSchema>
export type Bot = z.infer<typeof botSchema>
export type Capability = z.infer<typeof capabilitySchema>
export type ExecutionGraphNode = z.infer<typeof executionGraphNodeSchema>
export type Flow = z.infer<typeof flowSchema>
export type ContentOsProjectDashboard = z.infer<typeof contentOsProjectDashboardSchema>
export type DashboardData = z.infer<typeof dashboardSchema>
export type Task = z.infer<typeof taskSchema>
export type LinkItem = z.infer<typeof linkSchema>
