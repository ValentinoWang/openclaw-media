# C1 基础实现主线程接管证据

- 观察时间：2026-08-13（Asia/Shanghai）
- 远程主机：`106.52.146.37`
- 活动源：`/home/ubuntu/openclaw-bot-center`
- 隔离候选：`/home/ubuntu/worktrees/media-production-e2e-c1-op02-v2`
- 证据等级：源码与静态测试
- 结论：基础实现已验证；C1 正式节点仍为阻塞，未完成生产认证浏览器验收。

## 外部执行终态

外部 Luna 与唯一一次 L3 升级均因超时退出，且均未写出结构化返回。监督台账终态为 `BLOCKED/STOP`，因此主线程按合同接管，没有再次启动外部执行。

台账：`ledger/C1-FOUNDATION.json`

## 主线程发现与修复

主线程审查确认原隔离候选具有以下正确基础：

1. 明确拒绝自动挑选历史账号、同一身份承担两种角色以及跨租户拼接。
2. 只允许在声明为隔离质量验收的数据库中创建临时身份与会话。
3. 同一数据库事务提交后，才把临时身份和会话登记为本次已创建对象；事务内失败会回滚。
4. 页面子命令任意失败后仍进入 `finally`，删除已提交的两条会话及六条临时身份相关记录。
5. 收据只保存租户和身份的稳定摘要引用，不保存密码、Cookie、令牌、会话令牌或私人正文。

主线程另外修复了两个汇合前缺陷：

1. 候选 runner 不再要求自身文件等于旧活动版本哈希。它仍记录自身候选哈希，同时继续锁定页面脚本和项目规则文件，避免候选发布后自我拒绝。
2. 成功和失败收据现在必须显式包含整体结果；页面失败或清理失败不能形成看似成功的收据。

同时收紧运行编号，只接受安全的 ASCII 标识字符，避免运行编号被用来扩展证据目录或用户名边界。

## 数据库结构核对

- `openclaw_account.tenant_members` 允许一个租户拥有普通成员与唯一活动所有者。
- `openclaw_account.sessions` 的当前外键指向 `(tenant_id, user_id)` 成员关系，因此同一租户中的普通用户和管理员均可拥有独立会话。
- 临时 fixture 共六条业务记录：两条用户、一条租户、两条成员关系和一条钱包账户；清理计数与 SQL 删除顺序一致。
- 会话和 fixture 仅在事务提交后进入清理登记；提交前错误不会产生遗漏的已提交记录。

## 验证结果

```text
python3 -m py_compile production-qa/run_media_role_qa.py \
  production-qa/media_role_qa_foundation.py \
  production-qa/test_media_role_qa.py
exit 0

python3 -m unittest discover -s production-qa -p test_media_role_qa.py
Ran 11 tests
OK
```

隔离候选哈希：

| 文件 | SHA-256 |
| --- | --- |
| `production-qa/run_media_role_qa.py` | `88c820af8a1115efd64843fc9879411fc634d946b2a12f4267c4e4af7e114f06` |
| `production-qa/media_role_qa_foundation.py` | `0059bb7927ab02331cd9ad6b13755f5f443970570c720daad40633048c572b6e` |
| `production-qa/test_media_role_qa.py` | `0f950ff090a3679693446402288170c566ed856535c0f6ea2f9c6d938ce140df` |

活动四文件保持不变：

| 文件 | SHA-256 |
| --- | --- |
| `production-qa/run_media_role_qa.py` | `b684351bf639659ceb6b144f3ddf9d44a5d4c3efd654c6665a6568a4612f2b63` |
| `scripts/qa/captureMediaRolePages.ts` | `96be1d153e395f93bf879b9dcb2975e6ef63f8dec4573bb2d145c1b823126153` |
| `scripts/qa/checkMediaWebChannel.ts` | `de6165bbeb827b343b3a2dea7b71009c734e6c6b690a7f49b18dbd3c367b44b7` |
| `AGENTS.md` | `2c1626033f500a00417a8276081264f7e1d46d975590d2f840b62d904debe92b` |

本轮由远端补丁工具产生的 C1 `.orig` 与 `.rej` 文件已经精确删除；没有清理隔离副本中从活动源继承的其他历史文件。

## 尚未验证

1. 当前有效、同一生产质量验收租户内相互分离的普通用户与管理员身份。
2. 当次生产认证会话、角色和租户读回。
3. 桌面与移动浏览器的页面状态矩阵、控制台错误和横向溢出。
4. 会话过期后的重试、幂等与业务写入计数。
5. 绑定当前生产发布的安全负责人脱敏收据及人工验收结果。

因此，本证据最多支持 C1 基础实现为“已验证”，不能支持 C1、DB 或整体目标为“已接受”。
