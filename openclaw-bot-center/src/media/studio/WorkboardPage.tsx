import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertCircle,
  ArrowRight,
  Bot,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  FilePenLine,
  Images,
  LoaderCircle,
  PackageCheck,
  PenTool,
  Plus,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import { BusinessOperationError, callBusinessOperation } from '../generatedBusinessPagesContract'
import { projectStatusDisplayLabel } from '../ui/displayLabels'
import { formatDate } from '../ui/ordinaryPagePrimitives'
import styles from './WorkboardPage.module.css'
import { filterWorkboardAttentionTasks, workboardStageProgress } from './workboardPresentation'

type DashboardResponse = {
  revision: number
  summary: {
    counts: {
      contentProjects: number
      runs: number
      assets: number
      publishedPosts: number
      reviews: number
    }
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

type LoadState<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string }

export default function WorkboardPage() {
  const { openWorkspace, tasks } = useMediaWeb()
  const [dashboard, setDashboard] = useState<LoadState<DashboardResponse>>({ status: 'loading' })
  const [projects, setProjects] = useState<LoadState<ProjectListResponse>>({ status: 'loading' })
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    let active = true
    setDashboard({ status: 'loading' })
    setProjects({ status: 'loading' })
    void Promise.allSettled([
      callBusinessOperation<DashboardResponse>('getDashboard'),
      callBusinessOperation<ProjectListResponse>('listContentProjects', { query: { pageSize: 8 } }),
    ]).then(([dashboardResult, projectResult]) => {
      if (!active) return
      setDashboard(dashboardResult.status === 'fulfilled'
        ? { status: 'ready', data: dashboardResult.value }
        : { status: 'error', message: readError(dashboardResult.reason, '今日汇总暂时无法读取。') })
      setProjects(projectResult.status === 'fulfilled'
        ? { status: 'ready', data: projectResult.value }
        : { status: 'error', message: readError(projectResult.reason, '内容项目暂时无法读取。') })
    })
    return () => { active = false }
  }, [refreshToken])

  const summary = dashboard.status === 'ready' ? dashboard.data.summary : null
  const pendingTotal = summary ? summary.pendingDecisions + summary.pendingPublishing + summary.pendingReviews + summary.taskSummary.needsAttention : 0
  const attentionTasks = useMemo(
    () => filterWorkboardAttentionTasks(tasks).slice(0, 4),
    [tasks],
  )
  const activeTasks = useMemo(() => tasks.filter((task) => !task.terminal).slice(0, 4), [tasks])

  return (
    <main className={styles.page} data-accent="studio">
      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <span className={styles.eyebrow}><Sparkles size={15} />CREATOR PRODUCTION DESK</span>
          <h1>今天把内容推进到<em>可交付</em></h1>
          <p>从活动和商单 Brief 出发，持续维护可编辑脚本、分镜、拍摄单、返修版本与发布包。</p>
          <div className={styles.heroActions}>
            <button className={styles.primaryAction} type="button" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}><Plus size={17} />新建内容项目</button>
            <button className={styles.secondaryAction} type="button" onClick={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })}><BriefcaseBusiness size={17} />导入商单 Brief</button>
            <button className={styles.ghostAction} type="button" onClick={() => openWorkspace()}><Bot size={17} />打开 Agent 任务</button>
          </div>
        </div>
        <div className={styles.heroSignal}>
          <span>今日推进信号</span>
          {dashboard.status === 'loading' ? <LoaderCircle className={styles.spin} size={22} /> : dashboard.status === 'error' ? <AlertCircle size={22} /> : <strong>{pendingTotal}</strong>}
          <p>{pendingTotal ? '项内容、审核或发布事项等待处理' : '当前没有显式阻塞，可以开始下一条内容'}</p>
          <small>{summary ? `数据更新于 ${formatDate(summary.generatedAt)}` : '仅显示当前账户真实数据'}</small>
        </div>
      </section>

      <section className={styles.metricGrid} aria-label="工作区关键指标">
        <MetricCard tone="mint" icon={<FilePenLine size={18} />} label="内容项目" value={summary?.counts.contentProjects} detail="从 Brief 到发布" />
        <MetricCard tone="violet" icon={<PenTool size={18} />} label="创作运行" value={summary?.counts.runs} detail="脚本、分镜与交付" />
        <MetricCard tone="amber" icon={<Images size={18} />} label="素材证据" value={summary?.counts.assets} detail="原始素材与拆解" />
        <MetricCard tone="blue" icon={<PackageCheck size={18} />} label="已发布作品" value={summary?.counts.publishedPosts} detail="等待持续复盘" />
      </section>

      <section className={styles.loopGrid} aria-label="高价值业务闭环">
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
          description="统一管理达人账号事实、报价快照、权益边界和项目机会。"
          steps={['达人', '报价', '权益', '商机', '复购']}
          to="/business"
        />
        <LoopCard
          tone="desk"
          icon={<TrendingUp size={20} />}
          kicker="DESK"
          title="内容情报到下一条可拍"
          description="热榜、拆解、选题和发布复盘共同进入下一轮内容生产。"
          steps={['监控', '拆解', '决策', '创作', '复盘']}
          to="/desk"
        />
      </section>

      <div className={styles.workspaceGrid}>
        <section className={styles.projectPanel}>
          <header className={styles.sectionHeader}>
            <div><span>正在推进</span><h2>内容项目</h2></div>
            <Link to="/overview">高级项目视图<ArrowRight size={15} /></Link>
          </header>
          {projects.status === 'loading' ? <PanelState icon={<LoaderCircle className={styles.spin} size={20} />} title="正在读取内容项目" /> : null}
          {projects.status === 'error' ? <PanelState icon={<AlertCircle size={20} />} title={projects.message} action={<button type="button" onClick={() => setRefreshToken((value) => value + 1)}>重新读取</button>} /> : null}
          {projects.status === 'ready' && projects.data.items.length ? (
            <div className={styles.projectList}>
              {projects.data.items.slice(0, 5).map((project) => <ProjectCard key={project.publicProjectId} project={project} />)}
            </div>
          ) : null}
          {projects.status === 'ready' && !projects.data.items.length ? <PanelState icon={<Target size={20} />} title="还没有内容项目" detail="从活动、商单、灵感或素材开始创建第一条可交付内容。" action={<button type="button" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}>创建项目</button>} /> : null}
        </section>

        <aside className={styles.actionPanel}>
          <header className={styles.sectionHeader}>
            <div><span>行动收件箱</span><h2>需要你处理</h2></div>
            <button type="button" onClick={() => openWorkspace()}>全部任务</button>
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
              <div className={styles.actionEmpty}><CheckCircle2 size={22} /><strong>当前没有待处理任务</strong><span>可以创建下一条内容，或进入 Desk 研究新的方向。</span></div>
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

function MetricCard({ tone, icon, label, value, detail }: { tone: 'mint' | 'violet' | 'amber' | 'blue'; icon: ReactNode; label: string; value?: number; detail: string }) {
  return <article className={styles.metricCard} data-tone={tone}><span>{icon}</span><div><small>{label}</small><strong>{value === undefined ? '—' : value}</strong><p>{detail}</p></div></article>
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
  const stage = workboardStageProgress(project.stage)
  const artifactCount = Object.values(project.artifactCounts).reduce((total, count) => total + count, 0)
  return (
    <article className={styles.projectCard}>
      <div className={styles.projectTopline}>
        <span>{stage.label}</span>
        <small>{projectStatusDisplayLabel(project.status)}{stage.progress === null ? ' · 进度待确认' : null}</small>
      </div>
      <h3>{project.title}</h3>
      <div className={styles.projectProgress}>{stage.progress === null ? null : <span style={{ width: `${stage.progress}%` }} />}</div>
      <footer><span>{artifactCount} 个当前产物</span><span>更新于 {formatDate(project.updatedAt)}</span><Link to="/studio">打开 Studio<ArrowRight size={14} /></Link></footer>
    </article>
  )
}

function PanelState({ icon, title, detail, action }: { icon: ReactNode; title: string; detail?: string; action?: ReactNode }) {
  return <div className={styles.panelState}>{icon}<strong>{title}</strong>{detail ? <span>{detail}</span> : null}{action}</div>
}

function readError(error: unknown, fallback: string): string {
  if (error instanceof BusinessOperationError) {
    if (error.status === 401 || error.status === 403) return '当前账户没有读取这部分数据的权限。'
    if (error.status === 404) return '当前工作区还没有可读取的数据。'
  }
  return fallback
}
