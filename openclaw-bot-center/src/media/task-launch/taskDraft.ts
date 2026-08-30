import type {
  CapabilityCatalog,
  CapabilityDefinition,
} from "../../schemas/capabilityCatalogSchema";
import type { CapabilityMatchResponse } from "../../schemas/capabilityMatchSchema";
import type {
  CapabilityParams,
  MediaWebConfirmationReceipt,
  MediaWebTaskCreateRequest,
} from "../../schemas/mediaWebTaskSchema";
import {
  confirmationReceiptProblem,
  confirmationReceiptProblemMessage,
} from "../confirmationReceiptExpiry";
import { materialParsingIssues } from "./materialParsing";
import { newTaskIdempotencyKey } from "../idempotency";

export { newTaskIdempotencyKey };

export type DraftPhase =
  | "idle"
  | "editing"
  | "decomposing"
  | "review"
  | "submitting"
  | "submitted"
  | "error";
export type FieldProvenance = "user" | "ai" | "user-edited" | "prefill";
export type DraftIssue = {
  code: string;
  fieldKey?: string;
  ruleType: string;
  message: string;
};

export type TaskDraft = {
  phase: DraftPhase;
  capabilityId: string;
  variantId: string;
  params: CapabilityParams;
  uploads: File[];
  provenance: Record<string, FieldProvenance>;
  issues: DraftIssue[];
  initiation: "manual" | "ai";
  catalogVersion: string;
  query: string;
  matchResult: CapabilityMatchResponse | null;
  activeRequestId: string;
  idempotencyKey: string;
  submittedTaskId: string;
  confirmationReceipt: MediaWebConfirmationReceipt;
  error: string;
};

export type StructuredPrefill = {
  capabilityId: string;
  variantId?: string;
  params?: CapabilityParams;
  confirmationReceipt?: MediaWebConfirmationReceipt;
};

export type TaskDraftAction =
  | { type: "catalogLoaded"; catalog: CapabilityCatalog }
  | {
      type: "selectCapability";
      capability: CapabilityDefinition;
      variantId?: string;
    }
  | { type: "updateField"; key: string; value: CapabilityParams[string] }
  | { type: "setUploads"; files: File[] }
  | { type: "setQuery"; query: string }
  | { type: "decomposeStart"; requestId: string }
  | {
      type: "decomposeSuccess";
      requestId: string;
      response: CapabilityMatchResponse;
      catalog: CapabilityCatalog;
    }
  | { type: "decomposeFailure"; requestId: string; message: string }
  | {
      type: "chooseCandidate";
      capability: CapabilityDefinition;
      variantId: string;
    }
  | { type: "prefill"; prefill: StructuredPrefill; catalog: CapabilityCatalog }
  | {
      type: "prefillReview";
      prefill: StructuredPrefill;
      catalog: CapabilityCatalog;
    }
  | { type: "review"; catalog: CapabilityCatalog }
  | { type: "edit" }
  | { type: "submitStart" }
  | { type: "replaceIdempotencyKey"; idempotencyKey: string }
  | { type: "submitFailure"; message: string }
  | { type: "submitted"; taskId: string }
  | { type: "clear"; catalogVersion: string };

export function emptyTaskDraft(catalogVersion = ""): TaskDraft {
  return {
    phase: "idle",
    capabilityId: "",
    variantId: "",
    params: {},
    uploads: [],
    provenance: {},
    issues: [],
    initiation: "manual",
    catalogVersion,
    query: "",
    matchResult: null,
    activeRequestId: "",
    idempotencyKey: newTaskIdempotencyKey(),
    submittedTaskId: "",
    confirmationReceipt: null,
    error: "",
  };
}

export function taskDraftReducer(
  state: TaskDraft,
  action: TaskDraftAction,
): TaskDraft {
  switch (action.type) {
    case "catalogLoaded": {
      if (state.catalogVersion === action.catalog.catalogVersion) return state;
      const selected = action.catalog.capabilities.find(
        (item) => item.capabilityId === state.capabilityId && item.enabled,
      );
      if (!selected) return emptyTaskDraft(action.catalog.catalogVersion);
      return revalidate(
        refreshRequestIdentity(state, {
          catalogVersion: action.catalog.catalogVersion,
          phase: "editing",
        }),
        selected,
      );
    }
    case "selectCapability": {
      const variantId =
        action.variantId ?? action.capability.variants[0]?.variantId ?? "";
      const selectionError = capabilitySelectionError(
        action.capability,
        variantId,
      );
      if (selectionError) return invalidDraft(state, selectionError);
      const compatible = Object.fromEntries(
        action.capability.fields
          .filter(
            (field) =>
              field.key in state.params &&
              valueMatches(field.valueType, state.params[field.key]),
          )
          .map((field) => [field.key, state.params[field.key]]),
      );
      const provenance = Object.fromEntries(
        Object.keys(compatible).map((key) => [
          key,
          state.provenance[key] ?? "user",
        ]),
      );
      return revalidate(
        refreshRequestIdentity(state, {
          phase: "editing",
          capabilityId: action.capability.capabilityId,
          variantId,
          params: compatible,
          provenance,
          initiation: "manual",
          matchResult: null,
          confirmationReceipt: null,
          error: "",
        }),
        action.capability,
      );
    }
    case "updateField": {
      const source = state.provenance[action.key];
      return refreshRequestIdentity(state, {
        phase: "editing",
        params: { ...state.params, [action.key]: action.value },
        provenance: {
          ...state.provenance,
          [action.key]: source === "ai" ? "user-edited" : "user",
        },
        error: "",
      });
    }
    case "setUploads":
      return refreshRequestIdentity(state, {
        phase: "editing",
        uploads: action.files,
      });
    case "setQuery":
      return {
        ...state,
        query: action.query,
        matchResult: null,
        error: "",
        phase: state.capabilityId ? "editing" : "idle",
      };
    case "decomposeStart":
      return {
        ...state,
        phase: "decomposing",
        activeRequestId: action.requestId,
        error: "",
      };
    case "decomposeSuccess": {
      if (action.requestId !== state.activeRequestId) return state;
      if (action.response.pathStatus !== "matched")
        return refreshRequestIdentity(state, {
          phase: "editing",
          matchResult: action.response,
          activeRequestId: "",
          initiation: "ai",
        });
      const first = [...action.response.steps].sort(
        (a, b) => a.order - b.order,
      )[0];
      const capability = action.catalog.capabilities.find(
        (item) => item.capabilityId === first.capabilityId,
      );
      if (!capability || !capability.enabled)
        return {
          ...state,
          phase: "error",
          error: "AI 返回的能力不在当前可用目录中。",
          activeRequestId: "",
        };
      const selectionError = capabilitySelectionError(
        capability,
        first.variantId,
      );
      if (selectionError)
        return {
          ...state,
          phase: "error",
          error: selectionError,
          activeRequestId: "",
        };
      const params = compatibleParams(capability, first.extractedParams);
      const provenance = Object.fromEntries(
        Object.keys(params).map((key) => [key, "ai" as const]),
      );
      return revalidate(
        refreshRequestIdentity(state, {
          phase: "editing",
          capabilityId: first.capabilityId,
          variantId: first.variantId,
          params,
          provenance,
          initiation: "ai",
          matchResult: action.response,
          activeRequestId: "",
          confirmationReceipt: null,
          error: "",
        }),
        capability,
      );
    }
    case "decomposeFailure":
      return action.requestId === state.activeRequestId
        ? {
            ...state,
            phase: "error",
            activeRequestId: "",
            error: action.message,
          }
        : state;
    case "chooseCandidate": {
      const selectionError = capabilitySelectionError(
        action.capability,
        action.variantId,
      );
      if (selectionError) return invalidDraft(state, selectionError);
      return revalidate(
        refreshRequestIdentity(state, {
          capabilityId: action.capability.capabilityId,
          variantId: action.variantId,
          params: {},
          provenance: {},
          initiation: "ai",
          phase: "editing",
          confirmationReceipt: null,
          error: "",
        }),
        action.capability,
      );
    }
    case "prefill": {
      const resolved = resolvePrefill(action.catalog, action.prefill);
      if (!resolved.ok)
        return invalidDraft(
          state,
          resolved.error,
          action.catalog.catalogVersion,
        );
      const { capability, variantId } = resolved;
      const params = compatibleParams(capability, action.prefill.params);
      return revalidate(
        refreshRequestIdentity(state, {
          capabilityId: capability.capabilityId,
          variantId,
          params,
          provenance: Object.fromEntries(
            Object.keys(params).map((key) => [key, "prefill" as const]),
          ),
          initiation: "manual",
          phase: "editing",
          confirmationReceipt: action.prefill.confirmationReceipt ?? null,
          error: "",
        }),
        capability,
      );
    }
    case "prefillReview": {
      const resolved = resolvePrefill(action.catalog, action.prefill);
      if (!resolved.ok)
        return invalidDraft(
          state,
          resolved.error,
          action.catalog.catalogVersion,
        );
      const { capability, variantId } = resolved;
      const params = compatibleParams(capability, action.prefill.params);
      const validated = revalidate(
        refreshRequestIdentity(state, {
          capabilityId: capability.capabilityId,
          variantId,
          params,
          provenance: Object.fromEntries(
            Object.keys(params).map((key) => [key, "prefill" as const]),
          ),
          initiation: "manual",
          phase: "editing",
          confirmationReceipt: action.prefill.confirmationReceipt ?? null,
          error: "",
        }),
        capability,
      );
      return validated.issues.length
        ? validated
        : { ...validated, phase: "review" };
    }
    case "review": {
      const capability = action.catalog.capabilities.find(
        (item) => item.capabilityId === state.capabilityId && item.enabled,
      );
      if (!capability)
        return { ...state, phase: "error", error: "请选择能力。" };
      const validated = revalidate(state, capability);
      return validated.issues.length
        ? validated
        : { ...validated, phase: "review" };
    }
    case "edit":
      return { ...state, phase: "editing", error: "" };
    case "submitStart":
      return { ...state, phase: "submitting", error: "" };
    case "replaceIdempotencyKey":
      return { ...state, idempotencyKey: action.idempotencyKey };
    case "submitFailure":
      return { ...state, phase: "review", error: action.message };
    case "submitted":
      return { ...state, phase: "submitted", submittedTaskId: action.taskId };
    case "clear":
      return emptyTaskDraft(action.catalogVersion);
  }
}

export function validateDraft(
  draft: TaskDraft,
  capability: CapabilityDefinition,
): DraftIssue[] {
  const variant = capability.variants.find(
    (item) => item.variantId === draft.variantId,
  );
  if (!variant)
    return [
      {
        code: "variant_not_found",
        ruleType: "variant",
        message: "请选择具体操作。",
      },
    ];
  const fields = new Map(capability.fields.map((item) => [item.key, item]));
  const issues: DraftIssue[] = [];
  const receiptProblem = confirmationReceiptProblem(
    draft.capabilityId,
    draft.variantId,
    draft.confirmationReceipt,
  );
  if (receiptProblem) {
    issues.push({
      code: `confirmation_receipt_${receiptProblem}`,
      ruleType: "confirmation_receipt",
      message: confirmationReceiptProblemMessage(receiptProblem),
    });
  }
  const visibleFields = capability.fields.filter(
    (field) => fieldConditionState(field, draft).visible,
  );
  const visibleKeys = new Set(visibleFields.map((field) => field.key));
  for (const key of new Set([
    ...visibleFields.filter((item) => item.required).map((item) => item.key),
    ...variant.requiredFields.filter((key) => visibleKeys.has(key)),
  ])) {
    if (isEmpty(draft.params[key]))
      issues.push({
        code: "required",
        fieldKey: key,
        ruleType: "required",
        message: `${fields.get(key)?.label ?? key}为必填项。`,
      });
  }
  for (const group of variant.requiredAnyOf) {
    const visibleGroup = group.filter((key) => visibleKeys.has(key));
    if (
      visibleGroup.length &&
      !visibleGroup.some((key) => !isEmpty(draft.params[key]))
    )
      issues.push({
        code: "at_least_one",
        fieldKey: visibleGroup[0],
        ruleType: "at_least_one",
        message: `${visibleGroup.map((key) => fields.get(key)?.label ?? key).join("或")}至少填写一项。`,
      });
  }
  for (const field of capability.fields) {
    const value = draft.params[field.key];
    if (isEmpty(value)) continue;
    const state = fieldConditionState(field, draft);
    if (!state.visible) {
      issues.push({
        code: "field_not_visible",
        fieldKey: field.key,
        ruleType: "condition",
        message: `${field.label}不适用于当前操作。`,
      });
      continue;
    }
    if (!state.enabled) {
      issues.push({
        code: "field_disabled",
        fieldKey: field.key,
        ruleType: "condition",
        message: `${field.label}当前不可填写。`,
      });
      continue;
    }
    if (!valueMatches(field.valueType, value))
      issues.push({
        code: "invalid_type",
        fieldKey: field.key,
        ruleType: "type",
        message: `${field.label}格式不正确。`,
      });
    if (field.format.name === "uri" && typeof value === "string") {
      try {
        const url = new URL(value);
        if (
          !field.format.urlSchemes
            .map((item) => `${item}:`)
            .includes(url.protocol)
        )
          throw new Error();
      } catch {
        issues.push({
          code: "invalid_format",
          fieldKey: field.key,
          ruleType: "url",
          message: `${field.label}必须是有效链接。`,
        });
      }
    }
    const comparable =
      typeof value === "number"
        ? value
        : typeof value === "string" || Array.isArray(value)
          ? value.length
          : null;
    if (
      comparable !== null &&
      field.format.min !== null &&
      comparable < field.format.min
    )
      issues.push({
        code: "below_minimum",
        fieldKey: field.key,
        ruleType: "format",
        message: `${field.label}低于最小值。`,
      });
    if (
      comparable !== null &&
      field.format.max !== null &&
      comparable > field.format.max
    )
      issues.push({
        code: "above_maximum",
        fieldKey: field.key,
        ruleType: "format",
        message: `${field.label}超过最大值。`,
      });
    if (
      field.format.pattern &&
      typeof value === "string" &&
      !new RegExp(`^(?:${field.format.pattern})$`).test(value)
    )
      issues.push({
        code: "pattern_mismatch",
        fieldKey: field.key,
        ruleType: "format",
        message: `${field.label}格式不正确。`,
      });
    const allowed = variant.fieldValues[field.key]?.length
      ? variant.fieldValues[field.key]
      : field.options.map((item) => item.value);
    const values = Array.isArray(value) ? value : [value];
    if (
      allowed.length &&
      values.some((item) => !allowed.includes(String(item)))
    )
      issues.push({
        code: "invalid_option",
        fieldKey: field.key,
        ruleType: "option",
        message: `${field.label}包含未定义选项。`,
      });
  }
  for (const key of variant.forbiddenFields)
    if (!isEmpty(draft.params[key]))
      issues.push({
        code: "forbidden",
        fieldKey: key,
        ruleType: "forbidden",
        message: `${fields.get(key)?.label ?? key}不适用于当前操作。`,
      });
  if (draft.uploads.length > capability.attachmentPolicy.maxCount)
    issues.push({
      code: "too_many_uploads",
      ruleType: "upload",
      message: `最多上传 ${capability.attachmentPolicy.maxCount} 个文件。`,
    });
  for (const file of draft.uploads) {
    if (file.size > capability.attachmentPolicy.maxBytes)
      issues.push({
        code: "upload_too_large",
        ruleType: "upload",
        message: `${file.name}超过单文件大小限制。`,
      });
    const kind = uploadKind(file);
    if (!capability.attachmentPolicy.types.includes(kind))
      issues.push({
        code: "invalid_upload_type",
        ruleType: "upload",
        message: `${file.name}的文件类型不适用于当前能力。`,
      });
  }
  issues.push(
    ...materialParsingIssues({
      capabilityId: draft.capabilityId,
      params: draft.params,
      uploads: draft.uploads,
    }),
  );
  return issues;
}

export function fieldConditionState(
  field: CapabilityDefinition["fields"][number],
  draft: Pick<TaskDraft, "variantId" | "params">,
) {
  const matches = (
    condition: CapabilityDefinition["fields"][number]["visibleWhen"][number],
  ) => {
    const actual =
      condition.source === "variant"
        ? draft.variantId
        : draft.params[condition.source];
    if (condition.operator === "equals") return actual === condition.value;
    if (condition.operator === "not_equals") return actual !== condition.value;
    if (condition.operator === "in")
      return Array.isArray(condition.value) && condition.value.includes(actual);
    return !isEmpty(actual) === Boolean(condition.value);
  };
  return {
    visible: !field.visibleWhen.length || field.visibleWhen.every(matches),
    enabled: !field.enabledWhen.length || field.enabledWhen.every(matches),
  };
}

export function buildTaskRequest(
  draft: TaskDraft,
  uploadIds: string[],
): MediaWebTaskCreateRequest {
  return {
    schemaVersion: "3",
    capabilityId: draft.capabilityId,
    variantId: draft.variantId,
    params: draft.params,
    uploadIds,
    idempotencyKey: draft.idempotencyKey,
    catalogVersion: draft.catalogVersion,
    initiation: draft.initiation,
    confirmationReceipt: draft.confirmationReceipt,
  };
}

function revalidate(
  state: TaskDraft,
  capability: CapabilityDefinition,
): TaskDraft {
  return { ...state, issues: validateDraft(state, capability) };
}

type PrefillResolution =
  | { ok: false; error: string }
  | { ok: true; capability: CapabilityDefinition; variantId: string };

function resolvePrefill(
  catalog: CapabilityCatalog,
  prefill: StructuredPrefill,
): PrefillResolution {
  const capability = catalog.capabilities.find(
    (item) => item.capabilityId === prefill.capabilityId,
  );
  if (!capability)
    return {
      ok: false,
      error: `能力“${prefill.capabilityId}”不在当前目录中。`,
    };
  const variantId =
    prefill.variantId ?? capability.variants[0]?.variantId ?? "";
  const error = capabilitySelectionError(capability, variantId);
  return error ? { ok: false, error } : { ok: true, capability, variantId };
}

function capabilitySelectionError(
  capability: CapabilityDefinition,
  variantId: string,
): string {
  if (!capability.enabled) return `能力“${capability.displayName}”当前不可用。`;
  if (!capability.variants.some((variant) => variant.variantId === variantId)) {
    return `操作“${variantId || "未指定"}”不属于能力“${capability.displayName}”。`;
  }
  return "";
}

function compatibleParams(
  capability: CapabilityDefinition,
  params: CapabilityParams | undefined,
): CapabilityParams {
  if (!params) return {};
  return Object.fromEntries(
    capability.fields
      .filter(
        (field) =>
          field.key in params &&
          valueMatches(field.valueType, params[field.key]),
      )
      .map((field) => [field.key, params[field.key]]),
  );
}

function invalidDraft(
  state: TaskDraft,
  error: string,
  catalogVersion = state.catalogVersion,
): TaskDraft {
  return { ...emptyTaskDraft(catalogVersion), phase: "error", error };
}

function isEmpty(value: unknown) {
  return (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}
function valueMatches(type: string, value: unknown) {
  if (isEmpty(value)) return true;
  if (type === "string") return typeof value === "string";
  if (type === "number")
    return typeof value === "number" && Number.isFinite(value);
  if (type === "boolean") return typeof value === "boolean";
  if (type === "array") return Array.isArray(value);
  return typeof value === "object" && !Array.isArray(value);
}

function uploadKind(
  file: File,
): "text" | "image" | "video" | "audio" | "document" {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  if (file.type === "application/pdf") return "document";
  return "text";
}

function refreshRequestIdentity(
  state: TaskDraft,
  changes: Partial<TaskDraft>,
): TaskDraft {
  return {
    ...state,
    ...changes,
    idempotencyKey: newTaskIdempotencyKey(),
    submittedTaskId: "",
  };
}

