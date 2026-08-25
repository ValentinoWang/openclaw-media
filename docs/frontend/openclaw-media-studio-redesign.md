# OpenClaw Media Studio 前端重构说明

日期：2026-08-25  
范围：`openclaw-bot-center` 普通用户工作台  
目标：在不破坏现有租户、任务、权限和证据合同的前提下，把产品从“运营后台”升级为“从 Brief 到交付的 AI 内容生产工作台”。

## 1. 产品表达

新的一级对象是内容项目，而不是任务、运行或产物列表：

```text
Creative Project
├─ Brief
├─ Script
├─ Storyboard
├─ Shooting Plan
├─ Edit Handoff
├─ Publish Pack
├─ Revisions / Approvals
└─ Review
```

核心定位：

> MediaClaw 从活动、商单、灵感和素材出发，生成并持续维护可编辑脚本、分镜、拍摄、剪辑与发布交付物。

商业履约决定客单价，活稿编辑决定留存，数据复盘决定长期壁垒。

## 2. 新信息架构

普通用户默认入口从 `/overview` 调整为 `/today`。

```text
核心工作区
├─ 今日工作台        /today
├─ Studio           /studio
├─ Campaigns        /campaigns
├─ Business         /business
└─ Desk             /desk

资源与执行
├─ 素材库             /assets
├─ 复盘洞察           /reviews
├─ Agent 任务         /media-agent
└─ 云端归档           /archives

账户
├─ 用量与余额         /usage-billing
└─ 团队邀请           /invites
```

旧页面继续保留为高级视图，避免一次性破坏已有 API 和 QA：

- `/overview`
- `/tracks`
- `/decisions`
- `/publishing`
- `/runs/:runId`

`/runs` 重定向到 `/studio`，运行详情同时兼容 `/runs/:runId` 与 `/studio/:runId`。

## 3. 本轮实现

### 3.1 新生产型壳层

文件：

- `src/media/MediaStudioApp.tsx`
- `src/media/mediaStudioTheme.css`
- `src/media/main.tsx`
- `index.media.html`

实现：

- 深墨绿色生产型侧栏、暖白主画布和更高的信息层级；
- 新的核心工作区导航；
- 保留个人、组织和管理员模式；
- 保留任务抽屉、登录态、退出和原路由；
- 顶栏工作区搜索、任务中心和新建内容项目入口；
- 桌面、平板和移动端响应式适配。

### 3.2 今日工作台

文件：

- `src/media/studio/WorkboardPage.tsx`
- `src/media/studio/WorkboardPage.module.css`

读取真实 `getDashboard` 和 `listContentProjects` 数据，展示：

- 今日推进信号；
- 内容项目、创作运行、素材证据和已发布作品；
- Studio、Campaigns、Business、Desk 四条高价值业务闭环；
- 正在推进的内容项目；
- 待确认、待人工处理和执行中的任务；
- 新建内容、导入商单 Brief、打开 Agent 任务等下一步动作。

### 3.3 Campaigns

文件：

- `src/media/studio/CampaignsPage.tsx`
- `src/media/studio/CampaignsPage.module.css`

基于真实 `commercial_delivery_draft` 任务，表达：

```text
Brief → 初稿 → 审核 → 返修 → 交付
```

页面展示进行中、待人工处理、已完成商单，以及飞书或交付链接。空状态可以直接创建第一条商单。

### 3.4 Business

文件：

- `src/media/studio/BusinessPage.tsx`
- `src/media/studio/BusinessPage.module.css`

读取 `listBusinessOpportunities`，将以下事实分层：

```text
达人账号档案
→ 账号级报价快照
→ 项目级品牌机会、档期、返点、保价和授权
→ Campaign 履约
```

缺失报价、档期或授权时继续保留为空，不把默认值伪装成已确认事实。

### 3.5 Desk

文件：

- `src/media/studio/DeskPage.tsx`
- `src/media/studio/DeskPage.module.css`

将热榜监控、素材证据拆解、选题咨询和复盘回流表达为一条连续研究生产线：

```text
发现 → 拆解 → 决策 → 复盘 → Studio
```

各卡片继续使用现有能力 ID 和任务抽屉，不新增虚假的后端能力。

### 3.6 Studio 活稿编辑器

文件：

- `src/media/CreationRunDetailPage.tsx`
- `src/media/CreationRunDetailPage.module.css`

详情页读取：

- `getRun`
- `getRunSources`
- `getRunDecisions`
- `getRunOutputs`

并把持久化输出整理为四类可编辑区块：

- 创作脚本；
- 分镜脚本；
- 拍摄执行；
- 发布包。

首轮交互：

1. 直接编辑当前区块；
2. 人工锁定与解锁；
3. 恢复单个区块或整个服务端版本；
4. 修改前后 Diff；
5. 浏览器本地草稿版本；
6. Brief、人工决定和证据引用侧栏；
7. 只把当前区块和修改要求复制给 Agent；
8. 明确区分浏览器草稿和服务端权威版本。

## 4. 数据与事实边界

本轮没有伪造以下能力：

- 没有把浏览器 `localStorage` 草稿声称为服务端持久化；
- 没有绕过现有人工确认和任务抽屉；
- 没有新增虚构的报价、金额、品牌或发布日期；
- 没有让前端直接更改 Content OS 项目阶段；
- 没有让 AI 自动覆盖人工锁定内容。

## 5. 后续后端合同

为了完成真正的多人活稿闭环，后续建议新增：

```text
GET    /creative-projects/{id}
GET    /creative-projects/{id}/artifacts
GET    /creative-artifacts/{id}/revisions
POST   /creative-artifacts/{id}/patch-requests
POST   /creative-artifacts/{id}/revisions
POST   /creative-artifacts/{id}/blocks/{blockId}/lock
POST   /creative-artifacts/{id}/approvals
```

最关键的结构：

```text
CreativeProject
CreativeArtifact
CreativeArtifactBlock
CreativeRevision
CreativePatch
ApprovalRound
DeliveryReceipt
```

下游产物需要维护 `current / stale / blocked` 状态。例如 Brief 中品牌禁区变化时，脚本、分镜和发布包应被标记为待复核，而不是静默继续使用。

## 6. QA 兼容策略

- 原有 `MediaApp.tsx` 保留，避免静态 QA 直接失效；
- 新入口由 `src/media/main.tsx` 指向 `MediaStudioApp`；
- 新页面放在 `src/media/studio/`，不改变原有 `pages/ordinary` 固定清单；
- `CreationRunDetailPage` 继续保留 `data-page-prelude` 和 `data-run-detail-layout="compact"`；
- 移动端释放桌面固定高度并将详情网格堆叠为单列；
- 顶栏保留 `.topbar-command`、`.topbar-search` 等兼容选择器；
- 原任务抽屉、删除确认、租户边界和权限检查保持不变。

## 7. 本轮本地验证

已完成：

- 7 个新增或重写 TSX 文件语法检查；
- 未使用导入检查；
- 带接口桩的严格 TypeScript 编译；
- `CreationRunDetailPage` 原有桌面与移动布局正则合同；
- CSS 花括号平衡检查；
- 所有上传 GitHub 的 blob SHA 与本地 `git hash-object` 比对。

未在当前执行环境完成：

- 连接真实服务的完整 `npm run build:media`；
- Playwright 生产登录态截图；
- 多人服务端 Revision/Patch 持久化。

这些项目应由仓库 CI 或具有完整依赖、环境变量和真实服务的部署环境继续验证。
