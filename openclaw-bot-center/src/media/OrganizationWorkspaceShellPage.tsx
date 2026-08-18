import {
  AlertCircle,
  CheckCircle2,
  Cloud,
  FolderOpen,
  KeyRound,
  ShieldAlert,
  ShieldCheck,
  RotateCcw,
  Users,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useMediaWeb } from './MediaWebWorkspace'
import {
  confirmStage1Provision,
  deprovisionStage1,
  loadStage1ProvisionStatus,
  startStage1Provision,
  type MediaWebSession,
  type Stage1ProvisionRun,
} from './mediaWebApi'
import { secureUuid } from './secureUuid'

type OrganizationConnection = 'connected' | 'pending' | 'disabled' | 'revoked' | 'attention'
type OrganizationMediaWebSession = Extract<MediaWebSession, { workspaceMode: 'organization_lark' }>

type OrganizationConnectionPresentation = {
  state: OrganizationConnection
  label: string
  installation: string
  message: string
  tone: 'active' | 'attention'
}

const organizationConnectionPresentations: Record<OrganizationConnection, OrganizationConnectionPresentation> = {
  connected: {
    state: 'connected',
    label: '已连接',
    installation: '服务端已确认安装可用',
    message: '组织连接已由服务端确认；本页面只展示组织资源入口，不提供编辑或外部操作。',
    tone: 'active',
  },
  pending: {
    state: 'pending',
    label: '待确认',
    installation: '安装或授权尚未完成',
    message: '安装仍在等待服务端确认，请完成组织安装或等待状态回读。',
    tone: 'attention',
  },
  disabled: {
    state: 'disabled',
    label: '已停用',
    installation: '安装已停用，需要恢复',
    message: '当前组织连接已停用，资源入口保持只读且不会显示为已连接。',
    tone: 'attention',
  },
  revoked: {
    state: 'revoked',
    label: '已撤销',
    installation: '安装已撤销，需要重新处理',
    message: '当前组织连接已撤销，资源不会开放；请由组织负责人处理安装恢复。',
    tone: 'attention',
  },
  attention: {
    state: 'attention',
    label: '需确认',
    installation: '安装状态需要确认',
    message: '服务端没有返回可确认的组织连接状态，页面已安全停留在需确认状态。',
    tone: 'attention',
  },
}

const memberRoleLabels: Record<MediaWebSession['memberRole'], string> = {
  owner: '组织负责人',
  member: '组织成员',
}

export default function OrganizationWorkspaceShellPage() {
  const { runtimeState, session } = useMediaWeb()

  if (runtimeState === 'checking') {
    return <OrganizationShellState status="loading" message="正在确认组织工作区" />
  }
  if (runtimeState !== 'authenticated' || !session) {
    return <OrganizationShellState status="unauthorized" message="当前会话未获授权，组织资源不会被展示。" />
  }
  if (session.workspaceMode !== 'organization_lark' || session.bodyAuthority !== 'lark' || !session.organizationName) {
    return <OrganizationShellState status="invalid" message="当前服务端会话不是组织工作区，已停止组织资源展示。" />
  }

  const connection = resolveOrganizationConnectionPresentation(session)
  return <OrganizationWorkspaceContent session={session} connection={connection} />
}

function OrganizationWorkspaceContent({
  session,
  connection,
}: {
  session: OrganizationMediaWebSession
  connection: OrganizationConnectionPresentation
}) {
  const [provisionRun, setProvisionRun] = useState<Stage1ProvisionRun | null>(null)
  const [busyAction, setBusyAction] = useState<'confirm' | 'start' | 'retry' | 'deprovision' | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const canOperate = session.memberRole === 'owner'
  const idempotencyKeys = useRef(new Map<'confirm' | 'start' | 'retry' | 'deprovision', string>())
  const provisionRunId = provisionRun?.provisionRunId
  const provisionRunStatus = provisionRun?.status

  useEffect(() => {
    if (!provisionRunId || (provisionRunStatus !== 'PENDING' && provisionRunStatus !== 'RUNNING')) return
    let active = true
    const controller = new AbortController()
    const load = () => loadStage1ProvisionStatus(session, provisionRunId, controller.signal)
      .then((response) => {
        if (active) setProvisionRun(response.run)
      })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === 'AbortError')) {
          setActionMessage(error instanceof Error ? error.message : '组织接入状态暂不可用。')
        }
      })
    void load()
    const timer = window.setInterval(() => { if (active) void load() }, 4000)
    return () => {
      active = false
      controller.abort()
      window.clearInterval(timer)
    }
  }, [session, provisionRunId, provisionRunStatus])

  const idempotencyKeyFor = (action: 'confirm' | 'start' | 'retry' | 'deprovision') => {
    const existing = idempotencyKeys.current.get(action)
    if (existing) return existing
    const key = `stage1-${action}-${secureUuid()}`
    idempotencyKeys.current.set(action, key)
    return key
  }

  const execute = async (action: 'confirm' | 'start' | 'retry' | 'deprovision') => {
    if (!canOperate || busyAction) return
    setBusyAction(action)
    setActionMessage(null)
    try {
      const key = idempotencyKeyFor(action)
      if (action === 'confirm') {
        await confirmStage1Provision(session, key)
        setActionMessage('组织安装确认已保存，等待资源初始化。')
      } else if (action === 'deprovision') {
        await deprovisionStage1(session, key, false)
        setActionMessage('组织访问已在本地停用，外部凭据将在后台继续撤销。')
      } else {
        const response = await startStage1Provision(session, key)
        setProvisionRun(response.run)
        setActionMessage(response.run.status === 'SUCCEEDED' ? '组织资源已初始化。' : '组织接入已启动，页面会读取服务端步骤回执。')
      }
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : '组织接入操作暂不可用。')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <main
      className="organization-workspace-page"
      data-organization-connection={connection.state}
      data-workspace-mode="organization_lark"
    >
      <header className="page-heading organization-page-heading">
        <div>
          <span className="eyebrow">组织工作区</span>
          <h1>组织资源工作台</h1>
          <p>飞书组织、成员角色和组织连接状态均以当前服务端会话为准。</p>
        </div>
        <span className={`organization-shell-status is-${connection.tone}`} data-organization-connection-label={connection.label}>
          {connection.state === 'connected' ? <CheckCircle2 size={16} aria-hidden="true" /> : <ShieldAlert size={16} aria-hidden="true" />}
          {connection.label}
        </span>
      </header>

      <section className="organization-shell-grid" aria-label="组织工作区状态和资源入口">
        <article className="section-panel organization-shell-card">
          <div className="section-heading">
            <div><Users size={17} aria-hidden="true" /><h2>当前组织状态</h2></div>
          </div>
          <dl className="organization-shell-facts">
            <div><dt>飞书组织</dt><dd title={session.organizationName}>{session.organizationName}</dd></div>
            <div><dt>工作区</dt><dd>组织工作区</dd></div>
            <div><dt>成员角色</dt><dd>{memberRoleLabels[session.memberRole]}</dd></div>
            <div><dt>正文权威</dt><dd>飞书只读资源</dd></div>
            <div><dt>组织连接状态</dt><dd><span className={`organization-shell-inline-status is-${connection.tone}`}>{connection.label}</span></dd></div>
            <div><dt>安装状态</dt><dd>{connection.installation}</dd></div>
          </dl>
          <div className={`organization-shell-notice is-${connection.tone}`} role="status">
            {connection.state === 'connected' ? <ShieldCheck size={16} aria-hidden="true" /> : <AlertCircle size={16} aria-hidden="true" />}
            <span>{connection.message}</span>
          </div>
        </article>

        <article className="section-panel organization-shell-card">
          <div className="section-heading">
            <div><Cloud size={17} aria-hidden="true" /><h2>组织资源入口</h2></div>
          </div>
          <div className="organization-shell-resource-state" role="status">
            <FolderOpen size={30} aria-hidden="true" />
            <h3>只读资源由服务端投影</h3>
            <p>{connection.state === 'connected' ? '当前壳只保留组织资源的只读入口，资源详情将在服务端授权后显示。' : '组织连接尚未达到可用状态，资源入口保持关闭并等待安装恢复。'}</p>
            <span className="organization-shell-readonly-label">只读入口</span>
          </div>
          {canOperate ? <div className="organization-provision-actions" aria-label="组织接入操作">
            {!provisionRun && connection.state !== 'connected' ? <button type="button" className="button button-primary" disabled={busyAction !== null} onClick={() => void execute('confirm')}>
              <ShieldCheck size={15} aria-hidden="true" />{busyAction === 'confirm' ? '确认中...' : '确认组织安装'}
            </button> : null}
            {(!provisionRun || provisionRun.status === 'FAILED') && connection.state !== 'revoked' ? <button type="button" className="button button-secondary" disabled={busyAction !== null} onClick={() => void execute(provisionRun ? 'retry' : 'start')}>
              <RotateCcw size={15} aria-hidden="true" />{busyAction === 'start' || busyAction === 'retry' ? '处理中...' : provisionRun ? '重试接入' : '初始化组织资源'}
            </button> : null}
            {connection.state === 'connected' || provisionRun?.status === 'SUCCEEDED' ? <button type="button" className="button button-secondary" disabled={busyAction !== null} onClick={() => void execute('deprovision')}>
              <ShieldAlert size={15} aria-hidden="true" />{busyAction === 'deprovision' ? '停用中...' : '停用组织接入'}
            </button> : null}
          </div> : null}
          {provisionRun ? <div className={`organization-provision-progress is-${provisionRun.status.toLowerCase()}`} role="status">
            <strong>{provisionRun.status === 'SUCCEEDED' ? '资源初始化完成' : provisionRun.status === 'FAILED' ? '资源初始化失败' : '资源初始化进行中'}</strong>
            <span>已完成步骤：{provisionRun.completedSteps.length ? provisionRun.completedSteps.join('、') : '尚无'}</span>
            {provisionRun.failedStep ? <span>失败步骤：{provisionRun.failedStep}</span> : null}
            {provisionRun.retryAfter ? <span>下次可重试：{new Date(provisionRun.retryAfter).toLocaleString()}</span> : null}
          </div> : null}
          {actionMessage ? <p className="organization-provision-message" role="status">{actionMessage}</p> : null}
        </article>
      </section>
    </main>
  )
}

function resolveOrganizationConnectionPresentation(session: OrganizationMediaWebSession): OrganizationConnectionPresentation {
  const state = normalizeOrganizationConnection(session.organizationConnection)
  return organizationConnectionPresentations[state]
}

function normalizeOrganizationConnection(value: Exclude<MediaWebSession['organizationConnection'], 'not_applicable'>): OrganizationConnection {
  if (value === 'connected') return 'connected'
  if (value === 'pending') return 'pending'
  if (value === 'disabled') return 'disabled'
  if (value === 'revoked') return 'revoked'
  return 'attention'
}

function OrganizationShellState({
  status,
  message,
}: {
  status: 'loading' | 'unauthorized' | 'invalid'
  message: string
}) {
  const Icon = status === 'loading' ? KeyRound : status === 'unauthorized' ? ShieldAlert : AlertCircle
  return (
    <main className="organization-workspace-page">
      <div className={`organization-shell-state is-${status}`} role="status" aria-busy={status === 'loading'}>
        <Icon size={22} aria-hidden="true" />
        <div><strong>{status === 'loading' ? '正在确认组织工作区' : '组织工作区暂不可用'}</strong><span>{message}</span></div>
      </div>
    </main>
  )
}
