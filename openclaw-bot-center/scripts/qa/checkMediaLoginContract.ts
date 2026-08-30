import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const html = readFileSync('media.login.html', 'utf8')
const script = readFileSync('media.login.js', 'utf8')
const css = readFileSync('src/media.auth.css', 'utf8')
if (!html.includes('src="/media.login.js"')) throw new Error('media login module is missing')
if (/role\s*===\s*['"]user['"]/u.test(script)) {
  throw new Error('media login still reads a retired session field')
}

assert.match(script, /import QRCode from 'qrcode'/u)
assert.match(script, /QRCode\.toCanvas\(qrCanvas, started\.authorizationUrl/u)
assert.match(script, /\/openclaw\/media\/auth\/feishu\/start/u)
assert.doesNotMatch(script, /\/openclaw\/auth\/feishu\/start/u)
assert.doesNotMatch(script, /\/openclaw\/auth\/feishu\/status/u)
assert.match(script, /credentials:\s*'same-origin'/u)
assert.match(script, /session\.role === 'admin'/u)
for (const requiredField of [
  'tenantId',
  'workspaceMode',
  'editorMode',
  'bodyAuthority',
  'memberRole',
  'maintainer',
]) {
  assert.match(script, new RegExp(`session\\.${requiredField}|${requiredField}`), `login session parser must require ${requiredField}`)
}
assert.doesNotMatch(script, /localStorage|sessionStorage|document\.cookie/u)
assert.ok(html.includes('id="qr-canvas"'))
assert.ok(html.includes('id="password-panel"'))
assert.match(script, /const response = await postJson\(PERSONAL_ENDPOINTS\.resendVerification/u)
assert.match(script, /if \(!response\.ok\) \{\s*setText\('verify-message', registrationError\(payload\)\)/u)

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
for (const entryField of ['displayLabel', 'maskedIdentity', 'expiresAt']) {
  assert.match(script, new RegExp(`payload\\.entry\\.${entryField}`), `matched entry rendering must expose ${entryField}`)
}

assert.match(script, /async function loadEntryState\(mode\) \{\s*const run = \+\+entryStateRun\s*setHidden\(`\$\{mode\}-entry-state`, false\)/u)
assert.match(script, /const selectMode = \(mode,[\s\S]*?void loadEntryState\(mode\)/u)
assert.match(script, /#personal-entry-fallback[\s\S]*?setHidden\('personal-entry-state', true\)[\s\S]*?setHidden\('personal-password-fallback', false\)/u)
assert.match(script, /#organization-entry-fallback[\s\S]*?setHidden\('organization-entry-state', true\)[\s\S]*?setHidden\('organization-oauth-fallback', false\)[\s\S]*?startOrganizationAuth\(\)/u)

assert.match(css, /(?:\.entry-loading\[hidden\]|\[hidden\]\.entry-loading)[^{]*\{[^}]*display\s*:\s*none\b/u)

assert.match(script, /(?:const method = replace \? 'replaceState' : 'pushState'|window\.history\.pushState)/u)
assert.match(script, /window\.history\[method\]\(\{ mode: mode \|\| null \},\s*'',\s*nextUrl\)/u)
assert.match(script, /window\.addEventListener\('popstate',\s*\(\) => \{[\s\S]*?selectMode\(mode, false, (?:false|null)\)/u)
assert.match(script, /window\.addEventListener\('popstate',[\s\S]*?else\s*(?:\{\s*)?resetMode\(null\)/u)

console.log('media login contract QA passed')
