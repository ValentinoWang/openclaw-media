import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  ClipboardCheck,
  Eye,
  ExternalLink,
  FileCheck2,
  FilePenLine,
  FileText,
  FolderKanban,
  Images,
  Layers3,
  Lightbulb,
  LoaderCircle,
  NotebookText,
  PackageCheck,
  PenTool,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  Target,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import { TaskSettlementDetails, useMediaWeb } from "../../MediaWebWorkspace";
import type { MediaWebTask } from "../../mediaWebApi";
import { latestTaskFeed } from "../../recentTaskPresentation";
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
import {
  actionDisplayLabel,
  artifactTypeDisplayLabel,
  bodyAuthorityDisplayLabel,
  projectStageDisplayLabel,
  projectStatusDisplayLabel,
  syncStatusDisplayLabel,
  workspaceModeDisplayLabel,
} from "../../ui/displayLabels";
import styles from "./OverviewPage.module.css";
import CanonicalDocumentRenderer from "./CanonicalDocumentRenderer";
import type { DocumentBlock, DocumentInlineNode, DocumentRichTextBlock } from "../../documentWorkflow";

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
  displayName: string | null;
  bodyAuthority: "internal" | "lark";
  currentRevision: number;
  syncStatus: "not_applicable" | "pending" | "synced" | "conflict" | "failed";
  updatedAt: string;
  allowedActions: string[];
  organizationDocumentUrl?: string | null;
  organizationDocumentUrlExpiresAt?: string | null;
  larkDocumentUrl?: string | null;
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

type DocumentBodyResponse = {
  schemaVersion: string;
  revision: number;
  data: {
    artifact: {
      publicArtifactId: string;
      artifactKind: string;
      workspaceMode: "personal_web" | "organization_lark";
      bodyAuthority: "internal" | "lark";
      currentRevision: number;
      updatedAt: string;
    };
    revision: {
      revision: number;
      state: string;
      body: {
        schemaVersion: "media.document.body.v1";
        blocks: DocumentBlock[];
      };
      updatedAt: string;
    };
  };
};
type MediaTaskSummary = MediaWebTask;
type MediaTaskListResponse = {
  schemaVersion: string;
  revision: number;
  items: MediaTaskSummary[];
  nextCursor: string | null;
};
type MediaTaskV3ListResponse = {
  schemaVersion: string;
  tasks: MediaTaskSummary[];
};

type SummaryActionState =
  | { status: "idle" }
  | { status: "busy" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

const EMPTY_TASKS: MediaTaskSummary[] = [];
const B01_REQUEST_TIMEOUT_MS = 10_000;

const artifactIcons: Record<string, LucideIcon> = {
  research_snapshot: Search,
  asset_digest: Images,
  decision_brief: ClipboardCheck,
  creation_document: FilePenLine,
  publishing_package: PackageCheck,
  review_report: FileCheck2,
  project_summary: NotebookText,
};

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
  const {
    openWorkspace,
    session,
    cancelDeletionIntent,
  } = useMediaWeb();
  const [refreshToken, setRefreshToken] = useState(0);
  const [projectSearch, setProjectSearch] = useState("");
  const [projectCursor, setProjectCursor] = useState<string | undefined>();
  const [projectHistory, setProjectHistory] = useState<string[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [artifactCursor, setArtifactCursor] = useState<string | undefined>();
  const [artifactHistory, setArtifactHistory] = useState<string[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [summaryReason, setSummaryReason] = useState("更新项目摘要");
  const [summaryAction, setSummaryAction] = useState<SummaryActionState>({
    status: "idle",
  });
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
  const taskState = useB01Tasks(refreshToken);
  const tasks =
    taskState.status === "ready" ? taskState.data.items : EMPTY_TASKS;
  const activeTasks = useMemo(
    () => latestTaskFeed(tasks.filter((task) => !task.terminal)),
    [tasks],
  );
  const recentTask = useMemo(() => latestTaskFeed(tasks)[0], [tasks]);
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
    setSelectedArtifactId(null);
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
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("b01-summary"),
      });
      setSummaryAction({ status: "success", message: "摘要生成请求已提交。" });
      setRefreshToken((current) => current + 1);
      setArtifactCursor(undefined);
      setArtifactHistory([]);
    } catch {
      setSummaryAction({
        status: "error",
        message: "摘要暂时无法生成。请稍后重试。",
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
  const unavailableResources = [
    { label: "租户概览", state: dashboardState },
    { label: "内容项目", state: projectState },
    { label: "项目产物", state: artifactState },
    { label: "能力目录", state: capabilityState },
    { label: "网页任务", state: taskState },
  ].flatMap((resource) => {
    const message = unavailableResourceMessage(resource.state);
    return message ? [{ label: resource.label, message }] : [];
  });

  return (
    <main className={"overview-page fidelity-page " + styles.page}>
      <div data-page-prelude>
        <PageHeading
          title="运营总览"
          description="查看当前租户的内容项目、产物进度与待处理事项。"
        />
        <MetricStrip dashboardState={dashboardState} />
        {partial ? (
          <div className={styles.partialBanner} role="alert" data-page-partial>
            <ShieldAlert size={16} />
            <div>
              <strong>以下运营数据暂时无法读取</strong>
              <ul>{unavailableResources.map((resource) => <li key={resource.label}>{resource.label}：{resource.message}</li>)}</ul>
              <span>已成功返回的数据仍保留在当前页面。</span>
            </div>
            <button type="button" onClick={() => setRefreshToken((current) => current + 1)}>重新读取</button>
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
            selectedArtifactId={selectedArtifactId}
            onSelectArtifact={setSelectedArtifactId}
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
            recentTask={recentTask}
          />
          <WorkflowPanel />
          <PendingPanel
            state={taskState}
            tasks={pendingTasks}
            onOpenWorkspace={openWorkspace}
            onCancelDeletion={cancelDeletionIntent}
            onTasksChanged={() => setRefreshToken((current) => current + 1)}
          />
        </div>
      </div>
    </main>
  );
}

function unavailableResourceMessage(state: B01LoadState<unknown>): string | null {
  return state.status === "permission" || state.status === "notFound" || state.status === "timeout" || state.status === "error"
    ? state.message
    : null;
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

function useB01DocumentBody(
  artifactId: string | null,
  retryToken: number,
): B01LoadState<DocumentBodyResponse> {
  return useB01Request(
    (signal) =>
      callBusinessOperation<DocumentBodyResponse>("getDocumentBody", {
        path: { publicArtifactId: artifactId as string },
        signal,
      }),
    JSON.stringify([artifactId, retryToken]),
    "文档正文读取失败。",
    artifactId !== null,
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
          ? payload.tasks
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
    return { status: "error", message: fallback };
  }
  return { status: "error", message: fallback };
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
        detail="查看当前工作区的内容项目与摘要。"
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
                aria-pressed={project.publicProjectId === selectedProjectId}
              >
                <span className={styles.projectItemIcon}>
                  <FolderKanban size={16} />
                </span>
                <span className={styles.projectItemCopy}>
                  <strong title={project.title}>{project.title}</strong>
                  <span>{projectStageDisplayLabel(project.stage)} · {projectStatusDisplayLabel(project.status)} · {workspaceModeDisplayLabel(project.workspaceMode)}</span>
                  <small>
                    {Object.entries(project.artifactCounts).length
                      ? Object.entries(project.artifactCounts)
                          .slice(0, 3)
                          .map(([kind, count]) => `${artifactTypeDisplayLabel(kind)}：${count}`)
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
          <p>{project.title}</p>
        </div>
        <span>生成前会确认项目为最新状态</span>
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
  selectedArtifactId,
  onSelectArtifact,
  onNext,
  onPrevious,
  canPrevious,
}: {
  state: B01LoadState<ArtifactListResponse>;
  selectedProject: ContentProjectSummary | null;
  selectedArtifactId: string | null;
  onSelectArtifact: (publicArtifactId: string | null) => void;
  onNext: () => void;
  onPrevious: () => void;
  canPrevious: boolean;
}) {
  const [documentRetryToken, setDocumentRetryToken] = useState(0);
  const selectedArtifact =
    state.status === "ready"
      ? state.data.items.find((item) => item.publicArtifactId === selectedArtifactId) ?? null
      : null;
  const documentState = useB01DocumentBody(
    selectedArtifact?.publicArtifactId ?? null,
    documentRetryToken,
  );
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
        <PanelEmpty title="选择一个项目查看产物" detail="选择项目后即可查看相关产物。" />
      ) : state.status !== "ready" ? (
        <BusinessPanelState state={state} loadingText="正在读取项目产物" />
      ) : state.data.items.length === 0 ? (
        <PanelEmpty title="该项目还没有产物" detail="产物生成后会显示类型与同步状态。" />
      ) : (
        <>
          <div className={styles.artifactList} role="list" aria-label="项目产物列表">
            {state.data.items.map((artifact) => {
              const isSelected = artifact.publicArtifactId === selectedArtifactId;
              const displayName = artifactDisplayName(artifact);
              return (
                <div className={styles.artifactEntry} role="listitem" key={artifact.publicArtifactId}>
                  <article
                    className={`${styles.artifactItem}${isSelected ? ` ${styles.artifactItemSelected}` : ""}`}
                  >
                    <ArtifactRowContent artifact={artifact} />
                    <div className={styles.artifactActions} data-artifact-actions>
                      <button
                        type="button"
                        className={styles.previewButton}
                        data-artifact-row={artifact.publicArtifactId}
                        onClick={() => onSelectArtifact(isSelected ? null : artifact.publicArtifactId)}
                        aria-expanded={isSelected}
                        aria-label={`${isSelected ? "收起网页内容" : "查看网页内容"}：${displayName}`}
                      >
                        <Eye size={13} aria-hidden="true" />
                        {isSelected ? "收起网页内容" : "查看网页内容"}
                      </button>
                      {getOrganizationDocumentUrl(artifact) ? <a className={styles.documentLink} href={getOrganizationDocumentUrl(artifact)!} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden="true" />打开组织文档</a> : null}
                    </div>
                  </article>
                  {isSelected ? <DocumentPreview artifact={artifact} state={documentState} onRetry={() => setDocumentRetryToken((current) => current + 1)} /> : null}
                </div>
              );
            })}
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

function ArtifactRowContent({
  artifact,
}: {
  artifact: ArtifactSummary;
}) {
  const ArtifactIcon = artifactIcon(artifact.artifactType);
  const syncStatus = artifact.syncStatus;
  const allowedActions = artifact.allowedActions.map(actionDisplayLabel);
  return <>
    <span className={styles.artifactIdentity} data-artifact-identity>
      <span
        className={styles.artifactIcon}
        data-artifact-icon={artifactTypeDisplayLabel(artifact.artifactType)}
      >
        <ArtifactIcon size={16} aria-hidden="true" />
      </span>
      <span className={styles.artifactCopy}>
        <strong data-artifact-name>{artifactDisplayName(artifact)}</strong>
        <span data-artifact-detail>
          {artifactTypeDisplayLabel(artifact.artifactType)} · {bodyAuthorityDisplayLabel(artifact.bodyAuthority)} · {allowedActions.length ? allowedActions.join("、") : "暂无可用操作"}
        </span>
      </span>
    </span>
    <span className={styles.artifactMeta} data-artifact-meta>
      <span className={"status-badge is-" + artifactTone(syncStatus)}>{syncStatusDisplayLabel(artifact.syncStatus)}</span>
      <time dateTime={artifact.updatedAt}>{displayDate(artifact.updatedAt)}</time>
    </span>
  </>;
}

function artifactIcon(artifactType: string): LucideIcon {
  return artifactIcons[artifactType] ?? FileText;
}

function artifactDisplayName(
  artifact: Pick<ArtifactSummary, "artifactType" | "displayName">,
): string {
  const displayName = artifact.displayName?.trim();
  return displayName || `未命名${artifactTypeDisplayLabel(artifact.artifactType)}`;
}

function DocumentPreview({
  artifact,
  state,
  onRetry,
}: {
  artifact: ArtifactSummary;
  state: B01LoadState<DocumentBodyResponse>;
  onRetry: () => void;
}) {
  const documentUrl = getOrganizationDocumentUrl(artifact);
  const title =
    state.status === "ready"
      ? documentTitle(state.data.data.revision.body.blocks, artifact.artifactType)
      : artifactTypeDisplayLabel(artifact.artifactType);
  return (
    <section className={styles.documentPreview} aria-label="文档正文预览">
      <header className={styles.documentPreviewHeader}>
        <div>
          <span>网页正文预览</span>
          <h3>{title}</h3>
        </div>
        {documentUrl ? (
          <a className={styles.documentLink} href={documentUrl} target="_blank" rel="noreferrer">
            <ExternalLink size={14} aria-hidden="true" />打开组织文档
          </a>
        ) : null}
      </header>
      {state.status === "loading" ? (
        <BusinessPanelState state={state} loadingText="正在读取文档正文" compact />
      ) : state.status === "ready" ? (
        state.data.data.revision.body.blocks.length === 0 ? <PanelEmpty title="文档暂无正文" detail="当前修订没有可展示的内容块。" /> : <CanonicalDocumentRenderer blocks={state.data.data.revision.body.blocks} />
      ) : (
        <DocumentPreviewUnavailable state={state} onRetry={onRetry} />
      )}
    </section>
  );
}

function DocumentPreviewUnavailable({
  state,
  onRetry,
}: {
  state: Exclude<B01LoadState<DocumentBodyResponse>, { status: "loading" } | { status: "ready"; data: DocumentBodyResponse }>;
  onRetry: () => void;
}) {
  const detail = state.status === "permission"
    ? "当前账户无权在网页内读取这份文档，可打开组织文档继续查看。"
    : state.status === "notFound"
      ? "当前文档尚未提供可读取的网页正文，可打开组织文档继续查看。"
      : state.status === "timeout"
        ? "网页正文读取超时，文档列表仍可继续使用。"
        : "网页正文暂时不可读取，文档列表仍可继续使用。";
  return <div className={styles.documentUnavailable} role="status"><FileText size={18} aria-hidden="true" /><div><strong>网页正文暂不可读取</strong><span>{detail}</span></div><button type="button" onClick={onRetry}><RefreshCw size={14} aria-hidden="true" />重新读取</button></div>;
}

function documentTitle(blocks: DocumentBlock[], fallbackArtifactType: string): string {
  const title = blocks.find((block): block is DocumentRichTextBlock => block.type === "heading_1");
  const value = title ? inlineText(title.content) : "";
  return value || artifactTypeDisplayLabel(fallbackArtifactType);
}

function inlineText(nodes: DocumentInlineNode[] | undefined): string {
  return (nodes ?? []).map((node) => node.text).join("").trim();
}

function getOrganizationDocumentUrl(artifact: Pick<ArtifactSummary, "organizationDocumentUrl" | "larkDocumentUrl">): string | null {
  const value = artifact.organizationDocumentUrl ?? artifact.larkDocumentUrl;
  if (typeof value !== "string") return null;
  try {
    const parsed = new URL(value.trim());
    const validHost =
      parsed.hostname === "feishu.cn" ||
      parsed.hostname === "larksuite.com" ||
      parsed.hostname === "larkoffice.com" ||
      parsed.hostname.endsWith(".feishu.cn") ||
      parsed.hostname.endsWith(".larksuite.com") ||
      parsed.hostname.endsWith(".larkoffice.com");
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (
      parsed.protocol !== "https:" ||
      !validHost ||
      parts.length !== 2 ||
      !["wiki", "docx", "doc", "docs"].includes(parts[0].toLowerCase()) ||
      !/^[A-Za-z0-9_-]{8,160}$/u.test(parts[1])
    ) return null;
    return parsed.toString();
  } catch {
    return null;
  }
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
  return labels[value] ?? "未识别指标";
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
  recentTask,
}: {
  capabilityState: B01LoadState<CapabilityCatalog>;
  taskState: B01LoadState<MediaTaskListResponse>;
  activeTasks: MediaTaskSummary[];
  recentTask?: MediaTaskSummary;
}) {
  const catalog =
    capabilityState.status === "ready" ? capabilityState.data : null;
  const currentTask = activeTasks[0] ?? recentTask;
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
            <h3>{activeTasks.length ? "当前网页任务" : "最近网页任务"}</h3>
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
              <p className={styles.taskPath}>
                {currentTask.terminal
                  ? "服务端已返回任务终态"
                  : "任务正在按当前流程执行"}
              </p>
              <TaskSettlementDetails task={currentTask} compact />
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
  onOpenWorkspace,
  onCancelDeletion,
  onTasksChanged,
}: {
  state: B01LoadState<MediaTaskListResponse>;
  tasks: MediaTaskSummary[];
  onOpenWorkspace: () => void;
  onCancelDeletion: (taskId: string) => Promise<void>;
  onTasksChanged: () => void;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const actionableTasks = tasks.filter((task) => isPendingTask(task, nowMs));
  return (
    <section
      className={"section-panel " + styles.panel + " " + styles.pendingPanel}
      data-page-terminal-surface="inspector"
    >
      <PanelHeading
        icon={AlertCircle}
        title="需要处理"
        count={state.status === "ready" ? actionableTasks.length : undefined}
        detail="只列出当前租户需要人工查看的网页任务。"
      />
      {state.status !== "ready" ? (
        <BusinessPanelState state={state} loadingText="正在读取待处理任务" />
      ) : actionableTasks.length ? (
        <div
          className={styles.pendingList}
          tabIndex={0}
          aria-label="待处理任务列表"
        >
          {actionableTasks.map((task) => (
            <PendingTask
              key={task.taskId}
              task={task}
              onOpenWorkspace={onOpenWorkspace}
              onCancelDeletion={onCancelDeletion}
              onTasksChanged={onTasksChanged}
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
  onOpenWorkspace,
  onCancelDeletion,
  onTasksChanged,
}: {
  task: MediaTaskSummary;
  onOpenWorkspace: () => void;
  onCancelDeletion: (taskId: string) => Promise<void>;
  onTasksChanged: () => void;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [action, setAction] = useState<"idle" | "cancelling">("idle");
  const [actionError, setActionError] = useState("");
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const presentation = pendingTaskPresentation(task, nowMs);
  if (presentation.deletionState === "expired") return null;
  const requiresConfirmation = presentation.deletionState === "active";
  function openTaskReview() {
    onOpenWorkspace();
    window.setTimeout(() => {
      const taskItem = document.querySelector<HTMLElement>(
        `[data-task-id="${task.taskId}"]`,
      );
      taskItem?.scrollIntoView({ block: "start" });
      taskItem?.focus({ preventScroll: true });
    }, 0);
  }
  async function cancelDeletion() {
    setAction("cancelling");
    setActionError("");
    try {
      await onCancelDeletion(task.taskId);
      onTasksChanged();
    } catch {
      setActionError("暂时无法取消删除，请稍后再试。");
    } finally {
      setAction("idle");
    }
  }
  return (
    <article
      className={
        styles.pendingItem +
        (presentation.destructive ? " " + styles.pendingDanger : "")
      }
      data-confirmation-kind={presentation.kind}
    >
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
          <strong title={presentation.title}>{presentation.title}</strong>
          <span className={"status-badge is-" + presentation.statusTone}>
            {presentation.statusLabel}
          </span>
        </div>
        <p className={styles.pendingImpact}>{presentation.impact}</p>
        {presentation.target ? (
          <div className={styles.pendingTarget}>
            <span>{presentation.targetLabel}</span>
            <code>{presentation.target}</code>
          </div>
        ) : null}
        <span className={styles.pendingPath}>{presentation.detail}</span>
      </div>
      <time
        className={styles.pendingTime}
        dateTime={task.updatedAt || task.createdAt}
      >
        {displayDate(task.updatedAt || task.createdAt)}
      </time>
      <div className={styles.pendingActions}>
        <span>{presentation.actionHint}</span>
        <div className={styles.pendingButtonGroup}>
          <button
            type="button"
            className={
              requiresConfirmation
                ? styles.reviewTaskButton
                : styles.openTaskButton
            }
            onClick={openTaskReview}
          >
            {requiresConfirmation ? "查看影响并确认" : "打开任务工作区"}
            <ChevronRight size={14} />
          </button>
          {presentation.deletionState === "active" ? (
            <button
              type="button"
              className={styles.cancelTaskButton}
              disabled={action !== "idle"}
              onClick={() => void cancelDeletion()}
            >
              <X size={14} />
              {action === "cancelling" ? "正在取消" : "取消删除"}
            </button>
          ) : null}
        </div>
        {actionError ? (
          <strong className={styles.pendingActionError} role="alert">
            {actionError}
          </strong>
        ) : null}
      </div>
    </article>
  );
}

type PendingTaskPresentation = {
  kind: string;
  title: string;
  statusLabel: string;
  statusTone: "success" | "warning" | "info" | "neutral";
  impact: string;
  detail: string;
  actionHint: string;
  target?: string;
  targetLabel?: string;
  destructive: boolean;
  deletionState?: "active" | "expired";
};

function pendingTaskPresentation(
  task: MediaTaskSummary,
  nowMs = Date.now(),
): PendingTaskPresentation {
  const receipt = task.confirmationReceipt;
  if (
    task.capabilityId === "universal_deletion" &&
    task.variantId === "confirm" &&
    receipt?.kind === "deletion_preview"
  ) {
    const expiresAt = Date.parse(receipt.expiresAt);
    const expired = !Number.isFinite(expiresAt) || expiresAt <= nowMs;
    return {
      kind: receipt.kind,
      title: "删除素材资产",
      statusLabel: expired ? "预览已过期" : "等待确认",
      statusTone: "warning",
      impact: `${receipt.targetCount} 个删除目标，涉及 ${receipt.entityCount} 项数据`,
      detail: expired
        ? "上一次影响预览已失效，删除前需要重新检查当前数据状态。"
        : `预览有效至 ${displayDate(receipt.expiresAt)} · 剩余 ${formatRemainingTime(receipt.expiresAt, nowMs)}`,
      actionHint: expired
        ? "数据可能已经变化，请重新检查当前影响。"
        : "确认删除前请核对最新影响范围。",
      target: receipt.targetIds.join("、"),
      targetLabel: "删除目标",
      destructive: true,
      deletionState: expired ? "expired" : "active",
    };
  }
  if (
    task.capabilityId === "creator_profile_upsert" &&
    task.variantId === "confirm" &&
    receipt?.kind === "creator_profile_candidate"
  ) {
    return {
      kind: receipt.kind,
      title: "确认写入达人档案",
      statusLabel: taskStatusLabel(task.status),
      statusTone: taskTone(task.status),
      impact: "候选档案已生成，等待人工核对后入库",
      detail: `候选回执有效至 ${displayDate(receipt.expiresAt)}。`,
      actionHint: "请在任务工作区核对候选档案。",
      target: receipt.runId,
      targetLabel: "候选运行",
      destructive: false,
    };
  }
  if (
    task.capabilityId === "track_creator_membership_query" &&
    task.variantId === "confirm" &&
    receipt?.kind === "track_creator_membership_preview"
  ) {
    return {
      kind: receipt.kind,
      title: "确认保存赛道关系",
      statusLabel: taskStatusLabel(task.status),
      statusTone: taskTone(task.status),
      impact: "关系预览已生成，等待人工核对后写入",
      detail: `关系预览有效至 ${displayDate(receipt.expiresAt)}。`,
      actionHint: "请在任务工作区核对关系预览。",
      target: [task.params.track_id, task.params.creator_profile_id]
        .filter(Boolean)
        .map(String)
        .join(" ↔ ") || undefined,
      targetLabel: "关系对象",
      destructive: false,
    };
  }
  return {
    kind: requiresConfirmationReceipt(task) ? "confirmation" : "manual",
    title: task.capabilityPath.at(-1) || "待处理任务",
    statusLabel: taskStatusLabel(task.status),
    statusTone: taskTone(task.status),
    impact: displayText(task.summary),
    detail: "完整输入、来源和结果请在任务工作区核对。",
    actionHint: "请在任务工作区查看完整上下文。",
    destructive: false,
  };
}

function formatRemainingTime(value: string, nowMs: number) {
  const remainingSeconds = Math.max(
    0,
    Math.floor((Date.parse(value) - nowMs) / 1_000),
  );
  const minutes = Math.floor(remainingSeconds / 60);
  const seconds = remainingSeconds % 60;
  return `${minutes} 分 ${String(seconds).padStart(2, "0")} 秒`;
}

function requiresConfirmationReceipt(task: MediaTaskSummary) {
  return task.status === "awaiting_confirmation";
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

function isPendingTask(task: MediaTaskSummary, nowMs = Date.now()) {
  if (
    task.capabilityId === "universal_deletion" &&
    task.variantId === "confirm" &&
    task.status === "awaiting_confirmation"
  ) {
    const receipt = task.confirmationReceipt;
    const expiresAt = receipt?.kind === "deletion_preview"
      ? Date.parse(receipt.expiresAt)
      : Number.NaN;
    if (!Number.isFinite(expiresAt) || expiresAt <= nowMs) return false;
  }
  return !task.terminal && (
    task.status === "awaiting_confirmation" || task.status === "pending_manual"
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
