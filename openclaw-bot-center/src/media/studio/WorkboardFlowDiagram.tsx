import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'
import { ArrowRight, Bot, LoaderCircle, RefreshCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDate } from '../ui/ordinaryPagePrimitives'
import { pipelineDisplayLabel } from '../ui/displayLabels'
import type { Device, LocalAgentJob, PipelineSummary } from '../generatedProductContract'
import {
  WORKBOARD_FLOW_COLUMNS,
  WORKBOARD_FLOW_EDGES,
  WORKBOARD_FLOW_LANES,
  WORKBOARD_FLOW_NODES,
  WORKBOARD_FLOW_TOUR,
  workboardFlowNode,
  workboardStageIndex,
  type WorkboardFlowFact,
  type WorkboardFlowNode,
} from './workboardPresentation'
import {
  COLUMN_X,
  LANE_PAD,
  LANE_Y,
  NODE_BOXES,
  NODE_H,
  NODE_TEXT_INSET,
  NODE_W,
  VIEW_H,
  VIEW_W,
  edgeGeometry,
} from './workboardFlowLayout'
import styles from './WorkboardFlowDiagram.module.css'

/** 只取流程图用得到的合同字段（DashboardSummary），其余由 WorkboardPage 持有。 */
export type WorkboardFlowSummary = {
  counts: { contentProjects: number; runs: number; assets: number; tracks: number; creators: number; publishedPosts: number; reviews: number }
  contentProjectStages: readonly { stage: string; count: number }[]
  pendingDecisions: number
  pendingPublishing: number
  pendingReviews: number
  taskSummary: { queued: number; running: number; needsAttention: number; failed: number }
  generatedAt: string
}

export type WorkboardFlowProject = { publicProjectId: string; title: string; stage: string; updatedAt: string }
export type WorkboardFlowOpportunity = { publicOpportunityId: string; brand: string; product: string; status: string }
export type WorkboardFlowTask = { taskId: string; capabilityId: string; status: string; terminal: boolean; summary: string; progress: number; updatedAt: string }
/** 本机（Mac）协作状态：W1 流程目录、配对设备与本地任务。 */
export type WorkboardFlowLocalAgent = { pipelines: readonly PipelineSummary[]; devices: readonly Device[]; jobs: readonly LocalAgentJob[] }

type FlowData = {
  summary: WorkboardFlowSummary | null
  projects: readonly WorkboardFlowProject[]
  opportunities: readonly WorkboardFlowOpportunity[] | null
  tasks: readonly WorkboardFlowTask[]
  localAgent: WorkboardFlowLocalAgent | null
}

const AUTO_ADVANCE_MS = 4200

function factValue(fact: WorkboardFlowFact, data: FlowData, node: WorkboardFlowNode): number | null {
  switch (fact.source) {
    case 'stage': return data.summary ? data.summary.contentProjectStages.find((row) => row.stage === fact.stage)?.count ?? 0 : null
    case 'counts': return data.summary ? data.summary.counts[fact.key] : null
    case 'pending': return data.summary ? data.summary[fact.key] : null
    case 'opportunities': return data.opportunities ? data.opportunities.length : null
    case 'tasks': return data.tasks.filter((task) => task.capabilityId === fact.capabilityId && (fact.attention ? isAttentionTask(task) : !task.terminal)).length
    case 'devices': return data.localAgent ? data.localAgent.devices.filter((device) => device.state === 'online').length : null
    case 'localJobs': return data.localAgent ? data.localAgent.jobs.filter((job) => node.pipelines?.includes(job.pipeline_id)).length : null
  }
}

function isAttentionTask(task: WorkboardFlowTask): boolean {
  return task.status === 'awaiting_confirmation' || task.status === 'pending_manual' || (task.terminal && task.status === 'failed')
}

function pendingValue(node: WorkboardFlowNode, data: FlowData): number {
  return node.facts
    .filter((fact) => fact.source === 'pending' || (fact.source === 'tasks' && fact.attention))
    .reduce((total, fact) => total + (factValue(fact, data, node) ?? 0), 0)
}

// 图上每个节点只写一个首要数字，其余事实留给详情卡，避免小方块里塞两段文字。
function nodeCaption(node: WorkboardFlowNode, data: FlowData): string {
  const primary = node.facts[0]
  if (!primary) return node.hint ?? node.pathLabel
  const value = factValue(primary, data, node)
  return value === null ? '读取中' : `${value} ${primary.label}`
}

export function WorkboardFlowDiagram({ summary, loading, projects, opportunities, tasks, localAgent, onOpenTasks }: {
  summary: WorkboardFlowSummary | null
  loading: boolean
  projects: readonly WorkboardFlowProject[]
  opportunities: readonly WorkboardFlowOpportunity[] | null
  tasks: readonly WorkboardFlowTask[]
  localAgent: WorkboardFlowLocalAgent | null
  onOpenTasks: () => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const [cursor, setCursor] = useState(0)
  const [paused, setPaused] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReducedMotion(query.matches)
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  // 没有人工选择时自动沿流程巡游；用户悬停、聚焦或系统要求减少动态时停下。
  const autoAdvance = selected === null && !paused && !reducedMotion
  useEffect(() => {
    if (!autoAdvance) return
    const timer = window.setInterval(() => setCursor((value) => (value + 1) % WORKBOARD_FLOW_TOUR.length), AUTO_ADVANCE_MS)
    return () => window.clearInterval(timer)
  }, [autoAdvance])

  const data: FlowData = useMemo(() => ({ summary, projects, opportunities, tasks, localAgent }), [summary, projects, opportunities, tasks, localAgent])
  const activeId = selected ?? WORKBOARD_FLOW_TOUR[cursor]!
  const active = workboardFlowNode(activeId) ?? WORKBOARD_FLOW_NODES[0]!
  const tourIndex = WORKBOARD_FLOW_TOUR.indexOf(activeId as (typeof WORKBOARD_FLOW_TOUR)[number])
  const liveEdges = new Set(WORKBOARD_FLOW_EDGES.filter((edge) => edge.from === activeId || edge.to === activeId).map((edge) => `${edge.from}->${edge.to}`))
  const commercialTasks = useMemo(() => tasks.filter((task) => task.capabilityId === 'commercial_delivery_draft'), [tasks])

  function select(id: string) {
    setSelected((current) => (current === id ? null : id))
    const index = WORKBOARD_FLOW_TOUR.indexOf(id as (typeof WORKBOARD_FLOW_TOUR)[number])
    if (index !== -1) setCursor(index)
  }
  function onNodeKey(event: KeyboardEvent<SVGGElement>, id: string) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      select(id)
    }
  }

  return (
    <section className={`mg-panel ${styles.panel}`} aria-label="自媒体全流程" data-flow-auto={autoAdvance ? 'on' : 'off'}>
      <header className="mg-panel-head">
        <div><span>自媒体全流程</span><h2>内容线与商务线在创作合流，本机精剪后回到发布与复盘</h2></div>
        <div className={styles.headMeta}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <strong>{summary ? `${summary.counts.contentProjects} 个内容项目` : '汇总暂不可用'}</strong>}
          <small>{summary ? `按真实项目、商机、本机任务统计 · ${formatDate(summary.generatedAt)}` : '流程说明与真实数据分开展示'}</small>
        </div>
      </header>

      <div className={styles.legend} aria-label="泳道说明">
        {WORKBOARD_FLOW_LANES.map((lane) => <span key={lane.id} data-lane={lane.id}><i />{lane.label}<small>{lane.detail}</small></span>)}
      </div>

      <div
        className={styles.chart}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        onFocus={() => setPaused(true)}
        onBlur={() => setPaused(false)}
      >
        <svg className={styles.svg} viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="group" aria-label="自媒体全流程图：内容线、商务线、本机剪辑线与合流">
          <defs>
            <marker id="wb-arrow-muted" className={styles.arrowMuted} viewBox="0 0 8 8" refX="7.4" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse"><path d="M0,1 L8,4 L0,7 z" /></marker>
            {(['studio', 'campaign', 'business', 'desk', 'agent', 'archive'] as const).map((accent) => (
              <marker key={accent} id={`wb-arrow-${accent}`} className={styles.arrowLive} data-accent={accent} viewBox="0 0 8 8" refX="7.4" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse"><path d="M0,1 L8,4 L0,7 z" /></marker>
            ))}
          </defs>

          {WORKBOARD_FLOW_LANES.map((lane) => (
            <g key={lane.id} className={styles.laneBand} data-lane={lane.id}>
              <rect x={8} y={LANE_Y[lane.id] - LANE_PAD} width={VIEW_W - 16} height={NODE_H + LANE_PAD * 2} rx={12} />
              <text x={lane.id === 'shared' ? 24 : VIEW_W - 24} y={LANE_Y[lane.id] + 6} textAnchor={lane.id === 'shared' ? 'start' : 'end'}>{lane.label}</text>
            </g>
          ))}

          {WORKBOARD_FLOW_COLUMNS.map((column, index) => (
            <text key={column} className={styles.columnHead} x={COLUMN_X[index]! + NODE_W / 2} y={14} textAnchor="middle">{index + 1} · {column}</text>
          ))}

          {WORKBOARD_FLOW_EDGES.map((edge) => {
            const from = NODE_BOXES.get(edge.from)!
            const to = NODE_BOXES.get(edge.to)!
            const fromNode = workboardFlowNode(edge.from)!
            const key = `${edge.from}->${edge.to}`
            const live = liveEdges.has(key)
            const geometry = edgeGeometry(from, to, edge.from, edge.to, edge.kind)
            return (
              <g key={key} className={styles.edge} data-kind={edge.kind} data-live={live ? 'true' : undefined} data-accent={fromNode.accent}>
                <path d={geometry.d} markerEnd={`url(#wb-arrow-${live ? fromNode.accent : 'muted'})`} />
                {edge.label ? <text x={geometry.label[0]} y={geometry.label[1]} textAnchor={geometry.anchor}>{edge.label}</text> : null}
              </g>
            )
          })}

          {WORKBOARD_FLOW_NODES.map((node) => {
            const box = NODE_BOXES.get(node.id)!
            const pending = pendingValue(node, data)
            const isActive = node.id === activeId
            return (
              <g
                key={node.id}
                className={styles.node}
                data-accent={node.accent}
                data-active={isActive ? 'true' : undefined}
                role="button"
                tabIndex={0}
                aria-pressed={selected === node.id}
                aria-label={`${node.label}：${nodeCaption(node, data)}`}
                transform={`translate(${box.x} ${box.y})`}
                onClick={() => select(node.id)}
                onKeyDown={(event) => onNodeKey(event, node.id)}
              >
                <rect className={styles.nodeBox} width={NODE_W} height={NODE_H} rx={10} />
                <text className={styles.nodeLabel} x={NODE_TEXT_INSET} y={21}>{node.label}</text>
                <text className={styles.nodeCaption} x={NODE_TEXT_INSET} y={37}>{nodeCaption(node, data)}</text>
                {pending ? (
                  <g className={styles.nodePending} transform={`translate(${NODE_W - 10} 0)`}>
                    <rect x={-34} y={-10} width={34} height={16} rx={8} />
                    <text x={-17} y={2} textAnchor="middle">待 {pending}</text>
                  </g>
                ) : null}
              </g>
            )
          })}
        </svg>
      </div>

      <small className={styles.scrollHint}>横向滑动查看完整流程图</small>

      <div className={styles.laneList} aria-label="全流程节点（窄屏）">
        {WORKBOARD_FLOW_LANES.map((lane) => (
          <div key={lane.id} className={styles.laneGroup} data-lane={lane.id}>
            <span>{lane.label}<small>{lane.detail}</small></span>
            {WORKBOARD_FLOW_NODES.filter((node) => node.lane === lane.id).map((node) => (
              <button key={node.id} type="button" className={styles.laneNode} data-accent={node.accent} data-active={node.id === activeId ? 'true' : undefined} aria-pressed={selected === node.id} onClick={() => select(node.id)}>
                <strong>{node.label}</strong><small>{nodeCaption(node, data)}</small>
              </button>
            ))}
          </div>
        ))}
      </div>

      <FlowDetail node={active} step={tourIndex === -1 ? null : tourIndex + 1} data={data} commercialTasks={commercialTasks} />

      <footer className={styles.footer}>
        <span className={styles.loop}><RefreshCcw size={15} />复盘把经验送回研究与选题，把结案数据送回商机</span>
        <button type="button" className={styles.agentLane} onClick={onOpenTasks}>
          <Bot size={15} />
          <span>Agent 任务贯穿每一步</span>
          {summary ? (
            <em>运行中 {summary.taskSummary.running} · 排队 {summary.taskSummary.queued} · 需关注 {summary.taskSummary.needsAttention} · 失败 {summary.taskSummary.failed}</em>
          ) : <em>任务汇总暂不可用</em>}
          <ArrowRight size={14} />
        </button>
      </footer>
    </section>
  )
}

function FlowDetail({ node, step, data, commercialTasks }: { node: WorkboardFlowNode; step: number | null; data: FlowData; commercialTasks: readonly WorkboardFlowTask[] }) {
  const lane = WORKBOARD_FLOW_LANES.find((item) => item.id === node.lane)!
  const stageIndex = node.stage ? workboardStageIndex(node.stage) : null
  const stageProjects = stageIndex === null ? [] : data.projects.filter((project) => workboardStageIndex(project.stage) === stageIndex)
  const sideTitle = node.pipelines
    ? '本机可用流程'
    : node.id === 'opportunity' || node.id === 'profile' ? '当前商务机会' : node.id === 'brief' || node.id === 'acceptance' ? '商单交付任务' : '处于此阶段的项目'
  const sideItems: { key: string; title: string; detail: string }[] = node.pipelines
    ? (data.localAgent?.pipelines ?? [])
      .filter((pipeline) => node.pipelines?.includes(pipeline.pipeline_id))
      .map((pipeline) => ({ key: pipeline.pipeline_id, title: pipelineDisplayLabel(pipeline), detail: `版本 ${pipeline.version}` }))
    : node.id === 'opportunity' || node.id === 'profile'
      ? (data.opportunities ?? []).map((item) => ({ key: item.publicOpportunityId, title: `${item.brand} · ${item.product}`, detail: item.status }))
      : node.id === 'brief' || node.id === 'acceptance'
        ? commercialTasks.filter((task) => node.id === 'brief' ? !task.terminal : isAttentionTask(task)).map((task) => ({ key: task.taskId, title: task.summary || '商单交付任务', detail: `${task.progress}% · ${formatDate(task.updatedAt)}` }))
        : stageProjects.map((project) => ({ key: project.publicProjectId, title: project.title, detail: `更新于 ${formatDate(project.updatedAt)}` }))
  const emptyCopy = node.pipelines
    ? (data.localAgent === null ? '本机协作状态暂时无法读取。' : '还没有配对的 Mac 客户端，先在 Agent 任务页生成配对码。')
    : node.id === 'opportunity' || node.id === 'profile'
      ? (data.opportunities === null ? '商务机会暂时无法读取。' : '还没有已授权的商务机会。')
      : node.id === 'brief' || node.id === 'acceptance'
        ? '当前没有对应的商单交付任务。'
        : stageIndex === null
          ? '这一步不按项目阶段统计。'
          : '最近更新的项目里没有处于此阶段的。'

  return (
    <div className={styles.detail} data-accent={node.accent} aria-live="polite">
      <div className={styles.detailCopy}>
        <span className={styles.detailEyebrow}>{lane.label}{step ? ` · 巡游第 ${step} / ${WORKBOARD_FLOW_TOUR.length} 站` : ''} · {node.label}</span>
        <p><strong>做什么</strong>{node.action}</p>
        <p><strong>产出</strong>{node.outcome}</p>
        <div className={styles.detailFacts}>
          {node.facts.map((fact, index) => {
            const value = factValue(fact, data, node)
            return <span key={index}><small>{fact.label}</small><strong>{value === null ? '—' : value}</strong></span>
          })}
          {node.artifactLabel ? <span><small>产物类型</small><strong>{node.artifactLabel}</strong></span> : null}
          {node.stage ? <span><small>项目阶段</small><strong>第 {stageIndex! + 1} / 6 步</strong></span> : null}
        </div>
        <div className={styles.capabilities}>
          <small>用到的能力</small>
          {node.capabilities.map((capability) => <code key={capability.id} title={capability.id}>{capability.label}</code>)}
        </div>
      </div>
      <div className={styles.detailSide}>
        <span>{sideTitle}</span>
        {sideItems.length ? (
          <ul>
            {sideItems.slice(0, 3).map((item) => <li key={item.key}><strong>{item.title}</strong><small>{item.detail}</small></li>)}
            {sideItems.length > 3 ? <li><small>还有 {sideItems.length - 3} 项</small></li> : null}
          </ul>
        ) : <p>{emptyCopy}</p>}
        <Link className="mg-btn mg-btn-soft" to={node.path}>前往{node.pathLabel}<ArrowRight size={15} /></Link>
      </div>
    </div>
  )
}
