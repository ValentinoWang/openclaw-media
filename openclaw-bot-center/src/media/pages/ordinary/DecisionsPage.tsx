import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Check,
  CircleDot,
  Database,
  ExternalLink,
  Lightbulb,
  RefreshCw,
  Search,
} from "lucide-react";
import { useMediaWeb } from "../../MediaWebWorkspace";
import { loginUrl } from "../../mediaWebApi";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import { isForbiddenError, isNotFoundError } from "../../businessErrorPresentation";
import {
  CursorPagination,
  formatDate,
  useCursorTrail,
} from "../../ui/ordinaryPagePrimitives";
import { newIdempotencyKey } from "../../idempotency";
import { qualityDisplayLabel } from "../../ui/ordinaryDataLabels";
import { PlatformIdentity } from "../../ui/PlatformIdentity";
import { SearchBox } from "../../ui/SearchBox";
import { SurfaceState } from "../../ui/SurfaceState";
import { decisionStatusTone } from "../../statusPresentation";
import styles from "./DecisionsPage.module.css";

type DecisionStatus = "candidate" | "recommended" | "confirmed" | "rejected";
type CandidateType = "activity" | "material" | "deconstruction" | "pattern" | "business" | "creator";
type SignalKind = "hotlist" | "activity" | "research";

type DecisionSummary = {
  publicDecisionId: string;
  candidateTitle: string;
  candidateType: CandidateType;
  platform: string;
  trackName: string;
  decisionStatus: DecisionStatus;
  evidenceCount: number;
  humanConfirmedAt: string | null;
  updatedAt: string;
};

type DecisionListResponse = {
  schemaVersion: string;
  revision: number;
  items: DecisionSummary[];
  nextCursor: string | null;
};

type DecisionResponse = {
  schemaVersion: string;
  revision: number;
  decision: DecisionSummary;
};

type DecisionSignal = {
  publicSignalId: string;
  kind: SignalKind;
  platform: string;
  title: string;
  rank: number;
  sourceUrl: string;
  capturedAt: string;
  qualityStatus: string;
};

type DecisionSignalListResponse = {
  schemaVersion: string;
  revision: number;
  items: DecisionSignal[];
  nextCursor: string | null;
};

type ResourceState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "forbidden"; message: string }
  | { status: "notFound"; message: string }
  | { status: "unavailable"; message: string }
  | { status: "error"; message: string };

type ActionState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

type TabKey = "decisions" | "signals";

const pageSize = 20;
const signalPageSize = 24;
const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "decisions", label: "候选选题" },
  { key: "signals", label: "来源信号" },
];

export default function DecisionsPage() {
  const { runtimeState, session } = useMediaWeb();
  const [activeTab, setActiveTab] = useState<TabKey>("decisions");
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const cursorTrail = useCursorTrail();
  const signalCursorTrail = useCursorTrail();
  const [refreshToken, setRefreshToken] = useState(0);
  const [detailRefreshToken, setDetailRefreshToken] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [actionState, setActionState] = useState<ActionState>({ status: "idle" });
  const [listState, setListState] = useState<ResourceState<DecisionListResponse>>({
    status: "loading",
  });
  const [signalState, setSignalState] = useState<
    ResourceState<DecisionSignalListResponse>
  >({ status: "loading" });
  const [detailState, setDetailState] = useState<
    ResourceState<DecisionResponse> | null
  >(null);
  const listCursor = cursorTrail.cursor;
  const signalCursor = signalCursorTrail.cursor;

  useEffect(() => {
    if (runtimeState !== "authenticated" || !session) return;
    const controller = new AbortController();
    const queryParams: Record<string, unknown> = {
      cursor: listCursor,
      pageSize,
    };
    if (submittedQuery) queryParams.search = submittedQuery;
    setListState({ status: "loading" });
    callBusinessOperation<DecisionListResponse>("listDecisions", {
      query: queryParams,
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setListState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setListState(toResourceError(error, "候选选题"));
        }
      });
    return () => controller.abort();
  }, [listCursor, refreshToken, runtimeState, session, submittedQuery]);

  useEffect(() => {
    if (runtimeState !== "authenticated" || !session) return;
    const controller = new AbortController();
    setSignalState({ status: "loading" });
    callBusinessOperation<DecisionSignalListResponse>("listDecisionSignals", {
      query: { cursor: signalCursor, pageSize: signalPageSize },
      signal: controller.signal,
    })
      .then((data) => {
        if (!controller.signal.aborted) setSignalState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setSignalState(toResourceError(error, "来源信号"));
        }
      });
    return () => controller.abort();
  }, [refreshToken, runtimeState, session, signalCursor]);

  const decisions = useMemo(
    () => (listState.status === "ready" ? listState.data.items : []),
    [listState],
  );
  const selectedSummary = decisions.find(
    (item) => item.publicDecisionId === selectedId,
  );

  useEffect(() => {
    if (listState.status !== "ready") return;
    setSelectedId((current) => {
      if (current && listState.data.items.some((item) => item.publicDecisionId === current)) {
        return current;
      }
      return listState.data.items[0]?.publicDecisionId ?? null;
    });
  }, [listState]);

  useEffect(() => {
    if (runtimeState !== "authenticated" || !session || !selectedId) {
      setDetailState(null);
      return;
    }
    const controller = new AbortController();
    setDetailState({ status: "loading" });
    setActionState({ status: "idle" });
    callBusinessOperation<DecisionResponse>("getDecision", {
      path: { publicDecisionId: selectedId },
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!isDecisionResponse(data)) {
          setDetailState({
            status: "unavailable",
            message: "决策详情响应字段未开放。",
          });
          return;
        }
        setDetailState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setDetailState(toResourceError(error, "决策详情"));
        }
      });
    return () => controller.abort();
  }, [detailRefreshToken, runtimeState, selectedId, session]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittedQuery(query.trim());
    cursorTrail.reset();
    setSelectedId(null);
  }

  function resetSearch() {
    setQuery("");
    setSubmittedQuery("");
    cursorTrail.reset();
    setSelectedId(null);
  }

  function selectDecision(publicDecisionId: string) {
    setSelectedId(publicDecisionId);
    setReason("");
    setActionState({ status: "idle" });
  }

  async function confirmDecision(decision: "confirmed" | "rejected") {
    if (
      !session ||
      detailState?.status !== "ready" ||
      !isPendingDecision(detailState.data.decision.decisionStatus) ||
      !reason.trim()
    ) {
      return;
    }
    const current = detailState.data.decision;
    setActionState({ status: "submitting" });
    try {
      const data = await callBusinessOperation<DecisionResponse>("confirmDecision", {
        path: { publicDecisionId: current.publicDecisionId },
        body: {
          expectedRevision: detailState.data.revision,
          decision,
          reason: reason.trim(),
        },
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("b04-confirm"),
      });
      if (!isDecisionResponse(data)) {
        setDetailState({
          status: "unavailable",
          message: "确认响应字段未开放。",
        });
        setActionState({ status: "error", message: "确认结果字段未开放。" });
        return;
      }
      setDetailState({ status: "ready", data });
      setListState((currentState) => {
        if (currentState.status !== "ready") return currentState;
        return {
          status: "ready",
          data: {
            ...currentState.data,
            revision: data.revision,
            items: currentState.data.items.map((item) =>
              item.publicDecisionId === data.decision.publicDecisionId
                ? data.decision
                : item,
            ),
          },
        };
      });
      setActionState({
        status: "success",
        message: decision === "confirmed" ? "已确认，服务端已读回新修订。" : "已拒绝，服务端已读回新修订。",
      });
    } catch (error: unknown) {
      if (error instanceof BusinessOperationError && error.status === 409) {
        setActionState({
          status: "error",
          message: "当前决定已发生修订冲突，正在重新读取。",
        });
        setDetailRefreshToken((value) => value + 1);
        return;
      }
      setActionState({ status: "error", message: actionErrorMessage(error) });
    }
  }

  if (runtimeState === "checking") return <PageGate title="正在读取选题与决策" detail="" loading />;
  if (runtimeState === "unauthenticated") {
    return (
      <PageGate
        title="登录后查看选题与决策"
        detail="当前页面只展示所属账户的决策与来源信号。"
        kind="permission"
        action={<a className="mg-btn" data-component="mg-btn" href={loginUrl()}>登录</a>}
      />
    );
  }
  if (runtimeState === "unavailable") {
    return <PageGate title="选题与决策暂时不可用" detail="身份服务尚未连接。" />;
  }

  return (
    <main
      className={`fidelity-page ${styles.page}`}
      data-accent="campaign"
      data-page-ownership="personal"
    >
      <div className={styles.prelude} data-page-prelude>
        <header className={`page-heading mg-hero ${styles.heading}`} data-component="mg-hero">
          <div>
            <span className="mg-eyebrow" data-component="mg-eyebrow">内容运营</span>
            <h1>选题与决策</h1>
            <p>候选选题、来源信号和人工确认都来自当前租户的业务记录。</p>
          </div>
          <div className="page-heading-actions mg-hero-actions">
            <button
              className={`mg-btn mg-btn-primary ${styles.primaryAction}`}
              data-component="mg-btn"
              type="button"
              onClick={() => setRefreshToken((value) => value + 1)}
              title="重新读取决策数据"
            >
              <RefreshCw size={16} aria-hidden="true" />
              刷新数据
            </button>
          </div>
        </header>
        <nav className={`mg-tabs mg-tabs--pill ${styles.tabs}`} data-component="mg-tabs" role="tablist" aria-label="选题与决策视图">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={`mg-tab ${styles.tab}`}
              data-component="mg-tab"
              data-variant="pill"
              type="button"
              role="tab"
              id={`${tab.key}-tab`}
              aria-controls={`${tab.key}-tabpanel`}
              aria-selected={activeTab === tab.key}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <form className={`mg-panel ${styles.filterBar}`} data-component="mg-panel" onSubmit={submitSearch}>
          <SearchBox
            className={styles.searchField}
            value={query}
            onChange={setQuery}
            label="搜索候选标题、平台或赛道"
          />
          <button className="mg-btn mg-btn-ghost" data-component="mg-btn" type="button" onClick={resetSearch}>
            重置
          </button>
          <button className="mg-btn" data-component="mg-btn" type="submit">
            <Search size={15} aria-hidden="true" />
            搜索
          </button>
        </form>
      </div>
      <DecisionMetrics listState={listState} signalState={signalState} />
      <div className={styles.workspace} data-page-layout="persistent-rail">
        <div className={styles.candidatePanel} data-page-primary data-primary-flow>
          {activeTab === "decisions" ? (
            <DecisionListPanel
              state={listState}
              selectedId={selectedId}
              page={cursorTrail.page}
              onSelect={selectDecision}
              onPrevious={cursorTrail.previous}
              onNext={() => {
                if (listState.status === "ready" && listState.data.nextCursor) {
                  cursorTrail.next(listState.data.nextCursor);
                }
              }}
              onRetry={() => setRefreshToken((value) => value + 1)}
            />
          ) : (
            <SignalPanel
              state={signalState}
              page={signalCursorTrail.page}
              onPrevious={signalCursorTrail.previous}
              onNext={() => {
                if (signalState.status === "ready" && signalState.data.nextCursor) {
                  signalCursorTrail.next(signalState.data.nextCursor);
                }
              }}
              onRetry={() => setRefreshToken((value) => value + 1)}
            />
          )}
        </div>
        <DecisionInspector
          summary={selectedSummary}
          state={detailState}
          reason={reason}
          actionState={actionState}
          onReasonChange={setReason}
          onConfirm={(decision) => void confirmDecision(decision)}
          onRetry={() => setDetailRefreshToken((value) => value + 1)}
        />
      </div>
    </main>
  );
}

function DecisionMetrics({
  listState,
  signalState,
}: {
  listState: ResourceState<DecisionListResponse>;
  signalState: ResourceState<DecisionSignalListResponse>;
}) {
  const decisions = listState.status === "ready" ? listState.data.items : null;
  const signals = signalState.status === "ready" ? signalState.data.items : null;
  const pending = decisions?.filter((item) => isPendingDecision(item.decisionStatus)).length;
  return (
    <section className={`mg-metric-grid ${styles.metrics}`} data-component="mg-metric-grid" aria-label="选题与决策指标">
      <Metric label="候选选题" value={decisions ? String(decisions.length) : "—"} accent="teal" />
      <Metric label="待人工确认" value={pending === undefined ? "—" : String(pending)} accent="amber" />
      <Metric label="来源信号" value={signals ? String(signals.length) : "—"} accent="blue" />
      <Metric label="列表修订" value={listState.status === "ready" ? String(listState.data.revision) : "—"} accent="rose" />
    </section>
  );
}

function Metric({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "teal" | "amber" | "blue" | "rose";
}) {
  return (
    <div className={`mg-metric ${styles.metric}`} data-component="mg-metric" data-accent={accent}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DecisionListPanel({
  state,
  selectedId,
  page,
  onSelect,
  onPrevious,
  onNext,
  onRetry,
}: {
  state: ResourceState<DecisionListResponse>;
  selectedId: string | null;
  page: number;
  onSelect: (id: string) => void;
  onPrevious: () => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  return (
    <section
      className={`mg-panel ${styles.tablePanel}`}
      data-component="mg-panel"
      data-page-terminal-surface="primary"
      id="decisions-tabpanel"
      role="tabpanel"
      aria-labelledby="decisions-tab"
    >
      <header className={`mg-panel-heading ${styles.panelHeader}`} data-component="mg-panel-heading">
        <div>
          <h2>候选选题</h2>
          <span>{state.status === "ready" ? `${state.data.items.length} 条` : ""}</span>
        </div>
        <span className={styles.panelHint}>服务端摘要</span>
      </header>
      {state.status === "ready" ? (
        <>
          <div className={styles.tableScroll} role="region" aria-label="候选选题表格" tabIndex={0}>
            <table className={styles.table}>
              <colgroup><col /><col /><col /><col /><col /><col /><col /></colgroup>
              <thead>
                <tr><th scope="col">候选选题</th><th scope="col">平台</th><th scope="col">来源类型</th><th scope="col">赛道</th><th scope="col">状态</th><th scope="col">来源</th><th scope="col">更新时间</th></tr>
              </thead>
              <tbody>
                {state.data.items.map((item) => (
                  <DecisionRow
                    key={item.publicDecisionId}
                    item={item}
                    selected={item.publicDecisionId === selectedId}
                    onSelect={onSelect}
                  />
                ))}
              </tbody>
            </table>
            {!state.data.items.length ? (
              <EmptyState title="暂无候选选题" detail="当前租户还没有可展示的决策记录。" />
            ) : null}
          </div>
          <footer className={styles.tableFooter}>
            <span>列表修订 {state.data.revision}</span>
            <CursorPagination
              page={page}
              canPrevious={page > 1}
              canNext={!!state.data.nextCursor}
              onPrevious={onPrevious}
              onNext={onNext}
            />
          </footer>
        </>
      ) : (
        <StatePanel state={state} subject="候选选题" onRetry={onRetry} />
      )}
    </section>
  );
}

function DecisionRow({
  item,
  selected,
  onSelect,
}: {
  item: DecisionSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const select = () => onSelect(item.publicDecisionId);
  return (
    <tr className={selected ? styles.rowSelected : ""}>
      <th scope="row">
        <button className={styles.decisionButton} type="button" aria-current={selected ? "true" : undefined} onClick={select} aria-label={`查看候选选题 ${item.candidateTitle}`}>
          <span className={styles.decisionId}><CircleDot size={10} aria-hidden="true" /><span title={item.publicDecisionId}>{item.publicDecisionId}</span></span>
          <strong>{item.candidateTitle}</strong>
        </button>
      </th>
      <td className={styles.platformCell}><PlatformIdentity platform={item.platform} size="sm" /></td>
      <td>{candidateTypeDisplayLabel(item.candidateType)}</td>
      <td>{item.trackName}</td>
      <td><StatusBadge status={item.decisionStatus} /></td>
      <td><span className={styles.sourceCount}><Database size={13} aria-hidden="true" />{item.evidenceCount} 条</span></td>
      <td><span className={styles.dateCell}>{formatDate(item.updatedAt)}</span></td>
    </tr>
  );
}

function SignalPanel({
  state,
  page,
  onPrevious,
  onNext,
  onRetry,
}: {
  state: ResourceState<DecisionSignalListResponse>;
  page: number;
  onPrevious: () => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  return (
    <section
      className={`mg-panel ${styles.tracePanel}`}
      data-component="mg-panel"
      data-page-terminal-surface="primary"
      id="signals-tabpanel"
      role="tabpanel"
      aria-labelledby="signals-tab"
    >
      <header className="mg-panel-heading" data-component="mg-panel-heading">
        <div><h2>来源信号</h2><p>热榜快照与活动记录保留来源链接、采集时间和质量状态。</p></div>
        <span>{state.status === "ready" ? `修订 ${state.data.revision}` : ""}</span>
      </header>
      {state.status === "ready" ? (
        <>
          <ul className={styles.traceList}>
            {state.data.items.map((signal, index) => (
              <li key={signal.publicSignalId}>
                <span className={styles.traceNumber}>{index + 1}</span>
                <div>
                  <h3>{signal.title}</h3>
                  <div className={styles.signalMeta}>
                    <span className={styles.signalMetaItem}>{signalKindLabel(signal.kind)}</span>
                    <span className={styles.signalMetaItem}>
                      <PlatformIdentity platform={signal.platform} size="sm" />
                    </span>
                    {signal.rank > 0 ? <span className={styles.signalMetaItem}>排名 {signal.rank}</span> : null}
                    <span className={styles.signalMetaItem}>{qualityDisplayLabel(signal.qualityStatus)}</span>
                  </div>
                  <a className={styles.signalLink} href={signal.sourceUrl} target="_blank" rel="noreferrer">
                    查看来源 <ExternalLink size={13} aria-hidden="true" />
                  </a>
                  <small className={styles.signalCapturedAt}>采集于 {formatDate(signal.capturedAt)}</small>
                </div>
              </li>
            ))}
          </ul>
          {!state.data.items.length ? <EmptyState title="暂无来源信号" detail="当前租户还没有热榜或活动信号快照。" /> : null}
          <footer className={styles.tableFooter}>
            <span>来源快照不会替代决策判断。</span>
            <CursorPagination
              page={page}
              canPrevious={page > 1}
              canNext={!!state.data.nextCursor}
              onPrevious={onPrevious}
              onNext={onNext}
            />
          </footer>
        </>
      ) : (
        <StatePanel state={state} subject="来源信号" onRetry={onRetry} />
      )}
    </section>
  );
}

function DecisionInspector({
  summary,
  state,
  reason,
  actionState,
  onReasonChange,
  onConfirm,
  onRetry,
}: {
  summary?: DecisionSummary;
  state: ResourceState<DecisionResponse> | null;
  reason: string;
  actionState: ActionState;
  onReasonChange: (value: string) => void;
  onConfirm: (decision: "confirmed" | "rejected") => void;
  onRetry: () => void;
}) {
  const detail = state?.status === "ready" ? state.data.decision : null;
  const pending = detail ? isPendingDecision(detail.decisionStatus) : false;
  return (
    <div className={styles.inspectorColumn} data-page-inspector>
      <aside className={`mg-panel ${styles.inspector}`} data-component="mg-panel" data-page-terminal-surface="inspector">
        <header className={`mg-panel-heading ${styles.inspectorHeader}`} data-component="mg-panel-heading">
          <Lightbulb size={17} aria-hidden="true" />
          <h2>决策检查器</h2>
        </header>
        {!summary && !state ? (
          <EmptyState title="选择一条候选选题" detail="选择后查看服务端摘要和人工确认。" />
        ) : state?.status !== "ready" ? (
          <StatePanel state={state ?? { status: "loading" }} subject="决策详情" onRetry={onRetry} />
        ) : detail ? (
          <div className={styles.inspectorBody}>
            <section className={styles.inspectorSection}>
              <header><Lightbulb size={16} aria-hidden="true" /><h3>决策摘要</h3><span className={styles.sectionStatus}>服务端</span></header>
              <dl className={styles.factGrid}>
                <Fact label="候选选题" value={detail.candidateTitle} />
                <Fact label="来源类型" value={candidateTypeDisplayLabel(detail.candidateType)} />
                <Fact label="平台" value={<PlatformIdentity platform={detail.platform} size="sm" />} />
                <Fact label="赛道" value={detail.trackName} />
                <Fact label="来源数量" value={`${detail.evidenceCount} 条`} />
                <Fact label="更新时间" value={formatDate(detail.updatedAt)} />
              </dl>
            </section>
            <section className={styles.inspectorSection}>
              <header><Check size={16} aria-hidden="true" /><h3>人工确认</h3><span className={styles.sectionStatus}>{pending ? "待确认" : detail.decisionStatus === "rejected" ? "已拒绝" : "已确认"}</span></header>
              <dl className={styles.factGrid}>
                <Fact label="当前决定" value={pending ? "待确认" : decisionLabel(detail.decisionStatus)} />
                <Fact label="确认时间" value={formatDate(detail.humanConfirmedAt ?? undefined)} />
                <Fact label="服务端修订" value={`${state.data.revision}`} />
              </dl>
              {pending ? (
                <div className={styles.actionForm}>
                  <label className={styles.fieldLabel} htmlFor="decision-reason">确认理由</label>
                  <textarea
                    id="decision-reason"
                    className={styles.reasonInput}
                    value={reason}
                    maxLength={500}
                    rows={4}
                    placeholder="填写本次人工判断的依据"
                    onChange={(event) => onReasonChange(event.target.value)}
                  />
                  <div className={styles.actionButtons}>
                    <button
                      className={`mg-btn ${styles.confirmButton}`}
                      data-component="mg-btn"
                      type="button"
                      disabled={!reason.trim() || actionState.status === "submitting"}
                      onClick={() => onConfirm("confirmed")}
                    >
                      <Check size={15} aria-hidden="true" />确认选题
                    </button>
                    <button
                      className={`mg-btn mg-btn-ghost ${styles.rejectButton}`}
                      data-component="mg-btn"
                      type="button"
                      disabled={!reason.trim() || actionState.status === "submitting"}
                      onClick={() => onConfirm("rejected")}
                    >
                      暂不采用
                    </button>
                  </div>
                  <ActionMessage state={actionState} />
                </div>
              ) : <ActionMessage state={actionState} />}
            </section>
          </div>
        ) : null}
      </aside>
    </div>
  );
}


function Fact({ label, value }: { label: string; value: ReactNode }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function StatePanel<T>({
  state,
  subject,
  onRetry,
}: {
  state: ResourceState<T>;
  subject: string;
  onRetry: () => void;
}) {
  if (state.status === "loading") {
    return <SurfaceState kind="loading" title={`正在读取${subject}`} detail="等待服务端返回当前租户数据。" />;
  }
  if (state.status === "forbidden") {
    return <SurfaceState kind="forbidden" title="暂无查看权限" detail={state.message} />;
  }
  if (state.status === "notFound") {
    return <SurfaceState kind="notFound" title="记录不存在" detail={state.message} />;
  }
  if (state.status === "unavailable") {
    return <SurfaceState kind="error" title="字段暂不可用" detail={state.message} />;
  }
  if (state.status !== "error") return null;
  return <SurfaceState
    kind="error"
    title={`${subject}读取失败`}
    detail={state.message}
    action={<button className={`mg-btn mg-btn-ghost ${styles.retryButton}`} data-component="mg-btn" type="button" onClick={onRetry}><RefreshCw size={14} aria-hidden="true" />重试</button>}
  />;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <SurfaceState kind="empty" title={title} detail={detail} />;
}

function PageGate({ title, detail, action, loading = false, kind = "error" }: { title: string; detail: string; action?: ReactNode; loading?: boolean; kind?: "permission" | "error" }) {
  return <main className={`fidelity-page ${styles.gate}`} data-accent="campaign" data-page-ownership="personal"><SurfaceState kind={loading ? "loading" : kind} title={title} detail={detail} action={action} /></main>;
}

function StatusBadge({ status }: { status: DecisionStatus }) {
  return <span className="mg-badge" data-component="mg-badge" data-tone={decisionStatusTone(status)}>{decisionLabel(status)}</span>;
}

function decisionLabel(status: string): string {
  if (status === "confirmed") return "已确认";
  if (status === "rejected") return "暂不采用";
  if (status === "recommended") return "模型推荐";
  if (status === "candidate") return "候选";
  return "决策状态待确认";
}

function isPendingDecision(status: DecisionStatus): boolean {
  return status === "candidate" || status === "recommended";
}


function signalKindLabel(kind: string): string {
  if (kind === "hotlist") return "热榜";
  if (kind === "activity") return "活动";
  if (kind === "research") return "调研";
  return "来源类型待确认";
}

function candidateTypeDisplayLabel(candidateType: CandidateType): string {
  const labels: Record<CandidateType, string> = {
    activity: "现有平台活动",
    material: "现有素材",
    deconstruction: "现有素材拆解",
    pattern: "现有创作模式",
    business: "现有商务机会",
    creator: "现有达人账号",
  };
  return labels[candidateType];
}

function isCandidateType(value: unknown): value is CandidateType {
  return value === "activity" || value === "material" || value === "deconstruction" || value === "pattern" || value === "business" || value === "creator";
}

function isDecisionStatus(value: unknown): value is DecisionStatus {
  return value === "candidate" || value === "recommended" || value === "confirmed" || value === "rejected";
}

function isDecisionSummary(value: unknown): value is DecisionSummary {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.publicDecisionId === "string" &&
    typeof item.candidateTitle === "string" &&
    isCandidateType(item.candidateType) &&
    typeof item.platform === "string" &&
    typeof item.trackName === "string" &&
    isDecisionStatus(item.decisionStatus) &&
    typeof item.evidenceCount === "number" &&
    Number.isInteger(item.evidenceCount) &&
    item.evidenceCount >= 0 &&
    (item.humanConfirmedAt === null || typeof item.humanConfirmedAt === "string") &&
    typeof item.updatedAt === "string"
  );
}

function isDecisionResponse(value: unknown): value is DecisionResponse {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  return (
    typeof response.schemaVersion === "string" &&
    typeof response.revision === "number" &&
    Number.isInteger(response.revision) &&
    response.revision >= 0 &&
    isDecisionSummary(response.decision)
  );
}

function toResourceError<T>(error: unknown, subject: string): ResourceState<T> {
  if (error instanceof BusinessOperationError) {
    if (isForbiddenError(error)) {
      return { status: "forbidden", message: `当前账户没有权限查看${subject}。` };
    }
    if (isNotFoundError(error)) {
      return { status: "notFound", message: `${subject}不存在或已不可用。` };
    }
    if (error.code === "field_unavailable") {
      return { status: "unavailable", message: `${subject}当前字段尚未开放。` };
    }
  }
  return {
    status: "error",
    message: `${subject}暂时无法读取。请点击“重新读取”重试。`,
  };
}

function actionErrorMessage(error: unknown): string {
  if (error instanceof BusinessOperationError) {
    // Previously only checked status, missing the error.code === "forbidden"/"admin_required"
    // arm that toResourceError above already carried -- a forbidden response without a 401/403
    // status fell through to the generic "确认暂时无法完成" message. Fixed by using the same
    // classifier as every other check in this file.
    if (isForbiddenError(error)) return "当前账户没有确认权限。";
    if (error.status === 422) return "确认理由或决定字段不符合要求。";
    return "确认暂时无法完成，请稍后重试。";
  }
  return "确认暂时无法完成，请稍后重试。";
}

function ActionMessage({ state }: { state: ActionState }) {
  if (state.status === "submitting") return <p className={styles.actionMessage}>正在写入并读取确认结果。</p>;
  if (state.status === "success") return <p className={`${styles.actionMessage} ${styles.actionSuccess}`}>{state.message}</p>;
  if (state.status === "error") return <p className={`${styles.actionMessage} ${styles.actionError}`} role="alert">{state.message}</p>;
  return null;
}
