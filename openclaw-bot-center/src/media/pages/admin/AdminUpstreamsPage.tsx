import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  KeyRound,
  ReceiptText,
  RefreshCw,
  RotateCw,
  Server,
  ShieldAlert,
  ShieldCheck,
  Users,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { BusinessOperationError, callBusinessOperation } from '../../generatedBusinessPagesContract'
import { useMediaWeb } from '../../MediaWebWorkspace'
import { newIdempotencyKey } from '../../idempotency'
import { CANONICAL_UUID_PATTERN } from '../../identifiers'
import { formatTimestampFull } from '../../ui/datetime'
import styles from './AdminUpstreamsPage.module.css'

const SCHEMA_VERSION = 'media_web_business_pages_v2'

type CredentialHealth = 'healthy' | 'degraded' | 'unavailable' | 'revoked' | 'unknown'
type Summary = {
  availableAccountCount: number
  unhealthyAccountCount: number
  credentialHealth: CredentialHealth
  pendingReconciliationCount: number
  lastSyncedAt: string | null
  revision: number
}
type UpstreamResponse = { schemaVersion: string; revision: number; summary: Summary }
type MutationReceipt = { schemaVersion: string; revision: number; ok: boolean; updatedAt: string }
type JsonObject = { readonly [key: string]: unknown }
type LoadState =
  | { status: 'loading' }
  | { status: 'permission'; message: string }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: UpstreamResponse }
type ActionState = { kind: 'idle' | 'busy' | 'success' | 'error'; message: string }

const healthLabels: { readonly [key in CredentialHealth]: string } = {
  healthy: '健康',
  degraded: '降级',
  unavailable: '不可用',
  revoked: '已撤销',
  unknown: '未知',
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isDateTime(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}

function isHealth(value: unknown): value is CredentialHealth {
  return value === 'healthy' || value === 'degraded' || value === 'unavailable' ||
    value === 'revoked' || value === 'unknown'
}

function parseResponse(value: unknown): UpstreamResponse | null {
  if (!isObject(value) || value.schemaVersion !== SCHEMA_VERSION || !isCount(value.revision) || !isObject(value.summary)) return null
  const summary = value.summary
  if (!isCount(summary.availableAccountCount) || !isCount(summary.unhealthyAccountCount) ||
      !isHealth(summary.credentialHealth) || !isCount(summary.pendingReconciliationCount) ||
      !(summary.lastSyncedAt === null || isDateTime(summary.lastSyncedAt)) ||
      !isCount(summary.revision) || summary.revision !== value.revision) return null
  return {
    schemaVersion: value.schemaVersion,
    revision: value.revision,
    summary: {
      availableAccountCount: summary.availableAccountCount,
      unhealthyAccountCount: summary.unhealthyAccountCount,
      credentialHealth: summary.credentialHealth,
      pendingReconciliationCount: summary.pendingReconciliationCount,
      lastSyncedAt: summary.lastSyncedAt,
      revision: summary.revision,
    },
  }
}

function parseReceipt(value: unknown): MutationReceipt | null {
  if (!isObject(value) || value.schemaVersion !== SCHEMA_VERSION || !isCount(value.revision) ||
      typeof value.ok !== 'boolean' || !isDateTime(value.updatedAt)) return null
  return { schemaVersion: value.schemaVersion, revision: value.revision, ok: value.ok, updatedAt: value.updatedAt }
}

function isOperationReference(value: string): boolean {
  return CANONICAL_UUID_PATTERN.test(value.trim())
}

function publicError(error: unknown, fallback: string): string {
  if (error instanceof BusinessOperationError) {
    if (error.status === 401) return '当前登录已失效，请重新登录。'
    if (error.status === 403) return '当前会话没有执行此操作的权限。'
    if (error.status === 404) return '目标记录不存在或已不可用。'
    if (error.status === 409) return '数据已发生变化，请刷新后重试。'
    if (error.status >= 500) return '上游服务暂不可用，请稍后重试。'
  }
  return fallback
}

class ContractPayloadError extends Error {
  constructor() {
    super('B14 contract payload validation failed')
    this.name = 'ContractPayloadError'
  }
}

function count(value: number): string {
  return value.toLocaleString('zh-CN')
}

const timestamp = formatTimestampFull

function healthClass(value: CredentialHealth): string {
  if (value === 'healthy') return styles.statusHealthy
  if (value === 'degraded') return styles.statusDegraded
  if (value === 'unavailable') return styles.statusUnavailable
  if (value === 'revoked') return styles.statusRevoked
  return styles.statusUnknown
}

function healthDescription(value: CredentialHealth): string {
  if (value === 'healthy') return '当前凭证健康检查通过。'
  if (value === 'degraded') return '当前凭证健康检查存在异常。'
  if (value === 'unavailable') return '当前无法取得凭证健康结果。'
  if (value === 'revoked') return '当前凭证已经撤销。'
  return '当前凭证状态等待确认。'
}

function actionClass(value: ActionState['kind']): string {
  if (value === 'success') return styles.actionBannerSuccess
  if (value === 'error') return styles.actionBannerError
  return styles.actionBannerBusy
}

export default function AdminUpstreamsPage() {
  const { runtimeState, session } = useMediaWeb()
  const canRead = runtimeState === 'authenticated' && session?.role === 'admin'
  const canMutateCredential = canRead
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [action, setAction] = useState<ActionState>({ kind: 'idle', message: '' })
  const [operationReference, setOperationReference] = useState('')
  const [reconciliationReason, setReconciliationReason] = useState('')
  const [credentialReason, setCredentialReason] = useState('')
  const [revokeConfirmed, setRevokeConfirmed] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  const loadToken = useRef(0)
  const mutationKey = useRef({ fingerprint: '', value: '' })
  const data = loadState.status === 'ready' ? loadState.data : null
  const busy = action.kind === 'busy'
  const reconciliationReady = !!data && canRead && isOperationReference(operationReference) &&
    reconciliationReason.trim().length > 0 && !busy
  const credentialReady = !!data && canMutateCredential && credentialReason.trim().length > 0 && !busy

  const loadPage = useCallback(async (): Promise<UpstreamResponse | null> => {
    const tokenId = ++loadToken.current
    controllerRef.current?.abort()
    if (runtimeState === 'checking') {
      setLoadState({ status: 'loading' })
      return null
    }
    if (!canRead) {
      setLoadState({
        status: 'permission',
        message: runtimeState === 'authenticated' ? '当前会话没有管理员权限。' : '当前会话不可用。',
      })
      return null
    }
    const controller = new AbortController()
    controllerRef.current = controller
    setLoadState({ status: 'loading' })
    try {
      const payload = await callBusinessOperation<unknown>('getAdminUpstreams', { signal: controller.signal })
      const parsed = parseResponse(payload)
      if (!parsed) throw new ContractPayloadError()
      if (controller.signal.aborted || tokenId !== loadToken.current) return null
      setLoadState({ status: 'ready', data: parsed })
      return parsed
    } catch (error) {
      if (controller.signal.aborted || tokenId !== loadToken.current) return null
      setLoadState({ status: 'error', message: publicError(error, '上游汇总读取未完成。') })
      return null
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null
    }
  }, [canRead, runtimeState])

  useEffect(() => {
    void loadPage()
    return () => controllerRef.current?.abort()
  }, [loadPage])

  function keyFor(fingerprint: string): string {
    if (mutationKey.current.fingerprint !== fingerprint) {
      mutationKey.current = { fingerprint, value: newIdempotencyKey('b14') }
    }
    return mutationKey.current.value
  }

  function clearKey(fingerprint: string): void {
    if (mutationKey.current.fingerprint === fingerprint) mutationKey.current = { fingerprint: '', value: '' }
  }

  async function reconcile(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!session || !data || !reconciliationReady) return
    const reason = reconciliationReason.trim()
    const target = operationReference.trim()
    const fingerprint = 'reconcile:' + target + ':' + data.revision + ':' + reason
    setAction({ kind: 'busy', message: '正在提交重新对账。' })
    try {
      const payload = await callBusinessOperation<unknown>('reconcileAdminBillingOperation', {
        path: { operationId: target },
        body: { reason, expectedRevision: data.revision },
        csrfToken: session.csrfToken,
        idempotencyKey: keyFor(fingerprint),
        auditReason: reason,
      })
      const receipt = parseReceipt(payload)
      if (!receipt) throw new ContractPayloadError()
      const refreshed = await loadPage()
      if (!refreshed) {
        setAction({ kind: 'error', message: '操作已返回，但最新汇总回读未完成。' })
        return
      }
      clearKey(fingerprint)
      setOperationReference('')
      setReconciliationReason('')
      setAction({ kind: 'success', message: receipt.ok ? '重新对账已完成，汇总已回读。' : '重新对账已返回，汇总已回读。' })
    } catch (error) {
      setAction({ kind: 'error', message: publicError(error, '重新对账未完成。') })
    }
  }

  async function credentialMutation(kind: 'rotate' | 'revoke'): Promise<void> {
    if (!session || !data || !credentialReady || (kind === 'revoke' && !revokeConfirmed)) return
    const reason = credentialReason.trim()
    const operation = kind === 'rotate' ? 'rotateAdminUpstreamCredential' : 'revokeAdminUpstreamCredential'
    const fingerprint = kind + ':' + data.revision + ':' + reason
    setAction({ kind: 'busy', message: kind === 'rotate' ? '正在轮换凭证。' : '正在撤销凭证。' })
    try {
      const payload = await callBusinessOperation<unknown>(operation, {
        body: { reason, expectedRevision: data.revision },
        csrfToken: session.csrfToken,
        idempotencyKey: keyFor(fingerprint),
        auditReason: reason,
      })
      if (!parseResponse(payload)) throw new ContractPayloadError()
      const refreshed = await loadPage()
      if (!refreshed) {
        setAction({ kind: 'error', message: '操作已返回，但最新汇总回读未完成。' })
        return
      }
      clearKey(fingerprint)
      setCredentialReason('')
      setRevokeConfirmed(false)
      setAction({ kind: 'success', message: kind === 'rotate' ? '凭证已轮换，健康状态已回读。' : '凭证已撤销，健康状态已回读。' })
    } catch (error) {
      setAction({ kind: 'error', message: publicError(error, kind === 'rotate' ? '凭证轮换未完成。' : '凭证撤销未完成。') })
    }
  }

  return <main className={'fidelity-page ' + styles.page}>
    <header className={styles.pageHeader}>
      <div className={styles.titleBlock}>
        <div className={styles.kicker}><Server size={15} /> 管理 / 上游服务</div>
        <h1>上游服务</h1>
        <p>凭证健康、账户汇总与对账状态</p>
      </div>
      <div className={styles.headerActions}>
        <span className={styles.accessPill}><ShieldCheck size={14} />{canMutateCredential ? '维护者权限' : '管理员权限'}</span>
        <button className={styles.refreshButton} type="button" onClick={() => { setAction({ kind: 'idle', message: '' }); void loadPage() }} disabled={!canRead || loadState.status === 'loading'} aria-label="刷新上游服务">
          <RefreshCw size={15} className={loadState.status === 'loading' ? styles.spin : undefined} />刷新
        </button>
      </div>
    </header>
    {runtimeState === 'checking' ? <LoadingState /> : null}
    {runtimeState !== 'checking' && loadState.status === 'permission' ? <PageState icon={ShieldAlert} title="无法读取上游服务" message={loadState.message} /> : null}
    {runtimeState !== 'checking' && loadState.status === 'error' ? <PageState icon={AlertCircle} title="上游服务暂不可用" message={loadState.message} onRetry={() => { setAction({ kind: 'idle', message: '' }); void loadPage() }} /> : null}
    {loadState.status === 'ready' ? <ReadyView
      data={loadState.data}
      canRead={canRead}
      canMutateCredential={canMutateCredential}
      operationReference={operationReference}
      reconciliationReason={reconciliationReason}
      credentialReason={credentialReason}
      revokeConfirmed={revokeConfirmed}
      action={action}
      busy={busy}
      reconciliationReady={reconciliationReady}
      credentialReady={credentialReady}
      onOperationReferenceChange={setOperationReference}
      onReconciliationReasonChange={setReconciliationReason}
      onCredentialReasonChange={setCredentialReason}
      onRevokeConfirmedChange={setRevokeConfirmed}
      onReconcile={reconcile}
      onRotate={() => { void credentialMutation('rotate') }}
      onRevoke={() => { void credentialMutation('revoke') }}
    /> : null}
  </main>
}

function ReadyView({
  data, canRead, canMutateCredential, operationReference, reconciliationReason, credentialReason,
  revokeConfirmed, action, busy, reconciliationReady, credentialReady,
  onOperationReferenceChange, onReconciliationReasonChange, onCredentialReasonChange,
  onRevokeConfirmedChange, onReconcile, onRotate, onRevoke,
}: {
  data: UpstreamResponse
  canRead: boolean
  canMutateCredential: boolean
  operationReference: string
  reconciliationReason: string
  credentialReason: string
  revokeConfirmed: boolean
  action: ActionState
  busy: boolean
  reconciliationReady: boolean
  credentialReady: boolean
  onOperationReferenceChange: (value: string) => void
  onReconciliationReasonChange: (value: string) => void
  onCredentialReasonChange: (value: string) => void
  onRevokeConfirmedChange: (value: boolean) => void
  onReconcile: (event: FormEvent<HTMLFormElement>) => void
  onRotate: () => void
  onRevoke: () => void
}) {
  const summary = data.summary
  return <>
    <section className={styles.prelude} data-page-prelude><MetricBand summary={summary} /></section>
    <div className={styles.dashboardGrid} data-page-layout="persistent-rail">
      <div className={styles.primaryColumn} data-page-primary data-primary-flow>
        <section className={styles.primarySurface} data-page-terminal-surface="primary" aria-labelledby="upstream-health-title">
          <header className={styles.panelHeader}>
            <div><span className={styles.eyebrow}>聚合读模型</span><h2 id="upstream-health-title">凭证健康</h2></div>
            <span className={styles.revisionBadge}>修订 {data.revision}</span>
          </header>
          <div className={styles.primaryBody}>
            <div className={styles.healthHero}>
              <span className={styles.healthGlyph + ' ' + healthClass(summary.credentialHealth)}><ShieldCheck size={23} /></span>
              <div className={styles.healthCopy}><strong>{healthLabels[summary.credentialHealth]}</strong><p>{healthDescription(summary.credentialHealth)}</p></div>
            </div>
            <div className={styles.statusList}>
              <StatusRow label="可用账户" value={count(summary.availableAccountCount)} />
              <StatusRow label="异常账户" value={count(summary.unhealthyAccountCount)} />
              <StatusRow label="待对账调用" value={count(summary.pendingReconciliationCount)} />
              <StatusRow label="最近同步" value={timestamp(summary.lastSyncedAt, true)} />
            </div>
            <div className={styles.pendingBlock}>
              <div className={styles.blockHeading}><ReceiptText size={17} /><h3>对账状态</h3></div>
              <strong className={styles.pendingValue}>{summary.pendingReconciliationCount === 0 ? '当前无待对账调用' : count(summary.pendingReconciliationCount) + ' 项待处理'}</strong>
              <p>{summary.pendingReconciliationCount === 0 ? '汇总已回读。' : '请从右侧提交具体操作参考。'}</p>
            </div>
          </div>
        </section>
      </div>
      <aside className={styles.inspector} data-page-inspector data-page-terminal-surface="inspector" aria-label="上游服务操作">
        <div className={styles.inspectorScroll} tabIndex={0} aria-label="上游服务操作面板">
          <section className={styles.actionPanel} aria-labelledby="reconcile-title">
            <header className={styles.actionHeader}><div className={styles.actionTitle}><ReceiptText size={17} /><div><h2 id="reconcile-title">重新对账</h2><span>当前修订 {data.revision}</span></div></div></header>
            <form className={styles.actionForm} onSubmit={onReconcile}>
              <label className={styles.field}><span className={styles.fieldLabel}>操作参考</span><input className={styles.input} value={operationReference} onChange={(event) => onOperationReferenceChange(event.target.value)} placeholder="输入 UUID" autoCapitalize="none" autoCorrect="off" spellCheck={false} maxLength={36} aria-invalid={operationReference.length > 0 && !isOperationReference(operationReference)} disabled={!canRead || busy} /></label>
              <label className={styles.field}><span className={styles.fieldLabel}>原因</span><textarea className={styles.textarea} value={reconciliationReason} onChange={(event) => onReconciliationReasonChange(event.target.value)} placeholder="填写操作原因" maxLength={500} rows={3} disabled={!canRead || busy} /></label>
              <button className={styles.primaryButton} type="submit" disabled={!reconciliationReady}><ReceiptText size={16} />重新对账</button>
            </form>
          </section>
          <section className={styles.actionPanel} aria-labelledby="credential-title">
            <header className={styles.actionHeader}><div className={styles.actionTitle}><KeyRound size={17} /><div><h2 id="credential-title">凭证操作</h2><span>{canMutateCredential ? '可执行维护操作' : '仅可读取汇总'}</span></div></div></header>
            <div className={styles.actionForm}>
              <label className={styles.field}><span className={styles.fieldLabel}>原因</span><textarea className={styles.textarea} value={credentialReason} onChange={(event) => onCredentialReasonChange(event.target.value)} placeholder="填写操作原因" maxLength={500} rows={3} disabled={!canMutateCredential || busy} /></label>
              <div className={styles.buttonRow}>
                <button className={styles.secondaryButton} type="button" onClick={onRotate} disabled={!credentialReady}><RotateCw size={16} />轮换凭证</button>
                <button className={styles.dangerButton} type="button" onClick={onRevoke} disabled={!credentialReady || !revokeConfirmed}><XCircle size={16} />撤销凭证</button>
              </div>
              <label className={styles.confirmRow}><input type="checkbox" checked={revokeConfirmed} onChange={(event) => onRevokeConfirmedChange(event.target.checked)} disabled={!canMutateCredential || busy} /><span>确认撤销当前凭证</span></label>
              {!canMutateCredential ? <div className={styles.permissionNote}><ShieldAlert size={15} /><span>当前会话可读取汇总，但不能变更凭证。</span></div> : null}
            </div>
          </section>
          {action.message ? <ActionBanner action={action} /> : null}
        </div>
      </aside>
    </div>
  </>
}

function MetricBand({ summary }: { summary: Summary }) {
  return <section className={styles.metricBand} aria-label="上游状态摘要">
    <MetricCard icon={Users} tone="success" label="可用账户" value={count(summary.availableAccountCount)} />
    <MetricCard icon={XCircle} tone="danger" label="异常账户" value={count(summary.unhealthyAccountCount)} />
    <MetricCard icon={ReceiptText} tone="warning" label="待对账调用" value={count(summary.pendingReconciliationCount)} />
    <MetricCard icon={Clock3} tone="info" label="最近同步" value={timestamp(summary.lastSyncedAt)} />
  </section>
}

function MetricCard({ icon: Icon, tone, label, value }: {
  icon: LucideIcon
  tone: 'success' | 'danger' | 'warning' | 'info'
  label: string
  value: string
}) {
  const className = styles['metricIcon' + tone[0].toUpperCase() + tone.slice(1)]
  return <article className={styles.metric}><span className={className}><Icon size={18} /></span><div className={styles.metricCopy}><span className={styles.metricLabel}>{label}</span><strong className={styles.metricValue}>{value}</strong></div></article>
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div className={styles.statusRow}><span>{label}</span><strong>{value}</strong></div>
}

function ActionBanner({ action }: { action: ActionState }) {
  const Icon = action.kind === 'success' ? CheckCircle2 : action.kind === 'error' ? AlertCircle : RefreshCw
  return <div className={styles.actionBanner + ' ' + actionClass(action.kind)} role="status" aria-live="polite"><Icon size={16} className={action.kind === 'busy' ? styles.spin : undefined} /><span>{action.message}</span></div>
}

function LoadingState() {
  return <section className={styles.statePanel} data-page-terminal-surface="primary" aria-busy="true"><span className={styles.stateIcon}><RefreshCw size={22} className={styles.spin} /></span><div><h2>正在读取上游服务</h2><p>汇总状态加载中。</p></div></section>
}

function PageState({ icon: Icon, title, message, onRetry }: {
  icon: LucideIcon
  title: string
  message: string
  onRetry?: () => void
}) {
  return <section className={styles.statePanel} data-page-terminal-surface="primary"><span className={styles.stateIcon}><Icon size={22} /></span><div className={styles.stateCopy}><h2>{title}</h2><p>{message}</p>{onRetry ? <button className={styles.retryButton} type="button" onClick={onRetry}><RefreshCw size={15} />重试</button> : null}</div></section>
}
