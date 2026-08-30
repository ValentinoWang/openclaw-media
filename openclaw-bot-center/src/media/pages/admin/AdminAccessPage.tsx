import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Copy,
  EllipsisVertical,
  KeyRound,
  PencilLine,
  RefreshCw,
  Search,
  ShieldCheck,
  TicketCheck,
  UserRound,
  UsersRound,
  X,
} from 'lucide-react'
import { BusinessOperationError, callBusinessOperation } from '../../generatedBusinessPagesContract'
import { useMediaWeb } from '../../MediaWebWorkspace'
import { mutationFingerprint, useAdminAction, type ActionState } from '../../ui/adminAction'
import { describeBusinessError } from '../../ui/businessOperationError'
import { PlatformIdentity } from '../../ui/PlatformIdentity'
import { platformDisplayLabel } from '../../ui/platformRegistry'
import { Metric } from '../../ui/Metric'
import { SearchBox } from '../../ui/SearchBox'
import { isPublicId } from '../../identifiers'
import { formatDateTime, formatDateTimeMinutes } from '../../ui/datetime'
import styles from './AdminAccessPage.module.css'

type AccessTab = 'invitations' | 'admission' | 'registration'
type StatusTone = 'success' | 'warning' | 'muted' | 'danger'
type RegistrationPolicyMode = 'open' | 'invite_only' | 'closed'
type RuntimeState = 'checking' | 'authenticated' | 'unauthenticated' | 'unavailable'

type ResourceState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string }

type AffiliateUser = {
  publicUserId: string
  displayName: string
  affiliateEnabled: boolean
  invitationQuota: number
  usedQuota: number
  status: string
  updatedAt: string
}

type AffiliateUsersPage = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  items: AffiliateUser[]
  nextCursor: string | null
}

type AffiliateUserResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  user: AffiliateUser
}

type AdmissionBatch = {
  batchId: string
  name: string
  status: string
  codeCount: number
  usedCount: number
  expiresAt: string | null
  createdAt: string
}

type AdmissionBatchesPage = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  items: AdmissionBatch[]
  nextCursor: string | null
}

type AdmissionBatchResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  batch: AdmissionBatch
}

type RegistrationPolicy = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  policy: {
    mode: RegistrationPolicyMode
    revision: number
    updatedAt: string
  }
}

type MutationReceipt = {
  schemaVersion: 'media_web_business_pages_v2'
  revision: number
  ok: true
  updatedAt: string
}

type PlatformCookieStatus = {
  platform: 'douyin' | 'xiaohongshu'
  configured: boolean
  updatedAt: string | null
  validationStatus: 'valid' | 'missing' | 'invalid' | 'error'
  errorCode: string | null
  configurationScript: string
  safeCommand: string
}

type PlatformCookiesResponse = {
  schemaVersion: 'media_web_business_pages_v2'
  platforms: PlatformCookieStatus[]
}

const EMPTY_AFFILIATE_USERS: AffiliateUser[] = []
const EMPTY_ADMISSION_BATCHES: AdmissionBatch[] = []
const PAGE_SIZE = 30
const SCHEMA_VERSION = 'media_web_business_pages_v2'
const CURSOR_PATTERN = /^[A-Za-z0-9_-]{8,1024}$/
const tabs: Array<{ key: AccessTab; label: string; icon: typeof UsersRound }> = [
  { key: 'invitations', label: '邀请权限', icon: UsersRound },
  { key: 'admission', label: '准入码', icon: TicketCheck },
  { key: 'registration', label: '注册策略', icon: ShieldCheck },
]

export default function AdminAccessPage() {
  const { runtimeState, session } = useMediaWeb()
  const permitted = runtimeState === 'authenticated' && session?.role === 'admin'
  const canMutate = permitted && !!session?.csrfToken
  const [activeTab, setActiveTab] = useState<AccessTab>('invitations')
  const [refreshToken, setRefreshToken] = useState(0)
  const [userCursorStack, setUserCursorStack] = useState<Array<string | null>>([null])
  const [batchCursorStack, setBatchCursorStack] = useState<Array<string | null>>([null])
  const [search, setSearch] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null)

  const userCursor = userCursorStack[userCursorStack.length - 1] ?? null
  const batchCursor = batchCursorStack[batchCursorStack.length - 1] ?? null
  const loadUsers = useCallback(
    (signal: AbortSignal) => loadAffiliateUsersPage(userCursor, submittedSearch, signal),
    [submittedSearch, userCursor],
  )
  const loadBatches = useCallback(
    (signal: AbortSignal) => loadAdmissionBatchesPage(batchCursor, signal),
    [batchCursor],
  )
  const usersState = useAdminResource(permitted, loadUsers, refreshToken)
  const batchesState = useAdminResource(permitted, loadBatches, refreshToken)
  const policyState = useAdminResource(permitted, loadRegistrationPolicy, refreshToken)
  const cookieState = useAdminResource(permitted, loadPlatformCookies, refreshToken)
  const usersItems = usersState.status === 'ready' ? usersState.data.items : EMPTY_AFFILIATE_USERS
  const batchesItems = batchesState.status === 'ready' ? batchesState.data.items : EMPTY_ADMISSION_BATCHES
  const userIds = usersItems.map((item) => item.publicUserId).join(',')
  const batchIds = batchesItems.map((item) => item.batchId).join(',')
  const selectedUser = usersItems.find((item) => item.publicUserId === selectedUserId) ?? null
  const readbackUsers = useCallback(
    () => loadAffiliateUsersPage(userCursor, submittedSearch),
    [submittedSearch, userCursor],
  )
  const readbackBatches = useCallback(
    () => loadAdmissionBatchesPage(batchCursor),
    [batchCursor],
  )
  const readbackLatestBatches = useCallback(
    () => loadAdmissionBatchesPage(null),
    [],
  )
  const onMutationComplete = useCallback(() => {
    setRefreshToken((value) => value + 1)
  }, [])

  useEffect(() => {
    if (usersState.status !== 'ready') return
    setSelectedUserId((current) => {
      if (current && usersItems.some((item) => item.publicUserId === current)) return current
      return usersItems[0]?.publicUserId ?? null
    })
  }, [userIds, usersItems, usersState.status])

  useEffect(() => {
    if (batchesState.status !== 'ready') return
    setSelectedBatchId((current) => {
      if (current && batchesItems.some((item) => item.batchId === current)) return current
      return batchesItems[0]?.batchId ?? null
    })
  }, [batchIds, batchesItems, batchesState.status])

  function selectTab(next: AccessTab) {
    setActiveTab(next)
    if (next !== 'invitations') setSelectedUserId(null)
    if (next !== 'admission') setSelectedBatchId(null)
  }

  function submitSearch() {
    setSubmittedSearch(search.trim())
    setUserCursorStack([null])
    setSelectedUserId(null)
  }

  function previousUserPage() {
    if (userCursorStack.length > 1) setUserCursorStack((current) => current.slice(0, -1))
  }

  function nextUserPage() {
    if (usersState.status === 'ready' && usersState.data.nextCursor) {
      setUserCursorStack((current) => [...current, usersState.data.nextCursor])
      setSelectedUserId(null)
    }
  }

  function previousBatchPage() {
    if (batchCursorStack.length > 1) setBatchCursorStack((current) => current.slice(0, -1))
  }

  function nextBatchPage() {
    if (batchesState.status === 'ready' && batchesState.data.nextCursor) {
      setBatchCursorStack((current) => [...current, batchesState.data.nextCursor])
      setSelectedBatchId(null)
    }
  }

  const tabNavigation = <div className={['detail-tabs', styles.tabs].join(' ')} role="tablist" aria-label="用户与准入功能">
    {tabs.map(({ key, label, icon: Icon }) => <button key={key} type="button" role="tab" aria-selected={activeTab === key} className={activeTab === key ? 'active' : ''} onClick={() => selectTab(key)}><Icon size={15} />{label}</button>)}
  </div>

  return <main className={['fidelity-page', styles.page].join(' ')}>
    <header className="page-heading">
      <div>
        <h1>用户与准入</h1>
        <p>管理邀请权限、准入批次和注册策略。</p>
      </div>
      <button className={styles.secondaryButton} type="button" onClick={() => setRefreshToken((value) => value + 1)} disabled={!permitted || usersState.status === 'loading' || batchesState.status === 'loading' || policyState.status === 'loading' || cookieState.status === 'loading'} title="刷新用户与准入数据">
        <RefreshCw size={15} aria-hidden="true" />刷新
      </button>
    </header>
    {!permitted ? <AccessGate runtimeState={runtimeState as RuntimeState} /> : <>
      <div data-page-prelude>{tabNavigation}</div>
      <PlatformCookiePanel state={cookieState} />
      {activeTab === 'invitations' ? <div className={styles.accessLayout} data-page-layout="persistent-rail">
        <div className={styles.mainColumn} data-page-primary data-primary-flow>
          <InvitationTab
            state={usersState}
            admissionState={batchesState}
            policyState={policyState}
            search={search}
            submittedSearch={submittedSearch}
            selectedUserId={selectedUserId}
            cursorDepth={userCursorStack.length}
            onSearchChange={setSearch}
            onSearchSubmit={submitSearch}
            onSelectUser={setSelectedUserId}
            onPreviousPage={previousUserPage}
            onNextPage={nextUserPage}
            onOpenAdmission={() => selectTab('admission')}
            onOpenRegistration={() => selectTab('registration')}
          />
        </div>
        <InvitationInspector
          user={selectedUser}
          expectedRevision={usersState.status === 'ready' ? usersState.data.revision : 0}
          canMutate={canMutate}
          readback={readbackUsers}
          onClear={() => setSelectedUserId(null)}
          onMutationComplete={onMutationComplete}
        />
      </div> : null}
      {activeTab === 'admission' ? <AdmissionTab
        state={batchesState}
        selectedBatchId={selectedBatchId}
        expectedRevision={batchesState.status === 'ready' ? batchesState.data.revision : 0}
        canMutate={canMutate}
        cursorDepth={batchCursorStack.length}
        readback={readbackBatches}
        readbackLatest={readbackLatestBatches}
        onSelectBatch={setSelectedBatchId}
        onPreviousPage={previousBatchPage}
        onNextPage={nextBatchPage}
        onMutationComplete={onMutationComplete}
      /> : null}
      {activeTab === 'registration' ? <RegistrationTab state={policyState} canMutate={canMutate} onMutationComplete={onMutationComplete} /> : null}
    </>}
  </main>
}

function PlatformCookiePanel({ state }: { state: ResourceState<PlatformCookiesResponse> }) {
  const items = state.status === 'ready' ? state.data.platforms : []
  const allValid = items.length > 0 && items.every((item) => item.validationStatus === 'valid')
  return <section className={styles.cookiePanel} aria-labelledby="platform-cookie-heading" data-admin-cookie-panel>
    <header className={styles.cookieHeader}>
      <div className={styles.cookieTitle}>
        <ShieldCheck size={17} aria-hidden="true" />
        <div>
          <h2 id="platform-cookie-heading">平台会话凭据</h2>
          <p>仅管理员可见。页面只展示平台配置状态，不接收或显示凭据内容。</p>
        </div>
      </div>
      <StatusPill
        label={state.status === 'loading' ? '正在校验' : state.status === 'error' ? '读取失败' : allValid ? '配置有效' : '需要处理'}
        tone={allValid ? 'success' : state.status === 'error' ? 'danger' : 'warning'}
      />
    </header>
    <div className={styles.cookieBody}>
      <div className={styles.cookieStatusGrid}>
        {state.status === 'loading' ? <div className={styles.cookieStatusItem}><strong>平台状态</strong><span><i aria-hidden="true" />正在读取</span></div> : null}
        {state.status === 'error' ? <div className={styles.cookieStatusItem}><strong>平台状态</strong><span><i aria-hidden="true" />{state.message}</span></div> : null}
        {items.map((item) => <div className={styles.cookieStatusItem} key={item.platform}>
          <PlatformIdentity platform={item.platform} size="sm" />
          <span><i aria-hidden="true" />{platformCookieStatusLabel(item)}</span>
          <span>{item.updatedAt ? `更新于 ${formatDateTime(item.updatedAt)}` : '尚未配置'}</span>
          <code>{item.safeCommand}</code>
          <button type="button" className={styles.secondaryButton} onClick={() => void navigator.clipboard.writeText(item.safeCommand)} title="复制服务器配置命令" aria-label={`复制${platformDisplayLabel(item.platform)}配置命令`}>
            <Copy size={14} aria-hidden="true" />复制命令
          </button>
        </div>)}
      </div>
      <div className={styles.cookieContract}>
        <strong>服务器端配置脚本</strong>
        <span>脚本：<code>{items[0]?.configurationScript ?? '/home/ubuntu/selfmedia-tools/integrations/platform_auth/cookies/save_platform_cookie_secret.py'}</code></span>
        <span>凭据通过服务器隐藏输入写入私有文件；本页面不会接收、显示或下发 Cookie 内容。</span>
      </div>
    </div>
  </section>
}

function platformCookieStatusLabel(item: PlatformCookieStatus): string {
  if (item.validationStatus === 'valid') return '已配置且格式有效'
  if (item.validationStatus === 'missing') return '尚未配置'
  if (item.validationStatus === 'invalid') return '配置无效，请重新配置'
  return item.errorCode ? `校验失败（${item.errorCode}）` : '校验失败'
}

function useAdminResource<T>(
  permitted: boolean,
  loader: (signal: AbortSignal) => Promise<T>,
  refreshToken: number,
): ResourceState<T> {
  const [state, setState] = useState<ResourceState<T>>({ status: 'idle' })
  useEffect(() => {
    if (!permitted) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    loader(controller.signal)
      .then((data) => {
        if (active) setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return
        setState({ status: 'error', message: describeError(error) })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [loader, permitted, refreshToken])
  return state
}

type InvitationTabProps = {
  state: ResourceState<AffiliateUsersPage>
  admissionState: ResourceState<AdmissionBatchesPage>
  policyState: ResourceState<RegistrationPolicy>
  search: string
  submittedSearch: string
  selectedUserId: string | null
  cursorDepth: number
  onSearchChange: (value: string) => void
  onSearchSubmit: () => void
  onSelectUser: (value: string) => void
  onPreviousPage: () => void
  onNextPage: () => void
  onOpenAdmission: () => void
  onOpenRegistration: () => void
}

function InvitationTab({
  state,
  admissionState,
  policyState,
  search,
  submittedSearch,
  selectedUserId,
  cursorDepth,
  onSearchChange,
  onSearchSubmit,
  onSelectUser,
  onPreviousPage,
  onNextPage,
  onOpenAdmission,
  onOpenRegistration,
}: InvitationTabProps) {
  const items = state.status === 'ready' ? state.data.items : []
  return <section className={styles.tabContent} aria-label="邀请权限">
    <section className={styles.tablePanel} aria-labelledby="invitation-users-heading">
      <PanelHeader title="邀请权限" count={state.status === 'ready' ? items.length : null} id="invitation-users-heading" />
      <form className={styles.filterBar} onSubmit={(event) => { event.preventDefault(); onSearchSubmit() }}>
        <SearchBox className={styles.searchField} value={search} onChange={onSearchChange} label="搜索用户名" />
        <button className={styles.secondaryButton} type="submit"><Search size={14} aria-hidden="true" />搜索</button>
        {submittedSearch ? <button className={styles.quietButton} type="button" onClick={() => { onSearchChange(''); onSearchSubmit() }}><X size={14} aria-hidden="true" />清除搜索</button> : null}
      </form>
      {state.status === 'ready' ? <>
        <UserTable items={items} selectedUserId={selectedUserId} onSelect={onSelectUser} />
        <CursorPagination depth={cursorDepth} hasNext={state.data.nextCursor !== null} onPrevious={onPreviousPage} onNext={onNextPage} />
      </> : <PageState state={state} emptyTitle="暂无可管理用户" />}
    </section>
    <div className={styles.summaryGrid}>
      <AdmissionSummary state={admissionState} onOpen={onOpenAdmission} />
      <RegistrationSummary state={policyState} onOpen={onOpenRegistration} />
    </div>
  </section>
}

function UserTable({ items, selectedUserId, onSelect }: { items: AffiliateUser[]; selectedUserId: string | null; onSelect: (value: string) => void }) {
  if (!items.length) return <EmptyState icon={<UsersRound size={21} />} title="暂无匹配的用户" detail="服务端没有返回符合当前搜索条件的记录。" />
  return <div className={styles.tableScroll} role="region" tabIndex={0} aria-label="用户邀请权限表"><table className={styles.userTable}>
    <colgroup><col className={styles.userColumn} /><col className={styles.permissionColumn} /><col className={styles.switchColumn} /><col className={styles.numberColumn} /><col className={styles.numberColumn} /><col className={styles.statusColumn} /><col className={styles.actionColumn} /></colgroup>
    <thead><tr><th scope="col">用户</th><th scope="col">邀请权限</th><th scope="col">开关</th><th scope="col">配额</th><th scope="col">已用</th><th scope="col">账户状态</th><th scope="col"><span className={styles.srOnly}>操作</span></th></tr></thead>
    <tbody>{items.map((user) => {
      const selected = user.publicUserId === selectedUserId
      const status = affiliateStatus(user.status)
      return <tr key={user.publicUserId} className={selected ? styles.selectedRow : undefined} aria-selected={selected}>
        <td><button className={styles.userSelect} type="button" aria-pressed={selected} onClick={() => onSelect(user.publicUserId)}><span className={[styles.checkbox, selected ? styles.checkboxSelected : ''].join(' ')} aria-hidden="true">{selected ? <Check size={13} /> : null}</span><span className={styles.userIdentity}><strong>{user.displayName}</strong><small title={user.publicUserId}>公开编号：{user.publicUserId}</small></span></button></td>
        <td><StatusPill label={user.affiliateEnabled ? '可邀请' : '禁止邀请'} tone={user.affiliateEnabled ? 'success' : 'muted'} /></td>
        <td><span className={user.affiliateEnabled ? styles.switchOn : styles.switchOff}><span aria-hidden="true" />{user.affiliateEnabled ? '开启' : '关闭'}</span></td>
        <td className={styles.numericCell}>{user.invitationQuota}</td>
        <td className={styles.numericCell}>{user.usedQuota}</td>
        <td><StatusPill label={status.label} tone={status.tone} /></td>
        <td><button className={styles.iconButton} type="button" title="编辑邀请权限" aria-label={'编辑 ' + user.displayName + ' 的邀请权限'} onClick={() => onSelect(user.publicUserId)}><PencilLine size={15} /></button></td>
      </tr>
    })}</tbody>
  </table></div>
}

function InvitationInspector({
  user,
  expectedRevision,
  canMutate,
  readback,
  onClear,
  onMutationComplete,
}: {
  user: AffiliateUser | null
  expectedRevision: number
  canMutate: boolean
  readback: () => Promise<AffiliateUsersPage>
  onClear: () => void
  onMutationComplete: () => void
}) {
  const { session } = useMediaWeb()
  const [enabled, setEnabled] = useState(false)
  const [quota, setQuota] = useState('0')
  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [revokeReason, setRevokeReason] = useState('')
  const [revokeConfirmation, setRevokeConfirmation] = useState('')
  const updateAction = useAdminAction(onMutationComplete)
  const revokeAction = useAdminAction(onMutationComplete)
  const signature = user ? [user.publicUserId, user.affiliateEnabled, user.invitationQuota, user.usedQuota, user.updatedAt].join(':') : ''

  useEffect(() => {
    if (!user) {
      setEnabled(false)
      setQuota('0')
      setReason('')
      setConfirmation('')
      setRevokeReason('')
      setRevokeConfirmation('')
      return
    }
    setEnabled(user.affiliateEnabled)
    setQuota(String(user.invitationQuota))
    setReason('')
    setConfirmation('')
    setRevokeReason('')
    setRevokeConfirmation('')
  }, [signature, user])

  if (!user) return <aside className={[styles.inspector, styles.inspectorEmpty].join(' ')} aria-label="邀请权限检查器" data-page-inspector data-page-terminal-surface="inspector"><UserRound size={25} /><strong>选择用户查看邀请权限</strong><span>选择一条服务端记录后，这里会显示可编辑字段和审计确认。</span></aside>

  const currentUser = user
  const numericQuota = parseIntegerInput(quota)
  const quotaValid = numericQuota !== null && numericQuota >= user.usedQuota && numericQuota <= 1_000_000
  const confirmationValid = confirmation === user.displayName
  const revokeConfirmationValid = revokeConfirmation === user.displayName
  const reasonValid = reason.trim().length > 0
  const revokeReasonValid = revokeReason.trim().length > 0
  const updateReady = canMutate && !!session && quotaValid && confirmationValid && reasonValid && !updateAction.busy
  const revokeReady = canMutate && !!session && revokeConfirmationValid && revokeReasonValid && !revokeAction.busy
  const status = affiliateStatus(user.status)

  async function submitUpdate(event: FormEvent) {
    event.preventDefault()
    if (!session || !canMutate || !updateReady || numericQuota === null) return
    const path = '/admin/affiliate-users/' + currentUser.publicUserId
    const body = {
      affiliateEnabled: enabled,
      invitationQuota: numericQuota,
      reason: reason.trim(),
      expectedRevision,
    }
    const result = await updateAction.run(mutationFingerprint(path, 'PUT', body), async (idempotencyKey) => {
      const payload = parseAffiliateUserResponse(await callBusinessOperation<unknown>('updateAdminAffiliateUser', {
        path: { userId: currentUser.publicUserId },
        body,
        csrfToken: session.csrfToken,
        idempotencyKey,
        auditReason: body.reason,
      }))
      if (payload.user.publicUserId !== currentUser.publicUserId || payload.user.affiliateEnabled !== enabled || payload.user.invitationQuota !== numericQuota) {
        throw new Error('服务端写入回读与提交目标不一致。')
      }
      const readbackPage = await readback()
      const readbackUser = readbackPage.items.find((item) => item.publicUserId === currentUser.publicUserId)
      if (!readbackUser || readbackUser.affiliateEnabled !== enabled || readbackUser.invitationQuota !== numericQuota) {
        throw new Error('写入后未读到目标用户的最新状态。')
      }
      return readbackPage
    })
    if (result) {
      setReason('')
      setConfirmation('')
    }
  }

  async function submitRevoke(event: FormEvent) {
    event.preventDefault()
    if (!session || !canMutate || !revokeReady) return
    const path = '/admin/users/' + currentUser.publicUserId + '/sessions/revoke-all'
    const body = { reason: revokeReason.trim() }
    const result = await revokeAction.run(mutationFingerprint(path, 'POST', body), async (idempotencyKey) => {
      parseMutationReceipt(await callBusinessOperation<unknown>('revokeAdminUserSessions', {
        path: { userId: currentUser.publicUserId },
        body,
        csrfToken: session.csrfToken,
        idempotencyKey,
        auditReason: body.reason,
      }))
      const readbackPage = await readback()
      if (!readbackPage.items.some((item) => item.publicUserId === currentUser.publicUserId)) {
        throw new Error('会话撤销后未读到目标用户。')
      }
      return readbackPage
    })
    if (result) {
      setRevokeReason('')
      setRevokeConfirmation('')
    }
  }

  function resetDraft() {
    setEnabled(currentUser.affiliateEnabled)
    setQuota(String(currentUser.invitationQuota))
    setReason('')
    setConfirmation('')
  }

  return <aside className={styles.inspector} aria-labelledby="invitation-inspector-heading" data-page-inspector data-page-terminal-surface="inspector">
    <header className={styles.inspectorHeader}><div><h2 id="invitation-inspector-heading">编辑邀请权限</h2><span>服务端修订号：{expectedRevision}</span></div><button className={styles.iconButton} type="button" title="清除选择" aria-label="清除选择" onClick={onClear}><X size={17} /></button></header>
    <div className={styles.inspectorBody}>
      <div className={styles.inspectorIdentity}><span className={styles.identityIcon}><UserRound size={21} /></span><div><strong>{user.displayName}</strong><small title={user.publicUserId}>{user.publicUserId}</small></div><StatusPill label={status.label} tone={status.tone} /></div>
      <form className={styles.inspectorForm} onSubmit={(event) => void submitUpdate(event)}>
        <Field label="邀请权限"><select value={enabled ? 'enabled' : 'disabled'} onChange={(event) => setEnabled(event.target.value === 'enabled')}><option value="enabled">可邀请</option><option value="disabled">禁止邀请</option></select></Field>
        <Field label="开关"><label className={styles.switchField}><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /><span className={styles.switchTrack} aria-hidden="true"><span /></span><span>{enabled ? '开启' : '关闭'}</span></label></Field>
        <Field label="配额上限"><input type="number" min="0" max="1000000" step="1" value={quota} onChange={(event) => setQuota(event.target.value)} aria-describedby="quota-help" /></Field>
        <p id="quota-help" className={styles.fieldHint}>已用 {user.usedQuota} 个。</p>
        {!quotaValid ? <p className={styles.fieldError} role="alert">配额必须是整数，且不能低于已用名额。</p> : null}
        <div className={styles.scopeNote}><ShieldCheck size={16} /><div><strong>有效范围</strong><span>仅影响当前选中的用户。</span></div></div>
        <Field label={<span>审计原因 <b className={styles.required}>*</b></span>}><textarea value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} placeholder="说明本次权限变更的原因" rows={4} /><small className={styles.characterCount}>{reason.length}/500</small></Field>
        <div className={styles.confirmationBox}><div className={styles.confirmationHeading}><KeyRound size={15} /><strong>确认权限变更</strong></div><p>请输入用户名称以确认当前操作。</p><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={'请输入“' + user.displayName + '”以确认'} aria-label="输入用户名称确认变更" />{confirmation && !confirmationValid ? <small className={styles.fieldError}>输入内容与当前用户名不一致。</small> : null}</div>
        {updateAction.state.kind === 'success' ? <ReadbackMessage /> : null}
        <div className={styles.formActions}><button className={styles.cancelButton} type="button" onClick={resetDraft}>取消编辑</button><button className={styles.primaryButton} type="submit" disabled={!updateReady}>{updateAction.busy ? '正在保存' : '应用变更'}</button></div>
        <ActionMessage state={updateAction.state} />
      </form>
      <form className={[styles.inspectorForm, styles.dangerAction].join(' ')} onSubmit={(event) => void submitRevoke(event)}>
        <div className={styles.actionHeader}><div><h2>撤销用户会话</h2><p>撤销该用户的全部活动会话。</p></div></div>
        <Field label={<span>审计原因 <b className={styles.required}>*</b></span>}><textarea value={revokeReason} maxLength={500} onChange={(event) => setRevokeReason(event.target.value)} placeholder="说明本次会话撤销的原因" rows={3} /><small className={styles.characterCount}>{revokeReason.length}/500</small></Field>
        <div className={styles.confirmationBox}><div className={styles.confirmationHeading}><KeyRound size={15} /><strong>确认会话撤销</strong></div><p>请输入用户名称以确认当前操作。</p><input value={revokeConfirmation} onChange={(event) => setRevokeConfirmation(event.target.value)} placeholder={'请输入“' + user.displayName + '”以确认'} aria-label="输入用户名称确认会话撤销" />{revokeConfirmation && !revokeConfirmationValid ? <small className={styles.fieldError}>输入内容与当前用户名不一致。</small> : null}</div>
        {revokeAction.state.kind === 'success' ? <ReadbackMessage /> : null}
        <button className={styles.dangerButton} type="submit" disabled={!revokeReady}>{revokeAction.busy ? '正在撤销' : '撤销全部会话'}</button>
        <ActionMessage state={revokeAction.state} />
      </form>
    </div>
  </aside>
}

function AdmissionSummary({ state, onOpen }: { state: ResourceState<AdmissionBatchesPage>; onOpen: () => void }) {
  const items = state.status === 'ready' ? state.data.items : []
  const activeCount = items.filter((item) => item.status === 'active').length
  const usedCount = items.reduce((total, item) => total + item.usedCount, 0)
  return <section className={styles.summaryPanel} aria-labelledby="admission-summary-heading" data-page-terminal-surface="primary"><PanelHeader title="准入码批次（摘要）" id="admission-summary-heading" action={<button className={styles.quietButton} type="button" onClick={onOpen}>查看全部<ChevronRight size={14} /></button>} />{state.status === 'ready' ? <div className={styles.summaryBody}><div className={styles.metricGrid}><Metric className={styles.metric} label="当前页批次" value={items.length} detail="服务端返回" /><Metric className={styles.metric} label="生效批次" value={activeCount} detail="按服务端状态" /><Metric className={styles.metric} label="已用准入码" value={usedCount} detail="当前页汇总" /></div><SummaryTableHint items={items} /></div> : <SummaryState state={state} />}</section>
}

function RegistrationSummary({ state, onOpen }: { state: ResourceState<RegistrationPolicy>; onOpen: () => void }) {
  return <section className={styles.summaryPanel} aria-labelledby="registration-summary-heading" data-page-terminal-surface="primary"><PanelHeader title="当前注册策略（摘要）" id="registration-summary-heading" action={<button className={styles.quietButton} type="button" onClick={onOpen}>查看详情<ChevronRight size={14} /></button>} />{state.status === 'ready' ? <div className={styles.summaryBody}><dl className={styles.factList}><div><dt>注册模式</dt><dd>{policyLabel(state.data.policy.mode)}</dd></div><div><dt>服务端状态</dt><dd><StatusPill label="已读取" tone="success" /></dd></div><div><dt>更新时间</dt><dd>{formatDate(state.data.policy.updatedAt)}</dd></div></dl></div> : <SummaryState state={state} />}</section>
}

function SummaryTableHint({ items }: { items: AdmissionBatch[] }) {
  if (!items.length) return <p className={styles.summaryEmpty}>暂无准入码批次。</p>
  const latest = items[0]
  return <div className={styles.latestSummary}><span>最近批次</span><strong title={latest.name}>{latest.name}</strong><small>{latest.usedCount}/{latest.codeCount} 已用 · {formatDate(latest.createdAt)} 创建</small></div>
}

function AdmissionTab({
  state,
  selectedBatchId,
  expectedRevision,
  canMutate,
  cursorDepth,
  readback,
  readbackLatest,
  onSelectBatch,
  onPreviousPage,
  onNextPage,
  onMutationComplete,
}: {
  state: ResourceState<AdmissionBatchesPage>
  selectedBatchId: string | null
  expectedRevision: number
  canMutate: boolean
  cursorDepth: number
  readback: () => Promise<AdmissionBatchesPage>
  readbackLatest: () => Promise<AdmissionBatchesPage>
  onSelectBatch: (value: string) => void
  onPreviousPage: () => void
  onNextPage: () => void
  onMutationComplete: () => void
}) {
  const items = state.status === 'ready' ? state.data.items : []
  const selected = items.find((item) => item.batchId === selectedBatchId) ?? null
  return <section className={styles.tabContent} aria-label="准入码">
    <div className={styles.sectionLead}><div><h2>准入码批次</h2><p>批次库存和状态来自服务端。</p></div><StatusPill label="管理员视图" tone="success" /></div>
    <section className={styles.tablePanel} aria-labelledby="admission-table-heading"><PanelHeader title="批次库存" count={state.status === 'ready' ? items.length : null} id="admission-table-heading" />{state.status === 'ready' ? <><BatchTable items={items} selectedBatchId={selectedBatchId} onSelect={onSelectBatch} /><CursorPagination depth={cursorDepth} hasNext={state.data.nextCursor !== null} onPrevious={onPreviousPage} onNext={onNextPage} /></> : <PageState state={state} emptyTitle="暂无准入码批次" />}</section>
    <AdmissionActions selected={selected} expectedRevision={expectedRevision} canMutate={canMutate} readback={readback} readbackLatest={readbackLatest} onMutationComplete={onMutationComplete} />
  </section>
}

function BatchTable({ items, selectedBatchId, onSelect }: { items: AdmissionBatch[]; selectedBatchId: string | null; onSelect: (value: string) => void }) {
  if (!items.length) return <EmptyState icon={<TicketCheck size={21} />} title="暂无准入码批次" detail="服务端还没有返回批次记录。" />
  return <div className={styles.tableScroll} role="region" tabIndex={0} aria-label="准入码批次表"><table className={styles.batchTable}><colgroup><col className={styles.batchNameColumn} /><col className={styles.batchCreatedColumn} /><col className={styles.batchNumberColumn} /><col className={styles.batchNumberColumn} /><col className={styles.batchStatusColumn} /><col className={styles.batchDisabledColumn} /><col className={styles.actionColumn} /></colgroup><thead><tr><th scope="col">批次名称</th><th scope="col">创建时间</th><th className={styles.numericCell} scope="col">配额</th><th className={styles.numericCell} scope="col">已用</th><th scope="col">状态</th><th scope="col">到期</th><th className={styles.actionCell} scope="col"><span className={styles.srOnly}>操作</span></th></tr></thead><tbody>{items.map((batch) => {
    const selected = batch.batchId === selectedBatchId
    return <tr key={batch.batchId} className={selected ? styles.selectedRow : undefined} aria-selected={selected}><td><button className={styles.batchSelect} type="button" aria-pressed={selected} onClick={() => onSelect(batch.batchId)}><span className={[styles.checkbox, selected ? styles.checkboxSelected : ''].join(' ')} aria-hidden="true">{selected ? <Check size={13} /> : null}</span><span><strong title={batch.name}>{batch.name}</strong><small title={batch.batchId}>{batch.batchId}</small></span></button></td><td>{formatDate(batch.createdAt)}</td><td className={styles.numericCell}>{batch.codeCount}</td><td className={styles.numericCell}>{batch.usedCount}</td><td><StatusPill label={batchStatusLabel(batch.status)} tone={batch.status === 'active' ? 'success' : 'muted'} /></td><td>{formatDate(batch.expiresAt)}</td><td className={styles.actionCell}><button className={styles.iconButton} type="button" title="选择批次操作" aria-label={'选择 ' + batch.name + ' 进行操作'} onClick={() => onSelect(batch.batchId)}><EllipsisVertical size={16} /></button></td></tr>
  })}</tbody></table></div>
}

function AdmissionActions({
  selected,
  expectedRevision,
  canMutate,
  readback,
  readbackLatest,
  onMutationComplete,
}: {
  selected: AdmissionBatch | null
  expectedRevision: number
  canMutate: boolean
  readback: () => Promise<AdmissionBatchesPage>
  readbackLatest: () => Promise<AdmissionBatchesPage>
  onMutationComplete: () => void
}) {
  const { session } = useMediaWeb()
  const [mode, setMode] = useState<'issue' | 'disable'>('issue')
  const [name, setName] = useState('')
  const [count, setCount] = useState('10')
  const [createReason, setCreateReason] = useState('')
  const [createConfirmation, setCreateConfirmation] = useState(false)
  const [disableReason, setDisableReason] = useState('')
  const [disableConfirmation, setDisableConfirmation] = useState('')
  const action = useAdminAction(onMutationComplete)
  const numericCount = parseIntegerInput(count)
  const createReady = canMutate && !!session && name.trim().length > 0 && numericCount !== null && numericCount >= 1 && numericCount <= 1000 && createReason.trim().length > 0 && createConfirmation && !action.busy
  const disableReady = canMutate && !!session && !!selected && selected.status === 'active' && disableReason.trim().length > 0 && disableConfirmation === selected.name && !action.busy

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!session || !canMutate) return
    if (mode === 'issue') {
      if (!createReady || numericCount === null) return
      const path = '/admin/admission-batches'
      const body = { name: name.trim(), codeCount: numericCount, reason: createReason.trim() }
      const result = await action.run(mutationFingerprint(path, 'POST', body), async (idempotencyKey) => {
        const response = parseAdmissionBatchResponse(await callBusinessOperation<unknown>('createAdminAdmissionBatch', {
          body,
          csrfToken: session.csrfToken,
          idempotencyKey,
          auditReason: body.reason,
        }))
        const readbackPage = await readbackLatest()
        const readbackBatch = readbackPage.items.find((item) => item.batchId === response.batch.batchId)
        if (!readbackBatch || readbackBatch.name !== response.batch.name || readbackBatch.codeCount !== response.batch.codeCount) {
          throw new Error('签发后未读到服务端返回的批次。')
        }
        return readbackPage
      })
      if (result) {
        setCreateReason('')
        setCreateConfirmation(false)
        setName('')
      }
      return
    }
    if (!selected || !disableReady) return
    const path = '/admin/admission-batches/' + selected.batchId + '/disable'
    const body = { reason: disableReason.trim(), expectedRevision }
    const result = await action.run(mutationFingerprint(path, 'POST', body), async (idempotencyKey) => {
      parseMutationReceipt(await callBusinessOperation<unknown>('disableAdminAdmissionBatch', {
        path: { batchId: selected.batchId },
        body,
        csrfToken: session.csrfToken,
        idempotencyKey,
        auditReason: body.reason,
      }))
      const readbackPage = await readback()
      const readbackBatch = readbackPage.items.find((item) => item.batchId === selected.batchId)
      if (!readbackBatch || readbackBatch.status !== 'disabled') {
        throw new Error('禁用后未读到批次的服务端最新状态。')
      }
      return readbackPage
    })
    if (result) {
      setDisableReason('')
      setDisableConfirmation('')
    }
  }

  function changeMode(next: 'issue' | 'disable') {
    setMode(next)
    setCreateReason('')
    setCreateConfirmation(false)
    setDisableReason('')
    setDisableConfirmation('')
  }

  return <section className={styles.actionPanel} aria-labelledby="admission-action-heading">
    <div className={styles.actionHeader}><div><h2 id="admission-action-heading">批次操作</h2><p>写入需要审计原因、确认和服务端回读。</p></div><ActionMessage state={action.state} /></div>
    <div className={styles.segmented} role="tablist" aria-label="准入码批次操作"><button type="button" role="tab" aria-selected={mode === 'issue'} className={mode === 'issue' ? styles.segmentActive : ''} onClick={() => changeMode('issue')}>签发批次</button><button type="button" role="tab" aria-selected={mode === 'disable'} className={mode === 'disable' ? styles.segmentActive : ''} onClick={() => changeMode('disable')}>禁用批次</button></div>
    <form className={styles.actionForm} onSubmit={(event) => void submit(event)}>{mode === 'issue' ? <><div className={styles.actionFields}><Field label="批次名称"><input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} placeholder="例如：合作伙伴试用批次" /></Field><Field label="签发数量"><input type="number" min="1" max="1000" step="1" value={count} onChange={(event) => setCount(event.target.value)} /></Field></div><Field label={<span>审计原因 <b className={styles.required}>*</b></span>}><textarea value={createReason} maxLength={500} onChange={(event) => setCreateReason(event.target.value)} placeholder="说明为什么要签发这批准入码" rows={3} /><small className={styles.characterCount}>{createReason.length}/500</small></Field><label className={styles.confirmCheck}><input type="checkbox" checked={createConfirmation} onChange={(event) => setCreateConfirmation(event.target.checked)} /><span>我确认创建该准入码批次。</span></label></> : <><div className={styles.selectedTarget}>{selected ? <><span className={styles.identityIcon}><TicketCheck size={19} /></span><div><strong title={selected.name}>{selected.name}</strong><small>{selected.batchId}</small></div><StatusPill label={batchStatusLabel(selected.status)} tone={selected.status === 'active' ? 'success' : 'muted'} /></> : <span>请先选择批次。</span>}</div>{selected ? <Field label={<span>输入批次名称确认 <b className={styles.required}>*</b></span>}><input value={disableConfirmation} onChange={(event) => setDisableConfirmation(event.target.value)} placeholder={'请输入“' + selected.name + '”以确认'} /></Field> : null}<Field label={<span>审计原因 <b className={styles.required}>*</b></span>}><textarea value={disableReason} maxLength={500} onChange={(event) => setDisableReason(event.target.value)} placeholder="说明为什么要禁用这批准入码" rows={3} /><small className={styles.characterCount}>{disableReason.length}/500</small></Field></>}{action.state.kind === 'success' ? <ReadbackMessage /> : null}<button className={styles.primaryButton} type="submit" disabled={mode === 'issue' ? !createReady : !disableReady}>{action.busy ? '正在提交' : mode === 'issue' ? '生成批次' : '禁用批次'}</button></form>
  </section>
}

function RegistrationTab({ state, canMutate, onMutationComplete }: { state: ResourceState<RegistrationPolicy>; canMutate: boolean; onMutationComplete: () => void }) {
  const { session } = useMediaWeb()
  const [mode, setMode] = useState<RegistrationPolicyMode>('invite_only')
  const [reason, setReason] = useState('')
  const [confirmation, setConfirmation] = useState(false)
  const action = useAdminAction(onMutationComplete)
  const currentPolicy = state.status === 'ready' ? state.data.policy : null

  useEffect(() => {
    if (!currentPolicy) return
    setMode(currentPolicy.mode)
    setReason('')
    setConfirmation(false)
  }, [currentPolicy])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!session || !canMutate || state.status !== 'ready' || !reason.trim() || !confirmation || action.busy) return
    const path = '/admin/registration-policy'
    const body = { mode, reason: reason.trim(), expectedRevision: state.data.policy.revision }
    const result = await action.run(mutationFingerprint(path, 'PUT', body), async (idempotencyKey) => {
      const response = parseRegistrationPolicy(await callBusinessOperation<unknown>('updateAdminRegistrationPolicy', {
        body,
        csrfToken: session.csrfToken,
        idempotencyKey,
        auditReason: body.reason,
      }))
      if (response.policy.mode !== mode) throw new Error('服务端返回的注册策略与提交目标不一致。')
      const readback = parseRegistrationPolicy(await callBusinessOperation<unknown>('getAdminRegistrationPolicy'))
      if (readback.policy.mode !== mode) throw new Error('写入后未读到服务端最新注册策略。')
      return readback
    })
    if (result) {
      setReason('')
      setConfirmation(false)
    }
  }

  return <section className={styles.tabContent} aria-label="注册策略"><div className={styles.policyLayout}><section className={styles.policyPanel} aria-labelledby="registration-policy-heading"><PanelHeader title="当前注册策略" id="registration-policy-heading" />{state.status === 'ready' ? <div className={styles.policyBody}><div className={styles.currentPolicy}><span className={styles.identityIcon}><ShieldCheck size={20} /></span><div><span>服务端当前模式</span><strong>{policyLabel(state.data.policy.mode)}</strong></div><StatusPill label="已读取" tone="success" /></div><dl className={styles.factList}><div><dt>策略修订</dt><dd>{state.data.policy.revision}</dd></div><div><dt>更新时间</dt><dd>{formatDate(state.data.policy.updatedAt)}</dd></div></dl></div> : <PageState state={state} emptyTitle="暂无注册策略" />}</section><section className={styles.policyPanel} aria-labelledby="registration-edit-heading"><PanelHeader title="更新注册策略" id="registration-edit-heading" />{state.status === 'ready' ? <form className={styles.policyForm} onSubmit={(event) => void submit(event)}><Field label="注册模式"><select value={mode} onChange={(event) => setMode(event.target.value as RegistrationPolicyMode)}><option value="open">开放注册</option><option value="invite_only">仅邀请注册</option><option value="closed">关闭注册</option></select></Field><p className={styles.fieldHint}>当前值来自服务端策略读取。</p><Field label={<span>审计原因 <b className={styles.required}>*</b></span>}><textarea value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} placeholder="说明为什么要调整注册策略" rows={5} /><small className={styles.characterCount}>{reason.length}/500</small></Field><label className={styles.confirmCheck}><input type="checkbox" checked={confirmation} onChange={(event) => setConfirmation(event.target.checked)} /><span>我确认将更新当前注册策略。</span></label>{action.state.kind === 'success' ? <ReadbackMessage /> : null}<button className={styles.primaryButton} type="submit" disabled={!canMutate || !reason.trim() || !confirmation || action.busy}>{action.busy ? '正在保存' : '保存注册策略'}</button><ActionMessage state={action.state} /></form> : null}</section></div></section>
}

function AccessGate({ runtimeState }: { runtimeState: RuntimeState }) {
  if (runtimeState === 'checking') return <div className={[styles.pageState, styles.pageNotice, styles.pageNoticeNeutral].join(' ')} aria-busy="true"><span className={styles.loadingBar} /><strong>正在确认管理员权限</strong><span>业务数据尚未加载。</span></div>
  if (runtimeState === 'unauthenticated') return <div className={[styles.pageState, styles.pageNotice, styles.pageNoticeNeutral].join(' ')}><ShieldCheck size={22} /><strong>当前会话未登录</strong><span>业务数据不会加载。</span></div>
  if (runtimeState === 'unavailable') return <div className={[styles.pageState, styles.pageNotice, styles.pageNoticeDanger].join(' ')} role="alert"><AlertCircle size={22} /><strong>会话服务不可用</strong><span>业务数据不会加载。</span></div>
  return <div className={[styles.pageState, styles.pageNotice, styles.pageNoticeNeutral].join(' ')}><ShieldCheck size={22} /><strong>当前会话无权访问</strong><span>管理员业务数据不会加载。</span></div>
}

function PanelHeader({ title, count, id, action }: { title: string; count?: number | null; id: string; action?: ReactNode }) {
  return <header className={styles.panelHeader}><div><h2 id={id}>{title}</h2>{count !== undefined && count !== null ? <span>{count}</span> : null}</div>{action}</header>
}

function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <label className={styles.field}><span className={styles.fieldLabel}>{label}</span>{children}</label>
}

function CursorPagination({ depth, hasNext, onPrevious, onNext }: { depth: number; hasNext: boolean; onPrevious: () => void; onNext: () => void }) {
  return <nav className={styles.pagination} aria-label="游标分页"><span>{depth > 1 ? '第 ' + depth + ' 页' : '第 1 页'}</span><button type="button" title="上一页" aria-label="上一页" disabled={depth <= 1} onClick={onPrevious}><ChevronLeft size={15} /></button><button type="button" title="下一页" aria-label="下一页" disabled={!hasNext} onClick={onNext}><ChevronRight size={15} /></button></nav>
}

function StatusPill({ label, tone }: { label: string; tone: StatusTone }) {
  const toneClass = tone === 'success' ? styles.statusSuccess : tone === 'warning' ? styles.statusWarning : tone === 'danger' ? styles.statusDanger : styles.statusMuted
  return <span className={[styles.statusPill, toneClass].join(' ')}><span aria-hidden="true" />{label}</span>
}

function ReadbackMessage() {
  return <div className={styles.readbackMessage} role="status"><CheckCircle2 size={15} />已写入，并已从服务端重新读取。</div>
}

function ActionMessage({ state }: { state: ActionState }) {
  if (state.kind === 'idle' || state.kind === 'success') return null
  const toneClass = state.kind === 'error' ? styles.actionError : styles.actionBusy
  return <div className={[styles.actionMessage, toneClass].join(' ')} role={state.kind === 'error' ? 'alert' : 'status'}>{state.kind === 'error' ? <CircleAlert size={15} /> : null}{state.message}</div>
}

function SummaryState({ state }: { state: ResourceState<unknown> }) {
  if (state.status === 'loading') return <div className={styles.summaryState} aria-busy="true">正在读取摘要</div>
  if (state.status === 'error') return <div className={styles.summaryState} role="alert"><AlertCircle size={16} /><span>{state.message}</span></div>
  return <div className={styles.summaryState}>暂无数据。</div>
}

function PageState({ state, emptyTitle }: { state: ResourceState<unknown>; emptyTitle: string }) {
  if (state.status === 'loading') return <div className={styles.pageState} aria-busy="true"><span className={styles.loadingBar} /><strong>正在读取</strong><span>页面只展示服务端返回的数据。</span></div>
  if (state.status === 'error') return <div className={styles.pageState} role="alert"><AlertCircle size={22} /><strong>{state.message}</strong><span>当前数据未加载。</span></div>
  if (state.status === 'idle') return <div className={styles.pageState}><ShieldCheck size={22} /><strong>等待管理员权限</strong><span>业务数据不会加载。</span></div>
  return <EmptyState icon={<AlertCircle size={21} />} title={emptyTitle} detail="服务端没有返回可展示的记录。" />
}

function EmptyState({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className={styles.emptyState}>{icon}<strong>{title}</strong><span>{detail}</span></div>
}

function affiliateStatus(status: string): { label: string; tone: StatusTone } {
  if (status === 'active') return { label: '正常', tone: 'success' }
  if (status === 'disabled' || status === 'inactive') return { label: '已停用', tone: 'muted' }
  if (status === 'suspended' || status === 'locked') return { label: '受限', tone: 'warning' }
  return { label: status, tone: 'muted' }
}

function batchStatusLabel(status: string): string {
  if (status === 'active') return '生效中'
  if (status === 'disabled') return '已停用'
  if (status === 'expired') return '已过期'
  return status
}

function policyLabel(mode: RegistrationPolicyMode): string {
  if (mode === 'open') return '开放注册'
  if (mode === 'closed') return '关闭注册'
  return '仅邀请注册'
}

function formatDate(value: string | null): string {
  return formatDateTimeMinutes(value, { empty: '未设置', invalid: '时间不可用' })
}

function parseIntegerInput(value: string): number | null {
  if (!/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

async function loadAffiliateUsersPage(cursor: string | null, search: string, signal?: AbortSignal): Promise<AffiliateUsersPage> {
  const payload = await callBusinessOperation<unknown>('listAdminAffiliateUsers', {
    query: { cursor: cursor ?? undefined, pageSize: PAGE_SIZE, search: search || undefined },
    signal,
  })
  return parseAffiliateUsersPage(payload)
}

async function loadAdmissionBatchesPage(cursor: string | null, signal?: AbortSignal): Promise<AdmissionBatchesPage> {
  const payload = await callBusinessOperation<unknown>('listAdminAdmissionBatches', {
    query: { cursor: cursor ?? undefined, pageSize: PAGE_SIZE },
    signal,
  })
  return parseAdmissionBatchesPage(payload)
}

async function loadRegistrationPolicy(signal?: AbortSignal): Promise<RegistrationPolicy> {
  const payload = await callBusinessOperation<unknown>('getAdminRegistrationPolicy', { signal })
  return parseRegistrationPolicy(payload)
}

async function loadPlatformCookies(signal?: AbortSignal): Promise<PlatformCookiesResponse> {
  const payload = await callBusinessOperation<unknown>('getAdminPlatformCookies', { signal })
  return parsePlatformCookies(payload)
}

function parseAffiliateUsersPage(value: unknown): AffiliateUsersPage {
  const object = asRecord(value, '服务返回的邀请权限列表格式无效。')
  assertExactKeys(object, ['schemaVersion', 'revision', 'items', 'nextCursor'], '邀请权限列表字段不完整。')
  assertSchemaVersion(object)
  const items = object.items
  if (!Array.isArray(items)) throw new Error('服务返回的邀请权限记录格式无效。')
  return {
    schemaVersion: SCHEMA_VERSION,
    revision: integerField(object, 'revision'),
    items: items.map(parseAffiliateUser),
    nextCursor: cursorField(object, 'nextCursor'),
  }
}

function parseAffiliateUserResponse(value: unknown): AffiliateUserResponse {
  const object = asRecord(value, '服务返回的邀请权限写入结果格式无效。')
  assertExactKeys(object, ['schemaVersion', 'revision', 'user'], '邀请权限写入结果字段不完整。')
  assertSchemaVersion(object)
  return { schemaVersion: SCHEMA_VERSION, revision: integerField(object, 'revision'), user: parseAffiliateUser(object.user) }
}

function parseAffiliateUser(value: unknown): AffiliateUser {
  const object = asRecord(value, '服务返回的用户权限记录格式无效。')
  assertExactKeys(object, ['publicUserId', 'displayName', 'affiliateEnabled', 'invitationQuota', 'usedQuota', 'status', 'updatedAt'], '用户权限记录字段不完整。')
  const invitationQuota = integerField(object, 'invitationQuota')
  const usedQuota = integerField(object, 'usedQuota')
  if (usedQuota > invitationQuota) throw new Error('服务返回的用户权限计数无效。')
  const publicUserId = stringField(object, 'publicUserId')
  if (!isPublicId(publicUserId)) throw new Error('服务返回的用户公开编号无效。')
  return {
    publicUserId,
    displayName: nonEmptyStringField(object, 'displayName'),
    affiliateEnabled: booleanField(object, 'affiliateEnabled'),
    invitationQuota,
    usedQuota,
    status: nonEmptyStringField(object, 'status'),
    updatedAt: dateField(object, 'updatedAt'),
  }
}

function parseAdmissionBatchesPage(value: unknown): AdmissionBatchesPage {
  const object = asRecord(value, '服务返回的准入码列表格式无效。')
  assertExactKeys(object, ['schemaVersion', 'revision', 'items', 'nextCursor'], '准入码列表字段不完整。')
  assertSchemaVersion(object)
  if (!Array.isArray(object.items)) throw new Error('服务返回的准入码批次格式无效。')
  return {
    schemaVersion: SCHEMA_VERSION,
    revision: integerField(object, 'revision'),
    items: object.items.map(parseAdmissionBatch),
    nextCursor: cursorField(object, 'nextCursor'),
  }
}

function parseAdmissionBatchResponse(value: unknown): AdmissionBatchResponse {
  const object = asRecord(value, '服务返回的准入码写入结果格式无效。')
  assertExactKeys(object, ['schemaVersion', 'revision', 'batch'], '准入码写入结果字段不完整。')
  assertSchemaVersion(object)
  return { schemaVersion: SCHEMA_VERSION, revision: integerField(object, 'revision'), batch: parseAdmissionBatch(object.batch) }
}

function parseAdmissionBatch(value: unknown): AdmissionBatch {
  const object = asRecord(value, '服务返回的准入码批次记录格式无效。')
  assertExactKeys(object, ['batchId', 'name', 'status', 'codeCount', 'usedCount', 'expiresAt', 'createdAt'], '准入码批次记录字段不完整。')
  const codeCount = integerField(object, 'codeCount')
  const usedCount = integerField(object, 'usedCount')
  if (usedCount > codeCount) throw new Error('服务返回的准入码批次数量无效。')
  const batchId = stringField(object, 'batchId')
  if (!isPublicId(batchId)) throw new Error('服务返回的批次公开编号无效。')
  return {
    batchId,
    name: nonEmptyStringField(object, 'name'),
    status: nonEmptyStringField(object, 'status'),
    codeCount,
    usedCount,
    expiresAt: nullableDateField(object, 'expiresAt'),
    createdAt: dateField(object, 'createdAt'),
  }
}

function parseRegistrationPolicy(value: unknown): RegistrationPolicy {
  const object = asRecord(value, '服务返回的注册策略格式无效。')
  assertExactKeys(object, ['schemaVersion', 'revision', 'policy'], '注册策略字段不完整。')
  assertSchemaVersion(object)
  const policy = asRecord(object.policy, '服务返回的注册策略格式无效。')
  assertExactKeys(policy, ['mode', 'revision', 'updatedAt'], '注册策略字段不完整。')
  const mode = stringField(policy, 'mode')
  if (mode !== 'open' && mode !== 'invite_only' && mode !== 'closed') throw new Error('服务返回了无法识别的注册策略。')
  const revision = integerField(policy, 'revision')
  return {
    schemaVersion: SCHEMA_VERSION,
    revision: integerField(object, 'revision'),
    policy: { mode, revision, updatedAt: dateField(policy, 'updatedAt') },
  }
}

function parsePlatformCookies(value: unknown): PlatformCookiesResponse {
  const object = asRecord(value, '服务返回的平台会话状态格式无效。')
  assertExactKeys(object, ['schemaVersion', 'platforms'], '平台会话状态字段不完整。')
  assertSchemaVersion(object)
  if (!Array.isArray(object.platforms) || object.platforms.length !== 2) throw new Error('平台会话状态数量无效。')
  const platforms = object.platforms.map((value): PlatformCookieStatus => {
    const item = asRecord(value, '平台会话状态记录格式无效。')
    assertExactKeys(item, ['platform', 'configured', 'updatedAt', 'validationStatus', 'errorCode', 'configurationScript', 'safeCommand'], '平台会话状态记录字段不完整。')
    const platform = stringField(item, 'platform')
    if (platform !== 'douyin' && platform !== 'xiaohongshu') throw new Error('平台会话状态包含未知平台。')
    const validationStatus = stringField(item, 'validationStatus')
    if (!['valid', 'missing', 'invalid', 'error'].includes(validationStatus)) throw new Error('平台会话校验状态无效。')
    const errorCode = item.errorCode
    if (errorCode !== null && typeof errorCode !== 'string') throw new Error('平台会话错误码格式无效。')
    const safeCommand = nonEmptyStringField(item, 'safeCommand')
    if (!safeCommand.includes('save_platform_cookie_secret.py') || /--input-file|cookie=/i.test(safeCommand)) throw new Error('平台会话配置命令不安全。')
    return {
      platform,
      configured: booleanField(item, 'configured'),
      updatedAt: nullableDateField(item, 'updatedAt'),
      validationStatus: validationStatus as PlatformCookieStatus['validationStatus'],
      errorCode,
      configurationScript: nonEmptyStringField(item, 'configurationScript'),
      safeCommand,
    }
  })
  if (new Set(platforms.map((item) => item.platform)).size !== platforms.length) throw new Error('平台会话状态包含重复平台。')
  return { schemaVersion: SCHEMA_VERSION, platforms }
}

function parseMutationReceipt(value: unknown): MutationReceipt {
  const object = asRecord(value, '服务返回的操作回执格式无效。')
  assertExactKeys(object, ['schemaVersion', 'revision', 'ok', 'updatedAt'], '操作回执字段不完整。')
  assertSchemaVersion(object)
  if (object.ok !== true) throw new Error('服务端没有确认操作成功。')
  return { schemaVersion: SCHEMA_VERSION, revision: integerField(object, 'revision'), ok: true, updatedAt: dateField(object, 'updatedAt') }
}

function assertSchemaVersion(object: Record<string, unknown>) {
  if (object.schemaVersion !== SCHEMA_VERSION) throw new Error('服务返回的结构版本不受支持。')
}

function assertExactKeys(object: Record<string, unknown>, keys: string[], message: string) {
  const actual = Object.keys(object)
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) throw new Error(message)
}

function asRecord(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(message)
  return value as Record<string, unknown>
}

function stringField(object: Record<string, unknown>, key: string): string {
  const value = object[key]
  if (typeof value !== 'string') throw new Error('服务返回的字段 ' + key + ' 格式无效。')
  return value
}

function nonEmptyStringField(object: Record<string, unknown>, key: string): string {
  const value = stringField(object, key)
  if (!value.trim()) throw new Error('服务返回的字段 ' + key + ' 为空。')
  return value
}

function booleanField(object: Record<string, unknown>, key: string): boolean {
  const value = object[key]
  if (typeof value !== 'boolean') throw new Error('服务返回的字段 ' + key + ' 格式无效。')
  return value
}

function integerField(object: Record<string, unknown>, key: string): number {
  const value = object[key]
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('服务返回的字段 ' + key + ' 格式无效。')
  return value
}

function dateField(object: Record<string, unknown>, key: string): string {
  const value = stringField(object, key)
  if (Number.isNaN(new Date(value).getTime())) throw new Error('服务返回的字段 ' + key + ' 日期无效。')
  return value
}

function nullableDateField(object: Record<string, unknown>, key: string): string | null {
  const value = object[key]
  if (value === null) return null
  if (typeof value !== 'string' || Number.isNaN(new Date(value).getTime())) throw new Error('服务返回的字段 ' + key + ' 日期无效。')
  return value
}

function cursorField(object: Record<string, unknown>, key: string): string | null {
  const value = object[key]
  if (value === null) return null
  if (typeof value !== 'string' || !CURSOR_PATTERN.test(value)) throw new Error('服务返回的分页游标无效。')
  return value
}

function describeError(error: unknown): string {
  // Both the generic fallback and the conflict branch transparently surface the server's own
  // message (already guaranteed Chinese-safe by mediaProductHttpTransport's public error
  // table) with their own fallback text, so those two are computed before dispatch rather
  // than passed as fixed strings.
  const fallback =
    error instanceof BusinessOperationError
      ? error.message || '服务端请求失败。'
      : error instanceof Error
        ? error.message
        : '服务端请求失败。'
  return describeBusinessError(error, {
    fallback,
    unauthorized: '当前会话已失效，请重新登录。',
    forbidden: '当前会话无权执行此操作。',
    conflict: error instanceof BusinessOperationError ? error.message || '服务端检测到修订或幂等冲突。' : '服务端检测到修订或幂等冲突。',
  })
}
