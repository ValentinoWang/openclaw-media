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

## 常用命令

```bash
cd openclaw-bot-center
npm run qa:media-demo-parity     # 生产/原型一致性门禁（最快，先跑它）
npm run qa:media-workboard-flow  # /today 全流程图：数据绑定 + 排版（节点/标签不许互相压住）
npm run generate:demo-dataset    # 合同或能力注册表变更后重新生成演示数据
npm run build:demo               # 构建演示站并走查全部页面
npm run build:media              # 生产 Media 前端全套门禁
```

发布治理、目录边界和依赖方向仍以 [docs/architecture.md](docs/architecture.md) 为准；演示站的完整说明见 [docs/frontend/media-demo-site.md](docs/frontend/media-demo-site.md)。
