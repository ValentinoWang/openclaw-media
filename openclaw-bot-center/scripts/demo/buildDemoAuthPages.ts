/**
 * 演示站的认证页（登录 / 注册 / 邮箱验证 / 找回密码 / 重置密码）构建脚本。
 *
 * 背景：这五个页面在生产环境依赖 media.login.js 向 /openclaw/auth/* 发起真实请求
 * （登录、注册、验证邮箱、找回密码、重置密码、Feishu 授权等）。演示站是“不鉴权
 * 静态演示”——只走查页面结构和交互，绝不能发起任何真实请求。因此这里复用原始
 * HTML/CSS，但把行为脚本换成一段纯 DOM、零网络请求的演示脚本：拦截所有表单提交
 * 和站内认证链接，改为展示一条内联提示，不改变任何真实状态。
 *
 * 页面落盘为“目录 + index.html”而不是“xxx.html”，是为了绕开生产 nginx 里针对
 * 文件名带 login 的 .html 请求返回 404 的兜底规则（见
 * deploy/nginx-openclaw-bot-center.conf 中
 * `location ~* /[^/]*login[^/]*\.html$ { return 404; }`）——目录形式的请求 URI
 * 不以 .html 结尾，不会命中这条规则。
 *
 * 注意：注入到页面里的演示脚本（见 buildDemoScriptTag）是直接手写的 JS 源码
 * 字符串，而不是“写一个 TS 函数再 .toString() 序列化”。后者看起来更省事，但
 * tsx/esbuild 在转译时会给赋值给 const 的函数表达式包一层 __name(...) 之类的
 * 运行期辅助调用（用于保留 .name，供调试/HMR 使用）——那层辅助函数只存在于
 * Node 运行 tsx 的进程里，序列化出去塞进浏览器 <script> 后会直接抛
 * ReferenceError。手写字符串没有这个转译环节，才能保证产物就是最终跑在浏览器
 * 里的那段代码。
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** 本文件所在目录：<repo>/openclaw-bot-center/scripts/demo */
const moduleDir = dirname(fileURLToPath(import.meta.url))
/** 子项目根目录：<repo>/openclaw-bot-center。用绝对路径定位源文件，
 *  不依赖调用方的 process.cwd()，避免被不同调用位置坑。 */
const repoRoot = resolve(moduleDir, '..', '..')

type AuthPageSlug = 'login' | 'register' | 'verify' | 'recover' | 'reset'

type AuthPageSpec = {
  slug: AuthPageSlug
  /** 源 HTML 的绝对路径。 */
  sourcePath: string
}

/** 五个认证页的源文件位置，与 vite.media.config.ts 的 rollupOptions.input 保持一致
 *  （login/register 在仓库根目录，其余三个在 src/ 下）。 */
const AUTH_PAGES: AuthPageSpec[] = [
  { slug: 'login', sourcePath: resolve(repoRoot, 'media.login.html') },
  { slug: 'register', sourcePath: resolve(repoRoot, 'media.register.html') },
  { slug: 'verify', sourcePath: resolve(repoRoot, 'src/media.verify.html') },
  { slug: 'recover', sourcePath: resolve(repoRoot, 'src/media.recover.html') },
  { slug: 'reset', sourcePath: resolve(repoRoot, 'src/media.reset.html') },
]

/** 五个源 HTML 里完全一致的资源引用片段，用于定位替换。 */
const STYLESHEET_TAG = '<link rel="stylesheet" href="/media.auth.css" />'
const LOGIN_SCRIPT_TAG = '<script type="module" src="/media.login.js"></script>'
const HEAD_CLOSE_TAG = '</head>'
/** media.auth.css 内部对设计令牌的根路径引用。生产环境靠 nginx 把
 *  /mediaDesignTokens.css alias 到域名根，演示站没有这条 alias，必须
 *  改写成 base 前缀的路径才能在子路径部署下正确加载。 */
const TOKEN_IMPORT = '@import url("/mediaDesignTokens.css");'

/**
 * 在字符串里查找并替换第一处子串；找不到就抛出带上下文的 Error。
 * 目的是让“源文件结构变了但这里悄悄写出错误产物”这类问题在构建时就炸出来，
 * 而不是留到线上走查时才发现页面样式或脚本丢了。
 */
function replaceExpected(source: string, search: string, replacement: string, context: string): string {
  const index = source.indexOf(search)
  if (index === -1) {
    throw new Error(
      `[writeDemoAuthPages] ${context} 失败：未找到预期片段 ${JSON.stringify(search)}。` +
        '源 HTML/CSS 的结构可能已经变化，请更新 buildDemoAuthPages.ts 里的匹配逻辑。',
    )
  }
  return source.slice(0, index) + replacement + source.slice(index + search.length)
}

/** 演示横幅 + 内联提示的样式。颜色统一走 mediaDesignTokens.css 的 --mg-* 语义色
 *  令牌，并各自带一个浅色兜底值——万一令牌文件没加载出来，深浅色下依然可读。 */
function buildDemoStyleBlock(): string {
  return `<style>
      .demo-auth-banner {
        position: sticky;
        top: 0;
        z-index: 60;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        margin: 0;
        padding: 10px 20px;
        background: var(--mg-warning-soft, #fff0d2);
        color: var(--mg-warning, #a96d18);
        border-bottom: 1px solid var(--mg-border, #dde5de);
        font-family: var(--mg-font-sans, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif);
        font-size: var(--mg-text-xs, 0.8125rem);
        line-height: var(--mg-lh-snug, 1.45);
      }
      .demo-auth-banner-badge {
        flex: none;
        padding: 2px 9px;
        border-radius: var(--mg-r-full, 999px);
        background: var(--mg-warning, #a96d18);
        color: var(--mg-on-primary, #ffffff);
        font-size: var(--mg-text-2xs, 0.75rem);
        font-weight: 700;
        letter-spacing: 0.04em;
      }
      .demo-auth-notice {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 12px;
        margin: 0;
        padding: 12px 20px;
        background: var(--mg-primary-soft, #dff4e8);
        color: var(--mg-ink, #17241f);
        border-bottom: 1px solid var(--mg-border, #dde5de);
        font-size: var(--mg-text-sm, 0.875rem);
        line-height: var(--mg-lh-snug, 1.45);
      }
      .demo-auth-notice[hidden] {
        display: none;
      }
      .demo-auth-notice-text {
        margin: 0;
        flex: 1 1 260px;
      }
      .demo-auth-notice-link {
        flex: none;
        color: var(--mg-primary-dark, #10684a);
        font-weight: 700;
        text-decoration: underline;
      }
      .demo-auth-notice-close {
        flex: none;
        border: 0;
        background: transparent;
        color: var(--mg-muted, #647169);
        font-size: var(--mg-text-lg, 1.0625rem);
        line-height: 1;
        cursor: pointer;
        padding: 2px 6px;
      }
    </style>`
}

/**
 * 演示脚本本体：手写的纯 DOM 操作 JS 源码，不引入任何框架/依赖，不发起
 * fetch/XHR/EventSource。demoBase 作为立即执行函数的实参从外面传入——浏览器
 * 里没有 Node 端的任何变量，这是唯一能把部署 base 带进去的方式。
 */
function buildDemoClientScriptBody(): string {
  return `(function (demoBase) {
      document.addEventListener('DOMContentLoaded', function () {
        var BANNER_TEXT = '静态演示 · 不鉴权 · 本页仅用于走查登录注册流程的页面结构，不会创建账号，也不会发送验证码。'
        var NOTICE_TEXT = '演示站不做真实登录：这里只复刻页面结构与交互，提交不会发送任何请求。'

        // 顶部横幅：始终吸顶展示，提醒这是一份不发真实请求的静态复刻。
        var banner = document.createElement('div')
        banner.className = 'demo-auth-banner'
        banner.setAttribute('role', 'note')
        var badge = document.createElement('span')
        badge.className = 'demo-auth-banner-badge'
        badge.setAttribute('aria-hidden', 'true')
        badge.textContent = 'DEMO'
        var bannerText = document.createElement('span')
        bannerText.textContent = BANNER_TEXT
        banner.appendChild(badge)
        banner.appendChild(bannerText)
        document.body.insertBefore(banner, document.body.firstChild)

        // 内联提示：默认隐藏，用户触发一次“真实操作”（提交表单 / 点认证链接）时才展开。
        var notice = document.createElement('div')
        notice.className = 'demo-auth-notice'
        notice.setAttribute('role', 'status')
        notice.setAttribute('aria-live', 'polite')
        notice.setAttribute('tabindex', '-1')
        notice.hidden = true
        var noticeText = document.createElement('p')
        noticeText.className = 'demo-auth-notice-text'
        noticeText.textContent = NOTICE_TEXT
        var noticeLink = document.createElement('a')
        noticeLink.className = 'demo-auth-notice-link'
        noticeLink.href = demoBase
        noticeLink.textContent = '进入演示工作台 →'
        var noticeClose = document.createElement('button')
        noticeClose.type = 'button'
        noticeClose.className = 'demo-auth-notice-close'
        noticeClose.setAttribute('aria-label', '关闭提示')
        noticeClose.textContent = '×'
        noticeClose.addEventListener('click', function () {
          notice.hidden = true
        })
        notice.appendChild(noticeText)
        notice.appendChild(noticeLink)
        notice.appendChild(noticeClose)
        if (banner.parentNode) {
          banner.parentNode.insertBefore(notice, banner.nextSibling)
        }

        function showDemoNotice() {
          notice.hidden = false
          notice.focus()
        }

        // 拦截所有表单提交：演示站里填表单可以，但提交不发任何真实请求。
        var forms = document.querySelectorAll('form')
        forms.forEach(function (form) {
          form.addEventListener('submit', function (event) {
            event.preventDefault()
            showDemoNotice()
          })
        })

        // 拦截指向生产站认证接口 / 认证页面的链接（/openclaw/auth/*、/openclaw/media/*
        // 等站内导航，例如登录页之间互相跳转、返回工作台首页），这些路径在纯静态
        // 演示站里没有对应的真实后端或页面，点了会导航去一个不存在的地方。
        var links = document.querySelectorAll('a[href]')
        links.forEach(function (link) {
          var href = link.getAttribute('href') || ''
          if (/^\\/openclaw\\//.test(href)) {
            link.addEventListener('click', function (event) {
              event.preventDefault()
              showDemoNotice()
            })
          }
        })

        // 登录页比其余四页多一层“先选身份、再看到表单”的结构：生产环境的原脚本会先
        // 请求 /openclaw/auth/entry-state 判断当前浏览器有没有可用会话，据此决定展开
        // 哪个面板、要不要显示账号密码/Feishu 授权表单。演示脚本不发任何请求，这里按
        // 最常见的“未登录”态在本地直接展开对应面板，保证两种身份的表单都能被点开、
        // 填写——这仍然是纯 DOM 操作，不涉及任何网络请求。
        if (document.body.getAttribute('data-auth-page') === 'login') {
          var personalChoice = document.getElementById('personal-choice')
          var organizationChoice = document.getElementById('organization-choice')
          var passwordPanel = document.getElementById('password-panel')
          var organizationPanel = document.getElementById('organization-panel')
          var choiceStatus = document.getElementById('choice-status')

          var revealGuestState = function (mode) {
            var stateRoot = document.getElementById(mode + '-entry-state')
            if (stateRoot) {
              stateRoot.setAttribute('data-state', 'unavailable')
              stateRoot.setAttribute('aria-busy', 'false')
              var badgeEl = document.getElementById(mode + '-entry-badge')
              if (badgeEl) badgeEl.textContent = '演示模式'
              var views = stateRoot.querySelectorAll('[data-entry-view]')
              views.forEach(function (view) {
                view.hidden = view.getAttribute('data-entry-view') !== 'fallback'
              })
              var messageEl = document.getElementById(mode + '-entry-fallback-message')
              if (messageEl) {
                messageEl.textContent = mode === 'personal'
                  ? '静态演示不检测真实登录状态，请直接使用下方表单走查登录界面。'
                  : '静态演示不会真正发起 Feishu 授权，请直接查看下方页面结构。'
              }
            }
            var fallback = document.getElementById(
              mode === 'personal' ? 'personal-password-fallback' : 'organization-oauth-fallback',
            )
            if (fallback) fallback.hidden = false
          }

          var selectMode = function (mode) {
            var isPersonal = mode === 'personal'
            if (passwordPanel) passwordPanel.hidden = !isPersonal
            if (organizationPanel) organizationPanel.hidden = isPersonal
            if (personalChoice) personalChoice.setAttribute('aria-selected', String(isPersonal))
            if (organizationChoice) organizationChoice.setAttribute('aria-selected', String(!isPersonal))
            if (choiceStatus) choiceStatus.textContent = isPersonal ? '已选择：个人创作者。' : '已选择：组织成员。'
            revealGuestState(mode)
          }

          if (personalChoice) {
            personalChoice.addEventListener('click', function () {
              selectMode('personal')
            })
          }
          if (organizationChoice) {
            organizationChoice.addEventListener('click', function () {
              selectMode('organization')
            })
          }

          var backButtons = document.querySelectorAll('.back-button')
          backButtons.forEach(function (button) {
            button.addEventListener('click', function () {
              if (passwordPanel) passwordPanel.hidden = true
              if (organizationPanel) organizationPanel.hidden = true
              if (personalChoice) personalChoice.setAttribute('aria-selected', 'false')
              if (organizationChoice) organizationChoice.setAttribute('aria-selected', 'false')
              if (choiceStatus) choiceStatus.textContent = '请选择一个身份继续。'
            })
          })
        }
      })
    })`
}

/** 拼出可以直接写进 HTML 的 <script> 标签：手写脚本体 + 把部署 base 当作
 *  立即执行参数传入。 */
function buildDemoScriptTag(base: string): string {
  return `<script>\n      ${buildDemoClientScriptBody()}(${JSON.stringify(base)})\n    </script>`
}

/** 改写单个认证页：换掉样式表/脚本引用，插入演示横幅样式。 */
function transformAuthPage(html: string, base: string, slug: AuthPageSlug): string {
  let output = html

  output = replaceExpected(
    output,
    STYLESHEET_TAG,
    `<link rel="stylesheet" href="${base}media.auth.css" />`,
    `[${slug}] 改写 media.auth.css 引用`,
  )

  output = replaceExpected(
    output,
    LOGIN_SCRIPT_TAG,
    buildDemoScriptTag(base),
    `[${slug}] 替换 media.login.js 为演示脚本`,
  )

  output = replaceExpected(
    output,
    HEAD_CLOSE_TAG,
    `${buildDemoStyleBlock()}\n  ${HEAD_CLOSE_TAG}`,
    `[${slug}] 插入演示横幅样式`,
  )

  return output
}

/**
 * 把认证页依赖的静态资源落到 root 下，并返回本次实际确认存在（写入或已存在）的
 * 相对路径列表。media.auth.css 每次都按 base 重新生成（内容是 source+base 的纯
 * 函数，天然幂等）；mediaDesignTokens.css 只在主构建没有复制过的情况下兜底补上，
 * 绝不覆盖已有文件。
 */
function ensureSharedAssets(root: string, base: string): string[] {
  const authCssSource = resolve(repoRoot, 'src/media.auth.css')
  if (!existsSync(authCssSource)) {
    throw new Error(`[writeDemoAuthPages] 找不到认证页样式源文件：${authCssSource}`)
  }
  const authCssRaw = readFileSync(authCssSource, 'utf8')
  const authCssRewritten = replaceExpected(
    authCssRaw,
    TOKEN_IMPORT,
    `@import url("${base}mediaDesignTokens.css");`,
    'media.auth.css 改写设计令牌引用',
  )
  writeFileSync(resolve(root, 'media.auth.css'), authCssRewritten, 'utf8')

  const tokenDest = resolve(root, 'mediaDesignTokens.css')
  if (!existsSync(tokenDest)) {
    // 正常情况下这份文件已经由主构建（vite.demo.config.ts 的 closeBundle）复制过；
    // 这里只是兜底，保证单独调用本函数（比如自检脚本）时页面也不会因为缺样式裸奔。
    const tokenSource = resolve(repoRoot, 'src/media/mediaDesignTokens.css')
    if (!existsSync(tokenSource)) {
      throw new Error(`[writeDemoAuthPages] 找不到设计令牌源文件：${tokenSource}`)
    }
    copyFileSync(tokenSource, tokenDest)
  }

  return ['media.auth.css', 'mediaDesignTokens.css']
}

/**
 * 把登录 / 注册 / 邮箱验证 / 找回密码 / 重置密码这五个认证页复刻进演示站产物目录。
 *
 * @param options.root 产物根目录绝对路径（例如 `<repo>/openclaw-bot-center/dist-demo`）。
 * @param options.base 部署基址，形如 `/openclaw/media-demo/`，必须以 `/` 结尾。
 * @returns 写出的文件相对路径列表（相对 root）。
 */
export function writeDemoAuthPages(options: { root: string; base: string }): string[] {
  const { root, base } = options
  if (!base.endsWith('/')) {
    throw new Error(`[writeDemoAuthPages] base 必须以 "/" 结尾，收到：${JSON.stringify(base)}`)
  }

  mkdirSync(root, { recursive: true })

  const written: string[] = [...ensureSharedAssets(root, base)]

  for (const page of AUTH_PAGES) {
    if (!existsSync(page.sourcePath)) {
      throw new Error(`[writeDemoAuthPages] 找不到 ${page.slug} 页的源 HTML：${page.sourcePath}`)
    }
    const raw = readFileSync(page.sourcePath, 'utf8')
    const transformed = transformAuthPage(raw, base, page.slug)
    const pageDir = resolve(root, page.slug)
    mkdirSync(pageDir, { recursive: true })
    writeFileSync(resolve(pageDir, 'index.html'), transformed, 'utf8')
    written.push(`${page.slug}/index.html`)
  }

  return written
}
