import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertCircle, ArrowLeft, Bot, CheckCircle2, Clock3, FileCheck2, FilePenLine, Film,
  History, Layers3, LoaderCircle, Lock, LockOpen, MessageSquareText, PackageCheck,
  RefreshCw, RotateCcw, Save, Send, Sparkles, Target,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useMediaWeb } from './MediaWebWorkspace'
import { BusinessOperationError, callBusinessOperation } from './generatedBusinessPagesContract'
import { loginUrl } from './mediaWebApi'
import { runStatusLabel, runStatusTone } from './statusPresentation'
import { PlatformIdentity } from './ui/PlatformIdentity'
import { mediaTypeDisplayLabel } from './ui/ordinaryDataLabels'
import styles from './CreationRunDetailPage.module.css'

type SectionName = 'sources' | 'decisions' | 'outputs'
type EditorKind = 'script' | 'storyboard' | 'shooting' | 'publish'
type InspectorTab = 'brief' | 'agent' | 'versions'
type Value = string | number | boolean | null | readonly (string | number | boolean | null)[]
type ValueMap = Readonly<Record<string, Value>>

type Run = {
  publicRunId: string; title: string; platform: string | null; contentType: string | null;
  trackName: string | null; entrypoint: string; status: string; availableSections: SectionName[];
  publicProjectId: string | null; updatedAt: string; revision: number
}
type RunResponse = { revision: number; run: Run }
type Evidence = { kind: string; label: string; publicUrl: string | null; qualityStatus: 'verified' | 'partial' | 'unverified' | 'unavailable' }
type SourceSection = { sourceKinds: string[]; evidenceRefs: Evidence[] }
type Decision = { publicDecisionId: string; candidateTitle: string; platform: string; trackName: string; decisionStatus: string; evidenceCount: number }
type DecisionSection = { decisionItems: Decision[]; humanState: string }
type OutputSection = { outputVariants: ValueMap[] }
type Sections = { sources: SourceSection | null; decisions: DecisionSection | null; outputs: OutputSection | null }
type Block = { id: string; label: string; text: string; kind: EditorKind; locked: boolean; sourceKey: string }
type Snapshot = { id: string; label: string; createdAt: string; blocks: Block[] }
type LoadState<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; message: string }

const editorTabs: Array<{ id: EditorKind; label: string; icon: typeof FilePenLine }> = [
  { id: 'script', label: '创作脚本', icon: FilePenLine },
  { id: 'storyboard', label: '分镜脚本', icon: Film },
  { id: 'shooting', label: '拍摄执行', icon: Target },
  { id: 'publish', label: '发布包', icon: PackageCheck },
]

export default function CreationRunDetailPage() {
  const { runId = '' } = useParams()
  const { runtimeState, session, openWorkspace } = useMediaWeb()
  const [runState, setRunState] = useState<LoadState<RunResponse>>({ status: 'loading' })
  const [sectionState, setSectionState] = useState<LoadState<Sections>>({ status: 'loading' })
  const [blocks, setBlocks] = useState<Block[]>([])
  const [activeKind, setActiveKind] = useState<EditorKind>('script')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('brief')
  const [instruction, setInstruction] = useState('')
  const [notice, setNotice] = useState('')
  const [versions, setVersions] = useState<Snapshot[]>([])

  useEffect(() => {
    if (runtimeState !== 'authenticated' || !session || !runId) return
    const controller = new AbortController()
    setRunState({ status: 'loading' })
    callBusinessOperation<RunResponse>('getRun', { path: { publicRunId: runId }, signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setRunState({ status: 'ready', data }) })
      .catch((error: unknown) => { if (!controller.signal.aborted) setRunState({ status: 'error', message: readError(error) }) })
    return () => controller.abort()
  }, [runId, runtimeState, session])

  useEffect(() => {
    if (runState.status !== 'ready') return
    const run = runState.data.run
    setSectionState({ status: 'loading' })
    let active = true
    const source = run.availableSections.includes('sources')
      ? callBusinessOperation<{ section: SourceSection }>('getRunSources', { path: { publicRunId: run.publicRunId } }).then((value) => value.section)
      : Promise.resolve(null)
    const decisions = run.availableSections.includes('decisions')
      ? callBusinessOperation<{ section: DecisionSection }>('getRunDecisions', { path: { publicRunId: run.publicRunId } }).then((value) => value.section)
      : Promise.resolve(null)
    const outputs = run.availableSections.includes('outputs')
      ? callBusinessOperation<{ section: OutputSection }>('getRunOutputs', { path: { publicRunId: run.publicRunId } }).then((value) => value.section)
      : Promise.resolve(null)
    void Promise.all([source, decisions, outputs])
      .then(([sources, decisionData, outputData]) => { if (active) setSectionState({ status: 'ready', data: { sources, decisions: decisionData, outputs: outputData } }) })
      .catch((error: unknown) => { if (active) setSectionState({ status: 'error', message: readError(error) }) })
    return () => { active = false }
  }, [runState])

  const serverBlocks = useMemo(() => sectionState.status === 'ready' ? buildBlocks(sectionState.data.outputs?.outputVariants ?? []) : [], [sectionState])
  const storageKey = `mediaclaw:studio-draft:${runId}`

  useEffect(() => {
    if (!serverBlocks.length) return
    const stored = readSnapshots(storageKey)
    const initial = stored[0]?.blocks.length ? stored[0].blocks : serverBlocks
    setVersions(stored)
    setBlocks(initial)
    setSelectedId(initial[0]?.id ?? null)
  }, [serverBlocks, storageKey])

  const visibleBlocks = useMemo(() => blocks.filter((block) => block.kind === activeKind), [activeKind, blocks])
  const selected = blocks.find((block) => block.id === selectedId) ?? visibleBlocks[0] ?? null
  const original = selected ? serverBlocks.find((block) => block.id === selected.id) ?? null : null
  const dirtyCount = blocks.filter((block) => {
    const base = serverBlocks.find((item) => item.id === block.id)
    return !base || base.text !== block.text || base.locked !== block.locked
  }).length

  useEffect(() => {
    if (selected?.kind === activeKind) return
    setSelectedId(visibleBlocks[0]?.id ?? null)
  }, [activeKind, selected, visibleBlocks])

  if (runtimeState === 'checking' || runState.status === 'loading') return <Loading />
  if (runtimeState === 'unauthenticated') return <Gate icon={<FilePenLine size={24} />} title="登录后进入 Studio" detail="当前创作运行只对所属账户开放。" action={<a className="primary-button" href={loginUrl()}>登录</a>} />
  if (runtimeState === 'unavailable' || runState.status === 'error') return <Gate icon={<AlertCircle size={24} />} title="Studio 暂时不可用" detail={runState.status === 'error' ? runState.message : '任务服务尚未连接。'} />
  const run = runState.data.run

  function updateText(text: string) {
    if (!selected || selected.locked) return
    setBlocks((current) => current.map((block) => block.id === selected.id ? { ...block, text } : block))
  }

  function toggleLock() {
    if (!selected) return
    setBlocks((current) => current.map((block) => block.id === selected.id ? { ...block, locked: !block.locked } : block))
  }

  function resetSelected() {
    if (!selected || !original) return
    setBlocks((current) => current.map((block) => block.id === selected.id ? { ...original } : block))
  }

  function saveDraft() {
    const snapshot: Snapshot = { id: `draft-${Date.now()}`, label: `浏览器草稿 V${versions.length + 1}`, createdAt: new Date().toISOString(), blocks: blocks.map((block) => ({ ...block })) }
    const next = [snapshot, ...versions].slice(0, 12)
    localStorage.setItem(storageKey, JSON.stringify(next))
    setVersions(next)
    setNotice('浏览器草稿已保存；服务端权威版本没有被覆盖。')
  }

  async function sendPatchRequest() {
    if (!selected) return
    const request = [
      '修改内容项目', `运行编号：${run.publicRunId}`, `修改位置：${selected.label}`,
      `当前内容：${selected.text}`, `希望改成什么：${instruction.trim() || '只优化当前区块，不覆盖其他已确认内容。'}`,
      '要求：返回局部 Patch 和修改前后差异；尊重人工锁定。',
    ].join('\n')
    try { await navigator.clipboard.writeText(request); setNotice('局部修改请求已复制。') } catch { setNotice('任务窗口已打开，请手工复制当前区块和要求。') }
    openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })
  }

  return (
    <main className={styles.page} data-run-detail-layout="compact">
      <section className={styles.prelude} data-page-prelude>
        <Link className={styles.backLink} to="/studio"><ArrowLeft size={16} />返回 Studio</Link>
        <div className={styles.headingRow}>
          <div className={styles.titleBlock}><span>CREATIVE PROJECT · {run.entrypoint || '创作运行'}</span><h1>{run.title}</h1><p>在同一份活稿里维护脚本、分镜、拍摄执行和发布包；浏览器草稿不会伪装成服务端版本。</p></div>
          <div className={styles.headingActions}>
            <span className={styles.statusBadge} data-tone={runStatusTone(run.status)}><i />{runStatusLabel(run.status)}</span>
            <button className={styles.secondaryButton} type="button" disabled={!serverBlocks.length} onClick={() => { setBlocks(serverBlocks); setSelectedId(serverBlocks[0]?.id ?? null) }}><RotateCcw size={16} />恢复服务器版本</button>
            <button className={styles.primaryButton} type="button" disabled={!blocks.length} onClick={saveDraft}><Save size={16} />保存草稿{dirtyCount ? <b>{dirtyCount}</b> : null}</button>
          </div>
        </div>
      </section>

      <section className={styles.summaryBand} aria-label="项目摘要">
        <Summary icon={<CheckCircle2 size={17} />} label="运行状态" value={runStatusLabel(run.status)} />
        <Summary icon={<Target size={17} />} label="平台与赛道" value={<span>{run.platform ? <PlatformIdentity platform={run.platform} size="sm" /> : '未记录'}{run.trackName ? <small>{run.trackName}</small> : null}</span>} />
        <Summary icon={<FileCheck2 size={17} />} label="内容形态" value={run.contentType ? mediaTypeDisplayLabel(run.contentType) : '未记录'} />
        <Summary icon={<Clock3 size={17} />} label="当前修订" value={`R${run.revision} · ${formatDate(run.updatedAt)}`} />
      </section>

      <div className={styles.contentGrid}>
        <section className={styles.editorPanel}>
          <header className={styles.editorHeader}><div><Layers3 size={18} /><span><strong>活稿编辑器</strong><small>{dirtyCount ? `${dirtyCount} 个区块有本地修改` : '与服务器版本一致'}</small></span></div><div><button type="button" disabled={!selected} onClick={toggleLock}>{selected?.locked ? <Lock size={15} /> : <LockOpen size={15} />}{selected?.locked ? '已锁定' : '锁定区块'}</button><button type="button" disabled={!original} onClick={resetSelected}><RefreshCw size={15} />重置区块</button></div></header>
          {sectionState.status === 'loading' ? <State icon={<LoaderCircle className={styles.spin} size={22} />} title="正在读取脚本与成果" /> : null}
          {sectionState.status === 'error' ? <State icon={<AlertCircle size={22} />} title={sectionState.message} /> : null}
          {sectionState.status === 'ready' && !serverBlocks.length ? <State icon={<FilePenLine size={23} />} title="这条运行还没有可编辑输出" detail="先在任务中心生成并持久化脚本、分镜或发布包。" action={<button type="button" onClick={() => openWorkspace({ capabilityId: 'selfmedia_creation', variantId: 'default' })}><Sparkles size={16} />继续生成</button>} /> : null}
          {blocks.length ? <div className={styles.editorGrid}>
            <aside className={styles.outline}>
              <div className={styles.editorTabs} role="tablist" aria-label="创作产物类型">{editorTabs.map(({ id, label, icon: Icon }) => <button type="button" role="tab" aria-selected={activeKind === id} className={activeKind === id ? styles.activeTab : undefined} key={id} onClick={() => setActiveKind(id)}><Icon size={16} /><span>{label}</span><b>{blocks.filter((block) => block.kind === id).length}</b></button>)}</div>
              <div className={styles.blockList}>{visibleBlocks.length ? visibleBlocks.map((block, index) => <button type="button" className={block.id === selected?.id ? styles.selectedBlock : undefined} key={block.id} onClick={() => setSelectedId(block.id)}><span>{index + 1}</span><div><strong>{block.label}</strong><small>{block.text.slice(0, 42) || '空区块'}</small></div>{block.locked ? <Lock size={13} /> : null}</button>) : <p>当前类型暂无区块。</p>}</div>
            </aside>
            <div className={styles.canvas}>{selected ? <>
              <div className={styles.canvasMeta}><span>{kindLabel(selected.kind)}</span><strong>{selected.label}</strong><small>{selected.locked ? '人工锁定；编辑或 AI 修改前需解锁' : '可直接编辑，保存后形成浏览器草稿版本'}</small></div>
              <textarea aria-label={`编辑 ${selected.label}`} value={selected.text} readOnly={selected.locked} onChange={(event) => updateText(event.target.value)} />
              <div className={styles.canvasFooter}><span>{selected.text.length} 字符</span><span>来源字段：{humanize(selected.sourceKey)}</span></div>
              {original && original.text !== selected.text ? <section className={styles.diffCard} aria-label="修改差异"><header><span><History size={16} />当前区块差异</span><small>服务端原文 → 浏览器草稿</small></header><div><article><strong>修改前</strong><p>{original.text}</p></article><article><strong>修改后</strong><p>{selected.text}</p></article></div></section> : null}
            </> : <State icon={<FilePenLine size={22} />} title="选择一个区块开始编辑" />}</div>
          </div> : null}
        </section>

        <aside className={styles.inspectorPanel}>
          <div className={styles.inspectorTabs} role="tablist" aria-label="Studio 辅助面板">
            <button type="button" role="tab" aria-selected={inspectorTab === 'brief'} className={inspectorTab === 'brief' ? styles.activeInspectorTab : undefined} onClick={() => setInspectorTab('brief')}><MessageSquareText size={15} />Brief</button>
            <button type="button" role="tab" aria-selected={inspectorTab === 'agent'} className={inspectorTab === 'agent' ? styles.activeInspectorTab : undefined} onClick={() => setInspectorTab('agent')}><Bot size={15} />Agent</button>
            <button type="button" role="tab" aria-selected={inspectorTab === 'versions'} className={inspectorTab === 'versions' ? styles.activeInspectorTab : undefined} onClick={() => setInspectorTab('versions')}><History size={15} />版本</button>
          </div>
          <div className={styles.inspectorBody}>
            {inspectorTab === 'brief' ? <Brief state={sectionState} run={run} /> : null}
            {inspectorTab === 'agent' ? <div className={styles.agentPanel}><span><Sparkles size={17} />局部修改请求</span><h2>{selected?.label ?? '先选择一个区块'}</h2><p>只把当前区块交给 Agent，不要求整篇重写。</p><label><span>希望怎么改</span><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：保留卖点，只把开头改成第一人称现场感。" /></label><button type="button" disabled={!selected} onClick={() => void sendPatchRequest()}><Send size={16} />复制请求并打开 Agent</button>{notice ? <div className={styles.notice}>{notice}</div> : null}<div className={styles.agentRule}><Lock size={16} /><span><strong>修改边界</strong><small>锁定区块不进入改写；本轮只提交选中区块的 Patch。</small></span></div></div> : null}
            {inspectorTab === 'versions' ? <div className={styles.versionPanel}><span><History size={17} />浏览器草稿版本</span><p>这些版本只保存在当前浏览器。</p>{versions.length ? <div>{versions.map((snapshot) => <button type="button" key={snapshot.id} onClick={() => { setBlocks(snapshot.blocks.map((block) => ({ ...block }))); setSelectedId(snapshot.blocks[0]?.id ?? null); setNotice(`已恢复 ${snapshot.label}。`) }}><span><strong>{snapshot.label}</strong><small>{formatDate(snapshot.createdAt)} · {snapshot.blocks.length} 个区块</small></span><RefreshCw size={14} /></button>)}</div> : <State icon={<History size={21} />} title="还没有浏览器草稿" detail="修改后点击保存草稿即可创建版本。" />}</div> : null}
          </div>
        </aside>
      </div>
    </main>
  )
}

function Brief({ state, run }: { state: LoadState<Sections>; run: Run }) {
  if (state.status === 'loading') return <State icon={<LoaderCircle className={styles.spin} size={21} />} title="正在读取 Brief 与证据" />
  if (state.status === 'error') return <State icon={<AlertCircle size={21} />} title={state.message} />
  const { sources, decisions } = state.data
  return <div className={styles.briefPanel}><span><MessageSquareText size={17} />项目上下文</span><dl><div><dt>关联项目</dt><dd>{run.publicProjectId || '未关联项目'}</dd></div><div><dt>创作入口</dt><dd>{run.entrypoint || '未记录'}</dd></div><div><dt>来源类型</dt><dd>{sources?.sourceKinds.length ? sources.sourceKinds.join('、') : '未记录'}</dd></div><div><dt>人工决策</dt><dd>{decisions ? humanStateLabel(decisions.humanState) : '未记录'}</dd></div></dl><section><header><strong>已确认方向</strong><small>{decisions?.decisionItems.length ?? 0} 条</small></header>{decisions?.decisionItems.length ? decisions.decisionItems.slice(0, 4).map((item) => <article key={item.publicDecisionId}><span>{item.decisionStatus === 'confirmed' ? <CheckCircle2 size={15} /> : <Target size={15} />}</span><div><strong>{item.candidateTitle}</strong><small>{item.trackName || item.platform} · {item.evidenceCount} 条证据</small></div></article>) : <p>当前运行没有已持久化决定。</p>}</section><section><header><strong>证据引用</strong><small>{sources?.evidenceRefs.length ?? 0} 条</small></header>{sources?.evidenceRefs.length ? sources.evidenceRefs.slice(0, 5).map((item) => <a key={`${item.kind}-${item.label}`} href={item.publicUrl || undefined} aria-disabled={!item.publicUrl} target={item.publicUrl ? '_blank' : undefined} rel={item.publicUrl ? 'noreferrer' : undefined}><span><Layers3 size={15} /></span><div><strong>{item.label}</strong><small>{qualityLabel(item.qualityStatus)}</small></div></a>) : <p>当前运行没有可打开的证据引用。</p>}</section></div>
}

function Summary({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) { return <div className={styles.summaryItem}>{icon}<div><span>{label}</span><strong>{value}</strong></div></div> }
function State({ icon, title, detail, action }: { icon: ReactNode; title: string; detail?: string; action?: ReactNode }) { return <div className={styles.editorState}>{icon}<strong>{title}</strong>{detail ? <p>{detail}</p> : null}{action}</div> }
function Loading() { return <main className="detail-loading" aria-busy="true"><LoaderCircle className="spin" size={23} /><span>正在打开 Studio</span></main> }
function Gate({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: string; action?: ReactNode }) { return <main><Link className="back-link" to="/studio"><ArrowLeft size={16} />返回 Studio</Link><div className="detail-gate">{icon}<h1>{title}</h1><p>{detail}</p>{action}</div></main> }

function buildBlocks(variants: ValueMap[]): Block[] {
  const blocks: Block[] = []
  variants.forEach((variant, variantIndex) => Object.entries(variant).forEach(([key, raw]) => {
    const values = Array.isArray(raw) ? raw : [raw]
    values.forEach((value, valueIndex) => {
      if (value === null || value === undefined || !String(value).trim()) return
      const text = String(value).trim()
      blocks.push({ id: `${variantIndex}-${slug(key)}-${valueIndex}`, label: values.length > 1 ? `${humanize(key)} ${valueIndex + 1}` : humanize(key), text, kind: inferKind(key, text), locked: false, sourceKey: key })
    })
  }))
  return blocks.slice(0, 48)
}

function inferKind(key: string, text: string): EditorKind {
  const value = `${key} ${text.slice(0, 80)}`.toLowerCase()
  if (/storyboard|shot|scene|visual|镜头|分镜|画面/.test(value)) return 'storyboard'
  if (/shoot|route|checklist|onsite|拍摄|现场|路线|必拍|道具/.test(value)) return 'shooting'
  if (/publish|title|cover|hashtag|tag|caption|发布|标题|封面|正文|话题/.test(value)) return 'publish'
  return 'script'
}

function humanize(value: string): string {
  const labels: Record<string, string> = { title: '标题', body: '正文', publish_copy: '发布正文', opening_hook: '开头钩子', voiceover: '口播', storyboard: '分镜', shooting_script: '拍摄脚本', route_map: '拍摄路线', onsite_checklist: '现场检查', hashtags: '话题标签', cover_frame: '封面画面', content: '创作内容', script: '创作脚本' }
  return labels[value] ?? value.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')
}
function kindLabel(kind: EditorKind): string { return editorTabs.find((item) => item.id === kind)?.label ?? '内容区块' }
function slug(value: string): string { return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-').replace(/^-|-$/g, '') || 'block' }
function readSnapshots(key: string): Snapshot[] { try { const value = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value.filter((item): item is Snapshot => !!item && typeof item === 'object' && Array.isArray(item.blocks)) : [] } catch { return [] } }
function readError(error: unknown): string { if (error instanceof BusinessOperationError) { if (error.status === 401 || error.status === 403) return '当前账户无权查看这条运行。'; if (error.status === 404) return '这条创作运行不存在或已不可用。'; return error.message } return error instanceof Error && error.message ? error.message : '创作运行详情加载失败。' }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value || '暂无' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date) }
function humanStateLabel(value: string): string { return ({ pending: '待确认', confirmed: '已确认', rejected: '已拒绝' }[value] ?? '状态待确认') }
function qualityLabel(value: Evidence['qualityStatus']): string { return ({ verified: '已核验', partial: '部分可用', unverified: '待核验', unavailable: '不可用' }[value]) }
