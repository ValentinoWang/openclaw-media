import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { mediaWebTaskSchema } from "../../src/schemas/mediaWebTaskSchema";
import {
  latestTaskFeed,
  settlementStageLabel,
  shouldSubscribeToTask,
  stableTaskErrorMessage,
  taskSettlementPresentation,
} from "../../src/media/recentTaskPresentation";

const completedTask = {
  schemaVersion: "media_web_task_v3",
  taskId: "task-v3-completed",
  requestId: "request-v3-completed",
  modelCalls: [],
  capabilityId: "selfmedia_creation",
  capabilityPath: ["创作", "内容创作"],
  variantId: "default",
  params: {
    platform: "xiaohongshu",
    field_311bb313fdec: "customer-main",
  },
  confirmationReceipt: null,
  status: "multi_system_readback_complete",
  settlementStage: "multi_system_readback_complete",
  terminal: true,
  progress: 100,
  summary: "内容创作已经完成多系统读回",
  createdAt: "2026-08-14T01:00:00Z",
  updatedAt: "2026-08-14T01:02:00Z",
  confirmation: {
    state: "not_required",
    required: false,
    note: "",
    decidedAt: "",
  },
  result: {
    ok: true,
    status: "completed",
    reply: "创作结果已生成。",
    links: [
      { label: "打开创作文档", url: "https://example.test/doc/created" },
    ],
    receipt: null,
  },
  error: null,
  eventCursor: 8,
  accountBinding: {
    userPublicId: "user-public-a",
    ownedAccountPublicId: "account-public-a",
    relationshipRef: "relationship:101",
    platform: "xiaohongshu",
    normalizedAccount: "customer-main",
  },
  attempt: {
    attemptId: "attempt-public-2",
    runnerId: "runner...0001",
    executorId: "executor...0001",
    status: "succeeded",
    attemptNumber: 2,
    recoveryOfAttemptId: "attempt-public-1",
    startedAt: "2026-08-14T01:00:05Z",
    heartbeatAt: "2026-08-14T01:01:30Z",
    finishedAt: "2026-08-14T01:02:00Z",
  },
  readbacks: {
    database: {
      status: "verified",
      required: true,
      applicability: {},
      checkedAt: "2026-08-14T01:01:00Z",
    },
    external: {
      status: "verified",
      required: true,
      applicability: { provider: "feishu" },
      checkedAt: "2026-08-14T01:01:20Z",
    },
    web: {
      status: "verified",
      required: true,
      applicability: {},
      checkedAt: "2026-08-14T01:02:00Z",
    },
  },
  missingReadbacks: [],
  receipt: {
    receiptId: "mtr-receipt-public-1",
    schemaVersion: "media_e2e_receipt_v1",
    digest: `sha256:${"a".repeat(64)}`,
    status: "multi_system_readback_complete",
    createdAt: "2026-08-14T01:02:00Z",
  },
} as const;

const parsedCompleted = mediaWebTaskSchema.parse(completedTask);
const completedPresentation = taskSettlementPresentation(parsedCompleted);
assert.equal(completedPresentation.complete, true);
assert.equal(completedPresentation.stageLabel, "多系统读回完成");
assert.equal(
  completedPresentation.bindingSummary,
  "xiaohongshu · customer-main",
);
assert.equal(completedPresentation.attemptSummary, "第 2 次处理 · 已完成");
assert.equal(completedPresentation.executorSummary, null);
assert.equal(completedPresentation.recoverySummary, "已从上一次中断处恢复");
assert.equal(completedPresentation.missingReadbackLabels.length, 0);
assert.equal(completedPresentation.receiptId, "mtr-receipt-public-1");

const waitingTask = mediaWebTaskSchema.parse({
  ...completedTask,
  taskId: "task-v3-waiting",
  status: "waiting_external_readback",
  settlementStage: "external_readback",
  terminal: false,
  progress: 75,
  attempt: { ...completedTask.attempt, recoveryOfAttemptId: null },
  readbacks: {
    ...completedTask.readbacks,
    external: {
      ...completedTask.readbacks.external,
      status: "pending",
      checkedAt: null,
    },
    web: {
      ...completedTask.readbacks.web,
      status: "pending",
      checkedAt: null,
    },
  },
  missingReadbacks: ["external", "web"],
  receipt: null,
});
const waitingPresentation = taskSettlementPresentation(waitingTask);
assert.equal(waitingPresentation.complete, false);
assert.equal(waitingTask.result?.ok, true);
assert.equal(waitingPresentation.stageLabel, "等待外部系统读回");
assert.deepEqual(waitingPresentation.missingReadbackLabels, ["外部系统", "网页"]);
assert.equal(waitingPresentation.receiptId, null);

for (const [code, expected] of [
  ["required_input_missing", "请补充必填的平台、客户自有账号或能力输入。"],
  ["account_relationship_unavailable", "无法确认所选客户账号关系。"],
  ["account_relationship_conflict", "所选客户账号关系存在冲突。"],
] as const) {
  assert.equal(stableTaskErrorMessage(code, "不稳定的后端原文"), expected);
}
assert.equal(stableTaskErrorMessage("other_error", "后端可读提示"), "后端可读提示");
assert.equal(
  stableTaskErrorMessage("other_error", "executor lease expired"),
  "任务未完成，请稍后重试。",
);
assert.equal(settlementStageLabel("runner_claimed"), "执行器已领取");
assert.equal(settlementStageLabel("generating"), "正在生成内容");

assert.equal(
  mediaWebTaskSchema.safeParse({ ...completedTask, settlementStage: undefined }).success,
  false,
  "the settlement stage must survive the frontend API boundary",
);
assert.equal(
  mediaWebTaskSchema.safeParse({
    ...completedTask,
    result: {
      ok: true,
      status: "completed",
      reply: "旧任务结构",
      publicLinks: [],
    },
  }).success,
  false,
  "legacy publicLinks task results must not replace links and receipt",
);

const visible = latestTaskFeed([
  completedTask,
  { ...completedTask, taskId: "older-task", createdAt: "2026-08-14T00:00:00Z" },
  {
    ...completedTask,
    taskId: "technical-preview",
    capabilityId: "universal_deletion",
    variantId: "preview",
  },
]);
assert.deepEqual(
  visible.map((task) => task.taskId),
  ["task-v3-completed", "older-task"],
);

const activeDeletionConfirmation = {
  ...completedTask,
  taskId: "active-deletion-confirmation",
  capabilityId: "universal_deletion",
  variantId: "confirm",
  status: "awaiting_confirmation",
  terminal: false,
  confirmationReceipt: {
    kind: "deletion_preview",
    expiresAt: "2099-01-01T00:00:00Z",
  },
};
assert.equal(shouldSubscribeToTask(activeDeletionConfirmation), true);
assert.equal(
  shouldSubscribeToTask({
    ...activeDeletionConfirmation,
    taskId: "expired-deletion-confirmation",
    confirmationReceipt: {
      kind: "deletion_preview",
      expiresAt: "2020-01-01T00:00:00Z",
    },
  }),
  false,
);
assert.equal(shouldSubscribeToTask(completedTask), false);

const workspaceSource = readFileSync(
  new URL("../../src/media/MediaWebWorkspace.tsx", import.meta.url),
  "utf8",
);
const overviewSource = readFileSync(
  new URL("../../src/media/pages/ordinary/OverviewPage.tsx", import.meta.url),
  "utf8",
);
const runsSource = readFileSync(
  new URL("../../src/media/pages/ordinary/RunsPage.tsx", import.meta.url),
  "utf8",
);
for (const [name, source] of [
  ["task workspace", workspaceSource],
  ["overview", overviewSource],
  ["ordinary runs", runsSource],
] as const) {
  assert.match(
    source,
    /TaskSettlementDetails/,
    `${name} must render the server task settlement projection`,
  );
}
assert.doesNotMatch(
  workspaceSource + overviewSource + runsSource,
  /localStorage|sessionStorage/,
  "task completion must not be restored from local success state",
);
assert.match(
  workspaceSource,
  /const taskResultSuccessful =\s*task\.result\?\.ok === true && taskSettlementPresentation\(task\)\.complete;/,
  "the generic result card must derive success from final receipt settlement",
);
assert.match(
  workspaceSource,
  /className={`task-result \$\{taskResultSuccessful \? "is-success" : "is-warning"\}`}/,
  "an ok intermediate result must not receive success styling before settlement",
);

console.log(
  "recent task presentation: pass (binding, stages, readbacks, recovery, receipts, stable errors, and server-only restoration)",
);
