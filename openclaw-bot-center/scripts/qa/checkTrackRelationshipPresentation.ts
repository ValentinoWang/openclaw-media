import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  formatFitScore,
  relationshipRoleDisplayLabel,
  relationshipStatusDisplayLabel,
} from "../../src/media/ui/ordinaryDataLabels";

const pageSource = readFileSync(
  new URL("../../src/media/pages/ordinary/TracksPage.tsx", import.meta.url),
  "utf8",
);

assert.equal(formatFitScore(95), "匹配度 95%");
assert.equal(formatFitScore(90.4), "匹配度 90%");
assert.equal(formatFitScore(-1), "匹配度不可用");
assert.equal(formatFitScore(101), "匹配度不可用");
assert.equal(formatFitScore(Number.NaN), "匹配度不可用");

for (const role of [
  "标杆账号",
  "竞品账号",
  "合作候选",
  "素材来源",
  "同赛道观察",
  "风险账号",
]) {
  assert.equal(relationshipRoleDisplayLabel(role), role);
}
assert.equal(relationshipRoleDisplayLabel(""), "未设置赛道角色");

assert.equal(relationshipStatusDisplayLabel("candidate"), "待确认");
assert.equal(relationshipStatusDisplayLabel("active"), "已纳入");
assert.equal(relationshipStatusDisplayLabel("rejected"), "已排除");
assert.notEqual(relationshipStatusDisplayLabel("active"), "已确认");
assert.equal(relationshipStatusDisplayLabel("confirmed"), "关系状态待确认");

assert.match(pageSource, /title="账号与赛道"/);
for (const label of ["自有账号", "赛道概览", "对标账号"]) {
  assert.ok(pageSource.includes(`label: "${label}"`), `missing primary tab ${label}`);
}
for (const label of ["待确认", "已关注", "已忽略"]) {
  assert.ok(pageSource.includes(`label: "${label}"`), `missing benchmark queue ${label}`);
}
for (const role of ["标杆账号", "同赛道观察", "合作候选"]) {
  assert.ok(pageSource.includes(`"${role}"`), `missing benchmark role ${role}`);
}
assert.match(pageSource, /data-page-list="owned-accounts"/);
assert.match(pageSource, /data-page-list="tracks"/);
assert.match(pageSource, /data-page-list="benchmark-accounts"/);
assert.match(pageSource, /onShowOwned\(track\.publicTrackId\)/);
assert.match(pageSource, /onShowBenchmarks\(track\.publicTrackId\)/);
assert.match(pageSource, /title="平台覆盖"/);
assert.match(pageSource, /getAccountMonitor/);
assert.match(pageSource, /monitor_unavailable/);
assert.match(pageSource, /账号监控暂不可用/);
assert.match(pageSource, /H00 账号监控表/);
assert.match(pageSource, /https:\/\/tcnwueberajc\.feishu\.cn\/base\/OmjkbgBkwa2JEysEN8uc5PMhnTb\?table=tblc65xqnUjSw9Ah/);
for (const field of ["账号名称", "近期作品链接", "启用", "最近运行时间", "最近日报摘要"]) {
  assert.ok(pageSource.includes(`"${field}"`), `missing H00 monitor field ${field}`);
}
assert.match(pageSource, /trackById\.get\(relationship\.publicTrackId\)/);
assert.match(pageSource, /creatorById\.get\(relationship\.publicCreatorId\)/);
assert.match(pageSource, /import \{ PlatformIdentity \} from "\.\.\/\.\.\/ui\/PlatformIdentity";/);
assert.ok(
  (pageSource.match(/<PlatformIdentity\b/g) ?? []).length >= 5,
  "TracksPage must use the shared platform identity for every platform-bearing surface",
);
assert.doesNotMatch(pageSource, /platformDisplayLabel/);
assert.match(pageSource, /capabilityId: "track_creator_membership_query"/);
assert.match(pageSource, /variantId: "preview"/);
for (const fieldKey of [
  "id",
  "id_869e433eadc3",
  "field_c47b54e84e79",
  "field_76a17ec0d96f",
  "field_f93c8842699c",
]) {
  assert.match(pageSource, new RegExp(`${fieldKey}:`), `missing relationship preview prefill ${fieldKey}`);
}
assert.match(pageSource, /查看关系判断/);
assert.doesNotMatch(pageSource, /title="已确认关系"/);
assert.doesNotMatch(pageSource, />\s*\{item\.public(?:Track|Creator)Id\}\s*</);
assert.doesNotMatch(pageSource, /确认人|确认时间/);

console.log("track relationship presentation: PASS");
