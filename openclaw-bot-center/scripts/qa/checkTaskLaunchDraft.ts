import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  capabilityCatalogSchema,
  type CapabilityCatalog,
  type CapabilityDefinition,
} from "../../src/schemas/capabilityCatalogSchema";
import { DynamicTaskForm } from "../../src/media/task-launch/DynamicTaskForm";
import { TaskReview } from "../../src/media/task-launch/TaskReview";
import {
  buildTaskRequest,
  emptyTaskDraft,
  taskDraftReducer,
} from "../../src/media/task-launch/taskDraft";
import { workspacePrefillAction } from "../../src/media/task-launch/workspacePrefill";

Object.assign(globalThis, { React });

const field = (
  key: string,
  label: string,
  valueType: "string" | "array" = "string",
) => ({
  key,
  sourceLabel: label,
  label,
  inputType:
    valueType === "array"
      ? ("multiselect" as const)
      : key.includes("url")
        ? ("url" as const)
        : ("text" as const),
  valueType,
  format: {
    name: key.includes("url") ? ("uri" as const) : ("" as const),
    min: null,
    max: null,
    pattern: "",
    urlSchemes: key.includes("url") ? ["http" as const, "https" as const] : [],
  },
  required: false,
  defaultValue: null,
  options: [],
  placeholder: "",
  helpText: "",
  order: 0,
  visibleWhen: [],
  enabledWhen: [],
  semanticOwner: "test:semantic",
  persistenceOwner: "test:persistence",
  provenance: "declared_field_definition" as const,
});

const capability = (
  overrides: Partial<CapabilityDefinition>,
): CapabilityDefinition => ({
  capabilityId: "creator_profile_upsert",
  internalCode: "creator_profile_upsert",
  internalLabel: "博主-入库",
  label: "博主-入库",
  displayName: "博主-入库",
  description: "录入博主",
  example: "",
  aliases: [],
  bots: ["Media bot"],
  hierarchy: {
    categoryId: "account_content_map",
    categoryName: "账号内容地图",
    categoryOrder: 9,
    objectId: "creator",
    objectName: "博主",
    objectOrder: 0,
    actionId: "create",
    actionName: "入库",
    actionOrder: 1,
    pathIds: ["account_content_map", "creator", "create"],
    pathNames: ["账号内容地图", "博主", "入库"],
  },
  fields: [
    field("platform", "平台"),
    field("author_id", "作者ID"),
    field("profile_url", "主页链接"),
    field("account_name", "账号名称"),
    field("expertise_domains", "账号类型 / 内容领域", "array"),
  ],
  variants: [
    {
      variantId: "manual",
      label: "手工入库",
      requiredFields: ["platform", "expertise_domains"],
      requiredAnyOf: [["author_id", "profile_url"]],
      preActions: [],
      controlledInputFields: [],
      forbiddenFields: [],
      fieldValues: {},
    },
  ],
  validationRules: [
    {
      type: "at_least_one",
      fields: ["author_id", "profile_url"],
      message: "作者ID或主页链接至少填写一项",
    },
  ],
  supportedAttachments: [],
  attachmentPolicy: { types: [], maxCount: 0, maxBytes: 0 },
  status: "implemented",
  enabled: true,
  visibility: "public",
  riskLevel: "high",
  effect: "write",
  confirmationPolicy: {
    stage: "after_candidate",
    message: "先生成候选，再确认写入。",
  },
  handler: "handle_博主_入库",
  consumes: [],
  produces: [],
  writesTo: ["CreatorProfile"],
  sourceSystem: "media",
  ssotRefs: [],
  inputContractSource: "test",
  searchKeywords: ["博主", "入库"],
  provenance: "test",
  displayOrder: 0,
  requiresConfirmation: true,
  ...overrides,
});

const creator = capability({});
const lookup = capability({
  capabilityId: "creator_profile_lookup",
  internalCode: "creator_profile_lookup",
  label: "博主",
  effect: "read",
  riskLevel: "low",
  writesTo: [],
  confirmationPolicy: { stage: "none", message: "" },
  requiresConfirmation: false,
  hierarchy: {
    categoryId: "account_content_map",
    categoryName: "账号内容地图",
    categoryOrder: 9,
    objectId: "creator",
    objectName: "博主",
    objectOrder: 0,
    actionId: "query",
    actionName: "查询",
    actionOrder: 0,
    pathIds: ["account_content_map", "creator", "query"],
    pathNames: ["账号内容地图", "博主", "查询"],
  },
  fields: [field("platform", "平台"), field("account_name", "账号名称")],
  variants: [
    {
      variantId: "query",
      label: "查询",
      requiredFields: ["account_name"],
      requiredAnyOf: [],
      preActions: [],
      controlledInputFields: [],
      forbiddenFields: [],
      fieldValues: {},
    },
  ],
  validationRules: [],
});
const deletionPreview = capability({
  capabilityId: "universal_deletion",
  internalCode: "universal_deletion",
  label: "内容产物删除",
  displayName: "内容产物删除",
  effect: "read",
  riskLevel: "low",
  writesTo: [],
  confirmationPolicy: { stage: "none", message: "" },
  requiresConfirmation: false,
  fields: [field("id", "目标ID")],
  variants: [
    {
      variantId: "preview",
      label: "仅预览删除范围",
      requiredFields: ["id"],
      requiredAnyOf: [],
      preActions: [],
      controlledInputFields: [],
      forbiddenFields: [],
      fieldValues: {},
    },
  ],
});
const catalog: CapabilityCatalog = capabilityCatalogSchema.parse({
  schemaVersion: "capability_catalog_v3",
  catalogVersion: `sha256:${"a".repeat(64)}`,
  capabilities: [creator, lookup, deletionPreview],
});

const disabledCatalog: CapabilityCatalog = {
  ...catalog,
  capabilities: [{ ...creator, enabled: false }],
};

for (const [label, action, expectedMessage] of [
  [
    "unknown capability",
    {
      type: "prefill" as const,
      prefill: { capabilityId: "obsolete_display_id" },
      catalog,
    },
    "不在当前目录",
  ],
  [
    "disabled capability",
    {
      type: "prefill" as const,
      prefill: { capabilityId: creator.capabilityId },
      catalog: disabledCatalog,
    },
    "当前不可用",
  ],
  [
    "invalid variant",
    {
      type: "prefill" as const,
      prefill: { capabilityId: creator.capabilityId, variantId: "obsolete_variant" },
      catalog,
    },
    "不属于能力",
  ],
] as const) {
  const rejected = taskDraftReducer(emptyTaskDraft(catalog.catalogVersion), action);
  assert.equal(rejected.phase, "error", `${label} prefill must enter an explicit error state`);
  assert.equal(rejected.capabilityId, "", `${label} prefill must not retain a stale capability`);
  assert.match(rejected.error, new RegExp(expectedMessage));
}

const disabledSelection = taskDraftReducer(emptyTaskDraft(catalog.catalogVersion), {
  type: "selectCapability",
  capability: disabledCatalog.capabilities[0],
});
assert.equal(disabledSelection.phase, "error", "manual selection must reject disabled capabilities");

const disabledReview = taskDraftReducer(
  {
    ...emptyTaskDraft(catalog.catalogVersion),
    phase: "editing",
    capabilityId: creator.capabilityId,
    variantId: "manual",
  },
  { type: "review", catalog: disabledCatalog },
);
assert.equal(disabledReview.phase, "error", "review must reject a capability disabled after selection");

assert.deepEqual(
  workspacePrefillAction(catalog),
  { type: "clear", catalogVersion: catalog.catalogVersion },
  "a generic workspace opening must clear contextual state once the catalog is available",
);
assert.equal(
  workspacePrefillAction(catalog, { capabilityId: creator.capabilityId }).type,
  "prefill",
  "ordinary contextual launches must use normal prefill",
);
assert.equal(
  workspacePrefillAction(catalog, { capabilityId: "universal_deletion", variantId: "preview" }).type,
  "prefillReview",
  "deletion contextual launches must retain their direct-review path",
);

const prefilledWithUnknownParams = taskDraftReducer(
  emptyTaskDraft(catalog.catalogVersion),
  {
    type: "prefill",
    prefill: {
      capabilityId: creator.capabilityId,
      variantId: "manual",
      params: {
        platform: "小红书",
        unknown_prefill_key: "must-not-leak",
        profile_url: 123,
      },
    },
    catalog,
  },
);
assert.deepEqual(
  prefilledWithUnknownParams.params,
  { platform: "小红书" },
  "prefill must keep only declared fields with matching value types",
);

const reviewPrefilledWithUnknownParams = taskDraftReducer(
  emptyTaskDraft(catalog.catalogVersion),
  {
    type: "prefillReview",
    prefill: {
      capabilityId: creator.capabilityId,
      variantId: "manual",
      params: {
        platform: "小红书",
        unknown_review_key: "must-not-leak",
        expertise_domains: "wrong-type",
      },
    },
    catalog,
  },
);
assert.deepEqual(
  reviewPrefilledWithUnknownParams.params,
  { platform: "小红书" },
  "prefillReview must keep only declared fields with matching value types",
);

const dynamicFormMarkup = renderToStaticMarkup(
  React.createElement(DynamicTaskForm, {
    capability: creator,
    draft: emptyTaskDraft(catalog.catalogVersion),
    onVariant: () => undefined,
    onField: () => undefined,
    onUploads: () => undefined,
  }),
);
const requiredMarkup = dynamicFormMarkup.match(
  /required-field-group[\s\S]*?<\/section>/,
)?.[0] ?? "";
assert.match(requiredMarkup, /task-field-platform/);
assert.doesNotMatch(
  requiredMarkup,
  /task-field-author_id|task-field-profile_url/,
  "requiredAnyOf members must not render as single-field required inputs",
);
assert.match(
  dynamicFormMarkup,
  /作者ID或主页链接/,
  "requiredAnyOf must retain a group-level prompt",
);

const initialDeletionDraft = emptyTaskDraft(catalog.catalogVersion);
const directDeletionPreview = taskDraftReducer(
  initialDeletionDraft,
  {
    type: "prefillReview",
    prefill: {
      capabilityId: "universal_deletion",
      variantId: "preview",
      params: { id: "asset_item_20260620_cff58f08" },
    },
    catalog,
  },
);
assert.equal(
  directDeletionPreview.phase,
  "review",
  "a contextual delete click must bypass the generic capability form",
);
assert.equal(
  directDeletionPreview.params.id,
  "asset_item_20260620_cff58f08",
);
assert.notEqual(
  directDeletionPreview.idempotencyKey,
  initialDeletionDraft.idempotencyKey,
  "a contextual deletion request must receive a fresh submission identity",
);
const nextDeletionPreview = taskDraftReducer(directDeletionPreview, {
  type: "prefillReview",
  prefill: {
    capabilityId: "universal_deletion",
    variantId: "preview",
    params: { id: "asset_item_20260620_0a849194" },
  },
  catalog,
});
assert.notEqual(
  nextDeletionPreview.idempotencyKey,
  directDeletionPreview.idempotencyKey,
  "regenerating or changing a deletion preview must not reuse the earlier task key",
);

let draft = taskDraftReducer(emptyTaskDraft(), {
  type: "catalogLoaded",
  catalog,
});
draft = taskDraftReducer(draft, {
  type: "selectCapability",
  capability: creator,
});
draft = taskDraftReducer(draft, { type: "review", catalog });
assert.deepEqual(
  new Set(draft.issues.map((item) => item.code)),
  new Set(["required", "at_least_one"]),
);

for (const [key, value] of Object.entries({
  platform: "小红书",
  profile_url: "https://example.com/profile",
  expertise_domains: ["运动训练"],
})) {
  draft = taskDraftReducer(draft, { type: "updateField", key, value });
}
draft = taskDraftReducer(draft, { type: "review", catalog });
assert.equal(draft.phase, "review");
const stableKey = draft.idempotencyKey;
draft = taskDraftReducer(draft, { type: "submitStart" });
draft = taskDraftReducer(draft, { type: "submitFailure", message: "retry" });
assert.equal(draft.idempotencyKey, stableKey);

const keyBeforeEdit = draft.idempotencyKey;
draft = taskDraftReducer(draft, { type: "edit" });
assert.equal(
  draft.idempotencyKey,
  keyBeforeEdit,
  "opening the exact same request for editing must preserve replay safety",
);
draft = taskDraftReducer(draft, {
  type: "updateField",
  key: "profile_url",
  value: "https://example.com/updated-profile",
});
assert.notEqual(
  draft.idempotencyKey,
  keyBeforeEdit,
  "changing canonical request content must rotate the task key",
);

draft = taskDraftReducer(draft, {
  type: "selectCapability",
  capability: lookup,
});
assert.deepEqual(
  draft.params,
  { platform: "小红书" },
  "capability changes preserve only compatible fields",
);

const requestId = "request-current";
draft = taskDraftReducer(draft, { type: "decomposeStart", requestId });
const stale = taskDraftReducer(draft, {
  type: "decomposeFailure",
  requestId: "request-stale",
  message: "stale",
});
assert.equal(stale, draft, "stale AI responses must not mutate the draft");

const aiResponse = {
  schemaVersion: "3" as const,
  pathStatus: "matched" as const,
  needSummary: "录入博主",
  routeExplanation: "匹配入库",
  guidancePlanId: "capplan_abcdefghijklmnop",
  steps: [
    {
      order: 1,
      capabilityId: creator.capabilityId,
      variantId: "manual",
      capabilityPath: ["account_content_map", "creator", "create"],
      extractedParams: {
        platform: "小红书",
        profile_url: "https://example.com/profile",
        expertise_domains: ["运动训练"],
        unknown_ai_key: "must-not-leak",
        account_name: 123,
      },
      confidence: 0.95,
      evidence: [],
      issues: [],
    },
  ],
  copyProjection: "【博主-入库】",
};
const aiDraft = taskDraftReducer(draft, {
  type: "decomposeSuccess",
  requestId,
  response: aiResponse,
  catalog,
});
const manualDraft = { ...aiDraft, initiation: "manual" as const };
const aiRequest = buildTaskRequest(aiDraft, []);
const manualRequest = buildTaskRequest(manualDraft, []);
assert.deepEqual(
  { ...aiRequest, initiation: undefined },
  { ...manualRequest, initiation: undefined },
  "AI and manual submit identical invocation facts",
);
assert.equal(aiRequest.initiation, "ai");
assert.equal(manualRequest.initiation, "manual");
assert.equal("unknown_ai_key" in aiRequest.params, false);
assert.equal("account_name" in aiRequest.params, false);

const constrained = capability({
  fields: [
    {
      ...field("platform", "平台"),
      inputType: "select",
      options: [
        { value: "小红书", label: "小红书", aliases: [], source: "test" },
      ],
    },
  ],
  variants: [
    {
      variantId: "manual",
      label: "手工",
      requiredFields: ["platform"],
      requiredAnyOf: [],
      preActions: [],
      controlledInputFields: [],
      forbiddenFields: [],
      fieldValues: { platform: ["小红书"] },
    },
  ],
  validationRules: [],
  supportedAttachments: ["image"],
  attachmentPolicy: { types: ["image"], maxCount: 1, maxBytes: 4 },
});
const constrainedCatalog: CapabilityCatalog = capabilityCatalogSchema.parse({
  schemaVersion: "capability_catalog_v3",
  catalogVersion: `sha256:${"b".repeat(64)}`,
  capabilities: [constrained],
});
let constrainedDraft = taskDraftReducer(
  emptyTaskDraft(constrainedCatalog.catalogVersion),
  { type: "selectCapability", capability: constrained },
);
constrainedDraft = taskDraftReducer(constrainedDraft, {
  type: "updateField",
  key: "platform",
  value: "抖音",
});
constrainedDraft = taskDraftReducer(constrainedDraft, {
  type: "setUploads",
  files: [
    new File(["large"], "proof.pdf", { type: "application/pdf" }),
    new File(["x"], "extra.png", { type: "image/png" }),
  ],
});
constrainedDraft = taskDraftReducer(constrainedDraft, {
  type: "review",
  catalog: constrainedCatalog,
});
assert.deepEqual(
  new Set(constrainedDraft.issues.map((item) => item.code)),
  new Set([
    "invalid_option",
    "too_many_uploads",
    "upload_too_large",
    "invalid_upload_type",
  ]),
);

const systemFieldCapability = capability({
  fields: [
    ...creator.fields,
    {
      ...field("idempotency_receipt_id", "幂等收据 ID"),
      helpText: "用于防止重复提交的业务幂等标识。",
    },
  ],
});
const systemFieldDraft = taskDraftReducer(
  emptyTaskDraft(catalog.catalogVersion),
  { type: "selectCapability", capability: systemFieldCapability },
);
const systemFieldMarkup = renderToStaticMarkup(
  React.createElement(DynamicTaskForm, {
    capability: systemFieldCapability,
    draft: systemFieldDraft,
    onVariant: () => undefined,
    onField: () => undefined,
    onUploads: () => undefined,
  }),
);
assert.equal(
  systemFieldMarkup.includes("task-field-idempotency_receipt_id"),
  false,
  "system-managed idempotency fields must not render in the user task form",
);
assert.equal(
  /幂等|idempotency|重复提交保护/i.test(systemFieldMarkup),
  false,
  "system-managed terminology must not render in the user task form",
);

const workspaceSource = readFileSync(
  new URL("../../src/media/MediaWebWorkspace.tsx", import.meta.url),
  "utf8",
);
const mediaCss = readFileSync(
  new URL("../../src/media/media.css", import.meta.url),
  "utf8",
);
assert.match(
  workspaceSource,
  /!task\.terminal\s*\?\s*\(\s*<div className="task-progress"/s,
  "terminal tasks must not render a meaningless progress bar",
);
assert.match(
  workspaceSource,
  /confirmationReceiptSchema\.safeParse\(task\.result\?\.receipt\)/,
  "deletion preview receipts must pass the runtime schema before rendering",
);
assert.match(
  workspaceSource,
  /actionableReceipt\?\.kind === "deletion_preview"/,
  "deletion preview tasks must render only from a schema-validated receipt",
);
assert.match(
  workspaceSource,
  /task\.result && isDeletionPreview \?/,
  "all deletion preview outcomes must use the compact structured summary",
);
assert.doesNotMatch(
  mediaCss,
  /\.task-delete-action\s*\{[^}]*width:\s*100%/s,
  "deletion confirmation must not dominate the full drawer width",
);
assert.doesNotMatch(
  workspaceSource,
  /prefill\.capabilityId === "universal_deletion"\s*&&\s*prefill\.variantId === "preview"/s,
  "preview and confirmation must both bypass AI decomposition and capability selection",
);
assert.match(
  workspaceSource,
  /error\.code !== "idempotency_conflict"[\s\S]*newTaskIdempotencyKey\(\)[\s\S]*createMediaTask\(session, \{ \.\.\.request, idempotencyKey \}\)/,
  "a stale task key must be renewed and retried once without exposing an internal error",
);
assert.match(
  workspaceSource,
  /runtimeState === "authenticated" && draft\.phase === "idle"/,
  "recent task history must stay out of the active confirmation flow",
);
const deletionConfirm = capability({
  capabilityId: "universal_deletion",
  internalCode: "universal_deletion",
  label: "内容产物删除",
  displayName: "内容产物删除",
  effect: "destructive",
  riskLevel: "destructive",
  writesTo: ["target"],
  confirmationPolicy: { stage: "destructive_preview_apply", message: "确认删除" },
  requiresConfirmation: true,
  fields: [field("id", "目标ID"), field("action", "动作")],
  variants: [
    {
      variantId: "confirm",
      label: "确认删除",
      requiredFields: ["id", "action"],
      requiredAnyOf: [],
      preActions: [],
      controlledInputFields: [],
      forbiddenFields: [],
      fieldValues: { action: ["确认删除"] },
    },
  ],
});
const deletionConfirmDraft = {
  ...emptyTaskDraft(catalog.catalogVersion),
  phase: "review" as const,
  capabilityId: deletionConfirm.capabilityId,
  variantId: "confirm",
  params: { id: "asset_item_20260620_cff58f08", action: "确认删除" },
};
const deletionConfirmMarkup = renderToStaticMarkup(
  React.createElement(TaskReview, {
    draft: deletionConfirmDraft,
    capability: deletionConfirm,
    onEdit: () => undefined,
    onSubmit: () => undefined,
  }),
);
assert.match(deletionConfirmMarkup, /确认后将删除目标及其关联数据/);
assert.match(deletionConfirmMarkup, /asset_item_20260620_cff58f08/);
assert.equal(
  deletionConfirmMarkup.includes("内容产物删除"),
  false,
  "deletion confirmation must present the user action instead of the internal capability name",
);
assert.equal(
  deletionConfirmMarkup.includes("幂等"),
  false,
  "deletion confirmation must not expose internal replay terminology",
);
assert.equal(
  deletionConfirmMarkup.includes("返回修改"),
  false,
  "a confirmed deletion preview must not allow the target to be edited in place",
);

console.log("task launch draft contract passed");
