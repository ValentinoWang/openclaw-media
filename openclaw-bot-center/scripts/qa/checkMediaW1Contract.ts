import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import "./checkArchiveDeleteReplay";
import {
  MediaProductClient,
  operations,
} from "../../src/media/generatedProductContract";
import { MediaProductHttpTransport } from "../../src/media/mediaProductHttpTransport";
import { isCurrentW1Request } from "../../src/media/pages/ordinary/w1RequestGuard";

const requests: Array<{ url: string; init: RequestInit }> = [];
const fakeFetch: typeof fetch = async (input, init = {}) => {
  requests.push({ url: String(input), init });
  return new Response(
    JSON.stringify({
      pipelines: [],
      devices: [],
      jobs: [],
      archives: [],
      next_cursor: null,
      archive: null,
      verified: true,
      hard_deleted: true,
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
};

const transport = new MediaProductHttpTransport({
  fetchImpl: fakeFetch,
  getCsrfToken: () => "csrf-test-only",
  getDeviceCredential: () => "device-test-only",
});
const client = new MediaProductClient(transport);

const contract = JSON.parse(
  readFileSync(
    // 机器契约实例只存在于产品契约维护机；其它环境通过环境变量注入副本。
    process.env.OPENCLAW_MEDIA_PRODUCT_CONTRACT_PATH
      ?? "/home/ubuntu/docs/ai-harness/openclaw-media-product-contract.json",
    "utf8",
  ),
) as { api_operations: Array<Record<string, unknown>> };
assert.equal(Object.keys(operations).length, 20);
assert.deepEqual(
  Object.entries(operations).map(([operationId, operation]) => ({
    operation_id: operationId,
    ...operation,
  })),
  contract.api_operations,
  "all generated operation metadata must match the machine contract",
);
const clientMethodNames = new Set(
  Object.getOwnPropertyNames(Object.getPrototypeOf(client)),
);
for (const operation of contract.api_operations) {
  assert.equal(
    clientMethodNames.has(String(operation.operation_id)),
    true,
    `${String(operation.operation_id)} must have a generated method`,
  );
  assert.equal(typeof operation.method, "string");
  assert.equal(typeof operation.relative_path, "string");
  assert.equal(typeof operation.auth, "string");
  assert.equal(typeof operation.idempotency, "string");
}
execFileSync(
  "python3",
  [
    "/home/ubuntu/selfmedia-tools/media-agent-cli/generate_product_clients.py",
    "--check",
  ],
  { stdio: "pipe" },
);

await client.pipeline_list({ cursor: "cursor 1", limit: 2 });
assert.equal(
  requests.at(-1)!.url,
  "/openclaw/media/api/pipelines?cursor=cursor+1&limit=2",
);
assert.equal(requests.at(-1)!.init.method, "GET");
assert.equal(
  (requests.at(-1)!.init.headers as Record<string, string>)["X-OpenClaw-CSRF"],
  undefined,
);

await client.job_create(
  {
    pipeline_id: "media.project.prepare.v1",
    pipeline_version: "1.0.0",
    catalog_digest: "digest",
    device_id: "device-1",
    input_refs: [],
    output_selection: [],
  },
  { idempotencyKey: "job-key" },
);
const jobRequest = requests.at(-1)!;
assert.equal(jobRequest.url, "/openclaw/media/api/jobs");
assert.equal(
  (jobRequest.init.headers as Record<string, string>)["Idempotency-Key"],
  "job-key",
);
assert.equal(
  (jobRequest.init.headers as Record<string, string>)["X-OpenClaw-CSRF"],
  "csrf-test-only",
);
assert.deepEqual(JSON.parse(String(jobRequest.init.body)), {
  pipeline_id: "media.project.prepare.v1",
  pipeline_version: "1.0.0",
  catalog_digest: "digest",
  device_id: "device-1",
  input_refs: [],
  output_selection: [],
});

const heartbeatClient = client as unknown as {
  device_heartbeat: (
    request: Record<string, unknown>,
    options: { idempotencyKey: string; signal: AbortSignal },
  ) => Promise<unknown>;
};
const heartbeatSignal = new AbortController();
await heartbeatClient.device_heartbeat(
  {
    device_id: "device/1",
    observed_at: "2026-08-04T00:00:00Z",
    client_version: "1.0.0",
    api_version: "1",
    catalog_digest: "digest",
    expected_revision: 1,
  },
  { idempotencyKey: "heartbeat-key", signal: heartbeatSignal.signal },
);
const heartbeatRequest = requests.at(-1)!;
assert.equal(
  heartbeatRequest.url,
  "/openclaw/media/api/devices/device%2F1/heartbeat",
);
assert.equal(
  (heartbeatRequest.init.headers as Record<string, string>)["Idempotency-Key"],
  "heartbeat-key",
);
assert.equal(
  (heartbeatRequest.init.headers as Record<string, string>)["X-OpenClaw-CSRF"],
  undefined,
);
assert.equal(heartbeatRequest.init.signal, heartbeatSignal.signal);

await client.archive_delete(
  {
    archive_id: "archive/1",
    delete_plan_id: "plan-1",
    confirmation_ref: "confirm-1",
    expected_revision: 3,
  },
  { idempotencyKey: "delete-key" },
);
const deleteRequest = requests.at(-1)!;
assert.equal(deleteRequest.url, "/openclaw/media/api/archives/archive%2F1");
assert.equal(deleteRequest.init.method, "DELETE");
assert.deepEqual(JSON.parse(String(deleteRequest.init.body)), {
  delete_plan_id: "plan-1",
  confirmation_ref: "confirm-1",
  expected_revision: 3,
});

const deviceTransport = new MediaProductHttpTransport({
  fetchImpl: fakeFetch,
  getDeviceCredential: () => "bearer-only",
});
await new MediaProductClient(deviceTransport).job_lease(
  { job_id: "job-1", lease_seconds: 30, expected_revision: 1 },
  { idempotencyKey: "lease-key" },
);
assert.equal(
  (requests.at(-1)!.init.headers as Record<string, string>).Authorization,
  "Bearer bearer-only",
);

const sessionOrDevice = new MediaProductHttpTransport({
  fetchImpl: fakeFetch,
  getCsrfToken: () => "session-csrf",
  getDeviceCredential: () => "mixed-device",
});
await new MediaProductClient(sessionOrDevice).job_list({ limit: 1 });
assert.equal(
  (requests.at(-1)!.init.headers as Record<string, string>).Authorization,
  "Bearer mixed-device",
);
const sessionOnly = new MediaProductHttpTransport({
  fetchImpl: fakeFetch,
  getCsrfToken: () => "session-csrf",
});
await new MediaProductClient(sessionOnly).job_list({ limit: 1 });
assert.equal(
  (requests.at(-1)!.init.headers as Record<string, string>).Authorization,
  undefined,
);

await assert.rejects(
  () =>
    new MediaProductClient(
      new MediaProductHttpTransport({ fetchImpl: fakeFetch }),
    ).job_create(
      {
        pipeline_id: "p",
        pipeline_version: "1",
        catalog_digest: "d",
        device_id: "d",
        input_refs: [],
        output_selection: [],
      },
      { idempotencyKey: "csrf-missing" },
    ),
  /CSRF/,
);
await new MediaProductClient(
  new MediaProductHttpTransport({ fetchImpl: fakeFetch }),
).device_pair(
  {
    pair_code: "pair",
    device_label: "Mac",
    device_platform: "macos",
    client_version: "1",
  },
  { idempotencyKey: "pair-key" },
);
assert.equal(
  (requests.at(-1)!.init.headers as Record<string, string>)["X-OpenClaw-CSRF"],
  undefined,
);

await assert.rejects(
  () =>
    new MediaProductHttpTransport({ fetchImpl: fakeFetch }).request(
      "job_create",
      {
        method: "POST",
        path: "/jobs",
        query: {},
        body: {},
        authSource: "session",
        ownerRule: "tenant",
        idempotency: "required",
      },
    ),
  /幂等键/,
);

const mediaAgent = readFileSync(
  new URL("../../src/media/pages/ordinary/MediaAgentPage.tsx", import.meta.url),
  "utf8",
);
const archives = readFileSync(
  new URL("../../src/media/pages/ordinary/ArchivesPage.tsx", import.meta.url),
  "utf8",
);
const mediaWebApi = readFileSync(
  new URL("../../src/media/mediaWebApi.ts", import.meta.url),
  "utf8",
);
const runConsumers = [
  "../../src/media/pages/ordinary/RunsPage.tsx",
  "../../src/media/CreationRunDetailPage.tsx",
  "../../src/media/pages/ordinary/DecisionsPage.tsx",
  "../../src/media/pages/ordinary/PublishingPage.tsx",
  "../../src/media/ui/ordinaryPagePrimitives.tsx",
].map((relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8"),
);
assert.match(mediaWebApi, /loadMediaJobDetail/);
for (const source of [mediaWebApi, ...runConsumers]) {
  assert.doesNotMatch(source, /loadRun(?:Summaries|Base|Section)|\/media\/api\/runs|analysis-runs/);
}
for (const source of [mediaAgent, archives]) {
  assert.doesNotMatch(
    source,
    /contentBase64|deviceCredential|Authorization|原始 prompt|provider 流量/i,
  );
}
for (const label of ["流程目录", "本地运行", "设备与客户端"])
  assert.match(mediaAgent, new RegExp(label));
for (const wrapper of [
  "loadMediaPipelines",
  "loadMediaDevices",
  "loadMediaJobs",
  "createMediaJob",
  "createMediaPairCode",
])
  assert.match(mediaAgent, new RegExp(wrapper));
for (const retiredLabel of ["云端能力目录", "云端能力", "能力检查器", "网页任务"])
  assert.doesNotMatch(mediaAgent, new RegExp(retiredLabel));
for (const retiredWrapper of ["loadMediaCapabilities", "openWorkspace"])
  assert.doesNotMatch(mediaAgent, new RegExp(retiredWrapper));
assert.match(mediaAgent, /AbortController/);
assert.match(mediaAgent, /requestGeneration/);
assert.match(mediaAgent, /isCurrentW1Request/);
for (const label of [
  "loadArchiveList",
  "loadArchiveDetail",
  "planArchiveDelete",
  "deleteArchive",
  "readbackArchive",
])
  assert.match(archives, new RegExp(label));
for (const label of ["Final", "Proxy", "WAV", "仅本地媒体"])
  assert.match(archives, new RegExp(label));
assert.match(archives, /data-page-terminal-surface="primary"/);
assert.match(archives, /data-page-terminal-surface="inspector"/);
assert.match(archives, /mutationGeneration/);
assert.match(archives, /mutationController/);
assert.match(archives, /invalidateMutation/);
assert.match(
  archives,
  /generation,\s*mutationGeneration\.current,\s*controller\.signal/,
);
assert.match(mediaWebApi, /planArchiveDelete[\s\S]*signal\?: AbortSignal/);
assert.match(mediaWebApi, /deleteArchive[\s\S]*signal\?: AbortSignal/);
assert.match(mediaWebApi, /readbackArchive[\s\S]*signal\?: AbortSignal/);
assert.match(
  mediaWebApi,
  /archive_delete_plan\([\s\S]*?\{ idempotencyKey:[\s\S]*?\bsignal \},\s*\)/,
);
assert.match(
  mediaWebApi,
  /archive_delete\([\s\S]*?\{\s*idempotencyKey:[\s\S]*?\bsignal,\s*\},\s*\)/,
);
assert.match(
  mediaWebApi,
  /archive_readback\([\s\S]*?\{\s*idempotencyKey:[\s\S]*?\bsignal,\s*\},\s*\)/,
);
assert.doesNotMatch(
  archives,
  /if \(state === '(?:loading|permission|error|empty)'\) return/,
);
for (const state of [
  "checking",
  "unauthenticated",
  "unavailable",
  "authenticated",
])
  assert.match(mediaAgent, new RegExp(state));
for (const state of ["loading", "permission", "error", "empty", "ready"])
  assert.match(archives, new RegExp(state));
for (const state of ["loading", "permission", "error", "empty", "ready"])
  assert.match(mediaAgent, new RegExp(state));
const raceController = new AbortController();
assert.equal(isCurrentW1Request(1, 1, raceController.signal), true);
raceController.abort();
assert.equal(isCurrentW1Request(1, 1, raceController.signal), false);
assert.equal(isCurrentW1Request(1, 2, new AbortController().signal), false);
assert.equal(
  isCurrentW1Request(1, 3, new AbortController().signal),
  false,
  "A→B→A must invalidate mutation generation 1 when current generation is 3",
);
const archiveMutationSignal = new AbortController();
await client.archive_delete_plan(
  { archive_id: "archive/1" },
  { idempotencyKey: "plan-key", signal: archiveMutationSignal.signal },
);
assert.equal(requests.at(-1)!.init.signal, archiveMutationSignal.signal);
await client.archive_readback(
  {
    archive_id: "archive/1",
    readback_receipt_ref: "receipt-1",
    observed_refs: [],
  },
  { idempotencyKey: "readback-key", signal: archiveMutationSignal.signal },
);
assert.equal(requests.at(-1)!.init.signal, archiveMutationSignal.signal);
console.log("W1 focused contract/page QA passed");
