# OpenClaw Media 前端美化改造方案

日期：2026-08-26
范围：`openclaw-bot-center` — `src/media/**`（MediaStudioApp 生产壳层与全部业务页）
对标：`ValentinoWang/MediaClaw-Web`（MediaClaw 官网重建版）
原型：[`prototype/workboard-redesign.html`](./prototype/workboard-redesign.html)

---

## 0. 一句话结论

> 当前前端**不是"不好看"，而是"没有系统"**。
> 89 种字号、132 个硬编码色值、36 种圆角、49 种阴影、182 个 `:hover` 却只有 8 个 `transition`——
> 这些数字本身就是问题。**先补一层设计令牌（token）与动效层，再谈视觉。**

对标结果同样重要：**不要照抄竞品的 CSS 工程质量**（它 785 行 CSS 里塞了 98 种字号，比本项目更散）。
真正值得抄的是它的 **视觉语言**：Web 字体、暗色模式、粉彩卡片色族、大字重标题、慷慨留白、悬停位移。

---

## 1. 现状体检（可复现的硬数据）

复现命令（在 `openclaw-bot-center/src/media` 下执行）：

```bash
# 字号种类
grep -rhoE 'font-size: *[^;]+' --include=*.css . | sed 's/font-size: *//' | sort -u | wc -l
# 硬编码色值
grep -rhoE '#[0-9a-fA-F]{3,8}\b' --include=*.css . | tr 'A-F' 'a-f' | sort -u | wc -l
# 过渡 vs 悬停
grep -rhoE 'transition: *[^;]+' --include=*.css . | wc -l
grep -rho ':hover' --include=*.css . | wc -l
```

### 1.1 与竞品的量化对比

| 指标 | openclaw-media（工作台） | MediaClaw-Web（官网） | 判定 |
|---|---:|---:|---|
| CSS 总行数 | 19,460 | 785 | — |
| 字号种类 | **89** | 98 | 双方都差，但本项目字号**过小** |
| 最常用字号 | **0.68rem ≈ 10.9px** | **12–13px**，正文 lead 17px | ❌ 关键差距 |
| 最小在用字号 | **0.53rem ≈ 8.5px** | 9px | ❌ |
| 硬编码色值 | **132 种 / 200 处** | 121 种 | ❌ 双方都差 |
| 圆角种类 | **36**（最常用 5px/6px/4px） | 22 | ❌ 小圆角与 22px Hero 混用 |
| 阴影种类 | **49** | 22 | ❌ |
| `transition` 声明 | **8** | 7 | — |
| `:hover` 规则 | **182** | 42 | ❌ **174 个悬停态是瞬间跳变** |
| 暗色模式 | **0 处** `prefers-color-scheme` | 完整 `[data-theme='dark']` 调色板 | ❌ 关键差距 |
| Web 字体 | 无（系统 Inter 回退） | DM Sans + Noto Sans SC (400–800) | ❌ 关键差距 |
| 产品截图 / 视觉锚点 | 无 | Hero 窗口 mockup + 真实截图 | ❌ 关键差距 |
| 区块留白 | `gap: 20–22px` | `padding: 105px 0 112px` | ❌ 拥挤 |

### 1.2 根因一：两套 token 系统，19/25 被静默覆盖

`src/media/main.tsx` 的导入顺序：

```ts
import './media.css'            // 定义 :root，25 个 token（OKLCH 色彩空间）
import './mediaStudioTheme.css' // 又定义 :root，20 个 token（HEX）—— 后者胜出
```

两个文件同为 `:root` 选择器、同等特异性，**后导入者全量覆盖**。实测冲突：

| Token | media.css（失效） | mediaStudioTheme.css（生效） |
|---|---|---|
| `--mg-primary` | `oklch(0.49 0.115 166)` | `#239b69` |
| `--mg-bg` | `oklch(0.975 0.004 175)` | `#f4f6f1` |
| `--mg-ink` | `oklch(0.235 0.018 230)` | `#17241f` |
| `--mg-radius` | `8px` | `12px` |
| …共 **19 个** | OKLCH | HEX |

**后果**：`media.css` 里精心调过的 OKLCH 色彩体系是**死代码**。任何人改 `media.css` 的颜色都不会生效，
只会在 code review 里被当成"改过了"。这是最危险的一类问题——**沉默失败**。

幸存的 6 个（仅在 media.css 定义）：`--mg-level-one/two/three`、`--mg-control-height-sm/md`、`--mg-panel-heading-height`。

### 1.3 根因二：正文字号系统性过小

字号使用频次 Top 8（全部 `src/media/**/*.css`）：

| 字号 | 折合 px | 出现次数 |
|---|---:|---:|
| `0.68rem` | **10.9px** | 107 |
| `.74rem` | 11.8px | 83 |
| `0.64rem` | **10.2px** | 71 |
| `0.62rem` | **9.9px** | 71 |
| `0.7rem` | 11.2px | 68 |
| `0.66rem` | **10.6px** | 66 |
| `0.72rem` | 11.5px | 59 |
| `0.61rem` | **9.8px** | 52 |

同时 Hero 标题是 `clamp(2rem, 3.2vw, 3.35rem)` = **32–53px**。

**Hero 53px : 正文 10.9px ≈ 5:1**，中间层级全部被压缩在 10–12px 的区间里。
结果是：**标题很响亮，内容读不清**——这与"凸显内容"的目标正好相反。

### 1.4 根因三：174 个悬停态没有过渡

182 个 `:hover` 规则，只有 8 条 `transition`。**这是"廉价感"最直接、也最便宜修复的来源。**
鼠标划过时颜色瞬间跳变（0ms），大脑读到的是"网页"而不是"产品"。

### 1.5 根因四：组件复制粘贴

| 类名 | 在多少个 `.module.css` 里被重复定义 |
|---|---:|
| `.page` | 20 |
| `.panelHeader` | 12 |
| `.metric` | 9 |
| `.emptyState` | 9 |
| `.secondaryButton` | 8 |
| `.statusBadge` | 7 |
| `.primaryButton` | 7 |
| `.panelState` | 5 |
| `.hero` | 4 |

四个 Studio 页（Workboard / Campaigns / Business / Desk）的 `.hero` 是**逐行复制**的，
只有色值不同：绿 `#239b69` / 紫 `#5b4bb5` / 橙 `#ad6426` / 蓝 `#376da9`。

> 模块用不同色系区分是**正确的产品判断**，但实现方式错了——应该是一个组件 + 一组 accent token。

---

## 2. 竞品可借鉴清单（`MediaClaw-Web`）

逐条标注"是否采纳"，避免盲抄。

| # | 竞品做法 | 源码位置 | 采纳 | 说明 |
|---|---|---|:---:|---|
| 1 | DM Sans + Noto Sans SC，字重 400–800 | `src/styles.css:1` | ✅ | 中文产品的观感分水岭 |
| 2 | `:root[data-theme='dark']` 完整暗色调色板 | `src/styles.css:3` | ✅ | 本项目 0 支持 |
| 3 | 6 色粉彩卡片族 mint/lavender/peach/blue/yellow/green | `.feature-card.*` | ✅ | 直接映射到本项目 6 个业务模块 |
| 4 | `.button:hover { transform: translateY(-2px) }` + 阴影增长 | `.button` | ✅ | 悬停位移，成本极低 |
| 5 | 单一大阴影 token `0 24px 70px rgba(37,57,47,.12)` | `--shadow` | ✅ | 收敛 49 种阴影 |
| 6 | 标题 `font-weight: 800; letter-spacing: -.065em` | `.hero-copy h1` | ✅ | 本项目标题字重偏轻 |
| 7 | 区块 `padding: 105px 0 112px` 的呼吸感 | `.features-section` | ⚠️ 折中 | 官网可以，工作台需按 `48/64px` 收敛 |
| 8 | Hero 产品窗口 mockup（`rotate(2.2deg)` + 有机 blob 背景） | `.hero-window` / `.visual-backdrop` | ⚠️ 改造 | 工作台内改为**真实数据缩略图**，不放假截图 |
| 9 | 胶囊 tab（`border-radius: 999px`，激活态深色填充） | `.platform-tab` | ✅ | 替换现有方形 `.mode-switch` |
| 10 | 平台图标带品牌底色（小红书 `#ffe1e5`/`#cc4661`） | `.platform-icon.xhs` | ✅ | 本项目已有 `PlatformBrandIcon`，补底色即可 |
| 11 | `scroll-behavior: smooth` + 头部 `backdrop-filter: blur(18px)` | `html` / `.site-header` | ✅ | 顶栏已有 blur，补 smooth |
| 12 | 98 种字号、121 个硬编码 hex | 全局 | ❌ **不要抄** | 比本项目更散 |

---

## 3. 改造方案：四层结构

```text
┌─ Layer 0  mediaDesignTokens.css   ← 新增。唯一 token 真源，最先导入
├─ Layer 1  mediaStudioTheme.css    ← 删除 :root 块，改为消费 token
├─ Layer 2  mediaPrimitives.css     ← 新增。抽出 hero / metric / panel / badge / empty
└─ Layer 3  *.module.css            ← 只保留每页真正的差异
```

导入顺序（`src/media/main.tsx`）：

```ts
import './mediaDesignTokens.css'   // ① 新增，必须最先
import './media.css'               // ② 保持不动（受 QA 契约保护）
import './mediaPrimitives.css'     // ③ 新增
import './mediaStudioTheme.css'    // ④ 已有，改为消费 token
```

### ⚠️ 3.0 不可触碰的 QA 契约

`scripts/qa/checkMediaDesignSystemContract.ts` 对 **`media.css` 的字面内容**做正则断言。
以下内容**必须原样保留在 `media.css` 中**，否则 `npm run build:media` 直接失败：

| 契约 | 断言内容 |
|---|---|
| 组件尺寸 token | `--mg-control-height-sm: 36px;` `--mg-control-height-md: 44px;` `--mg-panel-heading-height: 54px;` **三者必须相邻同序** |
| 主按钮高度 | `min-height: var(--mg-control-height-md)` |
| 面板标题高度 | `min-height: var(--mg-panel-heading-height)` |
| 任务抽屉 | `.task-drawer { … width: min(500px, 100%) … }` |
| 表格基线 | `.data-table th, .data-table td { … vertical-align: top … }` |
| 持久轨布局 | `[data-page-layout="persistent-rail"]` 系列（stretch / `padding-bottom: 0` / 等高 / 760px 断点释放） |
| Prelude 视口 | `.fidelity-page:has(> [data-page-prelude])` 的 `height: calc(100dvh - var(--mg-shell-topbar, 86px) - 46px)` |
| 发布页比例 | `PublishingPage.module.css` 的 `minmax(0, 3fr) minmax(360px, 2fr)` |
| 自适应字段行 | `.required-field-group .dynamic-fields { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)) }` |

**因此本方案是"增量加层"，不是"重写 media.css"。**

另注：契约里写 `var(--mg-shell-topbar, 86px)`，而 `mediaStudioTheme.css` 实际设为 `68px`。
两者不一致（回退值 86 从未生效）。改造时统一为 token，不要改动契约正则匹配到的那行字面量。

---

## 4. P0 改造项（本周，按性价比排序）

### P0-1 ⭐ 新建 `src/media/mediaDesignTokens.css`

> **收益最高的单个文件。** 一次性解决 token 双源、字号、圆角、阴影、动效、暗色模式。

<details>
<summary><b>完整文件内容（可直接落盘）</b></summary>

```css
/* =========================================================================
   MediaClaw 设计令牌 —— 唯一真源
   必须在 media.css / mediaStudioTheme.css 之前导入。
   ========================================================================= */

@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;600;700;800&display=swap');

:root {
  /* ---- 字阶（root = 16px）------------------------------------------------
     替代当前 89 种散装字号。最小 12px，正文默认 14px。 */
  --mg-text-2xs: 0.75rem;    /* 12px  角标 / 时间戳 / 表头 */
  --mg-text-xs:  0.8125rem;  /* 13px  辅助说明 / 卡片副文案 */
  --mg-text-sm:  0.875rem;   /* 14px  正文默认 ← 主力 */
  --mg-text-md:  0.9375rem;  /* 15px  强调正文 */
  --mg-text-lg:  1.0625rem;  /* 17px  卡片标题 */
  --mg-text-xl:  1.375rem;   /* 22px  面板标题 */
  --mg-text-2xl: 1.75rem;    /* 28px  页面标题 */
  --mg-text-3xl: clamp(2rem, 2.6vw, 2.75rem); /* 32–44px Hero（较原 53px 收敛） */

  --mg-lh-tight: 1.25;
  --mg-lh-snug:  1.45;
  --mg-lh-base:  1.65;

  --mg-font-sans: 'DM Sans', 'Noto Sans SC', Inter, ui-sans-serif, system-ui,
                  -apple-system, 'Segoe UI', 'PingFang SC',
                  'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  --mg-font-num:  'DM Sans', ui-monospace, 'SF Mono', monospace;

  /* ---- 圆角（替代 36 种）---- */
  --mg-r-xs: 6px;
  --mg-r-sm: 8px;
  --mg-r-md: 12px;
  --mg-r-lg: 16px;
  --mg-r-xl: 22px;
  --mg-r-full: 999px;

  /* ---- 高度层级（替代 49 种阴影）---- */
  --mg-shadow-color: 220 12% 18%;
  --mg-e1: 0 1px 2px hsl(var(--mg-shadow-color) / .05);
  --mg-e2: 0 4px 12px hsl(var(--mg-shadow-color) / .06);
  --mg-e3: 0 10px 28px hsl(var(--mg-shadow-color) / .08);
  --mg-e4: 0 24px 60px hsl(var(--mg-shadow-color) / .10);

  /* ---- 动效 ---- */
  --mg-ease: cubic-bezier(.2, .7, .3, 1);
  --mg-ease-out: cubic-bezier(.16, 1, .3, 1);
  --mg-dur-1: 120ms;   /* 颜色 */
  --mg-dur-2: 190ms;   /* 阴影 / 位移 */
  --mg-dur-3: 280ms;   /* 展开 / 抽屉 */

  /* ---- 间距节奏 ---- */
  --mg-gap-1: 8px;
  --mg-gap-2: 12px;
  --mg-gap-3: 18px;
  --mg-gap-4: 26px;
  --mg-gap-5: 40px;
  --mg-gap-6: 64px;

  /* ---- 语义色（浅色）---- */
  --mg-bg:            #f4f6f1;
  --mg-bg-sunken:     #eceff0;
  --mg-surface:       #ffffff;
  --mg-surface-raised:#ffffff;
  --mg-ink:           #17241f;
  --mg-ink-soft:      #3f4f47;
  --mg-muted:         #68756e;
  --mg-border:        #dde5de;
  --mg-border-strong: #cbd7ce;

  --mg-primary:       #239b69;
  --mg-primary-dark:  #126344;
  --mg-primary-soft:  #dff4e8;
  --mg-teal-soft:     #e2f3f1;
  --mg-blue:          #4179b8;
  --mg-blue-soft:     #e8f1fb;
  --mg-warning:       #a96d18;
  --mg-warning-soft:  #fff0d2;
  --mg-danger:        #bd5147;
  --mg-danger-soft:   #fde9e6;

  --mg-sidebar:       #173029;
  --mg-sidebar-muted: rgba(233, 246, 238, .62);

  /* ---- 业务模块 accent 族（替代 132 个硬编码 hex）----
     用法：<main data-accent="campaign">，模块内一律 var(--accent-*)。 */
  --mg-accent-studio-ink:   #0f6a49;  --mg-accent-studio-base:  #239b69;
  --mg-accent-studio-soft:  #dff4e8;  --mg-accent-studio-line:  #b5e3cc;

  --mg-accent-campaign-ink: #4e419d;  --mg-accent-campaign-base:#5b4bb5;
  --mg-accent-campaign-soft:#efecff;  --mg-accent-campaign-line:#ded9fa;

  --mg-accent-business-ink: #95551f;  --mg-accent-business-base:#ad6426;
  --mg-accent-business-soft:#fff0df;  --mg-accent-business-line:#f0dcc6;

  --mg-accent-desk-ink:     #2f6198;  --mg-accent-desk-base:    #376da9;
  --mg-accent-desk-soft:    #eaf2fc;  --mg-accent-desk-line:    #cfdeef;

  --mg-accent-agent-ink:    #14706b;  --mg-accent-agent-base:   #1a908a;
  --mg-accent-agent-soft:   #e0f4f2;  --mg-accent-agent-line:   #bde5e1;

  --mg-accent-archive-ink:  #6b5a44;  --mg-accent-archive-base: #8a7458;
  --mg-accent-archive-soft: #f5efe6;  --mg-accent-archive-line: #e5dbca;

  /* 默认 accent = studio；由 [data-accent] 覆盖 */
  --accent-ink:  var(--mg-accent-studio-ink);
  --accent-base: var(--mg-accent-studio-base);
  --accent-soft: var(--mg-accent-studio-soft);
  --accent-line: var(--mg-accent-studio-line);

  /* ---- 平台品牌标（浅色）---- */
  --mg-brand-xhs-ink: #cc4661;    --mg-brand-xhs-soft: #ffe1e5;
  --mg-brand-douyin-ink: #108b88; --mg-brand-douyin-soft: #dff5f2;
  --mg-brand-wx-ink: #2b7a3f;     --mg-brand-wx-soft: #ddf3e1;

  /* ---- 兼容旧 token ---- */
  --mg-radius: var(--mg-r-md);
  --mg-shell-topbar: 68px;

  color-scheme: light;
  font-family: var(--mg-font-sans);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}

[data-accent='studio']   { --accent-ink: var(--mg-accent-studio-ink);   --accent-base: var(--mg-accent-studio-base);   --accent-soft: var(--mg-accent-studio-soft);   --accent-line: var(--mg-accent-studio-line); }
[data-accent='campaign'] { --accent-ink: var(--mg-accent-campaign-ink); --accent-base: var(--mg-accent-campaign-base); --accent-soft: var(--mg-accent-campaign-soft); --accent-line: var(--mg-accent-campaign-line); }
[data-accent='business'] { --accent-ink: var(--mg-accent-business-ink); --accent-base: var(--mg-accent-business-base); --accent-soft: var(--mg-accent-business-soft); --accent-line: var(--mg-accent-business-line); }
[data-accent='desk']     { --accent-ink: var(--mg-accent-desk-ink);     --accent-base: var(--mg-accent-desk-base);     --accent-soft: var(--mg-accent-desk-soft);     --accent-line: var(--mg-accent-desk-line); }
[data-accent='agent']    { --accent-ink: var(--mg-accent-agent-ink);    --accent-base: var(--mg-accent-agent-base);    --accent-soft: var(--mg-accent-agent-soft);    --accent-line: var(--mg-accent-agent-line); }
[data-accent='archive']  { --accent-ink: var(--mg-accent-archive-ink);  --accent-base: var(--mg-accent-archive-base);  --accent-soft: var(--mg-accent-archive-soft);  --accent-line: var(--mg-accent-archive-line); }

/* ---- 暗色模式：系统偏好 + 手动开关双通道 ---- */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) {
    color-scheme: dark;
    --mg-bg: #131c18;  --mg-bg-sunken: #0f1714;
    --mg-surface: #1a2621;  --mg-surface-raised: #202e28;
    --mg-ink: #e8f2ec;  --mg-ink-soft: #c2d2c9;  --mg-muted: #93a69c;
    --mg-border: #2c3b34;  --mg-border-strong: #3c4f46;
    --mg-primary: #4ec48d;  --mg-primary-dark: #7ad9ab;  --mg-primary-soft: #1c3d30;
    --mg-teal-soft: #17383a;
    --mg-blue: #7db4ea;  --mg-blue-soft: #1b2f42;
    --mg-warning: #d9a24a;  --mg-warning-soft: #3a2c14;
    --mg-danger: #e8877c;  --mg-danger-soft: #3d201c;
    --mg-sidebar: #0f1a16;
    --mg-shadow-color: 160 30% 3%;
    --mg-e1: 0 1px 2px hsl(var(--mg-shadow-color) / .30);
    --mg-e2: 0 4px 12px hsl(var(--mg-shadow-color) / .36);
    --mg-e3: 0 10px 28px hsl(var(--mg-shadow-color) / .44);
    --mg-e4: 0 24px 60px hsl(var(--mg-shadow-color) / .52);
    --mg-accent-studio-soft:  #17392c;  --mg-accent-studio-line:  #245842;  --mg-accent-studio-ink:  #6fd4a5;
    --mg-accent-campaign-soft:#262247;  --mg-accent-campaign-line:#3b3470;  --mg-accent-campaign-ink:#a99bec;
    --mg-accent-business-soft:#3a2a17;  --mg-accent-business-line:#57401f;  --mg-accent-business-ink:#e0a668;
    --mg-accent-desk-soft:    #1c2f44;  --mg-accent-desk-line:    #2b4767;  --mg-accent-desk-ink:    #8fbdea;
    --mg-accent-agent-soft:   #133533;  --mg-accent-agent-line:   #1e5350;  --mg-accent-agent-ink:   #63cdc6;
    --mg-accent-archive-soft: #302819;  --mg-accent-archive-line: #4a3d28;  --mg-accent-archive-ink: #cbb794;
    --mg-brand-xhs-ink: #ff8fa3;    --mg-brand-xhs-soft: #45222a;
    --mg-brand-douyin-ink: #4fd6d1; --mg-brand-douyin-soft: #14383a;
    --mg-brand-wx-ink: #6fcf8a;     --mg-brand-wx-soft: #17361f;
  }
}

:root[data-theme='dark'] {
  color-scheme: dark;
  --mg-bg: #131c18;  --mg-bg-sunken: #0f1714;
  --mg-surface: #1a2621;  --mg-surface-raised: #202e28;
  --mg-ink: #e8f2ec;  --mg-ink-soft: #c2d2c9;  --mg-muted: #93a69c;
  --mg-border: #2c3b34;  --mg-border-strong: #3c4f46;
  --mg-primary: #4ec48d;  --mg-primary-dark: #7ad9ab;  --mg-primary-soft: #1c3d30;
  --mg-teal-soft: #17383a;
  --mg-blue: #7db4ea;  --mg-blue-soft: #1b2f42;
  --mg-warning: #d9a24a;  --mg-warning-soft: #3a2c14;
  --mg-danger: #e8877c;  --mg-danger-soft: #3d201c;
  --mg-sidebar: #0f1a16;
  --mg-shadow-color: 160 30% 3%;
  --mg-e1: 0 1px 2px hsl(var(--mg-shadow-color) / .30);
  --mg-e2: 0 4px 12px hsl(var(--mg-shadow-color) / .36);
  --mg-e3: 0 10px 28px hsl(var(--mg-shadow-color) / .44);
  --mg-e4: 0 24px 60px hsl(var(--mg-shadow-color) / .52);
  --mg-accent-studio-soft:  #17392c;  --mg-accent-studio-line:  #245842;  --mg-accent-studio-ink:  #6fd4a5;
  --mg-accent-campaign-soft:#262247;  --mg-accent-campaign-line:#3b3470;  --mg-accent-campaign-ink:#a99bec;
  --mg-accent-business-soft:#3a2a17;  --mg-accent-business-line:#57401f;  --mg-accent-business-ink:#e0a668;
  --mg-accent-desk-soft:    #1c2f44;  --mg-accent-desk-line:    #2b4767;  --mg-accent-desk-ink:    #8fbdea;
  --mg-accent-agent-soft:   #133533;  --mg-accent-agent-line:   #1e5350;  --mg-accent-agent-ink:   #63cdc6;
  --mg-accent-archive-soft: #302819;  --mg-accent-archive-line: #4a3d28;  --mg-accent-archive-ink: #cbb794;
  --mg-brand-xhs-ink: #ff8fa3;    --mg-brand-xhs-soft: #45222a;
  --mg-brand-douyin-ink: #4fd6d1; --mg-brand-douyin-soft: #14383a;
  --mg-brand-wx-ink: #6fcf8a;     --mg-brand-wx-soft: #17361f;
}

/* ---- 全局动效兜底：一次性覆盖 174 个无过渡的悬停态 ---- */
a, button, summary, input, select, textarea,
[role='button'], [role='tab'], [role='menuitem'],
.studio-nav-link, .section-panel, .data-table tbody tr {
  transition:
    color var(--mg-dur-1) var(--mg-ease),
    background-color var(--mg-dur-1) var(--mg-ease),
    border-color var(--mg-dur-1) var(--mg-ease),
    box-shadow var(--mg-dur-2) var(--mg-ease),
    transform var(--mg-dur-2) var(--mg-ease),
    opacity var(--mg-dur-1) var(--mg-ease);
}

html { scroll-behavior: smooth; }

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after {
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 1ms !important;
    scroll-behavior: auto !important;
  }
}
```

</details>

**落盘后同步修改 `src/media/main.tsx`：**

```diff
  import { StrictMode } from 'react'
  import { createRoot } from 'react-dom/client'
  import MediaStudioApp from './MediaStudioApp'
+ import './mediaDesignTokens.css'
  import './media.css'
+ import './mediaPrimitives.css'
  import './mediaStudioTheme.css'
```

---

### P0-2 ⭐ 删除 `mediaStudioTheme.css` 的 `:root` 块

`src/media/mediaStudioTheme.css` **第 1–21 行整块删除**（token 已移入 Layer 0）。

```diff
- :root {
-   --mg-bg: #f4f6f1;
-   --mg-surface: #ffffff;
-   ... 共 20 行 ...
-   --mg-radius: 12px;
-   --mg-shell-topbar: 68px;
- }
-
  .studio-shell {
```

> 删除后 `media.css` 的 `:root` 重新生效，但其值会被 Layer 0 覆盖（Layer 0 先导入 ⇒ 后导入的 media.css 会赢）。
> **因此 Layer 0 的语义色必须同时写进 `media.css` 的 `:root`，或把 media.css 的 `:root` 颜色行删掉。**
> 推荐后者：`media.css` 的 `:root` **只保留受 QA 契约保护的三个尺寸 token**：
>
> ```css
> :root {
>   --mg-control-height-sm: 36px;
>   --mg-control-height-md: 44px;
>   --mg-panel-heading-height: 54px;
>   --mg-level-one: oklch(0.58 0.09 165);
>   --mg-level-two: oklch(0.6 0.1 250);
>   --mg-level-three: oklch(0.67 0.11 72);
> }
> ```
>
> 三个尺寸 token **必须相邻同序**，QA 正则 `--mg-control-height-sm: 36px;[\s\S]*?--mg-control-height-md: 44px;[\s\S]*?--mg-panel-heading-height: 54px;` 依赖此顺序。

**验证**：`npm run qa:media-design-system-contract` 必须通过。

---

### P0-3 ⭐ 新建 `src/media/mediaPrimitives.css`（收敛 4 份 Hero + 9 份 metric + 12 份 panelHeader）

<details>
<summary><b>完整文件内容</b></summary>

```css
/* =========================================================================
   MediaClaw 共享组件原语
   替代散落在 20 个 *.module.css 里的重复定义。
   所有色彩走 var(--accent-*)，由祖先的 [data-accent] 决定。
   ========================================================================= */

.mg-page { display: grid; gap: var(--mg-gap-4); width: min(100%, 1480px); margin: 0 auto; }

/* ---- Hero（原 4 份复制 → 1 份） ---- */
.mg-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(250px, 330px);
  gap: var(--mg-gap-4);
  overflow: hidden;
  padding: 30px 32px;
  border: 1px solid var(--accent-line);
  border-radius: var(--mg-r-xl);
  background:
    radial-gradient(circle at 84% 10%, var(--accent-soft), transparent 38%),
    linear-gradient(140deg, var(--mg-surface), var(--mg-bg) 62%, var(--accent-soft));
  box-shadow: var(--mg-e3);
}
.mg-hero::after {
  position: absolute; right: -90px; bottom: -130px;
  width: 300px; height: 300px; border-radius: 50%;
  background: color-mix(in srgb, var(--accent-base) 7%, transparent);
  content: '';
}
.mg-hero > * { position: relative; z-index: 1; }

.mg-eyebrow {
  display: inline-flex; align-items: center; gap: var(--mg-gap-1);
  color: var(--accent-ink);
  font-size: var(--mg-text-2xs); font-weight: 800; letter-spacing: .11em;
  text-transform: uppercase;
}
.mg-hero h1 {
  margin: 14px 0 12px;
  font-size: var(--mg-text-3xl);
  font-weight: 800;
  line-height: 1.08;
  letter-spacing: -.045em;
}
.mg-hero-lead {
  max-width: 68ch; margin: 0;
  color: var(--mg-muted);
  font-size: var(--mg-text-md); line-height: var(--mg-lh-base);
}

/* ---- 按钮 ---- */
.mg-btn {
  display: inline-flex; min-height: var(--mg-control-height-md);
  align-items: center; justify-content: center; gap: 7px;
  padding: 0 16px;
  border-radius: var(--mg-r-sm);
  font-size: var(--mg-text-sm); font-weight: 700;
  text-decoration: none; cursor: pointer;
}
.mg-btn:hover { transform: translateY(-2px); }
.mg-btn:active { transform: translateY(0); }
.mg-btn-primary {
  border: 1px solid var(--accent-base);
  color: #fff; background: var(--accent-base);
  box-shadow: 0 10px 22px color-mix(in srgb, var(--accent-base) 24%, transparent);
}
.mg-btn-primary:hover { box-shadow: 0 14px 28px color-mix(in srgb, var(--accent-base) 34%, transparent); }
.mg-btn-soft  { border: 1px solid var(--accent-line); color: var(--accent-ink); background: var(--accent-soft); }
.mg-btn-ghost { border: 1px solid var(--mg-border-strong); color: var(--mg-ink); background: var(--mg-surface); }

/* ---- 指标卡（原 9 份复制 → 1 份） ---- */
.mg-metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--mg-gap-2); }
/* 指标卡：图标 + 文案一行，sparkline 独占底部整行并出血到卡片边缘。
   ⚠️ 不要把 sparkline 挤成第三列——4 栏布局下文案只剩 ~106px，
   「已发布作品」会断成「已发布作 / 品」。这是原型里实测到的回归。 */
.mg-metric {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  grid-template-areas: 'icon body' 'spark spark';
  gap: var(--mg-gap-2); align-items: center; min-width: 0; overflow: hidden;
  padding: var(--mg-gap-3) var(--mg-gap-3) 0;
  border: 1px solid var(--mg-border);
  border-radius: var(--mg-r-lg);
  background: var(--mg-surface);
  box-shadow: var(--mg-e1);
}
.mg-metric:hover { border-color: var(--accent-line); box-shadow: var(--mg-e2); transform: translateY(-2px); }
.mg-metric-icon {
  grid-area: icon;
  display: grid; width: 44px; height: 44px; place-items: center;
  border-radius: var(--mg-r-md);
  color: var(--accent-ink); background: var(--accent-soft);
}
.mg-metric-body { grid-area: body; min-width: 0; }
.mg-metric-body small {
  display: block; overflow: hidden; color: var(--mg-muted);
  font-size: var(--mg-text-xs); text-overflow: ellipsis; white-space: nowrap;
}
.mg-metric-body strong {
  display: block; margin: 3px 0 1px;
  font-family: var(--mg-font-num);
  font-size: var(--mg-text-2xl); font-weight: 700; line-height: 1;
  letter-spacing: -.03em; font-variant-numeric: tabular-nums;
}
.mg-metric-body p {
  margin: 0; overflow: hidden; color: var(--mg-muted); font-size: var(--mg-text-2xs);
  text-overflow: ellipsis; white-space: nowrap;
}
.mg-metric-spark {
  grid-area: spark; display: block; height: 38px;
  width: calc(100% + var(--mg-gap-3) * 2);
  margin-left: calc(var(--mg-gap-3) * -1);
}

/* ---- 面板（原 12 份 panelHeader → 1 份） ---- */
.mg-panel {
  overflow: hidden; min-width: 0;
  border: 1px solid var(--mg-border);
  border-radius: var(--mg-r-lg);
  background: var(--mg-surface);
  box-shadow: var(--mg-e2);
}
.mg-panel-head {
  display: flex; min-height: var(--mg-panel-heading-height);
  align-items: center; justify-content: space-between; gap: var(--mg-gap-2);
  padding: 14px var(--mg-gap-3);
  border-bottom: 1px solid var(--mg-border);
}
.mg-panel-head span { display: block; color: var(--mg-muted); font-size: var(--mg-text-2xs); font-weight: 700; }
.mg-panel-head h2   { margin: 3px 0 0; font-size: var(--mg-text-lg); font-weight: 700; letter-spacing: -.02em; }

/* ---- 状态徽章（原 7 份 → 1 份） ---- */
.mg-badge {
  display: inline-flex; min-height: 28px; flex: 0 0 auto;
  align-items: center; gap: 5px; padding: 0 10px;
  border: 1px solid var(--mg-border); border-radius: var(--mg-r-full);
  color: var(--mg-muted); background: var(--mg-surface);
  font-size: var(--mg-text-2xs); font-weight: 700;
}
.mg-badge[data-tone='success'] { color: var(--mg-primary-dark); border-color: color-mix(in srgb, var(--mg-primary) 32%, var(--mg-border)); background: var(--mg-primary-soft); }
.mg-badge[data-tone='warning'] { color: var(--mg-warning);      border-color: color-mix(in srgb, var(--mg-warning) 28%, var(--mg-border)); background: var(--mg-warning-soft); }
.mg-badge[data-tone='danger']  { color: var(--mg-danger);       border-color: color-mix(in srgb, var(--mg-danger) 28%, var(--mg-border));  background: var(--mg-danger-soft); }
.mg-badge[data-tone='info']    { color: var(--mg-blue);         border-color: color-mix(in srgb, var(--mg-blue) 28%, var(--mg-border));    background: var(--mg-blue-soft); }

/* ---- 空态（原 9 份 → 1 份） ---- */
.mg-empty {
  display: flex; min-height: 280px; flex-direction: column;
  align-items: center; justify-content: center;
  padding: var(--mg-gap-5);
  color: var(--mg-muted); text-align: center;
}
.mg-empty > svg  { color: var(--accent-base); }
.mg-empty strong { margin-top: var(--mg-gap-2); color: var(--mg-ink); font-size: var(--mg-text-md); }
.mg-empty p      { max-width: 52ch; margin: 7px 0 0; font-size: var(--mg-text-xs); line-height: var(--mg-lh-snug); }

/* ---- 流水线轨道（新增，用于"凸显内容"）---- */
.mg-pipeline { display: flex; align-items: center; gap: 0; }
.mg-pipeline-step {
  position: relative; display: flex; min-width: 0; flex: 1;
  flex-direction: column; gap: 6px; padding: 10px 12px;
}
.mg-pipeline-step::before {
  height: 4px; border-radius: var(--mg-r-full);
  background: var(--mg-border); content: '';
}
.mg-pipeline-step[data-state='done']::before    { background: var(--accent-base); }
.mg-pipeline-step[data-state='current']::before { background: linear-gradient(90deg, var(--accent-base) 55%, var(--mg-border) 55%); }
.mg-pipeline-step > strong { font-size: var(--mg-text-2xs); font-weight: 700; color: var(--mg-muted); }
.mg-pipeline-step[data-state='done'] > strong,
.mg-pipeline-step[data-state='current'] > strong { color: var(--mg-ink); }

@media (max-width: 1120px) { .mg-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .mg-hero { grid-template-columns: 1fr; padding: 22px; border-radius: var(--mg-r-lg); }
  .mg-metric-grid { grid-template-columns: 1fr; }
  .mg-pipeline { flex-wrap: wrap; }
}
```

</details>

---

### P0-4 ⭐ 用 accent token 替换 132 个硬编码 hex

**改法**：给每个 Studio 页的根元素加 `data-accent`，然后模块 CSS 里把 hex 全部换成 `var(--accent-*)`。

`src/media/studio/CampaignsPage.tsx`（Business / Desk / Workboard 同理）：

```diff
- <main className={styles.page}>
+ <main className={styles.page} data-accent="campaign">
```

`src/media/studio/CampaignsPage.module.css` 替换映射：

| 原值 | 替换为 |
|---|---|
| `#5b4bb5` | `var(--accent-base)` |
| `#4e419d` / `#5144a9` | `var(--accent-ink)` |
| `#efecff` / `#f3f0ff` | `var(--accent-soft)` |
| `#ded9fa` / `#d5cff5` / `#d8d2f3` | `var(--accent-line)` |
| `#8c7be1` | `color-mix(in srgb, var(--accent-base) 72%, white)` |
| `#b2abc9` | `var(--mg-muted)` |

`BusinessPage.module.css`：`#ad6426`→`--accent-base`、`#95551f`→`--accent-ink`、`#fff0df`/`#fff7ef`→`--accent-soft`、`#f0dcc6`/`#efd4ba`→`--accent-line`、`#c5a98d`→`var(--mg-muted)`。

`DeskPage.module.css`：`#376da9`→`--accent-base`、`#2f6198`→`--accent-ink`、`#eaf2fc`/`#f2f7fd`→`--accent-soft`、`#cfdeef`/`#cbdced`/`#7aa3d0`→`--accent-line`、`#9aafc5`→`var(--mg-muted)`。
其 `.moduleCard[data-tone]` 的 4 组色（`#9c6036`/`#7962bd`/`#208661`）改为直接复用 `--mg-accent-business-*` / `--mg-accent-campaign-*` / `--mg-accent-studio-*`。

**一键核查残留**：

```bash
grep -rnE '#[0-9a-fA-F]{3,8}\b' --include=*.module.css src/media/studio/
# 期望输出：空
```

---

### P0-5 ⭐ 字阶迁移（**需回归测试，分批做**）

> ⚠️ **这是唯一会引起版面回流的改动。** 把 `0.62rem → 0.75rem` 是 **+21%**，
> 密集表格（AdminAccess / Tracks / Assets）可能换行或溢出。**必须分批。**

**批次 1（低风险，先做）** — Studio 五页，卡片式布局，容错高：
`WorkboardPage` / `CampaignsPage` / `BusinessPage` / `DeskPage` / `MediaAgentPage`

**批次 2（中风险）** — Overview / Reviews / Archives / Invites / UsageBilling

**批次 3（高风险，最后做）** — 密集表格页：`TracksPage` / `AssetsPage` / `AdminAccessPage` / `AdminTenantsPage` / `RunsPage`

**统一替换映射**：

| 原字号区间 | 替换 token | 折合 |
|---|---|---|
| `.53–.62rem` | `var(--mg-text-2xs)` | 12px |
| `.63–.70rem` | `var(--mg-text-xs)` | 13px |
| `.71–.78rem` | `var(--mg-text-sm)` | 14px |
| `.80–.88rem` | `var(--mg-text-md)` | 15px |
| `.90–1.05rem` | `var(--mg-text-lg)` | 17px |
| `1.2–1.5rem` | `var(--mg-text-xl)` | 22px |
| `1.55–1.8rem` | `var(--mg-text-2xl)` | 28px |
| `clamp(2rem, …)` | `var(--mg-text-3xl)` | 32–44px |

**辅助脚本**（先 dry-run，逐文件人工确认）：

```bash
# 用法：bash scripts/migrate-type-scale.sh src/media/studio/DeskPage.module.css
f="$1"
sed -i -E \
  -e 's/font-size: *\.?(5[3-9]|6[0-2])rem/font-size: var(--mg-text-2xs)/g' \
  -e 's/font-size: *0?\.(6[3-9]|70)rem/font-size: var(--mg-text-xs)/g' \
  -e 's/font-size: *0?\.7[1-8]rem/font-size: var(--mg-text-sm)/g' \
  -e 's/font-size: *0?\.(8[0-8])rem/font-size: var(--mg-text-md)/g' \
  -e 's/font-size: *0?\.(9[0-9])rem/font-size: var(--mg-text-lg)/g' \
  "$f"
```

**每批验收**：`npm run qa:media-role-screens`（Playwright 截图）+ 人工比对。

---

## 5. P1 改造项（下个迭代）—— 真正"凸显内容"

前面 P0 解决的是"不难看"。**P1 才是"凸显内容"。**

### P1-1 指标卡加趋势微图（sparkline）

现状：`MetricCard` 只有一个数字。竞品在 hero mockup 里放了 `.metric-row small` 的涨跌。

```tsx
// src/media/ui/Sparkline.tsx（新增）
import { useId } from 'react'

export function Sparkline({ points }: { points: number[] }) {
  const gradientId = useId()
  if (points.length < 2) return null
  const max = Math.max(...points)
  const min = Math.min(...points)
  const span = max - min || 1
  const line = points
    .map((p, i) => `${((i / (points.length - 1)) * 100).toFixed(2)},${(34 - ((p - min) / span) * 26).toFixed(2)}`)
    .join(' ')
  return (
    <svg viewBox="0 0 100 38" preserveAspectRatio="none" aria-hidden focusable="false"
         style={{ display: 'block', width: '100%', height: 38 }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--accent-base)" stopOpacity=".26" />
          <stop offset="1" stopColor="var(--accent-base)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,38 ${line} 100,38`} fill={`url(#${gradientId})`} />
      <polyline points={line} fill="none" stroke="var(--accent-base)" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
```

> ⚠️ `preserveAspectRatio="none"` 会横向非等比拉伸内容，**`<circle>` 端点会被压成椭圆**
> （卡片宽 ~250px 对 viewBox 100 单位，x 方向放大约 2.5 倍）。
> 因此端点强调交给面积渐变的收口，描边靠 `vector-effect="non-scaling-stroke"` 保持 2px 恒定。
> 这一点在原型里已验证。

数据来源：`getDashboard` 增加 `counts7d: { contentProjects: number[] , … }`。
**若后端暂不支持，先不要渲染假数据**——留空比编造好。

### P1-2 项目卡加"证据缩略图 + 平台标"

现状 `ProjectCard` 只有：阶段徽章 / 标题 / 进度条 / 产物数 / 时间。
内容型产品的卡片没有画面 = 没有说服力。

补充：
- 左侧 72×96 竖版缩略图（取首个 `asset` 的封面；无则渲染阶段图标占位，**不要用灰块**）
- 右上角平台图标组（复用已有 `PlatformBrandIcon`，补品牌底色，参考竞品 `.platform-icon.xhs`）
- 进度条替换为 `.mg-pipeline` 五段轨道，当前阶段高亮

### P1-3 Hero 减重，内容增重

当前 Workboard Hero：`padding: 34px` + `font-size: 3.8rem` 的信号数字，占掉首屏近一半，
而下面的项目卡正文只有 10.9px。**信息价值与视觉权重倒挂。**

```diff
  .hero { padding: 34px; }
+ .hero { padding: 30px 32px; }

  .heroCopy h1 { font-size: clamp(2rem, 3.2vw, 3.35rem); }
+ .heroCopy h1 { font-size: var(--mg-text-3xl); }   /* 32–44px，收敛 ~20% */

  .heroSignal > strong { font-size: 3.8rem; }
+ .heroSignal > strong { font-size: 2.75rem; }
```

省下的视觉预算给项目卡：`padding 17px → 20px`、标题 `.83rem → var(--mg-text-lg)`。

### P1-4 顶栏加暗色开关

```tsx
// MediaStudioApp.tsx —— 放在 .studio-topbar-actions 内
const [theme, setTheme] = useState<'light' | 'dark' | null>(
  () => (localStorage.getItem('mg-theme') as 'light' | 'dark' | null),
)
useEffect(() => {
  if (theme) document.documentElement.dataset.theme = theme
  else delete document.documentElement.dataset.theme
}, [theme])

<button className="icon-button" type="button" aria-label="切换主题"
        onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}>
  {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
</button>
```

`localStorage` 读写务必包 `try/catch`（隐私模式会抛异常）。

### P1-5 胶囊 tab 替换方形 `.mode-switch`

```diff
- .mode-switch { border-radius: 6px; }
- .mode-switch button { border-radius: 4px; }
+ .mode-switch { border-radius: var(--mg-r-full); padding: 3px; }
+ .mode-switch button { border-radius: var(--mg-r-full); }
+ .mode-switch button.active { color: var(--mg-bg); background: var(--mg-ink); }
```

---

## 6. P2（可选，视资源）

| 项 | 说明 |
|---|---|
| 骨架屏 | 现状 loading 是一个转圈图标；改为内容形状的 skeleton，感知性能提升明显 |
| 列表进入动画 | `@starting-style` + `transition` 做 60ms stagger（渐进增强，老浏览器自动降级） |
| 空态插画 | 9 个 `.emptyState` 现在只有一个 lucide 图标；换成品牌化 SVG |
| 数字滚动 | 指标卡数字用 `CSS @property` 做 count-up |
| 焦点可见性统一 | 现有 `outline: 3px solid oklch(...)` 散落多处，收敛为 `--mg-focus-ring` |

---

## 7. 执行清单与验收

### 7.1 分批计划

| 批次 | 内容 | 回流风险 | 验收命令 |
|---|---|:---:|---|
| **B1** | P0-1 token 层 + P0-2 删除重复 `:root` + 动效兜底 | 无 | `npm run qa:media-design-system-contract` |
| **B2** | P0-3 primitives + P0-4 accent 替换（Studio 5 页） | 低 | `npm run qa:media-design-system-contract && npm run lint` |
| **B3** | P0-5 字阶迁移 批次 1（Studio 5 页） | 中 | `npm run qa:media-role-screens` |
| **B4** | P1-3 Hero 减重 + P1-4 暗色开关 + P1-5 胶囊 tab | 低 | `npm run build:media` |
| **B5** | P0-5 字阶迁移 批次 2、3（含密集表格） | **高** | `npm run build:all` + 人工逐页比对 |
| **B6** | P1-1 sparkline + P1-2 项目卡证据图 | 低 | 需后端 `counts7d` 就绪 |

### 7.2 每批必跑

```bash
cd openclaw-bot-center
npm run lint
npm run qa:media-design-system-contract   # ← 契约红线
npm run qa:media-ordinary-presentation
npm run build:media                        # 完整门禁（含 14 项 QA）
```

### 7.3 量化验收标准

| 指标 | 现状 | 目标 |
|---|---:|---:|
| 字号种类 | 89 | **≤ 12**（8 个 token + 4 个 clamp 特例） |
| `*.module.css` 中硬编码 hex | 132 | **0** |
| 圆角种类 | 36 | **≤ 8** |
| 阴影种类 | 49 | **≤ 6** |
| 无过渡的 `:hover` | 174 | **0** |
| `prefers-color-scheme` 支持 | 无 | **完整** |
| 最小正文字号 | 8.5px | **≥ 12px** |
| `:root` 定义处 | 2（冲突） | **1** |

核查脚本（建议加进 `scripts/qa/`）：

```bash
#!/usr/bin/env bash
# scripts/qa/checkDesignTokenHygiene.sh
set -euo pipefail
cd "$(dirname "$0")/../../src/media"
fail=0
n=$(grep -rhoE 'font-size: *[^;]+' --include=*.css . | sed 's/font-size: *//' | grep -v 'var(--mg-text' | sort -u | wc -l)
[ "$n" -le 12 ] || { echo "❌ 字号种类 $n > 12"; fail=1; }
n=$(grep -rhoE '#[0-9a-fA-F]{3,8}\b' --include=*.module.css . | sort -u | wc -l)
[ "$n" -eq 0 ] || { echo "❌ module.css 残留 $n 个硬编码 hex"; fail=1; }
n=$(grep -rhoE 'border-radius: *[^;]+' --include=*.css . | sed 's/border-radius: *//' | grep -vE 'var\(--mg-r|50%|inherit' | sort -u | wc -l)
[ "$n" -le 8 ] || { echo "❌ 圆角种类 $n > 8"; fail=1; }
exit $fail
```

---

## 8. 风险与注意事项

| 风险 | 说明 | 缓解 |
|---|---|---|
| **QA 契约断裂** | `checkMediaDesignSystemContract.ts` 对 `media.css` 做**字面量正则**断言（见 §3.0） | 只增量加层，不重写 media.css；每批跑契约 |
| **字阶回流** | +21% 字号会撑破密集表格 | 分 3 批；表格页放最后；每批跑 `qa:media-role-screens` |
| **Google Fonts 可用性** | 内网 / 无外网环境加载失败 | fallback 链已含 `PingFang SC` / `Microsoft YaHei`；如需完全离线，把 woff2 放进 `public/fonts/` 并改 `@font-face` |
| **暗色下品牌色对比度** | 深底上 `#126344` 不可读 | Layer 0 暗色块已把 primary 提亮为 `#4ec48d`；上线前用 axe / Lighthouse 复核 AA |
| **`color-mix` 兼容性** | 代码里已大量使用 | 目标浏览器已支持（Chrome 111+/Safari 16.2+）；与现状一致，不新增风险 |
| **`:has()` 依赖** | `media.css` 的 prelude 契约依赖 `:has()` | 现状已依赖，不新增 |

---

## 9. 原型

[`prototype/workboard-redesign.html`](./prototype/workboard-redesign.html) —— 单文件、零依赖、可直接双击打开。

包含：
- 完整 Layer 0 token（可直接复制成 `mediaDesignTokens.css`）
- **左右对照**：现状 10.9px 正文 vs 改造后 14px 正文
- 改造后的「今日工作台」全页：Hero / 指标卡（含 sparkline）/ 业务闭环卡 / 项目卡（含流水线轨道）/ 行动收件箱
- 亮色 ⇄ 暗色实时切换
- 悬停位移动效
- 4 个模块 accent 实时切换（studio / campaign / business / desk），演示"一套组件 + 一组 token"如何取代 4 份复制的 CSS

---

## 10. 附：与既有文档的关系

本文档是 [`openclaw-media-studio-redesign.md`](./openclaw-media-studio-redesign.md)（2026-08-25，IA 与壳层重构）的**视觉层续篇**。
前者解决"信息架构对不对"，本文解决"看起来值不值这个价"。两者不冲突：
本方案**不改动任何路由、导航分组或数据契约**。
