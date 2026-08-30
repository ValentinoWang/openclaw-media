import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import {
  ArrowUpRight, BarChart3, CheckCircle2, CircleAlert, CreditCard,
  LoaderCircle, ReceiptText, RefreshCw, TicketCheck, WalletCards,
} from 'lucide-react'
import { useMediaWeb } from '../../MediaWebWorkspace'
import {
  BusinessOperationError,
  callBusinessOperation,
} from '../../generatedBusinessPagesContract'
import {
  PageHeading, type LoadState,
} from '../../ui/ordinaryPagePrimitives'
import { newIdempotencyKey } from '../../idempotency'
import { formatDateTime as sharedFormatDateTime, formatDateKey as sharedFormatDateKey } from '../../ui/datetime'
import { Metric } from '../../ui/Metric'
import { usageEventTone } from '../../statusPresentation'
import styles from './UsageBillingPage.module.css'

type UsageEventKind = 'text' | 'image' | 'credit' | 'compensation'
type UsageEventStatus = 'succeeded' | 'compensated' | 'pending_reconciliation'
type UsageEvent = {
  publicUsageId: string
  kind: UsageEventKind
  model: string
  quantity: number
  unit: string
  charge: string
  status: UsageEventStatus
  createdAt: string
}
type UsageEventListResponse = {
  schemaVersion: string
  revision: number
  items: UsageEvent[]
  nextCursor: string | null
}
type BillingBalanceResponse = {
  schemaVersion: string
  revision: number
  balance: {
    available: string
    currency: string
    asOf: string
    revision: number
  }
}
type BalancePack = {
  balancePackCode: string
  name: string
  creditAmount: number
  priceCny: string
  currency: string
  audience: 'all' | 'personal' | 'organization'
  productKind: 'balance_pack'
  purchaseAvailable: boolean
  purchaseUrl: string | null
}
type BalancePackListResponse = {
  schemaVersion: string
  revision: number
  items: BalancePack[]
  nextCursor: string | null
}
type BillingUsageSummaryResponse = {
  schemaVersion: string
  revision: number
  summary: {
    textQuantity: number
    imageQuantity: number
    totalCharge: string
    currency: string
    from: string
    to: string
    revision: number
  }
}
type MutationReceipt = {
  schemaVersion: string
  revision: number
  ok: boolean
  updatedAt: string
}
type UsagePageData = {
  items: UsageEvent[]
  usageRevision: number
  summary: BillingUsageSummaryResponse
}
type TabId = 'redemptions' | 'usage'
type ActionState = { kind: 'idle' | 'busy' | 'success' | 'error'; message: string }
type FixedDecimal = {
  coefficient: bigint
  scale: number
}
type DailyPoint = {
  date: string
  events: number
  textQuantity: number | null
  imageQuantity: number | null
  charge: string | null
  chargeValue: number | null
  chargeUnknown: boolean
}

function UsageBillingPage() {
  const { runtimeState, session } = useMediaWeb()
  const canRead = runtimeState === 'authenticated' && session?.role === 'ordinary'
  const [tab, setTab] = useState<TabId>('redemptions')
  const [refresh, setRefresh] = useState(0)
  const [code, setCode] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey('redemption'))
  const [action, setAction] = useState<ActionState>({ kind: 'idle', message: '' })
  const [receipt, setReceipt] = useState<MutationReceipt | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const balance = usePermissionLoad(canRead, readBalance, refresh)
  const balancePacks = usePermissionLoad(canRead, readBalancePacks, refresh)
  const usage = usePermissionLoad(canRead, readUsageBundle, refresh)
  const daily = useMemo(() => usage.status === 'ready' ? aggregateDaily(usage.data.items) : [], [usage])

  function openRedemption() {
    setTab('redemptions')
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  async function submitRedemption() {
    if (!canRead || !session || !code.trim() || action.kind === 'busy') return
    setAction({ kind: 'busy', message: '正在验证卡密并兑换' })
    try {
      const result = await callBusinessOperation<MutationReceipt>('redeemBillingCode', {
        body: { code: code.trim() },
        csrfToken: session.csrfToken,
        idempotencyKey,
      })
      setReceipt(result)
      setCode('')
      setIdempotencyKey(newIdempotencyKey('redemption'))
      setAction({ kind: 'success', message: '兑换已成功，正在重新读取余额、额度包和用量。' })
      setRefresh((value) => value + 1)
    } catch (error) {
      setAction({ kind: 'error', message: readableError(error, '兑换') })
    }
  }

  const refreshData = () => setRefresh((value) => value + 1)
  const pageAction = canRead ? <button className="primary-button" type="button" onClick={openRedemption}><TicketCheck size={16} />兑换卡密</button> : null

  return <main className={'fidelity-page ' + styles.page}>
    {!canRead ? <>
      <PageHeading title="用量与余额" description="查看当前账户的模型用量、余额和兑换入口。" />
      <AccessBoundary />
    </> : <>
      <div data-page-prelude>
        <PageHeading title="用量与余额" description="查看当前账户的模型用量、余额和兑换入口。" action={pageAction} />
        <nav className={styles.tabs} role="tablist" aria-label="用量与余额分区">
          <TabButton id="redemptions" active={tab === 'redemptions'} label="兑换入口" onSelect={() => setTab('redemptions')} />
          <TabButton id="usage" active={tab === 'usage'} label="模型用量" onSelect={() => setTab('usage')} />
        </nav>
      </div>
      <div className={styles.workspace} data-page-layout="persistent-rail">
      <div className={styles.primaryColumn} data-page-primary data-primary-flow>
        <div className={styles.tabContent}>
          {tab === 'usage' ? <UsagePanel state={usage} daily={daily} onRefresh={refreshData} /> : null}
          {tab === 'redemptions' ? <RedemptionPanel
            code={code}
            inputRef={inputRef}
            action={action}
            receipt={receipt}
            balanceStatus={balance.status}
            onCodeChange={(value) => { setCode(value); setIdempotencyKey(newIdempotencyKey('redemption')); setAction({ kind: 'idle', message: '' }) }}
            onSubmit={() => void submitRedemption()}
          /> : null}
        </div>
      </div>
      <aside className={styles.rail} aria-label="账户计费摘要" data-page-inspector tabIndex={0}>
        <BalancePanel state={balance} />
        <PurchasePanel state={balancePacks} />
        <ReceiptPanel receipt={receipt} events={usage.status === 'ready' ? usage.data.items : []} balanceStatus={balance.status} onOpen={openRedemption} />
      </aside>
    </div></>}
  </main>
}

function usePermissionLoad<T>(allowed: boolean, loader: () => Promise<T>, refresh: number): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  useEffect(() => {
    if (!allowed) {
      setState({ status: 'loading' })
      return
    }
    let active = true
    setState({ status: 'loading' })
    loader().then((data) => { if (active) setState({ status: 'ready', data }) }).catch(() => { if (active) setState({ status: 'error', message: '这部分信息暂时无法读取，请稍后重试。' }) })
    return () => { active = false }
  }, [allowed, loader, refresh])
  return state
}

function TabButton({ id, active, label, onSelect }: { id: TabId; active: boolean; label: string; onSelect: () => void }) {
  return <button id={id + '-tab'} className={active ? styles.tab + ' ' + styles.activeTab : styles.tab} type="button" role="tab" aria-selected={active} aria-controls={id + '-panel'} onClick={onSelect}>{label}</button>
}

function UsagePanel({ state, daily, onRefresh }: { state: LoadState<UsagePageData>; daily: DailyPoint[]; onRefresh: () => void }) {
  if (state.status !== 'ready') return <section className={styles.panel} id="usage-panel" role="tabpanel" aria-labelledby="usage-tab" data-page-terminal-surface="primary">
    <PanelHeading title="文本与图片用量" detail="服务端守恒汇总和不可变事件明细" />
    <ResourceState state={state} label="用量与守恒汇总" />
  </section>
  const { items, summary } = state.data
  const range = getRange(items)
  const summaryRange = formatDateTime(summary.summary.from) + ' - ' + formatDateTime(summary.summary.to)
  const rangeDetail = range ? '明细范围 ' + range : '服务端范围 ' + summaryRange
  return <div className={styles.stack} id="usage-panel" role="tabpanel" aria-labelledby="usage-tab">
    <section className={styles.panel}>
      <PanelHeading title="当前用量汇总" detail={rangeDetail} action={<button className={styles.quietButton} type="button" onClick={onRefresh}><RefreshCw size={14} />刷新数据</button>} />
      <div className={styles.metrics}>
        <Metric className={styles.metric} label="文本用量" value={formatQuantity(summary.summary.textQuantity)} detail="服务端守恒汇总" />
        <Metric className={styles.metric} label="图片用量" value={formatQuantity(summary.summary.imageQuantity)} detail="服务端守恒汇总" />
        <Metric className={styles.metric} label="计费金额" value={formatCredit(summary.summary.totalCharge) + ' ' + currencyDisplayLabel(summary.summary.currency)} detail="服务端守恒汇总" />
        <Metric className={styles.metric} label="用量事件" value={formatCount(items.length)} detail="服务端事件明细" />
      </div>
    </section>
    <section className={styles.panel}>
      <PanelHeading title="每日用量趋势" detail="由不可变事件的 createdAt 按本地日期归并，金额保留定点精度" />
      {daily.length ? <DailyTrend points={daily} /> : <EmptyState icon={<BarChart3 size={20} />} title="暂无可绘制的每日趋势" detail="返回明细没有可识别的时间字段。" />}
    </section>
    <section className={styles.panel} data-page-terminal-surface="primary">
      <PanelHeading title="不可变用量事件" detail="每行来自服务端 immutable usage event，包含文本、图片、补偿和额度事件" />
      {items.length ? <UsageTable rows={items} /> : <EmptyState icon={<ReceiptText size={20} />} title="暂无用量事件" detail="当前账户没有可展示的服务端不可变事件。" />}
    </section>
  </div>
}

function DailyTrend({ points }: { points: DailyPoint[] }) {
  const maxEvents = Math.max(...points.map((point) => point.events), 1)
  const maxText = Math.max(...points.map((point) => point.textQuantity ?? 0), 1)
  const maxImage = Math.max(...points.map((point) => point.imageQuantity ?? 0), 1)
  const maxCharge = Math.max(...points.map((point) => point.chargeValue ?? 0), 1)
  return <div className={styles.trend}>
    <div className={styles.trendLegend}><span><i className={styles.greenDot} />事件数</span><span><i className={styles.blueDot} />文本用量</span><span><i className={styles.orangeDot} />图片用量</span><span><i className={styles.purpleDot} />计费金额</span></div>
    <div className={styles.trendRows} role="region" aria-label="每日用量趋势" tabIndex={0}>{points.map((point) => <div className={styles.trendRow} key={point.date}>
      <strong className={styles.trendDate}>{point.date}</strong>
      <TrendBar label="事件" value={point.events} max={maxEvents} tone="green" suffix=" 次" />
      <TrendBar label="文本" value={point.textQuantity} max={maxText} tone="blue" suffix="" />
      <TrendBar label="图片" value={point.imageQuantity} max={maxImage} tone="orange" suffix="" />
      <TrendBar label="金额" value={point.chargeValue} max={maxCharge} tone="purple" suffix="" display={point.chargeUnknown ? '未知' : point.charge === null ? '—' : formatCredit(point.charge) + ' credit'} />
    </div>)}</div>
    <p className={styles.trendNote}>趋势按明细事件展示；总计以服务端守恒汇总为准。</p>
  </div>
}

function TrendBar({ label, value, max, tone, suffix, display }: { label: string; value: number | null; max: number; tone: 'green' | 'blue' | 'orange' | 'purple'; suffix: string; display?: string }) {
  const width = value === null ? 0 : Math.max(3, Math.round((value / max) * 100))
  const text = display ?? (value === null ? '—' : formatTrendNumber(value) + suffix)
  return <div className={styles.trendMetric}><span>{label}</span><div className={styles.bar}><i className={styles[tone + 'Bar']} style={{ width: width + '%' }} /></div><strong>{text}</strong></div>
}

function UsageTable({ rows }: { rows: UsageEvent[] }) {
  return <div className={styles.tableWrap} role="region" aria-label="不可变用量事件表格" tabIndex={0}><table className={styles.usageTable}><thead><tr><th scope="col">类型</th><th scope="col">模型</th><th scope="col">数量</th><th scope="col">单位</th><th scope="col">计费</th><th scope="col">状态</th><th scope="col">时间</th><th scope="col">公开事件编号</th></tr></thead><tbody>{rows.map((row) => <tr key={row.publicUsageId}><th scope="row">{kindLabel(row.kind)}</th><td title={billingModelLabel(row.model)}>{billingModelLabel(row.model)}</td><td>{formatQuantity(row.quantity)}</td><td>{usageUnitLabel(row.unit)}</td><td>{formatCredit(row.charge)} 额度</td><td><StatusBadge value={row.status} /></td><td>{formatDateTime(row.createdAt)}</td><td className={styles.breakAll}>{row.publicUsageId}</td></tr>)}</tbody></table></div>
}

function RedemptionPanel({ code, inputRef, action, receipt, balanceStatus, onCodeChange, onSubmit }: { code: string; inputRef: RefObject<HTMLInputElement | null>; action: ActionState; receipt: MutationReceipt | null; balanceStatus: LoadState<unknown>['status']; onCodeChange: (value: string) => void; onSubmit: () => void }) {
  return <div className={styles.stack} id="redemptions-panel" role="tabpanel" aria-labelledby="redemptions-tab">
    <section className={styles.panel} data-page-terminal-surface="primary">
      <PanelHeading title="兑换卡密" detail="兑换成功后会自动更新余额和用量" />
      <form className={styles.redemptionForm} onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
        <label className={styles.field}><span>卡密</span><input ref={inputRef} type="password" value={code} onChange={(event) => onCodeChange(event.target.value)} autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} placeholder="输入卡密" /></label>
        <button className="primary-button" type="submit" disabled={!code.trim() || action.kind === 'busy'} aria-busy={action.kind === 'busy'}><TicketCheck size={16} />{action.kind === 'busy' ? '正在兑换' : '兑换卡密'}</button>
      </form>
      {action.kind !== 'idle' ? <div className={action.kind === 'error' ? styles.errorNotice : styles.successNotice} role="status"><StateIcon kind={action.kind} /><span>{action.message}</span></div> : null}
      {receipt ? <ReceiptDetails receipt={receipt} balanceStatus={balanceStatus} /> : <EmptyState icon={<ReceiptText size={20} />} title="历史兑换记录暂未提供" detail="完成兑换后，本页会保留本次兑换结果。" />}
    </section>
  </div>
}

function ReceiptDetails({ receipt, balanceStatus }: { receipt: MutationReceipt; balanceStatus: LoadState<unknown>['status'] }) {
  const readback = !receipt.ok ? '兑换尚未确认成功，余额不会被视为到账。' : balanceStatus === 'ready' ? '余额已更新' : balanceStatus === 'error' ? '兑换已成功，但余额更新失败' : '余额正在更新'
  return <div className={styles.receipt} role="region" aria-label="兑换服务端回执" tabIndex={0}>
    <div className={styles.receiptHead}><CheckCircle2 size={18} /><strong>本次兑换结果</strong></div>
    <dl className={styles.facts}><div><dt>状态</dt><dd><StatusBadge value={receipt.ok ? 'succeeded' : 'failed'} /></dd></div><div><dt>处理时间</dt><dd>{formatDateTime(receipt.updatedAt)}</dd></div></dl>
    <p className={!receipt.ok || balanceStatus === 'error' ? styles.errorText : styles.successText}>{readback}</p>
  </div>
}

function BalancePanel({ state }: { state: LoadState<BillingBalanceResponse> }) {
  return <section className={styles.railPanel}>
    <PanelHeading title="当前余额" detail="当前租户可用余额" icon={<WalletCards size={17} />} />
    {state.status !== 'ready' ? <ResourceState state={state} label="账户余额" compact /> : <div className={styles.balance}><strong>{formatCredit(state.data.balance.available)} {currencyDisplayLabel(state.data.balance.currency)}</strong><dl className={styles.facts}><div><dt>可用余额</dt><dd>{formatCredit(state.data.balance.available)} {currencyDisplayLabel(state.data.balance.currency)}</dd></div><div><dt>余额最后变动</dt><dd>{formatDateTime(state.data.balance.asOf)}</dd></div></dl><p className={styles.balanceNote}>该时间表示余额最近一次发生变动，不是页面刷新时间。</p></div>}
  </section>
}

function PurchasePanel({ state }: { state: LoadState<BalancePackListResponse> }) {
  return <section className={styles.railPanel}>
    <PanelHeading title="可选额度包" detail={state.status === 'ready' ? '服务端可购买额度包' : '链动小铺购买入口'} icon={<CreditCard size={17} />} />
    {state.status !== 'ready' ? <ResourceState state={state} label="额度包" compact /> : state.data.items.length ? <div className={styles.purchaseList} role="region" tabIndex={0} aria-label="服务端额度包">{state.data.items.map((balancePack) => <PurchaseListItem balancePack={balancePack} key={balancePack.balancePackCode} />)}</div> : <EmptyState icon={<CreditCard size={18} />} title="暂无可用额度包" detail="额度包目录没有返回可展示的服务端记录。" compact />}
  </section>
}

function PurchaseListItem({ balancePack }: { balancePack: BalancePack }) {
  const purchaseUrl = chainStorePurchaseUrl(balancePack)
  const content = <><span><strong>{balancePack.name}</strong><small>{formatCredit(balancePack.priceCny)} {currencyDisplayLabel(balancePack.currency)} · {formatQuantity(balancePack.creditAmount)} 额度</small></span>{purchaseUrl ? <ArrowUpRight size={16} /> : <span className={styles.purchaseUnavailable}>暂不可购买 · 未配置或未启用链动映射</span>}</>
  return purchaseUrl ? <a className={styles.purchaseLink} href={purchaseUrl} target="_blank" rel="noopener noreferrer" aria-label={'购买 ' + balancePack.name} title={'购买 ' + balancePack.name}>{content}</a> : <div className={styles.purchaseLink + ' ' + styles.unavailablePurchase} aria-disabled="true" aria-label={balancePack.name + '暂不可购买'}>{content}</div>
}

function chainStorePurchaseUrl(balancePack: BalancePack): string | null {
  if (balancePack.purchaseAvailable !== true || !balancePack.purchaseUrl) return null
  try {
    const url = new URL(balancePack.purchaseUrl)
    const host = url.hostname.toLowerCase().replace(/\.$/, '')
    if (url.protocol !== 'https:' || (host !== 'ldxp.cn' && !host.endsWith('.ldxp.cn')) || url.username || url.password || url.port || url.hash) return null
    return url.toString()
  } catch {
    return null
  }
}

function ReceiptPanel({ receipt, events, balanceStatus, onOpen }: { receipt: MutationReceipt | null; events: UsageEvent[]; balanceStatus: LoadState<unknown>['status']; onOpen: () => void }) {
  const redemptionEvents = events.filter((event) => event.kind === 'credit' || event.kind === 'compensation').slice(-5).reverse()
  return <section className={styles.railPanel} data-page-terminal-surface="inspector">
    <PanelHeading title="最近兑换记录" detail={receipt ? '显示本次会话最新兑换结果' : redemptionEvents.length ? '显示已记录的额度变动' : '等待额度变动记录'} icon={<ReceiptText size={17} />} action={<button className={styles.textButton} type="button" onClick={onOpen}>打开兑换页 <ArrowUpRight size={13} /></button>} />
    {receipt ? <ReceiptDetails receipt={receipt} balanceStatus={balanceStatus} /> : redemptionEvents.length ? <RedemptionHistory events={redemptionEvents} /> : <EmptyState icon={<ReceiptText size={18} />} title="暂无历史记录" detail="服务端用量明细没有返回额度兑换事件。" compact />}
  </section>
}

function RedemptionHistory({ events }: { events: UsageEvent[] }) {
  return <div className={styles.history} role="region" aria-label="历史兑换记录" tabIndex={0}><strong className={styles.historyTitle}>额度变动记录</strong><div className={styles.historyList}>{events.map((event) => <article className={styles.historyItem} key={event.publicUsageId}><div className={styles.historyItemHead}><strong>{kindLabel(event.kind)}</strong><StatusBadge value={event.status} /></div><span className={styles.historyMeta}>{billingModelLabel(event.model)} · {formatQuantity(event.quantity)} {usageUnitLabel(event.unit)}</span><time dateTime={event.createdAt}>{formatDateTime(event.createdAt)}</time></article>)}</div></div>
}

function PanelHeading({ title, detail, action, icon }: { title: string; detail?: string; action?: ReactNode; icon?: ReactNode }) {
  return <header className={styles.heading}><div className={styles.headingTitle}>{icon}<div><h2>{title}</h2>{detail ? <p>{detail}</p> : null}</div></div>{action}</header>
}

const usageToneClasses: Record<ReturnType<typeof usageEventTone>, string> = {
  success: styles.statusSuccess,
  danger: styles.statusError,
  neutral: styles.statusNeutral,
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.trim().toLowerCase()
  const tone = usageToneClasses[usageEventTone(value)]
  const label = ['succeeded', 'success', 'completed'].includes(normalized) ? '已完成' : ['pending', 'processing', 'pending_reconciliation'].includes(normalized) ? '处理中' : ['failed', 'error', 'cancelled'].includes(normalized) ? '失败' : '状态待确认'
  return <span className={styles.statusBadge + ' ' + tone}>{label}</span>
}

function ResourceState({ state, label, compact = false }: { state: LoadState<unknown>; label: string; compact?: boolean }) {
  if (state.status === 'loading') return <div className={compact ? styles.state + ' ' + styles.compactState : styles.state} aria-busy="true"><LoaderCircle className={styles.spin} size={18} /><span>正在读取{label}</span></div>
  if (state.status === 'error') return <div className={compact ? styles.state + ' ' + styles.compactState + ' ' + styles.errorState : styles.state + ' ' + styles.errorState} role="alert"><CircleAlert size={18} /><span>{state.message}</span></div>
  return null
}

function EmptyState({ icon, title, detail, compact = false }: { icon: ReactNode; title: string; detail: string; compact?: boolean }) {
  return <div className={compact ? styles.empty + ' ' + styles.compactEmpty : styles.empty}>{icon}<div><strong>{title}</strong><p>{detail}</p></div></div>
}

function AccessBoundary() {
  return <section className={styles.access}><CircleAlert size={22} /><div><h2>无法加载账户计费页面</h2><p>当前页面只允许普通使用者查看所属租户的用量、余额、套餐和兑换回执。身份服务返回后才会读取任何账户数据。</p></div></section>
}

function StateIcon({ kind }: { kind: ActionState['kind'] }) {
  return kind === 'error' ? <CircleAlert size={17} /> : kind === 'busy' ? <LoaderCircle className={styles.spin} size={17} /> : <CheckCircle2 size={17} />
}

function aggregateDaily(rows: UsageEvent[]): DailyPoint[] {
  type DailyBucket = {
    events: number
    textQuantity: number
    hasText: boolean
    imageQuantity: number
    hasImage: boolean
    charge: FixedDecimal | null
    chargeUnknown: boolean
  }
  const buckets = new Map<string, DailyBucket>()
  for (const row of rows) {
    const timestamp = new Date(row.createdAt)
    if (Number.isNaN(timestamp.getTime())) continue
    const key = localDateKey(timestamp)
    const current = buckets.get(key) || { events: 0, textQuantity: 0, hasText: false, imageQuantity: 0, hasImage: false, charge: null, chargeUnknown: false }
    current.events += 1
    if (row.kind === 'text') { current.textQuantity += row.quantity; current.hasText = true }
    if (row.kind === 'image') { current.imageQuantity += row.quantity; current.hasImage = true }
    const parsedCharge = parseFixedDecimal(row.charge)
    if (!parsedCharge) current.chargeUnknown = true
    else current.charge = addFixedDecimal(current.charge, parsedCharge)
    buckets.set(key, current)
  }
  return Array.from(buckets.entries()).sort(([left], [right]) => left.localeCompare(right)).map(([key, value]) => {
    const chargeValue = value.charge === null ? null : fixedToNumber(value.charge)
    return {
      date: formatDateKey(key),
      events: value.events,
      textQuantity: value.hasText ? value.textQuantity : null,
      imageQuantity: value.hasImage ? value.imageQuantity : null,
      charge: value.charge === null ? null : fixedToString(value.charge),
      chargeValue,
      chargeUnknown: value.chargeUnknown || (value.charge !== null && chargeValue === null),
    }
  })
}

function getRange(rows: UsageEvent[]) {
  const timestamps = rows.map((row) => new Date(row.createdAt)).filter((date) => !Number.isNaN(date.getTime())).sort((left, right) => left.getTime() - right.getTime())
  return timestamps.length ? formatDateOnly(timestamps[0]) + ' - ' + formatDateOnly(timestamps[timestamps.length - 1]) : ''
}

function formatCount(value: number) { return new Intl.NumberFormat('zh-CN').format(value) }
function formatTrendNumber(value: number) { return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 2 }).format(value) }
function formatQuantity(value: number) { return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value) }
function formatCredit(value: string) {
  const parsed = parseFixedDecimal(value)
  return parsed ? fixedToString(parsed) : '未知'
}
function kindLabel(kind: UsageEventKind) {
  return kind === 'text' ? '文本' : kind === 'image' ? '图片' : kind === 'credit' ? '额度' : '补偿'
}
function billingModelLabel(value: string) {
  const normalized = value.trim().toLowerCase()
  if (['text', 'chat', 'completion'].includes(normalized)) return '文本模型'
  if (['image', 'image_generation'].includes(normalized)) return '图像模型'
  if (['credit', 'compensation'].includes(normalized)) return '额度服务'
  return '模型待确认'
}
function usageUnitLabel(value: string) {
  const normalized = value.trim().toLowerCase()
  if (['token', 'tokens'].includes(normalized)) return '词元'
  if (['image', 'images'].includes(normalized)) return '张'
  if (['credit', 'credits'].includes(normalized)) return '额度'
  if (['request', 'requests'].includes(normalized)) return '次'
  return '计量单位待确认'
}
function currencyDisplayLabel(value: string) {
  const normalized = value.trim().toUpperCase()
  if (normalized === 'CNY') return '人民币'
  if (normalized === 'USD') return '美元'
  if (normalized === 'CREDIT' || normalized === 'CREDITS') return '额度'
  return '计费单位待确认'
}
function parseFixedDecimal(value: string): FixedDecimal | null {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (!match) return null
  const fraction = match[3] || ''
  const coefficient = BigInt((match[2] + fraction) || '0')
  return { coefficient: match[1] === '-' ? -coefficient : coefficient, scale: fraction.length }
}
function addFixedDecimal(left: FixedDecimal | null, right: FixedDecimal): FixedDecimal {
  if (left === null) return right
  const scale = Math.max(left.scale, right.scale)
  return {
    coefficient: scaleCoefficient(left.coefficient, scale - left.scale) + scaleCoefficient(right.coefficient, scale - right.scale),
    scale,
  }
}
function scaleCoefficient(value: bigint, places: number) {
  let result = value
  for (let index = 0; index < places; index += 1) result *= 10n
  return result
}
function fixedToString(value: FixedDecimal) {
  const negative = value.coefficient < 0n
  const absolute = (negative ? -value.coefficient : value.coefficient).toString()
  if (value.scale === 0) return (negative ? '-' : '') + absolute
  const padded = absolute.padStart(value.scale + 1, '0')
  const integer = padded.slice(0, -value.scale)
  const fraction = padded.slice(-value.scale).replace(/0+$/, '')
  return (negative ? '-' : '') + integer + (fraction ? '.' + fraction : '')
}
function fixedToNumber(value: FixedDecimal) {
  const number = Number(fixedToString(value))
  return Number.isFinite(number) ? number : null
}
function formatDateTime(value: string | null) { return sharedFormatDateTime(value, { empty: '时间未提供', invalid: '时间未提供' }) }
function formatDateOnly(value: Date) { return value.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }) }
function localDateKey(value: Date) { return [value.getFullYear(), String(value.getMonth() + 1).padStart(2, '0'), String(value.getDate()).padStart(2, '0')].join('-') }
function formatDateKey(value: string) { return sharedFormatDateKey(value, { invalid: '日期未提供' }) }

async function readUsageBundle(): Promise<UsagePageData> {
  try {
    const [usage, summary] = await Promise.all([readUsageEvents(), readUsageSummary()])
    if (usage.revision !== summary.revision) throw new Error('用量数据版本不一致，请刷新重试。')
    return { items: usage.items, usageRevision: usage.revision, summary }
  } catch (error) {
    throw new Error(readableError(error, '模型用量'))
  }
}

async function readUsageEvents(): Promise<{ items: UsageEvent[]; revision: number }> {
  let cursor: string | undefined
  let revision: number | null = null
  const items: UsageEvent[] = []
  const seenCursors = new Set<string>()
  while (true) {
    const query: { cursor?: string; pageSize: number } = { pageSize: 100 }
    if (cursor !== undefined) query.cursor = cursor
    const page = await callBusinessOperation<UsageEventListResponse>('listBillingUsage', { query })
    if (revision === null) revision = page.revision
    else if (page.revision !== revision) throw new Error('用量数据在读取过程中发生变化，请刷新重试。')
    items.push(...page.items)
    if (page.nextCursor === null) return { items, revision: page.revision }
    if (seenCursors.has(page.nextCursor)) throw new Error('用量分页游标未推进，请刷新重试。')
    seenCursors.add(page.nextCursor)
    cursor = page.nextCursor
  }
}

async function readUsageSummary(): Promise<BillingUsageSummaryResponse> {
  try {
    return await callBusinessOperation<BillingUsageSummaryResponse>('getBillingUsageSummary')
  } catch (error) {
    throw new Error(readableError(error, '用量汇总'))
  }
}

async function readBalance(): Promise<BillingBalanceResponse> {
  try {
    return await callBusinessOperation<BillingBalanceResponse>('getBillingBalance')
  } catch (error) {
    throw new Error(readableError(error, '账户余额'))
  }
}

async function readBalancePacks(): Promise<BalancePackListResponse> {
  try {
    return await callBusinessOperation<BalancePackListResponse>('listBillingBalancePacks')
  } catch (error) {
    throw new Error(readableError(error, '额度包目录'))
  }
}

function readableError(error: unknown, subject: string) {
  if (error instanceof BusinessOperationError) {
    if (error.status === 401) return '登录状态已失效，请重新登录后再试。'
    if (error.status === 403) return '当前账户没有权限查看这部分个人计费信息。'
    if (error.status >= 500) return subject + '服务暂时不可用，请稍后再试。'
    return subject + '暂时无法读取，请稍后再试。'
  }
  return subject + '暂时无法读取，请稍后再试。'
}

export default UsageBillingPage
