import {
  callBusinessOperation,
  type BusinessOperationRequest,
  type DocumentOperationId,
} from "./generatedBusinessPagesContract";
import { newIdempotencyKey } from "./idempotency";

export const IF2_DOCUMENT_OPERATIONS = [
  "createDocumentExport",
  "getDocumentBody",
  "getDocumentExport",
  "getDocumentExportDownload",
  "getDocumentRevision",
  "listArtifactSyncBatches",
  "saveDocumentDraft",
] as const satisfies readonly DocumentOperationId[];

export type DocumentBodyAuthority = "internal" | "lark";
export type DocumentRevisionState = "draft" | "generating" | "ready" | "failed" | "conflict" | "archived";
export type DocumentExportState = "queued" | "rendering" | "ready" | "failed";
export type DocumentExportFormat = "docx" | "pdf";
export type DocumentArtifactKind = "research_snapshot" | "asset_digest" | "decision_brief" | "creation_document" | "publishing_package" | "review_report" | "project_summary";

export type DocumentLinkMark = { type: "link"; href: string; title: string | null };
export type DocumentMark = "bold" | "italic" | "underline" | "strike" | "inline_code" | DocumentLinkMark;
export type DocumentInlineNode = { type: "text"; text: string; marks: DocumentMark[] };

type EmptyAttrs = Record<string, never>;
export type DocumentRichTextBlock = {
  id: string;
  type: "paragraph" | "heading_1" | "heading_2" | "heading_3" | "heading_4" | "heading_5" | "heading_6" | "heading_7" | "heading_8" | "heading_9" | "quote";
  attrs: EmptyAttrs;
  content: DocumentInlineNode[];
};
export type DocumentListItem = { id: string; content: DocumentInlineNode[]; children: DocumentListBlock[] };
export type DocumentListBlock = { id: string; type: "bullet_list" | "ordered_list"; attrs: EmptyAttrs; items: DocumentListItem[] };
export type DocumentTodoBlock = { id: string; type: "todo_item"; attrs: { checked: boolean }; content: DocumentInlineNode[] };
export type DocumentCodeBlock = { id: string; type: "code_block"; attrs: { language: string | null }; text: string };
export type DocumentDividerBlock = { id: string; type: "divider"; attrs: EmptyAttrs };
export type DocumentCalloutBlock = { id: string; type: "callout"; attrs: { semanticTone: "info" | "success" | "warning" | "danger" }; content: DocumentInlineNode[] };
export type DocumentImageBlock = { id: string; type: "image"; attrs: { publicResourceId: string; altText: string; width: number; height: number; contentChecksum: string } };
export type DocumentAttachmentBlock = { id: string; type: "attachment"; attrs: { publicResourceId: string; fileName: string; contentType: string; contentChecksum: string } };
export type DocumentTableCell = { id: string; content: DocumentInlineNode[] };
export type DocumentTableRow = { id: string; cells: DocumentTableCell[] };
export type DocumentTableBlock = { id: string; type: "table"; attrs: { semanticPurpose: "general" | "storyboard" | "publishing_checklist" | "metric_snapshot" | "evidence_index"; headerRowCount: 1 }; rows: DocumentTableRow[] };
export type DocumentValue = string | number | boolean | Array<string | number | boolean> | null;
export type DocumentDataSnapshotBlock = { id: string; type: "data_snapshot"; attrs: { semanticPurpose: "metric_snapshot" | "evidence_index"; publicObjectId: string; sourceRevision: number; capturedAt: string; displayFields: Record<string, DocumentValue> } };

export type DocumentBlock =
  | DocumentRichTextBlock
  | DocumentListBlock
  | DocumentTodoBlock
  | DocumentCodeBlock
  | DocumentDividerBlock
  | DocumentCalloutBlock
  | DocumentImageBlock
  | DocumentAttachmentBlock
  | DocumentTableBlock
  | DocumentDataSnapshotBlock;

export type DocumentBody = { schemaVersion: "media.document.body.v1"; blocks: DocumentBlock[] };
export type DocumentArtifactRecord = {
  publicArtifactId: string;
  publicProjectId: string;
  artifactKind: DocumentArtifactKind;
  workspaceMode: "personal_web" | "organization_lark";
  bodyAuthority: DocumentBodyAuthority;
  currentRevision: number;
  updatedAt: string;
  organizationDocumentUrl?: string | null;
  larkDocumentUrl?: string | null;
};
export type DocumentRevisionRecord = {
  publicArtifactId: string;
  artifactKind: DocumentArtifactKind;
  bodyAuthority: DocumentBodyAuthority;
  revision: number;
  baseRevision: number | null;
  state: DocumentRevisionState;
  bodyChecksum: string;
  remoteDocumentVersion: string | null;
  body: DocumentBody;
  createdAt: string;
  updatedAt: string;
};
export type DocumentBodyResponse = { schemaVersion: string; data: { artifact: DocumentArtifactRecord; revision: DocumentRevisionRecord }; revision: number };
export type DocumentRevisionResponse = { schemaVersion: string; data: DocumentRevisionRecord; revision: number };
export type DocumentExportRecord = {
  publicExportId: string;
  publicArtifactId: string;
  revision: number;
  format: DocumentExportFormat;
  state: DocumentExportState;
  templateVersion: string;
  rendererVersion: string;
  sourceBodyChecksum: string;
  contentChecksum: string | null;
  createdAt: string;
  updatedAt: string;
};
export type DocumentExportResponse = { schemaVersion: string; data: DocumentExportRecord; revision: number };
export type DocumentExportDownload = { publicExportId: string; format: DocumentExportFormat; downloadUrl: string; expiresAt: string; contentChecksum: string };
export type DocumentExportDownloadResponse = { schemaVersion: string; data: DocumentExportDownload; revision: number };
export type DocumentSyncBatchState = "queued" | "running" | "succeeded" | "failed" | "conflict";
export type DocumentSyncBatchOperation = "read" | "save";
export type DocumentSyncBatch = {
  publicSyncId: string;
  publicArtifactId: string;
  revision: number;
  operation: DocumentSyncBatchOperation;
  state: DocumentSyncBatchState;
  remoteDocumentVersion: string | null;
  bodyChecksum: string | null;
  blockCount: number | null;
  protectedBlockCount: number | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  errorCode: string | null;
  errorDetail: Record<string, unknown>;
};
export type DocumentSyncBatchListResponse = {
  schemaVersion: string;
  revision: number;
  items: DocumentSyncBatch[];
  nextCursor: string | null;
};

export const DOCUMENT_EXPORT_TEMPLATE_VERSION = "media.document.export.v1" as const;
export const DOCUMENT_EXPORT_RENDERER_VERSION = "media.document.renderer.v1" as const;

export type DocumentSession = { csrfToken: string };
export type DocumentBusinessCaller = <T>(operationId: DocumentOperationId, request?: BusinessOperationRequest) => Promise<T>;
export type If2DocumentApi = {
  getBody: (publicArtifactId: string, signal?: AbortSignal) => Promise<DocumentBodyResponse>;
  saveDraft: (publicArtifactId: string, body: DocumentBody, base: DocumentRevisionRecord, session: DocumentSession, signal?: AbortSignal) => Promise<DocumentRevisionResponse>;
  getRevision: (publicArtifactId: string, revision: number, signal?: AbortSignal) => Promise<DocumentRevisionResponse>;
  createExport: (publicArtifactId: string, revision: number, format: DocumentExportFormat, session: DocumentSession, signal?: AbortSignal) => Promise<DocumentExportResponse>;
  getExport: (publicExportId: string, signal?: AbortSignal) => Promise<DocumentExportResponse>;
  getExportDownload: (publicExportId: string, signal?: AbortSignal) => Promise<DocumentExportDownloadResponse>;
  listSyncBatches: (publicArtifactId: string, cursor?: string, pageSize?: number, signal?: AbortSignal) => Promise<DocumentSyncBatchListResponse>;
};

function defaultCaller<T>(operationId: DocumentOperationId, request: BusinessOperationRequest = {}): Promise<T> {
  return callBusinessOperation<T>(operationId, request);
}

export function createIf2DocumentApi(caller: DocumentBusinessCaller = defaultCaller): If2DocumentApi {
  let draftIdentity: string | null = null;
  let draftIdempotencyKey: string | null = null;

  return {
    getBody: (publicArtifactId, signal) => caller<DocumentBodyResponse>("getDocumentBody", { path: { publicArtifactId }, signal }),
    saveDraft: (publicArtifactId, body, base, session, signal) => {
      const identity = JSON.stringify([publicArtifactId, base.revision, base.bodyChecksum, base.remoteDocumentVersion, body]);
      if (identity !== draftIdentity) {
        draftIdentity = identity;
        draftIdempotencyKey = newIdempotencyKey("document-draft");
      }
      if (!draftIdempotencyKey) throw new DocumentWorkflowInvariantError("草稿幂等标识未生成。");
      return caller<DocumentRevisionResponse>("saveDocumentDraft", {
        path: { publicArtifactId },
        body: {
          expectedRevision: base.revision,
          expectedBodyChecksum: base.bodyChecksum,
          expectedRemoteDocumentVersion: base.remoteDocumentVersion,
          body,
        },
        csrfToken: session.csrfToken,
        idempotencyKey: draftIdempotencyKey,
        signal,
      });
    },
    getRevision: (publicArtifactId, revision, signal) => caller<DocumentRevisionResponse>("getDocumentRevision", { path: { publicArtifactId, revision }, signal }),
    createExport: (publicArtifactId, revision, format, session, signal) => caller<DocumentExportResponse>("createDocumentExport", {
      path: { publicArtifactId },
      body: { revision, format, templateVersion: DOCUMENT_EXPORT_TEMPLATE_VERSION, rendererVersion: DOCUMENT_EXPORT_RENDERER_VERSION },
      csrfToken: session.csrfToken,
      idempotencyKey: `document-export-${publicArtifactId}-${revision}-${format}-${DOCUMENT_EXPORT_TEMPLATE_VERSION}-${DOCUMENT_EXPORT_RENDERER_VERSION}`,
      signal,
    }),
    getExport: (publicExportId, signal) => caller<DocumentExportResponse>("getDocumentExport", { path: { publicExportId }, signal }),
    getExportDownload: (publicExportId, signal) => caller<DocumentExportDownloadResponse>("getDocumentExportDownload", { path: { publicExportId }, signal }),
    listSyncBatches: (publicArtifactId, cursor, pageSize, signal) => caller<DocumentSyncBatchListResponse>("listArtifactSyncBatches", {
      path: { publicArtifactId },
      query: { cursor, pageSize },
      signal,
    }),
  };
}

export class DocumentWorkflowInvariantError extends Error {
  readonly code = "document_workflow_invariant";

  constructor(message: string) {
    super(message);
    this.name = "DocumentWorkflowInvariantError";
  }
}

export type DocumentFailureKind = "conflict" | "protected" | "unsupported" | "permission" | "generic";
export type DocumentFailure = { kind: DocumentFailureKind; code: string; message: string };
type ErrorLike = { status?: unknown; code?: unknown; message?: unknown };

const protectedCodes = new Set(["protected_block", "protected_document_block", "document_protected_block", "document_revision_protected"]);
const unsupportedCodes = new Set(["unsupported_document_block", "lark_table_shape_unsupported"]);

export function classifyDocumentFailure(error: unknown, fallback = "文档操作失败。"): DocumentFailure {
  const value = error && typeof error === "object" ? error as ErrorLike : {};
  const code = typeof value.code === "string" ? value.code : "document_request_failed";
  const status = typeof value.status === "number" ? value.status : undefined;
  const message = typeof value.message === "string" && value.message ? value.message : fallback;
  const kind: DocumentFailureKind = status === 401 || status === 403
    ? "permission"
    : status === 409 || code === "document_revision_conflict"
      ? "conflict"
      : protectedCodes.has(code)
        ? "protected"
        : unsupportedCodes.has(code)
          ? "unsupported"
          : "generic";
  return { kind, code, message };
}

export function assertDocumentBody(value: unknown): asserts value is DocumentBody {
  if (!value || typeof value !== "object") throw new DocumentWorkflowInvariantError("文档正文响应不是对象。");
  const candidate = value as { schemaVersion?: unknown; blocks?: unknown };
  if (candidate.schemaVersion !== "media.document.body.v1") throw new DocumentWorkflowInvariantError("文档正文 schemaVersion 不受支持。");
  if (!Array.isArray(candidate.blocks)) throw new DocumentWorkflowInvariantError("文档正文缺少 blocks。");
  for (const block of candidate.blocks) {
    if (!block || typeof block !== "object") throw new DocumentWorkflowInvariantError("文档正文包含无效块。");
    const record = block as { id?: unknown; type?: unknown };
    if (typeof record.id !== "string" || !record.id || typeof record.type !== "string" || !record.type) {
      throw new DocumentWorkflowInvariantError("文档正文包含缺少编号或类型的块。");
    }
  }
}

export function isSafelyEditableBlock(block: DocumentBlock): block is DocumentRichTextBlock | DocumentCodeBlock {
  if (block.type === "code_block") return true;
  return "content" in block && isRichTextType(block.type) && block.content.length <= 1;
}

export function readEditableBlockText(block: DocumentRichTextBlock | DocumentCodeBlock): string {
  return block.type === "code_block" ? block.text : block.content[0]?.text ?? "";
}

export function replaceBlockText(body: DocumentBody, blockId: string, text: string): DocumentBody {
  let replaced = false;
  const blocks = body.blocks.map((block) => {
    if (block.id !== blockId) return block;
    if (!isSafelyEditableBlock(block)) throw new DocumentWorkflowInvariantError(`正文块不可安全编辑：${blockId}`);
    replaced = true;
    if (block.type === "code_block") return { ...block, text };
    const previous = block.content[0];
    return { ...block, content: [{ type: "text" as const, text, marks: previous?.marks ?? [] }] };
  });
  if (!replaced) throw new DocumentWorkflowInvariantError(`找不到正文块：${blockId}`);
  return { ...body, blocks };
}

function isRichTextType(type: DocumentBlock["type"]): type is DocumentRichTextBlock["type"] {
  return type === "paragraph" || type === "quote" || /^heading_[1-9]$/.test(type);
}

export function isExportableRevision(state: DocumentRevisionState): boolean {
  return state === "ready";
}

export type Sleep = (milliseconds: number, signal?: AbortSignal) => Promise<void>;
export const defaultSleep: Sleep = (milliseconds, signal) => new Promise((resolve, reject) => {
  let timer: ReturnType<typeof globalThis.setTimeout>;
  const cleanup = () => signal?.removeEventListener("abort", abort);
  const finish = () => { cleanup(); resolve(); };
  const abort = () => { globalThis.clearTimeout(timer); cleanup(); reject(new DOMException("The operation was aborted.", "AbortError")); };
  timer = globalThis.setTimeout(finish, milliseconds);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
});

export async function pollDocumentExport(
  api: Pick<If2DocumentApi, "getExport">,
  publicExportId: string,
  options: { signal?: AbortSignal; intervalMs?: number; maxAttempts?: number; sleep?: Sleep; onUpdate?: (record: DocumentExportRecord) => void } = {},
): Promise<DocumentExportRecord> {
  const intervalMs = options.intervalMs ?? 1000;
  const maxAttempts = options.maxAttempts ?? 30;
  const sleep = options.sleep ?? defaultSleep;
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1) throw new DocumentWorkflowInvariantError("导出轮询次数必须为正整数。");
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const response = await api.getExport(publicExportId, options.signal);
    const record = response.data;
    options.onUpdate?.(record);
    if (record.state === "ready" || record.state === "failed") return record;
    if (record.state !== "queued" && record.state !== "rendering") throw new DocumentWorkflowInvariantError(`导出任务状态不受支持：${record.state}`);
    if (attempt + 1 < maxAttempts) await sleep(intervalMs, options.signal);
  }
  throw new DocumentWorkflowInvariantError("导出任务轮询超时。");
}
