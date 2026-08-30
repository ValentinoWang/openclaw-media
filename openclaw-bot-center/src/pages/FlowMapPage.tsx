import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Bot, CheckCircle2, FileCheck2, GitBranch, Link2, PackageCheck, ShieldCheck } from 'lucide-react'
import {
  buildDashboardPresentation,
  type CapabilityPresentationSummary,
  type FlowPresentationSummary,
  type FlowStagePresentationSummary,
} from '../lib/dashboardPresentation'
import { botChineseNames, botNames, flowOwnerNames, implementationStatusNames } from '../lib/labels'
import type { BotId, ContentOsProjectDashboard, DashboardData, Flow } from '../schemas/dashboardSchema'

type FlowMapPageProps = {
  data: DashboardData
  viewMode: 'normal' | 'maintainer'
}

type FlowBotGroup = {
  botId: BotId
  botName: string
  flows: FlowPresentationSummary[]
  stageCount: number
  capabilityCount: number
}

type FlowStage = Flow['stages'][number]

const ALL_BOTS = 'all'

export default function FlowMapPage({ data, viewMode }: FlowMapPageProps) {
  const presentation = useMemo(() => buildDashboardPresentation(data), [data])
  const visibleFlows = useMemo(
    () => presentation.flowSummaries.filter((flow) => viewMode === 'maintainer' || flow.visibility === 'normal'),
    [presentation.flowSummaries, viewMode],
  )
  const rawFlowById = useMemo(() => new Map(data.flows.map((flow) => [flow.id, flow])), [data.flows])
  const botGroups = useMemo(() => buildFlowBotGroups(data, visibleFlows), [data, visibleFlows])
  const [searchParams, setSearchParams] = useSearchParams()
  const botIds = useMemo(() => new Set(data.bots.map((bot) => bot.id)), [data.bots])
  const [selectedBotId, setSelectedBotId] = useState<BotId | typeof ALL_BOTS>(() => readBotParam(searchParams, botIds))
  const selectedGroup = botGroups.find((group) => group.botId === selectedBotId)
  const selectedBotFlows = useMemo(
    () => selectedBotId === ALL_BOTS ? visibleFlows : selectedGroup?.flows ?? [],
    [selectedBotId, selectedGroup, visibleFlows],
  )
  const [selectedFlowId, setSelectedFlowId] = useState(selectedBotFlows[0]?.id ?? visibleFlows[0]?.id ?? '')
  const selectedFlow = selectedBotFlows.find((flow) => flow.id === selectedFlowId) ?? selectedBotFlows[0] ?? visibleFlows[0]
  const [selectedStageId, setSelectedStageId] = useState(selectedFlow?.stages[0]?.id ?? '')
  const selectedStage = selectedFlow?.stages.find((stage) => stage.id === selectedStageId) ?? selectedFlow?.stages[0]
  const rawFlow = selectedFlow ? rawFlowById.get(selectedFlow.id) : undefined
  const rawStage = rawFlow?.stages.find((stage) => stage.id === selectedStage?.id)
  const currentBotLabel = selectedBotId === ALL_BOTS ? '全部 Bot' : botChineseNames[selectedBotId] ?? botNames[selectedBotId]
  const currentBot = selectedBotId === ALL_BOTS ? undefined : data.bots.find((bot) => bot.id === selectedBotId)

  useEffect(() => {
    const urlBot = readBotParam(searchParams, botIds)
    if (urlBot !== selectedBotId) {
      setSelectedBotId(urlBot)
    }
  }, [botIds, searchParams, selectedBotId])

  function selectBot(botId: BotId | typeof ALL_BOTS) {
    setSelectedBotId(botId)
    setSearchParams(botId === ALL_BOTS ? {} : { bot: botId })
  }

  useEffect(() => {
    if (!selectedBotFlows.length) return
    if (!selectedBotFlows.some((flow) => flow.id === selectedFlowId)) {
      setSelectedFlowId(selectedBotFlows[0].id)
    }
  }, [selectedBotFlows, selectedFlowId])

  useEffect(() => {
    if (!selectedFlow?.stages.length) return
    if (!selectedFlow.stages.some((stage) => stage.id === selectedStageId)) {
      setSelectedStageId(selectedFlow.stages[0].id)
    }
  }, [selectedFlow, selectedStageId])

  if (!data.bots.length || !visibleFlows.length) {
    return (
      <main className="redesign-flow-map" aria-label="Flow map">
        <header className="redesign-flow-map-header">
          <span className="redesign-kicker">流程地图</span>
          <h1>按 Bot 查看能力如何串起来</h1>
          <p>当前生成数据里还没有可展示的 Bot 或流程记录。</p>
        </header>
      </main>
    )
  }

  return (
    <main className="redesign-flow-map" aria-label="Flow map">
      <header className="redesign-flow-map-header">
        <span className="redesign-kicker">流程地图</span>
        <h1>按 Bot 查看能力如何串起来</h1>
        <p>从生成流程契约反推 Bot 参与关系，展示阶段顺序、交接产物与完成判断。</p>
      </header>

      <nav className="redesign-flow-tabs" aria-label="Bot filters">
        <button
          type="button"
          className={`redesign-flow-tab ${selectedBotId === ALL_BOTS ? 'redesign-is-selected' : ''}`}
          onClick={() => selectBot(ALL_BOTS)}
          aria-pressed={selectedBotId === ALL_BOTS}
        >
          全部 Bot
        </button>
        {botGroups.map((group) => (
          <button
            key={group.botId}
            type="button"
            className={`redesign-flow-tab ${selectedBotId === group.botId ? 'redesign-is-selected' : ''}`}
            onClick={() => selectBot(group.botId)}
            aria-pressed={selectedBotId === group.botId}
          >
            {botChineseNames[group.botId] ?? group.botName}
          </button>
        ))}
      </nav>

      <section className="redesign-current-bot-context" aria-label="Current Bot flow context">
        <span className="redesign-bot-selector-mark">{currentBot ? currentBot.name.slice(0, 1) : '全'}</span>
        <div>
          <strong>{currentBotLabel} / 流程地图</strong>
          <small>{currentBot?.description ?? '按全部 Bot 汇总生成流程契约、阶段交接和能力连接。'}</small>
        </div>
        <div className="redesign-current-bot-stats" aria-label="Current flow counts">
          <span><b>{selectedBotFlows.length}</b><small>流程</small></span>
          <span><b>{selectedBotFlows.reduce((count, flow) => count + flow.stageCount, 0)}</b><small>阶段</small></span>
          <span><b>{unique(selectedBotFlows.flatMap((flow) => flow.relatedCapabilityIds)).length}</b><small>能力</small></span>
        </div>
      </section>

      <section className="redesign-flow-layout">
        <aside className="redesign-flow-overview" aria-label="Flow overview grouped by Bot">
          {botGroups.map((group) => (
            <section key={group.botId} className="redesign-flow-bot-group">
              <button
                type="button"
                className={`redesign-flow-bot-heading ${selectedBotId === group.botId ? 'redesign-is-selected' : ''}`}
                onClick={() => selectBot(group.botId)}
                aria-pressed={selectedBotId === group.botId}
              >
                <span className="redesign-flow-bot-mark"><Bot size={16} aria-hidden="true" /></span>
                <span>
                  <strong>{botChineseNames[group.botId] ?? group.botName}</strong>
                  <small>{group.flows.length} 个流程 / {group.stageCount} 个阶段 / {group.capabilityCount} 个能力</small>
                </span>
              </button>
              <div className="redesign-flow-overview-list">
                {group.flows.map((flow) => (
                  <button
                    key={`${group.botId}-${flow.id}`}
                    type="button"
                    className={`redesign-flow-overview-card ${selectedFlow?.id === flow.id ? 'redesign-is-selected' : ''}`}
                    onClick={() => {
                      selectBot(group.botId)
                      setSelectedFlowId(flow.id)
                    }}
                    aria-pressed={selectedFlow?.id === flow.id}
                  >
                    <strong>{flow.title}</strong>
                    <small>{flow.stageCount} 个阶段 / {flow.relatedCapabilityIds.length} 个能力</small>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </aside>

        <section className="redesign-flow-main" aria-label="Selected flow detail">
          {selectedFlow && selectedStage ? (
            <>
              <header className="redesign-flow-detail-header">
                <span className="redesign-kicker">{currentBotLabel} / 生成流程契约</span>
                <h2>{selectedFlow.title}</h2>
                <p>{selectedFlow.description}</p>
                <div className="redesign-flow-meta-row" aria-label="Flow metadata">
                  <span><GitBranch size={15} aria-hidden="true" /> {selectedFlow.stageCount} 个阶段</span>
                  <span><Link2 size={15} aria-hidden="true" /> {selectedFlow.relatedCapabilityIds.length} 个关联能力</span>
                  <span><ShieldCheck size={15} aria-hidden="true" /> {visibilityLabel(selectedFlow.visibility)}</span>
                </div>
              </header>

              <div className="redesign-flow-stage-timeline" aria-label="Horizontal stage timeline">
                {selectedFlow.stages.map((stage, index) => (
                  <button
                    key={`${selectedFlow.id}-${stage.id}`}
                    type="button"
                    className={`redesign-flow-stage-node ${selectedStage.id === stage.id ? 'redesign-is-selected' : ''}`}
                    onClick={() => setSelectedStageId(stage.id)}
                    aria-pressed={selectedStage.id === stage.id}
                  >
                    <span className="redesign-flow-stage-index">{index + 1}</span>
                    <strong>{stage.title}</strong>
                    <small>{flowOwnerNames[stage.owner]}</small>
                  </button>
                ))}
              </div>

              {selectedFlow.id === 'cloud-mac-materials' ? (
                <ContentOsProjectDashboardPanel dashboard={data.contentOsProjectDashboard} />
              ) : null}

              <StageDetail flow={selectedFlow} stage={selectedStage} rawStage={rawStage} />
            </>
          ) : (
            <p className="redesign-empty-state">当前筛选下没有关联流程。</p>
          )}
        </section>

        <aside className="redesign-flow-right-rail" aria-label="Current Bot flow data and contracts">
          <section className="redesign-flow-panel">
            <h2><Bot size={18} aria-hidden="true" /> 当前 Bot 流程数据</h2>
            <p>{currentBotLabel}</p>
            <div className="redesign-flow-stat-grid">
              <span><strong>{selectedBotFlows.length}</strong><small>流程</small></span>
              <span><strong>{selectedBotFlows.reduce((count, flow) => count + flow.stageCount, 0)}</strong><small>阶段</small></span>
              <span><strong>{unique(selectedBotFlows.flatMap((flow) => flow.relatedCapabilityIds)).length}</strong><small>能力</small></span>
            </div>
          </section>

          <ContractPanel
            title="交接产物"
            icon={<PackageCheck size={18} aria-hidden="true" />}
            items={rawStage?.handoffArtifacts}
            emptyText="当前阶段没有交接产物。"
          />
          <ContractPanel
            title="完成信号"
            icon={<CheckCircle2 size={18} aria-hidden="true" />}
            items={rawStage?.completionSignals}
            emptyText="当前阶段没有完成信号。"
          />
          <ContractPanel
            title="阻塞项"
            icon={<AlertTriangle size={18} aria-hidden="true" />}
            items={rawStage?.blockers}
            emptyText="当前阶段没有阻塞项。"
          />
          <ContractPanel
            title="回读 / 验证"
            icon={<FileCheck2 size={18} aria-hidden="true" />}
            items={[...(rawStage?.entryConditions ?? []), ...(rawStage?.boundaries ?? []), ...(rawStage?.outputs ?? [])]}
            emptyText="当前阶段没有可展示的验证条件。"
          />
        </aside>
      </section>
    </main>
  )
}

function ContentOsProjectDashboardPanel({ dashboard }: { dashboard: ContentOsProjectDashboard }) {
  return (
    <section className="redesign-flow-stage-detail" aria-label="内容项目详情">
      <header className="redesign-flow-stage-detail-header">
        <span className="redesign-flow-owner-badge">项目</span>
        <div>
          <h3>{dashboard.title}</h3>
          <p>{dashboard.summary}</p>
        </div>
      </header>

      {dashboard.projects.length ? (
        <div className="redesign-content-os-project-list">
          {dashboard.projects.map((project) => (
            <article key={project.id} className="redesign-content-os-project-card">
              <header className="redesign-content-os-project-card-header">
                <div>
                  <span className="redesign-content-os-project-kicker">项目</span>
                  <h4>{project.title}</h4>
                </div>
                <div className="redesign-content-os-project-stage">
                  <span>项目阶段</span>
                  <strong>{project.stage}</strong>
                </div>
              </header>
              <dl className="redesign-content-os-project-metadata">
                <div><dt>当前版本</dt><dd>{project.revision}</dd></div>
                <div><dt>剪辑方式</dt><dd>{project.editingMethod}</dd></div>
                <div><dt>负责人</dt><dd>{project.owner}</dd></div>
              </dl>
              <div className="redesign-content-os-project-progress">
                <section className="redesign-content-os-project-next">
                  <span>下一步</span>
                  <p>{project.nextAction}</p>
                </section>
                <section className="redesign-content-os-project-blocker">
                  <span>阻塞原因</span>
                  <p>{project.blockedReason}</p>
                </section>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="redesign-empty-state">{dashboard.emptyText}</p>
      )}

      <footer className="redesign-content-os-modification-entry">
        <div>
          <span>需要调整？</span>
          <p>{dashboard.modificationEntry.instruction}</p>
        </div>
        <a href={dashboard.modificationEntry.url} className="redesign-flow-capability-chip">
          <strong>提交修改</strong>
          <small>{dashboard.modificationEntry.label}</small>
        </a>
      </footer>

    </section>
  )
}

function StageDetail({
  flow,
  stage,
  rawStage,
}: {
  flow: FlowPresentationSummary
  stage: FlowStagePresentationSummary
  rawStage: FlowStage | undefined
}) {
  return (
    <article className="redesign-flow-stage-detail">
      <header className="redesign-flow-stage-detail-header">
        <span className="redesign-flow-owner-badge">{flowOwnerNames[stage.owner]}</span>
        <div>
          <h3>{stage.title}</h3>
          <p>{stage.summary}</p>
        </div>
      </header>

      <div className="redesign-flow-stage-counts" aria-label="Selected stage counts">
        <span><strong>{stage.inputCount}</strong><small>输入</small></span>
        <span><strong>{stage.outputCount}</strong><small>输出</small></span>
        <span><strong>{stage.handoffArtifactCount}</strong><small>交接物</small></span>
        <span><strong>{stage.blockerCount}</strong><small>卡点</small></span>
      </div>

      <section className="redesign-flow-stage-section">
        <h4>相关能力</h4>
        {stage.capabilities.length ? (
          <div className="redesign-flow-chip-list">
            {stage.capabilities.map((capability, index) => (
              <CapabilityChip key={`${flow.id}-${stage.id}-${capability.id}-${index}`} capability={capability} />
            ))}
          </div>
        ) : (
          <p className="redesign-empty-state">当前阶段没有已解析的关联能力。</p>
        )}
        {stage.missingCapabilityIds.map((missingId, index) => (
          <span key={`${flow.id}-${stage.id}-${missingId}-${index}`} className="redesign-flow-missing-chip">未解析能力：{missingId}</span>
        ))}
      </section>

      <section className="redesign-flow-stage-section">
        <h4>阶段数据</h4>
        <div className="redesign-flow-data-columns">
          <FlowListBlock title="输入" items={rawStage?.inputs} />
          <FlowListBlock title="输出" items={rawStage?.outputs} />
          <FlowListBlock title="下一步" items={stage.nextStep ? [stage.nextStep] : []} />
        </div>
      </section>
    </article>
  )
}

function CapabilityChip({ capability }: { capability: CapabilityPresentationSummary }) {
  return (
    <a href={`#/capabilities/detail/${capability.id}`} className="redesign-flow-capability-chip">
      <strong>{capability.title}</strong>
      <small>{botChineseNames[capability.primaryBot] ?? botNames[capability.primaryBot]} / {implementationStatusNames[capability.implementationStatus]}</small>
    </a>
  )
}

function ContractPanel({
  title,
  icon,
  items,
  emptyText,
}: {
  title: string
  icon: ReactNode
  items: string[] | undefined
  emptyText: string
}) {
  return (
    <section className="redesign-flow-panel">
      <h2>{icon} {title}</h2>
      <FlowListBlock title={title} items={items} emptyText={emptyText} />
    </section>
  )
}

function FlowListBlock({ title, items, emptyText = '无记录。' }: { title: string; items: string[] | undefined; emptyText?: string }) {
  const visibleItems = items?.filter(Boolean) ?? []

  return (
    <div className="redesign-flow-list-block">
      <span className="redesign-flow-list-title">{title}</span>
      {visibleItems.length ? (
        <ul>
          {visibleItems.map((item, index) => (
            <li key={`${title}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="redesign-empty-state">{emptyText}</p>
      )}
    </div>
  )
}

function buildFlowBotGroups(data: DashboardData, flows: FlowPresentationSummary[]): FlowBotGroup[] {
  return data.bots.map((bot) => {
    const botFlows = flows.filter((flow) => flow.stages.some((stage) => stage.capabilities.some((capability) => capability.primaryBot === bot.id)))
    return {
      botId: bot.id,
      botName: bot.name,
      flows: botFlows,
      stageCount: botFlows.reduce(
        (count, flow) => count + flow.stages.filter((stage) => stage.capabilities.some((capability) => capability.primaryBot === bot.id)).length,
        0,
      ),
      capabilityCount: unique(botFlows.flatMap((flow) => flow.stages.flatMap((stage) => stage.capabilities.filter((capability) => capability.primaryBot === bot.id).map((capability) => capability.id)))).length,
    }
  }).filter((group) => group.flows.length > 0)
}

function unique<T>(items: T[]): T[] {
  return Array.from(new Set(items))
}

function readBotParam(searchParams: URLSearchParams, botIds: Set<string>) {
  const bot = searchParams.get('bot')
  return bot && botIds.has(bot) ? bot as BotId : ALL_BOTS
}

function visibilityLabel(visibility: FlowPresentationSummary['visibility']) {
  return visibility === 'normal' ? '普通模式可见' : '维护模式可见'
}
