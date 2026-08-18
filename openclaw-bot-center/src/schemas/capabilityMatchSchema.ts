// Generated from capability_match.schema.json (sha256:6d1acb2c0432683c736dfbd87331c547681175e6ceac4d8ebf12620629b58f53). Do not edit by hand.
import { z } from 'zod'

const scalarValueSchema = z.union([z.string(), z.number(), z.boolean(), z.array(z.union([z.string(), z.number()])), z.null()])
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
