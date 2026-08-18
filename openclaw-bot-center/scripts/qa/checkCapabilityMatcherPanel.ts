import { chromium } from 'playwright'

const baseUrl = ensureTrailingSlash(process.env.BOT_CENTER_BASE_URL ?? 'http://127.0.0.1:4173/openclaw/bots/')
const authCookie = process.env.BOT_CENTER_QA_COOKIE ?? ''
const copyProjection = '【素材】\n路径续接ID：capplan_abcdefghijklmnop\n链接或文字素材：博主资料'
const matched = {
  schemaVersion: '3', pathStatus: 'matched', needSummary: '将博主资料保存为素材。', routeExplanation: '需求首先需要保存来源事实。',
  guidancePlanId: 'capplan_abcdefghijklmnop', copyProjection,
  steps: [{ order: 1, capabilityId: 'source_asset_intake', variantId: 'default', extractedParams: { field_c675ffae69a2: '博主资料' }, confidence: 0.94, evidence: [{ fieldKey: 'field_c675ffae69a2', quote: '博主资料', source: 'query' }], issues: [] }],
}

function ensureTrailingSlash(value: string) { return value.endsWith('/') ? value : `${value}/` }

async function verify(viewport: { width: number; height: number }) {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport })
  if (authCookie) {
    const [name, value] = authCookie.split('=', 2)
    if (!name || !value) throw new Error('BOT_CENTER_QA_COOKIE must use name=value format')
    const target = new URL(baseUrl)
    await context.addCookies([{ name, value, domain: target.hostname, path: '/openclaw/', httpOnly: true, secure: target.protocol === 'https:', sameSite: 'Lax' }])
  }
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const page = await context.newPage()
  const consoleErrors: string[] = []
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('pageerror', (error) => consoleErrors.push(error.message))
  await page.route('**/api/capability-match', async (route) => {
    const request = route.request().postDataJSON() as { query?: string }
    const body = request.query?.includes('信息不足')
      ? { schemaVersion: '3', pathStatus: 'needs_clarification', needSummary: '查询商务事实。', clarificationQuestion: '请补充账号名称、作者ID或主页链接。', candidates: [], knownParams: { platform: '小红书' } }
      : matched
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto(`${baseUrl}#/bots`, { waitUntil: 'networkidle' })
  await page.getByLabel('描述你的需求').fill('保存博主资料')
  await page.getByRole('button', { name: '匹配能力' }).click()
  await page.getByText('为什么是这些能力').waitFor()
  await page.getByText(copyProjection).waitFor()
  await page.locator('.capability-matcher-copy-heading button').click()
  if (await page.evaluate(() => navigator.clipboard.readText()) !== copyProjection) throw new Error('copy projection mismatch')

  await page.getByLabel('描述你的需求').fill('信息不足')
  await page.getByRole('button', { name: '匹配能力' }).click()
  await page.getByText('请补充账号名称、作者ID或主页链接。').waitFor()
  if (await page.locator('.capability-matcher-copy-ready').count()) throw new Error('clarification must not expose executable copy')
  const panel = page.locator('.capability-matcher-panel')
  if (await panel.evaluate((element) => element.scrollWidth > element.clientWidth + 1)) throw new Error(`matcher panel overflowed at ${viewport.width}px`)
  if (consoleErrors.length) throw new Error(`console errors: ${consoleErrors.join(' | ')}`)
  await browser.close()
}

await verify({ width: 1366, height: 900 })
await verify({ width: 390, height: 844 })
console.log(`Capability matcher panel QA passed at ${baseUrl}`)
