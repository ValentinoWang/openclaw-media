import { useEffect, useState, type ReactNode } from 'react'
import { AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react'
import { secureUuid } from '../secureUuid'

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
export function PageHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) { return <header className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{action ? <div className="page-heading-actions">{action}</div> : null}</header> }
export function EmptyState({ title }: { title: string }) { return <div className="detail-empty"><AlertCircle size={20} /><strong>{title}</strong></div> }

// FE-06 canonical cursor pagination: default props reproduce the exact prior
// markup/behavior for existing callers (label="分页", always rendered, text
// density) so migrating a caller onto this component with no extra props is
// a no-op. `density="icon"` and `hideWhenSingle` are opt-in for callers that
// need those distinct behaviors (see dedup audit FE-06 divergences).
export function CursorPagination({
  page, canPrevious, canNext, onPrevious, onNext, label = '分页', hideWhenSingle = false, density = 'text',
}: {
  page: number
  canPrevious: boolean
  canNext: boolean
  onPrevious: () => void
  onNext: () => void
  label?: string
  hideWhenSingle?: boolean
  density?: 'text' | 'icon'
}) {
  if (hideWhenSingle && !canPrevious && !canNext) return null
  if (density === 'icon') {
    return <nav className="pagination" aria-label={label}>
      <button type="button" aria-label="上一页" title="上一页" disabled={!canPrevious} onClick={onPrevious}><ChevronLeft size={15} /></button>
      <span>第 {page} 页</span>
      <button type="button" aria-label="下一页" title="下一页" disabled={!canNext} onClick={onNext}><ChevronRight size={15} /></button>
    </nav>
  }
  return <nav className="pagination" aria-label={label}>
    <button type="button" disabled={!canPrevious} onClick={onPrevious}><ChevronLeft size={15} />上一页</button>
    <span>第 {page} 页</span>
    <button type="button" disabled={!canNext} onClick={onNext}>下一页<ChevronRight size={15} /></button>
  </nav>
}

// FE-06 canonical cursor-stack state machine: `[]` initial state, page =
// trail.length + 1 (the majority semantics among the prior 4 hand-rolled
// copies — see dedup audit FE-06 for the one outlier that used a different,
// off-by-one convention and was left as-is rather than silently reflowed).
export function useCursorTrail() {
  const [trail, setTrail] = useState<string[]>([])
  return {
    cursor: trail.at(-1),
    page: trail.length + 1,
    canPrevious: trail.length > 0,
    next: (nextCursor: string) => setTrail((current) => [...current, nextCursor]),
    previous: () => setTrail((current) => current.slice(0, -1)),
    reset: () => setTrail([]),
  }
}

export function displayValue(value: unknown): string { if (value === null || value === undefined || value === '') return '—'; if (typeof value === 'object') return Array.isArray(value) ? `${value.length} 项` : `${Object.keys(value).length} 项`; return String(value) }
export function displayNumber(value: unknown): string { return typeof value === 'number' ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value) : displayValue(value) }
export function humanize(value: string): string { return value.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ') }
export function formatDate(value?: string): string { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
