import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  Bot,
  CalendarClock,
  Check,
  CircleHelp,
  Clipboard,
  ExternalLink,
  FileSearch,
  GitBranch,
  Link as LinkIcon,
  Search,
  Settings2,
  ShieldCheck,
  Users,
} from 'lucide-react'
import {
  HashRouter,
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useParams,
  useSearchParams,
} from 'react-router-dom'
import './App.css'
import { loadDashboardData } from './data/loadDashboardData'
import {
  buildCapabilityMaintenancePresentation,
  buildDeletionBoundaryPresentation,
  executionEdgeLabelText,
  executionEdgeLabelWidth,
  executionNodeTypeLabel,
  executionStateLabel,
  validationProfileLabel,
} from './lib/capabilityMaintenancePresentation'
import { copyText } from './lib/clipboard'
import {
  layoutExecutionGraph,
  MAX_OVERVIEW_JUNCTION_WIDTH,
  recommendedExecutionNodeWidth,
  type ExecutionGraphLayout,
} from './lib/executionGraphLayout'
import { availabilityNames, botNames, categoryNames, flowOwnerNames, taskGroupNames, typeNames } from './lib/labels'
import { buildSearch } from './lib/search'
import BotsBoardPage from './pages/BotsBoardPage'
import BusinessMapPage from './pages/BusinessMapPage'
import CapabilityTreePage from './pages/CapabilityTreePage'
import FlowMapPage from './pages/FlowMapPage'
import type { Bot as DashboardBot, BotId, Capability, DashboardData, Flow, LinkItem } from './schemas/dashboardSchema'

type ViewMode = 'normal' | 'maintainer'
type ImplementationStatus = Capability['implementationStatus']
type CapabilityEntryTree = NonNullable<Capability['entryTree']>
type CapabilityEntryNode = CapabilityEntryTree['root']
type CapabilityDisplayArchetype =
  | 'entry_hub'
  | 'direct_action'
  | 'gate_review'
  | 'creation_handoff'
  | 'entity_store'
  | 'system_maintenance'
type CapabilityWithLegacyDisplayArchetype = Capability & { displayArchetype?: CapabilityDisplayArchetype | string }

const botIcons: Record<BotId, typeof Bot> = {
  media: FileSearch,
  daily: CalendarClock,
  knowledge: CircleHelp,
  social: Users,
  deepmath: Brain,
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>(() => initialViewMode())

  useEffect(() => {
    loadDashboardData()
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '数据加载失败')
      })
  }, [])

  if (error) {
    return (
      <main className="state-page">
        <AlertTriangle aria-hidden="true" />
        <h1>能力数据不可用</h1>
        <p>{error}</p>
      </main>
    )
  }

  if (!data) {
    return (
      <main className="state-page">
        <div className="skeleton-block" />
        <h1>正在加载能力中心</h1>
        <p>读取静态 JSON 并校验数据契约。</p>
      </main>
    )
  }

  return (
    <HashRouter>
      <AppShell data={data} viewMode={viewMode} onViewModeChange={setViewMode}>
        <Routes>
          <Route path="/" element={<Navigate to="/bots" replace />} />
          <Route path="/bots" element={<BotsPage data={data} viewMode={viewMode} />} />
          <Route path="/bots/:botId" element={<BotDetailPage data={data} viewMode={viewMode} />} />
          <Route path="/tasks" element={<TasksPage data={data} />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage data={data} />} />
          <Route path="/flows" element={<FlowsPage data={data} viewMode={viewMode} />} />
          <Route path="/flows/:flowId" element={<FlowDetailPage data={data} viewMode={viewMode} />} />
          <Route path="/capabilities" element={<CapabilityDirectoryPage data={data} viewMode={viewMode} />} />
          <Route path="/capabilities/matrix" element={<CapabilityMatrixPage data={data} viewMode={viewMode} />} />
          <Route path="/capabilities/detail/:capabilityId" element={<CapabilityDetailPage data={data} viewMode={viewMode} />} />
          <Route path="/links" element={<LinksPage data={data} viewMode={viewMode} />} />
          <Route path="*" element={<Navigate to="/bots" replace />} />
        </Routes>
      </AppShell>
    </HashRouter>
  )
}

function AppShell({
  children,
  data,
  viewMode,
  onViewModeChange,
}: {
  children: ReactNode
  data: DashboardData
  viewMode: ViewMode
  onViewModeChange: (viewMode: ViewMode) => void
}) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/bots" className="brand" aria-label="MediaClaw 能力中心首页">
          <span className="brand-mark">MC</span>
          <span>
            <strong>MediaClaw 能力中心</strong>
            <small>四 Bot 能力导航</small>
          </span>
        </Link>
        <nav className="main-nav" aria-label="主导航">
          <NavLink to="/bots">Bot</NavLink>
          <NavLink to="/tasks">业务</NavLink>
          <NavLink to="/capabilities">能力</NavLink>
          <NavLink to="/flows">流程</NavLink>
        </nav>
        <GlobalSearch data={data} />
        <div className="view-mode-switch" role="group" aria-label="视图模式">
          <button type="button" className={viewMode === 'normal' ? 'active' : ''} onClick={() => onViewModeChange('normal')}>普通</button>
          <button type="button" className={viewMode === 'maintainer' ? 'active' : ''} onClick={() => onViewModeChange('maintainer')}>维护</button>
        </div>
      </header>
      <div className="page-frame">{children}</div>
    </div>
  )
}

function GlobalSearch({ data }: { data: DashboardData }) {
  const [query, setQuery] = useState('')
  const location = useLocation()
  const search = useMemo(() => buildSearch(data), [data])
  const results = useMemo(() => search(query), [query, search])

  useEffect(() => {
    setQuery('')
  }, [location.pathname, location.search])

  return (
    <section className="search-band" aria-label="全局搜索">
      <div className="search-box">
        <Search size={18} aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索 Bot / 能力 / 任务 / 协同地图，例如 创作>小红书"
          aria-label="搜索 Bot、能力、任务、协同地图或跳转"
        />
      </div>
      {query.trim() ? (
        <div className="search-results" aria-live="polite">
          {results.length ? (
            results.map((result) => (
              <a key={`${result.kind}-${result.href}-${result.title}`} href={result.href} className="search-result">
                <span className="result-kind">{result.kind}</span>
                <span>
                  <strong>{result.title}</strong>
                  <small>{result.subtitle}</small>
                </span>
                <ArrowRight size={16} aria-hidden="true" />
              </a>
            ))
          ) : (
            <div className="empty-inline">没有匹配结果。请尝试真实触发标签或任务名。</div>
          )}
        </div>
      ) : null}
    </section>
  )
}

function BotsPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  return <BotsBoardPage data={data} viewMode={viewMode} />
}

function BotDetailPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  const { botId } = useParams()
  const bot = data.bots.find((item) => item.id === botId)
  if (!bot) return <Navigate to="/bots" replace />
  const capabilities = capabilitiesForBotDetail(data, bot.id, viewMode)
  const plannedCapabilities = plannedCapabilitiesForBotDetail(data, bot.id, viewMode)
  const primary = capabilities.filter((capability) => capability.primaryBot === bot.id)
  const visible = capabilities.filter((capability) => capability.primaryBot !== bot.id)
  const Icon = botIcons[bot.id]
  const mediaFlow = bot.id === 'media' ? data.flows.find((flow) => flow.id === 'cloud-mac-materials') : undefined

  return (
    <main>
      <PageHeader label={bot.name} title={bot.title} description={bot.description} icon={<Icon size={24} />} />
      {bot.helpProjection ? <BotHelpProjectionPanel projection={bot.helpProjection} /> : null}
      {bot.id === 'social' ? <BoundaryNotice compact /> : null}
      {mediaFlow ? (
        <section className="section-block">
          <SectionTitle title="内容生产协同路径" />
          <MediaWorkflowPanel flow={mediaFlow} capabilities={data.capabilities} />
        </section>
      ) : null}
      {viewMode === 'maintainer' ? (
        <section className="section-block">
          <SectionTitle title="主能力" count={primary.length} />
          <CapabilityList capabilities={primary} viewMode={viewMode} />
        </section>
      ) : (
        <>
          <section className="section-block">
            <SectionTitle title={bot.id === 'media' ? 'Media 增长链' : '精选能力'} count={capabilities.length} />
            <CapabilityList capabilities={capabilities} viewMode={viewMode} />
          </section>
          {plannedCapabilities.length ? (
            <section className="section-block planned-capabilities-section">
              <SectionTitle title="规划中" count={plannedCapabilities.length} />
              <p className="section-note">这些能力只返回待人工处理或缺口提示，不代表已经接入完整执行链路。</p>
              <CapabilityList capabilities={plannedCapabilities} viewMode={viewMode} />
            </section>
          ) : null}
        </>
      )}
      {viewMode === 'maintainer' ? (
        <section className="section-block">
          <SectionTitle title="协作可见能力" count={visible.length} />
          <CapabilityList capabilities={visible} viewMode={viewMode} />
        </section>
      ) : null}
    </main>
  )
}

function BotHelpProjectionPanel({ projection }: { projection: NonNullable<DashboardBot['helpProjection']> }) {
  const groups = [
    { title: '当前能力', items: projection.current },
    { title: '尚未开放', items: projection.notYet },
    { title: '冻结目标', items: projection.frozenTarget },
  ]

  return (
    <section className="section-block" aria-label={projection.title}>
      <SectionTitle title={projection.title} count={projection.current.length + projection.notYet.length + projection.frozenTarget.length} />
      <p className="section-note">{projection.summary}</p>
      <ImplementationBadge status={projection.implementationStatus} compact />
      <div className="help-projection-groups">
        {groups.map((group) => (
          <article className="summary-panel" key={group.title}>
            <h3>{group.title}</h3>
            {group.items.length ? (
              <ul>
                {group.items.map((item) => (
                  <li key={item}>
                    <p>{item}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="section-note">当前没有该状态的 DeepMath 能力。</p>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}

function TasksPage({ data }: { data: DashboardData }) {
  return <BusinessMapPage data={data} />
}

function TaskDetailPage({ data }: { data: DashboardData }) {
  const { taskId } = useParams()
  const task = data.tasks.find((item) => item.id === taskId)
  if (!task) return <Navigate to="/tasks" replace />
  const bot = data.bots.find((item) => item.id === task.recommendedBot)
  const capabilities = task.recommendedCapabilityIds
    .map((id) => data.capabilities.find((capability) => capability.id === id))
    .filter(Boolean) as Capability[]

  return (
    <main>
      <PageHeader label={taskGroupNames[task.group]} title={task.title} description={task.description} />
      {bot ? (
        <section className="summary-panel">
          <span className="muted-label">推荐 Bot</span>
          <strong>{bot.name}</strong>
          <p>{bot.description}</p>
          <Link className="text-link" to={`/bots/${bot.id}`}>进入 {bot.name}</Link>
        </section>
      ) : null}
      <section className="section-block">
        <SectionTitle title="推荐能力" count={capabilities.length} />
        <CapabilityList capabilities={capabilities} viewMode="normal" />
      </section>
    </main>
  )
}

function FlowsPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  return <FlowMapPage data={data} viewMode={viewMode} />
}

function FlowDetailPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  const { flowId } = useParams()
  const flow = data.flows.find((item) => item.id === flowId)
  const capabilityMap = useCapabilityMap(data)
  const [selectedStageId, setSelectedStageId] = useState(flow?.stages[0]?.id ?? '')
  if (!flow) return <Navigate to="/flows" replace />

  const selectedStage = flow.stages.find((stage) => stage.id === selectedStageId) ?? flow.stages[0]
  const relatedCapabilities = selectedStage.relatedCapabilityIds
    .map((id) => capabilityMap.get(id))
    .filter(Boolean) as Capability[]

  return (
    <main>
      <PageHeader label="Media bot / 内容生产看板" title={flow.title} description={flow.description} />
      <section className="flow-boundary">
        <ShieldCheck size={20} aria-hidden="true" />
        <div>
          <strong>这是给媒体运营判断流程的看板，不是 Mac 操作手册。</strong>
          <p>页面主体只看每一步谁负责、要准备什么、会产出什么、能用哪些能力；维护信息只放在底部折叠区或生成数据里核对。</p>
        </div>
      </section>

      <section className="flow-detail-layout">
        <div className="flow-timeline" aria-label="流程阶段">
          {flow.stages.map((stage, index) => (
            <button
              key={stage.id}
              type="button"
              className={stage.id === selectedStage.id ? 'active' : ''}
              onClick={() => setSelectedStageId(stage.id)}
            >
              <span className="stage-index">{index + 1}</span>
              <span>
                <strong>{stage.title}</strong>
                <small>{flowOwnerNames[stage.owner]}</small>
                <StageImplementationSummary capabilities={stage.relatedCapabilityIds.map((id) => capabilityMap.get(id)).filter(Boolean) as Capability[]} compact />
              </span>
            </button>
          ))}
        </div>
        <FlowStagePanel stage={selectedStage} capabilities={relatedCapabilities} />
      </section>

      {viewMode === 'maintainer' ? (
        <section className="summary-panel">
          <span className="muted-label">维护者视图</span>
          <div className="meta-grid wide">
            <span>流程 ID：{flow.id}</span>
            <span>协议来源：{flow.sourceDoc}</span>
            <span>阶段数：{flow.stages.length}</span>
            <span>数据生成：{new Date(data.meta.generatedAt).toLocaleString()}</span>
          </div>
          <p>维护信息只展示协议来源的相对位置和生成时间，不把真实本地素材路径、处理函数或运行日志写入公开 JSON。</p>
        </section>
      ) : null}
    </main>
  )
}

function CapabilityDirectoryPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  return <CapabilityTreePage data={data} viewMode={viewMode} />
}

function CapabilityDetailPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  const { capabilityId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const capability = data.capabilities.find((item) => item.id === capabilityId)
  if (!capability) return <Navigate to="/capabilities" replace />
  return (
    <main>
      <CapabilityUsagePanel
        capability={capability}
        data={data}
        selectedEntryId={searchParams.get('entry') ?? undefined}
        onSelectedEntryIdChange={(entryId) => {
          const rootId = capability.entryTree?.root.id
          setSearchParams(entryId && entryId !== rootId ? { entry: entryId } : {})
        }}
      />
      <CapabilityMaintenanceDisclosure capability={capability} data={data} defaultOpen={viewMode === 'maintainer'} />
    </main>
  )
}

function CapabilityMaintenanceDisclosure({
  capability,
  data,
  defaultOpen,
}: {
  capability: Capability
  data: DashboardData
  defaultOpen: boolean
}) {
  const maintenance = buildCapabilityMaintenancePresentation(capability, data.meta)
  const deletion = buildDeletionBoundaryPresentation(capability.deletionContract)
  const branchCount = executionBranchCount(capability.executionGraph)
  return (
    <section className="maintenance-disclosure-section">
      <details className="maintenance-details" open={defaultOpen}>
        <summary>
          <Settings2 size={18} aria-hidden="true" />
          <span>
            <strong>维护信息</strong>
            <small>业务归属、执行边界和删除保护。</small>
          </span>
        </summary>
        <div className="maintenance-body">
          <div className="maintenance-meta-grid">
            {maintenance.rows.map((row) => (
              <div key={row.label}>
                <span>{row.label}</span>
                {row.kind === 'status'
                  ? <strong><ImplementationBadge status={row.status} compact /></strong>
                  : <strong>{row.value}</strong>}
              </div>
            ))}
          </div>
          <details className="maintenance-nested-details execution-contract-details" open={defaultOpen}>
            <summary>
              <GitBranch size={18} aria-hidden="true" />
              <span>
                <strong>执行边界</strong>
                <small>自动生成 · {capability.executionGraph.nodes.length} 个节点 · {branchCount} 处分叉 · {capability.llmPromptContracts.length} 个 Prompt 契约</small>
              </span>
            </summary>
            <CapabilityExecutionGraphPanel graph={capability.executionGraph} contracts={capability.llmPromptContracts} />
          </details>
          <details className="maintenance-nested-details">
            <summary>
              <span>
                <strong>删除契约</strong>
                <small>仅展示公开边界；默认预览，确认后执行。</small>
              </span>
            </summary>
            <div className="deletion-contract-body">
              <OutputGroup title="处理范围" items={deletion.scope} />
              <OutputGroup title="保护措施" items={deletion.safeguards} />
            </div>
          </details>
          <p className="maintenance-footnote">
            维护信息是公开只读说明，不是权限控制；界面不展示内部编号、处理函数、源码路径、凭据、飞书原始记录或错误堆栈。
          </p>
        </div>
      </details>
    </section>
  )
}

function CapabilityUsagePanel({
  capability,
  data,
  selectedEntryId,
  onSelectedEntryIdChange,
}: {
  capability: Capability
  data: DashboardData
  selectedEntryId?: string
  onSelectedEntryIdChange: (entryId: string) => void
}) {
  const display = capability.displayProjection
  const entryTree = resolveCapabilityEntryTree(capability)
  const entries = [entryTree.root, ...entryTree.children]
  const selectedEntry = entries.find((entry) => entry.id === selectedEntryId) ?? entryTree.root
  const archetype = resolveCapabilityDisplayArchetype(capability, entryTree)
  const heroDescription = entryTree.root.purpose
  const heroTitle = normalCapabilityHeroTitle(capability, entryTree, archetype)
  const boundaryItems = normalCapabilityBoundaryItems(capability)
  return (
    <article className={`operator-capability-panel ${archetype}`}>
      <header className="operator-hero">
        <div>
          <div className="operator-label-row">
            <span className="capability-label compact">{capability.rawLabel}</span>
            <ImplementationBadge status={capability.implementationStatus} />
            <span className="operator-badge">{capabilityDisplayArchetypeLabel(archetype)}</span>
            {display.riskBadges.map((badge) => <span key={badge} className="operator-badge">{badge}</span>)}
          </div>
          <h1>{heroTitle}</h1>
          <p>{heroDescription}</p>
        </div>
      </header>

      <CapabilityArchetypeLayout
        archetype={archetype}
        capability={capability}
        data={data}
        entryTree={entryTree}
        selectedEntry={selectedEntry}
        onSelectedEntryIdChange={onSelectedEntryIdChange}
      />

      <section className="entry-evidence-strip">
        <div>
          <h2>边界提醒</h2>
          <p>普通视图只保留操作者能判断入口、输入、产出和下一步的摘要；内部字段放在底部维护信息。</p>
        </div>
        <div className="meta-grid wide">
          {boundaryItems.map((item) => <span key={item}>{item}</span>)}
        </div>
      </section>
    </article>
  )
}

function CapabilityArchetypeLayout({
  archetype,
  capability,
  data,
  entryTree,
  selectedEntry,
  onSelectedEntryIdChange,
}: {
  archetype: CapabilityDisplayArchetype
  capability: Capability
  data: DashboardData
  entryTree: CapabilityEntryTree
  selectedEntry: CapabilityEntryNode
  onSelectedEntryIdChange: (entryId: string) => void
}) {
  if (archetype === 'entry_hub') {
    return (
      <section className="capability-archetype-layout entry-hub-layout" aria-label={`${capability.rawLabel} 操作和分流`}>
        <RoutingRail
          capability={capability}
          data={data}
          entryTree={entryTree}
          selectedEntry={selectedEntry}
          onSelectedEntryIdChange={onSelectedEntryIdChange}
        />
        <OperatorActionPanel capability={capability} entry={selectedEntry} title="操作区" />
      </section>
    )
  }

  if (archetype === 'gate_review') {
    return (
      <section className="capability-archetype-layout gate-review-layout" aria-label={`${capability.rawLabel} 复核对象和状态`}>
        <OperatorActionPanel capability={capability} entry={selectedEntry} title="待检查对象" compact />
        <GateReviewPanel capability={capability} entry={selectedEntry} />
      </section>
    )
  }

  if (archetype === 'creation_handoff') {
    return (
      <section className="capability-archetype-layout creation-handoff-layout" aria-label={`${capability.rawLabel} 创作交接`}>
        <OperatorActionPanel capability={capability} entry={selectedEntry} title="创作输入" />
        <CreationHandoffPanel capability={capability} entry={selectedEntry} data={data} />
      </section>
    )
  }

  if (archetype === 'entity_store') {
    return (
      <section className="capability-archetype-layout compact-archetype-layout" aria-label={`${capability.rawLabel} 入库对象`}>
        <OperatorActionPanel capability={capability} entry={selectedEntry} title="实体输入" compact />
        <EntityStorePanel capability={capability} entry={selectedEntry} />
      </section>
    )
  }

  if (archetype === 'system_maintenance') {
    return (
      <section className="capability-archetype-layout compact-archetype-layout" aria-label={`${capability.rawLabel} 系统操作`}>
        <OperatorActionPanel capability={capability} entry={selectedEntry} title="命令模板" compact />
        <SystemMaintenancePanel capability={capability} entry={selectedEntry} />
      </section>
    )
  }

  return (
    <section className="capability-archetype-layout direct-action-layout" aria-label={`${capability.rawLabel} 任务面板`}>
      <OperatorActionPanel capability={capability} entry={selectedEntry} title="任务输入" compact />
      <DirectActionPanel capability={capability} entry={selectedEntry} data={data} />
    </section>
  )
}

function OperatorActionPanel({
  capability,
  entry,
  title,
  compact = false,
}: {
  capability: Capability
  entry: CapabilityEntryNode
  title: string
  compact?: boolean
}) {
  const [selectedTemplateId, setSelectedTemplateId] = useState(entry.templateId)
  const selectedTemplate =
    entry.inputContract.templates.find((template) => template.id === selectedTemplateId)
    ?? entry.inputContract.templates[0]

  useEffect(() => {
    setSelectedTemplateId(entry.templateId)
  }, [entry.id, entry.templateId])

  return (
    <section className={`operator-action-panel ${compact ? 'compact' : ''}`}>
      <div className="operator-panel-heading">
        <span className="muted-label">{title}</span>
        <h2>{entry.displayName}</h2>
        <p>{entry.purpose}</p>
      </div>
      <div className="operator-field-groups">
        <PlainList title="需要提供" items={[
          ...entry.inputContract.requiredFields.map((item) => `必填：${item}`),
          ...entry.inputContract.optionalFields.map((item) => `选填：${item}`),
        ]} />
        {!compact ? <PlainList title="适合场景" items={capability.displayProjection.whenToUse.slice(0, 4)} /> : null}
      </div>
      <section className="operator-template-block">
        <div className="operator-template-heading">
          <span className="entry-trigger large">{entry.trigger}</span>
          <CopyButton text={selectedTemplate.body} label={copyTemplateLabel(capability)} />
        </div>
        {entry.inputContract.templates.length > 1 ? (
          <div className="template-tabs" role="tablist" aria-label={`${entry.trigger} 输入模板`}>
            {entry.inputContract.templates.map((template) => (
              <button
                key={template.id}
                type="button"
                className={template.id === selectedTemplate.id ? 'active' : ''}
                onClick={() => setSelectedTemplateId(template.id)}
              >
                {template.title}
              </button>
            ))}
          </div>
        ) : null}
        <p>{selectedTemplate.description}</p>
        <pre className="copy-template"><code>{selectedTemplate.body}</code></pre>
        {capability.implementationStatus === 'not_implemented' ? (
          <p className="copy-note">规划中入口发送后会收到待人工处理回执，不代表系统故障。</p>
        ) : null}
      </section>
    </section>
  )
}

function RoutingRail({
  capability,
  data,
  entryTree,
  selectedEntry,
  onSelectedEntryIdChange,
}: {
  capability: Capability
  data: DashboardData
  entryTree: CapabilityEntryTree
  selectedEntry: CapabilityEntryNode
  onSelectedEntryIdChange: (entryId: string) => void
}) {
  const entries = [entryTree.root, ...entryTree.children]
  const nextCapabilities = nextCapabilitiesForEntry(selectedEntry, data)
  const fallbackActions = capability.displayProjection.nextActions
    .map((action) => action.label)
    .filter(Boolean)
  return (
    <aside className="routing-rail">
      <div className="operator-panel-heading">
        <span className="muted-label">{lifecycleName(entryTree.lifecycleLayer)}</span>
        <h2>分流轨道</h2>
        <p>先选入口，再看会得到什么和可以接到哪里。</p>
      </div>
      <div className="routing-step-list">
        {entries.map((entry, index) => (
          <button
            key={entry.id}
            type="button"
            className={`routing-step ${selectedEntry.id === entry.id ? 'active' : ''}`}
            onClick={() => onSelectedEntryIdChange(entry.id)}
          >
            <span className="routing-step-index">{index + 1}</span>
            <span>
              <strong>{entry.trigger}</strong>
              <small>{entry.displayName}</small>
            </span>
          </button>
        ))}
      </div>
      <div className="route-outcome">
        <PlainList title="会做" items={selectedEntry.outputContract.userReplySections.slice(0, 4)} />
        <PlainList title="不会做" items={capability.displayProjection.whenNotToUse.slice(0, 4)} tone="warning" />
      </div>
      {nextCapabilities.length ? (
        <section className="rail-next">
          <h3>下一步</h3>
          <div className="operator-action-row">
            {nextCapabilities.map((capability) => (
              <Link key={capability.id} className="button secondary" to={`/capabilities/detail/${capability.id}`}>
                {capability.rawLabel} <ArrowRight size={16} aria-hidden="true" />
              </Link>
            ))}
          </div>
        </section>
      ) : fallbackActions.length ? (
        <PlainList title="下一步" items={fallbackActions.slice(0, 5)} />
      ) : null}
    </aside>
  )
}

function DirectActionPanel({ capability, entry, data }: { capability: Capability; entry: CapabilityEntryNode; data: DashboardData }) {
  const nextCapabilities = nextCapabilitiesForEntry(entry, data)
  return (
    <section className="operator-outcome-panel direct-outcome">
      <div className="operator-panel-heading">
        <span className="muted-label">结果</span>
        <h2>输出和下一步</h2>
        <p>{entry.outputContract.summary}</p>
      </div>
      <div className="operator-field-groups">
        <PlainList title="会输出" items={entry.outputContract.userReplySections} />
        <PlainList title="沉淀位置" items={entry.outputContract.writesTo} />
        <PlainList title="边界" items={capability.displayProjection.whenNotToUse.concat(capability.outputDetail.boundaries).slice(0, 5)} tone="warning" />
      </div>
      {nextCapabilities.length ? <NextCapabilityActions capabilities={nextCapabilities} /> : null}
    </section>
  )
}

function GateReviewPanel({ capability, entry }: { capability: Capability; entry: CapabilityEntryNode }) {
  const evidenceItems = uniqueItems([
    ...capability.displayProjection.evidenceSummary,
    ...entry.outputContract.artifacts,
    ...capability.outputDetail.contentForms,
  ]).slice(0, 6)
  return (
    <section className="operator-outcome-panel gate-outcome">
      <div className="operator-panel-heading">
        <span className="muted-label">状态判断</span>
        <h2>通过、返修、缺证据</h2>
        <p>{entry.outputContract.summary}</p>
      </div>
      <div className="status-matrix" aria-label="复核状态">
        <StatusCell label="通过" detail={entry.outputContract.userReplySections[0] ?? '检查项满足要求时给出通过结论。'} />
        <StatusCell label="返修" detail={capability.outputDetail.boundaries[0] ?? capability.displayProjection.whenNotToUse[0] ?? '不满足要求时给出返修原因。'} tone="warning" />
        <StatusCell label="缺证据" detail={evidenceItems[0] ?? '证据不足时保留待补充状态。'} tone="warning" />
        <StatusCell label="待人工确认" detail={capability.implementationStatus === 'not_implemented' ? '规划中入口只返回待人工处理。' : '高风险结论保留人工确认。'} />
      </div>
      <PlainList title="证据要求" items={evidenceItems} />
      <PlainList title="不会自动执行" items={capability.displayProjection.whenNotToUse.concat(capability.outputDetail.boundaries).slice(0, 5)} tone="warning" />
    </section>
  )
}

function CreationHandoffPanel({
  capability,
  entry,
  data,
}: {
  capability: Capability
  entry: CapabilityEntryNode
  data: DashboardData
}) {
  const nextCapabilities = nextCapabilitiesForEntry(entry, data)
  const boundaries = creationBoundaries(capability)
  return (
    <section className="operator-outcome-panel creation-outcome">
      <div className="operator-panel-heading">
        <span className="muted-label">交付物</span>
        <h2>创作记录和后续节点</h2>
        <p>{entry.outputContract.summary}</p>
      </div>
      <div className="handoff-columns">
        <PlainList title="交付物" items={uniqueItems([...entry.outputContract.artifacts, ...capability.outputDetail.contentForms]).slice(0, 6)} />
        <PlainList title="保存 / 返回" items={entry.outputContract.writesTo.concat(capability.displayProjection.savedAs).filter(Boolean).slice(0, 5)} />
      </div>
      <PlainList title="边界" items={boundaries} tone="warning" />
      {nextCapabilities.length ? <NextCapabilityActions capabilities={nextCapabilities} title="可交接到" /> : null}
    </section>
  )
}

function EntityStorePanel({ capability, entry }: { capability: Capability; entry: CapabilityEntryNode }) {
  return (
    <section className="operator-outcome-panel entity-outcome">
      <div className="operator-panel-heading">
        <span className="muted-label">保存对象</span>
        <h2>入库、更新和复核</h2>
        <p>{entry.outputContract.summary}</p>
      </div>
      <div className="operator-field-groups">
        <PlainList title="会保存" items={uniqueItems([...entry.outputContract.artifacts, ...capability.outputDetail.contentForms, capability.displayProjection.savedAs]).filter(Boolean).slice(0, 6)} />
        <PlainList title="复核状态" items={capability.displayProjection.outputSummary.concat(capability.outputDetail.nextActions).slice(0, 5)} />
        <PlainList title="隐私 / 边界" items={capability.displayProjection.whenNotToUse.concat(capability.outputDetail.boundaries).slice(0, 5)} tone="warning" />
      </div>
    </section>
  )
}

function SystemMaintenancePanel({ capability, entry }: { capability: Capability; entry: CapabilityEntryNode }) {
  return (
    <section className="operator-outcome-panel system-outcome">
      <div className="operator-panel-heading">
        <span className="muted-label">结果状态</span>
        <h2>预览、确认和回执</h2>
        <p>{entry.outputContract.summary}</p>
      </div>
      <div className="operator-field-groups">
        <PlainList title="返回内容" items={entry.outputContract.userReplySections.concat(capability.outputDetail.contentForms).slice(0, 6)} />
        <PlainList title="确认门槛" items={systemConfirmationItems(capability)} tone="warning" />
        <PlainList title="输出位置" items={entry.outputContract.writesTo} />
      </div>
    </section>
  )
}

function NextCapabilityActions({ capabilities, title = '下一步' }: { capabilities: Capability[]; title?: string }) {
  return (
    <section className="rail-next">
      <h3>{title}</h3>
      <div className="operator-action-row">
        {capabilities.map((capability) => (
          <Link key={capability.id} className="button secondary" to={`/capabilities/detail/${capability.id}`}>
            {capability.rawLabel} <ArrowRight size={16} aria-hidden="true" />
          </Link>
        ))}
      </div>
    </section>
  )
}

function StatusCell({ label, detail, tone }: { label: string; detail: string; tone?: 'warning' }) {
  return (
    <div className={`status-cell ${tone ?? ''}`}>
      <strong>{label}</strong>
      <span>{detail}</span>
    </div>
  )
}

function PlainList({ title, items, tone }: { title: string; items: string[]; tone?: 'warning' }) {
  const visibleItems = uniqueItems(items).filter(Boolean)
  if (!visibleItems.length) return null
  return (
    <section className={`plain-list ${tone ?? ''}`}>
      <h3>{title}</h3>
      <ul>
        {visibleItems.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  )
}

function resolveCapabilityEntryTree(capability: Capability): CapabilityEntryTree {
  return capability.entryTree ?? buildSingleEntryTree(capability)
}

function buildSingleEntryTree(capability: Capability): CapabilityEntryTree {
  return {
    lifecycleLayer: capability.displayProjection.lifecycleLayer,
    root: buildSingleEntryNode(capability),
    children: [],
  }
}

function buildSingleEntryNode(capability: Capability): CapabilityEntryNode {
  const display = capability.displayProjection
  const output = capability.outputDetail
  const templates = capability.quickCopyTemplates.length
    ? capability.quickCopyTemplates
    : [{
        id: 'default',
        title: '默认模板',
        description: '按当前能力默认输入格式发送。',
        body: capability.defaultInputTemplate,
      }]
  const templateId = templates[0]?.id ?? 'default'
  const nextCapabilityIds = display.nextActions
    .map((action) => action.targetCapabilityId)
    .filter((id): id is string => Boolean(id))
  const requiredFields = inputFieldsFromTemplates(templates[0]?.body ?? '') || display.requiredInputs
  const writesTo = output.destinations.length ? output.destinations : ['当前 Bot 回复']
  return {
    id: capability.id,
    capabilityId: capability.id,
    trigger: capability.rawLabel,
    displayName: display.displayTitle,
    purpose: display.operatorSummary || display.displaySubtitle,
    entryRole: 'root_entry',
    dispatchMode: 'direct',
    recommended: true,
    canonicalCapabilityId: capability.canonicalCapabilityId,
    inputContract: {
      title: `${capability.rawLabel} 输入格式`,
      summary: display.whenToUse[0] ?? display.operatorSummary,
      requiredFields,
      optionalFields: requiredFields === display.requiredInputs ? display.optionalInputs : [],
      templates,
    },
    outputContract: {
      summary: display.outputSummary.slice(0, 2).join(' / ') || capability.description,
      userReplySections: display.outputSummary.length ? display.outputSummary : output.contentForms,
      artifacts: output.contentForms.length ? output.contentForms : ['能力输出'],
      writesTo,
      nextActions: display.nextActions
        .map((action) => action.label)
        .filter(Boolean)
        .concat(output.nextActions)
        .filter((item, index, items) => items.indexOf(item) === index),
    },
    nextCapabilityIds,
    templateId,
    supportedAttachments: ['text'],
    riskLevel: display.riskBadges[1] ?? display.riskBadges[0] ?? '风险待确认',
    visibility: capability.sensitivity,
  }
}

function inputFieldsFromTemplates(templateBody: string) {
  const fields = templateBody
    .split('\n')
    .slice(1)
    .map((line) => line.split('：', 1)[0]?.trim())
    .filter((field): field is string => Boolean(field))
  return fields.length ? Array.from(new Set(fields)) : null
}

function CapabilityMatrixPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  const [filter, setFilter] = useState<'all' | 'main' | 'common' | 'cross' | 'available'>('all')
  const capabilities = capabilitiesForView(data.capabilities, viewMode).filter((capability) => {
    if (filter === 'main') return capability.type === 'main'
    if (filter === 'common') return capability.type === 'common'
    if (filter === 'cross') return capability.visibleBots.length > 1
    if (filter === 'available') return capability.implementationStatus === 'implemented'
    return true
  })

  return (
    <main>
      <PageHeader
        label="能力对照"
        title="四 Bot 能力矩阵"
        description="原生表格展示主能力、可见、不可见。能力数量不大，第一版不做分页。"
      />
      <div className="segmented-control" role="group" aria-label="矩阵筛选">
        {[
          ['all', '全部'],
          ['main', '主能力'],
          ['common', '通用能力'],
          ['cross', '跨 Bot'],
          ['available', '仅可用'],
        ].map(([value, label]) => (
          <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value as typeof filter)} type="button">
            {label}
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>能力标签</th>
              <th>实装状态</th>
              <th>分类</th>
              {data.bots.map((bot) => <th key={bot.id}>{botNames[bot.id]}</th>)}
            </tr>
          </thead>
          <tbody>
            {capabilities.map((capability) => (
              <tr key={capability.id}>
                <th>
                  <Link to={`/capabilities/detail/${capability.id}`}>{capability.rawLabel}</Link>
                  <small>{capability.title}</small>
                </th>
                <td><ImplementationBadge status={capability.implementationStatus} compact /></td>
                <td>{categoryNames[capability.category]}</td>
                {data.bots.map((bot) => (
                  <td key={bot.id}>
                    <AvailabilityBadge value={capability.botAvailability[bot.id]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  )
}

function LinksPage({ data, viewMode }: { data: DashboardData; viewMode: ViewMode }) {
  const links = viewMode === 'maintainer' ? data.links : data.links.filter((link) => link.visibility === 'normal')
  const groups = groupBy(links, (link) => link.group)
  return (
    <main>
      <PageHeader
        label="跳转"
        title="跳转中心"
        description="汇总 Bot 对话入口、能力说明入口和协作文档入口。无效或未知链接会显示状态。"
      />
      <div className="link-groups">
        {Object.entries(groups).map(([group, items]) => (
          <section key={group} className="section-block">
            <SectionTitle title={linkGroupName(group)} count={items.length} />
            <div className="link-list">
              {items.map((link) => <LinkCard key={link.id} link={link} />)}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}

function MediaWorkflowPanel({ flow, capabilities }: { flow: Flow; capabilities: Capability[] }) {
  const capabilityMap = new Map(capabilities.map((capability) => [capability.id, capability]))
  const decisionStages = flow.stages.filter((stage) =>
    ['cloud-project-package', 'local-binding-gate', 'mac-material-analysis', 'output-review-writeback'].includes(stage.id),
  )
  return (
    <article className="media-workflow-panel">
      <div className="media-workflow-copy">
        <span className="muted-label">Media 专属路径</span>
        <h2>{flow.title}</h2>
        <p>{flow.description}</p>
        <div className="workflow-questions" aria-label="这个地图回答的问题">
          <span>项目现在卡在哪一步</span>
          <span>接下来该谁处理</span>
          <span>需要交给下一方什么</span>
        </div>
        <Link className="button" to={`/flows/${flow.id}`}>
          打开协同地图 <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
      <div className="workflow-checkpoints">
        {decisionStages.map((stage) => {
          const stageCapabilities = stage.relatedCapabilityIds.map((id) => capabilityMap.get(id)).filter(Boolean) as Capability[]
          return (
          <div key={stage.id} className={`workflow-checkpoint ${stageImplementationTone(stageCapabilities)}`}>
            <span className={`owner-badge ${stage.owner}`}>{flowOwnerNames[stage.owner]}</span>
            <StageImplementationSummary capabilities={stageCapabilities} compact />
            <strong>{stage.title}</strong>
            <small>{stage.handoffArtifacts.slice(0, 2).join(' / ')}</small>
          </div>
          )
        })}
      </div>
    </article>
  )
}

function FlowStagePanel({ stage, capabilities }: { stage: Flow['stages'][number]; capabilities: Capability[] }) {
  return (
    <section className="flow-stage-panel">
      <div className="flow-stage-heading">
        <span className={`owner-badge ${stage.owner}`}>{flowOwnerNames[stage.owner]}</span>
        <StageImplementationSummary capabilities={capabilities} />
        <h2>{stage.title}</h2>
        <p>{stage.summary}</p>
      </div>
      <div className="stage-decision-grid">
        <InfoPanel title="什么时候用这一步" items={stage.entryConditions} />
        <InfoPanel title="做到什么算完成" items={stage.completionSignals} />
        <InfoPanel title="常见卡点" items={stage.blockers} tone="warning" />
        <InfoPanel title="交给下一环节的材料" items={stage.handoffArtifacts} />
      </div>
      <div className="stage-info-grid">
        <InfoPanel title="要准备什么" items={stage.inputs} />
        <InfoPanel title="会得到什么" items={stage.outputs} />
        <InfoPanel title="这一步不要做什么" items={stage.boundaries} tone="warning" />
      </div>
      <section className="section-block compact-section">
        <SectionTitle title="相关能力" count={capabilities.length} />
        <div className="chip-cloud">
          {capabilities.map((capability) => <CapabilityChip key={capability.id} capability={capability} />)}
        </div>
      </section>
      <section className="next-step-panel">
        <strong>下一步</strong>
        <p>{stage.nextStep}</p>
      </section>
    </section>
  )
}

function CapabilityList({
  capabilities,
  viewMode,
  emptyText = '暂无能力。',
}: {
  capabilities: Capability[]
  viewMode: ViewMode
  emptyText?: string
}) {
  if (!capabilities.length) {
    return <div className="empty-inline">{emptyText}</div>
  }
  return (
    <div className="capability-list">
      {capabilities.map((capability) => (
        <article key={capability.id} className={`capability-row ${capability.implementationStatus === 'not_implemented' ? 'is-planned' : ''}`}>
          <div>
            <div className="capability-row-labels">
              <Link className="capability-label" to={`/capabilities/detail/${capability.id}`}>{capability.rawLabel}</Link>
              <ImplementationBadge status={capability.implementationStatus} />
            </div>
            <h3>{capability.title}</h3>
            <p>{capability.description}</p>
            {viewMode === 'normal' && capability.entryTree ? <EntryTreePreview capability={capability} /> : null}
            {viewMode === 'maintainer' ? (
              <div className="meta-grid">
                <span>{typeNames[capability.type]}</span>
                <span>{categoryNames[capability.category]}</span>
                <span>主归属：{botNames[capability.primaryBot]}</span>
                <span>可见：{capability.visibleBots.map((bot) => botNames[bot]).join(' / ')}</span>
              </div>
            ) : null}
          </div>
          <div className="row-actions">
            <Badge>{typeNames[capability.type]}</Badge>
            <span className="copy-with-status">
              <CopyButton text={capability.defaultInputTemplate} label={copyTemplateLabel(capability)} compact />
              {capability.implementationStatus === 'not_implemented' ? <small>规划中</small> : null}
            </span>
            <Link className="icon-link" to={`/capabilities/detail/${capability.id}`} aria-label={`查看 ${capability.rawLabel}`}>
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
        </article>
      ))}
    </div>
  )
}

function EntryTreePreview({ capability }: { capability: Capability }) {
  const tree = capability.entryTree
  if (!tree || tree.children.length === 0) return null
  return (
    <div className="entry-preview">
      <span>推荐发送：{tree.root.trigger}</span>
      <div>
        {tree.children.slice(0, 5).map((entry) => (
          <Link key={entry.id} to={`/capabilities/detail/${capability.id}?entry=${encodeURIComponent(entry.id)}`}>
            <b>{entry.trigger}</b>
            <small>{entry.displayName}</small>
          </Link>
        ))}
      </div>
    </div>
  )
}

function CapabilityChip({ capability }: { capability: Capability }) {
  return (
    <Link className="capability-chip" to={`/capabilities/detail/${capability.id}`}>
      {capability.rawLabel}
    </Link>
  )
}

function CapabilityExecutionGraphPanel({
  graph,
  contracts,
}: {
  graph: Capability['executionGraph']
  contracts: Capability['llmPromptContracts']
}) {
  const [activeNodeId, setActiveNodeId] = useState(graph.nodes[0]?.id ?? '')
  const viewportRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const [nodeWidth, setNodeWidth] = useState(248)
  const [graphLayout, setGraphLayout] = useState<ExecutionGraphLayout | null>(null)
  const incomingConditions = useMemo(() => executionBranchLabelsByTarget(graph), [graph])
  const edgeMarkerId = useMemo(() => `execution-edge-arrow-${graph.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`, [graph.id])
  const nodeWidthsById = useMemo(() => {
    const connectionCounts = new Map<string, number>()
    for (const edge of graph.edges) {
      connectionCounts.set(edge.from, Math.max(connectionCounts.get(edge.from) ?? 0, graph.edges.filter((item) => item.from === edge.from).length))
      connectionCounts.set(edge.to, Math.max(connectionCounts.get(edge.to) ?? 0, graph.edges.filter((item) => item.to === edge.to).length))
    }
    return new Map(graph.nodes.map((node) => {
      const connectionCount = connectionCounts.get(node.id) ?? 0
      const width = nodeWidth < 48 && connectionCount > 4
        ? Math.min(MAX_OVERVIEW_JUNCTION_WIDTH, nodeWidth + (connectionCount - 4) * 8)
        : nodeWidth
      return [node.id, width]
    }))
  }, [graph.edges, graph.nodes, nodeWidth])
  const activeNode = graph.nodes.find((node) => node.id === activeNodeId) ?? graph.nodes[0]
  const activeContract = activeNode?.promptContractId
    ? contracts.find((contract) => contract.id === activeNode.promptContractId)
    : undefined

  useEffect(() => {
    setActiveNodeId(graph.nodes[0]?.id ?? '')
    setGraphLayout(null)
  }, [graph])

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    const canvas = canvasRef.current
    if (!viewport || !canvas) return
    let frame = 0
    const update = () => {
      const nextWidth = recommendedExecutionNodeWidth(viewport.clientWidth, graph.nodes, graph.edges)
      if (Math.abs(nextWidth - nodeWidth) > 0.5) {
        setNodeWidth(nextWidth)
        return
      }
      const inputs = graph.nodes.map((node, index) => {
        const element = canvas.querySelector<HTMLElement>(`[data-execution-node-id="${CSS.escape(node.id)}"]`)
        return {
          id: node.id,
          index,
          width: nodeWidthsById.get(node.id) ?? nodeWidth,
          height: Math.max(78, element?.offsetHeight ?? 78),
        }
      })
      setGraphLayout(layoutExecutionGraph(inputs, graph.edges.map((edge, index) => ({ ...edge, index }))))
    }
    const schedule = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(update)
    }
    schedule()
    const observer = new ResizeObserver(schedule)
    observer.observe(viewport)
    canvas.querySelectorAll<HTMLElement>('[data-execution-node-id]').forEach((element) => observer.observe(element))
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [graph, nodeWidth, nodeWidthsById])

  if (!activeNode) return null
  const isActualPrompt = activeNode.nodeType === 'actual_llm_prompt'
  const bodyText = activeContract?.promptBody ?? activeNode.body
  const activeTerminalKind = executionTerminalKind(activeNode.terminalState)
  const nodesById = new Map(graphLayout?.nodes.map((node) => [node.id, node]) ?? [])

  return (
    <div className="execution-graph-panel" data-auto-generated-graph={graph.graphKind === 'manual' ? 'false' : 'true'}>
      <div className="execution-graph-debug-layout">
        <div className="execution-graph-view" aria-label={`${graph.title} 节点`}>
          <div className="execution-graph-summary">
            <strong>{graph.title}</strong>
            <span>{graph.summary}</span>
          </div>
          <div className="execution-graph-canvas-scroll" ref={viewportRef}>
            <div
              className="execution-graph-canvas"
              ref={canvasRef}
              data-layout-ready={graphLayout ? 'true' : 'false'}
              style={graphLayout ? { width: graphLayout.width, height: graphLayout.height } : undefined}
            >
              {graphLayout ? (
                <svg className="execution-graph-edges" viewBox={`0 0 ${graphLayout.width} ${graphLayout.height}`} aria-label={`${graph.title} 的 ${graph.edges.length} 条连接`}>
                  <defs><marker id={edgeMarkerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker></defs>
                  {graphLayout.edges.map((edge) => {
                    const source = graph.edges[edge.index]
                    const label = source?.label
                    const labelText = label && edge.labelWidth ? executionEdgeLabelText(label, edge.labelWidth) : undefined
                    const labelWidth = labelText && edge.labelWidth ? executionEdgeLabelWidth(labelText, edge.labelWidth) : undefined
                    return (
                      <g key={`${edge.from}-${edge.to}`} className="execution-graph-edge" data-edge-from={edge.from} data-edge-to={edge.to}>
                        <path d={edge.path} markerEnd={`url(#${edgeMarkerId})`} />
                        {labelText && labelWidth && edge.labelX !== undefined && edge.labelY !== undefined ? (
                          <g className="execution-edge-label" data-edge-label={label} transform={`translate(${edge.labelX - labelWidth / 2} ${edge.labelY - 14})`}>
                            <rect width={labelWidth} height="28" rx="4" /><text x={labelWidth / 2} y="18" textAnchor="middle">{labelText}</text>
                          </g>
                        ) : null}
                      </g>
                    )
                  })}
                </svg>
              ) : null}
              <div className="execution-graph-nodes">
                {graph.nodes.map((node, index) => {
                  const layoutNode = nodesById.get(node.id)
                  const terminalKind = executionTerminalKind(node.terminalState)
                  const condition = incomingConditions.get(node.id)
                  return (
                    <button
                      key={node.id}
                      type="button"
                      data-execution-node-id={node.id}
                      data-terminal-state={node.terminalState}
                      data-terminal-kind={terminalKind}
                      data-incoming-condition={condition}
                      className={`${node.id === activeNode.id ? 'active' : ''} ${terminalKind === 'manual' ? 'manual-terminal-node' : ''}`}
                      style={layoutNode ? { left: layoutNode.x - layoutNode.width / 2, top: layoutNode.y - layoutNode.height / 2, width: layoutNode.width } : { width: nodeWidthsById.get(node.id) }}
                      onClick={() => setActiveNodeId(node.id)}
                    >
                      <span className="execution-node-index">{index + 1}</span>
                      <span><strong>{node.title}</strong><small>{executionNodeTypeLabel(node.nodeType)}</small></span>
                      {condition ? <b className="incoming-condition-badge">{condition}</b> : null}
                      {node.terminalState ? <b className="terminal-state-badge">{executionStateLabel(node.terminalState)}</b> : null}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
        <article
          className={`execution-node-detail ${activeTerminalKind ? 'terminal-node-detail' : ''}`}
          data-validator-contract={activeContract?.postValidation ? 'bound' : undefined}
          data-validator-profile={activeContract?.postValidation?.profile}
        >
          <div className="execution-node-heading">
            <div>
              <em className={`node-type-badge ${activeNode.nodeType}`}>{executionNodeTypeLabel(activeNode.nodeType)}</em>
              <h3>{activeNode.title}</h3>
              <p>{executionNodeTypeLabel(activeNode.nodeType)}</p>
            </div>
            <CopyButton
              text={formatExecutionNodeForCopy(activeNode, activeContract)}
              label={isActualPrompt ? '复制该 LLM Prompt' : '复制该节点说明'}
            />
          </div>
          <dl className="execution-node-meta">
            <div>
              <dt>阶段类型</dt>
              <dd>{executionNodeTypeLabel(activeNode.nodeType)}</dd>
            </div>
            <div>
              <dt>内容性质</dt>
              <dd>{isActualPrompt ? '源码或契约定义的提示词正文' : `${executionNodeBodyTitle(activeNode.nodeType)}，非直接 LLM prompt`}</dd>
            </div>
            {activeContract?.postValidation ? <div><dt>完成校验</dt><dd>{validationProfileLabel(activeContract.postValidation.profile)} · {activeContract.postValidation.states.map(executionStateLabel).join(' / ')}</dd></div> : null}
            {activeNode.terminalState ? <div><dt>终止状态</dt><dd>{executionStateLabel(activeNode.terminalState)}</dd></div> : null}
          </dl>
          <div className="execution-node-contract-grid">
            <InfoPanel title="输入边界" items={activeNode.inputBoundary} />
            <InfoPanel title="输出契约" items={activeNode.outputContract} />
            <InfoPanel title="写入目标" items={activeNode.writesTo} />
            <InfoPanel title="完成信号" items={activeNode.completionSignals} />
          </div>
          <div className="execution-node-body">
            <div className="execution-node-body-title">
              {isActualPrompt ? '真实送入 LLM 的提示词' : executionNodeBodyTitle(activeNode.nodeType)}
            </div>
            <pre><code>{bodyText}</code></pre>
          </div>
        </article>
      </div>
    </div>
  )
}

function executionBranchLabelsByTarget(graph: Capability['executionGraph']) {
  const labels = new Map<string, string>()
  for (const edge of graph.edges) if (edge.label) labels.set(edge.to, edge.label)
  return labels
}

function executionBranchCount(graph: Capability['executionGraph']) {
  const outgoing = new Map<string, number>()
  for (const edge of graph.edges) outgoing.set(edge.from, (outgoing.get(edge.from) ?? 0) + 1)
  return [...outgoing.values()].filter((count) => count > 1).length
}

function executionTerminalKind(state?: string) {
  if (!state) return ''
  if (/manual|pending|review/i.test(state)) return 'manual'
  if (/fail|block|error/i.test(state)) return 'failed'
  return 'complete'
}

function executionNodeBodyTitle(type: Capability['executionGraph']['nodes'][number]['nodeType']) {
  if (type === 'actual_llm_prompt') return '真实送入 LLM 的提示词'
  if (type === 'bitable_write') return '多维表格写入契约'
  if (type === 'document_render') return '文档渲染契约'
  if (type === 'quality_check') return '完成校验契约'
  if (type === 'generated_execution_contract') return '生成的执行契约'
  if (type === 'vision_read') return '视觉读取契约'
  return '执行阶段契约'
}

function formatExecutionNodeForCopy(
  node: Capability['executionGraph']['nodes'][number],
  contract?: Capability['llmPromptContracts'][number],
) {
  return [
    node.title,
    `类型：${executionNodeTypeLabel(node.nodeType)}`,
    '',
    contract?.promptBody ?? node.body,
  ].join('\n')
}

function CopyButton({
  text,
  label,
  compact = false,
  variant = 'primary',
}: {
  text: string
  label: string
  compact?: boolean
  variant?: 'primary' | 'secondary'
}) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    await copyText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <button
      type="button"
      className={`copy-button ${compact ? 'compact' : ''} ${variant}`}
      onClick={handleCopy}
      title={label}
    >
      {copied ? <Check size={16} aria-hidden="true" /> : <Clipboard size={16} aria-hidden="true" />}
      {!compact ? <span>{copied ? '已复制' : label}</span> : null}
    </button>
  )
}

function AvailabilityBadge({ value }: { value: Capability['botAvailability'][BotId] }) {
  return <span className={`availability-badge ${value}`}>{availabilityNames[value]}</span>
}

function InfoPanel({ title, items, tone }: { title: string; items: string[]; tone?: 'warning' }) {
  return (
    <section className={`info-panel ${tone ?? ''}`}>
      <h2>{title}</h2>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  )
}

function OutputGroup({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="output-group">
      <strong>{title}</strong>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  )
}

function LinkCard({ link }: { link: LinkItem }) {
  return (
    <a className="link-card" href={link.url}>
      <span className="icon-tile"><LinkIcon size={18} aria-hidden="true" /></span>
      <span>
        <strong>{link.title}</strong>
        <small>{link.description}</small>
      </span>
      <span className={`status-pill ${link.status}`}>{link.status}</span>
      <ExternalLink size={16} aria-hidden="true" />
    </a>
  )
}

function BoundaryNotice({ compact = false }: { compact?: boolean }) {
  return (
    <section className={`boundary-notice ${compact ? 'compact' : ''}`}>
      <ShieldCheck size={20} aria-hidden="true" />
      <div>
        <strong>公开能力中心只展示可公开说明。</strong>
        <p>Social bot 不展示具体人名、关系细节或聊天原文；本地素材不展示真实路径或文件内容；底部维护信息不是权限控制。</p>
      </div>
    </section>
  )
}

function PageHeader({
  label,
  title,
  description,
  icon,
  meta,
}: {
  label: string
  title: string
  description: string
  icon?: ReactNode
  meta?: ReactNode
}) {
  const isCapabilityLabel = label.startsWith('【') && label.endsWith('】')
  const capabilitySummaryParts = isCapabilityLabel
    ? formatCapabilitySummaryParts(title, description)
    : []
  return (
    <header className={`page-header ${isCapabilityLabel ? 'capability-page-header' : ''}`}>
      <div className={`header-label ${isCapabilityLabel ? 'capability-header-label' : ''}`}>
        {icon}
        <span>{label}</span>
        {meta ? <span className="header-meta">{meta}</span> : null}
      </div>
      {isCapabilityLabel ? (
        <h1 className="capability-summary-line">
          {capabilitySummaryParts.map((part, index) => (
            <span key={`${part.label}-${part.text}`} className="capability-summary-part">
              <span>{part.label}：</span>{part.text}
              {index < capabilitySummaryParts.length - 1 ? <span>；</span> : null}
            </span>
          ))}
        </h1>
      ) : (
        <>
          <h1>{title}</h1>
          <p>
            {formatHeaderDescription(description).map((line) => (
              <span key={line} className="header-description-line">{line}</span>
            ))}
          </p>
        </>
      )}
    </header>
  )
}

function formatHeaderDescription(description: string) {
  return description
    .split(/；\s*/)
    .map((line) => line.trim())
    .filter(Boolean)
}

function formatCapabilitySummaryParts(title: string, description: string) {
  return [
    { label: '能力', text: title },
    ...formatHeaderDescription(description).map((line, index) => ({
      label: capabilitySummaryLabelFor(line, index),
      text: line,
    })),
  ]
}

function capabilitySummaryLabelFor(line: string, index: number) {
  if (/保存|原始表达|上下文|时序索引/.test(line)) return '保存'
  if (/大文件|附件|iCloud|缓存/.test(line)) return '附件'
  if (/写入|同步|输出|生成|整理|识别/.test(line)) return '产出'
  if (/只|不得|不能|不用于|不展示|边界/.test(line)) return '边界'
  return index === 0 ? '说明' : `补充${index}`
}

function SectionTitle({ title, action, count }: { title: string; action?: ReactNode; count?: number }) {
  return (
    <div className="section-title">
      <h2>{title}{typeof count === 'number' ? <span>{count}</span> : null}</h2>
      {action ? <div className="section-action">{action}</div> : null}
    </div>
  )
}


function resolveCapabilityDisplayArchetype(
  capability: Capability,
  entryTree: CapabilityEntryTree,
): CapabilityDisplayArchetype {
  const explicit = normalizeDisplayArchetype(capability.displayProjection.displayArchetype)
    ?? normalizeDisplayArchetype((capability as CapabilityWithLegacyDisplayArchetype).displayArchetype)
  if (explicit) return explicit

  const labelText = [
    capability.rawLabel,
    capability.title,
    capability.displayProjection.displayTitle,
    capability.displayProjection.operatorSummary,
  ].join(' ')
  const hasEntryRail = Boolean(capability.entryTree) && (
    entryTree.children.length > 0
    || capability.displayProjection.nextActions.length >= 4
  )
  if (hasEntryRail) return 'entry_hub'
  if (capability.category === 'review' || /复核|检查|验收/.test(labelText)) return 'gate_review'
  if (capability.category === 'creation' && /创作|拍摄执行|发布包|商单交付/.test(labelText)) return 'creation_handoff'
  if (
    capability.category === 'entity'
    || capability.category === 'wardrobe'
    || capability.category === 'business'
    || (capability.category === 'social' && capability.type !== 'boundary')
    || /入库|档案|账号|博主|衣橱|商务/.test(labelText)
  ) return 'entity_store'
  if (
    capability.category === 'system'
    || capability.category === 'development'
    || capability.type === 'boundary'
    || /删除|同步|状态|说明|最近|开发/.test(labelText)
  ) return 'system_maintenance'
  return 'direct_action'
}

function normalizeDisplayArchetype(value?: string): CapabilityDisplayArchetype | null {
  if (!value) return null
  const normalized = value.trim().toLowerCase().replace(/[\s/-]+/g, '_')
  const aliases: Record<string, CapabilityDisplayArchetype> = {
    entry_hub: 'entry_hub',
    hub: 'entry_hub',
    direct_action: 'direct_action',
    action: 'direct_action',
    gate_review: 'gate_review',
    gate: 'gate_review',
    review: 'gate_review',
    creation_handoff: 'creation_handoff',
    handoff: 'creation_handoff',
    entity_store: 'entity_store',
    entity: 'entity_store',
    system_maintenance: 'system_maintenance',
    system: 'system_maintenance',
    maintenance: 'system_maintenance',
  }
  return aliases[normalized] ?? null
}

function capabilityDisplayArchetypeLabel(archetype: CapabilityDisplayArchetype) {
  const labels: Record<CapabilityDisplayArchetype, string> = {
    entry_hub: '入口枢纽',
    direct_action: '单动作',
    gate_review: '门禁复核',
    creation_handoff: '创作交接',
    entity_store: '实体入库',
    system_maintenance: '系统操作',
  }
  return labels[archetype]
}

function normalCapabilityHeroTitle(
  capability: Capability,
  entryTree: CapabilityEntryTree,
  archetype: CapabilityDisplayArchetype,
) {
  if (archetype === 'entry_hub' && capability.entryTree) return entryTree.root.displayName
  return capability.displayProjection.displayTitle
}

function normalCapabilityBoundaryItems(capability: Capability) {
  const boundaryItems = uniqueItems([
    ...capability.displayProjection.whenNotToUse,
    ...capability.outputDetail.boundaries,
  ]).filter((item) => !looksLikeMaintainerTerm(item))
  return boundaryItems.length ? boundaryItems.slice(0, 5) : ['页面只生成可复制输入和公开说明，不直接代替 Bot 执行业务动作。']
}

function looksLikeMaintainerTerm(text: string) {
  return /SourceAsset|CreationRun|media_vault|source_assets|artifact|adapter|handler|runner|contract|canonical|03_CreationRuns|[_/][a-z0-9_-]+/i.test(text)
}

function nextCapabilitiesForEntry(entry: CapabilityEntryNode, data: DashboardData) {
  return entry.nextCapabilityIds
    .map((id) => data.capabilities.find((capability) => capability.id === id))
    .filter((capability): capability is Capability => Boolean(capability))
}

function uniqueItems(items: Array<string | undefined | null>) {
  return Array.from(new Set(items.map((item) => item?.trim()).filter((item): item is string => Boolean(item))))
}

function creationBoundaries(capability: Capability) {
  const boundaryItems = uniqueItems([
    ...capability.displayProjection.whenNotToUse,
    ...capability.outputDetail.boundaries,
  ])
  return boundaryItems.length ? boundaryItems : ['页面只生成可复制输入和交付说明，不直接发布内容。']
}

function systemConfirmationItems(capability: Capability) {
  const contract = capability.deletionContract
  if (capability.id === 'delete' || capability.rawLabel === '【删除】') {
    return [
      contract.previewRequired ? '未确认时只预览目标' : '允许直接执行',
      contract.confirmationRequired ? '确认删除后才执行' : '无需二次确认',
      ...capability.outputDetail.boundaries,
    ]
  }
  return uniqueItems([
    ...capability.displayProjection.whenNotToUse,
    ...capability.outputDetail.boundaries,
    capability.implementationStatus === 'not_implemented' ? '规划中入口只返回待人工处理。' : undefined,
  ])
}

function initialViewMode(): ViewMode {
  const search = new URLSearchParams(window.location.search)
  const hashQuery = window.location.hash.includes('?') ? window.location.hash.slice(window.location.hash.indexOf('?') + 1) : ''
  const hashSearch = new URLSearchParams(hashQuery)
  return search.get('view') === 'maintainer' || hashSearch.get('view') === 'maintainer' ? 'maintainer' : 'normal'
}

function ImplementationBadge({ status, compact = false }: { status: ImplementationStatus; compact?: boolean }) {
  const label = compact ? implementationStatusShortLabel(status) : implementationStatusLabel(status)
  return (
    <span className={`implementation-badge ${status}`} title={implementationStatusHelp(status)}>
      {label}
    </span>
  )
}

function StageImplementationSummary({ capabilities, compact = false }: { capabilities: Capability[]; compact?: boolean }) {
  if (!capabilities.length) {
    return <span className="stage-status neutral">未绑定能力</span>
  }
  const counts = implementationStatusCounts(capabilities)
  const label = compact
    ? `${counts.implemented}/${capabilities.length} 可用`
    : `阶段能力：${counts.implemented} 可用 · ${counts.not_implemented} 规划中 · ${counts.external} 既有链路`
  return <span className={`stage-status ${stageImplementationTone(capabilities)}`}>{label}</span>
}

function Badge({ children }: { children: ReactNode }) {
  return <span className="badge">{children}</span>
}

function useCapabilityMap(data: DashboardData) {
  return useMemo(() => new Map(data.capabilities.map((capability) => [capability.id, capability])), [data.capabilities])
}

function capabilitiesForView(capabilities: Capability[], viewMode: ViewMode) {
  if (viewMode === 'maintainer') return capabilities
  const folded = foldCapabilitiesByCanonical(capabilities)
  const treeChildren = entryTreeChildCapabilityIds(folded)
  return folded.filter((capability) => capability.entryTree || !treeChildren.has(capability.id))
}

function implementationStatusLabel(status: ImplementationStatus) {
  const labels: Record<ImplementationStatus, string> = {
    implemented: '可用',
    not_implemented: '规划中',
    external: '既有链路',
  }
  return labels[status]
}

function implementationStatusShortLabel(status: ImplementationStatus) {
  const labels: Record<ImplementationStatus, string> = {
    implemented: '可用',
    not_implemented: '规划中',
    external: '既有链路',
  }
  return labels[status]
}

function implementationStatusHelp(status: ImplementationStatus) {
  const labels: Record<ImplementationStatus, string> = {
    implemented: '已实装，可直接发送到对应 Bot 使用。',
    not_implemented: '规划中。复制模板发送后会收到待人工处理回执，不代表系统故障。',
    external: '由既有创作、复盘或其他 canonical 链路执行。',
  }
  return labels[status]
}


function copyTemplateLabel(capability: Capability) {
  if (capability.implementationStatus === 'not_implemented') {
    return '复制模板（规划中，发送后会收到待人工处理回执）'
  }
  if (capability.implementationStatus === 'external') {
    return '复制模板（由既有链路执行）'
  }
  return '复制模板'
}

function implementationStatusCounts(capabilities: Capability[]) {
  return capabilities.reduce(
    (counts, capability) => {
      counts[capability.implementationStatus] += 1
      return counts
    },
    { implemented: 0, not_implemented: 0, external: 0 } as Record<ImplementationStatus, number>,
  )
}

function stageImplementationTone(capabilities: Capability[]) {
  if (!capabilities.length) return 'neutral'
  if (capabilities.some((capability) => capability.implementationStatus === 'implemented')) return 'implemented'
  if (capabilities.some((capability) => capability.implementationStatus === 'external')) return 'external'
  return 'not_implemented'
}

function normalDirectoryLayer(capability: Capability) {
  if (capability.rawLabel === '【拆解】') return 'Create'
  return capability.displayProjection.lifecycleLayer
}

function capabilitiesForBotDetail(data: DashboardData, botId: BotId, viewMode: ViewMode) {
  const visibleCapabilities = capabilitiesForView(data.capabilities, viewMode).filter((capability) =>
    capability.visibleBots.includes(botId),
  )
  if (viewMode === 'maintainer') return visibleCapabilities

  if (botId === 'media') {
    return sortRecommendedEntries(visibleCapabilities.filter((capability) => capability.recommendedEntry && isActionableCapability(capability)))
  }

  if (botId === 'daily') {
    return sortRecommendedEntries(visibleCapabilities.filter((capability) => capability.recommendedEntry && isActionableCapability(capability)))
  }

  const bot = data.bots.find((item) => item.id === botId)
  const featured = (bot?.featuredCapabilityIds ?? [])
    .map((id) => data.capabilities.find((capability) => capability.id === id))
    .filter((capability): capability is Capability => Boolean(capability))
    .filter((capability) => capability.visibleBots.includes(botId))
    .filter(isActionableCapability)
  return foldCapabilitiesByCanonical(featured)
}

function plannedCapabilitiesForBotDetail(data: DashboardData, botId: BotId, viewMode: ViewMode) {
  if (viewMode === 'maintainer') return []
  const visibleCapabilities = capabilitiesForView(data.capabilities, viewMode).filter((capability) =>
    capability.visibleBots.includes(botId),
  )
  return sortRecommendedEntries(visibleCapabilities.filter((capability) => capability.implementationStatus === 'not_implemented'))
}

function isActionableCapability(capability: Capability) {
  return capability.implementationStatus !== 'not_implemented'
}

function sortRecommendedEntries(capabilities: Capability[]) {
  return [...capabilities].sort((left, right) => {
    const layerDelta = lifecycleOrderIndex(normalDirectoryLayer(left)) - lifecycleOrderIndex(normalDirectoryLayer(right))
    if (layerDelta !== 0) return layerDelta
    return left.rawLabel.localeCompare(right.rawLabel, 'zh-Hans-CN')
  })
}

function foldCapabilitiesByCanonical(capabilities: Capability[]) {
  const selected = new Map<string, Capability>()
  for (const capability of capabilities) {
    const existing = selected.get(capability.canonicalCapabilityId)
    if (!existing || (!existing.recommendedEntry && capability.recommendedEntry)) {
      selected.set(capability.canonicalCapabilityId, capability)
    }
  }
  return Array.from(selected.values())
}

function entryTreeChildCapabilityIds(capabilities: Capability[]) {
  const ids = new Set<string>()
  for (const capability of capabilities) {
    for (const entry of capability.entryTree?.children ?? []) {
      ids.add(entry.capabilityId)
    }
  }
  return ids
}

function lifecycleOrderIndex(layer: string) {
  const order = ['Strategy', 'Collect', 'Decide', 'Create', 'Polish', 'Verify', 'Publish', 'Learn', 'Daily', 'Entity', 'Govern', 'Operate']
  const index = order.indexOf(layer)
  return index >= 0 ? index : order.length
}

function lifecycleName(layer: string) {
  const names: Record<string, string> = {
    Strategy: '策略',
    Collect: '素材收集',
    Decide: '选题判断',
    Create: '内容创作',
    Polish: '表达优化',
    Verify: '检查验收',
    Publish: '发布准备',
    Learn: '复盘学习',
    Daily: '日常记录',
    Entity: '账号与关系',
    Govern: '治理维护',
    Operate: '通用操作',
  }
  return names[layer] ?? layer
}

function groupBy<T>(items: T[], getKey: (item: T) => string) {
  return items.reduce<Record<string, T[]>>((acc, item) => {
    const key = getKey(item)
    acc[key] ??= []
    acc[key].push(item)
    return acc
  }, {})
}

function linkGroupName(group: string) {
  const names: Record<string, string> = {
    bot_entry: 'Bot 对话入口',
    capability_doc: '能力说明入口',
    collaboration_doc: '协作文档入口',
    maintainer_doc: '维护者入口',
  }
  return names[group] ?? group
}

export default App
