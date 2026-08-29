# T1-AUTH-ROUTES 合同批准记录

- 批准角色：main-orchestrator
- 批准时间：2026-08-16T23:09:46+08:00
- 合同版本：1
- 决定：批准行为合同；测试基线继续保持 `PLANNED`
- 决定依据：`media.stage1.stable-decisions@2`、`media.stage1.decision.personal-auth-contract@1`、SSOT 节点 `T1`
- T1 候选门禁：`test_stage1_acceptance_harness.py` 共 7 项通过
- 跨根状态：`check_stage1_auth_route_alignment.py --expect-red` 返回 `STAGE1_AUTH_ROUTE_ALIGNMENT=EXPECTED_RED`
- 批准的测试变更：`TCR-T1-ROUTE-CARRIER`、`TCR-I2-PUBLIC-AUTH-ROUTES`
- 用户授权来源：用户要求按本 SSOT 完成 100% 代码开发并连续要求继续；据此批准验收合同和清单内容，不代表人工清单已经执行

批准范围是十个唯一公开认证/会话操作、硬切换别名边界、登录与重置字段、小写蛇形错误码、登录前 CSRF 例外和退出 CSRF 要求。批准不等于测试已锁定、产品已实现、发布已验收或真实邮件/飞书已经验证。
