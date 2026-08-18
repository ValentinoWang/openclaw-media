import { useEffect, useState, type ReactNode } from 'react'
import { AlertCircle, ChevronLeft, ChevronRight, FileCheck2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import { loadMediaJobs, type AssetSummary, type LocalAgentJob, type TenantDashboard } from '../mediaWebApi'
import { runStatusLabel, runStatusTone } from '../statusPresentation'
import { secureUuid } from '../secureUuid'

export function RunProjectionPage({ title, description, emptyTitle }: { title: string; description: string; emptyTitle: string }) {
  const { session } = useMediaWeb()
  const state = useLoad(() => session ? loadMediaJobs(session, { limit: 30 }) : Promise.resolve({ jobs: [], next_cursor: null }), [session])
  return <main className="fidelity-page"><PageHeading title={title} description={description} />
    {state.status !== 'ready' ? <PageState state={state} /> : state.data.jobs.length ? <RunTable items={state.data.jobs} /> : <EmptyState title={emptyTitle} />}
  </main>
}

export function WorkflowBoundary({ title, detail, to }: { title: string; detail: string; to?: string }) {
  return <aside className="section-panel workflow-boundary"><FileCheck2 size={19} /><div><h2>{title}</h2><p>{detail}</p>{to ? <Link to={to}>打开 Media Agent</Link> : null}</div></aside>
}

export function RunTable({ items, detailLinks = true }: { items: LocalAgentJob[]; detailLinks?: boolean }) {
  if (!items.length) return <EmptyState title="还没有创作运行" />
  return <div className="table-scroll"><table className="data-table run-data-table"><thead><tr><th>运行</th><th>状态</th><th>Pipeline</th><th>更新时间</th>{detailLinks ? <th>操作</th> : null}</tr></thead><tbody>{items.map((job) => <tr key={job.job_id}><th>{job.job_id}</th><td><StatusBadge tone={runStatusTone(job.state)}>{runStatusLabel(job.state)}</StatusBadge></td><td>{job.pipeline_id}</td><td>{formatDate(job.updated_at)}</td>{detailLinks ? <td><Link to={`/runs/${encodeURIComponent(job.job_id)}`}>查看详情</Link></td> : null}</tr>)}</tbody></table></div>
}

export function AssetTable({ items, selectedIds, onToggle }: { items: AssetSummary[]; selectedIds: string[]; onToggle: (id: string) => void }) {
  if (!items.length) return <EmptyState title="还没有素材" />
  return <div className="table-scroll"><table className="data-table asset-table"><thead><tr><th><span className="sr-only">选择</span></th><th>素材编号</th><th>创建时间</th></tr></thead><tbody>{items.map((asset) => <tr key={asset.publicAssetId} className={selectedIds.includes(asset.publicAssetId) ? 'focused' : ''}><td><input type="checkbox" aria-label={`选择素材 ${asset.publicAssetId}`} checked={selectedIds.includes(asset.publicAssetId)} onChange={() => onToggle(asset.publicAssetId)} /></td><th>{asset.publicAssetId}</th><td>{formatDate(asset.createdAt)}</td></tr>)}</tbody></table></div>
}

export function newIdempotencyKey(scope: string) { return `${scope}-${secureUuid()}` }

export type LoadState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }
export function useLoad<T>(loader: () => Promise<T>, dependencies: readonly unknown[]): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  useEffect(() => { let active = true; setState({ status: 'loading' }); loader().then((data) => { if (active) setState({ status: 'ready', data }) }).catch((error: unknown) => { if (active) setState({ status: 'error', message: error instanceof Error ? error.message : '读取失败' }) }); return () => { active = false } }, dependencies)
  return state
}

export function PageState({ state }: { state: LoadState<unknown> }) {
  return state.status === 'loading' ? <div className="detail-loading" aria-busy="true"><span>正在读取</span></div> : state.status === 'error' ? <EmptyState title={state.message} /> : null
}
export function SummaryBand({ dashboard, taskCount }: { dashboard: TenantDashboard; taskCount: number }) {
  const entries = Object.entries(dashboard.summary).slice(0, 3)
  return <section className="summary-band"><SummaryMetric label="进行中任务" value={taskCount} detail="网页任务" />{entries.map(([key, value]) => <SummaryMetric key={key} label={humanize(key)} value={displayNumber(value)} detail="当前账户" />)}</section>
}
function SummaryMetric({ label, value, detail }: { label: string; value: ReactNode; detail: string }) { return <div className="summary-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div> }
export function PageHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) { return <header className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{action ? <div className="page-heading-actions">{action}</div> : null}</header> }
function StatusBadge({ tone, children }: { tone: string; children: ReactNode }) { return <span className={`status-badge is-${tone}`}>{children}</span> }
export function EmptyState({ title }: { title: string }) { return <div className="detail-empty"><AlertCircle size={20} /><strong>{title}</strong></div> }
export function RecordTable({ value }: { value: unknown }) {
  const rows = normalizeRows(value); if (!rows.length) return <EmptyState title="暂无记录" />
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].slice(0, 8)
  return <div className="table-scroll"><table className="data-table"><thead><tr>{columns.map((column) => <th key={column}>{humanize(column)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div>
}
export function CursorPagination({ page, canPrevious, canNext, onPrevious, onNext }: { page: number; canPrevious: boolean; canNext: boolean; onPrevious: () => void; onNext: () => void }) { return <nav className="pagination" aria-label="分页"><button type="button" disabled={!canPrevious} onClick={onPrevious}><ChevronLeft size={15} />上一页</button><span>第 {page} 页</span><button type="button" disabled={!canNext} onClick={onNext}>下一页<ChevronRight size={15} /></button></nav> }
export function NumberPagination({ page, value, onPage }: { page: number; value: unknown; onPage: (page: number) => void }) { const rows = normalizeRows(value); const total = paginationTotal(value); const pageSize = paginationPageSize(value) ?? 30; const canNext = total === null ? rows.length >= pageSize : page * pageSize < total; return <CursorPagination page={page} canPrevious={page > 1} canNext={canNext} onPrevious={() => onPage(Math.max(1, page - 1))} onNext={() => onPage(page + 1)} /> }
export function FactList({ value }: { value: Record<string, unknown> }) { return <dl className="run-fact-list">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{humanize(key)}</dt><dd>{displayValue(item)}</dd></div>)}</dl> }
export function normalizeRows(value: unknown): Record<string, unknown>[] { if (Array.isArray(value)) return value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object'); if (value && typeof value === 'object') { const object = value as Record<string, unknown>; for (const key of ['items', 'data', 'records']) if (Array.isArray(object[key])) return normalizeRows(object[key]); return [object] } return [] }
export function paginationTotal(value: unknown): number | null { if (!value || typeof value !== 'object' || Array.isArray(value)) return null; const object = value as Record<string, unknown>; for (const key of ['total', 'total_count', 'totalCount']) if (typeof object[key] === 'number') return object[key]; const pagination = object.pagination; if (pagination && typeof pagination === 'object') { const total = (pagination as Record<string, unknown>).total; if (typeof total === 'number') return total } return null }
export function paginationPageSize(value: unknown): number | null { if (!value || typeof value !== 'object' || Array.isArray(value)) return null; const object = value as Record<string, unknown>; for (const key of ['page_size', 'pageSize', 'limit']) if (typeof object[key] === 'number') return object[key]; const pagination = object.pagination; if (pagination && typeof pagination === 'object') { const pageSize = (pagination as Record<string, unknown>).page_size; if (typeof pageSize === 'number') return pageSize } return null }
export function displayValue(value: unknown): string { if (value === null || value === undefined || value === '') return '—'; if (typeof value === 'object') return Array.isArray(value) ? `${value.length} 项` : `${Object.keys(value).length} 项`; return String(value) }
export function displayNumber(value: unknown): string { return typeof value === 'number' ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value) : displayValue(value) }
export function displayMoney(value: string): string { const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(number) : value }
export function humanize(value: string): string { return value.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ') }
export function formatDate(value?: string): string { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
