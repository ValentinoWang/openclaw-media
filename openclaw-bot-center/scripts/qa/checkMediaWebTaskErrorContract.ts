import assert from 'node:assert/strict'
import { createServer } from 'vite'

type MediaWebApiModule = {
  loadTenantDashboard: () => Promise<unknown>
  MediaWebApiError: new (...args: never[]) => Error
}

const originalFetch = globalThis.fetch
const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
const { loadTenantDashboard, MediaWebApiError } = await vite.ssrLoadModule('/src/media/mediaWebApi.ts') as MediaWebApiModule

async function expectFailure(payload: unknown): Promise<Error & { code: string; status: number; details: unknown }> {
  globalThis.fetch = async () => new Response(JSON.stringify(payload), {
    status: 503,
    headers: { 'content-type': 'application/json' },
  })
  try {
    await loadTenantDashboard()
    assert.fail('a non-OK response must reject')
  } catch (error) {
    assert.equal(error instanceof MediaWebApiError, true)
    return error as Error & { code: string; status: number; details: unknown }
  }
}

try {
  const valid = await expectFailure({
    ok: false,
    error: {
      code: 'service_unavailable',
      message: '服务暂时不可用，请稍后重试。',
      details: { retryAfterSeconds: 30 },
    },
  })
  assert.equal(valid.code, 'service_unavailable')
  assert.equal(valid.status, 503)
  assert.deepEqual(valid.details, { retryAfterSeconds: 30 })

  const malformed = await expectFailure({
    ok: false,
    error: { code: 'service_unavailable', reason: 'legacy envelope', action: 'retry' },
  })
  assert.equal(malformed.code, 'invalid_error_response')
  assert.equal(malformed.message, '服务返回了无法识别的错误。')
  assert.equal(malformed.details, null)
} finally {
  globalThis.fetch = originalFetch
  await vite.close()
}

console.log('media web task error contract QA passed')
