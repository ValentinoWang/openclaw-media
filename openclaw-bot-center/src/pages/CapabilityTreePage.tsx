import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowRight,
  BookOpen,
  CalendarDays,
  Check,
  Clapperboard,
  Clipboard,
  ExternalLink,
  Layers,
  ListTree,
  UsersRound,
} from 'lucide-react'
import { copyText } from '../lib/clipboard'
import {
  buildDashboardPresentation,
  type BotCapabilityClusters,
  type FlowPresentationSummary,
  type FlowStagePresentationSummary,
} from '../lib/dashboardPresentation'
import { botChineseNames, categoryNames, implementationStatusNames } from '../lib/labels'
import type { BotId, Capability, DashboardData } from '../schemas/dashboardSchema'

type CapabilityTreePageProps = {
  data: DashboardData
  viewMode: 'normal' | 'maintainer'
}

type QuickCopyTemplate = Capability['quickCopyTemplates'][number]
type CapabilityFlowPreview = Pick<FlowPresentationSummary, 'id' | 'title' | 'stages'> & {
  selectedStages: FlowStagePresentationSummary[]
}

const MAX_TEMPLATES = 2

type CapabilityCategoryBranch = {
  id: string
  label: string
  capabilities: Capability[]
}

type CapabilityLifecycleBranch = {
  id: string
  label: string
  capabilities: Capability[]
  categories: CapabilityCategoryBranch[]
}

export default function CapabilityTreePage({ data, viewMode }: CapabilityTreePageProps) {
  const presentation = useMemo(() => buildDashboardPresentation(data), [data])
  const [searchParams, setSearchParams] = useSearchParams()
  const botIds = useMemo(() => new Set(data.bots.map((bot) => bot.id)), [data.bots])
  const initialBotId = readBotParam(searchParams, botIds) ?? data.bots[0]?.id ?? 'media'
  const initialCapabilityId = defaultCapabilityId(data.capabilities, initialBotId, searchParams.get('capability'))
  const [selectedBotId, setSelectedBotId] = useState<BotId>(initialBotId)
  const [selectedCapabilityId, setSelectedCapabilityId] = useState(initialCapabilityId)
  const [selectedClusterId, setSelectedClusterId] = useState(() =>
    clusterIdForSelection(
      presentation.botCapabilityClusters,
      initialBotId,
      initialCapabilityId,
      searchParams.get('cluster'),
    ),
  )

  const selectedBot = data.bots.find((bot) => bot.id === selectedBotId) ?? data.bots[0]
  const selectedBotClusters = presentation.botCapabilityClusters.find((group) => group.botId === selectedBotId)
  const visibleCapabilities = useMemo(
    () => data.capabilities.filter((capability) => capability.visibleBots.includes(selectedBotId)),
    [data.capabilities, selectedBotId],
  )
  const visibleCapabilityIds = useMemo(
    () => new Set(visibleCapabilities.map((capability) => capability.id)),
    [visibleCapabilities],
  )
  const selectedCapability =
    visibleCapabilities.find((capability) => capability.id === selectedCapabilityId) ??
    visibleCapabilities.find((capability) => capability.recommendedEntry) ??
    visibleCapabilities[0]
  const selectedCluster =
    selectedBotClusters?.clusters.find((cluster) => cluster.id === selectedClusterId) ??
    selectedBotClusters?.clusters[0]
  const selectedBotFlows = useMemo(
    () => presentation.flowSummaries
      .map((flow) => ({
        id: flow.id,
        title: flow.title,
        stages: flow.stages,
        selectedStages: flow.stages.filter((stage) =>
          stage.relatedCapabilityIds.some((capabilityId) => visibleCapabilityIds.has(capabilityId)),
        ),
      }))
      .filter((flow) => flow.selectedStages.length > 0),
    [presentation.flowSummaries, visibleCapabilityIds],
  )
  const lifecycleTree = useMemo(
    () => buildCapabilityLifecycleTree(visibleCapabilities),
    [visibleCapabilities],
  )

  useEffect(() => {
    const urlBotId = readBotParam(searchParams, botIds) ?? data.bots[0]?.id
    if (!urlBotId) return

    const nextCapabilityId = defaultCapabilityId(data.capabilities, urlBotId, searchParams.get('capability'))
    const nextClusterId = clusterIdForSelection(
      presentation.botCapabilityClusters,
      urlBotId,
      nextCapabilityId,
      searchParams.get('cluster'),
    )
    if (urlBotId !== selectedBotId) {
      setSelectedBotId(urlBotId)
      setSelectedClusterId(nextClusterId)
    }
    if (nextCapabilityId !== selectedCapabilityId) {
      setSelectedCapabilityId(nextCapabilityId)
    }
    if (nextClusterId !== selectedClusterId) {
      setSelectedClusterId(nextClusterId)
    }
  }, [botIds, data.bots, data.capabilities, presentation.botCapabilityClusters, searchParams, selectedBotId, selectedCapabilityId, selectedClusterId])

  if (!selectedBot) {
    return (
      <main className="redesign-capability-tree-page" aria-label="Capabilities">
        <p className="redesign-empty-state">当前生成数据里还没有 Bot 记录。</p>
      </main>
    )
  }

  function selectBot(botId: BotId) {
    const capabilityId = defaultCapabilityId(data.capabilities, botId)
    const clusterId = clusterIdForCapability(presentation.botCapabilityClusters, botId, capabilityId)
    setSelectedBotId(botId)
    setSelectedCapabilityId(capabilityId)
    setSelectedClusterId(clusterId)
    updateSelection(botId, capabilityId, clusterId)
  }

  function selectCapability(capabilityId: string) {
    const clusterId = clusterIdForSelection(
      presentation.botCapabilityClusters,
      selectedBotId,
      capabilityId,
      selectedClusterId,
    )
    setSelectedCapabilityId(capabilityId)
    setSelectedClusterId(clusterId)
    updateSelection(selectedBotId, capabilityId, clusterId)
  }

  function updateSelection(botId: BotId, capabilityId: string, clusterId: string) {
    const nextSearchParams = new URLSearchParams(searchParams)
    nextSearchParams.set('bot', botId)
    if (capabilityId) nextSearchParams.set('capability', capabilityId)
    else nextSearchParams.delete('capability')
    if (clusterId) nextSearchParams.set('cluster', clusterId)
    else nextSearchParams.delete('cluster')
    setSearchParams(nextSearchParams)
  }

  function selectCluster(clusterId: string) {
    const cluster = selectedBotClusters?.clusters.find((candidate) => candidate.id === clusterId)
    const clusterCapabilityIds = new Set(cluster?.capabilities.map((capability) => capability.id))
    const capabilityId = data.capabilities.find((capability) =>
      clusterCapabilityIds.has(capability.id) && capability.recommendedEntry,
    )?.id ?? cluster?.capabilities[0]?.id ?? ''
    setSelectedClusterId(clusterId)
    setSelectedCapabilityId(capabilityId)
    updateSelection(selectedBotId, capabilityId, clusterId)
  }

  const recommendedEntryCount = visibleCapabilities.filter((capability) => capability.recommendedEntry).length

  return (
    <main className="redesign-capability-tree-page redesign-capability-nav-page" aria-label="Capabilities">
      <nav className="redesign-capability-nav-tabs" aria-label="Bot tabs">
        {data.bots.map((bot) => {
          const botClusters = presentation.botCapabilityClusters.find((group) => group.botId === bot.id)
          const entryCount = botClusters?.clusters.reduce(
            (count, cluster) => count + cluster.capabilities.filter((capability) => capability.recommendedEntry).length,
            0,
          ) ?? 0
          return (
            <button
              key={bot.id}
              type="button"
              className={`redesign-capability-nav-tab redesign-capability-nav-bot-${bot.id} ${bot.id === selectedBotId ? 'redesign-is-selected' : ''}`}
              onClick={() => selectBot(bot.id)}
              aria-pressed={bot.id === selectedBotId}
            >
              <span className="redesign-capability-nav-bot-icon">{botIcon(bot.id)}</span>
              <span><strong>{botChineseNames[bot.id] ?? bot.name}</strong><small>{entryCount} 个入口</small></span>
            </button>
          )
        })}
      </nav>

      <section className="redesign-capability-nav-layout">
        <aside className="redesign-capability-nav-index" aria-label="Selected Bot overview">
          <header className="redesign-capability-nav-bot-summary">
            <span className="redesign-kicker">当前 Bot</span>
            <h1>{selectedBot.title}</h1>
            <p>{selectedBot.description}</p>
            <div className="redesign-capability-nav-metrics" aria-label="Capability counts">
              <Metric label="能力" value={visibleCapabilities.length} />
              <Metric label="能力簇" value={selectedBotClusters?.clusters.length ?? 0} />
              <Metric label="推荐入口" value={recommendedEntryCount} />
            </div>
          </header>
          <ClusterNavigator
            clusters={selectedBotClusters}
            selectedClusterId={selectedCluster?.id}
            selectedCapabilityId={selectedCapability?.id}
            onSelectCluster={selectCluster}
            onSelectCapability={selectCapability}
          />
        </aside>

        <section className="redesign-capability-nav-main" aria-label="Capability navigator">
          <header className="redesign-capability-nav-header">
            <div>
              <span className="redesign-kicker">能力入口</span>
              <h1>{selectedBot.title} / 能力导航</h1>
              <p>先选入口，再在右侧查看输入、输出和可复制模板。</p>
            </div>
            <div className="redesign-capability-nav-legend" aria-label="Capability status legend">
              <span><i className="legend-implemented" /> 已落地</span>
              <span><i className="legend-external" /> 既有链路</span>
              <span><i className="legend-planned" /> 规划中</span>
            </div>
          </header>

          <div className="redesign-capability-nav-clusters">
            {lifecycleTree.length ? (
              <CapabilityHierarchyTree
                branches={lifecycleTree}
                selectedCapabilityId={selectedCapability?.id}
                onSelectCapability={selectCapability}
              />
            ) : <p className="redesign-empty-state">当前 Bot 暂无可展示能力。</p>}
          </div>
          <CapabilityFlowPreview flows={selectedBotFlows.slice(0, 2)} />
        </section>

        <CapabilityQuickDetail capability={selectedCapability} viewMode={viewMode} />
      </section>
    </main>
  )
}

function ClusterNavigator({
  clusters,
  selectedClusterId,
  selectedCapabilityId,
  onSelectCluster,
  onSelectCapability,
}: {
  clusters: BotCapabilityClusters | undefined
  selectedClusterId: string | undefined
  selectedCapabilityId: string | undefined
  onSelectCluster: (clusterId: string) => void
  onSelectCapability: (capabilityId: string) => void
}) {
  return (
    <section className="redesign-capability-nav-cluster-index" aria-label="Capability cluster index">
      <h2><ListTree size={17} aria-hidden="true" /> 能力簇</h2>
      {clusters?.clusters.map((cluster) => (
        <section key={cluster.id} className="redesign-capability-nav-index-group">
          <button
            type="button"
            className={`redesign-capability-nav-cluster-select ${cluster.id === selectedClusterId ? 'redesign-is-selected' : ''}`}
            onClick={() => onSelectCluster(cluster.id)}
          >
            <span>{cluster.label}</span><small>{cluster.capabilities.length}</small>
          </button>
          {cluster.id === selectedClusterId ? (
            <details className="redesign-capability-nav-index-entries" open={cluster.capabilities.length <= 8}>
              <summary>入口索引</summary>
              <div>
                {cluster.capabilities.map((capability) => (
                  <button
                    key={capability.id}
                    type="button"
                    className={capability.id === selectedCapabilityId ? 'redesign-is-selected' : ''}
                    onClick={() => onSelectCapability(capability.id)}
                  >
                    <span>{capability.title}</span>
                    <small>{implementationStatusNames[capability.implementationStatus]}</small>
                  </button>
                ))}
              </div>
            </details>
          ) : null}
        </section>
      ))}
    </section>
  )
}

function buildCapabilityLifecycleTree(capabilities: Capability[]): CapabilityLifecycleBranch[] {
  const lifecycleOrder = ['Strategy', 'Collect', 'Decide', 'Create', 'Polish', 'Verify', 'Publish', 'Learn', 'Daily', 'Entity', 'Govern', 'Operate']
  const lifecycleLabels: Record<string, string> = {
    Strategy: '策略与规划',
    Collect: '素材收集',
    Decide: '选题与判断',
    Create: '内容创作',
    Polish: '表达优化',
    Verify: '检查与验收',
    Publish: '发布准备',
    Learn: '数据复盘',
    Daily: '日常执行',
    Entity: '账号与实体',
    Govern: '治理与维护',
    Operate: '通用操作',
  }
  const lifecycleMap = new Map<string, Capability[]>()
  capabilities.forEach((capability) => {
    const lifecycle = capability.displayProjection.lifecycleLayer
    lifecycleMap.set(lifecycle, [...(lifecycleMap.get(lifecycle) ?? []), capability])
  })

  return [...lifecycleMap.entries()]
    .sort(([left], [right]) => {
      const leftIndex = lifecycleOrder.indexOf(left)
      const rightIndex = lifecycleOrder.indexOf(right)
      return (leftIndex < 0 ? lifecycleOrder.length : leftIndex) - (rightIndex < 0 ? lifecycleOrder.length : rightIndex)
    })
    .map(([id, branchCapabilities]) => {
      const categoryMap = new Map<Capability['category'], Capability[]>()
      branchCapabilities.forEach((capability) => {
        categoryMap.set(capability.category, [...(categoryMap.get(capability.category) ?? []), capability])
      })
      return {
        id,
        label: lifecycleLabels[id] ?? id,
        capabilities: branchCapabilities,
        categories: [...categoryMap.entries()]
          .sort(([left], [right]) => (categoryNames[left] ?? left).localeCompare(categoryNames[right] ?? right, 'zh-Hans-CN'))
          .map(([categoryId, categoryCapabilities]) => ({
            id: categoryId,
            label: categoryNames[categoryId] ?? categoryId,
            capabilities: categoryCapabilities,
          })),
      }
    })
}

function CapabilityHierarchyTree({
  branches,
  selectedCapabilityId,
  onSelectCapability,
}: {
  branches: CapabilityLifecycleBranch[]
  selectedCapabilityId: string | undefined
  onSelectCapability: (capabilityId: string) => void
}) {
  return (
    <section className="redesign-capability-hierarchy" aria-label="能力树">
      {branches.map((branch) => {
        const branchSelected = branch.capabilities.some((capability) => capability.id === selectedCapabilityId)
        return (
          <details key={branch.id} className="redesign-capability-tree-level" open={branchSelected || undefined}>
            <summary>
              <span><Layers size={16} aria-hidden="true" /><strong>{branch.label}</strong></span>
              <small>{branch.capabilities.length} 个能力 · {branch.categories.length} 个类别</small>
            </summary>
            <div className="redesign-capability-tree-branches">
              {branch.categories.map((category) => {
                const categorySelected = category.capabilities.some((capability) => capability.id === selectedCapabilityId)
                return (
                  <details key={category.id} className="redesign-capability-tree-category" open={categorySelected || undefined}>
                    <summary>
                      <span>{category.label}</span>
                      <small>{category.capabilities.length}</small>
                    </summary>
                    <div className="redesign-capability-nav-entry-grid">
                      {category.capabilities.map((capability) => (
                        <CapabilityNavigationCard
                          key={capability.id}
                          capability={capability}
                          selected={capability.id === selectedCapabilityId}
                          onSelect={() => onSelectCapability(capability.id)}
                        />
                      ))}
                    </div>
                  </details>
                )
              })}
            </div>
          </details>
        )
      })}
    </section>
  )
}

function CapabilityNavigationCard({
  capability,
  selected,
  onSelect,
}: {
  capability: Capability
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={`redesign-capability-nav-entry ${selected ? 'redesign-is-selected' : ''}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="redesign-capability-nav-entry-heading">
        <strong>{capability.displayProjection.displayTitle}</strong>
        <small>{implementationStatusNames[capability.implementationStatus]}</small>
      </span>
      <span className="redesign-capability-nav-entry-summary">{capability.displayProjection.operatorSummary}</span>
      <span className="redesign-capability-nav-entry-meta">
        {capability.recommendedEntry ? '推荐入口' : categoryNames[capability.category]}
      </span>
    </button>
  )
}

function CapabilityFlowPreview({ flows }: { flows: CapabilityFlowPreview[] }) {
  if (!flows.length) return null

  return (
    <section className="redesign-capability-nav-flow-preview" aria-label="Related flows">
      <span>关联流程</span>
      {flows.map((flow) => (
        <a key={flow.id} href={`#/flows/${flow.id}`}>
          <strong>{flow.title}</strong>
          <small>{flow.selectedStages.length} / {flow.stages.length} 个相关阶段</small>
          <ArrowRight size={14} aria-hidden="true" />
        </a>
      ))}
    </section>
  )
}

function CapabilityQuickDetail({
  capability,
  viewMode,
}: {
  capability: Capability | undefined
  viewMode: 'normal' | 'maintainer'
}) {
  const [copiedTemplateId, setCopiedTemplateId] = useState<string | null>(null)

  if (!capability) {
    return (
      <aside className="redesign-capability-nav-detail" aria-label="Selected capability detail">
        <p className="redesign-empty-state">选择一个入口后在这里查看详情。</p>
      </aside>
    )
  }

  const templates = capability.quickCopyTemplates.length
    ? capability.quickCopyTemplates.slice(0, MAX_TEMPLATES)
    : [{ id: 'default-input-template', title: '默认输入模板', description: capability.displayProjection.displaySubtitle, body: capability.defaultInputTemplate }]
  const inputSummary = capability.entryTree?.root.inputContract.summary ?? capability.displayProjection.requiredInputs[0] ?? capability.defaultInputTemplate
  const outputSummary = capability.entryTree?.root.outputContract.summary ?? capability.displayProjection.outputSummary[0] ?? capability.outputDetail.contentForms[0]

  async function copyTemplate(template: QuickCopyTemplate) {
    await copyText(template.body)
    setCopiedTemplateId(template.id)
  }

  return (
    <aside className="redesign-capability-nav-detail" aria-label="Selected capability detail">
      <section className="redesign-capability-nav-detail-card">
        <span className="redesign-kicker">{categoryNames[capability.category]} / {implementationStatusNames[capability.implementationStatus]}</span>
        <h2>{capability.displayProjection.displayTitle}</h2>
        <p>{capability.displayProjection.operatorSummary}</p>
        <a href={`#/capabilities/detail/${capability.id}`}>
          打开完整详情 <ExternalLink size={14} aria-hidden="true" />
        </a>
      </section>

      <section className="redesign-capability-nav-detail-card">
        <h3>输入与输出</h3>
        <dl>
          <div><dt>输入</dt><dd>{inputSummary}</dd></div>
          <div><dt>输出</dt><dd>{outputSummary}</dd></div>
        </dl>
        {capability.outputDetail.nextActions.length ? (
          <p className="redesign-capability-nav-next">下一步：{capability.outputDetail.nextActions.slice(0, 2).join('；')}</p>
        ) : null}
      </section>

      <section className="redesign-capability-nav-detail-card">
        <h3><Clipboard size={16} aria-hidden="true" /> 快捷模板</h3>
        <div className="redesign-capability-nav-template-list">
          {templates.map((template) => (
            <button key={template.id} type="button" onClick={() => void copyTemplate(template)}>
              <span><strong>{template.title}</strong><small>{template.description}</small></span>
              {copiedTemplateId === template.id ? <Check size={16} aria-hidden="true" /> : <Clipboard size={16} aria-hidden="true" />}
            </button>
          ))}
        </div>
      </section>

      {viewMode === 'maintainer' ? (
        <section className="redesign-capability-nav-detail-card redesign-capability-nav-maintainer">
          <h3>维护字段</h3>
          {capability.displayProjection.maintainerFields.map((field) => (
            <p key={`${capability.id}-${field.label}`}><strong>{field.label}</strong>{field.value}</p>
          ))}
        </section>
      ) : null}
    </aside>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return <span><strong>{value}</strong><small>{label}</small></span>
}

function botIcon(botId: BotId) {
  const props = { size: 17, 'aria-hidden': true as const }
  switch (botId) {
    case 'media': return <Clapperboard {...props} />
    case 'daily': return <CalendarDays {...props} />
    case 'knowledge': return <BookOpen {...props} />
    case 'social': return <UsersRound {...props} />
  }
}

function defaultCapabilityId(capabilities: Capability[], botId: BotId, requestedId?: string | null) {
  const visibleCapabilities = capabilities.filter((capability) => capability.visibleBots.includes(botId))
  return visibleCapabilities.find((capability) => capability.id === requestedId)?.id ??
    visibleCapabilities.find((capability) => capability.recommendedEntry)?.id ??
    visibleCapabilities[0]?.id ?? ''
}

function defaultClusterId(clusters: BotCapabilityClusters[], botId: BotId) {
  return clusters.find((cluster) => cluster.botId === botId)?.clusters[0]?.id ?? ''
}

function clusterIdForCapability(clusters: BotCapabilityClusters[], botId: BotId, capabilityId: string) {
  const botClusters = clusters.find((cluster) => cluster.botId === botId)?.clusters
  return botClusters?.find((cluster) => cluster.capabilities.some((capability) => capability.id === capabilityId))?.id ??
    defaultClusterId(clusters, botId)
}

function clusterIdForSelection(
  clusters: BotCapabilityClusters[],
  botId: BotId,
  capabilityId: string,
  requestedClusterId?: string | null,
) {
  const botClusters = clusters.find((cluster) => cluster.botId === botId)?.clusters
  const requestedCluster = botClusters?.find((cluster) => cluster.id === requestedClusterId)
  if (requestedCluster?.capabilities.some((capability) => capability.id === capabilityId)) {
    return requestedCluster.id
  }
  return clusterIdForCapability(clusters, botId, capabilityId)
}

function readBotParam(searchParams: URLSearchParams, botIds: Set<string>) {
  const bot = searchParams.get('bot')
  return bot && botIds.has(bot) ? bot as BotId : undefined
}
