# 第二阶段验收执行

## 自动化验收映射

| 验收区域 | 命令 | 证据 | 判读方式 | 缺口/边界 |
| --- | --- | --- | --- | --- |
| 登录入口状态 | npm run qa:media-login-visual-runtime | 运行时 PNG 与四态矩阵 | 自动化 + 人工读图 | 回退态需确认不超过一屏 |
| 普通路由矩阵 | npm run qa:media-route-matrix | 统一路由注册表与越权负例 | 自动化 | 导航重定向与数据/动作 403 必须分层 |
| 共享视觉原语 | npm run qa:media-primitive-adoption | 24 面结构清单与原语使用 | 自动化 | 采用率不等同本地样式完全删除 |
| 入口状态合同 | pytest openclaw-tag-router/tests/test_auth_entry_state.py | entry-state 四态响应与错误语义 | 自动化 | 与工作台 route grants 合同分开验收 |
| Stage-1 工作台运行时 | npm run qa:media-stage1-workspace-runtime | 认证浏览器运行时截图 | 自动化 + 人工读图 | 不等同真实部署读回 |
| 视觉构建门禁 | npm run build:media | 构建与视觉/结构 QA 门禁 | 自动化 | 记录已知基线失败，不提升 SSOT 节点状态 |
| 全量回归 | pytest openclaw-tag-router/tests/ --ignore=tests/test_sync_lark_base_projection.py | 全量测试与基线分类 | 自动化 | 已知失败必须与新回归分开 |

## 验收基线与判读材料

| 材料 | 路径 | 提交 | 用途 | 证据边界 |
| --- | --- | --- | --- | --- |
| C6 交互验收基线 | `docs/frontend/prototype/personal-document-editor.html` | `ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5` | 个人正文编辑器 8 态交互规格 | 设计基线/静态文档；不等同节点接受 |
| 组织镜像交互验收基线 | `docs/frontend/prototype/organization-document-mirror.html` | `ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5` | 组织只读镜像与同步控制台 8 态交互规格 | 设计基线/静态文档；不等同节点接受 |
| 验收判读材料 | `docs/frontend/prototype/stage2-acceptance-execution.html` | `ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5` | 7 个自动化区域的历史执行摘要与 4 项人工保留项 | 设计基线/静态文档；不等同节点接受 |
| 实施入口 | `docs/frontend/prototype/stage2-dev-brief.md` | `ade7c05cfe775aa3f9d3d1456eb02ae23dfbf9c5` | 第二阶段 C/B 实施顺序、范围和门禁 | 设计基线/静态文档；不等同节点接受 |

## 记录的最近执行

以下是当前源码重跑记录，源代码身份为 `ca17317f2a559eb033f9667a4d8ad6389010d190`，记录时间为 `2026-09-02T00:58:00+08:00`。每条记录均指向本包外的可复现输出；完整 Router 回归的历史基线差异单列，不能把 `PASS WITH BASELINE` 误写为全绿。

| 验收区域 | 执行日期 | 源码提交 | 结果 | 已知基线失败清单 | 证据路径 |
| --- | --- | --- | --- | --- | --- |
| 登录入口状态 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS：`build:media` 中的登录视觉运行时四态检查通过 | 无 | `agents-results/2026-09-01/stage2-document-edit-validation/media-build-output.txt` |
| 普通路由矩阵 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS：`build:media` 中的路由矩阵与合成漂移负例通过 | 无 | `agents-results/2026-09-01/stage2-document-edit-validation/media-build-output.txt` |
| 共享视觉原语 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS：`build:media` 中的原语采用及自测通过 | 无 | `agents-results/2026-09-01/stage2-document-edit-validation/media-build-output.txt` |
| 入口状态合同 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS WITH BASELINE：`test_auth_entry_state.py` 8 项通过 | 完整 Router 套件尚有 32 项历史失败；均为父提交 42 项失败集合的子集 | `agents-results/2026-09-01/stage2-document-edit-validation/router-full-pytest-output.txt` |
| Stage-1 工作台运行时 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS：`build:media` 中的双视口、路由和外部字体请求检查通过 | 无 | `agents-results/2026-09-01/stage2-document-edit-validation/media-build-output.txt` |
| 视觉构建门禁 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS：完整前端构建、TypeScript、Vite 和配置的 QA 门禁通过 | 仅 Vite 大 chunk 体积建议，非失败 | `agents-results/2026-09-01/stage2-document-edit-validation/media-build-output.txt` |
| 全量回归 | 2026-09-02T00:58:00+08:00 | `ca17317f2a559eb033f9667a4d8ad6389010d190` | PASS WITH BASELINE：1683 passed，40 skipped，32 failed | 32 项均在父提交 `37e58dc3` 的 42 项失败集合中；本轮额外修复了 10 项过期迁移清单断言 | `agents-results/2026-09-01/stage2-document-edit-validation/verification.md` |

## 证据分层

运行时门禁与截图只形成 source/local-runtime 证据，不能替代真实组织扫码、飞书编辑后再回读、28 天会话持久化部署读回或独立外部验收。

## 人工验收保留项

人类阻断预算：3/3。
1. `ST2-HUM-ORG-SCAN`：绑定 O1。
2. `ST2-HUM-LARK-READBACK`：绑定 O5。
3. `ST2-HUM-SESSION-28D`：绑定 DB。

降级为机器可测试（不占用人类阻断预算）：
- `ST2-HUM-LOGIN-FOLD`：绑定 K；改由机器验收，人工读图仅作非阻断参考。

上述工作区均为 `PREPARING`：没有 machine-green handoff，也没有人工签署结果；不得修改 checklist 记录一次执行。

## AI review lane policy

AI review 使用单一独立 zero-write lane；每个 scoped finding 最多允许一次 finding-only rereview。AI 只能提交结构化发现，不能写入候选、代替实现者修复、接受节点或晋升发布；修复由实现责任方完成后再触发该发现的独立复核。

## 当前合同提醒

K 第 5 版已裁决：routeGrants 保留为会话内路由清单漂移检测，而非授权投影。B 仍须把会话合同重签为 `media_web_business_pages_v3`，收敛三份人工维护的清单为一份生成源，并让登录入口状态接口同步进入 OpenAPI 与客户端类型；这些实施债务尚未因裁决或历史门禁而接受。
