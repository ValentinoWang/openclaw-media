# 给 AI 助手的仓库约定

目录职责、依赖方向和产物根的唯一事实源是 [docs/architecture.md](docs/architecture.md)；本文件只补充「改代码时容易忘记的同步动作」。

## 改 Media 前端时必须同步 HTML 原型

`openclaw-bot-center/` 下有两套产物，共用同一批页面组件：

| 角色 | 位置 | 构建 |
|---|---|---|
| 生产 Media 前端 | `src/media/**` | `npm run build:media` → `dist-media/` |
| 不鉴权静态演示站（HTML 原型） | `src/demo/**`、`scripts/demo/**` | `npm run build:demo` → `dist-demo/` |

演示站复用真实的 `MediaStudioApp` 和全部生产页面组件，**只替换网络层**（浏览器内假后端）。因此除了「示例数据」之外，两者必须保持一致：改了业务代码就要同步原型，否则演示站会和真实产品对不上。

下面这些改动**必须**同时更新演示站：

| 你改了 | 就要同步 |
|---|---|
| 新增/删除/重命名路由（`MediaStudioApp.tsx`、`mediaStudioRoutePolicy.ts`） | `src/demo/demoRoutes.ts` 的 `demoRouteGroups`（参数化路由要补一个具体示例） |
| 改会话路由授权（`mediaWebApi.ts` 的 `exactRouteGrants`） | `src/demo/demoPersonas.ts` 里对应身份的 `session.routeGrants`（逐项、按顺序一致） |
| 改业务合同（`contracts/media_web_business_pages.openapi.yaml`） | 重新生成数据集：`npm run generate:demo-dataset`；新接口若是有状态的，在 `scripts/demo/demo_seed.py` 的 `BACKEND_OWNED_OPERATIONS` 登记并在 `src/demo/demoBackend.ts` 实现 |
| 改页面读取/写回的字段（尤其是 mutation 之后的「读回校验」） | `src/demo/demoBackend.ts` 的 `applyMutation`：演示站的写操作必须返回页面真正会解析的形状 |
| 改能力注册表（`openclaw-tag-router/`） | 重新生成能力目录：`npm run generate:demo-dataset` |
| 新增认证页入口（`vite.media.config.ts`） | `src/demo/demoRoutes.ts` 的 `demoAuthPages` 与 `scripts/demo/buildDemoAuthPages.ts` |
| 改认证页 HTML（`media.login.html` 等五个） | 重新生成内嵌版：`npm run generate:demo-auth-pages`（单文件分发时只有这份够得着） |

这条约束由质量门禁 `npm run qa:media-demo-parity` 强制执行，它是 `build:media` 的第一步：**改了生产代码却没同步原型，生产构建会直接失败**，并指出该改哪个文件。

不需要同步的只有一件事：**演示数据本身**。演示站的项目、账号、金额、租户都是虚构示例，由 `scripts/demo/demo_seed.py` 维护，与生产数据无关。

## 演示数据的硬性边界

`scripts/demo/generate_demo_dataset.py` 会拒绝生成含有邮箱、手机号、服务器绝对路径、凭据，或演示域名（`demo.mediaclaw.example`）之外链接的数据集。写种子内容时不要试图绕过它。

## 改双栏页面（主栏 + 检视栏）时不要拼特异性

`src/media/media.css` 里的 `[data-page-layout="persistent-rail"]` 契约让两栏共用一个视口高度的盒子、各自内部滚动——**只在两栏真的并排时成立**。页面往往在 1120px、900px 就把两栏堆成一列，那时必须整体松开，否则两个 auto 行会把被强制的高度对半切开，内容高的一侧被压扁、溢出压住下一块。

松开的开关是四个自定义属性，在页面根元素上写一次即可（属性沿继承链传递，不参与选择器特异性）：

```css
@media (max-width: 1120px) {
  .page {
    --mg-rail-shell-height: auto;   /* 壳改回随内容增长 */
    --mg-rail-grow: 0 0 auto;       /* 栏容器不再吃掉剩余高度 */
    --mg-rail-fill: auto;           /* 两栏各自按内容定高 */
    --mg-rail-align: auto;          /* 不再被拉齐 */
  }
}
```

**不要**把 `[data-page-layout=…]`、`:has(> [data-page-prelude])` 抄进页面样式去比特异性，也不要用 `!important`——`qa:media-design-system-contract` 会直接拒绝，报错里写着该设哪几个属性。

### 那份高度是**预算**，不是必须填满的下限

等高契约给的是「这一列最多能有多高」。检视栏往往只有半屏（选中一条记录、几行事实），被 `stretch` 拉满之后剩下的不是页面留白，而是**一块画了边框、铺了底色的空盒子**，看着像没加载出来。所以检视栏与主栏终端面默认按内容定高，等高那份高度降级成 `max-height`：内容短就收，内容长仍然吃满一列并在自己内部滚。

页面里再把面板拉满（`height: 100%`、`flex: 1 1 auto`、`align-items: stretch`、写死的 `min-height`）就会把这件事撤销——`qa:media-layout-sanity` 的「面板底部空转」会抓。要顶部对齐两块并排的卡片用 `align-items: start`，别用等高。

### 圆点属于它右边那一项

一串短事实用居中圆点连成一行时，圆点是**下一项的引导**。它一旦单独作为一个 flex 子项，折行后就留在上一行行尾（`小红书 ·` / `更新于 3 天前`），读起来变成左边那项的后缀，右边那项则失去了分隔。`/reviews` 检视栏更严重：`post_xxx · 报告` / `review_xxx`——「报告」是给右边那个编号的标签，折行后它成了左边编号的后缀，第二行是一串**没有标签的孤儿编号**。

两种上下文两种写法：

| 上下文 | 写法 |
|---|---|
| flex 行（`.mg-meta`、自定义的一行事实） | 把「圆点 + 事实」包进同一个 flex 子项（`display: inline-flex; column-gap: inherit`），一起折行 |
| 纯内联文本（模板字符串拼出来的一行） | 圆点后面用不换行空格 `·&nbsp;`，禁掉那个断点 |

「标签 + 值」同理：标签和它的值要在同一个子项里，别让折行把它们拆开。破折号构成的区间（`2026/8/28 — 2026/9/22`）不在此列——按排版惯例本来就在破折号之后折行。`qa:media-layout-sanity` 的「分隔符被甩在行尾」量的是**字形**：分隔符那一个字成了某一行最右边的一点墨才算，圆点跟着自己那项一起换行不会误判。

### 想给面板开内部滚动，只能靠 `--mg-panel-overflow`

页面样式和原语的类选择器特异性同为 (0,1,0)，而原语在打包后的样式表里更靠后，**同分靠源序决胜负**：页面写 `.somePanel { overflow-y: auto }` 打不过 `.mg-panel { overflow: … }`，于是「以为开了内部滚动、算出来仍是 hidden」，视口一矮内容就被永久裁掉、连滚都滚不出来。开关同样是自定义属性：

```css
.somePanel { --mg-panel-overflow: hidden auto; }   /* 横向仍裁在圆角里，纵向可滚 */
```

配合链路上每一层的 `min-height: 0`——规范规定只有 `overflow` 非 `visible` 的子项自动最小尺寸才是 0，其余默认是内容高度，这就是「内层写了 `overflow-y: auto` 却永远不出滚动条」的原因。`qa:media-primitive-enhancements` 会钉住这个开关本身存在。

### 徽标不许被容器拉变形

`.mg-badge` 是内容尺寸的小药丸。它一旦成为 grid item 就会被块化、`flex: 0 0 auto` 失效，父级 `align-items` / `justify-items` 的默认值 `normal` 等于 `stretch`——`/organization-workspace` 的「只读镜像」因此被 330px 的轨道撑成过 330×112 的大色块。原语用 `width/height: fit-content` 两个方向都钉死（`stretch` 只在尺寸是 `auto` 时生效），同样由 `qa:media-primitive-enhancements` 守着。

## 排版破相靠渲染门禁兜底

`npm run qa:media-layout-sanity`（`build:demo` 的最后一步）会在 1440 / 1180 / 900 / 430 四个宽度真渲染演示站的每个页面，抓几类肉眼一看就知道坏了、但类型检查和单测永远看不见的问题：文字块互相重叠、不含空格的整串（ID、时间戳）被拦腰折断、非标题的值槽用展示级字号折行、八个字以内的短标题被折行、视口高度契约算错、内容被永久裁掉、**多列挤压**、**低信息密度**、**面板底部空转**、**徽标被拉变形**、**分隔符被甩在行尾**。

它不只量首屏：会逐个点开页面里的标签页、再选中列表首条，分别体检——`/tracks` 的「赛道概览」「对标账号」和 `/publishing` 选中发布包之后的详情栏都只在那几屏才看得见。失败信息里的 `〔…〕` 就是当时所处的那一屏。

迭代时可以只跑几条路由，几分钟出结果：

```bash
MEDIA_LAYOUT_QA_ROUTES=/tracks,/publishing npm run qa:media-layout-sanity
```

还有一遍**长列表压力**：在最宽的一档把页面里最大的一组重复兄弟复制到 8 倍，再查一遍有没有内容被永久裁掉。演示数据每张表只有两三行，凡是「装不下就把行吞掉、而且滚不出来」的页面在正常数据量下全是绿的——`/invites` 就是这样：4 条成员看着好好的，克隆到 32 条之后表格内容被面板的 `overflow: hidden` 裁掉 1598px，真实租户里就是「第 5 个人开始看不见」。

标识符类字段统一用 `.mg-id`（单行 + 省略号，完整值放 `title`），不要在页面样式里给它们加 `overflow-wrap: anywhere`。

## 密度：列数交给容器，短事实排成一行

同一段内容既会出现在 350px 的检视栏里，也会出现在 700px 的主面板里。**写死列数**的那一刻，窄的一边挤压、宽的一边稀疏就成了必然，页面只能各自再补一套断点。共享原语（`src/media/mediaPrimitives.css`）已经把这件事做掉了：

| 原语 | 干什么 |
|---|---|
| `.mg-facts` / `.mg-fact` | 标签 + 值的网格，列数由容器决定（`auto-fit` + `minmax`）；要调下限就改容器上的 `--mg-facts-min` |
| `--mg-fact-label` | 一组事实并排时标签长短不一，值的起点就参差；在容器上设一个标签下限宽度即可对齐成一列（比下限长的标签仍自己撑开，不是写死列宽） |
| `.mg-meta` | 一串短事实排成一行、放不下再折行——**不要**让「自有账号 2」「对标账号 1」这类计数各占一行 |
| `.mg-metric-grid` | 指标卡网格，同样按容器自适应 |

`qa:media-primitive-enhancements` 会拒绝把这三个原语改成写死列数或不折行；渲染门禁则从结果上兜底：宽 ≥480px 的重复列表卡片里，不允许有 ≥3 行「铺满整行、单行高度、字形宽度不到行宽四成」的行。

这条门禁挂在 `build:demo` 而不是 `build:media`：它要把页面真渲染出来，而生产前端要登录才进得去，演示站是唯一能在多个宽度下走完全部页面的地方。**所以改了页面样式或版式，跑完 `build:media` 还不够，必须再跑一次 `build:demo`**。

## 常用命令

```bash
cd openclaw-bot-center
npm run qa:media-demo-parity     # 生产/原型一致性门禁（最快，先跑它）
npm run qa:media-workboard-flow  # /today 全流程图：数据绑定 + 排版（节点/标签不许互相压住）
npm run qa:media-layout-sanity   # 排版体检：四个宽度真渲染，抓重叠/截断/折行（需要先 build:demo）
npm run generate:demo-dataset    # 合同或能力注册表变更后重新生成演示数据
npm run build:demo               # 构建演示站并走查全部页面
npm run build:media              # 生产 Media 前端全套门禁
```

演示站要发成**单文件**（Artifact 之类只托管一个文档的场合）时：

```bash
MEDIA_DEMO_BASE=/ npm run build:demo   # 单文件只有根路径，基址必须是 /
npm run build:demo-artifact            # 内联 CSS/JS、剥离本地字体，产出 dist-demo-artifact/demo-site.html
```

发布治理、目录边界和依赖方向仍以 [docs/architecture.md](docs/architecture.md) 为准；演示站的完整说明见 [docs/frontend/media-demo-site.md](docs/frontend/media-demo-site.md)。
