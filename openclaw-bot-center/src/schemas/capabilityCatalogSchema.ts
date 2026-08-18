// Generated from capability_catalog.schema.json (sha256:9ee2f203e991876aa450f77d719a16a7d925de9750180333a0d74cbc1030b0aa). Do not edit by hand.
import { z } from 'zod'

const optionSchema = z.object({ value: z.string(), label: z.string(), aliases: z.array(z.string()), source: z.string().min(1) }).strict()
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
