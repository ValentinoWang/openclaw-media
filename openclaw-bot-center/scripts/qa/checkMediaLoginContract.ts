import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const AUTH_HTML_ALIASES = [
  'media.login.html',
  'media.register.html',
  'media.verify.html',
  'media.recover.html',
  'media.reset.html',
  'src/media.verify.html',
  'src/media.recover.html',
  'src/media.reset.html',
] as const

const AUTH_STYLESHEET_LINK_RE = /<link\b[^>]*\bhref=(['"])\/media\.auth\.css\1[^>]*>/gu

function assertIgnoredAuthStylesheetLink(fileName: string, source: string): void {
  const links = [...source.matchAll(AUTH_STYLESHEET_LINK_RE)]
  assert.equal(links.length, 1, `${fileName} must contain exactly one auth stylesheet link`)
  const linkIndex = links[0]?.index ?? -1
  assert.ok(linkIndex >= 0, `${fileName} auth stylesheet link index is missing`)
  const beforeLink = source.slice(0, linkIndex)
  assert.match(beforeLink, /<!--\s*vite-ignore\s*-->\s*$/u, `${fileName} auth stylesheet link must use vite-ignore`)
}

function functionSection(source: string, start: string, end: string): string {
  const startIndex = source.indexOf(start)
  assert.ok(startIndex >= 0, `missing ${start}`)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.ok(endIndex >= 0, `missing ${end}`)
  return source.slice(startIndex, endIndex)
}

function assertRootTokenValues(tokenCss: string): void {
  const root = tokenCss.match(/:root\s*\{([\s\S]*?)\n\}/u)?.[1]
  assert.ok(root, 'media design token :root block is missing')
  for (const [name, value] of Object.entries({
    '--mg-primary': '#1a9b68',
    '--mg-primary-dark': '#10684a',
    '--mg-danger': '#b42318',
  })) {
    assert.match(root, new RegExp(`${name}:\\s*${value};`, 'u'), `${name} must keep the approved DS-01 value ${value}`)
  }
}

function assertBoundedRequests(script: string): void {
  const timeout = functionSection(script, 'async function fetchWithTimeout', 'async function postJson')
  assert.match(timeout, /new AbortController\(\)/u)
  assert.match(timeout, /controller\.abort\(\)/u)
  assert.match(timeout, /AUTH_REQUEST_TIMEOUT_MS/u)
  assert.match(timeout, /signal:\s*controller\.signal/u)
  assert.match(timeout, /clearTimeout\(timeout\)/u)

  const post = functionSection(script, 'async function postJson', 'function errorCode')
  assert.match(post, /fetchWithTimeout\(/u, 'postJson must use the bounded request helper')

  const session = functionSection(script, 'async function roleLanding', 'function parseLoginStart')
  assert.match(session, /fetchWithTimeout\(/u, 'roleLanding session read must be bounded')
}

function assertOrganizationAuthorizationLock(script: string): void {
  const organization = functionSection(script, 'async function startOrganizationAuth', 'function credentialError')
  assert.match(organization, /if \(organizationAuthInFlight\) return organizationAuthInFlight/u)
  assert.match(organization, /const run = \+\+organizationRun/u)
  assert.match(organization, /if \(run !== organizationRun\) return/u)
  assert.match(organization, /organizationAuthInFlight = task/u)
  assert.match(script, /function setOrganizationAuthBusy\(busy\)/u)
  assert.match(script, /organization-entry-fallback[\s\S]*?disabled = busy/u)
}

function assertOrganizationAuthorizationErrors(script: string): void {
  const organization = functionSection(script, 'async function startOrganizationAuth', 'function credentialError')
  assert.match(script, /class AuthRequestError extends Error/u)
  assert.match(script, /this\.code = code/u)
  assert.match(script, /this\.status = status/u)
  assert.match(organization, /if \(!response\.ok\) throw organizationAuthResponseError\(response, payload\)/u)
  assert.match(script, /errorCode\(payload\) \|\| fallbackCode/u)
  assert.match(script, /errorMessage\(payload\) \|\|/u)
  assert.match(script, /new AuthRequestError\([\s\S]*?response\.status/u)
  assert.match(organization, /caught instanceof AuthRequestError/u)
  assert.match(organization, /dataset\.errorCode = caught\.code/u)
  assert.match(organization, /dataset\.errorStatus = String\(caught\.status\)/u)
  assert.match(organization, /caught instanceof Error \? caught\.message/u)
}

function assertAuthTokenBuildWiring(css: string, viteConfig: string): void {
  assert.match(css, /^@import url\("\/mediaDesignTokens\.css"\);/u)
  assert.match(
    viteConfig,
    /['"]\/mediaDesignTokens\.css['"]:\s*resolve\(__dirname,\s*['"]src\/media\/mediaDesignTokens\.css['"]\)/u,
    'Vite must resolve the deployed root token URL to its source file',
  )
  assert.match(viteConfig, /copyFileSync\(authCssSource, resolve\(__dirname, 'dist-media\/media\.auth\.css'\)\)/u)
  assert.match(viteConfig, /copyFileSync\(tokenCssSource, resolve\(__dirname, 'dist-media\/mediaDesignTokens\.css'\)\)/u)
}

function runSelfTest(html: string, tokenCss: string, script: string, css: string, viteConfig: string): void {
  const oldUnignoredLink = html.replace(/<!--\s*vite-ignore\s*-->\s*/u, '')
  assert.throws(
    () => assertIgnoredAuthStylesheetLink('old-unignored-fixture.html', oldUnignoredLink),
    /vite-ignore/u,
    'self-test must reject an old unignored auth stylesheet link',
  )

  const wrongToken = tokenCss.replace('--mg-primary:       #1a9b68;', '--mg-primary:       #239b69;')
  assert.throws(
    () => assertRootTokenValues(wrongToken),
    /DS-01|mg-primary/u,
    'self-test must reject a wrong DS-01 token value',
  )

  const unboundedPost = script.replace('return fetchWithTimeout(path, {', 'return fetch(path, {')
  assert.throws(
    () => assertBoundedRequests(unboundedPost),
    /bounded request helper/u,
    'self-test must reject an unbounded postJson implementation',
  )

  const missingDedup = script.replace('if (organizationAuthInFlight) return organizationAuthInFlight', 'if (false) return organizationAuthInFlight')
  assert.throws(
    () => assertOrganizationAuthorizationLock(missingDedup),
    /organizationAuthInFlight/u,
    'self-test must reject missing authorization deduplication',
  )

  const missingErrorStatus = script.replace('this.status = status', 'this.status = 0')
  assert.throws(
    () => assertOrganizationAuthorizationErrors(missingErrorStatus),
    /status/u,
    'self-test must reject dropping the Feishu response status',
  )

  const missingErrorMessage = script.replace('caught instanceof Error ? caught.message', "caught instanceof Error ? '组织授权暂时不可用。'")
  assert.throws(
    () => assertOrganizationAuthorizationErrors(missingErrorMessage),
    /caught\.message/u,
    'self-test must reject dropping the Feishu response message',
  )

  const missingTokenAlias = viteConfig.replace("'/mediaDesignTokens.css':", "'/missing-mediaDesignTokens.css':")
  assert.throws(
    () => assertAuthTokenBuildWiring(css, missingTokenAlias),
    /root token URL/u,
    'self-test must reject a Vite config that cannot build the deployed token import',
  )
}

const authHtml = new Map(AUTH_HTML_ALIASES.map((fileName) => [fileName, readFileSync(fileName, 'utf8')]))
const html = authHtml.get('media.login.html')!
const script = readFileSync('media.login.js', 'utf8')
const css = readFileSync('src/media.auth.css', 'utf8')
const authCssAlias = readFileSync('media.auth.css', 'utf8')
const tokenCss = readFileSync('src/media/mediaDesignTokens.css', 'utf8')
const viteConfig = readFileSync('vite.media.config.ts', 'utf8')

for (const [fileName, source] of authHtml) assertIgnoredAuthStylesheetLink(fileName, source)
assert.equal(authCssAlias, css, 'auth stylesheet aliases must remain byte-identical')
assertAuthTokenBuildWiring(css, viteConfig)
assertRootTokenValues(tokenCss)

if (!html.includes('src="/media.login.js"')) throw new Error('media login module is missing')
if (/role\s*===\s*['"]user['"]/u.test(script)) throw new Error('media login still reads a retired session field')

assert.match(script, /import QRCode from 'qrcode'/u)
assert.match(script, /QRCode\.toCanvas\(qrCanvas, started\.authorizationUrl/u)
assert.match(script, /\/openclaw\/media\/auth\/feishu\/start/u)
assert.doesNotMatch(script, /\/openclaw\/auth\/feishu\/start/u)
assert.doesNotMatch(script, /\/openclaw\/auth\/feishu\/status/u)
assert.match(script, /credentials:\s*'same-origin'/u)
assert.match(script, /session\.role === 'admin'/u)
for (const requiredField of ['tenantId', 'workspaceMode', 'editorMode', 'bodyAuthority', 'memberRole', 'maintainer']) {
  assert.match(script, new RegExp(`session\\.${requiredField}|${requiredField}`), `login session parser must require ${requiredField}`)
}
assert.doesNotMatch(script, /localStorage|sessionStorage|document\.cookie/u)
assert.ok(html.includes('id="qr-canvas"'))
assert.ok(html.includes('id="password-panel"'))
assert.match(script, /const response = await postJson\(PERSONAL_ENDPOINTS\.resendVerification/u)
assert.match(script, /if \(!response\.ok\) \{\s*setText\('verify-message', registrationError\(payload\)/u)

for (const mode of ['personal', 'organization']) {
  assert.match(html, new RegExp(`id="${mode}-entry-state"[^>]*data-mode="${mode}"`), `${mode} entry-state container is missing`)
  assert.match(html, new RegExp(`id="${mode}-entry-matched"[^>]*data-entry-view="matched"[^>]*hidden`), `${mode} matched entry view is missing or not hidden by default`)
  assert.match(html, new RegExp(`id="${mode}-entry-fallback-state"[^>]*data-entry-view="fallback"[^>]*hidden`), `${mode} fallback entry view is missing or not hidden by default`)
}
assert.match(html, /id="personal-password-fallback" hidden/u)
assert.match(html, /id="organization-oauth-fallback" hidden/u)
assert.match(html, /id="qr-placeholder">选择组织成员后生成二维码/u)
assert.match(script, /const ENTRY_STATES = new Set\(\['matched', 'none', 'expired', 'mismatched'\]\)/u)
assert.match(script, /const visibleView = state === 'unavailable' \|\| state === 'none' \|\| state === 'expired' \|\| state === 'mismatched' \? 'fallback' : state/u)
assert.match(script, /if \(state === 'matched' && payload\?\.entry\)/u)
for (const entryField of ['displayLabel', 'maskedIdentity', 'expiresAt']) assert.match(script, new RegExp(`payload\\.entry\\.${entryField}`), `matched entry rendering must expose ${entryField}`)

assert.match(script, /async function loadEntryState\(mode\) \{\s*const run = \+\+entryStateRun\s*setHidden\(`\$\{mode\}-entry-state`, false\)/u)
assert.match(script, /const selectMode = \(mode,[\s\S]*?void loadEntryState\(mode\)/u)
assert.match(script, /#personal-entry-fallback[\s\S]*?setHidden\('personal-entry-state', true\)[\s\S]*?setHidden\('personal-password-fallback', false\)/u)
assert.match(script, /#organization-entry-fallback[\s\S]*?setHidden\('organization-entry-state', true\)[\s\S]*?setHidden\('organization-oauth-fallback', false\)[\s\S]*?startOrganizationAuth\(\)/u)
assert.match(script, /#personal-entry-fallback[\s\S]*?\+\+entryStateRun[\s\S]*?setHidden\('personal-entry-state', true\)/u)
assert.match(script, /#organization-entry-fallback[\s\S]*?\+\+entryStateRun[\s\S]*?setHidden\('organization-entry-state', true\)/u)
assert.match(script, /if \(run !== entryStateRun\) return null/u)
assert.match(script, /setBusy\(submit, true, '正在登录\.\.\.', '登录'\)[\s\S]*?finally \{[\s\S]*?setBusy\(submit, false/u)
assert.match(css, /(?:\.entry-loading\[hidden\]|\[hidden\]\.entry-loading)[^{]*\{[^}]*display\s*:\s*none\b/u)
assert.match(script, /(?:const method = replace \? 'replaceState' : 'pushState'|window\.history\.pushState)/u)
assert.match(script, /window\.history\[method\]\(\{ mode: mode \|\| null \},\s*'',\s*nextUrl\)/u)
assert.match(script, /window\.addEventListener\('popstate',\s*\(\) => \{[\s\S]*?selectMode\(mode, false, (?:false|null)\)/u)
assert.match(script, /window\.addEventListener\('popstate',[\s\S]*?else\s*(?:\{\s*)?resetMode\(null\)/u)

assertBoundedRequests(script)
assertOrganizationAuthorizationLock(script)
assertOrganizationAuthorizationErrors(script)
if (process.argv.includes('--self-test')) runSelfTest(html, tokenCss, script, css, viteConfig)

console.log('media login contract QA passed')
