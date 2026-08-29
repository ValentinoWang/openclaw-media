# H00 账号监控安装问题说明

日期：2026-08-29

## 结论

本次现象包含两个相互独立的问题，均已定位：

1. 飞书授权页面显示“飞书 CLI、AthleteOS、AI4Math 都无权限”，原因是本机默认使用了错误的 CLI 应用 profile，而不是生产环境绑定 Base 的应用。切换到生产应用 profile 后，主 Base 可正常读取和写入。
2. 第一次远端安装命令失败，原因是本地通过多层 shell/SSH 转发 heredoc 时换行被转成字面量 `\\n`，远端 Bash 将 `PYnfrom` 当作语法内容解析。命令在修改 unit 之前就退出，服务器文件没有被破坏。

## 权限问题

当时本机默认 profile 为 `cli_a941e7f86e399bd7`（“飞书 CLI”）。该应用的 bot 身份访问目标 Base 返回 `91403 you don't have permission`；其 user refresh token 也已过期。浏览器授权页展示的是当前登录用户可用的应用列表，因此 AthleteOS 和 AI4Math 显示“无权限”并不表示 Base 被删除，也不表示当前用户没有登录。

远端 release 使用的应用 ID 对应本机已有 profile `cli_a968263ac6f89bcb`（profile 名 `a1-main-bot`）。切换后读取主 Base 成功，确认共有 18 张表，并确认原先不存在 `H00_账号监控`。

## 表结构处理

在 Base `OmjkbgBkwa2JEysEN8uc5PMhnTb` 中创建：

- 表名：`H00_账号监控`
- Table ID：`tblc65xqnUjSw9Ah`
- 字段：账号名称、平台、近期作品链接、启用、最近运行时间、最近状态、最近作品数、最近总互动、最近错误、最近日报摘要

字段已通过 `lark-cli base +field-list` 回读，类型与 `runtime/cli/selfmedia.py` 的 `ACCOUNT_MONITOR_FIELD_SPECS` 一致。没有写入账号记录，也没有用主页链接冒充近期作品链接。

## 远端安装问题

第一次安装尝试使用内嵌 Python heredoc 修改 systemd unit。由于命令经过本地 shell、SSH 远端 shell 和 JSON 参数三层解析，heredoc 的真实换行被保留成字符序列 `\\n`，导致远端收到的内容类似 `PYnfrom pathlib import Path`，Bash 在执行 Python 前就报语法错误。

该失败属于执行器命令构造错误，不是服务器网络、systemd、Python 或飞书 API 故障。随后改用单行 `sed` 精确替换旧表 ID，成功完成修改。

## 当前实际状态

远端 `106.52.146.37`：

- service 的 `--monitor-url` 已指向 `tblc65xqnUjSw9Ah`
- `selfmedia-account-daily-poll.timer`：`enabled`、`active`
- 手动启动 service：`Result=success`、`ExecMainStatus=0`
- journal 已生成租户隔离产物：
  `/home/ubuntu/.openclaw/media_vault/tenants/618ff8c4-cc5a-4034-a2c5-226e3ad6cd37/account_daily_runs/account_daily_20260829100329.json`
  和同名 Markdown 报告
- 本次运行：`account_count=0`、`polled_account_count=0`、`errors=[]`

## 尚未关闭的验收缺口

安装和空表轮询已经通过，但 `BIZ-05`、`CD-13` 仍不能标记为完全验收。原因是 H00 表目前没有真实账号记录，也没有真实近期作品链接；空表运行只能证明调度、租户隔离和产物写入链路，不能证明账号抓取、指标更新和日报回写。

下一步必须由业务侧在 H00 表中填入真实账号及近期作品链接，并将对应记录设为“启用”，再执行一次生产轮询，核对：账号记录更新、日报写入、`account_daily_runs` 租户目录产物和 service journal。禁止使用主页链接、素材源或猜测 URL 代替真实作品链接。

## 相关证据

- P1 进度投影：`agents-results/2026-08-29/media-p1-remaining-development-paths/implementation-progress.md`
- H00 Base：`https://tcnwueberajc.feishu.cn/base/OmjkbgBkwa2JEysEN8uc5PMhnTb?table=tblc65xqnUjSw9Ah`
- 代码合同：`runtime/cli/selfmedia.py`
