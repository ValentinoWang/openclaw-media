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

## 证据分层

运行时门禁与截图只形成 source/local-runtime 证据，不能替代真实组织扫码、飞书编辑后再回读、28 天会话持久化部署读回或独立外部验收。

## 人工验收保留项

1. 真实组织扫码与部署读回。
2. 飞书编辑后再回读。
3. 登录回退态折线确认。
4. 28 天会话持久化真实部署读回。

## 当前合同提醒

routeGrants 已进入当前源码的严格会话 schema，但早期产品决定曾明确禁止向会话信封增加该字段；该冲突需在 B 节点重新裁决，不能由静态门禁自动视为已接受。
