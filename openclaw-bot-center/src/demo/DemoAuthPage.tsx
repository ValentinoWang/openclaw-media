import { ArrowLeft } from 'lucide-react'
import { demoAuthPageDocuments, type DemoAuthPageSlug } from './generatedDemoAuthPages'
import { demoNavigateHome } from './demoNavigation'
import './demoAuthPage.css'

/** 在演示站里渲染「退出登录后的首页」等认证页。
 *
 *  这些页面是构建期从生产 HTML 复刻出来的独立文档；单文件分发时取不到那些文件，
 *  所以这里用 iframe srcdoc 原样嵌入同一份 HTML：样式天然隔离，页内的演示脚本
 *  （身份选择、返回、提交拦截）照常运行，不需要在 React 里重写一遍。 */
export default function DemoAuthPage({ slug }: { slug: DemoAuthPageSlug }) {
  const page = demoAuthPageDocuments.find((item) => item.slug === slug)
  if (!page) return null
  return (
    <div className="demo-auth-shell">
      <div className="demo-auth-bar">
        <button type="button" onClick={demoNavigateHome}><ArrowLeft size={15} />返回封面</button>
        <span>{page.title}</span>
        <small>不鉴权复刻 · 提交一律被拦截</small>
      </div>
      <iframe className="demo-auth-frame" title={page.title} srcDoc={page.html} sandbox="allow-scripts" />
    </div>
  )
}
