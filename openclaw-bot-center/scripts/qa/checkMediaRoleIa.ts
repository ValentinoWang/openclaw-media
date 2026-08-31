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

for (const label of retiredMediaNavLabels) {
  requireContract(
    !ordinaryMediaNav.some((item) => item.label === label),
    'retired navigation label remains: ' + label,
  )
}

console.log('Media role IA data contract passed: 11 ordinary routes + 5 administrator routes')
