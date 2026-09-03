import { useEffect, useState } from 'react'
import MediaStudioApp from '../media/MediaStudioApp'
import DemoConsole from './DemoConsole'
import DemoCover from './DemoCover'
import DemoAuthPage from './DemoAuthPage'
import { demoAuthPageDocuments, type DemoAuthPageSlug } from './generatedDemoAuthPages'
import { currentDemoPath, isDemoRoot, subscribeDemoNavigation, withBase } from './demoNavigation'

/** 认证页不是 React 路由，它们是构建期复刻出来的独立文档；演示站在外壳这一层
 *  按路径接管，这样单文件分发时也能打开「退出登录后的首页」。 */
function matchAuthSlug(pathname: string): DemoAuthPageSlug | null {
  const normalized = pathname.replace(/\/$/, '')
  for (const page of demoAuthPageDocuments) {
    if (normalized === withBase(page.slug).replace(/\/$/, '')) return page.slug
  }
  return null
}

/** 演示站外壳：站点根路径渲染封面页，其它路径渲染真实的 MediaStudioApp。
 *
 *  生产的根路由是 `<Navigate to={defaultRoute} />`，直接落进内页；演示站在外面
 *  拦一层，既不动生产路由表，也让人一进来先知道这是什么。
 *
 *  navKey 会在每次封面/控制台导航后自增，用来重挂 MediaStudioApp——它内部的
 *  BrowserRouter 只听 popstate，不会感知我们的 pushState，重挂是最省心的同步方式，
 *  代价与过去的整页跳转相当，但不需要服务器上真的存在那个路径。 */
export default function DemoShell() {
  const [path, setPath] = useState(() => currentDemoPath())
  const [navKey, setNavKey] = useState(0)

  useEffect(() => subscribeDemoNavigation(() => {
    setPath(currentDemoPath())
    setNavKey((value) => value + 1)
  }), [])

  if (isDemoRoot(path)) return <DemoCover />

  const authSlug = matchAuthSlug(path)
  if (authSlug) return <DemoAuthPage slug={authSlug} />

  return (
    <>
      <MediaStudioApp key={navKey} />
      <DemoConsole />
    </>
  )
}
