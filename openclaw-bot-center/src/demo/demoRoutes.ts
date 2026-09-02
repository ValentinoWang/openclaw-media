/** 演示站的静态页面清单：既用于生成每个路由的独立 HTML 文件，
 *  也用于演示控制台的页面索引与 QA 走查。顺序与生产导航保持一致。 */
export type DemoRouteGroup = {
  label: string
  persona: 'personal' | 'organization' | 'admin'
  routes: ReadonlyArray<{ path: string; label: string; detail?: string }>
}

export const demoRouteGroups: readonly DemoRouteGroup[] = [
  {
    label: '核心工作区',
    persona: 'personal',
    routes: [
      { path: '/today', label: '今日工作台', detail: '下一步与截止事项' },
      { path: '/studio', label: 'Studio 创作台', detail: '脚本、分镜与交付' },
      { path: '/campaigns', label: '活动与商单', detail: '活动与商单履约' },
      { path: '/business', label: '商业化', detail: '报价、档期与商机' },
      { path: '/desk', label: '情报台', detail: '情报、拆解与增长' },
      { path: '/overview', label: '项目概览', detail: '项目状态与下一步' },
    ],
  },
  {
    label: '资源与执行',
    persona: 'personal',
    routes: [
      { path: '/assets', label: '素材库', detail: '原始素材与证据' },
      { path: '/tracks', label: '账号与赛道', detail: '自有账号与监控' },
      { path: '/decisions', label: '选题与决策', detail: '证据、候选与人工状态' },
      { path: '/publishing', label: '发布交付', detail: '发布准备与渠道交付' },
      { path: '/reviews', label: '复盘洞察', detail: '发布数据与账号学习' },
      { path: '/media-agent', label: 'Agent 任务', detail: '本机执行与人工确认' },
      { path: '/archives', label: '云端归档', detail: '成果与历史记录' },
    ],
  },
  {
    label: '账户与个人空间',
    persona: 'personal',
    routes: [
      { path: '/usage-billing', label: '用量与余额' },
      { path: '/invites', label: '团队邀请' },
      { path: '/workspace', label: '个人云端成果' },
    ],
  },
  {
    label: '详情页示例',
    persona: 'personal',
    routes: [
      { path: '/studio/run_autumn_camera_01', label: '创作运行详情', detail: '来源、决策与产物三段式' },
      { path: '/workspace/preview/artifact_creation_camera', label: '云端成果预览', detail: '只读正文与导出' },
      { path: '/workspace/edit/artifact_creation_camera', label: '正文编辑器', detail: '结构化正文与修订' },
    ],
  },
  {
    label: '组织工作区',
    persona: 'organization',
    routes: [
      { path: '/organization-workspace', label: '组织工作区', detail: '文档正文以飞书为准' },
      { path: '/organization-workspace/document/artifact_creation_camera', label: '组织文档镜像', detail: '飞书正文投影与修订' },
    ],
  },
  {
    label: '平台治理',
    persona: 'admin',
    routes: [
      { path: '/admin/overview', label: '平台总览' },
      { path: '/admin/access', label: '用户与准入' },
      { path: '/admin/tenants', label: '租户资源' },
      { path: '/admin/billing', label: '计费运营' },
      { path: '/admin/upstreams', label: '上游服务' },
    ],
  },
]

/** 需要落成物理 HTML 文件的路由：静态服务器没有 SPA 回退时也能直接打开。 */
export const demoStaticRoutes: readonly string[] = demoRouteGroups.flatMap((group) =>
  group.routes.map((route) => route.path),
)
