import { useEffect, useRef } from 'react'
import { ArrowLeft } from 'lucide-react'
import { demoAuthPageDocuments, type DemoAuthPageSlug } from './generatedDemoAuthPages'
import { demoNavigate, demoNavigateHome } from './demoNavigation'
import { demoPersonas, selectPersona } from './demoPersonas'
import './demoAuthPage.css'

/** 在演示站里渲染「退出登录后的首页」等认证页。
 *
 *  这些页面是构建期从生产 HTML 复刻出来的独立文档；单文件分发时取不到那些文件，
 *  所以这里用 iframe srcdoc 原样嵌入同一份 HTML：样式天然隔离，页内的演示脚本
 *  （身份选择、返回、提交拦截）照常运行，不需要在 React 里重写一遍。 */
export default function DemoAuthPage({ slug }: { slug: DemoAuthPageSlug }) {
  const page = demoAuthPageDocuments.find((item) => item.slug === slug)
  const frameRef = useRef<HTMLIFrameElement | null>(null)

  /* 登录页里的「以某个身份进入演示」按钮只能靠 postMessage 说话：iframe 带
   * sandbox="allow-scripts allow-forms"，是个不透明源——它写不了 localStorage，也做不了顶层
   * 导航（试过 window.top.location.assign，被沙箱静默拦下，工作台被装进了 iframe）。
   * 切身份和路由都由外壳这一侧执行。
   *
   * 校验只认 event.source 是不是我们自己那个 frame：沙箱源发出的消息 origin 是
   * "null"，按 origin 判等没有意义。落地路由也不采信消息里的值，只用身份 id 去
   * demoPersonas 里查它自己的 defaultRoute。 */
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!frameRef.current || event.source !== frameRef.current.contentWindow) return
      const data = event.data as { source?: unknown; action?: unknown; persona?: unknown } | null
      if (!data || data.source !== 'mediaclaw-demo-auth' || data.action !== 'enter') return
      const persona = demoPersonas.find((item) => item.id === data.persona)
      if (!persona) return
      selectPersona(persona.id)
      demoNavigate(persona.defaultRoute)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  if (!page) return null
  return (
    <div className="demo-auth-shell">
      <div className="demo-auth-bar">
        <button type="button" onClick={demoNavigateHome}><ArrowLeft size={15} />返回封面</button>
        <span>{page.title}</span>
        <small>不鉴权复刻 · 提交一律被拦截</small>
      </div>
      {/* sandbox 里必须带 allow-forms：只给 allow-scripts 时浏览器直接禁掉表单提交，
          submit 事件根本不触发——页内那段「拦截提交、给一条演示提示」的脚本在外壳里
          从来没跑过，登录表单填完点「登录」也毫无反应。allow-forms 只放开提交这一件事，
          提交仍然被页内脚本 preventDefault，不发任何请求；没有 allow-same-origin、
          没有 allow-top-navigation、没有 allow-popups，frame 依旧是不透明源，读不到
          外面的存储，也做不了顶层跳转（进入工作区仍然只能靠 postMessage 交给外壳）。 */}
      <iframe ref={frameRef} className="demo-auth-frame" title={page.title} srcDoc={page.html} sandbox="allow-scripts allow-forms" />
    </div>
  )
}
