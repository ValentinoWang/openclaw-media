# Wave 17 素材解析主线复核结果

验证时间：2026-08-15T10:50:29Z

## 结论

C3 前端与 C4 后端的素材解析实现已在本地隔离候选中通过主编排责任人复核。54 个“素材类型 × 平台”组合继续以冻结合同为唯一业务权威，前端与后端副本字节一致。自动解析只有在必填输出完整时才能完成；不支持、解析失败或缺失必填字段都会返回中文原因、缺失字段和下一步操作，进入人工补充复验；未完成时在入队前失败关闭。

本结果不是远程发布、生产验收或真实外部附件证据。本轮没有修改远程主机、生产数据库、飞书、账号、凭据、活动发布或服务配置。

## 固定合同

- 合同：`contracts/material-parsing-coverage-v1.json`
- SHA-256：`24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56`
- 覆盖：9 个平台、6 种素材类型、54 个唯一组合
- 允许入队的解析状态：`completed_auto`、`completed_manual`
- 未完成错误：`material_parsing_incomplete`，HTTP 422

## 红绿门禁

1. 修复前的认证 HTTP 往返可稳定复现 500：`SessionPrincipal` 缺失 `session_token_hash`，任务服务调用次数为 0。
2. 根因是账户会话未传递已经存在于租户数据中的 `workspace_mode`，导致 `SessionPrincipal` 位置参数错位。
3. 修复后，新会话发放和数据库会话读回都会校验并投影 `workspace_mode`，HTTP 上下文再把它传入 `SessionPrincipal`。
4. 修复后 HTTP 专项为 1 项通过，会话工作区模式单测为 2 项通过。
5. Wave 17 全量命令最终退出码为 0：后端 40 项通过；前端素材解析、任务启动、TypeScript、Media 生产构建和现有 Chromium 交互门禁通过；最终认证 HTTP 往返 1 项通过。

## 源码身份

- 前端候选树：`57b0b13ef179977d3b70c95caea660b2af54aa2859ec0f575f8db8d644a71edd`
- 后端候选树：`b1bee01ea908f6296ecd7377ff15a5cbf42a166315135de0434a5674cecaf69a`
- 计算方式：按相对路径排序后对每个文件计算 SHA-256，再对清单计算 SHA-256。前端排除 `node_modules`、`dist-media`、`dist`、`.vite`和 Python 缓存；后端排除 `.pytest_cache`、Python 缓存和 `*.pyc`。

## 证据路径

- C3 进程台账：`execution-wave-16/C3-MATERIAL-PARSING-FRONTEND/ledger/C3-MATERIAL-PARSING-FRONTEND.json`
- C3 结构化返回：`execution-wave-16/C3-MATERIAL-PARSING-FRONTEND/returns/C3-MATERIAL-PARSING-FRONTEND-luna.json`
- C4 进程台账：`execution-wave-16/C4-MATERIAL-PARSING-BACKEND/ledger/C4-MATERIAL-PARSING-BACKEND.json`
- C4 结构化返回：`execution-wave-16/C4-MATERIAL-PARSING-BACKEND/returns/C4-MATERIAL-PARSING-BACKEND-luna.json`
- 主线复核命令：`execution-wave-17/validation/material-parsing-main-thread-review.sh`

## 未验证边界

- 未部署到 `106.52.146.37`，未重启服务，未运行生产迁移。
- 未使用真实质量验收账号完成桌面端与移动端浏览器验收。
- 未使用真实图片、音频、视频、PDF 或外部平台链接生成生产收据。
- 未验收生产数据库、飞书、所有者投影和网页刷新读回是否属于同一收据。
