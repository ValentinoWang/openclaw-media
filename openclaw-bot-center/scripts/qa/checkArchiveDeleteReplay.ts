import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const apiSource = readFileSync('src/media/mediaWebApi.ts', 'utf8')
const pageSource = readFileSync('src/media/pages/ordinary/ArchivesPage.tsx', 'utf8')
const keyPattern = /^archive-(?:plan|delete|readback|confirmation)-[0-9a-f]{64}$/

function apiFunction(source: string, name: string, next: string): string {
  const start = source.indexOf(`export async function ${name}`)
  const end = source.indexOf(next, start)
  assert.ok(start >= 0 && end > start, `${name} wrapper must remain a bounded API function`)
  return source.slice(start, end)
}

function assertReplaySourceContract(api: string, page: string): void {
  assert.match(
    api,
    /async function archiveReplayKey[\s\S]*SHA-256[\s\S]*archive-\$\{operation\}-\$\{fingerprint\}/,
    'archive keys must be bounded, deterministic fingerprints',
  )
  assert.match(
    apiFunction(api, 'planArchiveDelete', 'export async function deleteArchive'),
    /archiveDeletePlanIdempotencyKey\(archiveId\)/,
    'plan wrapper must derive its key from archiveId',
  )
  assert.match(
    apiFunction(api, 'deleteArchive', 'export async function readbackArchive'),
    /archiveDeleteIdempotencyKey\(\s*archiveId,\s*request\.delete_plan_id,\s*request\.expected_revision/,
    'delete wrapper must bind archiveId, plan ID, and revision',
  )
  assert.match(
    apiFunction(api, 'readbackArchive', 'const API_BASE'),
    /archiveReadbackIdempotencyKey\(\s*archiveId,\s*request\.readback_receipt_ref/,
    'readback wrapper must bind archiveId and receipt',
  )
  assert.match(
    page,
    /archiveDeleteConfirmationRef\(\s*archiveId,\s*deletePlan\.delete_plan_id/,
    'confirmation_ref must be bound to the selected delete plan',
  )
  assert.match(
    page,
    /archiveDeleteIdempotencyKey\(\s*archiveId,\s*deletePlan\.delete_plan_id,\s*expectedRevision/,
    'page delete retry must retain archive, plan, and revision identity',
  )
  assert.match(
    page,
    /archiveReadbackIdempotencyKey\(\s*archiveId,\s*result\.delete_receipt\.receipt_ref/,
    'page readback retry must retain the delete receipt identity',
  )
  assert.match(
    page,
    /setPlan\(null\);\s*setConfirmed\(false\);\s*setError\("归档删除暂时无法完成。请重新尝试。"\)/,
    'a failed delete must discard the stale plan and require a fresh confirmation',
  )
  assert.match(
    page,
    /disabled=\{busy \|\| \(Boolean\(plan\) && !confirmed\)\}/,
    'delete execution must remain disabled until the user confirms the bound plan',
  )
  assert.doesNotMatch(
    page,
    /web-confirm-\$\{archiveId\}/,
    'confirmation_ref must not be archive-only',
  )
}

async function expectedArchiveReplayKey(
  operation: 'plan' | 'delete' | 'readback' | 'confirmation',
  parts: readonly (string | number)[],
): Promise<string> {
  const canonical = JSON.stringify([operation, ...parts.map(String)])
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical))
  const fingerprint = Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, '0'),
  ).join('')
  return `archive-${operation}-${fingerprint}`
}

const legacyApi = apiSource.replace(
  'idempotencyKey: idempotencyKey ?? await archiveDeletePlanIdempotencyKey(archiveId)',
  'idempotencyKey: idempotencyKey ?? secureUuid()',
)
assert.throws(
  () => assertReplaySourceContract(legacyApi, pageSource),
  /plan wrapper/,
  'red fixture: a fresh plan key must fail the replay guard',
)
assertReplaySourceContract(apiSource, pageSource)

const archiveId = 'arc_9d6bcdf249f64aab8e2a85865bde8697'
const planId = 'delplan_913a9924f35d4187ac2b3d345d96a6ee'
const receiptRef = 'del_arc_9d6bcdf249f64aab8e2a85865bde8697_33c991e3dd254d88a9d3ed25e89de8a9'
const [planKey, deleteKey, readbackKey, confirmationRef] = await Promise.all([
  expectedArchiveReplayKey('plan', [archiveId]),
  expectedArchiveReplayKey('delete', [archiveId, planId, 7]),
  expectedArchiveReplayKey('readback', [archiveId, receiptRef]),
  expectedArchiveReplayKey('confirmation', [archiveId, planId]),
])
for (const key of [planKey, deleteKey, readbackKey, confirmationRef]) {
  assert.match(key, keyPattern)
  assert.ok(key.length <= 128, 'server idempotency key limit')
}
assert.notEqual(deleteKey, await expectedArchiveReplayKey('delete', [archiveId, planId, 8]))
assert.notEqual(deleteKey, await expectedArchiveReplayKey('delete', [archiveId, `${planId}-other`, 7]))
assert.notEqual(readbackKey, await expectedArchiveReplayKey('readback', [archiveId, `${receiptRef}-other`]))
assert.notEqual(confirmationRef, await expectedArchiveReplayKey('confirmation', [archiveId, `${planId}-other`]))

console.log('archive delete replay guard: PASS')
