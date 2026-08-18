import assert from 'node:assert/strict'
import { createServer } from 'vite'

const originalFetch = globalThis.fetch
const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
const { loadMediaWebSession } = await vite.ssrLoadModule('/src/media/mediaWebApi.ts') as {
  loadMediaWebSession: () => Promise<unknown>
}

async function loadFixture(payload: unknown) {
  globalThis.fetch = async () => new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
  return loadMediaWebSession()
}

try {
  const session = {
    publicUserId: '11111111-1111-4111-8111-111111111111',
    tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    organizationName: '测试飞书组织',
    workspaceMode: 'organization_lark' as const,
    editorMode: 'lark_edit' as const,
    bodyAuthority: 'lark' as const,
    memberRole: 'member' as const,
    organizationConnection: 'connected' as const,
    installationConnection: 'connected' as const,
    role: 'ordinary' as const,
    maintainer: false,
    csrfToken: 'csrf-session-contract',
    expiresAt: '2026-08-08T00:00:00+00:00',
    schemaVersion: 'media_web_business_pages_v2' as const,
  }
  assert.deepEqual(
    await loadFixture({
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session,
    }),
    session,
  )

  const personalSession = {
    ...session,
    organizationName: null,
    workspaceMode: 'personal_web' as const,
    editorMode: 'web_edit' as const,
    bodyAuthority: 'internal' as const,
    organizationConnection: 'not_applicable' as const,
    installationConnection: 'not_applicable' as const,
  }
  assert.deepEqual(
    await loadFixture({
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: personalSession,
    }),
    personalSession,
  )

  const rejectedFixtures = [
    {
      schemaVersion: 'media_web_channel_v1',
      authenticated: true,
      tenantId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      maintainer: false,
      role: 'user',
      mustChangePassword: false,
      csrfToken: 'csrf-session-contract',
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      session,
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...session, role: 'user' },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...session, tenantId: undefined },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...session, workspaceMode: 'personal_web' },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...session, memberRole: 'administrator' },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...session, organizationConnection: 'unknown' },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...session, bindingState: 'ACTIVE' },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...personalSession, organizationName: '不应出现在个人会话' },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...personalSession, organizationConnection: undefined },
    },
    {
      schemaVersion: 'media_web_business_pages_v2',
      revision: 1,
      session: { ...personalSession, installationConnection: undefined },
    },
  ]

  for (const fixture of rejectedFixtures) {
    await assert.rejects(() => loadFixture(fixture))
  }
} finally {
  globalThis.fetch = originalFetch
  await vite.close()
}

console.log('media session contract QA passed')
