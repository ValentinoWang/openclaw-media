# 人工验收清单：PR-REL-MANIFEST

- 任务编号：PR-REL-MANIFEST
- 人工验收绑定：acceptance/human/PR-REL-MANIFEST/binding.md
- 验收合同：docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST/acceptance-contract.md
- 合同版本：1
- 清单状态：已批准
- 所需人工角色：生产对账负责人
- 清单负责人：用户授权的 2026-08-25 Production Reconciliation source-only 负责人
- 批准证据：用户提供的 `BASELINE=59e2adf`、父级 source authority `5f06780569568ccc3197f0ab16aad74bdf9d1c6f`、`TASK_SOURCE_SHA256=a74922a742e44b1ac2b9eb556f9c858bfbd91e7ecb44bbfdf1264dda3a2a071a` 与 `PR-REL-MANIFEST-DESIGN-V2` 任务授权；该证据只批准 source-only 验收设计，不批准产品、部署、发布或生产接受。
- 执行结果：acceptance/human/PR-REL-MANIFEST/runs/<run-id>/result.md

本清单只判断 source-only 边界、交接可理解性和后续使用条件，不重复自动化测试已经负责的路径、符号链接、文件模式、文件摘要、规范化 JSON、Git 状态或错误码断言。人工结论不能覆盖机器门禁，也不能把本任务变成生产发布批准。

## H-01

- 验收问题：生产对账人员能否仅根据验收合同，清楚区分本任务已经批准的 source-only 工作与仍然未验证的部署、回滚、外部系统和 Stage-2 接受事项？
- 必须人工判断的原因：边界是否清楚、是否容易误把验收设计当成发布批准，属于操作理解和治理风险，不能由确定性 manifest 断言单独证明。
- 前置条件：已阅读 `docs/production-reconciliation/20260825/deployment-gate.json`、`docs/production-reconciliation/20260825/source-shas.json`、验收合同和当前绑定；不访问远程主机、不读取秘密、不执行部署。
- 验收步骤：
  1. 不阅读生产实现代码，先阅读验收合同的“Non-goals”“Risks and open decisions”和冻结文档中的 claim boundary。
  2. 用自己的话说明本任务可以证明的 source-only 结果，以及至少三项仍需另行证明的发布或生产事项。
  3. 判断合同、中文清单和结构化返回是否明确写出不得宣称 `ACCEPTED` release state。
- 预期观察：人员能准确说明本任务只锁定 manifest schema、canonical serializer、fail-closed validator 的验收边界；能指出部署、服务、指针、Nginx、数据库、Feishu、真实请求、回滚和 Stage-2/Stage-1 正式接受均不在本次授权内；不会把测试红证据或 source-only 合同当作生产发布证据。
- 是否阻塞发布：否；本项只记录后续发布使用前的人工清晰度，不阻塞 source-only 代码实现。
- 结果记录规则：将人工说明、观察、结论和签名身份写入新的 `acceptance/human/PR-REL-MANIFEST/runs/<run-id>/result.md`；不得修改本清单来记录某次执行结果。

## H-02

- 验收问题：未来实现负责人能否根据合同和受保护测试，明确实现文件的保留范围、测试证据位置和交接限制，而无需自行推断额外的部署权限？
- 必须人工判断的原因：范围说明是否可操作、交接资料是否会诱导越权，属于文档可理解性和流程质量，不能仅由机器测试证明。
- 前置条件：已阅读验收合同的“Expected outcome”“Protected acceptance tests”“Reserved future implementation scope”和结构化返回；不创建或修改保留的生产实现文件。
- 验收步骤：
  1. 在不执行生产动作的前提下，指出三个保留的未来实现路径和一个受保护测试路径。
  2. 说明受保护测试为 baseline red 的含义，以及实现负责人不得修改、删除、跳过或削弱该测试的要求。
  3. 说明哪些变更必须新建或 supersede 验收决定，不能通过本合同自行扩展。
- 预期观察：人员能准确识别三个 reserved future implementation paths、受保护测试路径、fragment acceptance evidence 路径和结构化返回路径；能说明 source-only contract 不等于实现完成、部署完成或 release acceptance；能指出修改字段、路径策略、错误码、公共调用面或部署权限需要新的验收决定。
- 是否阻塞发布：否；本项只为后续实现和发布评审提供清晰交接，不阻塞 source-only 代码实现。
- 结果记录规则：将人工说明、观察、结论和签名身份写入新的 `acceptance/human/PR-REL-MANIFEST/runs/<run-id>/result.md`；不得修改本清单来记录某次执行结果。
