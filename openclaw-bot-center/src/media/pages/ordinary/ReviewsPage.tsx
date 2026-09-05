import {
  BarChart3,
  CheckCircle2,
  ExternalLink,
  FileCheck2,
  LoaderCircle,
  LogIn,
  Plus,
  RefreshCw,
  Send,
  Table2,
  Upload,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useMediaWeb } from "../../MediaWebWorkspace";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import { isForbiddenError, isNotFoundError } from "../../businessErrorPresentation";
import { loginUrl, type MediaWebSession } from "../../mediaWebApi";
import {
  formatDate,
} from "../../ui/ordinaryPagePrimitives";
import { newIdempotencyKey } from "../../idempotency";
import { Metric } from "../../ui/Metric";
import { PlatformIdentity } from "../../ui/PlatformIdentity";
import { qualityDisplayLabel } from "../../ui/ordinaryDataLabels";
import { platformDisplayLabel } from "../../ui/platformRegistry";
import { SurfaceState } from "../../ui/SurfaceState";
import { reviewQualityTone } from "../../statusPresentation";
import styles from "./ReviewsPage.module.css";

type TabId = "reviews" | "content" | "account" | "growth";
type DialogId = "review" | "metric" | "confirm" | null;

type ReviewItem = {
  publicReviewId: string;
  publicPostId: string;
  postTitle: string | null;
  documentUrl: string | null;
  platform: string;
  snapshot24h: string | null;
  snapshot7d: string | null;
  evidenceQuality: string;
  modelSuggestion: string | null;
  humanDecision: string | null;
  status: string;
  revision: number;
};

type ReviewListResponse = {
  schemaVersion: string;
  revision: number;
  items: ReviewItem[];
  nextCursor: string | null;
};

type ReviewSummaryResponse = {
  schemaVersion: string;
  revision: number;
  summary: {
    reviewCount: number;
    pending24h: number;
    pending7d: number;
    confirmedCount: number;
    evidenceCoverage: number;
    generatedAt: string;
  };
};

type MetricSnapshot = {
  publicSnapshotId: string;
  subjectType: "content" | "account";
  publicSubjectId: string;
  reviewWindow: "24h" | "7d" | "custom";
  metricKey: string;
  metricValue: number;
  unit: string;
  evidenceQuality: string;
  collectedAt: string;
};

type MetricListResponse = {
  schemaVersion: string;
  revision: number;
  items: MetricSnapshot[];
  nextCursor: string | null;
};

type ArtifactResponse = {
  schemaVersion: string;
  revision: number;
  item: {
    publicArtifactId: string;
    publicProjectId: string;
    artifactType: string;
    bodyAuthority: string;
    currentRevision: number;
    syncStatus: string;
    updatedAt: string;
    allowedActions: string[];
  };
};

type MetricImportResponse = {
  schemaVersion: string;
  revision: number;
  ok: true;
  updatedAt: string;
};

type LoadState<T> =
  | { status: "idle" | "loading" }
  | { status: "ready"; data: T }
  | { status: "permission" | "error"; message: string };

type B07DataState = {
  summary: LoadState<ReviewSummaryResponse>;
  reviews: LoadState<ReviewListResponse>;
  content: LoadState<MetricListResponse>;
  account: LoadState<MetricListResponse>;
};

type ActionState =
  | { status: "idle" }
  | { status: "busy" }
  | { status: "error"; message: string };

const primaryButtonClass = ["mg-btn", "mg-btn-primary", styles.primaryButton].join(" ");
const secondaryButtonClass = ["mg-btn", "mg-btn-ghost", styles.secondaryButton].join(" ");
const iconButtonClass = ["mg-btn", "mg-btn-ghost", styles.iconButton].join(" ");
const panelClass = ["mg-panel", styles.panel].join(" ");
const panelHeaderClass = ["mg-panel-head", styles.panelHeader].join(" ");

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "reviews", label: "发布复盘" },
  { id: "content", label: "作品指标" },
  { id: "account", label: "账号指标" },
  { id: "growth", label: "增长摘要" },
];

const metricWindows = [
  { value: "24h", label: "24 小时" },
  { value: "7d", label: "7 天" },
  { value: "custom", label: "自定义" },
] as const;

// windowLabel (below) used to carry a second, byte-identical copy of these three value/label
// pairs (cluster LE-17) -- derived from the array above so there is exactly one place that lists
// them. Note this array (and therefore windowLabel) still only covers 24h/7d/custom: the backend
// review scheduler (selfmedia/review/validation_window_scheduler.py) also emits 1h/2h windows,
// which fall through windowLabel's "时间窗口待确认" fallback today. That is a pre-existing
// frontend/backend value-range gap this cluster surfaces, not something safe to silently paper
// over here -- see report.
const metricWindowLabels: Record<string, string> = Object.fromEntries(
  metricWindows.map((item) => [item.value, item.label]),
);

const evidenceQualities = [
  { value: "verified", label: "已验证" },
  { value: "partial", label: "部分验证" },
  { value: "unverified", label: "未验证" },
  { value: "unavailable", label: "不可用" },
] as const;

const sourceTypes = [
  { value: "authorized_api", label: "授权 API" },
  { value: "structured_file", label: "结构化文件" },
  { value: "image", label: "截图或图片" },
  { value: "manual", label: "人工录入" },
] as const;

function emptyDataState(status: "idle" | "loading"): B07DataState {
  return {
    summary: { status },
    reviews: { status },
    content: { status },
    account: { status },
  };
}

function mapLoadError(error: unknown, resource: string): LoadState<never> {
  if (error instanceof BusinessOperationError) {
    if (isForbiddenError(error)) {
      return { status: "permission", message: "当前账户没有读取" + resource + "的权限。" };
    }
    if (isNotFoundError(error)) {
      return { status: "error", message: resource + "不存在或已不再可见。" };
    }
    return { status: "error", message: resource + "暂时无法读取。请点击“重新读取”重试。" };
  }
  return {
    status: "error",
    message: resource + "暂时无法读取。请点击“重新读取”重试。",
  };
}

function mapActionError(error: unknown): string {
  if (error instanceof BusinessOperationError) {
    if (isForbiddenError(error)) return "当前账户没有执行该操作的权限。";
    if (error.status === 409) return "版本已变化，请重新读取后再提交。";
    return "操作暂时无法完成，请稍后重试。";
  }
  return "操作暂时无法完成，请稍后重试。";
}

function reviewPostTitle(item: ReviewItem): string {
  const title = item.postTitle?.trim();
  return title || `${platformDisplayLabel(item.platform)}作品`;
}

function useB07Data(
  session: MediaWebSession | null,
  enabled: boolean,
  refreshToken: number,
  reviewCursor: string | undefined,
  contentCursor: string | undefined,
  accountCursor: string | undefined,
): B07DataState {
  const [data, setData] = useState<B07DataState>(() => emptyDataState("idle"));

  useEffect(() => {
    if (!enabled || !session) {
      setData(emptyDataState("idle"));
      return;
    }
    const controller = new AbortController();
    let active = true;
    // Keep loaded pages visible while a cursor request is in flight. The cursor
    // response below is merged into the existing collection instead of replacing it.
    const isPaging = reviewCursor !== undefined || contentCursor !== undefined || accountCursor !== undefined;
    if (!isPaging) setData(emptyDataState("loading"));

    const mergeItems = <T extends { publicReviewId?: string; publicSnapshotId?: string }>(current: T[], next: T[]) => {
      const byId = new Map<string, T>();
      for (const item of current) {
        const id = item.publicReviewId ?? item.publicSnapshotId;
        if (id) byId.set(id, item);
      }
      for (const item of next) {
        const id = item.publicReviewId ?? item.publicSnapshotId;
        if (id) byId.set(id, item);
      }
      return Array.from(byId.values());
    };

    void callBusinessOperation<ReviewSummaryResponse>("getReviewsSummary", {
      signal: controller.signal,
    })
      .then((value) => {
        if (active) setData((current) => ({ ...current, summary: { status: "ready", data: value } }));
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) {
          setData((current) => ({ ...current, summary: mapLoadError(error, "复盘摘要") }));
        }
      });

    void callBusinessOperation<ReviewListResponse>("listReviews", {
      query: { cursor: reviewCursor, pageSize: 50 },
      signal: controller.signal,
    })
      .then((value) => {
        if (active) setData((current) => {
          if (!isPaging || current.reviews.status !== "ready") return { ...current, reviews: { status: "ready", data: value } };
          return { ...current, reviews: { status: "ready", data: { ...value, nextCursor: reviewCursor === undefined ? current.reviews.data.nextCursor : value.nextCursor, items: mergeItems(current.reviews.data.items, value.items) } } };
        });
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) {
          setData((current) => ({ ...current, reviews: mapLoadError(error, "复盘列表") }));
        }
      });

    void callBusinessOperation<MetricListResponse>("listContentMetrics", {
      query: { cursor: contentCursor, pageSize: 50 },
      signal: controller.signal,
    })
      .then((value) => {
        if (active) setData((current) => {
          if (!isPaging || current.content.status !== "ready") return { ...current, content: { status: "ready", data: value } };
          return { ...current, content: { status: "ready", data: { ...value, nextCursor: contentCursor === undefined ? current.content.data.nextCursor : value.nextCursor, items: mergeItems(current.content.data.items, value.items) } } };
        });
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) {
          setData((current) => ({ ...current, content: mapLoadError(error, "作品指标") }));
        }
      });

    void callBusinessOperation<MetricListResponse>("listAccountMetrics", {
      query: { cursor: accountCursor, pageSize: 50 },
      signal: controller.signal,
    })
      .then((value) => {
        if (active) setData((current) => {
          if (!isPaging || current.account.status !== "ready") return { ...current, account: { status: "ready", data: value } };
          return { ...current, account: { status: "ready", data: { ...value, nextCursor: accountCursor === undefined ? current.account.data.nextCursor : value.nextCursor, items: mergeItems(current.account.data.items, value.items) } } };
        });
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) {
          setData((current) => ({ ...current, account: mapLoadError(error, "账号指标") }));
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [accountCursor, contentCursor, enabled, refreshToken, reviewCursor, session]);

  return data;
}

export default function ReviewsPage() {
  const { runtimeState, session } = useMediaWeb();
  const [activeTab, setActiveTab] = useState<TabId>("reviews");
  const [dialog, setDialog] = useState<DialogId>(null);
  const [actionState, setActionState] = useState<ActionState>({ status: "idle" });
  const [refreshToken, setRefreshToken] = useState(0);
  const [reviewCursor, setReviewCursor] = useState<string>();
  const [contentCursor, setContentCursor] = useState<string>();
  const [accountCursor, setAccountCursor] = useState<string>();
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);

  const authenticated = runtimeState === "authenticated" && session !== null;
  const data = useB07Data(session, authenticated, refreshToken, reviewCursor, contentCursor, accountCursor);
  const reviewItems = useMemo(
    () => (data.reviews.status === "ready" ? data.reviews.data.items : []),
    [data.reviews],
  );
  const selectedReview = useMemo(
    () => reviewItems.find((item) => item.publicReviewId === selectedReviewId) ?? null,
    [reviewItems, selectedReviewId],
  );

  useEffect(() => {
    if (selectedReviewId === null && reviewItems.length > 0) {
      setSelectedReviewId(reviewItems[0].publicReviewId);
    }
  }, [reviewItems, selectedReviewId]);

  function refreshPage() {
    setReviewCursor(undefined);
    setContentCursor(undefined);
    setAccountCursor(undefined);
    setRefreshToken((value) => value + 1);
  }

  function openDialog(next: Exclude<DialogId, null>) {
    setActionState({ status: "idle" });
    setDialog(next);
  }

  function closeDialog() {
    if (actionState.status !== "busy") {
      setDialog(null);
      setActionState({ status: "idle" });
    }
  }

  async function submitReview(body: Record<string, unknown>) {
    if (!session) return;
    setActionState({ status: "busy" });
    try {
      await callBusinessOperation<ArtifactResponse>("createReview", {
        body,
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("b07-review"),
      });
      setDialog(null);
      setActionState({ status: "idle" });
      refreshPage();
    } catch (error: unknown) {
      setActionState({ status: "error", message: mapActionError(error) });
    }
  }

  async function submitMetricImport(body: Record<string, unknown>) {
    if (!session) return;
    setActionState({ status: "busy" });
    try {
      await callBusinessOperation<MetricImportResponse>("createMetricImport", {
        body,
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("b07-metric-import"),
      });
      setDialog(null);
      setActionState({ status: "idle" });
      refreshPage();
    } catch (error: unknown) {
      setActionState({ status: "error", message: mapActionError(error) });
    }
  }

  async function submitConfirmation(body: Record<string, unknown>) {
    if (!session || !selectedReview) return;
    setActionState({ status: "busy" });
    try {
      await callBusinessOperation<ArtifactResponse>("confirmReview", {
        path: { publicReviewId: selectedReview.publicReviewId },
        body,
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("b07-confirm"),
      });
      setDialog(null);
      setActionState({ status: "idle" });
      refreshPage();
    } catch (error: unknown) {
      setActionState({ status: "error", message: mapActionError(error) });
    }
  }

  return (
    <main
      className={["fidelity-page", styles.page].join(" ")}
      data-page-ownership="personal"
      data-accent="desk"
      data-page-state={runtimeState}
    >
      <div data-page-prelude>
        <header className={["page-heading", "mg-hero", styles.pageHeading].join(" ")} data-component="mg-hero">
          <div>
            <span className="mg-eyebrow" data-component="mg-eyebrow">增长与证据</span>
            <h1>复盘增长</h1>
            <p className="mg-hero-lead">发布后的数据、证据质量和报告版本在同一工作区内闭环。</p>
          </div>
          {authenticated ? (
            <div className={["mg-hero-actions", styles.headingActions].join(" ")}>
              <button className={secondaryButtonClass} data-component="mg-btn" type="button" onClick={refreshPage} title="重新读取复盘数据">
                <RefreshCw size={16} aria-hidden="true" />
                刷新
              </button>
              <button className={primaryButtonClass} data-component="mg-btn" type="button" onClick={() => openDialog("review")}>
                <Plus size={16} aria-hidden="true" />
                新建数据复盘
              </button>
            </div>
          ) : null}
        </header>
      </div>
      {runtimeState === "checking" ? (
        <SessionState kind="loading" title="正在确认访问权限" detail="页面数据将在身份确认后读取。" />
      ) : runtimeState === "unauthenticated" || !session ? (
        <SessionState kind="permission" title="需要登录才能查看" detail="此页面只展示当前账户可查看的发布复盘记录。" />
      ) : runtimeState === "unavailable" ? (
        <SessionState kind="error" title="暂时无法读取页面数据" detail="身份服务或任务服务尚未就绪，请稍后重试。" />
      ) : (
        <section className={styles.workspace} data-page-layout="persistent-rail">
          <div className={styles.primaryColumn} data-page-primary data-primary-flow>
            <SummaryBand state={data.summary} />
            <nav className="mg-tabs" data-component="mg-tabs" aria-label="复盘增长视图" role="tablist">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  className="mg-tab"
                  data-component="mg-tab"
                  id={tab.id + "-tab"}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  aria-controls={tab.id + "-tabpanel"}
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
            <div className={styles.tabContent}>
              {activeTab === "reviews" ? (
                <ReviewsView
                  state={data.reviews}
                  selectedReview={selectedReview}
                  onSelectReview={setSelectedReviewId}
                  onNext={() => {
                    if (data.reviews.status === "ready" && data.reviews.data.nextCursor) setReviewCursor(data.reviews.data.nextCursor);
                  }}
                  onRetry={refreshPage}
                />
              ) : activeTab === "content" ? (
                <MetricView
                  id="content-tabpanel"
                  title="作品指标"
                  icon={<Table2 size={19} aria-hidden="true" />}
                  state={data.content}
                  onImport={() => openDialog("metric")}
                  onNext={() => {
                    if (data.content.status === "ready" && data.content.data.nextCursor) setContentCursor(data.content.data.nextCursor);
                  }}
                  onRetry={refreshPage}
                />
              ) : activeTab === "account" ? (
                <MetricView
                  id="account-tabpanel"
                  title="账号指标"
                  icon={<UsersRound size={19} aria-hidden="true" />}
                  state={data.account}
                  onNext={() => {
                    if (data.account.status === "ready" && data.account.data.nextCursor) setAccountCursor(data.account.data.nextCursor);
                  }}
                  onRetry={refreshPage}
                />
              ) : (
                <GrowthView summary={data.summary} onRetry={refreshPage} />
              )}
            </div>
          </div>
          <ReviewInspector
            selectedReview={selectedReview}
            canConfirm={activeTab === "reviews"}
            onConfirm={() => openDialog("confirm")}
          />
        </section>
      )}
      {dialog === "review" ? <ReviewDialog actionState={actionState} onClose={closeDialog} onSubmit={submitReview} /> : null}
      {dialog === "metric" ? <MetricDialog actionState={actionState} onClose={closeDialog} onSubmit={submitMetricImport} /> : null}
      {dialog === "confirm" && selectedReview ? (
        <ConfirmDialog
          key={selectedReview.publicReviewId + "-" + selectedReview.revision}
          review={selectedReview}
          actionState={actionState}
          onClose={closeDialog}
          onSubmit={submitConfirmation}
        />
      ) : null}
    </main>
  );
}

function SessionState({ kind, title, detail }: { kind: "loading" | "permission" | "error"; title: string; detail: string }) {
  return <SurfaceState
    kind={kind}
    title={title}
    detail={detail}
    action={kind === "error" ? <button className={secondaryButtonClass} data-component="mg-btn" type="button" onClick={() => window.location.reload()}><RefreshCw size={15} aria-hidden="true" />重新加载</button> : undefined}
  />;
}

function SummaryBand({ state }: { state: LoadState<ReviewSummaryResponse> }) {
  const summary = state.status === "ready" ? state.data.summary : null;
  const metrics = [
    { label: "复盘报告", value: summary ? formatCount(summary.reviewCount) : stateValue(state), detail: "当前账户" },
    { label: "24 小时待补", value: summary ? formatCount(summary.pending24h) : stateValue(state), detail: "窗口状态" },
    { label: "7 天待补", value: summary ? formatCount(summary.pending7d) : stateValue(state), detail: "窗口状态" },
    { label: "已确认", value: summary ? formatCount(summary.confirmedCount) : stateValue(state), detail: "人工决策" },
    { label: "证据覆盖", value: summary ? formatCoverage(summary.evidenceCoverage) : stateValue(state), detail: summary ? dateValue(summary.generatedAt) : "读取状态" },
  ];
  return (
    <section className={["mg-metric-grid", styles.summaryBand].join(" ")} data-component="mg-metric-grid" aria-label="复盘摘要" aria-busy={state.status === "loading"}>
      {metrics.map((metric) => <Metric variant="panel" className={styles.summaryMetric} key={metric.label} label={metric.label} value={metric.value} detail={metric.detail} />)}
    </section>
  );
}

function stateValue(state: LoadState<unknown>): string {
  if (state.status === "loading") return "读取中";
  if (state.status === "permission") return "无权限";
  if (state.status === "error") return "不可用";
  return "未读取";
}

function recordCountLabel(count: number): string {
  return count > 0 ? `${formatCount(count)} 条记录` : "暂无记录";
}

function ReviewsView({
  state,
  selectedReview,
  onSelectReview,
  onNext,
  onRetry,
}: {
  state: LoadState<ReviewListResponse>;
  selectedReview: ReviewItem | null;
  onSelectReview: (id: string) => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  return (
    <section className={panelClass} data-component="mg-panel" id="reviews-tabpanel" role="tabpanel" aria-labelledby="reviews-tab" data-page-terminal-surface="primary">
      <PanelHeader
        icon={<FileCheck2 size={19} aria-hidden="true" />}
        title="发布复盘"
        detail={state.status === "ready" ? recordCountLabel(state.data.items.length) : "读取状态"}
      />
      {state.status !== "ready" ? <ResourceState state={state} resource="复盘列表" onRetry={onRetry} /> : state.data.items.length === 0 ? (
        <EmptyState title="暂无复盘记录" detail="创建报告后，24 小时和 7 天数据会进入同一版本链。" />
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              {/* 曾经是 8 列（作品/平台/统计时间/证据质量/模型建议/人工决策/版本/操作）：
                  table-layout:fixed 把 min-width 均分成 8 份，740px 容器里「作品」只剩
                  约 105px，标题被折成 4 行。低信息量的列并入相邻列，主表降到 5 列：
                  统计时间（24h/7d 是否已采集）和证据质量原本就是短徽标，挪到作品列标题
                  下方排成一行（.mg-meta）；版本是纯数字，挪到人工决策列下方当次要信息。
                  th 上的 width 是 table-layout:fixed 认的显式列宽，把腾出来的空间分给
                  「作品/模型建议/人工决策」这三个真正需要宽度的列，而不是均分掉。 */}
              <thead><tr><th scope="col" style={{ width: "34%" }}>作品</th><th scope="col" style={{ width: "15%" }}>平台</th><th scope="col" style={{ width: "21%" }}>模型建议</th><th scope="col" style={{ width: "22%" }}>人工决策</th><th scope="col" style={{ width: "8%" }}>操作</th></tr></thead>
              <tbody>
                {state.data.items.map((item) => (
                  <tr key={item.publicReviewId} className={selectedReview?.publicReviewId === item.publicReviewId ? styles.selectedRow : ""}>
                    <th scope="row">
                      <div className={styles.postCell}>
                        {item.documentUrl ? (
                          <a
                            className={styles.documentLink}
                            href={item.documentUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="在飞书中打开复盘文档"
                            aria-label="在飞书中打开复盘文档"
                          >
                            <span className={styles.postTitle}>{reviewPostTitle(item)}</span>
                            <ExternalLink size={14} aria-hidden="true" />
                          </a>
                        ) : (
                          <span className={styles.postTitle}>{reviewPostTitle(item)}</span>
                        )}
                        <button className={styles.rowLink}
                          type="button"
                          onClick={() => onSelectReview(item.publicReviewId)}
                          aria-label={`查看${reviewPostTitle(item)}的复盘详情`}
                        >
                          <span className={`${styles.postId} mg-id`} title={item.publicPostId}>{item.publicPostId}</span>
                        </button>
                        <div className={["mg-meta", styles.postMeta].join(" ")}>
                          <WindowMark label="24h" value={item.snapshot24h} />
                          <WindowMark label="7d" value={item.snapshot7d} />
                          <QualityBadge value={item.evidenceQuality} />
                        </div>
                      </div>
                    </th>
                    <td><PlatformIdentity platform={item.platform} size="sm" /></td>
                    <td className={styles.longValue}>{valueOrUnknown(item.modelSuggestion, "未生成")}</td>
                    <td className={styles.longValue}><span>{valueOrUnknown(item.humanDecision, "未确认")}</span><span className={styles.versionTag}>版本 {formatCount(item.revision)}</span></td>
                    <td><button className={iconButtonClass} data-component="mg-btn" type="button" onClick={() => onSelectReview(item.publicReviewId)} disabled={item.humanDecision !== null || item.status === "confirmed"} title={item.humanDecision !== null || item.status === "confirmed" ? "已确认" : "选择后确认"} aria-label={item.humanDecision !== null || item.status === "confirmed" ? "已确认" : "选择后确认"}><ReviewStatusIcon status={item.status} confirmed={item.humanDecision !== null} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <CursorFooter cursor={state.data.nextCursor} onNext={onNext} />
        </>
      )}
    </section>
  );
}

function MetricView({
  id,
  title,
  icon,
  state,
  onImport,
  onNext,
  onRetry,
}: {
  id: string;
  title: string;
  icon: ReactNode;
  state: LoadState<MetricListResponse>;
  onImport?: () => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  return (
    <section className={panelClass} data-component="mg-panel" id={id} role="tabpanel" aria-labelledby={id.replace("-tabpanel", "-tab")} data-page-terminal-surface="primary">
      <PanelHeader icon={icon} title={title} detail={state.status === "ready" ? recordCountLabel(state.data.items.length) : "读取状态"} action={onImport ? <button className={secondaryButtonClass} data-component="mg-btn" type="button" onClick={onImport}><Upload size={15} aria-hidden="true" />导入指标</button> : null} />
      {state.status !== "ready" ? <ResourceState state={state} resource={title} onRetry={onRetry} /> : state.data.items.length === 0 ? (
        <EmptyState title={title + "暂无记录"} detail="只有带有时间窗口和证据质量的真实快照会显示在这里。" action={onImport ? <button className={primaryButtonClass} data-component="mg-btn" type="button" onClick={onImport}><Upload size={15} aria-hidden="true" />导入第一条指标</button> : null} />
      ) : (
        <>
          <MetricTable items={state.data.items} />
          <CursorFooter cursor={state.data.nextCursor} onNext={onNext} />
        </>
      )}
    </section>
  );
}

function GrowthView({ summary, onRetry }: { summary: LoadState<ReviewSummaryResponse>; onRetry: () => void }) {
  return (
    <section className={panelClass} data-component="mg-panel" id="growth-tabpanel" role="tabpanel" aria-labelledby="growth-tab" data-page-terminal-surface="primary">
      <PanelHeader icon={<BarChart3 size={19} aria-hidden="true" />} title="增长摘要" detail="仅呈现已汇总的数据" />
      {summary.status !== "ready" ? <ResourceState state={summary} resource="增长摘要" onRetry={onRetry} /> : (
        <>
          <div className={["mg-metric-grid", styles.growthGrid].join(" ")} data-component="mg-metric-grid">
            <Metric variant="panel" className={styles.growthMetric} label="复盘报告" value={formatCount(summary.data.summary.reviewCount)} />
            <Metric variant="panel" className={styles.growthMetric} label="24 小时待补" value={formatCount(summary.data.summary.pending24h)} />
            <Metric variant="panel" className={styles.growthMetric} label="7 天待补" value={formatCount(summary.data.summary.pending7d)} />
            <Metric variant="panel" className={styles.growthMetric} label="已确认" value={formatCount(summary.data.summary.confirmedCount)} />
            <Metric variant="panel" className={styles.growthMetric} label="证据覆盖" value={formatCoverage(summary.data.summary.evidenceCoverage)} />
          </div>
        </>
      )}
    </section>
  );
}

function ReviewInspector({ selectedReview, canConfirm, onConfirm }: { selectedReview: ReviewItem | null; canConfirm: boolean; onConfirm: () => void }) {
  return (
    <aside className={[panelClass, styles.inspector].join(" ")} data-component="mg-panel" aria-label="复盘检查器" data-page-inspector data-page-terminal-surface="inspector">
      <PanelHeader
        icon={<FileCheck2 size={19} aria-hidden="true" />}
        title="复盘检查器"
        detail={selectedReview ? "数据版本 " + formatCount(selectedReview.revision) : "尚未选择报告"}
      />
      {selectedReview ? (
        <ReviewLayers review={selectedReview} onConfirm={canConfirm ? onConfirm : undefined} />
      ) : (
        <EmptyState title="请选择一条复盘报告" detail="数据、模型建议和人工决策会在这里分层显示。" />
      )}
    </aside>
  );
}

function ReviewLayers({ review, onConfirm }: { review: ReviewItem; onConfirm?: () => void }) {
  return (
    <section className={styles.layers} aria-label="复盘分层">
      <div className={styles.layersHeader}>
        <div className={styles.layersHeading}>
          <h2>{reviewPostTitle(review)}</h2>
        </div>
        {onConfirm ? <button className={primaryButtonClass} data-component="mg-btn" type="button" onClick={onConfirm} disabled={review.humanDecision !== null || review.status === "confirmed"}><CheckCircle2 size={15} aria-hidden="true" />{review.humanDecision === null ? "确认人工决策" : "已完成确认"}</button> : null}
      </div>
      <div className={styles.layerGrid}>
        <LayerPanel title="数据层">
          <dl className="mg-facts">
            <div className="mg-fact"><dt>24h 快照</dt><dd><SnapshotValue value={review.snapshot24h} /></dd></div>
            <div className="mg-fact"><dt>7d 快照</dt><dd><SnapshotValue value={review.snapshot7d} /></dd></div>
            <div className="mg-fact"><dt>证据质量</dt><dd><QualityBadge value={review.evidenceQuality} /></dd></div>
            <div className="mg-fact"><dt>人工决策</dt><dd>{valueOrUnknown(review.humanDecision, "未确认")}</dd></div>
          </dl>
        </LayerPanel>
        <LayerPanel title="模型输出">
          <p className={styles.layerValue}>{valueOrUnknown(review.modelSuggestion, "未生成")}</p>
        </LayerPanel>
      </div>
      {/* 两个公开编号从标题下面挪到了整栏最下面。它们和标题同色同字号，紧贴标题时
          三行读起来像三个并列的标题，和下面那一整块事实对不上——而编号本身是「拿去
          核对用的」参考信息，不是进来第一眼要读的东西。放到脚注区、弱化成灰字之后，
          标题正下方直接就是那个唯一的操作按钮。
          「标签 + 编号」仍然各自包成一个整体（.metaItem），352px 的检视栏里两个编号
          放不进一行，折行时标签要跟着自己的值一起走。

          告诫那一句留在最后：另外两句出处说明（「数据层由指标快照提供」「人工决策由
          确认操作写入」）旁边就分别写着「24h 快照 / 7d 快照」和「确认人工决策」按钮，
          是复述。常驻可见而不是放进 title：hover 才出现的提醒在触屏上等于没写。 */}
      <footer className={styles.layersFooter}>
        <p className={styles.layersMeta}>
          <span className={styles.metaItem}>
            <small>作品</small>
            <span className="mg-id" title={review.publicPostId}>{review.publicPostId}</span>
          </span>
          <span className={styles.metaItem}>
            <small>报告</small>
            <span className="mg-id" title={review.publicReviewId}>{review.publicReviewId}</span>
          </span>
        </p>
        <p className={styles.layersFootnote}>模型输出是建议，不替代人工决策。</p>
      </footer>
    </section>
  );
}

function LayerPanel({ title, children }: { title: string; children: ReactNode }) {
  return <section className={styles.layerPanel}><header className={styles.layerHeader}><h3>{title}</h3></header>{children}</section>;
}

function MetricTable({ items }: { items: MetricSnapshot[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        {/* 8 列在 min-width:58rem 里曾经均分（每列 116px）：「采集时间」要装完整的
            日期+时间（如「2026/9/1 20:00:00」）装不下，在空格处折成两行，撑高整行——
            同一行里本来单行的「数值」列因此被判成了 3 行的假阳性（度量的是 <td>
            自己的盒高，行内 padding 加上被邻居撑高的行高，除以行高会多算出一整行）。
            给「采集时间」和存 ID 的「快照」显式让出更多宽度，其余短字段（窗口/指标/
            单位/证据质量）平分剩下的部分，而不是继续均分掉。 */}
        <thead><tr><th scope="col" style={{ width: "9.5%" }}>主体</th><th scope="col" style={{ width: "12%" }}>窗口</th><th scope="col" style={{ width: "9.5%" }}>指标</th><th scope="col" style={{ width: "9.5%" }}>数值</th><th scope="col" style={{ width: "9.5%" }}>单位</th><th scope="col" style={{ width: "12%" }}>证据质量</th><th scope="col" style={{ width: "22%" }}>采集时间</th><th scope="col" style={{ width: "16%" }}>快照</th></tr></thead>
        <tbody>
          {items.map((item) => <tr key={item.publicSnapshotId}><th scope="row"><span className="mg-id" title={valueOrUnknown(item.publicSubjectId)}>{valueOrUnknown(item.publicSubjectId)}</span></th><td className={styles.metricShortValue} title={windowLabel(item.reviewWindow)}>{windowLabel(item.reviewWindow)}</td><td className={styles.metricShortValue} title={metricKeyLabel(item.metricKey)}>{metricKeyLabel(item.metricKey)}</td><td><span className="mg-id">{numberValue(item.metricValue)}</span></td><td className={styles.metricShortValue} title={unitLabel(item.unit)}>{unitLabel(item.unit)}</td><td><QualityBadge value={item.evidenceQuality} /></td><td>{dateValue(item.collectedAt)}</td><td className={styles.codeValue}><span className="mg-id" title={valueOrUnknown(item.publicSnapshotId)}>{valueOrUnknown(item.publicSnapshotId)}</span></td></tr>)}
        </tbody>
      </table>
    </div>
  );
}

function PanelHeader({ icon, title, detail, action }: { icon: ReactNode; title: string; detail: string; action?: ReactNode }) {
  return <header className={panelHeaderClass} data-component="mg-panel-head"><div className={styles.panelTitle}><span className={styles.panelIcon}>{icon}</span><div><h2>{title}</h2><p>{detail}</p></div></div>{action}</header>;
}

function ResourceState<T>({ state, resource, onRetry }: { state: LoadState<T>; resource: string; onRetry: () => void }) {
  if (state.status === "loading") return <SurfaceState kind="loading" title={`正在读取${resource}`} detail="等待服务端返回当前账户数据。" />;
  if (state.status === "permission") return <SurfaceState kind="permission" title="暂无查看权限" detail={state.message} action={<a className={secondaryButtonClass} data-component="mg-btn" href={loginUrl()}><LogIn size={15} aria-hidden="true" />重新登录</a>} />;
  if (state.status === "error") return <SurfaceState kind="error" title={`${resource}读取失败`} detail={state.message} action={<button className={secondaryButtonClass} data-component="mg-btn" type="button" onClick={onRetry}><RefreshCw size={15} aria-hidden="true" />重试</button>} />;
  return <SurfaceState kind="empty" title={`等待读取${resource}`} detail="" />;
}

function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <SurfaceState kind="empty" title={title} detail={detail} action={action} />;
}

function CursorFooter({ cursor, onNext }: { cursor: string | null; onNext: () => void }) {
  return cursor ? <div className={styles.cursorFooter}><span>还有更多记录</span><button className={secondaryButtonClass} data-component="mg-btn" type="button" onClick={onNext}><RefreshCw size={15} aria-hidden="true" />继续读取</button></div> : null;
}

/** snapshot24h/snapshot7d 是后端拼好的单个字符串（如「曝光 18422 · 互动 1124 ·
 *  涨粉 213」），按 · 拆成独立短事实用 .mg-meta 排成一行、放不下再整段换行——
 *  而不是任由这一整句话在检视栏里逐字断行，把数字和单位拆散。 */
function SnapshotValue({ value }: { value: string | null }) {
  const text = valueOrUnknown(value);
  const parts = text.split("·").map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) return <>{text}</>;
  return <span className="mg-meta">{parts.map((part, index) => <span key={index}>{index > 0 ? `· ${part}` : part}</span>)}</span>;
}

function WindowMark({ label, value }: { label: string; value: string | null }) {
  return <span className={["mg-badge", value ? styles.windowKnown : styles.windowMissing].join(" ")} data-component="mg-badge" data-tone={value ? "good" : "warn"}>{label}: {value ? "已采集" : "未采集"}</span>;
}

function QualityBadge({ value }: { value: string }) {
  return <span className={["mg-badge", qualityClass(value)].join(" ")} data-component="mg-badge" data-tone={qualityTone(value)}>{qualityLabel(value)}</span>;
}

function ReviewStatusIcon({ status, confirmed }: { status: string; confirmed: boolean }) {
  const isConfirmed = confirmed || status.trim().toLowerCase() === "confirmed";
  return isConfirmed ? <CheckCircle2 size={16} aria-hidden="true" /> : <FileCheck2 size={16} aria-hidden="true" />;
}

const qualityToneClasses: Record<ReturnType<typeof reviewQualityTone>, string> = {
  verified: styles.qualityVerified,
  partial: styles.qualityPartial,
  unverified: styles.qualityUnverified,
  unavailable: styles.qualityUnavailable,
};

function qualityClass(value: string): string {
  return qualityToneClasses[reviewQualityTone(value)];
}

function qualityTone(value: string): "good" | "warn" | "danger" | "info" {
  const normalized = reviewQualityTone(value);
  if (normalized === "verified") return "good";
  if (normalized === "partial") return "warn";
  if (normalized === "unverified") return "danger";
  return "info";
}

// Left as its own word table rather than delegated to qualityDisplayLabel (cluster LE-05): three
// of the four words already match the shared table exactly, but "unavailable" reads "不可用" here
// versus "暂不可用" in ordinaryDataLabels.ts's default table (and evidenceQualities below matches
// this page, not the shared one). That is a narrow, already-shipped wording split with no clear
// single source of truth, so it is preserved rather than silently switched -- see report.
function qualityLabel(value: string): string {
  if (value === "verified") return "已验证";
  if (value === "partial") return "部分验证";
  if (value === "unverified") return "未验证";
  if (value === "unavailable") return "不可用";
  return qualityDisplayLabel(value);
}

function windowLabel(value: string): string {
  return metricWindowLabels[value] ?? "时间窗口待确认";
}

function metricKeyLabel(value: unknown): string {
  if (value === "views") return "播放量";
  if (value === "likes") return "点赞数";
  if (value === "comments") return "评论数";
  if (value === "shares") return "分享数";
  if (value === "favorites") return "收藏数";
  if (value === "followers") return "粉丝数";
  if (value === "engagement_rate") return "互动率";
  return "指标待确认";
}

function unitLabel(value: unknown): string {
  if (value === "count") return "次";
  if (value === "percent" || value === "%") return "百分比";
  if (value === "yuan" || value === "cny") return "元";
  return "单位待确认";
}

function formatCount(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value) : "不可用";
}

function numberValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(value) : "不可用";
}

function formatCoverage(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? (value * 100).toFixed(1) + "%" : "不可用";
}

function valueOrUnknown(value: unknown, missing = "未记录"): string {
  return typeof value === "string" && value.trim() ? value : missing;
}

function dateValue(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || Number.isNaN(Date.parse(value))) return "不可用";
  return formatDate(value);
}

function ReviewDialog({ actionState, onClose, onSubmit }: { actionState: ActionState; onClose: () => void; onSubmit: (body: Record<string, unknown>) => Promise<void> }) {
  const [publicPostId, setPublicPostId] = useState("");
  const [expectedRevision, setExpectedRevision] = useState("");
  const [reviewWindow, setReviewWindow] = useState<"24h" | "7d">("24h");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const revision = Number(expectedRevision);
    if (!publicPostId.trim() || !Number.isInteger(revision) || revision < 0 || !reason.trim()) {
      setFormError("请填写作品编号、当前版本和复盘原因。");
      return;
    }
    setFormError("");
    void onSubmit({ publicPostId: publicPostId.trim(), expectedRevision: revision, reviewWindow, reason: reason.trim() });
  }

  return <DialogFrame title="新建数据复盘" onClose={onClose} busy={actionState.status === "busy"}><form className={styles.form} onSubmit={handleSubmit}>
    <div className={styles.formGrid}>
      <Field label="作品 public ID"><input className={styles.input} value={publicPostId} onChange={(event) => setPublicPostId(event.target.value)} required /></Field>
      <Field label="当前报告数据版本"><input className={styles.input} type="number" min="0" step="1" value={expectedRevision} onChange={(event) => setExpectedRevision(event.target.value)} required /></Field>
    </div>
    <Field label="本次复盘窗口"><select className={styles.input} value={reviewWindow} onChange={(event) => setReviewWindow(event.target.value as "24h" | "7d")}><option value="24h">24 小时</option><option value="7d">7 天</option></select></Field>
    <Field label="复盘原因"><textarea className={styles.textarea} rows={4} value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>
    <FormNotice actionState={actionState} formError={formError} />
    <DialogActions onClose={onClose} busy={actionState.status === "busy"} submitLabel="写入复盘报告" icon={<FileCheck2 size={15} aria-hidden="true" />} />
  </form></DialogFrame>;
}

function MetricDialog({ actionState, onClose, onSubmit }: { actionState: ActionState; onClose: () => void; onSubmit: (body: Record<string, unknown>) => Promise<void> }) {
  const [publicPostId, setPublicPostId] = useState("");
  const [reviewWindow, setReviewWindow] = useState<(typeof metricWindows)[number]["value"]>("24h");
  const [sourceType, setSourceType] = useState<(typeof sourceTypes)[number]["value"]>("manual");
  const [metricKey, setMetricKey] = useState("views");
  const [metricValue, setMetricValue] = useState("");
  const [evidenceLabel, setEvidenceLabel] = useState("");
  const [capturedAt, setCapturedAt] = useState("");
  const [publicUrl, setPublicUrl] = useState("");
  const [quality, setQuality] = useState<(typeof evidenceQualities)[number]["value"]>("verified");
  const [formError, setFormError] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericValue = Number(metricValue);
    if (!publicPostId.trim() || !metricKey.trim() || !Number.isFinite(numericValue) || !evidenceLabel.trim() || !capturedAt) {
      setFormError("请填写作品编号、指标、数值、证据标签和采集时间。");
      return;
    }
    const timestamp = new Date(capturedAt);
    if (Number.isNaN(timestamp.getTime())) {
      setFormError("采集时间无效。");
      return;
    }
    setFormError("");
    void onSubmit({
      publicPostId: publicPostId.trim(),
      reviewWindow,
      sourceType,
      values: { [metricKey.trim()]: numericValue },
      evidenceRefs: [{ kind: sourceType, label: evidenceLabel.trim(), publicUrl: publicUrl.trim() || null, capturedAt: timestamp.toISOString(), qualityStatus: quality }],
    });
  }

  return <DialogFrame title="导入作品指标" onClose={onClose} busy={actionState.status === "busy"}><form className={styles.form} onSubmit={handleSubmit}>
    <div className={styles.formGrid}>
      <Field label="作品 public ID"><input className={styles.input} value={publicPostId} onChange={(event) => setPublicPostId(event.target.value)} required /></Field>
      <Field label="指标窗口"><select className={styles.input} value={reviewWindow} onChange={(event) => setReviewWindow(event.target.value as (typeof metricWindows)[number]["value"])}>{metricWindows.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
    </div>
    <div className={styles.formGrid}>
      <Field label="指标键"><input className={styles.input} value={metricKey} onChange={(event) => setMetricKey(event.target.value)} required /></Field>
      <Field label="指标数值"><input className={styles.input} inputMode="decimal" value={metricValue} onChange={(event) => setMetricValue(event.target.value)} required /></Field>
    </div>
    <div className={styles.formGrid}>
      <Field label="来源类型"><select className={styles.input} value={sourceType} onChange={(event) => setSourceType(event.target.value as (typeof sourceTypes)[number]["value"])}>{sourceTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
      <Field label="证据质量"><select className={styles.input} value={quality} onChange={(event) => setQuality(event.target.value as (typeof evidenceQualities)[number]["value"])}>{evidenceQualities.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></Field>
    </div>
    <Field label="证据标签"><input className={styles.input} value={evidenceLabel} onChange={(event) => setEvidenceLabel(event.target.value)} required /></Field>
    <div className={styles.formGrid}>
      <Field label="采集时间"><input className={styles.input} type="datetime-local" value={capturedAt} onChange={(event) => setCapturedAt(event.target.value)} required /></Field>
      <Field label="公开证据 URL"><input className={styles.input} type="url" value={publicUrl} onChange={(event) => setPublicUrl(event.target.value)} /></Field>
    </div>
    <FormNotice actionState={actionState} formError={formError} />
    <DialogActions onClose={onClose} busy={actionState.status === "busy"} submitLabel="写入指标快照" icon={<Upload size={15} aria-hidden="true" />} />
  </form></DialogFrame>;
}

function ConfirmDialog({ review, actionState, onClose, onSubmit }: { review: ReviewItem; actionState: ActionState; onClose: () => void; onSubmit: (body: Record<string, unknown>) => Promise<void> }) {
  const [expectedRevision, setExpectedRevision] = useState(String(review.revision));
  const [humanDecision, setHumanDecision] = useState("");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const revision = Number(expectedRevision);
    if (!Number.isInteger(revision) || revision < 0 || !humanDecision.trim() || !reason.trim()) {
      setFormError("请填写当前版本、人工决策和决策原因。");
      return;
    }
    setFormError("");
    void onSubmit({ expectedRevision: revision, humanDecision: humanDecision.trim(), reason: reason.trim() });
  }

  return <DialogFrame title="确认人工决策" onClose={onClose} busy={actionState.status === "busy"}><form className={styles.form} onSubmit={handleSubmit}>
    <div className={styles.readonlyContext}><span>报告</span><strong className="mg-id" title={review.publicReviewId}>{review.publicReviewId}</strong><small>当前数据版本 {formatCount(review.revision)}</small></div>
    <Field label="确认时的数据版本"><input className={styles.input} type="number" min="0" step="1" value={expectedRevision} onChange={(event) => setExpectedRevision(event.target.value)} required /></Field>
    <Field label="人工决策"><textarea className={styles.textarea} rows={3} value={humanDecision} onChange={(event) => setHumanDecision(event.target.value)} required /></Field>
    <Field label="决策原因"><textarea className={styles.textarea} rows={4} value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>
    <FormNotice actionState={actionState} formError={formError} />
    <DialogActions onClose={onClose} busy={actionState.status === "busy"} submitLabel="写入人工决策" icon={<Send size={15} aria-hidden="true" />} />
  </form></DialogFrame>;
}

function DialogFrame({ title, onClose, busy, children }: { title: string; onClose: () => void; busy: boolean; children: ReactNode }) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  onCloseRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (!focusable || focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, []);

  return <div className={styles.dialogBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="reviews-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
      <header className={styles.dialogHeader}><h2 id="reviews-dialog-title">{title}</h2><button ref={closeButtonRef} className={iconButtonClass} data-component="mg-btn" type="button" onClick={onClose} disabled={busy} title="关闭" aria-label="关闭"><X size={17} aria-hidden="true" /></button></header>
      {children}
    </section>
  </div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className={styles.field}><span>{label}</span>{children}</label>;
}

function FormNotice({ actionState, formError }: { actionState: ActionState; formError: string }) {
  return formError || actionState.status === "error" ? <p className={styles.formError} role="alert">{formError || (actionState.status === "error" ? actionState.message : "")}</p> : null;
}

function DialogActions({ onClose, busy, submitLabel, icon }: { onClose: () => void; busy: boolean; submitLabel: string; icon: ReactNode }) {
  return <div className={styles.dialogActions}>
    <button className={secondaryButtonClass} data-component="mg-btn" type="button" onClick={onClose} disabled={busy}>取消</button>
    <button className={primaryButtonClass} data-component="mg-btn" type="submit" disabled={busy} aria-busy={busy}>{busy ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : icon}{busy ? "提交中" : submitLabel}</button>
  </div>;
}
