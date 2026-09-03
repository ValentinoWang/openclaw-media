import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertCircle,
  ArrowRight,
  Bot,
  BriefcaseBusiness,
  CalendarClock,
  CircleDollarSign,
  Clock3,
  FilePenLine,
  Images,
  LoaderCircle,
  PackageCheck,
  PenTool,
  Plus,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import { callBusinessOperation } from '../generatedBusinessPagesContract'
import { loadMediaDevices, loadMediaJobs, loadMediaPipelines } from '../mediaWebApi'
import { projectStatusDisplayLabel } from '../ui/displayLabels'
import { describeBusinessError } from '../ui/businessOperationError'
import { SurfaceState } from '../ui/SurfaceState'
import { formatDate } from '../ui/ordinaryPagePrimitives'
import { Metric } from '../ui/Metric'
import styles from './WorkboardPage.module.css'
import { WorkboardFlowDiagram, type WorkboardFlowLocalAgent } from './WorkboardFlowDiagram'
import { WORKBOARD_FLOW_STAGE_ORDER, filterWorkboardAttentionTasks, workboardStageIndex, workboardStageNode, workboardStageProgress } from './workboardPresentation'

type DashboardResponse = {
  revision: number
  summary: {
    counts: {
      contentProjects: number
      runs: number
      assets: number
      tracks: number
      creators: number
      publishedPosts: number
      reviews: number
    }
    contentProjectStages: { stage: string; count: number }[]
    pendingDecisions: number
    pendingPublishing: number
    pendingReviews: number
    taskSummary: {
      queued: number
      running: number
      needsAttention: number
      failed: number
    }
    generatedAt: string
  }
}

type ContentProjectSummary = {
  publicProjectId: string
  title: string
  stage: string
  status: string
  artifactCounts: Record<string, number>
  updatedAt: string
}

type ProjectListResponse = {
  revision: number
  items: ContentProjectSummary[]
}

type BusinessOpportunitySummary = {
  publicOpportunityId: string
  brand: string
  product: string
  status: string
}

type OpportunityListResponse = {
  revision: number
  items: BusinessOpportunitySummary[]
}

type LoadState<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string }

export default function WorkboardPage() {
  const { openWorkspace, tasks, session } = useMediaWeb()
  const [dashboard, setDashboard] = useState<LoadState<DashboardResponse>>({ status: 'loading' })
  const [projects, setProjects] = useState<LoadState<ProjectListResponse>>({ status: 'loading' })
  const [opportunities, setOpportunities] = useState<LoadState<OpportunityListResponse>>({ status: 'loading' })
  const [localAgent, setLocalAgent] = useState<WorkboardFlowLocalAgent | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    let active = true
    setDashboard({ status: 'loading' })
    setProjects({ status: 'loading' })
    setOpportunities({ status: 'loading' })
    void Promise.allSettled([
      callBusinessOperation<DashboardResponse>('getDashboard'),
      callBusinessOperation<ProjectListResponse>('listContentProjects', { query: { pageSize: 8 } }),
      // 商务线节点（商机）直接读 Business 页同一份记录，流程图上的数字与 /business 一致。
      callBusinessOperation<OpportunityListResponse>('listBusinessOpportunities', { query: { pageSize: 50 } }),
    ]).then(([dashboardResult, projectResult, opportunityResult]) => {
      if (!active) return
      setDashboard(dashboardResult.status === 'fulfilled'
        ? { status: 'ready', data: dashboardResult.value }
        : { status: 'error', message: readError(dashboardResult.reason, '今日汇总暂时无法读取。') })
      setProjects(projectResult.status === 'fulfilled'
        ? { status: 'ready', data: projectResult.value }
        : { status: 'error', message: readError(projectResult.reason, '内容项目暂时无法读取。') })
      setOpportunities(opportunityResult.status === 'fulfilled'
        ? { status: 'ready', data: opportunityResult.value }
        : { status: 'error', message: readError(opportunityResult.reason, '商务机会暂时无法读取。') })
    })
    return () => { active = false }
  }, [refreshToken])

  // 本机剪辑线：W1 的流程目录、配对设备与本地任务。没有配对 Mac 或读取失败时留空，
  // 流程图上对应节点显示「—」，而不是编造本机状态。
  useEffect(() => {
    if (!session) return
    let active = true
    void Promise.all([
      loadMediaPipelines(session),
      loadMediaDevices(session),
      loadMediaJobs(session, { limit: 100 }),
    ]).then(([pipelines, devices, jobs]) => {
      if (!active) return
      setLocalAgent({ pipelines: pipelines.pipelines, devices: devices.devices, jobs: jobs.jobs })
    }).catch(() => {
      if (active) setLocalAgent(null)
    })
    return () => { active = false }
  }, [session, refreshToken])

  const summary = dashboard.status === 'ready' ? dashboard.data.summary : null
  const pendingTotal = summary ? summary.pendingDecisions + summary.pendingPublishing + summary.pendingReviews + summary.taskSummary.needsAttention : 0
  const attentionTasks = useMemo(
    () => filterWorkboardAttentionTasks(tasks).slice(0, 4),
    [tasks],
  )
  const activeTasks = useMemo(() => tasks.filter((task) => !task.terminal).slice(0, 4), [tasks])

  return (
    <main className="mg-page" data-accent="studio" data-page-ownership="personal">
      <section className="mg-hero" data-page-prelude>
        <div>
          <span className="mg-eyebrow"><Sparkles size={15} />CREATOR PRODUCTION DESK</span>
          <h1 className={styles.heroTitle}>今日<em>工作台</em></h1>
          <p className="mg-hero-lead">跟踪内容项目的脚本、分镜、拍摄单、返修和发布包进度。</p>
          <div className="mg-hero-actions">
            <button className="mg-btn mg-btn-primary" type="button" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}><Plus size={17} />新建内容项目</button>
            <button className="mg-btn mg-btn-soft" type="button" onClick={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })}><BriefcaseBusiness size={17} />导入商单 Brief</button>
            <button className="mg-btn mg-btn-ghost" type="button" onClick={() => openWorkspace()}><Bot size={17} />打开 Agent 任务</button>
          </div>
        </div>
        <div className="mg-hero-signal">
          <span>今日推进信号</span>
          {dashboard.status === 'loading' ? <LoaderCircle className="spin" size={22} /> : dashboard.status === 'error' ? <AlertCircle size={22} /> : <strong>{pendingTotal}</strong>}
          <p>{pendingTotal ? '项内容、审核或发布事项等待处理' : '当前没有显式阻塞，可以开始下一条内容'}</p>
          <small>{summary ? `数据更新于 ${formatDate(summary.generatedAt)}` : '仅显示当前账户真实数据'}</small>
        </div>
      </section>

      <section className={styles.metricGrid} aria-label="工作区关键指标">
        <div data-accent="studio"><Metric variant="card" className={styles.metricCard} tone="accent" icon={<FilePenLine size={18} />} label="内容项目" value={summary?.counts.contentProjects} detail="从 Brief 到发布" /></div>
        <div data-accent="campaign"><Metric variant="card" className={styles.metricCard} tone="accent" icon={<PenTool size={18} />} label="创作运行" value={summary?.counts.runs} detail="脚本、分镜与交付" /></div>
        <div data-accent="business"><Metric variant="card" className={styles.metricCard} tone="accent" icon={<Images size={18} />} label="素材证据" value={summary?.counts.assets} detail="原始素材与拆解" /></div>
        <div data-accent="desk"><Metric variant="card" className={styles.metricCard} tone="accent" icon={<PackageCheck size={18} />} label="已发布作品" value={summary?.counts.publishedPosts} detail="等待持续复盘" /></div>
      </section>

      <WorkboardFlowDiagram
        summary={summary}
        loading={dashboard.status === 'loading'}
        projects={projects.status === 'ready' ? projects.data.items : []}
        opportunities={opportunities.status === 'ready' ? opportunities.data.items : null}
        tasks={tasks}
        localAgent={localAgent}
        onOpenTasks={() => openWorkspace()}
      />

      <section className={styles.loopGrid} aria-label="相关工作页面入口">
        <LoopCard
          tone="studio"
          icon={<PenTool size={20} />}
          kicker="STUDIO"
          title="可编辑脚本与分镜活稿"
          description="人工直接改、区块可锁定、修改后继续生成拍摄清单与发布包。"
          steps={['脚本', '分镜', '拍摄', '剪辑', '发布']}
          to="/studio"
        />
        <LoopCard
          tone="campaign"
          icon={<BriefcaseBusiness size={20} />}
          kicker="CAMPAIGNS"
          title="活动与商单履约"
          description="把品牌要求、活动资料和返修意见维护在同一个交付项目里。"
          steps={['Brief', '初稿', '审核', '返修', '交付']}
          to="/campaigns"
        />
        <LoopCard
          tone="business"
          icon={<CircleDollarSign size={20} />}
          kicker="BUSINESS"
          title="报价、档期与商务机会"
          description="统一管理账号资料、报价快照、权益边界和项目机会。"
          steps={['达人', '报价', '权益', '商机', '复购']}
          to="/business"
        />
        <LoopCard
          tone="desk"
          icon={<TrendingUp size={20} />}
          kicker="DESK"
          title="监控、拆解与复盘"
          description="为选题和创作提供有据可查的研究结论。"
          steps={['监控', '拆解', '决策', '创作', '复盘']}
          to="/desk"
        />
      </section>

      <div className={styles.workspaceGrid}>
        <section className="mg-panel">
          <header className="mg-panel-head">
            <div><span>正在推进</span><h2>内容项目</h2></div>
            <Link className="mg-btn mg-btn-ghost" to="/overview">高级项目视图<ArrowRight size={15} /></Link>
          </header>
          {projects.status === 'loading' ? <SurfaceState kind="loading" title="正在读取内容项目" detail="正在读取当前账户可见的内容项目。" /> : null}
          {projects.status === 'error' ? <SurfaceState kind="error" title={projects.message} detail="请重新读取内容项目，或稍后再试。" action={<button className="mg-btn mg-btn-ghost" type="button" onClick={() => setRefreshToken((value) => value + 1)}>重新读取</button>} /> : null}
          {projects.status === 'ready' && projects.data.items.length ? (
            <div className={styles.projectList}>
              {projects.data.items.slice(0, 5).map((project) => <ProjectCard key={project.publicProjectId} project={project} />)}
            </div>
          ) : null}
          {projects.status === 'ready' && !projects.data.items.length ? <SurfaceState kind="empty" title="还没有内容项目" detail="从活动、商单、灵感或素材开始创建第一条可交付内容。" action={<button className="mg-btn mg-btn-primary" type="button" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}>创建项目</button>} /> : null}
        </section>

        <aside className="mg-panel">
          <header className="mg-panel-head">
            <div><span>行动收件箱</span><h2>需要你处理</h2></div>
            <button className="mg-btn mg-btn-ghost" type="button" onClick={() => openWorkspace()}>全部任务</button>
          </header>
          <div className={styles.actionList}>
            {attentionTasks.length ? attentionTasks.map((task) => (
              <button className={styles.taskCard} type="button" key={task.taskId} onClick={() => openWorkspace()}>
                <span className={styles.taskIcon}><AlertCircle size={17} /></span>
                <span><strong>{task.summary || '待人工处理的内容任务'}</strong><small>{task.progress}% · {formatDate(task.updatedAt)}</small></span>
                <ArrowRight size={15} />
              </button>
            )) : activeTasks.length ? activeTasks.map((task) => (
              <button className={styles.taskCard} type="button" key={task.taskId} onClick={() => openWorkspace()}>
                <span className={styles.taskIcon}><Clock3 size={17} /></span>
                <span><strong>{task.summary || '内容任务执行中'}</strong><small>{task.progress}% · {formatDate(task.updatedAt)}</small></span>
                <ArrowRight size={15} />
              </button>
            )) : (
              <SurfaceState kind="empty" title="当前没有待处理任务" detail="可以创建下一条内容，或进入 Desk 研究新的方向。" />
            )}
          </div>
          <div className={styles.deadlineCard}>
            <span><CalendarClock size={18} />生产原则</span>
            <strong>人工修改优先，AI 只提交局部变更</strong>
            <p>保留版本、来源与返修记录，避免每次修改都把整套内容推倒重来。</p>
          </div>
        </aside>
      </div>
    </main>
  )
}

function LoopCard({ tone, icon, kicker, title, description, steps, to }: { tone: 'studio' | 'campaign' | 'business' | 'desk'; icon: ReactNode; kicker: string; title: string; description: string; steps: string[]; to: string }) {
  return (
    <Link className={styles.loopCard} data-tone={tone} to={to}>
      <header><span>{icon}</span><small>{kicker}</small><ArrowRight size={16} /></header>
      <h2>{title}</h2>
      <p>{description}</p>
      <div>{steps.map((step, index) => <span key={step}>{step}{index < steps.length - 1 ? <i>→</i> : null}</span>)}</div>
    </Link>
  )
}

function ProjectCard({ project }: { project: ContentProjectSummary }) {
  // 进度只来自后端的 project.stage：六个阶段各占固定位置，不按产物数量或时间推算。
  const stage = workboardStageProgress(project.stage)
  const stageIndex = workboardStageIndex(project.stage)
  const artifactCount = Object.values(project.artifactCounts).reduce((total, count) => total + count, 0)
  const stageNode = workboardStageNode(project.stage)
  const stagePosition = stageIndex === null ? '阶段待确认' : `第 ${stageIndex + 1} / ${WORKBOARD_FLOW_STAGE_ORDER.length} 步 · ${stage.label}`
  return (
    <article className={styles.projectCard}>
      <div className={styles.projectTopline}>
        <span className="mg-badge" data-tone="accent">{stage.label}</span>
        <small>{projectStatusDisplayLabel(project.status)}{stage.progress === null ? ' · 进度待确认' : ` · ${stagePosition}`}</small>
      </div>
      <h3>{project.title}</h3>
      <div
        className={styles.projectProgress}
        role="progressbar"
        aria-label={`项目阶段：${stagePosition}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={stage.progress ?? undefined}
        title={stagePosition}
      >
        {stage.progress === null ? null : <span style={{ width: `${stage.progress}%` }} />}
        {stageIndex === null ? null : WORKBOARD_FLOW_STAGE_ORDER.map((flowStage, index) => (
          <i key={flowStage} data-reached={index <= stageIndex ? 'true' : undefined} data-current={index === stageIndex ? 'true' : undefined} style={{ left: `${workboardStageProgress(flowStage).progress ?? 0}%` }} />
        ))}
      </div>
      <footer><span>{artifactCount} 个当前产物</span><span>更新于 {formatDate(project.updatedAt)}</span><Link to={stageNode?.path ?? '/studio'}>{stageNode ? `前往${stageNode.pathLabel}` : '打开 Studio'}<ArrowRight size={14} /></Link></footer>
    </article>
  )
}

function readError(error: unknown, fallback: string): string {
  return describeBusinessError(error, {
    fallback,
    forbidden: '当前账户没有读取这部分数据的权限。',
    notFound: '当前工作区还没有可读取的数据。',
  })
}
