# B1-V2-LOCK 有界任务

## 身份与目标

- 任务编号：`B1-V2-LOCK`
- 直接父节点：B1（`media.authenticated-web-completeness-contract`）
- 版本元组：计划 4、依赖图 4、接口冻结 4、节点合同 3、SSOT schema 1
- 已接受决定：`media.no-inference-completion-boundary@1`、`media.qa-identity@1`
- 失效键：`contract.authenticated-web`、`decision.qa-identity`
- 目标：把 `MPE2E-AUTH-WEB` 重锁为第 2 版正式合同，覆盖现行飞书扫码登录、账号密码登录、飞书账号关联和租户角色会话；同时把本地候选认证验证与生产 QA 验收分层。真实 QA 身份和生产浏览器证据继续由 DB 负责，不得提前阻塞 C3、C4、C5 或 C1。

## 冻结输入

- `.ssot/manifest.json` SHA-256：`e6ac97c7864162751ab8ec1df73b0c5f9cd425b3ac746c550d89bba6382673c3`。
- `.ssot/nodes/B1.json` SHA-256：`7ff91b1f3cc446c368074f31b3aa8a1f1749eed5efbdf975df4521a747d4d1f3`，必须保持 B1 为 `READY`、`FORMAL`，合同目标版本为 2。
- `.ssot/nodes/D1.json` SHA-256：`8fafa1208ead99395489353de9bc32560a6b82863bb9028fda670fc3526a9997`。
- `.ssot/nodes/D3.json` SHA-256：`a53cbc80ea0b2010643e20194f2dc115e42b007014e356787e1ede9fa7cb2c47`。
- `openproblem.md` SHA-256：`f708e01fd4b0e0320ed0eb5c23b8c27f5348eaac4fce82841c21cbb8e94072ae`。
- 当前生产前端源码清单文件 SHA-256：`7e27523e6fbb3f5297a15917672ad03082e3c7b919cb99fccf9cba738bc80f14`。
- 当前生产后端清单文件 SHA-256：`bca0dac2e657d0d1fd939c87645ad278fb6e9a049ac18429c11e714b5684e49b`。
- 第 1 版合同 SHA-256：`cbd1f717653724ca862639f85f98cb82d254383d8b1b9db59b6287cf1c2d7b54`。
- 第 1 版中文清单 SHA-256：`8ed5abe505a6c7fe45c3566294e1ee77e197a7a5272e84d4815fd7d4ec24995c`。
- 第 1 版绑定 SHA-256：`1790949dacd23d60434c6f4c8ae28ece11f1c99ce87b0eff74c3beaa3d5cd1c4`。
- 第 1 版保护测试 SHA-256：`b52c61bbeaf71ad3db874a5493479d8d0d0ae5a53362cadc2ebe67cc1976c204`。
- 第 1 版四项资产是失效历史起点，可以在原路径升级到第 2 版；不得另建并行认证合同或保留运行时双轨事实来源。

## 唯一允许写入

- `agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/**`
- `acceptance/human/MPE2E-AUTH-WEB/checklist.md`
- `acceptance/human/MPE2E-AUTH-WEB/binding.md`
- `scripts/acceptance/test-mpe2e-auth-web.sh`
- 生成式索引 `acceptance/index.md`
- supervisor 指定的唯一结构化返回文件

## 禁止写入与副作用

- 不得写入 `.ssot/**`、`ssot-development-paths.md`、`openproblem.md`、`implementation-progress.md` 或任何视图源；正式节点迁移由主编排负责。
- 不得修改 `.codex-work/production-baseline-20260814T084319Z/**`、C2 候选、前后端源码、既有业务测试、远程主机、数据库、飞书、账号、活动发布、生产收据或人工运行结果。
- 不得创建认证兼容层、旧发布回退、默认身份、跨租户查找、弱化门禁或第二份活动合同。
- 不得保存或输出密码、Cookie、令牌、密钥、飞书授权码、私人正文或环境变量内容。
- 不得启动子代理、聊天内协作或其他 Codex worker。

## 必须完成的第 2 版语义

1. 合同任务编号保持 `MPE2E-AUTH-WEB`，合同版本改为 2，状态为 `APPROVED`，测试基线为 `LOCKED`，就绪模式为 `FORMAL`，活动假设为 `none`。批准证据引用用户已采纳 OP01 推荐方案、D1 v1、D3 v1 和当前 OP 的批准记录；不得把认证架构变化伪装成新的产品决定。
2. 基线身份必须引用当前生产前端 `20260814T084319Z-media-login-canonical`、当前生产后端 `20260814T062408Z-opc-feishu-login` 及其本地只读清单，不再绑定已失效的 B4 发布。
3. 飞书扫码登录和账号密码登录是并存的一等登录方式。两者成功后必须进入同一个规范会话契约，返回并读回同一组用户、租户、角色、维护权限、会话到期和防跨站请求字段；任何一条不得成为另一条的隐式回退。
4. 飞书扫码必须绑定一次短时登录尝试和浏览器绑定值；授权地址只允许受信飞书 HTTPS 主机；过期、重放、绑定不匹配、跨尝试或状态未知必须失败关闭，不能创建会话。
5. 飞书身份只有在验证信息精确关联到一个有效内部账号、一个有效租户成员关系和明确角色后才能发放会话。未关联、关联不唯一、用户停用、租户停用、跨租户或角色不一致必须失败关闭，且不能泄露其他租户是否存在。
6. 账号密码登录保持现有统一错误边界；成功后也必须经过有效用户、有效租户和角色校验。会话过期、撤销、密码变更、用户停用或租户停用后必须立即失效。
7. 普通用户、管理员和维护权限必须按租户会话读回并在路由侧执行。跨租户访问、管理员能力不足、普通用户访问管理员入口、缺少防跨站请求证明或会话无效时必须拒绝，页面存在和 HTTP 200 不能替代权限成功。
8. 验收证据分为两个明确层次：
   - `local-candidate`：C1 在唯一候选上使用本地受控身份或 fixture/mocked external auth，验证两种登录、关联、角色、失败关闭、退出、过期、恢复、桌面和移动布局；必须标记非生产、非真实 QA，不能据此声明生产完成。
   - `production`：DB 在当前实际发布上使用独立 QA 租户中两个真实且隔离的身份，取得当次桌面和移动浏览器、角色隔离、会话恢复、发布读回和同运行证据；缺少真实 QA 身份时只阻塞 DB。
9. 保护测试仍使用 `scripts/acceptance/test-mpe2e-auth-web.sh`，通过 `MPE2E_AUTH_WEB_MODE=local-candidate|production` 和绝对 JSON 定位读取脱敏收据。测试不得联网、登录或打印收据；两种模式都要校验合同版本 2、来源修订、候选或发布身份、两种登录方式、飞书关联、租户角色会话、失败关闭、双视口和敏感信息卫生。
10. `local-candidate` 收据必须明确 `mock_or_fixture`，并证明未把本地证据提升为生产；`production` 收据必须拒绝 fixture/mock，要求实际活动发布、两个真实 QA 身份和当次浏览器证据。测试缺少收据时保留稳定的失败关闭红灯。
11. 中文人工清单升级为第 2 版，只记录产品负责人或安全负责人必须人工判断的登录方式可理解性、飞书关联失败提示、角色隔离、恢复路径及生产证据卫生；不得填写某次运行结果。
12. 用 `manage_acceptance_artifacts.py bind-human --replace` 刷新绑定，生成并校验任务索引和项目人工索引。合同中的保护测试 SHA-256 必须等于升级后脚本的真实 SHA-256。

## 验收与停止条件

- 运行预冻结验收命令；合同、绑定、索引、清单、基线不变、双层证据、保护测试字段和缺收据红灯断言必须全部通过。
- 可提议 `VERIFIED`，不得自行标记 B1 为 `ACCEPTED`。
- 如果发现当前认证源码与 OP/D1/D3 存在不可在本合同范围内消解的权威冲突，返回 `BLOCKED`；使用闭集中的准确 `failure_class`，不得扩大写区。

## 结构化返回

结构化返回必须包含：任务编号、attempt role、版本元组、包装器路径、进程/会话身份、实际读写范围、命令与退出码、第 2 版合同/清单/绑定/保护测试哈希、冻结输入不变证明、缺收据红灯证据、禁止范围不变、未验证事项、共享资源影响、风险、偏差、`failure_class`、`acceptance_self_check` 和 proposed state。
