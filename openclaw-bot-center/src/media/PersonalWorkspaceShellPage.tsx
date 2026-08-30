import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Cloud,
  Eye,
  FileText,
  FolderOpen,
  LoaderCircle,
  LockKeyhole,
  LogIn,
  MessageSquareText,
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
import { loginUrl } from "./mediaWebApi";
import { useMediaWeb } from "./MediaWebWorkspace";
import CanonicalDocumentRenderer from "./pages/ordinary/CanonicalDocumentRenderer";
import { projectStageDisplayLabel, projectStatusDisplayLabel } from "./ui/displayLabels";
import { formatDateOnly } from "./ui/datetime";

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
    return <PersonalPageState status="loading" message="正在确认个人工作区" />;
  }
  if (runtimeState === "unauthenticated" || !session) {
    return <PersonalPageState status="unauthorized" message="当前会话无权访问个人云端成果。" />;
  }
  if (runtimeState === "unavailable") {
    return <PersonalPageState status="error" message="身份服务暂时不可用，个人成果不会使用默认数据。" onRefresh={refresh} />;
  }
  if (!personalSession) {
    return <PersonalPageState status="unauthorized" message="当前服务端会话不是个人工作区。" />;
  }

  return (
    <main className="personal-workspace-page" data-workspace-mode="personal_web">
      <header className="page-heading personal-page-heading">
        <div>
          <span className="eyebrow">个人工作区</span>
          <h1>{artifactId ? "云端成果预览" : "云端成果"}</h1>
          <p>个人成果只从服务端解析的云端内部成果读取，第一阶段不开放内容生产或组织资源操作。</p>
        </div>
        <div className="personal-page-actions">
          <span className="page-heading-status"><ShieldCheck size={16} />服务端已解析</span>
          <button
            className="topbar-command personal-task-status-command"
            type="button"
            aria-haspopup="dialog"
            aria-expanded={taskStatusOpen}
            onClick={() => setTaskStatusOpen(true)}
          >
            <MessageSquareText size={15} aria-hidden="true" />
            <span>查看任务状态</span>
          </button>
          <button className="quiet-button personal-refresh-button" type="button" onClick={refresh} disabled={projects.status === "loading"}>
            <RefreshCw size={15} aria-hidden="true" />刷新
          </button>
        </div>
      </header>

      {artifactId ? (
        <PersonalPreviewState artifactId={artifactId} state={preview} onRefresh={refresh} />
      ) : (
        <section className="personal-workspace-grid" aria-label="个人云端成果入口">
          <section className="section-panel personal-project-panel" aria-labelledby="personal-projects-title">
            <div className="section-heading">
              <div><FolderOpen size={17} aria-hidden="true" /><h2 id="personal-projects-title">我的云端成果</h2></div>
              <span>{projects.status === "ready" ? projects.data.length : 0}</span>
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

          <section className="section-panel personal-artifact-panel" aria-labelledby="personal-artifacts-title">
            <div className="section-heading">
              <div><Cloud size={17} aria-hidden="true" /><h2 id="personal-artifacts-title">云端交付与预览</h2></div>
              <span>{artifacts.status === "ready" ? artifacts.data.length : 0}</span>
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
                    <Link className="personal-preview-link" to={`/workspace/preview/${artifact.publicArtifactId}`}>
                      <Eye size={15} aria-hidden="true" />查看云端预览
                    </Link>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
        </section>
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
      <section className="section-panel personal-preview-panel" aria-label="云端成果预览">
        <header className="personal-preview-header">
          <div><span className="eyebrow">云端只读预览</span><h2>{state.data.data.artifact.artifactKind || "个人成果"}</h2></div>
          <Link className="quiet-button personal-back-link" to="/workspace"><ArrowLeft size={15} aria-hidden="true" />返回成果列表</Link>
        </header>
        {blocks.length ? <CanonicalDocumentRenderer blocks={blocks} /> : <PersonalPageState status="empty" message="当前修订没有可展示的正文。" />}
        <small className="personal-preview-id">成果标识：{artifactId}</small>
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
  const isMissingEntitlement = status === "missingEntitlement";
  const isError = status === "error" || status === "notFound";
  return (
    <div className={`personal-state is-${status}`} role="status" aria-busy={isLoading}>
      {isLoading ? <LoaderCircle className="spin" size={22} aria-hidden="true" /> : isUnauthorized ? <LockKeyhole size={22} aria-hidden="true" /> : isMissingEntitlement ? <ShieldCheck size={22} aria-hidden="true" /> : isError ? <AlertCircle size={22} aria-hidden="true" /> : <CheckCircle2 size={22} aria-hidden="true" />}
      <div><strong>{stateTitle(status)}</strong><span>{message || "个人云端成果暂时为空。"}</span></div>
      {isUnauthorized ? <a className="primary-button" href={loginUrl()}><LogIn size={15} aria-hidden="true" />重新登录</a> : onRefresh && !isLoading ? <button className="quiet-button" type="button" onClick={onRefresh}><RefreshCw size={15} aria-hidden="true" />重新读取</button> : null}
    </div>
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

function mapRequestError<T>(error: unknown, fallback: string): LoadState<T> {
  if (error instanceof BusinessOperationError) {
    if (error.status === 401) return { status: "unauthorized", message: "当前会话已失效，请重新登录。" };
    if (error.status === 403) return { status: "missingEntitlement", message: "当前账户尚未开通个人云端成果访问权限。" };
    if (error.status === 404) return { status: "notFound", message: "成果不存在，或已不再对当前账户可见。" };
  }
  if (error instanceof DOMException && error.name === "AbortError") return { status: "idle" };
  return { status: "error", message: fallback };
}

function formatDate(value: string): string {
  return formatDateOnly(value, { empty: "时间未记录", invalid: "时间未记录" });
}
