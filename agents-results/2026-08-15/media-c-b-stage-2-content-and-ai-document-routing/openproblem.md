# 第二阶段开放范围与待决合同

## 已裁决：个人开放范围

用户已确认：两组机器路由（普通路由清单 `studioOrdinaryRoutes` 与轨道路由清单 `studioTrackRoutes`）全量向个人人格开放。普通机器路由当前为 14 条：`/today`、`/studio`、`/campaigns`、`/business`、`/desk`、`/overview`、`/assets`、`/decisions`、`/publishing`、`/reviews`、`/media-agent`、`/archives`、`/usage-billing`、`/invites`；另有 `/tracks`、个人/组织/管理员路由和运行详情深链（`/runs/:runId`、`/studio/:runId`）。清单以源码 `mediaStudioRoutePolicy.ts` 为准，避免维护过时的页面副本。

开放页面不等于开放组织能力。所有个人查询、创建、编辑、发布、复盘、归档、计费和邀请动作必须由服务端按当前个人会话、租户和所有者作用域过滤；个人正文只能写入个人网页内部成果（`personal_web/internal`）。组织绑定（Binding）、飞书文档写入、组织资料和组织成员能力继续只属于组织人格，个人人格调用时必须稳定拒绝，不得回退到部署级凭据或静默切换人格。

默认入口由当前机器策略决定（个人工作台为 `/today`）；已开放深链进入对应个人页面。会话失效或动作越权必须显示稳定的未认证/无权状态，不能用其他业务页面伪装成功。

## 已落地但需分开命名的接口

登录前会话检查已落地：接口地址（`GET /openclaw/auth/entry-state?mode=`）和响应版本（`media_auth_entry_state_v1`）覆盖匹配（`matched`）、无匹配（`none`）、已失效（`expired`）、不一致（`mismatched`）四态，并已有脱敏和测试。该接口只表达“登录入口状态”。

角色、工作区模式、正文权威和可见界面由会话信封内的路由清单字段（`routeGrants`）配合路由策略承载。两者不得混为一个接口，也不得共用一个名字。

## 已裁决：路由清单字段的载体（K 第 5 版）

用户已裁决：`routeGrants` **保留在会话信封内**，定位为路由清单漂移检测，而不是授权投影。第 4 版“会话信封不得增加页面授权字段”的相反规定由本条取代。

裁决依据是三条源码事实。第一，已落地的入口状态接口是登录前探针，只返回四态、脱敏入口和回退方式，装不下角色和路由授权；硬装等于向未认证调用者泄露授权事实。第二，`routeGrants` 不是授权通道：客户端在 `mediaWebApi.ts` 中按角色和工作区模式独立推导期望清单，再与服务端下发值逐项按序比对，不一致即让会话解析失败关闭；它携带的信息量为零，真实作用是服务端与客户端路由清单漂移的失败关闭检测。第三，前端从不提交该字段。迁走它要付出同样的合同变更代价，却换不来安全收益。

保留不等于免账，以下两项是本裁决直接产生的待办：

1. **必须升版**：会话版本仍是 `media_web_business_pages_v2`，却已新增必填字段。必须升到 `media_web_business_pages_v3`，并由 B 节点按新版本重签接口冻结身份。在同一版本名下改变必填结构，是对已冻结合同身份的破坏；升版完成前，该字段不得被静态门禁当作已接受合同。
2. **清单收敛**：路由清单目前有三份人工维护副本（`mediaStudioRoutePolicy.ts` 的 `studioOrdinaryRoutes` 加 `studioTrackRoutes`、`mediaWebApi.ts` 的 `exactRouteGrants` 16 条、服务端生成器）。三份必须同步发布，否则每个会话都会解析失败。应收敛为一份生成源。

另有一笔既有欠账：登录入口状态接口尚未写入开放接口描述（OpenAPI），记在 B 与 T1 名下。

## 非法路由语义

导航层可以按当前工作区策略将合法会话误入不属于当前壳层的入口收敛到默认入口，避免空白壳层；数据和动作层仍必须稳定拒绝跨租户、跨所有者、缺失授权或组织能力调用（403 或等价无权状态），不得以重定向掩盖拒绝。该两层语义由 `checkMediaStudioRouteMatrix.ts` 及服务端动作授权共同验证。

## 验收边界

- 源码实现、聚焦测试、视觉图像（PNG）和人工智能读图只能证明来源级/本地运行时（`source/local-runtime`）证据，不能提升正式节点状态。
- 必须保留真实组织扫码与部署读回、飞书编辑后再回读、登录回退态折线确认、28 天会话持久化部署读回四项人工验收。
- 页面布局断言（`assertAuthLayout`）当前只保护初始 P1，登录回退态仍可能超过一屏；这属于自动化缺口，不得被误报为完整通过。
- 四项人工验收已建立项目级工作区，任务编号分别为 `ST2-HUM-ORG-SCAN`、`ST2-HUM-LARK-READBACK`、`ST2-HUM-LOGIN-FOLD`、`ST2-HUM-SESSION-28D`，清单与绑定位于 `acceptance/human/<task-id>/`。四份清单当前均为草稿，须由清单负责人明确批准后才能进入阻塞判定；签署结果写入该任务的 `runs/<run-id>/result.md`，不得改写清单来记录执行结果。

## 待办：生成视图需在编写机上重跑

本轮改动只落在权威源 `build_ssot.py` 与 `stage2_model.py`，生成产物尚未刷新，因此 `generated-views/`、`.ssot/view-sources/`、`.ssot/manifest.json`、`implementation-progress.md`、`ssot-development-paths.md` 与 `source-notes.md` 当前**落后于权威源**。

原因是这个 bundle 只能在编写机上重生成：`build_ssot.py` 的输入校验依赖四个本机文件（iCloud 事实审计文档与三个 codex 附件），且生成内容里嵌有由 `__file__` 推导出的绝对路径（`20-execution-governance.md` 中 86 处、`source-notes.md` 中 12 处）。在其他机器上重跑会把这些路径改写成该机器的路径，属于污染而非刷新。

刷新方式（在编写机的 bundle 目录下执行一次即可）：

```
python3 build_ssot.py
```

顺带记录一条可选改进：Harness 的前端规范把“不可移植路径”列为静态门禁的拒绝项，本 bundle 的绝对路径与之不符。是否把路径改为项目根相对路径，属于独立的改造决定，本轮不做。
