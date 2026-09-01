import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { ModuleKind, ScriptTarget, transpileModule } from 'typescript'

const decisionsSource = readFileSync(resolve('src/media/pages/ordinary/DecisionsPage.tsx'), 'utf8')
const runDetailSource = readFileSync(resolve('src/media/CreationRunDetailPage.tsx'), 'utf8')
const runsSource = readFileSync(resolve('src/media/pages/ordinary/RunsPage.tsx'), 'utf8')
const reviewsSource = readFileSync(resolve('src/media/pages/ordinary/ReviewsPage.tsx'), 'utf8')
const reviewsStyles = readFileSync(resolve('src/media/pages/ordinary/ReviewsPage.module.css'), 'utf8')
const ordinaryLabelsSource = readFileSync(resolve('src/media/ui/ordinaryDataLabels.ts'), 'utf8')
const registrySource = readFileSync(resolve('src/media/ui/platformRegistry.ts'), 'utf8')
const platformIconSource = readFileSync(resolve('src/media/ui/PlatformBrandIcon.tsx'), 'utf8')
const platformIdentitySource = readFileSync(resolve('src/media/ui/PlatformIdentity.tsx'), 'utf8')
const documentEditorSource = readFileSync(resolve('src/media/pages/ordinary/DocumentEditorPage.tsx'), 'utf8')
const documentEditorStyles = readFileSync(resolve('src/media/pages/ordinary/DocumentEditorPage.module.css'), 'utf8')
const documentWorkflowSource = readFileSync(resolve('src/media/documentWorkflow.ts'), 'utf8')
const stage2DocumentScreenshotSource = readFileSync(resolve('scripts/qa/captureStage2DocumentScreenshots.ts'), 'utf8')

assert.doesNotMatch(decisionsSource, /<small>\{item\.publicDecisionId\}<\/small>/)
assert.doesNotMatch(decisionsSource, /detail\?\.publicDecisionId\s*\?\?\s*summary\?\.publicDecisionId/)
assert.match(decisionsSource, /candidateTypeDisplayLabel\(item\.candidateType\)/)
assert.match(decisionsSource, /activity:\s*"现有平台活动"/)
assert.match(decisionsSource, /import \{ PlatformIdentity \} from "\.\.\/\.\.\/ui\/PlatformIdentity";/)
for (const expression of [
  '<PlatformIdentity platform={item.platform} size="sm" />',
  '<PlatformIdentity platform={signal.platform} size="sm" />',
  '<PlatformIdentity platform={detail.platform} size="sm" />',
]) {
  assert.ok(decisionsSource.includes(expression), `DecisionsPage is missing ${expression}`)
}
assert.doesNotMatch(decisionsSource, /PLATFORM_ICON_ASSETS|function PlatformIcon|\/platform-icons\/|<img\b/)

for (const contract of [
  'PLATFORM_REGISTRY',
  'BRANDED_PLATFORM_KEYS',
  'resolvePlatform',
  'platformDisplayLabel',
  'siTiktok',
  'siXiaohongshu',
  '"16.28.0"',
  '"CC0-1.0"',
]) {
  assert.ok(registrySource.includes(contract), `platform registry is missing ${contract}`)
}
assert.match(platformIdentitySource, /data-platform-identity=""/)
assert.match(platformIdentitySource, /<PlatformBrandIcon decorative/)
assert.match(platformIdentitySource, /data-platform-label=""/)
assert.match(platformIconSource, /data-platform-icon=""/)
assert.match(platformIconSource, /data-platform-icon-source=\{definition\.iconSource\.exportName\}/)
assert.match(platformIconSource, /<path d=\{icon\.path\} fill="currentColor" \/>/)
assert.doesNotMatch(ordinaryLabelsSource, /PLATFORM_LABELS|platformDisplayLabel/)

assert.match(documentEditorSource, /const blockLabel: Record<DocumentBlock\["type"\], string>/)
assert.match(documentEditorSource, /const revisionStateLabel: Record<DocumentRevisionRecord\["state"\], string>/)
assert.match(documentEditorSource, /const bodyAuthorityLabel: Record<DocumentRevisionRecord\["bodyAuthority"\], string>/)
assert.match(documentEditorSource, /\{bodyAuthorityLabel\[revision\.bodyAuthority\]\}/)
assert.doesNotMatch(documentEditorSource, /block\.type\.replace\(/)
assert.doesNotMatch(documentEditorSource, /\{(?:aiRevision|revision)\.state\}/)
assert.doesNotMatch(documentEditorSource, />\{block\.type\}</)
assert.doesNotMatch(documentEditorSource, /<dt>\{fieldName\}<\/dt>/)
assert.match(documentEditorSource, /snapshotWireValueLabel/)
for (const label of [
  'queued: "排队中"',
  'rendering: "正在处理"',
  'succeeded: "已完成"',
  'running: "处理中"',
  'pending: "等待处理"',
  'unknown: "待对账"',
  'partial: "部分完成"',
  'unavailable: "不可用"',
  'inline_code: "行内代码"',
  'link: "链接"',
]) {
  assert.ok(documentEditorSource.includes(label), `editor is missing wire label ${label}`)
}
assert.equal((documentEditorSource.match(/技术参考码：/g) ?? []).length, 1)
assert.match(documentEditorSource, /<TechnicalReference code=\{technicalCode\} \/>/)
const marksDeclaration = documentEditorSource.match(/const MARKS: readonly MarkName\[\] = \[([\s\S]*?)\];/)?.[1]
assert.ok(marksDeclaration, 'DocumentEditorPage contract marks declaration is missing')
assert.deepEqual(
  [...marksDeclaration.matchAll(/"([^"]+)"/g)].map((match) => match[1]),
  ['bold', 'italic', 'underline', 'strike', 'inline_code'],
  'the editor must keep exactly the five string marks; link remains the sixth object mark',
)
assert.match(documentEditorSource, /type: "link" as const/)
assert.match(documentEditorSource, /function isRichTextBlock\(/)
assert.match(documentEditorSource, /return isSafelyEditableBlock\(block\) \|\| isRichTextBlock\(block\)/)
assert.match(documentEditorSource, /function replaceInlineText\(/)
assert.match(documentEditorSource, /content: replaceInlineText\(block\.content, text\)/)
assert.match(documentEditorSource, /function toggleMarkInRange\(/)
assert.match(documentEditorSource, /content: toggleMarkInRange\(block\.content, range, mark\)/)
assert.match(documentEditorSource, /function applyLinkToRange\(/)
assert.match(documentEditorSource, /content: applyLinkToRange\(block\.content, range, href\)/)
assert.doesNotMatch(documentEditorSource, /block\.content\[0\]/)
assert.match(documentEditorSource, /const \[selectedRange, setSelectedRange\]/)
assert.match(documentEditorSource, /selectionStart/)
assert.match(documentEditorSource, /selectionEnd/)
assert.match(documentEditorSource, /disabled=\{!selectedRichTextBlock \|\| !selectedTextRange\}/)
assert.match(documentEditorSource, /const blockIds = status === 422 \? blockIdsFrom\(error\) : \[\]/)
assert.match(documentEditorSource, /status === 409 \|\| classifyDocumentFailure\(error\)\.kind === "conflict"/)
assert.match(documentEditorSource, /isProtectedSnapshot\(block\)/)
for (const operationId of [
  'getDocumentBody',
  'getDocumentRevision',
  'saveDocumentDraft',
  'createDocumentExport',
  'getDocumentExportDownload',
]) {
  assert.ok(documentWorkflowSource.includes(operationId), `document workflow lost operation ID ${operationId}`)
}
assert.ok(documentEditorSource.includes('createArtifactRevision'), 'DocumentEditorPage lost operation ID createArtifactRevision')
for (const apiMethod of ['api.getBody(', 'api.saveDraft(', 'api.getRevision(', 'api.createExport(', 'api.getExportDownload(']) {
  assert.ok(documentEditorSource.includes(apiMethod), `DocumentEditorPage lost API method ${apiMethod}`)
}
for (const label of ['写入正文', '登记保存回执', '读回正文并核对版本']) {
  assert.ok(documentEditorSource.includes(label), `DocumentEditorPage is missing save-readback label: ${label}`)
}
assert.match(documentEditorSource, /const PERSONAL_DOCUMENT_AI_FEATURE_ENABLED\s*=\s*import\.meta\.env\.VITE_MEDIA_PERSONAL_DOCUMENT_AI_ENABLED !== "false"/)
assert.match(documentEditorSource, /api\.getRevision\(artifactId, saved\.revision\)/)
assert.match(documentEditorSource, /readback\.revision === saved\.revision/)
assert.match(documentEditorSource, /readback\.bodyChecksum === saved\.bodyChecksum/)
assert.match(documentEditorSource, /JSON\.stringify\(readback\.body\) === JSON\.stringify\(saved\.body\)/)
assert.match(documentEditorSource, /setPendingSaveReadback\(response\.data\)/)
assert.match(documentEditorSource, /pendingSaveReadback \? "重新读取正文" : "重试保存"/)
assert.match(documentEditorSource, /SaveReadbackVerificationError/)
assert.match(documentEditorSource, /aiStatus === "timedOut"/)
assert.match(documentEditorSource, /重新读取改稿结果/)
for (const label of ['已应用', '需要人工处理', '受保护未改动']) {
  assert.ok(documentEditorSource.includes(label), `DocumentEditorPage is missing AI receipt label: ${label}`)
}
assert.match(documentEditorSource, /不代表服务端完整修订历史/)
assert.match(stage2DocumentScreenshotSource, /savedDraft: ReturnType<typeof documentRevision> \| null/)
assert.match(stage2DocumentScreenshotSource, /mock\.savedDraft = savedRevision/)
assert.match(stage2DocumentScreenshotSource, /mock\.savedDraft\?\.revision === requestedRevision/)
assert.match(documentEditorSource, /\/workspace\/preview\/\$\{artifactId\}/)
assert.match(documentEditorStyles, /\.toolbar button:disabled/)

const helperStart = documentEditorSource.indexOf('function isMark(')
const helperEnd = documentEditorSource.indexOf('function editorFailureMessage(')
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'editor inline transform helpers are missing')
const helperSource = documentEditorSource.slice(helperStart, helperEnd)
const helperModule = { exports: {} as Record<string, unknown> }
const helperProgram = transpileModule(
  `${helperSource}
module.exports = { replaceInlineText, toggleMarkInRange, applyLinkToRange }`,
  { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } },
).outputText
new Function('module', 'exports', helperProgram)(helperModule, helperModule.exports)
type TestRun = { type: 'text'; text: string; marks: unknown[] }
const transforms = helperModule.exports as unknown as {
  replaceInlineText: (runs: TestRun[], text: string) => TestRun[]
  toggleMarkInRange: (runs: TestRun[], range: { start: number; end: number }, mark: string) => TestRun[]
  applyLinkToRange: (runs: TestRun[], range: { start: number; end: number }, href: string) => TestRun[]
}
const multiRun: TestRun[] = [
  { type: 'text', text: 'alpha', marks: ['bold'] },
  { type: 'text', text: ' beta', marks: ['italic'] },
  { type: 'text', text: ' gamma', marks: [{ type: 'link', href: 'https://old.example', title: null }] },
]
const inlineText = (runs: TestRun[]): string => runs.map((run) => run.text).join('')
const marked = transforms.toggleMarkInRange(multiRun, { start: 2, end: 8 }, 'underline')
assert.equal(inlineText(marked), inlineText(multiRun), 'marking a range must preserve all run text')
assert.deepEqual(marked.map((run) => run.text), ['al', 'pha', ' be', 'ta', ' gamma'])
assert.deepEqual(marked.map((run) => run.marks), [
  ['bold'],
  ['bold', 'underline'],
  ['italic', 'underline'],
  ['italic'],
  [{ type: 'link', href: 'https://old.example', title: null }],
])
const linked = transforms.applyLinkToRange(multiRun, { start: 11, end: 13 }, 'https://new.example')
assert.equal(inlineText(linked), inlineText(multiRun), 'linking a range must preserve all run text')
assert.deepEqual(linked.map((run) => run.text), ['alpha', ' beta', ' ', 'ga', 'mma'])
assert.deepEqual(linked[2]?.marks, [{ type: 'link', href: 'https://old.example', title: null }])
assert.deepEqual(linked[3]?.marks, [{ type: 'link', href: 'https://new.example', title: null }])
assert.deepEqual(linked[4]?.marks, [{ type: 'link', href: 'https://old.example', title: null }])
const edited = transforms.replaceInlineText(multiRun, 'alXpha beta gamma')
assert.equal(inlineText(edited), 'alXpha beta gamma', 'text editing must preserve the flattened value')
assert.deepEqual(edited.map((run) => run.text), ['al', 'X', 'pha', ' beta', ' gamma'])
assert.deepEqual(edited.map((run) => run.marks), [
  ['bold'],
  ['bold'],
  ['bold'],
  ['italic'],
  [{ type: 'link', href: 'https://old.example', title: null }],
])
const conflictBanner = documentEditorSource.match(/\{saveState === "conflict" \? \([\s\S]*?\) : null\}/)?.[0]
assert.ok(conflictBanner, 'DocumentEditorPage conflict banner is missing')
assert.match(conflictBanner, /逐段对比并合并/)
assert.match(conflictBanner, /disabled/)
assert.match(conflictBanner, /保留为本地副本/)
assert.match(conflictBanner, /放弃本地修改并载入最新正文/)
assert.match(conflictBanner, /服务端尚未提供可对比的冲突差异/)

assert.match(runDetailSource, /<h1>\{run\.title\}<\/h1>/)
assert.match(runDetailSource, /<section className=\{[^>]*summaryBand[^>]*mg-panel[^>]*\}[^>]*aria-label="运行摘要">/)
for (const label of ['运行状态', '创作入口', '发布平台', '内容形态']) {
  assert.match(runDetailSource, new RegExp(`label: '${label}'`))
}
assert.match(runDetailSource, /<dl className=\{styles\.metadataList\}>/)
for (const label of ['关联项目', '内容赛道', '运行修订', '创建时间', '更新时间']) {
  assert.match(runDetailSource, new RegExp(`label="${label}"`))
}
for (const [key, label] of [['public_run_id', '公开运行编号'], ['available_sections', '可用分区'], ['response_revision', '响应修订']]) {
  assert.match(runDetailSource, new RegExp(`${key}: '${label}'`))
}

assert.doesNotMatch(runDetailSource, /function humanize\(/)
assert.match(runDetailSource, /<PlatformIdentity platform=\{run\.platform\} size="sm" \/>/)
assert.match(runDetailSource, /mediaTypeDisplayLabel\(run\.contentType\)/)

for (const label of ['平台', '内容类型', '赛道']) {
  assert.match(runsSource, new RegExp(`<th scope="col">${label}</th>`))
}
for (const [label, expression] of [
  ['发布平台', '<PlatformValue key="platform" platform={run.platform} />'],
  ['内容形态', 'run.contentType ? mediaTypeDisplayLabel(run.contentType) : "未记录"'],
  ['内容赛道', 'displayMetadata(run.trackName)'],
]) {
  assert.ok(runsSource.includes(`["${label}", ${expression}]`))
}
for (const field of ['platform', 'contentType', 'trackName']) {
  assert.ok(runsSource.includes(`run.${field}`))
}

assert.match(reviewsSource, /postTitle:\s*string \| null;/)
assert.ok(reviewsSource.includes('documentUrl: string | null;'))
assert.match(reviewsSource, /ExternalLink/)
const reviewRowCell = reviewsSource.match(/<th scope="row">([\s\S]*?)<\/th>/)?.[1]
assert.ok(reviewRowCell, 'ReviewsPage review title cell is missing')
assert.match(reviewRowCell, /<a[\s\S]*href=\{item\.documentUrl\}[\s\S]*target="_blank"[\s\S]*rel="noopener noreferrer"[\s\S]*title="在飞书中打开复盘文档"[\s\S]*aria-label="在飞书中打开复盘文档"/)
assert.match(reviewRowCell, /<ExternalLink[\s\S]*aria-hidden="true"/)
const reviewSelectionButton = reviewRowCell.match(/<button className=\{styles\.rowLink\}[\s\S]*?<\/button>/)?.[0]
assert.ok(reviewSelectionButton, 'ReviewsPage selection button is missing')
assert.doesNotMatch(reviewSelectionButton, /<a\b/)
assert.match(reviewsSource, /function reviewPostTitle\(item: ReviewItem\): string/)
assert.match(reviewsSource, /reviewPostTitle\(item\)/)
assert.doesNotMatch(reviewsSource, />\{item\.publicPostId\}<\/button>/)
const rowLinkRule = reviewsStyles.match(/\.rowLink\s*\{([^}]*)\}/s)?.[1]
assert.ok(rowLinkRule, 'ReviewsPage rowLink rule is missing')
assert.doesNotMatch(rowLinkRule, /overflow-wrap:\s*anywhere/)
assert.match(reviewsStyles, /\.postId\s*\{[^}]*white-space:\s*nowrap;/s)

console.log('media readable fields contract passed')
