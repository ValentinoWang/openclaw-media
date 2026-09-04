/** 认证页导航。
 *
 *  两件事都不能写死：
 *
 *  1. **路径按部署基址推导**。生产挂在 `/openclaw/media/`，演示站挂在
 *     `/openclaw/media-demo/`，打成单文件发出去时基址是 `/`。写死
 *     `'/openclaw/media/login'` 的后果是：演示站里点「退出登录」会跳到一个根本
 *     不存在的路径，用户只看到 not found，连登录页长什么样都看不到。
 *
 *  2. **跳转方式可替换**。生产是整页跳转；演示站把它换成站内 pushState——单文件
 *     分发时整个站只有一个文档，任何整页跳转都取不到文件。这和用浏览器内假后端
 *     替换网络层是同一种做法：只换掉与运行环境有关的那一层，页面代码保持不变。
 */

export type AuthPage = 'login' | 'register' | 'verify' | 'recover' | 'reset'

type AuthNavigator = (path: string) => void

let installed: AuthNavigator | null = null

/** 演示站在入口处装上自己的跳转实现；生产不调用这个函数。 */
export function installAuthNavigator(navigate: AuthNavigator): void {
  installed = navigate
}

/** 认证页在当前部署下的绝对路径。 */
export function authPageUrl(page: AuthPage = 'login', next?: string): string {
  // QA 脚本会在 node 里 import 到这条链路，import.meta.env 在那里是 undefined。
  const base = (import.meta.env?.BASE_URL as string | undefined) ?? '/'
  const target = `${base}${page}`
  return next ? `${target}?next=${encodeURIComponent(next)}` : target
}

/** 当前页面路径，登录后原路返回用。 */
export function currentLocationForReturn(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`
}

export function goToAuthPage(page: AuthPage = 'login', next?: string): void {
  const target = authPageUrl(page, next)
  if (installed) {
    installed(target)
    return
  }
  window.location.assign(target)
}
