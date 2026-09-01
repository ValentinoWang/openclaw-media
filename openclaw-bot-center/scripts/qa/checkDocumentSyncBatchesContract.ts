import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  IF2_DOCUMENT_OPERATIONS,
  createIf2DocumentApi,
  type DocumentBusinessCaller,
} from "../../src/media/documentWorkflow";
import {
  BusinessOperationError,
  callBusinessOperation,
  documentOperationIds,
  operations,
} from "../../src/media/generatedBusinessPagesContract";
import {
  isOrganizationMirrorDocumentResponse,
  projectExecutionReceipt,
  projectSyncBatchList,
  readDetailPart,
  safeTechnicalCode,
  syncActionFor,
  syncActionLabel,
  syncBatchOperationLabel,
  syncBatchStateLabel,
  syncDetailItemLabel,
  syncStateFor,
  syncStateLabels,
  type SyncState,
} from "../../src/media/organizationDocumentMirrorPresentation";

type Request = {
  path?: Readonly<Record<string, unknown>>;
  query?: Readonly<Record<string, unknown>>;
  signal?: AbortSignal;
};

const ARTIFACT_ID = "artifact_sync_1";
const BODY_CHECKSUM = "a".repeat(64);

function syncBatch(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    publicSyncId: "sync_batch_1",
    publicArtifactId: ARTIFACT_ID,
    revision: 2,
    operation: "save",
    state: "succeeded",
    remoteDocumentVersion: "v2",
    bodyChecksum: BODY_CHECKSUM,
    blockCount: 2,
    protectedBlockCount: 0,
    createdAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-01T00:01:00Z",
    completedAt: "2026-09-01T00:01:00Z",
    errorCode: null,
    errorDetail: {},
    ...overrides,
  };
}

function syncBatchResponse(items: unknown[]): Record<string, unknown> {
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision: 2,
    items,
    nextCursor: null,
  };
}

function organizationDocumentResponse(artifactId = ARTIFACT_ID, revisionArtifactId = artifactId): Record<string, unknown> {
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision: 2,
    data: {
      artifact: {
        publicArtifactId: artifactId,
        workspaceMode: "organization_lark",
        bodyAuthority: "lark",
      },
      revision: {
        publicArtifactId: revisionArtifactId,
        bodyAuthority: "lark",
        revision: 2,
        bodyChecksum: BODY_CHECKSUM,
        body: { schemaVersion: "media.document.body.v1", blocks: [] },
      },
    },
  };
}

async function assertMirrorPresentationContract(): Promise<void> {
  const stateCases: Array<{
    expected: Exclude<SyncState, "loading" | "unavailable">;
    batch: Record<string, unknown>;
    mirrorVersion: string;
    stateLabel: string;
    action: "reread" | "reconcile" | "refresh";
    actionLabel: string;
    batchLabel: string;
  }> = [
    { expected: "synced", batch: syncBatch({ operation: "read" }), mirrorVersion: "v2", stateLabel: "镜像已同步", action: "reread", actionLabel: "重新读取", batchLabel: "已完成" },
    { expected: "running", batch: syncBatch({ state: "running", remoteDocumentVersion: null, completedAt: null }), mirrorVersion: "v2", stateLabel: "正在写入飞书", action: "refresh", actionLabel: "检查处理进度", batchLabel: "正在处理" },
    { expected: "unknown", batch: syncBatch({ state: "running", errorCode: "lark_save_outcome_unknown", remoteDocumentVersion: null, completedAt: null }), mirrorVersion: "v2", stateLabel: "写入结果待对账", action: "reconcile", actionLabel: "重新核对状态", batchLabel: "写入结果待对账" },
    { expected: "conflict", batch: syncBatch({ state: "conflict", errorCode: "remote_document_conflict" }), mirrorVersion: "v2", stateLabel: "远端版本需要处理", action: "reread", actionLabel: "重新读取镜像", batchLabel: "需要处理冲突" },
    { expected: "unsupported", batch: syncBatch({ state: "failed", errorCode: "unsupported_document_block", errorDetail: { blockIds: ["blk_table_1"] } }), mirrorVersion: "v2", stateLabel: "部分内容暂不能同步", action: "reread", actionLabel: "处理后重新读取", batchLabel: "结构暂不支持" },
    { expected: "stale", batch: syncBatch({ operation: "read", remoteDocumentVersion: "v3" }), mirrorVersion: "v2", stateLabel: "飞书已有更新，等待回读", action: "reread", actionLabel: "重新读取镜像", batchLabel: "已完成" },
    { expected: "partial", batch: syncBatch({ errorDetail: { applied: ["blk_intro_1"], manualActions: ["blk_table_1"], protectedSkipped: ["blk_table_1"] } }), mirrorVersion: "v2", stateLabel: "部分内容已应用", action: "reread", actionLabel: "重新读取结果", batchLabel: "已完成" },
  ];

  for (const testCase of stateCases) {
    const projection = projectSyncBatchList(syncBatchResponse([testCase.batch]), ARTIFACT_ID);
    assert.equal(projection.status, "available", `${testCase.expected} batch should be available`);
    const item = projection.items[0];
    assert.ok(item, `${testCase.expected} batch should project an item`);
    assert.equal(syncStateFor(projection.items, testCase.mirrorVersion, "ready"), testCase.expected);
    assert.equal(syncStateLabels[testCase.expected], testCase.stateLabel);
    assert.equal(syncActionFor(testCase.expected), testCase.action);
    assert.equal(syncActionLabel(testCase.expected), testCase.actionLabel);
    assert.equal(syncBatchStateLabel(item), testCase.batchLabel);
    assert.match(syncBatchOperationLabel(item.operation), /[\u4e00-\u9fff]/u);
  }

  const malformedProjection = projectSyncBatchList(syncBatchResponse([syncBatch({
    operation: "delete",
    state: "waiting",
    revision: 0,
    remoteDocumentVersion: 12,
    bodyChecksum: `sha256:${BODY_CHECKSUM}`,
    blockCount: -1,
    protectedBlockCount: "1",
    createdAt: "not-a-time",
    updatedAt: {},
    completedAt: "not-a-time",
    errorCode: "http_500",
    errorDetail: { applied: "not-an-array" },
  })]), ARTIFACT_ID);
  assert.equal(malformedProjection.status, "available");
  const malformedItem = malformedProjection.items[0];
  assert.ok(malformedItem);
  assert.equal(malformedItem.operation, null);
  assert.equal(malformedItem.state, null);
  assert.equal(malformedItem.revision, null);
  assert.equal(malformedItem.remoteDocumentVersion, null);
  assert.equal(malformedItem.bodyChecksum, null);
  assert.equal(malformedItem.blockCount, null);
  assert.equal(malformedItem.protectedBlockCount, null);
  assert.equal(malformedItem.createdAt, null);
  assert.equal(malformedItem.updatedAt, null);
  assert.equal(malformedItem.completedAt, null);
  assert.equal(malformedItem.errorCode, null);
  assert.equal(syncStateFor(malformedProjection.items, "v2", "ready"), "unavailable");
  assert.equal(syncBatchOperationLabel(malformedItem.operation), "同步类型不可用");
  assert.equal(syncBatchStateLabel(malformedItem), "状态不可用");
  assert.equal(readDetailPart(malformedItem.errorDetail, "applied").available, false);

  assert.deepEqual(
    projectSyncBatchList(syncBatchResponse([syncBatch({ publicArtifactId: "artifact_other_1" })]), ARTIFACT_ID),
    { status: "unavailable", items: [], nextCursor: null },
    "a cross-artifact batch must invalidate the complete page",
  );
  assert.deepEqual(
    projectSyncBatchList(syncBatchResponse([syncBatch({ publicSyncId: "sync_duplicate" }), syncBatch({ publicSyncId: "sync_duplicate" })]), ARTIFACT_ID),
    { status: "unavailable", items: [], nextCursor: null },
    "duplicate public sync IDs must invalidate the complete page",
  );

  assert.equal(isOrganizationMirrorDocumentResponse(organizationDocumentResponse(), ARTIFACT_ID), true);
  assert.equal(isOrganizationMirrorDocumentResponse(organizationDocumentResponse("artifact_other_1"), ARTIFACT_ID), false);
  assert.equal(isOrganizationMirrorDocumentResponse(organizationDocumentResponse(ARTIFACT_ID, "artifact_other_1"), ARTIFACT_ID), false);
  assert.equal(isOrganizationMirrorDocumentResponse({ ...organizationDocumentResponse(), schemaVersion: "media.document.body.v1" }, ARTIFACT_ID), false);

  const validReceipt = projectExecutionReceipt({
    status: "ready",
    applied: [{ operation: "replace_text", blockId: "blk_intro_1" }],
    appliedCount: 1,
    manualActions: [{ reason: "protected_block", blockId: "blk_table_1" }],
    protectedSkipped: ["blk_table_1"],
  });
  assert.ok(validReceipt, "a schema-valid receipt enables the AI feature gate");
  assert.equal(validReceipt?.status, "ready");
  assert.equal(projectExecutionReceipt({
    status: "ready",
    applied: [{ operation: "unknown_operation" }],
    appliedCount: 1,
    manualActions: [],
    protectedSkipped: [],
  }), null);
  assert.equal(projectExecutionReceipt({
    status: "ready",
    applied: [],
    appliedCount: 0,
    manualActions: [],
    protectedSkipped: [{ blockId: "blk_table_1" }],
  }), null);
  assert.equal(safeTechnicalCode("http_500"), null);
  assert.equal(safeTechnicalCode("remote_document_conflict"), "remote_document_conflict");
  assert.equal(syncDetailItemLabel({ operation: "replace_text", blockId: "blk_intro_1" }, 0, "applied"), "替换文本 · 相关正文块 1");
  assert.equal(syncDetailItemLabel({ reason: "wire_internal_reason" }, 0, "manualActions"), "人工处理项目 1");

  const [pageSource, workflowSource] = await Promise.all([
    readFile(new URL("../../src/media/OrganizationDocumentMirrorPage.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../src/media/documentWorkflow.ts", import.meta.url), "utf8"),
  ]);
  assert.match(workflowSource, /"listArtifactSyncBatches"/u);
  assert.match(pageSource, /listSyncBatches/u);
  assert.match(pageSource, /CanonicalDocumentRenderer/u);
  assert.match(pageSource, /data-ai-feature-flag/u);
  assert.match(pageSource, /projectExecutionReceipt/u);
  assert.match(pageSource, /data-read-only-mirror="true"/u);
  assert.doesNotMatch(pageSource, /completedAt\s*\|\|\s*updatedAt/u);
}

async function main(): Promise<void> {
  assert.ok(documentOperationIds.includes("listArtifactSyncBatches"));
  assert.ok(IF2_DOCUMENT_OPERATIONS.includes("listArtifactSyncBatches"));
  assert.deepEqual(operations.listArtifactSyncBatches, {
    canonicalCapabilityIds: [],
    category: "document",
    existingHandlers: [],
    method: "GET",
    pageContracts: ["B05"],
    path: "/artifacts/{publicArtifactId}/sync-batches",
    pathParameters: ["publicArtifactId"],
    permission: "ordinary-session",
    productReadModels: ["sync_batches"],
    queryParameters: ["cursor", "pageSize"],
    runtimeStatus: "new",
  });

  const calls: Array<{ operationId: string; request: Request }> = [];
  const caller: DocumentBusinessCaller = async <T>(operationId, request = {}) => {
    calls.push({ operationId, request });
    return { schemaVersion: "media_web_business_pages_v2", revision: 2, items: [], nextCursor: null } as T;
  };
  await createIf2DocumentApi(caller).listSyncBatches("artifact_sync_1", "signed-cursor", 25);
  assert.deepEqual(calls, [{
    operationId: "listArtifactSyncBatches",
    request: {
      path: { publicArtifactId: "artifact_sync_1" },
      query: { cursor: "signed-cursor", pageSize: 25 },
      signal: undefined,
    },
  }]);

  await assertMirrorPresentationContract();

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    error: {
      code: "unsupported_document_block",
      message: "部分正文未通过校验。",
      details: { blockIds: ["blk_protected_1"] },
    },
  }), { status: 422, statusText: "Unprocessable Entity" });
  try {
    await assert.rejects(
      callBusinessOperation("saveDocumentDraft", {
        path: { publicArtifactId: "artifact_sync_1" },
        body: {},
      }),
      (error: unknown) => {
        assert.ok(error instanceof BusinessOperationError);
        assert.equal(error.status, 422);
        assert.equal(error.code, "unsupported_document_block");
        assert.deepEqual(error.details, { blockIds: ["blk_protected_1"] });
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
}

void main();
