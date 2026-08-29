# C5 唯一候选第 2 次汇合

- 任务：`C5-UNIQUE-CANDIDATE-R2`
- 候选 schema：`openclaw-media-unique-candidate-v1`
- 候选编号：`media-production-e2e-v4`
- 候选总清单：`.codex-work/merge-candidate-v4/candidate-manifest.json`
- 候选总清单 SHA-256：`ef8bfb2f251b99bc0b4c262e3e82ecd9a4a4ca0406408b94b5dedae6db7072bc`
- 候选校验文件：`.codex-work/merge-candidate-v4/candidate-manifest.sha256`

## 组件清单

- 前端：`.codex-work/merge-candidate-v4/frontend/.candidate-source.sha256`，200 项，SHA-256 `e4b35df091184f2d51be0c5ccb675223ddc7b6fb1df6ebf366956c1ac9619580`
- 后端：`.codex-work/merge-candidate-v4/backend/.candidate-source.sha256`，605 项，SHA-256 `80612a3bd5742de73eff2ee1e5fc6b1793ab3cfd071b58e3c3de229effdaa2e6`
- 后端来源：第 21 波 `current-candidate-source.sha256`，已字节复制到当前候选。

## 合同和证据

- 素材解析合同：`media-material-parsing-coverage-v1`，SHA-256 `24452e8b621fa3a797b7efba6c03a48aad86f3436193fbef38794bcf4de54f56`，54 个组合，生产验收为 `false`。
- 第 17 波结果 SHA-256：`27cfc24b13d7618127996a72f57c38608f4a0df2a32f213104823b6c97021dbf`。
- 第 17 波验证脚本 SHA-256：`fc2bec23ab69da35d18e269bb4cd1a0236eb3929c33c943ee4bff4e6da02de8b`。
- 第 21 波结果 SHA-256：`7f13ec0caef574073bf9ce907a503171be25fccf66bf7c2fbedc7dc4073cbc3b`。
- 第 21 波完整验证日志 SHA-256：`bc5f878b45b1b7f08050715470b823f840732d33a63efd593c8a6ab1f79cdbb8`。
- 第 21 波非数据库结果：`86 passed, 16 skipped`；正式迁移 `33` 条；PostgreSQL `27 passed`；生产收据门禁退出码 `3`；`production_accepted: false`。

## 冻结验证

- 五版本元组：计划 `5`、依赖图 `5`、接口冻结 `5`、节点合同 `4`、SSOT schema `1`。
- SSOT manifest、C3、C4、C5 节点及 C3→C5、C4→C5、C5→C1 边均与冻结 SHA-256 一致；C3/C4 为 `ACCEPTED`，C5 为正式 `READY`、尝试 `2`。
- 前端 200 项和后端 605 项均已独立按冻结排除规则重建并字节比较；受管文件无符号链接或非受管临时文件；合同副本字节一致。
- 发布协调身份保留为前端 `20260814T084319Z-media-login-canonical`，后端 `openclaw-tag-router-media-tenant-20260814T062408Z-opc-feishu-login`。

## 边界

- 未部署、未触碰远程、未生产验收。
- 未修改业务源码、测试、迁移、合同、SSOT 机器源、生成视图、保护测试、第 18 波或第 21 波证据。
- 未写入凭据、真实身份、Cookie、令牌、密码、私人正文或生产数据；未启动其他执行者或长期后台进程。
- C5 未自行标记为 `ACCEPTED`，C1 未解锁。
