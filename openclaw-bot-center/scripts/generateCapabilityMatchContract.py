from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


# 仓库整合后契约随仓库走；旧的维护机绝对路径仅作最后回退。
_REPO_CONTRACTS = Path(__file__).resolve().parents[2] / "openclaw-tag-router/openclaw_app/contracts"
_LEGACY_CONTRACTS = Path("/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app/contracts")
CONTRACT_ROOT = Path(os.environ.get(
    "OPENCLAW_CONTRACT_ROOT",
    str(_REPO_CONTRACTS if _REPO_CONTRACTS.exists() else _LEGACY_CONTRACTS),
))
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "src/schemas"


def _load(name: str) -> tuple[dict[str, object], str]:
    raw = (CONTRACT_ROOT / name).read_bytes()
    schema = json.loads(raw)
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError(f"{name} is not a canonical draft 2020-12 schema")
    return schema, hashlib.sha256(raw).hexdigest()


def _header(name: str, digest: str) -> str:
    return f"// Generated from {name} (sha256:{digest}). Do not edit by hand.\nimport {{ z }} from 'zod'\n\n"


def _catalog(digest: str) -> str:
    return _header("capability_catalog.schema.json", digest) + r'''const optionSchema = z.object({ value: z.string(), label: z.string(), aliases: z.array(z.string()), source: z.string().min(1) }).strict()
const conditionSchema = z.object({ source: z.string().min(1), operator: z.enum(['equals', 'not_equals', 'in', 'exists']), value: z.unknown() }).strict()
const formatSchema = z.object({
  name: z.enum(['', 'uri', 'date']), min: z.number().nullable(), max: z.number().nullable(), pattern: z.string(),
  urlSchemes: z.array(z.enum(['http', 'https'])),
}).strict()

export const capabilityFieldSchema = z.object({
  key: z.string().regex(/^[a-z][a-z0-9_]*$/), sourceLabel: z.string().min(1), label: z.string().min(1),
  inputType: z.enum(['text', 'textarea', 'select', 'radio', 'multiselect', 'number', 'date', 'url', 'file', 'object']),
  valueType: z.enum(['string', 'number', 'boolean', 'array', 'object']), format: formatSchema, required: z.boolean(), defaultValue: z.unknown(),
  options: z.array(optionSchema), placeholder: z.string(), helpText: z.string(), order: z.number().int().nonnegative(),
  visibleWhen: z.array(conditionSchema), enabledWhen: z.array(conditionSchema), semanticOwner: z.string().min(1), persistenceOwner: z.string().min(1),
  provenance: z.literal('declared_field_definition'),
}).strict()

export const capabilityVariantSchema = z.object({
  variantId: z.string().min(1), label: z.string().min(1), requiredFields: z.array(z.string()),
  requiredAnyOf: z.array(z.array(z.string()).min(2)), preActions: z.array(z.string()),
  controlledInputFields: z.array(z.string()), forbiddenFields: z.array(z.string()),
  fieldValues: z.record(z.string(), z.array(z.string())),
}).strict()

const hierarchySchema = z.object({
  categoryId: z.string(), categoryName: z.string(), categoryOrder: z.number().int().nonnegative(),
  objectId: z.string(), objectName: z.string(), objectOrder: z.number().int().nonnegative(),
  actionId: z.string(), actionName: z.string(), actionOrder: z.number().int().nonnegative(),
  pathIds: z.array(z.string()).min(2).max(3), pathNames: z.array(z.string()).min(2).max(3),
}).strict()

export const capabilityDefinitionSchema = z.object({
  capabilityId: z.string().regex(/^[a-z][a-z0-9_]*$/), internalCode: z.string(), internalLabel: z.string(), label: z.string(), displayName: z.string(), description: z.string(), example: z.string(), aliases: z.array(z.string()),
  bots: z.array(z.enum(['Media bot', 'Daily bot', 'Knowledge bot', 'Social bot', '任意 Bot'])).min(1),
  hierarchy: hierarchySchema, fields: z.array(capabilityFieldSchema), variants: z.array(capabilityVariantSchema).min(1),
  validationRules: z.array(z.object({ type: z.literal('at_least_one'), fields: z.array(z.string()).min(2), message: z.string().min(1) }).strict()),
  supportedAttachments: z.array(z.enum(['text', 'url', 'image', 'video', 'audio', 'document'])),
  attachmentPolicy: z.object({ types: z.array(z.enum(['text', 'url', 'image', 'video', 'audio', 'document'])), maxCount: z.number().int().min(0).max(8), maxBytes: z.number().int().min(0).max(52428800) }).strict(),
  status: z.enum(['implemented', 'external', 'not_implemented']), enabled: z.boolean(), visibility: z.enum(['public', 'ops', 'maintainer']),
  riskLevel: z.enum(['low', 'medium', 'high', 'destructive']), effect: z.enum(['read', 'write', 'destructive']),
  confirmationPolicy: z.object({ stage: z.enum(['none', 'before_execute', 'after_candidate', 'destructive_preview_apply']), message: z.string() }).strict(),
  handler: z.string(), consumes: z.array(z.string()), produces: z.array(z.string()), writesTo: z.array(z.string()), sourceSystem: z.string(),
  ssotRefs: z.array(z.string()), inputContractSource: z.string(), searchKeywords: z.array(z.string()), provenance: z.string().min(1),
  displayOrder: z.number().int().nonnegative(), requiresConfirmation: z.boolean(),
}).strict()

export const capabilityCatalogSchema = z.object({
  schemaVersion: z.literal('capability_catalog_v3'), catalogVersion: z.string().regex(/^sha256:[a-f0-9]{64}$/), capabilities: z.array(capabilityDefinitionSchema),
}).strict()

export type CapabilityCatalog = z.infer<typeof capabilityCatalogSchema>
export type CapabilityDefinition = z.infer<typeof capabilityDefinitionSchema>
export type CapabilityField = z.infer<typeof capabilityFieldSchema>
export type CapabilityVariant = z.infer<typeof capabilityVariantSchema>
'''


def _match(digest: str) -> str:
    return _header("capability_match.schema.json", digest) + r'''const scalarValueSchema = z.union([z.string(), z.number(), z.boolean(), z.array(z.union([z.string(), z.number()])), z.null()])
const paramsSchema = z.record(z.string(), scalarValueSchema)

const issueSchema = z.object({ code: z.string(), fieldKey: z.string().optional(), ruleType: z.string(), message: z.string() }).strict()
const evidenceSchema = z.object({ fieldKey: z.string().optional(), quote: z.string().min(1).max(500), source: z.enum(['query', 'bound_result']) }).strict()
const dependencySchema = z.object({ stepOrder: z.number().int().min(1).max(5), requiredOutputs: z.array(z.string()).min(1) }).strict()

export const capabilityMatchStepSchema = z.object({
  order: z.number().int().min(1).max(5), capabilityId: z.string(), variantId: z.string(), extractedParams: paramsSchema,
  confidence: z.number().min(0).max(1), evidence: z.array(evidenceSchema), issues: z.array(issueSchema), dependsOn: dependencySchema.optional(),
}).strict()

export const capabilityMatchCandidateSchema = z.object({
  capabilityId: z.string(), variantId: z.string(), confidence: z.number().min(0).max(1), reason: z.string(),
}).strict()

export const capabilityMatchRequestSchema = z.object({
  query: z.string().min(1).max(4000), currentBot: z.enum(['media', 'daily', 'knowledge', 'social']).optional(),
  catalogVersion: z.string().regex(/^sha256:[a-f0-9]{64}$/).optional(),
}).strict()

export const capabilityMatchResponseSchema = z.discriminatedUnion('pathStatus', [
  z.object({ schemaVersion: z.literal('3'), pathStatus: z.literal('matched'), needSummary: z.string(), routeExplanation: z.string(),
    guidancePlanId: z.string().regex(/^capplan_[A-Za-z0-9_-]{16,128}$/), steps: z.array(capabilityMatchStepSchema).min(1).max(5), copyProjection: z.string() }).strict(),
  z.object({ schemaVersion: z.literal('3'), pathStatus: z.literal('ambiguous'), needSummary: z.string(), candidates: z.array(capabilityMatchCandidateSchema).min(2).max(5) }).strict(),
  z.object({ schemaVersion: z.literal('3'), pathStatus: z.literal('needs_clarification'), needSummary: z.string(), clarificationQuestion: z.string(),
    candidates: z.array(capabilityMatchCandidateSchema).max(5), knownParams: paramsSchema }).strict(),
])

export const capabilityMatchErrorSchema = z.object({
  ok: z.literal(false), error: z.object({ code: z.enum(['invalid_request', 'provider_unavailable', 'invalid_model_response', 'authentication_required', 'auth_failed', 'auth_unavailable', 'matcher_unavailable', 'internal_error']), message: z.string(), action: z.string(), detail: z.string().optional() }).strict(),
}).strict()

export type CapabilityMatchResponse = z.infer<typeof capabilityMatchResponseSchema>
export type CapabilityMatchStep = z.infer<typeof capabilityMatchStepSchema>
export type CapabilityMatchCandidate = z.infer<typeof capabilityMatchCandidateSchema>
'''


def _task(digest: str) -> str:
    return _header("media_web_task.schema.json", digest) + r'''const taskValueSchema = z.union([z.string(), z.number(), z.boolean(), z.array(z.union([z.string(), z.number()])), z.null()])
export const capabilityParamsSchema = z.record(z.string(), taskValueSchema)

const receiptIdSchema = z.string().regex(/^[A-Za-z0-9_-]{8,160}$/)
const receiptDigestSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/)
const receiptExpirySchema = z.string().datetime()
const creatorProfileCandidateReceiptSchema = z.object({
  kind: z.literal('creator_profile_candidate'), previewTaskId: receiptIdSchema, runId: receiptIdSchema,
  candidateDigest: receiptDigestSchema, expiresAt: receiptExpirySchema,
}).strict()
const historicalCreatorProfileCandidateReceiptSchema = z.object({
  kind: z.literal('creator_profile_candidate'), runId: receiptIdSchema,
}).strict()
const trackCreatorMembershipPreviewReceiptSchema = z.object({
  kind: z.literal('track_creator_membership_preview'), previewTaskId: receiptIdSchema,
  fieldsDigest: receiptDigestSchema, expiresAt: receiptExpirySchema,
}).strict()
const deletionPreviewReceiptSchema = z.object({
  kind: z.literal('deletion_preview'), previewTaskId: receiptIdSchema,
  targetIds: z.array(receiptIdSchema).min(1).refine((values) => new Set(values).size === values.length),
  targetCount: z.number().int().positive(), entityCount: z.number().int().nonnegative(),
  planDigest: receiptDigestSchema, expiresAt: receiptExpirySchema,
}).strict()
export const confirmationReceiptSchema = z.discriminatedUnion('kind', [
  creatorProfileCandidateReceiptSchema, trackCreatorMembershipPreviewReceiptSchema, deletionPreviewReceiptSchema,
]).nullable()

export const mediaWebTaskCreateRequestSchema = z.object({
  schemaVersion: z.literal('3'), capabilityId: z.string().regex(/^[a-z][a-z0-9_]*$/), variantId: z.string().min(1),
  params: capabilityParamsSchema, uploadIds: z.array(z.string().regex(/^[A-Za-z0-9_-]{8,160}$/)).max(8),
  idempotencyKey: z.string().regex(/^[A-Za-z0-9_-]{8,128}$/), catalogVersion: z.string().regex(/^sha256:[a-f0-9]{64}$/), initiation: z.enum(['manual', 'ai']),
  confirmationReceipt: confirmationReceiptSchema,
}).strict()

const confirmationSchema = z.object({ state: z.enum(['not_required', 'required', 'approved', 'rejected']), required: z.boolean(), note: z.string(), decidedAt: z.string() }).strict()
const resultReceiptSchema = z.union([
  creatorProfileCandidateReceiptSchema,
  historicalCreatorProfileCandidateReceiptSchema,
  z.object({ kind: z.literal('creator_profile_written'), recordId: receiptIdSchema }).strict(),
  trackCreatorMembershipPreviewReceiptSchema,
  deletionPreviewReceiptSchema,
])
const resultSchema = z.object({
  ok: z.boolean(), status: z.enum(['completed', 'needs_attention', 'failed']), reply: z.string(),
  links: z.array(z.object({ label: z.string(), url: z.string().url() }).strict()),
  receipt: resultReceiptSchema.nullable(),
}).strict()
const modelCallSchema = z.object({
  requestId: z.string(), usageId: z.string().nullable(), status: z.enum(['pending', 'succeeded', 'failed', 'unknown_reconcile']), updatedAt: z.number().int(),
}).strict()
const taskErrorSchema = z.object({
  code: z.string(), message: z.string(), action: z.string(),
}).catchall(z.unknown())
const accountBindingSchema = z.object({
  userPublicId: z.string(), ownedAccountPublicId: z.string(), relationshipRef: z.string(), platform: z.string(), normalizedAccount: z.string(),
}).strict()
const attemptSchema = z.object({
  attemptId: z.string(), runnerId: z.string(), executorId: z.string(), status: z.string(),
  attemptNumber: z.number().int().min(1), recoveryOfAttemptId: z.string().nullable(),
  startedAt: z.string().nullable().optional(), heartbeatAt: z.string().nullable().optional(), finishedAt: z.string().nullable().optional(),
}).strict()
const readbackSchema = z.object({
  status: z.string(), required: z.boolean(), applicability: z.record(z.string(), z.unknown()), checkedAt: z.string().nullable(),
}).strict()
const readbacksSchema = z.object({ database: readbackSchema, external: readbackSchema, web: readbackSchema }).strict()
const settlementReceiptSchema = z.object({
  receiptId: z.string(), schemaVersion: z.literal('media_e2e_receipt_v1'), digest: receiptDigestSchema, status: z.string(), createdAt: z.string(),
}).strict()
export const mediaWebTaskSchema = z.object({
  schemaVersion: z.literal('media_web_task_v3'), taskId: z.string(), requestId: z.string(), modelCalls: z.array(modelCallSchema), capabilityId: z.string(), capabilityPath: z.array(z.string()).min(2).max(3),
  variantId: z.string(), params: capabilityParamsSchema, status: z.string(), settlementStage: z.string(), terminal: z.boolean(), progress: z.number().int().min(0).max(100),
  summary: z.string(), createdAt: z.string(), updatedAt: z.string(), confirmationReceipt: confirmationReceiptSchema, confirmation: confirmationSchema, result: resultSchema.nullable(),
  error: taskErrorSchema.nullable(), eventCursor: z.number().int(),
  accountBinding: accountBindingSchema.nullable().optional(), attempt: attemptSchema.nullable().optional(),
  readbacks: readbacksSchema.nullable().optional(), missingReadbacks: z.array(z.enum(['database', 'external', 'web'])).optional(),
  receipt: settlementReceiptSchema.nullable().optional(),
}).strict()

export const mediaWebUploadSchema = z.object({
  schemaVersion: z.literal('3'), uploadId: z.string().regex(/^[A-Za-z0-9_-]{8,160}$/), filename: z.string(), mimeType: z.string(),
  size: z.number().int().nonnegative(), sha256: receiptDigestSchema, status: z.string(), createdAt: z.string(),
  parsing: z.object({ status: z.string(), failureCode: z.string(), nextAction: z.string() }).strict().optional(),
}).strict()

export const mediaWebTaskErrorSchema = z.object({
  ok: z.literal(false), error: z.object({ code: z.string(), reason: z.string(), action: z.string(), detail: z.string().optional() }).strict(),
}).strict()

export type CapabilityParams = z.infer<typeof capabilityParamsSchema>
export type MediaWebConfirmationReceipt = z.infer<typeof confirmationReceiptSchema>
export type MediaWebTaskCreateRequest = z.infer<typeof mediaWebTaskCreateRequestSchema>
export type MediaWebTask = z.infer<typeof mediaWebTaskSchema>
export type MediaWebUpload = z.infer<typeof mediaWebUploadSchema>
'''


def generate_all() -> dict[Path, str]:
    _, catalog_digest = _load("capability_catalog.schema.json")
    _, match_digest = _load("capability_match.schema.json")
    _, task_digest = _load("media_web_task.schema.json")
    return {
        OUTPUT_ROOT / "capabilityCatalogSchema.ts": _catalog(catalog_digest),
        OUTPUT_ROOT / "capabilityMatchSchema.ts": _match(match_digest),
        OUTPUT_ROOT / "mediaWebTaskSchema.ts": _task(task_digest),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate frontend Zod contracts from canonical OpenClaw JSON Schemas.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for path, rendered in generate_all().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == rendered:
            continue
        if args.check:
            stale.append(path.name)
        else:
            path.write_text(rendered, encoding="utf-8")
            print(f"Wrote {path}")
    if stale:
        raise SystemExit("generated frontend contracts are stale: " + ", ".join(stale))
    print("frontend contracts are generated and current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
