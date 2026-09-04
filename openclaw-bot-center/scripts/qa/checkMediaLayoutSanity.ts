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
/** 迭代时可以只体检几条路由：MEDIA_LAYOUT_QA_ROUTES=/tracks,/publishing。
 *  留空就是全站（CI 与 build:demo 走的都是全站）。 */
const routeFilter = (process.env.MEDIA_LAYOUT_QA_ROUTES ?? '')
  .split(',')
  .map((entry) => entry.trim())
  .filter(Boolean)

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
  // 行数按**字形行盒**数，不按 height / line-height 估。带内边距的 <td>、有
  // min-height 的徽标，盒子比一行文字高一大截，估出来就是「折成了 2 行」——
  // 两位并行开发的同事都被这个假阳性带偏过：一个把徽标包进省略号容器导致文字
  // 整体消失，一个去加宽根本没折行的数字列。
  const inkRange = document.createRange()
  const lineCount = (element) => {
    const tops = []
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!(node.textContent || '').trim()) continue
      inkRange.selectNodeContents(node)
      for (const rect of inkRange.getClientRects()) {
        if (rect.width <= 0.5 || rect.height <= 0.5) continue
        let known = false
        for (const top of tops) { if (Math.abs(top - rect.top) < 2) { known = true; break } }
        if (!known) tops.push(rect.top)
      }
    }
    return tops.length
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
    const lines = lineCount(leaf.element)
    if (!/\\s/.test(leaf.text) && !/[⺀-鿿]/.test(leaf.text) && leaf.text.length > 6 && lines >= 2) {
      defects.push('单词被截断：' + describe(leaf.element, leaf.text) + ' 折成了 ' + lines + ' 行')
    }
    // 标题折两行是正常的；值槽用标题级字号去装任意长度的字段才是毛病。
    const isHeading = /^H[1-6]$/.test(leaf.element.tagName)
    if (!isHeading && leaf.fontSize >= 20 && lines >= 2) {
      defects.push('大字号折行：' + describe(leaf.element, leaf.text) + ' 字号 ' + Math.round(leaf.fontSize) + 'px 折成了 ' + lines + ' 行，值槽不该用展示级字号')
    }
  }
  // 第五类：多列挤压。容器把列数写死，窄容器里每列只剩百十来像素，值被挤成好几行。
  // 判据故意收紧成「**每一列**都窄」：图标 + 正文这种 44px + 1fr 的网格里也有窄列，
  // 但那是设计意图，不是挤压。
  for (const grid of root.querySelectorAll('*')) {
    // 控件（按钮、标签页）自己有一套排布逻辑，图标 + 文字 + 计数挤在几十像素里是
    // 它们的常态，不是「事实网格被写死列数」这回事。只看内容容器。
    if (grid.closest('button, [role="tab"], [role="tablist"]')) continue
    const gridStyle = getComputedStyle(grid)
    if (gridStyle.display !== 'grid' && gridStyle.display !== 'inline-grid') continue
    // 解析出来的是「179px 179px」这类字符串：Number('179px') 是 NaN，只能 parseFloat。
    const tracks = gridStyle.gridTemplateColumns.split(' ').map((track) => parseFloat(track)).filter((n) => Number.isFinite(n))
    if (tracks.length < 2 || Math.max(...tracks) >= 200) continue
    let worst = null
    for (const leaf of textLeaves) {
      if (leaf.element === grid || !grid.contains(leaf.element)) continue
      if (/^H[1-6]$/.test(leaf.element.tagName)) continue
      if (leaf.element.closest('button, [role="tab"]')) continue
      const lines = lineCount(leaf.element)
      if (lines >= 2 && leaf.rect.width < 200 && (!worst || lines > worst.lines)) worst = { leaf: leaf, lines: lines }
    }
    if (worst) {
      defects.push('多列挤压：' + describe(grid, (grid.textContent || '').trim()) + ' 排了 ' + tracks.length + ' 列、最宽一列也只有 ' + Math.round(Math.max(...tracks)) + 'px，' + describe(worst.leaf.element, worst.leaf.text) + ' 被挤成 ' + worst.lines + ' 行；列数应由容器决定（auto-fit + minmax），窄容器要能退回单列')
    }
  }

  // 第六类：低信息密度。宽卡片里若干短内容各自独占一行，右边留下大片空白。
  // 只看重复出现的列表项（同一父级下至少两个同类兄弟），避免误伤 hero、面板头这些
  // 本来就该留白的地方。
  // 量的是**字本身**占多宽，不是承载它的盒子占多宽：一个块级元素里直接躺着一行短
  // 文字时，盒子铺满整行，字却只有一小截——按盒子算就永远看不出稀疏。用 Range 量
  // 文本节点的实际字形框，再把图标/头像这类非文字内容按元素宽度补上。
  const inkWidth = (element) => {
    let ink = 0
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!(node.textContent || '').trim()) continue
      inkRange.selectNodeContents(node)
      for (const rect of inkRange.getClientRects()) ink += rect.width
    }
    for (const media of element.querySelectorAll('img, svg, canvas')) ink += media.getBoundingClientRect().width
    return ink
  }
  const firstClass = (element) =>
    typeof element.className === 'string' && element.className.trim() ? element.className.trim().split(/\s+/)[0] : ''
  for (const card of root.querySelectorAll('*')) {
    const own = firstClass(card)
    if (!own || !card.parentElement) continue
    const siblings = [...card.parentElement.children].filter((sibling) => firstClass(sibling) === own)
    if (siblings.length < 2) continue
    const cardRect = card.getBoundingClientRect()
    if (cardRect.width < 480) continue
    const rows = [...card.children].filter((child) => child.nodeType === Node.ELEMENT_NODE)
    if (rows.length < 3) continue
    let sparse = 0
    for (const row of rows) {
      const rowRect = row.getBoundingClientRect()
      if (rowRect.height > 40 || rowRect.width < cardRect.width * 0.8) continue
      // 完全没有文字的行（进度条、分隔线、缩略图带）本来就该铺满整行，不算稀疏。
      const ink = inkWidth(row)
      if (ink <= 0 || ink >= rowRect.width * 0.45) continue
      // 只有「事实行」才算：标签 + 值、或者带数字的计数。整行一句散文（眉标题、
      // 小标题、一句说明）短是正常的排版，不是「一条事实占一行」的稀疏。
      let leaves = 0
      for (const leaf of textLeaves) if (row.contains(leaf.element)) leaves += 1
      if (leaves < 2 && !/\d/.test((row.textContent || ''))) continue
      sparse += 1
    }
    if (sparse >= 3) {
      defects.push('低信息密度：' + describe(card, (card.textContent || '').trim()) + ' 宽 ' + Math.round(cardRect.width) + 'px，其中 ' + sparse + ' 行短内容各自独占一整行、文字占不到四成宽；短事实应排成一行（.mg-meta）而不是一条一行')
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

/** 逐个交互状态体检，而不是只看首屏。
 *
 *  破相往往藏在**默认看不到的那一屏**：/tracks 的「赛道概览」和「对标账号」是
 *  另外两个标签页，/publishing 的详情要先选中一个发布包才会有内容。只量首屏的
 *  门禁会把这些页面判成绿的——用户看到的却正是那几屏。
 *
 *  切换开销压得很低：标签页切换是纯客户端的，等一小会儿即可，不必再走一遍
 *  settle() 的 DOM 收敛循环。 */
async function sweep(page: Page): Promise<Array<[string, string[]]>> {
  const results: Array<[string, string[]]> = [['', (await page.evaluate(COLLECT_DEFECTS)) as string[]]]

  // 先把标签名抄下来再逐个点：切换标签会换掉整组标签（次级筛选标签只在某一个
  // 主标签下存在），按下标去点第二轮就会指向一个已经不存在的元素。
  const labels = [
    ...new Set(
      (await page.locator('[role="tab"]').allTextContents())
        .map((text) => text.trim())
        .filter(Boolean),
    ),
  ].slice(0, 8)
  for (const label of labels) {
    const tab = page.getByRole('tab', { name: label, exact: true }).first()
    if ((await tab.count()) === 0) continue
    const selected = await tab.getAttribute('aria-selected').catch(() => null)
    if (selected === 'true') continue
    const switched = await tab.click({ timeout: 3_000 }).then(() => true).catch(() => false)
    if (!switched) continue
    // 固定 sleep 会量到半成品：切换后往往还要向浏览器内假后端要一次数据。
    await settle(page)
    results.push([label.slice(0, 12), (await page.evaluate(COLLECT_DEFECTS)) as string[]])
  }

  // 主栏 + 检视栏的页面：不选中任何一条时检视栏只有空状态，真正的排版在选中之后。
  // 「第一个按钮」不行——主栏顶上往往是刷新之类的图标按钮，点它什么也不会选中，
  // 门禁就以为自己看过详情栏了。挑第一个**带文字**、且不在标签栏/面板头里的控件。
  const ROW_SELECTOR = '[data-page-primary] button, [data-page-primary] tr[tabindex]'
  if ((await page.locator('[data-page-inspector]').count()) > 0) {
    const rowIndex = (await page.evaluate((selector) => {
      const candidates = [...document.querySelectorAll(selector)]
      for (let index = 0; index < candidates.length; index += 1) {
        const candidate = candidates[index]
        if (candidate.closest('[role="tablist"]') || candidate.closest('.mg-panel-head')) continue
        if ((candidate.textContent || '').trim().length < 2) continue
        return index
      }
      return -1
    }, ROW_SELECTOR)) as number
    if (rowIndex >= 0) {
      const opened = await page
        .locator(ROW_SELECTOR)
        .nth(rowIndex)
        .click({ timeout: 3_000 })
        .then(() => true)
        .catch(() => false)
      if (opened) {
        await settle(page)
        results.push(['选中首条', (await page.evaluate(COLLECT_DEFECTS)) as string[]])
      }
    }
  }

  return results
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
          if (routeFilter.length && !routeFilter.includes(route.path)) continue
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
          for (const [state, defects] of await sweep(page)) {
            checked += 1
            const where = state ? `${route.path}〔${state}〕` : route.path
            for (const defect of defects) failures.push(`${where} @${width}px（${persona.label}）：${defect}`)
          }
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
  console.log(`qa:media-layout-sanity: PASS 页面状态体检 ${checked} 次（${WIDTHS.join(' / ')}px），无重叠、无单词截断、无大字号折行、视口高度契约无偏差`)
}

await run()
