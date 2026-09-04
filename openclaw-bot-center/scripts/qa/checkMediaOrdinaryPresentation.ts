import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from 'typescript'
import { pipelineDisplayLabel } from '../../src/media/ui/displayLabels'
import { generationSourceLabel, runStatusLabel } from '../../src/media/statusPresentation'
import {
  artifactTypeDisplayLabel,
  bodyAuthorityDisplayLabel,
  creatorRoleDisplayLabel,
  inviteStatusDisplayLabel,
  mediaTypeDisplayLabel,
  operationalStatusDisplayLabel,
  ownedAccountDataSourceDisplayLabel,
  qualityDisplayLabel,
  relationshipRoleDisplayLabel,
  relationshipStatusDisplayLabel,
  syncStatusDisplayLabel,
  trackStatusDisplayLabel,
} from '../../src/media/ui/ordinaryDataLabels'
import { platformDisplayLabel } from '../../src/media/ui/platformRegistry'

const ordinaryDirectory = resolve('src/media/pages/ordinary')
const ordinaryPages = readdirSync(ordinaryDirectory)
  .filter((name) => name.endsWith('Page.tsx'))
  .sort()

for (const retiredSource of [
  resolve('src/media/OverviewPage.tsx'),
  resolve('src/media/MediaAgentPage.tsx'),
  resolve('src/media/displayLabels.ts'),
]) {
  assert.equal(existsSync(retiredSource), false, `${retiredSource} is a retired duplicate; use pages/ordinary and ui/displayLabels instead`)
}

assert.equal(ordinaryPages.length, 12, 'ordinary Media page scope changed; update this presentation gate deliberately')

const presentationFiles = [
  ...ordinaryPages.map((name) => resolve(ordinaryDirectory, name)),
]

const ordinaryLabelsSource = readFileSync(resolve('src/media/ui/ordinaryDataLabels.ts'), 'utf8')
assert.doesNotMatch(ordinaryLabelsSource, /PLATFORM_LABELS|platformDisplayLabel/)

/** 只取**用户真的会看到**的文字：字符串字面量、模板字面量与 JSX 文本。
 *
 *  这几条判据是关于「给普通用户看的文案里不许出现接口/合同术语」的，之前却直接对
 *  整份源码做正则——注释里为了解释「这里把短事实排成一行」写下的「事实」二字就会
 *  让门禁变红。误报会教人绕着门禁写注释，最后注释越写越糊。 */
function userFacingText(file: string, source: string): string {
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const chunks: string[] = []
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) chunks.push(node.text)
    else if (ts.isTemplateExpression(node)) {
      chunks.push(node.head.text)
      for (const span of node.templateSpans) chunks.push(span.literal.text)
    } else if (ts.isJsxText(node)) chunks.push(node.text)
    ts.forEachChild(node, visit)
  }
  visit(tree)
  return chunks.join('\n')
}

for (const file of presentationFiles) {
  const source = readFileSync(file, 'utf8')
  assert.doesNotMatch(
    source,
    /(?:^|[^\w.$])(?:error|reason|cause)\.message\b/m,
    `${file} must not render a transport error message`,
  )
  const copy = userFacingText(file, source)
  assert.doesNotMatch(
    copy,
    /(?:部分|该|以下)?业务投影(?:暂时)?(?:不可用|无法读取)/,
    `${file} must name the failed resource instead of showing a generic projection failure`,
  )
  assert.doesNotMatch(
    copy,
    /接口|事实|回读|投影/,
    `${file} must not expose API or contract terminology to ordinary users`,
  )
}

const allOrdinaryTsxFiles = readdirSync(ordinaryDirectory)
  .filter((name) => name.endsWith('.tsx'))
  .sort()
  .map((name) => resolve(ordinaryDirectory, name))

for (const file of allOrdinaryTsxFiles) {
  const source = readFileSync(file, 'utf8')
  assert.doesNotMatch(source, /租户/, `${file} must not expose tenant wording to ordinary users`)
}

const overviewSource = readFileSync(resolve('src/media/pages/ordinary/OverviewPage.tsx'), 'utf8')
for (const expectedCopy of [
  '你账号下所有内容项目的汇总',
  '还没有可统计的内容，先从新建项目或导入素材开始',
  '部分数据暂时读不到，已如实标出',
]) {
  assert.match(overviewSource, new RegExp(expectedCopy), `OverviewPage must keep ordinary-user copy: ${expectedCopy}`)
}
for (const retiredCopy of [
  '运营总览接口返回的标准汇总',
  '当前租户没有可汇总的内容事实',
  '覆盖不完整，未知与不可用事实已明确保留',
]) {
  assert.doesNotMatch(overviewSource, new RegExp(retiredCopy), `OverviewPage must not restore contract copy: ${retiredCopy}`)
}

const ordinaryHelpSource = readFileSync(resolve('src/media/MediaStudioApp.tsx'), 'utf8')
assert.doesNotMatch(
  ordinaryHelpSource,
  /接口|事实|回读|投影/,
  'ordinary-user help must not expose API or contract terminology',
)

const runsSource = readFileSync(resolve('src/media/pages/ordinary/RunsPage.tsx'), 'utf8')
const decisionsSource = readFileSync(resolve('src/media/pages/ordinary/DecisionsPage.tsx'), 'utf8')
const decisionsStyles = readFileSync(resolve('src/media/pages/ordinary/DecisionsPage.module.css'), 'utf8')

assert.match(
  decisionsSource,
  /<th scope="row">[\s\S]*?publicDecisionId[\s\S]*?candidateTitle[\s\S]*?<\/th>[\s\S]*?<td className=\{styles\.platformCell\}>/,
  'DecisionsPage rows must present the public decision reference above the title and keep platform in its own column',
)
assert.equal(
  (decisionsSource.match(/<th scope="col">/g) ?? []).length,
  7,
  'DecisionsPage must expose all seven list columns to assistive technology',
)
// 列表呈现与 RunsPage 保持一致。字号自设计令牌迁移后走 mediaDesignTokens.css 的字阶：
//   0.65rem / 0.69rem -> --mg-text-xs（13px）
//   0.59rem           -> --mg-text-2xs（12px）
// 此处断言的是「两页共用同一套 token」这一奇偶性，而不是某个具体像素值。
for (const sharedRule of [
  'padding: 10px 12px;',
  'font-size: var(--mg-text-xs);',
  'line-height: 1.45;',
  'margin-top: 5px;',
  'font-size: var(--mg-text-2xs);',
  'text-overflow: ellipsis;',
  'white-space: nowrap;',
]) {
  assert.match(
    decisionsStyles,
    new RegExp(sharedRule.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
    `DecisionsPage list presentation must retain RunsPage parity rule: ${sharedRule}`,
  )
}

for (const rawEnum of ['artifact.artifactType', 'artifact.bodyAuthority', 'artifact.syncStatus']) {
  assert.doesNotMatch(
    runsSource,
    new RegExp(`\\{${rawEnum.replace('.', '\\.') }\\}`),
    `RunsPage must translate ${rawEnum} before display`,
  )
}

assert.equal(runStatusLabel('internal_backend_status'), '状态待确认')
assert.equal(generationSourceLabel('internal_backend_source'), '生成方式待确认')
assert.equal(operationalStatusDisplayLabel('active'), '运营中')
assert.equal(operationalStatusDisplayLabel('paused'), '暂停运营')
assert.equal(operationalStatusDisplayLabel('disabled'), '已停用')
assert.equal(ownedAccountDataSourceDisplayLabel('feishu_creator_profile'), '飞书达人账号档案')
for (const label of [
  platformDisplayLabel,
  trackStatusDisplayLabel,
  operationalStatusDisplayLabel,
  ownedAccountDataSourceDisplayLabel,
  creatorRoleDisplayLabel,
  relationshipRoleDisplayLabel,
  relationshipStatusDisplayLabel,
  inviteStatusDisplayLabel,
  qualityDisplayLabel,
  mediaTypeDisplayLabel,
  artifactTypeDisplayLabel,
  bodyAuthorityDisplayLabel,
  syncStatusDisplayLabel,
]) {
  assert.doesNotMatch(label('internal_backend_enum'), /internal_backend_enum/i)
}
assert.equal(
  pipelineDisplayLabel({
    pipeline_id: 'internal.backend.pipeline',
    version: '1',
    display_name: 'INTERNAL_BACKEND_PIPELINE',
    catalog_digest: '',
  }),
  '其他流程',
)

console.log('media ordinary presentation contract passed')
