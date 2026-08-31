import { useMediaWeb } from './MediaWebWorkspace'
import OrganizationWorkspaceShellPage from './OrganizationWorkspaceShellPage'
import PersonalWorkspaceShellPage from './PersonalWorkspaceShellPage'
import { SurfaceState } from './ui/SurfaceState'

export default function WorkspaceShellPage() {
  const { runtimeState, session } = useMediaWeb()
  const accent: WorkspaceAccent = session?.workspaceMode === 'organization_lark' ? 'campaign' : 'studio'
  if (session?.workspaceMode === 'personal_web' && session.bodyAuthority === 'internal') return <PersonalWorkspaceShellPage />
  if (session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark') return <OrganizationWorkspaceShellPage />
  if (!session) return <WorkspaceFallback accent={accent} kind="permission" title="当前会话未获授权" detail="无法进入工作区。" action={null} />
  if (runtimeState !== 'authenticated') return <WorkspaceFallback accent={accent} kind="error" title="工作区暂不可用" detail="身份服务尚未确认当前工作区。" action={null} />
  return <WorkspaceFallback accent={accent} kind="error" title="工作区暂不可用" detail="服务端会话没有可识别的工作区边界。" action={null} />
}

type WorkspaceAccent = 'studio' | 'campaign'

function WorkspaceFallback({ accent, kind, title, detail, action }: { accent: WorkspaceAccent; kind: 'permission' | 'error'; title: string; detail: string; action: null }) {
  return <main className="media-content workspace-shell-page" data-page-ownership="router" data-accent={accent}>
    <SurfaceState kind={kind} title={title} detail={detail} action={action} />
  </main>
}
