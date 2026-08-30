// Canonical zh-CN date/time formatting (cluster FE-02).
//
// Before this module existed, ~15 files each hand-rolled their own
// formatDate/formatTime/formatDateTime with independently-invented fallback
// text for the empty and NaN cases. Those fallback texts genuinely differ
// per page (see the divergences captured in the dedup audit for FE-02) and
// are treated here as callers' business, not something this module should
// silently unify — every formatter takes an explicit `DateTextOptions` so a
// caller can reproduce its exact previous wording instead of a merge forcing
// one wording onto every page.

export interface DateTextOptions {
  /** Text shown when the value is null/undefined/empty. Default: "暂无". */
  empty?: string
  /**
   * Text shown when the value fails to parse as a date. Default: "时间不可读".
   * Pass ECHO_INVALID to fall back to the original raw string instead (the
   * behavior several pages relied on before this module existed).
   */
  invalid?: string
}

/** Sentinel for DateTextOptions.empty/invalid: echo the original raw value back instead of a fixed string. */
export const ECHO_INVALID = "__openclaw_echo_original_value__"

function resolveFallback(raw: string, fallback: string): string {
  return fallback === ECHO_INVALID ? raw : fallback
}

function resolveEmpty(raw: string | null | undefined, opts: DateTextOptions): string {
  return resolveFallback(raw ?? "", opts.empty ?? "暂无")
}

function resolveInvalid(raw: string, opts: DateTextOptions): string {
  return resolveFallback(raw, opts.invalid ?? "时间不可读")
}

/** Full date + time, e.g. 2026/8/30 09:41:12 (toLocaleString, hour12:false, includes seconds). */
export function formatDateTime(value: string | null | undefined, opts: DateTextOptions = {}): string {
  if (!value) return resolveEmpty(value, opts)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return resolveInvalid(value, opts)
  return date.toLocaleString("zh-CN", { hour12: false })
}

/** Date only, e.g. 2026/8/30 (toLocaleDateString). */
export function formatDateOnly(value: string | null | undefined, opts: DateTextOptions = {}): string {
  if (!value) return resolveEmpty(value, opts)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return resolveInvalid(value, opts)
  return date.toLocaleDateString("zh-CN")
}

/** Date + time without seconds, e.g. 2026/08/30 09:41 (used by admin pages that show year/month/day/hour/minute). */
export function formatDateTimeMinutes(value: string | null | undefined, opts: DateTextOptions = {}): string {
  if (!value) return resolveEmpty(value, opts)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return resolveInvalid(value, opts)
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

/** Short "月-日 时:分" grain, e.g. 08-30 09:41 (AdminOverviewPage). */
export function formatShortDateTime(value: string | null | undefined, opts: DateTextOptions = {}): string {
  if (!value) return resolveEmpty(value, opts)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return resolveInvalid(value, opts)
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date)
}

/** Intl dateStyle:medium timeStyle:short grain, e.g. 2026年8月30日 09:41 (CreationRunDetailPage). */
export function formatMediumDateTime(value: string | null | undefined, opts: DateTextOptions = {}): string {
  if (!value) return resolveEmpty(value, opts)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return resolveInvalid(value, opts)
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date)
}

/**
 * Dual-grain timestamp used by AdminUpstreamsPage's credential sync display: `full=false` gives a short
 * "月-日 时:分" grain, `full=true` gives a complete date+time with seconds. Both the empty and invalid
 * cases collapse to the same fallback text per grain (this page never distinguished "missing" from
 * "unparseable" — preserved as-is rather than invented).
 */
export function formatTimestampFull(value: string | null | undefined, full = false): string {
  const fallback = full ? "暂无同步记录" : "暂无"
  if (!value) return fallback
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return fallback
  return new Intl.DateTimeFormat(
    "zh-CN",
    full
      ? { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }
      : { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false },
  ).format(date)
}

/**
 * Bare-date key formatter, e.g. "2026-08-30" -> "08-30". Appends T00:00:00 before parsing so a
 * date-only string is read in local time rather than UTC (UsageBillingPage's fix for cross-timezone
 * date drift — preserve this when reusing the formatter, do not parse `value` directly).
 */
export function formatDateKey(value: string, opts: DateTextOptions = {}): string {
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return resolveInvalid(value, opts)
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })
}
