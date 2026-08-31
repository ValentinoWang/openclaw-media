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

以下是验收判读材料已记录的历史执行，而非当前工作树的重跑。源代码身份为 `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235`；文档记录提交时间为 `2026-08-31T19:09:24+08:00`。原始材料没有保存每条命令的精确开始时间或完整测试日志，因此空缺明确保留，后续当前 HEAD 重跑必须另建带 source identity 的执行证据。

| 验收区域 | 执行日期 | 源码提交 | 结果 | 已知基线失败清单 | 证据路径 |
| --- | --- | --- | --- | --- | --- |
| 登录入口状态 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS：四态矩阵与 19 张运行时截图 | 无 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |
| 普通路由矩阵 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS：4 类会话全路径矩阵与合成漂移负例 | 无 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |
| 共享视觉原语 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS：原语采用门禁与自测通过 | 无 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |
| 入口状态合同 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS：matched、none、expired、mismatched 与越权负例 | 无 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |
| Stage-1 工作台运行时 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS：双视口、路由和外部字体请求检查 | 无 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |
| 视觉构建门禁 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS：15/15 门禁、两次 tsc 与 Vite 构建通过 | 无 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |
| 全量回归 | 源文档未记录精确开始时间；最晚于记录提交时间 | `759af4c659c6d6a85fd8eac7cd4d2d345d3cf235` | PASS WITH BASELINE：1638 passed，26 failed 与基线一致 | 26 条；原文只保留数量与逐字节一致结论，未保留逐项失败名，不能据此声明当前 HEAD 同样通过 | `docs/frontend/prototype/stage2-acceptance-execution.html（第 04 节）` |

## 证据分层

运行时门禁与截图只形成 source/local-runtime 证据，不能替代真实组织扫码、飞书编辑后再回读、28 天会话持久化部署读回或独立外部验收。

## 人工验收保留项

1. [`ST2-HUM-ORG-SCAN`](../../../acceptance/human/ST2-HUM-ORG-SCAN/checklist.md)：真实组织扫码、组织壳层与错误工作区恢复；绑定 O1。
2. [`ST2-HUM-LARK-READBACK`](../../../acceptance/human/ST2-HUM-LARK-READBACK/checklist.md)：飞书编辑后再回读；绑定 O5。
3. [`ST2-HUM-LOGIN-FOLD`](../../../acceptance/human/ST2-HUM-LOGIN-FOLD/checklist.md)：登录回退态折线确认；绑定 K，并跟踪 `assertAuthLayout` 缺口。
4. [`ST2-HUM-SESSION-28D`](../../../acceptance/human/ST2-HUM-SESSION-28D/checklist.md)：28 天会话持久化真实部署读回；绑定 DB。

四项工作区均为 `PREPARING`：没有 machine-green handoff，也没有人工签署结果；不得修改 checklist 记录一次执行。

## 当前合同提醒

K 第 5 版已裁决：routeGrants 保留为会话内路由清单漂移检测，而非授权投影。B 仍须把会话合同重签为 `media_web_business_pages_v3`，收敛三份人工维护的清单为一份生成源，并让登录入口状态接口同步进入 OpenAPI 与客户端类型；这些实施债务尚未因裁决或历史门禁而接受。
