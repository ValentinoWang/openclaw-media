# 第二阶段 C/B 界面开发任务书

> 本任务书是唯一的开发入口。两份交互原型是 UI 规格（做成什么样），验收执行文档是完成口径（怎么算做完），本文说清楚**改哪些文件、按什么顺序、哪些事禁止做**。
>
> 附件（同目录）：
> - `personal-document-editor.html` —— C 端规格，8 个状态，顶部控制条可逐态查看
> - `organization-document-mirror.html` —— B 端规格，8 个状态
> - `stage2-acceptance-execution.html` —— 验收矩阵与命令清单

---

## 0. 执行纪律（先读，违反任何一条即返工）

1. **分支**：从 `origin/main` 新建一个分支开发；原子提交，一个任务一个提交；只 `git commit -- <明确文件列表>`；禁止 rebase / stash / force-push。
2. **不碰 SSOT**：`agents-results/**` 全目录只读。写代码不改变任何节点状态——"源码已存在不等于节点已接受"。
3. **门禁必须全绿才算完**：每个交付物完成后运行 `npm run build:media`（含 15 个 QA 门禁 + tsc + vite）与后端 `python -m pytest tests/ --ignore=tests/test_sync_lark_base_projection.py`。后端已知基线失败为 26 条（清单见验收文档），失败集合必须与基线**逐字节一致**，多一条即回归。
4. **禁止发明端点**：前端只准调用 `contracts/media_web_business_pages.openapi.yaml` 里已存在的 operationId。注意：**AI 改稿的发起端点已经存在**——`createArtifactRevision`（`POST /artifacts/{publicArtifactId}/revisions`，绑定能力 `document_edit`「修改」，接受 `instruction` + `expectedRevision`，幂等，落一条 `state='generating'` 的新修订）。真正缺的是**执行器**（见交付物四 T5）与同步批次只读端点（T6）。在 T5 落地前不得给 AI 面板接线上线（发起了也永远等不来结果），更不得 mock。
5. **文案规矩**（原型已示范，逐字照搬为准）：
   - 用户可读文本零后端枚举字面量、零 wire 字段名（`draft`→草稿、`internal`→网页端……）；
   - 错误码只出现在「技术参考码：xxx」单独一行，全篇一次，人话说明在前（`test_media_feishu_login.py` 的呈现测试是这条的既有判例）；
   - 版本号统一 `v` 前缀；中文标题 letter-spacing 为 0。
6. **原型即验收基准**：每个交付物完成后，逐状态截图与对应原型比对（布局、状态机、文案）。差异要么修掉，要么在提交信息里逐条说明理由。

---

## 交付物一：后端欠账小包（独立可合，先做）

不依赖任何裁决，四个原子任务，每个一个提交。

### T1 `blockIds` 接进 422 响应
- **改**：`openclaw-tag-router/openclaw_app/adapters/http_api.py:727-729` 的 `except MediaBusinessError` 捕获——`_send_api_error` 已有 `details` 参数但没接。当异常带非空 `block_ids` 时传 `details={"blockIds": list(exc.block_ids)}`。
- **同步**：`contracts/media_web_business_pages.openapi.yaml` 的 `saveDocumentDraft` / `createDocumentExport` 错误响应结构补 `details.blockIds`（可选字段）。
- **测**：在 `tests/test_media_business_documents.py` 或 `test_http_api.py` 加一条 HTTP 层契约测试：422 响应体里能读到 `error.details.blockIds == ["blk_protected_1", ...]`。
- **为什么**：C 端「跳到该块」、B 端块高亮都靠它；异常对象里早就存了（`documents.py:78-85`），只是没送出去。

### T2 「写入结果未知需对账」给专属码
- **现状**：`openclaw-tag-router/openclaw_app/services/media_business/documents.py:656-659` 抛 `DocumentUnavailable("Lark save outcome is unknown and requires reconciliation")`，code 是通用 `internal_error`（500）+ 英文 message 直达客户端。
- **改**：该处改抛专属异常：code `lark_save_outcome_unknown`、status 保持 500 或改 409（自行判断后在提交信息说明）、message 换成中文（参考 B 端原型横幅文案）。`openapi.yaml` 的 errorCodes 清单登记该码。
- **测**：加一条：同一幂等键、上一批 `running` 时再次保存 → 响应 code 为 `lark_save_outcome_unknown`。
- **为什么**：前端要渲染「去对账」专属出口，通用 internal_error 无法区分。B 端原型已按此码占位。

### T3 entry-state 写进 OpenAPI
- **改**：把 `GET /openclaw/auth/entry-state?mode=`（`media_auth_entry_state_v1`，四态）补进 `media_web_business_pages.openapi.yaml`。行为不改，只补契约描述——B/T1 合同要求"同步开放 OpenAPI"的欠账。

### T4 D1 修复 + 门禁收紧（必须同一提交落地）
- **修**：登录页两个回退态超折线（个人 1076px / 组织 1135px，目标 ≤900）。方案：`media.auth.css`（根目录与 `src/` 两份保持字节一致）——入口状态区在 `state !== 'matched'` 时收成单行精简态（图标+一句话+徽标，砍标题与副本，预计省 120–150px）；组织分支二维码 200px→160px 且与「在 Feishu 中打开」按钮并排（再省约 80px）。
- **紧**：`scripts/qa/checkMediaLoginVisualRuntime.ts` 的 `assertAuthLayout`——`scrollHeight ≤ viewport.height` 断言从仅初始 P1 扩展到全部六状态。
- **验**：`npm run qa:media-login-visual-runtime` 全绿。先紧后修会把 build 打红，所以两件事一个提交。

---

## 交付物二：C 端 C6 编辑器（UI 规格 = `personal-document-editor.html`）

### 落点与接线（全部用现成件，禁止重造）
- **新页面** `src/media/pages/ordinary/DocumentEditorPage.tsx`（+ module.css），路由 `/workspace/edit/:artifactId`，经 `personalRoute()` 挂进 `MediaStudioApp.tsx`。
- **路由登记三件套**：`mediaStudioRoutePolicy.ts`、`scripts/qa/mediaPageStructureManifest.ts`（新 surface，声明 eligible 原语与 accent）、路由矩阵会自动拦未登记的 `<Route>`——门禁红了说明登记漏项，补登记而不是绕门禁。
- **API 只用这 7 个**（`documentWorkflow.ts` 的 `createIf2DocumentApi` 已封装好，含幂等键管理）：`getDocumentBody` / `saveDocumentDraft` / `getDocumentRevision` / `createDocumentExport` / `getDocumentExport` / `getDocumentExportDownload` / `getDocumentResource`。
- **块模型**复用 `documentWorkflow.ts` 的 `DocumentBlock` 联合类型；只读渲染直接复用 `CanonicalDocumentRenderer.tsx`，编辑态在其块模型上做，**不新发明块结构**。
- **样式**：`mg` 原语 + `mediaDesignTokens.css`，正文排版参数照原型（16px/1.85，标题字距 0）。

### 一期范围（本交付物做完的定义）
按原型逐状态实现：打开、块编辑（六种行内标记：加粗/斜体/下划线/删除线/行内代码/链接——契约就这六种，不加不减）、保存（`expected_revision` + 幂等键 + 三步实况横幅：写入→登记→回读）、修订冲突 409（三出口：对比合并入口可以先禁用置灰，另存分支/放弃载入必须可用）、不支持块 422（靠 T1 的 `blockIds` 高亮到块 + 「仅保存其余块」）、断网重试、受保护块（`data_snapshot` 不可编辑+理由）、修订链（AI 生成/手动保存分标）、右栏证据账本、导出。

### AI 改稿面板（依赖交付物四 T5，接线方式如下）
组件按原型实现，flag 默认关闭；**T5 合入后开启**，接线为：
- 指令条输入 → `createArtifactRevision`（`instruction` = 用户要求原文，`expectedRevision` = 当前修订，幂等键交给 `createIf2DocumentApi` 现成管理）；
- 发起后轮询 `getDocumentRevision`：`generating` → 渲染分步实况（对应原型「保存中」横幅），`ready` → 展示新修订与结果解读，`failed` → 稳定失败态；这三个状态本来就在 `DocumentRevisionState` 联合类型里；
- **一期交互降一档**：原型的「计划三段式（将执行/需你来/不会碰）」在一期作为**完成后的结果解读**渲染（数据来自执行回执的 applied / manual_actions / 受保护跳过），不是事前确认；事前确认（plan 拆成独立可查询对象 + 确认端点）属于合同新增，随 K 第 5 版裁决，**本任务书不做**。

### 验收
`tsc -b tsconfig.media-u12b.json`、`npm run build:media` 全绿；新页面进 manifest 后 `qa:media-primitive-adoption` 与 `qa:media-route-matrix` 通过；逐状态截图对照原型（8 态）。

---

## 交付物三：B 端组织镜像页（UI 规格 = `organization-document-mirror.html`）

### 一期范围
只读镜像页（组织 shell 下挂路由，`organizationRoute()`）：正文只读渲染（复用 CanonicalDocumentRenderer）+ 常驻「只读镜像」角标 + 「在飞书中打开」+ 回读元信息（`getDocumentBody` 已返回 `remoteDocumentVersion` / `bodyChecksum` / `updatedAt`，够渲染「镜像版本 / 回读于」）+ 绑定页签（会话上下文已有组织与 Binding 信息的部分先展示，没有的字段留空不造假）。

### 依赖交付物四的部分（未落地前不渲染，不 mock）
- **同步页签 / 批次账本 / 四步写入实况**：等 T6 `listDocumentSyncBatches`（数据都在 `media_product.sync_batches`，只差只读暴露）。
- **结果未知/待对账、远端冲突、结构不支持三个横幅**：依赖 T2 专属码 + T6。
- **AI 改稿 dock**：同 C 端——发起走现成的 `createArtifactRevision`，等 T5 执行器合入后开启；B 端 ready 的定义比 C 端多一段（执行器产出正文后还要走既有的 S3 飞书写入 + 回读链路收口）。

### 验收
同交付物二的门禁 + 对照原型可实现态截图比对（一期真正能达成的是「已同步」「飞书已改·待回读」两态 + 只读正文，其余态标注等待端点）。

---

## 交付物四：修改执行器与同步端点（后端，二/三 AI 面板与同步页签的解锁项）

### T5 修改执行器（本任务书里最大的一项）
- **现状**：`createArtifactRevision` 会落一条 `state='generating'` 的修订（`runs.py:714-825`），但**没有任何执行器消费它**——发起后永远停在 generating。能力本体存在于 bot 通道（`tag_capabilities.py` 的 `handle_修改`，经 `document_edit_contract.py` 的 plan/apply/readback），只是没接到 web 落的这条修订上。
- **做**：新增一个执行器（进程内 worker 或复用现有任务执行框架，自行调研后在提交信息说明选型），消费 `generating` 修订：
  1. 读取 artifact 的 `body_authority` 分流：`internal` → 在个人正文上执行改稿并写 `revision_bodies`；`lark` → 产出正文后走**既有的** S3 飞书写入链路（`documents.py` 的 Lark save，含同步批次与回读），禁止绕过统一写入路由；
  2. 改稿逻辑**复用 `document_edit_contract.py` 的既有不变量**：受保护块不改写、图片/附件/callout/表格结构不动、无法安全定位进 manual_actions；`replace_terms` 仅精确匹配；
  3. 完成置 `ready` 并把结果解读（applied 操作数、manual_actions、受保护跳过清单）写进可回读的回执；失败置 `failed` 带稳定错误码；崩溃恢复必须幂等（同一修订不能执行两次）。
- **测**：契约测试覆盖 internal/lark 两条分流、受保护块跳过、失败置位、重复执行幂等。

### T6 `listDocumentSyncBatches` 只读端点
- **做**：`GET /artifacts/{publicArtifactId}/sync-batches`（或并入既有查询），返回最近 N 条批次的 `state / error_code / base_remote_document_version / completed_at`（camelCase 化）；OpenAPI 登记；租户隔离与既有查询同规格；分页用现成的签名游标原语。
- **测**：跨租户负例 + 状态投影正确性。

---

## 顺序与依赖

```
交付物一 T1..T4（并行，四个原子提交）
   T1 ──→ 交付物二的 422 高亮
   T2 ──→ 交付物三的对账横幅
交付物二 一期（依赖 T1；AI 面板组件做好但 flag 关）
交付物三 一期（无硬依赖，可与二并行；同步页签不渲染）
交付物四 T5/T6（可与二/三并行开发）
   T5 ──→ 二/三的 AI 改稿面板开启（发起端点现成，缺的只是执行器）
   T6 ──→ 三的同步页签与三个横幅
「计划-确认」两步（plan 独立暴露）= 合同新增，随 K 第 5 版裁决，不在本任务书
文档层（SSOT 刷新）同样等裁决，另行处理
```

## 提交后自检清单

- [ ] `npm run build:media` 全绿（含全部 QA 门禁）
- [ ] `tsc -b` 与 `tsc -b tsconfig.media-u12b.json` 零错误
- [ ] 后端 pytest 失败集合与 26 条基线逐字节一致
- [ ] 新增用户可见文案里 grep 不到 snake_case / wire 字段名（`draft|internal|personal_web|organization_lark|metric_snapshot` 等）
- [ ] 每个实现状态截图与原型对照，差异已修或已在提交信息说明
- [ ] 未新增任何 openapi 之外的请求路径
