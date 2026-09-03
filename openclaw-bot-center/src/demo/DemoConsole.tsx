import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Compass, GripVertical, X } from 'lucide-react'
import { demoPersonas, activePersonaId, selectPersona, type DemoPersonaId } from './demoPersonas'
import { demoAuthPages, demoRouteGroups } from './demoRoutes'
import { demoNavigate, demoNavigateHome, withBase } from './demoNavigation'
import './demoConsole.css'

/** 详情路由的授权按其列表页判断，与生产 `resolveStudioRouteOutcome` 的映射一致。 */
function grantPath(path: string): string {
  if (/^\/(?:runs|studio)\/[^/]+$/.test(path)) return '/studio'
  if (/^\/workspace\/(?:preview|edit)\/[^/]+$/.test(path)) return '/workspace'
  if (/^\/organization-workspace\/document\/[^/]+$/.test(path)) return '/organization-workspace'
  return path
}

/* ---------------------------------------------------------------------------
 * 悬浮触发按钮的拖拽定位。
 *
 * 触发按钮默认贴在左下角（demoConsole.css 里 `.demo-console-wrapper` 的默认
 * 规则），拖拽后就切换成显式像素坐标覆盖默认贴边。面板永远锚在触发按钮所在的
 * wrapper 上：wrapper 是 `position:fixed` 且水平/垂直各只设一侧偏移（另一侧
 * 留 auto），盒子会天然收缩贴合按钮本身，不需要另外量它的尺寸。
 *
 * 面板该往哪个方向展开（data-side / data-align）只按「按钮当前落点距视口
 * 两侧还剩多少空间」一次性算好写成 data 属性，翻转交给 CSS 选择器，不做
 * 逐帧测量。
 * ------------------------------------------------------------------------- */

type ConsolePosition = { x: number; y: number }
type ConsoleSize = { width: number; height: number }
type ConsoleBox = { left: number; top: number; right: number; bottom: number }
type ConsoleSide = 'left' | 'right'
type ConsoleAlign = 'top' | 'bottom'
type ConsoleAnchor = { side: ConsoleSide; align: ConsoleAlign }

type TriggerDragState = {
  pointerId: number
  startClientX: number
  startClientY: number
  originX: number
  originY: number
  moved: boolean
}

const positionStorageKey = 'mediaclaw-demo-console-position'
/** 小于这个位移量按点击处理，避免手抖或触摸时的几像素抖动被当成拖拽。 */
const dragThresholdPx = 4

function readStoredPosition(): ConsolePosition | null {
  try {
    const raw = localStorage.getItem(positionStorageKey)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<ConsolePosition> | null
    if (parsed && Number.isFinite(parsed.x) && Number.isFinite(parsed.y)) {
      return { x: parsed.x as number, y: parsed.y as number }
    }
  } catch {
    /* 隐私模式或脏数据：退回默认贴边位置 */
  }
  return null
}

function writeStoredPosition(position: ConsolePosition): void {
  try {
    localStorage.setItem(positionStorageKey, JSON.stringify(position))
  } catch {
    /* 隐私模式：仅当前页面生效 */
  }
}

/** 把左上角坐标夹在 [0, 视口尺寸 - 按钮尺寸] 之间，保证按钮永远完整可见；
 *  视口比按钮还小的极端情况下退化为贴左上角。 */
function clampPosition(position: ConsolePosition, size: ConsoleSize): ConsolePosition {
  const maxX = Math.max(0, window.innerWidth - size.width)
  const maxY = Math.max(0, window.innerHeight - size.height)
  return {
    x: Math.min(Math.max(position.x, 0), maxX),
    y: Math.min(Math.max(position.y, 0), maxY),
  }
}

/** 按钮离视口哪一侧更近，面板就从哪一侧「往回」展开，翻转后就不会被顶出可视区域。 */
function computeAnchor(box: ConsoleBox): ConsoleAnchor {
  const side: ConsoleSide = window.innerWidth - box.left >= box.right ? 'left' : 'right'
  const align: ConsoleAlign = box.top >= window.innerHeight - box.bottom ? 'bottom' : 'top'
  return { side, align }
}

export default function DemoConsole() {
  const [open, setOpen] = useState(false)

  // personaId 的初始值来自 activePersonaId()，之后只在下面的
  // handleSelectPersona 里与 localStorage 一起更新，这样面板能立即
  // 反映切换结果，不必每次渲染都重新读一次 localStorage
  const [personaId, setPersonaId] = useState<DemoPersonaId>(() => activePersonaId())

  // 应用自己的抽屉/对话框贴在右下角，演示控制台不能盖住它们的操作按钮。
  const [overlayOpen, setOverlayOpen] = useState(false)

  // null = 还没拖拽过，交给 CSS 的默认贴边规则；拖拽过之后变成显式像素坐标，
  // 盖掉默认位置。
  const [position, setPosition] = useState<ConsolePosition | null>(null)
  const [anchor, setAnchor] = useState<ConsoleAnchor>({ side: 'left', align: 'bottom' })

  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const dragStateRef = useRef<TriggerDragState | null>(null)
  // 拖拽结束的 pointerup 后面浏览器还会补一个原生 click；这个标记让
  // handleTriggerClick 知道要不要把它吞掉，而不是直接在 pointerup 里切 open。
  const wasDraggedRef = useRef(false)
  // 只在触发按钮第一次真正挂到 DOM 上时，把存过的位置读回来一次。
  const restoredRef = useRef(false)
  // 与 position 状态保持同步的镜像：pointerup 时需要同步读到「刚刚那次拖拽
  // 落在哪」，不能等 React 下一轮渲染。
  const positionRef = useRef<ConsolePosition | null>(null)

  function applyPosition(next: ConsolePosition) {
    positionRef.current = next
    setPosition(next)
  }

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

  // 视口变化（窗口缩小、横转竖……）时重新夹紧一次，防止按钮被挤出可视区域，
  // 面板的展开方向也跟着重算。
  useEffect(() => {
    function handleResize() {
      const trigger = triggerRef.current
      if (!trigger) return
      const rect = trigger.getBoundingClientRect()
      const current = positionRef.current
      if (!current) {
        setAnchor(computeAnchor(rect))
        return
      }
      const next = clampPosition(current, rect)
      applyPosition(next)
      setAnchor(
        computeAnchor({ left: next.x, top: next.y, right: next.x + rect.width, bottom: next.y + rect.height }),
      )
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // 挂载后把上次拖拽的位置读回来（若有）并按当前视口夹紧一次；用 layout effect
  // 是为了赶在首次绘制前定好位，不闪一下默认贴边位置再跳过去。overlayOpen 是
  // 依赖项，因为按钮在抽屉/对话框打开期间根本不渲染，第一次挂载时可能还拿不到它，
  // 要等它下次真正出现在 DOM 里再补一次。
  useLayoutEffect(() => {
    if (restoredRef.current) return
    const trigger = triggerRef.current
    if (!trigger) return
    restoredRef.current = true
    const rect = trigger.getBoundingClientRect()
    const stored = readStoredPosition()
    if (stored) {
      const next = clampPosition(stored, rect)
      applyPosition(next)
      setAnchor(
        computeAnchor({ left: next.x, top: next.y, right: next.x + rect.width, bottom: next.y + rect.height }),
      )
    } else {
      setAnchor(computeAnchor(rect))
    }
  }, [overlayOpen])

  // 正常情况下一定能找到；兜底第一个 persona 只是为了防止 localStorage
  // 里出现脏数据时整个控制台崩溃
  const currentPersona = demoPersonas.find((persona) => persona.id === personaId) ?? demoPersonas[0]
  const routeGrants = currentPersona.session.routeGrants

  function handleSelectPersona(id: DemoPersonaId, defaultRoute: string) {
    selectPersona(id)
    setPersonaId(id)
    // 客户端导航 + 重挂应用：假后端每次请求都现读 activePersona()，不需要整页重载。
    demoNavigate(defaultRoute)
    setOpen(false)
  }

  function handleOpenRoute(event: React.MouseEvent<HTMLAnchorElement>, path: string) {
    // 保留 href 让中键/新标签页仍然可用；普通左键走客户端导航。
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    demoNavigate(path)
    setOpen(false)
  }

  function handleTriggerPointerDown(event: React.PointerEvent<HTMLButtonElement>) {
    if (dragStateRef.current) return // 已经有一根指针在拖了，忽略后来的
    if (event.button !== 0) return // 只响应主键 / 触摸主指针
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    dragStateRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originX: rect.left,
      originY: rect.top,
      moved: false,
    }
    // 用指针捕获而不是 window 级监听：之后无论指针移到哪儿，pointermove/up
    // 都还是发到这个按钮上，触发点不必再自己算命中测试。
    trigger.setPointerCapture(event.pointerId)
  }

  function handleTriggerPointerMove(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = dragStateRef.current
    const trigger = triggerRef.current
    if (!drag || !trigger || event.pointerId !== drag.pointerId) return
    const deltaX = event.clientX - drag.startClientX
    const deltaY = event.clientY - drag.startClientY
    if (!drag.moved && Math.hypot(deltaX, deltaY) < dragThresholdPx) return
    drag.moved = true
    const rect = trigger.getBoundingClientRect()
    const next = clampPosition({ x: drag.originX + deltaX, y: drag.originY + deltaY }, rect)
    applyPosition(next)
    setAnchor(computeAnchor({ left: next.x, top: next.y, right: next.x + rect.width, bottom: next.y + rect.height }))
  }

  function handleTriggerPointerUp(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = dragStateRef.current
    if (!drag || event.pointerId !== drag.pointerId) return
    const trigger = triggerRef.current
    if (trigger?.hasPointerCapture(event.pointerId)) trigger.releasePointerCapture(event.pointerId)
    wasDraggedRef.current = drag.moved
    if (drag.moved && positionRef.current) writeStoredPosition(positionRef.current)
    dragStateRef.current = null
  }

  function handleTriggerPointerCancel(event: React.PointerEvent<HTMLButtonElement>) {
    // 比如触摸手势被系统整个接管：不留下半截的拖拽状态，也不当成一次拖拽。
    const drag = dragStateRef.current
    if (!drag || event.pointerId !== drag.pointerId) return
    const trigger = triggerRef.current
    if (trigger?.hasPointerCapture(event.pointerId)) trigger.releasePointerCapture(event.pointerId)
    dragStateRef.current = null
    wasDraggedRef.current = false
  }

  function handleTriggerClick() {
    // 拖拽结束那次 pointerup 后面浏览器还会补一个原生 click；这里吞掉它，
    // 不然一次拖拽会被顺带当成开合面板的点击。键盘 Enter/Space 触发的 click
    // 不经过上面几个 pointer handler，wasDraggedRef 始终是 false，正常切换。
    if (wasDraggedRef.current) {
      wasDraggedRef.current = false
      return
    }
    setOpen((current) => !current)
  }

  if (overlayOpen) return null

  // 没拖拽过时不设内联样式，位置完全交给 CSS 的默认贴边规则（含窄屏媒体查询）。
  const wrapperStyle: React.CSSProperties | undefined = position
    ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto' }
    : undefined

  return (
    <div className="demo-console-wrapper" data-side={anchor.side} data-align={anchor.align} style={wrapperStyle}>
      <button
        ref={triggerRef}
        type="button"
        className="demo-console-trigger"
        aria-expanded={open}
        aria-label="演示导航（可拖拽移动位置）"
        title="可拖拽移动位置"
        onPointerDown={handleTriggerPointerDown}
        onPointerMove={handleTriggerPointerMove}
        onPointerUp={handleTriggerPointerUp}
        onPointerCancel={handleTriggerPointerCancel}
        onClick={handleTriggerClick}
      >
        <GripVertical className="demo-console-trigger-grip" size={14} aria-hidden="true" />
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
            <a className="demo-console-index-link" href={withBase('/pages.html')}>
              打开静态页面索引（无需 JavaScript）
            </a>
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
            <ul className="demo-console-route-list">
              <li className="demo-console-route-item">
                <a
                  className="demo-console-route-link"
                  href={withBase('/')}
                  onClick={(event) => {
                    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                    event.preventDefault()
                    demoNavigateHome()
                    setOpen(false)
                  }}
                >
                  返回封面页
                </a>
              </li>
            </ul>
            <div className="demo-console-group">
              <p className="demo-console-group-title">认证页面（只读复刻）</p>
              <ul className="demo-console-route-list">
                {demoAuthPages.map((page) => (
                  <li className="demo-console-route-item" key={page.path}>
                    <a className="demo-console-route-link" href={withBase(page.path)} title={page.detail}>
                      {page.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>

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
                        <a
                          className="demo-console-route-link"
                          href={withBase(route.path)}
                          title={route.detail}
                          onClick={(event) => handleOpenRoute(event, route.path)}
                        >
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
    </div>
  )
}
