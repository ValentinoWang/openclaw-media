import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { adminMediaNav, ordinaryMediaNav, ordinaryMediaNavGroups, retiredMediaNavLabels } from '../../src/media/mediaRoleIa'

function requireContract(condition: boolean, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function exactPairs(items: readonly { path: string; label: string }[], expected: readonly (readonly [string, string])[]) {
  return JSON.stringify(items.map((item) => [item.path, item.label])) === JSON.stringify(expected)
}

const expectedOrdinary = [
  ['/overview', '总览'], ['/tracks', '账号与赛道'], ['/assets', '素材与灵感'],
  ['/decisions', '选题与决策'], ['/runs', '创作与交付'], ['/publishing', '发布准备'],
  ['/reviews', '复盘增长'], ['/media-agent', 'Media Agent'], ['/archives', '云端归档'],
  ['/usage-billing', '用量与余额'], ['/invites', '邀请中心'],
] as const
const expectedAdmin = [
  ['/admin/overview', '平台总览'], ['/admin/access', '用户与准入'],
  ['/admin/tenants', '租户资源'], ['/admin/billing', '计费运营'],
  ['/admin/upstreams', '上游服务'],
] as const
const expectedOrdinaryGroups = [
  ['工作台', ['/overview']],
  ['内容运营', ['/tracks', '/assets', '/decisions', '/runs', '/publishing', '/reviews']],
  ['本机协作', ['/media-agent', '/archives']],
  ['账户', ['/usage-billing', '/invites']],
] as const

requireContract(exactPairs(ordinaryMediaNav, expectedOrdinary), 'ordinary Media IA drifted')
requireContract(exactPairs(adminMediaNav, expectedAdmin), 'administrator Media IA drifted')
requireContract(
  JSON.stringify(ordinaryMediaNavGroups.map((group) => [group.label, group.paths])) === JSON.stringify(expectedOrdinaryGroups),
  'ordinary Media navigation groups drifted',
)
requireContract(
  JSON.stringify(ordinaryMediaNavGroups.flatMap((group) => group.paths)) === JSON.stringify(ordinaryMediaNav.map((item) => item.path)),
  'ordinary Media navigation group boundaries do not cover the frozen route order',
)

const app = readFileSync(resolve('src/media/MediaApp.tsx'), 'utf8')
requireContract(!app.includes('用量与套餐'), 'retired billing label remains in MediaApp')
requireContract(/from\s+\x27\.\/mediaRoleIa\x27/.test(app), 'MediaApp does not consume the frozen Media IA')
requireContract(app.includes("const isAdmin = session?.role === 'admin'"), 'administrator shell role boundary is missing')
// 个人 / 组织工作区加入后，管理员判定收敛为 isAdminShell（isAdmin 且非组织模式）。
// 断言意图不变：管理员壳层必须整体替换普通导航，而不是叠加。
requireContract(app.includes("const isAdminShell = isAdmin && !isOrganization"), 'administrator shell boundary must derive from role and workspace mode')
requireContract(app.includes('isAdminShell ? adminMediaNav : ordinaryMediaNav'), 'administrator shell does not replace the ordinary shell')
requireContract(app.includes('ordinaryMediaNavGroups.map'), 'ordinary shell does not render frozen navigation groups')
for (const { path } of [...ordinaryMediaNav, ...adminMediaNav]) {
  requireContract(app.includes('path="' + path + '"'), 'missing production route ' + path)
}
for (const label of retiredMediaNavLabels) {
  requireContract(
    !app.includes(`>${label}<`) && !app.includes(`'${label}'`) && !app.includes(`"${label}"`),
    'retired navigation label remains: ' + label,
  )
}
for (const retiredRoute of ['path="/usage"', 'path="/billing"', 'path="/admin"']) {
  requireContract(!app.includes(retiredRoute), 'retired production route remains: ' + retiredRoute)
}

console.log('Media role IA contract passed: 11 ordinary routes + 5 administrator routes')
