# MediaClaw 静态演示站

演示站的构建目标、入口与假后端代码都在 `openclaw-bot-center/` 下：

```text
openclaw-bot-center/index.demo.html          # 演示站 HTML 入口
openclaw-bot-center/vite.demo.config.ts       # 演示站构建配置（dist-demo/、基址）
openclaw-bot-center/src/demo/
├── main.tsx                                  # 渲染 MediaStudioApp + 假后端 + 演示控制台
├── demoBackend.ts                             # 浏览器内假后端：拦截 fetch / EventSource
├── demoPersonas.ts                            # 三种演示身份与路由授权
├── demoRoutes.ts                              # 静态页面清单（生成路由 + 演示控制台索引共用）
├── DemoConsole.tsx                            # 右下角“演示导航”悬浮面板
├── generatedDemoDataset.json                  # 由业务合同生成的响应数据集（勿手改）
└── generatedDemoCatalog.json                  # 由能力注册表生成的能力目录（勿手改）
openclaw-bot-center/scripts/demo/
├── generate_demo_dataset.py                   # 数据集/目录生成器
└── demo_seed.py                                # 手写业务种子内容
```

## 这是什么

演示站渲染的是**真实的 `MediaStudioApp`**（`src/media/MediaStudioApp`）和**全部生产页面组件**——不是重新实现的简化版界面。它唯一替换掉的是数据来源：`src/demo/main.tsx` 在挂载应用之前先调用 `installDemoBackend()`，把 `window.fetch` 和 `EventSource` 替换成一套浏览器内的假后端（`src/demo/demoBackend.ts`），用生成好的静态数据集回放业务响应；页面组件本身完全不知道自己在演示环境里运行。

演示站因此具备三个特征：

- **没有登录**：不存在任何登录页或会话校验，`getMediaSession` 直接返回当前选中 persona 的会话对象（见下文“三种演示身份”）。
- **没有后端**：`index.demo.html` 打出来的产物是纯静态文件，不连接任何真实服务、数据库或 OpenClaw Control Plane；所有“写操作”（确认决策、编辑正文、兑换余额码等）只落在浏览器内存里，刷新页面即还原。
- **没有真实数据**：所有内容——项目、账号、素材、任务、复盘、计费——都是示例内容，见下文“数据来源与保证”。

用途是**业务流程走查与对外演示**：产品/业务同学不需要本地跑通登录、鉴权和后端依赖，就能点开任意页面、切换身份、走一遍完整的任务发起→确认→完成流程。

## 它不是什么

- **不是第二套前端实现**。演示站没有自己的页面组件、路由表或业务逻辑；`src/demo/main.tsx` 渲染的就是 `../media/MediaStudioApp`，样式也直接复用 `src/media/mediaDesignTokens.css`、`media.css`、`mediaPrimitives.css`、`mediaStudioTheme.css`。`src/demo/` 里只有假后端、演示身份和一个悬浮的演示控制台。
- **不是生产可用系统**。它不接受任何写回真实数据的操作，也没有鉴权、多租户隔离或权限校验——`demoPersonas.ts` 明确写着“完全在浏览器内构造，不连接任何身份服务，也不做鉴权”。
- **不能用它证明生产功能可用**。演示站展示的是页面组件能否正确渲染合同形状的数据，不代表对应的生产接口、Bot 能力或数据管线已经跑通；数据是示例内容，不是任何真实用户、项目或账号的投影。

## 数据来源与保证

演示数据不是手写的假 JSON，而是分两部分生成、并逐字段校验过的投影：

1. **业务页面数据集**（`src/demo/generatedDemoDataset.json`）：由 `scripts/demo/generate_demo_dataset.py` 读取 `contracts/media_web_business_pages.openapi.yaml`，对合同里每个 operation 的响应 schema 做实例化（`Sampler`），再与 `scripts/demo/demo_seed.py` 里手写的业务种子内容合并（`merge`）。合并后的每一份 payload 都会再跑一遍 `Validator`，逐字段核对类型、`enum`、`pattern`、`required`、`additionalProperties`——种子如果声明了合同之外的字段，或生成结果不满足合同约束，生成脚本直接报错退出。因此演示数据集里出现的字段、取值范围和分页/搜索行为（`demoBackend.ts` 里的 `applyListQuery`）都与生产合同保持逐字段一致。
2. **能力目录**（`src/demo/generatedDemoCatalog.json`）：由 `generate_demo_dataset.py` 的 `build_catalog()` 直接调用 `openclaw-tag-router` 里的真实 `CapabilityRegistry.compile_all()` 编译得到，序列化时限定 `visibilities={public, ops}`、`bots={Media bot, 任意 Bot}`。也就是说任务抽屉里出现的能力清单、层级路径、是否需要人工确认（`requiresConfirmation`）、确认文案等，都是生产能力注册表的真实编译结果，不是演示站自己臆造的清单。

两份文件的头部都带着可追溯信息：数据集记录了源合同的 `contractSha256` 与 `generatedAt`；目录记录 `schemaVersion` 与 `catalogVersion`。

## 三种演示身份

演示控制台右下角的“演示导航”面板可以在三种身份之间切换（`src/demo/demoPersonas.ts`），每种身份对应生产 `resolveStudioRoutePolicy` 的一种 shell，并各自拥有一份路由授权（`routeGrants`，与 `src/media/mediaWebApi.ts` 的 `exactRouteGrants` 保持逐项一致）。切到某个身份后，该身份未被授权的路由在页面索引里会标注“需切换身份”。

### 个人创作者（`personal`）— 默认路由 `/overview`

个人云端工作区，可见全部内容生产页面：

```text
/today            今日工作台 · 下一步与截止事项
/studio           Studio 创作台 · 脚本、分镜与交付
/campaigns        活动与商单 · 活动与商单履约
/business         商业化 · 报价、档期与商机
/desk             情报台 · 情报、拆解与增长
/overview         项目概览 · 项目状态与下一步
/assets           素材库 · 原始素材与证据
/tracks           账号与赛道 · 自有账号与监控
/decisions        选题与决策 · 证据、候选与人工状态
/publishing       发布交付 · 发布准备与渠道交付
/reviews          复盘洞察 · 发布数据与账号学习
/media-agent      Agent 任务 · 本机执行与人工确认
/archives         云端归档 · 成果与历史记录
/usage-billing    用量与余额
/invites          团队邀请
/workspace        个人云端成果
```

以及三个详情页示例：`/studio/run_autumn_camera_01`（创作运行详情）、`/workspace/preview/artifact_creation_camera`（云端成果预览）、`/workspace/edit/artifact_creation_camera`（正文编辑器）。

### 组织成员（`organization`）— 默认路由 `/organization-workspace`

飞书组织工作区，文档正文以飞书为准：

```text
/organization-workspace                                  组织工作区 · 文档正文以飞书为准
/organization-workspace/document/artifact_creation_camera 组织文档镜像 · 飞书正文投影与修订
/tracks                                                   账号与赛道
```

### 平台管理员（`admin`）— 默认路由 `/admin/overview`

平台治理控制台：

```text
/admin/overview     平台总览
/admin/access       用户与准入
/admin/tenants      租户资源
/admin/billing      计费运营
/admin/upstreams    上游服务
```

以上分组与命名与 `src/demo/demoRoutes.ts` 的 `demoRouteGroups` 一致；同一份清单也用来在构建时给每个路由落一个真实 HTML 文件（见下文“部署说明”）。

## 两个入口

演示站有两个可以直接发给别人的入口：

- `<base>/`：**封面页**（`src/demo/DemoCover.tsx`）。说明这是什么、边界在哪、有哪些页面、三种身份分别能看到什么，再由这里进应用。根路径不直接跳默认页是刻意的：单看一个内页，没人分得清这是不鉴权的复刻站还是真的产品。进去之后右下角有“演示导航”悬浮面板（可拖动），可以切身份、跳任意页面。
- `<base>pages.html`：**纯静态的页面索引**。它由构建脚本 `scripts/demo/renderDemoIndex.ts` 从同一份 `demoRouteGroups` 生成，不依赖 JavaScript，也不加载任何外部资源；适合作为“HTML 跳转版”的对外首页——打开就能看到全部页面清单，点哪个跳哪个。

两个入口用的是同一份路由清单，不存在“索引里有、站里没有”的漂移。封面页与演示导航都走 `src/demo/demoNavigation.ts` 的 pushState 导航，而不是整页跳转——单文件分发时只有一个文档，任何子路径的整页跳转都取不到文件。

## 认证页面（只读复刻）

登录、注册、邮箱验证、找回密码、重置密码这五个页面也复刻进了演示站，落在 `<base>login/`、`register/`、`verify/`、`recover/`、`reset/`：

- 页面结构、文案与样式来自生产源文件（`media.login.html` 等），**没有**引入生产的 `media.login.js`；
- 取而代之的是一段零网络请求的演示脚本（`scripts/demo/buildDemoAuthPages.ts` 注入）：拦截站内认证链接和其余四页的表单提交，改为显示「演示站不做真实登录」的内联提示；
- 页面顶部有固定的演示横幅，说明不会创建账号、不会发送验证码。

**登录表单是唯一的例外**——它是这一页的主路径，填了就该真的进得去，否则整页是死路：

| 在个人端登录表单里填 | 进入 |
|---|---|
| `p_admin` / `1qaz2wsx` | 平台管理员身份，落在 `/admin/overview` |
| 任意其它非空账号 + 非空口令 | 个人创作者身份，落在 `/overview` |

这**不是鉴权**：这一页没有后端、没有账号库，脚本只是把输入的字符串当成一个路由开关。写死这一组的原因是「管理员」在生产里是普通账号上的一个角色，没有独立的登录入口——演示站也就没有第二张表单可走，只能从个人端这张进。口令本身印在页面上，任何人打开都看得到。

一个踩过的坑：演示站外壳（SPA 退出登录后）把认证页放进 `sandbox="allow-scripts"` 的 iframe 里，那是**不透明源**——`allow-forms` 不给的话表单根本提交不了，上面这段拦截逻辑一次都不会跑。五个认证页的提交拦截曾因此在外壳里全程失效。

落盘成目录形式（`login/index.html` 而不是 `login.html`）是刻意的：生产 nginx 有一条 `location ~* /[^/]*login[^/]*\.html$ { return 404; }` 的兜底规则，文件名带 `login` 的 `.html` 请求会被拒；目录形式的请求 URI 不以 `.html` 结尾，不会命中。

## 常用命令

以下命令均定义在 `openclaw-bot-center/package.json`，需先 `cd openclaw-bot-center`。

```bash
# 本地开发（带热更新，默认绑定 0.0.0.0）
cd openclaw-bot-center && npm run dev:demo

# 重新生成演示数据集与能力目录（改了业务合同或种子内容之后跑）
cd openclaw-bot-center && npm run generate:demo-dataset

# 校验已提交的数据集/目录是否与合同、种子内容一致（CI / 提交前用）
cd openclaw-bot-center && npm run validate:demo-dataset

# 构建演示站（校验数据集 → 类型检查 → vite build → 静态产物 QA）
cd openclaw-bot-center && npm run build:demo

# 本地预览构建产物
cd openclaw-bot-center && npm run preview:demo

# 单独跑构建产物的走查 QA（build:demo 内部也会跑这一步）
cd openclaw-bot-center && npm run qa:media-demo-static

# 单独跑排版体检（同上，需要 dist-demo 已经构建过）
cd openclaw-bot-center && npm run qa:media-layout-sanity

# 打成单文件（发 Artifact 这类只托管一个文档的场合）
cd openclaw-bot-center && MEDIA_DEMO_BASE=/ npm run build:demo && npm run build:demo-artifact
```

`build:demo` 的完整流程是 `validate:demo-dataset && qa:media-demo-parity && qa:media-demo-parity-self-test && tsc -b tsconfig.demo.json && vite build --config vite.demo.config.ts && qa:media-demo-static && qa:media-layout-sanity`：先确认数据集没有过期（不是重新生成，而是校验当前已提交的文件是否等于按当前合同/种子重新生成的结果）和原型与生产没有漂移，再做类型检查、构建，最后跑构建产物的走查与排版体检。

`qa:media-layout-sanity` 会在 1440 / 1180 / 900 / 430 四个宽度真渲染每个演示页面，抓四类类型检查和单测看不见的破相：文字块互相重叠、不含空格的整串（ID、时间戳）被拦腰折断、非标题的值槽用展示级字号折行、视口高度契约生效时整页仍能纵向滚动。演示站在这里的价值不止是“给人看”——它是**唯一**能把全部生产页面在多个宽度下真渲染一遍的地方，生产前端要登录才进得去。

## 单文件分发

`npm run build:demo-artifact`（`scripts/demo/buildDemoArtifact.ts`）把构建产物压成一个 HTML 文件，落在 `dist-demo-artifact/demo-site.html`：CSS 和 JS 内联，本地 woff2 的 `@font-face` 整段剥掉改挂 Google Fonts（同样两个字族），最后自检没有残留的本地引用、没有 `@font-face`、总大小不超过 16MB。

前提是**基址必须是 `/`**（`MEDIA_DEMO_BASE=/`）：单文件只有根路径这一个文档，基址对不上会让封面页跳转到取不到的子路径。脚本会直接拒绝非 `/` 的产物，不会默默产出一个坏文件。

## 怎么打开

演示站是 SPA + 每路由静态 HTML 的组合，链接与资源都用**绝对路径**（默认 `/openclaw/media-demo/`），所以**不能直接双击 `index.html` 用 `file://` 打开**——必须经过一个 HTTP 服务：

```bash
# 最省事：构建产物本地预览（会打印 http://localhost:4173/openclaw/media-demo/）
cd openclaw-bot-center && npm run preview:demo
```

要放到别的路径（比如内网静态站的根目录），用基址重新构建即可：

```bash
cd openclaw-bot-center && MEDIA_DEMO_BASE=/ npm run build:demo
```

## 部署说明

- **产物是纯静态文件**：`vite.demo.config.ts` 的构建产物目录是 `dist-demo/`，不依赖任何服务端渲染或 API 网关。
- **每个路由都落了真实 HTML 文件**：`vite.demo.config.ts` 的 `closeBundle` 钩子会遍历 `src/demo/demoRoutes.ts` 里的 `demoStaticRoutes`，为每个路径创建对应目录并写入一份完整的 `index.html`（连同顶层的 `index.html`，由 `index.demo.html` 构建后改名而来），同时生成 `404.html`。因此**不需要 SPA 回退规则**，静态文件服务器（哪怕没有“找不到文件就回退到 index.html”的能力）也能直接打开任意深链接，比如 `/openclaw/media-demo/admin/billing/`。
- **基址与部署路径**：默认基址是 `/openclaw/media-demo/`（`vite.demo.config.ts` 里的 `base`），产物内的资源引用、路由链接都基于这个前缀。要换部署路径，用环境变量重新构建，不要在产物里手改路径：

  ```bash
  MEDIA_DEMO_BASE=/your/path/ npm run build:demo
  ```

- **与生产分开部署**：建议把演示站单独放在 `/openclaw/media-demo/`，与生产 Media 前端的 `/openclaw/media/`（`dist-media/` 的部署目标）区分开。演示站没有鉴权、没有登录页，页面上也没有任何提示会打断误访问的用户，所以**不得挂在任何可能被误认为生产环境的入口上**（例如生产域名根路径、生产同路径下的子路径、或对外可索引且未标注“演示”的地址）。`index.demo.html` 已经带了 `<meta name="robots" content="noindex, nofollow">` 和演示专属标题/图标，但这只是搜索引擎层面的提示，不能替代部署位置上的隔离。

## 一致性门禁

演示站最大的风险是**改了生产代码却忘了同步原型**，久而久之两边越差越远。`npm run qa:media-demo-parity` 就是拦这件事的：

- 它是 `build:media`（生产构建）的**第一步**，也在 `build:demo` 里跑；
- 检查生产路由注册表、会话路由授权、业务合同接口、合同摘要、能力目录、认证页入口是否都在演示站里有对应物；
- 失败时直接指出「该改哪个演示站文件、该跑什么命令」。

也就是说：**改业务代码而不更新原型，生产构建会红**。仓库根目录的 `CLAUDE.md` 用一张对照表写明了「改了什么就要同步什么」，AI 助手和人都以那张表为准。

唯一允许不一致的是演示数据本身：演示世界是虚构的，由 `scripts/demo/demo_seed.py` 维护。

## 维护约定

- **改了业务合同或页面之后**：先跑 `npm run generate:demo-dataset` 重新生成数据集与能力目录，再跑 `npm run build:demo` 确认演示站仍然能装配出合法数据；提交前建议再跑一次 `npm run validate:demo-dataset` 确认生成结果是确定性的（同一份合同 + 种子应当生成完全相同的文件）。
- **`generatedDemoDataset.json` 与 `generatedDemoCatalog.json` 不允许手改**：这两个文件是生成产物，唯一的修改路径是编辑 `contracts/media_web_business_pages.openapi.yaml`、`scripts/demo/demo_seed.py`（或上游的 `CapabilityRegistry`）之后重新生成。手改会在下一次 `validate:demo-dataset` 或 CI 校验时被判定为“stale”。
- **演示数据里不允许出现真实个人信息、真实域名、真实凭据**：`demo_seed.py` 文件头已经声明“这里描述的世界是虚构演示素材——没有真实创作者、租户、凭据或 URL”；新增种子内容时延续这个约束，示例链接统一使用 `https://demo.mediaclaw.example/...` 这类不可解析的占位域名，账号、租户、创作者一律使用虚构名称与 ID。
