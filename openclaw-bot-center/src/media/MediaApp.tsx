import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  AlertCircle, Archive, ArrowLeft, Bot, CalendarDays, ChevronDown, CircleDollarSign, CircleHelp, Cloud,
  CreditCard, Database, Gauge, Images, KeyRound, LayoutDashboard, Lightbulb,
  LogIn, LogOut, Menu, PenTool, Plus, Search, Send, Server, Settings, ShieldCheck,
  Target, TrendingUp, UserRoundCog, Users, X,
} from 'lucide-react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import CreationRunDetailPage from './CreationRunDetailPage'
import { MediaWebProvider, useMediaWeb } from './MediaWebWorkspace'
import { loginUrl, logoutMediaSession } from './mediaWebApi'
import { adminMediaNav, ordinaryMediaNav, ordinaryMediaNavGroups } from './mediaRoleIa'
import AdminAccessPage from './pages/admin/AdminAccessPage'
import AdminBillingPage from './pages/admin/AdminBillingPage'
import AdminOverviewPage from './pages/admin/AdminOverviewPage'
import AdminTenantsPage from './pages/admin/AdminTenantsPage'
import AdminUpstreamsPage from './pages/admin/AdminUpstreamsPage'
import ArchivesPage from './pages/ordinary/ArchivesPage'
import AssetsPage from './pages/ordinary/AssetsPage'
import DecisionsPage from './pages/ordinary/DecisionsPage'
import InvitesPage from './pages/ordinary/InvitesPage'
import MediaAgentPage from './pages/ordinary/MediaAgentPage'
import OverviewPage from './pages/ordinary/OverviewPage'
import PublishingPage from './pages/ordinary/PublishingPage'
import ReviewsPage from './pages/ordinary/ReviewsPage'
import RunsPage from './pages/ordinary/RunsPage'
import TracksPage from './pages/ordinary/TracksPage'
import UsageBillingPage from './pages/ordinary/UsageBillingPage'
import OrganizationWorkspaceShellPage from './OrganizationWorkspaceShellPage'
import PersonalWorkspaceShellPage from './PersonalWorkspaceShellPage'
import WorkspaceShellPage from './WorkspaceShellPage'

const navIcons = {
  '/overview': LayoutDashboard,
  '/tracks': Target,
  '/assets': Images,
  '/decisions': Lightbulb,
  '/runs': PenTool,
  '/publishing': Send,
  '/reviews': TrendingUp,
  '/media-agent': Bot,
  '/archives': Archive,
  '/usage-billing': CreditCard,
  '/invites': Users,
  '/admin/overview': Gauge,
  '/admin/access': UserRoundCog,
  '/admin/tenants': Database,
  '/admin/billing': CircleDollarSign,
  '/admin/upstreams': Server,
  '/workspace': Cloud,
  '/organization-workspace': Cloud,
} as const

const personalMediaNav = [
  { path: '/workspace', label: '个人云端成果' },
] as const

const organizationMediaNav = [
  { path: '/organization-workspace', label: '组织工作区' },
  { path: '/tracks', label: '账号与赛道' },
] as const

export default function MediaApp() {
  return <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '')}><MediaWebProvider><AppGate /></MediaWebProvider></BrowserRouter>
}

function AppGate() {
  const { runtimeState, session } = useMediaWeb()
  if (runtimeState === 'checking') return <LoadingState />
  if (runtimeState === 'unauthenticated') return <StandaloneState icon={<KeyRound size={24} />} title="需要登录" detail="此工作台仅展示当前账户的数据。" action={<a className="primary-button" href={loginUrl()}><LogIn size={16} />登录或注册</a>} />
  if (runtimeState === 'unavailable' || !session) return <StandaloneState icon={<AlertCircle size={24} />} title="工作台暂时不可用" detail="身份服务或任务服务尚未就绪。" />
  return <ProductShell />
}

function ProductShell() {
  const { session, tasks, openWorkspace } = useMediaWeb()
  const [menuOpen, setMenuOpen] = useState(false)
  const [footerMenuOpen, setFooterMenuOpen] = useState(false)
  const [adminMenuOpen, setAdminMenuOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const isAdmin = session?.role === 'admin'
  const isPersonal = session?.workspaceMode === 'personal_web'
  const isOrganization = session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark'
  const isAdminShell = isAdmin && !isOrganization
  const nav: readonly ShellNavItem[] = isPersonal ? personalMediaNav : isOrganization ? organizationMediaNav : isAdminShell ? adminMediaNav : ordinaryMediaNav
  const current = nav.find((item) => location.pathname.startsWith(item.path)) ?? nav[0]
  const CurrentIcon = navIcons[current.path]
  const defaultRoute = isPersonal ? '/workspace' : isOrganization ? '/organization-workspace' : isAdminShell ? '/admin/overview' : '/overview'
  useEffect(() => { setMenuOpen(false); setFooterMenuOpen(false); setAdminMenuOpen(false) }, [location.pathname])
  function renderNavLink(item: ShellNavItem) {
    const Icon = navIcons[item.path]
    return <NavLink key={item.path} to={item.path}><Icon size={18} /><span>{item.label}</span></NavLink>
  }
  const ordinaryRoute = (element: ReactNode) => isPersonal ? <Navigate to="/workspace" replace /> : isOrganization ? <Navigate to="/organization-workspace" replace /> : isAdminShell ? <Navigate to="/admin/overview" replace /> : element
  return <div className={`media-shell ${isAdminShell ? 'is-admin-shell' : isPersonal ? 'is-personal-shell' : isOrganization ? 'is-organization-shell' : 'is-ordinary-shell'}`}>
    <aside className={`media-sidebar ${menuOpen ? 'is-open' : ''}`}>
      <div className="media-brand"><div className="media-brand-mark">MC</div><div><strong>MediaClaw</strong>{isAdminShell ? <span>平台治理控制台</span> : isPersonal ? <span>个人云端工作区</span> : isOrganization ? <span>组织只读工作区</span> : null}</div></div>
      <nav className="media-nav" aria-label="主导航">{isPersonal
        ? personalMediaNav.map(renderNavLink)
        : isOrganization
          ? organizationMediaNav.map(renderNavLink)
          : isAdminShell
          ? adminMediaNav.map(renderNavLink)
          : ordinaryMediaNavGroups.map((group) => <section className="media-nav-section" key={group.label} aria-labelledby={`nav-${group.label}`}><h2 className="media-nav-heading" id={`nav-${group.label}`}>{group.label}</h2>{group.paths.map((path) => renderNavLink(ordinaryMediaNav.find((item) => item.path === path)!))}</section>)}</nav>
      {isPersonal
        ? <div className="sidebar-foot personal-sidebar-foot"><div className="sidebar-avatar"><Cloud size={20} /></div><div className="sidebar-identity"><strong className="sidebar-team">个人账号</strong><span className="sidebar-role"><i />个人工作区</span></div><button className="sidebar-account-button" type="button" aria-label="账户菜单" title="账户菜单" aria-expanded={footerMenuOpen} onClick={() => setFooterMenuOpen((value) => !value)}><ChevronDown size={16} /><Settings size={18} /></button>{footerMenuOpen ? <div className="sidebar-account-popover" role="menu"><button type="button" role="menuitem" onClick={() => session && void logout(session)}><LogOut size={15} />退出登录</button></div> : null}</div>
        : isOrganization
        ? <div className="sidebar-foot organization-sidebar-foot"><div className="sidebar-avatar"><Cloud size={20} /></div><div className="sidebar-identity"><strong className="sidebar-team" title={session?.organizationName ?? undefined}>{session?.organizationName}</strong><span className="sidebar-role"><i />{session?.memberRole === 'owner' ? '组织负责人' : '组织成员'}</span></div><button className="sidebar-account-button" type="button" aria-label="账户菜单" title="账户菜单" aria-expanded={footerMenuOpen} onClick={() => setFooterMenuOpen((value) => !value)}><ChevronDown size={16} /><Settings size={18} /></button>{footerMenuOpen ? <div className="sidebar-account-popover" role="menu"><button type="button" role="menuitem" onClick={() => session && void logout(session)}><LogOut size={15} />退出登录</button></div> : null}</div>
        : isAdminShell
        ? <div className="sidebar-foot admin-sidebar-foot"><a className="sidebar-return" href="/openclaw/"><ArrowLeft size={17} />返回租户工作台</a><div className="sidebar-role"><ShieldCheck size={18} /><strong>平台管理员</strong></div><button type="button" onClick={() => session && void logout(session)}><LogOut size={17} />退出登录</button></div>
        : <div className="sidebar-foot ordinary-sidebar-foot"><div className="sidebar-avatar">MC</div><div className="sidebar-identity"><strong className="sidebar-team">MediaClaw 团队</strong><span className="sidebar-role"><i />普通使用者</span></div><button className="sidebar-account-button" type="button" aria-label="账户菜单" title="账户菜单" aria-expanded={footerMenuOpen} onClick={() => setFooterMenuOpen((value) => !value)}><ChevronDown size={16} /><Settings size={18} /></button>{footerMenuOpen ? <div className="sidebar-account-popover" role="menu"><button type="button" role="menuitem" onClick={() => session && void logout(session)}><LogOut size={15} />退出登录</button></div> : null}</div>}
    </aside>
    {menuOpen ? <button className="sidebar-scrim" aria-label="关闭导航" onClick={() => setMenuOpen(false)} /> : null}
    <div className="media-workspace">
      <header className="media-topbar">
        <button className="icon-button menu-button" type="button" aria-label="打开导航" onClick={() => setMenuOpen((value) => !value)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>
        <div className="topbar-mobile-title"><CurrentIcon size={17} /><strong>{current.label}</strong></div>
        {isPersonal
          ? <div className="personal-global-toolbar"><span><Cloud size={18} />个人云端成果</span><small><ShieldCheck size={15} />服务端已解析</small></div>
          : isOrganization
          ? <OrganizationGlobalToolbar />
          : isAdminShell
          ? <AdminGlobalToolbar nav={adminMediaNav} onNavigate={(path) => navigate(path)} menuOpen={adminMenuOpen} onMenu={() => setAdminMenuOpen((value) => !value)} onLogout={() => session && void logout(session)} />
          : <OrdinaryGlobalToolbar nav={ordinaryMediaNav} tasks={tasks} onNavigate={(path) => navigate(path)} onOpenTasks={() => openWorkspace()} />}
      </header>
      <div className="media-content"><Routes>
        <Route path="/" element={<Navigate to={defaultRoute} replace />} />
        <Route path="/workspace" element={<WorkspaceShellPage />} />
        <Route path="/workspace/preview/:artifactId" element={isPersonal ? <PersonalWorkspaceShellPage /> : <Navigate to="/workspace" replace />} />
        <Route path="/organization-workspace" element={isOrganization ? <OrganizationWorkspaceShellPage /> : <Navigate to={defaultRoute} replace />} />
        <Route path="/overview" element={ordinaryRoute(<OverviewPage />)} />
        <Route path="/tracks" element={isOrganization ? <TracksPage /> : ordinaryRoute(<TracksPage />)} />
        <Route path="/assets" element={ordinaryRoute(<AssetsPage />)} />
        <Route path="/decisions" element={ordinaryRoute(<DecisionsPage />)} />
        <Route path="/runs" element={ordinaryRoute(<RunsPage />)} />
        <Route path="/runs/:runId" element={ordinaryRoute(<CreationRunDetailPage />)} />
        <Route path="/publishing" element={ordinaryRoute(<PublishingPage />)} />
        <Route path="/reviews" element={ordinaryRoute(<ReviewsPage />)} />
        <Route path="/media-agent" element={ordinaryRoute(<MediaAgentPage />)} />
        <Route path="/archives" element={ordinaryRoute(<ArchivesPage />)} />
        <Route path="/usage-billing" element={ordinaryRoute(<UsageBillingPage />)} />
        <Route path="/invites" element={ordinaryRoute(<InvitesPage />)} />
        <Route path="/admin/overview" element={isPersonal ? <Navigate to="/workspace" replace /> : isOrganization ? <Navigate to="/organization-workspace" replace /> : isAdminShell ? <AdminOverviewPage /> : <Navigate to="/overview" replace />} />
        <Route path="/admin/access" element={isPersonal ? <Navigate to="/workspace" replace /> : isOrganization ? <Navigate to="/organization-workspace" replace /> : isAdminShell ? <AdminAccessPage /> : <Navigate to="/overview" replace />} />
        <Route path="/admin/tenants" element={isPersonal ? <Navigate to="/workspace" replace /> : isOrganization ? <Navigate to="/organization-workspace" replace /> : isAdminShell ? <AdminTenantsPage /> : <Navigate to="/overview" replace />} />
        <Route path="/admin/billing" element={isPersonal ? <Navigate to="/workspace" replace /> : isOrganization ? <Navigate to="/organization-workspace" replace /> : isAdminShell ? <AdminBillingPage /> : <Navigate to="/overview" replace />} />
        <Route path="/admin/upstreams" element={isPersonal ? <Navigate to="/workspace" replace /> : isOrganization ? <Navigate to="/organization-workspace" replace /> : isAdminShell ? <AdminUpstreamsPage /> : <Navigate to="/overview" replace />} />
        <Route path="*" element={<Navigate to={defaultRoute} replace />} />
      </Routes></div>
    </div>
  </div>
}

type ShellNavItem = { path: keyof typeof navIcons; label: string }

type HelpGuide = { title: string; summary: string; whenToUse: string; steps: string[]; details: string[]; notes: string[] }

const pageHelpGuides: Record<string, HelpGuide> = {
  '/overview': {
    title: '总览',
    summary: '从机构当前的真实项目、任务和成果文档中快速找到下一个需要处理的事项。',
    whenToUse: '登录工作台后首先使用本页，或者需要检查项目进度、待决策、待发布和待复盘项时使用。',
    steps: ['先核对当前账户和租户，再查看项目、任务和待办数量。', '从项目列表选择目标项目，核对阶段、最近更新和当前成果。', '机构成果已绑定飞书且链接可用时，点击“打开组织文档”进入飞书编辑。', '需要开始新工作时使用右上角“新建任务”，完成后回到本页检查状态。'],
    details: ['项目阶段：表示项目当前所处的业务阶段，不等同于所有任务都已完成。', '成果文档：Web 展示版本和同步状态；机构文档的正式编辑在飞书中完成。', '待处理数量：只统计当前租户内有权限查看的记录。'],
    notes: ['完成条件：目标项目、当前阶段和下一步动作都已确认。', '没有组织文档入口时，先检查文档同步状态和飞书绑定，不要手工拼接链接。', '页面只读当前租户数据；修改地址参数不会获得其他机构资源。'],
  },
  '/tracks': {
    title: '账号与赛道',
    summary: '管理自有账号、了解赛道运营情况，并持续跟踪值得研究的对标账号。',
    whenToUse: '需要检查自有账号状态、判断赛道布局，或查看对标账号及其关系证据时使用。',
    steps: ['在“自有账号”检查授权、同步和运营赛道。', '在“赛道概览”查看账号布局与平台覆盖。', '从赛道详情带筛选跳转到对应账号列表。', '在“对标账号”核对角色、匹配判断和公开资料凭证。'],
    details: ['账号角色：标杆账号、同赛道观察和合作候选描述研究或合作价值。', '关注状态：待确认、已关注和已忽略只表示管理进度，不替代账号角色。'],
    notes: ['完成条件：目标账号或赛道的当前状态、关系角色和可用证据均已核对。', '缺少负责人、指标或资料凭证时页面明确显示未记录，不自动补全。'],
  },
  '/assets': {
    title: '素材',
    summary: '查看已纳入 Media OS 的素材来源、拆解结果和可回查证据。',
    whenToUse: '选题、创作或拍摄前需要找素材，或者需要核对素材来源时使用。',
    steps: ['使用筛选条件缩小素材范围。', '选择记录后核对类型、平台、来源和处理状态。', '有来源链接时打开原始证据，确认素材与描述一致。', '查看拆解结果后，再决定是否进入选题或创作。'],
    details: ['来源证据：用于回查原始页面或机构文档，不是系统对内容的背书。', '处理状态：区分待处理、已拆解、待人工确认和失败。'],
    notes: ['完成条件：素材来源可回查，且已明确后续用途。', '来源不可读或与描述不一致时，不将其作为已验证证据。'],
  },
  '/decisions': {
    title: '决策',
    summary: '核对选题依据、证据缺口、人工确认状态和下一步动作。',
    whenToUse: '素材已经整理，需要决定是否进入创作、拍摄或商务流程时使用。',
    steps: ['选择目标决策记录。', '查看目标、依据、证据引用和缺失项。', '打开可用的来源链接核对关键信息。', '需要人工判断时明确记录通过、驳回或待补充，再进入下一步。'],
    details: ['决策结果：是对当前证据的业务判断，不是系统自动发布指令。', '证据缺口：存在缺口时应保持待处理，不伪造完整结论。'],
    notes: ['完成条件：关键证据已回查，决策状态和责任人已明确。', '证据不足时补充来源，不要只根据摘要直接进入创作。'],
  },
  '/runs': {
    title: '创作与交付',
    summary: '查看创作任务的来源、决策、执行状态、成果文档和商单交付。',
    whenToUse: '已有选题或 Brief，需要跟踪创作进度、查看输出或打开机构云文档时使用。',
    steps: ['先按状态和日期找到目标运行。', '打开详情，核对来源、决策、流程版本和当前步骤。', '查看输出摘要和成果文档；有合法组织文档链接时进入飞书阅读或编辑。', '商单交付要额外核对客户、版本、交付文档和人工确认。'],
    details: ['运行状态：区分等待、执行中、待确认、完成和失败。', '成果文档：显示修订、正文权威和同步状态；机构正式正文以飞书为准。', '输出摘要：用于快速检查，不替代对完整文档和实际文件的验收。'],
    notes: ['完成条件：运行完成、产物可打开、必要的人工确认已处理。', '组织文档链接不可用时，保留同步异常状态并由机构管理员处理，不使用猜测链接。'],
  },
  '/publishing': {
    title: '发布准备',
    summary: '核对发布内容包、规则检查和人工发布回执。页面只记录人工提供的公开链接，不会自动登录或自动发布。',
    whenToUse: '创作任务已经生成可发布内容，准备在外部平台人工发布之前使用本页。',
    steps: ['先用顶部任务状态和日期范围缩小记录范围；需要重新读取时点击“刷新发布包”。', '在左侧“发布包”列表选择目标记录，并核对标题、任务来源和更新时间，避免选错版本。', '在右侧“发布内容”确认目标平台、内容版本和正文、素材等字段完整；字段缺失时返回创作任务补齐。', '查看“规则检查”。存在未通过项时先修复内容或素材，再重新生成发布包，不要直接进入人工发布。', '在“人工检查”记录标题、正文、素材、链接和平台限制的人工核验结果。', '前往目标平台手工发布；发布成功后返回本页，在“人工发布回执”填写真实公开链接并保存。'],
    details: ['发布内容：说明这份发布包来自哪个任务、面向哪个平台以及当前内容版本。', '规则检查：展示系统规则输出，只用于发现问题，不能替代人工复核。', '人工检查：记录实际检查人、检查结论和需要修正的内容。', '人工发布回执：只填写已经能够公开访问的最终链接，不填写草稿地址、后台编辑地址或示例链接。'],
    notes: ['完成条件：规则检查无阻断项、人工检查完成、公开链接已写入回执。', '左侧没有记录时，依次检查创作任务是否完成、日期筛选是否覆盖任务时间、当前账户是否正确，再点击刷新。', '页面不会自动登录平台或自动发布；外部平台失败时先在平台侧处理，成功后再回来登记回执。', '没有数据时保留双栏空状态，不会填充示例内容。'],
  },
  '/media-agent': {
    title: 'Media Agent',
    summary: '查看本机协作任务、设备状态和需要人工确认的执行结果。',
    whenToUse: '仅适用于已经配置并连接 Media Agent 的本机协作场景：目标 Mac 在线、设备身份可识别，并且你需要查看或处理本机执行任务。',
    steps: ['先检查设备状态，确认目标 Mac 在线并且设备标识与实际机器一致。', '在任务列表选择目标任务，核对任务名称、创建时间和所用流程版本。', '查看执行阶段和状态：等待中表示尚未领取，运行中表示本机正在处理，待确认表示需要人工决定，失败表示需要排查。', '展开任务详情，检查输入描述、当前步骤、输出摘要和错误信息；不要只根据任务标题判断是否成功。', '任务进入待确认后，先在本机检查生成文件，再根据页面提供的确认操作继续或拒绝。', '任务完成后核对最终产物摘要；确实需要云端保存时，再执行明确的归档操作。'],
    details: ['设备状态：在线只表示能够通信，不代表本机依赖、磁盘空间和模型配置全部可用。', '任务状态：以页面最新读取结果为准；长时间不变化时先刷新，再检查本机 Agent。', '流程版本：决定具体处理步骤，复现问题时必须记录流程名称和版本。', '输出摘要：是网页可查看的信息，不等于完整媒体文件；完整文件仍以本机目录为准。'],
    notes: ['完成条件：任务显示完成、本机产物可打开、需要的人工确认已经处理。', '设备离线时先启动本机 Media Agent，并检查网络与设备绑定；不要重复新建相同任务。', '任务失败时记录失败步骤和错误信息，修复本机环境后重试；不要把失败状态当成无结果空状态。', '媒体文件和模型密钥留在本机，网页只展示任务状态和明确归档的产物。'],
  },
  '/usage-billing': {
    title: '用量与余额',
    summary: '查看当前租户的套餐、用量统计和计费状态。',
    whenToUse: '需要确认当前租户可用额度、分析本周期消耗或判断是否需要调整套餐时使用本页。',
    steps: ['先确认页面顶部显示的租户名称，避免在错误的个人或机构工作区查看数据。', '查看当前套餐、计费周期起止时间和套餐状态，确认套餐仍在有效期内。', '读取总额度、已使用量和剩余额度；先看总体比例，再查看具体用量明细。', '按能力、任务或时间核对消耗来源，定位异常增长来自哪个工作流。', '需要调整套餐时，先确认当前账户具有租户管理权限，再按页面提供的操作提交变更。', '完成变更后重新读取页面，确认套餐名称、额度和生效时间已经更新。'],
    details: ['计费周期：所有本期用量都按该时间范围汇总，跨周期数据不能直接相加比较。', '已使用量：来自当前租户内已记录的任务消耗，不包含其他租户。', '剩余额度：用于判断是否还能继续执行任务；接近上限时应先确认高消耗任务。', '套餐状态：生效中、待生效或异常会影响可用额度，不能只看套餐名称。'],
    notes: ['完成条件：确认租户、周期、额度和用量来源；如已变更套餐，还要确认新配置生效。', '数字长时间不更新时先刷新页面并核对计费周期，不要通过重复任务测试额度。', '发现不认识的用量时记录时间、任务和能力名称，再由租户管理员核查。', '用量数据按当前租户和计费周期统计，页面不会混入其他租户数据。'],
  },
  '/reviews': {
    title: '复盘增长',
    summary: '记录真实发布后指标，查看作品、账号和增长摘要。',
    whenToUse: '内容已经人工发布，需要登记表现、归因结果并为后续选题提供证据时使用。',
    steps: ['选择目标作品或账号，核对平台和统计时间。', '填写来自平台后台的真实指标和可回查公开链接。', '保存后检查作品指标、账号指标和增长摘要是否使用同一时间口径。', '将可验证的结论用于下一轮素材或选题，不把猜测写成结论。'],
    details: ['指标快照：必须带有明确统计时间，不同时间快照不直接混合。', '公开链接：用于回查作品，不填写平台后台编辑地址。', '增长摘要：是对已登记指标的归纳，不是系统自动发布策略。'],
    notes: ['完成条件：时间口径、原始指标、公开链接和复盘结论均可回查。', '指标缺失时保留空值并说明原因，不用估算值代替平台真实数据。'],
  },
  '/archives': {
    title: '云端归档',
    summary: '查看已明确归档的任务描述符、运行结果和删除计划。',
    whenToUse: '任务完成后需要查找历史记录，或者在明确授权下进行归档删除时使用。',
    steps: ['按任务、设备或时间查找归档。', '打开详情并核对归档标识、流程版本、摘要和完整性状态。', '需要删除时先生成并检查删除计划，确认精确目标后再执行。', '执行后重新读取列表，确认目标已不可读且其他归档未受影响。'],
    details: ['归档描述符：页面展示的是可检索元数据，不等同于完整本机媒体文件。', '删除计划：必须先明确目标和影响范围，不接受模糊批量删除。'],
    notes: ['完成条件：归档记录可以打开；如执行删除，还必须确认删除结果。', '页面不保证本机文件仍存在，需要完整产物时应同时在目标 Mac 上检查。'],
  },
  '/invites': {
    title: '成员邀请',
    summary: '创建和管理当前租户的成员邀请码，并检查使用状态。',
    whenToUse: '租户 Owner 或有权限的管理员需要邀请新成员进入当前工作区时使用。',
    steps: ['先确认当前租户和拟邀请对象。', '按实际需求创建邀请码，不要预先大量生成。', '点击“复制邀请码”，成功后只通过受控渠道发给指定成员。', '成员注册后返回本页检查邀请码是否已使用或失效。'],
    details: ['邀请码状态：区分可用、已使用、已过期和已撤销。', '租户成员：邀请只建立当前租户的成员关系，不会授予平台管理员权限。'],
    notes: ['完成条件：新成员已注册并只能访问所属租户数据。', '浏览器拒绝剪贴板权限时，页面会提示手工选择；不会把失败的复制操作报告为成功。', '邀请码疑似泄露时立即撤销并创建新码。'],
  },
}

function pageHelpGuide(pathname: string, nav: readonly ShellNavItem[]): HelpGuide {
  const match = Object.entries(pageHelpGuides).find(([path]) => pathname.startsWith(path))
  if (match) return match[1]
  const current = nav.find((item) => pathname.startsWith(item.path))
  return { title: current?.label ?? 'MediaClaw', summary: '查看当前页面的真实数据并按页面状态完成操作。', whenToUse: '需要查看或处理当前页面对应的业务记录时使用。', steps: ['先阅读页面摘要和当前状态。', '选择需要查看或处理的记录。', '完成操作后检查页面反馈。'], details: ['页面字段以当前账户和当前租户的真实数据为准。'], notes: ['页面只展示当前账户有权限访问的数据。'] }
}

function OrganizationGlobalToolbar() {
  return <div className="organization-global-toolbar" aria-label="组织工作区状态"><span><Cloud size={18} />组织资源</span><small><ShieldCheck size={15} />只读状态</small></div>
}

function OrdinaryGlobalToolbar({ nav, tasks, onNavigate, onOpenTasks }: { nav: readonly ShellNavItem[]; tasks: ReturnType<typeof useMediaWeb>['tasks']; onNavigate: (path: string) => void; onOpenTasks: () => void }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'all' | 'active' | 'confirmation'>('all')
  const [startDate, setStartDate] = useState(() => relativeIsoDate(-7))
  const [endDate, setEndDate] = useState(() => relativeIsoDate(0))
  const [helpOpen, setHelpOpen] = useState(false)
  const location = useLocation()
  const guide = pageHelpGuide(location.pathname, nav)
  const normalized = query.trim().toLocaleLowerCase('zh-CN')
  const pageMatches = useMemo(() => normalized ? nav.filter((item) => item.label.toLocaleLowerCase('zh-CN').includes(normalized)).slice(0, 4) : [], [nav, normalized])
  const taskMatches = useMemo(() => {
    if (!normalized) return []
    return tasks.filter((task) => {
      const haystack = `${task.summary} ${task.capabilityPath.join(' ')}`.toLocaleLowerCase('zh-CN')
      const taskDate = (task.updatedAt || task.createdAt).slice(0, 10)
      const statusMatches = status === 'all' || (status === 'active' ? !task.terminal : task.confirmation.state === 'required')
      return haystack.includes(normalized) && statusMatches && taskDate >= startDate && taskDate <= endDate
    }).slice(0, 4)
  }, [endDate, normalized, startDate, status, tasks])
  function submit(event: FormEvent) {
    event.preventDefault()
    if (pageMatches[0]) onNavigate(pageMatches[0].path)
    else if (taskMatches[0]) onOpenTasks()
  }
  return <div className="ordinary-global-toolbar">
    <form className="topbar-search" role="search" aria-label="全局搜索" onSubmit={submit}><Search size={20} /><input aria-label="搜索页面和任务" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索页面和任务..." />{normalized ? <div className="topbar-search-results" role="listbox">{pageMatches.map((item) => <button type="button" key={item.path} onClick={() => onNavigate(item.path)}>{item.label}<span>页面</span></button>)}{taskMatches.map((task) => <button type="button" key={task.taskId} onClick={onOpenTasks}>{task.summary}<span>任务</span></button>)}{!pageMatches.length && !taskMatches.length ? <p>没有匹配结果</p> : null}</div> : null}</form>
    <label className="topbar-task-status"><span className="sr-only">任务状态</span><select aria-label="任务状态" value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="all">任务状态：全部</option><option value="active">任务状态：进行中</option><option value="confirmation">任务状态：待确认</option></select></label>
    <div className="topbar-date-range"><CalendarDays size={18} /><label><span className="sr-only">开始日期</span><input type="date" aria-label="开始日期" value={startDate} max={endDate} onChange={(event) => setStartDate(event.target.value)} /></label><span>至</span><label><span className="sr-only">结束日期</span><input type="date" aria-label="结束日期" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>
    <button className="topbar-command" type="button" onClick={onOpenTasks}><Plus size={18} /><span>新建任务</span>{tasks.some((task) => !task.terminal) ? <b>{tasks.filter((task) => !task.terminal).length}</b> : null}</button>
    <div className="topbar-help-wrap">
      <button className="topbar-help" type="button" aria-label="使用帮助" title="使用帮助" aria-expanded={helpOpen} onClick={() => setHelpOpen((value) => !value)}><CircleHelp size={21} /></button>
      {helpOpen ? <div className="help-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setHelpOpen(false) }}>
        <section className="help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-dialog-title">
          <header className="help-dialog-header"><div><span>页面使用说明</span><h1 id="help-dialog-title">{guide.title}</h1></div><button className="icon-button" type="button" aria-label="关闭使用帮助" onClick={() => setHelpOpen(false)}><X size={20} /></button></header>
          <article className="help-markdown"><p className="help-lead">{guide.summary}</p><h2>适用条件</h2><p>{guide.whenToUse}</p><h2>操作步骤</h2><ol>{guide.steps.map((step) => <li key={step}>{step}</li>)}</ol><h2>字段与状态</h2><ul>{guide.details.map((detail) => <li key={detail}>{detail}</li>)}</ul><h2>完成条件与异常处理</h2><ul>{guide.notes.map((note) => <li key={note}>{note}</li>)}</ul></article>
        </section>
      </div> : null}
    </div>
  </div>
}

function AdminGlobalToolbar({ nav, onNavigate, menuOpen, onMenu, onLogout }: { nav: readonly ShellNavItem[]; onNavigate: (path: string) => void; menuOpen: boolean; onMenu: () => void; onLogout: () => void }) {
  const [query, setQuery] = useState('')
  const matches = nav.filter((item) => item.label.includes(query.trim()))
  function submit(event: FormEvent) {
    event.preventDefault()
    if (query.trim() && matches[0]) onNavigate(matches[0].path)
  }
  return <div className="admin-global-toolbar">
    <form className="topbar-search topbar-governance-search" role="search" aria-label="治理搜索" onSubmit={submit}><Search size={20} /><input aria-label="搜索治理页面" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索治理对象（租户、用户、资源、审计等）" /></form>
    <div className="topbar-scope"><i />当前作用域：全局视图 <span>跨租户读取需显式目标</span></div>
    <div className="topbar-target">目标租户：<strong>页面内选择</strong></div>
    <div className="topbar-admin-account"><button type="button" aria-label="管理员账户" aria-expanded={menuOpen} onClick={onMenu}><span>A</span>平台管理员<ChevronDown size={16} /></button>{menuOpen ? <div className="topbar-account-popover" role="menu"><button type="button" role="menuitem" onClick={onLogout}><LogOut size={15} />退出登录</button></div> : null}</div>
  </div>
}

function relativeIsoDate(offsetDays: number) {
  const value = new Date()
  value.setDate(value.getDate() + offsetDays)
  return value.toISOString().slice(0, 10)
}

function LoadingState() { return <div className="load-shell" aria-busy="true"><aside className="load-sidebar" /><main className="load-main"><div className="skeleton heading-skeleton" /><div className="skeleton table-skeleton" /></main></div> }
function StandaloneState({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: string; action?: ReactNode }) { return <main className="standalone-state"><div className="state-icon">{icon}</div><h1>{title}</h1><p>{detail}</p>{action}</main> }
async function logout(session: Parameters<typeof logoutMediaSession>[0]) {
  await logoutMediaSession(session)
  window.location.assign('/openclaw/media/login')
}
