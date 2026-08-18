import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { AlertCircle, ChevronLeft, ChevronRight, CircleDollarSign, LayoutDashboard, PenTool, Search, Server, ShieldCheck, TicketCheck, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import {
  adminGet, adminMutate, loadAdminBillingSummary, loadAdminUpstreamSummary, loadTenantDashboard,
  type AdminBillingSummary, type AdminRunSummary, type AdminRunSummaryPage,
} from '../mediaWebApi'
import { runStatusLabel, runStatusTone } from '../statusPresentation'
import {
  canonicalUuid, liandongPurchaseUrl, mutationFingerprint, nonNegativeInteger, positiveId, positiveMoney,
  useAdminAction, useLoad,
  type ActionState, type LoadState,
} from './adminAction'

export type AdminModule = 'dashboard' | 'invitations' | 'admission' | 'registration' | 'resources' | 'billing' | 'upstream'

export function AdminPage({ initialModule, title, description, allowedModules = [initialModule] }: { initialModule: AdminModule; title: string; description: string; allowedModules?: AdminModule[] }) {
  const [module, setModule] = useState<AdminModule>(initialModule)
  const [refresh, setRefresh] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const routes: Record<AdminModule, string> = {
    dashboard: '',
    invitations: `/admin/affiliate-users?page=${page}&page_size=30${submittedSearch ? `&search=${encodeURIComponent(submittedSearch)}` : ''}`,
    admission: `/admin/admission-batches?page=${page}&page_size=30`, resources: '', registration: '', billing: '', upstream: '',
  }
  const state = useLoad(() => module === 'dashboard' ? loadTenantDashboard() : ['resources', 'registration', 'billing', 'upstream'].includes(module) ? Promise.resolve({}) : adminGet(routes[module]), [module, page, submittedSearch, refresh])
  function selectModule(next: AdminModule) { setModule(next); setPage(1); setSearch(''); setSubmittedSearch('') }
  const visibleModules = adminModules.filter(({ key }) => allowedModules.includes(key))
  return <main className="fidelity-page"><PageHeading title={title} description={description} />
    {visibleModules.length > 1 ? <div className="detail-tabs admin-tabs" role="tablist">{visibleModules.map(({ key, label, icon: Icon }) => <button key={key} className={module === key ? 'active' : ''} onClick={() => selectModule(key)}><Icon size={15} />{label}</button>)}</div> : null}
    {module === 'invitations' ? <form className="track-filter-bar admin-filter-bar" onSubmit={(event) => { event.preventDefault(); setPage(1); setSubmittedSearch(search.trim()) }}><label className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索用户" /></label><button className="quiet-button" type="submit">搜索</button></form> : null}
    <AdminActions module={module} refresh={refresh} onComplete={() => setRefresh((value) => value + 1)} />
    {module === 'resources' ? <AdminTenantResources /> : module === 'billing' ? <AdminBillingReadModel refresh={refresh} /> : module === 'upstream' ? <AdminUpstreamReadModel refresh={refresh} /> : module === 'registration' ? null : state.status === 'ready' ? <><RecordTable value={state.data} />{module === 'dashboard' ? null : <NumberPagination page={page} value={state.data} onPage={setPage} />}</> : <PageState state={state} />}
  </main>
}

const adminModules: Array<{ key: AdminModule; label: string; icon: typeof Users }> = [
  { key: 'dashboard', label: '概览', icon: LayoutDashboard },
  { key: 'invitations', label: '邀请权限', icon: Users },
  { key: 'admission', label: '准入码', icon: TicketCheck }, { key: 'registration', label: '注册策略', icon: ShieldCheck },
  { key: 'resources', label: '租户资源', icon: PenTool },
  { key: 'billing', label: '零售计费', icon: CircleDollarSign },
  { key: 'upstream', label: '上游运营', icon: Server },
]

function AdminActions({ module, refresh, onComplete }: { module: AdminModule; refresh: number; onComplete: () => void }) {
  if (module === 'dashboard' || module === 'resources') return null
  if (module === 'invitations') return <AdminInvitationActions onComplete={onComplete} />
  if (module === 'admission') return <AdminAdmissionActions onComplete={onComplete} />
  if (module === 'registration') return <AdminRegistrationPolicy refresh={refresh} onComplete={onComplete} />
  if (module === 'billing') return <AdminBillingActions onComplete={onComplete} />
  return null
}

type RegistrationPolicy = { registrationPolicyMode: 'controlled' | 'open' }

function AdminRegistrationPolicy({ refresh, onComplete }: { refresh: number; onComplete: () => void }) {
  const { session } = useMediaWeb()
  const policy = useLoad(() => adminGet<RegistrationPolicy>('/admin/registration-policy'), [refresh])
  const [mode, setMode] = useState<RegistrationPolicy['registrationPolicyMode']>('controlled')
  const [reason, setReason] = useState('')
  const action = useAdminAction(onComplete)
  useEffect(() => { if (policy.status === 'ready') setMode(policy.data.registrationPolicyMode) }, [policy])
  const ready = !!session && policy.status === 'ready' && !!reason.trim()
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!session || !ready) return
    const path = '/admin/registration-policy'
    const payload = { registrationPolicyMode: mode, reason: reason.trim() }
    const result = await action.run(mutationFingerprint(path, 'PUT', payload), (idempotencyKey) => adminMutate<RegistrationPolicy>(session, path, 'PUT', payload, idempotencyKey))
    if (result) setReason('')
  }
  return <AdminActionPanel title="注册策略" state={action.state}>
    {policy.status !== 'ready' ? <PageState state={policy} /> : <form onSubmit={(event) => void submit(event)}><AdminFields>
      <Field label="注册模式"><select value={mode} onChange={(event) => setMode(event.target.value as RegistrationPolicy['registrationPolicyMode'])}><option value="controlled">受控注册</option><option value="open">开放注册</option></select></Field>
      <ReasonField value={reason} onChange={setReason} />
    </AdminFields><button className="primary-button" disabled={!ready || action.busy}>保存注册策略</button></form>}
  </AdminActionPanel>
}

function AdminInvitationActions({ onComplete }: { onComplete: () => void }) {
  const { session } = useMediaWeb(); const [userId, setUserId] = useState(''); const [enabled, setEnabled] = useState(false); const [quota, setQuota] = useState('0'); const [expiresAt, setExpiresAt] = useState(''); const [reason, setReason] = useState(''); const action = useAdminAction(onComplete)
  const ready = !!session && canonicalUuid(userId) && nonNegativeInteger(quota) && (!expiresAt || !Number.isNaN(new Date(expiresAt).getTime())) && !!reason.trim()
  async function submit(event: FormEvent) { event.preventDefault(); if (session && ready) { const path = `/admin/affiliate-users/${userId}`; const payload = { signupEnabled: enabled, signupQuota: Number(quota), signupExpiresAt: expiresAt ? new Date(expiresAt).toISOString() : null, reason: reason.trim() }; await action.run(mutationFingerprint(path, 'PUT', payload), (idempotencyKey) => adminMutate(session, path, 'PUT', payload, idempotencyKey)) } }
  return <AdminActionPanel title="用户裂变权限" state={action.state}><form onSubmit={(event) => void submit(event)}><AdminFields><Field label="用户 ID"><input inputMode="text" autoCapitalize="none" value={userId} onChange={(event) => setUserId(event.target.value)} /></Field><Field label="允许裂变"><label className="toggle-field"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span>{enabled ? '已开启' : '已关闭'}</span></label></Field><Field label="可注册人数"><input type="number" min="0" step="1" value={quota} onChange={(event) => setQuota(event.target.value)} /></Field><Field label="注册有效期"><input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></Field><ReasonField value={reason} onChange={setReason} /></AdminFields><button className="primary-button" disabled={!ready || action.busy}>保存邀请权限</button></form></AdminActionPanel>
}

function AdminAdmissionActions({ onComplete }: { onComplete: () => void }) {
  const { session } = useMediaWeb(); const [mode, setMode] = useState<'issue' | 'disable'>('issue'); const [name, setName] = useState(''); const [count, setCount] = useState('10'); const [batchId, setBatchId] = useState(''); const [reason, setReason] = useState(''); const [issuedCodes, setIssuedCodes] = useState<string[]>([]); const action = useAdminAction(onComplete)
  const ready = !!session && !!reason.trim() && (mode === 'issue' ? !!name.trim() && positiveId(count) && Number(count) <= 1000 : positiveId(batchId))
  async function submit(event: FormEvent) { event.preventDefault(); if (!session || !ready) return; const path = mode === 'issue' ? '/admin/admission-batches' : `/admin/admission-batches/${batchId}/disable`; const payload = mode === 'issue' ? { name: name.trim(), codeCount: Number(count), reason: reason.trim() } : { reason: reason.trim() }; const result = await action.run(mutationFingerprint(path, 'POST', payload), (idempotencyKey) => adminMutate<Record<string, unknown>>(session, path, 'POST', payload, idempotencyKey)); if (mode === 'issue' && result) setIssuedCodes(Array.isArray(result.codes) ? result.codes.filter((value): value is string => typeof value === 'string' && !!value) : []); if (mode === 'disable' && result) setIssuedCodes([]) }
  return <AdminActionPanel title="平台注册准入码" state={action.state}><form onSubmit={(event) => void submit(event)}><div className="segmented-control"><button type="button" className={mode === 'issue' ? 'active' : ''} onClick={() => setMode('issue')}>签发批次</button><button type="button" className={mode === 'disable' ? 'active' : ''} onClick={() => { setMode('disable'); setIssuedCodes([]) }}>禁用批次</button></div><AdminFields>{mode === 'issue' ? <><Field label="批次名称"><input value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="数量"><input type="number" min="1" max="1000" value={count} onChange={(event) => setCount(event.target.value)} /></Field></> : <TextAdminField label="批次 ID" type="number" value={batchId} onChange={setBatchId} />}<ReasonField value={reason} onChange={setReason} /></AdminFields><button className="primary-button" disabled={!ready || action.busy}>{mode === 'issue' ? '生成批次' : '禁用批次'}</button></form>{issuedCodes.length ? <section className="controlled-export" aria-live="polite"><strong>准入码仅显示一次</strong><textarea readOnly value={issuedCodes.join('\n')} aria-label="本次签发的平台注册准入码" /><button type="button" className="quiet-button" onClick={() => setIssuedCodes([])}>清除准入码</button></section> : null}</AdminActionPanel>
}

const retailPlanCodes = ['mediaclaw-cny-1', 'mediaclaw-cny-5', 'mediaclaw-cny-20', 'mediaclaw-cny-50', 'mediaclaw-cny-100', 'mediaclaw-cny-500'] as const
type BillingAction = 'grant' | 'mapping' | 'batch'

function AdminBillingActions({ onComplete }: { onComplete: () => void }) {
  const { session } = useMediaWeb()
  const [mode, setMode] = useState<BillingAction>('grant')
  const [targetTenantId, setTargetTenantId] = useState('')
  const [amount, setAmount] = useState('')
  const [planCode, setPlanCode] = useState<(typeof retailPlanCodes)[number]>('mediaclaw-cny-1')
  const [externalProductId, setExternalProductId] = useState('')
  const [purchaseUrl, setPurchaseUrl] = useState('')
  const [count, setCount] = useState('1000')
  const [reason, setReason] = useState('')
  const action = useAdminAction(onComplete)
  const ready = !!session && ({
    grant: canonicalUuid(targetTenantId) && positiveMoney(amount) && !!reason.trim(),
    mapping: !!externalProductId.trim() && liandongPurchaseUrl(purchaseUrl) && !!reason.trim(),
    batch: positiveId(count) && Number(count) <= 1000,
  })[mode]
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!session || !ready) return
    const spec = {
      grant: ['/admin/billing/grants', { targetTenantId, amount, reason: reason.trim() }],
      mapping: ['/admin/billing/product-mappings', { planCode, externalProductId: externalProductId.trim(), purchaseUrl, reason: reason.trim() }],
      batch: ['/admin/billing/redemption-batches', { planCode, count: Number(count) }],
    } as const
    const [path, payload] = spec[mode]
    const result = await action.run(mutationFingerprint(path, 'POST', payload), (idempotencyKey) => adminMutate(session, path, 'POST', payload, idempotencyKey))
    if (result && mode !== 'batch') setReason('')
  }
  return <AdminActionPanel title="零售计费操作" state={action.state}><form onSubmit={(event) => void submit(event)}><div className="segmented-control" role="tablist" aria-label="零售计费操作"><button type="button" className={mode === 'grant' ? 'active' : ''} onClick={() => setMode('grant')}>管理员赠款</button><button type="button" className={mode === 'mapping' ? 'active' : ''} onClick={() => setMode('mapping')}>商品映射</button><button type="button" className={mode === 'batch' ? 'active' : ''} onClick={() => setMode('batch')}>生成卡密</button></div><AdminFields>
    {mode === 'grant' ? <><TextAdminField label="目标租户编号" value={targetTenantId} onChange={setTargetTenantId} /><TextAdminField label="赠款额度" type="number" value={amount} onChange={setAmount} /><ReasonField value={reason} onChange={setReason} /></> : <><Field label="套餐"><select value={planCode} onChange={(event) => setPlanCode(event.target.value as (typeof retailPlanCodes)[number])}>{retailPlanCodes.map((code) => <option key={code} value={code}>{code}</option>)}</select></Field>{mode === 'mapping' ? <><TextAdminField label="链动商品编号" value={externalProductId} onChange={setExternalProductId} /><TextAdminField label="链动购买链接" value={purchaseUrl} onChange={setPurchaseUrl} /><ReasonField value={reason} onChange={setReason} /></> : <TextAdminField label="卡密数量" type="number" value={count} onChange={setCount} />}</>}
  </AdminFields><button className="primary-button" disabled={!ready || action.busy}>{mode === 'batch' ? '生成受保护批次' : '提交操作'}</button></form></AdminActionPanel>
}

type BillingReadView = keyof Pick<AdminBillingSummary, 'plans' | 'mappings' | 'batches' | 'fulfillments' | 'grants'>
const billingReadViews: Array<{ key: BillingReadView; label: string }> = [
  { key: 'plans', label: '套餐' }, { key: 'mappings', label: '商品映射' }, { key: 'batches', label: '卡密批次' },
  { key: 'fulfillments', label: '兑换记录' }, { key: 'grants', label: '管理员赠款' },
]

function AdminBillingReadModel({ refresh }: { refresh: number }) {
  const [view, setView] = useState<BillingReadView>('plans')
  const state = useLoad(() => loadAdminBillingSummary(), [refresh])
  return <section className="admin-read-model"><div className="segmented-control" role="tablist" aria-label="零售计费数据">{billingReadViews.map((item) => <button type="button" key={item.key} className={view === item.key ? 'active' : ''} onClick={() => setView(item.key)}>{item.label}</button>)}</div>{state.status === 'ready' ? <RecordTable value={state.data[view]} /> : <PageState state={state} />}</section>
}

function AdminUpstreamReadModel({ refresh }: { refresh: number }) {
  const state = useLoad(() => loadAdminUpstreamSummary(), [refresh])
  if (state.status !== 'ready') return <PageState state={state} />
  return <div className="overview-grid upstream-operations"><section className="section-panel"><h2>Sub2API 上游状态</h2><FactList value={state.data.credential} /></section><section className="section-panel"><h2>待对账调用</h2><RecordTable value={state.data.reconciliation} /></section></div>
}

function AdminTenantResources() {
  const [target, setTarget] = useState('')
  const [submittedTarget, setSubmittedTarget] = useState('')
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [cursorTrail, setCursorTrail] = useState<string[]>([])
  const cursor = cursorTrail.at(-1)
  const path = submittedTarget ? `/admin/runs?targetTenantId=${encodeURIComponent(submittedTarget)}&pageSize=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}${submittedQuery ? `&search=${encodeURIComponent(submittedQuery)}` : ''}` : ''
  const state = useLoad(() => path ? adminGet<AdminRunSummaryPage>(path) : Promise.resolve<AdminRunSummaryPage | null>(null), [path])
  return <section className="admin-read-model"><form className="track-filter-bar" onSubmit={(event) => { event.preventDefault(); if (!canonicalUuid(target)) return; setCursorTrail([]); setSubmittedTarget(target); setSubmittedQuery(query.trim()) }}><label className="search-field"><input inputMode="text" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="目标租户编号" /></label><label className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索运行" /></label><button className="quiet-button" type="submit" disabled={!canonicalUuid(target)}>读取资源</button></form>{!submittedTarget ? <EmptyState title="输入目标租户后读取资源" /> : state.status !== 'ready' ? <PageState state={state} /> : state.data ? <><RunTable items={state.data.items} detailLinks={false} /><CursorPagination page={cursorTrail.length + 1} canPrevious={cursorTrail.length > 0} canNext={!!state.data.nextCursor} onPrevious={() => setCursorTrail((current) => current.slice(0, -1))} onNext={() => state.data?.nextCursor && setCursorTrail((current) => [...current, state.data!.nextCursor!])} /></> : null}</section>
}

function RunTable({ items, detailLinks = true }: { items: AdminRunSummary[]; detailLinks?: boolean }) {
  if (!items.length) return <EmptyState title="还没有创作运行" />
  return <div className="table-scroll"><table className="data-table run-data-table"><thead><tr><th>运行</th><th>状态</th><th>入口</th><th>更新时间</th>{detailLinks ? <th>操作</th> : null}</tr></thead><tbody>{items.map((run) => <tr key={run.publicRunId}><th>{run.title || '未命名运行'}</th><td><StatusBadge tone={runStatusTone(run.status || '')}>{runStatusLabel(run.status || '')}</StatusBadge></td><td>{run.entrypoint || '未注明'}</td><td>{formatDate(run.updatedAt)}</td>{detailLinks ? <td><Link to={`/runs/${run.publicRunId}`}>查看详情</Link></td> : null}</tr>)}</tbody></table></div>
}

function AdminActionPanel({ title, state, children }: { title: string; state: ActionState; children: ReactNode }) { return <section className="section-panel admin-action-panel"><div className="admin-action-heading"><h2>{title}</h2>{state.message ? <span className={`action-message is-${state.kind}`} role="status">{state.message}</span> : null}</div>{children}</section> }
function AdminFields({ children }: { children: ReactNode }) { return <div className="admin-fields">{children}</div> }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="admin-field"><span>{label}</span>{children}</label> }
function TextAdminField({ label, value = '', onChange, type = 'text' }: { label: string; value?: string; onChange: (value: string) => void; type?: string }) { return <Field label={label}><input type={type} value={value} onChange={(event) => onChange(event.target.value)} /></Field> }
function ReasonField({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <TextAdminField label="审计原因" value={value} onChange={onChange} /> }

function PageState({ state }: { state: LoadState<unknown> }) {
  return state.status === 'loading' ? <div className="detail-loading" aria-busy="true"><span>正在读取</span></div> : state.status === 'error' ? <EmptyState title={state.message} /> : null
}
function EmptyState({ title }: { title: string }) { return <div className="detail-empty"><AlertCircle size={20} /><strong>{title}</strong></div> }

function PageHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) { return <header className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{action ? <div className="page-heading-actions">{action}</div> : null}</header> }
function StatusBadge({ tone, children }: { tone: string; children: ReactNode }) { return <span className={`status-badge is-${tone}`}>{children}</span> }
function RecordTable({ value }: { value: unknown }) {
  const rows = normalizeRows(value); if (!rows.length) return <EmptyState title="暂无记录" />
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].slice(0, 8)
  return <div className="table-scroll"><table className="data-table"><thead><tr>{columns.map((column) => <th key={column}>{humanize(column)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div>
}
function CursorPagination({ page, canPrevious, canNext, onPrevious, onNext }: { page: number; canPrevious: boolean; canNext: boolean; onPrevious: () => void; onNext: () => void }) { return <nav className="pagination" aria-label="分页"><button type="button" disabled={!canPrevious} onClick={onPrevious}><ChevronLeft size={15} />上一页</button><span>第 {page} 页</span><button type="button" disabled={!canNext} onClick={onNext}>下一页<ChevronRight size={15} /></button></nav> }
function NumberPagination({ page, value, onPage }: { page: number; value: unknown; onPage: (page: number) => void }) { const rows = normalizeRows(value); const total = paginationTotal(value); const pageSize = paginationPageSize(value) ?? 30; const canNext = total === null ? rows.length >= pageSize : page * pageSize < total; return <CursorPagination page={page} canPrevious={page > 1} canNext={canNext} onPrevious={() => onPage(Math.max(1, page - 1))} onNext={() => onPage(page + 1)} /> }
function FactList({ value }: { value: Record<string, unknown> }) { return <dl className="run-fact-list">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{humanize(key)}</dt><dd>{displayValue(item)}</dd></div>)}</dl> }
function normalizeRows(value: unknown): Record<string, unknown>[] { if (Array.isArray(value)) return value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object'); if (value && typeof value === 'object') { const object = value as Record<string, unknown>; for (const key of ['items', 'data', 'records']) if (Array.isArray(object[key])) return normalizeRows(object[key]); return [object] } return [] }
function paginationTotal(value: unknown): number | null { if (!value || typeof value !== 'object' || Array.isArray(value)) return null; const object = value as Record<string, unknown>; for (const key of ['total', 'total_count', 'totalCount']) if (typeof object[key] === 'number') return object[key]; const pagination = object.pagination; if (pagination && typeof pagination === 'object') { const total = (pagination as Record<string, unknown>).total; if (typeof total === 'number') return total } return null }
function paginationPageSize(value: unknown): number | null { if (!value || typeof value !== 'object' || Array.isArray(value)) return null; const object = value as Record<string, unknown>; for (const key of ['page_size', 'pageSize', 'limit']) if (typeof object[key] === 'number') return object[key]; const pagination = object.pagination; if (pagination && typeof pagination === 'object') { const pageSize = (pagination as Record<string, unknown>).page_size; if (typeof pageSize === 'number') return pageSize } return null }
function displayValue(value: unknown): string { if (value === null || value === undefined || value === '') return '—'; if (typeof value === 'object') return Array.isArray(value) ? `${value.length} 项` : `${Object.keys(value).length} 项`; return String(value) }
function humanize(value: string): string { return value.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ') }
function formatDate(value?: string): string { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
