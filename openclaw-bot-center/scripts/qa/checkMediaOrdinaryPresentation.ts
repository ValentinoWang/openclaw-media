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
// 七件事实一件都不能丢，但它们**不必各占一列**：三件短事实并进标题下方那一行之后，
// 表格从 7 列收到 4 列，1180px 下 49% 的横滚（qa:media-layout-sanity 的「大半张表
// 藏在横滚里」）因此归零。所以判据从「数够七个 th」改成「七件事实每一件都还带着
// 自己的名字」——留在表格里的仍有列头，离开列的必须以「标签 + 值」出现，不能只剩
// 一个没有名字的值让读屏用户猜。
const DECISION_COLUMN_FACTS = ['候选选题', '平台', '状态', '更新时间']
const DECISION_FOLDED_FACTS = ['类型', '赛道', '证据']
for (const name of DECISION_COLUMN_FACTS) {
  assert.match(
    decisionsSource,
    new RegExp(`<th scope="col">${name}</th>`),
    `DecisionsPage must keep the ${name} column header for assistive technology`,
  )
}
for (const name of DECISION_FOLDED_FACTS) {
  assert.match(
    decisionsSource,
    new RegExp(`label:\\s*["']${name}["']`),
    `DecisionsPage folded the ${name} fact out of its own column, so it must carry its own label beside the value`,
  )
}
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

  // 标签函数兜底泄露的红/绿用例
  assert.equal(
    findRawEnumFallbacks("function planStatus(status){ if(status==='active') return '生效中'; return status }").length,
    1, 'self-test failed: 原样兜底没有被抓到')
  assert.equal(
    findRawEnumFallbacks("function planStatus(status){ if(status==='active') return {label:'生效中'}; return {label: status} }").length,
    1, 'self-test failed: 对象里的原样兜底没有被抓到')
  assert.deepEqual(
    findRawEnumFallbacks("function planStatus(status){ if(status==='active') return '生效中'; return '未知状态' }"),
    [], 'self-test failed: 中文兜底被误判')
  assert.deepEqual(
    findRawEnumFallbacks('function slug(value){ return value }'),
    [], 'self-test failed: 不是标签函数的透传被误判')

  // 原始枚举渲染的红/绿用例
  assert.equal(findRawEnumRenders('const X = ({ i }) => <dd>{i.status}</dd>').length, 1, 'self-test failed: 裸枚举没有被抓到')
  assert.equal(findRawEnumRenders('const X = ({ i }) => <dd>{i.registrationPolicyMode}</dd>').length, 1, 'self-test failed: 裸的 policy mode 没有被抓到')
  assert.deepEqual(findRawEnumRenders('const X = ({ i }) => <dd>{statusLabel(i.status)}</dd>'), [], 'self-test failed: 经过函数的枚举被误判')
  assert.deepEqual(findRawEnumRenders('const X = ({ i }) => <dd>{LABELS[i.status]}</dd>'), [], 'self-test failed: 查表的枚举被误判')
  assert.deepEqual(findRawEnumRenders("const X = ({ i }) => <dd>{i.status === 'ok' ? '正常' : '异常'}</dd>"), [], 'self-test failed: 三元翻译被误判')
  assert.deepEqual(findRawEnumRenders('const X = ({ i }) => <dd data-tone={i.status}>正常</dd>'), [], 'self-test failed: 属性位置的原始值被误判')
  assert.equal(findRawEnumRenders("const X = ({ i }) => <h2>{i.artifactKind || '个人成果'}</h2>").length,
    1, 'self-test failed: || 兜底掩护下的裸枚举没有被抓到')
  assert.deepEqual(findRawEnumRenders("const X = ({ i }) => <h2>{i.displayName || '未命名'}</h2>"),
    [], 'self-test failed: 不是枚举的字段被误判')

  // 查表不中渲染成空白的红/绿用例
  assert.equal(findUnguardedLabelLookups('const X = ({ i }) => <dd>{ACTION_STATUS_LABELS[i.status]}</dd>').length,
    1, 'self-test failed: 没有兜底的查表没有被抓到')
  assert.deepEqual(findUnguardedLabelLookups("const X = ({ i }) => <dd>{ACTION_STATUS_LABELS[i.status] ?? '未知状态'}</dd>"),
    [], 'self-test failed: 带 ?? 兜底的查表被误判')
  assert.deepEqual(findUnguardedLabelLookups("const X = ({ i }) => <dd>{ACTION_STATUS_LABELS[i.status] || '未知状态'}</dd>"),
    [], 'self-test failed: 带 || 兜底的查表被误判')
  assert.deepEqual(findUnguardedLabelLookups('const X = ({ rows }) => <dd>{rows[0]}</dd>'),
    [], 'self-test failed: 普通下标访问被误判')
  assert.deepEqual(findUnguardedLabelLookups('const X = ({ state }) => { const s = state; return <dd>{syncStateLabels[s]}</dd> }'),
    [], 'self-test failed: 下标是页面自己算出来的局部变量，被误判')

  console.log('media ordinary presentation self-test passed: raw byte renders and ArchivesPage jargon are caught; formatted/plain copy and comments are accepted')
}

/** 原始枚举被当成人读的值直接渲染出去。
 *
 *  用户在真实环境里看到过「注册策略复核：controlled」——`controlled` 是后端的枚举
 *  字面量，不是给人读的。这一类**渲染门禁永远抓不到**：演示种子里放的是完整中文
 *  句子，浏览器里根本看不到那个词。只能从源码查。
 *
 *  判据：JSX 的**可见文本位置**上直接放了一个名字以 status / state / mode / policy /
 *  kind / type / tier / level / role / authority / source 结尾的属性访问，而且没有经过
 *  任何一层转换。经过就放行——
 *    {runStatusLabel(item.status)}      函数调用
 *    {STATUS_LABELS[item.status]}       查表
 *    {item.status === 'ok' ? '正常' : '异常'}   三元
 *  这三种都是「有人负责把它翻成中文」的形态。裸 {item.status} 没有。
 *
 *  只看可见文本位置：`data-tone={item.status}`、`aria-*`、`key=` 这些属性照旧，
 *  它们本来就该用原始值。 */
const ENUM_SUFFIX_PATTERN = /(status|state|mode|policy|kind|type|tier|level|role|authority|source)$/i

export function findRawEnumRenders(sourceText: string, fileName = 'fixture.tsx'): readonly string[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const violations: string[] = []
  const visit = (node: ts.Node): void => {
    // 只有作为 JSX 子节点出现时才是可见文本位置；作为属性值时 parent 是 JsxAttribute。
    if (ts.isJsxExpression(node) && node.expression && node.parent && !ts.isJsxAttribute(node.parent)) {
      // `{item.kind || '个人成果'}` 也算裸渲染：`||` / `??` 只兜住了空值，兜不住
      // 「后端发来一个我们没登记的取值」——那时用户看到的仍然是那个英文串。
      // /workspace/preview 的 <h2> 就这样把 creation_document 顶到了标题位置。
      const inner =
        ts.isBinaryExpression(node.expression) &&
        (node.expression.operatorToken.kind === ts.SyntaxKind.BarBarToken ||
          node.expression.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken)
          ? node.expression.left
          : node.expression
      if (ts.isPropertyAccessExpression(inner) && ENUM_SUFFIX_PATTERN.test(inner.name.text)) {
        const { line } = source.getLineAndCharacterOfPosition(inner.getStart(source))
        violations.push(`${fileName}:${line + 1} 直接渲染了 ${inner.getText(source)}——原始枚举不是给人读的，套一层中文标签映射（函数、查表或三元都行），并且给未知取值一个兜底`)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return violations
}

/** 查表不中，渲染成一片空白。
 *
 *  `{ACTION_STATUS_LABELS[action.status]}` 看着比裸渲染枚举讲究，其实更糟：后端多一个
 *  没登记的取值，查表返回 `undefined`，React 什么也不渲染——用户看到的是一个**空格子**，
 *  比看到一个英文单词更难判断「是没加载出来还是本来就没有」。演示种子只放已登记的键，
 *  所以浏览器里永远看不到。
 *
 *  判据：JSX 的可见文本位置上，直接放了一个「标签表」下标访问且没有兜底，**而且下标是
 *  一个属性访问**（`action.status`、`summary.credentialHealth`）——也就是取值来自后端。
 *  下标是普通局部变量的（`syncStateLabels[currentSyncState]`）不算：那种取值是页面自己
 *  在有限几个分支里算出来的，TypeScript 的穷尽性是真的。标签表按名字认：全大写下划线
 *  （ACTION_STATUS_LABELS）或以 Labels 结尾。带 `??` / `||` 的整体是二元表达式，不会
 *  命中；`rows[0]` 这种普通下标也不会。 */
const LABEL_MAP_PATTERN = /^[A-Z][A-Z0-9_]*$|Labels$/

export function findUnguardedLabelLookups(sourceText: string, fileName = 'fixture.tsx'): readonly string[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const violations: string[] = []
  const visit = (node: ts.Node): void => {
    if (ts.isJsxExpression(node) && node.expression && node.parent && !ts.isJsxAttribute(node.parent)) {
      const inner = node.expression
      if (
        ts.isElementAccessExpression(inner) &&
        ts.isIdentifier(inner.expression) &&
        LABEL_MAP_PATTERN.test(inner.expression.text) &&
        inner.argumentExpression !== undefined &&
        ts.isPropertyAccessExpression(inner.argumentExpression)
      ) {
        const { line } = source.getLineAndCharacterOfPosition(inner.getStart(source))
        violations.push(`${fileName}:${line + 1} ${inner.getText(source)} 查表不中会渲染成空白——给它一个中文兜底（?? 或 ||），别让用户对着一个空格子猜是不是没加载出来`)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return violations
}

/** 标签函数拿原始值兜底。
 *
 *  真实环境里用户看到过「注册策略复核：controlled」。源码里并没有裸渲染
 *  `{x.mode}`——泄露发生在**标签函数的兜底分支**：一串 if 把已知取值翻成中文，
 *  最后 `return status` 把没覆盖到的原样吐出去。后端加一个新枚举值，用户就看到
 *  一个英文单词。演示种子只放已知取值，所以渲染门禁永远看不到。
 *
 *  判据：一个函数**明显是标签映射**（函数体里出现过中文字符串字面量），却存在
 *  `return <它自己的入参>` 这样的语句。兜底应该给一个中文的「未知」，而不是原始值。 */
export function findRawEnumFallbacks(sourceText: string, fileName = 'fixture.tsx'): readonly string[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const violations: string[] = []
  const inspect = (fn: ts.FunctionDeclaration | ts.ArrowFunction | ts.FunctionExpression, name: string): void => {
    const body = fn.body
    if (!body || !ts.isBlock(body)) return
    // 只认名字本身就是枚举的入参。`formatRelativeTime(value)` 透传格式化好的时间、
    // `guardedRoute(pathname, element, policy)` 透传 ReactNode、`toReadError(message)`
    // 透传服务端消息——这些原样返回都是对的，收紧之前它们全是假阳性。
    const parameterNames = new Set(
      fn.parameters
        .map((parameter) => (ts.isIdentifier(parameter.name) ? parameter.name.text : ''))
        .filter((name) => name.length > 0 && ENUM_SUFFIX_PATTERN.test(name)),
    )
    if (parameterNames.size === 0) return
    let hasChineseLabel = false
    let leak: ts.Node | null = null
    const walk = (node: ts.Node): void => {
      if (ts.isStringLiteral(node) && /[一-鿿]/.test(node.text)) hasChineseLabel = true
      if (ts.isReturnStatement(node) && node.expression) {
        const returned = node.expression
        if (ts.isIdentifier(returned) && parameterNames.has(returned.text)) leak = returned
        if (ts.isObjectLiteralExpression(returned)) {
          for (const property of returned.properties) {
            if (!ts.isPropertyAssignment(property)) continue
            const key = property.name.getText(source)
            if (key !== 'label' && key !== 'text') continue
            const value = property.initializer
            if (ts.isIdentifier(value) && parameterNames.has(value.text)) leak = value
          }
        }
      }
      ts.forEachChild(node, walk)
    }
    walk(body)
    if (!hasChineseLabel || !leak) return
    const { line } = source.getLineAndCharacterOfPosition((leak as ts.Node).getStart(source))
    violations.push(`${fileName}:${line + 1} ${name} 把原始取值当兜底返回——后端多一个枚举值，用户就会看到一个英文单词（真实环境里出现过「注册策略复核：controlled」）。兜底要给中文的「未知」之类，别把原始值吐出去`)
  }
  const visit = (node: ts.Node): void => {
    if (ts.isFunctionDeclaration(node) && node.name) inspect(node, node.name.text)
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const initializer = node.initializer
      if (ts.isArrowFunction(initializer) || ts.isFunctionExpression(initializer)) inspect(initializer, node.name.text)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return violations
}

if (process.argv.includes('--self-test')) runSelfTest()

/** 扫全部 Media 页面（普通页 + 管理员页 + studio 页），不只是 ordinary 目录：
 *  用户看到的那处泄露就在管理员页上。 */
const enumScanDirectories = [
  resolve('src/media/pages/ordinary'),
  resolve('src/media/pages/admin'),
  resolve('src/media/studio'),
  resolve('src/media'),
]
const enumScanFiles = [
  ...new Set(
    enumScanDirectories.flatMap((directory) =>
      existsSync(directory)
        ? readdirSync(directory)
            .filter((name) => name.endsWith('.tsx'))
            .map((name) => resolve(directory, name))
        : [],
    ),
  ),
]
const enumLeaks = enumScanFiles.flatMap((fileName) => {
  const relativeName = fileName.replace(resolve('.') + '/', '')
  const contents = readFileSync(fileName, 'utf8')
  return [...findRawEnumRenders(contents, relativeName), ...findRawEnumFallbacks(contents, relativeName), ...findUnguardedLabelLookups(contents, relativeName)]
})
assert.deepEqual(enumLeaks, [], `原始枚举被当成人读的值渲染出去：\n- ${enumLeaks.join('\n- ')}`)

console.log('media ordinary presentation contract passed')
