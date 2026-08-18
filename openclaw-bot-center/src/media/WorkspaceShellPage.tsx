import { ShieldCheck } from 'lucide-react'
import { useMediaWeb } from './MediaWebWorkspace'
import OrganizationWorkspaceShellPage from './OrganizationWorkspaceShellPage'
import PersonalWorkspaceShellPage from './PersonalWorkspaceShellPage'

export default function WorkspaceShellPage() {
  const { runtimeState, session } = useMediaWeb()
  if (session?.workspaceMode === 'personal_web' && session.bodyAuthority === 'internal') return <PersonalWorkspaceShellPage />
  if (session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark') return <OrganizationWorkspaceShellPage />
  if (!session) return <main className="media-content workspace-shell-page"><div className="personal-state is-unauthorized" role="status"><ShieldCheck size={22} /><div><strong>当前会话未获授权</strong><span>无法进入工作区。</span></div></div></main>
  if (runtimeState !== 'authenticated') return <main className="media-content workspace-shell-page"><div className="personal-state is-error" role="status"><ShieldCheck size={22} /><div><strong>工作区暂不可用</strong><span>身份服务尚未确认当前工作区。</span></div></div></main>
  return <main className="media-content workspace-shell-page"><div className="personal-state is-error" role="status"><ShieldCheck size={22} /><div><strong>工作区暂不可用</strong><span>服务端会话没有可识别的工作区边界。</span></div></div></main>
}
