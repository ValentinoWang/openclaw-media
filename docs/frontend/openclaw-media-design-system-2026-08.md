# MediaClaw 设计系统与业务闭环体验梳理（2026-08-26）

范围：`openclaw-bot-center` Media Web（普通用户 Studio 壳层、四条业务闭环、账号/资源页面、登录注册链路）。
参照：竞品 [MediaClaw-Web](https://github.com/ValentinoWang/MediaClaw-Web) 公开站重建的视觉语言（暖纸底 + 薄荷绿主色、
柔和多彩卡片族、大号紧排显示字、层次化软阴影、悬停位移微交互）。

## 1. 逐业务闭环的体验审计

| 闭环 | 触点 | 审计结论 |
| --- | --- | --- |
| 获客 / 登录 | `media.login.html` → `register` → `verify` → 工作台 | **品牌断裂**：登录链路使用橙色 `#b85d12` + 冷灰身份，与产品的深绿工作台毫无连续性；卡片 8px 直角、无动效，首触点缺乏产品感。 |
| 今日工作台 | `/today`（Workboard） | 结构完整（Hero + 指标 + 四闭环卡 + 项目/行动区），但字体无显示级层次、四张业务闭环卡的色彩表达全部依赖内联十六进制；hero 缺少品牌图形语言。 |
| Studio 活稿 | `/studio` → `/studio/:runId` | 详情编辑器信息密度合理，但主按钮为平面深绿、面板阴影层次不足，标题缺显示字族。 |
| Campaigns 商单履约 | `/campaigns` | Brief→初稿→审核→返修→交付 stage rail 概念好；紫色系全部硬编码（#5b4bb5 等 9 处），无 hover 反馈。 |
| Business 商务 | `/business` | 报价/档期/权益结构清晰；琥珀色系硬编码（#ad6426 等 10 处）；机会卡无交互层次。 |
| Desk 情报 | `/desk` | 发现→拆解→决策→复盘管线表达好；蓝色系硬编码（#376da9 等 8 处）；模块卡静态。 |
| 资源与执行 | `/assets` `/reviews` `/media-agent` `/archives` | 依赖共享 ordinary 原语（summary-band / section-panel / data-table / status-badge），整体偏"运营后台"，缺质感与动效。 |
| 账户 | `/usage-billing` `/invites` | 同上，由共享原语承载。 |
| 平台治理 | `/admin/*` | 同壳层与共享原语。 |

### 系统性根因

1. **双 token 层互相覆盖**：`media.css` 定义 oklch 版 `--mg-*`，`mediaStudioTheme.css` 又用十六进制重定义同名
   token 并因加载顺序获胜——同一变量存在两个"事实"，没有单一品牌事实源。
2. **无 accent 家族**：Campaigns/Business/Desk 各自复制紫/琥珀/蓝十六进制近 30 处，改一次品牌色要改四个文件。
3. **缺失比例系统**：无显示字族、无圆角/阴影/动效 scale，各文件各写各的 `border-radius`、`box-shadow`。
4. **登录链路品牌独立**：`media.auth.css` 自带一套与产品无关的色板。

## 2. 本轮"根本性"处置

### 2.1 单一品牌 token 层（`mediaStudioTheme.css`）

该文件成为品牌唯一表达点，`media.css` 保留结构与合同（控件高度、rail、抽屉宽度、表格基线），不再承担品牌角色。

新增/统一的 token：

```text
颜色     --mg-bg/surface/ink/muted/border(+strong)、--mg-primary(+dark/deep/soft)
accent   --mg-accent-{mint,violet,amber,blue}(+deep/soft) —— 四条业务闭环的色彩家族
形状     --mg-radius-{sm,md,lg,xl} = 9/12/16/22
高度层   --mg-shadow-{xs,sm,md,lg,primary}
动效     --mg-ease = cubic-bezier(.33,1,.48,1)、--mg-speed = .18s，含 prefers-reduced-motion 全局降级
字体     --mg-font-body = Noto Sans SC 栈、--mg-font-display = DM Sans + Noto Sans SC
```

字体经 `index.media.html` 与五个 auth 页的 Google Fonts `<link>` 装载，保留系统栈回退。

### 2.2 壳层升级

- 侧栏：三层径向/线性渐变的深松绿底、玻璃质 hover、active 项渐变底 + 左侧亮条 + 内阴影；工作区卡呼吸灯动画。
- 顶栏：模糊背景、搜索框 focus 光环、主按钮渐变 + 悬停上浮 + 品牌投影。
- 画布：双径向环境光底；`page-heading h1` 升级为显示字族；`section-panel/summary-band` 用统一阴影与圆角 token；
  表格行 hover、任务抽屉圆角与深投影。

### 2.3 业务闭环页面

- **Workboard**：hero 增加品牌有机形背景与 `em` 高亮题词；四张闭环卡接入 accent 家族，悬停上浮 + 箭头位移 +
  角落色块缩放；指标卡按业务语义分配 mint/violet/amber/blue 四色调（`data-tone`）。
- **Campaigns / Business / Desk**：约 30 处硬编码色全部迁移到 accent token；主/次按钮统一渐变 + 上浮；指标卡、
  机会卡、模块卡、链接行补齐 hover 反馈；hero 补有机形背景与显示字族。
- **Studio 活稿详情**：标题显示字族、主按钮渐变、面板/摘要带圆角阴影 token、激活 tab 强化——全部在既有布局
  合同（contentGrid 网格、移动端堆叠、无高空面板）内进行。

### 2.4 登录链路回归品牌

`media.auth.css` 的橙色身份整体退役：token 换为品牌绿家族，页面底加环境光，卡片 18px 圆角 + 品牌投影，
品牌 mark 与工作台侧栏同一渐变芯片，身份选择卡与主按钮获得与工作台一致的 hover 上浮/选中光环，焦点环统一为
品牌绿。全部选择器与文案保持不变（`qa:media-login-contract` / `qa:media-registration` 均通过）。

### 2.5 数据合同修复（顺带发现的真实缺口）

`qa:media-recent-task-presentation` 揭示前端结算投影（`settlementStage` / `accountBinding` / `attempt` /
`readbacks` / `missingReadbacks` / `receipt`）在 `mediaWebTaskSchema` 与服务端 `_project` 中双双缺失（合并主干
时丢失）。本轮补齐：schema 增加结算字段（缺失事实保持为空、不伪造），服务端投影输出 `settlementStage`
（无结算记录时回落到生命周期 status）与空绑定/读回字段。

## 3. 合同与 QA 兼容性

以下锁定合同全部保持并复验：

- `--mg-control-height-sm/md`、`--mg-panel-heading-height` 字面量与消费点（media.css，未触碰）；
- persistent-rail / prelude 视口列布局、等高契约、移动端释放；
- 任务抽屉 `min(500px, 100%)`、动态字段自适应行、表格顶部基线（新增样式无 th/td `vertical-align`）；
- run detail `contentGrid` 桌面双列 + 移动堆叠 + 无固定高空面板；
- Publishing 60/40 工作区比例；
- 平台品牌图标 registry 与 release 标签校验。

验证入口：`npm run build:media`（其内部包含登录/注册合同、能力启动、设计系统合同、ordinary 呈现、缩略图、
关系呈现、任务呈现、回执过期、删除恢复、确认安全、删除意图生命周期、tsc、vite build、release 标签）。

## 4. 2026-08-27 两分支合流裁决

同期存在两条前端美化分支，按以下裁决合并为一条（本分支）：

| 维度 | `claude/openclaw-media-frontend-design-147q30` | `claude/frontend-ui-interaction-polish-0lywkr` | 采用 |
| --- | --- | --- | --- |
| Token 架构 | mediaDesignTokens.css 唯一真源 + mediaPrimitives.css 原语层，覆盖全部 26 个样式表；8 级字阶（最小 12px）、暗色双通道、逐元素实测 AA 对比度 | mediaStudioTheme.css 品牌层，覆盖壳层 + 四闭环页 | **147q30**（更系统） |
| 任务契约 | 走生成器正路：media_web_task.schema.json + 生成器模板 + 重新生成 TS（该 TS 文件头明确 "Do not edit by hand"） | 直接手改生成文件（会被 `npm run build` 的生成器校验打回） | **147q30** |
| 后端 / 验收修复 | 无 | Stage-2 路由、SessionPrincipal、会话投影、口令路由退役、可移植性、conftest 等全量 | **0lywkr** |
| 登录链路品牌化 | 无 | media.auth.css（根 + src）+ 5 个 auth 页字体与主题色 | **0lywkr** |
| 字体加载 | CSS 内 render-blocking `@import`（离线/弱网下阻塞首屏） | HTML 非阻塞 `<link media="print" onload>` | **0lywkr**（并取权重并集） |
| Studio 表现力 | token 化但较克制 | 有机形 blob、`em` 高亮题词、指标卡分色、闭环卡 hover 位移 | **0lywkr** 细节以 token 安全方式回移 |
| 上传投影 | 前端契约锁定 schemaVersion "3" + `sha256:` 前缀（checkMaterialParsing 冻结） | 服务端 `_project_upload` 旧形状 | 契约为准，**服务端对齐**（本次合并内完成） |

合并后：`generateCapabilityMatchContract.py --check`、tsc、`build:media` 全链（含两个 Chromium 门禁与
release 标签）、oxlint、受保护 Python 套件（12 套）与触及套件共 262 项全部通过；浅色与暗色两主题截图复验。
