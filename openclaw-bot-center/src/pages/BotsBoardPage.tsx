import { useMemo, useState, type ReactNode } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Brain,
  BookOpen,
  CalendarDays,
  ChevronRight,
  Database,
  GitBranch,
  Link as LinkIcon,
  PenLine,
  RefreshCw,
  ShieldCheck,
  UsersRound,
} from 'lucide-react'
import {
  buildDashboardPresentation,
  type BotCapabilityCluster,
  type FlowPresentationSummary,
  type FlowStagePresentationSummary,
} from '../lib/dashboardPresentation'
import { botChineseNames } from '../lib/labels'
import type { Bot, BotId, DashboardData } from '../schemas/dashboardSchema'

export type ViewModeLike = 'normal' | 'maintainer'

type BotsBoardPageProps = {
  data: DashboardData
  viewMode: ViewModeLike
}

type SelectedFlowStrip = FlowPresentationSummary & {
  selectedStages: FlowStagePresentationSummary[]
}

const botIcons = {
  media: PenLine,
  daily: CalendarDays,
  knowledge: BookOpen,
  social: UsersRound,
  deepmath: Brain,
} satisfies Record<BotId, typeof PenLine>

export default function BotsBoardPage({ data, viewMode }: BotsBoardPageProps) {
  const presentation = useMemo(() => buildDashboardPresentation(data), [data])
  const [selectedBotId, setSelectedBotId] = useState<BotId>(data.bots[0]?.id ?? 'media')
  const selectedBot = data.bots.find((bot) => bot.id === selectedBotId) ?? data.bots[0]
  const selectedCapabilities = useMemo(
    () => data.capabilities.filter((capability) => selectedBot ? capability.visibleBots.includes(selectedBot.id) : false),
    [data.capabilities, selectedBot],
  )
  const selectedCapabilityIds = useMemo(
    () => new Set(selectedCapabilities.map((capability) => capability.id)),
    [selectedCapabilities],
  )
  const flowStrips = useMemo(
    () => selectFlowStripsForBot(presentation.flowSummaries, selectedCapabilityIds, viewMode),
    [presentation.flowSummaries, selectedCapabilityIds, viewMode],
  )

  if (!selectedBot) {
    return (
      <main className="redesign-bots-board" aria-label="MediaClaw Bot board">
        <div className="redesign-empty-state">当前生成数据里还没有 Bot 记录。</div>
      </main>
    )
  }

  const selectedBotIndex = data.bots.findIndex((bot) => bot.id === selectedBot.id)
  const selectedStats = presentation.botStats.find((stats) => stats.botId === selectedBot.id)
  const selectedClusters = presentation.botCapabilityClusters.find((cluster) => cluster.botId === selectedBot.id)
  const boundaryLines = Array.from(new Set(selectedCapabilities.flatMap((capability) => capability.outputDetail.boundaries).filter(Boolean))).slice(0, 3)
  if (viewMode === 'maintainer') boundaryLines.push(`Schema：${data.meta.schemaVersion}`)

  function moveSelection(direction: -1 | 1) {
    const nextIndex = (selectedBotIndex + direction + data.bots.length) % data.bots.length
    setSelectedBotId(data.bots[nextIndex]?.id ?? selectedBot.id)
  }

  return (
    <main className="redesign-bots-board" aria-label="MediaClaw Bot board">
      <section className="redesign-bots-hero">
        <aside className="redesign-bot-selector-panel" aria-label="Bot selector panel">
          <header>
            <strong>选择 Bot</strong>
            <small>点击卡片切换</small>
          </header>
          <div className="redesign-bots-selector-rail" aria-label="Bot selector">
            {data.bots.map((bot) => {
              const stats = presentation.botStats.find((item) => item.botId === bot.id)
              const Icon = botIcons[bot.id]
              return (
                <button
                  key={bot.id}
                  type="button"
                  className={`redesign-bot-selector ${bot.id === selectedBot.id ? 'redesign-is-selected' : ''}`}
                  onClick={() => setSelectedBotId(bot.id)}
                  aria-pressed={bot.id === selectedBot.id}
                >
                  <span className={`redesign-bot-selector-mark redesign-bot-selector-mark-${bot.id}`}>
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <span>
                    <strong>{botChineseNames[bot.id]} Bot</strong>
                    <small>{stats?.primaryCapabilityCount ?? 0} 个主责能力</small>
                    <span className="redesign-bot-selector-counts">
                      <em>{stats?.implementedCapabilityCount ?? 0} 已落地</em>
                      <em>{stats?.externalCapabilityCount ?? 0} 既有链路</em>
                      <em>{stats?.notImplementedCapabilityCount ?? 0} 规划中</em>
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
          <footer>
            <strong>{selectedBotIndex + 1} / {data.bots.length}</strong>
            <small>点击卡片或使用中间箭头切换 Bot</small>
          </footer>
        </aside>

        <div className="redesign-bot-main-area">
          <section className="redesign-selected-bot-stage" aria-label="Selected Bot">
            <header className="redesign-selected-bot-header">
              <div>
                <h1>{selectedBot.title}</h1>
                <span>/ 能力如何扩展成流程</span>
              </div>
              <small>
                <RefreshCw size={14} aria-hidden="true" />
                数据更新 <time dateTime={data.meta.generatedAt}>{formatGeneratedAt(data.meta.generatedAt)}</time>
              </small>
            </header>

            <div className="redesign-bot-toolbar">
              <div className="redesign-carousel-controls" aria-label="Bot carousel controls">
                <button type="button" onClick={() => moveSelection(-1)} aria-label="Previous Bot">
                  <ArrowLeft size={17} aria-hidden="true" />
                </button>
                <span>{botChineseNames[selectedBot.id]} Bot</span>
                <button type="button" onClick={() => moveSelection(1)} aria-label="Next Bot">
                  <ArrowRight size={17} aria-hidden="true" />
                </button>
              </div>
              <span>{selectedBotIndex + 1} / {data.bots.length}</span>
            </div>

            <BotRadialBoard
              bot={selectedBot}
              stats={selectedStats}
              clusters={selectedClusters?.clusters ?? []}
            />
            {flowStrips.length ? <BotFlowPreview flows={flowStrips.slice(0, 2)} /> : null}
          </section>

          <aside className="redesign-contract-rail" aria-label="Contract and data boundary">
            <DataLandingPanel capabilities={selectedCapabilities} />
            <JumpPanel bot={selectedBot} />
            <ContractPanel
              title="权限与边界"
              icon={<ShieldCheck size={18} aria-hidden="true" />}
              lines={boundaryLines.length ? boundaryLines : ['当前生成数据未声明额外边界。']}
            />
          </aside>
        </div>
      </section>
    </main>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <span className="redesign-metric">
      <strong>{value}</strong>
      <small>{label}</small>
    </span>
  )
}

function ContractPanel({
  title,
  icon,
  lines,
}: {
  title: string
  icon: ReactNode
  lines: string[]
}) {
  return (
    <section className="redesign-contract-panel">
      <h2>{icon}{title}</h2>
      <ul>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  )
}

function JumpPanel({ bot }: { bot: Bot }) {
  const jumpLinks = [
    ...bot.entryLinks.filter((link) => link.status === 'active').slice(0, 1).map((link) => ({
      label: link.label,
      description: `${botChineseNames[bot.id]} Bot 概览`,
      href: link.url,
    })),
    { label: '业务视图', description: '查看这个 Bot 支持的任务入口', href: `#/tasks?bot=${bot.id}` },
    { label: '能力入口树', description: '查看能力分层与输入输出定义', href: `#/capabilities?bot=${bot.id}` },
    { label: '流程地图', description: '查看能力如何串联成完整流程', href: `#/flows?bot=${bot.id}` },
  ]
  return (
    <section className="redesign-contract-panel redesign-link-panel">
      <h2><LinkIcon size={18} aria-hidden="true" /> 可跳转页面</h2>
      <div className="redesign-link-stack">
        {jumpLinks.map((link) => (
          <a key={link.href} href={link.href}>
            <span>{link.label}</span>
            <small>{link.description}</small>
            <ChevronRight size={16} aria-hidden="true" />
          </a>
        ))}
      </div>
    </section>
  )
}

function DataLandingPanel({ capabilities }: { capabilities: DashboardData['capabilities'] }) {
  const destinations = Array.from(new Set(capabilities.flatMap((capability) => capability.outputDetail.destinations).filter(Boolean))).slice(0, 4)
  return (
    <section className="redesign-contract-panel redesign-data-landing-panel">
      <h2><Database size={18} aria-hidden="true" /> 数据落点</h2>
      <div className="redesign-data-landing-rows">
        {destinations.map((destination) => (
          <span key={destination}>
            <strong>{destination}</strong>
            <small>已声明</small>
          </span>
        ))}
        {!destinations.length ? <span><strong>当前生成数据未声明输出位置</strong></span> : null}
      </div>
    </section>
  )
}

function BotRadialBoard({
  bot,
  stats,
  clusters,
}: {
  bot: Bot
  stats: ReturnType<typeof buildDashboardPresentation>['botStats'][number] | undefined
  clusters: BotCapabilityCluster[]
}) {
  const Icon = botIcons[bot.id]
  const orbitClusters = clusters.filter((cluster) => cluster.capabilities.length).slice(0, 4)
  return (
    <article className="redesign-bot-radial-board" aria-label={`${bot.name} capability expansion map`}>
      <div className="redesign-radial-canvas">
        <svg className="redesign-radial-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path d="M50 50 L20 22" />
          <path d="M50 50 L80 22" />
          <path d="M50 50 L22 78" />
          <path d="M50 50 L78 78" />
        </svg>
        <div className={`redesign-bot-orbit-center redesign-bot-orbit-center-${bot.id}`}>
          <span className={`redesign-bot-icon-large redesign-bot-icon-${bot.id}`}>
            <Icon size={25} aria-hidden="true" />
          </span>
          <strong>{botChineseNames[bot.id]} Bot</strong>
          <b>{stats?.visibleCapabilityCount ?? 0} 可见能力</b>
          <div className="redesign-orbit-status-row" aria-label="Selected Bot metrics">
            <Metric label="已落地" value={stats?.implementedCapabilityCount ?? 0} />
            <Metric label="既有链路" value={stats?.externalCapabilityCount ?? 0} />
            <Metric label="规划中" value={stats?.notImplementedCapabilityCount ?? 0} />
          </div>
        </div>
        {orbitClusters.map((cluster, index) => (
          <section key={`orbit-${cluster.id}`} className={`redesign-bot-orbit-node node-${index + 1}`}>
            <header>
              <h2>{cluster.label}</h2>
              <span>{cluster.capabilities.length} 个能力</span>
            </header>
            <div>
              {cluster.capabilities.slice(0, 4).map((capability) => (
                <a key={`${cluster.id}-${capability.id}`} href={`#/capabilities/detail/${capability.id}`}>
                  {capability.label}
                  <ChevronRight size={13} aria-hidden="true" />
                </a>
              ))}
            </div>
          </section>
        ))}
      </div>
    </article>
  )
}

function BotFlowPreview({ flows }: { flows: SelectedFlowStrip[] }) {
  return (
    <section className="redesign-bot-flow-preview" aria-label="Bot flow combinations">
      <header>
        <span><GitBranch size={16} aria-hidden="true" /> 关联流程</span>
        <a href="#/flows">查看流程地图 <ChevronRight size={15} aria-hidden="true" /></a>
      </header>
      <div className="redesign-bot-flow-preview-list">
        {flows.map((flow, flowIndex) => (
          <article key={`preview-${flow.id}`} className={`redesign-bot-flow-preview-card flow-${flowIndex + 1}`}>
            <div className="redesign-flow-preview-title">
              <span>流程 {flowIndex + 1}</span>
              <strong>{flow.title}</strong>
              <small>{flow.stageCount} 个阶段</small>
            </div>
            <div className="redesign-mini-stage-track" aria-label={`${flow.title} preview stages`}>
              {flow.selectedStages.slice(0, 6).map((stage) => (
                <a key={`${flow.id}-${stage.id}`} href={`#/flows/${flow.id}`} title={stage.title}>
                  <span>{flow.stages.findIndex((candidate) => candidate.id === stage.id) + 1}</span>
                  {stage.title}
                </a>
              ))}
            </div>
            <a className="redesign-flow-preview-link" href={`#/flows/${flow.id}`}>
              查看完整流程 <ChevronRight size={14} aria-hidden="true" />
            </a>
          </article>
        ))}
      </div>
    </section>
  )
}

function selectFlowStripsForBot(
  flows: FlowPresentationSummary[],
  selectedCapabilityIds: Set<string>,
  viewMode: ViewModeLike,
): SelectedFlowStrip[] {
  return flows
    .filter((flow) => viewMode === 'maintainer' || flow.visibility === 'normal')
    .map((flow) => ({
      ...flow,
      selectedStages: flow.stages.filter((stage) =>
        stage.relatedCapabilityIds.some((capabilityId) => selectedCapabilityIds.has(capabilityId)),
      ),
    }))
    .filter((flow) => flow.selectedStages.length > 0)
}

function formatGeneratedAt(value: string) {
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(timestamp)
}
