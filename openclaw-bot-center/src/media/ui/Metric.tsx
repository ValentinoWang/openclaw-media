import type { ReactNode } from 'react'

// FE-14 canonical metric-card component. The prior 7 copies split into two
// DOM families that differ in which tag carries the label vs. the detail
// text (studio's `<article>` cards use <small>=label/<p>=detail; the
// ordinary/admin `<div>` panels use <span>=label/<small>=detail) — each
// page's module.css targets those specific tags, so this keeps both
// families as an explicit `variant` instead of picking one DOM shape and
// silently reflowing the other pages' CSS selectors. Callers keep owning
// their own class names (including any modifier like "muted"/"emphasized")
// via `className`, exactly as the page-local copies did.
export type MetricVariant = 'card' | 'panel'

export interface MetricProps {
  label: string
  value: ReactNode
  detail?: ReactNode
  icon?: ReactNode
  iconClassName?: string
  tone?: string
  className: string
  variant?: MetricVariant
}

export function Metric({ label, value, detail, icon, iconClassName, tone, className, variant = 'panel' }: MetricProps) {
  const displayValue = value === undefined || value === null ? '—' : value
  if (variant === 'card') {
    return (
      <article className={className} data-tone={tone}>
        {icon !== undefined ? <span>{icon}</span> : null}
        <div>
          <small>{label}</small>
          <strong>{displayValue}</strong>
          {detail !== undefined ? <p>{detail}</p> : null}
        </div>
      </article>
    )
  }
  return (
    <div className={className}>
      {icon !== undefined ? <span className={iconClassName}>{icon}</span> : null}
      <span>{label}</span>
      <strong>{displayValue}</strong>
      {detail !== undefined ? <small>{detail}</small> : null}
    </div>
  )
}
