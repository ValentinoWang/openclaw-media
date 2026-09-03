/** 排版体检门禁：在多个宽度下把演示站的每个页面真渲染出来，量三类肉眼一看就知道
 *  「坏了」但类型检查和单元测试永远看不见的破相。
 *
 *    1. 文字块互相重叠——两段都带文字的元素框相交（平台徽标压住标题、图标压住数字）。
 *    2. 单个词被拦腰截断——不含空格的整串（ID、时间戳、URL）被折成多行，
 *       通常是 overflow-wrap: anywhere / word-break: break-all 一路继承下来的。
 *    3. 大字号折行——非标题的值槽用了展示级字号去装任意长度的内容，一折行就散架。
 *
 *  之所以按「宽度」而不是「视口断点」跑：这些页面里有大量窄容器（详情侧栏、两栏
 *  布局的次列），视口很宽时它们照样很窄，破相就发生在那里。
 */
import { createServer as createHttpServer } from 'node:http'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { extname, resolve, sep } from 'node:path'
import { chromium, type Page } from 'playwright'

import { demoRouteGroups } from '../../src/demo/demoRoutes'
import { demoPersonas } from '../../src/demo/demoPersonas'

const projectRoot = resolve(import.meta.dirname, '..', '..')
/** 默认体检 dist-demo；并行开发时可以用 MEDIA_LAYOUT_QA_DIST 指到自己的产物目录，
 *  免得两个人同时重建 dist-demo 互相踩。 */
const distDemoRoot = resolve(projectRoot, process.env.MEDIA_LAYOUT_QA_DIST ?? 'dist-demo')
/** 部署基址从产物里反推：build:demo 默认是 /openclaw/media-demo/，
 *  单文件分发时是 /。写死一个就会在另一种构建下加载不到 JS——页面一片空白，
 *  门禁却「全绿」，比没有门禁更糟。 */
const demoBase = (() => {
  const shell = readFileSync(resolve(distDemoRoot, 'index.html'), 'utf8')
  const assetPath = /(?:src|href)="([^"]*\/assets\/index-[^"]*)"/.exec(shell)?.[1]
  if (!assetPath) throw new Error('无法从 dist-demo/index.html 反推部署基址，解析逻辑需要更新')
  return assetPath.slice(0, assetPath.indexOf('assets/'))
})()
/** 逐个宽度都要体检：窄列的破相在宽视口下同样存在，反过来也一样。 */
const WIDTHS = [1440, 1180, 900, 430] as const

if (!existsSync(distDemoRoot)) {
  throw new Error('dist-demo 不存在，请先运行 npm run build:demo')
}

function contentTypeFor(filePath: string): string {
  const extension = extname(filePath)
  if (extension === '.html') return 'text/html; charset=utf-8'
  if (extension === '.js' || extension === '.mjs') return 'text/javascript; charset=utf-8'
  if (extension === '.css') return 'text/css; charset=utf-8'
  if (extension === '.json') return 'application/json; charset=utf-8'
  if (extension === '.svg') return 'image/svg+xml'
  if (extension === '.woff2') return 'font/woff2'
  if (extension === '.png') return 'image/png'
  return 'application/octet-stream'
}

function resolveStaticFile(relativePath: string): string | null {
  // 请求路径带着部署基址（默认 /openclaw/media-demo/），产物却是直接落在
  // dist-demo 根下的，先把基址剥掉再找文件——否则每个页面都 404，浏览器拿到空
  // 文档，门禁只会报「没渲染出主内容区」，看不出真正原因。
  const withoutBase = relativePath.startsWith(demoBase)
    ? relativePath.slice(demoBase.length)
    : relativePath
  const safeRelative = withoutBase.replace(/^\/+/, '')
  const exact = resolve(distDemoRoot, safeRelative)
  const within = (candidate: string) => candidate === distDemoRoot || candidate.startsWith(`${distDemoRoot}${sep}`)
  if (within(exact) && existsSync(exact) && statSync(exact).isFile()) return exact
  const asDirectory = resolve(distDemoRoot, safeRelative, 'index.html')
  if (within(asDirectory) && existsSync(asDirectory) && statSync(asDirectory).isFile()) return asDirectory
  return null
}

const server = createHttpServer((request, response) => {
  const url = new URL(request.url ?? '/', 'http://layout-qa.invalid')
  const filePath = resolveStaticFile(decodeURIComponent(url.pathname))
  if (!filePath) {
    response.writeHead(404).end('not found')
    return
  }
  response.writeHead(200, { 'content-type': contentTypeFor(filePath) }).end(readFileSync(filePath))
})

/** 页面内的体检逻辑。以源码字符串交给浏览器执行：tsx 会给函数注入 __name 之类的
 *  辅助符号，序列化进页面后会直接 ReferenceError。 */
const COLLECT_DEFECTS = `(() => {
  const defects = []
  const root = document.querySelector('.media-content') || document.body
  const textLeaves = []
  for (const element of root.querySelectorAll('*')) {
    let own = false
    for (const node of element.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && (node.textContent || '').trim().length > 0) { own = true; break }
    }
    if (!own) continue
    const text = (element.textContent || '').trim()
    if (!text) continue
    let rect = element.getBoundingClientRect()
    if (rect.width <= 1 || rect.height <= 1) continue
    // 祖先的 overflow 会把元素裁掉，但 getBoundingClientRect 仍然返回未裁位置——
    // 不跟着裁，横向滚动表格里的单元格就会和隔壁面板「重叠」，全是假阳性。
    let clipped = { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom }
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent)
      if (parentStyle.overflowX === 'visible' && parentStyle.overflowY === 'visible') continue
      const parentRect = parent.getBoundingClientRect()
      if (parentStyle.overflowX !== 'visible') {
        clipped.left = Math.max(clipped.left, parentRect.left)
        clipped.right = Math.min(clipped.right, parentRect.right)
      }
      if (parentStyle.overflowY !== 'visible') {
        clipped.top = Math.max(clipped.top, parentRect.top)
        clipped.bottom = Math.min(clipped.bottom, parentRect.bottom)
      }
    }
    // 被祖先裁掉（或滚出可视区）的元素不参与「重叠」判定——那只是没滚到而已；
    // 但「折行 / 截断」与滚动位置无关，仍然要量，否则滚动面板里的破相永远抓不到。
    const visible = clipped.right - clipped.left > 1 && clipped.bottom - clipped.top > 1
    const style = getComputedStyle(element)
    if (style.visibility === 'hidden' || style.opacity === '0') continue
    const fontSize = parseFloat(style.fontSize) || 16
    const lineHeight = parseFloat(style.lineHeight) || fontSize * 1.4
    textLeaves.push({ element, rect, text, fontSize, lineHeight, visible, clipped })
  }
  const describe = (element, text) => {
    const cls = typeof element.className === 'string' && element.className.trim() ? '.' + element.className.trim().split(/\\s+/)[0] : ''
    return '<' + element.tagName.toLowerCase() + cls + '>「' + text.slice(0, 18) + '」'
  }
  for (let i = 0; i < textLeaves.length; i += 1) {
    for (let j = i + 1; j < textLeaves.length; j += 1) {
      const a = textLeaves[i], b = textLeaves[j]
      if (!a.visible || !b.visible) continue
      if (a.element.contains(b.element) || b.element.contains(a.element)) continue
      const overlapX = Math.min(a.clipped.right, b.clipped.right) - Math.max(a.clipped.left, b.clipped.left)
      const overlapY = Math.min(a.clipped.bottom, b.clipped.bottom) - Math.max(a.clipped.top, b.clipped.top)
      if (overlapX > 4 && overlapY > 4) {
        defects.push('文字重叠：' + describe(a.element, a.text) + ' 与 ' + describe(b.element, b.text) + ' 相交 ' + Math.round(overlapX) + '×' + Math.round(overlapY) + 'px')
      }
    }
  }
  for (const leaf of textLeaves) {
    const lines = Math.round(leaf.rect.height / leaf.lineHeight)
    if (!/\\s/.test(leaf.text) && !/[⺀-鿿]/.test(leaf.text) && leaf.text.length > 6 && lines >= 2) {
      defects.push('单词被截断：' + describe(leaf.element, leaf.text) + ' 折成了 ' + lines + ' 行')
    }
    // 标题折两行是正常的；值槽用标题级字号去装任意长度的字段才是毛病。
    const isHeading = /^H[1-6]$/.test(leaf.element.tagName)
    if (!isHeading && leaf.fontSize >= 20 && lines >= 2) {
      defects.push('大字号折行：' + describe(leaf.element, leaf.text) + ' 字号 ' + Math.round(leaf.fontSize) + 'px 折成了 ' + lines + ' 行，值槽不该用展示级字号')
    }
  }
  // 第四类：视口高度契约算得对不对。契约把主工作区钉成
  // 100dvh - 顶栏 - 内容壳上下内边距；量的是**主工作区自己的底边**，加上内容壳
  // 的下内边距应当正好落在视口底边。这样只对「常量和实际内边距对不上」敏感，
  // 不会被「内容比一屏长、整页本来就要滚」这种正常情况误伤。
  const railForShell = document.querySelector('[data-page-layout="persistent-rail"]')
  const shell = railForShell ? railForShell.closest('.fidelity-page') : null
  if (shell && getComputedStyle(shell).getPropertyValue('--mg-rail-shell-height').trim() !== 'auto') {
    const contentShell = shell.closest('.media-content')
    const padBottom = contentShell ? parseFloat(getComputedStyle(contentShell).paddingBottom) || 0 : 0
    const slack = Math.round(shell.getBoundingClientRect().bottom + padBottom - window.innerHeight)
    if (Math.abs(slack) > 1) {
      defects.push('视口高度契约算错：主工作区底边加上内容壳的下内边距比视口' + (slack > 0 ? '低' : '高') + ' ' + Math.abs(slack) + 'px，--mg-shell-content-inset 与外壳实际上下内边距对不上')
    }
  }
  return defects
})()`

/** 等页面真正渲染完再量：这些页面的数据由浏览器内假后端异步给出，固定 sleep 会
 *  量到半成品——侧栏还没出来，门禁就「通过」了。这里等 DOM 规模连续两次不变。 */
async function settle(page: Page): Promise<void> {
  let previous = -1
  for (let attempt = 0; attempt < 12; attempt += 1) {
    await page.waitForTimeout(350)
    const size = await page.evaluate('document.querySelectorAll("*").length') as number
    if (size === previous) return
    previous = size
  }
}

async function run(): Promise<void> {
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done))
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('无法确定体检服务器端口')
  const origin = `http://127.0.0.1:${address.port}`
  const browser = await chromium.launch()
  const failures: string[] = []
  let checked = 0

  try {
    for (const group of demoRouteGroups) {
      const persona = demoPersonas.find((item) => item.id === group.persona) ?? demoPersonas[0]!
      for (const width of WIDTHS) {
        const context = await browser.newContext({ viewport: { width, height: 900 } })
        await context.addInitScript((id: string) => {
          try { localStorage.setItem('mediaclaw-demo-persona', id) } catch { /* 隐私模式 */ }
        }, persona.id)
        const page: Page = await context.newPage()
        for (const route of group.routes) {
          const url = `${origin}${demoBase}${route.path.replace(/^\//, '')}`
          // 首屏偶发起不来（构建产物刚落盘、浏览器冷启动），重试一次再判定：
          // 会抖的门禁比没有门禁更糟——它会教人忽略红灯。
          let booted = false
          for (let attempt = 0; attempt < 2 && !booted; attempt += 1) {
            await page.goto(url, { waitUntil: 'domcontentloaded' })
            booted = await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 15_000 }).then(() => true).catch(() => false)
          }
          if (!booted) {
            failures.push(`${route.path} @${width}px（${persona.label}）：重试后仍未渲染出主内容区，体检无从谈起`)
            continue
          }
          await settle(page)
          const defects = (await page.evaluate(COLLECT_DEFECTS)) as string[]
          checked += 1
          for (const defect of defects) failures.push(`${route.path} @${width}px（${persona.label}）：${defect}`)
        }
        await context.close()
      }
    }
  } finally {
    await browser.close()
    await new Promise<void>((done) => server.close(() => done()))
  }

  if (failures.length) {
    const unique = [...new Set(failures)]
    throw new Error(`排版体检发现 ${unique.length} 处问题：\n- ${unique.join('\n- ')}`)
  }
  console.log(`qa:media-layout-sanity: PASS 页面渲染 ${checked} 次（${WIDTHS.join(' / ')}px），无重叠、无单词截断、无大字号折行、视口高度契约无偏差`)
}

await run()
