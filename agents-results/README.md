# agents-results 发布边界

本目录保存 Media 项目的可接力开发事实和验收证据，不是运行时数据仓库。

## 本次发布来源

- 本机：`/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/agents-results/`
- 106 云服务器：`ubuntu@106.52.146.37:/home/ubuntu/selfmedia-tools/openclaw-tag-router/agents-results`
- GitHub：`ValentinoWang/openclaw-media` 的 `main`

106 云服务器的 `agents-results` 是指向 `/home/ubuntu/agents-results/openclaw-tag-router` 的符号链接。云端当前主要是 2026-08-12 数学发布历史和通用质量门禁，没有与 Media Stage-1/Stage-2 同名的必要 SSOT；因此本次没有把无关历史整体搬入本仓库。云端实际代码、服务和运行数据继续以服务器工作树和部署记录为准。

## 保留内容

- `2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding/`：Stage-1 canonical SSOT、进度、归档声明、生成视图、验收片段、确定性 receipts、发布契约/门禁和可复核脚本。
- `2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/`：Stage-2 canonical SSOT、进度、生成视图、节点/执行契约和必要 worker 返回材料。
- `2026-08-13/media-production-e2e-closure/`：E2E closure 的 canonical SSOT、契约和必要结果/校验材料。
- `2026-08-18/`、`2026-08-19/`：个人认证、飞书登录、组织身份公开投影的必要验证记录。
- `2026-08-28/`、`2026-08-29/`：已有 P1 实施、审查、去重和剩余开发路径记录。

接力入口优先阅读：

1. `2026-08-15/media-c-b-stage-2-content-and-ai-document-routing/ssot-development-paths.md`
2. 同目录 `implementation-progress.md`、`.ssot/manifest.json` 和 `.ssot/validation-report.json`
3. Stage-1 对应目录的 `ssot-development-paths.md` 与 `implementation-progress.md`
4. 当前 P1 的 `2026-08-29/media-p1-remaining-development-paths/ssot-development-paths.md`

## 明确排除

运行日志、临时 worker 输出、缓存、`__pycache__`、截图 PNG/JPG/WebP、音视频、下载物、数据库和任何凭据不进入 GitHub。需要这些材料时，应从原始本机/106 云端证据路径按任务单独取证，而不是把整个运行目录提交。

SSOT Markdown 是人类阅读入口；`.ssot/manifest.json` 和其中的机器文件是该 bundle 的机器权威。GitHub 副本是开发交接和代码审查材料，不替代生产部署状态、真实设备验收或云端运行时读回。
