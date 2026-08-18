import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveMatchedCapabilities } from '../../src/lib/capabilityMatchPresentation'
import { dashboardSchema } from '../../src/schemas/dashboardSchema'
import { capabilityMatchResponseSchema } from '../../src/schemas/capabilityMatchSchema'

const data = dashboardSchema.parse(JSON.parse(readFileSync(new URL('../../public/data/openclaw-bot-center.generated.json', import.meta.url), 'utf8')))
const capability = data.capabilities.find((item) => item.canonicalCapabilityId === 'source_asset_intake')
assert(capability, 'source_asset_intake must be published')

const step = {
  order: 1, capabilityId: 'source_asset_intake', variantId: 'default',
  extractedParams: { field_c675ffae69a2: '博主资料' }, confidence: 0.94,
  evidence: [{ fieldKey: 'field_c675ffae69a2', quote: '博主资料', source: 'query' as const }], issues: [],
}
const matched = capabilityMatchResponseSchema.parse({
  schemaVersion: '3', pathStatus: 'matched', needSummary: '保存博主资料', routeExplanation: '先登记来源事实。',
  guidancePlanId: 'capplan_abcdefghijklmnop', steps: [step], copyProjection: '【素材】\n链接或文字素材：博主资料',
})
assert.equal(matched.pathStatus, 'matched')
if (matched.pathStatus !== 'matched') throw new Error('matched fixture changed type')
const resolved = resolveMatchedCapabilities(matched, data.capabilities)
assert.equal(resolved?.[0]?.capability.id, capability.id)
assert.deepEqual(resolved?.[0]?.step.extractedParams, step.extractedParams)

assert.equal(capabilityMatchResponseSchema.safeParse({ ...matched, schemaVersion: '2' }).success, false)
assert.equal(capabilityMatchResponseSchema.safeParse({ ...matched, steps: [{ ...step, copyText: 'retired' }] }).success, false)
assert.equal(capabilityMatchResponseSchema.safeParse({ ...matched, steps: [{ ...step, capabilityId: undefined }] }).success, false)

assert.equal(capabilityMatchResponseSchema.safeParse({
  schemaVersion: '3', pathStatus: 'ambiguous', needSummary: '查询或录入博主', candidates: [
    { capabilityId: 'creator_profile_lookup', variantId: 'query', confidence: 0.61, reason: '可能只需查询。' },
    { capabilityId: 'creator_profile_upsert', variantId: 'url_candidate', confidence: 0.58, reason: '也可能需要入库。' },
  ],
}).success, true)

assert.equal(capabilityMatchResponseSchema.safeParse({
  schemaVersion: '3', pathStatus: 'needs_clarification', needSummary: '处理博主', clarificationQuestion: '你想查询还是入库？', candidates: [], knownParams: { platform: '小红书' },
}).success, true)
assert.equal(capabilityMatchResponseSchema.safeParse({
  schemaVersion: '2', pathStatus: 'unclear', needSummary: '旧格式', unclearReason: '旧格式', clarificationQuestion: '旧格式', clarificationCopyText: '旧格式',
}).success, false)

console.log('capability matcher frontend contract passed')
