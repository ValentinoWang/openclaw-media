export const MEDIA_PRIMITIVES = ['mg-panel', 'mg-btn', 'mg-tabs', 'mg-metric-grid', 'mg-hero', 'state'] as const
export type MediaPrimitive = (typeof MEDIA_PRIMITIVES)[number]
export type MediaSurfaceFamily = 'admin' | 'ordinary' | 'studio' | 'organization' | 'shared'

type RouteSurface = { component: string; importModule: string; paths: readonly string[] }

export type MediaSurfaceSpec = {
  id: string
  source: string
  family: MediaSurfaceFamily
  ownership?: 'governance' | 'personal' | 'organization'
  accent?: 'studio' | 'campaign' | 'business' | 'desk' | 'agent' | 'archive'
  eligible: readonly MediaPrimitive[]
  exemption?: string
  route?: RouteSurface
}

const primitives = <T extends MediaPrimitive>(...values: T[]) => values

// This is the sole 24-surface visual-adoption ledger. The adoption guard binds
// each routed entry below to the production MediaStudioApp route registry.
export const CANONICAL_MEDIA_PAGE_SURFACES: readonly MediaSurfaceSpec[] = [
  { id: 'admin-overview', source: 'pages/admin/AdminOverviewPage.tsx', family: 'admin', ownership: 'governance', accent: 'desk', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), exemption: 'single overview surface has no switchable view', route: { component: 'AdminOverviewPage', importModule: './pages/admin/AdminOverviewPage', paths: ['/admin/overview'] } },
  { id: 'admin-access', source: 'pages/admin/AdminAccessPage.tsx', family: 'admin', ownership: 'governance', accent: 'campaign', eligible: primitives('mg-panel', 'mg-btn', 'mg-tabs', 'mg-hero', 'state'), route: { component: 'AdminAccessPage', importModule: './pages/admin/AdminAccessPage', paths: ['/admin/access'] } },
  { id: 'admin-tenants', source: 'pages/admin/AdminTenantsPage.tsx', family: 'admin', ownership: 'governance', accent: 'studio', eligible: primitives(...MEDIA_PRIMITIVES), route: { component: 'AdminTenantsPage', importModule: './pages/admin/AdminTenantsPage', paths: ['/admin/tenants'] } },
  { id: 'admin-billing', source: 'pages/admin/AdminBillingPage.tsx', family: 'admin', ownership: 'governance', accent: 'business', eligible: primitives(...MEDIA_PRIMITIVES), route: { component: 'AdminBillingPage', importModule: './pages/admin/AdminBillingPage', paths: ['/admin/billing'] } },
  { id: 'admin-upstreams', source: 'pages/admin/AdminUpstreamsPage.tsx', family: 'admin', ownership: 'governance', accent: 'agent', eligible: primitives('mg-panel', 'mg-btn', 'state'), exemption: 'no switchable view, repeated metrics, or hero geometry', route: { component: 'AdminUpstreamsPage', importModule: './pages/admin/AdminUpstreamsPage', paths: ['/admin/upstreams'] } },
  { id: 'ordinary-overview', source: 'pages/ordinary/OverviewPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'studio', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), exemption: 'single overview surface has no switchable view', route: { component: 'OverviewPage', importModule: './pages/ordinary/OverviewPage', paths: ['/overview'] } },
  { id: 'ordinary-assets', source: 'pages/ordinary/AssetsPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'studio', eligible: primitives('mg-panel', 'mg-btn', 'mg-tabs', 'mg-hero', 'state'), route: { component: 'AssetsPage', importModule: './pages/ordinary/AssetsPage', paths: ['/assets'] } },
  { id: 'ordinary-decisions', source: 'pages/ordinary/DecisionsPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'campaign', eligible: primitives('mg-panel', 'mg-btn', 'mg-tabs', 'mg-hero', 'state'), route: { component: 'DecisionsPage', importModule: './pages/ordinary/DecisionsPage', paths: ['/decisions'] } },
  { id: 'ordinary-runs', source: 'pages/ordinary/RunsPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'studio', eligible: primitives(...MEDIA_PRIMITIVES), route: { component: 'RunsPage', importModule: './pages/ordinary/RunsPage', paths: ['/studio'] } },
  { id: 'ordinary-run-detail', source: 'CreationRunDetailPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'studio', eligible: primitives('mg-panel', 'mg-btn', 'mg-tabs', 'mg-hero', 'state'), route: { component: 'CreationRunDetailPage', importModule: './CreationRunDetailPage', paths: ['/runs/:runId', '/studio/:runId'] } },
  { id: 'ordinary-publishing', source: 'pages/ordinary/PublishingPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'campaign', eligible: primitives('mg-panel', 'mg-hero', 'state'), exemption: 'read-only publishing status has no in-page action or switchable view', route: { component: 'PublishingPage', importModule: './pages/ordinary/PublishingPage', paths: ['/publishing'] } },
  { id: 'ordinary-reviews', source: 'pages/ordinary/ReviewsPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'desk', eligible: primitives(...MEDIA_PRIMITIVES), route: { component: 'ReviewsPage', importModule: './pages/ordinary/ReviewsPage', paths: ['/reviews'] } },
  { id: 'ordinary-media-agent', source: 'pages/ordinary/MediaAgentPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'agent', eligible: primitives('mg-panel', 'mg-btn', 'mg-tabs', 'mg-hero', 'state'), route: { component: 'MediaAgentPage', importModule: './pages/ordinary/MediaAgentPage', paths: ['/media-agent'] } },
  { id: 'ordinary-archives', source: 'pages/ordinary/ArchivesPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'archive', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), route: { component: 'ArchivesPage', importModule: './pages/ordinary/ArchivesPage', paths: ['/archives'] } },
  { id: 'ordinary-usage-billing', source: 'pages/ordinary/UsageBillingPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'business', eligible: primitives('mg-panel', 'mg-btn', 'mg-tabs', 'mg-hero', 'state'), route: { component: 'UsageBillingPage', importModule: './pages/ordinary/UsageBillingPage', paths: ['/usage-billing'] } },
  { id: 'ordinary-invites', source: 'pages/ordinary/InvitesPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'campaign', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), exemption: 'single invitation flow has no switchable view', route: { component: 'InvitesPage', importModule: './pages/ordinary/InvitesPage', paths: ['/invites'] } },
  { id: 'ordinary-tracks', source: 'pages/ordinary/TracksPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'desk', eligible: primitives(...MEDIA_PRIMITIVES), route: { component: 'TracksPage', importModule: './pages/ordinary/TracksPage', paths: ['/tracks'] } },
  { id: 'ordinary-personal-workspace', source: 'PersonalWorkspaceShellPage.tsx', family: 'ordinary', ownership: 'personal', accent: 'studio', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), exemption: 'workspace shell has no switchable view', route: { component: 'PersonalWorkspaceShellPage', importModule: './PersonalWorkspaceShellPage', paths: ['/workspace/preview/:artifactId'] } },
  { id: 'studio-business', source: 'studio/BusinessPage.tsx', family: 'studio', ownership: 'personal', accent: 'business', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), route: { component: 'BusinessPage', importModule: './studio/BusinessPage', paths: ['/business'] } },
  { id: 'studio-campaigns', source: 'studio/CampaignsPage.tsx', family: 'studio', ownership: 'personal', accent: 'campaign', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), route: { component: 'CampaignsPage', importModule: './studio/CampaignsPage', paths: ['/campaigns'] } },
  { id: 'studio-desk', source: 'studio/DeskPage.tsx', family: 'studio', ownership: 'personal', accent: 'desk', eligible: primitives('mg-panel', 'mg-btn', 'mg-hero'), exemption: 'static research entry has no metric collection or load-state branch', route: { component: 'DeskPage', importModule: './studio/DeskPage', paths: ['/desk'] } },
  { id: 'studio-workboard', source: 'studio/WorkboardPage.tsx', family: 'studio', ownership: 'personal', accent: 'studio', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), route: { component: 'WorkboardPage', importModule: './studio/WorkboardPage', paths: ['/today'] } },
  { id: 'organization-workspace', source: 'OrganizationWorkspaceShellPage.tsx', family: 'organization', ownership: 'organization', accent: 'campaign', eligible: primitives('mg-panel', 'mg-btn', 'mg-metric-grid', 'mg-hero', 'state'), exemption: 'organization shell has no switchable view', route: { component: 'OrganizationWorkspaceShellPage', importModule: './OrganizationWorkspaceShellPage', paths: ['/organization-workspace'] } },
  { id: 'canonical-document-renderer', source: 'pages/ordinary/CanonicalDocumentRenderer.tsx', family: 'shared', eligible: primitives('mg-panel', 'state'), exemption: 'shared block renderer is not a route root' },
]

export const CANONICAL_ROUTE_EXEMPTIONS = [
  { path: '/', reason: 'redirect route has no page renderer' },
  { path: '/runs', reason: 'legacy route alias has no page renderer' },
  { path: '/workspace', component: 'WorkspaceShellPage', importModule: './WorkspaceShellPage', reason: 'workspace dispatcher is intentionally outside the 24-surface visual ledger' },
  { path: '*', reason: 'fallback redirect has no page renderer' },
] as const

export const CANONICAL_RENDERER_EXEMPTIONS = [
  { source: 'pages/ordinary/CanonicalDocumentRenderer.tsx', reason: 'non-route shared renderer is intentionally outside the production route registry' },
] as const

export const CANONICAL_PERSISTENT_RAIL_PAGES = [
  'admin/AdminAccessPage.tsx', 'admin/AdminBillingPage.tsx', 'admin/AdminOverviewPage.tsx', 'admin/AdminTenantsPage.tsx', 'admin/AdminUpstreamsPage.tsx',
  'ordinary/ArchivesPage.tsx', 'ordinary/AssetsPage.tsx', 'ordinary/DecisionsPage.tsx', 'ordinary/InvitesPage.tsx', 'ordinary/MediaAgentPage.tsx', 'ordinary/OverviewPage.tsx', 'ordinary/PublishingPage.tsx', 'ordinary/ReviewsPage.tsx', 'ordinary/RunsPage.tsx', 'ordinary/TracksPage.tsx', 'ordinary/UsageBillingPage.tsx',
] as const

export const CANONICAL_PERSISTENT_RAIL_SOURCE_FILES = CANONICAL_PERSISTENT_RAIL_PAGES.map((file) => `src/media/pages/${file}` as const)
