import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
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
  LayoutDashboard,
  LogIn,
  LogOut,
  Menu,
  Moon,
  PenTool,
  Plus,
  Search,
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
import { loginUrl, logoutMediaSession } from './mediaWebApi'
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
import PersonalWorkspaceShellPage from './PersonalWorkspaceShellPage'
import WorkspaceShellPage from './WorkspaceShellPage'


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

const ordinaryNavigation: readonly NavigationGroup[] = [
  {
    label: '核心工作区',
    items: [
      { path: '/today', label: '今日工作台', detail: '下一步与截止事项', icon: LayoutDashboard },
      { path: '/studio', label: 'Studio', detail: '脚本、分镜与交付', icon: PenTool },
      { path: '/campaigns', label: 'Campaigns', detail: '活动与商单履约', icon: BriefcaseBusiness },
      { path: '/business', label: 'Business', detail: '报价、档期与商机', icon: CircleDollarSign },
      { path: '/desk', label: 'Desk', detail: '情报、拆解与增长', icon: Sparkles },
    ],
  },
  {
    label: '资源与执行',
    items: [
      { path: '/assets', label: '素材库', detail: '原始素材与证据', icon: Images },
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
  { label: '个人工作区', items: [{ path: '/workspace', label: '个人云端成果', icon: Cloud }] },
]

const organizationNavigation: readonly NavigationGroup[] = [
  { label: '组织工作区', items: [{ path: '/organization-workspace', label: '组织工作区', icon: Cloud }] },
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
  const { resolved: theme, toggle: toggleTheme } = useThemePreference()
  const [query, setQuery] = useState('')
  const location = useLocation()
  const navigate = useNavigate()

  const isAdmin = session?.role === 'admin'
  const isPersonal = session?.workspaceMode === 'personal_web'
  const isOrganization = session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark'
  const isAdminShell = isAdmin && !isOrganization
  const navigation = isPersonal
    ? personalNavigation
    : isOrganization
      ? organizationNavigation
      : isAdminShell
        ? adminNavigation
        : ordinaryNavigation
  const flatNavigation = useMemo(() => navigation.flatMap((group) => group.items), [navigation])
  const current = currentNavigationItem(location.pathname, flatNavigation)
  const CurrentIcon = current?.icon ?? LayoutDashboard
  const defaultRoute = isPersonal
    ? '/workspace'
    : isOrganization
      ? '/organization-workspace'
      : isAdminShell
        ? '/admin/overview'
        : '/today'
  const activeTasks = tasks.filter((task) => !task.terminal)
  const searchMatches = query.trim()
    ? flatNavigation.filter((item) => `${item.label} ${item.detail ?? ''}`.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 6)
    : []

  useEffect(() => {
    setMenuOpen(false)
    setAccountOpen(false)
    setSearchOpen(false)
    setQuery('')
  }, [location.pathname])

  function submitSearch(event: FormEvent) {
    event.preventDefault()
    if (searchMatches[0]) navigate(searchMatches[0].path)
  }

  return (
    <div className={`media-shell studio-shell ${isAdminShell ? 'is-admin-shell' : isPersonal ? 'is-personal-shell' : isOrganization ? 'is-organization-shell' : 'is-ordinary-shell'}`}>
      <aside className={`media-sidebar studio-sidebar ${menuOpen ? 'is-open' : ''}`}>
        <div className="studio-brand">
          <div className="studio-brand-mark">MC</div>
          <div className="studio-brand-copy">
            <strong>MediaClaw</strong>
            <span>{isAdminShell ? '平台治理控制台' : isPersonal ? '个人内容资产' : isOrganization ? '组织协作工作区' : 'AI 内容生产工作台'}</span>
          </div>
        </div>

        {!isAdminShell && !isPersonal && !isOrganization ? (
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
          <button className="studio-account-button" type="button" aria-label="账户菜单" aria-expanded={accountOpen} onClick={() => setAccountOpen((value) => !value)}>
            <Settings size={17} /><ChevronDown size={14} />
          </button>
          {accountOpen ? (
            <div className="studio-account-popover" role="menu">
              <button type="button" role="menuitem" onClick={() => session && void logout(session)}><LogOut size={15} />退出登录</button>
            </div>
          ) : null}
        </div>
      </aside>

      {menuOpen ? <button className="sidebar-scrim" aria-label="关闭导航" onClick={() => setMenuOpen(false)} /> : null}

      <div className="media-workspace studio-workspace">
        <header className="media-topbar studio-topbar">
          <button className="icon-button menu-button" type="button" aria-label="打开导航" onClick={() => setMenuOpen((value) => !value)}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <div className="studio-breadcrumb"><CurrentIcon size={17} /><span>MediaClaw</span><b>/</b><strong>{current?.label ?? '工作台'}</strong></div>
          {!isPersonal && !isOrganization ? (
            <div className="studio-topbar-actions">
              <div className="studio-search-wrap">
                <form className="studio-search topbar-search" role="search" onSubmit={submitSearch}>
                  <Search size={17} />
                  <input aria-label="搜索工作区" value={query} onFocus={() => setSearchOpen(true)} onChange={(event) => { setQuery(event.target.value); setSearchOpen(true) }} placeholder="搜索 Studio、商单或素材…" />
                  <kbd>⌘K</kbd>
                </form>
                {searchOpen && query.trim() ? (
                  <div className="studio-search-results" role="listbox">
                    {searchMatches.length ? searchMatches.map((item) => { const Icon = item.icon; return <button type="button" key={item.path} onClick={() => navigate(item.path)}><Icon size={16} /><span><strong>{item.label}</strong><small>{item.detail}</small></span></button> }) : <p>没有匹配的工作区</p>}
                  </div>
                ) : null}
              </div>
              <button className="studio-command-button studio-theme-toggle" type="button"
                aria-label={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}
                title={theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'}
                onClick={toggleTheme}>{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
              <button className="studio-command-button topbar-command" type="button" aria-label="新建任务" onClick={() => openWorkspace()}><Command size={17} /><span>任务中心</span>{activeTasks.length ? <b>{activeTasks.length}</b> : null}</button>
              {!isAdminShell ? <button className="studio-primary-button" type="button" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}><Plus size={17} /><span>新建内容项目</span></button> : null}
            </div>
          ) : null}
        </header>

        <div className="media-content studio-content">
          <Routes>
            <Route path="/" element={<Navigate to={defaultRoute} replace />} />
            <Route path="/today" element={ordinaryRoute(<WorkboardPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/studio" element={ordinaryRoute(<RunsPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/runs" element={<Navigate to="/studio" replace />} />
            <Route path="/runs/:runId" element={ordinaryRoute(<CreationRunDetailPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/studio/:runId" element={ordinaryRoute(<CreationRunDetailPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/campaigns" element={ordinaryRoute(<CampaignsPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/business" element={ordinaryRoute(<BusinessPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/desk" element={ordinaryRoute(<DeskPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/overview" element={ordinaryRoute(<OverviewPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/tracks" element={ordinaryRoute(<TracksPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/assets" element={ordinaryRoute(<AssetsPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/decisions" element={ordinaryRoute(<DecisionsPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/publishing" element={ordinaryRoute(<PublishingPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/reviews" element={ordinaryRoute(<ReviewsPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/media-agent" element={ordinaryRoute(<MediaAgentPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/archives" element={ordinaryRoute(<ArchivesPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/usage-billing" element={ordinaryRoute(<UsageBillingPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/invites" element={ordinaryRoute(<InvitesPage />, isPersonal, isOrganization, isAdminShell, defaultRoute)} />
            <Route path="/workspace" element={<WorkspaceShellPage />} />
            <Route path="/workspace/preview/:artifactId" element={isPersonal ? <PersonalWorkspaceShellPage /> : <Navigate to="/workspace" replace />} />
            <Route path="/organization-workspace" element={isOrganization ? <OrganizationWorkspaceShellPage /> : <Navigate to={defaultRoute} replace />} />
            <Route path="/admin/overview" element={isAdminShell ? <AdminOverviewPage /> : <Navigate to={defaultRoute} replace />} />
            <Route path="/admin/access" element={isAdminShell ? <AdminAccessPage /> : <Navigate to={defaultRoute} replace />} />
            <Route path="/admin/tenants" element={isAdminShell ? <AdminTenantsPage /> : <Navigate to={defaultRoute} replace />} />
            <Route path="/admin/billing" element={isAdminShell ? <AdminBillingPage /> : <Navigate to={defaultRoute} replace />} />
            <Route path="/admin/upstreams" element={isAdminShell ? <AdminUpstreamsPage /> : <Navigate to={defaultRoute} replace />} />
            <Route path="*" element={<Navigate to={defaultRoute} replace />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

function ordinaryRoute(element: ReactNode, isPersonal: boolean, isOrganization: boolean, isAdminShell: boolean, defaultRoute: string) {
  return isPersonal || isOrganization || isAdminShell ? <Navigate to={defaultRoute} replace /> : element
}

function currentNavigationItem(pathname: string, items: readonly NavigationItem[]): NavigationItem | undefined {
  if (pathname.startsWith('/runs/')) return items.find((item) => item.path === '/studio')
  return items.find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`)) ?? items[0]
}

function navigationAliasActive(pathname: string, itemPath: string): boolean {
  return itemPath === '/studio' && pathname.startsWith('/runs/')
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
