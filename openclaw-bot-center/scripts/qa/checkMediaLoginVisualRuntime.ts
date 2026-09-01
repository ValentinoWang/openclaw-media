import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, type Browser, type BrowserContext, type Page, type Route } from 'playwright'
import { createServer } from 'vite'

const mediaRoot = '/openclaw/media'
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const outputRoot = resolve(
  process.env.MEDIA_LOGIN_VISUAL_QA_OUTPUT ??
    join(projectRoot, 'agents-results/2026-08-31/media-visual-mainline-migration/runtime-auth/green'),
)
const viewports = [
  { width: 1440, height: 900, label: '1440x900' },
  { width: 390, height: 844, label: '390x844' },
] as const

type Viewport = (typeof viewports)[number]
type EntryState = 'matched' | 'none' | 'expired' | 'mismatched' | 'unavailable'
type EntryMode = 'personal' | 'organization'
type Telemetry = {
  consoleErrors: string[]
  pageErrors: string[]
  failedRequests: string[]
  entryRequests: EntryMode[]
  feishuRequests: number
}

type EntryHandler = (route: Route, mode: EntryMode, requestIndex: number) => Promise<void>

const fallbackSelectors: Record<EntryMode, string> = {
  personal: '#personal-password-fallback',
  organization: '#organization-oauth-fallback',
}

const authPages = new Map<string, string>([
  [`${mediaRoot}/login`, 'media.login.html'],
  [`${mediaRoot}/register`, 'media.register.html'],
  [`${mediaRoot}/verify`, 'src/media.verify.html'],
  [`${mediaRoot}/recover`, 'src/media.recover.html'],
  [`${mediaRoot}/reset`, 'src/media.reset.html'],
])
let delayedServerEntryMode: EntryMode | null = null

function entryPayload(mode: EntryMode, state: EntryState): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    schemaVersion: 'media_auth_entry_state_v1',
    mode,
    state,
  }
  if (state === 'matched') {
    payload.entry = {
      displayLabel: mode === 'personal' ? '林创作者' : '创作协作组',
      maskedIdentity: mode === 'personal' ? 'lin***@example.test' : 'ou_8c***',
      expiresAt: '2099-01-01T00:00:00+08:00',
    }
  }
  return payload
}

function sessionPayload(): Record<string, unknown> {
  return {
    schemaVersion: 'media_web_business_pages_v2',
    revision: 1,
    session: {
      publicUserId: '11111111-1111-4111-8111-111111111111',
      role: 'ordinary',
      memberRole: 'member',
      maintainer: false,
      csrfToken: 'visual-runtime-csrf',
      expiresAt: '2099-01-01T00:00:00+08:00',
      schemaVersion: 'media_web_business_pages_v2',
      workspaceMode: 'personal_web',
      editorMode: 'web_edit',
      bodyAuthority: 'internal',
      organizationName: null,
      organizationConnection: 'not_applicable',
      installationConnection: 'not_applicable',
      routeGrants: ['/today', '/studio', '/campaigns', '/business', '/desk', '/overview', '/assets', '/tracks', '/decisions', '/publishing', '/reviews', '/media-agent', '/archives', '/usage-billing', '/invites', '/workspace'],
    },
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function installNetwork(page: Page, telemetry: Telemetry, entryHandler: EntryHandler): Promise<void> {
  await page.route('**/openclaw/auth/entry-state?**', async (route) => {
    const mode = new URL(route.request().url()).searchParams.get('mode')
    assert.ok(mode === 'personal' || mode === 'organization', `unexpected entry-state mode ${mode}`)
    telemetry.entryRequests.push(mode)
    await entryHandler(route, mode, telemetry.entryRequests.length)
  })
  await page.route('**/openclaw/media/auth/feishu/start', async (route) => {
    telemetry.feishuRequests += 1
    assert.equal(route.request().method(), 'POST', 'Feishu authorization must be a POST request')
    assert.deepEqual(route.request().postDataJSON(), { workspaceIntent: 'organization_lark' }, 'Feishu authorization must preserve the organization workspace intent')
    await fulfillJson(route, {
      ok: true,
      authorizationUrl: 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?visual-runtime=1',
      expiresAt: '2099-01-01T00:00:00+08:00',
      maximumAge: 120,
    })
  })
  await page.route('**/openclaw/media/api/session', async (route) => fulfillJson(route, sessionPayload()))
  await page.route(/^https:\/\/fonts\.(?:googleapis|gstatic)\.com\//u, async (route) => {
    await route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  })
}

function attachTelemetry(page: Page, telemetry: Telemetry): void {
  page.on('console', (message) => {
    if (message.type() === 'error') telemetry.consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => telemetry.pageErrors.push(error.message))
  page.on('requestfailed', (request) => {
    telemetry.failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? 'unknown'}`)
  })
}

function freshTelemetry(): Telemetry {
  return { consoleErrors: [], pageErrors: [], failedRequests: [], entryRequests: [], feishuRequests: 0 }
}

async function assertNoRuntimeErrors(telemetry: Telemetry, label: string): Promise<void> {
  assert.deepEqual(telemetry.consoleErrors, [], `${label}: console errors\n${telemetry.consoleErrors.join('\n')}`)
  assert.deepEqual(telemetry.pageErrors, [], `${label}: page errors\n${telemetry.pageErrors.join('\n')}`)
  assert.deepEqual(telemetry.failedRequests, [], `${label}: failed requests\n${telemetry.failedRequests.join('\n')}`)
}

async function assertAuthLayout(page: Page, viewport: Viewport, label: string, initialP1 = false): Promise<void> {
  const layout = await page.evaluate(({ height, initial }) => {
    const root = document.querySelector<HTMLElement>('main.auth-shell')
    if (!root) throw new Error('auth shell is missing')
    const viewportWidth = document.documentElement.clientWidth
    const documentWidth = document.documentElement.scrollWidth
    if (documentWidth > viewportWidth + 1) throw new Error(`horizontal overflow ${documentWidth} > ${viewportWidth}`)
    const rootRect = root.getBoundingClientRect()
    if (rootRect.left < -1 || rootRect.right > viewportWidth + 1) throw new Error('auth shell exceeds viewport horizontally')
    const controls = [...document.querySelectorAll<HTMLElement>('button:not([hidden]), a[href]:not([hidden]), input:not([hidden])')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
      })
    for (const element of controls) {
      const rect = element.getBoundingClientRect()
      if (rect.left < -1 || rect.right > viewportWidth + 1) throw new Error(`interactive control overflows: ${element.id || element.tagName}`)
      const center = document.elementFromPoint(Math.max(1, rect.left + rect.width / 2), Math.max(1, rect.top + rect.height / 2))
      if (center && !element.contains(center) && !(element.id && center.closest(`#${CSS.escape(element.id)}`))) {
        throw new Error(`interactive control is obscured: ${element.id || element.tagName}`)
      }
    }
    const qrShell = document.querySelector<HTMLElement>('.qr-shell')
    const qrCanvas = document.querySelector<HTMLElement>('#qr-canvas')
    if (qrShell && qrCanvas && getComputedStyle(qrShell).display !== 'none') {
      const shellRect = qrShell.getBoundingClientRect()
      const canvasRect = qrCanvas.getBoundingClientRect()
      if (canvasRect.left < shellRect.left - 1 || canvasRect.right > shellRect.right + 1 || canvasRect.top < shellRect.top - 1 || canvasRect.bottom > shellRect.bottom + 1) {
        throw new Error('QR canvas exceeds its shell')
      }
      const verticalBlocks = [qrShell, document.querySelector<HTMLElement>('#qr-status'), document.querySelector<HTMLElement>('#mobile-authorize'), document.querySelector<HTMLElement>('.security-note')]
        .filter((element): element is HTMLElement => Boolean(element && getComputedStyle(element).display !== 'none' && !element.hidden))
      for (let index = 0; index < verticalBlocks.length - 1; index += 1) {
        const current = verticalBlocks[index].getBoundingClientRect()
        const next = verticalBlocks[index + 1].getBoundingClientRect()
        if (current.bottom > next.top + 1) throw new Error(`${verticalBlocks[index].id || verticalBlocks[index].className} overlaps ${verticalBlocks[index + 1].id || verticalBlocks[index + 1].className}`)
      }
    }
    const identityChoices = [...document.querySelectorAll<HTMLElement>('.identity-choice-button')]
      .filter((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
      })
    for (let leftIndex = 0; leftIndex < identityChoices.length; leftIndex += 1) {
      const left = identityChoices[leftIndex].getBoundingClientRect()
      for (let rightIndex = leftIndex + 1; rightIndex < identityChoices.length; rightIndex += 1) {
        const right = identityChoices[rightIndex].getBoundingClientRect()
        const overlapWidth = Math.min(left.right, right.right) - Math.max(left.left, right.left)
        const overlapHeight = Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top)
        if (overlapWidth > 1 && overlapHeight > 1) {
          throw new Error(`identity choices overlap: ${identityChoices[leftIndex].id} and ${identityChoices[rightIndex].id}`)
        }
      }
    }
    if (initial && document.documentElement.scrollHeight > height + 1) {
      throw new Error(`initial P1 does not fit one viewport: ${document.documentElement.scrollHeight} > ${height}`)
    }
    return { viewportWidth, documentWidth, documentHeight: document.documentElement.scrollHeight }
  }, { height: viewport.height, initial: initialP1 })
  assert.equal(layout.viewportWidth, viewport.width, `${label}: viewport width drifted`)
}

async function assertFallbackFitsViewport(page: Page, viewport: Viewport, mode: EntryMode, state: EntryState): Promise<void> {
  const selector = fallbackSelectors[mode]
  const scrollHeight = await page.evaluate(({ fallbackSelector, requireVisible }) => {
    const fallback = document.querySelector<HTMLElement>(fallbackSelector)
    if (requireVisible && (!fallback || fallback.hidden)) throw new Error(`fallback is not visible: ${fallbackSelector}`)
    return document.documentElement.scrollHeight
  }, { fallbackSelector: selector, requireVisible: state !== 'matched' })
  assert.ok(
    scrollHeight <= viewport.height + 1,
    `${viewport.label} ${mode} ${state}: fallback scrollHeight ${scrollHeight} exceeds viewport ${viewport.height}`,
  )
}

async function screenshot(page: Page, name: string): Promise<string> {
  const path = join(outputRoot, `${name}.png`)
  await page.screenshot({ path, fullPage: true, animations: 'disabled' })
  return path
}

async function newLoginPage(browser: Browser, viewport: Viewport, entryHandler: EntryHandler): Promise<{
  context: BrowserContext
  page: Page
  telemetry: Telemetry
}> {
  const context = await browser.newContext({ viewport })
  const page = await context.newPage()
  const telemetry = freshTelemetry()
  attachTelemetry(page, telemetry)
  await installNetwork(page, telemetry, entryHandler)
  return { context, page, telemetry }
}

async function expectState(page: Page, mode: EntryMode, state: EntryState): Promise<void> {
  const root = page.locator(`#${mode}-entry-state`)
  await root.waitFor({ state: 'visible' })
  await page.waitForFunction(
    ({ selector, expected }) => document.querySelector(selector)?.getAttribute('data-state') === expected,
    { selector: `#${mode}-entry-state`, expected: state },
  )
}

async function runInitialAndHistory(browser: Browser, origin: string, viewport: Viewport): Promise<void> {
  const { context, page, telemetry } = await newLoginPage(browser, viewport, async (route, mode) => fulfillJson(route, entryPayload(mode, mode === 'organization' ? 'matched' : 'none')))
  try {
    await page.goto(`${origin}${mediaRoot}/login`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: '选择进入方式', exact: true }).waitFor()
    await assertAuthLayout(page, viewport, `${viewport.label} P1`, true)
    await screenshot(page, `login-p1-${viewport.label}`)
    assert.equal(telemetry.entryRequests.length, 0, `${viewport.label}: P1 must not query entry state before a choice`)
    assert.equal(telemetry.feishuRequests, 0, `${viewport.label}: P1 must not request a QR code before an organization click`)

    await page.getByRole('tab', { name: /个人创作者/ }).click()
    await expectState(page, 'personal', 'none')
    await page.locator('#personal-password-fallback').waitFor({ state: 'visible' })
    await assertAuthLayout(page, viewport, `${viewport.label} personal P2`)
    await screenshot(page, `login-personal-none-${viewport.label}`)
    assert.match(page.url(), /[?&]mode=personal(?:&|$)/u, `${viewport.label}: personal mode is absent from URL`)
    assert.equal(telemetry.feishuRequests, 0, `${viewport.label}: personal P2 must not request Feishu`)

    await page.goBack()
    await page.getByRole('tab', { name: /个人创作者/ }).evaluate((element) => {
      if (element.getAttribute('aria-selected') !== 'false') throw new Error('back navigation did not restore P1')
    })
    await page.locator('#password-panel').waitFor({ state: 'hidden' })
    await page.goForward()
    await expectState(page, 'personal', 'none')
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expectState(page, 'personal', 'none')
    await assertNoRuntimeErrors(telemetry, `${viewport.label} P1/P2 history`)
  } finally {
    await context.close()
  }
}

async function runIdentityChoiceOverlapNegativeProof(browser: Browser, origin: string): Promise<void> {
  const viewport = viewports.find(({ label }) => label === '390x844')
  assert.ok(viewport, 'mobile viewport fixture is missing')
  const { context, page } = await newLoginPage(browser, viewport, async (route, mode) => fulfillJson(route, entryPayload(mode, 'expired')))
  try {
    await page.goto(`${origin}${mediaRoot}/login?mode=organization`, { waitUntil: 'domcontentloaded' })
    await expectState(page, 'organization', 'expired')
    await page.addStyleTag({
      content: '.identity-choice:has(.identity-choice-button[aria-selected="true"]) .choice-grid { grid-template-columns: minmax(0, 1fr) auto !important; }',
    })
    await assert.rejects(
      () => assertAuthLayout(page, viewport, 'synthetic overlapping identity choices'),
      /identity choices overlap/u,
    )
  } finally {
    await context.close()
  }
}

async function runEntryStateMatrix(browser: Browser, origin: string, viewport: Viewport): Promise<void> {
  for (const mode of ['personal', 'organization'] as const) {
    for (const state of ['matched', 'none', 'expired', 'mismatched', 'unavailable'] as const) {
      const { context, page, telemetry } = await newLoginPage(browser, viewport, async (route, requestedMode) => fulfillJson(route, entryPayload(requestedMode, state)))
      try {
        await page.goto(`${origin}${mediaRoot}/login?mode=${mode}`, { waitUntil: 'domcontentloaded' })
        await expectState(page, mode, state)
        const fallback = state !== 'matched'
        await page.locator(`#${mode}-entry-${fallback ? 'fallback-state' : 'matched'}`).waitFor({ state: 'visible' })
        if (mode === 'personal') {
          await page.locator('#personal-password-fallback').waitFor({ state: fallback ? 'visible' : 'hidden' })
          assert.equal(telemetry.feishuRequests, 0, `${viewport.label}: personal ${state} requested Feishu`)
        } else if (fallback) {
          await page.locator('#mobile-authorize').waitFor({ state: 'visible' })
          assert.equal(telemetry.feishuRequests, 1, `${viewport.label}: organization ${state} must request one QR code`)
        } else {
          assert.equal(telemetry.feishuRequests, 0, `${viewport.label}: matched organization must not request Feishu`)
        }
        await assertFallbackFitsViewport(page, viewport, mode, state)
        await assertAuthLayout(page, viewport, `${viewport.label} ${mode} ${state}`)
        if ((state === 'matched' || state === 'expired') && mode === 'organization') await screenshot(page, `login-${mode}-${state}-${viewport.label}`)
        await assertNoRuntimeErrors(telemetry, `${viewport.label} ${mode} ${state}`)
      } finally {
        await context.close()
      }
    }
  }
}

async function runFallbackAndKeyboard(browser: Browser, origin: string, viewport: Viewport): Promise<void> {
  const { context, page, telemetry } = await newLoginPage(browser, viewport, async (route, mode) => fulfillJson(route, entryPayload(mode, 'matched')))
  try {
    await page.goto(`${origin}${mediaRoot}/login?mode=personal`, { waitUntil: 'domcontentloaded' })
    await expectState(page, 'personal', 'matched')
    await page.getByRole('button', { name: '使用其他账号登录', exact: true }).click()
    await page.locator('#personal-entry-state').waitFor({ state: 'hidden' })
    await page.locator('#personal-password-fallback').waitFor({ state: 'visible' })
    await page.getByLabel('用户名或已验证邮箱').waitFor({ state: 'visible' })
    await assertFallbackFitsViewport(page, viewport, 'personal', 'matched')
    await assertAuthLayout(page, viewport, `${viewport.label} personal manual fallback`)

    await page.goto(`${origin}${mediaRoot}/login?mode=organization`, { waitUntil: 'domcontentloaded' })
    await expectState(page, 'organization', 'matched')
    await page.getByRole('button', { name: '使用其他组织授权', exact: true }).click()
    await page.locator('#organization-entry-state').waitFor({ state: 'hidden' })
    await page.locator('#mobile-authorize').waitFor({ state: 'visible' })
    assert.equal(telemetry.feishuRequests, 1, `${viewport.label}: organization fallback must request one QR code`)
    await assertFallbackFitsViewport(page, viewport, 'organization', 'matched')
    await assertAuthLayout(page, viewport, `${viewport.label} organization manual fallback`)

    await page.goto(`${origin}${mediaRoot}/login`, { waitUntil: 'domcontentloaded' })
    const personal = page.getByRole('tab', { name: /个人创作者/ })
    await personal.focus()
    await personal.press('ArrowRight')
    await expectState(page, 'organization', 'matched')
    await page.getByRole('tab', { name: /组织成员/ }).evaluate((element) => {
      if (element.getAttribute('aria-selected') !== 'true') throw new Error('keyboard choice did not select organization')
    })
    await assertNoRuntimeErrors(telemetry, `${viewport.label} fallback and keyboard`)
  } finally {
    await context.close()
  }
}

async function runStaleEntryFence(browser: Browser, origin: string): Promise<void> {
  let resolvePersonal: (() => void) | null = null
  const delayedPersonal = new Promise<void>((resolve) => { resolvePersonal = resolve })
  const { context, page, telemetry } = await newLoginPage(browser, viewports[0], async (route, mode) => {
    if (mode === 'personal') {
      await delayedPersonal
      await fulfillJson(route, entryPayload(mode, 'matched'))
      return
    }
    await fulfillJson(route, entryPayload(mode, 'matched'))
  })
  try {
    await page.goto(`${origin}${mediaRoot}/login`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('tab', { name: /个人创作者/ }).click()
    await page.waitForFunction(() => document.querySelector('#personal-entry-state')?.getAttribute('data-state') === 'loading')
    await page.getByRole('tab', { name: /组织成员/ }).click()
    await expectState(page, 'organization', 'matched')
    resolvePersonal?.()
    await page.waitForTimeout(100)
    await page.locator('#organization-entry-matched').waitFor({ state: 'visible' })
    await page.locator('#password-panel').waitFor({ state: 'hidden' })
    await screenshot(page, 'login-stale-entry-fence-1440x900')
    await assertNoRuntimeErrors(telemetry, 'stale entry-state fence')
  } finally {
    await context.close()
  }
}

async function runEntryTimeout(browser: Browser, origin: string): Promise<void> {
  const { context, page, telemetry } = await newLoginPage(browser, viewports[0], async (route, mode) => fulfillJson(route, entryPayload(mode, 'matched')))
  try {
    await page.unroute('**/openclaw/auth/entry-state?**')
    delayedServerEntryMode = 'personal'
    await page.goto(`${origin}${mediaRoot}/login?mode=personal`, { waitUntil: 'domcontentloaded' })
    const state = page.locator('#personal-entry-state')
    await state.waitFor({ state: 'visible' })
    await state.evaluate((element) => new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('entry-state timeout did not fail closed')), 6_000)
      const observer = new MutationObserver(() => {
        if (element.getAttribute('data-state') === 'unavailable') {
          window.clearTimeout(timeout)
          observer.disconnect()
          resolve()
        }
      })
      observer.observe(element, { attributes: true, attributeFilter: ['data-state'] })
    }))
    await page.locator('#personal-password-fallback').waitFor({ state: 'visible' })
    await screenshot(page, 'login-entry-timeout-1440x900')
    assert.equal(telemetry.failedRequests.length, 1, 'entry-state timeout must abort exactly one request')
    assert.match(telemetry.failedRequests[0] ?? '', /entry-state\?mode=personal.*ERR_ABORTED/u)
    telemetry.failedRequests.length = 0
    await assertNoRuntimeErrors(telemetry, 'entry-state timeout')
  } finally {
    delayedServerEntryMode = null
    await context.close()
  }
}

async function runOrganizationReselectionFence(browser: Browser, origin: string): Promise<void> {
  let resolveFirstAuthorization: (() => void) | null = null
  const firstAuthorization = new Promise<void>((resolve) => { resolveFirstAuthorization = resolve })
  const { context, page, telemetry } = await newLoginPage(browser, viewports[0], async (route, mode) => fulfillJson(route, entryPayload(mode, 'none')))
  await page.unroute('**/openclaw/media/auth/feishu/start')
  await page.route('**/openclaw/media/auth/feishu/start', async (route) => {
    telemetry.feishuRequests += 1
    if (telemetry.feishuRequests === 1) {
      await firstAuthorization
      await fulfillJson(route, {
        ok: true,
        authorizationUrl: 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?visual-runtime=late',
        expiresAt: '2099-01-01T00:00:00+08:00',
        maximumAge: 120,
      })
      return
    }
    await fulfillJson(route, {
      ok: true,
      authorizationUrl: 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?visual-runtime=fresh',
      expiresAt: '2099-01-01T00:00:00+08:00',
      maximumAge: 120,
    })
  })
  try {
    await page.goto(`${origin}${mediaRoot}/login?mode=organization`, { waitUntil: 'domcontentloaded' })
    await expectState(page, 'organization', 'none')
    await page.waitForFunction(() => document.querySelector('#qr-status')?.textContent?.includes('正在连接'))
    assert.equal(telemetry.feishuRequests, 1, 'first organization selection did not start authorization')
    await page.getByRole('button', { name: '返回身份选择', exact: true }).click()
    await page.getByRole('tab', { name: /组织成员/ }).click()
    await expectState(page, 'organization', 'none')
    await page.waitForFunction(() => document.querySelector('#mobile-authorize')?.hidden === false, undefined, { timeout: 2_000 })
    assert.equal(telemetry.feishuRequests, 2, 'reselected organization must start a fresh authorization request')
    resolveFirstAuthorization?.()
    await page.waitForTimeout(100)
    await page.locator('#mobile-authorize').waitFor({ state: 'visible' })
    await screenshot(page, 'login-organization-reselection-fence-1440x900')
    await assertNoRuntimeErrors(telemetry, 'organization reselection fence')
  } finally {
    await context.close()
  }
}

async function runOrganizationErrorFidelity(browser: Browser, origin: string): Promise<void> {
  const { context, page, telemetry } = await newLoginPage(browser, viewports[0], async (route, mode) => fulfillJson(route, entryPayload(mode, 'none')))
  await page.unroute('**/openclaw/media/auth/feishu/start')
  await page.route('**/openclaw/media/auth/feishu/start', async (route) => {
    telemetry.feishuRequests += 1
    assert.deepEqual(route.request().postDataJSON(), { workspaceIntent: 'organization_lark' })
    await fulfillJson(route, { error: { code: 'feishu_provider_unavailable', message: '组织授权上游正在维护。' } }, 503)
  })
  try {
    await page.goto(`${origin}${mediaRoot}/login?mode=organization`, { waitUntil: 'domcontentloaded' })
    await expectState(page, 'organization', 'none')
    const status = page.locator('#qr-status')
    await page.waitForFunction(() => document.querySelector<HTMLElement>('#qr-status')?.dataset.errorStatus === '503')
    assert.equal(telemetry.consoleErrors.length, 1, 'organization 503 must emit exactly one browser resource error')
    assert.match(telemetry.consoleErrors[0] ?? '', /503 \(Service Unavailable\)/u)
    telemetry.consoleErrors.length = 0
    await assertNoRuntimeErrors(telemetry, 'organization error fidelity')
    await assert.doesNotReject(async () => {
      await status.waitFor({ state: 'visible' })
      assert.equal(await status.textContent(), '组织授权上游正在维护。')
      assert.equal(await status.getAttribute('data-error-code'), 'feishu_provider_unavailable')
      assert.equal(await status.getAttribute('data-error-status'), '503')
    })
    await page.locator('#qr-refresh').waitFor({ state: 'visible' })
  } finally {
    await context.close()
  }
}

async function runAuthPageSmoke(browser: Browser, origin: string, viewport: Viewport): Promise<void> {
  const pages = [
    { path: 'register', heading: '创建个人账号', form: '#register-form' },
    { path: 'verify', heading: '完成个人邮箱验证', form: '#verify-form' },
    { path: 'recover', heading: '忘记密码', form: '#recover-form' },
    { path: 'reset', heading: '设置新密码', form: '#reset-form' },
  ]
  for (const definition of pages) {
    const { context, page, telemetry } = await newLoginPage(browser, viewport, async (route, mode) => fulfillJson(route, entryPayload(mode, 'none')))
    try {
      await page.goto(`${origin}${mediaRoot}/${definition.path}`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: definition.heading, exact: true }).waitFor()
      await page.locator(definition.form).waitFor({ state: 'visible' })
      await assertAuthLayout(page, viewport, `${viewport.label} ${definition.path}`)
      await screenshot(page, `auth-${definition.path}-${viewport.label}`)
      await assertNoRuntimeErrors(telemetry, `${viewport.label} ${definition.path}`)
    } finally {
      await context.close()
    }
  }
}

await mkdir(outputRoot, { recursive: true })
const server = await createServer({
  root: projectRoot,
  configFile: false,
  appType: 'custom',
  publicDir: false,
  resolve: {
    alias: {
      '/mediaDesignTokens.css': resolve(projectRoot, 'src/media/mediaDesignTokens.css'),
    },
  },
  plugins: [{
    name: 'media-login-visual-runtime-auth-pages',
    configureServer(viteServer) {
      viteServer.middlewares.use(async (request, response, next) => {
        const url = new URL(request.url ?? '/', 'http://visual-runtime.local')
        if (url.pathname === '/openclaw/auth/entry-state' && delayedServerEntryMode) {
          const mode = url.searchParams.get('mode')
          if (mode !== delayedServerEntryMode) return next()
          await new Promise((resolveDelay) => setTimeout(resolveDelay, 6_000))
          if (!response.writableEnded && !response.destroyed) {
            response.statusCode = 200
            response.setHeader('Content-Type', 'application/json')
            response.end(JSON.stringify(entryPayload(delayedServerEntryMode, 'matched')))
          }
          return
        }
        const source = authPages.get(url.pathname)
        if (!source || !request.headers.accept?.includes('text/html')) return next()
        try {
          const html = await readFile(join(projectRoot, source), 'utf8')
          response.statusCode = 200
          response.setHeader('Content-Type', 'text/html')
          response.end(await viteServer.transformIndexHtml(request.url ?? url.pathname, html))
        } catch (error) {
          next(error as Error)
        }
      })
    },
  }],
  server: { host: '127.0.0.1', port: 0, strictPort: false },
})

await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const address = server.httpServer?.address()
  assert.ok(address && typeof address !== 'string', 'Vite QA server did not expose a TCP port')
  const origin = `http://127.0.0.1:${address.port}`
  for (const viewport of viewports) {
    await runInitialAndHistory(browser, origin, viewport)
    await runEntryStateMatrix(browser, origin, viewport)
    await runFallbackAndKeyboard(browser, origin, viewport)
    await runAuthPageSmoke(browser, origin, viewport)
  }
  await runIdentityChoiceOverlapNegativeProof(browser, origin)
  await runStaleEntryFence(browser, origin)
  await runEntryTimeout(browser, origin)
  await runOrganizationReselectionFence(browser, origin)
  await runOrganizationErrorFidelity(browser, origin)
  console.log(JSON.stringify({ ok: true, outputRoot, viewports, authPageSmoke: 8 }, null, 2))
} finally {
  await browser.close()
  await server.close()
}
