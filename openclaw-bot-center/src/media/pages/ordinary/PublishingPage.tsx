import { useEffect, useState, type ReactNode } from "react";
import {
  CheckCircle2,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileText,
  Info,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useMediaWeb } from "../../MediaWebWorkspace";
import { callBusinessOperation } from "../../generatedBusinessPagesContract";
import { newIdempotencyKey } from "../../idempotency";
import { PlatformIdentity } from "../../ui/PlatformIdentity";
import { describeBusinessError } from "../../ui/businessOperationError";
import { SurfaceState } from "../../ui/SurfaceState";
import { formatDate } from "../../ui/ordinaryPagePrimitives";
import { platformDisplayLabel } from "../../ui/platformRegistry";
import {
  artifactTypeDisplayLabel,
  bodyAuthorityDisplayLabel,
  qualityDisplayLabel,
  syncStatusDisplayLabel,
} from "../../ui/ordinaryDataLabels";
import { publishingStatusStage } from "../../statusPresentation";
import styles from "./PublishingPage.module.css";

const primaryButtonClass = ["mg-btn", "mg-btn-primary", styles.primaryAction].join(" ");
const secondaryButtonClass = ["mg-btn", "mg-btn-ghost", styles.secondaryButton].join(" ");
const iconButtonClass = ["mg-btn", "mg-btn-ghost", styles.iconButton].join(" ");
const listPanelClass = ["mg-panel", styles.listPanel].join(" ");
const detailPanelClass = ["mg-panel", styles.detailPanel].join(" ");
const panelHeaderClass = ["mg-panel-head", styles.panelHeader].join(" ");
const detailHeaderClass = ["mg-panel-head", styles.detailHeader].join(" ");

type ReadState<T> =
  | { status: "idle" | "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };
type Status = "draft" | "checking" | "ready" | "published";
type CheckKey = "content" | "publication";
type Notice = { kind: "success" | "error"; message: string } | null;

type PublishingPackage = {
  publicPackageId: string;
  publicRunId: string;
  platform: string;
  contentFields: Record<string, unknown>;
  ruleChecks: Array<Record<string, unknown>>;
  artifactDescriptor: {
    publicArtifactId: string;
    publicProjectId: string;
    artifactType: string;
    bodyAuthority: string;
    currentRevision: number;
    syncStatus: string;
    updatedAt: string;
    allowedActions: string[];
  };
  humanChecks: Array<{ key: string; checked: boolean; status?: string }>;
  status: Status;
  revision: number;
};
type PackageList = { schemaVersion: string; revision: number; items: PublishingPackage[]; nextCursor: string | null };
type PackageResponse = { schemaVersion: string; revision: number; package: PublishingPackage };
type Receipt = {
  publicPostId: string;
  publicPackageId: string;
  platform: string;
  publishedUrl: string;
  publishedAt: string;
  recordedBy: "user" | "admin";
  evidenceQuality: string;
};
type ReceiptResponse = { schemaVersion: string; revision: number; publishedPost: Receipt };
type DocxResponse = {
  schemaVersion: string;
  revision: number;
  document: { publicArtifactId: string; url: string; expiresAt: string };
};

const checks: Array<{ key: CheckKey; label: string; detail: string }> = [
  { key: "content", label: "内容字段已人工核对", detail: "核对标题、正文和平台字段。" },
  { key: "publication", label: "人工发布边界已确认", detail: "确认由人工完成发布并记录公开链接。" },
];

export default function PublishingPage() {
  const { runtimeState, session } = useMediaWeb();
  const [reload, setReload] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [list, setList] = useState<ReadState<PackageList>>({ status: "idle" });
  const [detail, setDetail] = useState<ReadState<PackageResponse>>({ status: "idle" });
  const [notice, setNotice] = useState<Notice>(null);

  useEffect(() => {
    if (runtimeState !== "authenticated" || !session) return;
    const controller = new AbortController();
    setList({ status: "loading" });
    setNotice(null);
    callBusinessOperation<PackageList>("listPublishingPackages", {
      query: { pageSize: 30 },
      signal: controller.signal,
    }).then((data) => {
      if (controller.signal.aborted) return;
      setList({ status: "ready", data });
      setSelectedId((current) =>
        current && data.items.some((item) => item.publicPackageId === current)
          ? current
          : data.items[0]?.publicPackageId ?? null,
      );
    }).catch((error: unknown) => {
      if (!controller.signal.aborted)
        setList({ status: "error", message: readError(error, "发布包暂时无法读取。") });
    });
    return () => controller.abort();
  }, [runtimeState, session, reload]);

  useEffect(() => {
    if (runtimeState !== "authenticated" || !session || !selectedId) {
      setDetail({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setDetail({ status: "loading" });
    callBusinessOperation<PackageResponse>("getPublishingPackage", {
      path: { publicPackageId: selectedId },
      signal: controller.signal,
    }).then((data) => {
      if (!controller.signal.aborted) setDetail({ status: "ready", data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted)
        setDetail({ status: "error", message: readError(error, "发布包详情暂时无法读取。") });
    });
    return () => controller.abort();
  }, [runtimeState, session, selectedId, reload]);

  const refresh = () => setReload((value) => value + 1);
  const updatePackage = (response: PackageResponse) => {
    setDetail({ status: "ready", data: response });
    setList((current) => current.status === "ready"
      ? { ...current, data: { ...current.data, items: current.data.items.map((item) =>
        item.publicPackageId === response.package.publicPackageId ? response.package : item) } }
      : current);
  };

  const listData = list.status === "ready" ? list.data : null;
  let body: ReactNode;
  if (runtimeState === "checking") {
    body = <State kind="loading" title="正在确认访问权限" detail="发布包将在身份确认后读取。" />;
  } else if (runtimeState === "unauthenticated" || !session) {
    body = <State kind="permission" title="需要登录才能查看发布准备" detail="此页面只展示当前账户可读的发布包和人工回执。" />;
  } else if (runtimeState === "unavailable") {
    body = <State kind="error" title="发布准备暂时不可用" detail="身份服务尚未连接，请稍后重新加载。" action={<button className={secondaryButtonClass} type="button" onClick={refresh}><RefreshCw size={15} aria-hidden="true" />重新读取</button>} />;
  } else if (list.status === "loading" || list.status === "idle") {
    body = <State kind="loading" title="正在读取发布包" detail="读取当前账户的发布准备信息。" />;
  } else if (list.status === "error") {
    body = <State kind="error" title="发布包读取失败" detail={list.message} action={<button className={secondaryButtonClass} type="button" onClick={refresh}><RefreshCw size={15} aria-hidden="true" />重新读取</button>} />;
  } else if (listData === null) {
    body = <State kind="error" title="发布包读取失败" detail="发布包数据不可用。" action={<button className={secondaryButtonClass} type="button" onClick={refresh}><RefreshCw size={15} aria-hidden="true" />重新读取</button>} />;
  } else {
    body = <PublishingWorkspace
      listData={listData}
      selectedId={selectedId}
      detail={detail}
      session={session}
      onSelect={setSelectedId}
      onRefresh={refresh}
      onUpdate={updatePackage}
      onNotice={setNotice}
    />;
  }

  const pageState = runtimeState === "authenticated" ? list.status : runtimeState;
  return <main className={["fidelity-page", styles.page].join(" ")} data-accent="campaign" data-page-ownership="personal" data-page-state={pageState}>
    <div className={styles.prelude} data-page-prelude>
      <header className="page-heading mg-hero" data-component="mg-hero">
        <div><span className="mg-eyebrow" data-component="mg-eyebrow">内容运营</span><h1>发布准备</h1><p>核对发布内容包、完成人工检查，并记录已经由人工发布的公开链接。</p></div>
        {runtimeState === "authenticated" ? <div className="page-heading-actions"><button className={primaryButtonClass} type="button" onClick={refresh} title="重新读取发布包"><RefreshCw size={15} aria-hidden="true" />刷新发布包</button></div> : null}
      </header>
    </div>
    <Boundary />
    {notice ? <div className={notice.kind === "error" ? styles.noticeError : styles.noticeSuccess} role={notice.kind === "error" ? "alert" : "status"}><CheckCircle2 size={16} aria-hidden="true" /><span>{notice.message}</span></div> : null}
    {body}
  </main>;
}

function Boundary() {
  return <aside className={styles.boundaryNotice}><span className={styles.boundaryIcon}><ShieldCheck size={16} aria-hidden="true" /></span><div><strong>人工发布边界</strong><p>页面只记录人工检查和人工提供的公开链接，不自动登录平台，也不自动发布。</p></div></aside>;
}

function PublishingWorkspace({ listData, selectedId, detail, session, onSelect, onRefresh, onUpdate, onNotice }: {
  listData: PackageList;
  selectedId: string | null;
  detail: ReadState<PackageResponse>;
  session: { csrfToken: string };
  onSelect: (id: string) => void;
  onRefresh: () => void;
  onUpdate: (response: PackageResponse) => void;
  onNotice: (notice: Notice) => void;
}) {
  const empty = listData.items.length === 0;
  return <div className={styles.workspace} data-empty-workspace={empty ? "" : undefined} data-page-layout="persistent-rail">
    {empty
      ? <EmptyPackageList onRefresh={onRefresh} />
      : <PackageList items={listData.items} selectedId={selectedId} onSelect={onSelect} onRefresh={onRefresh} />}
    {empty
      ? <EmptyPackageDetail />
      : <Detail state={detail} session={session} onRetry={onRefresh} onUpdate={onUpdate} onNotice={onNotice} />}
  </div>;
}

function EmptyPackageList({ onRefresh }: { onRefresh: () => void }) {
  return <section className={listPanelClass} data-component="mg-panel" data-page-primary data-primary-flow aria-label="发布包列表">
    <header className={panelHeaderClass}><div className={styles.panelHeading}><PackageCheck size={17} aria-hidden="true" /><div><h2>发布包</h2><p>0 条当前账户记录</p></div></div><button className={iconButtonClass} type="button" onClick={onRefresh} aria-label="重新读取发布包" title="重新读取"><RefreshCw size={16} aria-hidden="true" /></button></header>
    <SurfaceState kind="empty" title="暂无发布包" detail="发布包生成后会出现在这里。" density="compact" />
  </section>;
}

function EmptyPackageDetail() {
  return <section className={detailPanelClass} data-component="mg-panel" data-page-inspector data-page-terminal-surface="inspector" aria-label="发布包详情">
    <SurfaceState kind="empty" title="等待选择发布包" detail="选择发布包后，这里会显示发布内容、规则检查、人工检查和发布回执。" density="compact" />
  </section>;
}

function PackageList({ items, selectedId, onSelect, onRefresh }: { items: PublishingPackage[]; selectedId: string | null; onSelect: (id: string) => void; onRefresh: () => void }) {
  return <section className={listPanelClass} data-component="mg-panel" data-page-primary data-primary-flow aria-label="发布包列表">
    <header className={panelHeaderClass}><div className={styles.panelHeading}><PackageCheck size={17} aria-hidden="true" /><div><h2>发布包</h2><p>{items.length} 条当前账户记录</p></div></div><button className={iconButtonClass} type="button" onClick={onRefresh} aria-label="重新读取发布包" title="重新读取"><RefreshCw size={16} aria-hidden="true" /></button></header>
    <div className={styles.packageList} role="list">{items.map((item) => {
      const selected = item.publicPackageId === selectedId;
      return <div role="listitem" key={item.publicPackageId}>
        <button className={[styles.packageRow, selected ? styles.packageRowSelected : ""].join(" ")} type="button" aria-current={selected ? "true" : undefined} onClick={() => onSelect(item.publicPackageId)}>
          <span className={styles.packageRowTopline}><PlatformIdentity className={styles.packagePlatformIdentity} platform={item.platform} size="sm" /><StatusPill status={item.status} /></span>
          <span className={styles.packageRowId}>{item.publicPackageId}</span>
          <span className={styles.packageRowMeta}><span>修订 {item.revision}</span><span>{checkSummary(item.humanChecks)}</span><ChevronRight size={14} aria-hidden="true" /></span>
        </button>
      </div>;
    })}</div>
  </section>;
}

function Detail({ state, session, onRetry, onUpdate, onNotice }: { state: ReadState<PackageResponse>; session: { csrfToken: string }; onRetry: () => void; onUpdate: (response: PackageResponse) => void; onNotice: (notice: Notice) => void }) {
  if (state.status !== "ready") {
    if (state.status === "error") return <section className={detailPanelClass} data-component="mg-panel" data-page-inspector data-page-terminal-surface="inspector"><State kind="error" title="发布包详情读取失败" detail={state.message} action={<button className={secondaryButtonClass} type="button" onClick={onRetry}><RefreshCw size={15} aria-hidden="true" />重新读取</button>} /></section>;
    return <section className={detailPanelClass} data-component="mg-panel" data-page-inspector data-page-terminal-surface="inspector"><State kind="loading" title="正在读取发布包详情" detail="读取内容字段、规则检查和人工检查。" /></section>;
  }
  return <PackageDetail package={state.data.package} session={session} onUpdate={onUpdate} onNotice={onNotice} />;
}

function PackageDetail({ package: item, session, onUpdate, onNotice }: { package: PublishingPackage; session: { csrfToken: string }; onUpdate: (response: PackageResponse) => void; onNotice: (notice: Notice) => void }) {
  const [draft, setDraft] = useState<Record<CheckKey, boolean>>(() => readChecks(item));
  const [reason, setReason] = useState("");
  const [checkState, setCheckState] = useState<ReadState<PackageResponse>>({ status: "idle" });
  const [docxState, setDocxState] = useState<ReadState<DocxResponse>>({ status: "idle" });
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [url, setUrl] = useState("");
  const [publishedAt, setPublishedAt] = useState("");
  const [publicationState, setPublicationState] = useState<ReadState<ReceiptResponse>>({ status: "idle" });
  const [localError, setLocalError] = useState<string | null>(null);
  const packageId = item.publicPackageId;
  const serverContentChecked = checkValue(item, "content");
  const serverPublicationChecked = checkValue(item, "publication");

  useEffect(() => {
    setDraft({ content: serverContentChecked, publication: serverPublicationChecked });
    setReason("");
    setDocxState({ status: "idle" });
    setReceipt(null);
    setUrl("");
    setPublishedAt("");
    setPublicationState({ status: "idle" });
    setLocalError(null);
  }, [packageId, serverContentChecked, serverPublicationChecked]);

  const changed = draft.content !== checkValue(item, "content") || draft.publication !== checkValue(item, "publication");
  const savingChecks = checkState.status === "loading";
  const recording = publicationState.status === "loading";

  async function saveChecks() {
    if (item.status === "published" || !changed || savingChecks) return;
    if (!reason.trim()) { setLocalError("请填写人工检查记录。"); return; }
    setLocalError(null);
    setCheckState({ status: "loading" });
    try {
      const response = await callBusinessOperation<PackageResponse>("updatePublishingChecks", {
        path: { publicPackageId: item.publicPackageId },
        body: { expectedRevision: item.revision, checks: checks.map(({ key }) => ({ key, checked: draft[key], status: draft[key] ? "complete" : "pending" })), reason: reason.trim() },
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("publishing-checks"),
      });
      setCheckState({ status: "ready", data: response });
      setReason("");
      onUpdate(response);
      onNotice({ kind: "success", message: "人工检查已保存，页面已读取服务器回执。" });
    } catch (error: unknown) {
      setCheckState({ status: "error", message: readError(error, "人工检查保存失败。") });
    }
  }

  async function getDocx() {
    setDocxState({ status: "loading" });
    try {
      const response = await callBusinessOperation<DocxResponse>("getResourceDocxLink", { query: { publicArtifactId: item.artifactDescriptor.publicArtifactId } });
      setDocxState({ status: "ready", data: response });
    } catch (error: unknown) {
      setDocxState({ status: "error", message: readError(error, "受控 DOCX 链接暂不可用。") });
    }
  }

  async function recordPublication() {
    if (item.status !== "ready" || recording) return;
    if (!url.trim() || !publishedAt) { setLocalError("请填写已发布的公开链接和实际发布时间。"); return; }
    const date = new Date(publishedAt);
    if (Number.isNaN(date.getTime())) { setLocalError("实际发布时间无效。"); return; }
    setLocalError(null);
    setPublicationState({ status: "loading" });
    try {
      const created = await callBusinessOperation<ReceiptResponse>("createPublishedPost", {
        body: { publicPackageId: item.publicPackageId, expectedRevision: item.revision, platform: item.platform, publishedUrl: url.trim(), publishedAt: date.toISOString() },
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("published-post"),
      });
      const post = await callBusinessOperation<ReceiptResponse>("getPublishedPost", { path: { publicPostId: created.publishedPost.publicPostId } });
      const packageReadback = await callBusinessOperation<PackageResponse>("getPublishingPackage", { path: { publicPackageId: item.publicPackageId } });
      setReceipt(post.publishedPost);
      setPublicationState({ status: "ready", data: post });
      onUpdate(packageReadback);
      onNotice({ kind: "success", message: "人工发布回执已保存，并确认发布记录。" });
    } catch (error: unknown) {
      setPublicationState({ status: "error", message: readError(error, "人工发布回执保存失败。") });
    }
  }

  return <section className={detailPanelClass} data-component="mg-panel" data-page-inspector data-page-terminal-surface="inspector" aria-label="发布包详情">
    <header className={detailHeaderClass}><div className={styles.detailTitle}><span className={styles.detailIcon}><PackageCheck size={18} aria-hidden="true" /></span><div><h2 className={styles.detailHeading}><PlatformIdentity platform={item.platform} size="sm" /><span>发布包</span></h2><p>{item.publicPackageId}</p></div></div><StatusPill status={item.status} /></header>
    <div className={styles.detailScroll}>
      <section className={styles.factSection}><Heading icon={<FileText size={16} />} title="发布内容" detail="已保存的发布记录" /><dl className={styles.factGrid}><Fact label="关联运行" value={item.publicRunId} /><Fact label="平台" value={<PlatformIdentity platform={item.platform} size="sm" />} /><Fact label="修订" value={item.revision} /><Fact label="包状态" value={statusLabel(item.status)} /></dl><span className={styles.fieldLabel}>内容字段</span>{Object.keys(item.contentFields).length ? <dl className={styles.contentGrid}>{Object.entries(item.contentFields).map(([key, value], index) => <Fact key={key} label={contentFieldLabel(key, index)} value={formatValue(value)} />)}</dl> : <p className={styles.mutedText}>未提供内容字段。</p>}</section>
      <section className={styles.factSection}><Heading icon={<ShieldCheck size={16} />} title="规则检查" detail="规则输出与人工决定分开显示" />{item.ruleChecks.length ? <ul className={styles.ruleList}>{item.ruleChecks.map((check, index) => <li key={index}><span className={styles.ruleMarker} aria-hidden="true" /><span>{formatValue(check)}</span></li>)}</ul> : <p className={styles.mutedText}>未提供规则检查。</p>}</section>
      <section className={styles.factSection}><Heading icon={<FileText size={16} />} title="产物引用" detail="只读取服务端受控资源" /><dl className={styles.factGrid}><Fact label="公开产物 ID" value={item.artifactDescriptor.publicArtifactId} /><Fact label="公开项目 ID" value={item.artifactDescriptor.publicProjectId} /><Fact label="产物类型" value={artifactTypeDisplayLabel(item.artifactDescriptor.artifactType)} /><Fact label="正文来源" value={bodyAuthorityDisplayLabel(item.artifactDescriptor.bodyAuthority)} /><Fact label="当前修订" value={item.artifactDescriptor.currentRevision} /><Fact label="同步状态" value={syncStatusDisplayLabel(item.artifactDescriptor.syncStatus)} /></dl><div className={styles.resourceAction}>{docxState.status === "ready" ? <a className={secondaryButtonClass} href={docxState.data.document.url} target="_blank" rel="noreferrer"><ExternalLink size={15} aria-hidden="true" />打开 DOCX</a> : <button className={secondaryButtonClass} type="button" onClick={getDocx} disabled={docxState.status === "loading"}>{docxState.status === "loading" ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <FileText size={15} aria-hidden="true" />}获取受控 DOCX 链接</button>}{docxState.status === "ready" ? <span className={styles.expiryText}>有效至 {formatDate(docxState.data.document.expiresAt)}</span> : docxState.status === "error" ? <span className={styles.errorText}>{docxState.message}</span> : null}</div></section>
      <section className={styles.decisionSection}><Heading icon={<CheckCircle2 size={16} />} title="人工检查" detail="保存后以最新结果为准" /><div className={styles.checkList}>{checks.map(({ key, label, detail }) => <label className={styles.checkRow} key={key}><input type="checkbox" checked={draft[key]} disabled={item.status === "published" || savingChecks} onChange={() => setDraft((current) => ({ ...current, [key]: !current[key] }))} /><span className={styles.checkCopy}><strong>{label}</strong><small>{detail}</small></span><span className={draft[key] ? styles.checkComplete : styles.checkPending}>{draft[key] ? "已完成" : "待检查"}</span></label>)}</div>{item.status !== "published" ? <label className={styles.reasonField}><span>检查记录</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="填写本次人工检查记录" rows={3} disabled={savingChecks} /></label> : null}{checkState.status === "error" ? <p className={styles.errorText} role="alert">{checkState.message}</p> : null}{localError ? <p className={styles.errorText} role="alert">{localError}</p> : null}{item.status !== "published" ? <button className={primaryButtonClass} type="button" onClick={saveChecks} disabled={!changed || savingChecks}>{savingChecks ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <CheckCircle2 size={15} aria-hidden="true" />}保存人工检查</button> : null}</section>
      <section className={styles.publicationSection}><Heading icon={<ExternalLink size={16} />} title="人工发布回执" detail="页面只记录已经发生的人工发布" />{item.status === "ready" ? <div className={styles.publicationForm}><div className={styles.controlGrid}><label className={styles.field}><span>平台</span><input value={platformDisplayLabel(item.platform)} readOnly /></label><label className={styles.field}><span>实际发布时间</span><input type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} disabled={recording} /></label></div><label className={styles.field}><span>已发布公开链接</span><input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://" disabled={recording} /></label>{publicationState.status === "error" ? <p className={styles.errorText} role="alert">{publicationState.message}</p> : null}<button className={primaryButtonClass} type="button" onClick={recordPublication} disabled={recording}>{recording ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <CheckCircle2 size={15} aria-hidden="true" />}记录人工发布回执</button></div> : null}{item.status === "draft" || item.status === "checking" ? <div className={styles.inlineState}><Info size={16} aria-hidden="true" /><span>完成人工检查并确认“可发布”后，才可记录公开链接。</span></div> : null}{item.status === "published" && !receipt ? <div className={styles.inlineState}><CheckCircle2 size={16} aria-hidden="true" /><span>该发布包已有人工发布状态；本次页面会话没有可展示的回执链接。</span></div> : null}{receipt ? <ReceiptPanel receipt={receipt} /> : null}</section>
    </div>
  </section>;
}

function ReceiptPanel({ receipt }: { receipt: Receipt }) {
  return <div className={["mg-panel", styles.receiptPanel].join(" ")} data-component="mg-panel"><div className={styles.receiptHeader}><CheckCircle2 size={17} aria-hidden="true" /><div><strong>发布回执已确认</strong><span>{receipt.publicPostId}</span></div></div><dl className={styles.factGrid}><Fact label="平台" value={<PlatformIdentity platform={receipt.platform} size="sm" />} /><Fact label="发布时间" value={formatDate(receipt.publishedAt)} /><Fact label="记录人" value={recordedByLabel(receipt.recordedBy)} /><Fact label="证据质量" value={qualityDisplayLabel(receipt.evidenceQuality)} /></dl><a className={styles.receiptLink} href={receipt.publishedUrl} target="_blank" rel="noreferrer"><span>{receipt.publishedUrl}</span><ExternalLink size={14} aria-hidden="true" /></a><div className={styles.reviewWindowNote}><Clock3 size={16} aria-hidden="true" /><div><strong>复盘窗口</strong><span>24 小时 / 7 天</span><small>后续复盘页面读取真实指标和证据质量。</small></div></div></div>;
}

function Heading({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <header className={styles.sectionHeading}><span className={styles.sectionIcon}>{icon}</span><div><h3>{title}</h3><p>{detail}</p></div></header>;
}
function Fact({ label, value }: { label: string; value: ReactNode }) { return <div className={styles.fact}><dt>{label}</dt><dd>{value}</dd></div>; }
function StatusPill({ status }: { status: string }) { return <span className={[styles.statusPill, statusToneClass(status)].join(" ")}>{statusLabel(status)}</span>; }

function State({ kind, title, detail, action }: { kind: "loading" | "permission" | "error" | "empty"; title: string; detail: string; action?: ReactNode }) {
  return <SurfaceState kind={kind} title={title} detail={detail} action={action} />;
}

function readChecks(item: PublishingPackage): Record<CheckKey, boolean> { return { content: checkValue(item, "content"), publication: checkValue(item, "publication") }; }
function checkValue(item: PublishingPackage, key: CheckKey): boolean { return item.humanChecks.find((check) => check.key === key)?.checked === true; }
function checkSummary(items: PublishingPackage["humanChecks"]): string { return items.filter((check) => check.checked).length + "/" + checks.length + " 项人工检查"; }
function statusLabel(status: string): string { return { draft: "草稿", checking: "检查中", ready: "可发布", published: "已记录发布" }[status] ?? "发布状态待确认"; }
const publishingToneClasses: Record<ReturnType<typeof publishingStatusStage>, string> = {
  ready: styles.status_ready,
  published: styles.status_published,
  checking: styles.status_checking,
  draft: styles.status_draft,
};

function statusToneClass(status: string): string {
  return publishingToneClasses[publishingStatusStage(status)];
}
function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未提供";
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join("、") : "未提供";
  if (typeof value === "object") return "结构化内容";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "未提供";
  return typeof value === "string" ? value : "未提供";
}
function readError(error: unknown, fallback: string): string {
  return describeBusinessError(error, {
    fallback,
    forbidden: "当前账户没有访问该发布数据的权限。",
    notFound: "发布资源不存在或已不可用。",
    conflict: "发布包已发生修订变化，请重新读取后再试。",
  });
}

function contentFieldLabel(key: string, index: number): string {
  return ({ title: "标题", body: "正文", summary: "摘要", tags: "标签" }[key] ?? `内容字段 ${index + 1}`);
}

function recordedByLabel(value: string): string {
  if (value === "admin") return "管理员";
  if (value === "user") return "当前用户";
  return "记录人待确认";
}
