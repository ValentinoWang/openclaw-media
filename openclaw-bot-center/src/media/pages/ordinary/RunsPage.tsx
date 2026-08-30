import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  AlertCircle,
  ArrowRight,
  BriefcaseBusiness,
  CircleDot,
  ExternalLink,
  FileCheck2,
  FileOutput,
  Layers3,
  ListFilter,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  UserRoundCheck,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { TaskSettlementDetails, useMediaWeb } from "../../MediaWebWorkspace";
import type { MediaWebTask } from "../../mediaWebApi";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import { runStatusLabel, runStatusTone } from "../../statusPresentation";
import {
  CursorPagination,
  PageHeading,
  formatDate,
  useCursorTrail,
} from "../../ui/ordinaryPagePrimitives";
import { DISPLAY_LABELS } from "../../ui/displayLabels";
import { artifactTypeDisplayLabel, bodyAuthorityDisplayLabel, mediaTypeDisplayLabel, qualityDisplayLabel, syncStatusDisplayLabel } from "../../ui/ordinaryDataLabels";
import { PlatformIdentity } from "../../ui/PlatformIdentity";
import { getOrganizationDocumentUrl } from "../../ui/organizationDocumentUrl";
import styles from "./RunsPage.module.css";

type StatusTone = ReturnType<typeof runStatusTone>;
type View = "runs" | "opportunities" | "deliveries";
type SectionName = "sources" | "decisions" | "outputs";
type Value = string | number | boolean | null | readonly (string | number | boolean)[];
type StringValueMap = Readonly<Record<string, Value>>;

type RunSummary = {
  readonly publicRunId: string;
  readonly title: string;
  readonly platform: string | null;
  readonly contentType: string | null;
  readonly trackName: string | null;
  readonly entrypoint: string;
  readonly status: string;
  readonly availableSections: readonly SectionName[];
  readonly publicProjectId: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly revision: number;
};

type RunListResponse = {
  readonly schemaVersion: "media_web_business_pages_v2";
  readonly revision: number;
  readonly items: readonly RunSummary[];
  readonly nextCursor: string | null;
};

type RunResponse = {
  readonly schemaVersion: "media_web_business_pages_v2";
  readonly revision: number;
  readonly run: RunSummary;
};

type EvidenceRef = {
  readonly kind: string;
  readonly label: string;
  readonly publicUrl: string | null;
  readonly capturedAt: string | null;
  readonly qualityStatus: "verified" | "partial" | "unverified" | "unavailable";
};

type RunSourceSection = {
  readonly publicRunId: string;
  readonly items: readonly StringValueMap[];
  readonly sourceKinds: readonly string[];
  readonly evidenceRefs: readonly EvidenceRef[];
  readonly revision: number;
};

type DecisionSummary = {
  readonly publicDecisionId: string;
  readonly candidateTitle: string;
  readonly platform: string;
  readonly trackName: string;
  readonly decisionStatus: "candidate" | "recommended" | "confirmed" | "rejected";
  readonly evidenceCount: number;
  readonly humanConfirmedAt: string | null;
  readonly updatedAt: string;
};

type RunDecisionSection = {
  readonly publicRunId: string;
  readonly decisionItems: readonly DecisionSummary[];
  readonly humanState: string;
  readonly revision: number;
};

type ArtifactSummary = {
  readonly publicArtifactId: string;
  readonly publicProjectId: string;
  readonly artifactType:
    | "research_snapshot"
    | "asset_digest"
    | "decision_brief"
    | "creation_document"
    | "publishing_package"
    | "review_report"
    | "project_summary";
  readonly bodyAuthority: "internal" | "lark";
  readonly currentRevision: number;
  readonly syncStatus: "not_applicable" | "pending" | "synced" | "conflict" | "failed";
  readonly updatedAt: string;
  readonly allowedActions: readonly string[];
  readonly organizationDocumentUrl?: string | null;
  readonly larkDocumentUrl?: string | null;
};

type RunOutputSection = {
  readonly publicRunId: string;
  readonly outputVariants: readonly StringValueMap[];
  readonly artifactSummaries: readonly ArtifactSummary[];
  readonly verificationReports: readonly StringValueMap[];
  readonly revision: number;
};

type SectionResponse =
  | {
      readonly schemaVersion: "media_web_business_pages_v2";
      readonly revision: number;
      readonly section: RunSourceSection;
    }
  | {
      readonly schemaVersion: "media_web_business_pages_v2";
      readonly revision: number;
      readonly section: RunDecisionSection;
    }
  | {
      readonly schemaVersion: "media_web_business_pages_v2";
      readonly revision: number;
      readonly section: RunOutputSection;
    };

type BusinessOpportunity = {
  readonly publicOpportunityId: string;
  readonly brand: string;
  readonly product: string;
  readonly platform: string;
  readonly contentType: string;
  readonly validFrom: string | null;
  readonly validUntil: string | null;
  readonly authorizationScope: string;
  readonly status: string;
};

type BusinessOpportunityListResponse = {
  readonly schemaVersion: "media_web_business_pages_v2";
  readonly revision: number;
  readonly items: readonly BusinessOpportunity[];
  readonly nextCursor: string | null;
};

type CommercialDeliveryListResponse = {
  readonly schemaVersion: "media_web_task_v3";
  readonly items: readonly MediaWebTask[];
  readonly nextCursor: null;
};

type PageResponse = RunListResponse | BusinessOpportunityListResponse | CommercialDeliveryListResponse;

type PageReadErrorKind = "forbidden" | "notFound" | "error";

class PageReadError extends Error {
  readonly kind: PageReadErrorKind;

  constructor(kind: PageReadErrorKind, message: string) {
    super(message);
    this.name = "PageReadError";
    this.kind = kind;
  }
}

type ResourceState<T> =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "error"; readonly error: PageReadError };

const PAGE_SIZE = 30;

const statusToneClasses: Record<StatusTone, string> = {
  success: styles.toneSuccess,
  warning: styles.toneWarning,
  info: styles.toneInfo,
  neutral: styles.toneNeutral,
  danger: styles.toneDanger,
};

export default function RunsPage() {
  const { openWorkspace, runtimeState, session, tasks } = useMediaWeb();
  const [activeView, setActiveView] = useState<View>("runs");
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const cursorTrail = useCursorTrail();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedDeliveryId, setSelectedDeliveryId] = useState<string | null>(null);
  const [runMetadata, setRunMetadata] = useState<Record<string, Pick<RunSummary, "platform" | "contentType" | "trackName">>>({});
  const [reloadToken, setReloadToken] = useState(0);
  const { cursor } = cursorTrail;
  const state = useResource<PageResponse>(
    () => {
      if (!session) {
        return Promise.reject(new PageReadError("forbidden", "当前账户无权查看这部分内容。"));
      }
      if (activeView === "runs") return readRuns(session, cursor, submittedQuery);
      if (activeView === "opportunities") return readBusinessOpportunities(session, cursor);
      return Promise.resolve(readCommercialDeliveries(tasks));
    },
    [activeView, cursor, reloadToken, session, submittedQuery, tasks],
  );
  const runResponse = state.status === "ready" && activeView === "runs" && isRunListResponse(state.data)
    ? state.data
    : null;
  useEffect(() => {
    if (!runResponse) return;
    let cancelled = false;
    void Promise.all(runResponse.items.map(async (run) => {
      try {
        const detail = await readRun(run.publicRunId);
        return [run.publicRunId, {
          platform: detail.run.platform ?? null,
          contentType: detail.run.contentType ?? null,
          trackName: detail.run.trackName ?? null,
        }] as const;
      } catch {
        return [run.publicRunId, { platform: null, contentType: null, trackName: null }] as const;
      }
    })).then((entries) => {
      if (!cancelled) setRunMetadata(Object.fromEntries(entries));
    });
    return () => { cancelled = true; };
  }, [runResponse]);
  const enrichedRunResponse = runResponse
    ? { ...runResponse, items: runResponse.items.map((run) => ({ ...run, ...runMetadata[run.publicRunId] })) }
    : null;
  const selectedRun = enrichedRunResponse?.items.find((run) => run.publicRunId === selectedRunId) ?? null;
  const deliveryResponse = state.status === "ready" && activeView === "deliveries" && isDeliveryListResponse(state.data)
    ? state.data
    : null;
  const selectedDelivery = deliveryResponse?.items.find((task) => task.taskId === selectedDeliveryId) ?? null;

  useEffect(() => {
    if (!runResponse) return;
    setSelectedRunId((current) =>
      current && runResponse.items.some((run) => run.publicRunId === current)
        ? current
        : (runResponse.items[0]?.publicRunId ?? null),
    );
  }, [runResponse]);

  useEffect(() => {
    if (!deliveryResponse) return;
    setSelectedDeliveryId((current) =>
      current && deliveryResponse.items.some((task) => task.taskId === current)
        ? current
        : (deliveryResponse.items[0]?.taskId ?? null),
    );
  }, [deliveryResponse]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (activeView !== "runs") return;
    cursorTrail.reset();
    setSelectedRunId(null);
    setSubmittedQuery(query.trim());
  };

  const clearSearch = () => {
    setQuery("");
    cursorTrail.reset();
    setSelectedRunId(null);
    setSubmittedQuery("");
  };

  const switchView = (view: View) => {
    setActiveView(view);
    cursorTrail.reset();
    setSelectedRunId(null);
    setSelectedDeliveryId(null);
    if (view !== "runs") setSubmittedQuery("");
  };

  const page = cursorTrail.page;
  const statusItems = useMemo(
    () => summarizeStatuses(runResponse?.items ?? []),
    [runResponse],
  );

  return (
    <main className={`runs-page fidelity-page ${styles.page}`}>
      <div className={styles.prelude} data-page-prelude>
        <PageHeading
          title="创作与交付"
          description="集中查看真实创作运行、来源、决定、输出与已授权商务机会。"
          action={activeView === "deliveries" ? (
            <button
              className={`primary-button ${styles.primaryAction}`}
              type="button"
              disabled={runtimeState !== "authenticated"}
              onClick={() => openWorkspace(activeView === "deliveries"
                ? { capabilityId: "commercial_delivery_draft", variantId: "default" }
                : { capabilityId: "selfmedia_creation", variantId: "default" })}
            >
              <Plus size={16} />
              新建商单
            </button>
          ) : undefined}
        />
        <div className={styles.tabs} role="tablist" aria-label="创作与交付视图">
          <button
            className={`${styles.tab} ${activeView === "runs" ? styles.activeTab : ""}`}
            type="button"
            role="tab"
            aria-selected={activeView === "runs"}
            onClick={() => switchView("runs")}
          >
            创作运行
          </button>
          <button
            className={`${styles.tab} ${activeView === "opportunities" ? styles.activeTab : ""}`}
            type="button"
            role="tab"
            aria-selected={activeView === "opportunities"}
            onClick={() => switchView("opportunities")}
          >
            商务机会
          </button>
          <button
            className={`${styles.tab} ${activeView === "deliveries" ? styles.activeTab : ""}`}
            type="button"
            role="tab"
            aria-selected={activeView === "deliveries"}
            onClick={() => switchView("deliveries")}
          >
            商单交付
          </button>
        </div>
        {activeView === "runs" && state.status === "ready" && runResponse ? (
          <StatusStrip items={statusItems} itemCount={runResponse.items.length} />
        ) : activeView === "runs" && state.status === "loading" ? (
          <StatusStripLoading />
        ) : null}
        <form className={styles.filterBar} onSubmit={submitSearch}>
          <label className={styles.searchField}>
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">搜索创作运行</span>
            <input
              value={query}
              disabled={activeView !== "runs"}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={activeView === "runs" ? "搜索运行标题、入口、状态或公开编号" : activeView === "deliveries" ? "商单交付按任务时间展示" : "商务机会不支持搜索"}
            />
          </label>
          <DisabledFilter label="能力" />
          <DisabledFilter label="当前环节" />
          <DisabledFilter label="状态" />
          <DisabledFilter label="本机关联" />
          {submittedQuery && activeView === "runs" ? (
            <button className={styles.clearButton} type="button" onClick={clearSearch}>
              <X size={15} />清除搜索
            </button>
          ) : null}
          <button className={styles.resetButton} type="button" disabled={activeView !== "runs" || !submittedQuery} onClick={clearSearch}>
            <RefreshCw size={14} />重置
          </button>
          <button className={styles.submitButton} type="submit" disabled={activeView !== "runs"}>
            <Search size={15} />搜索
          </button>
        </form>
      </div>
      <div className={styles.workspace} data-page-layout="persistent-rail">
        <div className={styles.mainColumn} data-page-primary>
          {state.status === "loading" ? (
            <ReadState kind="loading" message={activeView === "runs" ? "正在读取创作运行" : activeView === "deliveries" ? "正在读取商单交付" : "正在读取商务机会"} />
          ) : null}
          {state.status === "error" ? <ReadState kind={state.error.kind} message={state.error.message} onRetry={() => setReloadToken((value) => value + 1)} /> : null}
          {state.status === "ready" && activeView === "runs" && isRunListResponse(state.data) ? (
            <RunsTable
              response={enrichedRunResponse ?? state.data}
              page={page}
              canPrevious={cursorTrail.canPrevious}
              selectedRunId={selectedRunId}
              submittedQuery={submittedQuery}
              onSelect={setSelectedRunId}
              onClearSearch={clearSearch}
              onPrevious={() => { setSelectedRunId(null); cursorTrail.previous(); }}
              onNext={() => {
                if (!runResponse?.nextCursor) return;
                setSelectedRunId(null);
                cursorTrail.next(runResponse.nextCursor);
              }}
            />
          ) : null}
          {state.status === "ready" && activeView === "opportunities" && isOpportunityListResponse(state.data) ? (
            <BusinessOpportunityTable
              response={state.data}
              page={page}
              canPrevious={cursorTrail.canPrevious}
              onPrevious={() => cursorTrail.previous()}
              onNext={() => {
                if (!isOpportunityListResponse(state.data) || !state.data.nextCursor) return;
                cursorTrail.next(state.data.nextCursor);
              }}
            />
          ) : null}
          {state.status === "ready" && activeView === "deliveries" && isDeliveryListResponse(state.data) ? (
            <CommercialDeliveryTable
              response={state.data}
              selectedDeliveryId={selectedDeliveryId}
              onSelect={setSelectedDeliveryId}
              onCreate={() => openWorkspace({ capabilityId: "commercial_delivery_draft", variantId: "default" })}
            />
          ) : null}
        </div>
        <div className={styles.inspectorColumn} data-page-inspector>
          {selectedRun ? <RunInspector key={selectedRun.publicRunId} run={selectedRun} /> : selectedDelivery ? <CommercialDeliveryInspector key={selectedDelivery.taskId} task={selectedDelivery} /> : <InspectorEmpty view={activeView} />}
        </div>
      </div>
    </main>
  );
}

function DisabledFilter({ label }: { label: string }) {
  return <label className={styles.filterSelect}><span className="sr-only">{label}</span><select aria-label={label} defaultValue="" disabled><option value="">{label}：全部</option></select></label>;
}

function RunsTable({
  response,
  page,
  canPrevious,
  selectedRunId,
  submittedQuery,
  onSelect,
  onClearSearch,
  onPrevious,
  onNext,
}: {
  response: RunListResponse;
  page: number;
  canPrevious: boolean;
  selectedRunId: string | null;
  submittedQuery: string;
  onSelect: (runId: string) => void;
  onClearSearch: () => void;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <section className={styles.tableRegion} aria-labelledby="runs-table-title" data-page-terminal-surface="primary">
      <header className={styles.tableHeader}>
        <div><h2 id="runs-table-title">创作运行</h2><span>{response.items.length} 条当前页记录</span></div>
        <span>每页最多 {PAGE_SIZE} 条</span>
      </header>
      <div className={styles.tableScroll} role="region" aria-label="创作运行表格" tabIndex={0}>
        <table className={styles.table}>
          <thead><tr>
            <th scope="col">运行</th><th scope="col">平台</th><th scope="col">内容类型</th><th scope="col">赛道</th><th scope="col">入口</th><th scope="col">状态</th>
            <th scope="col">可用分区</th><th scope="col">项目</th><th scope="col">修订</th><th scope="col">更新时间</th>
          </tr></thead>
          <tbody>
            {response.items.map((run) => (
              <RunRow key={run.publicRunId} run={run} selected={run.publicRunId === selectedRunId} onSelect={onSelect} />
            ))}
          </tbody>
        </table>
        {response.items.length === 0 ? <RunsEmpty searched={!!submittedQuery} onClear={onClearSearch} /> : null}
      </div>
      <div className={styles.paginationWrap}>
        <CursorPagination page={page} canPrevious={canPrevious} canNext={!!response.nextCursor} onPrevious={onPrevious} onNext={onNext} />
      </div>
    </section>
  );
}

function RunRow({ run, selected, onSelect }: { run: RunSummary; selected: boolean; onSelect: (runId: string) => void }) {
  const select = () => onSelect(run.publicRunId);
  return (
    <tr className={selected ? styles.selectedRow : undefined} aria-selected={selected} tabIndex={0} onClick={select}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }}>
      <th scope="row"><button className={styles.runButton} type="button" onClick={(event) => { event.stopPropagation(); select(); }} aria-label={`查看运行 ${run.publicRunId}`}>
        <span className={styles.runId}><CircleDot size={10} aria-hidden="true" />{run.publicRunId}</span><strong>{run.title}</strong>
      </button></th>
      <td className={`${styles.longCell} ${styles.platformCell}`}><PlatformValue platform={run.platform} /></td>
      <td className={styles.longCell}>{displayMetadata(run.contentType)}</td>
      <td className={styles.longCell}>{displayMetadata(run.trackName)}</td>
      <td className={styles.longCell}>{run.entrypoint ? "已登记入口" : "未提供"}</td>
      <td><StatusPill status={run.status} /></td>
      <td className={styles.longCell}>{displaySections(run.availableSections)}</td>
      <td className={styles.longCell}>{run.publicProjectId ?? "未关联项目"}</td>
      <td>{run.revision}</td>
      <td className={styles.dateCell}>{formatDate(run.updatedAt)}</td>
    </tr>
  );
}

function BusinessOpportunityTable({
  response,
  page,
  canPrevious,
  onPrevious,
  onNext,
}: {
  response: BusinessOpportunityListResponse;
  page: number;
  canPrevious: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <section className={styles.tableRegion} aria-labelledby="opportunities-table-title" data-page-terminal-surface="primary">
      <header className={styles.tableHeader}>
        <div><h2 id="opportunities-table-title">已授权商务机会</h2><span>{response.items.length} 条当前页记录</span></div>
        <span>仅显示当前租户授权对象</span>
      </header>
      <div className={styles.tableScroll} role="region" aria-label="商务机会表格" tabIndex={0}>
        <table className={styles.table}>
          <thead><tr>
            <th scope="col">品牌</th><th scope="col">产品</th><th scope="col">平台</th>
            <th scope="col">内容类型</th><th scope="col">有效期</th><th scope="col">授权范围</th><th scope="col">状态</th>
          </tr></thead>
          <tbody>
            {response.items.map((opportunity) => (
              <tr key={opportunity.publicOpportunityId}>
                <th scope="row" className={styles.longCell}><span className={styles.runId}>{opportunity.brand}</span><strong className={styles.inlineId}>{opportunity.publicOpportunityId}</strong></th>
                <td className={styles.longCell}>{opportunity.product}</td>
                <td className={styles.platformCell}><PlatformValue platform={opportunity.platform} /></td>
                <td>{mediaTypeDisplayLabel(opportunity.contentType)}</td>
                <td className={styles.longCell}>{formatValidity(opportunity.validFrom, opportunity.validUntil)}</td>
                <td className={styles.longCell}>{authorizationScopeDisplayLabel(opportunity.authorizationScope)}</td>
                <td><StatusPill status={opportunity.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {response.items.length === 0 ? <BusinessOpportunityEmpty /> : null}
      </div>
      <div className={styles.paginationWrap}>
        <CursorPagination page={page} canPrevious={canPrevious} canNext={!!response.nextCursor} onPrevious={onPrevious} onNext={onNext} />
      </div>
    </section>
  );
}

function CommercialDeliveryTable({
  response,
  selectedDeliveryId,
  onSelect,
  onCreate,
}: {
  response: CommercialDeliveryListResponse;
  selectedDeliveryId: string | null;
  onSelect: (taskId: string) => void;
  onCreate: () => void;
}) {
  return (
    <section className={styles.tableRegion} aria-labelledby="deliveries-table-title" data-page-terminal-surface="primary">
      <header className={styles.tableHeader}>
        <div><h2 id="deliveries-table-title">商单交付</h2><span>{response.items.length} 条最近任务</span></div>
        <span>已登记商单交付能力</span>
      </header>
      <div className={styles.tableScroll} role="region" aria-label="商单交付表格" tabIndex={0}>
        <table className={styles.table}>
          <thead><tr>
            <th scope="col">交付任务</th><th scope="col">状态</th><th scope="col">进度</th>
            <th scope="col">交付结果</th><th scope="col">更新时间</th>
          </tr></thead>
          <tbody>
            {response.items.map((task) => {
              const selected = task.taskId === selectedDeliveryId;
              const select = () => onSelect(task.taskId);
              return (
                <tr key={task.taskId} className={selected ? styles.selectedRow : undefined} aria-selected={selected} tabIndex={0}
                  onClick={select} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }}>
                  <th scope="row"><button className={styles.runButton} type="button" onClick={(event) => { event.stopPropagation(); select(); }} aria-label={`查看商单交付 ${task.taskId}`}>
                    <span className={styles.runId}><BriefcaseBusiness size={11} aria-hidden="true" />{task.taskId}</span><strong>{task.summary || "未命名商单交付"}</strong>
                  </button></th>
                  <td><StatusPill status={task.status} /></td>
                  <td>{task.progress}%</td>
                  <td className={styles.longCell}><DeliveryLinks task={task} compact /></td>
                  <td className={styles.dateCell}>{formatDate(task.updatedAt)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {response.items.length === 0 ? <CommercialDeliveryEmpty onCreate={onCreate} /> : null}
      </div>
    </section>
  );
}

function CommercialDeliveryInspector({ task }: { task: MediaWebTask }) {
  const params = Object.entries(task.params);
  return (
    <aside className={styles.inspector} aria-label="商单交付详情" data-page-terminal-surface="inspector">
      <header className={styles.inspectorHeader}>
        <div className={styles.inspectorHeading}><span>商单交付详情</span><h2>{task.summary || "未命名商单交付"}</h2><code>{task.taskId}</code></div>
      </header>
      <div className={styles.inspectorBody} role="region" aria-label="商单交付详情内容" tabIndex={0}>
        <div className={styles.inspectorFacts}><div className={styles.factGrid}>
          <div className={styles.factCard}><FileCheck2 size={16} aria-hidden="true" /><div><h3>状态</h3><p><StatusPill status={task.status} /></p></div></div>
          <div className={styles.factCard}><CircleDot size={16} aria-hidden="true" /><div><h3>进度</h3><p>{task.progress}%</p></div></div>
          <div className={styles.factCard}><BriefcaseBusiness size={16} aria-hidden="true" /><div><h3>能力</h3><p>商单交付</p></div></div>
          <div className={styles.factCard}><FileOutput size={16} aria-hidden="true" /><div><h3>更新时间</h3><p>{formatDate(task.updatedAt)}</p></div></div>
        </div></div>
        <section className={styles.deliveryResult} aria-labelledby="delivery-result-title">
          <header><h3 id="delivery-result-title">交付结果</h3><span>{task.result?.status ? runStatusLabel(task.result.status) : "尚未生成"}</span></header>
          {task.result?.reply ? <p>{task.result.reply}</p> : <SectionEmpty message={`任务完成后，交付文档与${DISPLAY_LABELS.commercialDeliveryRecord}会显示在这里。`} />}
          <DeliveryLinks task={task} />
        </section>
        <TaskSettlementDetails task={task} />
        {params.length ? <section className={styles.deliveryResult} aria-labelledby="delivery-input-title"><header><h3 id="delivery-input-title">任务输入</h3><span>{params.length} 项</span></header><dl className={styles.deliveryParams}>{params.map(([key, value], index) => <div key={key}><dt>{`任务参数 ${index + 1}`}</dt><dd>{formatTaskValue(value)}</dd></div>)}</dl></section> : null}
      </div>
    </aside>
  );
}

function DeliveryLinks({ task, compact = false }: { task: MediaWebTask; compact?: boolean }) {
  const links = task.result?.links ?? [];
  if (!links.length) return <span className={styles.mutedCopy}>尚无交付链接</span>;
  return <div className={`${styles.deliveryLinks} ${compact ? styles.deliveryLinksCompact : ""}`}>{links.map((link) => <a key={`${link.label}-${link.url}`} href={link.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}><ExternalLink size={13} />{link.label}</a>)}</div>;
}

function RunInspector({ run }: { run: RunSummary }) {
  const [activeSection, setActiveSection] = useState<SectionName | null>(run.availableSections[0] ?? null);
  const [detailReloadToken, setDetailReloadToken] = useState(0);
  const [sectionReloadToken, setSectionReloadToken] = useState(0);
  const detailState = useResource<RunResponse>(() => readRun(run.publicRunId), [run.publicRunId, detailReloadToken]);
  const detailRun = detailState.status === "ready" ? detailState.data.run : null;

  useEffect(() => {
    const available = detailRun?.availableSections ?? run.availableSections;
    setActiveSection((current) => current && available.includes(current) ? current : (available[0] ?? null));
  }, [detailRun, run.availableSections]);

  const sectionState = useResource<SectionResponse | null>(
    () => {
      if (!detailRun || !activeSection) return Promise.resolve(null);
      return readSection(detailRun.publicRunId, activeSection);
    },
    [activeSection, detailRun?.publicRunId, detailRun?.revision, sectionReloadToken],
  );

  return (
    <aside className={styles.inspector} aria-label="运行详情预览" data-page-terminal-surface="inspector">
      <header className={styles.inspectorHeader}>
        <div className={styles.inspectorHeading}><span>运行详情</span><h2>{run.title}</h2><code>{run.publicRunId}</code></div>
        <Link className={styles.closeButton} to={`/runs/${encodeURIComponent(run.publicRunId)}`} aria-label="打开运行详情"><ExternalLink size={17} /></Link>
      </header>
      <div className={styles.inspectorBody} role="region" aria-label="运行详情内容" tabIndex={0}>
        {detailState.status === "loading" ? <ReadState kind="loading" message="正在读取运行详情" /> : null}
        {detailState.status === "error" ? <ReadState kind={detailState.error.kind} message={detailState.error.message} onRetry={() => setDetailReloadToken((value) => value + 1)} /> : null}
        {detailState.status === "ready" ? (
          <>
            <RunFacts run={detailState.data.run} />
            <SectionPicker availableSections={detailState.data.run.availableSections} activeSection={activeSection} onSelect={setActiveSection} />
            <SectionResult
              state={sectionState}
              activeSection={activeSection}
              onRetry={() => setSectionReloadToken((value) => value + 1)}
            />
          </>
        ) : null}
        <Link className={styles.detailLink} to={`/runs/${encodeURIComponent(run.publicRunId)}`}>
          <span>查看运行详情</span><ArrowRight size={15} /><ExternalLink size={14} />
        </Link>
      </div>
    </aside>
  );
}

function RunFacts({ run }: { run: RunSummary }) {
  const facts = [
    ["状态", <StatusPill key="status" status={run.status} />],
    ["入口", run.entrypoint ? "已登记入口" : "未提供"],
    ["发布平台", <PlatformValue key="platform" platform={run.platform} />],
    ["内容形态", run.contentType ? mediaTypeDisplayLabel(run.contentType) : "未记录"],
    ["内容赛道", displayMetadata(run.trackName)],
    ["项目", run.publicProjectId ?? "未关联项目"],
    ["修订号", run.revision],
    ["创建时间", formatDate(run.createdAt)],
    ["更新时间", formatDate(run.updatedAt)],
  ] as const;
  return <div className={styles.inspectorFacts}><div className={styles.factGrid}>{facts.map(([label, value]) => <div className={styles.factCard} key={label}><FileCheck2 size={16} aria-hidden="true" /><div><h3>{label}</h3><p>{value}</p></div></div>)}</div></div>;
}

function displayMetadata(value: string | null | undefined): string {
  return value?.trim() || "未记录";
}

function PlatformValue({ platform }: { platform: string | null | undefined }) {
  if (!platform?.trim()) return <span className={styles.missingPlatform}>未记录</span>;
  return <PlatformIdentity className={styles.platformIdentity} platform={platform} size="sm" />;
}

function SectionPicker({ availableSections, activeSection, onSelect }: { availableSections: readonly SectionName[]; activeSection: SectionName | null; onSelect: (section: SectionName) => void }) {
  return <section className={styles.sectionPicker} aria-labelledby="run-section-title"><h3 id="run-section-title">运行分区</h3>{availableSections.length ? <div role="tablist" aria-label="运行分区"><button className={`${styles.sectionTab} ${activeSection === "sources" ? styles.sectionTabActive : ""}`} type="button" role="tab" aria-selected={activeSection === "sources"} onClick={() => onSelect("sources")} disabled={!availableSections.includes("sources")}><Layers3 size={14} />来源</button><button className={`${styles.sectionTab} ${activeSection === "decisions" ? styles.sectionTabActive : ""}`} type="button" role="tab" aria-selected={activeSection === "decisions"} onClick={() => onSelect("decisions")} disabled={!availableSections.includes("decisions")}><UserRoundCheck size={14} />决定</button><button className={`${styles.sectionTab} ${activeSection === "outputs" ? styles.sectionTabActive : ""}`} type="button" role="tab" aria-selected={activeSection === "outputs"} onClick={() => onSelect("outputs")} disabled={!availableSections.includes("outputs")}><FileOutput size={14} />输出</button></div> : <p className={styles.mutedCopy}>当前运行没有可用分区。</p>}</section>;
}

function SectionResult({ state, activeSection, onRetry }: { state: ResourceState<SectionResponse | null>; activeSection: SectionName | null; onRetry: () => void }) {
  if (!activeSection) return <section className={styles.sectionResult}><SectionEmpty message="当前运行没有可用分区。" /></section>;
  const sectionUnavailable = state.status === "ready" && state.data !== null && state.data.revision === 0;
  return <section className={styles.sectionResult}><header><h3>{sectionLabel(activeSection)}</h3><span>{state.status === "ready" && state.data ? `修订 ${state.data.revision}` : "合同化读取"}</span></header>{state.status === "loading" ? <ReadState kind="loading" message={`正在读取${sectionLabel(activeSection)}`} /> : null}{state.status === "error" ? <ReadState kind={state.error.kind} message={state.error.message} onRetry={onRetry} /> : null}{sectionUnavailable ? <ReadState kind="partial" message="该分区尚未持久化，当前字段暂不可用。" onRetry={onRetry} /> : null}{state.status === "ready" && state.data && !sectionUnavailable ? <SectionContent response={state.data} activeSection={activeSection} /> : null}{state.status === "ready" && !state.data ? <SectionEmpty message="该分区暂无已持久化内容。" /> : null}</section>;
}

function SectionContent({ response, activeSection }: { response: SectionResponse; activeSection: SectionName }) {
  if (activeSection === "sources" && "items" in response.section) return <SourceContent section={response.section} />;
  if (activeSection === "decisions" && "decisionItems" in response.section) return <DecisionContent section={response.section} />;
  if (activeSection === "outputs" && "outputVariants" in response.section) return <OutputContent section={response.section} />;
  return <SectionEmpty message="分区响应与当前选择不一致。" />;
}

function SourceContent({ section }: { section: RunSourceSection }) {
  const empty = section.items.length === 0 && section.evidenceRefs.length === 0;
  if (empty) return <SectionEmpty message="该运行没有已持久化来源。" />;
  return <div className={styles.sectionBody}><div className={styles.sectionMeta}><span>来源类型</span><strong>{section.sourceKinds.length ? `已登记 ${section.sourceKinds.length} 类来源` : "未记录"}</strong></div>{section.items.map((item, index) => <TypedMap key={`source-${index}`} title={`来源记录 ${index + 1}`} value={item} />)}{section.evidenceRefs.length ? <div className={styles.evidenceList}><h4>证据引用</h4>{section.evidenceRefs.map((ref) => <div className={styles.evidenceItem} key={`${ref.kind}-${ref.label}`}><strong>{ref.label}</strong><span>来源证据 · {qualityDisplayLabel(ref.qualityStatus)}</span>{ref.publicUrl ? <a href={ref.publicUrl} target="_blank" rel="noreferrer">打开公开来源</a> : null}</div>)}</div> : null}</div>;
}

function DecisionContent({ section }: { section: RunDecisionSection }) {
  if (section.decisionItems.length === 0) return <SectionEmpty message="该运行没有已持久化决定。" />;
  return <div className={styles.sectionBody}><div className={styles.sectionMeta}><span>人工状态</span><strong>{humanStateLabel(section.humanState)}</strong></div><div className={styles.decisionList}>{section.decisionItems.map((decision) => <article className={styles.decisionCard} key={decision.publicDecisionId}><div><span className={styles.runId}>{decision.publicDecisionId}</span><h4>{decision.candidateTitle}</h4></div><StatusPill status={decision.decisionStatus} /><dl><div><dt>平台</dt><dd><PlatformValue platform={decision.platform} /></dd></div><div><dt>赛道</dt><dd>{decision.trackName}</dd></div><div><dt>证据数</dt><dd>{decision.evidenceCount}</dd></div><div><dt>人工确认</dt><dd>{decision.humanConfirmedAt ? formatDate(decision.humanConfirmedAt) : "尚未确认"}</dd></div></dl></article>)}</div></div>;
}

function OutputContent({ section }: { section: RunOutputSection }) {
  const empty = section.outputVariants.length === 0 && section.artifactSummaries.length === 0 && section.verificationReports.length === 0;
  if (empty) return <SectionEmpty message="该运行没有已持久化输出。" />;
  return <div className={styles.sectionBody}>{section.outputVariants.length ? <div className={styles.outputGroup}><h4>输出变体</h4>{section.outputVariants.map((item, index) => <TypedMap key={`variant-${index}`} title={`输出变体 ${index + 1}`} value={item} />)}</div> : null}{section.artifactSummaries.length ? <div className={styles.outputGroup}><h4>成果文档</h4>{section.artifactSummaries.map((artifact) => { const documentUrl = getOrganizationDocumentUrl(artifact); return <article className={styles.artifactCard} key={artifact.publicArtifactId}><div><span className={styles.runId}>{artifact.publicArtifactId}</span><strong>{artifactTypeDisplayLabel(artifact.artifactType)}</strong></div><span>修订 {artifact.currentRevision} · {bodyAuthorityDisplayLabel(artifact.bodyAuthority)} · {syncStatusDisplayLabel(artifact.syncStatus)}{documentUrl ? <a className={styles.documentLink} href={documentUrl} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden="true" />打开组织文档</a> : null}</span></article>; })}</div> : null}{section.verificationReports.length ? <div className={styles.outputGroup}><h4>验收报告</h4>{section.verificationReports.map((item, index) => <TypedMap key={`report-${index}`} title={`验收报告 ${index + 1}`} value={item} />)}</div> : null}</div>;
}

function TypedMap({ title, value }: { title: string; value: StringValueMap }) {
  const entries = Object.entries(value);
  return <div className={styles.typedMap}><h4>{title}</h4>{entries.length ? <dl className={styles.structuredList}>{entries.map(([key, item], index) => <div key={key}><dt>{`内容字段 ${index + 1}`}</dt><dd><TypedValue value={item} /></dd></div>)}</dl> : <span className={styles.missingValue}>暂无字段</span>}</div>;
}

function TypedValue({ value }: { value: Value }) {
  if (value === null) return <span className={styles.missingValue}>暂无</span>;
  if (isValueArray(value)) return value.length ? <ol className={styles.structuredArray}>{value.map((item, index) => <li key={index}><TypedValue value={item} /></li>)}</ol> : <span className={styles.missingValue}>暂无</span>;
  return <span className={styles.longValue}>{displayStructuredValue(value)}</span>;
}

function isValueArray(value: Value): value is readonly (string | number | boolean)[] {
  return Array.isArray(value);
}

function SectionEmpty({ message }: { message: string }) {
  return <div className={styles.sectionEmpty}><ListFilter size={18} aria-hidden="true" /><span>{message}</span></div>;
}

function InspectorEmpty({ view }: { view: View }) {
  const title = view === "runs" ? "选择一条运行" : view === "deliveries" ? "选择一条商单交付" : "商务机会列表";
  const copy = view === "runs" ? "选中列表运行后，这里会读取合同化详情与分区。" : view === "deliveries" ? "选中交付任务后，这里会展示任务输入、状态与交付链接。" : "商务机会按当前账户权限在主列表中展示。";
  return <aside className={styles.inspector} aria-label="运行详情预览" data-page-terminal-surface="inspector"><div className={styles.inspectorEmpty}>{view === "runs" ? <ListFilter size={21} aria-hidden="true" /> : <BriefcaseBusiness size={21} aria-hidden="true" />}<strong>{title}</strong><span>{copy}</span></div></aside>;
}

function RunsEmpty({ searched, onClear }: { searched: boolean; onClear: () => void }) {
  return <section className={styles.emptyState}><AlertCircle size={22} aria-hidden="true" /><h2>{searched ? "没有匹配的创作运行" : "当前账户还没有创作运行"}</h2><p>{searched ? "当前结果里没有符合搜索条件的运行。" : "任务创建并持久化后会显示在这里。"}</p>{searched ? <button className={styles.clearButton} type="button" onClick={onClear}><X size={15} />清除搜索</button> : null}</section>;
}

function BusinessOpportunityEmpty() {
  return <section className={styles.emptyState}><BriefcaseBusiness size={22} aria-hidden="true" /><h2>当前没有已授权商务机会</h2><p>列表为空表示当前租户没有可展示的授权商务对象。</p></section>;
}

function CommercialDeliveryEmpty({ onCreate }: { onCreate: () => void }) {
  return <section className={styles.emptyState}><FileOutput size={22} aria-hidden="true" /><h2>当前还没有商单交付</h2><p>通过商单交付能力创建任务后，交付初稿、飞书文档与{DISPLAY_LABELS.commercialDeliveryRecord}会在这里集中展示。</p><button className={styles.submitButton} type="button" onClick={onCreate}><Plus size={15} />新建商单</button></section>;
}

function ReadState({ kind, message, onRetry }: { kind: "loading" | "forbidden" | "notFound" | "error" | "partial"; message: string; onRetry?: () => void }) {
  const icon = kind === "loading" ? <LoaderCircle className={styles.spin} size={21} aria-hidden="true" /> : kind === "forbidden" ? <UserRoundCheck size={21} aria-hidden="true" /> : <AlertCircle size={21} aria-hidden="true" />;
  return <div className={`${styles.readState} ${kind === "partial" ? styles.partialState : ""}`} data-read-state={kind} aria-busy={kind === "loading"} role={kind === "loading" ? undefined : "alert"}>{icon}<strong>{message}</strong>{onRetry ? <button className={styles.retryButton} type="button" onClick={onRetry}><RefreshCw size={14} />重新读取</button> : null}</div>;
}

function StatusStrip({ items, itemCount }: { items: Array<{ label: string; count: number; tone: StatusTone }>; itemCount: number }) {
  return <section className={styles.statusStrip} aria-label="当前页状态摘要"><div className={styles.statusHeading}><strong>本页状态</strong><span>基于当前响应的 {itemCount} 条运行</span></div><div className={styles.statusItems} role="region" aria-label="运行状态项目" tabIndex={0}>{items.length ? items.map((item) => <div className={styles.statusItem} key={item.label}><span className={`${styles.statusDot} ${statusToneClasses[item.tone]}`} aria-hidden="true" /><div><span>{item.label}</span><strong>{item.count}</strong></div></div>) : <div className={styles.statusItem}><span className={`${styles.statusDot} ${styles.toneNeutral}`} aria-hidden="true" /><div><span>运行记录</span><strong>0</strong></div></div>}</div></section>;
}

function StatusStripLoading() {
  return <section className={styles.statusStrip} aria-busy="true" aria-label="正在读取状态摘要"><div className={styles.statusHeading}><strong>本页状态</strong><span>正在读取当前响应</span></div><div className={styles.statusLoading}>{Array.from({ length: 5 }, (_, index) => <span key={index} />)}</div></section>;
}

function StatusPill({ status }: { status: string }) {
  const tone = runStatusTone(status);
  return <span className={`${styles.statusPill} ${statusToneClasses[tone]}`}>{runStatusLabel(status)}</span>;
}

function useResource<T>(loader: () => Promise<T>, dependencies: readonly unknown[]): ResourceState<T> {
  const [state, setState] = useState<ResourceState<T>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    loader().then((data) => {
      if (active) setState({ status: "ready", data });
    }).catch((error: unknown) => {
      if (active) setState({ status: "error", error: toReadError(error, "读取内容暂时不可用。") });
    });
    return () => { active = false; };
  }, dependencies);
  return state;
}

async function readRuns(session: unknown, cursor: string | undefined, search: string): Promise<RunListResponse> {
  if (!session) throw new PageReadError("forbidden", "当前账户无权查看这部分内容。");
  return callBusinessOperation<RunListResponse>("listRuns", { query: { cursor, pageSize: PAGE_SIZE, search } });
}

async function readBusinessOpportunities(session: unknown, cursor: string | undefined): Promise<BusinessOpportunityListResponse> {
  if (!session) throw new PageReadError("forbidden", "当前账户无权查看这部分内容。");
  return callBusinessOperation<BusinessOpportunityListResponse>("listBusinessOpportunities", { query: { cursor, pageSize: PAGE_SIZE } });
}

function readCommercialDeliveries(tasks: readonly MediaWebTask[]): CommercialDeliveryListResponse {
  return {
    schemaVersion: "media_web_task_v3",
    items: tasks.filter((task) => task.capabilityId === "commercial_delivery_draft"),
    nextCursor: null,
  };
}

async function readRun(publicRunId: string): Promise<RunResponse> {
  return callBusinessOperation<RunResponse>("getRun", { path: { publicRunId } });
}

async function readSection(publicRunId: string, section: SectionName): Promise<SectionResponse> {
  if (section === "sources") return callBusinessOperation<Extract<SectionResponse, { readonly section: RunSourceSection }>>("getRunSources", { path: { publicRunId } });
  if (section === "decisions") return callBusinessOperation<Extract<SectionResponse, { readonly section: RunDecisionSection }>>("getRunDecisions", { path: { publicRunId } });
  return callBusinessOperation<Extract<SectionResponse, { readonly section: RunOutputSection }>>("getRunOutputs", { path: { publicRunId } });
}

function toReadError(error: unknown, fallback: string): PageReadError {
  if (error instanceof PageReadError) return error;
  if (error instanceof BusinessOperationError) {
    if (error.status === 401 || error.status === 403 || error.code === "forbidden") return new PageReadError("forbidden", "当前账户无权查看这部分内容。");
    if (error.status === 404 || error.code === "resource_not_found") return new PageReadError("notFound", "这条内容不存在或已不可用。");
    return new PageReadError("error", fallback);
  }
  return new PageReadError("error", fallback);
}

function humanStateLabel(value: string): string {
  return ({ pending: "待确认", confirmed: "已确认", rejected: "已拒绝" }[value] ?? "状态待确认");
}

function isRunListResponse(response: PageResponse): response is RunListResponse {
  return "items" in response && (response.items.length === 0 || "publicRunId" in response.items[0]);
}

function isOpportunityListResponse(response: PageResponse): response is BusinessOpportunityListResponse {
  return "items" in response && (response.items.length === 0 || "publicOpportunityId" in response.items[0]);
}

function isDeliveryListResponse(response: PageResponse): response is CommercialDeliveryListResponse {
  return response.schemaVersion === "media_web_task_v3";
}

function formatTaskValue(value: MediaWebTask["params"][string]): string {
  if (value === null) return "未填写";
  if (Array.isArray(value)) return value.map(displayStructuredValue).join("、");
  return displayStructuredValue(value);
}

function displayStructuredValue(value: string | number | boolean): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return String(value);
  const normalized = value.trim();
  if (!normalized) return "未填写";
  if (/^[a-z0-9]+(?:[_-][a-z0-9]+)+$/i.test(normalized)) return "内容待确认";
  return normalized;
}

function authorizationScopeDisplayLabel(value: string): string {
  const labels: Record<string, string> = {
    public: "公开合作",
    private: "定向合作",
    exclusive: "独家合作",
    non_exclusive: "非独家合作",
  };
  return labels[value] ?? "授权范围待确认";
}

function summarizeStatuses(runs: readonly RunSummary[]) {
  const summary = new Map<string, { label: string; count: number; tone: StatusTone }>();
  runs.forEach((run) => {
    const current = summary.get(run.status);
    if (current) current.count += 1;
    else summary.set(run.status, { label: runStatusLabel(run.status), count: 1, tone: runStatusTone(run.status) });
  });
  return Array.from(summary.values());
}

function displaySections(sections: readonly SectionName[]): string {
  return sections.length ? sections.map(sectionLabel).join("、") : "暂无分区";
}

function sectionLabel(section: SectionName): string {
  if (section === "sources") return "来源";
  if (section === "decisions") return "决定";
  return "输出";
}

function formatValidity(validFrom: string | null, validUntil: string | null): string {
  if (!validFrom && !validUntil) return "未提供有效期";
  return `${validFrom ? formatDate(validFrom) : "不限起始"} - ${validUntil ? formatDate(validUntil) : "不限结束"}`;
}
