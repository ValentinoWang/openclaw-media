import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import {
  Archive,
  ArrowLeft,
  Bot,
  BriefcaseBusiness,
  ChevronDown,
  CircleDollarSign,
  Cloud,
  Command,
  CreditCard,
  Database,
  Gauge,
  Images,
  Lightbulb,
  LayoutDashboard,
  LogIn,
  LogOut,
  Menu,
  Moon,
  PenTool,
  Plus,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  TrendingUp,
  UserRoundCog,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import CreationRunDetailPage from './CreationRunDetailPage'
import { MediaWebProvider, useMediaWeb } from './MediaWebWorkspace'
import { loginUrl, logoutMediaSession, type MediaWebSession } from './mediaWebApi'
import AdminAccessPage from './pages/admin/AdminAccessPage'
import AdminBillingPage from './pages/admin/AdminBillingPage'
import AdminOverviewPage from './pages/admin/AdminOverviewPage'
import AdminTenantsPage from './pages/admin/AdminTenantsPage'
import AdminUpstreamsPage from './pages/admin/AdminUpstreamsPage'
import ArchivesPage from './pages/ordinary/ArchivesPage'
import AssetsPage from './pages/ordinary/AssetsPage'
import BusinessPage from './studio/BusinessPage'
import CampaignsPage from './studio/CampaignsPage'
import DecisionsPage from './pages/ordinary/DecisionsPage'
import DeskPage from './studio/DeskPage'
import InvitesPage from './pages/ordinary/InvitesPage'
import MediaAgentPage from './pages/ordinary/MediaAgentPage'
import OverviewPage from './pages/ordinary/OverviewPage'
import PublishingPage from './pages/ordinary/PublishingPage'
import ReviewsPage from './pages/ordinary/ReviewsPage'
import RunsPage from './pages/ordinary/RunsPage'
import TracksPage from './pages/ordinary/TracksPage'
import UsageBillingPage from './pages/ordinary/UsageBillingPage'
import WorkboardPage from './studio/WorkboardPage'
import OrganizationWorkspaceShellPage from './OrganizationWorkspaceShellPage'
import OrganizationDocumentMirrorPage from './OrganizationDocumentMirrorPage'
import PersonalWorkspaceShellPage from './PersonalWorkspaceShellPage'
import DocumentEditorPage from './pages/ordinary/DocumentEditorPage'
import WorkspaceShellPage from './WorkspaceShellPage'
import {
  resolveStudioRouteOutcome,
  resolveStudioRoutePolicy,
  type StudioRoutePolicy,
  type StudioShell,
} from './mediaStudioRoutePolicy'

type NavigationItem = {
  path: string
  label: string
  detail?: string
  icon: LucideIcon
  badge?: string
}

type NavigationGroup = {
  label: string
  items: readonly NavigationItem[]
}

type StudioAccent = 'studio' | 'campaign' | 'business' | 'desk' | 'agent' | 'archive'

const ordinaryNavigation: readonly NavigationGroup[] = [
  {
    label: '核心工作区',
    items: [
      { path: '/today', label: '今日工作台', detail: '下一步与截止事项', icon: LayoutDashboard },
      { path: '/studio', label: 'Studio', detail: '脚本、分镜与交付', icon: PenTool },
      { path: '/campaigns', label: 'Campaigns', detail: '活动与商单履约', icon: BriefcaseBusiness },
      { path: '/business', label: 'Business', detail: '报价、档期与商机', icon: CircleDollarSign },
      { path: '/desk', label: 'Desk', detail: '情报、拆解与增长', icon: Sparkles },
      { path: '/overview', label: '概览', detail: '项目状态与下一步', icon: LayoutDashboard },
    ],
  },
  {
    label: '资源与执行',
    items: [
      { path: '/assets', label: '素材库', detail: '原始素材与证据', icon: Images },
      { path: '/tracks', label: '账号与赛道', detail: '自有账号与监控', icon: Users },
      { path: '/decisions', label: '选题与决策', detail: '证据、候选与人工状态', icon: Lightbulb },
      { path: '/publishing', label: '发布交付', detail: '发布准备与渠道交付', icon: Send },
      { path: '/reviews', label: '复盘洞察', detail: '发布数据与账号学习', icon: TrendingUp },
      { path: '/media-agent', label: 'Agent 任务', detail: '本机执行与人工确认', icon: Bot },
      { path: '/archives', label: '云端归档', detail: '成果与历史记录', icon: Archive },
    ],
  },
  {
    label: '账户',
    items: [
      { path: '/usage-billing', label: '用量与余额', icon: CreditCard },
      { path: '/invites', label: '团队邀请', icon: Users },
    ],
  },
]

const adminNavigation: readonly NavigationGroup[] = [
  {
    label: '平台治理',
    items: [
      { path: '/admin/overview', label: '平台总览', icon: Gauge },
      { path: '/admin/access', label: '用户与准入', icon: UserRoundCog },
      { path: '/admin/tenants', label: '租户资源', icon: Database },
      { path: '/admin/billing', label: '计费运营', icon: CircleDollarSign },
      { path: '/admin/upstreams', label: '上游服务', icon: Server },
    ],
  },
]

const personalNavigation: readonly NavigationGroup[] = [
  ...ordinaryNavigation,
  { label: '个人工作区', items: [{ path: '/workspace', label: '个人云端成果', icon: Cloud }] },
]

const organizationNavigation: readonly NavigationGroup[] = [
  {
    label: '组织工作区',
    items: [
      { path: '/organization-workspace', label: '组织工作区', icon: Cloud },
      { path: '/tracks', label: '账号与赛道', detail: '自有账号与监控', icon: Users },
    ],
  },
]

/** 主题偏好：未显式选择时跟随系统（不打 data-theme 标记）。
 *  localStorage 在隐私模式下会抛异常，读写都必须包 try/catch。 */
function useThemePreference() {
  const [theme, setTheme] = useState<'light' | 'dark' | null>(() => {
    try {
      const stored = localStorage.getItem('mg-theme')
      return stored === 'light' || stored === 'dark' ? stored : null
    } catch {
      return null
    }
  })
  useEffect(() => {
    const root = document.documentElement
    if (theme) root.dataset.theme = theme
    else delete root.dataset.theme
    try {
      if (theme) localStorage.setItem('mg-theme', theme)
      else localStorage.removeItem('mg-theme')
    } catch {
      /* 隐私模式：仅当前会话生效 */
    }
  }, [theme])
  const resolved = theme ?? (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  return { resolved, toggle: () => setTheme(resolved === 'dark' ? 'light' : 'dark') }
}

export default function MediaStudioApp() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}>
      <MediaWebProvider>
        <AppGate />
      </MediaWebProvider>
    </BrowserRouter>
  )
}

function AppGate() {
  const { runtimeState, session } = useMediaWeb()
  if (runtimeState === 'checking') return <LoadingState />
  if (runtimeState === 'unauthenticated') {
    return (
      <StandaloneState
        icon={<ShieldCheck size={25} />}
        title="登录后进入内容生产工作台"
        detail="脚本、分镜、商单与账号数据只对当前账户开放。"
        action={<a className="primary-button" href={loginUrl()}><LogIn size={16} />登录或注册</a>}
      />
    )
  }
  if (runtimeState === 'unavailable' || !session) {
    return <StandaloneState icon={<Bot size={25} />} title="工作台暂时不可用" detail="身份服务或任务服务尚未就绪。" />
  }
  return <ProductShell />
}

function ProductShell() {
  const { session, tasks, openWorkspace } = useMediaWeb()
  const [menuOpen, setMenuOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedSearchIndex, setSelectedSearchIndex] = useState(0)
  const { resolved: theme, toggle: toggleTheme } = useThemePreference()
  const [query, setQuery] = useState('')
  const location = useLocation()
  const navigate = useNavigate()

  const authenticatedSession = requireAuthenticatedSession(session)
  const routePolicy = resolveStudioRoutePolicy(authenticatedSession)
  const sessionScope = JSON.stringify([authenticatedSession.publicUserId, authenticatedSession.workspaceMode, authenticatedSession.bodyAuthority, authenticatedSession.role, authenticatedSession.csrfToken])
  const isAdminShell = routePolicy.shell === 'admin'
  const isPersonal = routePolicy.shell === 'personal'
  const isOrganization = routePolicy.shell === 'organization'
  const navigationByShell: Record<StudioShell, readonly NavigationGroup[]> = {
    admin: adminNavigation,
    personal: personalNavigation,
    organization: organizationNavigation,
  }
  const navigation = navigationByShell[routePolicy.shell]
  const flatNavigation = useMemo(() => navigation.flatMap((group) => group.items), [navigation])
  const visibleNavigationItemCount = flatNavigation.length
  const isCompactNavigation = visibleNavigationItemCount < 3 && routePolicy.navigationMode === 'compact'
  const current = currentNavigationItem(location.pathname, flatNavigation)
  const CurrentIcon = current?.icon ?? LayoutDashboard
  const defaultRoute = routePolicy.defaultRoute
  const activeTasks = tasks.filter((task) => !task.terminal)
  const searchMatches = query.trim()
    ? flatNavigation.filter((item) => `${item.label} ${item.detail ?? ''}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 6)
    : []
  const selectedSearchMatch = searchMatches[selectedSearchIndex]
  const shellAccent = studioAccentForPath(location.pathname)

  useEffect(() => {
    setMenuOpen(false)
    setAccountOpen(false)
    setSearchOpen(false)
    setQuery('')
    setSelectedSearchIndex(0)
  }, [location.pathname])

  function submitSearch(event: FormEvent) {
    event.preventDefault()
    selectSearchMatch(selectedSearchIndex)
  }

  function selectSearchMatch(index: number) {
    const match = searchMatches[index]
    if (!match) return
    setSearchOpen(false)
    navigate(match.path)
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      setSearchOpen(false)
      setSelectedSearchIndex(0)
      return
    }
    if (!searchMatches.length) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setSearchOpen(true)
      setSelectedSearchIndex((current) => {
        const offset = event.key === 'ArrowDown' ? 1 : -1
        return (current + offset + searchMatches.length) % searchMatches.length
      })
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      selectSearchMatch(selectedSearchIndex)
    }
  }

  return (
    <div className={`media-shell studio-shell ${isAdminShell ? 'is-admin-shell' : isPersonal ? 'is-personal-shell' : isOrganization ? 'is-organization-shell' : 'is-ordinary-shell'} ${isCompactNavigation ? 'is-compact-navigation' : ''}`} data-accent={shellAccent}>
      <aside id="studio-mobile-navigation" className={`media-sidebar studio-sidebar ${menuOpen ? 'is-open' : ''}`}>
        <NavLink className="studio-brand" to={defaultRoute} aria-label="MediaClaw 工作台" title="MediaClaw 工作台">
          <div className="studio-brand-mark">MC</div>
          <div className="studio-brand-copy">
            <strong>MediaClaw</strong>
            <span>{isAdminShell ? '平台治理控制台' : isPersonal ? '个人内容资产' : isOrganization ? '组织协作工作区' : 'AI 内容生产工作台'}</span>
          </div>
        </NavLink>

        {!isAdminShell && !isOrganization ? (
          <div className="studio-workspace-card">
            <span>当前工作区</span>
            <strong>Creator Studio</strong>
            <small><i />真实项目 · 可编辑活稿</small>
          </div>
        ) : null}

        <nav className="studio-navigation" aria-label="主导航">
          {navigation.map((group) => (
            <section className="studio-nav-group" key={group.label} aria-labelledby={`studio-nav-${group.label}`}>
              <h2 id={`studio-nav-${group.label}`}>{group.label}</h2>
              <div>
                {group.items.map((item) => {
                  const Icon = item.icon
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      aria-label={item.detail ? `${item.label}：${item.detail}` : item.label}
                      title={item.label}
                      className={({ isActive }) => isActive || navigationAliasActive(location.pathname, item.path) ? 'studio-nav-link active' : 'studio-nav-link'}
                    >
                      <span className="studio-nav-icon"><Icon size={18} /></span>
                      <span className="studio-nav-copy"><strong>{item.label}</strong>{item.detail ? <small>{item.detail}</small> : null}</span>
                      {item.badge ? <b>{item.badge}</b> : null}
                    </NavLink>
                  )
                })}
              </div>
            </section>
          ))}
        </nav>

        <div className="studio-sidebar-footer">
          {isAdminShell ? <a className="studio-return-link" href="/openclaw/"><ArrowLeft size={16} />返回租户工作台</a> : null}
          <div className="studio-avatar">{isAdminShell ? 'A' : 'MC'}</div>
          <div className="studio-account-copy">
            <strong>{isAdminShell ? '平台管理员' : session?.organizationName || 'MediaClaw 团队'}</strong>
            <span>{isOrganization ? session?.memberRole === 'owner' ? '组织负责人' : '组织成员' : isPersonal ? '个人工作区' : '内容生产成员'}</span>
          </div>
          <button className="studio-account-button" type="button" aria-label="账户菜单" title="账户菜单" aria-haspopup="menu" aria-controls="studio-account-popover" aria-expanded={accountOpen} onClick={() => setAccountOpen((value) => !value)}>
            <Settings size={17} /><ChevronDown size={14} />
          </button>
          {accountOpen ? (
            <div id="studio-account-popover" className="studio-account-popover" role="menu">
              <button type="button" role="menuitem" onClick={() => session && void logout(session)}><LogOut size={15} />退出登录</button>
            </div>
          ) : null}
        </div>
      </aside>

      {menuOpen ? <button className="sidebar-scrim" type="button" aria-label="关闭导航" onClick={() => setMenuOpen(false)} /> : null}

      <div className="media-workspace studio-workspace">
        <header className="media-topbar studio-topbar">
          <button className="icon-button menu-button" type="button" aria-label={menuOpen ? '关闭导航' : '打开导航'} aria-expanded={menuOpen} aria-controls="studio-mobile-navigation" onClick={() => setMenuOpen((value) => !value)}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="studio-breadcrumb"><CurrentIcon size={17} /><span>MediaClaw</span><b>/</b><strong>{current?.label ?? '工作台'}</strong></div>
          {!isOrganization ? (
            <div className="studio-topbar-actions">
              <div className="studio-search-wrap">
                <form className="studio-search topbar-search" role="search" onSubmit={submitSearch}>
                  <Search size={17} />
                  <input aria-label="搜索工作区" aria-haspopup="listbox" aria-controls="studio-search-results" aria-expanded={searchOpen && Boolean(query.trim())} aria-autocomplete="list" aria-activedescendant={searchOpen && selectedSearchMatch ? `studio-search-option-${selectedSearchIndex}` : undefined} value={query} onFocus={() => setSearchOpen(true)} onKeyDown={handleSearchKeyDown} onChange={(event) => { setQuery(event.target.value); setSelectedSearchIndex(0); setSearchOpen(true) }} placeholder="搜索 Studio、商单或素材…" />
                  <kbd>⌘K</kbd>
                </form>
                {searchOpen && query.trim() ? (
                  <div id="studio-search-results" className="studio-search-results" role="listbox" aria-label="工作区搜索结果">
                    {searchMatches.length ? searchMatches.map((item, index) => { const Icon = item.icon; return <button id={`studio-search-option-${index}`} type="button" role="option" aria-selected={selectedSearchIndex === index} key={item.path} onMouseMove={() => setSelectedSearchIndex(index)} onClick={() => selectSearchMatch(index)}><Icon size={16} aria-hidden="true" /><span><strong>{item.label}</strong><small>{item.detail}</small></span></button> }) : <p>没有匹配的工作区</p>}
                  </div>
                ) : null}
              </div>
              <button className="studio-command-button studio-theme-toggle" type="button"
                aria-label={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}
                title={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}
                onClick={toggleTheme}>{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
              <button className="studio-command-button topbar-command" type="button" aria-label="新建任务" onClick={() => openWorkspace()}><Command size={17} /><span>任务中心</span>{activeTasks.length ? <b>{activeTasks.length}</b> : null}</button>
              {!isAdminShell ? <button className="studio-primary-button" type="button" aria-label="新建内容项目" title="新建内容项目" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}><Plus size={17} /><span>新建内容项目</span></button> : null}
            </div>
          ) : null}
        </header>

        <div className="media-content studio-content">
          <Routes key={sessionScope}>
            <Route path="/" element={<Navigate to={defaultRoute} replace />} />
            <Route path="/today" element={ordinaryRoute('/today', <WorkboardPage />, routePolicy)} />
            <Route path="/studio" element={ordinaryRoute('/studio', <RunsPage />, routePolicy)} />
            <Route path="/runs" element={studioAliasRoute(routePolicy)} />
            <Route path="/runs/:runId" element={ordinaryRoute('/runs/:runId', <CreationRunDetailPage />, routePolicy)} />
            <Route path="/studio/:runId" element={ordinaryRoute('/studio/:runId', <CreationRunDetailPage />, routePolicy)} />
            <Route path="/campaigns" element={ordinaryRoute('/campaigns', <CampaignsPage />, routePolicy)} />
            <Route path="/business" element={ordinaryRoute('/business', <BusinessPage />, routePolicy)} />
            <Route path="/desk" element={ordinaryRoute('/desk', <DeskPage />, routePolicy)} />
            <Route path="/overview" element={ordinaryRoute('/overview', <OverviewPage />, routePolicy)} />
            <Route path="/tracks" element={tracksRoute(<TracksPage />, routePolicy)} />
            <Route path="/assets" element={ordinaryRoute('/assets', <AssetsPage />, routePolicy)} />
            <Route path="/decisions" element={ordinaryRoute('/decisions', <DecisionsPage />, routePolicy)} />
            <Route path="/publishing" element={ordinaryRoute('/publishing', <PublishingPage />, routePolicy)} />
            <Route path="/reviews" element={ordinaryRoute('/reviews', <ReviewsPage />, routePolicy)} />
            <Route path="/media-agent" element={ordinaryRoute('/media-agent', <MediaAgentPage />, routePolicy)} />
            <Route path="/archives" element={ordinaryRoute('/archives', <ArchivesPage />, routePolicy)} />
            <Route path="/usage-billing" element={ordinaryRoute('/usage-billing', <UsageBillingPage />, routePolicy)} />
            <Route path="/invites" element={ordinaryRoute('/invites', <InvitesPage />, routePolicy)} />
            <Route path="/workspace" element={personalRoute('/workspace', <WorkspaceShellPage />, routePolicy)} />
            <Route path="/workspace/preview/:artifactId" element={personalRoute('/workspace/preview/:artifactId', <PersonalWorkspaceShellPage />, routePolicy)} />
            <Route path="/workspace/edit/:artifactId" element={personalRoute('/workspace/edit/:artifactId', <DocumentEditorPage />, routePolicy)} />
            <Route path="/organization-workspace" element={organizationRoute(<OrganizationWorkspaceShellPage />, routePolicy)} />
            <Route path="/organization-workspace/document/:artifactId" element={organizationRoute(<OrganizationDocumentMirrorPage />, routePolicy)} />
            <Route path="/admin/overview" element={adminRoute('/admin/overview', <AdminOverviewPage />, routePolicy)} />
            <Route path="/admin/access" element={adminRoute('/admin/access', <AdminAccessPage />, routePolicy)} />
            <Route path="/admin/tenants" element={adminRoute('/admin/tenants', <AdminTenantsPage />, routePolicy)} />
            <Route path="/admin/billing" element={adminRoute('/admin/billing', <AdminBillingPage />, routePolicy)} />
            <Route path="/admin/upstreams" element={adminRoute('/admin/upstreams', <AdminUpstreamsPage />, routePolicy)} />
            <Route path="*" element={<Navigate to={defaultRoute} replace />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

function ordinaryRoute(pathname: string, element: ReactNode, policy: StudioRoutePolicy) {
  return guardedRoute(pathname, element, policy)
}

function tracksRoute(element: ReactNode, policy: StudioRoutePolicy) {
  return guardedRoute('/tracks', element, policy)
}

function personalRoute(pathname: string, element: ReactNode, policy: StudioRoutePolicy) {
  return guardedRoute(pathname, element, policy)
}

function organizationRoute(element: ReactNode, policy: StudioRoutePolicy) {
  return guardedRoute('/organization-workspace', element, policy)
}

function studioAliasRoute(policy: StudioRoutePolicy) {
  return guardedRoute('/runs', null, policy)
}

function adminRoute(pathname: string, element: ReactNode, policy: StudioRoutePolicy) {
  return guardedRoute(pathname, element, policy)
}

function guardedRoute(pathname: string, element: ReactNode, policy: StudioRoutePolicy) {
  const outcome = resolveStudioRouteOutcome(policy, pathname)
  if (outcome.kind === 'render') return element
  if (outcome.kind === 'forbidden') return <StandaloneState icon={<ShieldCheck size={25} />} title="无权访问此页面" detail="当前会话未获服务端授予该路由权限。" />
  return <Navigate to={outcome.target} replace />
}

function currentNavigationItem(pathname: string, items: readonly NavigationItem[]): NavigationItem | undefined {
  if (pathname === '/runs' || pathname.startsWith('/runs/')) return items.find((item) => item.path === '/studio')
  return items.find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`)) ?? items[0]
}

function navigationAliasActive(pathname: string, itemPath: string): boolean {
  return itemPath === '/studio' && (pathname === '/runs' || pathname.startsWith('/runs/'))
}

function studioAccentForPath(pathname: string): StudioAccent {
  if (pathname === '/campaigns' || pathname === '/decisions' || pathname === '/publishing' || pathname === '/invites' || pathname === '/organization-workspace' || pathname === '/admin/access') return 'campaign'
  if (pathname === '/business' || pathname === '/usage-billing' || pathname === '/admin/billing') return 'business'
  if (pathname === '/desk' || pathname === '/reviews' || pathname === '/tracks' || pathname === '/admin/overview') return 'desk'
  if (pathname === '/media-agent' || pathname === '/admin/upstreams') return 'agent'
  if (pathname === '/archives') return 'archive'
  return 'studio'
}

function LoadingState() {
  return <div className="load-shell" aria-busy="true"><aside className="load-sidebar" /><main className="load-main"><div className="skeleton heading-skeleton" /><div className="skeleton table-skeleton" /></main></div>
}

function StandaloneState({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: string; action?: ReactNode }) {
  return <main className="standalone-state"><div className="state-icon">{icon}</div><h1>{title}</h1><p>{detail}</p>{action}</main>
}

async function logout(session: Parameters<typeof logoutMediaSession>[0]) {
  await logoutMediaSession(session)
  window.location.assign('/openclaw/media/login')
}

function requireAuthenticatedSession(session: MediaWebSession | null): MediaWebSession {
  if (!session) throw new Error('Media Studio rendered without an authenticated session')
  return session
}
