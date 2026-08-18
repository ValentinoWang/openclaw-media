import { readFileSync } from 'node:fs'

const page = readFileSync('media.register.html', 'utf8')
const login = readFileSync('media.login.html', 'utf8')
const script = readFileSync('media.login.js', 'utf8')
const config = readFileSync('vite.media.config.ts', 'utf8')
const routeContract = JSON.parse(readFileSync('contracts/media-auth-route-contract.json', 'utf8')) as {
  canonicalRoutes: string[]
  staticAssets: string[]
  retiredRoutes: string[]
}

const required = [
  '创建个人账号', 'id="username"', 'id="email"', 'id="password"',
  '注册和验证都不会自动登录', 'minlength="8"', 'id="register-resend"',
]
for (const token of required) if (!page.includes(token)) throw new Error(`registration page missing ${token}`)
if (page.includes('minlength="12"')) throw new Error('registration page still requires 12-character passwords')
for (const token of ['PERSONAL_ENDPOINTS.register', 'username: document.querySelector', 'email: document.querySelector', 'password: document.querySelector']) {
  if (!script.includes(token)) throw new Error(`registration behavior missing ${token}`)
}
for (const token of ['registrationError(payload)', 'PERSONAL_ENDPOINTS.resendVerification', 'register-resend-message']) {
  if (!script.includes(token)) throw new Error(`registration recovery behavior missing ${token}`)
}
if (!login.includes('/openclaw/media/register')) throw new Error('login page has no registration link')
if (!config.includes('register: resolve(__dirname, \'media.register.html\')')) throw new Error('media build does not include registration entry')
for (const route of ['/openclaw/media/register', '/openclaw/media/verify', '/openclaw/media/recover', '/openclaw/media/reset']) {
  if (!routeContract.canonicalRoutes.includes(route)) throw new Error(`auth route is not declared: ${route}`)
}
for (const asset of ['/media.login.js', '/media.auth.css']) {
  if (!routeContract.staticAssets.includes(asset)) throw new Error(`auth asset is not declared: ${asset}`)
}
if (!routeContract.retiredRoutes.includes('/openclaw/media/auth/registration-policy')) {
  throw new Error('retired registration-policy route is not declared')
}
for (const retired of [
  'value="organization"', 'id="display-name"', 'id="organization-name"',
  'id="admission-code"', '/openclaw/auth/registration-policy',
  'tenantType', 'workspaceMode', 'bodyAuthority',
]) if (page.includes(retired) || (retired.startsWith('/') && script.includes(retired))) {
  throw new Error(`retired organization registration field remains: ${retired}`)
}
if (page.includes('api_key') || page.includes('secret') || page.includes('turnstile')) throw new Error('frontend contains a secret or provider credential field')
console.log('media_registration_page=PASS')
