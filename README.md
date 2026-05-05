# SelfMedia Tools

`/home/ubuntu/selfmedia-tools` 是一套自媒体素材处理和爆款分析工具。当前重点支持抖音、小红书链接的字段抽取、素材下载、拆解、爆款雷达、评论选题、账号轮询、素材评分和字段健康诊断。

当前推荐用法是：

1. 飞书多维表格作为主要查看和协作入口。
2. OpenClaw `feishu-media` Bot 作为远程调用入口。
3. 本地 SQLite/JSON/Markdown 作为备份和排错依据。

## 当前状态

- Part1/Part2 已有原始素材下载、字段抽取、拆解、飞书文档/多维表格写入能力。
- Part4-Part9 已实现可运行 CLI，并统一支持飞书写入。
- 四个互动数：`点赞`、`收藏`、`评论`、`分享` 已接入字段来源诊断。
- OpenClaw 已接入 media Bot 固定入口。
- 账号每日轮询 OpenClaw cron 已注册，但默认禁用，等飞书账号监控表和凭证配置好后再启用。

## 目录结构

```text
SelfMedia/
├── Part1/
│   ├── content-flow/                 # 抖音/小红书素材下载、字段抽取、转写、分析
│   └── MP4-extract/                  # 汽水音乐资源提取
├── Part2/
│   └── viral-deconstruct/            # 爆款拆解、再创作、飞书文档/多维表格写入
├── Part4/
│   └── viral-radar/                  # 爆款雷达
├── Part5/
│   └── comment-topic-pool/           # 高赞评论选题池
├── Part6/
│   └── viral-structure-db/           # 爆款结构数据库
├── Part7/
│   └── account-competitor-weekly/    # 账号竞品日报/周报
├── Part8/
│   └── material-quality-score/       # 素材入库质量评分
├── Part9/
│   └── field-health-diagnostics/     # 字段健康诊断
├── common/
│   └── social_runtime.py             # Part4-Part9 共享字段刷新、飞书写入、评分工具
├── tools/
│   ├── selfmedia_openclaw.py         # OpenClaw 统一桥接入口
│   └── selfmedia_openclaw.env.example
├── part3/                            # 抖音/小红书 Cookie 导出和保存
└── README.md
```

## 飞书优先工作流

这套工具默认可以只写本地文件，但正式使用建议开启飞书写入：

```bash
export FEISHU_APP_ID='cli_xxx'
export FEISHU_APP_SECRET='xxx'
export FEISHU_BITABLE_URL='https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx'
export FEISHU_REQUIRED=1
```

`FEISHU_REQUIRED=1` 的含义：如果飞书没有写入成功，命令直接失败。正式跑批建议打开，避免表格没落地但误以为完成。

Part4-Part9 会自动补齐通用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| 模块 | 文本 | Part4/Part5/... |
| 运行时间 | 日期 | 抓取或运行时间 |
| 平台 | 文本 | douyin / xiaohongshu |
| 作品ID | 文本 | 抖音 aweme id 或小红书 note id |
| 参考链接 | 链接 | 原作品链接 |
| 点赞 | 数字 | like_count |
| 收藏 | 数字 | collect_count |
| 评论 | 数字 | comment_count |
| 分享 | 数字 | share_count |
| 总互动 | 数字 | 点赞 + 收藏 + 评论 + 分享 |
| 收藏率 | 数字 | 收藏 / 点赞 |
| 评论率 | 数字 | 评论 / 点赞 |
| 分享率 | 数字 | 分享 / 点赞 |
| 状态 | 文本 | ok / partial / missing |
| 失败原因 | 文本 | 字段缺失、验证码、Cookie、签名等原因 |
| 分数 | 数字 | 模块内评分 |
| 决策 | 文本 | deconstruct / review / skip / ok 等 |
| 摘要 | 文本 | 人可读摘要 |
| 详情JSON | 文本 | 完整原始诊断和业务明细 |
| 报告路径 | 文本 | 本地备份报告路径 |

## 飞书 App 凭证是什么

飞书 App 凭证是自建应用的 API 身份：

```bash
FEISHU_APP_ID='cli_xxx'
FEISHU_APP_SECRET='xxx'
```

它不是多维表格链接，也不是你的个人登录密码。这里的凭证是给 OpenClaw 的 `feishu-media` 媒体 Bot 使用的：media Bot 运行 `/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py` 时，会用这组凭证向飞书开放平台换取 `tenant_access_token`，再读写账号监控表、账号日报表和素材/爆款总表。

不要把这组凭证给 main/daily/social Bot 混用。自媒体素材、账号轮询、Part1-Part9 都统一走 `feishu-media`。

当前代码会优先按这个顺序找凭证：

1. 当前进程环境变量：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`
2. `/home/ubuntu/selfmedia-tools/.env.local`
3. `/home/ubuntu/selfmedia-tools/Part1/content-flow/.env`
4. OpenClaw 配置里的 `channels.feishu.accounts.media.appId/appSecret`

也就是说，如果 OpenClaw 的媒体 Bot 已经能正常收发飞书消息，通常不需要再给 selfmedia 单独创建一个新的飞书应用。脚本会自动复用 media Bot 的 App ID/App Secret。

只有 media Bot 没有配置飞书应用，或者你想把自媒体读写权限和聊天 Bot 隔离时，才需要新建应用。新建方式：

1. 打开飞书开放平台：`https://open.feishu.cn/`
2. 进入开发者后台。
3. 创建一个“企业自建应用”。
4. 在应用的“凭证与基础信息”里复制 `App ID` 和 `App Secret`。
5. 给应用开通多维表格相关权限：读取记录、写入记录、读取字段、创建字段、更新记录。
6. 如果使用 `https://xxx.feishu.cn/wiki/...?...table=tblxxx` 这种知识库里的多维表格链接，还需要知识库节点读取权限。
7. 打开目标多维表格，把这个自建应用添加为协作者，并给编辑权限。
8. 发布或启用应用，让权限生效。

不要把 `FEISHU_APP_SECRET` 发到群里，也不要提交到 Git。

### 给媒体 Bot 配置表格链接

凭证可以直接复用 OpenClaw 的 media Bot，但表格链接仍然需要告诉 selfmedia。推荐写到 selfmedia-tools 的本地环境文件：

```bash
/home/ubuntu/selfmedia-tools/.env.local
```

media Bot 的 selfmedia 入口会自动读取这个文件：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py
```

示例：

```bash
FEISHU_ACCOUNT_MONITOR_URL="https://xxx.feishu.cn/base/bascn_monitor?table=tbl_monitor"
FEISHU_ACCOUNT_REPORT_URL="https://xxx.feishu.cn/base/bascn_report?table=tbl_report"
FEISHU_BITABLE_URL="https://xxx.feishu.cn/base/bascn_common?table=tbl_common"
FEISHU_REQUIRED=1
```

如果不用 OpenClaw media Bot 的已有凭证，也可以在同一个文件里显式覆盖：

```bash
FEISHU_APP_ID="cli_xxx"
FEISHU_APP_SECRET="xxx"
```

也可以用 OpenClaw secret 或系统服务环境变量注入，但不要只在当前 shell 临时 `export` 后就启用 cron；cron 不一定继承当前终端环境。

本仓库已经在 `.gitignore` 里忽略：

```text
.env
.env.local
private/
secrets/
*cookies*.json
*cookie*.txt
```

如果只是在当前终端临时测试，也可以这样跑：

```bash
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part3
```

不含密钥的示例文件：

```bash
/home/ubuntu/selfmedia-tools/tools/selfmedia_openclaw.env.example
```

## FEISHU_BITABLE_URL 是什么

`FEISHU_BITABLE_URL` 是通用飞书多维表格写入地址。Part4-Part9 如果没有指定专门的表，就写入这张表。

示例：

```bash
FEISHU_BITABLE_URL="https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx"
```

也支持知识库里的多维表格链接：

```bash
FEISHU_BITABLE_URL="https://xxx.feishu.cn/wiki/wikixxxx?table=tblxxxx"
```

脚本需要 URL 里能解析到：

- `/base/<app_token>` 或 `/wiki/<wiki_token>`
- `table=tblxxxx`

## FEISHU_ACCOUNT_MONITOR_URL 是什么

`FEISHU_ACCOUNT_MONITOR_URL` 是账号每日轮询的输入表，也就是“账号监控表”。

它由你在飞书里创建，例如：

```bash
FEISHU_ACCOUNT_MONITOR_URL="https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx"
```

这张表负责维护要监控的账号和该账号近期作品链接。脚本每天读取这张表，然后刷新对应作品的四个互动数。

### 账号监控表必填字段

| 字段 | 建议类型 | 示例 | 说明 |
| --- | --- | --- | --- |
| 账号名称 | 文本 | 跑步精英 | 人看的账号名 |
| 平台 | 文本 | douyin | `douyin` 或 `xiaohongshu` |
| 近期作品链接 | 多行文本 | https://v.douyin.com/xxxx/ | 可一格多条链接，换行即可 |
| 启用 | 复选框/文本 | true | 关闭后跳过 |

`近期作品链接` 是当前最稳的轮询方式。抖音/小红书公开搜索、主页批量作品抓取容易受登录、验证码、签名和页面结构影响，所以先用“飞书维护近期作品链接”的方式确保每日轮询稳定。

### 账号监控表可选字段

这些字段脚本会尝试自动创建或更新：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| 最近运行时间 | 日期 | 本账号最近一次轮询时间 |
| 最近状态 | 文本 | ok / partial / missing_urls / error |
| 最近作品数 | 数字 | 本次轮询作品数量 |
| 最近总互动 | 数字 | 本次轮询总互动 |
| 最近错误 | 文本 | 出错原因 |
| 最近日报摘要 | 文本 | 简短摘要 |

## FEISHU_ACCOUNT_REPORT_URL 是什么

`FEISHU_ACCOUNT_REPORT_URL` 是账号每日轮询的输出表，也就是“账号日报表”。

示例：

```bash
FEISHU_ACCOUNT_REPORT_URL="https://xxx.feishu.cn/base/bascnyyyy?table=tblyyyy"
```

如果不配置它，`daily-poll` 会回退写入 `FEISHU_BITABLE_URL`。

建议单独建一张日报表，因为它会每天追加作品记录，字段包括：

- 模块
- 运行时间
- 平台
- 作品ID
- 参考链接
- 点赞
- 收藏
- 评论
- 分享
- 总互动
- 收藏率
- 评论率
- 分享率
- 状态
- 分数
- 决策
- 摘要
- 详情JSON

## 推荐飞书配置

完整 `.env.local` 示例：

```bash
FEISHU_APP_ID="cli_xxx"
FEISHU_APP_SECRET="xxx"

# 通用 Part4-Part9 输出表
FEISHU_BITABLE_URL="https://xxx.feishu.cn/base/bascn_common?table=tbl_common"

# 账号每日轮询输入表
FEISHU_ACCOUNT_MONITOR_URL="https://xxx.feishu.cn/base/bascn_monitor?table=tbl_monitor"

# 账号每日轮询输出表
FEISHU_ACCOUNT_REPORT_URL="https://xxx.feishu.cn/base/bascn_report?table=tbl_report"

FEISHU_REQUIRED=1
```

如果你只想先跑通一张表，可以让三者指向同一张多维表格：

```bash
FEISHU_BITABLE_URL="https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx"
FEISHU_ACCOUNT_MONITOR_URL="https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx"
FEISHU_ACCOUNT_REPORT_URL="https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx"
```

但正式使用更建议拆成：

- `账号监控表`：手动维护账号和近期作品链接。
- `账号日报表`：每天自动追加结果。
- `素材/爆款总表`：Part4-Part9 通用业务输出。

## OpenClaw 调用

OpenClaw media Bot 固定入口：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py
```

查看可用模块：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py list
```

输出包括：

- `part1`：字段刷新/素材入口
- `part2`：拆解/再创作，写飞书文档和多维表格
- `part3`：Cookie 状态检查
- `part4`：爆款雷达
- `part5`：高赞评论选题池
- `part6`：爆款结构数据库
- `part7`：账号竞品周报
- `part8`：素材入库质量评分
- `part9`：字段健康诊断
- `daily-poll`：飞书账号监控表每日轮询

### OpenClaw 跑单个模块

字段刷新：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part1 \
  --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

字段健康诊断：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part9 \
  --require-feishu \
  --urls 'https://v.douyin.com/xxxx/'
```

素材质量评分：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part8 \
  --require-feishu \
  --urls 'https://v.douyin.com/xxxx/'
```

Part2 拆解必须显式带 `【拆解】`：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part2 \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

如果只写本地、不写飞书：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part2 \
  --no-write \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

### OpenClaw 每日账号轮询

手动跑一次：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll --require-feishu
```

限制只跑前 N 个账号，适合测试：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll --limit 1 --require-feishu
```

只做本地测试，不写飞书：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll --dry-run
```

## OpenClaw cron 定时任务

已注册任务：

```text
id: c115fa3a-6a8f-466a-89e0-44854eddf838
name: selfmedia-account-daily-poll
agent: feishu-media
schedule: 每天 08:00 Asia/Shanghai
enabled: false
```

当前默认禁用，因为没有确认真实飞书表 URL 和凭证已经配置好。

查看任务：

```bash
openclaw cron show c115fa3a-6a8f-466a-89e0-44854eddf838 --json
```

配置好飞书环境后启用：

```bash
openclaw cron enable c115fa3a-6a8f-466a-89e0-44854eddf838
```

立即手动跑一次：

```bash
openclaw cron run c115fa3a-6a8f-466a-89e0-44854eddf838
```

禁用：

```bash
openclaw cron disable c115fa3a-6a8f-466a-89e0-44854eddf838
```

如果要重新注册：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py install-cron --disabled
```

或者指定表链接：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py install-cron \
  --monitor-url 'https://xxx.feishu.cn/base/bascn_monitor?table=tbl_monitor' \
  --report-url 'https://xxx.feishu.cn/base/bascn_report?table=tbl_report' \
  --disabled
```

## 账号每日轮询如何工作

每日轮询流程：

1. 读取 `FEISHU_ACCOUNT_MONITOR_URL` 指向的账号监控表。
2. 跳过 `启用=false` 的账号。
3. 从 `近期作品链接` 提取抖音/小红书作品链接。
4. 调用 Part1 字段刷新能力拿到四个互动数。
5. 更新账号监控表中的最近状态、最近运行时间、最近作品数、最近总互动、最近错误。
6. 把每条作品写入 `FEISHU_ACCOUNT_REPORT_URL`。
7. 同时在本地 Part7 `outputs/` 保存 JSON/Markdown 备份。

当前轮询逻辑不做“自动搜索新账号”。原因是抖音/小红书搜索和主页批量抓取稳定性受验证码、Cookie、接口签名影响较大。当前最稳路线是：

- 人在飞书账号监控表维护账号和近期作品链接。
- OpenClaw 每天稳定刷新这些链接。
- 后续再加“关键词/话题发现新账号”作为候选账号池，不影响已知账号每日轮询。

## 直接运行 Part4-Part9

如果不用 OpenClaw，也可以进入各目录直接跑。

### Part4 爆款雷达

```bash
cd /home/ubuntu/selfmedia-tools/Part4/viral-radar
python3 cli.py --require-feishu --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

### Part5 高赞评论选题池

```bash
cd /home/ubuntu/selfmedia-tools/Part5/comment-topic-pool
python3 cli.py --require-feishu --urls 'https://v.douyin.com/xxxx/'
```

### Part6 爆款结构数据库

```bash
cd /home/ubuntu/selfmedia-tools/Part6/viral-structure-db
python3 cli.py --require-feishu --urls 'https://v.douyin.com/xxxx/'
```

也可以导入 Part2 输出：

```bash
python3 cli.py --json-input /path/to/deconstruct.json
```

### Part7 账号竞品周报

```bash
cd /home/ubuntu/selfmedia-tools/Part7/account-competitor-weekly
python3 cli.py --require-feishu --account '竞品账号' --urls 'https://v.douyin.com/xxxx/'
```

### Part8 素材入库质量评分

```bash
cd /home/ubuntu/selfmedia-tools/Part8/material-quality-score
python3 cli.py --require-feishu --urls 'https://v.douyin.com/xxxx/'
```

### Part9 字段健康诊断

```bash
cd /home/ubuntu/selfmedia-tools/Part9/field-health-diagnostics
python3 cli.py --require-feishu --urls 'https://v.douyin.com/xxxx/'
```

## Part1 content-flow

能力概览：

- 支持抖音、小红书分享链接。
- 下载视频、图文素材、封面、文案。
- 提取点赞、收藏、评论、分享。
- 可选接入 DashScope 做音频转写。
- 可选接入 Gemini 做内容分析。
- 可选写入 Notion 数据库。
- 提供本地 Web UI。

快速启动：

```bash
cd /home/ubuntu/selfmedia-tools/Part1/content-flow
cp .env.example .env
uv sync
./run.sh
```

如果只想通过 OpenClaw 或命令行刷新字段，优先用：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part1 --urls 'https://v.douyin.com/xxxx/'
```

## Part2 viral-deconstruct

能力概览：

- `【拆解】`：下载原素材，基于真实视频/图文证据拆解，创建飞书拆解文档，写入多维表格摘要。
- `【拆解】【再创作】`：先拆解，再基于拆解结果创建再创作文档。
- 只有显式带 `【拆解】` 才会执行分镜/图文脚本拆解。
- 仅 `【再创作】` 不会直接执行，必须先拆解或提供已有拆解结果。

OpenClaw 调用：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part2 \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

直接调用：

```bash
cd /home/ubuntu/selfmedia-tools/Part2/viral-deconstruct
.venv/bin/python -m src.cli '【拆解】 https://v.douyin.com/xxxx/'
```

## part3 Cookie

Part3 用于导出并保存抖音/小红书 Cookie 到本地未提交文件。

查看 Cookie 状态：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part3
```

自动导出：

```bash
cd /home/ubuntu/selfmedia-tools/part3
./run_export.sh --save-secrets
```

Cookie 文件默认不提交 Git：

```text
Part1/content-flow/private/douyin-cookies.json
Part1/content-flow/private/xiaohongshu-cookies.json
part3/private/
part3/secrets/
```

## 字段健康诊断

Part9 会记录每个互动字段的来源：

```text
like_count
collect_count
comment_count
share_count
```

常见来源：

- `xhs.interactInfo.likedCount`
- `xhs.interactInfo.collectedCount`
- `xhs.interactInfo.commentCount`
- `xhs.interactInfo.shareCount`
- `douyin_share_html.statistics.digg_count`
- `douyin_share_html.statistics.collect_count`
- `douyin_share_html.statistics.comment_count`
- `douyin_share_html.statistics.share_count`

如果字段拿不到，会记录失败原因，例如：

- Cookie 缺失或过期
- 验证码
- 登录要求
- 接口签名变化
- 页面结构变化
- 链接失效或权限不可见

## 常见问题

### 1. 飞书写入失败：缺少 FEISHU_APP_ID / FEISHU_APP_SECRET

说明脚本没有读到飞书自建应用凭证。

检查：

```bash
env | rg '^FEISHU_'
```

如果没有，写入：

```bash
/home/ubuntu/selfmedia-tools/.env.local
```

### 2. 飞书写入失败：没有权限

检查：

- 自建应用是否已启用。
- 应用是否有多维表格读写权限。
- 应用是否被添加为目标多维表格协作者。
- 表格链接是否包含 `table=tblxxxx`。
- 如果是知识库链接，应用是否有 wiki 节点读取权限。

### 3. daily-poll 提示 missing FEISHU_ACCOUNT_MONITOR_URL

说明没有配置账号监控表链接。

设置：

```bash
FEISHU_ACCOUNT_MONITOR_URL="https://xxx.feishu.cn/base/bascnxxxx?table=tblxxxx"
```

### 4. 账号每日轮询没有作品

检查账号监控表：

- `启用` 是否为 true。
- `近期作品链接` 是否有完整抖音/小红书分享链接。
- 链接是否已经失效。

### 5. 抖音/小红书字段偶发缺失

优先跑字段诊断：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part9 --urls 'https://v.douyin.com/xxxx/'
```

看 `详情JSON` 里的 `stats_sources`、`missing_interaction_fields` 和 `failure_reason`。

### 6. 不想强制写飞书

不要设置 `FEISHU_REQUIRED=1`，也不要加 `--require-feishu`。

命令会继续写本地 SQLite/JSON/Markdown。

## 验证命令

编译检查：

```bash
cd /home/ubuntu/selfmedia-tools
python3 -m py_compile common/social_runtime.py tools/selfmedia_openclaw.py
```

Part1 测试：

```bash
cd /home/ubuntu/selfmedia-tools/Part1/content-flow
python3 -m unittest discover -s tests
```

Part2 测试：

```bash
cd /home/ubuntu/selfmedia-tools/Part2/viral-deconstruct
.venv/bin/python -m pytest -q
```

OpenClaw wrapper smoke test：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py list
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run part3
```

## 发布到 GitHub 前注意

- 不要提交 `.env`、`.env.local`。
- 不要提交 Cookie。
- 不要提交下载媒体文件。
- 不要提交 Part4-Part9 的 `data/` 和 `outputs/`。
- 如果后续公开发布，建议补开源许可证。
