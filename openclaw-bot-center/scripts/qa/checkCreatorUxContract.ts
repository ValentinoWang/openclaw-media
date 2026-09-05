import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const projectRoot = path.resolve(import.meta.dirname, '../..')
const tracksPath = path.join(projectRoot, 'src/media/pages/ordinary/TracksPage.tsx')
const tracksSource = fs.readFileSync(tracksPath, 'utf8')
const tracksCss = fs.readFileSync(path.join(projectRoot, 'src/media/pages/ordinary/TracksPage.module.css'), 'utf8')
const adminSource = fs.readFileSync(path.join(projectRoot, 'src/media/pages/admin/AdminAccessPage.tsx'), 'utf8')
const adminCss = fs.readFileSync(path.join(projectRoot, 'src/media/pages/admin/AdminAccessPage.module.css'), 'utf8')

assert.match(tracksSource, /avatarUrl: string \| null/)
assert.match(tracksSource, /referrerPolicy="no-referrer"/)
assert.match(tracksSource, /onError=\{\(\) => setAvatarFailed\(true\)\}/)
assert.match(tracksSource, /creator\.avatarUrl && !avatarFailed/)
assert.match(tracksCss, /\.avatarImage[\s\S]*?width: 100%;[\s\S]*?height: 100%;[\s\S]*?border-radius: 50%/)

const captureStart = tracksSource.indexOf('data-capability-action="creator_profile_upsert"', tracksSource.indexOf('function BenchmarkInspector'))
assert.ok(captureStart >= 0, 'creator inspector capture action is missing')
const captureSnippet = tracksSource.slice(captureStart, captureStart + 900)
assert.match(captureSnippet, /disabled=\{!creator\.profileUrl\}/)
assert.match(captureSnippet, /onClick=\{\(\) => onCapture\(creator\)\}/)
assert.match(tracksSource, /capabilityId: "creator_profile_upsert"[\s\S]*?variantId: "url_candidate"[\s\S]*?profile_url: creator\.profileUrl/)
assert.doesNotMatch(captureSnippet, /cookie|token|secret/i)

assert.match(adminSource, /const permitted = runtimeState === 'authenticated' && session\?\.role === 'admin'/)
assert.match(adminSource, /<PlatformCookiePanel state=\{cookieState\} \/>/)
assert.match(adminSource, /data-admin-cookie-panel/)
assert.match(adminSource, /getAdminPlatformCookies/)
// 这里曾经**要求**页面把配置脚本名写出来。后来服务端把 configurationScript /
// safeCommand 从合同里删掉了（服务器绝对路径和命令不再下发给前端），页面改成
// 「平台凭据由服务器安全管理」。判据跟着反过来：现在要求这一页**不含**脚本名或
// 服务器绝对路径——它们属于服务器，不该出现在浏览器拿得到的产物里。
assert.doesNotMatch(adminSource, /save_platform_cookie_secret|\/home\/[a-z]+\//)
assert.match(adminSource, /不接收、显示或下发 Cookie 内容/)
const panelStart = adminSource.indexOf('function PlatformCookiePanel')
const panelEnd = adminSource.indexOf('function useAdminResource', panelStart)
assert.ok(panelStart >= 0 && panelEnd > panelStart, 'cookie panel boundaries are missing')
assert.doesNotMatch(adminSource.slice(panelStart, panelEnd), /adminMutate|csrfToken|cookieValue|cookie_value|<input|<textarea/i)
assert.match(adminCss, /\.cookiePanel[\s\S]*?\.cookieStatusGrid/)

console.log('qa:creator-ux-contract: PASS avatar-fallback=1 profile-capture=1 admin-cookie-status=1')
