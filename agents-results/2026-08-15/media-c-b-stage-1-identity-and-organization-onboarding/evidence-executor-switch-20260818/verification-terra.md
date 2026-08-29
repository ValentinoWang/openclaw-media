# Terra 执行器切换验证

验证时间：2026-08-18（Asia/Shanghai）

## 结论

- 项目级 `.ssot/manifest.json` 的默认执行器为 `lw-terra`。
- 默认可写封装为 `run-lw-terra.sh`。
- `lw-luna` 与 `lw-terra` 均仍在允许的执行器集合中；历史节点的显式 Luna 记录保持不变。
- SSOT 机器、结构、视图、复杂度和中文可读性门禁通过。
- Harness 路由合同测试和 schema 回归测试通过。
- Harness 修复已快进远端 `main`：`93d2a2f03770f66094285981b2a6dc26b1a5f0e5`。
- Obsidian 选择性快照同步和 `--check` 通过，共管理 1 个声明文档，无 `openproblem.md`。
- 远端产品服务在 2026-08-18 04:53（中国标准时间）复核时仍运行于 r3；`healthz`、`readyz`、会话组合守卫和官方部署守卫通过。

## 机器源校验值

| 文件 | SHA-256 |
|---|---|
| `.ssot/manifest.json` 的稳定身份 | `8e27e2d6e96f9454653d161fe0ead4dd92c55395bde351dca8a02a36156cfadd` |
| `.ssot/planning-compiler.json` | `3ab2e14ca3431f515311e4c4ad6357572f7b8afddc3bcc6487515fdc034e7ac5` |
| `ssot-development-paths.md` | `558b40b11c399fd6f5d8b9e766562a07e7ecd8968c83df9a07a60496112659e6` |
| `implementation-progress.md` | `c861217397a24148278b40dc4666ad2897e7a0ff4a38e0cf675ed03ecc3b7afc` |

## 验证命令

```text
validate_ssot_complexity.py .ssot/planning-compiler.json -> passed
check_ssot_program.py .ssot/manifest.json -> passed (nodes=50)
render_ssot_views.py --check .ssot/manifest.json -> passed
check_chinese_readability.py ssot-development-paths.md -> passed
analyze_ssot_parallelism.py .ssot/manifest.json -> passed
python3 -m unittest .../test_external_worker_routing_contract.py -> 13 passed
python3 -m unittest .../test_schema_v2_regressions.py -> 15 passed
snapshot_ssot.py --check -> verified (file_count=1)
validate_ssot_bundle.py -> passed
```

## 审计边界

全局 `snapshot_ssot.py --audit-archive` 仍被四个历史归档的失效源路径阻塞：

- `2026-08-07/openclaw-media/media-cb-web-document-preview`
- `2026-08-09/openclaw-media/media-operations-master-base-naming`
- `2026-08-12/鸿儒数字化教育/math-markdown-feishu-opc-publishing`
- `2026-08-15/Company-OS/feishu-organization-ai-installation`

这些归档不属于本次项目范围；未删除、未改写，也未将其错误包装为本项目完成证据。
