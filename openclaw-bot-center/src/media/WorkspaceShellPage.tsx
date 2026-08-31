import { useMediaWeb } from './MediaWebWorkspace'
import OrganizationWorkspaceShellPage from './OrganizationWorkspaceShellPage'
import PersonalWorkspaceShellPage from './PersonalWorkspaceShellPage'
import { SurfaceState } from './ui/SurfaceState'

export default function WorkspaceShellPage() {
  const { runtimeState, session } = useMediaWeb()
  if (session?.workspaceMode === 'personal_web' && session.bodyAuthority === 'internal') return <PersonalWorkspaceShellPage />
  if (session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark') return <OrganizationWorkspaceShellPage />
  if (!session) return <WorkspaceFallback kind="permission" title="当前会话未获授权" detail="无法进入工作区。" action={null} />
  if (runtimeState !== 'authenticated') return <WorkspaceFallback kind="error" title="工作区暂不可用" detail="身份服务尚未确认当前工作区。" action={null} />
  return <WorkspaceFallback kind="error" title="工作区暂不可用" detail="服务端会话没有可识别的工作区边界。" action={null} />
}

function WorkspaceFallback({ kind, title, detail, action }: { kind: 'permission' | 'error'; title: string; detail: string; action: null }) {
  return <main className="media-content workspace-shell-page" data-page-ownership="personal" data-accent="studio" data-page-prelude>
    <SurfaceState kind={kind} title={title} detail={detail} action={action} />
  </main>
}
