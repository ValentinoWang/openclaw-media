import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, ChevronRight, LoaderCircle, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { useMediaWeb } from "../../MediaWebWorkspace";
import { createMediaJob, createMediaPairCode, loadMediaDevices, loadMediaJobs, loadMediaPipelines, loginUrl, type MediaWebSession } from "../../mediaWebApi";
import type { Device, LocalAgentJob, PipelineSummary } from "../../generatedProductContract";
import { PageHeading } from "../../ui/ordinaryPagePrimitives";
import { pipelineDisplayDescription, pipelineDisplayLabel } from "../../ui/displayLabels";
import { formatDateTime as sharedFormatDateTime } from "../../ui/datetime";
import { SurfaceState } from "../../ui/SurfaceState";
import { isCurrentW1Request } from "./w1RequestGuard";
import styles from "./MediaAgentPage.module.css";

type Tab = "pipelines" | "run" | "devices";
type DataState = "loading" | "permission" | "error" | "empty" | "ready";
type PageData = { pipelines: PipelineSummary[]; devices: Device[]; jobs: LocalAgentJob[] };
const EMPTY_DATA: PageData = { pipelines: [], devices: [], jobs: [] };
const TABS: Array<{ id: Tab; label: string }> = [
  { id: "devices", label: "设备与客户端" },
  { id: "run", label: "本地运行" },
  { id: "pipelines", label: "流程目录" },
];

function MediaAgentPage() {
  const { runtimeState, session } = useMediaWeb();
  const [tab, setTab] = useState<Tab>("devices");
  const [data, setData] = useState<PageData>(EMPTY_DATA);
  const [state, setState] = useState<DataState>("loading");
  const [error, setError] = useState("");
  const [selectedPipeline, setSelectedPipeline] = useState("");
  const [selectedDevice, setSelectedDevice] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [pairLabel, setPairLabel] = useState("我的 Mac");
  const [pairCode, setPairCode] = useState("");
  const controllerRef = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);

  const cancelPendingRequests = useCallback(() => {
    controllerRef.current?.abort();
    ++requestGeneration.current;
  }, []);

  const loadData = useCallback(async (currentSession: MediaWebSession) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const generation = ++requestGeneration.current;
    setState("loading");
    setError("");
    try {
      const [pipelines, devices, jobs] = await Promise.all([
        loadMediaPipelines(currentSession, controller.signal),
        loadMediaDevices(currentSession, controller.signal),
        loadMediaJobs(currentSession, { limit: 100 }, controller.signal),
      ]);
      if (!isCurrentW1Request(generation, requestGeneration.current, controller.signal)) return;
      const nextData = { pipelines: pipelines.pipelines, devices: devices.devices, jobs: jobs.jobs };
      setData(nextData);
      const availableDevices = devices.devices.filter((item) => item.state === "online");
      setSelectedPipeline((value) => pipelines.pipelines.some((item) => item.pipeline_id === value) ? value : pipelines.pipelines[0]?.pipeline_id || "");
      setSelectedDevice((value) => availableDevices.some((item) => item.device_id === value) ? value : availableDevices[0]?.device_id || "");
      setState(nextData.pipelines.length || nextData.devices.length || nextData.jobs.length ? "ready" : "empty");
    } catch (reason: unknown) {
      if (!isCurrentW1Request(generation, requestGeneration.current, controller.signal)) return;
      if (reason instanceof Error && reason.name === "AbortError") return;
      const status = (reason as { status?: number })?.status;
      setState(status === 401 || status === 403 ? "permission" : "error");
      setError("流程目录、设备列表或本地运行任务暂时无法读取。请点击“重试”重新读取。");
    }
  }, []);

  useEffect(() => {
    if (runtimeState === "unauthenticated" || !session) {
      cancelPendingRequests();
      setSelectedPipeline("");
      setSelectedDevice("");
      setPairCode("");
      setState(runtimeState === "unauthenticated" ? "permission" : "loading");
      return;
    }
    setSelectedPipeline("");
    setSelectedDevice("");
    void loadData(session);
    return cancelPendingRequests;
  }, [cancelPendingRequests, loadData, runtimeState, session]);

  async function runJob() {
    const pipeline = data.pipelines.find((item) => item.pipeline_id === selectedPipeline);
    const device = data.devices.find((item) => item.device_id === selectedDevice && item.state === "online");
    if (!session || !pipeline || !device) return;
    setBusy("job"); setNotice(""); setError("");
    try {
      const response = await createMediaJob(session, {
        pipeline_id: pipeline.pipeline_id,
        pipeline_version: pipeline.version,
        catalog_digest: pipeline.catalog_digest,
        device_id: device.device_id,
        input_refs: [],
        output_selection: [],
      });
      setData((current) => ({ ...current, jobs: [response.job, ...current.jobs] }));
      setNotice("已创建本地运行任务，等待 Mac Agent 领取。");
      setTab("run");
    } catch {
      setError("本地任务暂时无法创建。请稍后重试。");
    } finally { setBusy(""); }
  }

  async function requestPairCode() {
    if (!session || !pairLabel.trim()) return;
    setBusy("pair"); setNotice(""); setError("");
    try {
      const response = await createMediaPairCode(session, pairLabel.trim());
      setPairCode(response.pair_code);
      setNotice(`配对码有效期至 ${sharedFormatDateTime(response.expires_at)}`);
    } catch {
      setError("配对码暂时无法创建。请稍后重试。");
    } finally { setBusy(""); }
  }

  if (runtimeState === "checking") return <PageFrame><SurfaceState kind="loading" title="正在连接 Media Agent" detail="正在确认当前账户的网页权限。" /></PageFrame>;
  if (runtimeState === "unauthenticated" || state === "permission") return <PageFrame><SurfaceState kind="permission" title="登录后查看本端协作" detail="当前页面不会在无权限状态下读取设备或运行数据。" action={<a className="mg-btn mg-btn-primary" data-component="mg-btn" href={loginUrl()}>登录并继续 <ChevronRight size={14} /></a>} /></PageFrame>;
  if (runtimeState === "unavailable") return <PageFrame><SurfaceState kind="error" title="本端协作数据暂不可用" detail="远端控制面当前不可用，请稍后重试。" /></PageFrame>;
  if (state === "loading") return <PageFrame><SurfaceState kind="loading" title="正在读取本端协作状态" detail="正在读取流程、设备与运行任务。" /></PageFrame>;
  if (state === "error") return <PageFrame><SurfaceState kind="error" title="本端协作数据暂不可用" detail={error || "请稍后重试。"} action={<button className="mg-btn mg-btn-ghost" data-component="mg-btn" type="button" onClick={() => session && void loadData(session)}><RefreshCw size={14} />重试</button>} /></PageFrame>;
  if (state === "empty") return <PageFrame>
    <section className={`mg-panel ${styles.modeBar}`} data-component="mg-panel" aria-label="Media Agent 工作区"><div><span className={styles.modeMarker} aria-hidden="true" /><strong>本端协作控制面</strong><span className={styles.modeHint}>只展示远端账号状态，不读取本地路径或媒体字节。</span></div><span className={styles.catalogVersion}>{data.pipelines.length} 个流程 · {data.devices.length} 台设备</span></section>
    <SurfaceState kind="empty" title="暂无本端协作数据" detail="请先安装并启动 Mac 客户端，或完成设备配对。" />
    {notice ? <div className={styles.notice} role="status"><CheckCircle2 size={15} />{notice}</div> : null}
    {error ? <div className={styles.actionError} role="alert"><AlertCircle size={15} />{error}</div> : null}
    <nav className={styles.tabBar} data-component="mg-tabs" aria-label="Media Agent 功能标签" role="tablist"><TabButton tab="devices" active onClick={() => setTab("devices")}>设备与客户端</TabButton></nav>
    <TabPanel id="media-agent-panel-devices" labelledBy="media-agent-tab-devices"><DevicesTab devices={data.devices} pairLabel={pairLabel} pairCode={pairCode} setPairLabel={setPairLabel} onPair={() => void requestPairCode()} busy={busy === "pair"} /></TabPanel>
  </PageFrame>;

  return <PageFrame>
    <section className={`mg-panel ${styles.modeBar}`} data-component="mg-panel" aria-label="Media Agent 工作区"><div><span className={styles.modeMarker} aria-hidden="true" /><strong>本端协作控制面</strong><span className={styles.modeHint}>只展示远端账号状态，不读取本地路径或媒体字节。</span></div><span className={styles.catalogVersion}>{data.pipelines.length} 个流程 · {data.devices.length} 台设备</span></section>
    <nav className={styles.tabBar} data-component="mg-tabs" aria-label="Media Agent 功能标签" role="tablist" onKeyDown={(event) => handleTabKeyDown(event, tab, setTab)}>{TABS.map((item) => <TabButton key={item.id} tab={item.id} active={tab === item.id} onClick={() => setTab(item.id)}>{item.label}</TabButton>)}</nav>
    {notice ? <div className={styles.notice} role="status"><CheckCircle2 size={15} />{notice}</div> : null}
    {error ? <div className={styles.actionError} role="alert"><AlertCircle size={15} />{error}</div> : null}
    {tab === "pipelines" ? <TabPanel id="media-agent-panel-pipelines" labelledBy="media-agent-tab-pipelines"><PipelineTab pipelines={data.pipelines} /></TabPanel> : null}
    {tab === "run" ? <TabPanel id="media-agent-panel-run" labelledBy="media-agent-tab-run"><RunTab pipelines={data.pipelines} devices={data.devices.filter((item) => item.state === "online")} jobs={data.jobs} selectedPipeline={selectedPipeline} selectedDevice={selectedDevice} setSelectedPipeline={setSelectedPipeline} setSelectedDevice={setSelectedDevice} onRun={() => void runJob()} busy={busy === "job"} /></TabPanel> : null}
    {tab === "devices" ? <TabPanel id="media-agent-panel-devices" labelledBy="media-agent-tab-devices"><DevicesTab devices={data.devices} pairLabel={pairLabel} pairCode={pairCode} setPairLabel={setPairLabel} onPair={() => void requestPairCode()} busy={busy === "pair"} /></TabPanel> : null}
  </PageFrame>;
}

function PageFrame({ children }: { children: ReactNode }) {
  return <main className={styles.page + " fidelity-page"} data-page-ownership="personal" data-accent="agent">
    <div className={`${styles.prelude} mg-hero`} data-component="mg-hero" data-page-prelude><PageHeading title="Media Agent" description="Mac 本端流程、远端任务与设备配对。" /></div>
    <section className={styles.pageRail} data-page-layout="persistent-rail">
      <div className={styles.mainColumn} data-page-primary data-primary-flow>{children}</div>
      <aside className={`mg-panel ${styles.boundaryPanel}`} data-component="mg-panel" data-page-inspector data-page-terminal-surface="inspector" aria-label="本地媒体边界">
        <ShieldCheck size={19} />
        <div><strong>本地执行边界</strong><span>媒体字节与模型密钥留在 Mac；远端仅保存任务状态、描述符和明确归档的小产物。</span></div>
      </aside>
    </section>
  </main>;
}
function TabButton({ tab, active, onClick, children }: { tab: Tab; active: boolean; onClick: () => void; children: ReactNode }) { return <button id={`media-agent-tab-${tab}`} className="mg-tab" data-component="mg-tab" type="button" role="tab" tabIndex={active ? 0 : -1} aria-selected={active} aria-controls={`media-agent-panel-${tab}`} onClick={onClick}>{children}</button>; }

function handleTabKeyDown(event: KeyboardEvent<HTMLElement>, activeTab: Tab, setTab: (tab: Tab) => void) {
  const currentIndex = TABS.findIndex((item) => item.id === activeTab);
  const nextIndex = event.key === "ArrowRight"
    ? (currentIndex + 1) % TABS.length
    : event.key === "ArrowLeft"
      ? (currentIndex + TABS.length - 1) % TABS.length
      : event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : -1;
  if (nextIndex < 0) return;
  event.preventDefault();
  const nextTab = TABS[nextIndex];
  setTab(nextTab.id);
  requestAnimationFrame(() => document.getElementById(`media-agent-tab-${nextTab.id}`)?.focus());
}

function TabPanel({ id, labelledBy, children }: { id: string; labelledBy: string; children: ReactNode }) { return <section id={id} className={styles.tabPanel} role="tabpanel" aria-labelledby={labelledBy}>{children}</section>; }

function PipelineTab({ pipelines }: { pipelines: PipelineSummary[] }) {
  return <section className={`${styles.workspaceGrid} ${styles.workspaceGridSingle}`} data-page-terminal-surface="primary"><section className={`mg-panel ${styles.catalogPanel}`} data-component="mg-panel" aria-labelledby="pipeline-catalog-title"><PanelHeader eyebrow="已安装流程" title="流程目录" count={`${pipelines.length} 项`} id="pipeline-catalog-title" /><div className={styles.tableViewport} tabIndex={0} aria-label="流程目录表格"><table className={styles.catalogTable}><colgroup><col className={styles.pipelineColumn} /><col className={styles.versionColumn} /><col className={styles.purposeColumn} /></colgroup><thead><tr><th>流程</th><th>版本</th><th>用途</th></tr></thead><tbody>{pipelines.map((pipeline) => <tr key={pipeline.pipeline_id + pipeline.version}><th scope="row"><strong>{pipelineDisplayLabel(pipeline)}</strong></th><td>{pipeline.version}</td><td className={styles.pathText}>{pipelineDisplayDescription(pipeline)}</td></tr>)}</tbody></table></div></section></section>;
}

function RunTab({ pipelines, devices, jobs, selectedPipeline, selectedDevice, setSelectedPipeline, setSelectedDevice, onRun, busy }: { pipelines: PipelineSummary[]; devices: Device[]; jobs: LocalAgentJob[]; selectedPipeline: string; selectedDevice: string; setSelectedPipeline: (value: string) => void; setSelectedDevice: (value: string) => void; onRun: () => void; busy: boolean }) {
  return <section className={styles.workspaceGrid} data-page-terminal-surface="primary"><section className={`mg-panel ${styles.catalogPanel}`} data-component="mg-panel"><PanelHeader eyebrow="远端派发" title="本地运行" /><div className={styles.formStack}><label>处理流程<select value={selectedPipeline} onChange={(event) => setSelectedPipeline(event.target.value)}><option value="">选择处理流程</option>{pipelines.map((item) => <option key={item.pipeline_id} value={item.pipeline_id}>{pipelineDisplayLabel(item)} · {item.version}</option>)}</select></label><label>目标设备<select value={selectedDevice} onChange={(event) => setSelectedDevice(event.target.value)}><option value="">选择在线设备</option>{devices.map((item) => <option key={item.device_id} value={item.device_id}>{item.device_label} · {deviceStateLabel(item.state)}</option>)}</select></label><button className="mg-btn mg-btn-primary" data-component="mg-btn" type="button" disabled={busy || !selectedPipeline || !selectedDevice} onClick={onRun}>{busy ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}创建本地任务</button></div></section><JobPanel jobs={jobs} /></section>;
}

function JobPanel({ jobs }: { jobs: LocalAgentJob[] }) { return <section className={`mg-panel ${styles.taskPanel}`} data-component="mg-panel"><PanelHeader eyebrow="任务状态" title="本地运行任务" count={`${jobs.length} 项`} /><div className={styles.taskList}>{jobs.map((job) => { const tone = jobStateTone(job.state); return <article className={styles.taskItem} key={job.job_id}><div className={styles.taskHeader}><div className={styles.taskTitle}><span className={`${styles.statusDot} ${statusToneClass(tone)}`} aria-hidden="true" /><strong>{pipelineDisplayLabel({ pipeline_id: job.pipeline_id, version: job.pipeline_version, display_name: job.pipeline_id, catalog_digest: "" })}</strong><span className={`mg-badge ${styles.statusPill}`} data-component="mg-badge" data-tone={tone}>{jobStateLabel(job.state)}</span></div><span className={styles.muted}>{job.device_id ? "已分配设备" : "未分配设备"}</span></div><p className={styles.taskSummary}>版本 {job.pipeline_version} · 创建于 {formatDateTime(job.created_at)}</p></article>; })}</div></section>; }

function DevicesTab({ devices, pairLabel, pairCode, setPairLabel, onPair, busy }: { devices: Device[]; pairLabel: string; pairCode: string; setPairLabel: (value: string) => void; onPair: () => void; busy: boolean }) {
  return <section className={styles.workspaceGrid} data-page-terminal-surface="primary"><section className={`mg-panel ${styles.catalogPanel}`} data-component="mg-panel"><PanelHeader eyebrow="设备状态" title="设备与客户端" count={`${devices.length} 台`} /><div className={styles.taskList}>{devices.map((device) => { const tone = deviceStateTone(device.state); return <article className={styles.taskItem} key={device.device_id}><div className={styles.taskHeader}><div className={styles.taskTitle}><span className={`${styles.statusDot} ${statusToneClass(tone)}`} aria-hidden="true" /><strong>{device.device_label}</strong><span className={`mg-badge ${styles.statusPill}`} data-component="mg-badge" data-tone={tone}>{deviceStateLabel(device.state)}</span></div><span className={styles.muted}>{devicePlatformLabel(device.device_platform)}</span></div><p className={styles.taskSummary}>客户端版本 {device.client_version} · 最近连接 {formatDateTime(device.last_seen_at)}</p></article>; })}</div></section><section className={`mg-panel ${styles.inspectorPanel}`} data-component="mg-panel"><header className={`mg-panel-head ${styles.inspectorHeader}`} data-component="mg-panel-head"><div><span className="mg-eyebrow" data-component="mg-eyebrow">首次连接</span><h2>生成 Mac 配对码</h2></div><ShieldCheck size={18} /></header><div className={styles.formStack}><label>设备名称<input value={pairLabel} onChange={(event) => setPairLabel(event.target.value)} /></label><button className="mg-btn mg-btn-primary" data-component="mg-btn" type="button" disabled={busy || !pairLabel.trim()} onClick={onPair}>{busy ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}生成配对码</button>{pairCode ? <div className={styles.pairCode} aria-label="配对码">{pairCode}</div> : null}</div></section></section>;
}

function deviceStateLabel(value: string): string { return value === "online" ? "在线" : value === "offline" ? "离线" : value === "revoked" ? "已停用" : "待连接"; }
function devicePlatformLabel(value: string): string { return value === "macos" || value === "mac" ? "Mac" : value === "windows" ? "Windows" : value === "linux" ? "Linux" : "其他设备"; }
// Device-side job lease state machine (leased/acknowledged/running), independent from
// statusPresentation.ts's runStatusLabels (creation-run lifecycle) -- see dedup audit LE-07.
function jobStateLabel(value: string): string { return value === "queued" ? "排队中" : value === "leased" ? "已分配" : value === "acknowledged" ? "已确认" : value === "running" ? "运行中" : value === "succeeded" ? "已完成" : value === "blocked" ? "待处理" : value === "failed" ? "失败" : "待处理"; }
// Previously had no NaN guard (an unparseable value rendered the literal string "Invalid Date");
// delegating to the shared formatter fixes that in passing.
function formatDateTime(value: string | null | undefined): string { return sharedFormatDateTime(value, { empty: "暂无" }); }

function PanelHeader({ eyebrow, title, count, id }: { eyebrow: string; title: string; count?: string; id?: string }) { return <header className={`mg-panel-head ${styles.panelHeader}`} data-component="mg-panel-head"><div className={styles.panelHeaderContent}><span className="mg-eyebrow" data-component="mg-eyebrow">{eyebrow}</span><h2 id={id}>{title}</h2></div>{count ? <span className={styles.panelMeta}>{count}</span> : null}</header>; }

type StatusTone = "good" | "warn" | "info" | "danger" | "neutral";
function jobStateTone(value: string): StatusTone { return value === "succeeded" ? "good" : value === "failed" ? "danger" : value === "queued" || value === "blocked" ? "warn" : value === "running" || value === "leased" || value === "acknowledged" ? "info" : "neutral"; }
function deviceStateTone(value: string): StatusTone { return value === "online" ? "good" : value === "revoked" ? "danger" : value === "offline" ? "warn" : "neutral"; }
function statusToneClass(tone: StatusTone): string { return tone === "good" ? styles.statusSuccess : tone === "warn" ? styles.statusAttention : tone === "danger" ? styles.statusError : tone === "info" ? styles.statusInfo : styles.statusNeutral; }
export default MediaAgentPage;
