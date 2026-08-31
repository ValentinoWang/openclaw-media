import { useEffect, useState, type ReactNode } from 'react'
import {
  CalendarDays, Check, ChevronLeft, ChevronRight, CircleAlert, Copy, Link2,
  RefreshCcw, ShieldCheck, UserRound, UsersRound,
} from 'lucide-react'
import {
  callBusinessOperation,
} from '../../generatedBusinessPagesContract'
import { isForbiddenError } from '../../businessErrorPresentation'
import { copyText } from '../../../lib/clipboard'
import { inviteStatusDisplayLabel } from '../../ui/ordinaryDataLabels'
import { ECHO_INVALID, formatDateOnly, formatDateTime as sharedFormatDateTime } from '../../ui/datetime'
import { Metric } from '../../ui/Metric'
import { SurfaceState } from '../../ui/SurfaceState'
import styles from './InvitesPage.module.css'

type AffiliateProfileResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  profile: {
    affiliateCode: string
    enabled: boolean
    quota: number
    used: number
    expiresAt: string | null
    revision: number
  }
}

type Invitee = {
  publicUserId: string
  displayName: string
  status: string
  joinedAt: string
}

type InviteeListResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  items: Invitee[]
  nextCursor: string | null
}

type ResourceState<T> =
  | { status: 'loading' }
  | { status: 'forbidden' }
  | { status: 'error' }
  | { status: 'ready'; data: T }

type PageStatus = 'loading' | 'forbidden' | 'error' | 'partial' | 'ready'
type CopyState = 'idle' | 'copied' | 'error'

const INVITEE_PAGE_SIZE = 30

function toResourceError<T>(error: unknown): ResourceState<T> {
  if (isForbiddenError(error)) {
    return {
      status: 'forbidden',
    }
  }
  return { status: 'error' }
}

function useAffiliateProfile(refreshToken: number): ResourceState<AffiliateProfileResponse> {
  const [state, setState] = useState<ResourceState<AffiliateProfileResponse>>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<AffiliateProfileResponse>('getAffiliateProfile', {
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState(toResourceError(error))
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [refreshToken])

  return state
}

function useInvitees(cursor: string | undefined, refreshToken: number): ResourceState<InviteeListResponse> {
  const [state, setState] = useState<ResourceState<InviteeListResponse>>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<InviteeListResponse>('listInvitees', {
      query: {
        cursor,
        pageSize: INVITEE_PAGE_SIZE,
      },
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState(toResourceError(error))
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [cursor, refreshToken])

  return state
}

function pageStatus(summary: ResourceState<unknown>, invitees: ResourceState<unknown>): PageStatus {
  const statuses = [summary.status, invitees.status]
  if (statuses.every((status) => status === 'ready')) return 'ready'
  if (statuses.some((status) => status === 'ready')) return 'partial'
  if (statuses.every((status) => status === 'loading')) return 'loading'
  if (statuses.every((status) => status === 'forbidden')) return 'forbidden'
  if (statuses.every((status) => status === 'error')) return 'error'
  if (statuses.includes('error')) return 'error'
  if (statuses.includes('forbidden')) return 'forbidden'
  return 'loading'
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
}

function formatDate(value: string | null): string {
  return formatDateOnly(value, { empty: '未设置', invalid: ECHO_INVALID })
}

function formatDateTime(value: string): string {
  return sharedFormatDateTime(value, { empty: ECHO_INVALID, invalid: ECHO_INVALID })
}

function ResourceStateView({
  state,
  subject,
  onRetry,
}: {
  state: ResourceState<unknown>
  subject: string
  onRetry: () => void
}) {
  if (state.status === 'loading') {
    return (
      <div className={styles.panelState} data-component="mg-state" data-resource-state="loading" aria-busy="true">
        <SurfaceState
          kind="loading"
          title={'正在读取' + subject}
          detail="等待服务端返回当前租户数据。"
          density="compact"
        />
      </div>
    )
  }

  const forbidden = state.status === 'forbidden'
  const message = forbidden
    ? '当前账户没有权限查看' + subject + '。'
    : subject + '暂时无法读取。请点击“重新读取”重试。'
  return (
    <div
      className={styles.panelState}
      data-component="mg-state"
      data-resource-state={forbidden ? 'forbidden' : 'error'}
      role="alert"
    >
      <SurfaceState
        kind={forbidden ? 'forbidden' : 'error'}
        title={forbidden ? '暂无查看权限' : '邀请数据读取失败'}
        detail={message}
        density="compact"
        action={!forbidden ? (
          <button className={'mg-btn mg-btn-ghost ' + styles.retryButton} type="button" onClick={onRetry}>
            <RefreshCcw size={15} aria-hidden="true" />
            重新读取
          </button>
        ) : undefined}
      />
    </div>
  )
}

function FactCard({
  icon,
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  icon: ReactNode
  label: string
  value: string
  detail: string
  tone?: 'neutral' | 'success' | 'warning'
}) {
  return <Metric
    variant="card"
    className={'mg-metric ' + styles.factCard}
    icon={icon}
    label={label}
    value={value}
    detail={detail}
    tone={tone}
  />
}

function SummaryFacts({ profile }: { profile: AffiliateProfileResponse['profile'] }) {
  return (
    <section className={'mg-metric-grid ' + styles.summaryGrid} data-component="mg-metric-grid" aria-label="邀请摘要">
      <FactCard
        icon={<Link2 size={21} aria-hidden="true" />}
        label="邀请权限"
        value={profile.enabled ? '已开启' : '未开启'}
        detail={profile.enabled ? '当前邀请码可以使用' : '当前邀请码不可使用'}
        tone={profile.enabled ? 'success' : 'warning'}
      />
      <FactCard
        icon={<UserRound size={21} aria-hidden="true" />}
        label="剩余名额"
        value={formatNumber(profile.quota - profile.used)}
        detail={'总名额 ' + formatNumber(profile.quota)}
      />
      <FactCard
        icon={<UsersRound size={21} aria-hidden="true" />}
        label="已使用名额"
        value={formatNumber(profile.used)}
        detail="邀请额度已使用数量"
      />
      <FactCard
        icon={<CalendarDays size={21} aria-hidden="true" />}
        label="有效期"
        value={formatDate(profile.expiresAt)}
        detail="以服务端邀请档案为准"
        tone="warning"
      />
    </section>
  )
}

function InviteeTable({ items }: { items: Invitee[] }) {
  return (
    <div className={styles.tableArea}>
      <div className={styles.tableViewport} role="region" aria-label="邀请记录表格" tabIndex={0}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">受邀用户</th>
              <th scope="col">状态</th>
              <th scope="col">加入时间</th>
              <th scope="col">公开用户编号</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.publicUserId}>
                <th scope="row">
                  <div className={styles.userCell}>
                    <span className={styles.avatar} aria-hidden="true">{Array.from(item.displayName)[0]}</span>
                    <span className={styles.userText}>
                      <strong>{item.displayName}</strong>
                    </span>
                  </div>
                </th>
                <td>
                  <span className={'mg-badge ' + styles.statusPill} data-component="mg-badge" data-tone={inviteStatusTone(item.status)}>
                    {inviteStatusDisplayLabel(item.status)}
                  </span>
                </td>
                <td>{formatDateTime(item.joinedAt)}</td>
                <td><code className={styles.publicId} title={item.publicUserId}>{item.publicUserId}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function InvitePagination({
  page,
  rowCount,
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
}: {
  page: number
  rowCount: number
  hasPrevious: boolean
  hasNext: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  return (
    <nav className={styles.pagination} aria-label="邀请记录分页">
      <span>当前页 {rowCount} 条</span>
      <div className={styles.paginationControls}>
        <button className="mg-btn mg-btn-ghost" data-component="mg-btn" type="button" aria-label="上一页" disabled={!hasPrevious} onClick={onPrevious}>
          <ChevronLeft size={17} aria-hidden="true" />
        </button>
        <strong>第 {page} 页</strong>
        <button className="mg-btn mg-btn-ghost" data-component="mg-btn" type="button" aria-label="下一页" disabled={!hasNext} onClick={onNext}>
          <ChevronRight size={17} aria-hidden="true" />
        </button>
      </div>
    </nav>
  )
}

function InvitesPage() {
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [cursorHistory, setCursorHistory] = useState<Array<string | undefined>>([])
  const [refreshToken, setRefreshToken] = useState(0)
  const [copyState, setCopyState] = useState<CopyState>('idle')
  const summary = useAffiliateProfile(refreshToken)
  const invitees = useInvitees(cursor, refreshToken)
  const currentPage = cursorHistory.length + 1
  const rootState = pageStatus(summary, invitees)
  const unavailableResources = [
    { label: '邀请档案', state: summary },
    { label: '邀请记录', state: invitees },
  ].filter((resource) => resource.state.status === 'forbidden' || resource.state.status === 'error')

  function retry() {
    setCopyState('idle')
    setCursor(undefined)
    setCursorHistory([])
    setRefreshToken((value) => value + 1)
  }

  function previousPage() {
    if (!cursorHistory.length) return
    const previousCursor = cursorHistory[cursorHistory.length - 1]
    setCursorHistory(cursorHistory.slice(0, -1))
    setCursor(previousCursor)
  }

  function nextPage(nextCursor: string | null) {
    if (!nextCursor) return
    setCursorHistory([...cursorHistory, cursor])
    setCursor(nextCursor)
  }

  async function copyAffiliateCode(code: string) {
    try {
      await copyText(code)
      setCopyState('copied')
    } catch {
      setCopyState('error')
    }
  }

  return (
    <main className={'fidelity-page ' + styles.page} data-page-ownership="personal" data-accent="campaign" data-page-state={rootState}>
      <div data-page-prelude>
        <header className={'page-heading mg-hero ' + styles.pageHeading} data-component="mg-hero">
          <div>
            <span className="mg-eyebrow" data-component="mg-eyebrow">成员访问</span>
            <h1>邀请中心</h1>
            <p>查看当前账户的邀请码、额度、到期和被邀请用户。</p>
          </div>
        </header>
        {rootState === 'partial' ? (
          <div className={styles.partialNotice} role="alert" data-page-partial>
            <CircleAlert size={15} aria-hidden="true" />
            <div>
              <strong>以下邀请数据暂时无法读取</strong>
              <ul>{unavailableResources.map((resource) => <li key={resource.label}>{resource.state.status === 'forbidden' ? '当前账户没有权限查看' + resource.label + '。' : resource.label + '暂时无法读取。请点击“重新读取”重试。'}</li>)}</ul>
              <span>已成功返回的邀请数据仍保留在当前页面。</span>
            </div>
            <button className={'mg-btn mg-btn-ghost ' + styles.retryButton} data-component="mg-btn" type="button" onClick={retry}>重新读取</button>
          </div>
        ) : null}
        {summary.status === 'ready' ? (
          <SummaryFacts profile={summary.data.profile} />
        ) : (
          <section className={'mg-panel ' + styles.summaryState} data-component="mg-panel" aria-label="邀请摘要">
            <ResourceStateView state={summary} subject="邀请档案" onRetry={retry} />
          </section>
        )}
      </div>

      <div className={styles.bodyGrid} data-page-layout="persistent-rail">
        <div className={styles.mainColumn} data-page-primary data-primary-flow role="region" aria-label="邀请记录列表" tabIndex={0}>
          <section className={'mg-panel ' + styles.recordsPanel} data-component="mg-panel" aria-labelledby="invite-records-title" data-page-terminal-surface="primary">
            <header className={'mg-panel-head ' + styles.panelHeader} data-component="mg-panel-head">
              <div>
                <h2 id="invite-records-title">邀请记录</h2>
                <p>当前用户的直接邀请关系。</p>
              </div>
              {invitees.status === 'ready' ? <span className={styles.recordCount}>{invitees.data.items.length} 条</span> : null}
            </header>
            {invitees.status !== 'ready' ? (
              <ResourceStateView state={invitees} subject="邀请记录" onRetry={retry} />
            ) : invitees.data.items.length ? (
              <>
                <InviteeTable items={invitees.data.items} />
                <InvitePagination
                  page={currentPage}
                  rowCount={invitees.data.items.length}
                  hasPrevious={cursorHistory.length > 0}
                  hasNext={invitees.data.nextCursor !== null}
                  onPrevious={previousPage}
                  onNext={() => nextPage(invitees.data.nextCursor)}
                />
              </>
            ) : (
              <div className={styles.emptyState} data-component="mg-state" data-resource-state="empty">
                <SurfaceState kind="empty" title="当前还没有被邀请用户" detail="服务端尚未返回可展示的邀请记录。" density="compact" />
              </div>
            )}
          </section>
        </div>

        <aside className={styles.rail} aria-label="邀请详情" data-page-inspector>
          <section className={'mg-panel ' + styles.inspectorPanel} data-component="mg-panel" aria-labelledby="current-invite-title">
            <header className={'mg-panel-head ' + styles.panelHeader} data-component="mg-panel-head">
              <div>
                <h2 id="current-invite-title">当前邀请码</h2>
                <p>邀请码与邀请档案由服务端返回。</p>
              </div>
            </header>
            {summary.status !== 'ready' ? (
              <ResourceStateView state={summary} subject="邀请档案" onRetry={retry} />
            ) : (
              <div className={styles.inspectorBody} role="region" aria-label="当前邀请码详情" tabIndex={0}>
                <span className={styles.fieldLabel}>邀请码</span>
                <div className={styles.linkValue}>
                  <code>{summary.data.profile.affiliateCode}</code>
                  <button
                    className={'mg-btn mg-btn-ghost ' + styles.iconAction}
                    data-component="mg-btn"
                    type="button"
                    aria-label="复制邀请码"
                    title="复制邀请码"
                    onClick={() => void copyAffiliateCode(summary.data.profile.affiliateCode)}
                  >
                    {copyState === 'copied' ? <Check size={17} aria-hidden="true" /> : <Copy size={17} aria-hidden="true" />}
                  </button>
                </div>
                {copyState !== 'idle' ? (
                  <p className={styles.actionMessage + ' ' + (copyState === 'copied' ? styles.actionSuccess : styles.actionError)} role="status">
                    {copyState === 'copied' ? '已复制到剪贴板' : '复制未完成，请手动选择邀请码。'}
                  </p>
                ) : null}
                <dl className={styles.detailList}>
                  <div>
                    <dt>有效期</dt>
                    <dd className={summary.data.profile.expiresAt ? styles.successValue : styles.mutedValue}>{formatDate(summary.data.profile.expiresAt)}</dd>
                  </div>
                  <div>
                    <dt>当前状态</dt>
                    <dd>{summary.data.profile.enabled ? '已开启' : '未开启'}</dd>
                  </div>
                  <div>
                    <dt>名额使用</dt>
                    <dd>{formatNumber(summary.data.profile.used) + ' / ' + formatNumber(summary.data.profile.quota)}</dd>
                  </div>
                </dl>
                <p className={styles.apiNote}><ShieldCheck size={14} aria-hidden="true" />邀请码只从当前用户的服务端邀请档案读取。</p>
              </div>
            )}
          </section>

          <section className={'mg-panel ' + styles.rulesPanel} data-component="mg-panel" aria-labelledby="invite-notes-title" data-page-terminal-surface="inspector">
            <h2 id="invite-notes-title">说明</h2>
            <ul>
              <li>邀请凭证可分享至社交平台、邮件或私信。</li>
              <li>达到名额上限后，凭证将无法继续用于注册。</li>
              <li>受邀用户的状态与加入时间以服务端记录为准。</li>
            </ul>
          </section>
        </aside>
      </div>
    </main>
  )
}

function inviteStatusTone(status: string): 'good' | 'warn' | 'info' | undefined {
  if (status === 'accepted') return 'good'
  if (status === 'pending') return 'warn'
  if (status === 'expired' || status === 'revoked') return 'info'
  return undefined
}

export default InvitesPage
