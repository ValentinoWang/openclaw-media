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
assert.match(adminSource, /save_platform_cookie_secret\.py/)
const panelStart = adminSource.indexOf('function PlatformCookiePanel')
const panelEnd = adminSource.indexOf('function useAdminResource', panelStart)
assert.ok(panelStart >= 0 && panelEnd > panelStart, 'cookie panel boundaries are missing')
assert.doesNotMatch(adminSource.slice(panelStart, panelEnd), /adminMutate|csrfToken|cookieValue|cookie_value|<input|<textarea/i)
assert.match(adminCss, /\.cookiePanel[\s\S]*?\.cookieStatusGrid/)

console.log('qa:creator-ux-contract: PASS avatar-fallback=1 profile-capture=1 admin-cookie-status=1')
