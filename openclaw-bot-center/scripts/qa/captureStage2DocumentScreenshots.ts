import assert from "node:assert/strict";
import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { inflateSync } from "node:zlib";
import { isAbsolute, resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import react from "@vitejs/plugin-react";
import {
  chromium,
  type Browser,
  type Locator,
  type Page,
  type Route,
} from "playwright";
import { expect } from "playwright/test";
import { createServer as createViteServer, type ViteDevServer } from "vite";

const TASK_ID = "STAGE2-SCREENSHOT-QA";
const SOURCE_IDENTITY = process.env.STAGE2_DOCUMENT_SOURCE_IDENTITY ?? "workspace";
const mediaBase = "/openclaw/media";
const apiRoot = `${mediaBase}/api`;
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const outputDir = process.env.STAGE2_DOCUMENT_SCREENSHOT_DIR ?? "/tmp/openclaw-stage2-document-screenshots";
const externalBaseUrl = process.env.STAGE2_DOCUMENT_BASE_URL?.replace(/\/$/u, "");
const reviewIdentity = process.env.STAGE2_DOCUMENT_REVIEW_IDENTITY?.trim() || "REVIEW_IDENTITY_PLACEHOLDER";
const execFile = promisify(execFileCallback);

if (!isAbsolute(outputDir)) {
  throw new Error(`STAGE2_DOCUMENT_SCREENSHOT_DIR must be absolute: ${outputDir}`);
}

const viewports = [
  { name: "desktop-1440x900", width: 1440, height: 900, isMobile: false },
  { name: "desktop-1280x800", width: 1280, height: 800, isMobile: false },
  { name: "tablet-1024x768", width: 1024, height: 768, isMobile: false },
  { name: "mobile-390x844", width: 390, height: 844, isMobile: true },
] as const;

type CState =
  | "clean"
  | "dirty"
  | "conflict"
  | "unsupported"
  | "saving"
  | "aiResultProgress"
  | "offlineRetry"
  | "organizationDocument";
type BState =
  | "synced"
  | "running"
  | "unknown"
  | "conflict"
  | "unsupported"
  | "stale"
  | "aiResultProgress"
  | "partialApplication";
type Side = "C" | "B";
type State = CState | BState;
type Viewport = (typeof viewports)[number];

type ApiObservation = {
  method: string;
  path: string;
  operationId: string | null;
  status: number;
  mockedAtBrowserBoundary: true;
};

type CheckRecord = {
  name: string;
  ok: boolean;
  detail: string;
};

type ScreenshotRecord = {
  path: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  uniqueColors: number;
  nonTransparentPixels: number;
};

type PendingContract = {
  reason: string;
  selectorContract: Record<string, unknown>;
  responseContract: Record<string, unknown>;
};

type ManifestEntry = {
  side: Side;
  state: State;
  status: "captured" | "pendingIntegration" | "failed";
  viewport: { name: string; width: number; height: number; isMobile: boolean };
  file: string | null;
  additionalFiles?: string[];
  screenshots: ScreenshotRecord[];
  checks: CheckRecord[];
  api: ApiObservation[];
  requestFailures: string[];
  expectedRequestFailures?: string[];
  consoleErrors: string[];
  expectedConsoleErrors?: string[];
  pageErrors: string[];
  error?: string;
  pendingIntegration?: PendingContract;
};

type Manifest = {
  taskId: string;
  sourceIdentity: string;
  authority: {
    devBrief: string;
    acceptanceExecution: string;
  };
  baseUrl: string;
  outputDirectory: string;
  viewports: typeof viewports;
  sourceGitSha: string | null;
  browserIdentity: { name: string; version: string } | null;
  captureTimestamp: string;
  reviewIdentity: string;
  entries: ManifestEntry[];
  matrixCompleteness: MatrixCompleteness;
  validationFailures: string[];
  summary: {
    requiredCStates: number;
    requiredBStates: number;
    capturedEntries: number;
    pendingIntegrationEntries: number;
    failedEntries: number;
    screenshotFiles: number;
  };
  ok: boolean;
};

type MatrixCompleteness = {
  expectedCells: number;
  observedEntries: number;
  observedCells: number;
  completeCells: number;
  missingCells: number;
  duplicateCells: number;
  unexpectedCells: number;
  pendingCells: number;
  failedCells: number;
  missingScreenshotCells: number;
  requestFailureCells: number;
  unexpectedConsoleErrorCells: number;
  pageErrorCells: number;
  failedCheckCells: number;
};

type MatrixValidation = {
  ok: boolean;
  failures: string[];
  completeness: MatrixCompleteness;
};

type ScreenshotExists = (path: string) => Promise<boolean>;

function derivePendingStates<T extends string>(required: readonly T[], rendered: ReadonlySet<T>): T[] {
  return required.filter((state) => !rendered.has(state));
}

const requiredCStates: readonly CState[] = [
  "clean",
  "dirty",
  "conflict",
  "unsupported",
  "saving",
  "aiResultProgress",
  "offlineRetry",
  "organizationDocument",
];
const requiredBStates: readonly BState[] = [
  "synced",
  "running",
  "unknown",
  "conflict",
  "unsupported",
  "stale",
  "aiResultProgress",
  "partialApplication",
];

const renderedCStates = new Set<CState>([
  "clean",
  "dirty",
  "conflict",
  "unsupported",
  "saving",
  "aiResultProgress",
  "offlineRetry",
  "organizationDocument",
]);
const renderedBStates = new Set<BState>([
  "synced",
  "running",
  "unknown",
  "conflict",
  "unsupported",
  "stale",
  "aiResultProgress",
  "partialApplication",
]);
const pendingC = derivePendingStates(requiredCStates, renderedCStates);
const pendingB = derivePendingStates(requiredBStates, renderedBStates);
const runtimeC = requiredCStates.filter((state) => renderedCStates.has(state));
const runtimeB = requiredBStates.filter((state) => renderedBStates.has(state));

const personalArtifactId = "stage2c-personal-document";
const cleanArtifactId = "stage2c-clean-document";
const organizationArtifactId = "stage2b-organization-document";

const personalSession = {
  publicUserId: "11111111-1111-4111-8111-111111111111",
  organizationName: null,
  memberRole: "owner" as const,
  organizationConnection: "not_applicable" as const,
  installationConnection: "not_applicable" as const,
  role: "ordinary" as const,
  maintainer: false,
  csrfToken: "stage2-document-csrf",
  expiresAt: "2099-01-01T00:00:00+00:00",
  routeGrants: [
    "/today",
    "/studio",
    "/campaigns",
    "/business",
    "/desk",
    "/overview",
    "/assets",
    "/tracks",
    "/decisions",
    "/publishing",
    "/reviews",
    "/media-agent",
    "/archives",
    "/usage-billing",
    "/invites",
    "/workspace",
  ],
  schemaVersion: "media_web_business_pages_v2" as const,
  workspaceMode: "personal_web" as const,
  editorMode: "web_edit" as const,
  bodyAuthority: "internal" as const,
};

const organizationSession = {
  publicUserId: "33333333-3333-4333-8333-333333333333",
  organizationName: "光合内容工作室",
  memberRole: "member" as const,
  organizationConnection: "connected" as const,
  installationConnection: "connected" as const,
  role: "ordinary" as const,
  maintainer: false,
  csrfToken: "stage2-document-org-csrf",
  expiresAt: "2099-01-01T00:00:00+00:00",
  routeGrants: ["/organization-workspace", "/tracks"],
  schemaVersion: "media_web_business_pages_v2" as const,
  workspaceMode: "organization_lark" as const,
  editorMode: "lark_edit" as const,
  bodyAuthority: "lark" as const,
};

const personalBody = {
  schemaVersion: "media.document.body.v1" as const,
  blocks: [
    {
      id: "blk_c_intro",
      type: "paragraph" as const,
      attrs: {},
      content: [{ type: "text" as const, text: "这一份个人正文用于验证编辑、保存和修订链的真实页面路径。", marks: ["bold" as const] }],
    },
    {
      id: "blk_c_heading",
      type: "heading_2" as const,
      attrs: {},
      content: [{ type: "text" as const, text: "一、正文要点", marks: [] }],
    },
    {
      id: "blk_c_quote",
      type: "quote" as const,
      attrs: {},
      content: [{ type: "text" as const, text: "先确认正文，再决定是否保存为新的修订。", marks: ["italic" as const] }],
    },
    {
      id: "blk_c_list",
      type: "bullet_list" as const,
      attrs: {},
      items: [
        {
          id: "blk_c_list_item_1",
          content: [{ type: "text" as const, text: "保留已有事实和证据边界。", marks: [] }],
          children: [],
        },
        {
          id: "blk_c_list_item_2",
          content: [{ type: "text" as const, text: "把可编辑内容和受保护内容分开。", marks: [] }],
          children: [],
        },
      ],
    },
    {
      id: "blk_c_callout",
      type: "callout" as const,
      attrs: { semanticTone: "warning" as const },
      content: [{ type: "text" as const, text: "受保护数据快照只读，保存时必须原样保留。", marks: [] }],
    },
    {
      id: "blk_c_table",
      type: "table" as const,
      attrs: { semanticPurpose: "general" as const, headerRowCount: 1 as const },
      rows: [
        {
          id: "blk_c_table_header",
          cells: [
            { id: "blk_c_table_header_1", content: [{ type: "text" as const, text: "阶段", marks: [] }] },
            { id: "blk_c_table_header_2", content: [{ type: "text" as const, text: "状态", marks: [] }] },
          ],
        },
        {
          id: "blk_c_table_row_1",
          cells: [
            { id: "blk_c_table_row_1_1", content: [{ type: "text" as const, text: "编辑", marks: [] }] },
            { id: "blk_c_table_row_1_2", content: [{ type: "text" as const, text: "可修改", marks: [] }] },
          ],
        },
      ],
    },
    {
      id: "blk_c_snapshot",
      type: "data_snapshot" as const,
      attrs: {
        semanticPurpose: "metric_snapshot" as const,
        publicObjectId: "stage2-object-snapshot",
        sourceRevision: 3,
        capturedAt: "2026-08-29T15:02:00+08:00",
        displayFields: { 样本数: 5, 完成度: "18.4%", 已确认: true },
      },
    },
    {
      id: "blk_c_todo",
      type: "todo_item" as const,
      attrs: { checked: false },
      content: [{ type: "text" as const, text: "保存前检查未完成事项", marks: [] }],
    },
  ],
};

const organizationBody = {
  schemaVersion: "media.document.body.v1" as const,
  blocks: [
    {
      id: "blk_b_intro",
      type: "paragraph" as const,
      attrs: {},
      content: [{ type: "text" as const, text: "这是一份组织正文的回读镜像，飞书是唯一编辑权威。", marks: ["bold" as const] }],
    },
    {
      id: "blk_b_heading",
      type: "heading_2" as const,
      attrs: {},
      content: [{ type: "text" as const, text: "一、组织交付要点", marks: [] }],
    },
    {
      id: "blk_b_quote",
      type: "quote" as const,
      attrs: {},
      content: [{ type: "text" as const, text: "网页端只展示回读结果，不承担组织正文编辑职责。", marks: ["italic" as const] }],
    },
    {
      id: "blk_b_list",
      type: "bullet_list" as const,
      attrs: {},
      items: [
        {
          id: "blk_b_list_item_1",
          content: [{ type: "text" as const, text: "正文版本来自当前组织绑定。", marks: [] }],
          children: [],
        },
        {
          id: "blk_b_list_item_2",
          content: [{ type: "text" as const, text: "网页端保留只读镜像和追溯信息。", marks: [] }],
          children: [],
        },
      ],
    },
    {
      id: "blk_b_callout",
      type: "callout" as const,
      attrs: { semanticTone: "info" as const },
      content: [{ type: "text" as const, text: "需要修改时，请在飞书中打开这篇文档。", marks: [] }],
    },
    {
      id: "blk_b_table",
      type: "table" as const,
      attrs: { semanticPurpose: "publishing_checklist" as const, headerRowCount: 1 as const },
      rows: [
        {
          id: "blk_b_table_header",
          cells: [
            { id: "blk_b_table_header_1", content: [{ type: "text" as const, text: "阶段", marks: [] }] },
            { id: "blk_b_table_header_2", content: [{ type: "text" as const, text: "负责人", marks: [] }] },
          ],
        },
        {
          id: "blk_b_table_row_1",
          cells: [
            { id: "blk_b_table_row_1_1", content: [{ type: "text" as const, text: "品牌确认", marks: [] }] },
            { id: "blk_b_table_row_1_2", content: [{ type: "text" as const, text: "组织成员", marks: [] }] },
          ],
        },
      ],
    },
    {
      id: "blk_b_snapshot",
      type: "data_snapshot" as const,
      attrs: {
        semanticPurpose: "evidence_index" as const,
        publicObjectId: "stage2-remote-snapshot",
        sourceRevision: 14,
        capturedAt: "2026-09-01T11:26:00+08:00",
        displayFields: { 排期天数: 12, 交付条数: 3, 商务字段: null },
      },
    },
  ],
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function documentArtifact(
  publicArtifactId: string,
  workspaceMode: "personal_web" | "organization_lark",
  bodyAuthority: "internal" | "lark",
) {
  return {
    publicArtifactId,
    publicProjectId: workspaceMode === "personal_web" ? "stage2c-project" : "stage2b-project",
    artifactKind: "creation_document" as const,
    workspaceMode,
    bodyAuthority,
    currentRevision: workspaceMode === "personal_web" ? 7 : 14,
    updatedAt: "2026-09-01T11:26:00+08:00",
    organizationDocumentUrl: workspaceMode === "organization_lark" ? "https://example.feishu.cn/docx/stage2remote" : null,
    larkDocumentUrl: workspaceMode === "organization_lark" ? "https://example.feishu.cn/docx/stage2remote" : null,
  };
}

function documentRevision(
  artifactId: string,
  bodyAuthority: "internal" | "lark",
  body: typeof personalBody | typeof organizationBody,
  revision: number,
  remoteDocumentVersion: string | null,
) {
  return {
    publicArtifactId: artifactId,
    artifactKind: "creation_document" as const,
    bodyAuthority,
    revision,
    baseRevision: revision > 1 ? revision - 1 : null,
    state: "ready" as const,
    bodyChecksum: createHash("sha256").update(JSON.stringify(body)).digest("hex"),
    remoteDocumentVersion,
    body: clone(body),
    createdAt: "2026-09-01T11:20:00+08:00",
    updatedAt: "2026-09-01T11:26:00+08:00",
  };
}

function organizationReadyExecutionReceipt() {
  return {
    status: "ready" as const,
    applied: [{ operation: "replace_text" as const, blockId: "blk_b_intro" }],
    appliedCount: 1,
    manualActions: [{ reason: "protected_block", blockId: "blk_b_snapshot" }],
    protectedSkipped: ["blk_b_snapshot"],
  };
}

function bodyResponse(mock: MockState) {
  const isPersonal = mock.workspaceMode === "personal_web";
  const artifactId = mock.artifactId;
  const body = isPersonal ? personalBody : organizationBody;
  const revision = isPersonal
    ? documentRevision(artifactId, "internal", body, 7, null)
    : documentRevision(artifactId, "lark", body, 14, "v14");
  const executionReceipt =
    mock.side === "B" && mock.state === "aiResultProgress"
      ? organizationReadyExecutionReceipt()
      : undefined;
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision: revision.revision,
    data: {
      artifact: documentArtifact(artifactId, isPersonal ? "personal_web" : "organization_lark", isPersonal ? "internal" : "lark"),
      revision: executionReceipt ? { ...revision, executionReceipt } : revision,
    },
  };
}

function revisionResponse(
  mock: MockState,
  artifactId: string,
  state: "generating" | "ready",
) {
  const isPersonal = mock.workspaceMode === "personal_web";
  const body = isPersonal ? clone(personalBody) : clone(organizationBody);
  if (isPersonal && state === "ready") {
    const first = body.blocks.find((block) => block.id === "blk_c_intro");
    if (first && "content" in first && first.content?.[0]) first.content[0].text = "AI 改稿结果已回到个人正文，等待你确认采用。";
  }
  const revision = documentRevision(
    artifactId,
    isPersonal ? "internal" : "lark",
    body,
    isPersonal ? 8 : 15,
    isPersonal ? null : "v15",
  );
  const receipt = !isPersonal && state === "ready"
    ? organizationReadyExecutionReceipt()
    : undefined;
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision: revision.revision,
    data: { ...revision, state, ...(receipt ? { executionReceipt: receipt } : {}) },
  };
}

function syncBatchesResponse(mock: MockState) {
  const state: BState = mock.state === "organizationDocument" ? "synced" : mock.state as BState;
  const itemByState: Record<Exclude<BState, "aiResultProgress">, Record<string, unknown>> = {
    synced: { state: "succeeded", operation: "read", remoteDocumentVersion: "v14", errorCode: null, errorDetail: {} },
    running: { state: "running", operation: "save", remoteDocumentVersion: null, errorCode: null, errorDetail: {} },
    unknown: { state: "running", operation: "save", remoteDocumentVersion: null, errorCode: "lark_save_outcome_unknown", errorDetail: {} },
    conflict: { state: "conflict", operation: "save", remoteDocumentVersion: "v15", errorCode: "document_remote_version_conflict", errorDetail: {} },
    unsupported: { state: "failed", operation: "save", remoteDocumentVersion: null, errorCode: "unsupported_document_block", errorDetail: { blockIds: ["blk_b_table"] } },
    stale: { state: "succeeded", operation: "read", remoteDocumentVersion: "v15", errorCode: null, errorDetail: {} },
    partialApplication: { state: "succeeded", operation: "save", remoteDocumentVersion: "v14", errorCode: null, errorDetail: { applied: ["blk_b_intro"], manualActions: ["blk_b_snapshot"], protectedSkipped: ["blk_b_snapshot"] } },
  };
  const selected = itemByState[state === "aiResultProgress" ? "synced" : state];
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision: 15,
    items: [{
      publicSyncId: `stage2-sync-${state}`,
      publicArtifactId: mock.artifactId,
      revision: state === "synced" ? 14 : 15,
      bodyChecksum: "b".repeat(64),
      blockCount: organizationBody.blocks.length,
      protectedBlockCount: 1,
      createdAt: "2026-09-01T11:25:00+08:00",
      updatedAt: "2026-09-01T11:26:00+08:00",
      completedAt: state === "running" || state === "unknown" ? null : "2026-09-01T11:26:00+08:00",
      ...selected,
    }],
    nextCursor: null,
  };
}

function operationIdFor(path: string, method: string): string | null {
  if (method === "GET" && path === "/session") return "getMediaSession";
  if (method === "GET" && path === "/capabilities") return "listMediaCapabilities";
  if (method === "GET" && path === "/tasks") return "listMediaTasks";
  if (method === "GET" && /^\/documents\/[^/]+\/body$/u.test(path)) return "getDocumentBody";
  if (method === "PUT" && /^\/documents\/[^/]+\/draft$/u.test(path)) return "saveDocumentDraft";
  if (method === "POST" && /^\/artifacts\/[^/]+\/revisions$/u.test(path)) return "createArtifactRevision";
  if (method === "GET" && /^\/documents\/[^/]+\/revisions\/\d+$/u.test(path)) return "getDocumentRevision";
  if (method === "GET" && /^\/artifacts\/[^/]+\/sync-batches$/u.test(path)) return "listArtifactSyncBatches";
  return null;
}

async function fulfillJson(route: Route, payload: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

type MockState = {
  side: Side;
  state: State;
  workspaceMode: "personal_web" | "organization_lark";
  artifactId: string;
  requests: ApiObservation[];
  unhandled: ApiObservation[];
  aiRevisionReads: number;
  offline: boolean;
  releaseSaving: (() => void) | null;
  savingGate: Promise<void> | null;
};

function createMockState(side: Side, state: State): MockState {
  const organizationCapture = side === "B" || (side === "C" && state === "organizationDocument");
  let releaseSaving: (() => void) | null = null;
  let savingGate: Promise<void> | null = null;
  if (side === "C" && state === "saving") {
    savingGate = new Promise<void>((resolveGate) => {
      releaseSaving = resolveGate;
    });
  }
  return {
    side,
    state,
    workspaceMode: organizationCapture ? "organization_lark" : "personal_web",
    artifactId: organizationCapture
      ? organizationArtifactId
      : state === "clean" ? cleanArtifactId : personalArtifactId,
    requests: [],
    unhandled: [],
    aiRevisionReads: 0,
    offline: false,
    releaseSaving,
    savingGate,
  };
}

async function installApi(page: Page, mock: MockState): Promise<void> {
  await page.route(`**${apiRoot}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(apiRoot, "") || "/";
    const method = request.method();
    const operationId = operationIdFor(path, method);
    const record: ApiObservation = {
      method,
      path,
      operationId,
      status: 200,
      mockedAtBrowserBoundary: true,
    };
    mock.requests.push(record);

    if (method === "GET" && path === "/session") {
      await fulfillJson(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        session: mock.workspaceMode === "personal_web" ? personalSession : organizationSession,
      });
      return;
    }
    if (method === "GET" && path === "/capabilities") {
      await fulfillJson(route, {
        schemaVersion: "capability_catalog_v3",
        catalogVersion: `sha256:${"0".repeat(64)}`,
        capabilities: [],
      });
      return;
    }
    if (method === "GET" && path === "/tasks") {
      await fulfillJson(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        items: [],
        nextCursor: null,
        tasks: [],
      });
      return;
    }
    if (method === "GET" && path === `/documents/${mock.artifactId}/body`) {
      await fulfillJson(route, bodyResponse(mock));
      return;
    }
    if (method === "POST" && path === `/artifacts/${mock.artifactId}/revisions`) {
      await fulfillJson(route, {
        schemaVersion: "media.document.revision.v1",
        revision: mock.workspaceMode === "personal_web" ? 8 : 15,
        item: { currentRevision: mock.workspaceMode === "personal_web" ? 8 : 15 },
      });
      return;
    }
    if (method === "GET" && new RegExp(`^/documents/${mock.artifactId}/revisions/\\d+$`, "u").test(path)) {
      mock.aiRevisionReads += 1;
      await fulfillJson(route, revisionResponse(mock, mock.artifactId, mock.aiRevisionReads === 1 ? "generating" : "ready"));
      return;
    }
    if (method === "GET" && path === `/artifacts/${mock.artifactId}/sync-batches`) {
      await fulfillJson(route, syncBatchesResponse(mock));
      return;
    }
    if (method === "PUT" && path === `/documents/${mock.artifactId}/draft`) {
      if (mock.offline) {
        record.status = 0;
        await route.abort("internetdisconnected");
        return;
      }
      if (mock.workspaceMode === "personal_web" && mock.state === "conflict") {
        record.status = 409;
        await fulfillJson(route, {
          ok: false,
          error: { code: "document_revision_conflict", message: "远端正文已有更新，请先重新读取。" },
        }, 409);
        return;
      }
      if (mock.workspaceMode === "personal_web" && mock.state === "unsupported") {
        record.status = 422;
        await fulfillJson(route, {
          ok: false,
          error: {
            code: "unsupported_document_block",
            message: "部分正文结构暂不能保存。",
            details: { blockIds: ["blk_c_table"] },
          },
        }, 422);
        return;
      }
      if (mock.workspaceMode === "personal_web" && mock.state === "saving") {
        assert(mock.savingGate, "saving state did not initialize a response gate");
        await mock.savingGate;
      }
      const posted = request.postDataJSON() as { body?: unknown } | null;
      const savedBody = posted?.body && typeof posted.body === "object" ? posted.body : personalBody;
      const savedRevision = documentRevision(mock.artifactId, "internal", savedBody as typeof personalBody, 8, null);
      await fulfillJson(route, {
        schemaVersion: "media.document.revision.v1",
        revision: 8,
        data: savedRevision,
      });
      return;
    }

    record.status = 500;
    mock.unhandled.push(record);
    await fulfillJson(route, {
      ok: false,
      error: { code: "unexpected_stage2_document_qa_request", message: `${method} ${path}` },
    }, 500);
  });
}

function attachDiagnostics(page: Page): {
  consoleErrors: string[];
  pageErrors: string[];
  requestFailures: string[];
} {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    requestFailures.push(`${request.method()} ${new URL(request.url()).pathname} ${request.failure()?.errorText ?? "unknown"}`);
  });
  return { consoleErrors, pageErrors, requestFailures };
}

async function waitForCPage(page: Page): Promise<Locator> {
  const root = page.locator('main[data-document-editor="true"]');
  await expect(root).toBeVisible({ timeout: 10_000 });
  await expect(root.getByRole("heading", { name: "正文编辑", exact: true })).toBeVisible();
  return root;
}

async function waitForBPage(page: Page): Promise<Locator> {
  const root = page.locator('main[data-read-only-mirror="true"]');
  await expect(root).toBeVisible({ timeout: 10_000 });
  await expect(root.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(root.getByText("只读镜像", { exact: true }).first()).toBeVisible();
  return root;
}

async function saveDraftAndWait(page: Page, artifactId: string): Promise<void> {
  const response = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "PUT" && url.pathname === `${apiRoot}/documents/${artifactId}/draft`;
  }, { timeout: 10_000 });
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await response;
}

async function driveCState(
  page: Page,
  mock: MockState,
  state: CState,
  primaryPath: string,
): Promise<{ root: Locator; anchor: Locator; anchorDetail: string; additional: ScreenshotRecord[] }> {
  if (state === "organizationDocument") {
    const root = await waitForBPage(page);
    await expect(root).toHaveAttribute("data-page-ownership", "organization");
    await expect(root).toHaveAttribute("data-workspace-mode", "organization_lark");
    await expect(root).toHaveAttribute("data-document-sync-state", "synced");
    const anchor = root.getByText("只读镜像", { exact: true }).first();
    await expect(anchor).toBeVisible();
    await expect(root.getByRole("link", { name: "在飞书中打开", exact: true })).toBeVisible();
    await expect(root.locator('[contenteditable="true"]')).toHaveCount(0);
    return { root, anchor, anchorDetail: "个人原型的组织状态已切换到组织只读镜像路由。", additional: [] };
  }
  const root = await waitForCPage(page);
  const editor = page.getByLabel("段落", { exact: true }).first();
  const changedText = "这是一处已在编辑区产生的待保存修改。";
  const additional: ScreenshotRecord[] = [];

  if (state === "clean") {
    const anchor = root.getByText(/当前版本\s+v7\s+·\s+个人正文/u).first();
    await expect(anchor).toBeVisible();
    return { root, anchor, anchorDetail: "当前版本和个人正文权威已加载。", additional };
  }
  if (state === "dirty") {
    await editor.fill(changedText);
    await expect(editor).toHaveValue(changedText);
    return { root, anchor: editor, anchorDetail: "编辑器中的段落已变更且尚未提交。", additional };
  }
  if (state === "conflict") {
    await editor.fill(changedText);
    await saveDraftAndWait(page, mock.artifactId);
    const anchor = root.getByRole("alert").filter({ hasText: "这篇正文已在别处更新" });
    await expect(anchor).toBeVisible();
    await expect(root.getByRole("button", { name: "逐段对比并合并", exact: true })).toBeDisabled();
    await expect(root.getByRole("button", { name: "放弃本地修改并载入最新正文", exact: true })).toBeVisible();
    return { root, anchor, anchorDetail: "409 冲突横幅和三个处置出口可见，逐段对比入口按当前产品状态置灰。", additional };
  }
  if (state === "unsupported") {
    await editor.fill(changedText);
    await saveDraftAndWait(page, mock.artifactId);
    const anchor = root.getByRole("alert").filter({ hasText: "部分正文未通过校验" });
    await expect(anchor).toBeVisible();
    await expect(root.getByRole("button", { name: "跳到第一个问题块", exact: true })).toBeVisible();
    await expect(root.locator('[data-editor-block-id="blk_c_table"]')).toHaveClass(/invalid/u);
    return { root, anchor, anchorDetail: "422 响应的块标识被投影为高亮和仅保存其余正文出口。", additional };
  }
  if (state === "saving") {
    await editor.fill(changedText);
    const response = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "PUT" && url.pathname === `${apiRoot}/documents/${mock.artifactId}/draft`;
    }, { timeout: 10_000 });
    await page.getByRole("button", { name: "保存", exact: true }).click();
    const anchor = root.getByRole("status").filter({ hasText: "保存中" });
    await expect(anchor).toBeVisible();
    await expect(anchor.getByText("校验正文", { exact: true })).toBeVisible();
    additional.push(await saveScreenshot(page, primaryPath));
    mock.releaseSaving?.();
    await response;
    return { root, anchor, anchorDetail: "保存中横幅在写入响应返回前可见，并列出三步写入流程。", additional };
  }
  if (state === "offlineRetry") {
    await editor.fill(changedText);
    const context = page.context();
    await context.setOffline(true);
    mock.offline = true;
    await page.evaluate(() => {
      Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    });
    await page.getByRole("button", { name: "保存", exact: true }).click();
    const anchor = root.getByRole("alert");
    await expect(anchor).toBeVisible();
    await expect(root.getByRole("button", { name: "重试保存", exact: true })).toBeVisible();
    additional.push(await saveScreenshot(page, primaryPath));
    await context.setOffline(false);
    mock.offline = false;
    await page.evaluate(() => {
      Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    });
    const response = page.waitForResponse((candidate) => {
      const url = new URL(candidate.url());
      return candidate.request().method() === "PUT" && url.pathname === `${apiRoot}/documents/${mock.artifactId}/draft`;
    }, { timeout: 10_000 });
    await root.getByRole("button", { name: "重试保存", exact: true }).click();
    await response;
    await expect(anchor).toBeHidden();
    await expect(editor).toHaveValue(changedText);
    await expect(root.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
    return { root, anchor, anchorDetail: "断网横幅保留草稿并提供恢复后的重试按钮。", additional };
  }
  if (state === "aiResultProgress") {
    const request = page.getByRole("textbox", { name: "改稿要求", exact: true });
    await request.fill("把正文开头改得更清楚");
    await page.getByRole("button", { name: "生成改稿修订", exact: true }).click();
    const progressAnchor = page.getByRole("button", { name: "正在生成", exact: true });
    await expect(progressAnchor).toBeVisible();
    const progressPath = resolve(outputDir, `C-aiResultProgress-${viewportName(page)}-progress.png`);
    additional.push(await saveScreenshot(page, progressPath));
    const resultAnchor = root.getByText("改稿修订已就绪。", { exact: true });
    await expect(resultAnchor).toBeVisible({ timeout: 15_000 });
    await expect(root.getByRole("button", { name: "载入此修订", exact: true })).toBeVisible();
    return { root, anchor: resultAnchor, anchorDetail: "同一浏览器流程先观察 AI 生成中，再等待可采用修订结果。", additional };
  }
  throw new Error(`Unsupported C capture state reached driveCState: ${state}`);
}

async function driveBState(
  page: Page,
  mock: MockState,
  state: BState,
): Promise<{ root: Locator; anchor: Locator; anchorDetail: string; additional: ScreenshotRecord[] }> {
  const root = await waitForBPage(page);
  const additional: ScreenshotRecord[] = [];
  if (state === "aiResultProgress") {
    await expect(root).toHaveAttribute("data-ai-feature-flag", "on");
    await expect(root).toHaveAttribute("data-ai-execution-receipt", "available");
    const request = root.getByRole("textbox", { name: "改稿要求", exact: true });
    await request.fill("把正文开头改得更清楚");
    await root.getByRole("button", { name: "生成改稿修订", exact: true }).click();
    const progressAnchor = root.getByRole("button", { name: "正在生成", exact: true });
    await expect(progressAnchor).toBeVisible();
    const progressPath = resolve(outputDir, `B-aiResultProgress-${viewportName(page)}-progress.png`);
    additional.push(await saveScreenshot(page, progressPath));
    const resultAnchor = root.getByText("改稿修订已就绪。", { exact: true });
    await expect(resultAnchor).toBeVisible({ timeout: 15_000 });
    await expect(root).toHaveAttribute("data-ai-state", "ready");
    await expect(root.getByText("已应用", { exact: true })).toBeVisible();
    await expect(root.getByText("需要人工处理", { exact: true })).toBeVisible();
    await expect(root.getByText("受保护未改动", { exact: true })).toBeVisible();
    const load = root.getByRole("button", { name: "载入此修订", exact: true });
    await expect(load).toBeVisible();
    await load.click();
    await expect(root.getByText("已载入改稿修订", { exact: false })).toBeVisible();
    return { root, anchor: resultAnchor, anchorDetail: "同一浏览器流程先观察组织 AI 生成中，再验证服务端修订回读、执行回执和只读预览。", additional };
  }
  const syncState = state === "partialApplication" ? "partial" : state;
  await expect(root).toHaveAttribute("data-ai-feature-flag", "off");
  await expect(root.locator('[data-ai-feature-flag="on"]')).toHaveCount(0);
  await expect(root).toHaveAttribute("data-document-sync-state", syncState);
  await expect(root.locator(`[data-sync-pipeline="${syncState}"]`)).toBeVisible();
  const anchor = syncState === "synced"
    ? root.getByText("镜像版本", { exact: false }).first()
    : root.locator(`[data-sync-state="${syncState}"]`).first();
  await expect(anchor).toBeVisible();
  await expect(root.getByText("飞书", { exact: true }).first()).toBeVisible();
  await expect(root.getByText("回读正文", { exact: true })).toBeVisible();
  if (syncState === "running") await expect(root.locator('[data-sync-step-state="running"]')).toBeVisible();
  if (syncState === "unknown") await expect(root.locator('button[data-sync-action="reconcile"]')).toBeVisible();
  if (syncState === "unsupported") await expect(root.locator('[data-block-id="blk_b_table"][data-document-state="unsupported"]')).toBeVisible();
  if (syncState === "partial") await expect(root.getByText("需要人工处理", { exact: true })).toBeVisible();
  return { root, anchor, anchorDetail: `组织镜像页展示 ${syncState} 的服务端同步批次投影、四步链路与只读正文。`, additional };
}

async function assertNoHorizontalOverflow(page: Page): Promise<{ ok: boolean; detail: string }> {
  const metrics = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const root = document.querySelector<HTMLElement>("main[data-document-editor], main[data-read-only-mirror]");
    return {
      viewportWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      rootWidth: root?.scrollWidth ?? -1,
      rootClientWidth: root?.clientWidth ?? -1,
    };
  });
  const ok = metrics.documentWidth <= metrics.viewportWidth + 1 &&
    metrics.bodyWidth <= metrics.viewportWidth + 1 &&
    (metrics.rootWidth < 0 || metrics.rootWidth <= metrics.rootClientWidth + 1);
  return { ok, detail: JSON.stringify(metrics) };
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

function inspectPng(data: Buffer): Omit<ScreenshotRecord, "path" | "sha256" | "bytes"> {
  assert.equal(data.subarray(0, 8).toString("hex"), "89504e470d0a1a0a", "screenshot is not a PNG");
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idat: Buffer[] = [];
  while (offset < data.length) {
    const length = data.readUInt32BE(offset);
    const type = data.subarray(offset + 4, offset + 8).toString("ascii");
    const chunk = data.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;
    if (type === "IHDR") {
      width = chunk.readUInt32BE(0);
      height = chunk.readUInt32BE(4);
      bitDepth = chunk[8] ?? 0;
      colorType = chunk[9] ?? 0;
      assert.equal(chunk[12], 0, "interlaced screenshots are unsupported by the nonblank checker");
    } else if (type === "IDAT") {
      idat.push(chunk);
    } else if (type === "IEND") {
      break;
    }
  }
  assert.ok(width > 0 && height > 0, "screenshot has no dimensions");
  assert.equal(bitDepth, 8, "screenshot bit depth changed; update the nonblank checker");
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : 0;
  assert.ok(channels > 0, `unsupported PNG color type: ${colorType}`);
  const rowLength = width * channels;
  const inflated = inflateSync(Buffer.concat(idat));
  let cursor = 0;
  let previous = Buffer.alloc(rowLength);
  const colors = new Set<string>();
  let nonTransparentPixels = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[cursor++];
    assert.notEqual(filter, undefined, "PNG scanline is truncated");
    const row = Buffer.from(inflated.subarray(cursor, cursor + rowLength));
    cursor += rowLength;
    for (let index = 0; index < row.length; index += 1) {
      const left = index >= channels ? row[index - channels]! : 0;
      const up = previous[index] ?? 0;
      const upperLeft = index >= channels ? previous[index - channels]! : 0;
      const value = row[index]!;
      row[index] = filter === 0
        ? value
        : filter === 1
          ? (value + left) & 255
          : filter === 2
            ? (value + up) & 255
            : filter === 3
              ? (value + Math.floor((left + up) / 2)) & 255
              : filter === 4
                ? (value + paeth(left, up, upperLeft)) & 255
                : (() => { throw new Error(`unsupported PNG filter: ${filter}`); })();
    }
    for (let x = 0; x < width; x += 1) {
      const index = x * channels;
      colors.add(`${row[index]}-${row[index + 1]}-${row[index + 2]}`);
      if (channels === 3 || row[index + 3] !== 0) nonTransparentPixels += 1;
      if (colors.size > 64) colors.delete(colors.values().next().value as string);
    }
    previous = row;
  }
  return { width, height, uniqueColors: colors.size, nonTransparentPixels };
}

async function saveScreenshot(page: Page, path: string): Promise<ScreenshotRecord> {
  await page.screenshot({ path, fullPage: true, animations: "disabled" });
  const data = await readFile(path);
  const inspected = inspectPng(data);
  assert.ok(inspected.uniqueColors >= 5, `screenshot appears blank: ${path}`);
  assert.ok(inspected.nonTransparentPixels > 0, `screenshot has no visible pixels: ${path}`);
  return {
    path,
    sha256: createHash("sha256").update(data).digest("hex"),
    bytes: data.length,
    ...inspected,
  };
}

function statePath(side: Side, state: State, viewport: Viewport): string {
  return resolve(outputDir, `${side}-${state}-${viewport.name}.png`);
}

function routePathFor(mock: MockState): string {
  return mock.workspaceMode === "personal_web"
    ? `${mediaBase}/workspace/edit/${mock.artifactId}`
    : `${mediaBase}/organization-workspace/document/${mock.artifactId}`;
}

function viewportName(page: Page): string {
  const size = page.viewportSize();
  const viewport = viewports.find((candidate) => candidate.width === size?.width && candidate.height === size?.height);
  assert.ok(viewport, `unsupported screenshot viewport: ${size ? `${size.width}x${size.height}` : "unknown"}`);
  return viewport.name;
}

function expectedConsoleErrors(mock: MockState, errors: string[]): string[] {
  if (mock.side === "C" && (mock.state === "conflict" || mock.state === "unsupported")) {
    return errors.filter((message) => /status of (?:409|422)\b/u.test(message));
  }
  if (mock.side === "C" && mock.state === "offlineRetry") {
    return errors.filter((message) => /ERR_INTERNET_DISCONNECTED/u.test(message));
  }
  return [];
}

function expectedRequestFailures(mock: MockState, failures: string[]): string[] {
  const expected: string[] = [];
  const offlineDraftFailure = `PUT ${apiRoot}/documents/${mock.artifactId}/draft net::ERR_INTERNET_DISCONNECTED`;
  const organizationReadPaths = new Set([
    `${apiRoot}/documents/${mock.artifactId}/body`,
    `${apiRoot}/artifacts/${mock.artifactId}/sync-batches`,
  ]);

  for (const failure of failures) {
    if (expected.includes(failure)) continue;
    if (mock.side === "C" && mock.state === "offlineRetry" && failure === offlineDraftFailure) {
      expected.push(failure);
      continue;
    }
    const readMatch = /^GET (\S+) net::ERR_ABORTED$/u.exec(failure);
    const fullReadPath = readMatch?.[1];
    const relativeReadPath = fullReadPath?.startsWith(apiRoot) ? fullReadPath.slice(apiRoot.length) : undefined;
    if (
      mock.workspaceMode === "organization_lark" &&
      readMatch !== null &&
      organizationReadPaths.has(readMatch[1]!) &&
      relativeReadPath !== undefined &&
      mock.requests.some((request) => request.method === "GET" && request.path === relativeReadPath && request.status === 200)
    ) {
      expected.push(failure);
    }
  }
  return expected;
}

function unexpectedRequestFailures(mock: MockState, failures: string[]): string[] {
  const expected = [...expectedRequestFailures(mock, failures)];
  return failures.filter((failure) => {
    const index = expected.indexOf(failure);
    if (index < 0) return true;
    expected.splice(index, 1);
    return false;
  });
}

function pendingContract(side: Side, state: State): PendingContract {
  if (side === "C" && state === "organizationDocument") {
    return {
      reason: "个人原型的组织只读状态尚未接入组织镜像路由，不能用个人编辑页代替。",
      selectorContract: {
        root: 'main[data-read-only-mirror="true"][data-workspace-mode="organization_lark"]',
        mirrorBadge: 'main[data-read-only-mirror="true"] .mg-badge',
        organizationLink: 'main[data-read-only-mirror="true"] a.mg-btn',
      },
      responseContract: {
        operationId: "getDocumentBody",
        method: "GET",
        path: "/documents/{publicArtifactId}/body",
        artifact: { workspaceMode: "organization_lark", bodyAuthority: "lark" },
      },
    };
  }
  if (side === "C" && state === "unsupported") {
    return {
      reason: "当前 DocumentEditorPage 会识别 unsupported_document_block，但 BusinessOperationError 丢弃 error.details.blockIds，因此 invalidBlocks 永远为空，422 横幅不能被真实页面渲染。",
      selectorContract: {
        root: 'main[data-document-editor="true"]',
        banner: 'main[data-document-editor="true"] section[role="alert"][data-document-state="unsupported"]',
        requiredVisibleText: "部分正文未通过校验",
        highlightedBlock: 'main[data-document-editor="true"] [data-block-id="<blockId>"][data-document-state="unsupported"]',
        action: 'main[data-document-editor="true"] button[name="仅保存其余正文"]',
      },
      responseContract: {
        operationId: "saveDocumentDraft",
        method: "PUT",
        path: "/documents/{publicArtifactId}/draft",
        status: 422,
        json: {
          ok: false,
          error: {
            code: "unsupported_document_block",
            message: "人话说明",
            details: { blockIds: ["blk_c_table"] },
          },
        },
        integrationNote: "前端错误对象必须保留 details.blockIds，或由 callBusinessOperation 映射为 error.blockIds；否则页面现有 invalidBlocks 分支不可达。",
      },
    };
  }
  const commonRoot = 'main[data-read-only-mirror="true"]';
  const syncState = state === "partialApplication" ? "partial" : state;
  if (state === "aiResultProgress") {
    return {
      reason: "组织镜像页当前只有 getDocumentBody 的只读正文，没有 AI dock 或修订轮询呈现。",
      selectorContract: {
        root: `${commonRoot}[data-ai-state="generating|ready"]`,
        progress: `${commonRoot} [data-ai-state="generating"]`,
        result: `${commonRoot} [data-ai-state="ready"]`,
        resultAction: `${commonRoot} button[name="载入此修订"]`,
      },
      responseContract: {
        operationIds: ["createArtifactRevision", "getDocumentRevision"],
        create: { method: "POST", path: "/artifacts/{publicArtifactId}/revisions", body: { expectedRevision: 14, instruction: "string", mode: "regenerate" } },
        pollStates: ["generating", "ready", "failed"],
      },
    };
  }
  const responseByState: Record<string, Record<string, unknown>> = {
    running: { state: "running", operation: "save", completedAt: null },
    unknown: { state: "running", operation: "save", errorCode: "lark_save_outcome_unknown", completedAt: null },
    conflict: { state: "conflict", operation: "save", errorCode: "remote_document_conflict", completedAt: "2026-09-01T11:26:00+08:00" },
    unsupported: { state: "failed", operation: "save", errorCode: "lark_table_shape_unsupported", errorDetail: { blockIds: ["blk_b_table"] } },
    stale: { state: "succeeded", operation: "read", remoteDocumentVersion: "v15", completedAt: "2026-09-01T11:26:00+08:00" },
    partialApplication: { state: "succeeded", operation: "save", errorDetail: { applied: ["blk_b_intro"], manualActions: ["blk_b_snapshot"], protectedSkipped: ["blk_b_snapshot"] } },
  };
  return {
    reason: `组织镜像页当前没有同步状态 ${state} 的 banner、批次账本或动作出口；页面只渲染 getDocumentBody 的 ready 正文。`,
    selectorContract: {
      root: `${commonRoot}[data-document-sync-state="${syncState}"]`,
      banner: `${commonRoot} section[role="alert"][data-document-sync-state="${syncState}"]`,
      stateAnchor: `${commonRoot} [data-sync-state="${syncState}"]`,
      action: state === "running" || state === "unknown" ? `${commonRoot} button[data-sync-action]` : `${commonRoot} button[data-sync-action="reread"]`,
    },
    responseContract: {
      operationId: "listArtifactSyncBatches",
      method: "GET",
      path: "/artifacts/{publicArtifactId}/sync-batches",
      query: { cursor: "optional", pageSize: "optional" },
      itemContract: responseByState[state],
      schemaFields: ["publicSyncId", "revision", "operation", "state", "remoteDocumentVersion", "completedAt", "errorCode", "errorDetail"],
    },
  };
}

function pendingEntries(): ManifestEntry[] {
  const entries: ManifestEntry[] = [];
  for (const viewport of viewports) {
    for (const state of pendingC) {
      const contract = pendingContract("C", state);
      entries.push({
        side: "C",
        state,
        status: "pendingIntegration",
        viewport,
        file: null,
        screenshots: [],
        checks: [
          { name: "pendingIntegration", ok: false, detail: contract.reason },
          { name: "selectorContract", ok: false, detail: JSON.stringify(contract.selectorContract) },
          { name: "responseContract", ok: false, detail: JSON.stringify(contract.responseContract) },
        ],
        api: [],
        requestFailures: [],
        consoleErrors: [],
        pageErrors: [],
        pendingIntegration: contract,
      });
    }
    for (const state of pendingB) {
      const contract = pendingContract("B", state);
      entries.push({
        side: "B",
        state,
        status: "pendingIntegration",
        viewport,
        file: null,
        screenshots: [],
        checks: [
          { name: "pendingIntegration", ok: false, detail: contract.reason },
          { name: "selectorContract", ok: false, detail: JSON.stringify(contract.selectorContract) },
          { name: "responseContract", ok: false, detail: JSON.stringify(contract.responseContract) },
        ],
        api: [],
        requestFailures: [],
        consoleErrors: [],
        pageErrors: [],
        pendingIntegration: contract,
      });
    }
  }
  return entries;
}

function matrixKey(side: Side, state: State, viewportNameValue: string): string {
  return `${side}/${state}/${viewportNameValue}`;
}

function entryKey(entry: ManifestEntry): string {
  return matrixKey(entry.side, entry.state, entry.viewport.name);
}

function unexpectedConsoleErrors(entry: ManifestEntry): string[] {
  const expected = [...(entry.expectedConsoleErrors ?? [])];
  return entry.consoleErrors.filter((message) => {
    const index = expected.indexOf(message);
    if (index < 0) return true;
    expected.splice(index, 1);
    return false;
  });
}

function listedScreenshotPaths(entry: ManifestEntry): string[] {
  return [entry.file, ...(entry.additionalFiles ?? [])].filter((path): path is string => path !== null);
}

async function hasScreenshotEvidence(
  entry: ManifestEntry,
  expectedViewport: Viewport | undefined,
  screenshotExists: ScreenshotExists,
): Promise<boolean> {
  const screenshots = entry.screenshots;
  const listedPaths = listedScreenshotPaths(entry);
  if (
    !expectedViewport ||
    entry.viewport.name !== expectedViewport.name ||
    entry.viewport.width !== expectedViewport.width ||
    entry.viewport.height !== expectedViewport.height ||
    entry.viewport.isMobile !== expectedViewport.isMobile ||
    !entry.file ||
    screenshots.length === 0
  ) return false;
  if (listedPaths.length !== screenshots.length) return false;
  if (new Set(listedPaths).size !== listedPaths.length) return false;
  if (screenshots.some((screenshot, index) => screenshot.path !== listedPaths[index] || !isAbsolute(screenshot.path))) return false;
  if (screenshots.some((screenshot) => screenshot.width !== expectedViewport.width || screenshot.height < expectedViewport.height)) return false;
  if (screenshots.some((screenshot) => screenshot.bytes <= 0 || screenshot.uniqueColors < 5 || screenshot.nonTransparentPixels <= 0)) return false;
  const filesExist = await Promise.all(screenshots.map((screenshot) => screenshotExists(screenshot.path)));
  return filesExist.every(Boolean);
}

export async function validateManifestEvidence(
  entries: readonly ManifestEntry[],
  cStates: readonly CState[] = requiredCStates,
  bStates: readonly BState[] = requiredBStates,
  viewportDefinitions: readonly Viewport[] = viewports,
  options: { screenshotExists?: ScreenshotExists } = {},
): Promise<MatrixValidation> {
  const expectedKeys = new Set<string>();
  for (const viewport of viewportDefinitions) {
    for (const state of cStates) expectedKeys.add(matrixKey("C", state, viewport.name));
    for (const state of bStates) expectedKeys.add(matrixKey("B", state, viewport.name));
  }
  const entriesByKey = new Map<string, ManifestEntry[]>();
  for (const entry of entries) {
    const key = entryKey(entry);
    const existing = entriesByKey.get(key) ?? [];
    existing.push(entry);
    entriesByKey.set(key, existing);
  }
  const expectedViewportByName = new Map<string, Viewport>(viewportDefinitions.map((viewport) => [viewport.name, viewport]));
  const screenshotExists = options.screenshotExists ?? (async (path: string) => {
    try {
      return (await stat(path)).isFile();
    } catch {
      return false;
    }
  });
  const screenshotValidity = new Map<ManifestEntry, boolean>();
  await Promise.all(entries.map(async (entry) => {
    screenshotValidity.set(entry, await hasScreenshotEvidence(entry, expectedViewportByName.get(entry.viewport.name), screenshotExists));
  }));
  const failures: string[] = [];
  const missingKeys = [...expectedKeys].filter((key) => !entriesByKey.has(key));
  const duplicateKeys = [...expectedKeys].filter((key) => (entriesByKey.get(key)?.length ?? 0) > 1);
  const unexpectedKeys = [...entriesByKey.keys()].filter((key) => !expectedKeys.has(key));
  for (const key of missingKeys) failures.push(`missing matrix cell: ${key}`);
  for (const key of duplicateKeys) failures.push(`duplicate matrix cell: ${key}`);
  for (const key of unexpectedKeys) failures.push(`unexpected matrix cell: ${key}`);

  const pendingKeys: string[] = [];
  const failedKeys: string[] = [];
  const missingScreenshotKeys: string[] = [];
  const requestFailureKeys: string[] = [];
  const unexpectedConsoleErrorKeys: string[] = [];
  const pageErrorKeys: string[] = [];
  const failedCheckKeys: string[] = [];
  const completeKeys: string[] = [];
  for (const key of expectedKeys) {
    const cellEntries = entriesByKey.get(key) ?? [];
    if (cellEntries.some((entry) => entry.status === "pendingIntegration")) pendingKeys.push(key);
    if (cellEntries.some((entry) => entry.status === "failed")) failedKeys.push(key);
    if (cellEntries.some((entry) => !screenshotValidity.get(entry))) missingScreenshotKeys.push(key);
    if (cellEntries.some((entry) => entry.requestFailures.length > 0)) requestFailureKeys.push(key);
    if (cellEntries.some((entry) => unexpectedConsoleErrors(entry).length > 0)) unexpectedConsoleErrorKeys.push(key);
    if (cellEntries.some((entry) => entry.pageErrors.length > 0)) pageErrorKeys.push(key);
    if (cellEntries.some((entry) => entry.checks.some((check) => !check.ok))) failedCheckKeys.push(key);
    const onlyEntry = cellEntries.length === 1 ? cellEntries[0] : undefined;
    if (
      onlyEntry &&
      onlyEntry.status === "captured" &&
      screenshotValidity.get(onlyEntry) === true &&
      onlyEntry.requestFailures.length === 0 &&
      unexpectedConsoleErrors(onlyEntry).length === 0 &&
      onlyEntry.pageErrors.length === 0 &&
      onlyEntry.checks.every((check) => check.ok)
    ) completeKeys.push(key);
  }
  for (const key of pendingKeys) failures.push(`pending matrix cell: ${key}`);
  for (const key of failedKeys) failures.push(`failed matrix cell: ${key}`);
  for (const key of missingScreenshotKeys) failures.push(`missing screenshot evidence: ${key}`);
  for (const key of requestFailureKeys) failures.push(`request failure in matrix cell: ${key}`);
  for (const key of unexpectedConsoleErrorKeys) failures.push(`unexpected console error in matrix cell: ${key}`);
  for (const key of pageErrorKeys) failures.push(`page error in matrix cell: ${key}`);
  for (const key of failedCheckKeys) failures.push(`failed selector/state check: ${key}`);

  const completeness: MatrixCompleteness = {
    expectedCells: expectedKeys.size,
    observedEntries: entries.length,
    observedCells: [...expectedKeys].filter((key) => entriesByKey.has(key)).length,
    completeCells: completeKeys.length,
    missingCells: missingKeys.length,
    duplicateCells: duplicateKeys.length,
    unexpectedCells: unexpectedKeys.length,
    pendingCells: pendingKeys.length,
    failedCells: failedKeys.length,
    missingScreenshotCells: missingScreenshotKeys.length,
    requestFailureCells: requestFailureKeys.length,
    unexpectedConsoleErrorCells: unexpectedConsoleErrorKeys.length,
    pageErrorCells: pageErrorKeys.length,
    failedCheckCells: failedCheckKeys.length,
  };
  return { ok: failures.length === 0, failures, completeness };
}

async function captureRuntimeState(
  browser: Browser,
  side: Side,
  state: CState | BState,
  viewport: Viewport,
  baseUrl: string,
): Promise<ManifestEntry> {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const diagnostics = attachDiagnostics(page);
  const mock = createMockState(side, state);
  const checks: CheckRecord[] = [];
  const primaryPath = statePath(side, state, viewport);
  const additionalScreenshots: ScreenshotRecord[] = [];
  let screenshotRecords: ScreenshotRecord[] = [];
  try {
    await page.route(/^https:\/\/fonts\.(?:googleapis|gstatic)\.com\//u, async (route) => {
      await route.fulfill({ status: 200, contentType: "text/css", body: "" });
    });
    await installApi(page, mock);
    const routePath = routePathFor(mock);
    await page.goto(new URL(routePath, baseUrl).toString(), { waitUntil: "domcontentloaded" });
    assert.equal(new URL(page.url()).pathname, routePath, `${side}/${state}/${viewport.name}: route drifted`);
    checks.push({ name: "route", ok: true, detail: new URL(page.url()).pathname });

    let root: Locator;
    let anchorDetail: string;
    if (side === "C") {
      const driven = await driveCState(page, mock, state as CState, primaryPath);
      root = driven.root;
      anchorDetail = driven.anchorDetail;
      additionalScreenshots.push(...driven.additional);
    } else {
      const driven = await driveBState(page, mock, state as BState);
      root = driven.root;
      anchorDetail = driven.anchorDetail;
      additionalScreenshots.push(...driven.additional);
    }
    if (mock.workspaceMode === "organization_lark") {
      await expect(root).toHaveAttribute("data-workspace-mode", "organization_lark");
      checks.push({ name: "workspaceRouteState", ok: true, detail: "organization_lark" });
    } else {
      await expect(root).toHaveAttribute("data-document-editor", "true");
      checks.push({ name: "workspaceRouteState", ok: true, detail: "personal_web" });
    }
    checks.push({ name: "pageTitle", ok: true, detail: (await root.getByRole("heading", { level: 1 }).first().textContent())?.trim() ?? "" });
    checks.push({ name: "stateAnchor", ok: true, detail: anchorDetail });

    const overflow = await assertNoHorizontalOverflow(page);
    checks.push({ name: "documentHorizontalOverflow", ok: overflow.ok, detail: overflow.detail });
    assert.equal(overflow.ok, true, `${side}/${state}/${viewport.name}: horizontal overflow ${overflow.detail}`);

    let primaryScreenshot: ScreenshotRecord;
    if (state !== "saving" && state !== "offlineRetry") {
      primaryScreenshot = await saveScreenshot(page, primaryPath);
    } else {
      assert.ok(additionalScreenshots.length > 0, `${side}/${state}/${viewport.name}: state did not capture its primary screenshot`);
      primaryScreenshot = additionalScreenshots[0]!;
    }
    screenshotRecords = [primaryScreenshot, ...additionalScreenshots.filter((item) => item.path !== primaryScreenshot.path)];
    checks.push({
      name: "screenshotNonBlank",
      ok: screenshotRecords.every((item) => item.uniqueColors >= 5 && item.nonTransparentPixels > 0),
      detail: JSON.stringify(screenshotRecords.map((item) => ({ path: item.path, bytes: item.bytes, width: item.width, height: item.height, uniqueColors: item.uniqueColors }))),
    });
    assert.ok(screenshotRecords.every((item) => item.uniqueColors >= 5 && item.nonTransparentPixels > 0), `${side}/${state}/${viewport.name}: blank screenshot`);
    const allowedRequestFailures = expectedRequestFailures(mock, diagnostics.requestFailures);
    const unexpectedRequestFailureList = unexpectedRequestFailures(mock, diagnostics.requestFailures);
    checks.push({
      name: "noUnexpectedRequestFailures",
      ok: unexpectedRequestFailureList.length === 0,
      detail: unexpectedRequestFailureList.join("\n") || "none",
    });
    assert.deepEqual(unexpectedRequestFailureList, [], `${side}/${state}/${viewport.name}: request failures`);
    const allowedConsoleErrors = expectedConsoleErrors(mock, diagnostics.consoleErrors);
    const unexpectedConsoleErrors = diagnostics.consoleErrors.filter((message) => !allowedConsoleErrors.includes(message));
    checks.push({ name: "noUnexpectedConsoleErrors", ok: unexpectedConsoleErrors.length === 0, detail: unexpectedConsoleErrors.join("\n") || "none" });
    checks.push({ name: "noPageErrors", ok: diagnostics.pageErrors.length === 0, detail: diagnostics.pageErrors.join("\n") || "none" });
    assert.deepEqual(unexpectedConsoleErrors, [], `${side}/${state}/${viewport.name}: console errors`);
    assert.deepEqual(diagnostics.pageErrors, [], `${side}/${state}/${viewport.name}: page errors`);
    const unexpectedApi = mock.unhandled.map((item) => `${item.method} ${item.path}`);
    checks.push({ name: "onlyDeclaredBrowserBoundaryMocks", ok: unexpectedApi.length === 0, detail: unexpectedApi.join("\n") || "all observed API requests were handled by the harness" });
    assert.deepEqual(unexpectedApi, [], `${side}/${state}/${viewport.name}: unexpected API requests`);

    return {
      side,
      state,
      status: "captured",
      viewport,
      file: primaryScreenshot.path,
      additionalFiles: screenshotRecords.slice(1).map((item) => item.path),
      screenshots: screenshotRecords,
      checks,
      api: mock.requests,
      requestFailures: unexpectedRequestFailureList,
      expectedRequestFailures: allowedRequestFailures,
      consoleErrors: diagnostics.consoleErrors,
      expectedConsoleErrors: allowedConsoleErrors,
      pageErrors: diagnostics.pageErrors,
    };
  } catch (error) {
    return {
      side,
      state,
      status: "failed",
      viewport,
      file: screenshotRecords[0]?.path ?? null,
      additionalFiles: screenshotRecords.slice(1).map((item) => item.path),
      screenshots: screenshotRecords,
      checks: [
        ...checks,
        { name: "runtimeCapture", ok: false, detail: error instanceof Error ? error.message : String(error) },
      ],
      api: mock.requests,
      requestFailures: diagnostics.requestFailures,
      consoleErrors: diagnostics.consoleErrors,
      expectedConsoleErrors: expectedConsoleErrors(mock, diagnostics.consoleErrors),
      pageErrors: diagnostics.pageErrors,
      error: error instanceof Error ? error.stack ?? error.message : String(error),
    };
  } finally {
    await context.setOffline(false).catch(() => undefined);
    await context.close();
  }
}

async function startLocalServer(): Promise<{ baseUrl: string; server: ViteDevServer }> {
  const configuredPort = process.env.STAGE2_DOCUMENT_QA_PORT;
  const port = configuredPort === undefined ? 0 : Number(configuredPort);
  assert.ok(Number.isInteger(port) && port >= 0 && port < 65536, `invalid STAGE2_DOCUMENT_QA_PORT: ${port}`);
  const server = await createViteServer({
    root: projectRoot,
    configFile: false,
    base: `${mediaBase}/`,
    publicDir: false,
    appType: "spa",
    plugins: [
      react(),
      {
        name: "stage2-document-qa-media-index",
        configureServer(viteServer) {
          viteServer.middlewares.use(async (request, response, next) => {
            if (!request.headers.accept?.includes("text/html")) return next();
            try {
              const html = await readFile(join(projectRoot, "index.media.html"), "utf8");
              response.statusCode = 200;
              response.setHeader("Content-Type", "text/html");
              response.end(await viteServer.transformIndexHtml(request.url ?? mediaBase, html));
            } catch (error) {
              next(error as Error);
            }
          });
        },
      },
    ],
    server: { host: "127.0.0.1", port, strictPort: port !== 0 },
  });
  await server.listen();
  const address = server.httpServer?.address();
  assert.ok(address && typeof address !== "string", "Vite QA server did not expose a TCP port");
  return { baseUrl: `http://127.0.0.1:${address.port}`, server };
}

async function stopLocalServer(server: ViteDevServer | null): Promise<void> {
  if (server) await server.close();
}

async function readSourceGitSha(): Promise<string | null> {
  try {
    const { stdout } = await execFile("git", ["rev-parse", "HEAD"], { cwd: projectRoot });
    const sha = stdout.trim();
    return /^[0-9a-f]{40}$/iu.test(sha) ? sha : null;
  } catch {
    return null;
  }
}

async function main(): Promise<void> {
  const captureTimestamp = new Date().toISOString();
  const sourceGitSha = await readSourceGitSha();
  await mkdir(outputDir, { recursive: true });
  const started = externalBaseUrl ? null : await startLocalServer();
  const baseUrl = externalBaseUrl ?? started!.baseUrl;
  const localServer = started?.server ?? null;
  const browser = await chromium.launch({ headless: true });
  const browserIdentity = { name: browser.browserType().name(), version: browser.version() };
  const entries: ManifestEntry[] = [];
  try {
    for (const viewport of viewports) {
      for (const state of runtimeC) entries.push(await captureRuntimeState(browser, "C", state, viewport, baseUrl));
      for (const state of runtimeB) entries.push(await captureRuntimeState(browser, "B", state, viewport, baseUrl));
    }
    entries.push(...pendingEntries());
  } finally {
    await browser.close();
    await stopLocalServer(localServer);
  }
  const validation = await validateManifestEvidence(entries);
  const validationFailures = [
    ...validation.failures,
    ...(sourceGitSha ? [] : ["source git SHA unavailable"]),
    ...(browserIdentity.name && browserIdentity.version ? [] : ["browser identity unavailable"]),
  ];
  const screenshotFiles = entries.reduce((count, entry) => count + entry.screenshots.length, 0);
  const capturedEntries = entries.filter((entry) => entry.status === "captured").length;
  const pendingIntegrationEntries = entries.filter((entry) => entry.status === "pendingIntegration").length;
  const failedEntries = entries.filter((entry) => entry.status === "failed").length;
  const manifest: Manifest = {
    taskId: TASK_ID,
    sourceIdentity: SOURCE_IDENTITY,
    authority: {
      devBrief: "docs/frontend/prototype/stage2-dev-brief.md",
      acceptanceExecution: "docs/frontend/prototype/stage2-acceptance-execution.html",
    },
    baseUrl,
    outputDirectory: outputDir,
    viewports,
    sourceGitSha,
    browserIdentity,
    captureTimestamp,
    reviewIdentity,
    entries,
    matrixCompleteness: validation.completeness,
    validationFailures,
    summary: {
      requiredCStates: requiredCStates.length,
      requiredBStates: requiredBStates.length,
      capturedEntries,
      pendingIntegrationEntries,
      failedEntries,
      screenshotFiles,
    },
    ok: validationFailures.length === 0,
  };
  const manifestPath = resolve(outputDir, "manifest.json");
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(`Stage2 document screenshot manifest: ${manifestPath}`);
  console.log(`Observed ${validation.completeness.observedCells}/${validation.completeness.expectedCells} matrix cells; complete=${validation.completeness.completeCells}; screenshots=${screenshotFiles}; pending=${pendingIntegrationEntries}; failed=${failedEntries}`);
  if (!manifest.ok) process.exitCode = 1;
}

function selfTestEntry(overrides: Partial<ManifestEntry> = {}): ManifestEntry {
  const viewport = viewports[0];
  const screenshot: ScreenshotRecord = {
    path: "/tmp/stage2-self-test.png",
    sha256: "0".repeat(64),
    bytes: 100,
    width: viewport.width,
    height: viewport.height,
    uniqueColors: 5,
    nonTransparentPixels: 1,
  };
  return {
    side: "C",
    state: "clean",
    status: "captured",
    viewport,
    file: screenshot.path,
    additionalFiles: [],
    screenshots: [screenshot],
    checks: [
      { name: "route", ok: true, detail: "ok" },
      { name: "stateAnchor", ok: true, detail: "ok" },
    ],
    api: [],
    requestFailures: [],
    consoleErrors: [],
    pageErrors: [],
    ...overrides,
  };
}

export async function runSelfTest(): Promise<void> {
  assert.deepEqual(
    viewports.map(({ name, width, height }) => ({ name, width, height })),
    [
      { name: "desktop-1440x900", width: 1440, height: 900 },
      { name: "desktop-1280x800", width: 1280, height: 800 },
      { name: "tablet-1024x768", width: 1024, height: 768 },
      { name: "mobile-390x844", width: 390, height: 844 },
    ],
  );
  assert.deepEqual(derivePendingStates(["rendered", "missing"] as const, new Set(["rendered"])), ["missing"]);
  assert.deepEqual(pendingC, []);
  assert.deepEqual(pendingB, []);

  const organizationMock = createMockState("C", "organizationDocument");
  assert.equal(organizationMock.workspaceMode, "organization_lark");
  assert.equal(organizationMock.artifactId, organizationArtifactId);
  assert.equal(routePathFor(organizationMock), `${mediaBase}/organization-workspace/document/${organizationArtifactId}`);
  const organizationBodyResponse = bodyResponse(organizationMock);
  assert.equal(organizationBodyResponse.data.artifact.workspaceMode, "organization_lark");
  assert.equal(organizationBodyResponse.data.artifact.bodyAuthority, "lark");

  const offlineMock = createMockState("C", "offlineRetry");
  const offlineFailure = `PUT ${apiRoot}/documents/${offlineMock.artifactId}/draft net::ERR_INTERNET_DISCONNECTED`;
  assert.deepEqual(expectedRequestFailures(offlineMock, [offlineFailure, "GET /unexpected net::ERR_FAILED"]), [offlineFailure]);
  assert.deepEqual(unexpectedRequestFailures(offlineMock, [offlineFailure, "GET /unexpected net::ERR_FAILED"]), ["GET /unexpected net::ERR_FAILED"]);

  const organizationRetryMock = createMockState("B", "synced");
  organizationRetryMock.requests.push({
    method: "GET",
    path: `/documents/${organizationRetryMock.artifactId}/body`,
    operationId: "getDocumentBody",
    status: 200,
    mockedAtBrowserBoundary: true,
  });
  const abortedRead = `GET ${apiRoot}/documents/${organizationRetryMock.artifactId}/body net::ERR_ABORTED`;
  assert.deepEqual(expectedRequestFailures(organizationRetryMock, [abortedRead]), [abortedRead]);
  assert.deepEqual(unexpectedRequestFailures(organizationRetryMock, [abortedRead]), []);

  const green = await validateManifestEvidence(
    [selfTestEntry()],
    ["clean"],
    [],
    [viewports[0]],
    { screenshotExists: async () => true },
  );
  assert.equal(green.ok, true, `self-test green fixture failed: ${green.failures.join("; ")}`);

  const expectRejected = async (name: string, entry: ManifestEntry, expectedFailure: string, screenshotExists = true) => {
    const result = await validateManifestEvidence(
      [entry],
      ["clean"],
      [],
      [viewports[0]],
      { screenshotExists: async () => screenshotExists },
    );
    assert.equal(result.ok, false, `${name} fixture unexpectedly passed`);
    assert.ok(result.failures.some((failure) => failure.includes(expectedFailure)), `${name} fixture did not report ${expectedFailure}: ${result.failures.join("; ")}`);
  };
  await expectRejected("missing screenshot", selfTestEntry({ file: null, screenshots: [], additionalFiles: [] }), "missing screenshot evidence");
  await expectRejected("request failure", selfTestEntry({ requestFailures: ["GET /openclaw/media/api/example net::ERR_FAILED"] }), "request failure in matrix cell");
  await expectRejected("unexpected console error", selfTestEntry({ consoleErrors: ["unexpected console error"] }), "unexpected console error in matrix cell");
  await expectRejected("page error", selfTestEntry({ pageErrors: ["unexpected page error"] }), "page error in matrix cell");
  await expectRejected("failed selector check", selfTestEntry({ checks: [{ name: "stateAnchor", ok: false, detail: "missing" }] }), "failed selector/state check");
  await expectRejected("failed status", selfTestEntry({ status: "failed", file: null, screenshots: [], additionalFiles: [] }), "failed matrix cell");
  await expectRejected("pending status", selfTestEntry({ status: "pendingIntegration", file: null, screenshots: [], additionalFiles: [] }), "pending matrix cell");
  await expectRejected("filesystem screenshot missing", selfTestEntry(), "missing screenshot evidence", false);
  const missingCell = await validateManifestEvidence([], ["clean"], [], [viewports[0]], { screenshotExists: async () => true });
  assert.equal(missingCell.ok, false);
  assert.ok(missingCell.failures.includes("missing matrix cell: C/clean/desktop-1440x900"));
  console.log("Stage2 document screenshot harness self-test: PASS");
}

const isDirectExecution = process.argv[1] !== undefined && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
if (isDirectExecution) {
  const operation = process.argv.includes("--self-test") ? runSelfTest() : main();
  operation.catch((error: unknown) => {
    console.error(error instanceof Error ? error.stack ?? error.message : String(error));
    process.exitCode = 1;
  });
}
