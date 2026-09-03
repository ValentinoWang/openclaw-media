/** 演示站的客户端导航。
 *
 *  静态站点每个路由都落了一个 index.html，所以 `<a href>` 整页跳转是能用的；
 *  但演示站还会被打包成**单文件**分发（例如发布成一个 Artifact），那时候只有一个
 *  文档，任何子路径的整页跳转都取不到文件。所以封面页和演示控制台一律走这里的
 *  pushState 导航：两种部署方式下都成立，而且省掉一次整页重载。 */

// Vite 保证 BASE_URL 恒以 / 结尾。
const baseUrl = import.meta.env.BASE_URL

export function withBase(path: string): string {
  return baseUrl + path.replace(/^\//, '')
}

/** 去掉尾部斜杠后的部署根路径，用来判断“现在是不是停在封面页”。 */
const rootPath = baseUrl.replace(/\/$/, '')

export function isDemoRoot(pathname: string): boolean {
  const normalized = pathname.replace(/\/$/, '')
  return normalized === rootPath
}

const listeners = new Set<() => void>()

export function currentDemoPath(): string {
  return window.location.pathname
}

/** 订阅路径变化：popstate（前进/后退）与本模块自己的 pushState 都会通知。 */
export function subscribeDemoNavigation(listener: () => void): () => void {
  listeners.add(listener)
  if (listeners.size === 1) window.addEventListener('popstate', notify)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) window.removeEventListener('popstate', notify)
  }
}

function notify(): void {
  for (const listener of [...listeners]) listener()
}

export function demoNavigate(path: string): void {
  const target = withBase(path)
  if (window.location.pathname !== target) window.history.pushState({}, '', target)
  notify()
}

/** 回到封面页。 */
export function demoNavigateHome(): void {
  if (window.location.pathname !== baseUrl) window.history.pushState({}, '', baseUrl)
  notify()
}
