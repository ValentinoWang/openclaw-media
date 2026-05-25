# SelfMedia Tools

`/home/ubuntu/selfmedia-tools` 是一套自媒体素材处理和爆款分析工具，重点服务抖音、小红书内容流。

它不是单个下载器，而是一条工作流：

```text
链接/账号样本
  -> 字段抽取
  -> 素材下载
  -> 拆解/评论/结构/评分
  -> 飞书多维表格查看
  -> OpenClaw media Bot 调用和每日轮询
```

当前主入口有两个：

- 本地命令：各 Part 目录下的 `cli.py`
- OpenClaw：`/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py`

## 全局公共组件

跨 Part 复用的能力放在 `common/`。当前稳定公共入口包括：

- `common.content_cleaner.clean_ocr_text()`：图片 OCR 原始文本清洗
- `common.content_cleaner.clean_transcript_text()`：视频/音频转写文本清洗
- `common.content_cleaner.clean_collected_text()`：普通采集正文清洗
- `common.content_cleaner.clean_text_by_source()`：按来源自动分发清洗

命令行也可以直接调用：

```bash
python3 /home/ubuntu/selfmedia-tools/common/content_cleaner_cli.py \
  --source ocr \
  --title '素材标题' \
  --input raw_ocr.txt \
  --output cleaned.txt
```

LLM 配置只走 `common/llm_settings.py` 中定义的统一命名空间。主模型和内容清洗共用：
`SELFMEDIA_CLEAN_LLM_API_KEY`、`SELFMEDIA_CLEAN_LLM_BASE_URL`、`SELFMEDIA_CLEAN_LLM_MODEL`、
`SELFMEDIA_CLEAN_LLM_API_TYPE`、`SELFMEDIA_CLEAN_LLM_TIMEOUT`；内容清洗额外使用
`SELFMEDIA_CLEAN_LLM_MAX_CHARS`。

## 各模块是做什么的

| 模块 | 目录 | 主要职责 | 输入 | 主要输出 | 飞书定位 |
| --- | --- | --- | --- | --- | --- |
| 01 内容采集 | `01-ingest-content-flow` | 抖音/小红书素材下载和基础字段抽取 | 单条或多条作品链接 | 视频/图片/封面/文案/四个互动数/评论 | 给后续模块提供原始素材和字段 |
| 02 音乐资源提取 | `02-extract-music-media` | 汽水音乐分享资源提取 | 汽水音乐链接或 curl 文本 | 音视频资源、本地 Web UI | 独立小工具 |
| 03 爆款拆解 | `03-deconstruct-viral-content` | 爆款拆解和创作-再创 | 带 `【拆解】` 的作品链接 | 飞书拆解文档、创作-再创文档、多维表格摘要 | 形成可复用创作样本 |
| 04 平台 Cookie 管理 | `04-manage-platform-cookies` | 抖音/小红书 Cookie 导出和保存 | 已登录浏览器或手动导出的 Cookie | 本地未提交 Cookie 文件 | 提高字段和素材抓取稳定性 |
| 05 爆款雷达 | `05-detect-viral-radar` | 爆款雷达 | 一批作品链接 | 起量信号、互动增速、候选爆款 | 爆款雷达表 |
| 06 评论选题池 | `06-mine-comment-topics` | 高赞评论选题池 | 作品链接 | 高赞评论、痛点/争议/需求选题卡 | 评论选题池 |
| 07 爆款结构库 | `07-index-viral-structures` | 爆款结构数据库 | 作品链接或 03 爆款拆解 JSON | 标题、开头、封面、话题、互动率、结构标签 | 爆款结构库 |
| 08 账号竞品报告 | `08-report-account-competitors` | 账号竞品日报/周报 | 账号名和近期作品链接 | 账号表现、爆款、互动变化 | 账号日报/周报 |
| 09 素材质量评分 | `09-score-material-quality` | 素材入库质量评分 | 作品链接 | 字段完整度、互动质量、复刻价值、决策 | 素材筛选表 |
| 10 字段健康诊断 | `10-diagnose-field-health` | 字段健康诊断 | 作品链接 | 每个字段来源、失败原因、缺失字段 | 字段健康表 |
| 素材创作 | `tools/material_creation` | 上传素材定位分析和初稿 | 飞书上传视频/图片 + `【素材创作】` | 创作文档、作品档案、账号监控记录 | 创作记录表 / 账号监控表 |
| 媒体上下文 | `tools/media_context` | 账号画像、历史创作、复盘记忆 | `账号=`、创作结果、复盘文本 | 本地账号画像、JSONL 创作/复盘流水 | 下一次创作自动注入 |

## 推荐业务流

### 1. 单条素材快速判断

先看字段是不是能拿全，再决定是否下载或拆解：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run field-health \
  --urls 'https://v.douyin.com/xxxx/'

/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run material-quality \
  --urls 'https://v.douyin.com/xxxx/'
```

用途：

- 10 字段健康诊断 判断点赞、收藏、评论、分享从哪里来。
- 09 素材质量评分 判断素材值不值得拆解。

### 2. 爆款拆解

拆解必须显式写 `【拆解】`：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run deconstruct \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

03 爆款拆解 会先调用 01 内容采集 下载真实原素材，再基于视频帧或图文证据分析。不能只看链接和标题猜。

### 3. 上传素材生成定位分析和初稿

飞书 Media bot 里可以先上传视频或图片附件，再发送 `【素材创作】` 指令：

```text
第1条：上传视频或多张图片
第2条：【素材创作-小红书】类型=图文 账号=主账号 发布时间=今晚8点 用户想法=更真实一点
```

也可以在同一条消息里同时发送附件和指令：

```text
【素材创作-小红书】类型=图文 账号=主账号 发布时间=今晚8点 用户想法=更真实一点
```

用途：

- 从上传视频抽关键帧，或从上传图片/图文素材读取视觉证据。
- 视频前 5 秒按 10fps 高密度采样；5 秒之后按 fps=2 连续采样。
- 图文首图会作为封面/首图重点分析，后续图片按原顺序分析。
- 先输出定位分析，再生成平台化初稿。
- 创建飞书创作文档，并在创作记录表形成作品级档案。
- 如果填写 `账号=`，会在账号监控表建立或更新账号记录，后续补发布链接后可进入数据复盘。

### 4. 建立账号记忆和复盘闭环

`【创作】`、`【素材创作】` 现在会在生成前自动读取本地媒体上下文，生成后写回创作流水和账号画像。只要消息里带 `账号=`，后续同账号创作会自动继承历史定位、创作记录和复盘结论。

从飞书标签入口进入时，tag-router 还会把同一会话/同一用户的最近对话注入到创作链路，避免 `【创作】`、`【素材创作】` 只基于当前这一条消息回答。本地 CLI 调试时可以用两种方式传入同样结构：

```bash
--conversation-context-json '{"loaded_count":1,"prompt":"最近飞书对话上下文：..."}'
OPENCLAW_CONVERSATION_CONTEXT_JSON='{"loaded_count":1,"prompt":"最近飞书对话上下文：..."}'
```

`【创作】` 和 `【素材创作】` 的回复会显示 `对话 N 条`，用于确认它没有只基于当前一条消息生成。

本地存储位置：

```text
/home/ubuntu/selfmedia-tools/data/media_memory/
  accounts/*.json
  creations.jsonl
  reviews.jsonl
```

发布后发 `【复盘】`，如果内容包含平台、账号、发布链接、作品数据或点赞/收藏/评论/播放等指标，tag-router 会先保留通用复盘归档，再额外写入媒体账号记忆：

```text
【复盘】平台=小红书 账号=主账号 主题=表达力 发布链接=https://example.com/note 点赞=1200 收藏=500 评论=80 结论=封面直接写痛点有效，下一条继续保留强痛点首图
```

也可以直接在本机写入或查看：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py review \
  --text '【复盘】平台=小红书 账号=主账号 主题=表达力 点赞=1200 收藏=500 结论=封面直接写痛点有效'

/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py context \
  --platform 小红书 --account 主账号 --topic 表达力
```

推荐以后所有创作请求都带 `账号=`。如果不带账号，系统仍会按平台和主题查近期记录，但不会形成稳定的账号画像。

### 5. 一批链接做爆款雷达

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run viral-radar \
  --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

用途：

- 记录作品互动快照。
- 计算起量信号。
- 输出值得进入 03 爆款拆解 的候选内容。

### 6. 高赞评论做选题池

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run comment-topics \
  --urls 'https://v.douyin.com/xxxx/'
```

用途：

- 抓高赞评论。
- 聚类问题、痛点、需求、争议。
- 给创作-再创提供选题角度。

### 7. 每日账号轮询

在飞书维护“账号监控表”，每天刷新近期作品互动数据：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll
```

用途：

- 读取账号监控表。
- 刷新每个账号近期作品的点赞、收藏、评论、分享。
- 更新账号监控表的最近状态。
- 写入账号日报表。

## OpenClaw media Bot 入口

统一入口：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py
```

查看可调用模块：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py list
```

常用命令：

```bash
# Cookie 状态
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run cookies

# 字段刷新
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run ingest --urls 'https://v.douyin.com/xxxx/'

# 字段健康诊断
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run field-health --urls 'https://v.douyin.com/xxxx/'

# 素材质量评分
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run material-quality --urls 'https://v.douyin.com/xxxx/'

# 账号每日轮询
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll

# 写入一次媒体复盘
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py review \
  --text '【复盘】平台=小红书 账号=主账号 主题=表达力 点赞=1200 收藏=500 结论=封面痛点有效'

# 查看下一次创作会加载哪些账号上下文
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py context \
  --platform 小红书 --account 主账号 --topic 表达力
```

## 飞书怎么接

当前方案默认复用 OpenClaw 的 `feishu-media` 媒体 Bot 信息。

也就是说，一般不需要再在 README 里让你手动填：

```bash
FEISHU_APP_ID
FEISHU_APP_SECRET
```

代码会自动读取：

```text
/home/ubuntu/.openclaw/openclaw.json
channels.feishu.accounts.media.appId
channels.feishu.accounts.media.appSecret
```

你真正需要告诉 selfmedia 的，是写到哪些飞书表。

建议写到：

```bash
/home/ubuntu/selfmedia-tools/.env.local
```

最小配置：

```bash
# 05 爆款雷达-10 字段健康诊断 通用输出表
FEISHU_BITABLE_URL="https://xxx.feishu.cn/base/bascn_common?table=tbl_common"

# 账号每日轮询输入表
FEISHU_ACCOUNT_MONITOR_URL="https://xxx.feishu.cn/base/bascn_monitor?table=tbl_monitor"

# 账号每日轮询输出表
FEISHU_ACCOUNT_REPORT_URL="https://xxx.feishu.cn/base/bascn_report?table=tbl_report"

# 正式跑批建议打开；飞书没写进去就失败
FEISHU_REQUIRED=1
```

如果你想覆盖 media Bot 的飞书应用，才需要额外写：

```bash
FEISHU_APP_ID="cli_xxx"
FEISHU_APP_SECRET="xxx"
```

不含密钥的示例文件：

```bash
tools/selfmedia_openclaw.env.example
```

## 飞书表怎么建

### 素材/爆款总表

给 05 爆款雷达-10 字段健康诊断 使用，对应：

```bash
FEISHU_BITABLE_URL
```

脚本会自动补齐常用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| 模块 | 文本 | 05 爆款雷达/06 评论选题池/... |
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
| 失败原因 | 文本 | Cookie、验证码、签名、字段结构等 |
| 分数 | 数字 | 模块内评分 |
| 决策 | 文本 | deconstruct / review / skip / ok |
| 摘要 | 文本 | 人可读摘要 |
| 详情JSON | 文本 | 完整诊断和业务明细 |
| 报告路径 | 文本 | 本地备份报告路径 |

### 账号监控表

给每日账号轮询使用，对应：

```bash
FEISHU_ACCOUNT_MONITOR_URL
```

必填字段：

| 字段 | 类型 | 示例 | 说明 |
| --- | --- | --- | --- |
| 账号名称 | 文本 | 跑步精英 | 人看的账号名 |
| 平台 | 文本 | douyin | `douyin` 或 `xiaohongshu` |
| 近期作品链接 | 多行文本 | https://v.douyin.com/xxxx/ | 可一格多条链接，换行即可 |
| 启用 | 复选框/文本 | true | false 时跳过 |

脚本会尝试更新或创建这些字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| 最近运行时间 | 日期 | 最近一次轮询时间 |
| 最近状态 | 文本 | ok / partial / missing_urls / error |
| 最近作品数 | 数字 | 本次轮询作品数量 |
| 最近总互动 | 数字 | 本次轮询总互动 |
| 最近错误 | 文本 | 出错原因 |
| 最近日报摘要 | 文本 | 本账号当天摘要 |

### 账号日报表

给每日账号轮询写结果，对应：

```bash
FEISHU_ACCOUNT_REPORT_URL
```

日报表每天追加每条作品的字段：

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
- 摘要
- 详情JSON

## Part 详细说明

### 01-ingest-content-flow

做什么：

- 解析抖音、小红书分享链接。
- 下载视频、图文图片、封面、文案。
- 提取点赞、收藏、评论、分享。
- 可选转写音频。
- 可选做基础内容分析。

输入：

- 抖音链接
- 小红书链接

输出：

- 下载文件
- 文案
- 四个互动数
- 评论
- 分析 JSON

本地启动 Web UI：

```bash
cd /home/ubuntu/selfmedia-tools/01-ingest-content-flow
./run.sh
```

命令行只刷新字段：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run ingest --urls 'https://v.douyin.com/xxxx/'
```

### 03-deconstruct-viral-content

做什么：

- 只有输入带 `【拆解】` 才做拆解。
- 先下载真实原素材。
- 视频基于抽帧证据分析。
- 图文基于原图证据分析。
- 创建飞书拆解文档。
- 可选创建创作-再创文档。
- 写入飞书多维表格摘要。

输入：

```text
【拆解】 https://v.douyin.com/xxxx/
【拆解】【创作-再创】 https://v.douyin.com/xxxx/ 用户想法...
```

输出：

- 飞书拆解文档
- 飞书创作-再创文档
- 多维表格摘要
- 本地 JSON

运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run deconstruct \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

### 04 平台 Cookie 管理

做什么：

- 从已登录浏览器导出抖音/小红书 Cookie。
- 保存到本地未提交目录。
- 给 01 内容采集 字段抽取和素材下载使用。

查看状态：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run cookies
```

导出 Cookie：

```bash
cd /home/ubuntu/selfmedia-tools/04-manage-platform-cookies
./run_export.sh --save-secrets
```

### 05-detect-viral-radar

做什么：

- 维护一批作品链接。
- 多次运行后记录互动快照。
- 计算起量信号和增速。
- 找正在变热的内容。

输入：

- 作品链接列表

输出：

- 起量候选
- 互动快照
- 飞书爆款雷达记录

运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run viral-radar \
  --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

### 06-mine-comment-topics

做什么：

- 抓作品高赞评论。
- 识别评论里的问题、痛点、争议、需求。
- 生成选题卡。

输入：

- 作品链接

输出：

- 评论池
- 选题卡
- 飞书评论选题记录

运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run comment-topics \
  --urls 'https://v.douyin.com/xxxx/'
```

### 07-index-viral-structures

做什么：

- 把爆款作品沉淀成结构库。
- 保存标题、开头、封面、话题、互动率、评论和拆解标签。
- 可以导入 03 爆款拆解 的拆解 JSON。

输入：

- 作品链接
- 03 爆款拆解 拆解 JSON

输出：

- 爆款结构样本
- 可检索案例
- 飞书结构库记录

运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run viral-structures \
  --urls 'https://v.douyin.com/xxxx/'
```

导入 03 爆款拆解 JSON：

```bash
cd /home/ubuntu/selfmedia-tools/07-index-viral-structures
python3 cli.py --json-input /path/to/deconstruct.json
```

### 08-report-account-competitors

做什么：

- 针对账号或竞品账号维护近期作品样本。
- 统计账号表现、爆款、互动变化。
- 输出日报/周报。

输入：

- 账号名称
- 近期作品链接

输出：

- 账号日报/周报
- 飞书账号表现记录

单次运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run account-competitors \
  --account '竞品账号' \
  --urls 'https://v.douyin.com/xxxx/'
```

每日轮询：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py daily-poll
```

### 09-score-material-quality

做什么：

- 在下载和拆解前先评估素材。
- 根据字段完整度、互动质量、复刻价值打分。
- 给出 `deconstruct`、`review`、`skip` 决策。

输入：

- 作品链接

输出：

- 素材评分
- 决策
- 飞书素材质量记录

运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run material-quality \
  --urls 'https://v.douyin.com/xxxx/'
```

### 10-diagnose-field-health

做什么：

- 诊断点赞、收藏、评论、分享每个字段的来源。
- 判断字段缺失是 HTML、XHR、Cookie、验证码、签名还是页面结构问题。
- 给 05 爆款雷达 和 09 素材质量评分 提供健康状态。

输入：

- 作品链接

输出：

- 字段来源
- 缺失字段
- 失败原因
- 飞书字段健康记录

运行：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run field-health \
  --urls 'https://v.douyin.com/xxxx/'
```

## 每日轮询说明

OpenClaw 已注册账号每日轮询任务：

```text
id: c115fa3a-6a8f-466a-89e0-44854eddf838
name: selfmedia-account-daily-poll
agent: feishu-media
schedule: 每天 08:00 Asia/Shanghai
enabled: false
```

启用前先确认：

- `FEISHU_ACCOUNT_MONITOR_URL` 已配置。
- `FEISHU_ACCOUNT_REPORT_URL` 或 `FEISHU_BITABLE_URL` 已配置。
- 账号监控表有账号和近期作品链接。
- media Bot 的飞书应用有目标表编辑权限。

启用：

```bash
openclaw cron enable c115fa3a-6a8f-466a-89e0-44854eddf838
```

手动跑一次：

```bash
openclaw cron run c115fa3a-6a8f-466a-89e0-44854eddf838
```

## 当前边界

- 当前账号轮询是“已知账号 + 近期作品链接”的稳定方案，不是自动搜索全网新账号。
- 抖音/小红书搜索和主页批量抓取容易受验证码、Cookie、接口签名和页面结构影响。
- 后续可以新增“候选账号池”：按关键词/话题抓作品，从作品里提取作者账号，再写入飞书候选表。

## 验证命令

Python 编译检查：

```bash
cd /home/ubuntu/selfmedia-tools
python3 -m py_compile common/social_runtime.py tools/selfmedia_openclaw.py
```

01 内容采集 测试：

```bash
cd /home/ubuntu/selfmedia-tools/01-ingest-content-flow
python3 -m unittest discover -s tests
```

03 爆款拆解 测试：

```bash
cd /home/ubuntu/selfmedia-tools/03-deconstruct-viral-content
.venv/bin/python -m pytest -q
```

OpenClaw wrapper smoke test：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py list
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run cookies
```

## 不要提交的内容

`.gitignore` 已排除：

- `.env`
- `.env.local`
- Cookie 文件
- 下载媒体文件
- 05 爆款雷达-10 字段健康诊断 的 `data/` 和 `outputs/`
- 03 爆款拆解 的 `outputs/`

提交前可以检查：

```bash
git status --short
git diff --check
```
