import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  BusinessOperationError,
  callBusinessOperation,
  documentOperationIds,
  operationGroups,
  operationIdsByPage,
  operations,
  pageOperationIds,
  schemaNames,
  schemaRefs,
  sharedOperationIds,
  sourceSha256,
} from "../../src/media/generatedBusinessPagesContract";

const root = path.resolve(import.meta.dirname, "../..");
const expectedHash =
  "3c31e78dec2dff4b19fbd227385de3e5d276cb0349c2dab25e87e383622b5147";
const generator = path.join(
  root,
  "scripts/generateMediaBusinessPagesContract.py",
);
const generatedFile = path.join(
  root,
  "src/media/generatedBusinessPagesContract.ts",
);
const sourceFile = path.resolve(
  root,
  "../openclaw-tag-router/openclaw_app/contracts/media_web_business_pages.openapi.yaml",
);
const resourceFile = path.resolve(
  root,
  "../openclaw-tag-router/openclaw_app/contracts/media_web_business_pages.resources.yaml",
);

function requireContract(
  condition: unknown,
  message: string,
): asserts condition {
  if (!condition) throw new Error(message);
}

function requireUnique(values: readonly string[], label: string): void {
  requireContract(
    new Set(values).size === values.length,
    `${label} contains duplicates`,
  );
}

function sorted(values: readonly string[]): string[] {
  return [...values].sort();
}

function requireSameSet(
  actual: readonly string[],
  expected: readonly string[],
  label: string,
): void {
  requireContract(
    JSON.stringify(sorted(actual)) === JSON.stringify(sorted(expected)),
    `${label} drifted`,
  );
}

function validateGeneratedContract(): void {
  requireContract(sourceSha256 === expectedHash, "generated source hash drift");
  requireContract(schemaNames.length === 187, "expected 187 OpenAPI schemas");
  requireUnique(schemaNames, "schema names");
  requireSameSet(
    Object.keys(schemaRefs),
    schemaNames,
    "schema reference mapping",
  );
  for (const schemaName of schemaNames) {
    requireContract(
      schemaRefs[schemaName] === `#/components/schemas/${schemaName}`,
      `invalid schema reference for ${schemaName}`,
    );
  }

  const operationIds = Object.keys(operations);
  requireContract(operationIds.length === 92, "expected 92 operations");
  requireUnique(operationIds, "operation IDs");
  requireContract(
    pageOperationIds.length === 74,
    "expected 74 page operations",
  );
  requireContract(
    sharedOperationIds.length === 10,
    "expected 10 shared operations",
  );
  requireContract(
    documentOperationIds.length === 8,
    "expected 8 document operations",
  );
  requireSameSet(
    operationIds,
    [...pageOperationIds, ...sharedOperationIds, ...documentOperationIds],
    "operation category union",
  );
  requireSameSet(
    operationGroups.page,
    pageOperationIds,
    "page operation group",
  );
  requireSameSet(
    operationGroups.shared,
    sharedOperationIds,
    "shared operation group",
  );
  requireSameSet(
    operationGroups.document,
    documentOperationIds,
    "document operation group",
  );

  requireContract(
    Object.keys(operationIdsByPage).length === 14,
    "expected 14 page operation mappings",
  );
  const declaredPageOperations = [
    ...new Set(Object.values(operationIdsByPage).flat()),
  ];
  const declaredDocumentOperations = documentOperationIds.filter((operationId) =>
    declaredPageOperations.includes(operationId),
  );
  requireSameSet(
    declaredPageOperations,
    [...pageOperationIds, ...declaredDocumentOperations],
    "page declaration operation union",
  );
  requireSameSet(
    declaredDocumentOperations,
    ["getDocumentResource", "listArtifactSyncBatches"],
    "declared document page-operation set",
  );

  for (const operationId of operationIds) {
    const operation = operations[operationId as keyof typeof operations];
    requireContract(
      operation.method === operation.method.toUpperCase(),
      `${operationId} has a non-canonical method`,
    );
    requireContract(
      operation.path.startsWith("/"),
      `${operationId} has a non-canonical path`,
    );
    requireContract(
      operationGroups[operation.category].includes(operationId as never),
      `${operationId} category mapping drifted`,
    );
  }
}

function validateResources(): void {
  const resources = fs.readFileSync(resourceFile, "utf8");
  const nodes = [...resources.matchAll(/\bnode:\s*(B\d{2})\b/g)].map(
    (match) => match[1],
  );
  const ports = [...resources.matchAll(/\bport:\s*(\d+)\b/g)].map((match) =>
    Number(match[1]),
  );
  requireSameSet(
    nodes,
    Array.from(
      { length: 14 },
      (_, index) => `B${String(index + 1).padStart(2, "0")}`,
    ),
    "resource lane nodes",
  );
  requireSameSet(
    ports.map(String),
    Array.from({ length: 14 }, (_, index) => String(18001 + index)),
    "resource lane ports",
  );
  requireContract(
    /^\s*chromiumConcurrency:\s*4\s*$/m.test(resources),
    "Chromium concurrency must be 4",
  );
}

function requireNonFakeSuccess(value: {
  status: string;
  items: readonly unknown[];
}): void {
  requireContract(
    value.status !== "success" || value.items.length > 0,
    "fake-success empty state",
  );
}

function runRedFixtures(): void {
  let fakeSuccessRejected = false;
  try {
    requireNonFakeSuccess({ status: "success", items: [] });
  } catch (error) {
    fakeSuccessRejected =
      error instanceof Error && error.message === "fake-success empty state";
  }
  requireContract(fakeSuccessRejected, "fake-success fixture was accepted");
  requireNonFakeSuccess({ status: "empty", items: [] });

  const temporaryRoot = fs.mkdtempSync(
    path.join(os.tmpdir(), "media-business-foundation-"),
  );
  try {
    const generated = fs.readFileSync(generatedFile, "utf8");
    const driftedTarget = path.join(temporaryRoot, "generated.ts");
    fs.writeFileSync(
      driftedTarget,
      generated.replace("getDashboard", "getDashboardDrift"),
    );
    const generatedDrift = spawnSync(
      "python3",
      [generator, "--check", "--target", driftedTarget],
      { encoding: "utf8" },
    );
    requireContract(
      generatedDrift.status !== 0 &&
        generatedDrift.stderr.includes("generated business contract drift"),
      "generated operation/schema drift fixture was accepted",
    );

    const driftedSource = path.join(temporaryRoot, "openapi.yaml");
    fs.writeFileSync(
      driftedSource,
      `${fs.readFileSync(sourceFile, "utf8")}\n# undeclared drift\n`,
    );
    const sourceDrift = spawnSync(
      "python3",
      [
        generator,
        "--check",
        "--source",
        driftedSource,
        "--target",
        generatedFile,
      ],
      { encoding: "utf8" },
    );
    requireContract(
      sourceDrift.status !== 0 &&
        sourceDrift.stderr.includes("accepted OpenAPI hash mismatch"),
      "undeclared OpenAPI drift fixture was accepted",
    );
  } finally {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
}

async function runOperationCallerTests(): Promise<void> {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ input: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ input: String(input), init });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    await callBusinessOperation("listAssets", {
      query: { cursor: "next page", pageSize: 25, ignored: "no" },
    });
    requireContract(
      requests[0]?.input ===
        "/openclaw/media/api/assets?cursor=next+page&pageSize=25",
      "declared query expansion drifted",
    );
    requireContract(
      requests[0]?.init?.credentials === "same-origin",
      "business caller must use same-origin credentials",
    );

    await callBusinessOperation("updatePublishingChecks", {
      path: { publicPackageId: "package/id" },
      body: { revision: 7 },
      csrfToken: "csrf-test-only-1234",
      idempotencyKey: "idem_test_1234",
      auditReason: "中文审计原因：逐字回读",
    });
    requireContract(
      requests[1]?.input ===
        "/openclaw/media/api/publishing/packages/package%2Fid/checks",
      "encoded path expansion drifted",
    );
    const headers = requests[1]?.init?.headers as Record<string, string>;
    const auditHeaderNames = Object.keys(headers).filter((name) =>
      /audit.*reason/iu.test(name),
    );
    const auditWireValue = headers["X-Audit-Reason"];
    const auditWirePrefix = "utf8-base64url-v1.";
    const decodedAuditReason = Buffer.from(
      auditWireValue.slice(auditWirePrefix.length),
      "base64url",
    ).toString("utf8");
    requireContract(
      headers["X-OpenClaw-CSRF"] === "csrf-test-only-1234" &&
        headers["Idempotency-Key"] === "idem_test_1234" &&
        auditHeaderNames.length === 1 &&
        auditHeaderNames[0] === "X-Audit-Reason" &&
        /^utf8-base64url-v1\.[A-Za-z0-9_-]+$/u.test(auditWireValue) &&
        decodedAuditReason === "中文审计原因：逐字回读",
      "business mutation headers drifted",
    );

    for (const [operationId, request, expectedCode] of [
      ["missingOperation", {}, "undeclared_operation"],
      ["getRun", {}, "missing_path_parameter"],
      ["getRun", { path: { publicRunId: "run-12345678", extra: 1 } }, "unexpected_path_parameter"],
    ] as const) {
      let rejected = false;
      try {
        await callBusinessOperation(operationId as never, request);
      } catch (error) {
        rejected =
          error instanceof BusinessOperationError && error.code === expectedCode;
      }
      requireContract(rejected, `${expectedCode} fixture was accepted`);
    }

    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          error: { code: "revision_conflict", message: "Revision changed", field: null },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      );
    let preserved = false;
    try {
      await callBusinessOperation("getDashboard");
    } catch (error) {
      preserved =
        error instanceof BusinessOperationError &&
        error.status === 409 &&
        error.code === "revision_conflict" &&
        error.message === "Revision changed";
    }
    requireContract(preserved, "IF2 error detail was not preserved");
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function runOverflowSelfTest(): void {
  const result = spawnSync(
    path.join(root, "node_modules/.bin/tsx"),
    [path.join(root, "scripts/qa/captureMediaRolePages.ts")],
    {
      cwd: root,
      encoding: "utf8",
      env: { ...process.env, MEDIA_ROLE_QA_GEOMETRY_SELF_TEST: "1" },
    },
  );
  requireContract(
    result.status === 0 &&
      result.stdout.includes("Clipped-content geometry self-test PASS"),
    `existing overflow self-test failed: ${result.stderr || result.stdout}`,
  );
}

validateGeneratedContract();
validateResources();
runRedFixtures();
await runOperationCallerTests();
runOverflowSelfTest();
console.log(
  `media business foundation: PASS (${schemaNames.length} schemas; ${pageOperationIds.length} page + ${sharedOperationIds.length} shared + ${documentOperationIds.length} document operations)`,
);
