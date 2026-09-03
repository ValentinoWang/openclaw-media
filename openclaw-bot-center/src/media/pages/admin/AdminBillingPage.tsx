import { useEffect, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  ExternalLink,
  Gift,
  Link2,
  LoaderCircle,
  RotateCcw,
  RefreshCw,
  ShieldCheck,
  TicketCheck,
  Undo2,
} from 'lucide-react'
import { useMediaWeb } from '../../MediaWebWorkspace'
import {
  BusinessOperationError,
  callBusinessOperation,
} from '../../generatedBusinessPagesContract'
import {
  liandongPurchaseUrl,
  mutationFingerprint,
  positiveId,
  positiveMoney,
  useAdminAction,
} from '../../ui/adminAction'
import { Metric } from '../../ui/Metric'
import { SurfaceState } from '../../ui/SurfaceState'
import { DISPLAY_LABELS } from '../../ui/displayLabels'
import { isPublicId, PUBLIC_ID_HTML_PATTERN } from '../../identifiers'
import { formatDateTime } from '../../ui/datetime'
import styles from './AdminBillingPage.module.css'

type BillingView = 'plans' | 'mappings' | 'batches' | 'fulfillments' | 'grants'
type OperationMode = 'mapping' | 'grant' | 'batch' | 'recover' | 'refund'
type CollectionKey = 'plans' | 'productMappings' | 'redemptionBatches' | 'fulfillments' | 'grants'
type BillingRecord = Record<string, unknown>
type MutationOperationId =
  | 'createAdminProductMapping'
  | 'createAdminBillingGrant'
  | 'createAdminRedemptionBatch'
  | 'recoverAdminFulfillment'
  | 'refundAdminFulfillment'

type BillingPlan = {
  planCode: string
  name: string
  status: string
  textQuota: number
  imageQuota: number
  price: string
  currency: string
}

type RedemptionBatchSummary = {
  batchId: string
  planCode: string
  status: string
  codeCount: number
  redeemedCount: number
  createdAt: string
}

type BillingSummary = {
  plans: BillingPlan[]
  productMappings: BillingRecord[]
  redemptionBatches: RedemptionBatchSummary[]
  fulfillments: BillingRecord[]
  grants: BillingRecord[]
  ledgerRevision: number
}

type BillingSummaryResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  summary: BillingSummary
}

type MutationReceiptDTO = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  ok: true
  updatedAt: string
}

type MutationReceipt = MutationReceiptDTO & {
  operation: string
  idempotencyKey: string
  phase: 'submitting' | 'awaiting' | 'reading' | 'verified' | 'error'
  summary: string
  refreshAt: number
}

type BillingRequestError = {
  status: number
  code: string
  message: string
}

type BillingLoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: BillingSummaryResponse }
  | { status: 'error'; error: BillingRequestError }

type MutationSpec = {
  operationId: MutationOperationId
  path?: Record<string, string>
  body: Record<string, unknown>
  label: string
  auditReason: string
}

const billingTabs: Array<{ key: BillingView; label: string }> = [
  { key: 'plans', label: '套餐' },
  { key: 'mappings', label: '商品映射' },
  { key: 'batches', label: '卡密批次' },
  { key: 'fulfillments', label: '兑换记录' },
  { key: 'grants', label: '管理员赠款' },
]

const operationTabs: Array<{ key: OperationMode; label: string }> = [
  { key: 'mapping', label: '编辑映射' },
  { key: 'grant', label: '管理员赠款' },
  { key: 'batch', label: '生成批次' },
  { key: 'recover', label: '恢复履约' },
  { key: 'refund', label: '退款履约' },
]

const billingTabId = (key: BillingView) => 'admin-billing-data-tab-' + key
const billingPanelId = (key: BillingView) => 'admin-billing-data-panel-' + key
const operationTabId = (key: OperationMode) => 'admin-billing-operation-tab-' + key
const operationPanelId = (key: OperationMode) => 'admin-billing-operation-panel-' + key

const collectionLabels: Array<{ key: CollectionKey; label: string }> = [
  { key: 'plans', label: '套餐' },
  { key: 'productMappings', label: '商品映射' },
  { key: 'redemptionBatches', label: '卡密批次' },
  { key: 'fulfillments', label: '兑换记录' },
  { key: 'grants', label: '管理员赠款' },
]

export default function AdminBillingPage() {
  const { runtimeState, session } = useMediaWeb()
  const [view, setView] = useState<BillingView>('plans')
  const [mode, setMode] = useState<OperationMode>('mapping')
  const [refresh, setRefresh] = useState(0)
  const [planCode, setPlanCode] = useState('')
  const [externalProductId, setExternalProductId] = useState('')
  const [purchaseUrl, setPurchaseUrl] = useState('')
  const [publicTenantId, setPublicTenantId] = useState('')
  const [fulfillmentId, setFulfillmentId] = useState('')
  const [amount, setAmount] = useState('')
  const [count, setCount] = useState('')
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [receipt, setReceipt] = useState<MutationReceipt | null>(null)

  const allowed = runtimeState === 'authenticated' && session?.role === 'admin'
  const canMutate = allowed && !!session?.csrfToken
  const summary = useBillingSummary(allowed, refresh)
  const data = summary.status === 'ready' ? summary.data : null
  const summaryData = data?.summary ?? null
  const planCollection = getCollection<BillingPlan>(summaryData, 'plans')
  const mappingCollection = getCollection<BillingRecord>(summaryData, 'productMappings')
  const batchCollection = getCollection<RedemptionBatchSummary>(summaryData, 'redemptionBatches')
  const fulfillmentCollection = getCollection<BillingRecord>(summaryData, 'fulfillments')
  const grantCollection = getCollection<BillingRecord>(summaryData, 'grants')
  const plans = planCollection ?? []
  const mappings = mappingCollection ?? []
  const batches = batchCollection ?? []
  const fulfillments = fulfillmentCollection ?? []
  const grants = grantCollection ?? []
  const viewCollection = view === 'plans'
    ? planCollection
    : view === 'mappings'
      ? mappingCollection
      : view === 'batches'
        ? batchCollection
        : view === 'fulfillments'
          ? fulfillmentCollection
          : grantCollection
  const missingCollections = summaryData
    ? collectionLabels
      .filter(({ key }) => getCollection(summaryData, key) === null)
      .map(({ label }) => label)
    : []

  useEffect(() => {
    if (!summaryData) return
    const availablePlans = getCollection<BillingPlan>(summaryData, 'plans') ?? []
    setPlanCode((current) => availablePlans.some((plan) => plan.planCode === current) ? current : availablePlans[0]?.planCode ?? '')
  }, [summaryData])

  useEffect(() => {
    if (!summaryData) return
    const availableMappings = getCollection<BillingRecord>(summaryData, 'productMappings') ?? []
    const mapping = availableMappings.find((item) => readString(item, 'planCode') === planCode)
    setExternalProductId(mapping ? readString(mapping, 'externalProductId') : '')
    setPurchaseUrl(mapping ? readString(mapping, 'purchaseUrl') : '')
  }, [summaryData, planCode])

  useEffect(() => {
    if (!receipt || refresh <= receipt.refreshAt) return
    if (receipt.phase !== 'awaiting' && receipt.phase !== 'reading') return
    if (summary.status === 'loading') {
      if (receipt.phase === 'awaiting') setReceipt((current) => current ? { ...current, phase: 'reading' } : current)
      return
    }
    if (summary.status === 'ready') {
      setReceipt((current) => current ? { ...current, phase: 'verified', revision: summary.data.revision } : current)
    } else if (summary.status === 'error') {
      setReceipt((current) => current ? { ...current, phase: 'error', summary: '写入接口已返回，但汇总回读失败。' } : current)
    }
  }, [receipt, refresh, summary])

  const action = useAdminAction(() => setRefresh((current) => current + 1))
  const currentRevision = data?.revision ?? null
  const mappingReady = canMutate
    && !!planCode
    && !!externalProductId.trim()
    && liandongPurchaseUrl(purchaseUrl.trim())
    && !!reason.trim()
    && confirmed
  const grantReady = canMutate
    && isPublicId(publicTenantId.trim())
    && positiveMoney(amount.trim())
    && !!reason.trim()
    && confirmed
  const batchReady = canMutate
    && !!planCode
    && positiveId(count.trim())
    && Number(count) <= 1000
    && !!reason.trim()
    && confirmed
  const fulfillmentReady = canMutate
    && isPublicId(fulfillmentId.trim())
    && currentRevision !== null
    && !!reason.trim()
    && confirmed
  const readyByMode: Record<OperationMode, boolean> = {
    mapping: mappingReady,
    grant: grantReady,
    batch: batchReady,
    recover: fulfillmentReady,
    refund: fulfillmentReady,
  }
  const submitReady = summary.status === 'ready' && data !== null && readyByMode[mode] && !action.busy

  function changeMode(nextMode: OperationMode) {
    setMode(nextMode)
    setConfirmed(false)
  }

  function handleBillingTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    handleTabKeyDown(event, billingTabs, view, setView, billingTabId)
  }

  function handleOperationTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    handleTabKeyDown(event, operationTabs, mode, changeMode, operationTabId)
  }

  function selectPlan(nextPlanCode: string) {
    setPlanCode(nextPlanCode)
    setMode('mapping')
    setConfirmed(false)
  }

  function prepareFulfillment(nextMode: 'recover' | 'refund', nextFulfillmentId: string) {
    setFulfillmentId(nextFulfillmentId)
    setMode(nextMode)
    setConfirmed(false)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canMutate || !session || !submitReady || currentRevision === null) return
    const spec = buildMutationSpec(mode, {
      planCode,
      externalProductId,
      purchaseUrl,
      publicTenantId,
      fulfillmentId,
      amount,
      count,
      reason,
    }, currentRevision)
    let submittedKey = ''
    const result = await action.run(
      mutationFingerprint(spec.operationId, 'POST', { ...spec.path, ...spec.body }),
      (idempotencyKey) => {
        submittedKey = idempotencyKey
        setReceipt({
          schemaVersion: 'media_web_business_pages_v2',
          revision: currentRevision,
          ok: true,
          updatedAt: '',
          operation: spec.label,
          idempotencyKey,
          phase: 'submitting',
          summary: '正在提交写入请求。',
          refreshAt: refresh,
        })
        return callBusinessOperation<MutationReceiptDTO>(spec.operationId, {
          path: spec.path,
          body: spec.body,
          csrfToken: session.csrfToken,
          idempotencyKey,
          auditReason: spec.auditReason,
        })
      },
    )
    if (!submittedKey) return
    if (!result) {
      setReceipt((current) => current ? { ...current, phase: 'error', summary: '写入未完成，服务端没有返回成功回执。' } : current)
      return
    }
    setReceipt((current) => current ? {
      ...current,
      ...result,
      phase: 'awaiting',
      summary: '服务端已返回固定 MutationReceipt，等待汇总回读。',
      refreshAt: refresh,
    } : current)
    setConfirmed(false)
    setReason('')
  }

  function renderOperationFields() {
    if (mode === 'mapping') return <>
      <FormField label="目标套餐">
        <select value={planCode} onChange={(event) => { setPlanCode(event.target.value); setConfirmed(false) }} disabled={!plans.length}>
          {!plans.length ? <option value="">当前没有可用套餐</option> : plans.map((plan) => <option key={plan.planCode} value={plan.planCode}>{planOptionLabel(plan)}</option>)}
        </select>
      </FormField>
      <FormField label="链动商品编号">
        <input value={externalProductId} onChange={(event) => { setExternalProductId(event.target.value); setConfirmed(false) }} autoCapitalize="none" maxLength={128} placeholder="输入真实商品编号" />
      </FormField>
      <FormField label="购买链接" hint="只接受链动 HTTPS 购买链接。">
        <input
          type="url"
          value={purchaseUrl}
          onChange={(event) => { setPurchaseUrl(event.target.value); setConfirmed(false) }}
          autoCapitalize="none"
          maxLength={2048}
          placeholder="输入已核验的购买链接"
          aria-invalid={!!purchaseUrl && !liandongPurchaseUrl(purchaseUrl.trim())}
        />
      </FormField>
      <ReasonField value={reason} onChange={(value) => { setReason(value); setConfirmed(false) }} />
    </>
    if (mode === 'grant') return <>
      <FormField label="目标租户公开编号" hint="只提交服务端返回的 opaque publicTenantId。">
        <input
          value={publicTenantId}
          onChange={(event) => { setPublicTenantId(event.target.value); setConfirmed(false) }}
          autoCapitalize="none"
          spellCheck={false}
          maxLength={160}
          pattern={PUBLIC_ID_HTML_PATTERN}
          placeholder="输入 opaque 租户编号"
          aria-invalid={!!publicTenantId && !isPublicId(publicTenantId.trim())}
        />
      </FormField>
      <FormField label="赠款额度" hint="最多支持 8 位小数。">
        <input
          type="text"
          inputMode="decimal"
          value={amount}
          onChange={(event) => { setAmount(event.target.value); setConfirmed(false) }}
          placeholder="例如 10.00000000"
          aria-invalid={!!amount && !positiveMoney(amount.trim())}
        />
      </FormField>
      <ReasonField value={reason} onChange={(value) => { setReason(value); setConfirmed(false) }} />
    </>
    if (mode === 'batch') return <>
      <FormField label="批次套餐">
        <select value={planCode} onChange={(event) => { setPlanCode(event.target.value); setConfirmed(false) }} disabled={!plans.length}>
          {!plans.length ? <option value="">当前没有可用套餐</option> : plans.map((plan) => <option key={plan.planCode} value={plan.planCode}>{planOptionLabel(plan)}</option>)}
        </select>
      </FormField>
      <FormField label="卡密数量" hint="单批次最多 1,000 个。">
        <input type="number" min="1" max="1000" step="1" value={count} onChange={(event) => { setCount(event.target.value); setConfirmed(false) }} />
      </FormField>
      <div className={styles.protectedNote}><ShieldCheck size={16} /><span>服务只返回批次收据；受保护卡密不会出现在页面列表、普通响应或回读摘要中。</span></div>
      <ReasonField value={reason} onChange={(value) => { setReason(value); setConfirmed(false) }} />
    </>
    return <>
      <FormField label="目标履约公开编号" hint="只能使用兑换记录中的 opaque fulfillmentId。">
        <input
          value={fulfillmentId}
          onChange={(event) => { setFulfillmentId(event.target.value); setConfirmed(false) }}
          autoCapitalize="none"
          spellCheck={false}
          maxLength={160}
          pattern={PUBLIC_ID_HTML_PATTERN}
          placeholder="输入 opaque 履约编号"
          aria-invalid={!!fulfillmentId && !isPublicId(fulfillmentId.trim())}
        />
      </FormField>
      <div className={styles.revisionNote}>
        <span>写入前{DISPLAY_LABELS.dataVersion}</span>
        <strong>{currentRevision === null ? '—' : formatCount(currentRevision)}</strong>
        <small>服务端会拒绝过期{DISPLAY_LABELS.dataVersion}。</small>
      </div>
      <ReasonField value={reason} onChange={(value) => { setReason(value); setConfirmed(false) }} />
    </>
  }

  const heading = <header className="page-heading mg-hero" data-component="mg-hero">
    <div>
      <h1>计费运营</h1>
      <p className="mg-hero-lead">管理零售套餐、商品映射、卡密履约和管理员赠款。</p>
    </div>
    {summary.status === 'ready' && data ? <div className={styles.headingArea}>
      <div className={styles.headingActions}>
        <button type="button" className={styles.headingAction + ' mg-btn mg-btn-ghost'} onClick={() => setRefresh((current) => current + 1)}><RefreshCw size={15} />刷新</button>
      </div>
    </div> : null}
  </header>
  const pagePrelude = <div className={styles.pagePrelude} data-page-prelude>{heading}{summary.status === 'ready' && data ? <SummaryMetrics summary={summaryData} loading={false} /> : null}</div>

  if (runtimeState === 'checking') return <main className={'fidelity-page ' + styles.page} data-accent="business" data-page-ownership="governance">{pagePrelude}<LoadingState /></main>
  if (!allowed) return <main className={'fidelity-page ' + styles.page} data-accent="business" data-page-ownership="governance">{pagePrelude}<PermissionState /></main>
  if (summary.status === 'loading') return <main className={'fidelity-page ' + styles.page} data-accent="business" data-page-ownership="governance">{pagePrelude}<LoadingState /></main>
  if (summary.status === 'error') {
    return <main className={'fidelity-page ' + styles.page} data-accent="business" data-page-ownership="governance">{pagePrelude}{summary.error.status === 403 ? <ForbiddenState /> : <ErrorState error={summary.error} onRetry={() => setRefresh((current) => current + 1)} />}</main>
  }
  if (summary.status !== 'ready' || !data || !summaryData) return <main className={'fidelity-page ' + styles.page} data-accent="business" data-page-ownership="governance">{pagePrelude}<ErrorState error={{ status: 502, code: 'invalid_response', message: '服务没有返回可读的计费汇总。' }} onRetry={() => setRefresh((current) => current + 1)} /></main>

  return <main className={'fidelity-page ' + styles.page} data-accent="business" data-page-ownership="governance">
    {pagePrelude}
    {missingCollections.length ? <div className={styles.partialNotice}><AlertCircle size={16} /><span>服务未返回：{missingCollections.join('、')}。页面已隐藏缺失集合，不使用其他业务数据替代。</span></div> : null}
    <nav className="mg-tabs" aria-label="计费数据视图" role="tablist">
      {billingTabs.map((tab) => <button
        type="button"
        key={tab.key}
        id={billingTabId(tab.key)}
        role="tab"
        aria-selected={view === tab.key}
        aria-controls={billingPanelId(tab.key)}
        tabIndex={view === tab.key ? 0 : -1}
        className="mg-tab"
        onClick={() => setView(tab.key)}
        onKeyDown={handleBillingTabKeyDown}
      >{tab.label}</button>)}
    </nav>
    <div className={styles.bodyGrid} data-page-layout="persistent-rail">
      <div className={styles.mainColumn} data-page-primary data-primary-flow>
        {billingTabs.map((tab) => view === tab.key ? <section key={tab.key} className={styles.tablePanel + ' mg-panel'} id={billingPanelId(tab.key)} role="tabpanel" aria-labelledby={billingTabId(tab.key)}>
          <header className="mg-panel-head">
            <div><span className={styles.eyebrow}>服务端汇总</span><h2>{tab.label}</h2></div>
            <span className={styles.resultCount}>{viewCollection === null ? '—' : viewCollection.length + ' 条'}</span>
          </header>
          {tab.key === 'plans' ? <PlanTable available={planCollection !== null} items={plans} mappings={mappings} selectedPlanCode={planCode} onSelectPlan={selectPlan} /> : null}
          {tab.key === 'mappings' ? <MappingTable available={mappingCollection !== null} items={mappings} /> : null}
          {tab.key === 'batches' ? <BatchTable available={batchCollection !== null} items={batches} /> : null}
          {tab.key === 'fulfillments' ? <FulfillmentTable available={fulfillmentCollection !== null} items={fulfillments} onPrepare={prepareFulfillment} /> : null}
          {tab.key === 'grants' ? <GrantTable available={grantCollection !== null} items={grants} /> : null}
        </section> : <section key={tab.key} id={billingPanelId(tab.key)} role="tabpanel" aria-labelledby={billingTabId(tab.key)} hidden />)}
        <div className={styles.bottomGrid}>
          <BatchSummary available={batchCollection !== null} items={batches} onViewAll={() => setView('batches')} />
          <GrantSummary available={grantCollection !== null} items={grants} onViewAll={() => setView('grants')} />
        </div>
      </div>
      <aside className={styles.inspector + ' mg-panel'} aria-labelledby="billing-inspector-title" data-page-inspector data-page-terminal-surface="inspector">
        <header className={styles.inspectorHeader + ' mg-panel-head'}>
          <div className={styles.inspectorTitle}><Link2 size={18} /><div><h2 id="billing-inspector-title">{operationTitle(mode)}</h2><p>{operationDescription(mode)}</p></div></div>
          {action.state.message ? <span className={styles.actionMessage + (action.state.kind === 'error' ? ' ' + styles.actionError : action.state.kind === 'success' ? ' ' + styles.actionSuccess : '')} role="status">{action.state.message}</span> : null}
        </header>
        <div className={styles.operationTabs + ' mg-tabs'} role="tablist" aria-label="计费写入操作">
          {operationTabs.map((tab) => <button
            type="button"
            key={tab.key}
            id={operationTabId(tab.key)}
            role="tab"
            aria-selected={mode === tab.key}
            aria-controls={operationPanelId(tab.key)}
            tabIndex={mode === tab.key ? 0 : -1}
            className={styles.operationTab + ' mg-tab'}
            onClick={() => changeMode(tab.key)}
            onKeyDown={handleOperationTabKeyDown}
          >{tab.label}</button>)}
        </div>
        {operationTabs.map((tab) => mode === tab.key ? <form key={tab.key} className={styles.form} id={operationPanelId(tab.key)} role="tabpanel" aria-labelledby={operationTabId(tab.key)} onSubmit={(event) => void submit(event)}>
          <div className={styles.fields}>{renderOperationFields()}</div>
          <label className={styles.confirmation}>
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            <span><strong>确认边界</strong><small>{confirmationText(mode)}</small></span>
          </label>
          <div className={styles.formFooter}>
            <span>提交后会保留幂等键，并重新读取管理员计费汇总。</span>
            <button type="submit" className={styles.submitButton + ' mg-btn mg-btn-primary'} disabled={!submitReady}>
              {action.busy ? <LoaderCircle className="spin" size={16} /> : mode === 'mapping' ? <Link2 size={16} /> : mode === 'grant' ? <Gift size={16} /> : mode === 'batch' ? <TicketCheck size={16} /> : mode === 'recover' ? <RotateCcw size={16} /> : <Undo2 size={16} />}
              {operationButtonLabel(mode)}
            </button>
          </div>
        </form> : <div key={tab.key} id={operationPanelId(tab.key)} role="tabpanel" aria-labelledby={operationTabId(tab.key)} hidden />)}
        {receipt ? <MutationReceipt receipt={receipt} /> : null}
      </aside>
    </div>
  </main>
}

function handleTabKeyDown<Key extends string>(
  event: KeyboardEvent<HTMLButtonElement>,
  tabs: ReadonlyArray<{ key: Key }>,
  activeKey: Key,
  activate: (key: Key) => void,
  tabId: (key: Key) => string,
) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight' && event.key !== 'Home' && event.key !== 'End') return
  const currentIndex = tabs.findIndex((tab) => tab.key === activeKey)
  if (currentIndex < 0) return
  event.preventDefault()
  const nextIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? tabs.length - 1
      : event.key === 'ArrowRight'
        ? (currentIndex + 1) % tabs.length
        : (currentIndex - 1 + tabs.length) % tabs.length
  const nextKey = tabs[nextIndex].key
  activate(nextKey)
  document.getElementById(tabId(nextKey))?.focus()
}

function useBillingSummary(allowed: boolean, refresh: number): BillingLoadState {
  const [state, setState] = useState<BillingLoadState>({ status: 'idle' })

  useEffect(() => {
    if (!allowed) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<unknown>('getAdminBillingSummary', { signal: controller.signal })
      .then((payload) => {
        if (active) setState({ status: 'ready', data: parseBillingSummary(payload) })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState({ status: 'error', error: toBillingError(error) })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [allowed, refresh])

  return state
}

class BillingPageError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'BillingPageError'
    this.status = status
    this.code = code
  }
}

function parseBillingSummary(payload: unknown): BillingSummaryResponse {
  if (!isRecord(payload) || payload.schemaVersion !== 'media_web_business_pages_v2' || !isRevision(payload.revision) || !isRecord(payload.summary)) {
    throw new BillingPageError(502, 'invalid_response', '服务没有返回符合 IF2 的计费汇总。')
  }
  return payload as unknown as BillingSummaryResponse
}

function toBillingError(error: unknown): BillingRequestError {
  if (error instanceof BillingPageError) return error
  if (error instanceof BusinessOperationError) return { status: error.status, code: error.code, message: error.message }
  if (error instanceof Error) return { status: 0, code: 'request_failed', message: error.message }
  return { status: 0, code: 'request_failed', message: '计费汇总读取失败。' }
}

function isRecord(value: unknown): value is BillingRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRevision(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function getCollection<T>(data: BillingSummary | null, key: CollectionKey): T[] | null {
  if (!data) return null
  const value = (data as unknown as BillingRecord)[key]
  return Array.isArray(value) ? value as T[] : null
}

function SummaryMetrics({ summary, loading }: { summary: BillingSummary | null; loading: boolean }) {
  const metrics = [
    { label: '套餐', detail: '当前目录', icon: CircleDollarSign, value: metricCount(summary, 'plans', loading) },
    { label: '商品映射', detail: '当前读取', icon: Link2, value: metricCount(summary, 'productMappings', loading) },
    { label: '卡密批次', detail: '当前读取', icon: TicketCheck, value: metricCount(summary, 'redemptionBatches', loading) },
    { label: '管理员赠款', detail: '当前读取', icon: Gift, value: metricCount(summary, 'grants', loading) },
  ]
  return <section className={styles.metricBand + ' mg-metric-grid'} aria-label="计费摘要指标">{metrics.map(({ label, detail, icon: Icon, value }) => <Metric variant="card" className={styles.metric + ' mg-metric'} key={label} label={label} value={value} detail={detail} icon={<Icon size={17} aria-hidden="true" />} />)}</section>
}

function PlanTable({ available, items, mappings, selectedPlanCode, onSelectPlan }: { available: boolean; items: BillingPlan[]; mappings: BillingRecord[]; selectedPlanCode: string; onSelectPlan: (planCode: string) => void }) {
  if (!available) return <CollectionUnavailable title="套餐" />
  if (!items.length) return <EmptyState title="暂无套餐" />
  return <TableViewport minWidth="720px"><table className={styles.table}><thead><tr><th>套餐编码</th><th className={styles.numericCell}>零售金额</th><th>状态</th><th>关联商品</th><th>额度</th></tr></thead><tbody>{items.map((plan) => {
    const mapping = mappings.find((item) => readString(item, 'planCode') === plan.planCode)
    const selected = selectedPlanCode === plan.planCode
    return <tr key={plan.planCode} className={selected ? styles.selectedRow : ''} aria-selected={selected} tabIndex={0} onClick={() => onSelectPlan(plan.planCode)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectPlan(plan.planCode) } }}>
      <th scope="row"><button type="button" className={styles.rowSelect} onClick={() => onSelectPlan(plan.planCode)}>{plan.planCode}</button><span className={styles.secondaryText}>{plan.name || '—'}</span></th>
      <td className={styles.numericCell}>{formatMoney(plan.price)} {plan.currency}</td>
      <td><StatusBadge {...planStatus(plan, mapping !== undefined)} /></td>
      <td>{mapping ? <span className={styles.longValue} title={readString(mapping, 'externalProductId')}>{readString(mapping, 'externalProductId') || '已关联商品'}</span> : '—'}</td>
      <td>{formatCount(plan.textQuota)} / {formatCount(plan.imageQuota)}</td>
    </tr>
  })}</tbody></table></TableViewport>
}

function MappingTable({ available, items }: { available: boolean; items: BillingRecord[] }) {
  if (!available) return <CollectionUnavailable title="商品映射" />
  if (!items.length) return <EmptyState title="暂无商品映射" />
  return <TableViewport minWidth="820px"><table className={styles.table}><thead><tr><th>套餐编码</th><th>外部商品编号</th><th>购买链接</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{items.map((item, index) => <tr key={readString(item, 'mappingId') || index}><th scope="row">{readString(item, 'planCode') || '—'}</th><td className={styles.longCell}><span className={styles.longValue} title={readString(item, 'externalProductId')}>{readString(item, 'externalProductId') || '—'}</span></td><td className={styles.longCell}><PurchaseLink value={item.purchaseUrl} /></td><td><StatusBadge {...recordStatus(item)} /></td><td>{formatTime(item.createdAt)}</td></tr>)}</tbody></table></TableViewport>
}

function BatchTable({ available, items }: { available: boolean; items: RedemptionBatchSummary[] }) {
  if (!available) return <CollectionUnavailable title="卡密批次" />
  if (!items.length) return <EmptyState title="暂无卡密批次" />
  return <TableViewport minWidth="760px"><table className={styles.table}><thead><tr><th>批次编号</th><th>套餐编码</th><th className={styles.numericCell}>数量</th><th className={styles.numericCell}>已兑换</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{items.map((item) => <tr key={item.batchId}><th scope="row" className={styles.longCell}><span className="mg-id" title={item.batchId}>{item.batchId}</span></th><td><span className="mg-id" title={item.planCode}>{item.planCode}</span></td><td className={styles.numericCell}>{formatCount(item.codeCount)}</td><td className={styles.numericCell}>{formatCount(item.redeemedCount)}</td><td><StatusBadge {...recordStatus(item)} /></td><td>{formatTime(item.createdAt)}</td></tr>)}</tbody></table></TableViewport>
}

function FulfillmentTable({ available, items, onPrepare }: { available: boolean; items: BillingRecord[]; onPrepare: (mode: 'recover' | 'refund', fulfillmentId: string) => void }) {
  if (!available) return <CollectionUnavailable title="兑换记录" />
  if (!items.length) return <EmptyState title="暂无兑换记录" />
  return <TableViewport minWidth="1020px"><table className={styles.table}><thead><tr><th>履约编号</th><th>目标租户</th><th>套餐</th><th className={styles.numericCell}>到账额度</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{items.map((item, index) => {
    const id = readString(item, 'fulfillmentId')
    return <tr key={id || index}><th scope="row" className={styles.longCell}>{id || '—'}</th><td className={styles.longCell}>{readString(item, 'publicTenantId') || '—'}</td><td>{readString(item, 'planCode') || '—'}</td><td className={styles.numericCell}>{formatDecimal(item.creditedAmount, 8)}</td><td><StatusBadge {...recordStatus(item)} /></td><td>{formatTime(item.createdAt)}</td><td><div className={styles.rowActions}><button type="button" className={styles.iconButton + ' mg-btn mg-btn-ghost'} title="选择恢复履约" aria-label="选择恢复履约" onClick={() => onPrepare('recover', id)} disabled={!id}><RotateCcw size={14} /></button><button type="button" className={styles.iconButton + ' mg-btn mg-btn-ghost'} title="选择退款履约" aria-label="选择退款履约" onClick={() => onPrepare('refund', id)} disabled={!id}><Undo2 size={14} /></button></div></td></tr>
  })}</tbody></table></TableViewport>
}

function GrantTable({ available, items }: { available: boolean; items: BillingRecord[] }) {
  if (!available) return <CollectionUnavailable title="管理员赠款" />
  if (!items.length) return <EmptyState title="暂无管理员赠款" />
  return <TableViewport minWidth="900px"><table className={styles.table}><thead><tr><th>账本编号</th><th>目标租户</th><th>账户</th><th className={styles.numericCell}>赠款额度</th><th>审计原因</th><th>创建时间</th></tr></thead><tbody>{items.map((item, index) => <tr key={readString(item, 'ledgerEntryId') || index}><th scope="row" className={styles.longCell}>{readString(item, 'ledgerEntryId') || '—'}</th><td className={styles.longCell}>{readString(item, 'publicTenantId') || '—'}</td><td className={styles.longCell}>{readString(item, 'username') || '—'}</td><td className={styles.numericCell}>{formatDecimal(item.amount, 8)}</td><td className={styles.reasonCell}>{readString(item, 'reason') || '—'}</td><td>{formatTime(item.createdAt)}</td></tr>)}</tbody></table></TableViewport>
}

function BatchSummary({ available, items, onViewAll }: { available: boolean; items: RedemptionBatchSummary[]; onViewAll: () => void }) {
  const stats = [
    ['批次数', items.length ? formatCount(items.length) : '—'],
    ['卡密数量', sumNumeric(items, 'codeCount')],
    ['已兑换', sumNumeric(items, 'redeemedCount')],
    ['待兑换', remainingCodes(items)],
  ]
  return <section className={styles.bottomPanel + ' mg-panel'} data-page-terminal-surface="primary"><PanelHeader icon={<TicketCheck size={17} />} title="卡密批次履约" actionLabel="查看全部批次" onAction={onViewAll} />{!available ? <CollectionUnavailable title="卡密批次" /> : !items.length ? <EmptyState title="暂无卡密批次" /> : <><div className={styles.compactMetrics}>{stats.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><MiniBatchTable items={items.slice(0, 4)} /></>}</section>
}

function GrantSummary({ available, items, onViewAll }: { available: boolean; items: BillingRecord[]; onViewAll: () => void }) {
  return <section className={styles.bottomPanel + ' mg-panel'} data-page-terminal-surface="primary"><PanelHeader icon={<Gift size={17} />} title="管理员赠款" actionLabel="查看全部赠款" onAction={onViewAll} />{!available ? <CollectionUnavailable title="管理员赠款" /> : !items.length ? <EmptyState title="暂无管理员赠款" /> : <MiniGrantTable items={items.slice(0, 5)} />}</section>
}

function MiniBatchTable({ items }: { items: RedemptionBatchSummary[] }) {
  return <TableViewport minWidth="520px"><table className={styles.table + ' ' + styles.miniTable}><thead><tr><th>批次编号</th><th>套餐</th><th className={styles.numericCell}>数量</th><th>状态</th></tr></thead><tbody>{items.map((item) => <tr key={item.batchId}><th scope="row" className={styles.longCell}><span className="mg-id" title={item.batchId}>{item.batchId}</span></th><td><span className="mg-id" title={item.planCode}>{item.planCode}</span></td><td className={styles.numericCell}>{formatCount(item.codeCount)}</td><td><StatusBadge {...recordStatus(item)} /></td></tr>)}</tbody></table></TableViewport>
}

function MiniGrantTable({ items }: { items: BillingRecord[] }) {
  return <TableViewport minWidth="560px"><table className={styles.table + ' ' + styles.miniTable}><thead><tr><th>审计原因</th><th>账户</th><th className={styles.numericCell}>额度</th><th>创建时间</th></tr></thead><tbody>{items.map((item, index) => <tr key={readString(item, 'ledgerEntryId') || index}><th scope="row" className={styles.reasonCell}>{readString(item, 'reason') || '—'}</th><td className={styles.longCell}>{readString(item, 'username') || '—'}</td><td className={styles.numericCell}>{formatDecimal(item.amount, 8)}</td><td>{formatTime(item.createdAt)}</td></tr>)}</tbody></table></TableViewport>
}

function PanelHeader({ icon, title, actionLabel, onAction }: { icon: ReactNode; title: string; actionLabel: string; onAction: () => void }) {
  return <header className="mg-panel-head"><div className={styles.panelTitle}><span className={styles.panelIcon}>{icon}</span><h2>{title}</h2></div><button type="button" className={styles.linkButton + ' mg-btn mg-btn-ghost'} onClick={onAction}>{actionLabel}<ChevronRight size={15} /></button></header>
}

function MutationReceipt({ receipt }: { receipt: MutationReceipt }) {
  const verified = receipt.phase === 'verified'
  const failed = receipt.phase === 'error'
  const Icon = verified ? CheckCircle2 : failed ? AlertCircle : LoaderCircle
  return <section className={styles.receipt + (verified ? ' ' + styles.receiptVerified : failed ? ' ' + styles.receiptError : '')} aria-live="polite" role="status"><Icon size={17} className={!verified && !failed ? "spin" : ''} /><div><strong>{verified ? '已完成并回读' : failed ? '操作需要处理' : receipt.phase === 'reading' ? '正在读取服务端回执' : '写入请求已发送'}</strong><span>{receipt.summary}</span><small>操作：{receipt.operation} · {DISPLAY_LABELS.dataVersion}：{receipt.revision === 0 ? '0' : formatCount(receipt.revision)}</small><code>幂等键：{receipt.idempotencyKey}</code></div></section>
}

function FormField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className={styles.field}><span>{label}</span>{children}{hint ? <small>{hint}</small> : null}</label>
}

function ReasonField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <FormField label="审计原因" hint="写入会进入管理员审计记录。"><textarea value={value} onChange={(event) => onChange(event.target.value)} rows={3} maxLength={500} placeholder="说明本次操作的业务原因" required /></FormField>
}

function TableViewport({ children, minWidth }: { children: ReactNode; minWidth: string }) {
  return <div className={styles.tableViewport}><div style={{ minWidth }}>{children}</div></div>
}

function StatusBadge({ label, tone }: { label: string; tone: string }) {
  return <span className={styles.statusBadge + ' mg-badge'} data-tone={tone}><span aria-hidden="true" /><span className={styles.badgeLabel}>{label}</span></span>
}

function LoadingState() {
  return <SurfaceState kind="loading" title="正在读取计费数据" detail="正在确认管理员权限并读取服务端汇总。" />
}

function PermissionState() {
  return <SurfaceState kind="permission" title="当前会话无权查看计费运营" detail="只有管理员会话可以读取或写入这里的计费数据。" action={null} />
}

function ForbiddenState() {
  return <SurfaceState kind="forbidden" title="服务端拒绝了计费运营访问" detail="当前会话没有服务端管理员权限。" />
}

function ErrorState({ error, onRetry }: { error: BillingRequestError; onRetry: () => void }) {
  return <SurfaceState kind="error" title="计费数据暂时不可用" detail={error.message || '服务没有返回可读的错误信息。'} action={<button type="button" className="mg-btn mg-btn-ghost" onClick={onRetry}><RefreshCw size={15} />重试</button>} />
}

function EmptyState({ title }: { title: string }) {
  return <SurfaceState kind="empty" title={title} detail="" density="compact" />
}

function CollectionUnavailable({ title }: { title: string }) {
  return <SurfaceState kind="empty" title={'服务未返回' + title + '集合'} detail="" density="compact" />
}

function PurchaseLink({ value }: { value: unknown }) {
  const url = typeof value === 'string' ? value.trim() : ''
  if (!url) return <span>—</span>
  if (!liandongPurchaseUrl(url)) return <span className={styles.longValue} title={url}>{url}</span>
  return <a className={styles.externalLink} href={url} target="_blank" rel="noreferrer"><span className={styles.longValue}>{url}</span><ExternalLink size={13} /></a>
}

function metricCount(data: BillingSummary | null, key: CollectionKey, loading: boolean): string {
  if (loading || !data) return '—'
  const items = getCollection(data, key)
  return items ? formatCount(items.length) : '—'
}

function readString(record: BillingRecord, key: string): string {
  const value = record[key]
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

function formatCount(value: unknown): string {
  const number = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : Number.NaN
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(number) : '—'
}

function formatDecimal(value: unknown, maximumFractionDigits: number): string {
  const number = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : Number.NaN
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { minimumFractionDigits: maximumFractionDigits === 2 ? 2 : 0, maximumFractionDigits }).format(number) : '—'
}

function formatMoney(value: unknown): string {
  const formatted = formatDecimal(value, 2)
  return formatted === '—' ? '—' : '¥' + formatted
}

function formatTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—'
  return formatDateTime(value, { invalid: '—' })
}

function planOptionLabel(plan: BillingPlan): string {
  return (plan.name || plan.planCode) + '（' + plan.planCode + '）'
}

function planStatus(plan: BillingPlan, mapped: boolean) {
  if (plan.status === 'active' && mapped) return { label: '生效中', tone: 'success' }
  if (plan.status === 'active') return { label: '待映射', tone: 'info' }
  return { label: plan.status || '待核对', tone: 'neutral' }
}

function recordStatus(record: BillingRecord | RedemptionBatchSummary) {
  const status = readString(record as BillingRecord, 'status')
  if (status === 'active' || status === 'available') return { label: '生效中', tone: 'success' }
  if (status === 'succeeded' || status === 'completed' || status === 'redeemed') return { label: '已完成', tone: 'success' }
  if (status === 'redeeming' || status === 'processing' || status === 'pending') return { label: '处理中', tone: 'warning' }
  if (status === 'refunded' || status === 'revoked' || status === 'failed' || status === 'disabled' || status === 'inactive') return { label: status === 'failed' ? '失败' : status === 'refunded' ? '已退款' : status === 'revoked' ? '已撤销' : '已停用', tone: status === 'failed' ? 'danger' : 'warning' }
  return status ? { label: '待核对', tone: 'neutral' } : { label: '—', tone: 'neutral' }
}

function sumNumeric(items: RedemptionBatchSummary[], key: 'codeCount' | 'redeemedCount'): string {
  if (!items.length) return '—'
  const total = items.reduce((sum, item) => sum + (Number.isFinite(item[key]) ? item[key] : 0), 0)
  return formatCount(total)
}

function remainingCodes(items: RedemptionBatchSummary[]): string {
  if (!items.length) return '—'
  const remaining = items.reduce((sum, item) => sum + Math.max(0, item.codeCount - item.redeemedCount), 0)
  return formatCount(remaining)
}

function operationTitle(mode: OperationMode): string {
  return mode === 'mapping' ? '产品映射编辑' : mode === 'grant' ? '管理员赠款' : mode === 'batch' ? '生成卡密批次' : mode === 'recover' ? '恢复履约' : '退款履约'
}

function operationDescription(mode: OperationMode): string {
  return mode === 'mapping' ? '编辑所选套餐的商品映射与购买链接。' : mode === 'grant' ? '向明确指定的 opaque 租户写入一笔可审计额度。' : mode === 'batch' ? '按当前套餐生成受保护的兑换批次。' : mode === 'recover' ? `按当前汇总${DISPLAY_LABELS.dataVersion}恢复未完成履约。` : `按当前汇总${DISPLAY_LABELS.dataVersion}对已完成履约执行退款。`
}

function operationButtonLabel(mode: OperationMode): string {
  return mode === 'mapping' ? '保存映射' : mode === 'grant' ? '提交赠款' : mode === 'batch' ? '生成受保护批次' : mode === 'recover' ? '恢复履约' : '执行退款'
}

function confirmationText(mode: OperationMode): string {
  return mode === 'mapping' ? '我确认保存当前套餐的商品映射，并承担本次审计边界。' : mode === 'grant' ? '我确认目标租户、额度和审计原因均已核对。' : mode === 'batch' ? '我确认生成当前套餐的受保护卡密批次，卡密不在页面显示。' : mode === 'recover' ? `我确认履约编号、当前${DISPLAY_LABELS.dataVersion}和恢复原因均已核对。` : `我确认履约编号、当前${DISPLAY_LABELS.dataVersion}和退款原因均已核对。`
}

function buildMutationSpec(mode: OperationMode, values: { planCode: string; externalProductId: string; purchaseUrl: string; publicTenantId: string; fulfillmentId: string; amount: string; count: string; reason: string }, revision: number): MutationSpec {
  const auditReason = values.reason.trim()
  if (mode === 'mapping') return { operationId: 'createAdminProductMapping', label: '商品映射', body: { planCode: values.planCode, externalProductId: values.externalProductId.trim(), purchaseUrl: values.purchaseUrl.trim(), reason: auditReason }, auditReason }
  if (mode === 'grant') return { operationId: 'createAdminBillingGrant', label: '管理员赠款', body: { publicTenantId: values.publicTenantId.trim(), amount: values.amount.trim(), reason: auditReason }, auditReason }
  if (mode === 'batch') return { operationId: 'createAdminRedemptionBatch', label: '卡密批次', body: { planCode: values.planCode, count: Number(values.count), reason: auditReason }, auditReason }
  if (mode === 'recover') return { operationId: 'recoverAdminFulfillment', label: '恢复履约', path: { fulfillmentId: values.fulfillmentId.trim() }, body: { reason: auditReason, expectedRevision: revision }, auditReason }
  return { operationId: 'refundAdminFulfillment', label: '退款履约', path: { fulfillmentId: values.fulfillmentId.trim() }, body: { reason: auditReason, expectedRevision: revision }, auditReason }
}
