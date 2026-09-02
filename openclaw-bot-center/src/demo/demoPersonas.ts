/** 演示站身份：完全在浏览器内构造，不连接任何身份服务，也不做鉴权。
 *  三个 persona 与生产 `resolveStudioRoutePolicy` 的三种 shell 一一对应。 */
export type DemoPersonaId = 'personal' | 'organization' | 'admin'

export type DemoSession = {
  publicUserId: string
  organizationName: string | null
  memberRole: 'owner' | 'member'
  organizationConnection: 'not_applicable' | 'connected' | 'pending' | 'disabled' | 'revoked' | 'attention'
  installationConnection: 'not_applicable' | 'connected' | 'pending' | 'disabled' | 'revoked' | 'attention'
  role: 'ordinary' | 'admin'
  maintainer: boolean
  csrfToken: string
  expiresAt: string
  routeGrants: string[]
  schemaVersion: 'media_web_business_pages_v2'
  workspaceMode: 'personal_web' | 'organization_lark'
  editorMode: 'web_edit' | 'lark_edit'
  bodyAuthority: 'internal' | 'lark'
}

/** 与 mediaWebApi.ts 的 exactRouteGrants 保持逐项一致，顺序也必须一致。 */
const personalRouteGrants = [
  '/today', '/studio', '/campaigns', '/business', '/desk', '/overview', '/assets', '/tracks',
  '/decisions', '/publishing', '/reviews', '/media-agent', '/archives', '/usage-billing', '/invites', '/workspace',
]
const organizationRouteGrants = ['/organization-workspace', '/tracks']
const adminRouteGrants = ['/admin/overview', '/admin/access', '/admin/tenants', '/admin/billing', '/admin/upstreams']

const baseSession = {
  maintainer: false,
  csrfToken: 'demo-csrf-token',
  expiresAt: '2099-01-01T00:00:00+00:00',
  schemaVersion: 'media_web_business_pages_v2',
} as const

export type DemoPersona = {
  id: DemoPersonaId
  label: string
  detail: string
  defaultRoute: string
  session: DemoSession
}

export const demoPersonas: readonly DemoPersona[] = [
  {
    id: 'personal',
    label: '个人创作者',
    detail: '个人云端工作区 · 全部内容生产页面',
    defaultRoute: '/overview',
    session: {
      ...baseSession,
      publicUserId: '11111111-1111-4111-8111-111111111111',
      organizationName: null,
      memberRole: 'owner',
      organizationConnection: 'not_applicable',
      installationConnection: 'not_applicable',
      role: 'ordinary',
      workspaceMode: 'personal_web',
      editorMode: 'web_edit',
      bodyAuthority: 'internal',
      routeGrants: personalRouteGrants,
    },
  },
  {
    id: 'organization',
    label: '组织成员',
    detail: '飞书组织工作区 · 文档正文以飞书为准',
    defaultRoute: '/organization-workspace',
    session: {
      ...baseSession,
      publicUserId: '22222222-2222-4222-8222-222222222222',
      organizationName: '光合内容工作室',
      memberRole: 'member',
      organizationConnection: 'connected',
      installationConnection: 'connected',
      role: 'ordinary',
      workspaceMode: 'organization_lark',
      editorMode: 'lark_edit',
      bodyAuthority: 'lark',
      routeGrants: organizationRouteGrants,
    },
  },
  {
    id: 'admin',
    label: '平台管理员',
    detail: '平台治理控制台 · 租户、计费与上游',
    defaultRoute: '/admin/overview',
    session: {
      ...baseSession,
      publicUserId: '33333333-3333-4333-8333-333333333333',
      organizationName: null,
      memberRole: 'owner',
      organizationConnection: 'not_applicable',
      installationConnection: 'not_applicable',
      role: 'admin',
      maintainer: true,
      workspaceMode: 'personal_web',
      editorMode: 'web_edit',
      bodyAuthority: 'internal',
      routeGrants: adminRouteGrants,
    },
  },
]

const storageKey = 'mediaclaw-demo-persona'

export function activePersonaId(): DemoPersonaId {
  try {
    const stored = localStorage.getItem(storageKey)
    if (stored === 'personal' || stored === 'organization' || stored === 'admin') return stored
  } catch {
    /* 隐私模式下退回默认 persona */
  }
  return 'personal'
}

export function activePersona(): DemoPersona {
  const id = activePersonaId()
  return demoPersonas.find((persona) => persona.id === id) ?? demoPersonas[0]
}

export function selectPersona(id: DemoPersonaId): void {
  try {
    localStorage.setItem(storageKey, id)
  } catch {
    /* 隐私模式：仅当前页面生效 */
  }
}
