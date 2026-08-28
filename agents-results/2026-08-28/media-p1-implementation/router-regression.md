# Router 回归证据

- 日期：2026-08-28
- 候选基线：`b8586379be58169250ed28f19c6dea805da239a9`
- 范围：系统说明路由与其关联的 15 个 Router 测试文件。
- 环境：临时 `uv` Python 3.11 环境；通过 `127.0.0.1:7897` 代理下载缺失依赖。

## 结果

命令通过：`136 passed, 196 warnings, 76 subtests passed in 8.60s`。

警告均为现有的 `Pydantic` 和 `jsonschema.RefResolver` 弃用告警；没有测试失败。系统说明测试现在直接渲染仓内 `generate_bot_capability_docs.py`，不再读取不存在的远端绝对路径或断言完整聊天说明文案。
