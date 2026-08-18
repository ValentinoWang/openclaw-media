// Generated from media_web_task.schema.json (sha256:06933aafb597cd6984be5c77f0098e631267d4be0e76624fb5e286a02ed8b466). Do not edit by hand.
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
export const mediaWebTaskSchema = z.object({
  schemaVersion: z.literal('media_web_task_v3'), taskId: z.string(), requestId: z.string(), modelCalls: z.array(modelCallSchema), capabilityId: z.string(), capabilityPath: z.array(z.string()).min(2).max(3),
  variantId: z.string(), params: capabilityParamsSchema, status: z.string(), terminal: z.boolean(), progress: z.number().int().min(0).max(100),
  summary: z.string(), createdAt: z.string(), updatedAt: z.string(), confirmationReceipt: confirmationReceiptSchema, confirmation: confirmationSchema, result: resultSchema.nullable(),
  error: z.record(z.string(), z.unknown()).nullable(), eventCursor: z.number().int(),
}).strict()

export const mediaWebTaskErrorSchema = z.object({
  ok: z.literal(false), error: z.object({ code: z.string(), reason: z.string(), action: z.string(), detail: z.string().optional() }).strict(),
}).strict()

export type CapabilityParams = z.infer<typeof capabilityParamsSchema>
export type MediaWebConfirmationReceipt = z.infer<typeof confirmationReceiptSchema>
export type MediaWebTaskCreateRequest = z.infer<typeof mediaWebTaskCreateRequestSchema>
export type MediaWebTask = z.infer<typeof mediaWebTaskSchema>
