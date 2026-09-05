/** 走查构建出来的静态演示站（dist-demo/）：证明每个声明过的路由都落成了真实的
 *  HTML 文件，并且真实生产 React 外壳能在浏览器里完整渲染出业务内容——而不是
 *  只在 `vite dev`/SPA 回退下看起来能跑。因此这里手写一个不做 SPA 全局回退的
 *  静态文件服务器：命中不到具体文件就必须 404，这正是本脚本要验证的东西。 */
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { createServer as createHttpServer } from 'node:http'
import { dirname, extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, type Browser } from 'playwright'
import { demoAuthPages, demoStaticRoutes } from '../../src/demo/demoRoutes'
import { demoPersonas } from '../../src/demo/demoPersonas'
import { resolveStudioRouteOutcome, resolveStudioRoutePolicy } from '../../src/media/mediaStudioRoutePolicy'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
// 与 vite.demo.config.ts 一致：基址可以用 MEDIA_DEMO_BASE 覆盖，走查必须跟着走。
const demoBase = process.env.MEDIA_DEMO_BASE ?? '/openclaw/media-demo/'
/** 默认走查 dist-demo；并行开发时可以用 MEDIA_DEMO_QA_DIST 指到自己的产物目录，
 *  免得几个人互相覆盖（和 MEDIA_LAYOUT_QA_DIST 同一个用法）。 */
const distDemoRoot = resolve(projectRoot, process.env.MEDIA_DEMO_QA_DIST ?? 'dist-demo')
const outputRoot = resolve(process.env.MEDIA_DEMO_QA_OUTPUT ?? '/tmp/openclaw-media-demo-qa')
const viewport = { width: 1440, height: 1000 } as const
const minContentTextLength = 80

// 与 src/demo/demoPersonas.ts 内部私有的 storageKey 保持一致；那个模块没有导出
// 这个字符串常量，这里按约定直接写死，用来在打开第一页之前把身份"预先"写进
// localStorage（真实生产代码在挂载时同步读取它，必须赶在应用脚本之前落地）。
const demoPersonaStorageKey = 'mediaclaw-demo-persona'

// Chromium 对 /favicon.ico 的自动探测、以及个别环境下的连接噪音都不是页面本身的
// 缺陷，走查目标是"业务内容有没有真的渲染出来"，所以显式过滤掉这类噪声。
const consoleNoiseMarkers = ['favicon', 'ERR_CONNECTION']
// 这三句是生产代码里的终态兜底文案：出现在 .media-content 里说明该身份并没有
// 真正进入这个路由的业务页面（会话未就绪 / 无权限 / 需要登录），而只是落在了
// 某个兜底分支上——这正是本脚本要拦下的"看起来能跑但其实没有渲染业务内容"。
const fallbackCopyMarkers = ['工作台暂时不可用', '无权访问此页面', '登录后进入']

if (!existsSync(distDemoRoot)) {
  console.error(
    `未找到静态演示站产物目录：${distDemoRoot}\n` +
      '请先运行 `npm run build:demo` 生成 dist-demo/，再执行本脚本。',
  )
  process.exit(1)
}

await mkdir(outputRoot, { recursive: true })

const failures: string[] = []
function record(condition: boolean, message: string): void {
  if (!condition) failures.push(message)
}

// --- 产物完整性：构建骨架文件与每个声明路由的静态 HTML 是否都落地了 ---
for (const requiredFile of ['index.html', '404.html', 'pages.html', 'mediaDesignTokens.css', 'mediaFonts.css']) {
  record(existsSync(join(distDemoRoot, requiredFile)), `产物缺少必需文件 dist-demo/${requiredFile}`)
}
record(
  existsSync(join(distDemoRoot, 'fonts')) && statSync(join(distDemoRoot, 'fonts')).isDirectory(),
  '产物缺少本地字体目录 dist-demo/fonts/',
)
for (const page of demoAuthPages) {
  const authIndexPath = join(distDemoRoot, page.path.replace(/^\//, '').replace(/\/$/, ''), 'index.html')
  record(existsSync(authIndexPath), `认证页 ${page.path} 缺少静态文件 ${authIndexPath.replace(distDemoRoot + sep, '')}`)
}
for (const route of demoStaticRoutes) {
  const routeIndexPath = join(distDemoRoot, route.replace(/^\//, ''), 'index.html')
  record(existsSync(routeIndexPath), `路由 ${route} 缺少对应的静态文件 dist-demo${route}/index.html`)
}

// --- 静态文件服务器：只做“精确文件 / 目录回退到 index.html”，不做 SPA 全局回退 ---
function contentTypeFor(filePath: string): string {
  switch (extname(filePath)) {
    case '.html':
      return 'text/html; charset=utf-8'
    case '.js':
    case '.mjs':
      return 'text/javascript; charset=utf-8'
    case '.css':
      return 'text/css; charset=utf-8'
    case '.json':
      return 'application/json; charset=utf-8'
    case '.svg':
      return 'image/svg+xml'
    case '.png':
      return 'image/png'
    case '.woff2':
      return 'font/woff2'
    case '.woff':
      return 'font/woff'
    case '.ico':
      return 'image/x-icon'
    case '.txt':
      return 'text/plain; charset=utf-8'
    default:
      return 'application/octet-stream'
  }
}

function isWithinDistDemo(candidate: string): boolean {
  return candidate === distDemoRoot || candidate.startsWith(`${distDemoRoot}${sep}`)
}

function resolveStaticFile(relativePath: string): string | null {
  const safeRelative = relativePath.replace(/^\/+/, '')
  const exactCandidate = resolve(distDemoRoot, safeRelative)
  if (isWithinDistDemo(exactCandidate) && existsSync(exactCandidate) && statSync(exactCandidate).isFile()) {
    return exactCandidate
  }
  // 只有“看起来像目录”（以 / 结尾，或压根没有扩展名）才尝试 <path>/index.html；
  // 命中不到就是 404，绝不像 SPA dev server 那样兜底到根 index.html。
  const looksLikeDirectory = safeRelative === '' || safeRelative.endsWith('/') || extname(safeRelative) === ''
  if (!looksLikeDirectory) return null
  const indexCandidate = resolve(distDemoRoot, safeRelative, 'index.html')
  if (isWithinDistDemo(indexCandidate) && existsSync(indexCandidate) && statSync(indexCandidate).isFile()) {
    return indexCandidate
  }
  return null
}

const server = createHttpServer((request, response) => {
  const requestUrl = new URL(request.url ?? '/', 'http://media-demo-qa.invalid')
  let pathname: string
  try {
    pathname = decodeURIComponent(requestUrl.pathname)
  } catch {
    response.statusCode = 400
    response.end('bad request path')
    return
  }
  if (!pathname.startsWith(demoBase)) {
    response.statusCode = 404
    response.end('not found')
    return
  }
  const filePath = resolveStaticFile(pathname.slice(demoBase.length))
  if (!filePath) {
    response.statusCode = 404
    response.end('not found')
    return
  }
  response.statusCode = 200
  response.setHeader('Content-Type', contentTypeFor(filePath))
  response.end(readFileSync(filePath))
})

await new Promise<void>((resolveListen, rejectListen) => {
  server.once('error', rejectListen)
  server.listen(0, '127.0.0.1', () => resolveListen())
})
const address = server.address()
assert.ok(address && typeof address !== 'string', '静态服务器未能分配端口')
const origin = `http://127.0.0.1:${address.port}`

// --- 逐身份、逐路由走查真实渲染出的页面 ---
type RouteTelemetry = {
  consoleErrors: string[]
  pageErrors: string[]
  offOriginRequests: string[]
}

function freshTelemetry(): RouteTelemetry {
  return { consoleErrors: [], pageErrors: [], offOriginRequests: [] }
}

function isNoise(text: string): boolean {
  return consoleNoiseMarkers.some((marker) => text.includes(marker))
}

function routeSlug(route: string): string {
  return route.replace(/^\//, '').replace(/\//g, '-')
}

let browser: Browser | null = null
let totalVisits = 0
try {
  // 部分运行环境预装了 Chromium 但版本与 playwright 期望的构建号不一致，
  // 允许用环境变量直接指向可执行文件，避免为一次走查重新下载浏览器。
  const executablePath = process.env.MEDIA_DEMO_QA_CHROMIUM
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'], ...(executablePath ? { executablePath } : {}) })

  for (const persona of demoPersonas) {
    // 身份能访问哪些路由，跟着生产的路由策略走（而不是自己再猜一套规则）：
    // 详情页示例（如 /studio/:runId、/workspace/preview/:artifactId）并不会
    // 逐条出现在 routeGrants 里，resolveStudioRouteOutcome 才是唯一的准绳。
    const policy = resolveStudioRoutePolicy(persona.session)
    const routes = demoStaticRoutes.filter((route) => resolveStudioRouteOutcome(policy, route).kind === 'render')
    if (routes.length === 0) {
      failures.push(`身份「${persona.label}」（${persona.id}）没有可走查的静态路由，请检查 routeGrants 与 mediaStudioRoutePolicy 是否同步`)
      continue
    }

    const context = await browser.newContext({ viewport })
    const page = await context.newPage()

    let telemetry = freshTelemetry()
    page.on('console', (message) => {
      if (message.type() !== 'error') return
      const text = message.text()
      if (isNoise(text)) return
      telemetry.consoleErrors.push(text)
    })
    page.on('pageerror', (error) => {
      if (isNoise(error.message)) return
      telemetry.pageErrors.push(error.message)
    })
    page.on('request', (request) => {
      const requestUrl = new URL(request.url())
      if (requestUrl.protocol === 'data:' || requestUrl.protocol === 'blob:') return
      if (requestUrl.origin === origin) return
      telemetry.offOriginRequests.push(`${request.method()} ${request.url()}`)
    })

    // 身份切换是纯前端状态，且在应用挂载时同步读取一次，所以必须用
    // addInitScript 在应用脚本跑之前写入 localStorage；切路由都是整页刷新
    // （不是 SPA 内部跳转），addInitScript 会在每次刷新前重新执行一遍，无需
    // 在每个路由前手动重复设置。
    await page.addInitScript(
      ({ key, value }) => {
        localStorage.setItem(key, value)
      },
      { key: demoPersonaStorageKey, value: persona.id },
    )

    for (const route of routes) {
      totalVisits += 1
      telemetry = freshTelemetry()
      const label = `身份「${persona.label}」（${persona.id}）路由 ${route}`
      const screenshotPath = join(outputRoot, `${persona.id}-${routeSlug(route)}.png`)

      try {
        const url = `${origin}${demoBase}${route.replace(/^\//, '')}`
        const response = await page.goto(url, { waitUntil: 'domcontentloaded' })
        const status = response?.status() ?? null
        record(status === 200, `${label}：页面未返回 200（实际 ${status ?? '无响应'}）`)

        await page.locator('.media-shell').first().waitFor({ state: 'visible', timeout: 10_000 })
        const contentLocator = page.locator('.media-content').first()
        await contentLocator.waitFor({ state: 'visible', timeout: 10_000 })
        const rawText = await contentLocator.innerText()
        const normalizedLength = rawText.replace(/\s+/g, '').length
        record(
          normalizedLength >= minContentTextLength,
          `${label}：主内容区文本过短（去空白后 ${normalizedLength} 字，少于 ${minContentTextLength} 字），页面可能没有真正渲染业务内容`,
        )
        for (const marker of fallbackCopyMarkers) {
          record(!rawText.includes(marker), `${label}：主内容区出现兜底文案『${marker}』，该身份没有正常进入此路由`)
        }
        // 指标卡的两种破相在类型检查里都看不见，只有真渲染出来才量得到：
        //   图标压住正文（页面覆写列数、原语用命名区域时会发生）；
        //   正文列被挤到几十像素宽（窄容器里仍排多列时会发生，文字被迫一行一个字）。
        const metricDefects = await page.evaluate(() => {
          const problems: string[] = []
          for (const body of document.querySelectorAll('.mg-metric-body')) {
            const card = body.parentElement
            const icon = card?.querySelector(':scope > .mg-metric-icon')
            const bodyRect = body.getBoundingClientRect()
            if (bodyRect.width === 0 && bodyRect.height === 0) continue
            const name = (body.querySelector('small')?.textContent ?? '').trim() || '未命名指标'
            if (icon) {
              const iconRect = icon.getBoundingClientRect()
              const overlaps = iconRect.left < bodyRect.right && bodyRect.left < iconRect.right
                && iconRect.top < bodyRect.bottom && bodyRect.top < iconRect.bottom
              if (overlaps) problems.push(`指标「${name}」的图标压住了正文`)
            }
            // 「被挤成一行一个字」的特征是又窄又高：正文列窄，却被撑出好几行。
            // 只看宽度会误报——flex 卡里的正文本来就收缩到内容宽度。
            if (bodyRect.width < 90 && bodyRect.height > 110) {
              problems.push(`指标「${name}」的正文列只有 ${Math.round(bodyRect.width)}px 宽却有 ${Math.round(bodyRect.height)}px 高，文字被挤成一行一个字`)
            }
          }
          return problems
        })
        record(
          metricDefects.length === 0,
          `${label}：指标卡排版破相 -\n${metricDefects.map((line) => `    ${line}`).join('\n')}`,
        )
      } catch (error) {
        failures.push(`${label}：走查过程中抛出异常 - ${error instanceof Error ? error.message : String(error)}`)
      }

      try {
        await page.screenshot({ path: screenshotPath, fullPage: true })
      } catch (error) {
        failures.push(`${label}：截图失败 - ${error instanceof Error ? error.message : String(error)}`)
      }

      record(
        telemetry.consoleErrors.length === 0,
        `${label}：出现未捕获的 console 错误 -\n${telemetry.consoleErrors.map((line) => `    ${line}`).join('\n')}`,
      )
      record(
        telemetry.pageErrors.length === 0,
        `${label}：出现未捕获的页面异常 -\n${telemetry.pageErrors.map((line) => `    ${line}`).join('\n')}`,
      )
      record(
        telemetry.offOriginRequests.length === 0,
        `${label}：页面发出了演示站以外的网络请求（演示站必须完全离线可用）-\n${telemetry.offOriginRequests.map((line) => `    ${line}`).join('\n')}`,
      )
    }

    await context.close()
  }

  // 认证页不是 React 路由：它们是独立静态页面，这里单独确认结构、演示横幅
  // 和「提交被拦截」这三件事都还在。
  {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    let telemetry = freshTelemetry()
    page.on('console', (message) => {
      if (message.type() !== 'error' || isNoise(message.text())) return
      telemetry.consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => {
      if (isNoise(error.message)) return
      telemetry.pageErrors.push(error.message)
    })
    page.on('request', (request) => {
      const requestUrl = new URL(request.url())
      if (requestUrl.protocol === 'data:' || requestUrl.protocol === 'blob:') return
      if (requestUrl.origin === origin) return
      telemetry.offOriginRequests.push(`${request.method()} ${request.url()}`)
    })

    for (const authPage of demoAuthPages) {
      totalVisits += 1
      telemetry = freshTelemetry()
      const label = `认证页 ${authPage.path}（${authPage.label}）`
      try {
        const response = await page.goto(`${origin}${demoBase}${authPage.path.replace(/^\//, '')}`, {
          waitUntil: 'domcontentloaded',
        })
        record(response?.status() === 200, `${label}：页面未返回 200（实际 ${response?.status() ?? '无响应'}）`)
        const bodyText = await page.locator('body').innerText()
        record(bodyText.includes('静态演示'), `${label}：缺少演示横幅，可能没有注入演示脚本`)
        record(
          !bodyText.includes('undefined'),
          `${label}：页面文本里出现 undefined，说明改写产物有问题`,
        )
        await page.screenshot({ path: join(outputRoot, `auth-${routeSlug(authPage.path)}.png`), fullPage: true })
      } catch (error) {
        failures.push(`${label}：走查过程中抛出异常 - ${error instanceof Error ? error.message : String(error)}`)
      }
      record(
        telemetry.pageErrors.length === 0,
        `${label}：出现未捕获的页面异常 -\n${telemetry.pageErrors.map((line) => `    ${line}`).join('\n')}`,
      )
      record(
        telemetry.offOriginRequests.length === 0,
        `${label}：页面发出了演示站以外的网络请求 -\n${telemetry.offOriginRequests.map((line) => `    ${line}`).join('\n')}`,
      )
    }

    // 「退出登录」必须真的能走到登录页。生产是整页跳到 /openclaw/media/login，
    // 演示站里那个路径不存在，单文件分发时更是只有一个文档——写死路径的那一版，
    // 用户点完只看到 not found，连登录页长什么样都看不到。
    for (const persona of demoPersonas) {
      totalVisits += 1
      telemetry = freshTelemetry()
      const label = `退出登录（${persona.label}）`
      try {
        await page.evaluate(
          ([key, id]) => { try { localStorage.setItem(key, id) } catch { /* 隐私模式 */ } },
          [demoPersonaStorageKey, persona.id] as const,
        )
        await page.goto(`${origin}${demoBase}${persona.defaultRoute.replace(/^\//, '')}`, { waitUntil: 'domcontentloaded' })
        await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 20_000 })
        await page.getByRole('button', { name: '账户菜单' }).click({ timeout: 5_000 })
        await page.getByRole('menuitem', { name: /退出登录/ }).click({ timeout: 5_000 })
        await page.waitForTimeout(1_500)
        const landedOn = new URL(page.url()).pathname
        const isAuthPage = demoAuthPages.some(
          (authPage) => landedOn.replace(/\/$/, '') === `${demoBase}${authPage.path.replace(/^\//, '')}`.replace(/\/$/, ''),
        )
        record(isAuthPage, `${label}：落到了 ${landedOn}，不是任何一个认证页；认证页路径必须跟着部署基址走`)
        // 认证页是构建期复刻出来的独立文档，外壳用 iframe 承载：演示横幅在 iframe 里面，
        // 只看外层 innerText 是看不到的。
        const shellText = await page.locator('body').innerText()
        record(shellText.includes('不鉴权复刻'), `${label}：外壳没有渲染认证页容器（当前正文「${shellText.slice(0, 40)}」）`)
        const frameText = await page
          .frameLocator('iframe')
          .locator('body')
          .innerText()
          .catch(() => '')
        record(
          frameText.includes('静态演示'),
          `${label}：登录页复刻没有渲染出来（iframe 正文「${frameText.slice(0, 40)}」）`,
        )
        await page.screenshot({ path: join(outputRoot, `logout-${persona.id}.png`), fullPage: true })
      } catch (error) {
        failures.push(`${label}：走查过程中抛出异常 - ${error instanceof Error ? error.message : String(error)}`)
      }
    }

    // 登录页在演示站里必须真的能走进工作区。它是唯一没有真实后端可依赖的一屏：
    // 生产靠账号密码提交和 Feishu 授权，静态站两条都发不出请求，选完身份就是死路
    // ——组织那一侧尤其明显：一个永远不会填上的二维码占位框加一行红色的
    // 「等待开始 Feishu 授权」。演示脚本给两种身份各补了一个入口按钮。
    //
    // 这一屏还有个只在真实承载方式下才暴露的坑：外壳用
    // <iframe srcdoc sandbox="allow-scripts"> 装认证页，那是个不透明源——写不了
    // localStorage，也做不了顶层导航。第一版按钮用的 window.top.location.assign
    // 被沙箱静默拦下，工作台被装进了 iframe、外面还套着登录页的壳；直接访问
    // /login 那个静态文件时反而是好的，所以只测「直接打开登录页」会漏掉。
    // 这里走的是和用户一样的路：退出登录 → 在 iframe 里选身份 → 点进入。
    for (const entry of [
      { choiceId: 'personal-choice', personaId: 'personal' },
      { choiceId: 'organization-choice', personaId: 'organization' },
    ] as const) {
      const persona = demoPersonas.find((item) => item.id === entry.personaId)
      if (!persona) continue
      totalVisits += 1
      telemetry = freshTelemetry()
      const label = `登录页入口（${persona.label}）`
      try {
        // 必须走用户那条路：直接访问 /login 拿到的是构建期落盘的**独立静态文件**，
        // 顶层就是认证页本身，没有 iframe，也就测不到沙箱那一层；只有 SPA 退出登录
        // 后 pushState 到 /login，外壳才会用 sandbox iframe 承载它。第一版直接
        // goto /login，两条断言都过，真实流程照样是坏的。
        // 从平台管理员出发，落地身份才有区分度（不是「本来就是这个身份」）。
        await page.evaluate(
          ([key, id]) => { try { localStorage.setItem(key, id) } catch { /* 隐私模式 */ } },
          [demoPersonaStorageKey, 'admin'] as const,
        )
        await page.goto(`${origin}${demoBase}admin/overview`, { waitUntil: 'domcontentloaded' })
        await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 20_000 })
        await page.getByRole('button', { name: '账户菜单' }).click({ timeout: 5_000 })
        await page.getByRole('menuitem', { name: /退出登录/ }).click({ timeout: 5_000 })
        await page.locator('.demo-auth-frame').waitFor({ state: 'visible', timeout: 20_000 })
        const frame = page.frameLocator('.demo-auth-frame')
        await frame.locator(`#${entry.choiceId}`).click({ timeout: 10_000 })
        await frame.locator('.demo-auth-enter-button').first().click({ timeout: 10_000 })
        await page.waitForTimeout(1_200)
        const landedOn = new URL(page.url()).pathname.replace(/\/$/, '')
        const expected = `${demoBase}${persona.defaultRoute.replace(/^\//, '')}`.replace(/\/$/, '')
        record(
          landedOn === expected,
          `${label}：最外层窗口落到了 ${landedOn}，应当是 ${expected}——认证页装在 sandbox iframe 里，` +
            '顶层导航和 localStorage 都被禁，入口只能靠 postMessage 交给外壳执行',
        )
        record(
          (await page.locator('.demo-auth-frame').count()) === 0,
          `${label}：工作台被装进了认证页的 iframe 里，外面还套着一层登录页的壳`,
        )
        const storedPersona = await page.evaluate(
          (key) => { try { return localStorage.getItem(key) } catch { return null } },
          demoPersonaStorageKey,
        )
        record(storedPersona === persona.id, `${label}：身份没有切成 ${persona.id}（当前 ${storedPersona}）`)
        await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 20_000 })
        await page.screenshot({ path: join(outputRoot, `login-entry-${persona.id}.png`), fullPage: true })
      } catch (error) {
        failures.push(`${label}：走查过程中抛出异常 - ${error instanceof Error ? error.message : String(error)}`)
      }
    }

    // 管理员在生产里是普通账号上的一个角色，没有单独的登录入口、也没有单独的 HTML 页，
    // 所以演示站也走个人端那张表单：填演示口令落到平台管理员控制台，填别的落到个人
    // 工作区。这条路径两个坑都踩过：iframe 的 sandbox 少了 allow-forms 时浏览器直接
    // 禁掉表单提交、submit 事件根本不触发（外壳里点「登录」毫无反应）；而顶层导航同样
    // 被沙箱禁着，只能靠 postMessage 交给外壳。所以必须走外壳这条真实路径来验。
    for (const attempt of [
      { identifier: 'p_admin', password: '1qaz2wsx', personaId: 'admin', label: '演示口令' },
      { identifier: 'someone', password: 'whatever', personaId: 'personal', label: '任意账号' },
      { identifier: 'p_admin', password: 'wrong-password', personaId: 'personal', label: '口令不对' },
    ] as const) {
      const persona = demoPersonas.find((item) => item.id === attempt.personaId)
      if (!persona) continue
      totalVisits += 1
      telemetry = freshTelemetry()
      const label = `登录表单（${attempt.label}）`
      try {
        await page.goto(`${origin}${demoBase}organization-workspace`, { waitUntil: 'domcontentloaded' })
        await page.evaluate(
          ([key, id]) => { try { localStorage.setItem(key, id) } catch { /* 隐私模式 */ } },
          [demoPersonaStorageKey, 'organization'] as const,
        )
        await page.goto(`${origin}${demoBase}organization-workspace`, { waitUntil: 'domcontentloaded' })
        await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 20_000 })
        await page.getByRole('button', { name: '账户菜单' }).click({ timeout: 5_000 })
        await page.getByRole('menuitem', { name: /退出登录/ }).click({ timeout: 5_000 })
        await page.locator('.demo-auth-frame').waitFor({ state: 'visible', timeout: 20_000 })
        const frame = page.frameLocator('.demo-auth-frame')
        await frame.locator('#personal-choice').click({ timeout: 10_000 })
        await frame.locator('#identifier').fill(attempt.identifier, { timeout: 10_000 })
        await frame.locator('#password').fill(attempt.password, { timeout: 10_000 })
        await frame.locator('#submit').click({ timeout: 10_000 })
        await page.waitForTimeout(1_500)
        const landedOn = new URL(page.url()).pathname.replace(/\/$/, '')
        const expected = `${demoBase}${persona.defaultRoute.replace(/^\//, '')}`.replace(/\/$/, '')
        record(
          landedOn === expected,
          `${label}：落到了 ${landedOn}，应当是 ${expected}——沙箱少了 allow-forms 时 submit 事件根本不触发，点「登录」会毫无反应`,
        )
        const storedPersona = await page.evaluate(
          (key) => { try { return localStorage.getItem(key) } catch { return null } },
          demoPersonaStorageKey,
        )
        record(storedPersona === persona.id, `${label}：身份没有切成 ${persona.id}（当前 ${storedPersona}）`)
        await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 20_000 })
        await page.screenshot({ path: join(outputRoot, `login-form-${attempt.personaId}-${attempt.label}.png`), fullPage: true })
      } catch (error) {
        failures.push(`${label}：走查过程中抛出异常 - ${error instanceof Error ? error.message : String(error)}`)
      }
    }

    await context.close()
  }
} finally {
  if (browser) await browser.close()
  await new Promise<void>((resolveClose, rejectClose) => {
    server.close((closeError) => (closeError ? rejectClose(closeError) : resolveClose()))
  })
}

if (failures.length > 0) {
  console.error(`静态演示站走查发现 ${failures.length} 处失败：`)
  failures.forEach((failure, index) => console.error(`${index + 1}. ${failure}`))
  process.exitCode = 1
}
console.log(`MediaClaw 静态演示站走查完成：共访问 ${totalVisits} 个页面，截图目录 ${outputRoot}`)
