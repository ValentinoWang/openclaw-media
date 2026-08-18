import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const releaseRoot = 'dist-media'

function releaseFiles(root: string, relativeRoot = ''): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const relativePath = join(relativeRoot, entry.name)
    const absolutePath = join(root, entry.name)
    return entry.isDirectory() ? releaseFiles(absolutePath, relativePath) : [relativePath]
  })
}

const files = releaseFiles(releaseRoot)
const text = files
  .filter((file) => /\.(?:css|html|js|json|txt)$/.test(file))
  .map((file) => readFileSync(join(releaseRoot, file), 'utf8'))
  .join('\n')

if (!text.includes('用量与余额')) {
  throw new Error('Media release is missing the current billing label')
}
if (text.includes('用量与套餐')) {
  throw new Error('Media release still contains the retired billing label')
}

assert.equal(
  files.some((file) => /(^|[/\\])platform-icons([/\\]|$)/.test(file)),
  false,
  'Media release must not contain the retired platform-icons directory',
)
assert.doesNotMatch(text, /platform-icons\/(?:douyin|xiaohongshu)\.png/)
for (const marker of [
  'data-platform-identity',
  'data-platform-icon',
  'data-platform-key',
  'data-platform-icon-source',
  'siTiktok',
  'siXiaohongshu',
  'siKuaishou',
  'siBilibili',
  'siWechat',
  'siSinaweibo',
  'siZhihu',
]) {
  assert.ok(text.includes(marker), `Media release is missing platform registry marker ${marker}`)
}
assert.doesNotMatch(text, /https?:\\?\/\\?\/(?:[^\s"']*\.)?(?:iconify|simpleicons|simple-icons)\./i)

console.log('media release label QA passed')
