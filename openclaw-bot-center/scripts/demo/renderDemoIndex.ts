/** 生成演示站首页：一张纯静态的站点导航页，把 demoRoutes.ts / demoPersonas.ts
 *  里的全部路由按身份分组列出来。不引入任何浏览器 API —— 这个文件在 node
 *  构建阶段被调用（例如 vite.demo.config.ts 的 closeBundle 钩子），产出的
 *  HTML 字符串本身则不依赖 JavaScript 就能完整可用。 */
import type { DemoRouteGroup } from '../../src/demo/demoRoutes.ts'
import { demoRouteGroups } from '../../src/demo/demoRoutes.ts'
import type { DemoPersona, DemoPersonaId } from '../../src/demo/demoPersonas.ts'
import { demoPersonas } from '../../src/demo/demoPersonas.ts'

export type RenderDemoIndexOptions = {
  /** 演示站部署基址，形如 `/openclaw/media-demo/`，必须以 `/` 结尾。 */
  base: string
  /** 构建时间，ISO 字符串，原样展示在页脚。 */
  generatedAt: string
}

const personaLabelById: Record<DemoPersonaId, string> = {
  personal: '个人创作者',
  organization: '组织成员',
  admin: '平台管理员',
}

/** 转义插入到 HTML 文本 / 属性中的字符串。当前所有数据都来自仓库内的可信
 *  常量，但导航页面向未来可能变化的路由表，转义成本很低，仍然一律做。 */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 拼接 base 与路由 path，保证中间只有一个 `/`。 */
function joinRoute(base: string, path: string): string {
  return base + path.replace(/^\//, '')
}

function renderPersonaCard(persona: DemoPersona, base: string): string {
  const href = joinRoute(base, persona.defaultRoute)
  return `
        <li class="persona-card">
          <h3 class="persona-card__title">${escapeHtml(persona.label)}</h3>
          <p class="persona-card__detail">${escapeHtml(persona.detail)}</p>
          <a class="persona-card__action" href="${escapeHtml(href)}">以该身份进入</a>
        </li>`
}

function renderRouteCard(base: string, route: { path: string; label: string; detail?: string }): string {
  const href = joinRoute(base, route.path)
  const detail = route.detail ? `<p class="route-card__detail">${escapeHtml(route.detail)}</p>` : ''
  return `
          <li class="route-card">
            <a class="route-card__link" href="${escapeHtml(href)}">
              <span class="route-card__label">${escapeHtml(route.label)}</span>
              ${detail}
              <code class="route-card__path">${escapeHtml(route.path)}</code>
            </a>
          </li>`
}

function renderRouteGroup(base: string, group: DemoRouteGroup): string {
  const personaLabel = personaLabelById[group.persona]
  return `
      <section class="route-group">
        <h3 class="route-group__title">
          ${escapeHtml(group.label)}
          <span class="route-group__persona">${escapeHtml(personaLabel)}</span>
        </h3>
        <ul class="route-group__list">${group.routes.map((route) => renderRouteCard(base, route)).join('')}
        </ul>
      </section>`
}

export function renderDemoIndex(options: RenderDemoIndexOptions): string {
  const { base, generatedAt } = options

  const personaCards = demoPersonas.map((persona) => renderPersonaCard(persona, base)).join('')
  const routeGroups = demoRouteGroups.map((group) => renderRouteGroup(base, group)).join('')

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>MediaClaw 演示站 · 页面索引</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f8f5;
    --surface: #ffffff;
    --surface-muted: #eaf2ec;
    --ink: #17241f;
    --muted: #4d5c54;
    --border: #dde5de;
    --primary: #1a9b68;
    --primary-dark: #10684a;
    --primary-ink: #16302a;
    --on-primary: #ffffff;
    --notice-bg: #fff7e6;
    --notice-border: #e8c777;
    --notice-ink: #6b4c00;
    --code-bg: #eef4f0;
    --focus-ring: 3px solid rgba(26, 155, 104, 0.55);
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1713;
      --surface: #16211c;
      --surface-muted: #1c2a23;
      --ink: #eaf3ee;
      --muted: #a7b6ae;
      --border: #2b3a33;
      --primary: #1fb977;
      --primary-dark: #35d18d;
      --primary-ink: #d9f2e6;
      --on-primary: #0b1712;
      --notice-bg: #2c2410;
      --notice-border: #7a5c14;
      --notice-ink: #f2d989;
      --code-bg: #1c2a23;
      --focus-ring: 3px solid rgba(53, 209, 141, 0.6);
    }
  }

  * {
    box-sizing: border-box;
  }

  html, body {
    margin: 0;
    padding: 0;
    max-width: 100%;
    overflow-x: hidden;
  }

  body {
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    line-height: 1.5;
  }

  a {
    color: inherit;
  }

  a:focus-visible,
  button:focus-visible {
    outline: var(--focus-ring);
    outline-offset: 2px;
  }

  .page {
    max-width: 1080px;
    margin: 0 auto;
    padding: 32px 20px 64px;
  }

  header.hero {
    padding: 28px 24px;
    border-radius: 20px;
    background: linear-gradient(135deg, var(--primary-ink), var(--primary-dark));
    color: var(--on-primary);
  }

  .hero__site-name {
    margin: 0 0 6px;
    font-size: 1.75rem;
    font-weight: 800;
    letter-spacing: 0.01em;
  }

  .hero__subtitle {
    margin: 0;
    color: rgba(255, 255, 255, 0.85);
    font-size: 0.95rem;
  }

  .notice {
    margin-top: 20px;
    padding: 14px 16px;
    border: 1px solid var(--notice-border);
    border-radius: 12px;
    background: var(--notice-bg);
    color: var(--notice-ink);
    font-size: 0.9rem;
    line-height: 1.6;
  }

  .notice strong {
    font-weight: 700;
  }

  section.block {
    margin-top: 40px;
  }

  .block__title {
    margin: 0 0 4px;
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--ink);
  }

  .block__hint {
    margin: 0 0 16px;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .persona-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 16px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .persona-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--surface);
  }

  .persona-card__title {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
  }

  .persona-card__detail {
    margin: 0;
    flex: 1;
    color: var(--muted);
    font-size: 0.85rem;
  }

  .persona-card__action {
    display: inline-block;
    padding: 9px 14px;
    border-radius: 999px;
    background: var(--primary);
    color: var(--on-primary);
    font-size: 0.85rem;
    font-weight: 600;
    text-align: center;
    text-decoration: none;
  }

  .persona-card__action:hover {
    background: var(--primary-dark);
  }

  .route-group {
    margin-bottom: 28px;
  }

  .route-group__title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin: 0 0 10px;
    font-size: 1rem;
    font-weight: 700;
    color: var(--ink);
  }

  .route-group__persona {
    padding: 2px 10px;
    border-radius: 999px;
    background: var(--surface-muted);
    color: var(--muted);
    font-size: 0.75rem;
    font-weight: 600;
  }

  .route-group__list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 12px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .route-card__link {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--surface);
    text-decoration: none;
    color: var(--ink);
  }

  .route-card__link:hover {
    border-color: var(--primary);
  }

  .route-card__label {
    font-size: 0.95rem;
    font-weight: 600;
  }

  .route-card__detail {
    margin: 0;
    color: var(--muted);
    font-size: 0.8rem;
  }

  .route-card__path {
    margin-top: auto;
    padding-top: 6px;
    color: var(--muted);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.75rem;
    background: var(--code-bg);
    border-radius: 6px;
    padding: 2px 6px;
    width: fit-content;
  }

  footer.page-footer {
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 0.78rem;
  }

  footer.page-footer p {
    margin: 0 0 4px;
  }
</style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <p class="hero__site-name">MediaClaw 演示站</p>
      <p class="hero__subtitle">静态演示 · 不鉴权 · 示例数据，不连接任何后端</p>
    </header>

    <div class="notice" role="note">
      <strong>提示：</strong>这是产品流程走查用的静态复刻。页面上出现的项目、账号、金额、租户等信息均为虚构示例，不代表任何真实数据，也不能用来验证生产功能。
    </div>

    <section class="block">
      <h2 class="block__title">按身份进入</h2>
      <p class="block__hint">切换身份也可以在站内右下角的「演示导航」里完成。</p>
      <ul class="persona-list">${personaCards}
      </ul>
    </section>

    <section class="block">
      <h2 class="block__title">全部页面</h2>
      <p class="block__hint">按导航分组列出演示站的全部页面，点击直接跳转。</p>
      ${routeGroups}
    </section>

    <footer class="page-footer">
      <p>构建时间：${escapeHtml(generatedAt)}</p>
      <p>本页由构建脚本生成，请勿手工编辑。</p>
    </footer>
  </div>
</body>
</html>
`
}
