export const ordinaryMediaNav = [
  { path: '/overview', label: '总览' },
  { path: '/tracks', label: '账号与赛道' },
  { path: '/assets', label: '素材与灵感' },
  { path: '/decisions', label: '选题与决策' },
  { path: '/runs', label: '创作与交付' },
  { path: '/publishing', label: '发布准备' },
  { path: '/reviews', label: '复盘增长' },
  { path: '/media-agent', label: 'Media Agent' },
  { path: '/archives', label: '云端归档' },
  { path: '/usage-billing', label: '用量与余额' },
  { path: '/invites', label: '邀请中心' },
] as const

export const ordinaryMediaNavGroups = [
  { label: '工作台', paths: ['/overview'] },
  { label: '内容运营', paths: ['/tracks', '/assets', '/decisions', '/runs', '/publishing', '/reviews'] },
  { label: '本机协作', paths: ['/media-agent', '/archives'] },
  { label: '账户', paths: ['/usage-billing', '/invites'] },
] as const

export const adminMediaNav = [
  { path: '/admin/overview', label: '平台总览' },
  { path: '/admin/access', label: '用户与准入' },
  { path: '/admin/tenants', label: '租户资源' },
  { path: '/admin/billing', label: '计费运营' },
  { path: '/admin/upstreams', label: '上游服务' },
] as const

export const retiredMediaNavLabels = [
  '媒体处理',
  '系统与工具',
  '设置与偏好',
  '平台管理',
] as const
