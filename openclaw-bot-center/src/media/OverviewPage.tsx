import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  FileText,
  FolderKanban,
  Layers3,
  Lightbulb,
  LoaderCircle,
  PackageCheck,
  PenTool,
  RefreshCw,
  Send,
  ShieldAlert,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useMediaWeb } from "../../MediaWebWorkspace";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import type { CapabilityCatalog } from "../../../schemas/capabilityCatalogSchema";
import {
  displayNumber,
  formatDate,
  newIdempotencyKey,
  PageHeading,
} from "../../ui/ordinaryPagePrimitives";
import styles from "./OverviewPage.module.css";

type TaskActionState =
  | { status: "busy" }
  | { status: "error"; message: string };

type B01LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "permission"; message: string }
  | { status: "notFound"; message: string }
  | { status: "timeout"; message: string }
  | { status: "error"; message: string };

type DashboardSummary = {
  counts: {
    contentProjects: number;
    runs: number;
    assets: number;
    tracks: number;
    creators: number;
    publishedPosts: number;
    reviews: number;
  };
  contentProjectStages: Array<{ stage: string; count: number }>;
  pendingDecisions: number;
  pendingPublishing: number;
  pendingReviews: number;
  taskSummary: {
    queued: number;
    running: number;
    needsAttention: number;
    failed: number;
  };
  coverage: { known: number; unknown: number; unavailable: number };
  generatedAt: string;
  revision: number;
};

type DashboardResponse = {
  schemaVersion: string;
  revision: number;
  summary: DashboardSummary;
};

type ContentProjectSummary = {
  publicProjectId: string;
  title: string;
  workspaceMode: "personal_web" | "organization_lark";
  stage: string;
  status: string;
  artifactCounts: Record<string, number>;
  updatedAt: string;
};

type ContentProjectListResponse = {
  schemaVersion: string;
  revision: number;
  items: ContentProjectSummary[];
  nextCursor: string | null;
};

type ArtifactSummary = {
  publicArtifactId: string;
  publicProjectId: string;
  artifactType: string;
  bodyAuthority: "internal" | "lark";
  currentRevision: number;
  syncStatus: "not_applicable" | "pending" | "synced" | "conflict" | "failed";
  updatedAt: string;
  allowedActions: string[];
};

type ArtifactListResponse = {
  schemaVersion: string;
  revision: number;
  items: ArtifactSummary[];
  nextCursor: string | null;
};

type ArtifactResponse = {
  schemaVersion: string;
  revision: number;
  item: ArtifactSummary;
};
type MediaTaskSummary = {
  taskId: string;
  capabilityId: string;
  variantId: string;
  status: string;
  terminal: boolean;
  progress: number;
  summary: string;
  createdAt: string;
  updatedAt: string;
  result: unknown | null;
  error: unknown | null;
  revision: number;
};
type MediaTaskListResponse = {
  schemaVersion: string;
  revision: number;
  items: MediaTaskSummary[];
  nextCursor: string | null;
};
type MediaTaskV3ListResponse = {
  schemaVersion: string;
  tasks: Array<Omit<MediaTaskSummary, "revision"> & { revision?: number }>;
};
type MediaTaskResponse = {
  schemaVersion: string;
  revision: number;
  task: MediaTaskSummary;
};

type SummaryActionState =
  | { status: "idle" }
  | { status: "busy" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

const EMPTY_TASKS: MediaTaskSummary[] = [];
const B01_REQUEST_TIMEOUT_MS = 10_000;

const workflowChain: Array<{ label: string; to: string; icon: LucideIcon }> = [
  { label: "素材与灵感", to: "/assets", icon: Lightbulb },
  { label: "选题与决策", to: "/decisions", icon: Target },
  { label: "创作与交付", to: "/runs", icon: PenTool },
  { label: "发布准备", to: "/publishing", icon: Send },
  { label: "复盘增长", to: "/reviews", icon: TrendingUp },
];

const taskStatusLabels: Record<string, string> = {
  awaiting_confirmation: "待人工确认",
  pending_manual: "待人工处理",
  queued: "排队中",
  validating: "校验中",
  retrieving: "读取来源",
  generating: "生成中",
  persisting: "写入中",
  rendering: "渲染中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function OverviewPage() {
  const { openWorkspace, session } = useMediaWeb();
  const [refreshToken, setRefreshToken] = useState(0);
  const [projectSearch, setProjectSearch] = useState("");
  const [projectCursor, setProjectCursor] = useState<string | undefined>();
  const [projectHistory, setProjectHistory] = useState<string[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [artifactCursor, setArtifactCursor] = useState<string | undefined>();
  const [artifactHistory, setArtifactHistory] = useState<string[]>([]);
  const [summaryReason, setSummaryReason] = useState("更新项目摘要");
  const [summaryAction, setSummaryAction] = useState<SummaryActionState>({
    status: "idle",
  });
  const [taskRefresh, setTaskRefresh] = useState(0);
  const [taskActions, setTaskActions] = useState<
    Record<string, TaskActionState>
  >({});
  const dashboardState = useB01Dashboard(refreshToken);
  const projectState = useB01Projects(
    projectCursor,
    projectSearch,
    refreshToken,
  );
  const artifactState = useB01Artifacts(
    selectedProjectId,
    artifactCursor,
    refreshToken,
  );
  const capabilityState = useB01Capabilities(refreshToken);
  const taskState = useB01Tasks(taskRefresh);
  const tasks =
    taskState.status === "ready" ? taskState.data.items : EMPTY_TASKS;
  const activeTasks = useMemo(
    () => tasks.filter((task) => !task.terminal),
    [tasks],
  );
  const pendingTasks = useMemo(() => tasks.filter(isPendingTask), [tasks]);

  useEffect(() => {
    if (projectState.status !== "ready") return;
    const visibleIds = projectState.data.items.map((item) => item.publicProjectId);
    if (selectedProjectId && visibleIds.includes(selectedProjectId)) return;
    setSelectedProjectId(visibleIds[0] ?? null);
    setArtifactCursor(undefined);
    setArtifactHistory([]);
  }, [projectState, selectedProjectId]);

  const selectedProject =
    projectState.status === "ready"
      ? projectState.data.items.find(
          (item) => item.publicProjectId === selectedProjectId,
        ) ?? null
      : null;

  function selectProject(publicProjectId: string) {
    setSelectedProjectId(publicProjectId);
    setArtifactCursor(undefined);
    setArtifactHistory([]);
    setSummaryAction({ status: "idle" });
  }

  function updateProjectSearch(value: string) {
    setProjectSearch(value);
    setProjectCursor(undefined);
    setProjectHistory([]);
  }

  function nextProjects() {
    if (projectState.status !== "ready" || !projectState.data.nextCursor) return;
    setProjectHistory((current) => [...current, projectCursor ?? ""]);
    setProjectCursor(projectState.data.nextCursor);
  }

  function previousProjects() {
    const previous = projectHistory.at(-1);
    if (previous === undefined) return;
    setProjectHistory((current) => current.slice(0, -1));
    setProjectCursor(previous || undefined);
  }

  function nextArtifacts() {
    if (artifactState.status !== "ready" || !artifactState.data.nextCursor) return;
    setArtifactHistory((current) => [...current, artifactCursor ?? ""]);
    setArtifactCursor(artifactState.data.nextCursor);
  }

  function previousArtifacts() {
    const previous = artifactHistory.at(-1);
    if (previous === undefined) return;
    setArtifactHistory((current) => current.slice(0, -1));
    setArtifactCursor(previous || undefined);
  }

  async function createProjectSummary() {
    if (!selectedProject || projectState.status !== "ready") return;
    if (artifactState.status !== "ready") {
      setSummaryAction({ status: "error", message: "项目产物版本尚未读取完成。" });
      return;
    }
    const reason = summaryReason.trim();
    if (!reason) {
      setSummaryAction({ status: "error", message: "请填写生成原因。" });
      return;
    }
    if (!session) {
      setSummaryAction({ status: "error", message: "当前会话不可用，无法提交。" });
      return;
    }
    setSummaryAction({ status: "busy" });
    try {
      await callBusinessOperation<ArtifactResponse>("createProjectSummary", {
        path: { publicProjectId: selectedProject.publicProjectId },
        body: { expectedRevision: artifactState.data.revision, reason },
        csrfToken: session.session.csrfToken,
        idempotencyKey: newIdempotencyKey("b01-summary"),
      });
      setSummaryAction({ status: "success", message: "摘要生成请求已提交。" });
      setRefreshToken((current) => current + 1);
      setArtifactCursor(undefined);
      setArtifactHistory([]);
    } catch (error) {
      setSummaryAction({
        status: "error",
        message: error instanceof Error ? error.message : "摘要生成未完成。",
      });
    }
  }

  const partial = [dashboardState, projectState, artifactState, capabilityState, taskState].some(
    (state) =>
      state.status === "permission" ||
      state.status === "notFound" ||
      state.status === "timeout" ||
      state.status === "error",
  );

  async function decideTask(task: MediaTaskSummary, reason: string) {
    if (!session) {
      setTaskActions((current) => ({
        ...current,
        [task.taskId]: { status: "error", message: "当前会话不可用，无法提交。" },
      }));
      return;
    }
    const normalizedReason = reason.trim();
    if (!normalizedReason) {
      setTaskActions((current) => ({
        ...current,
        [task.taskId]: { status: "error", message: "请填写确认原因。" },
      }));
      return;
    }
    setTaskActions((current) => ({ ...current, [task.taskId]: { status: "busy" } }));
    try {
      await callBusinessOperation<MediaTaskResponse>("confirmMediaTask", {
        path: { taskId: task.taskId },
        body: {
          reason: normalizedReason,
          expectedRevision: task.revision,
        },
        csrfToken: session.session.csrfToken,
        idempotencyKey: newIdempotencyKey("b01-task-confirm"),
      });
      setTaskActions((current) => {
        const next = { ...current };
        delete next[task.taskId];
        return next;
      });
      setTaskRefresh((current) => current + 1);
      setRefreshToken((current) => current + 1);
    } catch (error) {
      setTaskActions((current) => ({
        ...current,
        [task.taskId]: {
          status: "error",
          message: error instanceof Error ? error.message : "操作未完成。",
        },
      }));
    }
  }

  return (
    <main className={"overview-page fidelity-page " + styles.page}>
      <div data-page-prelude>
        <PageHeading
          title="运营总览"
          description="查看当前租户的内容项目、产物进度与待处理事项。"
        />
        <MetricStrip dashboardState={dashboardState} />
        {partial ? (
          <div className={styles.partialBanner} role="status">
            <ShieldAlert size={16} />
            <span>部分运营汇总数据暂不可用，页面没有用其它数据源替代。</span>
          </div>
        ) : null}
      </div>
      <div className={styles.overviewGrid} data-page-layout="persistent-rail">
        <div className={styles.primaryColumn} data-page-primary>
          <DashboardPanel state={dashboardState} />
          <ProjectsPanel
            state={projectState}
            selectedProjectId={selectedProjectId}
            search={projectSearch}
            onSearchChange={updateProjectSearch}
            onSelect={selectProject}
            onNext={nextProjects}
            onPrevious={previousProjects}
            canPrevious={projectHistory.length > 0}
            summaryReason={summaryReason}
            summaryAction={summaryAction}
            onReasonChange={setSummaryReason}
            onCreateSummary={() => void createProjectSummary()}
            canCreateSummary={!!session && !!selectedProject && artifactState.status === "ready"}
          />
          <ArtifactsPanel
            state={artifactState}
            selectedProject={selectedProject}
            onNext={nextArtifacts}
            onPrevious={previousArtifacts}
            canPrevious={artifactHistory.length > 0}
          />
        </div>
        <div className={styles.sideColumn} data-page-inspector>
          <AgentPanel
            capabilityState={capabilityState}
            taskState={taskState}
            activeTasks={activeTasks}
          />
          <WorkflowPanel />
          <PendingPanel
            state={taskState}
            tasks={pendingTasks}
            taskActions={taskActions}
            onDecide={decideTask}
            onOpenWorkspace={openWorkspace}
          />
        </div>
      </div>
    </main>
  );
}

type B01Request<T> = (signal: AbortSignal) => Promise<T>;

function useB01Request<T>(
  request: B01Request<T>,
  dependencyKey: string,
  fallback: string,
  enabled = true,
): B01LoadState<T> {
  const requestRef = useRef(request);
  requestRef.current = request;
  const [state, setState] = useState<B01LoadState<T>>({ status: "loading" });
  useEffect(() => {
    if (!enabled) {
      setState({ status: "loading" });
      return;
    }
    const controller = new AbortController();
    let active = true;
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, B01_REQUEST_TIMEOUT_MS);
    setState({ status: "loading" });
    requestRef.current(controller.signal)
      .then((data) => {
        if (active) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (timedOut) {
          setState({ status: "timeout", message: "运营汇总请求超时，未使用默认值。" });
          return;
        }
        if (controller.signal.aborted) return;
        setState(mapB01Error(error, fallback));
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [dependencyKey, enabled, fallback]);
  return state;
}

function useB01Dashboard(refreshToken: number): B01LoadState<DashboardResponse> {
  return useB01Request(
    (signal) => callBusinessOperation<DashboardResponse>("getDashboard", { signal }),
    String(refreshToken),
    "总览读取失败。",
  );
}

function useB01Projects(
  cursor: string | undefined,
  search: string,
  refreshToken: number,
): B01LoadState<ContentProjectListResponse> {
  return useB01Request(
    (signal) =>
      callBusinessOperation<ContentProjectListResponse>("listContentProjects", {
        query: {
          cursor,
          pageSize: 20,
          search: search.trim() || undefined,
        },
        signal,
      }),
    JSON.stringify([cursor ?? null, search, refreshToken]),
    "项目列表读取失败。",
  );
}

function useB01Artifacts(
  projectId: string | null,
  cursor: string | undefined,
  refreshToken: number,
): B01LoadState<ArtifactListResponse> {
  return useB01Request(
    (signal) =>
      callBusinessOperation<ArtifactListResponse>("listProjectArtifacts", {
        path: { publicProjectId: projectId as string },
        query: { cursor, pageSize: 20 },
        signal,
      }),
    JSON.stringify([projectId, cursor ?? null, refreshToken]),
    "项目产物读取失败。",
    projectId !== null,
  );
}

function useB01Capabilities(refreshToken: number): B01LoadState<CapabilityCatalog> {
  return useB01Request(
    (signal) =>
      callBusinessOperation<CapabilityCatalog>("listMediaCapabilities", {
        query: { pageSize: 100 },
        signal,
      }),
    String(refreshToken),
    "能力目录读取失败。",
  );
}

function useB01Tasks(refreshToken: number): B01LoadState<MediaTaskListResponse> {
  return useB01Request(
    (signal) =>
      callBusinessOperation<MediaTaskV3ListResponse>("listMediaTasks", {
        query: { pageSize: 100 },
        signal,
      }).then((payload) => ({
        schemaVersion: payload.schemaVersion,
        revision: 0,
        items: Array.isArray(payload.tasks)
          ? payload.tasks.map((task) => ({ ...task, revision: task.revision ?? 0 }))
          : [],
        nextCursor: null,
      })),
    String(refreshToken),
    "任务列表读取失败。",
  );
}

function mapB01Error<T>(error: unknown, fallback: string): B01LoadState<T> {
  if (error instanceof BusinessOperationError) {
    if (error.status === 408 || error.status === 504 || error.code === "timeout") {
      return { status: "timeout", message: "运营汇总请求超时，未使用默认值。" };
    }
    if (error.status === 401 || error.status === 403) {
      return { status: "permission", message: "当前账户没有读取运营汇总的权限。" };
    }
    if (error.status === 404 || error.code === "resource_not_found") {
      return { status: "notFound", message: "资源不存在，或已不再对当前账户可见。" };
    }
    return { status: "error", message: error.message || fallback };
  }
  return { status: "error", message: error instanceof Error ? error.message : fallback };
}

function DashboardPanel({ state }: { state: B01LoadState<DashboardResponse> }) {
  return (
    <section className={"section-panel " + styles.panel + " " + styles.dashboardPanel}>
      <PanelHeading
        icon={Layers3}
        title="租户概览"
        detail="只显示运营总览接口返回的标准汇总。"
      />
      {state.status !== "ready" ? (
        <BusinessPanelState state={state} loadingText="正在读取租户概览" />
      ) : (
        <div className={styles.dashboardBody}>
          {isEmptyDashboard(state.data.summary) ? (
            <div className={styles.emptyDashboardHint} role="status">
              <CircleDashed size={15} />
              <span>当前租户没有可汇总的内容事实，以下仍保留接口返回的完整字段。</span>
            </div>
          ) : null}
          <div className={styles.countGrid}>
            {Object.entries(state.data.summary.counts).map(([label, value]) => (
              <div className={styles.countItem} key={label}>
                <span>{dashboardLabel(label)}</span>
                <strong>{displayNumber(value)}</strong>
              </div>
            ))}
          </div>
          <div className={styles.stageList} aria-label="内容项目阶段分布">
            {state.data.summary.contentProjectStages.map((item) => (
              <div className={styles.stageItem} key={item.stage}>
                <span>{dashboardLabel(item.stage)}</span>
                <strong>{displayNumber(item.count)}</strong>
              </div>
            ))}
          </div>
          <DashboardMetricGroup
            title="待处理摘要"
            values={[
              ["待决策", state.data.summary.pendingDecisions],
              ["待发布", state.data.summary.pendingPublishing],
              ["待复盘", state.data.summary.pendingReviews],
            ]}
          />
          <DashboardMetricGroup
            title="网页任务摘要"
            values={[
              ["排队中", state.data.summary.taskSummary.queued],
              ["运行中", state.data.summary.taskSummary.running],
              ["需关注", state.data.summary.taskSummary.needsAttention],
              ["失败", state.data.summary.taskSummary.failed],
            ]}
          />
          <DashboardMetricGroup
            title="覆盖情况"
            values={[
              ["已知", state.data.summary.coverage.known],
              ["未知", state.data.summary.coverage.unknown],
              ["不可用", state.data.summary.coverage.unavailable],
            ]}
          />
          <div className={styles.partialInline + (state.data.summary.coverage.unknown || state.data.summary.coverage.unavailable ? "" : " " + styles.coverageComplete)} role="status">
            {state.data.summary.coverage.unknown || state.data.summary.coverage.unavailable ? (
              <ShieldAlert size={15} />
            ) : (
              <CheckCircle2 size={15} />
            )}
            <span>
              {state.data.summary.coverage.unknown || state.data.summary.coverage.unavailable
                ? "覆盖不完整，未知与不可用事实已明确保留。"
                : "覆盖完整，未知与不可用事实均为 0。"}
            </span>
          </div>
          <div className={styles.dashboardFooter}>
            <span>生成于 {displayDate(state.data.summary.generatedAt)}</span>
            <span>摘要 revision {displayNumber(state.data.summary.revision)}</span>
            <span>响应 revision {displayNumber(state.data.revision)}</span>
          </div>
        </div>
      )}
    </section>
  );
}

function DashboardMetricGroup({
  title,
  values,
}: {
  title: string;
  values: Array<[string, number]>;
}) {
  return (
    <section className={styles.dashboardMetricGroup}>
      <h3>{title}</h3>
      <div className={styles.dashboardDetailGrid}>
        {values.map(([label, value]) => (
          <div className={styles.dashboardDetailItem} key={label}>
            <span>{label}</span>
            <strong>{displayNumber(value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProjectsPanel({
  state,
  selectedProjectId,
  search,
  onSearchChange,
  onSelect,
  onNext,
  onPrevious,
  canPrevious,
  summaryReason,
  summaryAction,
  onReasonChange,
  onCreateSummary,
  canCreateSummary,
}: {
  state: B01LoadState<ContentProjectListResponse>;
  selectedProjectId: string | null;
  search: string;
  onSearchChange: (value: string) => void;
  onSelect: (publicProjectId: string) => void;
  onNext: () => void;
  onPrevious: () => void;
  canPrevious: boolean;
  summaryReason: string;
  summaryAction: SummaryActionState;
  onReasonChange: (value: string) => void;
  onCreateSummary: () => void;
  canCreateSummary: boolean;
}) {
  const selectedProject =
    state.status === "ready"
      ? state.data.items.find((item) => item.publicProjectId === selectedProjectId) ?? null
      : null;
  return (
    <section className={"section-panel " + styles.panel + " " + styles.projectsPanel}>
      <PanelHeading
        icon={FolderKanban}
        title="内容项目"
        count={state.status === "ready" ? state.data.items.length : undefined}
        detail="按租户读取项目摘要；列表为空与服务失败保持区分。"
        action={
          <label className={styles.searchControl}>
            <span className="sr-only">搜索项目</span>
            <input
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="搜索项目"
              type="search"
            />
          </label>
        }
      />
      {state.status !== "ready" ? (
        <BusinessPanelState state={state} loadingText="正在读取内容项目" />
      ) : state.data.items.length === 0 ? (
        <PanelEmpty
          title={search ? "没有匹配的内容项目" : "还没有内容项目"}
          detail={search ? "调整搜索条件后重新读取。" : "项目创建后会出现在这里。"}
        />
      ) : (
        <>
          <div className={styles.projectList} role="list" aria-label="内容项目列表">
            {state.data.items.map((project) => (
              <button
                type="button"
                className={
                  styles.projectItem +
                  (project.publicProjectId === selectedProjectId ? " " + styles.projectItemSelected : "")
                }
                key={project.publicProjectId}
                onClick={() => onSelect(project.publicProjectId)}
              >
                <span className={styles.projectItemIcon}>
                  <FolderKanban size={16} />
                </span>
                <span className={styles.projectItemCopy}>
                  <strong title={project.title}>{project.title}</strong>
                  <span>{project.stage} · {project.status} · {project.workspaceMode}</span>
                  <small>
                    {Object.entries(project.artifactCounts).length
                      ? Object.entries(project.artifactCounts)
                          .slice(0, 3)
                          .map(([kind, count]) => `${kind}: ${count}`)
                          .join(" · ")
                      : "暂无产物"}
                  </small>
                </span>
                <time dateTime={project.updatedAt}>{displayDate(project.updatedAt)}</time>
                <ChevronRight size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
          <ProjectComposer
            project={selectedProject}
            reason={summaryReason}
            action={summaryAction}
            onReasonChange={onReasonChange}
            onCreate={onCreateSummary}
            disabled={!canCreateSummary}
          />
          <CursorPager
            pageLabel="项目列表"
            canPrevious={canPrevious}
            canNext={!!state.data.nextCursor}
            onPrevious={onPrevious}
            onNext={onNext}
          />
        </>
      )}
    </section>
  );
}

function ProjectComposer({
  project,
  reason,
  action,
  onReasonChange,
  onCreate,
  disabled,
}: {
  project: ContentProjectSummary | null;
  reason: string;
  action: SummaryActionState;
  onReasonChange: (value: string) => void;
  onCreate: () => void;
  disabled: boolean;
}) {
  if (!project) return null;
  return (
    <div className={styles.projectComposer}>
      <div className={styles.composerHeading}>
        <div>
          <h3>项目摘要</h3>
          <p title={project.publicProjectId}>{project.title} · {project.publicProjectId}</p>
        </div>
        <span>生成 revision 受服务端校验</span>
      </div>
      <div className={styles.composerControls}>
        <label>
          <span>生成原因</span>
          <input value={reason} onChange={(event) => onReasonChange(event.target.value)} />
        </label>
        <button type="button" onClick={onCreate} disabled={disabled || action.status === "busy"}>
          <RefreshCw size={14} className={action.status === "busy" ? styles.spin : undefined} />
          {action.status === "busy" ? "提交中" : "生成摘要"}
        </button>
      </div>
      {action.status === "success" || action.status === "error" ? (
        <p className={action.status === "error" ? styles.actionError : styles.actionSuccess} role={action.status === "error" ? "alert" : "status"}>
          {action.message}
        </p>
      ) : null}
    </div>
  );
}

function ArtifactsPanel({
  state,
  selectedProject,
  onNext,
  onPrevious,
  canPrevious,
}: {
  state: B01LoadState<ArtifactListResponse>;
  selectedProject: ContentProjectSummary | null;
  onNext: () => void;
  onPrevious: () => void;
  canPrevious: boolean;
}) {
  return (
    <section className={"section-panel " + styles.panel + " " + styles.artifactsPanel}>
      <PanelHeading
        icon={FileText}
        title="项目产物"
        count={state.status === "ready" && selectedProject ? state.data.items.length : undefined}
        detail={selectedProject ? `当前项目：${selectedProject.title}` : "选择内容项目后读取产物。"}
        action={
          <Link className={styles.panelLink} to="/runs">
            查看运行
            <ArrowUpRight size={14} />
          </Link>
        }
      />
      {!selectedProject ? (
        <PanelEmpty title="选择一个项目查看产物" detail="项目产物不会从其它页面或旧接口推断。" />
      ) : state.status !== "ready" ? (
        <BusinessPanelState state={state} loadingText="正在读取项目产物" />
      ) : state.data.items.length === 0 ? (
        <PanelEmpty title="该项目还没有产物" detail="产物生成后会显示当前 revision 与同步状态。" />
      ) : (
        <>
          <div className={styles.artifactList} role="list" aria-label="项目产物列表">
            {state.data.items.map((artifact) => (
              <article className={styles.artifactItem} key={artifact.publicArtifactId}>
                <span className={styles.artifactIcon}>
                  <Layers3 size={16} />
                </span>
                <div className={styles.artifactCopy}>
                  <strong title={artifact.publicArtifactId}>{artifact.artifactType}</strong>
                  <span title={artifact.publicArtifactId}>{artifact.publicArtifactId}</span>
                  <small>{artifact.bodyAuthority} · revision {artifact.currentRevision}</small>
                </div>
                <div className={styles.artifactMeta}>
                  <span className={"status-badge is-" + artifactTone(artifact.syncStatus)}>{artifact.syncStatus}</span>
                  <time dateTime={artifact.updatedAt}>{displayDate(artifact.updatedAt)}</time>
                  <span className={styles.actionList}>{artifact.allowedActions.join(" · ")}</span>
                </div>
              </article>
            ))}
          </div>
          <CursorPager
            pageLabel="产物列表"
            canPrevious={canPrevious}
            canNext={!!state.data.nextCursor}
            onPrevious={onPrevious}
            onNext={onNext}
          />
        </>
      )}
    </section>
  );
}

function CursorPager({
  pageLabel,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
}: {
  pageLabel: string;
  canPrevious: boolean;
  canNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (!canPrevious && !canNext) return null;
  return (
    <nav className={styles.cursorPager} aria-label={pageLabel + "分页"}>
      <button type="button" onClick={onPrevious} disabled={!canPrevious} aria-label="上一页">
        <ChevronLeft size={15} />
        上一页
      </button>
      <button type="button" onClick={onNext} disabled={!canNext} aria-label="下一页">
        下一页
        <ChevronRight size={15} />
      </button>
    </nav>
  );
}

function BusinessPanelState<T>({
  state,
  loadingText,
  compact = false,
}: {
  state: B01LoadState<T>;
  loadingText: string;
  compact?: boolean;
}) {
  if (state.status === "loading") {
    return (
      <div className={styles.panelState + (compact ? " " + styles.compactState : "")} aria-busy="true">
        <LoaderCircle className={styles.spin} size={18} />
        <span>{loadingText}</span>
      </div>
    );
  }
  if (state.status === "ready") return null;
  return (
    <div
      className={
        styles.panelState +
        " " +
        styles.errorState +
        (compact ? " " + styles.compactState : "")
      }
      role="alert"
    >
      <ShieldAlert size={18} />
      <span>{state.message}</span>
    </div>
  );
}

function isEmptyDashboard(summary: DashboardSummary) {
  return (
    Object.values(summary.counts).every((value) => value === 0) &&
    summary.contentProjectStages.every((item) => item.count === 0) &&
    [summary.pendingDecisions, summary.pendingPublishing, summary.pendingReviews].every(
      (value) => value === 0,
    ) &&
    Object.values(summary.taskSummary).every((value) => value === 0) &&
    Object.values(summary.coverage).every((value) => value === 0)
  );
}

function dashboardLabel(value: string) {
  const labels: Record<string, string> = {
    contentProjects: "内容项目",
    runs: "创作运行",
    assets: "素材",
    tracks: "赛道",
    creators: "博主",
    publishedPosts: "已发布",
    reviews: "复盘记录",
    research: "研究",
    decision: "决策",
    creation: "创作",
    publishing: "发布",
    review: "复盘",
  };
  return labels[value] ?? value;
}

function artifactTone(status: ArtifactSummary["syncStatus"]): "success" | "warning" | "info" | "neutral" {
  if (status === "synced" || status === "not_applicable") return "success";
  if (status === "conflict" || status === "failed") return "warning";
  if (status === "pending") return "info";
  return "neutral";
}

function MetricStrip({
  dashboardState,
}: {
  dashboardState: B01LoadState<DashboardResponse>;
}) {
  const summary = dashboardState.status === "ready" ? dashboardState.data.summary : null;
  return (
    <section className={styles.metricStrip} aria-label="账户指标">
      <MetricCard
        icon={FolderKanban}
        label="内容项目"
        value={summary ? displayNumber(summary.counts.contentProjects) : "—"}
        detail={loadDetail(dashboardState, "当前租户")}
      />
      <MetricCard
        icon={PackageCheck}
        label="创作运行"
        value={summary ? displayNumber(summary.counts.runs) : "—"}
        detail={loadDetail(dashboardState, "标准汇总")}
      />
      <MetricCard
        icon={Target}
        label="待决策"
        value={summary ? displayNumber(summary.pendingDecisions) : "—"}
        detail={loadDetail(dashboardState, "当前租户")}
      />
      <MetricCard
        icon={Send}
        label="待发布"
        value={summary ? displayNumber(summary.pendingPublishing) : "—"}
        detail={loadDetail(dashboardState, "当前租户")}
      />
    </section>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  detail: string;
}) {
  return (
    <div className={styles.metricCard}>
      <span className={styles.metricIcon}>
        <Icon size={18} />
      </span>
      <div className={styles.metricCopy}>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function PanelHeading({
  icon: Icon,
  title,
  count,
  detail,
  action,
}: {
  icon: LucideIcon;
  title: string;
  count?: ReactNode;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <header className={styles.panelHeading}>
      <div className={styles.headingCopy}>
        <div className={styles.headingTitle}>
          <Icon size={17} />
          <h2>{title}</h2>
          {count !== undefined ? <span>{count}</span> : null}
        </div>
        <p>{detail}</p>
      </div>
      {action}
    </header>
  );
}

function AgentPanel({
  capabilityState,
  taskState,
  activeTasks,
}: {
  capabilityState: B01LoadState<CapabilityCatalog>;
  taskState: B01LoadState<MediaTaskListResponse>;
  activeTasks: MediaTaskSummary[];
}) {
  const catalog =
    capabilityState.status === "ready" ? capabilityState.data : null;
  const currentTask = activeTasks[0];
  const capabilityNames =
    catalog?.capabilities
      .slice(0, 6)
      .map((item) => item.displayName || item.label)
      .filter(Boolean) ?? [];
  const capabilityCount = catalog?.capabilities.length ?? 0;
  const progress = currentTask
    ? Math.min(100, Math.max(0, currentTask.progress))
    : 0;
  return (
    <section
      className={"section-panel " + styles.panel + " " + styles.agentPanel}
    >
      <PanelHeading
        icon={Bot}
        title="Media Agent"
        detail="读取当前账户可用的能力目录与网页任务状态。"
      />
      <div className={styles.agentBody}>
        <div
          className={
            styles.catalogState + (catalog ? " " + styles.stateReady : "")
          }
        >
          {catalog ? (
            <CheckCircle2 size={16} />
          ) : capabilityState.status === "loading" ? (
            <LoaderCircle className={styles.spin} size={16} />
          ) : (
            <AlertCircle size={16} />
          )}
          <strong>
            {catalog
              ? "目录已匹配"
              : capabilityState.status === "loading"
                ? "正在读取能力目录"
                : "目录暂不可用"}
          </strong>
        </div>
        <div className={styles.agentFacts}>
          <div>
            <span>可用能力</span>
            <strong>
              {catalog ? displayNumber(catalog.capabilities.length) : "—"}
            </strong>
            <small>{catalog ? "当前账户目录" : "等待目录响应"}</small>
          </div>
          <div>
            <span>进行中网页任务</span>
            <strong>
              {taskState.status === "ready"
                ? displayNumber(activeTasks.length)
                : "—"}
            </strong>
            <small>
              {taskState.status === "ready" ? "当前租户任务" : "等待任务响应"}
            </small>
          </div>
        </div>
        <div className={styles.agentSection}>
          <div className={styles.subsectionHeading}>
            <h3>当前网页任务</h3>
            {currentTask ? (
              <span
                className={"status-badge is-" + taskTone(currentTask.status)}
              >
                {taskStatusLabel(currentTask.status)}
              </span>
            ) : null}
          </div>
          {taskState.status !== "ready" ? (
            <BusinessPanelState
              state={taskState}
              loadingText="正在读取任务状态"
              compact
            />
          ) : currentTask ? (
            <div className={styles.progressBlock}>
              <div className={styles.progressMeta}>
                <strong title={currentTask.summary || undefined}>
                  {displayText(currentTask.summary)}
                </strong>
                <span>{progress}%</span>
              </div>
              <div
                className={styles.progressTrack}
                role="progressbar"
                aria-label="当前网页任务进度"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress}
              >
                <span style={{ width: progress + "%" }} />
              </div>
              <p
                className={styles.taskPath}
                title={currentTask.capabilityId + " / " + currentTask.variantId}
              >
                能力 {currentTask.capabilityId} · variant {currentTask.variantId} · revision {displayNumber(currentTask.revision)}
              </p>
            </div>
          ) : (
            <PanelEmpty
              compact
              title="当前没有进行中的网页任务"
              detail="任务开始后，进度会显示在这里。"
            />
          )}
        </div>
        <div className={styles.agentSection}>
          <div className={styles.subsectionHeading}>
            <h3>能力摘要</h3>
            {catalog ? <span>{catalog.capabilities.length} 项</span> : null}
          </div>
          {capabilityState.status !== "ready" ? (
            <BusinessPanelState
              state={capabilityState}
              loadingText="正在读取能力目录"
              compact
            />
          ) : capabilityNames.length ? (
            <div className={styles.capabilityList}>
              {capabilityNames.map((name) => (
                <span key={name} title={name}>
                  {name}
                </span>
              ))}
              {capabilityCount > capabilityNames.length ? (
                <span>+{capabilityCount - capabilityNames.length} 项</span>
              ) : null}
            </div>
          ) : (
            <PanelEmpty
              compact
              title="暂无可用能力"
              detail="当前账户目录没有返回能力项。"
            />
          )}
        </div>
        <p className={styles.interfaceNote}>
          设备、客户端与本机运行状态未由当前页面接口提供。
        </p>
      </div>
    </section>
  );
}

function WorkflowPanel() {
  return (
    <section
      className={"section-panel " + styles.panel + " " + styles.workflowPanel}
    >
      <PanelHeading
        icon={TrendingUp}
        title="执行链路"
        detail="从素材进入发布与复盘。"
      />
      <nav className={styles.workflow} aria-label="执行链路">
        {workflowChain.map((item, index) => {
          const Icon = item.icon;
          return (
            <span className={styles.workflowItem} key={item.to}>
              <Link
                className={styles.workflowLink}
                to={item.to}
                title={item.label}
              >
                <Icon size={16} />
                <span>{item.label}</span>
              </Link>
              {index < workflowChain.length - 1 ? (
                <ChevronRight
                  className={styles.workflowArrow}
                  size={14}
                  aria-hidden="true"
                />
              ) : null}
            </span>
          );
        })}
      </nav>
    </section>
  );
}

function PendingPanel({
  state,
  tasks,
  taskActions,
  onDecide,
  onOpenWorkspace,
}: {
  state: B01LoadState<MediaTaskListResponse>;
  tasks: MediaTaskSummary[];
  taskActions: Record<string, TaskActionState>;
  onDecide: (task: MediaTaskSummary, reason: string) => Promise<void>;
  onOpenWorkspace: () => void;
}) {
  return (
    <section
      className={"section-panel " + styles.panel + " " + styles.pendingPanel}
      data-page-terminal-surface="inspector"
    >
      <PanelHeading
        icon={AlertCircle}
        title="需要处理"
        count={state.status === "ready" ? tasks.length : undefined}
        detail="只列出当前租户需要人工查看的网页任务。"
      />
      {state.status !== "ready" ? (
        <BusinessPanelState state={state} loadingText="正在读取待处理任务" />
      ) : tasks.length ? (
        <div
          className={styles.pendingList}
          tabIndex={0}
          aria-label="待处理任务列表"
        >
          {tasks.map((task) => (
            <PendingTask
              key={task.taskId}
              task={task}
              actionState={taskActions[task.taskId]}
              onDecide={onDecide}
              onOpenWorkspace={onOpenWorkspace}
            />
          ))}
        </div>
      ) : (
        <PanelEmpty
          title="当前没有待处理任务"
          detail="需要人工确认或处理的任务会出现在这里。"
        />
      )}
    </section>
  );
}

function PendingTask({
  task,
  actionState,
  onDecide,
  onOpenWorkspace,
}: {
  task: MediaTaskSummary;
  actionState?: TaskActionState;
  onDecide: (task: MediaTaskSummary, reason: string) => Promise<void>;
  onOpenWorkspace: () => void;
}) {
  const [reason, setReason] = useState("确认网页任务");
  const taskTitle = task.capabilityId || "待处理任务";
  const busy = actionState?.status === "busy";
  const requiresConfirmation = task.status === "awaiting_confirmation";
  return (
    <article className={styles.pendingItem}>
      <span
        className={
          styles.pendingIcon +
          (requiresConfirmation ? " " + styles.pendingWarning : "")
        }
      >
        {requiresConfirmation ? (
          <AlertCircle size={17} />
        ) : (
          <CircleDashed size={17} />
        )}
      </span>
      <div className={styles.pendingCopy}>
        <div className={styles.pendingTitle}>
          <strong title={taskTitle}>{taskTitle}</strong>
          <span className={"status-badge is-" + taskTone(task.status)}>
            {taskStatusLabel(task.status)}
          </span>
        </div>
        <p title={task.summary || undefined}>{displayText(task.summary)}</p>
        <span className={styles.pendingPath} title={task.variantId}>
          variant {task.variantId} · revision {displayNumber(task.revision)}
        </span>
      </div>
      <time
        className={styles.pendingTime}
        dateTime={task.updatedAt || task.createdAt}
      >
        {displayDate(task.updatedAt || task.createdAt)}
      </time>
      <div className={styles.pendingActions}>
        {requiresConfirmation ? (
          <>
            <label className={styles.confirmReason}>
              <span>确认原因</span>
              <input
                value={reason}
                maxLength={4096}
                onChange={(event) => setReason(event.target.value)}
                placeholder="填写确认原因"
              />
            </label>
            <button
              type="button"
              className={styles.approveButton}
              disabled={busy}
              onClick={() => void onDecide(task, reason)}
            >
              <CheckCircle2 size={14} />
              确认执行
            </button>
          </>
        ) : (
          <button
            type="button"
            className={styles.openTaskButton}
            onClick={onOpenWorkspace}
          >
            打开任务工作区
            <ChevronRight size={14} />
          </button>
        )}
        {actionState?.status === "error" ? (
          <span className={styles.actionError} role="alert">
            {actionState.message}
          </span>
        ) : null}
      </div>
    </article>
  );
}


function PanelEmpty({
  title,
  detail,
  compact = false,
}: {
  title: string;
  detail: string;
  compact?: boolean;
}) {
  return (
    <div
      className={styles.panelEmpty + (compact ? " " + styles.compactEmpty : "")}
    >
      <CircleDashed size={18} />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function isPendingTask(task: MediaTaskSummary) {
  return (
    !task.terminal &&
    (task.status === "awaiting_confirmation" || task.status === "pending_manual")
  );
}

function taskStatusLabel(status: string) {
  return taskStatusLabels[status] ?? "状态待读取";
}

function taskTone(status: string): "success" | "warning" | "info" | "neutral" {
  if (status === "succeeded") return "success";
  if (status === "failed" || status === "cancelled") return "warning";
  if (status === "awaiting_confirmation" || status === "pending_manual")
    return "warning";
  return status ? "info" : "neutral";
}

function loadDetail<T>(state: B01LoadState<T>, readyText: string) {
  return state.status === "loading"
    ? "读取中"
    : state.status === "timeout"
      ? "请求超时"
      : state.status === "error" ||
          state.status === "permission" ||
          state.status === "notFound"
        ? "读取失败"
        : readyText;
}

function displayText(value?: string) {
  return value?.trim() ? value : "—";
}

function displayDate(value?: string) {
  if (!value || Number.isNaN(Date.parse(value))) return "时间待读取";
  return formatDate(value);
}

export default OverviewPage;
