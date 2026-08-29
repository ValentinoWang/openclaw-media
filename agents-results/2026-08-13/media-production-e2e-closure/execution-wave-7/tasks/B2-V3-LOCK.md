# B2-V3-LOCK 有界任务

## 身份与目标

- 任务编号：`B2-V3-LOCK`
- 直接父节点：B2（`media.context-task-e2e-contract`）
- 版本元组：计划 3、依赖图 3、接口冻结 3、节点合同 3、SSOT schema 1
- 已接受决定：`media.no-inference-completion-boundary@1`、`media.same-receipt-proof@1`、`media.release-capability-samples@2`、`media.representative-account-binding-input@1`
- 失效键：`contract.context-task-e2e`、`decision.release-capability-samples`、`decision.representative-account-binding-input`
- 目标：按用户已经接受的 OP03 与 D5 v1，新增并正式锁定 `MPE2E-TASK-RUN-V3` 合同、中文人工清单、哈希绑定和保护性测试。第 2 版四项资产必须保持字节不变。本任务只完成验收设计，不实现 C2，不创建生产任务或生产收据。

## 冻结输入

- `.ssot/nodes/D5.json` SHA-256：`c6bd807376561c25820938b1839f50b633a7e2f4911f3460fea9a6f5e1a0e12b`，必须保持 D5 v1 `ACCEPTED`。
- `.ssot/nodes/B2.json` SHA-256：`bc03cff59c504da915380b0357550ff34eaa231a37c5cbd103170c1adb6bbf7d`，必须保持 `READY`、`FORMAL`，且无活动假设。
- 第 2 版合同 SHA-256：`f2f97099c514b8a9b5570c7626cc5e746ce99394370985000cdddd5094a18bf2`。
- 第 2 版中文清单 SHA-256：`45664f75ee37535b3e67242a4c0550735a131f50281d5fca34f0e6d1e095724f`。
- 第 2 版绑定 SHA-256：`48b84499da08393953eec17fe7afc0fed209ed908e427522254ef20414c2fe9b`。
- 第 2 版保护测试 SHA-256：`334d2393059e54980a8434a99d59bef1b1f82d1466549f540aa40e4f5f0e50d0`。
- 第 2 版合同、清单、绑定和保护测试只读作为历史基线，不得覆盖、重命名、删除或修改。
- B3 收据检查器 `scripts/check-media-e2e-receipt.mjs` 只读复用，不得修改。

## 唯一允许写入

- `agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-TASK-RUN-V3/**`
- `acceptance/human/MPE2E-TASK-RUN-V3/checklist.md`
- `acceptance/human/MPE2E-TASK-RUN-V3/binding.md`
- `scripts/acceptance/test-mpe2e-task-run-v3.sh`
- 生成式索引 `acceptance/index.md`
- supervisor 在提示词中指定的唯一结构化返回文件

## 禁止写入与副作用

- 不得写入 `.ssot/**`、`ssot-development-paths.md`、`openproblem.md`、`implementation-progress.md` 或任何视图源；正式节点迁移由主编排负责。
- 不得修改第 2 版四项资产、B3 检查器、既有 fixtures、C1/C2 候选代码、远程主机、数据库、飞书、活动发布、生产收据或人工运行结果。
- 不得修改、弱化、跳过、隔离或删除既有保护测试。
- 不得创建旧输入兼容、回退、默认账号、模糊查找或双轨合同。
- 不得保存或输出密码、Cookie、令牌、密钥、私人正文或环境变量内容。
- 不得启动子代理、聊天内协作或其他 Codex worker。

## 必须完成的第 3 版语义

1. 新合同任务编号为 `MPE2E-TASK-RUN-V3`，合同版本为 3，状态为 `APPROVED`，测试基线为 `LOCKED`，就绪模式为 `FORMAL`，活动假设为 `none`。批准证据必须引用用户在 2026-08-14 采纳 OP03 推荐方案以及 D5 v1 的已接受机器决定。
2. 决定引用必须完整包含四项已接受决定，失效键必须包含 `decision.representative-account-binding-input`。
3. 只对创作咨询（`selfmedia_creation_consultation`）和自媒体创作（`selfmedia_creation`）收紧创建任务输入。两项都必须提供平台和客户自有账号；创作咨询还必须提供问题，自媒体创作保留其原有必填内容。其他能力保持现有输入要求。
4. 精确绑定键必须由当前租户、当前认证用户公开编号、规范化平台和规范化账号共同构成。账号文字相同不能替代正式关系记录。
5. 缺少平台、缺少账号、缺少认证用户公开编号、关系不存在、多义关系、跨租户、跨用户或关系冲突必须在入队前失败关闭，不创建任务、执行尝试、租约、产物、飞书对象或成功收据。
6. API 与前端必须使用稳定、可区分且不泄露跨租户存在性的错误语义。至少区分：必填输入缺失、账号关系未找到或不可见、账号关系不唯一或冲突。不得退回旧输入路径、默认账号或事后异步失败。
7. 成功收据必须在既有第 2 版同收据要求之上，证明平台、客户账号、认证用户公开编号、租户及正式绑定关系与任务一致；两项代表能力都必须满足。创作咨询仍不得新建飞书对象，自媒体创作仍必须完成飞书强制读回。
8. 保护测试必须是独立新文件 `scripts/acceptance/test-mpe2e-task-run-v3.sh`，复用而不是修改 B3 检查器。它必须在缺少真实生产收据时以退出码 3 保留预实现红灯，并对上述必填、精确绑定和失败关闭字段进行可执行断言。固定样例、模拟数据或历史拼接不得通过生产门禁。
9. 中文人工清单必须只记录产品负责人需要人工判断的账号选择、错误可理解性、跨租户不可见性、失败不入队和成功收据一致性；不得填写一次运行结果。
10. 用 `manage_acceptance_artifacts.py bind-human --replace` 生成哈希绑定，并生成、校验任务索引和项目人工索引。所有路径使用项目根相对路径。

## 验收与停止条件

- 运行预冻结验收命令；所有静态、合同、绑定、索引、字节不变和预实现红灯断言必须通过。
- 可提议 `VERIFIED`，不得自行标记 B2 为 `ACCEPTED`。
- 如果发现 OP03/D5 与现有权威冲突、无法在上述写区内形成完整合同，返回 `BLOCKED`，`failure_class` 使用闭集中的准确值，不得自行扩大范围。

## 结构化返回

结构化返回必须包含：任务编号、attempt role、版本元组、包装器路径、实际读写范围、命令及退出码、v3 合同/清单/绑定/保护测试哈希、v2 四项哈希不变证明、有效红灯证据、禁止范围不变、未验证事项、共享资源影响、风险、偏差、`failure_class`、`acceptance_self_check` 和 proposed state。
