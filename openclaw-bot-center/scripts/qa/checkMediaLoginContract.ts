import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const html = readFileSync('media.login.html', 'utf8')
const script = readFileSync('media.login.js', 'utf8')
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

console.log('media login contract QA passed')
