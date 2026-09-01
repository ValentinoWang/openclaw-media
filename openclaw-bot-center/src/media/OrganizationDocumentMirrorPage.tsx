import { CheckCircle2, ExternalLink, FileText, LoaderCircle, RefreshCw, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { useMediaWeb } from './MediaWebWorkspace'
import { BusinessOperationError, callBusinessOperation } from './generatedBusinessPagesContract'
import { createIf2DocumentApi, defaultSleep, type DocumentBodyResponse, type DocumentEditExecutionReceipt, type DocumentRevisionRecord, type DocumentSyncBatch } from './documentWorkflow'
import { getOrganizationDocumentUrl } from './ui/organizationDocumentUrl'
import { newIdempotencyKey } from './idempotency'
import { loginUrl } from './mediaWebApi'
import CanonicalDocumentRenderer from './pages/ordinary/CanonicalDocumentRenderer'
import { formatDateOnly, formatDateTime } from './ui/datetime'
import { SurfaceState, type SurfaceStateKind } from './ui/SurfaceState'
import styles from './OrganizationDocumentMirrorPage.module.css'

type LoadState = { status: 'idle' | 'loading' } | { status: 'ready'; data: DocumentBodyResponse } | { status: 'empty' | 'error' | 'unauthorized' | 'notFound'; message: string }
type SyncLoadState = 'idle' | 'loading' | 'ready' | 'error'
type SyncState = 'loading' | 'synced' | 'running' | 'unknown' | 'conflict' | 'unsupported' | 'stale' | 'partial' | 'unavailable'
type SyncPipelineState = 'complete' | 'running' | 'attention' | 'pending'
type SyncPipelineStep = { title: string; detail: string; state: SyncPipelineState }
type AiStatus = 'idle' | 'generating' | 'ready' | 'failed'
type ArtifactRevisionResponse = { item?: { currentRevision?: unknown } }
type AiExecutionReceipt = DocumentEditExecutionReceipt
type ReceiptPart = { available: boolean; values: unknown[] }

const AI_POLL_INTERVAL_MS = 1000
const AI_POLL_MAX_ATTEMPTS = 30

const documentApi = createIf2DocumentApi()
const artifactKindLabels: Record<string, string> = { decision_brief: '决策简报', creation_document: '创作文档', publishing_package: '发布包', review_report: '复盘报告', project_summary: '项目摘要' }
const syncStateLabels: Record<SyncState, string> = { loading: '正在读取同步记录', synced: '镜像已同步', running: '正在写入飞书', unknown: '写入结果待对账', conflict: '远端版本需要处理', unsupported: '部分内容暂不能同步', stale: '飞书已有更新，等待回读', partial: '部分内容已应用', unavailable: '同步记录暂不可读' }
const aiOperationLabels: Record<string, string> = { replace_text: '替换文本', replace_terms: '替换文本', insert_table_row: '新增表格行' }
const manualReasonLabels: Record<string, string> = { intent_target_block_not_found: '目标正文块未找到', protected_block: '内容受到保护', rich_text_elements_without_style_run_proof: '复杂格式需要人工复核', replace_terms_no_exact_match: '没有找到精确匹配' }

function humanArtifactKind(value: string | null | undefined): string {
  const normalized = value?.trim().toLowerCase()
  return normalized ? artifactKindLabels[normalized] ?? '组织文档镜像' : '组织文档镜像'
}

function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : [] }
function isUnknown(batch: DocumentSyncBatch): boolean { return batch.errorCode === 'lark_save_outcome_unknown' }
function isUnsupported(batch: DocumentSyncBatch): boolean { return batch.state === 'failed' && (batch.errorCode === 'lark_table_shape_unsupported' || batch.errorCode === 'unsupported_document_block') }
function receiptLabel(value: string, index: number): string { return /^blk_[a-z0-9_-]+$/i.test(value) ? `相关正文块 ${index + 1}` : `第 ${index + 1} 项` }
function isRecord(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === 'object' && !Array.isArray(value) }
function isAbortError(error: unknown): boolean { return error instanceof DOMException && error.name === 'AbortError' }
function safeTechnicalCode(value: unknown): string | null {
  const candidate = typeof value === 'string' ? value : isRecord(value) && typeof value.code === 'string' ? value.code : null
  if (!candidate || !/^[a-z0-9][a-z0-9_.:-]{0,95}$/i.test(candidate) || /^http_\d{3}$/i.test(candidate)) return null
  return candidate
}
function readExecutionReceipt(value: DocumentRevisionRecord): AiExecutionReceipt | null {
  return value.executionReceipt ?? null
}
function readReceiptPart(receipt: AiExecutionReceipt | null, key: 'applied' | 'manualActions' | 'protectedSkipped'): ReceiptPart {
  if (!receipt) return { available: false, values: [] }
  return { available: true, values: receipt[key] as unknown[] }
}
function readReceiptCount(receipt: AiExecutionReceipt | null): number | null {
  const value = receipt?.appliedCount
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
}
function receiptBlockId(value: unknown): string | null {
  if (typeof value === 'string' && /^blk_[a-z0-9_-]+$/i.test(value.trim())) return value.trim()
  if (isRecord(value)) {
    const blockId = typeof value.blockId === 'string' ? value.blockId : typeof value.block_id === 'string' ? value.block_id : null
    return blockId?.trim() || null
  }
  return null
}
function receiptOperation(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null
  if (!isRecord(value)) return null
  const operation = typeof value.operation === 'string' ? value.operation : typeof value.operationId === 'string' ? value.operationId : typeof value.operation_id === 'string' ? value.operation_id : typeof value.requestedOp === 'string' ? value.requestedOp : typeof value.requested_op === 'string' ? value.requested_op : null
  return operation?.trim() || null
}
function receiptOperationLabel(value: unknown): string | null {
  const operation = receiptOperation(value)
  return operation ? aiOperationLabels[operation] ?? null : null
}
function aiReceiptItemLabel(value: unknown, index: number, kind: 'applied' | 'manual' | 'protected'): string {
  const operationLabel = kind !== 'protected' ? receiptOperationLabel(value) : null
  const blockId = receiptBlockId(value)
  if (kind === 'manual') {
    const reason = isRecord(value) && typeof value.reason === 'string' ? manualReasonLabels[value.reason] : null
    const parts = [reason, operationLabel, blockId ? `相关正文块 ${index + 1}` : null].filter((part): part is string => Boolean(part))
    return parts.length ? parts.join(' · ') : `人工处理项目 ${index + 1}`
  }
  if (kind === 'protected') return blockId ? `相关正文块 ${index + 1}` : `受保护内容 ${index + 1}`
  if (operationLabel) return operationLabel
  if (blockId) return `相关正文块 ${index + 1}`
  return `已应用项目 ${index + 1}`
}
function aiFailureMessage(error: unknown): string {
  if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) return '当前会话没有执行组织改稿的权限。'
  if (error instanceof BusinessOperationError && error.status === 409) return '当前正文已更新，请重新读取组织文档后再发起改稿。'
  if (error instanceof BusinessOperationError && error.status === 404) return '改稿结果暂时不可读取，请重新读取组织文档后重试。'
  return '改稿请求暂时失败。请保留当前镜像内容，稍后重新发起。'
}

function syncStateFor(batches: DocumentSyncBatch[], mirrorVersion: string | null | undefined, loadState: SyncLoadState): SyncState {
  if (loadState === 'loading' || loadState === 'idle') return 'loading'
  if (loadState === 'error') return 'unavailable'
  const latest = batches[0]
  if (!latest) return 'unavailable'
  if (isUnknown(latest)) return 'unknown'
  if (latest.state === 'running' || latest.state === 'queued') return 'running'
  if (latest.state === 'conflict') return 'conflict'
  if (isUnsupported(latest)) return 'unsupported'
  if (latest.state === 'succeeded' && (strings(latest.errorDetail.applied).length > 0 || strings(latest.errorDetail.manualActions).length > 0 || strings(latest.errorDetail.protectedSkipped).length > 0)) return 'partial'
  if (latest.remoteDocumentVersion && mirrorVersion && latest.remoteDocumentVersion !== mirrorVersion) return 'stale'
  return latest.state === 'succeeded' ? 'synced' : 'unavailable'
}

function syncMessage(state: SyncState, batch: DocumentSyncBatch | null): string {
  if (state === 'running') return '飞书写入仍在进行。网页会在服务端完成回读后更新镜像版本。'
  if (state === 'unknown') return '飞书可能已经保存，但服务端尚未完成确认。请重新读取状态，避免重复写入。'
  if (state === 'conflict') return '飞书中的版本与本次同步基线不一致。请先在飞书确认内容，再重新读取镜像。'
  if (state === 'unsupported') return '检测到当前结构无法安全写入飞书。其余已确认的正文不会被自动改写。'
  if (state === 'stale') return '飞书中出现了更高版本，网页镜像正在等待下一次回读。'
  if (state === 'partial') return '部分内容已经应用；需要人工处理和受保护内容会保留原状。'
  if (state === 'unavailable') return batch ? '本次同步没有返回可确认的完成状态。' : '服务端尚未返回可确认的同步记录。'
  return '本地镜像与最近一次服务端回读记录一致。'
}

function syncPipelineFor(state: SyncState, batch: DocumentSyncBatch | null): SyncPipelineStep[] {
  const hasRevision = Boolean(batch && batch.revision > 0)
  const initial: SyncPipelineStep = { title: '生成正文', detail: hasRevision ? `修订 v${batch?.revision} 已产生` : '等待服务端确认正文修订', state: hasRevision ? 'complete' : 'pending' }
  if (state === 'synced') return [initial, { title: '写入飞书', detail: '最近一次批次已完成', state: 'complete' }, { title: '登记绑定', detail: '组织绑定已确认', state: 'complete' }, { title: '写后回读', detail: '镜像版本与回读记录一致', state: 'complete' }]
  if (state === 'running') return [initial, { title: '写入飞书', detail: '服务端正在处理写入批次', state: 'running' }, { title: '登记绑定', detail: '等待写入回执', state: 'pending' }, { title: '写后回读', detail: '等待远端版本读回', state: 'pending' }]
  if (state === 'unknown') return [initial, { title: '写入飞书', detail: '尚未取得可确认的写入结果', state: 'attention' }, { title: '登记绑定', detail: '等待对账结论', state: 'pending' }, { title: '写后回读', detail: '结果确认前不自动重发', state: 'pending' }]
  if (state === 'conflict') return [initial, { title: '写入飞书', detail: '远端版本与同步基线不一致', state: 'attention' }, { title: '登记绑定', detail: '等待在飞书确认正文', state: 'pending' }, { title: '写后回读', detail: '确认后重新读取', state: 'pending' }]
  if (state === 'unsupported') return [initial, { title: '写入飞书', detail: '检测到不能安全写入的正文结构', state: 'attention' }, { title: '登记绑定', detail: '未确认的内容不会自动登记', state: 'pending' }, { title: '写后回读', detail: '等待人工处理后回读', state: 'pending' }]
  if (state === 'stale') return [initial, { title: '写入飞书', detail: '最近一次批次已返回', state: 'complete' }, { title: '登记绑定', detail: '当前绑定仍被保留', state: 'complete' }, { title: '写后回读', detail: '发现更高远端版本，等待重新读取', state: 'attention' }]
  if (state === 'partial') return [initial, { title: '写入飞书', detail: '服务端返回部分应用结果', state: 'attention' }, { title: '登记绑定', detail: '仅已确认内容继续保留', state: 'complete' }, { title: '写后回读', detail: '受保护内容保持原状', state: 'attention' }]
  return [initial, { title: '写入飞书', detail: '尚无可确认的同步记录', state: 'pending' }, { title: '登记绑定', detail: '尚无可确认的同步记录', state: 'pending' }, { title: '写后回读', detail: '尚无可确认的同步记录', state: 'pending' }]
}

export default function OrganizationDocumentMirrorPage() {
  const { artifactId } = useParams<{ artifactId?: string }>()
  const { runtimeState, session } = useMediaWeb()
  const [state, setState] = useState<LoadState>({ status: 'idle' })
  const [syncLoadState, setSyncLoadState] = useState<SyncLoadState>('idle')
  const [batches, setBatches] = useState<DocumentSyncBatch[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [aiInstruction, setAiInstruction] = useState('')
  const [aiStatus, setAiStatus] = useState<AiStatus>('idle')
  const [aiRevision, setAiRevision] = useState<DocumentRevisionRecord | null>(null)
  const [aiReceipt, setAiReceipt] = useState<AiExecutionReceipt | null>(null)
  const [aiMessage, setAiMessage] = useState<string | null>(null)
  const [aiTechnicalCode, setAiTechnicalCode] = useState<string | null>(null)
  const [previewRevision, setPreviewRevision] = useState<DocumentRevisionRecord | null>(null)
  const aiRequestRef = useRef<AbortController | null>(null)
  const organizationSession = session?.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark'

  useEffect(() => () => { aiRequestRef.current?.abort() }, [artifactId, organizationSession])

  useEffect(() => {
    if (!artifactId || runtimeState !== 'authenticated' || !organizationSession) return
    const controller = new AbortController()
    let active = true
    setState({ status: 'loading' })
    setSyncLoadState('loading')
    setSyncError(null)
    setBatches([])
    setNextCursor(null)
    setPreviewRevision(null)
    void callBusinessOperation<DocumentBodyResponse>('getDocumentBody', { path: { publicArtifactId: artifactId }, signal: controller.signal })
      .then((data) => {
        if (!active) return
        const artifact = data.data?.artifact
        const blocks = data.data?.revision?.body?.blocks
        if (artifact?.workspaceMode !== 'organization_lark' || artifact.bodyAuthority !== 'lark' || !Array.isArray(blocks)) setState({ status: 'notFound', message: '这份文档不属于当前组织工作区，正文不会被展示。' })
        else if (!blocks.length) setState({ status: 'empty', message: '当前修订没有可展示的正文。' })
        else setState({ status: 'ready', data })
      })
      .catch((error: unknown) => {
        if (!active || isAbortError(error)) return
        if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) setState({ status: 'unauthorized', message: '当前会话无权读取组织文档。' })
        else if (error instanceof BusinessOperationError && error.status === 404) setState({ status: 'notFound', message: '文档不存在，或已不再对当前组织可见。' })
        else setState({ status: 'error', message: '组织文档暂时不可读取，服务端没有返回可确认的正文。' })
      })
    void documentApi.listSyncBatches(artifactId, undefined, 20, controller.signal)
      .then((response) => { if (active) { setBatches(response.items); setNextCursor(response.nextCursor); setSyncLoadState('ready') } })
      .catch((error: unknown) => { if (active && !isAbortError(error)) { setSyncLoadState('error'); setSyncError(error instanceof BusinessOperationError && (error.status === 401 || error.status === 403) ? '当前会话无权读取同步记录。' : '同步记录暂时不可读取，请稍后重新读取。') } })
    return () => { active = false; controller.abort() }
  }, [artifactId, organizationSession, retryToken, runtimeState])

  const loadMore = async () => {
    if (!artifactId || !nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const response = await documentApi.listSyncBatches(artifactId, nextCursor, 20)
      setBatches((current) => [...current, ...response.items.filter((item) => !current.some((known) => known.publicSyncId === item.publicSyncId))])
      setNextCursor(response.nextCursor)
    } catch { setSyncError('下一页同步记录暂时不可读取，请稍后重试。') } finally { setLoadingMore(false) }
  }

  if (runtimeState === 'checking') return <MirrorState kind="loading" title="正在确认组织工作区" detail="正文只会在组织会话确认后读取。" />
  if (runtimeState !== 'authenticated' || !session) return <MirrorState kind="permission" title="当前会话未获授权" detail="组织文档不会使用默认内容。" action={<a href={loginUrl()} className="mg-btn mg-btn-primary">重新登录</a>} />
  if (!organizationSession) return <MirrorState kind="forbidden" title="当前会话不是组织工作区" detail="这份文档仅向组织工作区开放。" />
  if (!artifactId) return <MirrorState kind="error" title="缺少文档标识" detail="服务端没有提供可读取的文档标识。" />

  const document = state.status === 'ready' ? state.data.data : null
  const artifact = document?.artifact
  const revision = document?.revision
  const documentUrl = artifact ? getOrganizationDocumentUrl(artifact) : null
  const latestBatch = batches[0] ?? null
  const currentSyncState = syncStateFor(batches, revision?.remoteDocumentVersion, syncLoadState)
  const syncAction = currentSyncState === 'unknown' ? 'reconcile' : currentSyncState === 'running' ? 'refresh' : 'reread'
  const technicalCode = latestBatch?.errorCode && currentSyncState !== 'synced' ? latestBatch.errorCode : null
  const blockRefs = latestBatch ? strings(latestBatch.errorDetail.blockIds) : []
  const applied = latestBatch ? strings(latestBatch.errorDetail.applied) : []
  const manualActions = latestBatch ? strings(latestBatch.errorDetail.manualActions) : []
  const protectedSkipped = latestBatch ? strings(latestBatch.errorDetail.protectedSkipped) : []
  const showSyncBanner = currentSyncState !== 'synced' && currentSyncState !== 'loading'
  const syncPipeline = syncPipelineFor(currentSyncState, latestBatch)
  const sourceRevision = revision
  const visibleRevision = previewRevision ?? revision
  const aiStateAttribute = aiStatus === 'idle' ? 'unavailable' : aiStatus

  const createAiRevision = async () => {
    const instruction = aiInstruction.trim()
    if (!artifactId || !sourceRevision || !session || !instruction || aiStatus === 'generating') return
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
        const nextRevision = response.data
        const receipt = readExecutionReceipt(nextRevision)
        setAiRevision(nextRevision)
        setAiReceipt(receipt)
        if (nextRevision.state === 'ready') {
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
    if (!aiRevision || aiRevision.state !== 'ready') return
    setPreviewRevision(aiRevision)
    setAiMessage('已载入改稿修订，当前正文仍保持只读。')
  }

  return <main className={`${styles.page} mg-page`} data-page-ownership="organization" data-accent="campaign" data-workspace-mode="organization_lark" data-read-only-mirror="true" data-document-sync-state={currentSyncState} data-ai-state={aiStateAttribute}>
    <header className="mg-hero" data-page-prelude><div><span className="mg-eyebrow">组织文档</span><h1>{humanArtifactKind(artifact?.artifactKind)}</h1><p className="mg-hero-lead">正文以飞书为唯一编辑权威，网页端仅提供只读回读镜像。</p></div><span className="mg-badge" data-tone="info"><ShieldCheck size={15} aria-hidden="true" />只读镜像</span></header>
    {showSyncBanner ? <section className={`${styles.syncBanner} ${styles[`sync${currentSyncState[0].toUpperCase()}${currentSyncState.slice(1)}`]}`} role="alert" data-document-sync-state={currentSyncState}><div><TriangleAlert size={18} aria-hidden="true" /><div><strong data-sync-state={currentSyncState}>{syncStateLabels[currentSyncState]}</strong><p>{syncError || syncMessage(currentSyncState, latestBatch)}</p>{technicalCode ? <small>技术参考码：{technicalCode}</small> : null}</div></div><button type="button" className="mg-btn mg-btn-ghost" data-sync-action={syncAction} onClick={() => setRetryToken((value) => value + 1)}><RefreshCw size={15} />重新读取</button></section> : null}
    <section className={`${styles.panel} mg-panel`} aria-label="组织文档正文"><header className={styles.header}><div><span className={styles.kicker}><FileText size={15} />回读正文</span><h2>{humanArtifactKind(artifact?.artifactKind)}</h2></div>{documentUrl ? <a className="mg-btn mg-btn-primary" href={documentUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} />在飞书中打开</a> : null}</header>{state.status === 'loading' || state.status === 'idle' ? <MirrorState kind="loading" title="正在读取组织正文" detail="等待服务端回读结果。" /> : state.status === 'ready' && visibleRevision ? <><div className={styles.meta}><span>正文权威 <b>飞书</b></span><span>{previewRevision ? '当前预览' : '镜像版本'} <b>{previewRevision ? `v${visibleRevision.revision}` : visibleRevision.remoteDocumentVersion || '未记录'}</b></span><span>回读于 <b>{formatDateOnly(visibleRevision.updatedAt, { empty: '未记录', invalid: '未记录' })}</b></span><span>校验值 <b>{visibleRevision.bodyChecksum ? `${visibleRevision.bodyChecksum.slice(0, 12)}...` : '未记录'}</b></span></div>{previewRevision ? <div className={styles.previewBadge}><Sparkles size={14} />已载入改稿修订 · 仅限当前页面只读预览</div> : <div className={styles.mirrorBadge}><ShieldCheck size={14} />只读镜像 · 不可在网页端编辑</div>}<CanonicalDocumentRenderer blocks={visibleRevision.body.blocks} highlightedBlockIds={currentSyncState === 'unsupported' ? blockRefs : []} /></> : <MirrorState kind={state.status === 'empty' ? 'empty' : state.status === 'unauthorized' ? 'permission' : state.status === 'notFound' ? 'notFound' : 'error'} title={state.status === 'empty' ? '文档暂无正文' : state.status === 'unauthorized' ? '当前会话未获授权' : state.status === 'notFound' ? '文档暂不可见' : '组织正文暂不可读取'} detail={'message' in state ? state.message : '服务端没有返回可确认的正文。'} action={<button type="button" className="mg-btn mg-btn-ghost" onClick={() => setRetryToken((value) => value + 1)}><RefreshCw size={15} />重新读取</button>} />}</section>
    <section className={`${styles.aiDock} mg-panel`} aria-labelledby="organization-ai-dock-title" data-ai-state={aiStateAttribute} data-ai-required-capability="document_edit" aria-busy={aiStatus === 'generating'}><header className={styles.aiHeader}><div><span className={styles.kicker}><Sparkles size={15} />AI 改稿修订</span><h2 id="organization-ai-dock-title">让 AI 改稿</h2><p>网页端不直接编辑组织正文。提交后由服务端按当前组织绑定执行，并通过修订回读确认结果。</p></div><span className="mg-badge" data-tone="info">只读预览</span></header><form className={styles.aiForm} onSubmit={(event) => { event.preventDefault(); void createAiRevision() }}><label htmlFor="organization-ai-instruction">改稿要求</label><textarea id="organization-ai-instruction" aria-describedby="organization-ai-hint" value={aiInstruction} onChange={(event) => setAiInstruction(event.target.value)} disabled={aiStatus === 'generating'} placeholder="例如：把正文开头改得更清楚，并保留受保护内容。" rows={3} /><div className={styles.aiFormFooter}><p id="organization-ai-hint">需要具备改稿权限的组织成员。受保护内容与结构不会在网页端直接改写。</p><button type="submit" className="mg-btn mg-btn-primary" disabled={!sourceRevision || !aiInstruction.trim() || aiStatus === 'generating'}>{aiStatus === 'generating' ? <LoaderCircle className={styles.spin} size={15} aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}{aiStatus === 'generating' ? '正在生成' : '生成改稿修订'}</button></div></form>{aiStatus === 'generating' ? <div className={styles.aiProgress} role="status" aria-live="polite"><div><LoaderCircle className={styles.spin} size={18} aria-hidden="true" /><div><strong>正在生成改稿修订</strong><p>{aiMessage || '服务端正在处理当前组织绑定，页面会根据修订状态更新。'}</p></div></div><span className="mg-badge" data-tone="warning">生成中</span></div> : null}{aiStatus === 'ready' && aiRevision ? <AiRevisionResult revision={aiRevision} receipt={aiReceipt} technicalCode={aiTechnicalCode} onLoad={loadAiRevision} /> : null}{aiStatus === 'failed' ? <div className={styles.aiFailure} role="alert"><TriangleAlert size={18} aria-hidden="true" /><div><strong>改稿结果暂不可用</strong><p>{aiMessage || '改稿请求暂时失败。请稍后重新发起。'}</p>{aiTechnicalCode ? <small>技术参考码：{aiTechnicalCode}</small> : null}</div></div> : null}</section>
    <section className={`${styles.ledger} mg-panel`} aria-label="同步账本" data-sync-ledger="true"><header className={styles.ledgerHead}><div><span className={styles.kicker}><CheckCircle2 size={15} />同步账本</span><h2>最近同步记录</h2><p>记录仅反映服务端已返回的同步状态，不替代飞书正文。</p></div><span className="mg-badge" data-sync-state={currentSyncState}>{syncStateLabels[currentSyncState]}</span></header><ol className={styles.pipeline} aria-label="同步链路" data-sync-pipeline={currentSyncState}>{syncPipeline.map((step, index) => <li key={step.title} data-sync-step={index + 1} data-sync-step-state={step.state}><span aria-hidden="true">{index + 1}</span><div><strong>{step.title}</strong><small>{step.detail}</small></div></li>)}</ol>{currentSyncState === 'partial' ? <dl className={styles.receipt}><ReceiptList label="已应用" values={applied} /><ReceiptList label="需要人工处理" values={manualActions} /><ReceiptList label="受保护未改动" values={protectedSkipped} /></dl> : null}{currentSyncState === 'unsupported' && blockRefs.length > 0 ? <p className={styles.blockRefs}>涉及 {blockRefs.map(receiptLabel).join('、')}，请在飞书中处理该正文块后重新读取。</p> : null}{syncLoadState === 'loading' || syncLoadState === 'idle' ? <p className={styles.ledgerState}>正在读取同步账本。</p> : batches.length === 0 ? <p className={styles.ledgerState}>服务端尚未返回可展示的同步记录。</p> : <ol className={styles.batchList}>{batches.map((batch) => <li key={batch.publicSyncId}><div><strong>{batch.operation === 'read' ? '回读镜像' : '写入飞书'}</strong><span>{batchStateLabel(batch)}</span></div><dl><div><dt>远端版本</dt><dd>{batch.remoteDocumentVersion || '等待确认'}</dd></div><div><dt>完成时间</dt><dd>{formatDateTime(batch.completedAt || batch.updatedAt, { empty: '未完成', invalid: '时间不可读' })}</dd></div></dl></li>)}</ol>}{nextCursor ? <button type="button" className="mg-btn mg-btn-ghost" onClick={() => void loadMore()} disabled={loadingMore}>{loadingMore ? '正在加载' : '加载更多记录'}</button> : null}</section>
    <section className={`${styles.binding} mg-panel`} aria-label="组织绑定信息"><h2>组织绑定</h2><dl><div><dt>组织</dt><dd>{session.organizationName || '未记录'}</dd></div><div><dt>成员角色</dt><dd>{session.memberRole === 'owner' ? '组织负责人' : '组织成员'}</dd></div><div><dt>文档标识</dt><dd>{artifactId}</dd></div></dl></section>
  </main>
}

function batchStateLabel(batch: DocumentSyncBatch): string { if (isUnknown(batch)) return '写入结果待对账'; if (batch.state === 'running' || batch.state === 'queued') return '正在处理'; if (batch.state === 'succeeded') return '已完成'; if (batch.state === 'conflict') return '需要处理冲突'; if (isUnsupported(batch)) return '结构暂不支持'; return '未完成' }
function ReceiptList({ label, values }: { label: string; values: string[] }) { return <div><dt>{label}</dt><dd>{values.length ? values.map(receiptLabel).join('、') : '无'}</dd></div> }
function MirrorState({ kind, title, detail, action }: { kind: SurfaceStateKind; title: string; detail: string; action?: ReactNode }) { return <SurfaceState kind={kind} title={title} detail={detail} action={action} /> }

function AiReceiptPart({ label, kind, part }: { label: string; kind: 'applied' | 'manual' | 'protected'; part: ReceiptPart }) {
  return <section className={styles.aiReceiptPart} data-receipt-part={kind} data-receipt-availability={part.available ? 'available' : 'missing'}><div className={styles.aiReceiptPartHead}><strong>{label}</strong><span>{part.available ? part.values.length ? `${part.values.length} 项` : '无' : '未提供'}</span></div>{part.available && part.values.length ? <ul>{part.values.map((value, index) => <li key={`${kind}-${index}`}>{aiReceiptItemLabel(value, index, kind)}</li>)}</ul> : <p>{part.available ? '服务端未报告此类结果。' : '本次回读未提供此项执行回执。'}</p>}</section>
}

function AiRevisionResult({ revision, receipt, technicalCode, onLoad }: { revision: DocumentRevisionRecord; receipt: AiExecutionReceipt | null; technicalCode: string | null; onLoad: () => void }) {
  const applied = readReceiptPart(receipt, 'applied')
  const manual = readReceiptPart(receipt, 'manualActions')
  const protectedSkipped = readReceiptPart(receipt, 'protectedSkipped')
  const appliedCount = readReceiptCount(receipt)
  return <div className={styles.aiResult} data-ai-result="ready"><header className={styles.aiResultHeader}><div><span className={styles.kicker}><CheckCircle2 size={15} />执行结果</span><h3>改稿修订已就绪。</h3><p>服务端已完成本次改稿修订，以下内容只显示实际回读到的执行回执。</p></div><span className={styles.aiRevisionLabel}>修订 v{revision.revision}</span></header><div className={styles.aiResultMeta}><span>已应用数量 <b>{appliedCount === null ? '未提供' : appliedCount}</b></span><span>执行回执 <b>{receipt ? '已回读' : '未提供'}</b></span></div><div className={styles.aiReceipt} aria-label="AI 改稿执行回执"><AiReceiptPart label="已应用" kind="applied" part={applied} /><AiReceiptPart label="需要人工处理" kind="manual" part={manual} /><AiReceiptPart label="受保护未改动" kind="protected" part={protectedSkipped} /></div><div className={styles.aiResultFooter}><p>载入后仅在本页预览修订，不会绕过组织绑定直接写入正文。</p><button type="button" className="mg-btn mg-btn-primary" onClick={onLoad}><FileText size={15} aria-hidden="true" />载入此修订</button></div>{technicalCode ? <small className={styles.technicalReference}>技术参考码：{technicalCode}</small> : null}</div>
}
