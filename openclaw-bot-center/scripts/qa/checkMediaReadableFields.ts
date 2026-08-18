import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const decisionsSource = readFileSync(resolve('src/media/pages/ordinary/DecisionsPage.tsx'), 'utf8')
const runDetailSource = readFileSync(resolve('src/media/CreationRunDetailPage.tsx'), 'utf8')
const runsSource = readFileSync(resolve('src/media/pages/ordinary/RunsPage.tsx'), 'utf8')
const reviewsSource = readFileSync(resolve('src/media/pages/ordinary/ReviewsPage.tsx'), 'utf8')
const reviewsStyles = readFileSync(resolve('src/media/pages/ordinary/ReviewsPage.module.css'), 'utf8')
const ordinaryLabelsSource = readFileSync(resolve('src/media/ui/ordinaryDataLabels.ts'), 'utf8')
const registrySource = readFileSync(resolve('src/media/ui/platformRegistry.ts'), 'utf8')
const platformIconSource = readFileSync(resolve('src/media/ui/PlatformBrandIcon.tsx'), 'utf8')
const platformIdentitySource = readFileSync(resolve('src/media/ui/PlatformIdentity.tsx'), 'utf8')

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

assert.match(runDetailSource, /<h1>\{run\.title\}<\/h1>/)
assert.match(runDetailSource, /<section className=\{styles\.summaryBand\} aria-label="运行摘要">/)
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
  assert.ok(runsSource.includes(`detail.run.${field}`))
}

assert.match(reviewsSource, /postTitle:\s*string \| null;/)
assert.match(reviewsSource, /documentUrl:\s*string \| null;/)
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
