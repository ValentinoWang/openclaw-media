import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const page = readFileSync(resolve('src/media/OrganizationWorkspaceShellPage.tsx'), 'utf8')
const workspace = readFileSync(resolve('src/media/WorkspaceShellPage.tsx'), 'utf8')
const app = readFileSync(resolve('src/media/MediaApp.tsx'), 'utf8')
const styles = readFileSync(resolve('src/media/media.css'), 'utf8')

assert.match(page, /workspaceMode !== 'organization_lark' \|\| session\.bodyAuthority !== 'lark'/, 'organization shell must require the server organization session')
assert.match(page, /!session\.organizationName/, 'organization shell must fail closed when the server organization name is unavailable')
assert.match(page, /memberRoleLabels[\s\S]*owner:[\s\S]*member:/, 'organization shell must define both server member roles')
assert.match(page, /memberRoleLabels\[session\.memberRole\]/, 'organization shell must render the server member role')
assert.match(page, /session\.organizationName/, 'organization shell must render the server organization name')
assert.match(page, /session\.organizationConnection/, 'organization shell must consume the public organization connection projection')
for (const state of ['connected', 'pending', 'disabled', 'revoked', 'attention']) {
  assert.match(page, new RegExp(`['"]${state}['"]`), `organization shell is missing public connection state ${state}`)
}
assert.match(page, /return 'attention'/, 'missing or unknown public connection state must fail closed')
assert.match(page, /data-organization-connection=\{connection\.state\}/, 'rendered organization connection must be traceable to the public projection')
assert.match(app, /session\?\.organizationName/, 'organization sidebar must render the server organization name')
assert.doesNotMatch(app, /organizationName\s*\?\?\s*['"]组织工作区['"]/, 'organization sidebar must not hide a missing organization name behind a generic label')

for (const forbidden of [
  'tenantId',
  'localStorage',
  'sessionStorage',
  'useSearchParams',
  'URLSearchParams',
  'session.role',
  'bindingState',
  'installationState',
  'Binding 状态',
  'ACTIVE',
  'NEEDS_ATTENTION',
  'data-binding-',
]) {
  assert.equal(page.includes(forbidden), false, `organization shell must not expose internal field or value ${forbidden}`)
}
for (const forbidden of ['Writer', 'writer', 'openWorkspace', 'createMediaTask', '<Link', 'href=']) {
  assert.equal(page.includes(forbidden), false, `organization shell exposes forbidden write action ${forbidden}`)
}

assert.match(workspace, /PersonalWorkspaceShellPage/, 'personal workspace branch must remain separate')
assert.match(workspace, /OrganizationWorkspaceShellPage/, 'workspace shell must dispatch the organization branch')
assert.doesNotMatch(workspace, /tenantId/, 'shared workspace shell must not display a client tenant identifier')

assert.match(app, /const isOrganization = session\?\.workspaceMode === 'organization_lark' && session\.bodyAuthority === 'lark'/, 'MediaApp must use the server workspace authority for organization routing')
assert.match(app, /const organizationMediaNav/, 'organization shell must have a dedicated read-only navigation')
assert.match(app, /path="\/organization-workspace"/, 'organization shell route is missing')
assert.match(app, /isOrganization\s*\?\s*<OrganizationGlobalToolbar\s*\/>/, 'organization mode must not render the ordinary task toolbar')
assert.match(app, /isOrganization\s*\?\s*<Navigate to="\/organization-workspace" replace \/>/, 'ordinary and admin routes must return to the organization shell')

assert.match(styles, /\.organization-shell-grid\s*\{[\s\S]*?min-width: 0/, 'organization shell grid must prevent narrow-content overflow')
assert.match(styles, /\.organization-shell-facts[^\n]*overflow-wrap: anywhere/, 'organization shell facts must wrap long server values')
assert.match(styles, /@media \(max-width: 980px\) \{[\s\S]*?\.organization-shell-grid \{ grid-template-columns: 1fr; \}/, 'organization shell must collapse to one column on smaller screens')
assert.match(styles, /\.organization-shell-state[^\n]*min-height/, 'organization shell status needs a stable layout box')

console.log('organization workspace shell QA passed: real organization name, public connection projection, read-only boundary, route, and mobile structure')
