import { useEffect, useState } from 'react'
import { Compass, X } from 'lucide-react'
import { demoPersonas, activePersonaId, selectPersona, type DemoPersonaId } from './demoPersonas'
import { demoRouteGroups } from './demoRoutes'
import './demoConsole.css'

// Vite 保证 BASE_URL 恒以 / 结尾，因此可以直接与去掉前导 / 的路径拼接，
// 不必再补一次分隔符
const baseUrl = import.meta.env.BASE_URL

function withBase(path: string): string {
  return baseUrl + path.replace(/^\//, '')
}

/** 详情路由的授权按其列表页判断，与生产 `resolveStudioRouteOutcome` 的映射一致。 */
function grantPath(path: string): string {
  if (/^\/(?:runs|studio)\/[^/]+$/.test(path)) return '/studio'
  if (/^\/workspace\/(?:preview|edit)\/[^/]+$/.test(path)) return '/workspace'
  if (/^\/organization-workspace\/document\/[^/]+$/.test(path)) return '/organization-workspace'
  return path
}

export default function DemoConsole() {
  const [open, setOpen] = useState(false)

  // personaId 的初始值来自 activePersonaId()，之后只在下面的
  // handleSelectPersona 里与 localStorage 一起更新，这样面板能立即
  // 反映切换结果，不必每次渲染都重新读一次 localStorage
  const [personaId, setPersonaId] = useState<DemoPersonaId>(() => activePersonaId())

  // 应用自己的抽屉/对话框贴在右下角，演示控制台不能盖住它们的操作按钮。
  const [overlayOpen, setOverlayOpen] = useState(false)

  useEffect(() => {
    const sync = () => setOverlayOpen(Boolean(document.querySelector('.task-drawer, [role="dialog"]')))
    sync()
    const observer = new MutationObserver(sync)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open])

  // 正常情况下一定能找到；兜底第一个 persona 只是为了防止 localStorage
  // 里出现脏数据时整个控制台崩溃
  const currentPersona = demoPersonas.find((persona) => persona.id === personaId) ?? demoPersonas[0]
  const routeGrants = currentPersona.session.routeGrants

  function handleSelectPersona(id: DemoPersonaId, defaultRoute: string) {
    selectPersona(id)
    setPersonaId(id)
    window.location.assign(withBase(defaultRoute))
  }

  if (overlayOpen) return null

  return (
    <>
      <button
        type="button"
        className="demo-console-trigger"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Compass size={18} />
        演示导航
      </button>

      {open ? (
        <div className="demo-console-panel">
          <div className="demo-console-header">
            <div>
              <p className="demo-console-title">MediaClaw 演示站</p>
              <p className="demo-console-subtitle">静态演示 · 不鉴权 · 数据为示例内容，不连接任何后端</p>
            </div>
            <button
              type="button"
              className="demo-console-close"
              aria-label="关闭演示导航"
              onClick={() => setOpen(false)}
            >
              <X size={16} />
            </button>
          </div>

          <div className="demo-console-section">
            <p className="demo-console-section-title">身份切换</p>
            <div className="demo-console-persona-list">
              {demoPersonas.map((persona) => {
                const isActive = persona.id === personaId
                return (
                  <button
                    key={persona.id}
                    type="button"
                    className={isActive ? 'demo-console-persona is-active' : 'demo-console-persona'}
                    aria-pressed={isActive}
                    onClick={() => handleSelectPersona(persona.id, persona.defaultRoute)}
                  >
                    <span className="demo-console-persona-label">{persona.label}</span>
                    <span className="demo-console-persona-detail">{persona.detail}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="demo-console-section">
            <p className="demo-console-section-title">页面索引</p>
            {demoRouteGroups.map((group) => (
              <div className="demo-console-group" key={group.label}>
                <p className="demo-console-group-title">{group.label}</p>
                <ul className="demo-console-route-list">
                  {group.routes.map((route) => {
                    const isForeign = !routeGrants.includes(grantPath(route.path))
                    return (
                      <li
                        key={route.path}
                        className={isForeign ? 'demo-console-route-item is-foreign' : 'demo-console-route-item'}
                      >
                        <a className="demo-console-route-link" href={withBase(route.path)} title={route.detail}>
                          {route.label}
                        </a>
                        {isForeign ? <small className="demo-console-route-hint">需切换身份</small> : null}
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  )
}
