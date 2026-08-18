import { useEffect, useState, type ReactNode } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Database,
  FileCheck2,
  FolderKanban,
  Hash,
  Layers3,
  LoaderCircle,
  Route,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useMediaWeb } from './MediaWebWorkspace'
import { BusinessOperationError, callBusinessOperation } from './generatedBusinessPagesContract'
import { loginUrl } from './mediaWebApi'
import { runStatusLabel, runStatusTone } from './statusPresentation'
import { PlatformIdentity } from './ui/PlatformIdentity'
import { mediaTypeDisplayLabel } from './ui/ordinaryDataLabels'
import styles from './CreationRunDetailPage.module.css'

type SectionName = 'sources' | 'decisions' | 'outputs'

type RunSummary = {
  publicRunId: string
  title: string
  platform: string | null
  contentType: string | null
  trackName: string | null
  entrypoint: string
  status: string
  availableSections: SectionName[]
  publicProjectId: string | null
  createdAt: string
  updatedAt: string
  revision: number
}

type RunResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  run: RunSummary
}

type DetailState =
  | { status: 'idle' | 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: RunResponse }

type SummaryItem = Readonly<{
  label: string
  value: ReactNode
  icon: typeof CheckCircle2
}>

const RUN_FIELD_LABELS = {
  public_run_id: '公开运行编号',
  available_sections: '可用分区',
  response_revision: '响应修订',
} as const

const SECTION_PRESENTATION: Record<SectionName, { label: string; detail: string; icon: typeof Layers3 }> = {
  sources: { label: '来源', detail: '创作使用的素材与证据', icon: Layers3 },
  decisions: { label: '决定', detail: '选题与人工确认结果', icon: Route },
  outputs: { label: '输出', detail: '生成内容与成果文档', icon: FileCheck2 },
}

export default function CreationRunDetailPage() {
  const { runId = '' } = useParams()
  const { runtimeState, session } = useMediaWeb()
  const [detail, setDetail] = useState<DetailState>({ status: 'idle' })

  useEffect(() => {
    if (runtimeState !== 'authenticated' || !session || !runId) return
    const controller = new AbortController()
    setDetail({ status: 'loading' })
    callBusinessOperation<RunResponse>('getRun', {
      path: { publicRunId: runId },
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setDetail({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setDetail({ status: 'error', message: detailError(error) })
      })
    return () => controller.abort()
  }, [runId, runtimeState, session])

  if (runtimeState === 'checking' || detail.status === 'loading') return <DetailLoading />
  if (runtimeState === 'unauthenticated') {
    return <Gate icon={<Database size={24} />} title="登录后查看创作运行" detail="当前运行仅对所属账户开放。" action={<a className="primary-button" href={loginUrl()}>登录</a>} />
  }
  if (runtimeState === 'unavailable' || detail.status === 'error') {
    return <Gate icon={<AlertCircle size={24} />} title="创作运行暂时不可用" detail={detail.status === 'error' ? detail.message : '任务服务尚未连接。'} />
  }
  if (detail.status !== 'ready') return <DetailLoading />

  const run = detail.data.run
  const statusTone = runStatusTone(run.status)
  const summaryItems: SummaryItem[] = [
    { label: '运行状态', value: runStatusLabel(run.status), icon: CheckCircle2 },
    { label: '创作入口', value: run.entrypoint || '未记录', icon: Route },
    { label: '发布平台', value: run.platform ? <PlatformIdentity platform={run.platform} size="sm" /> : '未记录', icon: FolderKanban },
    { label: '内容形态', value: run.contentType ? mediaTypeDisplayLabel(run.contentType) : '未记录', icon: FileCheck2 },
  ]

  return (
    <main className={`fidelity-page ${styles.page}`} data-run-detail-layout="compact">
      <section className={styles.prelude} data-page-prelude>
        <Link className={styles.backLink} to="/runs"><ArrowLeft size={16} />返回创作与交付</Link>
        <div className={styles.headingRow}>
          <div className={styles.titleBlock}>
            <span>创作运行</span>
            <h1>{run.title}</h1>
            <p>查看本次运行的状态、业务上下文和已持久化内容。</p>
          </div>
          <span className={styles.statusBadge} data-tone={statusTone}><span aria-hidden="true" />{runStatusLabel(run.status)}</span>
        </div>
      </section>

      <section className={styles.summaryBand} aria-label="运行摘要">
        {summaryItems.map(({ label, value, icon: Icon }) => (
          <div className={styles.summaryItem} key={label}>
            <Icon size={17} aria-hidden="true" />
            <div className={styles.summaryCopy}>
              <span className={styles.summaryLabel}>{label}</span>
              <strong className={styles.summaryValue}>
                {typeof value === 'string' ? <span className={styles.summaryText}>{value}</span> : value}
              </strong>
            </div>
          </div>
        ))}
      </section>

      <div className={styles.contentGrid}>
        <section className={styles.panel} aria-labelledby="run-sections-title">
          <header className={styles.panelHeader}>
            <div><Layers3 size={18} aria-hidden="true" /><h2 id="run-sections-title">运行内容</h2></div>
            <span>{run.availableSections.length} 个分区</span>
          </header>
          {run.availableSections.length ? (
            <div className={styles.sectionList}>
              {run.availableSections.map((section) => {
                const presentation = SECTION_PRESENTATION[section]
                const Icon = presentation.icon
                return <article className={styles.sectionItem} key={section}><span><Icon size={18} aria-hidden="true" /></span><div><h3>{presentation.label}</h3><p>{presentation.detail}</p></div><strong>已记录</strong></article>
              })}
            </div>
          ) : (
            <div className={styles.emptyState}>
              <Layers3 size={22} aria-hidden="true" />
              <strong>暂无可用内容分区</strong>
              <span>本次运行仅保留基础运行信息。</span>
            </div>
          )}
        </section>

        <aside className={styles.panel} aria-labelledby="run-metadata-title">
          <header className={styles.panelHeader}>
            <div><Hash size={18} aria-hidden="true" /><h2 id="run-metadata-title">运行信息</h2></div>
          </header>
          <dl className={styles.metadataList}>
            <MetadataRow icon={<Hash size={15} />} label={RUN_FIELD_LABELS.public_run_id} value={<code>{run.publicRunId}</code>} />
            <MetadataRow icon={<FolderKanban size={15} />} label="关联项目" value={run.publicProjectId || '未关联项目'} />
            <MetadataRow icon={<Route size={15} />} label="内容赛道" value={run.trackName || '未记录'} />
            <MetadataRow icon={<FileCheck2 size={15} />} label="运行修订" value={String(run.revision)} />
            <MetadataRow icon={<Database size={15} />} label={RUN_FIELD_LABELS.response_revision} value={String(detail.data.revision)} />
            <MetadataRow icon={<CalendarDays size={15} />} label="创建时间" value={formatRunDate(run.createdAt)} />
            <MetadataRow icon={<Clock3 size={15} />} label="更新时间" value={formatRunDate(run.updatedAt)} />
          </dl>
          <span className="sr-only">{RUN_FIELD_LABELS.available_sections}</span>
        </aside>
      </div>
    </main>
  )
}

function MetadataRow({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return <div className={styles.metadataRow}><dt>{icon}<span>{label}</span></dt><dd>{value}</dd></div>
}

function Gate({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: string; action?: ReactNode }) {
  return <main><Link className="back-link" to="/runs"><ArrowLeft size={16} />返回创作运行</Link><div className="detail-gate">{icon}<h1>{title}</h1><p>{detail}</p>{action}</div></main>
}

function DetailLoading() {
  return <main className="detail-loading" aria-busy="true"><LoaderCircle className="spin" size={23} /><span>正在读取创作运行详情</span></main>
}

function detailError(error: unknown): string {
  if (error instanceof BusinessOperationError) {
    if (error.status === 401 || error.status === 403) return '当前账户无权查看这条运行。'
    if (error.status === 404) return '这条创作运行不存在或已不可用。'
    return error.message
  }
  return error instanceof Error && error.message ? error.message : '创作运行详情加载失败。'
}

function formatRunDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '暂无'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}
