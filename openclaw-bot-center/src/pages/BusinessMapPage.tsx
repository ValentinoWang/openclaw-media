import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  BookOpen,
  CalendarDays,
  Clapperboard,
  Database,
  GitBranch,
  ShieldCheck,
  Star,
  UsersRound,
} from 'lucide-react'
import {
  buildDashboardPresentation,
  type CapabilityPresentationSummary,
  type FlowPresentationSummary,
  type FlowStagePresentationSummary,
  type TaskPresentationRow,
} from '../lib/dashboardPresentation'
import { botChineseNames, botNames, taskGroupNames } from '../lib/labels'
import type { BotId, DashboardData } from '../schemas/dashboardSchema'

type BusinessMapPageProps = {
  data: DashboardData
}

type BusinessTaskRow = TaskPresentationRow & {
  flows: MatchedFlow[]
}

type MatchedFlow = Pick<FlowPresentationSummary, 'id' | 'title'> & {
  stages: FlowStagePresentationSummary[]
  totalStageCount: number
}

const ALL_BOTS = 'all'
const MAX_CAPABILITY_CHIPS = 6
const MAX_RECOMMENDED_ENTRIES = 5

export default function BusinessMapPage({ data }: BusinessMapPageProps) {
  const presentation = useMemo(() => buildDashboardPresentation(data), [data])
  const [searchParams, setSearchParams] = useSearchParams()
  const botIds = useMemo(() => new Set(data.bots.map((bot) => bot.id)), [data.bots])
  const [selectedBotId, setSelectedBotId] = useState<BotId | typeof ALL_BOTS>(() => readBotParam(searchParams, botIds, true))

  const botById = useMemo(() => new Map(data.bots.map((bot) => [bot.id, bot])), [data.bots])
  const businessRows = useMemo(
    () => buildBusinessRows(presentation.taskRows, presentation.flowSummaries),
    [presentation.flowSummaries, presentation.taskRows],
  )
  const visibleRows = useMemo(
    () => businessRows.filter((row) => selectedBotId === ALL_BOTS || row.recommendedBot === selectedBotId),
    [businessRows, selectedBotId],
  )
  const recommendedEntries = useMemo(
    () => uniqueCapabilities(visibleRows.flatMap((row) => row.capabilities).filter((capability) => capability.recommendedEntry)),
    [visibleRows],
  )
  const currentBot = selectedBotId === ALL_BOTS ? undefined : data.bots.find((bot) => bot.id === selectedBotId)
  const currentBotLabel = currentBot ? botChineseNames[currentBot.id] ?? currentBot.name : '全部 Bot'
  const currentDescription = currentBot?.description ?? '汇总全部 Bot 的业务任务、推荐入口与关联流程。'
  const visibleFlowCount = uniqueStrings(visibleRows.flatMap((row) => row.flows.map((flow) => flow.id))).length

  useEffect(() => {
    const urlBot = readBotParam(searchParams, botIds, true)
    if (urlBot !== selectedBotId) {
      setSelectedBotId(urlBot)
    }
  }, [botIds, searchParams, selectedBotId])

  function selectBot(botId: BotId | typeof ALL_BOTS) {
    setSelectedBotId(botId)
    const nextSearchParams = new URLSearchParams(searchParams)
    if (botId === ALL_BOTS) nextSearchParams.delete('bot')
    else nextSearchParams.set('bot', botId)
    setSearchParams(nextSearchParams)
  }

  return (
    <main className="redesign-business-map" aria-label="Business task map">
      <section className="redesign-business-map-layout">
        <aside className="redesign-business-bot-rail" aria-label="Bot grouping rail">
          <header className="redesign-business-rail-heading">
            <span className="redesign-business-heading-icon"><Clapperboard size={18} aria-hidden="true" /></span>
            <span><strong>Bot 分组</strong><small>选择业务归属</small></span>
          </header>
          <div className="redesign-business-bot-list">
            {data.bots.map((bot) => {
              const botRows = businessRows.filter((row) => row.recommendedBot === bot.id)
              const entryCount = uniqueCapabilities(
                botRows.flatMap((row) => row.capabilities).filter((capability) => capability.recommendedEntry),
              ).length
              return (
                <button
                  key={bot.id}
                  type="button"
                  className={`redesign-business-bot-group redesign-business-bot-${bot.id} ${selectedBotId === bot.id ? 'redesign-is-selected' : ''}`}
                  onClick={() => selectBot(bot.id)}
                  aria-pressed={selectedBotId === bot.id}
                >
                  <span className="redesign-business-bot-mark">{botIcon(bot.id)}</span>
                  <span>
                    <strong>{botChineseNames[bot.id] ?? bot.name}</strong>
                    <small>{botRows.length} 个业务 · {entryCount} 个推荐入口</small>
                  </span>
                </button>
              )
            })}
          </div>
          <p className="redesign-business-rail-note">先选业务，再进入能力或完整流程查看细节。</p>
        </aside>

        <section className="redesign-business-main-panel" aria-label="Business map overview">
          <header className="redesign-business-map-header">
            <div>
              <span className="redesign-kicker">业务地图</span>
              <h1>按 Bot 找业务入口</h1>
              <p>任务、推荐能力与关联流程的一页导航。</p>
            </div>
            <div className="redesign-business-summary" aria-label="Current business counts">
              <span><b>{visibleRows.length}</b><small>业务</small></span>
              <span><b>{recommendedEntries.length}</b><small>入口</small></span>
              <span><b>{visibleFlowCount}</b><small>流程</small></span>
            </div>
          </header>

          <div className="redesign-business-toolbar">
            <nav className="redesign-business-tabs" aria-label="Bot filters">
              <button
                type="button"
                className={`redesign-business-tab ${selectedBotId === ALL_BOTS ? 'redesign-is-selected' : ''}`}
                onClick={() => selectBot(ALL_BOTS)}
                aria-pressed={selectedBotId === ALL_BOTS}
              >
                全部
              </button>
              {data.bots.map((bot) => (
                <button
                  key={bot.id}
                  type="button"
                  className={`redesign-business-tab ${selectedBotId === bot.id ? 'redesign-is-selected' : ''}`}
                  onClick={() => selectBot(bot.id)}
                  aria-pressed={selectedBotId === bot.id}
                >
                  {botChineseNames[bot.id] ?? bot.name}
                </button>
              ))}
            </nav>
            <div className="redesign-business-legend" aria-label="Implementation status legend">
              <span><i className="legend-implemented" /> 已落地</span>
              <span><i className="legend-external" /> 既有链路</span>
              <span><i className="legend-planned" /> 规划中</span>
            </div>
          </div>

          <section className="redesign-business-table-wrap" aria-label="Business task rows">
            <div className="redesign-business-table" role="table" aria-label="Business task to capability and flow mapping">
              <div className="redesign-business-table-head" role="row">
                <span role="columnheader">所属 Bot</span>
                <span role="columnheader">用户想做什么</span>
                <span role="columnheader">能力入口</span>
                <span role="columnheader">关联流程</span>
              </div>
              {visibleRows.map((row) => (
                <BusinessRow key={row.id} row={row} botName={botById.get(row.recommendedBot)?.name ?? botNames[row.recommendedBot]} />
              ))}
              {!visibleRows.length ? <p className="redesign-empty-state">当前 Bot 暂无可展示的业务任务。</p> : null}
            </div>
          </section>
        </section>

        <aside className="redesign-business-right-rail" aria-label="Current selection and recommended entries">
          <section className="redesign-business-panel redesign-business-selection-panel">
            <span className={`redesign-business-selection-mark redesign-business-bot-${currentBot?.id ?? 'all'}`}>
              {currentBot ? botIcon(currentBot.id) : '全'}
            </span>
            <div>
              <small>当前选择</small>
              <h2>{currentBotLabel}</h2>
              <p>{currentDescription}</p>
            </div>
          </section>

          <section className="redesign-business-panel">
            <h2><Star size={17} aria-hidden="true" /> 推荐入口</h2>
            {recommendedEntries.length ? (
              <div className="redesign-business-entry-list">
                {recommendedEntries.slice(0, MAX_RECOMMENDED_ENTRIES).map((capability) => (
                  <a key={capability.id} href={`#/capabilities/detail/${capability.id}`} className="redesign-business-entry">
                    <strong>{capability.title}</strong>
                    <small>{capability.label}</small>
                  </a>
                ))}
              </div>
            ) : (
              <p className="redesign-empty-state">当前筛选下没有推荐入口能力。</p>
            )}
          </section>

          <section className="redesign-business-panel redesign-business-boundary-panel">
            <h2><ShieldCheck size={17} aria-hidden="true" /> 数据边界</h2>
            <ul className="redesign-business-contract-list">
              <li>只展示生成数据中的任务与入口。</li>
              <li>流程仅按能力绑定关系匹配。</li>
              <li>不代表后端运行态或实时数量。</li>
            </ul>
            <footer><Database size={14} aria-hidden="true" /> Schema {data.meta.schemaVersion} · {formatGeneratedAt(data.meta.generatedAt)}</footer>
          </section>
        </aside>
      </section>
    </main>
  )
}

function BusinessRow({ row, botName }: { row: BusinessTaskRow; botName: string }) {
  const visibleCapabilities = row.capabilities.slice(0, MAX_CAPABILITY_CHIPS)
  const remainingCapabilities = row.capabilities.length - visibleCapabilities.length

  return (
    <article className={`redesign-business-table-row redesign-business-bot-${row.recommendedBot}`} role="row">
      <div className="redesign-business-bot-cell" role="cell">
        <span className="redesign-business-row-bot-mark">{botIcon(row.recommendedBot)}</span>
        <span><strong>{botChineseNames[row.recommendedBot] ?? botName}</strong><small>{botName}</small></span>
      </div>
      <div className="redesign-business-intent-cell" role="cell">
        <a href={`#/tasks/${row.id}`} className="redesign-business-task-link">{row.title}</a>
        <p>{row.description}</p>
        <small>{taskGroupNames[row.group] ?? row.group}</small>
      </div>
      <div className="redesign-business-capability-cell" role="cell">
        <div className="redesign-business-capability-chips">
          {visibleCapabilities.map((capability) => (
            <CapabilityEntry key={`${row.id}-${capability.id}`} capability={capability} />
          ))}
          {remainingCapabilities > 0 ? (
            <a href={`#/tasks/${row.id}`} className="redesign-business-more-link">+{remainingCapabilities} 个</a>
          ) : null}
        </div>
        {row.missingCapabilityIds.map((missingId) => (
          <span key={`${row.id}-${missingId}`} className="redesign-business-missing">未解析入口：{missingId}</span>
        ))}
      </div>
      <div className="redesign-business-flow-cell" role="cell">
        {row.flows.length ? (
          row.flows.map((flow) => <MatchedFlowCard key={`${row.id}-${flow.id}`} flow={flow} />)
        ) : (
          <span className="redesign-business-muted">暂无关联流程</span>
        )}
      </div>
    </article>
  )
}

function CapabilityEntry({ capability }: { capability: CapabilityPresentationSummary }) {
  return (
    <a
      href={`#/capabilities/detail/${capability.id}`}
      className={`redesign-business-capability-link redesign-status-${capability.implementationStatus}`}
      title={`${capability.title} · ${implementationStatusLabel(capability.implementationStatus)}`}
    >
      {capability.label}
    </a>
  )
}

function MatchedFlowCard({ flow }: { flow: MatchedFlow }) {
  return (
    <a href={`#/flows/${flow.id}`} className="redesign-business-flow-card">
      <span className="redesign-business-flow-title"><GitBranch size={14} aria-hidden="true" /><strong>{flow.title}</strong></span>
      <span className="redesign-business-flow-meta">命中 {flow.stages.length} / 共 {flow.totalStageCount} 个阶段</span>
      <span className="redesign-business-flow-dots" aria-label={`${flow.title}，共 ${flow.totalStageCount} 个阶段`}>
        {Array.from({ length: Math.min(flow.totalStageCount, 8) }, (_, index) => (
          <i key={`${flow.id}-dot-${index}`} className={index < flow.stages.length ? 'is-matched' : ''} />
        ))}
      </span>
    </a>
  )
}

function implementationStatusLabel(status: CapabilityPresentationSummary['implementationStatus']) {
  const labels: Record<CapabilityPresentationSummary['implementationStatus'], string> = {
    implemented: '已落地',
    external: '既有链路',
    not_implemented: '规划中',
  }
  return labels[status]
}

function buildBusinessRows(tasks: TaskPresentationRow[], flows: FlowPresentationSummary[]): BusinessTaskRow[] {
  return tasks.map((task) => {
    const capabilityIds = new Set(task.recommendedCapabilityIds)
    const matchedFlows = flows
      .map((flow) => ({
        id: flow.id,
        title: flow.title,
        totalStageCount: flow.stages.length,
        stages: flow.stages.filter((stage) => stage.relatedCapabilityIds.some((capabilityId) => capabilityIds.has(capabilityId))),
      }))
      .filter((flow) => flow.stages.length > 0)

    return { ...task, flows: matchedFlows }
  })
}

function botIcon(botId: BotId): ReactNode {
  const props = { size: 17, 'aria-hidden': true as const }
  switch (botId) {
    case 'media': return <Clapperboard {...props} />
    case 'daily': return <CalendarDays {...props} />
    case 'knowledge': return <BookOpen {...props} />
    case 'social': return <UsersRound {...props} />
  }
}

function formatGeneratedAt(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function uniqueCapabilities(capabilities: CapabilityPresentationSummary[]) {
  const seen = new Set<string>()
  return capabilities.filter((capability) => {
    if (seen.has(capability.id)) return false
    seen.add(capability.id)
    return true
  })
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values))
}

function readBotParam(searchParams: URLSearchParams, botIds: Set<string>, allowAll: true): BotId | typeof ALL_BOTS
function readBotParam(searchParams: URLSearchParams, botIds: Set<string>, allowAll: false): BotId | undefined
function readBotParam(searchParams: URLSearchParams, botIds: Set<string>, allowAll: boolean) {
  const bot = searchParams.get('bot')
  if (bot && botIds.has(bot)) return bot as BotId
  return allowAll ? ALL_BOTS : undefined
}
