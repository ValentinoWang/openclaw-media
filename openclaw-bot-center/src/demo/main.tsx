/** 演示站入口：与 `src/media/main.tsx` 渲染同一个 MediaStudioApp，区别只有三点——
 *  先装上浏览器内假后端，站点根路径先给一张封面页，再挂一个演示导航控制台。 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import DemoShell from './DemoShell'
import { installDemoBackend } from './demoBackend'
import { installAuthNavigator } from '../media/mediaNavigation'
import { demoNavigateTo } from './demoNavigation'
import { demoAuthPageDocuments } from './generatedDemoAuthPages'
import '../media/mediaDesignTokens.css'
import '../media/media.css'
import '../media/mediaPrimitives.css'
import '../media/mediaStudioTheme.css'

installDemoBackend()

/** 「退出登录」在生产是整页跳到 /openclaw/media/login。演示站里那个路径不存在，
 *  单文件分发时更是连一个可跳的文档都没有——用户点完只会看到 not found，
 *  连登录页长什么样都看不到。这里把跳转换成站内 pushState，外壳按路径渲染
 *  构建期复刻出来的认证页。 */
installAuthNavigator(demoNavigateTo)

/** 页面里还有一批 `<a href={loginUrl()}>`（权限不足、会话过期这些状态里的「登录」
 *  按钮）。它们是普通链接，不走上面的跳转实现，整页跳同样会落到不存在的路径上，
 *  所以在捕获阶段截下指向认证页的那些。其余链接（React Router 的 Link）不碰。 */
const authTargets = new Set(demoAuthPageDocuments.map((page) => page.slug.replace(/^\/|\/$/g, '')))
document.addEventListener(
  'click',
  (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const anchor = (event.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
    if (!anchor || anchor.target === '_blank') return
    const url = new URL(anchor.href, window.location.origin)
    if (url.origin !== window.location.origin) return
    const base = import.meta.env.BASE_URL
    if (!url.pathname.startsWith(base)) return
    const slug = url.pathname.slice(base.length).replace(/\/$/, '')
    if (!authTargets.has(slug)) return
    event.preventDefault()
    demoNavigateTo(`${url.pathname}${url.search}`)
  },
  true,
)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <DemoShell />
  </StrictMode>,
)
