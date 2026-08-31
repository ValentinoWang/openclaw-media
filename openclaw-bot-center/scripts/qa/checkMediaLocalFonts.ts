import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const projectRoot = resolve(import.meta.dirname, '../..')
const mediaRoot = join(projectRoot, 'src/media')
const fontCssPath = join(mediaRoot, 'mediaFonts.css')
const fontDirectory = join(mediaRoot, 'fonts')
const tokenCssPath = join(mediaRoot, 'mediaDesignTokens.css')
const viteConfigPath = join(projectRoot, 'vite.media.config.ts')
const forbiddenFontHosts = /https?:\/\/fonts\.(?:googleapis|gstatic)\.com/iu

const htmlPaths = [
  'index.media.html',
  'media.login.html',
  'media.register.html',
  'src/media.verify.html',
  'src/media.recover.html',
  'src/media.reset.html',
]

function fontFaces(css: string): string[] {
  return css.match(/@font-face\s*\{[^}]*\}/gu) ?? []
}

function localFontSources(css: string): string[] {
  return [...css.matchAll(/url\(.*?\.\/fonts\/([^)'"\s]+\.woff2).*?\)/gu)].map((match) => match[1]!)
}

function assertLocalFontSources(css: string, root: string): void {
  const faces = fontFaces(css)
  const sources = localFontSources(css)

  assert.equal(faces.length, 103, 'DS-26 must retain the complete local DM Sans and Noto Sans SC declarations')
  assert.equal(sources.length, faces.length, 'each local font declaration must resolve to one WOFF2 asset')
  assert.ok(faces.some((face) => /font-family:\s*'DM Sans';[\s\S]*font-weight:\s*100 1000;[\s\S]*dm-sans-latin-opsz-normal/u.test(face)), 'DM Sans must provide its local variable Latin source')
  assert.ok(faces.some((face) => /font-family:\s*'Noto Sans SC';[\s\S]*font-weight:\s*100 900;[\s\S]*noto-sans-sc-119-wght-normal/u.test(face)), 'Noto Sans SC must provide its local variable subset sources')
  assert.ok(faces.every((face) => /font-display:\s*swap;/u.test(face)), 'local font declarations must preserve non-blocking rendering')

  for (const source of sources) {
    const fontPath = join(root, source)
    assert.ok(existsSync(fontPath), `missing local font asset: ${fontPath}`)
    assert.ok(statSync(fontPath).size > 0, `empty local font asset: ${fontPath}`)
  }
}

function assertNoGoogleFontDependency(files: Iterable<string>): void {
  for (const file of files) {
    assert.doesNotMatch(readFileSync(file, 'utf8'), forbiddenFontHosts, `Google Fonts dependency remains in ${file}`)
  }
}

function releaseTextFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = join(root, entry.name)
    if (entry.isDirectory()) return releaseTextFiles(entryPath)
    return /\.(?:css|html|js)$/u.test(entry.name) ? [entryPath] : []
  })
}

const fontCss = readFileSync(fontCssPath, 'utf8')
const tokenCss = readFileSync(tokenCssPath, 'utf8')
const viteConfig = readFileSync(viteConfigPath, 'utf8')

assertLocalFontSources(fontCss, fontDirectory)
assert.match(tokenCss, /^@import url\("\.\/mediaFonts\.css"\);/u, 'design tokens must import the local font declarations first')
assert.match(tokenCss, /--mg-font-sans:\s*'DM Sans', 'Noto Sans SC'/u, 'design tokens must retain the intended UI family order')
assert.match(viteConfig, /copyFileSync\(fontCssSource, resolve\(__dirname, 'dist-media\/mediaFonts\.css'\)\)/u, 'media build must publish the local font stylesheet')
assert.match(viteConfig, /cpSync\(fontDirectory, resolve\(__dirname, 'dist-media\/fonts'\), \{ recursive: true \}\)/u, 'media build must publish the local font assets')
assert.ok(existsSync(join(fontDirectory, 'README.md')), 'font provenance note is missing')
assert.ok(existsSync(join(fontDirectory, 'OFL-1.1.txt')), 'font license text is missing')

assertNoGoogleFontDependency([
  fontCssPath,
  tokenCssPath,
  join(projectRoot, 'src/media.auth.css'),
  ...htmlPaths.map((path) => join(projectRoot, path)),
])

if (process.argv.includes('--build')) {
  const releaseRoot = join(projectRoot, 'dist-media')
  const releaseFontCss = join(releaseRoot, 'mediaFonts.css')
  const releaseTokenCss = join(releaseRoot, 'mediaDesignTokens.css')
  assert.ok(existsSync(releaseFontCss), 'media release is missing mediaFonts.css')
  assert.ok(existsSync(releaseTokenCss), 'media release is missing mediaDesignTokens.css')
  assertLocalFontSources(readFileSync(releaseFontCss, 'utf8'), join(releaseRoot, 'fonts'))
  assert.match(readFileSync(releaseTokenCss, 'utf8'), /^@import url\("\.\/mediaFonts\.css"\);/u, 'release token stylesheet must retain local font import')
  assertNoGoogleFontDependency(releaseTextFiles(releaseRoot))
}

console.log(`media local font ${process.argv.includes('--build') ? 'build ' : ''}QA passed`)
