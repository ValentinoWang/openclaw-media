import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  confirmationReceiptProblem,
  confirmationReceiptState,
} from "../../src/media/confirmationReceiptExpiry";

const now = Date.parse("2026-08-09T00:00:00Z");
const activeReceipt = { expiresAt: "2026-08-09T00:00:01Z" };
const expiredReceipt = { expiresAt: "2026-08-09T00:00:00Z" };

assert.equal(confirmationReceiptState(activeReceipt, now), "active");
assert.equal(confirmationReceiptState(expiredReceipt, now), "expired");
assert.equal(confirmationReceiptState({ expiresAt: "invalid" }, now), "invalid");
assert.equal(confirmationReceiptState(null, now), "missing");

for (const capabilityId of [
  "universal_deletion",
  "creator_profile_upsert",
  "track_creator_membership_query",
]) {
  assert.equal(
    confirmationReceiptProblem(capabilityId, "confirm", activeReceipt, now),
    null,
  );
  assert.equal(
    confirmationReceiptProblem(capabilityId, "confirm", expiredReceipt, now),
    "expired",
  );
  assert.equal(
    confirmationReceiptProblem(capabilityId, "confirm", null, now),
    "missing",
  );
}
assert.equal(
  confirmationReceiptProblem("universal_deletion", "preview", null, now),
  null,
  "preview creation must not require an earlier receipt",
);

const workspaceSource = readFileSync(
  new URL("../../src/media/MediaWebWorkspace.tsx", import.meta.url),
  "utf8",
);
const recentTaskSource = readFileSync(
  new URL("../../src/media/recentTaskPresentation.ts", import.meta.url),
  "utf8",
);
const draftSource = readFileSync(
  new URL("../../src/media/task-launch/taskDraft.ts", import.meta.url),
  "utf8",
);
const reviewSource = readFileSync(
  new URL("../../src/media/task-launch/TaskReview.tsx", import.meta.url),
  "utf8",
);
assert.match(workspaceSource, /setInterval\([^,]+,\s*1_000\)/s);
assert.match(workspaceSource, /候选已过期/);
assert.match(workspaceSource, /关系预览已过期/);
assert.match(workspaceSource, /draft\.phase === "idle"/);
assert.match(workspaceSource, /newTaskIdempotencyKey\(\)/);
assert.doesNotMatch(workspaceSource, /幂等键已绑定其他任务请求/);
const cancelDeletionIntentSource = workspaceSource.match(
  /const cancelDeletionIntent = useCallback\([\s\S]*?\n  \);/,
)?.[0] ?? "";
assert.match(cancelDeletionIntentSource, /cancelMediaTask\(session, taskId\)/);
assert.doesNotMatch(cancelDeletionIntentSource, /confirmMediaTask\(session, taskId, "reject"\)/);
assert.match(recentTaskSource, /task\.variantId === "preview"/);
assert.match(recentTaskSource, /Number\.isFinite\(expiresAt\) && expiresAt > nowMs/);
assert.match(draftSource, /confirmationReceiptProblem\(/);
assert.match(draftSource, /refreshRequestIdentity\(/);
assert.match(reviewSource, /disabled=\{draft\.phase === "submitting" \|\| receiptProblem !== null\}/);
assert.match(reviewSource, /deletionConfirm\s*\?\s*"确认删除"/s);
assert.match(reviewSource, /className=\{deletionConfirm \? "danger-button" : "primary-button"\}/);

console.log("confirmation receipt expiry: pass");
