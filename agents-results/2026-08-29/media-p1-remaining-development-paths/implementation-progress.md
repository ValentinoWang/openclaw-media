# P1 剩余问题进度投影

此文件是执行状态投影，不是编排权威。权威依赖、节点状态和发布边界以 `.ssot/manifest.json` 为准。

| 冻结基线 | 当前状态 | 说明 |
|---|---|---|
| P1 未修复 148 条 | 已开始逐条复验与产品修复 | `148` 仍是冻结起点，不是当前实时剩余数；截至本次 `main@d8a62c2`，历史逐条复验投影仍为 49 条（31 条已覆盖、7 条部分覆盖、11 条仍缺），另有 114 条尚未逐条复验；本轮新增提交须按条目重新绑定，不能自动扣减 |
| 发布切片 | 5 个已建立 | `REL-P1-UX`、`REL-P1-PIPE`、`REL-P1-BIZ`、`REL-P1-PORT`、`REL-P1-QA` 均未组装候选 |
| 当前就绪交付包 | 14 个 | P1 至 P14 均可继续；本轮已处理用户可见渲染、Router 状态呈现和创作证据合同，尚未完成全部交付包验收 |
| 已接受发布验收 | 0 个 | C1 至 C5 均等待对应交付包 |
| P1 发布决定 | 未开始 | 仅在五个候选都完成独立验收后评估 |

本计划本身通过校验不等同于 P1 已完成。

## 2026-08-29 实时复验

| 复验分片 | 已覆盖 | 部分覆盖 | 仍缺 | 合计 |
|---|---:|---:|---:|---:|
| 数据流断链与无消费产物 | 8 | 3 | 1 | 12 |
| 用户可见渲染面 | 15 | 3 | 3 | 21 |
| 创作主链 prompt | 8 | 1 | 7 | 16 |
| 已逐条复验合计 | 31 | 7 | 11 | 49 |

本轮进入 `main` 的实现提交：

- `8f32429`：复盘文档中文化并隐藏本地截图路径；任务结算状态中文化，隐藏执行器与租约内部信息。
- `7209710`：保留拆解镜头与生产摘要证据；对齐小红书轮播图文合同；修复 insight-card 否定句误伤；使 platform-fit 截断显式可见。

本轮新增进入 `main` 的原子提交：

- `d2272b5`：增长链用户可见错误信息中文化，并隔离 provider 异常细节。
- `a248d8b`：注册完播率、跳出率、互动率等复盘指标，并保留复盘记忆回链字段。
- `9683c38`：入库 analyzer 与 CreatorProfile 中文 prompt/校验合同，失败不再静默吞掉。
- `dfa6a96`：创作交接显式接入多信号合同。
- `707fdb2`：商业排期闭环测试对齐。
- `6f95e92`：修复创作候选 payload 合并后语法错误。
- `72fa092`：保留创作归因并写入交付回执，补齐归因链回归测试。
- `18b3368`：Router 活动链接注册表优先解析、强制 `table` 参数；创作回执区分 Mac 素材已绑定与未绑定状态。
- `89b9940`：增长链拒绝非中文创作者可见文本，避免英文机器腔进入结果。
- `94c5e70`：补充选题候选英文标题的负例门禁测试。
- `35bba72`：Content OS 状态推进返回机器可判定布尔结果，业务回执由上层统一渲染。

本轮验证证据：

- `/tmp/openclaw-media-p1-venv/bin/python -m pytest -q tests/test_media_growth_v2.py tests/test_media_model.py tests/test_review_memory_backflow.py selfmedia/ingest/content_flow/tests/test_analyzer_provider_order.py tests/selfmedia/creator_profiles/test_creator_profile_enrichment.py`
- 结果：`123 passed, 14 subtests passed`（Pydantic 兼容性弃用警告，不影响断言结果）。
- `python -m py_compile` 与 `git diff --check` 通过。
- `tests/test_creation_receipt.py tests/test_creation_v1.py tests/test_p0_review_loop.py`：`53 passed`。
- `openclaw-tag-router/tests/test_content_os_bridge_presentation.py tests/test_content_flow_client.py`：`98 passed`。
- `tests/test_media_growth_v2.py openclaw-tag-router/tests/test_content_os_bridge_presentation.py`：`75 passed, 18 subtests passed`。
- Router 全套：`1515 passed, 24 failed, 39 skipped, 270 warnings, 271 subtests passed`；失败集中在既有删除能力、复盘投影和能力目录合同，未将其计为 P1 完成。

补充复验（2026-08-29 后续轮次）：

- 修复 `selfmedia/creation/workflow.py` 中候选 payload 重复字典起始行后，原 P1 定向集合重新通过：`120 passed, 14 subtests passed`。
- 仓库根目录全量 `pytest` 当前不能作为整体绿灯：跨子项目收集时缺少 `openclaw_media` 安装包、`httpx`、`opentimelineio` 等独立依赖，收集阶段出现 71 个错误；这些错误不归因于本轮 P1 定向改动，后续按子项目依赖矩阵拆开验证。
- 本地验证环境使用隔离目录 `/tmp/openclaw-media-p1-venv`，未写入仓库依赖文件或全局 Python。

验证：Python 定向集合分别为 `8 passed`、`44 passed`；Router 定向集合 `13 passed, 4 subtests passed`；前端定向 QA 与 `npm run build:media` 通过。尚未复验的 114 条不得自动记为已覆盖，部分覆盖条目也不得计入关闭数。
