# C3 素材解析前端闭环

## 身份与终点

- 任务编号：`C3-MATERIAL-PARSING-FRONTEND`
- 直接节点：C3（`media.production-baseline-frontend-merge`）
- 版本元组：计划 5、依赖图 5、接口冻结 5、节点合同 4、SSOT schema 1。
- 已接受决定：D6 第 1 版；权威合同为 `agents-results/2026-08-13/media-production-e2e-closure/contracts/material-parsing-coverage-v1.json`，SHA-256 必须为 `24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56`。
- 目标：在当前隔离候选前端中完成素材解析预览、明确失败提示、人工补充、重新校验和确认卡；修复上传正文合同。不得发布或触碰远程生产。

## 唯一允许写入

- `.codex-work/merge-candidate-v4/frontend/contracts/material-parsing-coverage-v1.json`，必须与权威合同字节一致。
- `.codex-work/merge-candidate-v4/frontend/src/media/task-launch/materialParsing.ts`。
- `.codex-work/merge-candidate-v4/frontend/src/media/task-launch/DynamicTaskForm.tsx`。
- `.codex-work/merge-candidate-v4/frontend/src/media/task-launch/TaskReview.tsx`。
- `.codex-work/merge-candidate-v4/frontend/src/media/task-launch/taskDraft.ts`。
- `.codex-work/merge-candidate-v4/frontend/src/media/MediaWebWorkspace.tsx`。
- `.codex-work/merge-candidate-v4/frontend/src/media/mediaWebApi.ts`。
- `.codex-work/merge-candidate-v4/frontend/src/schemas/mediaWebTaskSchema.ts`。
- `.codex-work/merge-candidate-v4/frontend/src/media/media.css`。
- `.codex-work/merge-candidate-v4/frontend/scripts/qa/checkMaterialParsing.ts`。
- `.codex-work/merge-candidate-v4/frontend/scripts/qa/checkTaskLaunchDraft.ts`。
- `.codex-work/merge-candidate-v4/frontend/package.json`、`tsconfig.app.json`、`tsconfig.media-u12b.json`，仅在编译或脚本注册确实需要时修改。
- 监督器指定的结构化返回文件。

禁止写后端候选、SSOT、权威合同、生产快照、远程主机、数据库、飞书、账号、发布目录、凭据或服务配置。不得启动子代理或其他 worker。

## 必须实现

1. 只对 `source_asset_intake` 启用本合同。按素材类型字段 `field_3be96f8eb83d`、平台字段 `platform`、文本或链接字段 `field_c675ffae69a2`、人工补充字段 `remark` 和草稿附件查找唯一矩阵项。
2. 页面必须展示当前组合的解析方式。自动项显示“支持自动解析，提交时校验”；人工项显示权威合同中的中文失败提示、需要补充的字段和下一步动作。
3. 人工项在 `remark` 为空时必须产生草稿问题并阻止进入确认页；用户填写后必须重新计算并允许进入确认页。文件类型没有上传文件、文本或链接类型没有内容时同样阻止。
4. 确认页必须显示解析方式、预期状态、失败原因、缺失字段、人工补充结果和下一步，不得把人工补充显示为自动成功。
5. 后端返回 `material_parsing_incomplete` 或结构化解析详情时，提交失败必须保留明确中文原因并引导返回修改，不能降级为泛化错误或继续成功页。
6. `uploadMediaFile()` 正文必须精确发送 `schemaVersion: "3"`、`filename`、`contentBase64`、`idempotencyKey`；幂等键可同时保留请求头，但正文不得发送未被后端接受的 `mimeType`。上传回执 schema 能接收可选结构化 `parsing`。
7. 新建 `qa:material-parsing` 门禁，至少覆盖 54 项唯一组合、自动/人工边界、缺少 `remark` 被阻止、补充后通过、文件缺失被阻止、确认卡含解析信息、上传正文合同以及后端结构化失败提示。
8. 不改变其他能力的草稿校验和确认行为。不要手工维护第二份矩阵逻辑；前端只消费字节一致合同。

## 返回与停止条件

- 固定验证退出码为 0 时，返回 `proposed_state: VERIFIED`、`acceptance_self_check: pass`、`failure_class: none`。
- 合同漂移、越权写入、隐式默认支持或绕过人工补充时，返回 `BLOCKED`、`scope-conflict` 并停止。
- 编译、测试或构建失败时返回 `FAILED`、`failure_class: verification`；不得删除断言或扩大写入范围。
- 不得自行把 C3 标记为 `ACCEPTED`。返回必须列出实际修改文件、命令退出码、合同哈希、未验证事项、风险和生产未触碰声明。
