// Generated from media_web_task.schema.json (sha256:47ec597735d9c0fd37ad2e0f420b357ffe7d959f505592243630330e0b8fd9f5). Do not edit by hand.
import { z } from 'zod'

const taskValueSchema = z.union([z.string(), z.number(), z.boolean(), z.array(z.union([z.string(), z.number()])), z.null()])
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
