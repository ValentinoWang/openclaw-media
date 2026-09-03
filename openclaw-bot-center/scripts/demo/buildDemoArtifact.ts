/** 把演示站打成**一个** HTML 文件，用于发布成 Artifact 这类只托管单文档的场合。
 *
 *  单文件分发有三条硬约束，这个脚本逐条兜住，并在最后自检：
 *    1. 只有一个文档，没有 /assets/ 可取——CSS 和 JS 必须内联；
 *    2. 本地 woff2 字体同样取不到，@font-face 留着只会让首屏卡在字体超时上，
 *       所以整段剔除，改挂 Google Fonts（同样两个字族，字形一致）；
 *    3. 子路径不存在，所以部署基址必须是 /（演示站的客户端导航已经按 BASE_URL
 *       走 pushState，基址对不上会导致封面页跳转到 404）。
 *
 *  用法：MEDIA_DEMO_BASE=/ npm run build:demo && npm run build:demo-artifact
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(import.meta.dirname, '..', '..')
/** 默认读 dist-demo；并行验证时可以用 MEDIA_DEMO_ARTIFACT_DIST 指到别的产物目录。 */
const distRoot = resolve(projectRoot, process.env.MEDIA_DEMO_ARTIFACT_DIST ?? 'dist-demo')
const outputPath = resolve(projectRoot, 'dist-demo-artifact', 'demo-site.html')

/** 与 mediaDesignTokens.css 的 --mg-font-sans 保持同样两个字族。 */
const GOOGLE_FONTS =
  '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' +
  '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?' +
  'family=DM+Sans:opsz,wght@9..40,100..1000&family=Noto+Sans+SC:wght@100..900&display=swap">'

function fail(message: string): never {
  throw new Error(`build:demo-artifact: ${message}`)
}

const shell = readFileSync(resolve(distRoot, 'index.html'), 'utf8')
const scriptSrc = /<script type="module"[^>]*src="([^"]+)"[^>]*><\/script>/.exec(shell)
const styleHref = /<link rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/.exec(shell)
if (!scriptSrc || !styleHref) fail('dist-demo/index.html 里找不到构建产物引用，产物结构变了')

const base = scriptSrc[1]!.slice(0, scriptSrc[1]!.indexOf('assets/'))
if (base !== '/') {
  fail(`部署基址是 ${base}，单文件分发只能用 /：请以 MEDIA_DEMO_BASE=/ 重新构建演示站`)
}

const script = readFileSync(resolve(distRoot, scriptSrc[1]!.replace(/^\//, '')), 'utf8')
let style = readFileSync(resolve(distRoot, styleHref[1]!.replace(/^\//, '')), 'utf8')

/** 逐个大括号配对地剥掉 @font-face：这些块里嵌套着 url()、unicode-range，
 *  正则一把梭很容易把后面的规则一起吃掉。 */
function stripFontFaces(css: string): string {
  let result = ''
  let cursor = 0
  for (;;) {
    const start = css.indexOf('@font-face', cursor)
    if (start < 0) {
      result += css.slice(cursor)
      return result
    }
    result += css.slice(cursor, start)
    const open = css.indexOf('{', start)
    if (open < 0) fail('@font-face 没有块体，CSS 产物结构异常')
    let depth = 1
    let index = open + 1
    while (index < css.length && depth > 0) {
      if (css[index] === '{') depth += 1
      else if (css[index] === '}') depth -= 1
      index += 1
    }
    cursor = index
  }
}

style = stripFontFaces(style)

const head = shell.slice(0, shell.indexOf('</head>'))
  .replace(scriptSrc[0], '')
  .replace(styleHref[0], '')

const document = [
  head.trimEnd(),
  `    ${GOOGLE_FONTS}`,
  '    <style>',
  style,
  '    </style>',
  '  </head>',
  '  <body>',
  '    <div id="root"></div>',
  '    <script type="module">',
  script,
  '    </script>',
  '  </body>',
  '</html>',
  '',
].join('\n')

/** 自检：会真的去发请求的引用在单文件里都是死链，宁可构建失败也不要发出去。
 *  只看**文档外壳**里的资源引用（<script src>、<link href>、<img src>）——内联进来的
 *  CSS/JS 里还有大量以 / 开头的字符串（演示站自己的路由、内嵌认证页里指向生产
 *  登录页的锚点），那些由页面内的路由与拦截逻辑接住，不是要加载的资源。 */
const shellHead = document.slice(0, document.indexOf('<style>'))
const shellResources = [...shellHead.matchAll(/<(?:script|link|img)\b[^>]*\b(?:src|href)="(\/[^"]*)"/g)].map(
  (match) => match[1]!,
)
if (shellResources.length) {
  fail(`产物外壳里仍有取不到的本地资源引用：${[...new Set(shellResources)].slice(0, 5).join(', ')}`)
}
// 具体到构建产物的文件名与字体文件——「/assets/」本身还会出现在演示站的接口
// 路径里（例如 /assets/{publicAssetId}），不能拿它当判据。
const bundledFiles = [scriptSrc[1]!, styleHref[1]!].map((path) => path.slice(path.lastIndexOf('/') + 1))
for (const name of bundledFiles) {
  if (document.includes(name)) fail(`产物里仍引用着构建文件 ${name}，内联没做全`)
}
if (document.includes('.woff2')) fail('产物里仍引用着本地字体文件，@font-face 没有剥干净')
if (document.includes('@font-face')) fail('@font-face 没有被完全剥离')
const bytes = Buffer.byteLength(document, 'utf8')
if (bytes > 16 * 1024 * 1024) fail(`单文件 ${(bytes / 1024 / 1024).toFixed(1)}MB，超过 16MB 上限`)

mkdirSync(resolve(projectRoot, 'dist-demo-artifact'), { recursive: true })
writeFileSync(outputPath, document, 'utf8')
console.log(
  `build:demo-artifact: PASS 单文件 ${(bytes / 1024 / 1024).toFixed(2)}MB → ${outputPath.replace(`${projectRoot}/`, '')}`,
)
