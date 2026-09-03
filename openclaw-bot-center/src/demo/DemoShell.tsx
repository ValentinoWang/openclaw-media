import { useEffect, useState } from 'react'
import MediaStudioApp from '../media/MediaStudioApp'
import DemoConsole from './DemoConsole'
import DemoCover from './DemoCover'
import { currentDemoPath, isDemoRoot, subscribeDemoNavigation } from './demoNavigation'

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

  return (
    <>
      <MediaStudioApp key={navKey} />
      <DemoConsole />
    </>
  )
}
