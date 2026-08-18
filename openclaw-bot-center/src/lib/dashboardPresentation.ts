import type { BotId, Capability, DashboardData, Flow, Task } from '../schemas/dashboardSchema'

export type CapabilityPresentationSummary = {
  id: string
  canonicalCapabilityId: string
  label: string
  title: string
  description: string
  primaryBot: BotId
  visibleBots: BotId[]
  type: Capability['type']
  category: Capability['category']
  implementationStatus: Capability['implementationStatus']
  recommendedEntry: boolean
  taskGroups: string[]
}

export type PresentationGap = {
  sourceType: 'bot' | 'task' | 'flowStage'
  sourceId: string
  field: string
  missingId: string
}

export type BotPresentationStats = {
  botId: BotId
  name: string
  title: string
  description: string
  primaryTaskGroups: string[]
  entryLinkCount: number
  featuredCapabilityCount: number
  primaryCapabilityCount: number
  visibleCapabilityCount: number
  implementedCapabilityCount: number
  externalCapabilityCount: number
  notImplementedCapabilityCount: number
  recommendedEntryCount: number
  taskCount: number
  flowStageCount: number
  missingFeaturedCapabilityIds: string[]
}

export type BotCapabilityCluster = {
  id: string
  botId: BotId
  label: string
  description: string
  capabilityIds: string[]
  capabilities: CapabilityPresentationSummary[]
  implementedCount: number
  externalCount: number
  notImplementedCount: number
}

export type BotCapabilityClusters = {
  botId: BotId
  botName: string
  clusters: BotCapabilityCluster[]
  gaps: PresentationGap[]
}

export type TaskPresentationRow = {
  id: string
  title: string
  group: Task['group']
  description: string
  recommendedBot: BotId
  recommendedCapabilityIds: string[]
  capabilities: CapabilityPresentationSummary[]
  missingCapabilityIds: string[]
  implementedCapabilityCount: number
  externalCapabilityCount: number
  notImplementedCapabilityCount: number
}

export type FlowStagePresentationSummary = {
  id: string
  title: string
  summary: string
  owner: Flow['stages'][number]['owner']
  inputCount: number
  outputCount: number
  blockerCount: number
  handoffArtifactCount: number
  relatedCapabilityIds: string[]
  capabilities: CapabilityPresentationSummary[]
  missingCapabilityIds: string[]
  nextStep: string
}

export type FlowPresentationSummary = {
  id: string
  title: string
  description: string
  sourceDoc: string
  visibility: Flow['visibility']
  stageCount: number
  ownerIds: Flow['stages'][number]['owner'][]
  relatedCapabilityIds: string[]
  missingCapabilityIds: string[]
  stages: FlowStagePresentationSummary[]
}

export type DashboardPresentation = {
  botStats: BotPresentationStats[]
  botCapabilityClusters: BotCapabilityClusters[]
  taskRows: TaskPresentationRow[]
  flowSummaries: FlowPresentationSummary[]
  gaps: PresentationGap[]
}

export function buildDashboardPresentation(data: DashboardData): DashboardPresentation {
  const botStats = buildBotStats(data)
  const botCapabilityClusters = buildBotCapabilityClusters(data)
  const taskRows = buildTaskRows(data)
  const flowSummaries = buildFlowSummaries(data)

  return {
    botStats,
    botCapabilityClusters,
    taskRows,
    flowSummaries,
    gaps: [
      ...botCapabilityClusters.flatMap((bot) => bot.gaps),
      ...taskRows.flatMap((task) =>
        task.missingCapabilityIds.map((missingId) => ({
          sourceType: 'task' as const,
          sourceId: task.id,
          field: 'recommendedCapabilityIds',
          missingId,
        })),
      ),
      ...flowSummaries.flatMap((flow) =>
        flow.stages.flatMap((stage) =>
          stage.missingCapabilityIds.map((missingId) => ({
            sourceType: 'flowStage' as const,
            sourceId: `${flow.id}:${stage.id}`,
            field: 'relatedCapabilityIds',
            missingId,
          })),
        ),
      ),
    ],
  }
}

export function buildBotStats(data: DashboardData): BotPresentationStats[] {
  const capabilityById = capabilityMap(data)

  return data.bots.map((bot) => {
    const capabilities = data.capabilities.filter((capability) => capability.visibleBots.includes(bot.id))
    const primaryCapabilities = capabilities.filter((capability) => capability.primaryBot === bot.id)
    const tasks = data.tasks.filter((task) => task.recommendedBot === bot.id)
    const flowStageCount = data.flows.reduce(
      (count, flow) =>
        count + flow.stages.filter((stage) => stage.relatedCapabilityIds.some((id) => capabilityById.get(id)?.visibleBots.includes(bot.id))).length,
      0,
    )
    const missingFeaturedCapabilityIds = bot.featuredCapabilityIds.filter((id) => !capabilityById.has(id))

    return {
      botId: bot.id,
      name: bot.name,
      title: bot.title,
      description: bot.description,
      primaryTaskGroups: [...bot.primaryTaskGroups],
      entryLinkCount: bot.entryLinks.length,
      featuredCapabilityCount: bot.featuredCapabilityIds.length - missingFeaturedCapabilityIds.length,
      primaryCapabilityCount: primaryCapabilities.length,
      visibleCapabilityCount: capabilities.length,
      implementedCapabilityCount: countByImplementationStatus(capabilities, 'implemented'),
      externalCapabilityCount: countByImplementationStatus(capabilities, 'external'),
      notImplementedCapabilityCount: countByImplementationStatus(capabilities, 'not_implemented'),
      recommendedEntryCount: capabilities.filter((capability) => capability.recommendedEntry).length,
      taskCount: tasks.length,
      flowStageCount,
      missingFeaturedCapabilityIds,
    }
  })
}

export function buildBotCapabilityClusters(data: DashboardData): BotCapabilityClusters[] {
  const capabilityById = capabilityMap(data)

  return data.bots.map((bot) => {
    const featured = bot.featuredCapabilityIds.map((id) => capabilityById.get(id)).filter(isPresent)
    const visible = data.capabilities.filter((capability) => capability.visibleBots.includes(bot.id))
    const primary = visible.filter((capability) => capability.primaryBot === bot.id)
    const shared = visible.filter((capability) => capability.primaryBot !== bot.id)
    const recommendedEntries = visible.filter((capability) => capability.recommendedEntry)
    const missingFeatured = bot.featuredCapabilityIds.filter((id) => !capabilityById.has(id))

    return {
      botId: bot.id,
      botName: bot.name,
      clusters: [
        makeCluster(bot.id, 'featured', '精选能力', '当前 Bot 首页重点展示的高频能力。', featured),
        makeCluster(bot.id, 'primary', '主责能力', '由当前 Bot 负责承接的能力。', primary),
        makeCluster(bot.id, 'shared', '可见协作能力', '当前 Bot 可调用、但由其他 Bot 主责的能力。', shared),
        makeCluster(bot.id, 'recommended-entry', '推荐入口', '适合作为业务入口直接点击的能力。', recommendedEntries),
      ],
      gaps: missingFeatured.map((missingId) => ({
        sourceType: 'bot' as const,
        sourceId: bot.id,
        field: 'featuredCapabilityIds',
        missingId,
      })),
    }
  })
}

export function buildTaskRows(data: DashboardData): TaskPresentationRow[] {
  const capabilityById = capabilityMap(data)

  return data.tasks.map((task) => {
    const capabilities = task.recommendedCapabilityIds.map((id) => capabilityById.get(id)).filter(isPresent)
    const missingCapabilityIds = task.recommendedCapabilityIds.filter((id) => !capabilityById.has(id))

    return {
      id: task.id,
      title: task.title,
      group: task.group,
      description: task.description,
      recommendedBot: task.recommendedBot,
      recommendedCapabilityIds: [...task.recommendedCapabilityIds],
      capabilities: capabilities.map(summarizeCapability),
      missingCapabilityIds,
      implementedCapabilityCount: countByImplementationStatus(capabilities, 'implemented'),
      externalCapabilityCount: countByImplementationStatus(capabilities, 'external'),
      notImplementedCapabilityCount: countByImplementationStatus(capabilities, 'not_implemented'),
    }
  })
}

export function buildFlowSummaries(data: DashboardData): FlowPresentationSummary[] {
  const capabilityById = capabilityMap(data)

  return data.flows.map((flow) => {
    const stages = flow.stages.map((stage) => {
      const capabilities = stage.relatedCapabilityIds.map((id) => capabilityById.get(id)).filter(isPresent)
      const missingCapabilityIds = stage.relatedCapabilityIds.filter((id) => !capabilityById.has(id))

      return {
        id: stage.id,
        title: stage.title,
        summary: stage.summary,
        owner: stage.owner,
        inputCount: stage.inputs.length,
        outputCount: stage.outputs.length,
        blockerCount: stage.blockers.length,
        handoffArtifactCount: stage.handoffArtifacts.length,
        relatedCapabilityIds: [...stage.relatedCapabilityIds],
        capabilities: capabilities.map(summarizeCapability),
        missingCapabilityIds,
        nextStep: stage.nextStep,
      }
    })
    const relatedCapabilityIds = unique(stages.flatMap((stage) => stage.relatedCapabilityIds))
    const missingCapabilityIds = unique(stages.flatMap((stage) => stage.missingCapabilityIds))

    return {
      id: flow.id,
      title: flow.title,
      description: flow.description,
      sourceDoc: flow.sourceDoc,
      visibility: flow.visibility,
      stageCount: flow.stages.length,
      ownerIds: unique(flow.stages.map((stage) => stage.owner)),
      relatedCapabilityIds,
      missingCapabilityIds,
      stages,
    }
  })
}

function makeCluster(
  botId: BotId,
  id: string,
  label: string,
  description: string,
  capabilities: Capability[],
): BotCapabilityCluster {
  return {
    id: `${botId}:${id}`,
    botId,
    label,
    description,
    capabilityIds: capabilities.map((capability) => capability.id),
    capabilities: capabilities.map(summarizeCapability),
    implementedCount: countByImplementationStatus(capabilities, 'implemented'),
    externalCount: countByImplementationStatus(capabilities, 'external'),
    notImplementedCount: countByImplementationStatus(capabilities, 'not_implemented'),
  }
}

function summarizeCapability(capability: Capability): CapabilityPresentationSummary {
  return {
    id: capability.id,
    canonicalCapabilityId: capability.canonicalCapabilityId,
    label: capability.rawLabel,
    title: capability.title,
    description: capability.description,
    primaryBot: capability.primaryBot,
    visibleBots: [...capability.visibleBots],
    type: capability.type,
    category: capability.category,
    implementationStatus: capability.implementationStatus,
    recommendedEntry: capability.recommendedEntry ?? false,
    taskGroups: [...capability.taskGroups],
  }
}

function countByImplementationStatus(
  capabilities: Capability[],
  implementationStatus: Capability['implementationStatus'],
) {
  return capabilities.filter((capability) => capability.implementationStatus === implementationStatus).length
}

function capabilityMap(data: DashboardData) {
  return new Map(data.capabilities.map((capability) => [capability.id, capability]))
}

function unique<T>(items: T[]): T[] {
  return Array.from(new Set(items))
}

function isPresent<T>(item: T | undefined): item is T {
  return item !== undefined
}
