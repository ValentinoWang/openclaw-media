import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Download,
  Link as LinkIcon,
  RefreshCw,
  Save,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  classifyDocumentFailure,
  createIf2DocumentApi,
  isSafelyEditableBlock,
  pollDocumentExport,
  type DocumentBlock,
  type DocumentBody,
  type DocumentDataSnapshotBlock,
  type DocumentMark,
  type DocumentRevisionRecord,
  type DocumentRichTextBlock,
  type DocumentValue,
} from "../../documentWorkflow";
import { callBusinessOperation } from "../../generatedBusinessPagesContract";
import { newIdempotencyKey } from "../../idempotency";
import { useMediaWeb } from "../../MediaWebWorkspace";
import CanonicalDocumentRenderer from "./CanonicalDocumentRenderer";
import { SurfaceState } from "../../ui/SurfaceState";
import styles from "./DocumentEditorPage.module.css";

type SaveState =
  "clean" | "dirty" | "saving" | "saved" | "conflict" | "offline" | "error";
type MarkName = Exclude<DocumentMark, { type: "link" }>;
type ArtifactRevisionResponse = {
  item?: { currentRevision?: number };
};
const MARKS: readonly MarkName[] = [
  "bold",
  "italic",
  "underline",
  "strike",
  "inline_code",
];
const blockLabel: Record<DocumentBlock["type"], string> = {
  paragraph: "段落",
  quote: "引用",
  heading_1: "一级标题",
  heading_2: "二级标题",
  heading_3: "三级标题",
  heading_4: "四级标题",
  heading_5: "五级标题",
  heading_6: "六级标题",
  heading_7: "七级标题",
  heading_8: "八级标题",
  heading_9: "九级标题",
  bullet_list: "无序列表",
  ordered_list: "有序列表",
  todo_item: "待办事项",
  code_block: "代码块",
  divider: "分隔线",
  callout: "提示块",
  image: "图片",
  attachment: "附件",
  table: "表格",
  data_snapshot: "数据快照",
};
const revisionStateLabel: Record<DocumentRevisionRecord["state"], string> = {
  draft: "草稿",
  generating: "正在生成",
  ready: "可用",
  failed: "生成失败",
  conflict: "需要处理冲突",
  archived: "已归档",
};

function cloneBody(body: DocumentBody): DocumentBody {
  return JSON.parse(JSON.stringify(body)) as DocumentBody;
}
function textOf(block: DocumentBlock): string {
  if (block.type === "code_block") return block.text;
  return "content" in block
    ? block.content.map((run) => run.text).join("")
    : "";
}
function marksOf(block: DocumentBlock | undefined): DocumentMark[] {
  return block && "content" in block ? (block.content[0]?.marks ?? []) : [];
}
function isMark(value: DocumentMark, mark: MarkName): boolean {
  return value === mark;
}
function isLinkableBlock(
  block: DocumentBlock | undefined,
): block is DocumentRichTextBlock {
  return Boolean(
    block && isSafelyEditableBlock(block) && block.type !== "code_block",
  );
}
function isProtectedSnapshot(
  block: DocumentBlock,
): block is DocumentDataSnapshotBlock {
  return block.type === "data_snapshot";
}
function versionLabel(value: number | null): string {
  return value === null ? "初始正文" : `v${value}`;
}
function editorFailureMessage(error: unknown, fallback: string): string {
  const failure = classifyDocumentFailure(error);
  if (failure.kind === "conflict")
    return "正文已在其他位置更新。请载入最新内容，或先导出本地副本。";
  if (failure.kind === "protected")
    return "此内容受到保护，不能在编辑器中改写。";
  if (failure.kind === "unsupported")
    return "部分正文的结构暂时无法保存。请处理已高亮的内容，或仅保存其余正文。";
  if (failure.kind === "permission") return "当前会话没有执行此操作的权限。";
  return fallback;
}
function technicalReference(error: unknown): string {
  const code = classifyDocumentFailure(error).code;
  return /^[a-z0-9][a-z0-9_.:-]{0,95}$/i.test(code)
    ? code
    : "document_request_failed";
}
function blockIdsFrom(error: unknown): string[] {
  if (!error || typeof error !== "object") return [];
  const details = (error as { details?: unknown }).details;
  if (!details || typeof details !== "object") return [];
  const candidate = (details as { blockIds?: unknown }).blockIds;
  if (!Array.isArray(candidate)) return [];
  return [
    ...new Set(
      candidate.filter(
        (value): value is string =>
          typeof value === "string" && value.length > 0,
      ),
    ),
  ];
}
function scrollToBlock(blockId: string): void {
  window.requestAnimationFrame(() => {
    const target = Array.from(
      document.querySelectorAll<HTMLElement>("[data-editor-block-id]"),
    ).find((element) => element.dataset.editorBlockId === blockId);
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
    target?.focus({ preventScroll: true });
  });
}
function formatSnapshotValue(value: DocumentValue): string {
  if (Array.isArray(value)) return value.map(String).join("、");
  if (value === null) return "未提供";
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}
function ProtectedSnapshot({ block }: { block: DocumentDataSnapshotBlock }) {
  return (
    <aside className={styles.protectedSnapshot} aria-label="受保护数据快照">
      <div>
        <strong>受保护数据快照</strong>
        <span>不可编辑</span>
      </div>
      <dl>
        {Object.entries(block.attrs.displayFields).map(([, value], index) => (
          <div key={index}>
            <dt>数据项 {index + 1}</dt>
            <dd>{formatSnapshotValue(value)}</dd>
          </div>
        ))}
      </dl>
      <p>
        这些数据来自受控快照。为避免与来源记录不一致，编辑器仅提供只读查看；需要更新时请回到生成该数据的原始记录处理。
      </p>
      <small>来源版本 {versionLabel(block.attrs.sourceRevision)}</small>
    </aside>
  );
}

export default function DocumentEditorPage() {
  const { artifactId } = useParams<{ artifactId?: string }>();
  const { runtimeState, session } = useMediaWeb();
  const navigate = useNavigate();
  const api = useMemo(() => createIf2DocumentApi(), []);
  const [revision, setRevision] = useState<DocumentRevisionRecord | null>(null);
  const [body, setBody] = useState<DocumentBody | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("clean");
  const [message, setMessage] = useState("正在读取正文");
  const [technicalCode, setTechnicalCode] = useState<string | null>(null);
  const [invalidBlocks, setInvalidBlocks] = useState<string[]>([]);
  const [selectedBlock, setSelectedBlock] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [aiInstruction, setAiInstruction] = useState("");
  const [aiRevision, setAiRevision] =
    useState<DocumentRevisionRecord | null>(null);
  const [aiStatus, setAiStatus] = useState<
    "idle" | "generating" | "ready" | "failed"
  >("idle");

  const load = useCallback(async () => {
    if (!artifactId) return;
    setMessage("正在读取正文");
    setTechnicalCode(null);
    setSaveState("saving");
    try {
      const response = await api.getBody(artifactId);
      setRevision(response.data.revision);
      setBody(cloneBody(response.data.revision.body));
      setInvalidBlocks([]);
      setSaveState("clean");
      setMessage("已读取最新正文");
    } catch (error) {
      setMessage(editorFailureMessage(error, "正文暂时不可读取，请稍后重试。"));
      setTechnicalCode(technicalReference(error));
      setSaveState(!navigator.onLine ? "offline" : "error");
    }
  }, [api, artifactId]);
  useEffect(() => {
    void load();
  }, [load]);

  function updateBlock(blockId: string, text: string) {
    setBody((current) => {
      if (!current) return current;
      return {
        ...current,
        blocks: current.blocks.map((block) => {
          if (block.id !== blockId || !isSafelyEditableBlock(block))
            return block;
          if (block.type === "code_block") return { ...block, text };
          const previous = block.content[0];
          return {
            ...block,
            content: [
              { type: "text" as const, text, marks: previous?.marks ?? [] },
            ],
          };
        }),
      };
    });
    setSaveState("dirty");
    setMessage("有未保存修改");
    setTechnicalCode(null);
  }
  function toggleMark(mark: MarkName) {
    if (!selectedBlock) return;
    setBody((current) => {
      if (!current) return current;
      return {
        ...current,
        blocks: current.blocks.map((block) => {
          if (
            block.id !== selectedBlock ||
            !("content" in block) ||
            !isSafelyEditableBlock(block)
          )
            return block;
          const run = block.content[0] ?? {
            type: "text" as const,
            text: "",
            marks: [],
          };
          const active = run.marks.some((value) => isMark(value, mark));
          const marks = active
            ? run.marks.filter((value) => !isMark(value, mark))
            : [...run.marks, mark];
          return {
            ...block,
            content: [{ ...run, marks }],
          } as DocumentRichTextBlock;
        }),
      };
    });
    setSaveState("dirty");
    setTechnicalCode(null);
  }
  function addLink() {
    const selected = body?.blocks.find((block) => block.id === selectedBlock);
    if (!isLinkableBlock(selected)) return;
    const href = window.prompt("链接地址");
    if (!href) return;
    setBody(
      (current) =>
        current && {
          ...current,
          blocks: current.blocks.map((block) =>
            block.id === selectedBlock && "content" in block
              ? {
                  ...block,
                  content: [
                    {
                      ...(block.content[0] ?? {
                        type: "text" as const,
                        text: "",
                      }),
                      marks: [
                        ...(block.content[0]?.marks ?? []),
                        { type: "link" as const, href, title: null },
                      ],
                    },
                  ],
                }
              : block,
          ),
        },
    );
    setSaveState("dirty");
    setTechnicalCode(null);
  }
  async function createAiRevision() {
    if (
      !artifactId ||
      !revision ||
      !session ||
      !aiInstruction.trim() ||
      aiStatus === "generating"
    )
      return;
    setAiStatus("generating");
    setAiRevision(null);
    setMessage("已提交改稿请求，正在生成新的修订。");
    setTechnicalCode(null);
    try {
      const created = await callBusinessOperation<ArtifactRevisionResponse>(
        "createArtifactRevision",
        {
          path: { publicArtifactId: artifactId },
          body: {
            expectedRevision: revision.revision,
            instruction: aiInstruction.trim(),
            mode: "regenerate",
          },
          csrfToken: session.csrfToken,
          idempotencyKey: newIdempotencyKey("ai-edit"),
        },
      );
      const revisionNumber = created.item?.currentRevision;
      if (
        typeof revisionNumber !== "number" ||
        !Number.isInteger(revisionNumber) ||
        revisionNumber < 1
      )
        throw new Error("改稿修订未返回可读取的版本号。");

      for (let attempt = 0; attempt < 30; attempt += 1) {
        const current = await api.getRevision(artifactId, revisionNumber);
        setAiRevision(current.data);
        if (current.data.state === "ready") {
          setAiStatus("ready");
          setMessage("AI 改稿已生成，可载入后继续审阅和保存。");
          return;
        }
        if (
          current.data.state === "failed" ||
          current.data.state === "conflict" ||
          current.data.state === "archived"
        ) {
          setAiStatus("failed");
          setMessage("AI 改稿未能生成可采用的修订。");
          return;
        }
        await new Promise<void>((resolve) => {
          window.setTimeout(resolve, 1000);
        });
      }
      setAiStatus("failed");
      setMessage("AI 改稿仍在生成，可稍后重新读取结果。");
    } catch (error) {
      setAiStatus("failed");
      setMessage(editorFailureMessage(error, "改稿请求失败，请稍后重试。"));
      setTechnicalCode(technicalReference(error));
    }
  }
  function adoptAiRevision() {
    if (!aiRevision || aiRevision.state !== "ready") return;
    setRevision(aiRevision);
    setBody(cloneBody(aiRevision.body));
    setAiStatus("idle");
    setAiInstruction("");
    setMessage("已载入 AI 修订。保存后会成为当前正文。");
    setSaveState("dirty");
    setTechnicalCode(null);
  }
  async function save(onlyValid = false) {
    if (!artifactId || !body || !revision || !session || saveState === "saving")
      return;
    setSaveState("saving");
    setMessage("保存中：校验正文");
    setTechnicalCode(null);
    const nextBody =
      onlyValid && invalidBlocks.length
        ? {
            ...body,
            blocks: body.blocks.filter(
              (block) => !invalidBlocks.includes(block.id),
            ),
          }
        : body;
    try {
      setMessage("保存中：写入修订链");
      const response = await api.saveDraft(artifactId, nextBody, revision, {
        csrfToken: session.csrfToken,
      });
      setRevision(response.data);
      setBody(cloneBody(response.data.body));
      setInvalidBlocks([]);
      setSaveState("saved");
      setMessage("已保存，修订链已更新");
    } catch (error) {
      const status = (error as { status?: number }).status;
      const blockIds = status === 422 ? blockIdsFrom(error) : [];
      const offline = !navigator.onLine;
      setInvalidBlocks(blockIds);
      setMessage(
        offline
          ? "保存没有送达。请恢复网络后重试，原编辑内容仍保留在当前页面。"
          : editorFailureMessage(error, "保存失败，请稍后重试。"),
      );
      setTechnicalCode(technicalReference(error));
      if (blockIds[0]) {
        setSelectedBlock(blockIds[0]);
        scrollToBlock(blockIds[0]);
      }
      setSaveState(
        status === 409 || classifyDocumentFailure(error).kind === "conflict"
          ? "conflict"
          : offline
            ? "offline"
            : "error",
      );
    }
  }
  function downloadLocalCopy() {
    if (!body || !revision) return;
    const downloadUrl = URL.createObjectURL(
      new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `正文-${versionLabel(revision.revision)}-本地副本.json`;
    link.click();
    URL.revokeObjectURL(downloadUrl);
    setMessage("已导出本地副本。本次保存未覆盖其他位置的正文。");
    setTechnicalCode(null);
  }
  async function exportDocument(format: "pdf" | "docx") {
    if (
      !artifactId ||
      !revision ||
      !session ||
      exporting ||
      revision.state !== "ready"
    )
      return;
    setExporting(true);
    setMessage("正在生成导出文件");
    setTechnicalCode(null);
    try {
      const created = await api.createExport(
        artifactId,
        revision.revision,
        format,
        { csrfToken: session.csrfToken },
      );
      const ready = await pollDocumentExport(api, created.data.publicExportId);
      if (ready.state !== "ready") throw new Error("导出未完成");
      const download = await api.getExportDownload(ready.publicExportId);
      setExportUrl(download.data.downloadUrl);
      setMessage(`${format.toUpperCase()} 导出已就绪`);
    } catch (error) {
      setMessage(editorFailureMessage(error, "导出失败，请稍后重试。"));
      setTechnicalCode(technicalReference(error));
    } finally {
      setExporting(false);
    }
  }
  if (runtimeState !== "authenticated" || !session)
    return (
      <SurfaceState
        kind="permission"
        title="个人正文编辑"
        detail="当前会话无权访问正文编辑。"
      />
    );
  if (!artifactId)
    return (
      <SurfaceState
        kind="notFound"
        title="未找到正文"
        detail="缺少要编辑的正文编号。"
      />
    );
  if (!body || !revision)
    return (
      <main className={styles.page} data-page-ownership="personal" data-accent="studio" data-document-editor="true">
        <SurfaceState
          kind={saveState === "error" || saveState === "offline" ? "error" : "loading"}
          title="个人正文编辑"
          detail={message}
          action={
            <button className="mg-btn mg-btn-soft" onClick={() => void load()}>
              <RefreshCw size={15} />
              重新读取
            </button>
          }
        />
        {technicalCode ? <p className={styles.technicalReference}>技术参考码：{technicalCode}</p> : null}
      </main>
    );
  return (
    <main
      className={styles.page}
      data-page-ownership="personal"
      data-accent="studio"
      data-document-editor="true"
    >
      <header className="mg-hero" data-page-prelude>
        <div>
          <span className="mg-eyebrow">个人正文编辑与修订</span>
          <h1>正文编辑</h1>
          <p className="mg-hero-lead">
            当前版本 {versionLabel(revision.revision)} ·{" "}
            {revision.bodyAuthority === "internal"
              ? "个人正文"
              : "受保护正文"}
          </p>
        </div>
        <div className={`${styles.actions} mg-hero-actions`}>
          <button
            className="mg-btn mg-btn-ghost"
            onClick={() => navigate(`/workspace/preview/${artifactId}`)}
          >
            <X size={16} />
            关闭
          </button>
          <button
            className="mg-btn mg-btn-primary"
            disabled={saveState === "saving" || saveState === "conflict"}
            onClick={() => void save()}
          >
            <Save size={16} />
            保存
          </button>
        </div>
      </header>
      {saveState === "saving" ? (
        <section className={`${styles.banner} ${styles.writing}`} role="status">
          <strong>保存中</strong>
          <span>{message}</span>
          <ol>
            <li>校验正文</li>
            <li>写入修订链</li>
            <li>记录证据账本</li>
          </ol>
        </section>
      ) : null}
      {saveState === "conflict" ? (
        <section className={`${styles.banner} ${styles.conflict}`} role="alert">
          <strong>这篇正文已在别处更新</strong>
          <span>{message}</span>
          <div>
            <button className="mg-btn mg-btn-primary" onClick={downloadLocalCopy}>
              <Download size={15} />
              导出本地副本
            </button>
            <button
              className="mg-btn mg-btn-soft"
              onClick={() => void load()}
            >
              <RefreshCw size={15} />
              放弃本地修改并载入最新正文
            </button>
          </div>
        </section>
      ) : null}
      {saveState === "offline" ? (
        <section className={`${styles.banner} ${styles.offline}`} role="alert">
          <WifiOff size={18} />
          <span>{message}</span>
          <button className="mg-btn mg-btn-soft" onClick={() => void save()}>
            重试保存
          </button>
        </section>
      ) : null}
      {saveState === "error" && !invalidBlocks.length ? (
        <section className={`${styles.banner} ${styles.validation}`} role="alert">
          <strong>本次操作未完成</strong>
          <span>{message}</span>
          <button className="mg-btn mg-btn-soft" onClick={() => void save()}>
            重试保存
          </button>
        </section>
      ) : null}
      {invalidBlocks.length ? (
        <section
          className={`${styles.banner} ${styles.validation}`}
          role="alert"
        >
          <strong>部分正文未通过校验</strong>
          <span>已高亮 {invalidBlocks.length} 个块；可跳到问题位置，或仅保存其余正文。</span>
          <div>
            <button
              className="mg-btn mg-btn-soft"
              onClick={() => scrollToBlock(invalidBlocks[0])}
            >
              跳到第一个问题块
            </button>
            <button
              className="mg-btn mg-btn-primary"
              onClick={() => void save(true)}
            >
              仅保存其余正文
            </button>
          </div>
        </section>
      ) : null}
      {technicalCode ? <p className={styles.technicalReference}>技术参考码：{technicalCode}</p> : null}
      <div className={styles.layout}>
        <section
          className={`${styles.canvas} mg-panel`}
          aria-label="正文编辑区"
        >
          <div className={styles.toolbar}>
            {MARKS.map((mark) => (
              <button
                key={mark}
                type="button"
                aria-pressed={
                  selectedBlock
                    ? marksOf(
                        body.blocks.find((b) => b.id === selectedBlock)!,
                      ).some((value) => isMark(value, mark))
                    : false
                }
                onClick={() => toggleMark(mark)}
              >
                {mark === "inline_code"
                  ? "代码"
                  : mark === "bold"
                    ? "粗体"
                    : mark === "italic"
                      ? "斜体"
                      : mark === "underline"
                        ? "下划线"
                        : "删除线"}
              </button>
            ))}
            <button
              type="button"
              disabled={
                !isLinkableBlock(
                  body.blocks.find((block) => block.id === selectedBlock),
                )
              }
              onClick={addLink}
            >
              <LinkIcon size={15} />
              链接
            </button>
          </div>
          <div className={styles.blocks}>
            {body.blocks.map((block) => (
              <article
                key={block.id}
                className={
                  [
                    invalidBlocks.includes(block.id) ? styles.invalid : "",
                    selectedBlock === block.id ? styles.selected : "",
                  ]
                    .filter(Boolean)
                    .join(" ")
                }
                data-editor-block-id={block.id}
                tabIndex={-1}
                onClick={() => setSelectedBlock(block.id)}
              >
                {isSafelyEditableBlock(block) ? (
                  <>
                    <label htmlFor={`block-${block.id}`}>
                      {blockLabel[block.type]}
                    </label>
                    <textarea
                      id={`block-${block.id}`}
                      value={textOf(block)}
                      onChange={(event) =>
                        updateBlock(block.id, event.target.value)
                      }
                      onFocus={() => setSelectedBlock(block.id)}
                      rows={Math.max(
                        2,
                        Math.min(8, textOf(block).split("\n").length + 1),
                      )}
                    />
                  </>
                ) : isProtectedSnapshot(block) ? (
                  <ProtectedSnapshot block={block} />
                ) : (
                  <CanonicalDocumentRenderer blocks={[block]} />
                )}
              </article>
            ))}
          </div>
        </section>
        <aside className={`${styles.side} mg-panel`}>
          <div className={styles.ai}>
            <Sparkles size={17} />
            <strong>AI 改稿</strong>
            <textarea
              aria-label="改稿要求"
              value={aiInstruction}
              onChange={(event) => setAiInstruction(event.target.value)}
              placeholder="说明需要改善的表达、结构或语气"
              rows={3}
            />
            <button
              className="mg-btn mg-btn-soft"
              disabled={!aiInstruction.trim() || aiStatus === "generating"}
              onClick={() => void createAiRevision()}
            >
              {aiStatus === "generating" ? "正在生成" : "生成改稿修订"}
            </button>
            {aiStatus !== "idle" ? (
              <span>
                {aiStatus === "generating"
                  ? "服务端正在生成，页面会持续读取结果。"
                  : aiStatus === "ready"
                    ? "改稿修订已就绪。"
                    : "改稿未生成可采用结果。"}
              </span>
            ) : null}
            {aiRevision ? (
              <div className={styles.aiResult}>
                <b>{revisionStateLabel[aiRevision.state]}</b>
                <small>修订 {versionLabel(aiRevision.revision)}</small>
                {aiRevision.state === "ready" ? (
                  <button
                    className="mg-btn mg-btn-primary"
                    onClick={adoptAiRevision}
                  >
                    载入此修订
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
          <h2>证据账本</h2>
          <dl>
            <div>
              <dt>正文校验</dt>
              <dd>服务端保存时执行</dd>
            </div>
            <div>
              <dt>当前修订</dt>
              <dd>{versionLabel(revision.revision)}</dd>
            </div>
            <div>
              <dt>正文校验和</dt>
              <dd>{revision.bodyChecksum.slice(0, 16)}…</dd>
            </div>
          </dl>
          <h2>修订链</h2>
          <p className={styles.revision}>
            修订 {versionLabel(revision.revision)} ·{" "}
            {revisionStateLabel[revision.state]}
            <br />
            <small>基于 {versionLabel(revision.baseRevision)}</small>
          </p>
          <div className={styles.export}>
            <h2>导出</h2>
            <button
              className="mg-btn mg-btn-soft"
              disabled={exporting || revision.state !== "ready"}
              onClick={() => void exportDocument("pdf")}
            >
              <Download size={15} />
              PDF
            </button>
            <button
              className="mg-btn mg-btn-soft"
              disabled={exporting || revision.state !== "ready"}
              onClick={() => void exportDocument("docx")}
            >
              <Download size={15} />
              DOCX
            </button>
            {exportUrl ? (
              <a href={exportUrl} target="_blank" rel="noreferrer">
                下载导出文件
              </a>
            ) : null}
          </div>
        </aside>
      </div>
    </main>
  );
}
