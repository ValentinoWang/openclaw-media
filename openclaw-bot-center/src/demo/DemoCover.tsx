import { ArrowRight, Compass, Database, LayoutDashboard, ShieldCheck, Workflow } from 'lucide-react'
import generatedCatalog from './generatedDemoCatalog.json'
import generatedDataset from './generatedDemoDataset.json'
import { demoPersonas } from './demoPersonas'
import { demoAuthPages, demoRouteGroups, demoStaticRoutes } from './demoRoutes'
import { demoNavigate } from './demoNavigation'
import './demoCover.css'

/** 演示站封面页：说明这是什么、边界在哪、有哪些页面，然后再进应用。
 *  站点根路径渲染它，而不是像生产那样直接跳到默认页——单看一个内页，
 *  没人知道这是不鉴权的复刻站，还是真的产品。 */

const personaLabelById: Record<string, string> = {
  personal: '个人创作者',
  organization: '组织成员',
  admin: '平台管理员',
}

const stats = [
  { icon: <LayoutDashboard size={17} />, value: demoStaticRoutes.length, label: '业务页面', detail: '与生产同一批页面组件' },
  { icon: <ShieldCheck size={17} />, value: demoAuthPages.length, label: '认证页面', detail: '只保留结构，提交被拦截' },
  { icon: <Database size={17} />, value: Object.keys(generatedDataset.operations).length, label: '接口样本', detail: '按业务合同生成并校验' },
  { icon: <Workflow size={17} />, value: generatedCatalog.capabilities.length, label: '能力目录', detail: '取自真实能力注册表' },
]

export default function DemoCover() {
  return (
    <main className="demo-cover">
      <section className="demo-cover-hero">
        <span className="demo-cover-eyebrow"><Compass size={15} />MEDIACLAW 静态演示站</span>
        <h1>不鉴权的 Media 前端复刻，<em>点得动的完整业务流程</em></h1>
        <p className="demo-cover-lead">
          页面、组件、路由和状态机都直接来自生产代码，只把网络层换成浏览器内的假后端；
          按真实的信息架构走一遍从选题、创作、本机精剪到发布复盘的全流程。
        </p>
        <div className="demo-cover-actions">
          <button type="button" className="demo-cover-primary" onClick={() => demoNavigate('/today')}>
            从今日工作台开始<ArrowRight size={16} />
          </button>
          <button type="button" className="demo-cover-secondary" onClick={() => demoNavigate('/overview')}>
            看运营总览
          </button>
        </div>
        <ul className="demo-cover-stats">
          {stats.map((stat) => (
            <li key={stat.label}>
              <span className="demo-cover-stat-icon">{stat.icon}</span>
              <strong>{stat.value}</strong>
              <b>{stat.label}</b>
              <small>{stat.detail}</small>
            </li>
          ))}
        </ul>
      </section>

      <section className="demo-cover-panel">
        <header><h2>先选一个身份</h2><p>不同身份看到的导航、页面授权和数据范围都不一样，和生产的会话授权一致。</p></header>
        <ul className="demo-cover-personas">
          {demoPersonas.map((persona) => (
            <li key={persona.id}>
              <h3>{persona.label}</h3>
              <p>{persona.detail}</p>
              <small>{persona.session.routeGrants.length} 个可访问路由</small>
              <button type="button" onClick={() => demoNavigate(persona.defaultRoute)}>
                以该身份进入<ArrowRight size={15} />
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="demo-cover-panel">
        <header><h2>这里的数据是什么</h2></header>
        <ul className="demo-cover-notes">
          <li><strong>虚构示例</strong>项目、账号、品牌、金额都是编出来的演示数据，不含任何真实账户或联系方式。</li>
          <li><strong>写操作只在本页生效</strong>新建、确认、发布这些动作会真的改变界面状态，但只存在内存里，刷新就回到初始数据。</li>
          <li><strong>没有后端</strong>所有请求被浏览器内的假后端接住；接口样本按业务合同生成并逐条校验，形状与生产一致。</li>
          <li><strong>认证页不鉴权</strong>登录、注册、找回密码只复刻页面结构，任何提交都会被拦下。</li>
        </ul>
      </section>

      <section className="demo-cover-panel">
        <header><h2>页面索引</h2><p>也可以随时点右下角的「演示导航」切换身份或跳到任意页面。</p></header>
        {demoRouteGroups.map((group) => (
          <div className="demo-cover-group" key={group.label}>
            <p className="demo-cover-group-title">{group.label}<small>{personaLabelById[group.persona] ?? group.persona}</small></p>
            <ul className="demo-cover-routes">
              {group.routes.map((route) => (
                <li key={route.path}>
                  <button type="button" onClick={() => demoNavigate(route.path)}>
                    <strong>{route.label}</strong>
                    {route.detail ? <small>{route.detail}</small> : null}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="demo-cover-group">
          <p className="demo-cover-group-title">认证页面<small>只读复刻</small></p>
          <ul className="demo-cover-routes">
            {demoAuthPages.map((page) => (
              <li key={page.path}>
                {/* 认证页是构建期生成的独立静态文件，不走 React 路由，只能整页打开。 */}
                <a href={page.path.replace(/^\//, '')}>
                  <strong>{page.label}</strong><small>{page.detail}</small>
                </a>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </main>
  )
}
