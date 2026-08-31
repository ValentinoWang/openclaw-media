import assert from "node:assert/strict";

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

type Request = {
  path?: Readonly<Record<string, unknown>>;
  query?: Readonly<Record<string, unknown>>;
  signal?: AbortSignal;
};

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
