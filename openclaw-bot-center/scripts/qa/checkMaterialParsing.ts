import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  capabilityCatalogSchema,
  capabilityDefinitionSchema,
  type CapabilityDefinition,
} from "../../src/schemas/capabilityCatalogSchema";
import { mediaWebUploadSchema } from "../../src/schemas/mediaWebTaskSchema";
import { DynamicTaskForm } from "../../src/media/task-launch/DynamicTaskForm";
import { TaskReview } from "../../src/media/task-launch/TaskReview";
import {
  emptyTaskDraft,
  taskDraftReducer,
  validateDraft,
} from "../../src/media/task-launch/taskDraft";
import {
  getMaterialParsingPreview,
  materialParsingContract,
  materialParsingIssues,
  materialParsingServerFailureMessage,
} from "../../src/media/task-launch/materialParsing";

Object.assign(globalThis, { React });

const contractPath = resolve("contracts/material-parsing-coverage-v1.json");
const apiSource = readFileSync(resolve("src/media/mediaWebApi.ts"), "utf8");
const contractSource = readFileSync(contractPath, "utf8");
const contract = JSON.parse(contractSource) as typeof materialParsingContract;

assert.equal(contract.schemaVersion, "1");
assert.equal(contract.coverage.length, 54);
assert.equal(new Set(contract.coverage.map((item) => `${item.platform}:${item.materialType}`)).size, 54);
assert.equal(contract.platforms.length, 9);
assert.equal(contract.materialTypes.length, 6);
assert.deepEqual(
  contract.coverage.map((item) => `${item.platform}:${item.materialType}`),
  materialParsingContract.coverage.map((item) => `${item.platform}:${item.materialType}`),
  "the frontend must consume the copied contract without maintaining a second matrix",
);

function field(
  key: string,
  label: string,
  inputType: "text" | "textarea" = "text",
) {
  return {
    key,
    sourceLabel: label,
    label,
    inputType,
    valueType: "string" as const,
    format: {
      name: "" as const,
      min: null,
      max: null,
      pattern: "",
      urlSchemes: [],
    },
    required: false,
    defaultValue: null,
    options: [],
    placeholder: `请输入${label}`,
    helpText: `请输入${label}`,
    order: 0,
    visibleWhen: [],
    enabledWhen: [],
    semanticOwner: "test:material-parsing",
    persistenceOwner: "test:material-parsing",
    provenance: "declared_field_definition" as const,
  };
}

const sourceAssetCapability: CapabilityDefinition = capabilityDefinitionSchema.parse({
  capabilityId: "source_asset_intake",
  internalCode: "source_asset_intake",
  internalLabel: "素材",
  label: "素材",
  displayName: "素材入池",
  description: "收集来源素材。",
  example: "",
  aliases: [],
  bots: ["Media bot"],
  hierarchy: {
    categoryId: "source_inspiration",
    categoryName: "素材 / 灵感池",
    categoryOrder: 0,
    objectId: "source_asset",
    objectName: "素材",
    objectOrder: 0,
    actionId: "intake",
    actionName: "收集",
    actionOrder: 0,
    pathIds: ["source_inspiration", "source_asset", "intake"],
    pathNames: ["素材 / 灵感池", "素材", "收集"],
  },
  fields: [
    field("field_3be96f8eb83d", "素材类型"),
    field("field_05b36669c4ad", "用途"),
    field("platform", "平台"),
    field("field_311bb313fdec", "账号"),
    field("field_c675ffae69a2", "链接或文字素材", "textarea"),
    field("remark", "补充说明", "textarea"),
  ],
  variants: [
    {
      variantId: "default",
      label: "标准输入",
      requiredFields: [],
      requiredAnyOf: [],
      preActions: [],
      controlledInputFields: [],
      forbiddenFields: [],
      fieldValues: {},
    },
  ],
  validationRules: [],
  supportedAttachments: ["text", "url", "image", "video", "audio", "document"],
  attachmentPolicy: {
    types: ["text", "url", "image", "video", "audio", "document"],
    maxCount: 8,
    maxBytes: 52428800,
  },
  status: "implemented",
  enabled: true,
  visibility: "public",
  riskLevel: "medium",
  effect: "write",
  confirmationPolicy: { stage: "none", message: "" },
  handler: "handle_media_growth",
  consumes: [],
  produces: [],
  writesTo: [],
  sourceSystem: "media",
  ssotRefs: [],
  inputContractSource: "test",
  searchKeywords: ["素材"],
  provenance: "test",
  displayOrder: 0,
  requiresConfirmation: false,
});

const catalog = capabilityCatalogSchema.parse({
  schemaVersion: "capability_catalog_v3",
  catalogVersion: `sha256:${"c".repeat(64)}`,
  capabilities: [sourceAssetCapability],
});

function labelFor(values: readonly { id: string; label: string }[], id: string) {
  return values.find((item) => item.id === id)?.label ?? id;
}

function fileFor(materialType: string): File {
  const mimeType = {
    image: "image/png",
    audio: "audio/mpeg",
    video: "video/mp4",
    pdf: "application/pdf",
  }[materialType] ?? "application/octet-stream";
  return new File(["material"], `${materialType}.bin`, { type: mimeType });
}

function draftFor(
  platform: string,
  materialType: string,
  options: { source?: boolean; remark?: boolean } = {},
) {
  const source = options.source ?? true;
  const remark = options.remark ?? true;
  const params: Record<string, string> = {
    field_3be96f8eb83d: labelFor(materialParsingContract.materialTypes, materialType),
    platform: labelFor(materialParsingContract.platforms, platform),
  };
  if (source && (materialType === "text" || materialType === "url")) {
    params.field_c675ffae69a2 = materialType === "url"
      ? "https://example.com/source"
      : "原始文本素材";
  }
  if (remark) params.remark = "人工补充的素材主题、关键信息和用途";
  const uploads = source && !["text", "url"].includes(materialType)
    ? [fileFor(materialType)]
    : [];
  return {
    ...emptyTaskDraft(catalog.catalogVersion),
    phase: "editing" as const,
    capabilityId: "source_asset_intake",
    variantId: "default",
    params,
    uploads,
  };
}

const automatic = contract.coverage.filter((item) => item.mode === "automatic");
const manual = contract.coverage.filter((item) => item.mode === "manual_required");
assert.equal(automatic.length, 12);
assert.equal(manual.length, 42);

for (const item of contract.coverage) {
  const sourceDraft = draftFor(item.platform, item.materialType);
  const preview = getMaterialParsingPreview(sourceDraft);
  assert.equal(preview.platformId, item.platform);
  assert.equal(preview.materialTypeId, item.materialType);
  assert.equal(preview.mode, item.mode);
  assert.equal(preview.platformLabel, labelFor(contract.platforms, item.platform));
  assert.equal(preview.materialTypeLabel, labelFor(contract.materialTypes, item.materialType));
  if (item.mode === "automatic") {
    assert.equal(preview.methodLabel, "支持自动解析，提交时校验");
    assert.equal(preview.canConfirm, true);
    assert.equal(preview.expectedStatus, "completed_auto");
  } else {
    assert.equal(preview.methodLabel, "需要人工补充");
    assert.equal(preview.canConfirm, true);
    assert.equal(preview.expectedStatus, "completed_manual");
    assert.match(preview.failureReason, new RegExp(item.failurePrompt));
    assert.match(preview.manualSupplementResult, /不会显示为自动成功/);
  }
}

for (const item of contract.coverage) {
  const noRemark = draftFor(item.platform, item.materialType, { remark: false });
  const noRemarkPreview = getMaterialParsingPreview(noRemark);
  if (item.mode === "manual_required") {
    assert.equal(noRemarkPreview.canConfirm, false);
    assert.deepEqual(noRemarkPreview.missingFields, ["补充说明"]);
    assert.equal(noRemarkPreview.failureReason, item.failurePrompt);
    assert.equal(noRemarkPreview.nextAction, item.nextAction);
    assert.equal(materialParsingIssues(noRemark).length, 1);
    assert.equal(
      validateDraft(noRemark, sourceAssetCapability).some(
        (issue) => issue.ruleType === "material_parsing" && issue.fieldKey === "remark",
      ),
      true,
    );
  }
}

for (const materialType of ["image", "audio", "video", "pdf"]) {
  const missingUpload = draftFor("douyin", materialType, { remark: true, source: false });
  const preview = getMaterialParsingPreview(missingUpload);
  assert.equal(preview.canConfirm, false);
  assert.deepEqual(preview.missingFields, ["草稿附件"]);
  assert.equal(materialParsingIssues(missingUpload).length, 1);
}

const missingText = draftFor("douyin", "text", { source: false, remark: true });
assert.equal(getMaterialParsingPreview(missingText).canConfirm, false);
assert.deepEqual(getMaterialParsingPreview(missingText).missingFields, ["链接或文字素材"]);

const filledManual = taskDraftReducer(
  taskDraftReducer(
    taskDraftReducer(emptyTaskDraft(catalog.catalogVersion), {
      type: "selectCapability",
      capability: sourceAssetCapability,
    }),
    {
      type: "updateField",
      key: "field_3be96f8eb83d",
      value: "图片",
    },
  ),
  { type: "updateField", key: "platform", value: "抖音" },
);
const filledManualWithSource = taskDraftReducer(
  taskDraftReducer(filledManual, {
    type: "updateField",
    key: "remark",
    value: "补充图片主体、关键内容和用途",
  }),
  {
    type: "setUploads",
    files: [fileFor("image")],
  },
);
const reviewedManual = taskDraftReducer(filledManualWithSource, {
  type: "review",
  catalog,
});
assert.equal(reviewedManual.phase, "review");
assert.equal(reviewedManual.issues.length, 0);

const manualFormMarkup = renderToStaticMarkup(
  React.createElement(DynamicTaskForm, {
    capability: sourceAssetCapability,
    draft: draftFor("douyin", "image", { remark: false }),
    onVariant: () => undefined,
    onField: () => undefined,
    onUploads: () => undefined,
  }),
);
assert.match(manualFormMarkup, /需要人工补充/);
assert.match(manualFormMarkup, /当前不支持自动解析抖音图片素材。/);
assert.match(manualFormMarkup, /补充说明/);
assert.match(manualFormMarkup, /请补充图片主体、关键信息和用途后重新校验。/);
assert.match(manualFormMarkup, /type="file"/);

const reviewMarkup = renderToStaticMarkup(
  React.createElement(TaskReview, {
    draft: {
      ...draftFor("douyin", "image"),
      phase: "review" as const,
    },
    capability: sourceAssetCapability,
    onEdit: () => undefined,
    onSubmit: () => undefined,
  }),
);
for (const label of ["解析方式", "预期状态", "失败原因", "缺失字段", "人工补充结果", "下一步"]) {
  assert.match(reviewMarkup, new RegExp(label));
}
assert.match(reviewMarkup, /人工补充完成/);
assert.doesNotMatch(reviewMarkup, /自动解析成功/);

const unknownCombination = getMaterialParsingPreview({
  capabilityId: "source_asset_intake",
  params: {
    field_3be96f8eb83d: "未知素材类型",
    platform: "未知平台",
    field_c675ffae69a2: "原始内容",
    remark: "人工说明",
  },
  uploads: [],
});
assert.equal(unknownCombination.canConfirm, false);
assert.equal(unknownCombination.methodLabel, "无法确定解析方式");

const unrelated = getMaterialParsingPreview({
  capabilityId: "other_capability",
  params: {},
  uploads: [],
});
assert.equal(unrelated.applicable, false);

const uploadReceipt = mediaWebUploadSchema.parse({
  schemaVersion: "3",
  uploadId: "mwu_12345678",
  filename: "image.png",
  mimeType: "image/png",
  size: 7,
  sha256: "sha256:" + "a".repeat(64),
  status: "ready",
  createdAt: "2026-08-15T00:00:00.000Z",
  parsing: {
    status: "pending_manual",
    failureCode: "douyin_image_unsupported",
    nextAction: "请补充图片主体、关键信息和用途后重新校验。",
  },
});
assert.equal(uploadReceipt.parsing?.status, "pending_manual");

const uploadFunctionSource = apiSource.slice(apiSource.indexOf("export async function uploadMediaFile"));
const uploadBody = uploadFunctionSource.match(/body: JSON\.stringify\(\{[\s\S]*?\n    \}\)/)?.[0] ?? "";
assert.match(uploadBody, /schemaVersion:\s*['"]3['"]/);
assert.match(uploadBody, /filename:/);
assert.match(uploadBody, /contentBase64:/);
assert.match(uploadBody, /idempotencyKey:/);
assert.match(uploadBody, /mimeType:\s*file\.type/);
assert.match(apiSource, /mediaWebUploadSchema\.parse\(response\)/);

const serverFailure = materialParsingServerFailureMessage(
  "material_parsing_incomplete",
  "素材解析未完成。",
  {
    failurePrompt: "当前不支持自动解析抖音图片素材。",
    missingFields: ["uploadIds.mimeType", "remark"],
    nextAction: "请补充图片主体、关键信息和用途后重新校验。",
  },
);
assert.match(serverFailure, /当前不支持自动解析抖音图片素材/);
assert.match(serverFailure, /缺少：上传文件类型、补充说明/);
assert.doesNotMatch(serverFailure, /uploadIds|remark/);
assert.match(serverFailure, /请返回修改后重新校验/);

console.log("material parsing frontend contract passed");
