import type { MediaWebSession } from './mediaWebApi'

export type StudioShell = 'admin' | 'personal' | 'organization'
export type StudioDefaultRoute = '/admin/overview' | '/overview' | '/organization-workspace'
export type StudioRouteRedirectTarget = StudioDefaultRoute | '/studio'
export type StudioNavigationMode = 'full' | 'compact'
export type StudioSessionAuthority = Pick<MediaWebSession, 'role' | 'workspaceMode' | 'bodyAuthority'>

export const studioAdminRoutes = [
  '/admin/overview',
  '/admin/access',
  '/admin/tenants',
  '/admin/billing',
  '/admin/upstreams',
] as const

export const studioOrdinaryRoutes = [
  '/today',
  '/studio',
  '/campaigns',
  '/business',
  '/desk',
  '/overview',
  '/assets',
  '/decisions',
  '/publishing',
  '/reviews',
  '/media-agent',
  '/archives',
  '/usage-billing',
  '/invites',
] as const

export const studioTrackRoutes = ['/tracks'] as const
export const studioPersonalRoutes = ['/workspace', '/workspace/preview/artifact-1'] as const
export const studioOrganizationRoutes = ['/organization-workspace'] as const

export const studioPersonalNavigationPaths = [
  '/today',
  '/studio',
  '/campaigns',
  '/business',
  '/desk',
  '/overview',
  '/assets',
  '/tracks',
  '/decisions',
  '/publishing',
  '/reviews',
  '/media-agent',
  '/archives',
  '/usage-billing',
  '/invites',
  '/workspace',
] as const

export const studioNavigationPaths = {
  admin: studioAdminRoutes,
  personal: studioPersonalNavigationPaths,
  organization: ['/organization-workspace', '/tracks'] as const,
} as const

export const studioShellNavigationModes: Readonly<Record<StudioShell, StudioNavigationMode>> = {
  admin: 'full',
  personal: 'full',
  organization: 'compact',
}

export type StudioRoutePolicy = {
  shell: StudioShell
  defaultRoute: StudioDefaultRoute
  navigationPaths: readonly string[]
  navigationMode: StudioNavigationMode
}

export type StudioRouteOutcome = { kind: 'render' } | { kind: 'redirect'; target: StudioRouteRedirectTarget }

function policyForShell(shell: StudioShell, defaultRoute: StudioDefaultRoute): StudioRoutePolicy {
  return {
    shell,
    defaultRoute,
    navigationPaths: studioNavigationPaths[shell],
    navigationMode: studioShellNavigationModes[shell],
  }
}

export function resolveStudioRoutePolicy(session: StudioSessionAuthority): StudioRoutePolicy {
  if (!session || typeof session !== 'object') throw new Error('Unsupported media session authority shape')
  if (session.role !== 'ordinary' && session.role !== 'admin') throw new Error('Unsupported media session authority shape')
  if (session.role === 'admin') return policyForShell('admin', '/admin/overview')
  if (session.workspaceMode === 'personal_web' && session.bodyAuthority === 'internal') {
    return policyForShell('personal', '/overview')
  }
  if (session.workspaceMode === 'organization_lark' && session.bodyAuthority === 'lark') {
    return policyForShell('organization', '/organization-workspace')
  }
  throw new Error('Unsupported media session authority shape')
}

export function resolveStudioRouteOutcome(policy: StudioRoutePolicy, pathname: string): StudioRouteOutcome {
  if (pathname === '/runs') {
    return policy.shell === 'personal' ? { kind: 'redirect', target: '/studio' } : { kind: 'redirect', target: policy.defaultRoute }
  }
  if (/^\/runs\/[^/]+$/.test(pathname) || /^\/studio\/[^/]+$/.test(pathname)) {
    return policy.shell === 'personal' ? { kind: 'render' } : { kind: 'redirect', target: policy.defaultRoute }
  }
  if (studioAdminRoutes.includes(pathname as (typeof studioAdminRoutes)[number])) {
    return policy.shell === 'admin' ? { kind: 'render' } : { kind: 'redirect', target: policy.defaultRoute }
  }
  if (pathname === '/tracks') {
    return policy.shell === 'personal' || policy.shell === 'organization'
      ? { kind: 'render' }
      : { kind: 'redirect', target: policy.defaultRoute }
  }
  if (studioOrdinaryRoutes.includes(pathname as (typeof studioOrdinaryRoutes)[number])) {
    return policy.shell === 'personal' ? { kind: 'render' } : { kind: 'redirect', target: policy.defaultRoute }
  }
  if (pathname === '/workspace' || /^\/workspace\/preview\/[^/]+$/.test(pathname)) {
    return policy.shell === 'personal' ? { kind: 'render' } : { kind: 'redirect', target: policy.defaultRoute }
  }
  if (pathname === '/organization-workspace') {
    return policy.shell === 'organization' ? { kind: 'render' } : { kind: 'redirect', target: policy.defaultRoute }
  }
  return { kind: 'redirect', target: policy.defaultRoute }
}
