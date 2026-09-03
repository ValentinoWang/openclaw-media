/** 生成「可内嵌」版本的认证页。
 *
 *  演示站原本把五个认证页写成 dist-demo/<slug>/index.html 这样的独立静态文件，
 *  静态服务器上没问题；但演示站也会被打包成**单文件**分发（发布成 Artifact 时），
 *  那时候只有一个文档，这些页面根本够不着——「退出登录后的首页」就这么消失了。
 *
 *  这里复用 buildDemoAuthPages.ts 里同一套改写逻辑（同一个来源、同一个演示脚本），
 *  只是把外链样式全部内联，产出一份自包含的 HTML 字符串写进
 *  src/demo/generatedDemoAuthPages.ts，供演示站 SPA 用 iframe srcdoc 原样渲染。
 *  样式因此天然隔离，不会和应用样式打架。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { AUTH_PAGES, transformAuthPage, type AuthPageSlug } from './buildDemoAuthPages.ts'

const moduleDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(moduleDir, '..', '..')
const outputPath = resolve(repoRoot, 'src/demo/generatedDemoAuthPages.ts')

const STYLESHEET_LINK = '<link rel="stylesheet" href="/media.auth.css" />'
const TOKEN_IMPORT = '@import url("/mediaDesignTokens.css");'

function inlineStyles(html: string): string {
  const tokens = readFileSync(resolve(repoRoot, 'src/media/mediaDesignTokens.css'), 'utf8')
  const authCss = readFileSync(resolve(repoRoot, 'src/media.auth.css'), 'utf8')
  if (!authCss.includes(TOKEN_IMPORT)) {
    throw new Error('media.auth.css 里找不到设计令牌的 @import，内联逻辑需要更新')
  }
  // @import 只能出现在样式表最前面，内联后直接用令牌内容替换掉这一行。
  const merged = `${tokens}\n${authCss.replace(TOKEN_IMPORT, '')}`
  if (!html.includes(STYLESHEET_LINK)) {
    throw new Error('认证页里找不到 media.auth.css 的引用，内联逻辑需要更新')
  }
  return html.replace(STYLESHEET_LINK, `<style>\n${merged}\n</style>`)
}

function pageTitle(html: string, slug: AuthPageSlug): string {
  const title = /<title>([^<]*)<\/title>/.exec(html)?.[1]
  if (!title) throw new Error(`[${slug}] 认证页缺少 <title>`)
  return title.trim()
}

const pages = AUTH_PAGES.map((page) => {
  const raw = readFileSync(page.sourcePath, 'utf8')
  // base 用 '/'：内嵌版本没有子路径部署的概念，页面之间的跳转由演示站接管。
  const html = inlineStyles(transformAuthPage(raw, '/', page.slug))
  return { slug: page.slug, title: pageTitle(html, page.slug), html }
})

const banner = `/** 由 scripts/demo/generateDemoAuthPages.ts 生成，请勿手改。\n *  来源：${AUTH_PAGES.map((page) => page.sourcePath.slice(repoRoot.length + 1)).join('、')}\n *  重新生成：npm run generate:demo-auth-pages */`

writeFileSync(
  outputPath,
  `${banner}\nexport type DemoAuthPageSlug = ${pages.map((page) => `'${page.slug}'`).join(' | ')}\n\n` +
    `export type DemoAuthPage = { readonly slug: DemoAuthPageSlug; readonly title: string; readonly html: string }\n\n` +
    `export const demoAuthPageDocuments: readonly DemoAuthPage[] = ${JSON.stringify(pages, null, 2)}\n`,
  'utf8',
)

console.log(`generate:demo-auth-pages: 写入 ${pages.length} 个内嵌认证页 -> src/demo/generatedDemoAuthPages.ts`)
