import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  LoaderCircle,
  LogIn,
  MessageSquareText,
  RotateCcw,
  StopCircle,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { CapabilityCatalog } from "../schemas/capabilityCatalogSchema";
import { confirmationReceiptSchema } from "../schemas/mediaWebTaskSchema";
import {
  cancelMediaTask,
  confirmMediaTask,
  createMediaTask,
  loadMediaCapabilities,
  loadMediaTask,
  loadMediaTasks,
  loadMediaWebSession,
  loginUrl,
  matchMediaCapabilities,
  MediaWebApiError,
  subscribeToMediaTask,
  uploadMediaFile,
  type MediaWebSession,
  type MediaWebTask,
} from "./mediaWebApi";
import { AiDecompositionPanel } from "./task-launch/AiDecompositionPanel";
import { CapabilitySelector } from "./task-launch/CapabilitySelector";
import { DynamicTaskForm } from "./task-launch/DynamicTaskForm";
import { TaskReview } from "./task-launch/TaskReview";
import {
  buildTaskRequest,
  emptyTaskDraft,
  newTaskIdempotencyKey,
  taskDraftReducer,
  type StructuredPrefill,
  type TaskDraft,
} from "./task-launch/taskDraft";
import { secureUuid } from "./secureUuid";
import { formatDateTime } from "./ui/datetime";
import { presentCapabilityText } from "./task-launch/fieldPresentation";
import {
  latestTaskFeed,
  shouldSubscribeToTask,
  taskSettlementPresentation,
} from "./recentTaskPresentation";
import { workspacePrefillAction } from "./task-launch/workspacePrefill";
import { getMaterialParsingPreview } from "./task-launch/materialParsing";
import {
  confirmationReceiptProblem,
  confirmationReceiptProblemMessage,
  confirmationReceiptState,
} from "./confirmationReceiptExpiry";

type RuntimeState =
  "checking" | "authenticated" | "unauthenticated" | "unavailable";
export type MediaViewMode = "normal" | "maintainer";

type MediaWebContextValue = {
  runtimeState: RuntimeState;
  viewMode: MediaViewMode;
  setViewMode: (mode: MediaViewMode) => void;
  session: MediaWebSession | null;
  catalog: CapabilityCatalog | null;
  tasks: MediaWebTask[];
  draft: TaskDraft;
  dispatch: React.Dispatch<Parameters<typeof taskDraftReducer>[1]>;
  drawerOpen: boolean;
  openWorkspace: (prefill?: StructuredPrefill) => void;
  closeWorkspace: () => void;
  refreshTask: (taskId: string) => Promise<void>;
  submitDraft: () => Promise<MediaWebTask>;
  cancel: (taskId: string) => Promise<void>;
  confirm: (taskId: string, decision: "approve" | "reject") => Promise<void>;
  regenerateDeletionPreview: (task: MediaWebTask) => Promise<MediaWebTask>;
  cancelDeletionIntent: (taskId: string) => Promise<void>;
  prepareDeletionIntent: (targetIds: string[]) => Promise<PreparedDeletionIntent>;
  executeDeletionIntent: (taskId: string) => Promise<void>;
};

export type PreparedDeletionIntent = {
  taskId: string;
  targetIds: string[];
  targetCount: number;
  entityCount: number;
  expiresAt: string;
};

const MediaWebContext = createContext<MediaWebContextValue | null>(null);

async function waitForTerminalTask(
  task: MediaWebTask,
  timeoutMessage = "删除影响仍在计算，请稍后再试。",
): Promise<MediaWebTask> {
  let current = task;
  const deadline = Date.now() + 60_000;
  while (!current.terminal && Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 750));
    current = await loadMediaTask(current.taskId);
  }
  if (!current.terminal) {
    throw new Error(timeoutMessage);
  }
  return current;
}

export function MediaWebProvider({ children }: { children: ReactNode }) {
  const [runtimeState, setRuntimeState] = useState<RuntimeState>("checking");
  const [viewMode, setViewMode] = useState<MediaViewMode>("normal");
  const [session, setSession] = useState<MediaWebSession | null>(null);
  const [catalog, setCatalog] = useState<CapabilityCatalog | null>(null);
  const [tasks, setTasks] = useState<MediaWebTask[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [draft, dispatch] = useReducer(taskDraftReducer, emptyTaskDraft());
  const pendingWorkspacePrefill = useRef<StructuredPrefill | null | undefined>(
    undefined,
  );

  const refreshTask = useCallback(async (taskId: string) => {
    try {
      const updated = await loadMediaTask(taskId);
      setTasks((current) => [
        updated,
        ...current.filter((item) => item.taskId !== taskId),
      ]);
    } catch (error) {
      if (error instanceof MediaWebApiError && error.status === 401) {
        setRuntimeState("unauthenticated");
        setSession(null);
      }
    }
  }, []);

  useEffect(() => {
    let active = true;
    loadMediaWebSession()
      .then((value) => {
        if (!active) return;
        setSession(value);
        setRuntimeState("authenticated");
        if (value.role === "admin") return;
        void loadMediaCapabilities()
          .then((nextCatalog) => {
            if (!active) return;
            setCatalog(nextCatalog);
            dispatch({ type: "catalogLoaded", catalog: nextCatalog });
            if (pendingWorkspacePrefill.current !== undefined) {
              dispatch(workspacePrefillAction(
                  nextCatalog,
                  pendingWorkspacePrefill.current ?? undefined,
              ));
              pendingWorkspacePrefill.current = undefined;
            }
          })
          .catch(() => null);
        void loadMediaTasks()
          .then((nextTasks) => {
            if (active) setTasks(nextTasks);
          })
          .catch(() => null);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setRuntimeState(
          error instanceof MediaWebApiError && error.status === 401
            ? "unauthenticated"
            : "unavailable",
        );
      });
    return () => {
      active = false;
    };
  }, []);

  const activeTaskIds = useMemo(
    () =>
      tasks
        .filter((task) => shouldSubscribeToTask(task))
        .map((task) => task.taskId)
        .sort()
        .join(","),
    [tasks],
  );
  useEffect(() => {
    if (!activeTaskIds) return;
    const close = activeTaskIds
      .split(",")
      .map((taskId) =>
        subscribeToMediaTask(taskId, () => void refreshTask(taskId)),
      );
    return () => close.forEach((dispose) => dispose());
  }, [activeTaskIds, refreshTask]);

  const openWorkspace = useCallback(
    (prefill?: StructuredPrefill) => {
      if (catalog) {
        dispatch(workspacePrefillAction(catalog, prefill));
      } else {
        pendingWorkspacePrefill.current = prefill ?? null;
      }
      // Task launch remains a contextual side workspace so the user keeps the
      // source page and its selected records in view while filling the form.
      setDrawerOpen(true);
    },
    [catalog],
  );

  const submitDraft = useCallback(async () => {
    if (!session || !catalog) throw new Error("请先登录。");
    const materialParsing = getMaterialParsingPreview({
      capabilityId: draft.capabilityId,
      params: draft.params,
      uploads: draft.uploads,
    });
    if (materialParsing.applicable && !materialParsing.canConfirm) {
      const message = `${materialParsing.failureReason} ${materialParsing.nextAction}`.trim();
      dispatch({ type: "submitFailure", message });
      throw new Error(message);
    }
    const receiptProblem = confirmationReceiptProblem(
      draft.capabilityId,
      draft.variantId,
      draft.confirmationReceipt,
    );
    if (receiptProblem) {
      const message = confirmationReceiptProblemMessage(receiptProblem);
      dispatch({ type: "submitFailure", message });
      throw new Error(message);
    }
    dispatch({ type: "submitStart" });
    try {
      const uploads = [];
      for (const file of draft.uploads)
        uploads.push(await uploadMediaFile(session, file));
      const request = buildTaskRequest(
        draft,
        uploads.map((item) => item.uploadId),
      );
      let task: MediaWebTask;
      try {
        task = await createMediaTask(session, request);
      } catch (error) {
        if (
          !(error instanceof MediaWebApiError) ||
          error.code !== "idempotency_conflict"
        ) {
          throw error;
        }
        const idempotencyKey = newTaskIdempotencyKey();
        dispatch({ type: "replaceIdempotencyKey", idempotencyKey });
        task = await createMediaTask(session, { ...request, idempotencyKey });
      }
      const deletionConfirmation =
        draft.capabilityId === "universal_deletion" &&
        draft.variantId === "confirm";
      if (
        deletionConfirmation &&
        task.status === "awaiting_confirmation" &&
        task.confirmation.state === "required"
      ) {
        task = await confirmMediaTask(session, task.taskId, "approve");
      }
      setTasks((current) => [
        task,
        ...current.filter((item) => item.taskId !== task.taskId),
      ]);
      dispatch({ type: "submitted", taskId: task.taskId });
      setDrawerOpen(true);
      return task;
    } catch (error) {
      const message =
        error instanceof MediaWebApiError &&
        error.code === "idempotency_conflict"
          ? "提交状态已更新，请再试一次。"
          : error instanceof Error
            ? error.message
            : "任务提交失败。";
      dispatch({
        type: "submitFailure",
        message,
      });
      throw error;
    }
  }, [session, catalog, draft]);

  const cancel = useCallback(
    async (taskId: string) => {
      if (!session) return;
      const task = await cancelMediaTask(session, taskId);
      setTasks((current) => [
        task,
        ...current.filter((item) => item.taskId !== task.taskId),
      ]);
    },
    [session],
  );
  const confirm = useCallback(
    async (taskId: string, decision: "approve" | "reject") => {
      if (!session) return;
      const task = await confirmMediaTask(session, taskId, decision);
      setTasks((current) => [
        task,
        ...current.filter((item) => item.taskId !== task.taskId),
      ]);
    },
    [session],
  );
  const cancelDeletionIntent = useCallback(
    async (taskId: string) => {
      if (!session) throw new Error("当前会话不可用，无法取消删除。");
      const task = await cancelMediaTask(session, taskId);
      setTasks((current) => [
        task,
        ...current.filter((item) => item.taskId !== task.taskId),
      ]);
    },
    [session],
  );
  const createDeletionConfirmationTask = useCallback(
    async (targetIds: string[]) => {
      if (!session || !catalog) {
        throw new Error("当前会话或能力目录不可用，无法删除素材。");
      }
      const uniqueTargetIds = [...new Set(targetIds.map((value) => value.trim()).filter(Boolean))];
      if (!uniqueTargetIds.length) throw new Error("请选择要删除的素材。");
      const createDeletionTask = async (
        request: Parameters<typeof createMediaTask>[1],
      ) => {
        try {
          return await createMediaTask(session, request);
        } catch (error) {
          if (
            !(error instanceof MediaWebApiError) ||
            error.code !== "idempotency_conflict"
          ) {
            throw error;
          }
          const idempotencyKey = newTaskIdempotencyKey();
          return createMediaTask(session, { ...request, idempotencyKey });
        }
      };

      let preview = await createDeletionTask({
        schemaVersion: "3",
        capabilityId: "universal_deletion",
        variantId: "preview",
        params: { id: uniqueTargetIds.join("、") },
        uploadIds: [],
        idempotencyKey: newTaskIdempotencyKey(),
        catalogVersion: catalog.catalogVersion,
        initiation: "manual",
        confirmationReceipt: null,
      });
      setTasks((current) => [
        preview,
        ...current.filter((item) => item.taskId !== preview.taskId),
      ]);
      preview = await waitForTerminalTask(preview);
      setTasks((current) => [
        preview,
        ...current.filter((item) => item.taskId !== preview.taskId),
      ]);

      const parsedNewReceipt = confirmationReceiptSchema.safeParse(
        preview.result?.receipt,
      );
      const newReceipt = parsedNewReceipt.success
        ? parsedNewReceipt.data
        : null;
      if (
        !preview.result?.ok ||
        newReceipt?.kind !== "deletion_preview" ||
        confirmationReceiptState(newReceipt) !== "active"
      ) {
        throw new Error("新的删除影响预览未能生成，请稍后重试。");
      }

      const confirmation = await createDeletionTask({
        schemaVersion: "3",
        capabilityId: "universal_deletion",
        variantId: "confirm",
        params: {
          id: newReceipt.targetIds.join("、"),
          action: "确认删除",
        },
        uploadIds: [],
        idempotencyKey: newTaskIdempotencyKey(),
        catalogVersion: catalog.catalogVersion,
        initiation: "manual",
        confirmationReceipt: newReceipt,
      });
      setTasks((current) => [
        confirmation,
        ...current.filter((item) => item.taskId !== confirmation.taskId),
      ]);
      return confirmation;
    },
    [session, catalog],
  );
  const prepareDeletionIntent = useCallback(
    async (targetIds: string[]): Promise<PreparedDeletionIntent> => {
      const confirmation = await createDeletionConfirmationTask(targetIds);
      const parsedReceipt = confirmationReceiptSchema.safeParse(
        confirmation.confirmationReceipt,
      );
      const receipt = parsedReceipt.success ? parsedReceipt.data : null;
      if (receipt?.kind !== "deletion_preview") {
        throw new Error("删除影响无法读取，请重新发起删除。");
      }
      return {
        taskId: confirmation.taskId,
        targetIds: [...receipt.targetIds],
        targetCount: receipt.targetCount,
        entityCount: receipt.entityCount,
        expiresAt: receipt.expiresAt,
      };
    },
    [createDeletionConfirmationTask],
  );
  const executeDeletionIntent = useCallback(
    async (taskId: string) => {
      if (!session) throw new Error("当前会话不可用，无法删除素材。");
      let task = await confirmMediaTask(session, taskId, "approve");
      setTasks((current) => [
        task,
        ...current.filter((item) => item.taskId !== task.taskId),
      ]);
      task = await waitForTerminalTask(task, "删除仍在执行，请稍后再试。");
      setTasks((current) => [
        task,
        ...current.filter((item) => item.taskId !== task.taskId),
      ]);
      if (task.status !== "succeeded" || task.result?.ok !== true) {
        throw new Error("删除没有完成，素材仍然保留。");
      }
    },
    [session],
  );
  const regenerateDeletionPreview = useCallback(
    async (task: MediaWebTask) => {
      if (!session) throw new Error("当前会话不可用，无法重新检查删除影响。");
      const parsedReceipt = confirmationReceiptSchema.safeParse(
        task.confirmationReceipt,
      );
      const receipt = parsedReceipt.success ? parsedReceipt.data : null;
      if (receipt?.kind !== "deletion_preview") {
        throw new Error("删除目标无法读取，请重新发起删除请求。");
      }
      const rejected = await confirmMediaTask(session, task.taskId, "reject");
      setTasks((current) => [
        rejected,
        ...current.filter((item) => item.taskId !== rejected.taskId),
      ]);
      return createDeletionConfirmationTask(receipt.targetIds);
    },
    [session, createDeletionConfirmationTask],
  );

  const value = useMemo<MediaWebContextValue>(
    () => ({
      runtimeState,
      viewMode,
      setViewMode,
      session,
      catalog,
      tasks,
      draft,
      dispatch,
      drawerOpen,
      openWorkspace,
      closeWorkspace: () => setDrawerOpen(false),
      refreshTask,
      submitDraft,
      cancel,
      confirm,
      regenerateDeletionPreview,
      cancelDeletionIntent,
      prepareDeletionIntent,
      executeDeletionIntent,
    }),
    [
      runtimeState,
      viewMode,
      session,
      catalog,
      tasks,
      draft,
      drawerOpen,
      openWorkspace,
      refreshTask,
      submitDraft,
      cancel,
      confirm,
      regenerateDeletionPreview,
      cancelDeletionIntent,
      prepareDeletionIntent,
      executeDeletionIntent,
    ],
  );
  return (
    <MediaWebContext.Provider value={value}>
      {children}
      <TaskWorkspaceDrawer />
    </MediaWebContext.Provider>
  );
}

export function useMediaWeb() {
  const value = useContext(MediaWebContext);
  if (!value)
    throw new Error("useMediaWeb must be used inside MediaWebProvider");
  return value;
}

export function MediaCommandPanel({ inline = false }: { inline?: boolean }) {
  const {
    runtimeState,
    session,
    catalog,
    tasks,
    draft,
    dispatch,
    submitDraft,
    openWorkspace,
  } = useMediaWeb();
  const requestRef = useRef<AbortController | null>(null);
  useEffect(() => () => requestRef.current?.abort(), []);

  if (runtimeState === "checking")
    return (
      <div className="command-gate" aria-busy="true">
        <LoaderCircle className="spin" size={20} />
        <span>正在确认执行权限</span>
      </div>
    );
  if (runtimeState === "unauthenticated")
    return (
      <div
        className={`command-panel command-panel-locked ${inline ? "is-inline" : ""}`}
      >
        <div className="command-panel-heading">
          <div>
            <MessageSquareText size={18} />
            <span>
              <strong>发起任务</strong>
              <small>登录后使用 AI 拆解与动态表单</small>
            </span>
          </div>
        </div>
        <div className="locked-command-note">
          <AlertCircle size={15} />
          <span>公开数据可浏览；发起任务需要认证。</span>
        </div>
        <a className="primary-button" href={loginUrl()}>
          <LogIn size={16} />
          登录并发起
        </a>
      </div>
    );
  if (runtimeState === "unavailable" || !session || !catalog)
    return (
      <div className="command-gate is-warning">
        <AlertCircle size={20} />
        <div>
          <strong>执行入口暂未连接</strong>
          <span>能力目录恢复后可在此提交。</span>
        </div>
      </div>
    );

  const authenticatedSession = session;
  const selected = catalog.capabilities.find(
    (item) => item.capabilityId === draft.capabilityId,
  );
  const recommendedId =
    draft.matchResult?.pathStatus === "matched"
      ? draft.matchResult.steps[0]?.capabilityId
      : undefined;
  const submittedTask = draft.submittedTaskId
    ? (tasks.find((task) => task.taskId === draft.submittedTaskId) ?? null)
    : null;
  const submittedDeletion =
    draft.capabilityId === "universal_deletion" &&
    draft.variantId === "confirm";

  async function decompose() {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const requestId = secureUuid();
    dispatch({ type: "decomposeStart", requestId });
    try {
      const response = await matchMediaCapabilities(
        authenticatedSession,
        {
          query: draft.query.trim(),
          currentBot: "media",
          catalogVersion: catalog!.catalogVersion,
          idempotencyKey: requestId,
        },
        controller.signal,
      );
      dispatch({
        type: "decomposeSuccess",
        requestId,
        response,
        catalog: catalog!,
      });
    } catch (error) {
      if (!controller.signal.aborted)
        dispatch({
          type: "decomposeFailure",
          requestId,
          message:
            error instanceof Error ? error.message : "AI 拆解暂时不可用。",
        });
    }
  }

  function enterReview() {
    dispatch({ type: "review", catalog: catalog! });
    window.setTimeout(
      () =>
        document
          .querySelector<HTMLElement>(
            ".has-error input, .has-error textarea, .has-error select",
          )
          ?.focus(),
      0,
    );
  }

  if (draft.phase === "review" || draft.phase === "submitting")
    return (
      <div
        className={`command-panel task-launch-panel ${inline ? "is-inline" : ""}`}
      >
        <TaskReview
          draft={draft}
          capability={selected!}
          onEdit={() => dispatch({ type: "edit" })}
          onSubmit={() => void submitDraft().catch(() => undefined)}
        />
      </div>
    );
  if (draft.phase === "submitted" && submittedDeletion) {
    const deletionSucceeded =
      submittedTask?.terminal === true &&
      submittedTask.status === "succeeded" &&
      submittedTask.result?.ok === true;
    const deletionFinished = submittedTask?.terminal === true;
    const deletionErrorText =
      typeof submittedTask?.error?.message === "string"
        ? submittedTask.error.message
        : "";
    const deletionMessage = deletionSucceeded
      ? submittedTask.result?.reply || "目标及其关联数据已删除。"
      : deletionFinished
        ? deletionErrorText ||
          submittedTask?.result?.reply ||
          "删除未完成，请查看任务结果后重试。"
        : submittedTask
          ? `${statusText(submittedTask.status)} · ${submittedTask.progress}%`
          : "正在等待删除任务状态。";
    return (
      <div
        className={`command-panel task-launch-panel ${inline ? "is-inline" : ""}`}
      >
        <div
          className={`task-submit-success ${deletionFinished && !deletionSucceeded ? "is-error" : ""}`}
          role="status"
          aria-live="polite"
        >
          {deletionSucceeded ? (
            <CheckCircle2 size={24} />
          ) : deletionFinished ? (
            <AlertCircle size={24} />
          ) : (
            <LoaderCircle className="spin" size={24} />
          )}
          <strong>
            {deletionSucceeded
              ? "删除已完成"
              : deletionFinished
                ? "删除未完成"
                : "任务删除中"}
          </strong>
          <span>{deletionMessage}</span>
          {deletionFinished ? (
            <button
              type="button"
              onClick={() =>
                dispatch({
                  type: "clear",
                  catalogVersion: catalog.catalogVersion,
                })
              }
            >
              返回任务列表
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (draft.phase === "submitted")
    return (
      <div
        className={`command-panel task-launch-panel ${inline ? "is-inline" : ""}`}
      >
        <div className="task-submit-success">
          <CheckCircle2 size={24} />
          <strong>任务已提交</strong>
          <span>可关闭当前页面，任务将在后台持续执行。</span>
          <button
            type="button"
            onClick={() =>
              dispatch({
                type: "clear",
                catalogVersion: catalog.catalogVersion,
              })
            }
          >
            继续发起
          </button>
        </div>
      </div>
    );

  return (
    <div
      className={`command-panel task-launch-panel ${inline ? "is-inline" : ""}`}
    >
      <div className="command-panel-heading">
        <div>
          <MessageSquareText size={18} />
          <span>
            <strong>发起任务</strong>
            <small>AI 与手动模式共用同一份能力配置</small>
          </span>
        </div>
        {tasks[0] && inline ? (
          <button
            type="button"
            className="quiet-button"
            onClick={() => openWorkspace()}
          >
            {tasks[0].terminal ? "查看最近结果" : "查看进行中任务"}
            <ChevronRight size={15} />
          </button>
        ) : null}
      </div>
      <AiDecompositionPanel
        draft={draft}
        capabilities={catalog.capabilities}
        onQuery={(query) => dispatch({ type: "setQuery", query })}
        onDecompose={() => void decompose()}
        onClear={() => {
          requestRef.current?.abort();
          dispatch({ type: "clear", catalogVersion: catalog.catalogVersion });
        }}
        onCandidate={(capability, variantId) =>
          dispatch({ type: "chooseCandidate", capability, variantId })
        }
      />
      <CapabilitySelector
        capabilities={catalog.capabilities}
        selectedId={draft.capabilityId}
        aiRecommendedId={recommendedId}
        tasks={tasks}
        onSelect={(capability) =>
          dispatch({ type: "selectCapability", capability })
        }
      />
      {selected ? (
        <DynamicTaskForm
          capability={selected}
          draft={draft}
          onVariant={(variantId) =>
            dispatch({
              type: "selectCapability",
              capability: selected,
              variantId,
            })
          }
          onField={(key, value) =>
            dispatch({ type: "updateField", key, value })
          }
          onUploads={(files) => dispatch({ type: "setUploads", files })}
        />
      ) : null}
      <div className="task-launch-footer">
        <span>
          {selected
            ? `当前任务：${selected.hierarchy.pathNames.map(presentCapabilityText).join(" / ")}`
            : "请选择能力后填写任务信息。"}
        </span>
        <button
          type="button"
          className="primary-button"
          disabled={!selected}
          onClick={enterReview}
        >
          检查并确认
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}

export function TaskWorkspacePage() {
  const navigate = useNavigate();
  return (
    <main className="fidelity-page task-workspace-page">
      <header className="task-workspace-heading">
        <div className="page-heading">
          <h1>任务工作区</h1>
          <p>根据当前能力填写必填信息，确认后提交任务。</p>
        </div>
        <button
          className="task-workspace-back"
          type="button"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft size={16} aria-hidden="true" />
          返回上一页
        </button>
      </header>
      <section className="task-workspace-surface" aria-label="任务工作区内容">
        <MediaCommandPanel inline />
      </section>
    </main>
  );
}

function TaskWorkspaceDrawer() {
  const {
    drawerOpen,
    closeWorkspace,
    runtimeState,
    tasks,
    draft,
    cancel,
    confirm,
  } = useMediaWeb();
  const [nowMs, setNowMs] = useState(() => Date.now());
  const visibleTasks = useMemo(
    () => latestTaskFeed(tasks, nowMs),
    [tasks, nowMs],
  );
  useEffect(() => {
    if (!drawerOpen) return;
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [drawerOpen]);
  if (!drawerOpen) return null;
  const deletionPreview =
    draft.capabilityId === "universal_deletion" &&
    draft.variantId === "preview";
  const deletionConfirm =
    draft.capabilityId === "universal_deletion" &&
    draft.variantId === "confirm";
  return (
    <>
      <button
        className="task-drawer-scrim"
        type="button"
        aria-label="关闭任务工作区"
        onClick={closeWorkspace}
      />
      <aside className="task-drawer" aria-label="Media 任务工作区">
        <header>
          <div>
            <MessageSquareText size={19} />
            <span>
              <strong>
                {deletionPreview
                  ? "删除预览"
                  : deletionConfirm
                    ? "确认删除"
                    : "任务工作区"}
              </strong>
              <small>
                {deletionPreview
                  ? "检查影响范围，不会直接删除"
                  : deletionConfirm
                    ? "核对目标后完成删除"
                    : "拆解、填写、确认与进度"}
              </small>
            </span>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭任务工作区"
            onClick={closeWorkspace}
          >
            <X size={19} />
          </button>
        </header>
        <div className="task-drawer-body">
          <MediaCommandPanel />
          {runtimeState === "authenticated" && draft.phase === "idle" ? (
            <section className="task-feed" aria-label="最近任务">
              <h2>
                最近任务 <span>{visibleTasks.length}</span>
              </h2>
              {visibleTasks.length ? (
                visibleTasks.map((task) => (
                  <TaskItem
                    key={task.taskId}
                    task={task}
                    nowMs={nowMs}
                    onCancel={cancel}
                    onConfirm={confirm}
                  />
                ))
              ) : (
                <div className="task-empty">
                  <CheckCircle2 size={20} />
                  <span>尚未提交网页任务</span>
                </div>
              )}
            </section>
          ) : null}
        </div>
      </aside>
    </>
  );
}

function TaskItem({
  task,
  nowMs,
  onCancel,
  onConfirm,
}: {
  task: MediaWebTask;
  nowMs: number;
  onCancel: (id: string) => Promise<void>;
  onConfirm: (id: string, decision: "approve" | "reject") => Promise<void>;
}) {
  const {
    openWorkspace,
    tasks,
    regenerateDeletionPreview,
    cancelDeletionIntent,
  } = useMediaWeb();
  const [deletionAction, setDeletionAction] = useState<
    "idle" | "regenerating" | "cancelling"
  >("idle");
  const [deletionActionError, setDeletionActionError] = useState("");
  const isDeletionPreview =
    task.capabilityId === "universal_deletion" && task.variantId === "preview";
  const taskResultSuccessful =
    task.result?.ok === true && taskSettlementPresentation(task).complete;
  const parsedResultReceipt = confirmationReceiptSchema.safeParse(task.result?.receipt);
  const actionableReceipt = parsedResultReceipt.success
    ? parsedResultReceipt.data
    : null;
  const parsedConfirmationReceipt = confirmationReceiptSchema.safeParse(
    task.confirmationReceipt,
  );
  const confirmationReceipt = parsedConfirmationReceipt.success
    ? parsedConfirmationReceipt.data
    : null;
  const confirmationRequiresReceipt =
    task.variantId === "confirm" &&
    [
      "universal_deletion",
      "creator_profile_upsert",
      "track_creator_membership_query",
    ].includes(task.capabilityId);
  const confirmationReceiptActive =
    !confirmationRequiresReceipt ||
    confirmationReceiptState(confirmationReceipt, nowMs) === "active";
  const deletionConfirmationReceipt =
    confirmationReceipt?.kind === "deletion_preview" ? confirmationReceipt : null;
  const deletionConfirmationExpired =
    deletionConfirmationReceipt !== null && !confirmationReceiptActive;
  const creatorConfirmationReceipt =
    confirmationReceipt?.kind === "creator_profile_candidate"
      ? confirmationReceipt
      : null;
  const trackConfirmationReceipt =
    confirmationReceipt?.kind === "track_creator_membership_preview"
      ? confirmationReceipt
      : null;
  const deletionReceipt =
    actionableReceipt?.kind === "deletion_preview" ? actionableReceipt : null;
  const receiptState = confirmationReceiptState(actionableReceipt, nowMs);
  const hasRelatedDeletionConfirmation = tasks.some((candidate) => {
    const parsed = confirmationReceiptSchema.safeParse(
      candidate.confirmationReceipt,
    );
    return (
      candidate.capabilityId === "universal_deletion" &&
      candidate.variantId === "confirm" &&
      parsed.success &&
      parsed.data?.kind === "deletion_preview" &&
      parsed.data.previewTaskId === task.taskId
    );
  });
  const deletionPreviewReady =
    isDeletionPreview &&
    task.status === "succeeded" &&
    task.result?.ok === true &&
    deletionReceipt !== null &&
    receiptState === "active" &&
    !hasRelatedDeletionConfirmation;
  const creatorCandidate =
    actionableReceipt?.kind === "creator_profile_candidate"
      ? actionableReceipt
      : null;
  const creatorCandidateReady =
    creatorCandidate !== null && receiptState === "active";
  const trackMembershipPreview =
    actionableReceipt?.kind === "track_creator_membership_preview"
      ? actionableReceipt
      : null;
  const trackMembershipPreviewReady =
    trackMembershipPreview !== null && receiptState === "active";
  const ids = task.params.id
    ? String(task.params.id)
        .split(/[、,，]/)
        .filter(Boolean)
    : [];
  async function regenerateDeletion() {
    setDeletionAction("regenerating");
    setDeletionActionError("");
    try {
      await regenerateDeletionPreview(task);
    } catch (error) {
      setDeletionActionError(
        error instanceof Error ? error.message : "删除影响重新检查失败。",
      );
    } finally {
      setDeletionAction("idle");
    }
  }
  async function cancelDeletion() {
    setDeletionAction("cancelling");
    setDeletionActionError("");
    try {
      await cancelDeletionIntent(task.taskId);
    } catch (error) {
      setDeletionActionError(
        error instanceof Error ? error.message : "取消删除失败。",
      );
    } finally {
      setDeletionAction("idle");
    }
  }
  const deletionPreviewStatus =
    isDeletionPreview && task.result?.ok && deletionReceipt
      ? receiptState === "active"
        ? "有效"
        : "已过期"
      : null;
  return (
    <article
      className={`task-item ${task.status === "failed" ? "is-failed" : ""}`}
      data-task-id={task.taskId}
      tabIndex={-1}
    >
      <header className="task-item-header">
        <div className="task-item-title">
          <strong>
            {isDeletionPreview
              ? "删除预览"
              : deletionConfirmationReceipt
                ? "删除素材资产"
                : task.capabilityPath.at(-1)}
          </strong>
          <span
            className={`task-status is-${
              deletionPreviewStatus
                ? receiptState === "active"
                  ? "active"
                  : "expired"
                : deletionConfirmationExpired
                  ? "expired"
                  : task.status
            }`}
          >
            {deletionPreviewStatus ??
              (deletionConfirmationExpired
                ? "预览已过期"
                : statusText(task.status))}
          </span>
        </div>
        <time>
          {formatDateTime(task.createdAt)}
        </time>
      </header>
      {isDeletionPreview && ids.length ? (
        <div className="task-target-row">
          <span>目标</span>
          <strong>{ids.join("、")}</strong>
        </div>
      ) : (
        <p className="task-summary">{task.summary}</p>
      )}
      {!task.terminal ? (
        <div className="task-progress" aria-label={`任务进度 ${task.progress}%`}>
          <span style={{ width: `${task.progress}%` }} />
        </div>
      ) : null}
      <TaskSettlementDetails task={task} />
      {deletionConfirmationReceipt ? (
        <div className="task-confirmation-context is-destructive">
          <div>
            <strong>
              {deletionConfirmationExpired ? "删除预览已过期" : "删除影响"}
            </strong>
            <span>
              {deletionConfirmationExpired
                ? "数据可能已经发生变化，需要重新计算删除影响。"
                : `${deletionConfirmationReceipt.targetCount} 个删除目标，涉及 ${deletionConfirmationReceipt.entityCount} 项数据`}
            </span>
          </div>
          <dl>
            <div>
              <dt>删除目标</dt>
              <dd>{deletionConfirmationReceipt.targetIds.join("、")}</dd>
            </div>
            <div>
              <dt>预览有效期</dt>
              <dd>
                {formatConfirmationExpiry(deletionConfirmationReceipt.expiresAt)}
                {confirmationReceiptActive
                  ? ` · 剩余 ${formatRemainingTime(deletionConfirmationReceipt.expiresAt, nowMs)}`
                  : " · 现已过期"}
              </dd>
            </div>
          </dl>
          <p>
            {confirmationReceiptActive
              ? "请核对目标和影响范围，确认后才会执行删除。"
              : "上一次影响预览已失效，删除前需要重新检查当前数据状态。"}
          </p>
        </div>
      ) : creatorConfirmationReceipt ? (
        <div className="task-confirmation-context">
          <div>
            <strong>达人档案候选确认</strong>
            <span>核对候选内容后再决定是否写入</span>
          </div>
          <dl>
            <div>
              <dt>候选运行</dt>
              <dd>{creatorConfirmationReceipt.runId}</dd>
            </div>
            <div>
              <dt>候选有效期</dt>
              <dd>{formatConfirmationExpiry(creatorConfirmationReceipt.expiresAt)}</dd>
            </div>
          </dl>
        </div>
      ) : trackConfirmationReceipt ? (
        <div className="task-confirmation-context">
          <div>
            <strong>赛道关系预览确认</strong>
            <span>核对关系字段后再决定是否写入</span>
          </div>
          <dl>
            <div>
              <dt>关系对象</dt>
              <dd>
                {[task.params.track_id, task.params.creator_profile_id]
                  .filter(Boolean)
                  .map(String)
                  .join(" ↔ ") || "任务参数中未提供可读对象"}
              </dd>
            </div>
            <div>
              <dt>预览有效期</dt>
              <dd>{formatConfirmationExpiry(trackConfirmationReceipt.expiresAt)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
      {task.confirmation?.state === "required" && deletionConfirmationExpired ? (
        <div className="task-expired-actions">
          <span>删除预览已过期，请重新检查或取消本次删除。</span>
          <div>
            <button
              className="task-refresh-action"
              type="button"
              disabled={deletionAction !== "idle"}
              onClick={() => void regenerateDeletion()}
            >
              <RotateCcw size={15} />
              {deletionAction === "regenerating"
                ? "正在重新检查"
                : "重新生成删除预览"}
            </button>
            <button
              className="task-cancel"
              type="button"
              disabled={deletionAction !== "idle"}
              onClick={() => void cancelDeletion()}
            >
              <StopCircle size={15} />
              {deletionAction === "cancelling" ? "正在取消" : "取消删除"}
            </button>
          </div>
          {deletionActionError ? (
            <strong role="alert">{deletionActionError}</strong>
          ) : null}
        </div>
      ) : task.confirmation?.state === "required" ? (
        <div className="task-confirm">
          <span>
            {confirmationReceiptActive
              ? deletionConfirmationReceipt
                ? "批准后将按上方预览执行删除"
                : "此任务需要确认后执行"
              : "确认回执已过期，请拒绝后重新生成"}
          </span>
          <button
            type="button"
            onClick={() => void onConfirm(task.taskId, "reject")}
          >
            {deletionConfirmationReceipt ? "取消删除" : "拒绝"}
          </button>
          <button
            type="button"
            className="approve"
            disabled={!confirmationReceiptActive}
            onClick={() => void onConfirm(task.taskId, "approve")}
          >
            {deletionConfirmationReceipt ? "确认删除" : "确认执行"}
          </button>
        </div>
      ) : null}
      {task.result && isDeletionPreview ? (
        <div
          className={`task-deletion-preview ${task.result.ok && deletionReceipt && receiptState === "active" ? "" : "is-warning"}`}
          role="status"
        >
          {task.result.ok && deletionReceipt && receiptState === "active" ? (
            <CheckCircle2 size={16} />
          ) : (
            <AlertCircle size={16} />
          )}
          <div>
            <strong>
              {task.result.ok
                ? deletionReceipt
                  ? receiptState === "active"
                    ? "影响范围已生成"
                    : "删除预览已过期"
                  : "历史预览已完成"
                : "预览未完成"}
            </strong>
            <span>
              {task.result.ok
                ? deletionReceipt
                  ? receiptState === "active"
                    ? `${deletionReceipt.targetCount} 个目标，涉及 ${deletionReceipt.entityCount} 项数据`
                    : "有效期已结束，请重新生成后再确认"
                  : "请重新读取影响范围后继续"
                : "请检查来源状态后重新读取"}
            </span>
          </div>
        </div>
      ) : task.result ? (
        <div
          className={`task-result ${taskResultSuccessful ? "is-success" : "is-warning"}`}
        >
          <p>{task.result.reply}</p>
          {task.result.links.map((link) => (
            <a key={link.url} href={link.url} target="_blank" rel="noreferrer">
              {link.label}
              <ChevronRight size={14} />
            </a>
          ))}
        </div>
      ) : null}
      {deletionPreviewReady && ids.length ? (
        <div className="task-item-actions">
          <button
            className="task-delete-action"
            type="button"
            onClick={() =>
              openWorkspace({
                capabilityId: "universal_deletion",
                variantId: "confirm",
                params: { id: ids.join("、"), action: "确认删除" },
                confirmationReceipt: deletionReceipt,
              })
            }
          >
            <ChevronRight size={15} />
            查看影响并确认
          </button>
        </div>
      ) : null}
      {creatorCandidate && !creatorCandidateReady ? (
        <div className="task-deletion-preview is-warning" role="status">
          <AlertCircle size={16} />
          <div>
            <strong>候选已过期</strong>
            <span>请重新生成候选后再确认入库</span>
          </div>
        </div>
      ) : null}
      {creatorCandidateReady ? (
        <button
          className="task-delete-action"
          type="button"
          onClick={() =>
            openWorkspace({
              capabilityId: "creator_profile_upsert",
              variantId: "confirm",
              params: { run_id: creatorCandidate.runId, action: "确认写入" },
              confirmationReceipt: creatorCandidate,
            })
          }
        >
          <CheckCircle2 size={15} />
          审核并确认入库
        </button>
      ) : null}
      {creatorCandidate && !creatorCandidateReady ? (
        <button
          className="task-refresh-action"
          type="button"
          onClick={() =>
            openWorkspace({
              capabilityId: task.capabilityId,
              variantId: task.variantId,
              params: task.params,
            })
          }
        >
          <RotateCcw size={15} />
          重新生成候选
        </button>
      ) : null}
      {trackMembershipPreview && !trackMembershipPreviewReady ? (
        <div className="task-deletion-preview is-warning" role="status">
          <AlertCircle size={16} />
          <div>
            <strong>关系预览已过期</strong>
            <span>请重新生成关系预览后再确认</span>
          </div>
        </div>
      ) : null}
      {trackMembershipPreviewReady ? (
        <button
          className="task-delete-action"
          type="button"
          onClick={() =>
            openWorkspace({
              capabilityId: "track_creator_membership_query",
              variantId: "confirm",
              params: {
                ...task.params,
                action: "关系确认",
                confirmation: "是",
              },
              confirmationReceipt: trackMembershipPreview,
            })
          }
        >
          <CheckCircle2 size={15} />
          审核并确认关系
        </button>
      ) : null}
      {trackMembershipPreview && !trackMembershipPreviewReady ? (
        <button
          className="task-refresh-action"
          type="button"
          onClick={() =>
            openWorkspace({
              capabilityId: task.capabilityId,
              variantId: task.variantId,
              params: task.params,
            })
          }
        >
          <RotateCcw size={15} />
          重新生成关系预览
        </button>
      ) : null}
      {!task.terminal && task.confirmation?.state !== "required" ? (
        <button
          className="task-cancel"
          type="button"
          onClick={() => void onCancel(task.taskId)}
        >
          <StopCircle size={15} />
          取消任务
        </button>
      ) : null}
    </article>
  );
}

export function TaskSettlementDetails({
  task,
  compact = false,
}: {
  task: MediaWebTask;
  compact?: boolean;
}) {
  const presentation = taskSettlementPresentation(task);
  return (
    <section
      className={`task-settlement ${compact ? "is-compact" : ""} ${presentation.complete ? "is-complete" : ""}`}
      aria-label="任务状态"
      data-task-settlement-stage={task.settlementStage}
    >
      <header>
        <strong>任务状态</strong>
        <span>{presentation.stageLabel}</span>
      </header>
      <dl>
        <div>
          <dt>关联账号</dt>
          <dd>
            {presentation.bindingSummary ?? "此任务不适用客户自有账号绑定"}
          </dd>
        </div>
        <div>
          <dt>处理进度</dt>
          <dd>{presentation.attemptSummary ?? "等待开始处理"}</dd>
        </div>
        {presentation.recoverySummary ? (
          <div>
            <dt>处理状态</dt>
            <dd>{presentation.recoverySummary}</dd>
          </div>
        ) : null}
        <div>
          <dt>同步状态</dt>
          <dd>
            {presentation.missingReadbackLabels.length
              ? `正在同步：${presentation.missingReadbackLabels.join("、")}`
              : presentation.complete
                ? "任务结果已确认"
                : "等待任务处理"}
          </dd>
        </div>
        <div>
          <dt>结果确认</dt>
          <dd>
            {presentation.receiptSummary ?? "尚未完成"}
          </dd>
        </div>
      </dl>
      {presentation.errorMessage ? (
        <p className="task-settlement-error" role="alert">
          {presentation.errorMessage}
          {task.error?.action ? ` ${task.error.action}` : ""}
        </p>
      ) : null}
    </section>
  );
}

function formatConfirmationExpiry(value: string) {
  return formatDateTime(value, { empty: "有效期无法读取", invalid: "有效期无法读取" });
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

export function statusText(status: string): string {
  return (
    (
      {
        queued: "排队中",
        validating: "校验中",
        retrieving: "检索来源",
        generating: "生成中",
        persisting: "写入中",
        rendering: "渲染中",
        awaiting_confirmation: "等待确认",
        succeeded: "已完成",
        pending_manual: "待人工处理",
        failed: "失败",
        cancelled: "已取消",
      } as Record<string, string>
    )[status] ?? "状态更新中"
  );
}
