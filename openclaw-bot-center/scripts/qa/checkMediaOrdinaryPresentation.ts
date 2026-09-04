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
  formatByteSize,
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

/** ArchivesPage-local terminology that reads as machine-translated internal jargon
 *  ("小产物"/"轻量产物"/"小附件" are literal renderings of "artifact", "描述符" of
 *  "descriptor", "合同" of the OpenAPI/business contract) instead of the plain wording
 *  this product already uses elsewhere for the same concepts (plain "产物", spelled-out
 *  sentences instead of "descriptor"/"contract" nouns). Scoped to ArchivesPage only:
 *  MediaAgentPage.tsx and RunsPage.tsx still carry some of these same words and are not
 *  part of this pass, so widening this into the all-ordinary-pages loop above would fail
 *  on files this gate isn't cleaning up. */
const ARCHIVES_INTERNAL_JARGON_PATTERN = /小产物|轻量产物|小附件|描述符|合同/

/** True for a bare identifier / property-access / string-keyed element-access whose own final
 *  name looks like a byte count (e.g. `cloud_bytes`, `archive.media_cloud_bytes`,
 *  `row["size_bytes"]`). Deliberately narrow -- this must NOT walk into the expression and
 *  match any *nested* "bytes" text, or it would also flag a large wrapping expression such as
 *  `archive ? (<>...{archive.media_cloud_bytes}...</>) : (...)` just because a bytes-named
 *  identifier happens to sit somewhere inside its JSX; that ternary is fine; only the bare
 *  inner expression is the violation, and it is reached on its own by the recursive walk in
 *  findRawByteRenders below. */
function isByteCountExpression(expr: ts.Expression): boolean {
  const unwrapped = ts.isParenthesizedExpression(expr) ? expr.expression : expr
  if (ts.isIdentifier(unwrapped)) return /bytes/i.test(unwrapped.text)
  if (ts.isPropertyAccessExpression(unwrapped)) return /bytes/i.test(unwrapped.name.text)
  if (ts.isElementAccessExpression(unwrapped) && ts.isStringLiteralLike(unwrapped.argumentExpression)) {
    return /bytes/i.test(unwrapped.argumentExpression.text)
  }
  return false
}

/** Flags a byte-count-shaped JSX expression that is rendered bare -- not passed through a
 *  formatting call such as formatByteSize(...) -- as a JSX *child* (a value in an attribute
 *  like `data-size-bytes={x}` is not user-facing prose and is left alone). This is a
 *  structural check on the expression itself, not a text scan, so it also catches the
 *  `{archive.cloud_bytes}` / `{archive.media_cloud_bytes}` cases where the "字节" unit sits
 *  in a sibling element's text rather than right next to the number. */
function findRawByteRenders(file: string, source: string): string[] {
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const hits: string[] = []
  const visit = (node: ts.Node): void => {
    if (
      ts.isJsxExpression(node) &&
      node.expression &&
      !ts.isJsxAttribute(node.parent) &&
      !ts.isCallExpression(node.expression) &&
      isByteCountExpression(node.expression)
    ) {
      hits.push(node.expression.getText(tree).trim())
    }
    ts.forEachChild(node, visit)
  }
  visit(tree)
  return hits
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
  if (file === resolve(ordinaryDirectory, 'ArchivesPage.tsx')) {
    assert.doesNotMatch(
      copy,
      ARCHIVES_INTERNAL_JARGON_PATTERN,
      `${file} must not expose internal artifact/descriptor/contract jargon to ordinary users`,
    )
  }
  const rawByteRenders = findRawByteRenders(file, source)
  assert.equal(
    rawByteRenders.length,
    0,
    `${file} must format byte counts for display (e.g. via formatByteSize) instead of rendering raw: ${rawByteRenders.join(', ')}`,
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

// ArchivesPage renders archive/artifact byte counts (e.g. 984233120 -> "939 MB") through this
// formatter instead of the raw integer; pin the exact reference case from that fix plus the
// always-0 media_cloud_bytes contract field, which formatByteSize must still show as a unit
// ("0 字节"), not a bare "0".
assert.equal(formatByteSize(984_233_120), '939 MB')
assert.equal(formatByteSize(18_422), '18 KB')
assert.equal(formatByteSize(0), '0 字节')
assert.equal(formatByteSize(-1), '大小待确认')

function runSelfTest(): void {
  const fixtureFile = resolve('src/media/pages/ordinary/__fixture__.tsx')

  // findRawByteRenders: red on the exact pre-fix ArchivesPage shapes, green once the same
  // value is wrapped in a formatting call, and unbothered by a non-prose attribute use.
  const rawByteRed1 = findRawByteRenders(fixtureFile, 'const X = () => <td>{archive.cloud_bytes}</td>')
  assert.deepEqual(rawByteRed1, ['archive.cloud_bytes'], 'self-test failed: bare {archive.cloud_bytes} child was not caught')

  const rawByteRed2 = findRawByteRenders(
    fixtureFile,
    'const X = () => <small>{archiveArtifactModeLabel(artifact.mode)} · {artifact.size_bytes} 字节</small>',
  )
  assert.deepEqual(rawByteRed2, ['artifact.size_bytes'], 'self-test failed: bare {artifact.size_bytes} next to a literal 字节 was not caught')

  const rawByteGreen1 = findRawByteRenders(fixtureFile, 'const X = () => <td>{formatByteSize(archive.cloud_bytes)}</td>')
  assert.deepEqual(rawByteGreen1, [], 'self-test failed: {formatByteSize(archive.cloud_bytes)} was rejected even though it is already formatted')

  const rawByteGreen2 = findRawByteRenders(fixtureFile, 'const X = () => <div data-size-bytes={artifact.size_bytes} />')
  assert.deepEqual(rawByteGreen2, [], 'self-test failed: a non-prose attribute value was flagged as if it were rendered copy')

  // ARCHIVES_INTERNAL_JARGON_PATTERN, run the same way the real check runs it: through
  // userFacingText first, so this also proves a code comment mentioning the same words does
  // not trip the gate (matches the existing 接口/事实/回读/投影 check's own guarantee).
  const jargonRed = userFacingText(fixtureFile, 'const X = () => <h3>小产物与本地描述符</h3>')
  assert.match(jargonRed, ARCHIVES_INTERNAL_JARGON_PATTERN, 'self-test failed: "小产物与本地描述符" was accepted')

  const jargonGreen = userFacingText(fixtureFile, 'const X = () => <h3>归档产物</h3>')
  assert.doesNotMatch(jargonGreen, ARCHIVES_INTERNAL_JARGON_PATTERN, 'self-test failed: plain "归档产物" copy was rejected')

  const jargonCommentOnly = userFacingText(fixtureFile, '// 小产物与本地描述符，只是解释这段做了什么\nconst X = () => <h3>归档产物</h3>')
  assert.doesNotMatch(jargonCommentOnly, ARCHIVES_INTERNAL_JARGON_PATTERN, 'self-test failed: a comment-only mention of the blacklisted words was scanned')

  console.log('media ordinary presentation self-test passed: raw byte renders and ArchivesPage jargon are caught; formatted/plain copy and comments are accepted')
}

if (process.argv.includes('--self-test')) runSelfTest()

console.log('media ordinary presentation contract passed')
