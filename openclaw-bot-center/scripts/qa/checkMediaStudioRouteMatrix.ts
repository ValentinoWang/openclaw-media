import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  resolveStudioRouteOutcome,
  resolveStudioRoutePolicy,
  studioAdminRoutes,
  studioOrganizationRoutes,
  studioOrdinaryRoutes,
  studioPersonalRoutes,
  studioTrackRoutes,
  type StudioRoutePolicy,
  type StudioSessionAuthority,
} from '../../src/media/mediaStudioRoutePolicy'

const projectRoot = resolve(import.meta.dirname, '../..')
const appSource = readFileSync(resolve(projectRoot, 'src/media/MediaStudioApp.tsx'), 'utf8')
const policySource = readFileSync(resolve(projectRoot, 'src/media/mediaStudioRoutePolicy.ts'), 'utf8')

type SessionFixture = StudioSessionAuthority

function requireStatic(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`static route-matrix check failed: ${message}`)
}

function requireInOrder(source: string, markers: readonly string[], message: string) {
  let cursor = -1
  for (const marker of markers) {
    const next = source.indexOf(marker, cursor + 1)
    requireStatic(next >= 0, `${message}: missing ${marker}`)
    requireStatic(next > cursor, `${message}: ${marker} is out of order`)
    cursor = next
  }
}

function requireNavigationPaths(startMarker: string, endMarker: string, expected: readonly string[], label: string) {
  const start = appSource.indexOf(startMarker)
  const end = appSource.indexOf(endMarker, start + startMarker.length)
  requireStatic(start >= 0 && end > start, `${label} declaration boundary is missing`)
  const block = appSource.slice(start, end)
  const explicitPaths = [...block.matchAll(/path: '([^']+)'/g)].map((match) => match[1])
  const actual = block.includes('...ordinaryNavigation')
    ? [...extractNavigationPaths('const ordinaryNavigation:', 'const adminNavigation:'), ...explicitPaths]
    : explicitPaths
  assert.deepEqual(actual, expected, `${label} paths drifted`)
}

function extractNavigationPaths(startMarker: string, endMarker: string): string[] {
  const start = appSource.indexOf(startMarker)
  const end = appSource.indexOf(endMarker, start + startMarker.length)
  requireStatic(start >= 0 && end > start, `navigation declaration boundary is missing for ${startMarker}`)
  return [...appSource.slice(start, end).matchAll(/path: '([^']+)'/g)].map((match) => match[1])
}

requireStatic(appSource.includes('resolveStudioRouteOutcome,') && appSource.includes('resolveStudioRoutePolicy,'), 'MediaStudioApp does not import the production route policy')
requireStatic(appSource.includes("from './mediaStudioRoutePolicy'"), 'MediaStudioApp policy import source is missing')
requireInOrder(
  policySource,
  [
    "if (session.role === 'admin')",
    "policyForShell('admin', '/admin/overview')",
    "if (session.workspaceMode === 'personal_web' && session.bodyAuthority === 'internal')",
    "policyForShell('personal', '/overview')",
    "if (session.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark')",
    "policyForShell('organization', '/organization-workspace')",
    "throw new Error('Unsupported media session authority shape')",
  ],
  'route policy must be role-first and fail closed',
)
requireStatic(!/const isAdminShell = isAdmin && !isOrganization/.test(appSource), 'old workspace-before-role admin boundary remains')
requireStatic(!/const navigation = isPersonal[\s\S]*?isOrganization[\s\S]*?isAdminShell/.test(appSource), 'old impossible ordinary navigation ordering remains')
requireStatic(appSource.includes('const authenticatedSession = requireAuthenticatedSession(session)'), 'ProductShell does not fail closed for a missing session')
requireStatic(appSource.includes('const routePolicy = resolveStudioRoutePolicy(authenticatedSession)'), 'ProductShell does not consume the production route policy')
requireStatic(appSource.includes('const navigation = navigationByShell[routePolicy.shell]'), 'navigation is not derived from the resolved shell policy')
requireStatic(appSource.includes("const isAdminShell = routePolicy.shell === 'admin'"), 'admin shell is not role-policy controlled')
requireStatic(appSource.includes("const isPersonal = routePolicy.shell === 'personal'"), 'personal shell is not policy controlled')
requireStatic(appSource.includes("const isOrganization = routePolicy.shell === 'organization'"), 'organization shell is not policy controlled')
requireStatic(appSource.includes("const isCompactNavigation = visibleNavigationItemCount < 3 && routePolicy.navigationMode === 'compact'"), 'compact navigation is not guarded by the explicit shell outcome')
requireStatic(appSource.includes('<BrowserRouter basename={import.meta.env.BASE_URL.replace(/\\/$/, \'\')}>'), 'BrowserRouter basename wiring drifted')
requireStatic(appSource.includes('replace />'), 'Navigate replace semantics are missing')
requireStatic(appSource.includes('<Route path="/runs/:runId" element={ordinaryRoute(\'/runs/:runId\', <CreationRunDetailPage />, routePolicy)} />'), 'run detail renderer identity drifted')
requireStatic(appSource.includes('<Route path="/studio/:runId" element={ordinaryRoute(\'/studio/:runId\', <CreationRunDetailPage />, routePolicy)} />'), 'studio detail renderer identity drifted')
requireStatic(appSource.includes('<Route path="/workspace/preview/:artifactId" element={personalRoute(\'/workspace/preview/:artifactId\', <PersonalWorkspaceShellPage />, routePolicy)} />'), 'workspace preview renderer identity drifted')

requireStatic(appSource.includes('!isAdminShell && !isOrganization ?'), 'personal Studio shell does not retain the current workspace card')
requireStatic(appSource.includes('{!isOrganization ? ('), 'personal Studio shell does not retain the current toolbar')
requireNavigationPaths('const ordinaryNavigation:', 'const adminNavigation:', [
  '/today', '/studio', '/campaigns', '/business', '/desk',
  '/overview', '/assets', '/tracks', '/decisions', '/publishing', '/reviews', '/media-agent', '/archives',
  '/usage-billing', '/invites',
], 'ordinary navigation')
requireNavigationPaths('const adminNavigation:', 'const personalNavigation:', [
  '/admin/overview', '/admin/access', '/admin/tenants', '/admin/billing', '/admin/upstreams',
], 'admin navigation')
requireNavigationPaths('const personalNavigation:', 'const organizationNavigation:', [
  '/today', '/studio', '/campaigns', '/business', '/desk',
  '/overview', '/assets', '/tracks', '/decisions', '/publishing', '/reviews', '/media-agent', '/archives',
  '/usage-billing', '/invites', '/workspace',
], 'personal navigation')
requireNavigationPaths('const organizationNavigation:', '/** 主题偏好', ['/organization-workspace', '/tracks'], 'organization navigation')

for (const pathname of [
  ...studioOrdinaryRoutes,
  ...studioTrackRoutes,
  '/runs',
  '/runs/:runId',
  '/studio/:runId',
  ...studioPersonalRoutes.slice(0, 1),
  '/workspace/preview/:artifactId',
  ...studioOrganizationRoutes,
  ...studioAdminRoutes,
]) {
  requireStatic(appSource.includes(`<Route path="${pathname}"`), `production route is missing: ${pathname}`)
}
requireStatic(appSource.includes('<Route path="/runs" element={studioAliasRoute(routePolicy)} />'), 'legacy /runs alias is not policy guarded')
requireStatic(appSource.includes('<Route path="/tracks" element={tracksRoute(<TracksPage />, routePolicy)} />'), 'Tracks route does not allow the organization shell')
requireStatic(appSource.includes('<Route path="/workspace" element={personalRoute(\'/workspace\', <WorkspaceShellPage />, routePolicy)} />'), 'workspace route is not personal-only')
requireStatic(appSource.includes('<Route path="/organization-workspace" element={organizationRoute(<OrganizationWorkspaceShellPage />, routePolicy)} />'), 'organization route is not organization-only')
requireStatic((appSource.match(/element=\{ordinaryRoute\(/g) ?? []).length === 16, 'ordinary route family is not guarded consistently')
requireStatic(!appSource.includes('<Route path="/workspace" element={<WorkspaceShellPage />} />'), 'unguarded workspace route regression remains')
requireStatic(!appSource.includes('<Route path="/runs" element={<Navigate to="/studio" replace />} />'), 'legacy alias is unguarded for admin and organization sessions')
requireStatic(appSource.includes('const outcome = resolveStudioRouteOutcome(policy, pathname)'), 'production route guards do not consume the pure policy outcome')
requireStatic(!appSource.includes("target: '/workspace'"), 'ordinary route policy must not redirect to the personal workspace')

const expectedNavigationPaths = {
  admin: ['/admin/overview', '/admin/access', '/admin/tenants', '/admin/billing', '/admin/upstreams'],
  personal: [
    '/today', '/studio', '/campaigns', '/business', '/desk', '/overview', '/assets', '/tracks', '/decisions',
    '/publishing', '/reviews', '/media-agent', '/archives', '/usage-billing', '/invites', '/workspace',
  ],
  organization: ['/organization-workspace', '/tracks'],
} as const

const expectedDefaultRoutes = {
  admin: '/admin/overview',
  personal: '/overview',
  organization: '/organization-workspace',
} as const

const fixtures: readonly [string, SessionFixture, StudioRoutePolicy][] = [
  [
    'admin with personal workspace',
    { role: 'admin', workspaceMode: 'personal_web', bodyAuthority: 'internal' },
    { shell: 'admin', defaultRoute: '/admin/overview', navigationPaths: expectedNavigationPaths.admin, navigationMode: 'full' },
  ],
  [
    'admin with organization workspace',
    { role: 'admin', workspaceMode: 'organization_lark', bodyAuthority: 'lark' },
    { shell: 'admin', defaultRoute: '/admin/overview', navigationPaths: expectedNavigationPaths.admin, navigationMode: 'full' },
  ],
  [
    'ordinary personal workspace',
    { role: 'ordinary', workspaceMode: 'personal_web', bodyAuthority: 'internal' },
    { shell: 'personal', defaultRoute: '/overview', navigationPaths: expectedNavigationPaths.personal, navigationMode: 'full' },
  ],
  [
    'ordinary organization workspace',
    { role: 'ordinary', workspaceMode: 'organization_lark', bodyAuthority: 'lark' },
    { shell: 'organization', defaultRoute: '/organization-workspace', navigationPaths: expectedNavigationPaths.organization, navigationMode: 'compact' },
  ],
]

const allMatrixPaths = [
  '/',
  ...studioOrdinaryRoutes,
  ...studioTrackRoutes,
  '/runs',
  '/runs/example',
  '/runs/example/details',
  '/studio/example',
  '/workspace',
  '/workspace/preview/artifact-1',
  '/organization-workspace',
  ...studioAdminRoutes,
  '/not-a-real-media-route',
] as const

function acceptedOutcome(shell: StudioRoutePolicy['shell'], pathname: string): ReturnType<typeof resolveStudioRouteOutcome> {
  const defaultRoute = expectedDefaultRoutes[shell]
  if (shell === 'admin' && studioAdminRoutes.includes(pathname as (typeof studioAdminRoutes)[number])) return { kind: 'render' }
  if (shell === 'organization' && (pathname === '/organization-workspace' || pathname === '/tracks')) return { kind: 'render' }
  if (shell === 'personal' && (pathname === '/workspace' || pathname === '/workspace/preview/artifact-1')) return { kind: 'render' }
  if (shell === 'personal' && pathname === '/runs') return { kind: 'redirect', target: '/studio' }
  if (shell === 'personal' && (studioOrdinaryRoutes.includes(pathname as (typeof studioOrdinaryRoutes)[number]) || pathname === '/tracks' || /^\/(?:runs|studio)\/[^/]+$/.test(pathname))) return { kind: 'render' }
  return { kind: 'redirect', target: defaultRoute }
}

type OutcomeResolver = (policy: StudioRoutePolicy, pathname: string) => ReturnType<typeof resolveStudioRouteOutcome>

function assertRouteMatrix(policy: StudioRoutePolicy, resolver: OutcomeResolver = resolveStudioRouteOutcome) {
  for (const pathname of allMatrixPaths) {
    assert.deepEqual(resolver(policy, pathname), acceptedOutcome(policy.shell, pathname), `${policy.shell} ${pathname} has the wrong accepted outcome`)
  }
}

function finalPathname(policy: StudioRoutePolicy, pathname: string): string {
  const outcome = resolveStudioRouteOutcome(policy, pathname)
  return outcome.kind === 'render' ? pathname : outcome.target
}

type CriticalRouteFixture = {
  label: string
  session: SessionFixture
  pathname: string
  finalPathname: string
  routeMarker: string
}

const criticalRouteFixtures: readonly CriticalRouteFixture[] = [
  {
    label: 'personal legacy Studio alias',
    session: { role: 'ordinary', workspaceMode: 'personal_web', bodyAuthority: 'internal' },
    pathname: '/runs',
    finalPathname: '/studio',
    routeMarker: '<Route path="/studio" element={ordinaryRoute(\'/studio\', <RunsPage />, routePolicy)} />',
  },
  {
    label: 'personal artifact preview',
    session: { role: 'ordinary', workspaceMode: 'personal_web', bodyAuthority: 'internal' },
    pathname: '/workspace/preview/artifact-1',
    finalPathname: '/workspace/preview/artifact-1',
    routeMarker: '<Route path="/workspace/preview/:artifactId" element={personalRoute(\'/workspace/preview/:artifactId\', <PersonalWorkspaceShellPage />, routePolicy)} />',
  },
  {
    label: 'organization excludes personal workspace',
    session: { role: 'ordinary', workspaceMode: 'organization_lark', bodyAuthority: 'lark' },
    pathname: '/workspace',
    finalPathname: '/organization-workspace',
    routeMarker: '<Route path="/organization-workspace" element={organizationRoute(<OrganizationWorkspaceShellPage />, routePolicy)} />',
  },
  {
    label: 'organization Tracks remains reachable',
    session: { role: 'ordinary', workspaceMode: 'organization_lark', bodyAuthority: 'lark' },
    pathname: '/tracks',
    finalPathname: '/tracks',
    routeMarker: '<Route path="/tracks" element={tracksRoute(<TracksPage />, routePolicy)} />',
  },
  {
    label: 'admin excludes ordinary Studio',
    session: { role: 'admin', workspaceMode: 'personal_web', bodyAuthority: 'internal' },
    pathname: '/studio',
    finalPathname: '/admin/overview',
    routeMarker: '<Route path="/admin/overview" element={adminRoute(\'/admin/overview\', <AdminOverviewPage />, routePolicy)} />',
  },
]

for (const fixture of criticalRouteFixtures) {
  const policy = resolveStudioRoutePolicy(fixture.session)
  assert.equal(
    finalPathname(policy, fixture.pathname),
    fixture.finalPathname,
    `${fixture.label} did not resolve to the expected final pathname`,
  )
  requireStatic(appSource.includes(fixture.routeMarker), `${fixture.label} route marker drifted from its guarded page renderer`)
}

for (const [label, session, expected] of fixtures) {
  const actual = resolveStudioRoutePolicy(session)
  assert.deepEqual(actual, expected, `${label} policy drifted`)
  assert.equal(actual.navigationPaths.length > 0, true, `${label} has no reachable navigation`)
  assertRouteMatrix(actual)
}

const invalidFixtures: readonly unknown[] = [
  null,
  { role: 'ordinary', workspaceMode: 'personal_web', bodyAuthority: 'lark' },
  { role: 'viewer', workspaceMode: 'personal_web', bodyAuthority: 'internal' },
]
for (const [index, invalid] of invalidFixtures.entries()) {
  assert.throws(() => resolveStudioRoutePolicy(invalid as SessionFixture), /Unsupported media session authority shape/, `invalid fixture ${index + 1} was accepted`)
}

const personalPolicy = resolveStudioRoutePolicy(fixtures[2][1])
const syntheticWorkspaceRedirect: OutcomeResolver = (policy, pathname) => {
  if (policy.shell === 'personal' && (studioOrdinaryRoutes.includes(pathname as (typeof studioOrdinaryRoutes)[number]) || pathname === '/tracks')) {
    return { kind: 'redirect', target: '/workspace' } as unknown as ReturnType<typeof resolveStudioRouteOutcome>
  }
  return resolveStudioRouteOutcome(policy, pathname)
}
assert.throws(
  () => assertRouteMatrix(personalPolicy, syntheticWorkspaceRedirect),
  /personal .* has the wrong accepted outcome/,
  'route matrix accepted a synthetic personal ordinary-route redirect to /workspace',
)

console.log('Media Studio route matrix QA passed: accepted personal/organization/admin authority, shared policy wiring, renderer identities, and synthetic /workspace drift rejection')
