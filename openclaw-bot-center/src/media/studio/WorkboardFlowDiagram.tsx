import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Bot, LoaderCircle, RefreshCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDate } from '../ui/ordinaryPagePrimitives'
import { WORKBOARD_FLOW_STAGES, workboardStageIndex, type WorkboardFlowStage } from './workboardPresentation'
import styles from './WorkboardFlowDiagram.module.css'

/** 只取流程图用得到的合同字段（DashboardSummary），其余由 WorkboardPage 持有。 */
export type WorkboardFlowSummary = {
  counts: { contentProjects: number }
  contentProjectStages: readonly { stage: string; count: number }[]
  pendingDecisions: number
  pendingPublishing: number
  pendingReviews: number
  taskSummary: { queued: number; running: number; needsAttention: number; failed: number }
  generatedAt: string
}

export type WorkboardFlowProject = {
  publicProjectId: string
  title: string
  stage: string
  updatedAt: string
}

const stageAccent: Readonly<Record<string, string>> = {
  research: 'desk',
  assets: 'archive',
  decision: 'business',
  creation: 'studio',
  publishing: 'campaign',
  review: 'agent',
}

const AUTO_ADVANCE_MS = 4200

export function WorkboardFlowDiagram({ summary, loading, projects, onOpenTasks }: {
  summary: WorkboardFlowSummary | null
  loading: boolean
  projects: readonly WorkboardFlowProject[]
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
    const timer = window.setInterval(() => setCursor((value) => (value + 1) % WORKBOARD_FLOW_STAGES.length), AUTO_ADVANCE_MS)
    return () => window.clearInterval(timer)
  }, [autoAdvance])

  const stageCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of summary?.contentProjectStages ?? []) counts.set(row.stage, row.count)
    return counts
  }, [summary])
  const totalProjects = summary?.counts.contentProjects ?? 0
  const projectsByStage = useMemo(() => {
    const groups = new Map<number, WorkboardFlowProject[]>()
    for (const project of projects) {
      const index = workboardStageIndex(project.stage)
      if (index === null) continue
      groups.set(index, [...(groups.get(index) ?? []), project])
    }
    return groups
  }, [projects])

  const activeStage = selected ?? WORKBOARD_FLOW_STAGES[cursor]!.stage
  const activeIndex = WORKBOARD_FLOW_STAGES.findIndex((stage) => stage.stage === activeStage)
  const active = WORKBOARD_FLOW_STAGES[activeIndex]!
  const activeCount = stageCounts.get(active.stage)
  const activePending = pendingCount(active, summary)
  const activeProjects = projectsByStage.get(activeIndex) ?? []

  function select(stage: string) {
    setSelected((current) => (current === stage ? null : stage))
    const index = WORKBOARD_FLOW_STAGES.findIndex((item) => item.stage === stage)
    if (index !== -1) setCursor(index)
  }

  return (
    <section className={`mg-panel ${styles.panel}`} aria-label="自媒体全流程" data-flow-auto={autoAdvance ? 'on' : 'off'}>
      <header className="mg-panel-head">
        <div><span>自媒体全流程</span><h2>从研究到复盘的内容闭环</h2></div>
        <div className={styles.headMeta}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <strong>{summary ? `${totalProjects} 个内容项目` : '汇总暂不可用'}</strong>}
          <small>{summary ? `按项目当前阶段统计 · ${formatDate(summary.generatedAt)}` : '阶段说明与真实数据分开展示'}</small>
        </div>
      </header>

      <div className={styles.distribution} role="img" aria-label={distributionLabel(stageCounts, totalProjects)}>
        {WORKBOARD_FLOW_STAGES.map((stage) => {
          const count = stageCounts.get(stage.stage) ?? 0
          const share = totalProjects ? (count / totalProjects) * 100 : 0
          return <span key={stage.stage} data-accent={stageAccent[stage.stage]} data-active={stage.stage === activeStage ? 'true' : undefined} style={{ flexBasis: `${share}%` }} title={`${stage.label} ${count}`} />
        })}
      </div>

      <ol
        className={styles.track}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        onFocus={() => setPaused(true)}
        onBlur={() => setPaused(false)}
      >
        {WORKBOARD_FLOW_STAGES.map((stage, index) => {
          const count = stageCounts.get(stage.stage)
          const pending = pendingCount(stage, summary)
          const isActive = stage.stage === activeStage
          return (
            <li key={stage.stage} data-accent={stageAccent[stage.stage]} data-active={isActive ? 'true' : undefined} data-reached={index <= activeIndex ? 'true' : undefined}>
              <button type="button" className={styles.node} aria-pressed={selected === stage.stage} onClick={() => select(stage.stage)}>
                <span className={styles.nodeIndex}>{index + 1}</span>
                <strong>{stage.label}</strong>
                <em>{summary ? `${count ?? 0} 个项目` : '—'}</em>
                <small>{stage.artifactLabel}</small>
                {pending ? <b className={styles.nodePending}>{stage.pendingLabel} {pending}</b> : null}
              </button>
            </li>
          )
        })}
      </ol>

      <div className={styles.detail} data-accent={stageAccent[active.stage]} aria-live="polite">
        <div className={styles.detailCopy}>
          <span className={styles.detailEyebrow}>第 {activeIndex + 1} / {WORKBOARD_FLOW_STAGES.length} 步 · {active.label}</span>
          <p><strong>做什么</strong>{active.action}</p>
          <p><strong>产出</strong>{active.outcome}</p>
          <div className={styles.detailFacts}>
            <span><small>当前项目</small><strong>{summary ? activeCount ?? 0 : '—'}</strong></span>
            <span><small>{active.pendingLabel ?? '待处理'}</small><strong>{active.pending ? (summary ? activePending : '—') : '无'}</strong></span>
            <span><small>产物类型</small><strong>{active.artifactLabel}</strong></span>
          </div>
        </div>
        <div className={styles.detailSide}>
          <span>处于此阶段的项目</span>
          {activeProjects.length ? (
            <ul>
              {activeProjects.slice(0, 3).map((project) => <li key={project.publicProjectId}><strong>{project.title}</strong><small>更新于 {formatDate(project.updatedAt)}</small></li>)}
              {activeProjects.length > 3 ? <li><small>还有 {activeProjects.length - 3} 个项目</small></li> : null}
            </ul>
          ) : <p>{summary && (activeCount ?? 0) > 0 ? '最近更新的项目里没有处于此阶段的，可到对应页面查看全部。' : '暂无项目处于此阶段。'}</p>}
          <Link className="mg-btn mg-btn-soft" to={active.path}>前往{active.pathLabel}<ArrowRight size={15} /></Link>
        </div>
      </div>

      <footer className={styles.footer}>
        <span className={styles.loop}><RefreshCcw size={15} />复盘报告回流到下一轮研究，形成闭环</span>
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

function pendingCount(stage: WorkboardFlowStage, summary: WorkboardFlowSummary | null): number {
  if (!stage.pending || !summary) return 0
  return summary[stage.pending]
}

function distributionLabel(counts: ReadonlyMap<string, number>, total: number): string {
  const parts = WORKBOARD_FLOW_STAGES.map((stage) => `${stage.label} ${counts.get(stage.stage) ?? 0}`)
  return `${total} 个项目按阶段分布：${parts.join('，')}`
}
