# 人工验收清单：PR-REL-PLANNER

- 任务编号：PR-REL-PLANNER
- 人工验收绑定：acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/binding.md
- 验收合同：docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance-contract.md
- 合同版本：1
- 清单状态：已批准
- 所需人工角色：生产协调负责人
- 清单负责人：用户授权的 2026-08-25 Production Reconciliation 负责人
- 批准证据：用户提供的 `BASELINE=59e2adfd34853b6929d9fa69e69585806ac9c83a`、`TASK_SOURCE_SHA256=a639ea7ae4b95fe6b2689fcbb5357d3851bd83a9e70f31d36b18bcad4fbb62a` 与后续“请继续”授权；该证据仅批准 source-only 验收设计，不批准产品、部署、发布或生产接受。
- 执行结果：acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/runs/<run-id>/result.md

本清单只判断边界理解、计划可读性和后续交接质量，不重复自动化测试已经负责的 SHA、路径、manifest、指针 CAS、回滚兼容、规范化 JSON、幂等或无外部动作断言。人工结论不能覆盖机器门禁，也不能把 source-only 设计或红证据解释为部署、发布或生产接受。

## H-01

- 验收问题：生产协调人员能否仅根据验收合同，清楚区分本任务已经批准的 source-only 计划设计与仍然未验证的部署、回读、外部系统和生产事项？
- 必须人工判断的原因：边界是否清楚、是否容易把计划设计误读为发布批准，属于治理理解风险，不能由确定性断言单独证明。
- 前置条件：已阅读 `docs/production-reconciliation/20260825/deployment-gate.json`、`docs/production-reconciliation/20260825/source-shas.json`、验收合同和当前绑定；不访问远程主机、不读取秘密、不执行部署。
- 验收步骤：
  1. 先阅读验收合同的“Non-goals”“Risks and open decisions”和冻结文档的 claim boundary。
  2. 用自己的话说明本任务可以证明的 source-only 结果，以及至少三项仍需另行证明的发布或生产事项。
  3. 判断合同、中文清单和结构化返回是否明确写出不能宣称部署、release 或 production acceptance。
- 预期观察：人员能准确指出本任务只锁定纯 dry-run planner 的输入、输出、失败边界和保护测试；能指出部署、服务、指针、Nginx、数据库、HTTP、Feishu、真实回读、激活、回滚和人工发布批准均未被本任务证明；不会把红证据当作生产绿证据。
- 是否阻塞发布：否；本项只记录后续发布使用前的边界理解，不阻塞 source-only 设计交付。
- 结果记录规则：将人工说明、观察、结论和签名身份写入新的 `acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/runs/<run-id>/result.md`；不得修改本清单来记录某次执行结果。

## H-02

- 验收问题：生产协调人员能否按验收合同理解 activate 与 rollback 的计划顺序，并明确每一步都是 planned-only 而不是已执行动作？
- 必须人工判断的原因：计划的可读性、顺序理解和执行边界属于人工流程质量，不能仅由 JSON 结构断言证明。
- 前置条件：已阅读验收合同的“Expected outcome”“Normal path”“Invariants”和保护测试路径；不运行生产动作，不访问外部服务。
- 验收步骤：
  1. 从 full Git SHA、release ID/root 和 manifest preflight 开始复述计划顺序。
  2. 指出 expected-current pointer CAS、planned atomic switch、可选 user-systemd、same-round readback、observation 和 rollback 各自的边界。
  3. 说明为什么输出中的 planned-only、空 external_actions 和无命令字段不能作为执行回执。
- 预期观察：人员能完整复述顺序，能识别 stale pointer、缺失 previous release、rollback 不兼容和 identity collision 是阻断条件，能说明任何服务、指针、HTTP 或数据库动作都需要另行授权和独立证据。
- 是否阻塞发布：否；本项是交接可读性记录，不是生产批准。
- 结果记录规则：将人工说明、观察、结论和签名身份写入新的 `acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/runs/<run-id>/result.md`；不得修改本清单来记录某次执行结果。

## H-03

- 验收问题：未来实现负责人能否根据合同和保护测试，明确实现文件、受保护测试、证据位置和不得扩展的权限边界？
- 必须人工判断的原因：交接资料是否会诱导越权，属于文档理解和流程质量，不能仅由机器测试证明。
- 前置条件：已阅读验收合同的“Non-goals”“Protected acceptance tests”“Requirements-test traceability”和当前绑定；不创建或修改保留的生产实现文件。
- 验收步骤：
  1. 指出两个保留的未来实现路径和一个受保护测试路径。
  2. 说明保护测试在冻结基线上的红结果意味着“模块/API 尚不存在”，而不是允许削弱测试。
  3. 说明修改 release ID、path policy、manifest compatibility、CAS、rollback、redaction 或外部动作边界时需要新的验收决定。
- 预期观察：人员能准确识别 `openclaw_app/services/production_reconciliation_planner.py`、`openclaw-tag-router/scripts/plan_production_reconciliation.py`、`openclaw-tag-router/tests/test_production_reconciliation_planner.py` 和证据目录；能说明 source-only contract 不等于实现完成、部署完成或 release acceptance；能指出保护测试不得修改、删除、跳过或削弱。
- 是否阻塞发布：否；本项只为后续实现和发布评审提供清晰交接，不阻塞 source-only 设计交付。
- 结果记录规则：将人工说明、观察、结论和签名身份写入新的 `acceptance/human/2026-W35/2026-08-25-PR-REL-PLANNER/runs/<run-id>/result.md`；不得修改本清单来记录某次执行结果。
