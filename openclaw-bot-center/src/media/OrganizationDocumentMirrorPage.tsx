import { ExternalLink, FileText, RefreshCw, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { useMediaWeb } from './MediaWebWorkspace'
import { BusinessOperationError, callBusinessOperation } from './generatedBusinessPagesContract'
import { getOrganizationDocumentUrl } from './ui/organizationDocumentUrl'
import { loginUrl } from './mediaWebApi'
import type { DocumentBodyResponse } from './documentWorkflow'
import CanonicalDocumentRenderer from './pages/ordinary/CanonicalDocumentRenderer'
import { formatDateOnly } from './ui/datetime'
import styles from './OrganizationDocumentMirrorPage.module.css'

type LoadState = { status: 'idle' | 'loading' } | { status: 'ready'; data: DocumentBodyResponse } | { status: 'empty' | 'error' | 'unauthorized' | 'notFound'; message: string }

export default function OrganizationDocumentMirrorPage() {
  const { artifactId } = useParams<{ artifactId?: string }>()
  const { runtimeState, session } = useMediaWeb()
  const [state, setState] = useState<LoadState>({ status: 'idle' })
  const [retryToken, setRetryToken] = useState(0)
  const organizationSession = session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark'

  useEffect(() => {
    if (!artifactId || runtimeState !== 'authenticated' || !organizationSession) return
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    callBusinessOperation<DocumentBodyResponse>('getDocumentBody', { path: { publicArtifactId: artifactId }, signal: controller.signal })
      .then((data) => {
        if (!active) return
        const artifact = data.data?.artifact
        const blocks = data.data?.revision?.body?.blocks
        if (artifact?.workspaceMode !== 'organization_lark' || artifact.bodyAuthority !== 'lark' || !Array.isArray(blocks)) {
          setState({ status: 'notFound', message: '这份文档不属于当前组织工作区，正文不会被展示。' })
        } else if (!blocks.length) {
          setState({ status: 'empty', message: '当前修订没有可展示的正文。' })
        } else {
          setState({ status: 'ready', data })
        }
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof DOMException && error.name === 'AbortError')) return
        if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) {
          setState({ status: 'unauthorized', message: '当前会话无权读取组织文档。' })
        } else if (error instanceof BusinessOperationError && error.status === 404) {
          setState({ status: 'notFound', message: '文档不存在，或已不再对当前组织可见。' })
        } else {
          setState({ status: 'error', message: '组织文档暂时不可读取，服务端没有返回可确认的正文。' })
        }
      })
    return () => { active = false; controller.abort() }
  }, [artifactId, organizationSession, retryToken, runtimeState])

  if (runtimeState === 'checking') return <MirrorState title="正在确认组织工作区" detail="正文只会在组织会话确认后读取。" />
  if (runtimeState !== 'authenticated' || !session) return <MirrorState title="当前会话未获授权" detail="组织文档不会使用默认内容。" action={<a href={loginUrl()} className="mg-btn mg-btn-primary">重新登录</a>} />
  if (!organizationSession) return <MirrorState title="当前会话不是组织工作区" detail="这份文档仅向组织工作区开放。" />
  if (!artifactId) return <MirrorState title="缺少文档标识" detail="服务端没有提供可读取的文档标识。" />

  const document = state.status === 'ready' ? state.data.data : null
  const artifact = document?.artifact
  const revision = document?.revision
  const documentUrl = artifact ? getOrganizationDocumentUrl(artifact) : null
  return (
    <main className={`${styles.page} mg-page`} data-page-ownership="organization" data-workspace-mode="organization_lark" data-read-only-mirror="true">
      <header className="mg-hero" data-page-prelude>
        <div><span className="mg-eyebrow">组织文档</span><h1>{artifact?.artifactKind || '组织文档镜像'}</h1><p className="mg-hero-lead">正文以飞书为唯一编辑权威，网页端仅提供只读回读镜像。</p></div>
        <span className="mg-badge" data-tone="info"><ShieldCheck size={15} aria-hidden="true" />只读镜像</span>
      </header>
      <section className={`${styles.panel} mg-panel`} aria-label="组织文档正文">
        <header className={styles.header}><div><span className={styles.kicker}><FileText size={15} />回读正文</span><h2>{artifact?.artifactKind || '组织文档'}</h2></div>{documentUrl ? <a className="mg-btn mg-btn-primary" href={documentUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} />在飞书中打开</a> : null}</header>
        {state.status === 'loading' || state.status === 'idle' ? <MirrorState title="正在读取组织正文" detail="等待服务端回读结果。" /> : state.status === 'ready' && revision ? <><div className={styles.meta}><span>正文权威 <b>飞书</b></span><span>镜像版本 <b>{revision.remoteDocumentVersion || '未记录'}</b></span><span>回读于 <b>{formatDateOnly(revision.updatedAt, { empty: '未记录', invalid: '未记录' })}</b></span><span>校验值 <b>{revision.bodyChecksum ? `${revision.bodyChecksum.slice(0, 12)}…` : '未记录'}</b></span></div><div className={styles.mirrorBadge}><ShieldCheck size={14} />只读镜像 · 不可在网页端编辑</div><CanonicalDocumentRenderer blocks={revision.body.blocks} /></> : <MirrorState title={state.status === 'empty' ? '文档暂无正文' : state.status === 'unauthorized' ? '当前会话未获授权' : state.status === 'notFound' ? '文档暂不可见' : '组织正文暂不可读取'} detail={'message' in state ? state.message : '服务端没有返回可确认的正文。'} action={<button type="button" className="mg-btn mg-btn-ghost" onClick={() => setRetryToken((value) => value + 1)}><RefreshCw size={15} />重新读取</button>} />}
      </section>
      <section className={`${styles.binding} mg-panel`} aria-label="组织绑定信息"><h2>组织绑定</h2><dl><div><dt>组织</dt><dd>{session.organizationName || '未记录'}</dd></div><div><dt>成员角色</dt><dd>{session.memberRole === 'owner' ? '组织负责人' : '组织成员'}</dd></div><div><dt>文档标识</dt><dd>{artifactId}</dd></div></dl></section>
    </main>
  )
}

function MirrorState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className={styles.state} role="status"><strong>{title}</strong><p>{detail}</p>{action}</div>
}
