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
    // 长标题折行是正常的排版；**八个字以内、中间没有空格**的短标题折行不是——那是
    // 容器把它挤到放不下一个词的宽度了。/archives 的「删除云端归档」曾被隔壁那句
    // 说明挤成「删除云 / 端归档」：六个字从中间劈开，读起来像两个词。
    if (isHeading && !/\s/.test(leaf.text) && leaf.text.length <= 8 && lines >= 2) {
      defects.push('短标题被折行：' + describe(leaf.element, leaf.text) + ' 只有 ' + leaf.text.length + ' 个字却折成了 ' + lines + ' 行——容器把它挤到放不下一个词；该让挤它的邻居先换行（flex-wrap）或给标题 white-space: nowrap，而不是把标题劈开')
    }
  }
  // 第五类：被永久裁掉的内容。祖先把它裁掉了，而且没有任何一层能滚出来——
  // 用户没有任何办法看到这段文字。这一类本次已经真实发生过两回：/overview 的
  // Media Agent 面板有 377px 内容被固定高度的网格裁掉且滚动条根本不出现，
  // /usage-billing 在 900px 下指标带被裁。滚出可视区（祖先能滚）不算，
  // display:none / visibility:hidden 前面已经排除。
  for (const leaf of textLeaves) {
    if (leaf.clipped.right - leaf.clipped.left > 1 && leaf.clipped.bottom - leaf.clipped.top > 1) continue
    let reachable = false
    for (let parent = leaf.element.parentElement; parent && !reachable; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent)
      const scrollsY = (parentStyle.overflowY === 'auto' || parentStyle.overflowY === 'scroll') && parent.scrollHeight > parent.clientHeight + 1
      const scrollsX = (parentStyle.overflowX === 'auto' || parentStyle.overflowX === 'scroll') && parent.scrollWidth > parent.clientWidth + 1
      if (scrollsY || scrollsX) reachable = true
    }
    if (!reachable) {
      defects.push('内容被永久裁掉：' + describe(leaf.element, leaf.text) + ' 被祖先裁掉了，而且没有任何一层能滚出来——用户没有办法看到它')
    }
  }

  // 第五类：多列挤压。容器把列数写死，窄容器里每列只剩百十来像素，值被挤成好几行。
  // 判据故意收紧成「**每一列**都窄」：图标 + 正文这种 44px + 1fr 的网格里也有窄列，
  // 但那是设计意图，不是挤压。
  for (const grid of root.querySelectorAll('*')) {
    // 控件（按钮、标签页）自己有一套排布逻辑，图标 + 文字 + 计数挤在几十像素里是
    // 它们的常态，不是「事实网格被写死列数」这回事。只看内容容器。
    if (grid.closest('button, [role="tab"], [role="tablist"]')) continue
    // 共享原语（.mg-metric-grid / .mg-facts / .mg-metric）本来就是按容器算列数的，
    // 这条判定的建议正是「改用它们」——再去指着它们说「列数应由容器决定」没有意义。
    // 它们真要出问题也是另一回事（minmax 的下限定得太小），那是一次设计判断，
    // 不该由这条判定来替人做主。
    if (grid.closest('.mg-metric-grid, .mg-facts, .mg-metric')) continue
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

  // 第八类：分隔符被甩在行尾。一串短事实用居中圆点连成一行时，圆点是**下一项的
  // 引导**；它一旦成为某一行最右边的一点墨，读出来就变成了左边那项的后缀，右边那项
  // 也失去了分隔（/tracks 的「小红书 ·」/「更新于 3 天前」）。修法是把圆点和它右边
  // 那项包进同一个 flex 子项，让它们一起折行。
  //
  // 判据量的是**字形**不是元素：找出分隔符那一个字的行盒，再看同一行里它右边还有没有
  // 别的墨。这样「圆点和自己那项一起换行」（正确写法）不会被误判——那时圆点右边永远
  // 还有自己那项的字。行的范围限定在承载行盒的那个祖先里，避免把并排另一栏的文字
  // 算成「同一行」。
  //
  // 破折号（— –）不在判定范围内：区间「2026/8/28 — 2026/9/22」按排版惯例本来就在
  // 破折号之后折行，行尾那一横是「还没完」的信号，不是被甩下的分隔符。已经实截图
  // 核对过 /business 的「有效期」两行，读起来是对的。
  const separatorRange = document.createRange()
  const seenSeparators = new Set()
  const inkOn = (container) => {
    const rects = []
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!(node.textContent || '').trim()) continue
      separatorRange.selectNodeContents(node)
      for (const rect of separatorRange.getClientRects()) {
        if (rect.width <= 0.5 || rect.height <= 0.5) continue
        rects.push(rect)
      }
    }
    return rects
  }
  const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let node = textWalker.nextNode(); node; node = textWalker.nextNode()) {
    const raw = node.textContent || ''
    if (!/[·•|／]/.test(raw)) continue
    const owner = node.parentElement
    if (!owner) continue
    const ownerStyle = getComputedStyle(owner)
    if (ownerStyle.visibility === 'hidden' || ownerStyle.opacity === '0') continue
    // 承载行盒的是**祖先**，不是分隔符自己那个元素：flex 子项会被块化，所以不能靠
    // display 是不是 inline 来判断。往上找第一个「自己身上不止一处墨」的祖先——
    // 那正是这一行的排布容器；再往上就会把并排另一栏的文字算进同一行。
    let flow = owner
    let flowInk = []
    for (let hop = 0; hop < 6; hop += 1) {
      if (!flow.parentElement) break
      flow = flow.parentElement
      flowInk = inkOn(flow)
      if (flowInk.length >= 2) break
    }
    if (flowInk.length < 2) continue
    for (let index = 0; index < raw.length; index += 1) {
      if (!/[·•|／]/.test(raw[index])) continue
      separatorRange.setStart(node, index)
      separatorRange.setEnd(node, index + 1)
      const glyph = separatorRange.getBoundingClientRect()
      if (glyph.width <= 0.5 || glyph.height <= 0.5) continue
      const middle = (glyph.top + glyph.bottom) / 2
      let inkToTheRight = false
      let lineCount = 0
      for (const rect of flowInk) {
        if (rect.top > middle || rect.bottom < middle) continue
        lineCount += 1
        if (rect.right > glyph.right + 0.5) { inkToTheRight = true; break }
      }
      // 整个容器只有一行时，行尾的分隔符是内容本身末尾多了一个符号，不是折行造成的。
      if (inkToTheRight || lineCount === 0) continue
      let wrapped = false
      for (const rect of flowInk) { if (rect.top > glyph.bottom - 1) { wrapped = true; break } }
      if (!wrapped) continue
      const key = describe(owner, raw.trim())
      if (seenSeparators.has(key)) break
      seenSeparators.add(key)
      defects.push('分隔符被甩在行尾：' + key + ' 里的「' + raw[index] + '」成了这一行最右边的一点墨，' +
        '它引导的是右边那一项，折行后却留在了上一行末尾，读起来变成左边那项的后缀；把分隔符和它右边那一项包进同一个 flex 子项，让它们一起折行')
      break
    }
  }

  // 第七类：面板底部空转。面板的高度来自视口高度契约（被拉满一列），内容却只填了
  // 上半截——剩下的一大片不是页面留白，是**一块画了边框、铺了底色的空盒子**，看上去
  // 像加载失败。/reviews 的「复盘检查器」就是这样：把三个小节头压紧之后，内容少了
  // 56px，空白反而从 88px 涨到 144px——因为高度是 100dvh 减出来的，跟内容无关。
  // 修法不是往里塞东西，是让这类面板按内容定高（--mg-rail-align: start 配
  // --mg-rail-fill: auto，再用 max-height 保留「内容超长时自己滚」）。
  const idlePanels = []
  for (const panel of root.querySelectorAll('[data-component="mg-panel"], [data-page-terminal-surface]')) {
    const panelRect = panel.getBoundingClientRect()
    if (panelRect.height < 260 || panelRect.width < 1) continue
    // 里面还有滚不完的内容，说明高度是被内容用满的，底部的空只是没滚到。
    if (panel.scrollHeight > panel.clientHeight + 1) continue
    const panelStyle = getComputedStyle(panel)
    // 只看真的画成了一块面（有边框或自己的底色）的盒子：纯布局容器的空白就是页面留白。
    const painted = parseFloat(panelStyle.borderTopWidth) > 0 || parseFloat(panelStyle.borderBottomWidth) > 0 ||
      (panelStyle.backgroundColor !== 'rgba(0, 0, 0, 0)' && panelStyle.backgroundColor !== 'transparent')
    if (!painted) continue
    let inkTop = Infinity
    let inkBottom = -Infinity
    const walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!(node.textContent || '').trim()) continue
      inkRange.selectNodeContents(node)
      for (const rect of inkRange.getClientRects()) {
        if (rect.width <= 0.5 || rect.height <= 0.5) continue
        inkTop = Math.min(inkTop, rect.top)
        inkBottom = Math.max(inkBottom, rect.bottom)
      }
    }
    for (const media of panel.querySelectorAll('img, svg, canvas, hr, input, progress')) {
      const mediaRect = media.getBoundingClientRect()
      if (mediaRect.width <= 0.5 || mediaRect.height <= 0.5) continue
      inkTop = Math.min(inkTop, mediaRect.top)
      inkBottom = Math.max(inkBottom, mediaRect.bottom)
    }
    if (!Number.isFinite(inkBottom)) continue
    const floor = panelRect.bottom - parseFloat(panelStyle.borderBottomWidth) - parseFloat(panelStyle.paddingBottom)
    const ceiling = panelRect.top + parseFloat(panelStyle.borderTopWidth) + parseFloat(panelStyle.paddingTop)
    const tail = floor - inkBottom
    // 内容整体居中（空状态、占位提示）是设计意图：上下留白差不多就不算空转。
    if (Math.abs(tail - (inkTop - ceiling)) < 24) continue
    if (tail < 88 || tail < panelRect.height * 0.18) continue
    idlePanels.push({ panel: panel, tail: tail, rect: panelRect })
  }
  for (const entry of idlePanels) {
    // 外层面板与内层面板底边挨着时只报最里面那个，否则一处空白报三遍。
    let inner = false
    for (const other of idlePanels) {
      if (other !== entry && entry.panel.contains(other.panel)) { inner = true; break }
    }
    if (inner) continue
    defects.push('面板底部空转：' + describe(entry.panel, (entry.panel.textContent || '').trim()) + ' 高 ' + Math.round(entry.rect.height) + 'px，内容到底还剩 ' + Math.round(entry.tail) + 'px 的空盒子——高度是视口算出来的、与内容无关；该让它按内容定高（--mg-rail-align: start + --mg-rail-fill: auto，再用 max-height 保留内部滚动），而不是往里填东西')
  }

  // 第八类：徽标被拉变形。徽标是内容尺寸的小药丸；一旦它成了 grid item，
  // inline-flex 会被块化、flex: 0 0 auto 随之失效，父级 align-items / justify-items
  // 的默认值 normal 就等于 stretch——/organization-workspace 的文档页里「只读镜像」
  // 因此被 .mg-hero 的 330px 轨道撑成了 330×112 的大色块。量的是「盒子内容区比
  // 里面那点字形大出多少」，不看具体是哪个属性把它拉开的。
  for (const chip of root.querySelectorAll('.mg-badge, [data-component="mg-badge"]')) {
    const chipRect = chip.getBoundingClientRect()
    if (chipRect.width < 1 || chipRect.height < 1) continue
    const chipStyle = getComputedStyle(chip)
    if (chipStyle.visibility === 'hidden' || chipStyle.display === 'none') continue
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity
    const chipWalker = document.createTreeWalker(chip, NodeFilter.SHOW_TEXT)
    for (let node = chipWalker.nextNode(); node; node = chipWalker.nextNode()) {
      if (!(node.textContent || '').trim()) continue
      inkRange.selectNodeContents(node)
      for (const rect of inkRange.getClientRects()) {
        if (rect.width <= 0.5 || rect.height <= 0.5) continue
        left = Math.min(left, rect.left); right = Math.max(right, rect.right)
        top = Math.min(top, rect.top); bottom = Math.max(bottom, rect.bottom)
      }
    }
    for (const media of chip.querySelectorAll('img, svg, canvas')) {
      const mediaRect = media.getBoundingClientRect()
      if (mediaRect.width <= 0.5 || mediaRect.height <= 0.5) continue
      left = Math.min(left, mediaRect.left); right = Math.max(right, mediaRect.right)
      top = Math.min(top, mediaRect.top); bottom = Math.max(bottom, mediaRect.bottom)
    }
    if (!Number.isFinite(right)) continue
    const inkW = right - left, inkH = bottom - top
    const boxW = chipRect.width - parseFloat(chipStyle.paddingLeft) - parseFloat(chipStyle.paddingRight) -
      parseFloat(chipStyle.borderLeftWidth) - parseFloat(chipStyle.borderRightWidth)
    const boxH = chipRect.height - parseFloat(chipStyle.paddingTop) - parseFloat(chipStyle.paddingBottom) -
      parseFloat(chipStyle.borderTopWidth) - parseFloat(chipStyle.borderBottomWidth)
    const tallerThanInk = boxH > Math.max(inkH * 2, inkH + 24)
    const widerThanInk = boxW > Math.max(inkW * 2, inkW + 80)
    if (tallerThanInk || widerThanInk) {
      defects.push('徽标被拉变形：' + describe(chip, (chip.textContent || '').trim()) + ' 被容器拉成 ' +
        Math.round(chipRect.width) + '×' + Math.round(chipRect.height) + 'px，里面的字只有 ' +
        Math.round(inkW) + '×' + Math.round(inkH) + 'px——徽标是内容尺寸的小药丸，成为 grid/flex 子项后 stretch 会把它撑开；用 fit-content 钉住尺寸，别让它去填格子')
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
  // 字体没加载完就量，量到的是回退字体的度量——同一份页面，单跑一条路由（字体还没
  // 缓存）和全站跑（前面的路由已经把字体拉下来了）会得出不同的折行结论，门禁就成了
  // 掷骰子。等 document.fonts.ready 之后再量。
  await page.evaluate('document.fonts ? document.fonts.ready.then(() => true) : true').catch(() => undefined)
  let previous = -1
  for (let attempt = 0; attempt < 12; attempt += 1) {
    await page.waitForTimeout(350)
    const size = await page.evaluate('document.querySelectorAll("*").length') as number
    if (size === previous) {
      await page.evaluate('document.fonts ? document.fonts.ready.then(() => true) : true').catch(() => undefined)
      return
    }
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


/** 长列表压力：把页面里最大的一组「重复兄弟」复制到 8 倍，再查一遍有没有内容被
 *  永久裁掉。演示数据每张表只有两三行，凡是「装不下就把行吞掉、而且滚不出来」的
 *  页面在正常数据量下全是绿的——/invites 就是这样：4 条成员看着好好的，克隆到
 *  32 条之后 1598px 的表格内容被 .recordsPanel 的 overflow: hidden 裁掉，
 *  .tableViewport 虽然写了 overflow-y: auto 却因为自己就有内容那么高而永远不滚。
 *  真实租户里成员多了就是「第 5 个人开始看不见」。
 *
 *  这一遍只在最宽的一档跑一次：它要的是「高度契约链路是否留了内部滚动」，
 *  与断点无关，四档跑四遍只是四倍的时间。 */
const STRESS_LONG_LIST = `(() => {
  const root = document.querySelector('.media-content') || document.body
  let best = null
  for (const element of root.querySelectorAll('*')) {
    const kids = [...element.children]
    if (kids.length < 2) continue
    const tag = kids[0].tagName, cls = kids[0].className
    let uniform = true
    for (const kid of kids) if (kid.tagName !== tag || kid.className !== cls) { uniform = false; break }
    if (!uniform) continue
    const rect = element.getBoundingClientRect()
    if (rect.height < 60) continue
    const score = kids.length * rect.height
    if (!best || score > best.score) best = { element: element, score: score }
  }
  if (!best) return null
  const kids = [...best.element.children]
  for (let round = 0; round < 7; round += 1) for (const kid of kids) best.element.appendChild(kid.cloneNode(true))
  return best.element.children.length
})()`

const COLLECT_CLIPPED = `(() => {
  const defects = []
  const root = document.querySelector('.media-content') || document.body
  const seen = new Set()
  for (const element of root.querySelectorAll('*')) {
    let own = false
    for (const node of element.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && (node.textContent || '').trim().length > 0) { own = true; break }
    }
    if (!own) continue
    const text = (element.textContent || '').trim()
    if (!text) continue
    const rect = element.getBoundingClientRect()
    if (rect.width <= 1 || rect.height <= 1) continue
    const style = getComputedStyle(element)
    if (style.visibility === 'hidden' || style.opacity === '0') continue
    let top = rect.top, bottom = rect.bottom, left = rect.left, right = rect.right
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent)
      const parentRect = parent.getBoundingClientRect()
      if (parentStyle.overflowY !== 'visible') { top = Math.max(top, parentRect.top); bottom = Math.min(bottom, parentRect.bottom) }
      if (parentStyle.overflowX !== 'visible') { left = Math.max(left, parentRect.left); right = Math.min(right, parentRect.right) }
    }
    if (bottom - top > 1 && right - left > 1) continue
    let reachable = false
    for (let parent = element.parentElement; parent && !reachable; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent)
      if ((parentStyle.overflowY === 'auto' || parentStyle.overflowY === 'scroll') && parent.scrollHeight > parent.clientHeight + 1) reachable = true
      if ((parentStyle.overflowX === 'auto' || parentStyle.overflowX === 'scroll') && parent.scrollWidth > parent.clientWidth + 1) reachable = true
    }
    if (reachable) continue
    // 同一类行会重复上百条，按「类名 + 标签」收敛，报一条就够定位。
    const key = element.tagName + '.' + (typeof element.className === 'string' ? element.className : '')
    if (seen.has(key)) continue
    seen.add(key)
    defects.push('长列表压力：把列表复制到 8 倍之后，<' + element.tagName.toLowerCase() +
      (typeof element.className === 'string' && element.className.trim() ? '.' + element.className.trim().split(/\\s+/)[0] : '') +
      '>「' + text.slice(0, 14) + '」被祖先裁掉了，而且没有任何一层能滚出来——演示数据只有两三行时看不出来，真实数据一多，用户就再也看不到后面的记录了')
  }
  return defects
})()`

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
          if (width === WIDTHS[0]) {
            // sweep() 之后 DOM 已经切到了别的标签页，先回到首屏再压，结论才可复现。
            await page.goto(url, { waitUntil: 'domcontentloaded' })
            if (await page.locator('.media-content').first().waitFor({ state: 'visible', timeout: 15_000 }).then(() => true).catch(() => false)) {
              await settle(page)
              if ((await page.evaluate(STRESS_LONG_LIST)) !== null) {
                await page.waitForTimeout(120)
                checked += 1
                for (const defect of (await page.evaluate(COLLECT_CLIPPED)) as string[]) {
                  failures.push(`${route.path}〔长列表压力〕 @${width}px（${persona.label}）：${defect}`)
                }
              }
            }
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
  console.log(`qa:media-layout-sanity: PASS 页面状态体检 ${checked} 次（${WIDTHS.join(' / ')}px），无重叠、无单词截断、无大字号折行、无短标题被折行、无分隔符被甩在行尾、视口高度契约无偏差、无永久裁切、无多列挤压、无低信息密度、无面板底部空转、无徽标被拉变形，长列表压力下无内容被吞`)
}

await run()
