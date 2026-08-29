# C4 素材解析后端闭环

## 身份与终点

- 任务编号：`C4-MATERIAL-PARSING-BACKEND`
- 直接节点：C4（`media.production-baseline-backend-merge`）
- 版本元组：计划 5、依赖图 5、接口冻结 5、节点合同 4、SSOT schema 1。
- 已接受决定：D6 第 1 版；权威合同为 `agents-results/2026-08-13/media-production-e2e-closure/contracts/material-parsing-coverage-v1.json`，SHA-256 必须为 `24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56`。
- 目标：在当前隔离候选后端中完成素材自动解析、结构化人工补充、重新校验、上传合同统一和入队前失败关闭。不得发布或触碰远程生产。

## 唯一允许写入

- `.codex-work/merge-candidate-v4/backend/contracts/material-parsing-coverage-v1.json`，必须与权威合同字节一致。
- `.codex-work/merge-candidate-v4/backend/openclaw_app/services/material_parsing.py`。
- `.codex-work/merge-candidate-v4/backend/openclaw_app/services/media_web_tasks.py`。
- `.codex-work/merge-candidate-v4/backend/openclaw_app/services/capability_input_contracts.py`。
- `.codex-work/merge-candidate-v4/backend/openclaw_app/server_cli.py`，仅用于注入已有内容流 URL 解析回调。
- `.codex-work/merge-candidate-v4/backend/openclaw_app/contracts/media_web_tasks.openapi.yaml`。
- `.codex-work/merge-candidate-v4/backend/tests/test_material_parsing.py`。
- `.codex-work/merge-candidate-v4/backend/tests/test_media_web_tasks.py`。
- 与上传或能力合同直接对应的现有测试文件，仅在确实需要验证公开合同漂移时修改。
- 监督器指定的结构化返回文件。

禁止写前端候选、SSOT、权威合同、生产快照、远程主机、数据库、飞书、账号、发布目录、凭据或服务配置。不得启动子代理或其他 worker。

## 必须实现

1. 新建严格加载器，启动时验证合同编号、状态集合、9 个平台、6 个素材类型、54 个唯一组合、解析模式、解析器版本、中文失败提示、人工字段和下一步动作；任何漂移或重复必须失败关闭。
2. 只对 `source_asset_intake` 在创建任务前执行素材解析。按 `field_3be96f8eb83d`、`platform`、`field_c675ffae69a2`、`remark` 和已验证上传文件确定唯一组合，禁止猜测未知组合。
3. 文本非空时用 `utf8-text` 返回 `completed_auto` 和 `normalizedText`。微信、抖音、小红书链接调用已有 `content_flow_client.analyze`；只有回调成功且 `sourceUrl`、`title`、`content` 全部非空才是 `completed_auto`。
4. 不支持项、解析器不可用、解析异常或自动输出不完整必须返回结构化 `pending_manual`，包含平台、素材类型、模式、解析器、错误码、中文原因、缺失字段、`manualFields: ["remark"]` 和 `nextAction`。若原始素材存在且 `remark` 非空，则重新校验为 `completed_manual`；不得伪装为自动成功。
5. 任务只能在解析状态为 `completed_auto` 或 `completed_manual` 时调用 `repository.create_task()`。否则抛出 `material_parsing_incomplete`、HTTP 422，并附结构化解析详情；测试必须证明仓库创建调用次数为 0。
6. 最终结果写入 `invocation.material_parsing`，保留原始参数与上传引用，不覆盖用户原文。素材类型与实际 MIME 不一致、文件类型没有上传、文本或链接没有原始内容必须失败关闭并给出明确缺失字段。
7. 上传存储状态与解析状态分开。`create_upload()` 请求正文精确接受 `schemaVersion`、`filename`、`contentBase64`、`idempotencyKey`；OpenAPI 与实现一致，回执可包含结构化 `parsing`，不得把存储 `ready` 当成解析完成。
8. 补强 `source_asset_intake` 能力合同：素材类型、平台必填；枚举必须是合同中的 6 类和 9 平台；文本/链接要求原文，文件类型要求上传；人工补充继续使用 `remark`。不得影响其他能力。
9. 测试至少覆盖 54 项唯一组合、合同漂移、文本自动完成、三种 URL 完整成功、URL 不完整、解析异常、所有人工项、人工补充复验、类型/MIME 不一致、缺上传、缺原文、未完成不创建任务、完成结果写入 invocation，以及上传/OpenAPI 正文一致。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 合同漂移、越权写入、静默缺字段、未完成仍入队时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 编译或测试失败时返回 `FAILED`、`failure_class: verification`；不得删除断言或扩大写入范围。
- 不得自行把 C4 标记为 `ACCEPTED`。返回必须列出实际修改文件、命令退出码、合同哈希、未验证事项、风险和生产未触碰声明。
