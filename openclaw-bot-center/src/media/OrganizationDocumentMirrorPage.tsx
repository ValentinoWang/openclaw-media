import { CheckCircle2, ExternalLink, FileText, LoaderCircle, RefreshCw, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { useMediaWeb } from './MediaWebWorkspace'
import { BusinessOperationError, callBusinessOperation } from './generatedBusinessPagesContract'
import { createIf2DocumentApi, defaultSleep, type DocumentBodyResponse, type DocumentRevisionRecord } from './documentWorkflow'
import { isPublicId } from './identifiers'
import { getOrganizationDocumentUrl } from './ui/organizationDocumentUrl'
import { newIdempotencyKey } from './idempotency'
import { loginUrl } from './mediaWebApi'
import CanonicalDocumentRenderer from './pages/ordinary/CanonicalDocumentRenderer'
import { formatDateOnly, formatDateTime } from './ui/datetime'
import { SurfaceState, type SurfaceStateKind } from './ui/SurfaceState'
import {
  isOrganizationMirrorDocumentResponse,
  isUnknownBatch,
  projectExecutionReceipt,
  projectSyncBatchList,
  readBlockIds,
  readDetailPart,
  safeTechnicalCode,
  syncActionFor,
  syncActionLabel,
  syncBatchOperationLabel,
  syncBatchStateLabel,
  syncDetailItemLabel,
  syncMessage,
  syncPipelineFor,
  syncStateFor,
  syncStateLabels,
  type DetailPart,
  type ExecutionReceiptProjection,
  type MirrorSyncBatch,
  type SyncDetailKey,
  type SyncLoadState,
} from './organizationDocumentMirrorPresentation'
import styles from './OrganizationDocumentMirrorPage.module.css'

type LoadState = { status: 'idle' | 'loading' } | { status: 'ready'; data: DocumentBodyResponse } | { status: 'empty' | 'error' | 'unauthorized' | 'notFound'; message: string }
type AiStatus = 'idle' | 'generating' | 'ready' | 'failed'
type ArtifactRevisionResponse = { item?: { currentRevision?: unknown } }

const AI_POLL_INTERVAL_MS = 1000
const AI_POLL_MAX_ATTEMPTS = 30

const documentApi = createIf2DocumentApi()
const artifactKindLabels: Record<string, string> = {
  decision_brief: '决策简报',
  creation_document: '创作文档',
  publishing_package: '发布包',
  review_report: '复盘报告',
  project_summary: '项目摘要',
}

function humanArtifactKind(value: string | null | undefined): string {
  const normalized = value?.trim().toLowerCase()
  return normalized ? artifactKindLabels[normalized] ?? '组织文档镜像' : '组织文档镜像'
}

function humanMemberRole(value: unknown): string {
  if (value === 'owner') return '组织负责人'
  if (value === 'member') return '组织成员'
  return '不可用'
}

function optionalText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function displayText(value: unknown, fallback = '不可用'): string {
  return optionalText(value) ?? fallback
}

function bodyChecksumLabel(value: unknown): string {
  const checksum = typeof value === 'string' && /^[a-f0-9]{64}$/.test(value) ? value : null
  return checksum ? `${checksum.slice(0, 12)}...` : '不可用'
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function isOrganizationRevision(value: unknown, artifactId: string): value is DocumentRevisionRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const candidate = value as Partial<DocumentRevisionRecord>
  return candidate.publicArtifactId === artifactId && candidate.bodyAuthority === 'lark' && typeof candidate.revision === 'number' && Number.isSafeInteger(candidate.revision) && candidate.revision > 0 && typeof candidate.bodyChecksum === 'string' && /^[a-f0-9]{64}$/.test(candidate.bodyChecksum) && Boolean(candidate.body && candidate.body.schemaVersion === 'media.document.body.v1' && Array.isArray(candidate.body.blocks))
}

function syncRequestErrorMessage(error: unknown, nextPage: boolean): string {
  const prefix = nextPage ? '下一页同步记录' : '同步记录'
  if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) return `当前会话无权读取${prefix}。`
  return `${prefix}暂时不可读取，请稍后重新读取。`
}

function batchRemoteVersionLabel(batch: MirrorSyncBatch): string {
  if (batch.remoteDocumentVersion) return batch.remoteDocumentVersion
  return batch.state === 'queued' || batch.state === 'running' || isUnknownBatch(batch) ? '等待远端确认' : '不可用'
}

function batchCompletedAtLabel(batch: MirrorSyncBatch): string {
  if (batch.completedAt) return formatDateTime(batch.completedAt, { empty: '不可用', invalid: '时间不可读' })
  return batch.state === 'queued' || batch.state === 'running' || isUnknownBatch(batch) ? '尚未完成' : '不可用'
}

function batchRevisionLabel(batch: MirrorSyncBatch): string {
  return batch.revision === null ? '不可用' : `v${batch.revision}`
}

function documentRevisionLabel(value: unknown): string {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? `v${value}` : '不可用'
}

function readReceiptPart(receipt: ExecutionReceiptProjection | null, key: 'applied' | 'manualActions' | 'protectedSkipped'): DetailPart {
  const values = receipt?.[key]
  return Array.isArray(values) ? { available: true, values } : { available: false, values: [] }
}

function readReceiptCount(receipt: ExecutionReceiptProjection | null): number | null {
  return receipt?.appliedCount ?? null
}

export default function OrganizationDocumentMirrorPage() {
  const { artifactId } = useParams<{ artifactId?: string }>()
  const { runtimeState, session } = useMediaWeb()
  const [state, setState] = useState<LoadState>({ status: 'idle' })
  const [syncLoadState, setSyncLoadState] = useState<SyncLoadState>('idle')
  const [batches, setBatches] = useState<MirrorSyncBatch[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [aiInstruction, setAiInstruction] = useState('')
  const [aiStatus, setAiStatus] = useState<AiStatus>('idle')
  const [aiRevision, setAiRevision] = useState<DocumentRevisionRecord | null>(null)
  const [aiReceipt, setAiReceipt] = useState<ExecutionReceiptProjection | null>(null)
  const [aiMessage, setAiMessage] = useState<string | null>(null)
  const [aiTechnicalCode, setAiTechnicalCode] = useState<string | null>(null)
  const [previewRevision, setPreviewRevision] = useState<DocumentRevisionRecord | null>(null)
  const aiRequestRef = useRef<AbortController | null>(null)
  const organizationSession = session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark'

  useEffect(() => () => { aiRequestRef.current?.abort() }, [artifactId, organizationSession])

  useEffect(() => {
    if (!artifactId || !isPublicId(artifactId) || runtimeState !== 'authenticated' || !organizationSession) return
    const controller = new AbortController()
    let active = true
    aiRequestRef.current?.abort()
    setState({ status: 'loading' })
    setSyncLoadState('loading')
    setSyncError(null)
    setBatches([])
    setNextCursor(null)
    setAiInstruction('')
    setAiStatus('idle')
    setAiRevision(null)
    setAiReceipt(null)
    setAiMessage(null)
    setAiTechnicalCode(null)
    setPreviewRevision(null)
    void callBusinessOperation<DocumentBodyResponse>('getDocumentBody', { path: { publicArtifactId: artifactId }, signal: controller.signal })
      .then((data) => {
        if (!active) return
        if (!isOrganizationMirrorDocumentResponse(data, artifactId)) setState({ status: 'notFound', message: '这份文档不属于当前组织工作区，正文不会被展示。' })
        else if (!data.data.revision.body.blocks.length) setState({ status: 'empty', message: '当前修订没有可展示的正文。' })
        else setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || isAbortError(error)) return
        if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) setState({ status: 'unauthorized', message: '当前会话无权读取组织文档。' })
        else if (error instanceof BusinessOperationError && error.status === 404) setState({ status: 'notFound', message: '文档不存在，或已不再对当前组织可见。' })
        else setState({ status: 'error', message: '组织文档暂时不可读取，服务端没有返回可确认的正文。' })
      })
    void documentApi.listSyncBatches(artifactId, undefined, 20, controller.signal)
      .then((response) => {
        if (!active) return
        const projection = projectSyncBatchList(response, artifactId)
        if (projection.status !== 'available') {
          setBatches([])
          setNextCursor(null)
          setSyncLoadState('error')
          setSyncError('同步记录与当前组织文档不匹配，暂不展示。')
          return
        }
        setBatches(projection.items)
        setNextCursor(projection.nextCursor)
        setSyncLoadState('ready')
      })
      .catch((error: unknown) => {
        if (active && !isAbortError(error)) {
          setBatches([])
          setNextCursor(null)
          setSyncLoadState('error')
          setSyncError(syncRequestErrorMessage(error, false))
        }
      })
    return () => { active = false; controller.abort() }
  }, [artifactId, organizationSession, retryToken, runtimeState])

  const loadMore = async () => {
    if (!artifactId || !nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const response = await documentApi.listSyncBatches(artifactId, nextCursor, 20)
      const projection = projectSyncBatchList(response, artifactId)
      if (projection.status !== 'available') {
        setSyncLoadState('error')
        setSyncError('下一页同步记录与当前组织文档不匹配，已停止加载。')
        setNextCursor(null)
        return
      }
      if (projection.items.some((item) => batches.some((known) => known.publicSyncId === item.publicSyncId))) {
        setSyncLoadState('error')
        setSyncError('下一页同步记录包含重复记录，已停止加载。')
        setNextCursor(null)
        return
      }
      setBatches((current) => [...current, ...projection.items])
      setNextCursor(projection.nextCursor)
      setSyncLoadState('ready')
      setSyncError(null)
    } catch (error: unknown) {
      setSyncLoadState('error')
      setSyncError(syncRequestErrorMessage(error, true))
    } finally {
      setLoadingMore(false)
    }
  }

  if (runtimeState === 'checking') return <MirrorState kind="loading" title="正在确认组织工作区" detail="正文只会在组织会话确认后读取。" />
  if (runtimeState !== 'authenticated' || !session) return <MirrorState kind="permission" title="当前会话未获授权" detail="组织文档不会使用默认内容。" action={<a href={loginUrl()} className="mg-btn mg-btn-primary">重新登录</a>} />
  if (!organizationSession) return <MirrorState kind="forbidden" title="当前会话不是组织工作区" detail="这份文档仅向组织工作区开放。" />
  if (!artifactId || !isPublicId(artifactId)) return <MirrorState kind="error" title="缺少文档标识" detail="服务端没有提供可读取的文档标识。" />

  const document = state.status === 'ready' ? state.data.data : null
  const artifact = document?.artifact
  const revision = document?.revision
  const documentUrl = artifact ? getOrganizationDocumentUrl(artifact) : null
  const latestBatch = batches[0] ?? null
  const currentSyncState = syncStateFor(batches, revision?.remoteDocumentVersion, syncLoadState)
  const syncAction = syncActionFor(currentSyncState)
  const technicalCode = latestBatch?.errorCode && currentSyncState !== 'synced' ? latestBatch.errorCode : null
  const latestDetail = latestBatch?.errorDetail ?? null
  const blockRefs = latestDetail ? readBlockIds(latestDetail.blockIds) : []
  const applied = latestDetail ? readDetailPart(latestDetail, 'applied') : { available: false, values: [] }
  const manualActions = latestDetail ? readDetailPart(latestDetail, 'manualActions') : { available: false, values: [] }
  const protectedSkipped = latestDetail ? readDetailPart(latestDetail, 'protectedSkipped') : { available: false, values: [] }
  const showSyncBanner = currentSyncState !== 'loading'
  const syncPipeline = syncPipelineFor(currentSyncState, latestBatch)
  const sourceRevision = revision
  const visibleRevision = previewRevision ?? revision
  const currentExecutionReceipt = projectExecutionReceipt(revision?.executionReceipt)
  const aiDockEnabled = currentExecutionReceipt !== null
  const aiStateAttribute = aiDockEnabled ? aiStatus : 'off'

  const createAiRevision = async () => {
    const instruction = aiInstruction.trim()
    if (!aiDockEnabled || !artifactId || !sourceRevision || !session || !instruction || aiStatus === 'generating') return
    aiRequestRef.current?.abort()
    const controller = new AbortController()
    aiRequestRef.current = controller
    setAiStatus('generating')
    setAiRevision(null)
    setAiReceipt(null)
    setPreviewRevision(null)
    setAiMessage('正在生成改稿修订，网页会持续读取服务端状态。')
    setAiTechnicalCode(null)
    try {
      const created = await callBusinessOperation<ArtifactRevisionResponse>('createArtifactRevision', {
        path: { publicArtifactId: artifactId },
        body: { expectedRevision: sourceRevision.revision, instruction, mode: 'regenerate' },
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey('ai-edit'),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      const createdRevision = created.item?.currentRevision
      if (typeof createdRevision !== 'number' || !Number.isSafeInteger(createdRevision) || createdRevision < 1) throw new Error('改稿修订未返回可读取的版本号。')
      for (let attempt = 0; attempt < AI_POLL_MAX_ATTEMPTS; attempt += 1) {
        const response = await documentApi.getRevision(artifactId, createdRevision, controller.signal)
        if (controller.signal.aborted) return
        if (response.schemaVersion !== 'media_web_business_pages_v2' || !isOrganizationRevision(response.data, artifactId)) throw new Error('改稿结果与当前组织文档不匹配。')
        const nextRevision = response.data
        const receipt = projectExecutionReceipt(nextRevision.executionReceipt)
        setAiRevision(nextRevision)
        setAiReceipt(receipt)
        if (nextRevision.state === 'ready') {
          if (!receipt || receipt.status !== 'ready') {
            setAiStatus('failed')
            setAiMessage('改稿结果缺少可确认的执行回执，暂不可采用。请重新读取组织文档后再试。')
            setAiTechnicalCode(safeTechnicalCode(receipt?.errorCode))
            return
          }
          setAiStatus('ready')
          setAiMessage('改稿修订已就绪。')
          setAiTechnicalCode(null)
          return
        }
        if (nextRevision.state === 'failed') {
          setAiStatus('failed')
          setAiMessage('AI 改稿未能生成可采用的修订。请保留当前镜像内容，稍后重新发起。')
          setAiTechnicalCode(safeTechnicalCode(receipt?.errorCode))
          return
        }
        if (nextRevision.state !== 'generating') {
          setAiStatus('failed')
          setAiMessage('改稿结果暂不可采用。请重新读取组织文档后再试。')
          setAiTechnicalCode(safeTechnicalCode(receipt?.errorCode))
          return
        }
        if (attempt + 1 < AI_POLL_MAX_ATTEMPTS) await defaultSleep(AI_POLL_INTERVAL_MS, controller.signal)
      }
      if (controller.signal.aborted) return
      setAiMessage('改稿仍在生成。请稍后重新读取页面查看结果。')
      setAiTechnicalCode(null)
    } catch (error: unknown) {
      if (controller.signal.aborted || isAbortError(error)) return
      setAiStatus('failed')
      setAiMessage(aiFailureMessage(error))
      setAiTechnicalCode(safeTechnicalCode(error))
    } finally {
      if (aiRequestRef.current === controller) aiRequestRef.current = null
    }
  }

  const loadAiRevision = () => {
    if (!aiRevision || aiRevision.state !== 'ready' || !aiReceipt || aiReceipt.status !== 'ready') return
    setPreviewRevision(aiRevision)
    setAiMessage('已载入改稿修订，当前正文仍保持只读。')
  }

  return <main className={`${styles.page} mg-page`} data-page-ownership="organization" data-accent="campaign" data-workspace-mode="organization_lark" data-read-only-mirror="true" data-document-sync-state={currentSyncState} data-ai-state={aiStateAttribute} data-ai-feature-flag={aiDockEnabled ? 'on' : 'off'} data-ai-execution-receipt={aiDockEnabled ? 'available' : 'unavailable'}>
    <header className="mg-hero" data-page-prelude><div><span className="mg-eyebrow">组织文档</span><h1>{humanArtifactKind(artifact?.artifactKind)}</h1><p className="mg-hero-lead">正文以飞书为唯一编辑权威，网页端仅提供只读回读镜像。</p></div><span className="mg-badge" data-tone="info"><ShieldCheck size={15} aria-hidden="true" />只读镜像</span></header>
    {showSyncBanner ? <section className={`${styles.syncBanner} ${styles[`sync${currentSyncState[0].toUpperCase()}${currentSyncState.slice(1)}`]}`} role={currentSyncState === 'synced' ? 'status' : 'alert'} data-document-sync-state={currentSyncState}><div><TriangleAlert size={18} aria-hidden="true" /><div><strong data-sync-state={currentSyncState}>{syncStateLabels[currentSyncState]}</strong><p>{syncError || syncMessage(currentSyncState, latestBatch)}</p>{technicalCode ? <small className={styles.technicalReference}>技术参考码：{technicalCode}</small> : null}</div></div><button type="button" className="mg-btn mg-btn-ghost" data-sync-action={syncAction} onClick={() => setRetryToken((value) => value + 1)}><RefreshCw size={15} aria-hidden="true" />{syncActionLabel(currentSyncState)}</button></section> : null}
    <section className={`${styles.panel} mg-panel`} aria-label="组织文档正文"><header className={styles.header}><div><span className={styles.kicker}><FileText size={15} aria-hidden="true" />回读正文</span><h2>{humanArtifactKind(artifact?.artifactKind)}</h2></div>{documentUrl ? <a className="mg-btn mg-btn-primary" href={documentUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} aria-hidden="true" />在飞书中打开</a> : null}</header>{state.status === 'loading' || state.status === 'idle' ? <MirrorState kind="loading" title="正在读取组织正文" detail="等待服务端回读结果。" /> : state.status === 'ready' && visibleRevision ? <><div className={styles.meta}><span>正文权威 <b>飞书</b></span><span>{previewRevision ? '当前预览' : '镜像版本'} <b>{previewRevision ? documentRevisionLabel(visibleRevision.revision) : displayText(visibleRevision.remoteDocumentVersion, '未记录')}</b></span><span>回读于 <b>{formatDateOnly(optionalText(visibleRevision.updatedAt), { empty: '未记录', invalid: '时间不可读' })}</b></span><span>校验值 <b>{bodyChecksumLabel(visibleRevision.bodyChecksum)}</b></span></div>{previewRevision ? <div className={styles.previewBadge}><Sparkles size={14} aria-hidden="true" />已载入改稿修订 · 仅限当前页面只读预览</div> : <div className={styles.mirrorBadge}><ShieldCheck size={14} aria-hidden="true" />只读镜像 · 不可在网页端编辑</div>}<CanonicalDocumentRenderer blocks={visibleRevision.body.blocks} highlightedBlockIds={currentSyncState === 'unsupported' ? blockRefs : []} /></> : <MirrorState kind={state.status === 'empty' ? 'empty' : state.status === 'unauthorized' ? 'permission' : state.status === 'notFound' ? 'notFound' : 'error'} title={state.status === 'empty' ? '文档暂无正文' : state.status === 'unauthorized' ? '当前会话无权读取组织文档' : state.status === 'notFound' ? '文档暂不可见' : '组织正文暂不可读取'} detail={'message' in state ? state.message : '服务端没有返回可确认的正文。'} action={<button type="button" className="mg-btn mg-btn-ghost" onClick={() => setRetryToken((value) => value + 1)}><RefreshCw size={15} aria-hidden="true" />重新读取</button>} />}</section>
    {aiDockEnabled ? <section className={`${styles.aiDock} mg-panel`} aria-labelledby="organization-ai-dock-title" data-ai-state={aiStateAttribute} data-ai-feature-flag="on" data-ai-execution-receipt="available" aria-busy={aiStatus === 'generating'}><header className={styles.aiHeader}><div><span className={styles.kicker}><Sparkles size={15} aria-hidden="true" />AI 改稿修订</span><h2 id="organization-ai-dock-title">让 AI 改稿</h2><p>网页端不直接编辑组织正文。提交后由服务端按当前组织绑定执行，并通过修订回读确认结果。</p></div><span className="mg-badge" data-tone="info">只读预览</span></header><form className={styles.aiForm} onSubmit={(event) => { event.preventDefault(); void createAiRevision() }}><label htmlFor="organization-ai-instruction">改稿要求</label><textarea id="organization-ai-instruction" aria-describedby="organization-ai-hint" value={aiInstruction} onChange={(event) => setAiInstruction(event.target.value)} disabled={aiStatus === 'generating'} placeholder="例如：把正文开头改得更清楚，并保留受保护内容。" rows={3} /><div className={styles.aiFormFooter}><p id="organization-ai-hint">需要具备改稿权限的组织成员。受保护内容与结构不会在网页端直接改写。</p><button type="submit" className="mg-btn mg-btn-primary" disabled={!sourceRevision || !aiInstruction.trim() || aiStatus === 'generating'}>{aiStatus === 'generating' ? <LoaderCircle className={styles.spin} size={15} aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}{aiStatus === 'generating' ? '正在生成' : '生成改稿修订'}</button></div></form>{aiStatus === 'generating' ? <div className={styles.aiProgress} role="status" aria-live="polite"><div><LoaderCircle className={styles.spin} size={18} aria-hidden="true" /><div><strong>正在生成改稿修订</strong><p>{aiMessage || '服务端正在处理当前组织绑定，页面会根据修订状态更新。'}</p></div></div><span className="mg-badge" data-tone="warning">生成中</span></div> : null}{aiStatus === 'ready' && aiRevision ? <AiRevisionResult revision={aiRevision} receipt={aiReceipt} technicalCode={aiTechnicalCode} onLoad={loadAiRevision} /> : null}{aiStatus === 'failed' ? <div className={styles.aiFailure} role="alert"><TriangleAlert size={18} aria-hidden="true" /><div><strong>改稿结果暂不可用</strong><p>{aiMessage || '改稿请求暂时失败。请稍后重新发起。'}</p>{aiTechnicalCode ? <small className={styles.technicalReference}>技术参考码：{aiTechnicalCode}</small> : null}</div></div> : null}</section> : null}
    <section className={`${styles.ledger} mg-panel`} aria-label="同步账本" data-sync-ledger="true"><header className={styles.ledgerHead}><div><span className={styles.kicker}><CheckCircle2 size={15} aria-hidden="true" />同步账本</span><h2>最近同步记录</h2><p>记录仅反映服务端已返回的同步状态，不替代飞书正文。</p></div><span className="mg-badge" data-sync-state={currentSyncState}>{syncStateLabels[currentSyncState]}</span></header><ol className={styles.pipeline} aria-label="同步链路" data-sync-pipeline={currentSyncState}>{syncPipeline.map((step, index) => <li key={step.title} data-sync-step={index + 1} data-sync-step-state={step.state}><span aria-hidden="true">{index + 1}</span><div><strong>{step.title}</strong><small>{step.detail}</small></div></li>)}</ol>{currentSyncState === 'partial' ? <dl className={styles.receipt}><DetailList label="已应用" keyName="applied" part={applied} /><DetailList label="需要人工处理" keyName="manualActions" part={manualActions} /><DetailList label="受保护未改动" keyName="protectedSkipped" part={protectedSkipped} /></dl> : null}{currentSyncState === 'unsupported' ? <p className={styles.blockRefs}>{blockRefs.length ? `涉及 ${blockRefs.map((value, index) => syncDetailItemLabel(value, index, 'blockIds')).join('、')}，请在飞书中处理该正文块后重新读取。` : '涉及的正文块信息不可用，请在飞书中确认结构后重新读取。'}</p> : null}{syncLoadState === 'loading' || syncLoadState === 'idle' ? <p className={styles.ledgerState}>正在读取同步账本。</p> : syncLoadState === 'error' ? <p className={styles.ledgerState}>{syncError || '同步账本暂不可用。'}</p> : batches.length === 0 ? <p className={styles.ledgerState}>服务端尚未返回可展示的同步记录。</p> : <ol className={styles.batchList}>{batches.map((batch) => <li key={batch.publicSyncId}><div><strong>{syncBatchOperationLabel(batch.operation)}</strong><span>{syncBatchStateLabel(batch)}</span></div><dl><div><dt>修订版本</dt><dd>{batchRevisionLabel(batch)}</dd></div><div><dt>远端版本</dt><dd>{batchRemoteVersionLabel(batch)}</dd></div><div><dt>完成时间</dt><dd>{batchCompletedAtLabel(batch)}</dd></div></dl></li>)}</ol>}{nextCursor ? <button type="button" className="mg-btn mg-btn-ghost" onClick={() => void loadMore()} disabled={loadingMore}>{loadingMore ? <LoaderCircle className={styles.spin} size={15} aria-hidden="true" /> : <RefreshCw size={15} aria-hidden="true" />}{loadingMore ? '正在加载' : '加载更多记录'}</button> : null}</section>
    <section className={`${styles.binding} mg-panel`} aria-label="组织绑定信息"><h2>组织绑定</h2><dl><div><dt>组织</dt><dd>{displayText(session.organizationName)}</dd></div><div><dt>成员角色</dt><dd>{humanMemberRole(session.memberRole)}</dd></div><div><dt>文档标识</dt><dd>{isPublicId(artifactId) ? artifactId : '不可用'}</dd></div></dl></section>
  </main>
}

function aiFailureMessage(error: unknown): string {
  if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) return '当前会话没有执行组织改稿的权限。'
  if (error instanceof BusinessOperationError && error.status === 409) return '当前正文已更新，请重新读取组织文档后再发起改稿。'
  if (error instanceof BusinessOperationError && error.status === 404) return '改稿结果暂时不可读取，请重新读取组织文档后重试。'
  return '改稿请求暂时失败。请保留当前镜像内容，稍后重新发起。'
}

function DetailList({ label, keyName, part }: { label: string; keyName: SyncDetailKey; part: DetailPart }) {
  const value = !part.available ? '不可用' : part.values.length ? part.values.map((item, index) => syncDetailItemLabel(item, index, keyName)).join('、') : '无'
  return <div data-detail-availability={part.available ? 'available' : 'unavailable'}><dt>{label}</dt><dd>{value}</dd></div>
}

function MirrorState({ kind, title, detail, action }: { kind: SurfaceStateKind; title: string; detail: string; action?: ReactNode }) {
  return <SurfaceState kind={kind} title={title} detail={detail} action={action} />
}

function AiReceiptPart({ label, kind, keyName, part }: { label: string; kind: 'applied' | 'manual' | 'protected'; keyName: SyncDetailKey; part: DetailPart }) {
  return <section className={styles.aiReceiptPart} data-receipt-part={kind} data-receipt-availability={part.available ? 'available' : 'missing'}><div className={styles.aiReceiptPartHead}><strong>{label}</strong><span>{part.available ? part.values.length ? `${part.values.length} 项` : '无' : '未提供'}</span></div>{part.available && part.values.length ? <ul>{part.values.map((value, index) => <li key={`${kind}-${index}`}>{syncDetailItemLabel(value, index, keyName)}</li>)}</ul> : <p>{part.available ? '服务端未报告此类结果。' : '本次回读未提供此项执行回执。'}</p>}</section>
}

function AiRevisionResult({ revision, receipt, technicalCode, onLoad }: { revision: DocumentRevisionRecord; receipt: ExecutionReceiptProjection | null; technicalCode: string | null; onLoad: () => void }) {
  const applied = readReceiptPart(receipt, 'applied')
  const manual = readReceiptPart(receipt, 'manualActions')
  const protectedSkipped = readReceiptPart(receipt, 'protectedSkipped')
  const appliedCount = readReceiptCount(receipt)
  return <div className={styles.aiResult} data-ai-result="ready"><header className={styles.aiResultHeader}><div><span className={styles.kicker}><CheckCircle2 size={15} aria-hidden="true" />执行结果</span><h3>改稿修订已就绪。</h3><p>服务端已完成本次改稿修订，以下内容只显示实际回读到的执行回执。</p></div><span className={styles.aiRevisionLabel}>修订 v{revision.revision}</span></header><div className={styles.aiResultMeta}><span>已应用数量 <b>{appliedCount === null ? '未提供' : appliedCount}</b></span><span>执行回执 <b>{receipt ? '已回读' : '未提供'}</b></span></div><div className={styles.aiReceipt} aria-label="AI 改稿执行回执"><AiReceiptPart label="已应用" kind="applied" keyName="applied" part={applied} /><AiReceiptPart label="需要人工处理" kind="manual" keyName="manualActions" part={manual} /><AiReceiptPart label="受保护未改动" kind="protected" keyName="protectedSkipped" part={protectedSkipped} /></div><div className={styles.aiResultFooter}><p>载入后仅在本页预览修订，不会绕过组织绑定直接写入正文。</p><button type="button" className="mg-btn mg-btn-primary" onClick={onLoad}><FileText size={15} aria-hidden="true" />载入此修订</button></div>{technicalCode ? <small className={styles.technicalReference}>技术参考码：{technicalCode}</small> : null}</div>
}
