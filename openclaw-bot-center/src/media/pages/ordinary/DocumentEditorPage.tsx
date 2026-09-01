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
  type DocumentExportFormat,
  type DocumentInlineNode,
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
type EditorEditableBlock =
  | DocumentRichTextBlock
  | Extract<DocumentBlock, { type: "code_block" }>;
type TextRange = { start: number; end: number };
type SelectedTextRange = TextRange & { blockId: string };
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
const markLabel: Record<MarkName, string> = {
  bold: "粗体",
  italic: "斜体",
  underline: "下划线",
  strike: "删除线",
  inline_code: "代码",
};
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
const bodyAuthorityLabel: Record<DocumentRevisionRecord["bodyAuthority"], string> = {
  internal: "个人正文",
  lark: "受保护正文",
};
const exportFormatLabel: Record<DocumentExportFormat, string> = {
  pdf: "PDF",
  docx: "Word 文档",
};
const snapshotWireValueLabel: Record<string, string> = {
  ...blockLabel,
  ...revisionStateLabel,
  ...bodyAuthorityLabel,
  ...exportFormatLabel,
  general: "通用表格",
  storyboard: "分镜表",
  publishing_checklist: "发布清单",
  metric_snapshot: "指标快照",
  evidence_index: "证据索引",
  personal_web: "个人工作区",
  organization_lark: "组织工作区",
  queued: "排队中",
  rendering: "正在处理",
  succeeded: "已完成",
  running: "处理中",
  pending: "等待处理",
  unknown: "待对账",
  partial: "部分完成",
  unavailable: "不可用",
  info: "提示",
  success: "成功",
  warning: "注意",
  danger: "风险",
  bold: "粗体",
  italic: "斜体",
  underline: "下划线",
  strike: "删除线",
  inline_code: "行内代码",
  link: "链接",
  write: "写入",
  owner: "组织负责人",
  member: "组织成员",
  unsupported: "结构不支持",
  empty: "暂无数据",
  "application/pdf": "PDF 文档",
  "text/plain": "文本文件",
};
const snapshotEnumFields = new Set([
  "authority",
  "body_authority",
  "bodyAuthority",
  "workspace_mode",
  "workspaceMode",
  "state",
  "status",
  "revision_state",
  "revisionState",
  "export_state",
  "exportState",
  "semantic_purpose",
  "semanticPurpose",
  "block_type",
  "blockType",
  "type",
  "kind",
  "tone",
  "semantic_tone",
  "semanticTone",
  "format",
  "export_format",
  "exportFormat",
]);

function cloneBody(body: DocumentBody): DocumentBody {
  return JSON.parse(JSON.stringify(body)) as DocumentBody;
}
function textOf(block: DocumentBlock): string {
  if (block.type === "code_block") return block.text;
  return "content" in block
    ? block.content.map((run) => run.text).join("")
    : "";
}
function isMark(value: DocumentMark, mark: MarkName): boolean {
  return value === mark;
}
function isRichTextBlock(block: DocumentBlock): block is DocumentRichTextBlock {
  return (
    block.type === "paragraph" ||
    block.type === "quote" ||
    /^heading_[1-9]$/.test(block.type)
  );
}
function isEditorEditableBlock(block: DocumentBlock): block is EditorEditableBlock {
  return isSafelyEditableBlock(block) || isRichTextBlock(block);
}
function isLinkableBlock(
  block: DocumentBlock | undefined,
): block is DocumentRichTextBlock {
  return Boolean(
    block && isEditorEditableBlock(block) && block.type !== "code_block",
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
function normalizeTextRange(range: TextRange, textLength: number): TextRange | null {
  if (
    !Number.isFinite(range.start) ||
    !Number.isFinite(range.end) ||
    textLength < 1
  )
    return null;
  const lower = Math.max(0, Math.min(textLength, Math.trunc(Math.min(range.start, range.end))));
  const upper = Math.max(0, Math.min(textLength, Math.trunc(Math.max(range.start, range.end))));
  return upper > lower ? { start: lower, end: upper } : null;
}
function isMarkActiveInRange(
  runs: DocumentInlineNode[],
  range: TextRange,
  mark: MarkName,
): boolean {
  const normalized = normalizeTextRange(
    range,
    runs.reduce((length, run) => length + run.text.length, 0),
  );
  if (!normalized) return false;
  let offset = 0;
  let hasText = false;
  let everyRunHasMark = true;
  for (const run of runs) {
    const runStart = offset;
    const runEnd = runStart + run.text.length;
    offset = runEnd;
    if (
      run.text.length === 0 ||
      runEnd <= normalized.start ||
      runStart >= normalized.end
    )
      continue;
    hasText = true;
    if (!run.marks.some((value) => isMark(value, mark))) everyRunHasMark = false;
  }
  return hasText && everyRunHasMark;
}
function transformInlineRange(
  runs: DocumentInlineNode[],
  range: TextRange,
  transformMarks: (marks: DocumentMark[]) => DocumentMark[],
): DocumentInlineNode[] {
  const textLength = runs.reduce((length, run) => length + run.text.length, 0);
  const normalized = normalizeTextRange(range, textLength);
  if (!normalized) return runs;

  // Split only at the selected boundaries so untouched runs and their marks survive.
  const nextRuns: DocumentInlineNode[] = [];
  let offset = 0;
  for (const run of runs) {
    const runStart = offset;
    const runEnd = runStart + run.text.length;
    offset = runEnd;
    if (run.text.length === 0) {
      nextRuns.push({ ...run, marks: [...run.marks] });
      continue;
    }
    const selectedStart = Math.max(runStart, normalized.start);
    const selectedEnd = Math.min(runEnd, normalized.end);
    if (selectedStart >= selectedEnd) {
      nextRuns.push({ ...run, marks: [...run.marks] });
      continue;
    }
    const localStart = selectedStart - runStart;
    const localEnd = selectedEnd - runStart;
    if (localStart > 0) {
      nextRuns.push({
        ...run,
        text: run.text.slice(0, localStart),
        marks: [...run.marks],
      });
    }
    nextRuns.push({
      ...run,
      text: run.text.slice(localStart, localEnd),
      marks: transformMarks([...run.marks]),
    });
    if (localEnd < run.text.length) {
      nextRuns.push({
        ...run,
        text: run.text.slice(localEnd),
        marks: [...run.marks],
      });
    }
  }
  return nextRuns;
}
function toggleMarkInRange(
  runs: DocumentInlineNode[],
  range: TextRange,
  mark: MarkName,
): DocumentInlineNode[] {
  const remove = isMarkActiveInRange(runs, range, mark);
  return transformInlineRange(runs, range, (marks) => {
    if (remove) return marks.filter((value) => !isMark(value, mark));
    return marks.some((value) => isMark(value, mark))
      ? marks
      : [...marks, mark];
  });
}
function applyLinkToRange(
  runs: DocumentInlineNode[],
  range: TextRange,
  href: string,
): DocumentInlineNode[] {
  const link = { type: "link" as const, href, title: null };
  return transformInlineRange(runs, range, (marks) => [
    ...marks.filter((value) => !(typeof value === "object" && value.type === "link")),
    link,
  ]);
}
function sliceInlineRuns(
  runs: DocumentInlineNode[],
  start: number,
  end: number,
): DocumentInlineNode[] {
  const result: DocumentInlineNode[] = [];
  let offset = 0;
  for (const run of runs) {
    const runStart = offset;
    const runEnd = runStart + run.text.length;
    offset = runEnd;
    if (run.text.length === 0) {
      if (runStart >= start && runStart < end)
        result.push({ ...run, marks: [...run.marks] });
      continue;
    }
    const sliceStart = Math.max(runStart, start);
    const sliceEnd = Math.min(runEnd, end);
    if (sliceStart < sliceEnd) {
      result.push({
        ...run,
        text: run.text.slice(sliceStart - runStart, sliceEnd - runStart),
        marks: [...run.marks],
      });
    }
  }
  return result;
}
function marksAtPosition(runs: DocumentInlineNode[], position: number): DocumentMark[] {
  let offset = 0;
  let fallback: DocumentMark[] = [];
  for (const run of runs) {
    if (run.text.length === 0) continue;
    const end = offset + run.text.length;
    if (position <= end) return [...run.marks];
    fallback = [...run.marks];
    offset = end;
  }
  return fallback;
}
function replaceInlineText(
  runs: DocumentInlineNode[],
  nextText: string,
): DocumentInlineNode[] {
  const previousText = runs.map((run) => run.text).join("");
  if (previousText === nextText) return runs;
  let prefixLength = 0;
  while (
    prefixLength < previousText.length &&
    prefixLength < nextText.length &&
    previousText[prefixLength] === nextText[prefixLength]
  )
    prefixLength += 1;
  let suffixLength = 0;
  while (
    suffixLength < previousText.length - prefixLength &&
    suffixLength < nextText.length - prefixLength &&
    previousText[previousText.length - suffixLength - 1] ===
      nextText[nextText.length - suffixLength - 1]
  )
    suffixLength += 1;
  const previousEnd = previousText.length - suffixLength;
  const nextEnd = nextText.length - suffixLength;
  const insertedText = nextText.slice(prefixLength, nextEnd);
  const nextRuns = [
    ...sliceInlineRuns(runs, 0, prefixLength),
    ...(insertedText
      ? [
          {
            type: "text" as const,
            text: insertedText,
            marks: marksAtPosition(runs, prefixLength),
          },
        ]
      : []),
    ...sliceInlineRuns(runs, previousEnd, previousText.length),
  ];
  return nextRuns.length
    ? nextRuns
    : [{ type: "text", text: "", marks: marksAtPosition(runs, prefixLength) }];
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
function technicalReference(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const candidate = (error as { code?: unknown }).code;
  if (
    typeof candidate !== "string" ||
    !/^[a-z0-9][a-z0-9_.:-]{0,95}$/i.test(candidate) ||
    /^http_\d{3}$/i.test(candidate)
  )
    return null;
  return candidate;
}
function TechnicalReference({ code }: { code: string | null }) {
  if (!code) return null;
  return <p className={styles.technicalReference}>技术参考码：{code}</p>;
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
function formatSnapshotValue(fieldName: string, value: DocumentValue): string {
  if (Array.isArray(value))
    return value.map((item) => formatSnapshotScalar(fieldName, item)).join("、");
  if (value === null) return "未提供";
  if (typeof value === "boolean") return value ? "是" : "否";
  return formatSnapshotScalar(fieldName, value);
}
function formatSnapshotScalar(
  fieldName: string,
  value: string | number | boolean,
): string {
  if (typeof value !== "string") return String(value);
  if (/^image\//i.test(value)) return "图片";
  return (
    snapshotWireValueLabel[value] ??
    (snapshotEnumFields.has(fieldName) || /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/u.test(value)
      ? "待确认"
      : value)
  );
}
function ProtectedSnapshot({ block }: { block: DocumentDataSnapshotBlock }) {
  return (
    <aside className={styles.protectedSnapshot} aria-label="受保护数据快照">
      <div>
        <strong>受保护数据快照</strong>
        <span>不可编辑</span>
      </div>
      <dl>
        {Object.entries(block.attrs.displayFields).map(([fieldName, value], index) => (
          <div key={index}>
            <dt>数据项 {index + 1}</dt>
            <dd>{formatSnapshotValue(fieldName, value)}</dd>
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
  const [selectedRange, setSelectedRange] =
    useState<SelectedTextRange | null>(null);
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
      setSelectedBlock(null);
      setSelectedRange(null);
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

  function captureSelection(blockId: string, target: HTMLTextAreaElement): void {
    setSelectedBlock(blockId);
    setSelectedRange({
      blockId,
      start: target.selectionStart,
      end: target.selectionEnd,
    });
  }
  function updateBlock(blockId: string, text: string) {
    setBody((current) => {
      if (!current) return current;
      return {
        ...current,
        blocks: current.blocks.map((block) => {
          if (block.id !== blockId || !isEditorEditableBlock(block))
            return block;
          if (block.type === "code_block") return { ...block, text };
          return {
            ...block,
            content: replaceInlineText(block.content, text),
          };
        }),
      };
    });
    setSaveState("dirty");
    setMessage("有未保存修改");
    setTechnicalCode(null);
  }
  function toggleMark(mark: MarkName) {
    const range = selectedRange;
    const selected = body?.blocks.find((block) => block.id === selectedBlock);
    if (
      !range ||
      range.blockId !== selectedBlock ||
      !isLinkableBlock(selected) ||
      !normalizeTextRange(range, textOf(selected).length)
    )
      return;
    setBody((current) => {
      if (!current) return current;
      return {
        ...current,
        blocks: current.blocks.map((block) => {
          if (block.id !== range.blockId || !isLinkableBlock(block))
            return block;
          return {
            ...block,
            content: toggleMarkInRange(block.content, range, mark),
          };
        }),
      };
    });
    setSaveState("dirty");
    setTechnicalCode(null);
  }
  function addLink() {
    const range = selectedRange;
    const selected = body?.blocks.find((block) => block.id === selectedBlock);
    if (
      !range ||
      range.blockId !== selectedBlock ||
      !isLinkableBlock(selected) ||
      !normalizeTextRange(range, textOf(selected).length)
    )
      return;
    const href = window.prompt("链接地址");
    if (!href) return;
    setBody(
      (current) =>
        current && {
          ...current,
          blocks: current.blocks.map((block) =>
            block.id === range.blockId && isLinkableBlock(block)
              ? {
                  ...block,
                  content: applyLinkToRange(block.content, range, href),
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
      setMessage("AI 改稿仍在生成，请稍后重新读取页面查看结果。");
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
    setSelectedBlock(null);
    setSelectedRange(null);
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
  async function exportDocument(format: DocumentExportFormat) {
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
      setMessage(`${exportFormatLabel[format]} 导出已就绪`);
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
        <TechnicalReference code={technicalCode} />
      </main>
    );
  const selectedBlockRecord = body.blocks.find(
    (block) => block.id === selectedBlock,
  );
  const selectedRichTextBlock = isLinkableBlock(selectedBlockRecord)
    ? selectedBlockRecord
    : null;
  const selectedTextRange =
    selectedRichTextBlock && selectedRange?.blockId === selectedRichTextBlock.id
      ? normalizeTextRange(
          selectedRange,
          textOf(selectedRichTextBlock).length,
        )
      : null;
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
            {bodyAuthorityLabel[revision.bodyAuthority]}
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
            <button
              className="mg-btn mg-btn-ghost"
              disabled
              title="服务端尚未提供可用于逐段对比的冲突差异。"
            >
              逐段对比并合并
            </button>
            <button className="mg-btn mg-btn-primary" onClick={downloadLocalCopy}>
              <Download size={15} />
              保留为本地副本
            </button>
            <button
              className="mg-btn mg-btn-soft"
              onClick={() => void load()}
            >
              <RefreshCw size={15} />
              放弃本地修改并载入最新正文
            </button>
          </div>
          <small>
            服务端尚未提供可对比的冲突差异，因此暂不能逐段合并；本地改动可先保留为副本，或放弃后载入最新正文。
          </small>
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
      <TechnicalReference code={technicalCode} />
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
                  selectedRichTextBlock && selectedTextRange
                    ? isMarkActiveInRange(
                        selectedRichTextBlock.content,
                        selectedTextRange,
                        mark,
                      )
                    : false
                }
                disabled={!selectedRichTextBlock || !selectedTextRange}
                title={
                  selectedRichTextBlock && selectedTextRange
                    ? markLabel[mark]
                    : "请先选择正文片段"
                }
                onClick={() => toggleMark(mark)}
              >
                {markLabel[mark]}
              </button>
            ))}
            <button
              type="button"
              disabled={!selectedRichTextBlock || !selectedTextRange}
              title={
                selectedRichTextBlock && selectedTextRange
                  ? "链接"
                  : "请先选择正文片段"
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
                onClick={(event) => {
                  setSelectedBlock(block.id);
                  if (!(event.target instanceof HTMLTextAreaElement))
                    setSelectedRange(null);
                }}
              >
                {isEditorEditableBlock(block) ? (
                  <>
                    <label htmlFor={`block-${block.id}`}>
                      {blockLabel[block.type]}
                    </label>
                    <textarea
                      id={`block-${block.id}`}
                      value={textOf(block)}
                      onChange={(event) => {
                        captureSelection(block.id, event.currentTarget);
                        updateBlock(block.id, event.currentTarget.value);
                      }}
                      onFocus={(event) =>
                        captureSelection(block.id, event.currentTarget)
                      }
                      onSelect={(event) =>
                        captureSelection(block.id, event.currentTarget)
                      }
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
              Word 文档
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
