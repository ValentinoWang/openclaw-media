import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Cloud,
  Eye,
  FileText,
  FolderOpen,
  LogIn,
  MessageSquareText,
  PenLine,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import type { DocumentBlock } from "./documentWorkflow";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "./generatedBusinessPagesContract";
import { isMissingEntitlementError, isNotFoundError, isUnauthorizedError } from "./businessErrorPresentation";
import { loginUrl } from "./mediaWebApi";
import { useMediaWeb } from "./MediaWebWorkspace";
import CanonicalDocumentRenderer from "./pages/ordinary/CanonicalDocumentRenderer";
import { projectStageDisplayLabel, projectStatusDisplayLabel } from "./ui/displayLabels";
import { formatDateOnly } from "./ui/datetime";
// artifactKind 和「产物列表」里的 artifactType 是同一套后端枚举（decision_brief /
// creation_document / publishing_package / review_report / project_summary，
// ordinaryDataLabels.ts 的 ARTIFACT_TYPE_LABELS 就是这张表，只是字段名在不同接口
// 形状里叫法不同）。复用这个已导出的翻译函数，不再新造一张重复的表——也不用去改
// OrganizationDocumentMirrorPage.tsx 里那个模块内部、没有导出的 humanArtifactKind
// （那个文件当前锁给另一个并行改动，且它的兜底文案「组织文档镜像」也不适合个人
// 工作区）。
import { artifactTypeDisplayLabel } from "./ui/ordinaryDataLabels";
import { Metric } from "./ui/Metric";
import { SurfaceState, type SurfaceStateKind } from "./ui/SurfaceState";

type PersonalProject = {
  publicProjectId: string;
  title: string;
  workspaceMode: "personal_web" | "organization_lark";
  stage: string;
  status: string;
  artifactCounts: Record<string, number>;
  updatedAt: string;
};

type PersonalProjectResponse = {
  items: PersonalProject[];
};

type PersonalArtifact = {
  publicArtifactId: string;
  publicProjectId: string;
  artifactType: string;
  displayName: string | null;
  bodyAuthority: "internal" | "lark";
  currentRevision: number;
  syncStatus: "not_applicable" | "pending" | "synced" | "conflict" | "failed";
  updatedAt: string;
  allowedActions: string[];
};

type PersonalArtifactResponse = {
  items: PersonalArtifact[];
};

type PersonalDocumentResponse = {
  data: {
    artifact: {
      workspaceMode: "personal_web" | "organization_lark";
      bodyAuthority: "internal" | "lark";
      artifactKind: string;
    };
    revision: {
      body: {
        blocks: DocumentBlock[];
      };
    };
  };
};

type LoadState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "empty" }
  | { status: "unauthorized"; message: string }
  | { status: "missingEntitlement"; message: string }
  | { status: "notFound"; message: string }
  | { status: "error"; message: string };

type LoadStatus = LoadState<unknown>["status"];

const EMPTY_STATE_MESSAGE = "个人云端成果会在服务端可见后显示。";

export default function PersonalWorkspaceShellPage() {
  const { runtimeState, session } = useMediaWeb();
  const { artifactId } = useParams<{ artifactId?: string }>();
  const [projects, setProjects] = useState<LoadState<PersonalProject[]>>({ status: "idle" });
  const [artifacts, setArtifacts] = useState<LoadState<PersonalArtifact[]>>({ status: "idle" });
  const [preview, setPreview] = useState<LoadState<PersonalDocumentResponse>>({ status: "idle" });
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [taskStatusOpen, setTaskStatusOpen] = useState(false);
  const personalSession = session?.workspaceMode === "personal_web" && session.bodyAuthority === "internal";
  const refresh = useCallback(() => setRefreshToken((current) => current + 1), []);

  useEffect(() => {
    if (!taskStatusOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTaskStatusOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [taskStatusOpen]);

  useEffect(() => {
    if (runtimeState !== "authenticated" || !personalSession) return;
    const controller = new AbortController();
    let active = true;
    setProjects({ status: "loading" });
    callBusinessOperation<PersonalProjectResponse>("listContentProjects", {
      query: { pageSize: 50 },
      signal: controller.signal,
    })
      .then((response) => {
        if (!active) return;
        const personalItems = response.items.filter((item) => item.workspaceMode === "personal_web");
        setProjects(personalItems.length ? { status: "ready", data: personalItems } : { status: "empty" });
        setSelectedProjectId((current) =>
          current && personalItems.some((item) => item.publicProjectId === current)
            ? current
            : personalItems[0]?.publicProjectId ?? null,
        );
      })
      .catch((error: unknown) => {
        if (active) setProjects(mapRequestError(error, "云端成果列表暂时不可读取。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [personalSession, refreshToken, runtimeState]);

  useEffect(() => {
    if (runtimeState !== "authenticated" || !personalSession || !selectedProjectId) {
      setArtifacts({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setArtifacts({ status: "loading" });
    callBusinessOperation<PersonalArtifactResponse>("listProjectArtifacts", {
      path: { publicProjectId: selectedProjectId },
      query: { pageSize: 50 },
      signal: controller.signal,
    })
      .then((response) => {
        if (!active) return;
        const personalItems = response.items.filter((item) => item.bodyAuthority === "internal");
        setArtifacts(personalItems.length ? { status: "ready", data: personalItems } : { status: "empty" });
      })
      .catch((error: unknown) => {
        if (active) setArtifacts(mapRequestError(error, "云端成果暂时不可读取。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [personalSession, refreshToken, runtimeState, selectedProjectId]);

  useEffect(() => {
    if (!artifactId) {
      setPreview({ status: "idle" });
      return;
    }
    if (runtimeState !== "authenticated" || !personalSession) return;
    const controller = new AbortController();
    let active = true;
    setPreview({ status: "loading" });
    callBusinessOperation<PersonalDocumentResponse>("getDocumentBody", {
      path: { publicArtifactId: artifactId },
      signal: controller.signal,
    })
      .then((response) => {
        if (!active) return;
        const authority = response.data?.artifact;
        const blocks = response.data?.revision?.body?.blocks;
        if (
          authority?.workspaceMode !== "personal_web" ||
          authority.bodyAuthority !== "internal" ||
          !Array.isArray(blocks)
        ) {
          setPreview({ status: "notFound", message: "这份成果不属于当前个人云端工作区。" });
          return;
        }
        setPreview({ status: "ready", data: response });
      })
      .catch((error: unknown) => {
        if (active) setPreview(mapRequestError(error, "云端预览暂时不可读取。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [artifactId, personalSession, refreshToken, runtimeState]);

  if (runtimeState === "checking") {
    return <PersonalShellState><PersonalPageState status="loading" message="正在确认个人工作区" /></PersonalShellState>;
  }
  if (runtimeState === "unauthenticated" || !session) {
    return <PersonalShellState><PersonalPageState status="unauthorized" message="当前会话无权访问个人云端成果。" /></PersonalShellState>;
  }
  if (runtimeState === "unavailable") {
    return <PersonalShellState><PersonalPageState status="error" message="身份服务暂时不可用，个人成果不会使用默认数据。" onRefresh={refresh} /></PersonalShellState>;
  }
  if (!personalSession) {
    return <PersonalShellState><PersonalPageState status="unauthorized" message="当前服务端会话不是个人工作区。" /></PersonalShellState>;
  }

  return (
    <main className="personal-workspace-page" data-workspace-mode="personal_web" data-page-ownership="personal" data-accent="studio">
      <header className="page-heading personal-page-heading mg-hero" data-page-prelude>
        <div>
          <span className="eyebrow mg-eyebrow">个人工作区</span>
          <h1>{artifactId ? "云端成果预览" : "云端成果"}</h1>
          <p className="mg-hero-lead">个人成果只从服务端解析的云端内部成果读取，第一阶段不开放内容生产或组织资源操作。</p>
        </div>
        <div className="personal-page-actions">
          <span className="page-heading-status mg-badge" data-tone="good"><ShieldCheck size={16} />服务端已解析</span>
          <button
            className="personal-task-status-command mg-btn mg-btn-soft"
            type="button"
            aria-haspopup="dialog"
            aria-expanded={taskStatusOpen}
            onClick={() => setTaskStatusOpen(true)}
          >
            <MessageSquareText size={15} aria-hidden="true" />
            <span>查看任务状态</span>
          </button>
          <button className="quiet-button personal-refresh-button mg-btn mg-btn-ghost" type="button" onClick={refresh} disabled={projects.status === "loading"}>
            <RefreshCw size={15} aria-hidden="true" />刷新
          </button>
        </div>
      </header>

      {artifactId ? (
        <PersonalPreviewState artifactId={artifactId} state={preview} onRefresh={refresh} />
      ) : (
        <>
          <section className="personal-workspace-metrics mg-metric-grid" aria-label="个人云端成果指标">
            <Metric
              variant="card"
              className="mg-metric personal-workspace-metric"
              tone="accent"
              icon={<FolderOpen size={18} aria-hidden="true" />}
              label="云端项目"
              value={projects.status === "ready" ? projects.data.length : "—"}
              detail={projects.status === "ready" ? "服务端已读取" : "等待服务端读取"}
            />
            <Metric
              variant="card"
              className="mg-metric personal-workspace-metric"
              tone="accent"
              icon={<Cloud size={18} aria-hidden="true" />}
              label="可预览成果"
              value={artifacts.status === "ready" ? artifacts.data.length : "—"}
              detail={artifacts.status === "ready" ? "当前项目范围" : "选择项目后读取"}
            />
          </section>
          <section className="personal-workspace-grid" aria-label="个人云端成果入口">
          <section className="section-panel personal-project-panel mg-panel" aria-labelledby="personal-projects-title">
            <div className="section-heading mg-panel-head">
              <div><FolderOpen size={17} aria-hidden="true" /><h2 id="personal-projects-title">我的云端成果</h2></div>
              <span className="mg-badge" data-tone="accent">{projects.status === "ready" ? projects.data.length : 0}</span>
            </div>
            <PersonalListState state={projects} emptyMessage={EMPTY_STATE_MESSAGE} onRefresh={refresh} />
            {projects.status === "ready" ? (
              <div className="personal-project-list" role="list" aria-label="个人云端项目">
                {projects.data.map((project) => (
                  <button
                    className={`personal-project-item ${project.publicProjectId === selectedProjectId ? "is-selected" : ""}`}
                    type="button"
                    role="listitem"
                    key={project.publicProjectId}
                    aria-pressed={project.publicProjectId === selectedProjectId}
                    onClick={() => setSelectedProjectId(project.publicProjectId)}
                  >
                    <span className="personal-project-copy"><strong>{project.title || "未命名项目"}</strong><span>{projectStageDisplayLabel(project.stage)} · {projectStatusDisplayLabel(project.status)}</span></span>
                    <time dateTime={project.updatedAt}>{formatDate(project.updatedAt)}</time>
                  </button>
                ))}
              </div>
            ) : null}
          </section>

          <section className="section-panel personal-artifact-panel mg-panel" aria-labelledby="personal-artifacts-title">
            <div className="section-heading mg-panel-head">
              <div><Cloud size={17} aria-hidden="true" /><h2 id="personal-artifacts-title">云端交付与预览</h2></div>
              <span className="mg-badge" data-tone="accent">{artifacts.status === "ready" ? artifacts.data.length : 0}</span>
            </div>
            {!selectedProjectId && projects.status === "ready" ? (
              <PersonalPageState status="empty" message="选择一个云端项目后查看成果。" />
            ) : (
              <PersonalListState state={artifacts} emptyMessage="该项目暂无可预览成果。" onRefresh={refresh} />
            )}
            {artifacts.status === "ready" ? (
              <div className="personal-artifact-list" role="list" aria-label="个人云端成果">
                {artifacts.data.map((artifact) => (
                  <article className="personal-artifact-item" role="listitem" key={artifact.publicArtifactId}>
                    <div className="personal-artifact-icon" aria-hidden="true"><FileText size={17} /></div>
                    <div className="personal-artifact-copy"><strong>{artifact.displayName?.trim() || "未命名成果"}</strong><span>修订 {artifact.currentRevision} · {formatDate(artifact.updatedAt)}</span></div>
                    {/* 正文编辑器一直都在（/workspace/edit/:artifactId），但此前界面上没有任何入口，
                        只能手敲地址。受控快照类成果由编辑器自己降级成只读，这里不需要再判一次。 */}
                    {/* .personal-artifact-item 在 700px 断点把 grid-template-columns 从三列
                        （34px minmax(0,1fr) auto）收成两列（34px minmax(0,1fr)），这个 actions
                        div 是第三个直接子元素、没有显式 grid-column，落到隐式新行的第一列
                        （只有 34px 宽）：两个按钮的文案顶不住 white-space:nowrap，被挤到负坐标，
                        又被 .personal-artifact-panel 的 overflow:hidden 在左边裁掉一截、滚不出来。
                        `grid-column: -2` 用负值线号取「最后一条显式列的起点」——三列时是第 3
                        条线（列 3，跟浏览器原来的自动放置结果一致，桌面宽度不受影响）、两列时
                        是第 2 条线（列 2，跟上面「作品」标题同一列，自动换到新的一行），两种列数
                        都落在正确的最后一列，不用按断点分别写值。 */}
                    <div className="personal-artifact-actions" style={{ gridColumn: "-2" }}>
                      <Link className="personal-preview-link mg-btn mg-btn-ghost" to={`/workspace/preview/${artifact.publicArtifactId}`}>
                        <Eye size={15} aria-hidden="true" />查看云端预览
                      </Link>
                      <Link className="personal-preview-link mg-btn mg-btn-ghost" to={`/workspace/edit/${artifact.publicArtifactId}`}>
                        <PenLine size={15} aria-hidden="true" />编辑正文
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
          </section>
        </>
      )}

      {taskStatusOpen ? <PersonalTaskStatusDrawer onClose={() => setTaskStatusOpen(false)} /> : null}
    </main>
  );
}

function PersonalTaskStatusDrawer({ onClose }: { onClose: () => void }) {
  return (
    <>
      <button className="task-drawer-scrim personal-task-status-scrim" type="button" aria-label="关闭任务状态" onClick={onClose} />
      <aside className="task-drawer personal-task-status-drawer" aria-label="Media 任务工作区">
        <header>
          <div>
            <MessageSquareText size={19} aria-hidden="true" />
            <span><strong>任务状态</strong><small>个人工作区只读状态</small></span>
          </div>
          <button type="button" className="icon-button" aria-label="关闭任务状态" onClick={onClose}><X size={19} /></button>
        </header>
        <div className="task-drawer-body personal-task-status-body">
          <section className="task-feed" aria-label="最近任务">
            <h2>最近任务 <span>0</span></h2>
            <div className="task-empty"><CheckCircle2 size={20} aria-hidden="true" /><span>尚未提交网页任务</span></div>
          </section>
        </div>
      </aside>
    </>
  );
}

function PersonalPreviewState({
  artifactId,
  state,
  onRefresh,
}: {
  artifactId: string;
  state: LoadState<PersonalDocumentResponse>;
  onRefresh: () => void;
}) {
  if (state.status === "ready") {
    const blocks = state.data.data.revision.body.blocks;
    return (
      <section className="section-panel personal-preview-panel mg-panel" aria-label="云端成果预览">
        <header className="personal-preview-header">
          {/* 之前是 artifact.artifactKind || "个人成果"：|| 只兜住了空字符串，兜不住
              「后端发来一个前端没登记的枚举值」——探针在 /workspace/preview/artifact_creation_camera
              上抓到过 <h2> 里直接渲染出机器可读的 "creation_document"。已登记的枚举值走翻译表，
              只有真正的空值才落到「个人成果」；未登记的非空值交给 artifactTypeDisplayLabel 自己的
              通用兜底（「其他产物」），不会再把原始枚举吐给用户。 */}
          <div><span className="eyebrow mg-eyebrow">云端只读预览</span><h2>{state.data.data.artifact.artifactKind ? artifactTypeDisplayLabel(state.data.data.artifact.artifactKind) : "个人成果"}</h2></div>
          <Link className="quiet-button personal-back-link mg-btn mg-btn-ghost" to="/workspace"><ArrowLeft size={15} aria-hidden="true" />返回成果列表</Link>
        </header>
        {blocks.length ? <CanonicalDocumentRenderer blocks={blocks} /> : <PersonalPageState status="empty" message="当前修订没有可展示的正文。" />}
        {/* 真实后端的标识符是几百字符、没有断点的串；.mg-id 是仓库里统一的单行省略号
            + 完整值放 title 的契约，承载它的每一层（section-panel/personal-preview-panel/
            mg-panel）已经有 min-width: 0，不用额外补。 */}
        <small className="personal-preview-id mg-id" title={artifactId}>成果标识：{artifactId}</small>
      </section>
    );
  }
  return <PersonalListState state={state} emptyMessage="当前修订没有可展示的正文。" onRefresh={onRefresh} />;
}

function PersonalListState<T>({
  state,
  emptyMessage,
  onRefresh,
}: {
  state: LoadState<T>;
  emptyMessage: string;
  onRefresh: () => void;
}) {
  if (state.status === "ready" || state.status === "idle") return null;
  if (state.status === "empty") return <PersonalPageState status="empty" message={emptyMessage} onRefresh={onRefresh} />;
  return <PersonalPageState status={state.status} message={"message" in state ? state.message : undefined} onRefresh={onRefresh} />;
}

function PersonalPageState({
  status,
  message,
  onRefresh,
}: {
  status: LoadStatus;
  message?: string;
  onRefresh?: () => void;
}) {
  const isLoading = status === "loading";
  const isUnauthorized = status === "unauthorized";
  const action = isUnauthorized ? (
    <a className="mg-state-action mg-btn mg-btn-primary" href={loginUrl()}>
      <LogIn size={15} aria-hidden="true" />重新登录
    </a>
  ) : onRefresh && !isLoading ? (
    <button className="mg-state-action mg-btn mg-btn-ghost" type="button" onClick={onRefresh}>
      <RefreshCw size={15} aria-hidden="true" />重新读取
    </button>
  ) : undefined;
  return <SurfaceState kind={stateKind(status)} title={stateTitle(status)} detail={message || "个人云端成果暂时为空。"} action={action} />;
}

function PersonalShellState({ children }: { children: ReactNode }) {
  return (
    <main className="personal-workspace-page" data-workspace-mode="personal_web" data-page-ownership="personal" data-accent="studio">
      <div data-page-prelude>{children}</div>
    </main>
  );
}

function stateTitle(status: LoadStatus): string {
  if (status === "loading") return "正在读取云端成果";
  if (status === "empty") return "暂无云端成果";
  if (status === "unauthorized") return "当前会话未获授权";
  if (status === "missingEntitlement") return "个人成果访问权限未开通";
  if (status === "notFound") return "成果暂不可见";
  if (status === "error") return "云端成果暂不可读取";
  return "等待云端成果";
}

function stateKind(status: LoadStatus): SurfaceStateKind {
  if (status === "loading") return "loading";
  if (status === "unauthorized") return "permission";
  if (status === "missingEntitlement") return "forbidden";
  if (status === "notFound") return "notFound";
  if (status === "empty" || status === "idle") return "empty";
  return "error";
}

function mapRequestError<T>(error: unknown, fallback: string): LoadState<T> {
  if (error instanceof BusinessOperationError) {
    if (isUnauthorizedError(error)) return { status: "unauthorized", message: "当前会话已失效，请重新登录。" };
    if (isMissingEntitlementError(error)) return { status: "missingEntitlement", message: "当前账户尚未开通个人云端成果访问权限。" };
    if (isNotFoundError(error)) return { status: "notFound", message: "成果不存在，或已不再对当前账户可见。" };
  }
  if (error instanceof DOMException && error.name === "AbortError") return { status: "idle" };
  return { status: "error", message: fallback };
}

function formatDate(value: string): string {
  return formatDateOnly(value, { empty: "时间未记录", invalid: "时间未记录" });
}
