import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  Archive,
  AudioLines,
  Box,
  CheckCircle2,
  FileText,
  Hash,
  LoaderCircle,
  LogIn,
  Monitor,
  RefreshCw,
  ShieldAlert,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useMediaWeb } from "../../MediaWebWorkspace";
import {
  archiveDeleteConfirmationRef,
  archiveDeleteIdempotencyKey,
  archiveDeletePlanIdempotencyKey,
  archiveReadbackIdempotencyKey,
  deleteArchive,
  loadArchiveDetail,
  loadArchiveList,
  loginUrl,
  planArchiveDelete,
  readbackArchive,
  type MediaWebApiError,
} from "../../mediaWebApi";
import type {
  ArchiveDeletePlanResponse,
  ArchiveRecord,
} from "../../generatedProductContract";
import { PageHeading } from "../../ui/ordinaryPagePrimitives";
import styles from "./ArchivesPage.module.css";
import { isCurrentW1Request } from "./w1RequestGuard";

type LoadState = "loading" | "ready" | "empty" | "error" | "permission";

const localMediaBoundaries = [
  { label: "Final", detail: "仅本地媒体", Icon: Box },
  { label: "Proxy", detail: "仅本地媒体", Icon: Monitor },
  { label: "WAV", detail: "仅本地媒体", Icon: AudioLines },
] as const;

function ArchivesPage() {
  const { runtimeState, session } = useMediaWeb();
  const [archives, setArchives] = useState<ArchiveRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<ArchiveRecord | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [plan, setPlan] = useState<ArchiveDeletePlanResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState("");
  const listGeneration = useRef(0);
  const listController = useRef<AbortController | null>(null);
  const detailGeneration = useRef(0);
  const detailController = useRef<AbortController | null>(null);
  const mutationGeneration = useRef(0);
  const mutationController = useRef<AbortController | null>(null);

  const invalidateMutation = useCallback((resetBusy = false) => {
    mutationController.current?.abort();
    mutationController.current = null;
    mutationGeneration.current += 1;
    if (resetBusy) setBusy(false);
  }, []);

  const selectArchive = useCallback(
    (archiveId: string) => {
      detailController.current?.abort();
      detailGeneration.current += 1;
      invalidateMutation(true);
      setSelectedId(archiveId);
      setDetail(null);
      setPlan(null);
      setConfirmed(false);
      setReceipt("");
    },
    [invalidateMutation],
  );

  const refresh = useCallback(async () => {
    if (!session || runtimeState !== "authenticated") return;
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    const generation = ++listGeneration.current;
    setState("loading");
    setError("");
    try {
      const response = await loadArchiveList(
        session,
        { limit: 100 },
        controller.signal,
      );
      if (
        !isCurrentW1Request(
          generation,
          listGeneration.current,
          controller.signal,
        )
      )
        return;
      const nextSelectedId = response.archives.some(
        (item) => item.archive_id === selectedId,
      )
        ? selectedId
        : response.archives[0]?.archive_id || "";
      if (nextSelectedId !== selectedId) {
        detailController.current?.abort();
        detailGeneration.current += 1;
        invalidateMutation(true);
        setDetail(null);
        setPlan(null);
        setConfirmed(false);
        setReceipt("");
      }
      setArchives(response.archives);
      setSelectedId(nextSelectedId);
      setState(response.archives.length ? "ready" : "empty");
    } catch (cause) {
      if (
        !isCurrentW1Request(
          generation,
          listGeneration.current,
          controller.signal,
        )
      )
        return;
      const failure = cause as Partial<MediaWebApiError>;
      setState(
        failure.status === 401 || failure.status === 403
          ? "permission"
          : "error",
      );
      setError("归档暂时无法读取。请点击“重试”重新读取。");
    }
  }, [invalidateMutation, runtimeState, selectedId, session]);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    detailController.current?.abort();
    const controller = new AbortController();
    detailController.current = controller;
    const generation = ++detailGeneration.current;
    setDetail(null);
    setPlan(null);
    setConfirmed(false);
    setReceipt("");
    if (!session || !selectedId) {
      return;
    }
    void loadArchiveDetail(session, selectedId, controller.signal)
      .then((response) => {
        if (
          isCurrentW1Request(
            generation,
            detailGeneration.current,
            controller.signal,
          )
        )
          setDetail(response.archive);
      })
      .catch(() => {
        if (
          isCurrentW1Request(
            generation,
            detailGeneration.current,
            controller.signal,
          )
        )
          setDetail(null);
      });
  }, [selectedId, session]);

  useEffect(
    () => () => {
      listGeneration.current += 1;
      detailGeneration.current += 1;
      invalidateMutation();
      listController.current?.abort();
      detailController.current?.abort();
    },
    [invalidateMutation, runtimeState, session],
  );

  const selected =
    detail || archives.find((item) => item.archive_id === selectedId) || null;
  async function requestDeletePlan() {
    if (!session || !selected) return;
    const archiveId = selected.archive_id;
    invalidateMutation(true);
    const controller = new AbortController();
    mutationController.current = controller;
    const generation = ++mutationGeneration.current;
    setBusy(true);
    setError("");
    setReceipt("");
    try {
      const nextPlan = await planArchiveDelete(
        session,
        archiveId,
        await archiveDeletePlanIdempotencyKey(archiveId),
        controller.signal,
      );
      if (
        isCurrentW1Request(
          generation,
          mutationGeneration.current,
          controller.signal,
        ) &&
        selectedId === archiveId
      ) {
        setPlan(nextPlan);
        setConfirmed(false);
      }
    } catch {
      if (
        isCurrentW1Request(
          generation,
          mutationGeneration.current,
          controller.signal,
        ) &&
        selectedId === archiveId
      )
        setError(
          "删除影响计划暂时无法读取。请重新尝试。",
        );
    } finally {
      if (
        isCurrentW1Request(
          generation,
          mutationGeneration.current,
          controller.signal,
        )
      )
        setBusy(false);
    }
  }
  async function confirmDelete() {
    if (!session || !selected || !plan || !confirmed) return;
    const archiveId = selected.archive_id;
    const deletePlan = plan;
    const expectedRevision = selected.revision;
    invalidateMutation(true);
    const controller = new AbortController();
    mutationController.current = controller;
    const generation = ++mutationGeneration.current;
    setBusy(true);
    setError("");
    try {
      const confirmationRef = await archiveDeleteConfirmationRef(
        archiveId,
        deletePlan.delete_plan_id,
      );
      const result = await deleteArchive(
        session,
        archiveId,
        {
          delete_plan_id: deletePlan.delete_plan_id,
          confirmation_ref: confirmationRef,
          expected_revision: expectedRevision,
        },
        await archiveDeleteIdempotencyKey(
          archiveId,
          deletePlan.delete_plan_id,
          expectedRevision,
        ),
        controller.signal,
      );
      const readback = await readbackArchive(
        session,
        archiveId,
        {
          readback_receipt_ref: result.delete_receipt.receipt_ref,
          observed_refs: result.delete_receipt.deleted_projection_refs,
        },
        await archiveReadbackIdempotencyKey(
          archiveId,
          result.delete_receipt.receipt_ref,
        ),
        controller.signal,
      );
      if (
        !readback.verified ||
        !readback.hard_deleted ||
        readback.archive !== null
      )
        throw new Error("删除读回未确认硬删除结果。");
      if (
        !isCurrentW1Request(
          generation,
          mutationGeneration.current,
          controller.signal,
        ) ||
        selectedId !== archiveId
      )
        return;
      setReceipt(result.delete_receipt.receipt_ref);
      setPlan(null);
      setConfirmed(false);
      await refresh();
    } catch {
      if (
        isCurrentW1Request(
          generation,
          mutationGeneration.current,
          controller.signal,
        ) &&
        selectedId === archiveId
      ) {
        setPlan(null);
        setConfirmed(false);
        setError("归档删除暂时无法完成。请重新尝试。");
      }
    } finally {
      if (
        isCurrentW1Request(
          generation,
          mutationGeneration.current,
          controller.signal,
        )
      )
        setBusy(false);
    }
  }

  if (runtimeState === "checking")
    return (
      <Status
        kind="loading"
        title="正在读取归档"
        detail="正在确认身份并读取真实归档记录。"
      />
    );
  if (runtimeState === "unauthenticated" || !session)
    return (
      <Status
        kind="permission"
        title="登录后查看归档"
        detail="页面不会在无权限状态下读取归档内容。"
      />
    );
  const records =
    state === "ready" ? (
      <div
        className={styles.tableViewport}
        tabIndex={0}
        aria-label="归档记录列表"
      >
        <table className={styles.table}>
          <thead>
            <tr>
              <th>归档记录</th>
              <th>来源运行</th>
              <th>云端字节</th>
              <th>状态</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {archives.map((archive) => (
              <tr
                key={archive.archive_id}
                className={
                  archive.archive_id === selectedId
                    ? styles.selectedRow
                    : undefined
                }
                onClick={() => {
                  selectArchive(archive.archive_id);
                }}
              >
                <td>
                  <button type="button" className={styles.rowButton}>
                    {archive.archive_id}
                  </button>
                </td>
                <td>{archive.run_id}</td>
                <td>{archive.cloud_bytes}</td>
                <td>{archiveStateLabel(archive.state)}</td>
                <td>{formatTime(archive.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ) : state === "loading" ? (
      <Status
        kind="loading"
        title="正在读取真实归档"
        detail="记录区等待服务端返回，不使用静态记录填充。"
      />
    ) : state === "permission" ? (
      <Status
        kind="permission"
        title="没有归档读取权限"
        detail={error || "当前账户不能读取归档。"}
      />
    ) : state === "error" ? (
      <Status
        kind="error"
        title="归档读取失败"
        detail={error}
        action={
          <button type="button" onClick={() => void refresh()}>
            <RefreshCw size={14} />
            重试
          </button>
        }
      />
    ) : (
      <Status
        kind="empty"
        title="暂无归档记录"
        detail="服务端没有返回归档；记录区保持真实空态。"
        compact
      />
    );

  return (
    <main className={`fidelity-page ${styles.page}`}>
      <div data-page-prelude>
        <PageHeading
          title="云端归档"
          description="查看用户明确选择后提交的轻量产物、描述符和验证收据。"
        />
      </div>
      <section
        className={styles.workspace}
        data-w1-state={state}
        data-page-layout="persistent-rail"
      >
        <div className={styles.mainColumn} data-page-primary>
          <section
            className={styles.recordsPanel}
            aria-labelledby="archive-records-title"
            data-page-terminal-surface="primary"
          >
            <PanelHeader
              icon={Archive}
              title="归档记录"
              detail="仅展示服务端返回的小产物和本地媒体描述符。"
            />
            {records}
          </section>
        </div>
        <aside
          className={styles.rail}
          tabIndex={0}
          aria-label="归档详情"
          data-page-inspector
        >
          <ArchiveDetail archive={selected} />
          <DeletionPanel
            archive={selected}
            plan={plan}
            confirmed={confirmed}
            onConfirm={setConfirmed}
            onPlan={() => void requestDeletePlan()}
            onDelete={() => void confirmDelete()}
            busy={busy}
            receipt={receipt}
            error={error}
          />
        </aside>
      </section>
    </main>
  );
}
function PanelHeader({
  icon: Icon,
  title,
  detail,
}: {
  icon: LucideIcon;
  title: string;
  detail: string;
}) {
  return (
    <header className={styles.panelHeader}>
      <div className={styles.panelHeading}>
        <span className={styles.panelIcon}>
          <Icon size={17} />
        </span>
        <div>
          <h2>{title}</h2>
          <p>{detail}</p>
        </div>
      </div>
    </header>
  );
}
function ArchiveDetail({ archive }: { archive: ArchiveRecord | null }) {
  return (
    <section
      className={styles.inspectorPanel}
      aria-labelledby="archive-detail-title"
    >
      <PanelHeader
        icon={FileText}
        title="归档详情"
        detail="小产物可审阅；媒体本身始终仅在本地。"
      />
      <div
        className={styles.inspectorBody}
        tabIndex={0}
        aria-label="归档详情与本地媒体边界"
      >
        <div className={styles.archiveContent}>
          {archive ? (
            <>
              <dl className={styles.receiptFacts}>
                <div>
                  <dt>来源运行</dt>
                  <dd>{archive.run_id}</dd>
                </div>
                <div>
                  <dt>处理流程</dt>
                  <dd>{archive.pipeline_id ? "已登记处理流程" : "未提供"}</dd>
                </div>
                <div>
                  <dt>媒体云端字节</dt>
                  <dd>{archive.media_cloud_bytes}</dd>
                </div>
              </dl>
              <h3>小产物与本地描述符</h3>
              <ul className={styles.artifactList}>
                {archive.artifacts.map((artifact) => (
                  <li key={artifact.ref}>
                    <span>
                      <strong>{artifact.ref}</strong>
                      <small>
                        {archiveArtifactModeLabel(artifact.mode)} · {archiveArtifactMimeLabel(artifact.mime_type)} · {artifact.size_bytes} 字节
                      </small>
                    </span>
                    <Hash size={15} aria-label="hash" />
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <Status
              kind="empty"
              title="选择归档记录"
              detail="服务端无记录时保持真实空态；本地媒体边界仍持续可见。"
              compact
            />
          )}
        </div>
        <div className={styles.localBoundary}>
          <h3 className={styles.boundaryHeading}>本地媒体边界</h3>
          <ul
            className={styles.localMediaList}
            aria-label="始终留在本地的媒体类型"
          >
            {localMediaBoundaries.map(({ label, detail, Icon }) => (
              <li
                className={styles.localMediaRow}
                key={label}
                data-qa-fully-visible-item
              >
                <span className={styles.localMediaIcon}>
                  <Icon size={15} />
                </span>
                <span className={styles.artifactCopy}>
                  <strong>{label}</strong>
                  <small>{detail}</small>
                </span>
                <span className={styles.localOnly}>仅本地</span>
              </li>
            ))}
          </ul>
          <p className={styles.descriptorNote}>
            网页不播放、不下载、不接收媒体字节；仅显示合同允许的描述符和服务端校验字段。
          </p>
        </div>
      </div>
    </section>
  );
}
function DeletionPanel({
  archive,
  plan,
  confirmed,
  onConfirm,
  onPlan,
  onDelete,
  busy,
  receipt,
  error,
}: {
  archive: ArchiveRecord | null;
  plan: ArchiveDeletePlanResponse | null;
  confirmed: boolean;
  onConfirm: (value: boolean) => void;
  onPlan: () => void;
  onDelete: () => void;
  busy: boolean;
  receipt: string;
  error: string;
}) {
  return (
    <section
      className={styles.dangerPanel}
      aria-labelledby="delete-archive-title"
      data-page-terminal-surface="inspector"
    >
      <header className={styles.dangerHeader}>
        <ShieldAlert size={17} />
        <div>
          <h2 id="delete-archive-title">删除云端归档</h2>
          <p>先读取影响计划，再确认删除；不影响本地媒体。</p>
        </div>
      </header>
      <div
        className={styles.dangerBody}
        tabIndex={0}
        aria-label="云端归档删除计划"
      >
        {archive ? (
          <>
            <p className={styles.dangerIntro}>
              目标：{archive.archive_id}
              ；系统将删除归档记录和小附件，并在完成后提示确认结果。
            </p>
            {plan ? (
              <div className={styles.impactPlan}>
                <strong>删除计划已读回</strong>
                <span>计划 {plan.delete_plan_id}</span>
                <span>有效期至 {formatTime(plan.expires_at)}</span>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => onConfirm(event.target.checked)}
                  />
                  我确认删除此云端归档
                </label>
              </div>
            ) : null}
            <button
              className={styles.dangerButton}
              type="button"
              onClick={plan ? onDelete : onPlan}
              disabled={busy || (Boolean(plan) && !confirmed)}
            >
              {busy ? (
                <LoaderCircle className={styles.spin} size={16} />
              ) : (
                <Trash2 size={16} />
              )}
              {plan ? "确认删除并读回" : "读取删除影响计划"}
            </button>
            {receipt ? (
              <p className={styles.receiptNote}>
                <CheckCircle2 size={14} />
                删除已读回，收据 {receipt}
              </p>
            ) : null}
            {error ? (
              <p className={styles.errorBox} role="alert">
                <AlertCircle size={14} />
                {error}
              </p>
            ) : null}
          </>
        ) : (
          <p className={styles.dangerIntro}>
            当前没有可选择的归档记录；删除操作保持禁用。
          </p>
        )}
      </div>
    </section>
  );
}
function Status({
  kind,
  title,
  detail,
  action,
  compact = false,
}: {
  kind: "loading" | "permission" | "error" | "empty";
  title: string;
  detail: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  const Icon =
    kind === "loading"
      ? LoaderCircle
      : kind === "permission"
        ? LogIn
        : kind === "empty"
          ? CheckCircle2
          : AlertCircle;
  return (
    <div
      className={`${styles.stateSurface} ${compact ? styles.compactState : ""}`}
      role={kind === "error" ? "alert" : "status"}
    >
      <Icon className={kind === "loading" ? styles.spin : ""} size={20} />
      <strong>{title}</strong>
      <p>{detail}</p>
      {kind === "permission" ? (
        <a className={styles.loginLink} href={loginUrl()}>
          登录并查看
        </a>
      ) : null}
      {action}
    </div>
  );
}
function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "时间未提供"
    : date.toLocaleString("zh-CN", { hour12: false });
}

function archiveStateLabel(value: string): string {
  return ({ active: "可用", deleting: "正在删除", delete_failed: "删除失败" }[value] ?? "状态待确认");
}

function archiveArtifactModeLabel(value: string): string {
  return ({ content: "可查看内容", descriptor_only: "仅本地描述符", forbidden: "不可展示" }[value] ?? "展示方式待确认");
}

function archiveArtifactMimeLabel(value: string): string {
  return ({
    "application/json": "JSON 数据",
    "application/pdf": "PDF 文档",
    "text/markdown": "Markdown 文档",
    "text/plain": "文本文档",
    "image/jpeg": "JPEG 图片",
    "image/png": "PNG 图片",
  }[value.toLowerCase()] ?? "文件类型待确认");
}
export default ArchivesPage;
