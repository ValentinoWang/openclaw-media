import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  AlertCircle,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  FileArchive,
  FolderOpen,
  RefreshCw,
  Search,
  ShieldCheck,
  TimerReset,
} from 'lucide-react'
import {
  BusinessOperationError,
  callBusinessOperation,
} from '../../generatedBusinessPagesContract'
import { isForbiddenError } from '../../businessErrorPresentation'
import { useMediaWeb } from '../../MediaWebWorkspace'
import { runStatusLabel, runStatusTone } from '../../statusPresentation'
import { Metric } from '../../ui/Metric'
import { SearchBox } from '../../ui/SearchBox'
import { SurfaceState } from '../../ui/SurfaceState'
import { describeBusinessError } from '../../ui/businessOperationError'
import type { LoadState } from '../../ui/loadState'
import { formatDateTime } from '../../ui/datetime'
import styles from './AdminTenantsPage.module.css'

const PAGE_SIZE = 20
const AUDIT_REASON_MIN_LENGTH = 8

type AdminTenantSummary = {
  publicTenantId: string
  status: string
  userCount: number
  runCount: number
  assetCount: number
  archiveCount: number
  usageCharge: string
  lastActiveAt: string | null
}

type AdminTenantListResponse = {
  schemaVersion: string
  revision: number
  items: AdminTenantSummary[]
  nextCursor: string | null
}

type AdminTenantResponse = {
  schemaVersion: string
  revision: number
  tenant: AdminTenantSummary
}

type AdminTenantRun = {
  publicRunId: string
  title: string
  platform: string | null
  contentType: string | null
  trackName: string | null
  entrypoint: string
  status: string
  availableSections: string[]
  publicProjectId: string | null
  createdAt: string
  updatedAt: string
  revision: number
}

type AdminTenantRunListResponse = {
  schemaVersion: string
  revision: number
  items: AdminTenantRun[]
  nextCursor: string | null
}

// LoadState<T> comes from ui/loadState.ts (cluster FE-04) -- this page only ever produces
// idle/loading/ready/permission/error, never the type's empty/notFound branches.

export default function AdminTenantsPage() {
  const { runtimeState, session } = useMediaWeb()
  const canRead = runtimeState === 'authenticated' && session?.role === 'admin'
  const [directorySearch, setDirectorySearch] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [directoryCursorTrail, setDirectoryCursorTrail] = useState<string[]>([])
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null)
  const [auditReason, setAuditReason] = useState('')
  const [submittedReason, setSubmittedReason] = useState('')
  const [validationMessage, setValidationMessage] = useState('')
  const [directoryRefresh, setDirectoryRefresh] = useState(0)
  const [auditRefresh, setAuditRefresh] = useState(0)
  const [runCursorTrail, setRunCursorTrail] = useState<string[]>([])

  const directoryCursor = directoryCursorTrail.at(-1)
  const runCursor = runCursorTrail.at(-1)
  const directoryState = useTenantDirectory(canRead, submittedSearch, directoryCursor, directoryRefresh)
  const detailState = useAuditedTenant(canRead, selectedTenantId, submittedReason, auditRefresh)
  const runsState = useAuditedTenantRuns(canRead, selectedTenantId, submittedReason, runCursor, auditRefresh)

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmittedSearch(directorySearch.trim())
    setDirectoryCursorTrail([])
  }

  function selectTenant(tenant: AdminTenantSummary) {
    setSelectedTenantId(tenant.publicTenantId)
    setAuditReason('')
    setSubmittedReason('')
    setValidationMessage('')
    setRunCursorTrail([])
  }

  function submitAudit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedTenantId) {
      setValidationMessage('请先从租户目录选择一个目标。')
      return
    }
    const reason = auditReason.trim()
    if (reason.length < AUDIT_REASON_MIN_LENGTH) {
      setValidationMessage('审计原因至少需要 8 个字符。')
      return
    }
    setValidationMessage('')
    setSubmittedReason(reason)
    setRunCursorTrail([])
    setAuditRefresh((value) => value + 1)
  }

  function clearSelection() {
    setSelectedTenantId(null)
    setAuditReason('')
    setSubmittedReason('')
    setValidationMessage('')
    setRunCursorTrail([])
  }

  function refresh() {
    setDirectoryRefresh((value) => value + 1)
    if (selectedTenantId && submittedReason) setAuditRefresh((value) => value + 1)
  }

  return <main className={'fidelity-page ' + styles.page} data-accent="studio" data-page-ownership="governance">
    <header className="page-heading mg-hero" data-component="mg-hero" data-page-prelude>
      <div>
        <p className="mg-eyebrow" data-component="mg-eyebrow">平台治理控制台</p>
        <h1>租户资源</h1>
        <p className="mg-hero-lead">从服务端目录选择目标，再读取脱敏资源和运行审计。</p>
      </div>
      {canRead ? <button
        className={'mg-btn mg-btn-ghost ' + styles.iconButton}
        data-component="mg-btn"
        type="button"
        onClick={refresh}
        disabled={directoryState.status === 'loading' || detailState.status === 'loading' || runsState.status === 'loading'}
        aria-label="刷新租户资源"
        title="刷新租户资源"
      >
        <RefreshCw size={17} aria-hidden="true" />
      </button> : null}
    </header>

    {runtimeState === 'checking' ? <RuntimeState kind="loading" title="正在确认管理员权限" detail="租户目录暂不发起读取请求。" /> : null}
    {runtimeState === 'unauthenticated' ? <RuntimeState kind="forbidden" title="当前会话未登录" detail="租户资源不会在未确认身份前加载。" /> : null}
    {runtimeState === 'unavailable' ? <RuntimeState kind="error" title="会话服务不可用" detail="租户资源暂时不能读取，请稍后重试。" /> : null}
    {runtimeState === 'authenticated' && !canRead ? <RuntimeState kind="forbidden" title="当前会话没有管理员读取权限" detail="租户资源不会在未确认管理员身份时加载。" /> : null}

    {canRead ? <div className={styles.surface}>
      <section className={'section-panel mg-panel ' + styles.scopePanel} data-component="mg-panel" aria-label="租户目录查询">
        <form className={styles.scopeForm} onSubmit={submitSearch}>
          <SearchBox value={directorySearch} onChange={setDirectorySearch} label="按状态或账号检索" maxLength={200} />
          <button className={'mg-btn mg-btn-primary ' + styles.primaryAction} data-component="mg-btn" type="submit" disabled={directoryState.status === 'loading'}>
            <Search size={15} aria-hidden="true" />
            查询目录
          </button>
        </form>
        <div className={styles.scopeFooter}>
          <div className={'mg-badge ' + (selectedTenantId ? styles.scopeBadgeSelected : styles.scopeBadgePending)} data-component="mg-badge" data-tone={selectedTenantId ? 'success' : 'neutral'} role="status">
            <Building2 size={17} aria-hidden="true" />
            <span>{selectedTenantId ? '当前目标：' + selectedTenantId : '尚未选择目标租户'}</span>
          </div>
          {selectedTenantId ? <button className={'mg-btn mg-btn-ghost ' + styles.quietAction} data-component="mg-btn" type="button" onClick={clearSelection}>清除目标</button> : null}
        </div>
      </section>

      <nav className="mg-tabs" aria-label="租户治理分区" role="tablist" data-component="mg-tabs">
        <a className="mg-tab mg-tab-pill" href="#tenant-directory" role="tab" aria-selected="true" aria-controls="tenant-directory">租户目录</a>
        <a className="mg-tab mg-tab-pill" href="#tenant-detail" role="tab" aria-selected="false" aria-controls="tenant-detail">租户详情</a>
        <a className="mg-tab mg-tab-pill" href="#tenant-runs" role="tab" aria-selected="false" aria-controls="tenant-runs">运行审计</a>
        <a className="mg-tab mg-tab-pill" href="#tenant-audit" role="tab" aria-selected="false" aria-controls="tenant-audit">审计检查器</a>
      </nav>

      <div className={styles.workspace} data-page-layout="persistent-rail">
        <div className={styles.mainColumn} data-page-primary data-primary-flow>
          <TenantDirectoryPanel
            state={directoryState}
            selectedTenantId={selectedTenantId}
            search={submittedSearch}
            page={directoryCursorTrail.length + 1}
            onSelect={selectTenant}
            onPrevious={() => setDirectoryCursorTrail((value) => value.slice(0, -1))}
            onNext={() => {
              if (directoryState.status === 'ready' && directoryState.data.nextCursor) {
                setDirectoryCursorTrail((value) => [...value, directoryState.data.nextCursor as string])
              }
            }}
          />
          <TenantDetailPanel state={detailState} selectedTenantId={selectedTenantId} onRetry={refresh} />
          <TenantRunsPanel
            state={runsState}
            selectedTenantId={selectedTenantId}
            page={runCursorTrail.length + 1}
            onPrevious={() => setRunCursorTrail((value) => value.slice(0, -1))}
            onNext={() => {
              if (runsState.status === 'ready' && runsState.data.nextCursor) {
                setRunCursorTrail((value) => [...value, runsState.data.nextCursor as string])
              }
            }}
            onRetry={refresh}
          />
        </div>
        <AuditInspector
          selectedTenantId={selectedTenantId}
          reason={auditReason}
          submittedReason={submittedReason}
          validationMessage={validationMessage}
          detailState={detailState}
          runsState={runsState}
          onReasonChange={(value) => {
            setAuditReason(value)
            setValidationMessage('')
          }}
          onSubmit={submitAudit}
        />
      </div>
    </div> : null}
  </main>
}

function useTenantDirectory(permitted: boolean, search: string, cursor: string | undefined, refresh: number): LoadState<AdminTenantListResponse> {
  const [state, setState] = useState<LoadState<AdminTenantListResponse>>({ status: 'idle' })

  useEffect(() => {
    if (!permitted) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<AdminTenantListResponse>('listAdminTenants', {
      query: { cursor, pageSize: PAGE_SIZE, search: search || undefined },
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState(toLoadState(error, '租户目录'))
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [cursor, permitted, refresh, search])

  return state
}

function useAuditedTenant(permitted: boolean, publicTenantId: string | null, auditReason: string, refresh: number): LoadState<AdminTenantResponse> {
  const [state, setState] = useState<LoadState<AdminTenantResponse>>({ status: 'idle' })

  useEffect(() => {
    if (!permitted || !publicTenantId || auditReason.length < AUDIT_REASON_MIN_LENGTH) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<AdminTenantResponse>('getAdminTenant', {
      path: { publicTenantId },
      auditReason,
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState(toLoadState(error, '租户详情'))
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [auditReason, permitted, publicTenantId, refresh])

  return state
}

function useAuditedTenantRuns(permitted: boolean, publicTenantId: string | null, auditReason: string, cursor: string | undefined, refresh: number): LoadState<AdminTenantRunListResponse> {
  const [state, setState] = useState<LoadState<AdminTenantRunListResponse>>({ status: 'idle' })

  useEffect(() => {
    if (!permitted || !publicTenantId || auditReason.length < AUDIT_REASON_MIN_LENGTH) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<AdminTenantRunListResponse>('listAdminTenantRuns', {
      path: { publicTenantId },
      query: { cursor, pageSize: PAGE_SIZE },
      auditReason,
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState(toLoadState(error, '租户运行'))
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [auditReason, cursor, permitted, publicTenantId, refresh])

  return state
}

function toLoadState<T>(error: unknown, subject: string): LoadState<T> {
  // notFound classifies to this page's plain 'error' branch, not LoadState's 'notFound' --
  // this page's server classifier keeps that message in the normal error surface, so a bare
  // classification merge here would silently drop the message (see FE-04 divergences).
  if (isForbiddenError(error)) {
    return { status: 'permission', error: '当前会话没有读取' + subject + '的权限。' }
  }
  const message = describeBusinessError(error, {
    fallback: error instanceof Error && error.message ? error.message : subject + '读取失败，请稍后再试。',
    notFound: '目标租户不存在或不可见。',
    byCode: { invalid_request: error instanceof BusinessOperationError ? error.message : '' },
  })
  return { status: 'error', error: message }
}

function TenantDirectoryPanel({ state, selectedTenantId, search, page, onSelect, onPrevious, onNext }: {
  state: LoadState<AdminTenantListResponse>
  selectedTenantId: string | null
  search: string
  page: number
  onSelect: (tenant: AdminTenantSummary) => void
  onPrevious: () => void
  onNext: () => void
}) {
  return <section className={'section-panel mg-panel ' + styles.directoryPanel} data-component="mg-panel" id="tenant-directory" aria-labelledby="tenant-directory-heading">
    <header className={'mg-panel-head ' + styles.panelHeading} data-component="mg-panel-head">
      <div>
        <h2 id="tenant-directory-heading">租户目录</h2>
        <p>{search ? '当前检索：' + search : '服务端脱敏聚合'}</p>
      </div>
      <span className={'mg-badge ' + styles.readOnlyTag} data-component="mg-badge" data-tone="info"><ShieldCheck size={14} aria-hidden="true" />只读</span>
    </header>
    {state.status === 'idle' ? <SurfaceState kind="empty" title="等待会话权限" detail="确认管理员身份后读取目录。" action={null} /> : null}
    {state.status !== 'idle' ? <ResourceStateSurface
      state={state}
      subject="租户目录"
      loadingDetail="服务端正在返回当前管理员可见的摘要。"
      emptyTitle="暂无匹配租户"
      emptyDetail="服务端当前查询范围返回 0 条记录。"
      isEmpty={(data) => data.items.length === 0}
      render={(data) => <>
        <div className={styles.tableViewport} role="region" aria-label="租户目录表格" tabIndex={0}>
          <table className={styles.directoryTable}>
            <thead>
              <tr>
                <th scope="col">公开租户引用</th>
                <th scope="col">状态</th>
                <th scope="col">用户</th>
                <th scope="col">运行</th>
                <th scope="col">素材</th>
                <th scope="col">归档</th>
                <th scope="col">用量</th>
                <th scope="col">最近活动</th>
                <th scope="col"><span className={styles.visuallyHidden}>操作</span></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((tenant) => <tr key={tenant.publicTenantId} className={tenant.publicTenantId === selectedTenantId ? styles.selectedRow : undefined}>
                <th scope="row"><code className={styles.publicId}>{tenant.publicTenantId}</code></th>
                <td><StatusBadge status={tenant.status} /></td>
                <td>{formatInteger(tenant.userCount)}</td>
                <td>{formatInteger(tenant.runCount)}</td>
                <td>{formatInteger(tenant.assetCount)}</td>
                <td>{formatInteger(tenant.archiveCount)}</td>
                <td><span className={styles.monoValue}>{tenant.usageCharge}</span></td>
                <td><span className={styles.cellText}>{formatDate(tenant.lastActiveAt)}</span></td>
                <td><button className={'mg-btn mg-btn-ghost ' + styles.rowAction} data-component="mg-btn" type="button" onClick={() => onSelect(tenant)} aria-label={'查看租户 ' + tenant.publicTenantId} title="选择此租户">查看<ChevronRight size={14} aria-hidden="true" /></button></td>
              </tr>)}
            </tbody>
          </table>
        </div>
        <Pagination page={page} canPrevious={page > 1} canNext={!!data.nextCursor} onPrevious={onPrevious} onNext={onNext} label="租户目录分页" />
      </>}
    /> : null}
  </section>
}

function TenantDetailPanel({ state, selectedTenantId, onRetry }: { state: LoadState<AdminTenantResponse>; selectedTenantId: string | null; onRetry: () => void }) {
  return <section className={'section-panel mg-panel ' + styles.detailPanel} data-component="mg-panel" id="tenant-detail" aria-labelledby="tenant-detail-heading">
    <header className={'mg-panel-head ' + styles.panelHeading} data-component="mg-panel-head">
      <div>
        <h2 id="tenant-detail-heading">租户详情</h2>
        <p>{selectedTenantId ? '目标：' + selectedTenantId : '选择目标并提交审计原因后读取'}</p>
      </div>
      {state.status === 'ready' ? <span className={'mg-badge ' + styles.receipt} data-component="mg-badge" data-tone="neutral"><ClipboardList size={14} aria-hidden="true" />修订 {state.data.revision}</span> : null}
    </header>
    {state.status === 'idle' ? <AuditPendingState selected={!!selectedTenantId} subject="租户详情" /> : null}
    {state.status !== 'idle' ? <ResourceStateSurface
      state={state}
      subject="租户详情"
      loadingDetail="本次读取会写入不可变管理员审计。"
      emptyTitle="暂无租户详情"
      emptyDetail="服务端当前查询范围没有返回可见的租户详情。"
      onRetry={onRetry}
      render={(data) => <TenantDetailFacts tenant={data.tenant} />}
    /> : null}
  </section>
}

function TenantDetailFacts({ tenant }: { tenant: AdminTenantSummary }) {
  return <div className={styles.detailBody}>
    <div className={'mg-metric-grid ' + styles.metricGrid} data-component="mg-metric-grid">
      <Metric className={styles.metric} iconClassName={styles.metricIcon} label="用户" value={formatInteger(tenant.userCount)} icon={<Building2 size={16} />} />
      <Metric className={styles.metric} iconClassName={styles.metricIcon} label="运行" value={formatInteger(tenant.runCount)} icon={<ClipboardList size={16} />} />
      <Metric className={styles.metric} iconClassName={styles.metricIcon} label="素材" value={formatInteger(tenant.assetCount)} icon={<FolderOpen size={16} />} />
      <Metric className={styles.metric} iconClassName={styles.metricIcon} label="归档" value={formatInteger(tenant.archiveCount)} icon={<FileArchive size={16} />} />
      <Metric className={styles.metric} iconClassName={styles.metricIcon} label="用量" value={tenant.usageCharge} icon={<TimerReset size={16} />} />
    </div>
    <dl className={styles.factList}>
      <div><dt>公开租户引用</dt><dd><code>{tenant.publicTenantId}</code></dd></div>
      <div><dt>租户状态</dt><dd><StatusBadge status={tenant.status} /></dd></div>
      <div><dt>最近活动</dt><dd>{formatDate(tenant.lastActiveAt)}</dd></div>
    </dl>
  </div>
}

function TenantRunsPanel({ state, selectedTenantId, page, onPrevious, onNext, onRetry }: { state: LoadState<AdminTenantRunListResponse>; selectedTenantId: string | null; page: number; onPrevious: () => void; onNext: () => void; onRetry: () => void }) {
  return <section className={'section-panel mg-panel ' + styles.runsPanel} data-component="mg-panel" id="tenant-runs" aria-labelledby="tenant-runs-heading">
    <header className={'mg-panel-head ' + styles.panelHeading} data-component="mg-panel-head">
      <div>
        <h2 id="tenant-runs-heading">租户运行审计</h2>
        <p>{selectedTenantId ? '仅显示当前目标租户的运行摘要' : '选择目标后读取运行摘要'}</p>
      </div>
      {state.status === 'ready' ? <span className={'mg-badge ' + styles.receipt} data-component="mg-badge" data-tone="neutral"><ClipboardList size={14} aria-hidden="true" />修订 {state.data.revision}</span> : null}
    </header>
    {state.status === 'idle' ? <AuditPendingState selected={!!selectedTenantId} subject="租户运行" /> : null}
    {state.status !== 'idle' ? <ResourceStateSurface
      state={state}
      subject="租户运行"
      loadingDetail="本次读取会写入不可变管理员审计。"
      emptyTitle="暂无运行摘要"
      emptyDetail="服务端当前查询范围返回 0 条记录。"
      onRetry={onRetry}
      isEmpty={(data) => data.items.length === 0}
      render={(data) => <>
        <div className={styles.tableViewport} role="region" aria-label="租户运行审计表" tabIndex={0}>
          <table className={styles.runsTable}>
            <thead><tr><th scope="col">公开运行引用</th><th scope="col">标题</th><th scope="col">入口</th><th scope="col">状态</th><th scope="col">可用分区</th><th scope="col">项目引用</th><th scope="col">更新时间</th></tr></thead>
            <tbody>{data.items.map((run) => <tr key={run.publicRunId}>
              <th scope="row"><code className={styles.publicId}>{run.publicRunId}</code></th>
              <td><span className={styles.cellText}>{run.title}</span></td>
              <td><span className={styles.cellText}>{run.entrypoint}</span></td>
              <td><StatusBadge status={run.status} /></td>
              <td><span className={styles.sectionList}>{run.availableSections.length ? run.availableSections.map(sectionLabel).join('、') : '无'}</span></td>
              <td><span className={styles.cellText}>{run.publicProjectId || '暂无'}</span></td>
              <td><span className={styles.cellText}>{formatDate(run.updatedAt)}</span></td>
            </tr>)}</tbody>
          </table>
        </div>
        <Pagination page={page} canPrevious={page > 1} canNext={!!data.nextCursor} onPrevious={onPrevious} onNext={onNext} label="租户运行审计分页" />
      </>}
    /> : null}
  </section>
}

function AuditInspector({ selectedTenantId, reason, submittedReason, validationMessage, detailState, runsState, onReasonChange, onSubmit }: { selectedTenantId: string | null; reason: string; submittedReason: string; validationMessage: string; detailState: LoadState<AdminTenantResponse>; runsState: LoadState<AdminTenantRunListResponse>; onReasonChange: (value: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  const hasPendingRead = detailState.status === 'loading' || runsState.status === 'loading'
  const hasReadback = detailState.status === 'ready' || runsState.status === 'ready'
  return <aside className={'section-panel mg-panel ' + styles.inspector} data-component="mg-panel" id="tenant-audit" aria-labelledby="audit-inspector-heading" data-page-inspector data-page-terminal-surface="inspector">
    <header className={'mg-panel-head ' + styles.panelHeading} data-component="mg-panel-head">
      <div><h2 id="audit-inspector-heading">审计检查器</h2><p>目标和原因提交后才读取跨租户资源。</p></div>
      <ShieldCheck size={19} aria-hidden="true" />
    </header>
    <dl className={styles.factList + ' ' + styles.inspectorFacts}>
      <div><dt>目标租户</dt><dd className={styles.longValue}>{selectedTenantId ? <code>{selectedTenantId}</code> : '尚未选择'}</dd></div>
      <div><dt>审计原因</dt><dd>
        <form className={styles.reasonForm} onSubmit={onSubmit}>
          <textarea value={reason} maxLength={500} minLength={AUDIT_REASON_MIN_LENGTH} rows={4} onChange={(event) => onReasonChange(event.target.value)} placeholder="填写本次读取的业务原因" aria-label="本次审计原因" aria-invalid={validationMessage ? 'true' : 'false'} />
          <span className={styles.fieldNote}>至少 8 个字符；详情和运行分页均会留痕。</span>
          {validationMessage ? <span className={styles.validationMessage} role="alert"><AlertCircle size={14} aria-hidden="true" />{validationMessage}</span> : null}
          <button className={'mg-btn mg-btn-primary ' + styles.primaryAction} data-component="mg-btn" type="submit" disabled={!selectedTenantId || reason.trim().length < AUDIT_REASON_MIN_LENGTH || hasPendingRead}><ShieldCheck size={15} aria-hidden="true" />读取目标资源</button>
        </form>
      </dd></div>
      <div><dt>查询回执</dt><dd className={styles.longValue}>{hasPendingRead ? '正在读取并写入审计' : hasReadback ? '服务端已返回当前目标的读取结果' : submittedReason ? '等待读取' : '尚未提交审计请求'}</dd></div>
      {submittedReason ? <div><dt>已提交原因</dt><dd className={styles.longValue}>{submittedReason}</dd></div> : null}
    </dl>
    <div className={styles.readOnlyNotice}><CheckCircle2 size={17} aria-hidden="true" /><div><strong>只读资源</strong><p>页面不修改租户、运行、素材或归档数据；服务端只追加不可变读取审计。</p></div></div>
  </aside>
}

function RuntimeState({ kind, title, detail }: { kind: 'loading' | 'forbidden' | 'error'; title: string; detail: string }) {
  return <section className={'mg-panel ' + styles.runtimeState} data-component="mg-panel"><SurfaceState kind={kind} title={title} detail={detail} action={null} /></section>
}

function ResourceStateSurface<T>({ state, subject, loadingDetail, emptyTitle, emptyDetail, onRetry, isEmpty, render }: {
  state: LoadState<T>
  subject: string
  loadingDetail: string
  emptyTitle: string
  emptyDetail: string
  onRetry?: () => void
  isEmpty?: (data: T) => boolean
  render: (data: T) => ReactNode
}): ReactNode {
  if (state.status === 'idle') return null
  if (state.status === 'loading') return <SurfaceState kind="loading" title={'正在读取' + subject} detail={loadingDetail} action={null} />
  if (state.status === 'permission') return <SurfaceState kind="forbidden" title={subject + '不可读取'} detail={state.error} action={null} />
  if (state.status === 'notFound') return <SurfaceState kind="notFound" title="记录不存在" detail={state.error} action={null} />
  if (state.status === 'empty') return <SurfaceState kind="empty" title={emptyTitle} detail={emptyDetail} action={null} />
  if (state.status === 'error') {
    return <SurfaceState
      kind="error"
      title={subject + '读取失败'}
      detail={state.error}
      action={onRetry ? <button className={'mg-btn mg-btn-ghost ' + styles.inlineAction} data-component="mg-btn" type="button" onClick={onRetry}>重新读取</button> : null}
    />
  }
  if (isEmpty?.(state.data)) return <SurfaceState kind="empty" title={emptyTitle} detail={emptyDetail} action={null} />
  return render(state.data)
}

function AuditPendingState({ selected, subject }: { selected: boolean; subject: string }) {
  return <SurfaceState
    kind="empty"
    title={selected ? '等待审计请求' : '尚未选择目标租户'}
    detail={selected ? '在右侧填写原因并提交后，服务端才读取' + subject + '。' : '从租户目录选择目标后，此处会显示' + subject + '。'}
    action={null}
  />
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === 'active' ? 'success' : status === 'suspended' || status === 'disabled' ? 'danger' : runStatusTone(status)
  const label = status === 'active' ? '正常' : status === 'suspended' ? '已暂停' : status === 'disabled' ? '已停用' : runStatusLabel(status)
  return <span className={'mg-badge ' + styles.statusBadge} data-component="mg-badge" data-tone={tone}>{label}</span>
}

function Pagination({ page, canPrevious, canNext, onPrevious, onNext, label }: { page: number; canPrevious: boolean; canNext: boolean; onPrevious: () => void; onNext: () => void; label: string }) {
  return <nav className={styles.pagination} aria-label={label}><button className="mg-btn mg-btn-ghost" data-component="mg-btn" type="button" disabled={!canPrevious} onClick={onPrevious} aria-label="上一页" title="上一页"><ChevronLeft size={16} aria-hidden="true" /></button><span>第 {page} 页</span><button className="mg-btn mg-btn-ghost" data-component="mg-btn" type="button" disabled={!canNext} onClick={onNext} aria-label="下一页" title="下一页"><ChevronRight size={16} aria-hidden="true" /></button></nav>
}

function formatInteger(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatDate(value: string | null) {
  return formatDateTime(value)
}

function sectionLabel(value: string) {
  return value === 'sources' ? '来源' : value === 'decisions' ? '决定' : value === 'outputs' ? '输出' : value
}
