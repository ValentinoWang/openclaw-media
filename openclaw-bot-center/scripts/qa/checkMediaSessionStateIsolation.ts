import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(import.meta.dirname, '../..')
const source = readFileSync(resolve(projectRoot, 'src/media/MediaStudioApp.tsx'), 'utf8')

function inspect(value: string): string[] {
  const errors: string[] = []
  if (!value.includes('const authenticatedSession = requireAuthenticatedSession(session)')) errors.push('ProductShell must require an authenticated session')
  if (!value.includes('const sessionScope = JSON.stringify([authenticatedSession.publicUserId, authenticatedSession.workspaceMode, authenticatedSession.bodyAuthority, authenticatedSession.role, authenticatedSession.csrfToken])')) errors.push('session scope must unambiguously bind public user, workspace authority, and CSRF identity')
  if (!value.includes('<Routes key={sessionScope}>')) errors.push('route subtree must remount when session identity changes')
  return errors
}

assert.deepEqual(inspect(source), [])
assert.ok(inspect(source.replace('<Routes key={sessionScope}>', '<Routes>')).some((error) => error.includes('remount')), 'session remount red fixture was accepted')
assert.ok(inspect(source.replace('JSON.stringify([authenticatedSession.publicUserId, authenticatedSession.workspaceMode, authenticatedSession.bodyAuthority, authenticatedSession.role, authenticatedSession.csrfToken])', 'JSON.stringify([authenticatedSession.publicUserId])')).some((error) => error.includes('bind public user, workspace authority, and CSRF')), 'incomplete session scope red fixture was accepted')
assert.ok(inspect(source.replace('JSON.stringify([authenticatedSession.publicUserId, authenticatedSession.workspaceMode, authenticatedSession.bodyAuthority, authenticatedSession.role, authenticatedSession.csrfToken])', '`${authenticatedSession.publicUserId}:${authenticatedSession.workspaceMode}:${authenticatedSession.bodyAuthority}:${authenticatedSession.role}:${authenticatedSession.csrfToken}`')).some((error) => error.includes('unambiguously')), 'ambiguous delimiter-based session scope red fixture was accepted')
console.log('media session state isolation QA passed')
