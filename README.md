# SelfMedia Tools

`/home/ubuntu/selfmedia-tools` 是一套自媒体素材处理和爆款分析工具，重点服务抖音、小红书内容流。

它不是单个下载器，而是一条工作流：

```text
链接/账号样本
  -> selfmedia 公共 workflow
  -> media_model 契约校验
  -> media_vault 证据落盘
  -> integrations/feishu 写入
  -> OpenClaw media Bot 调用和每日轮询
```

当前主入口：

- OpenClaw：`/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py`
- 本地公共 CLI：`/home/ubuntu/selfmedia-tools/runtime/cli/selfmedia.py`

## 当前文件夹结构

目录职责的唯一事实源是：

```text
/home/ubuntu/selfmedia-tools/docs/architecture.md
```

README 只保留入口和常用命令。新增能力、移动目录、判断某个路径是不是事实源时，以 architecture 文档为准。

```text
selfmedia-tools/
|-- README.md
|-- docs/
|   `-- architecture.md             # 目录职责 SSOT
|-- common/                         # 跨业务公共组件
|-- config/
|   |-- openclaw_bots.json          # Bot/model/profile 配置 SSOT
|   `-- platform_mechanisms/        # 平台机制配置
|-- selfmedia/                      # 公共自媒体业务能力层
|-- media_model/                    # Media Model 契约和 writer ports
|-- media_vault/                    # artifact / evidence 存储 API
|-- integrations/                   # Feishu、平台认证等外部实现
|-- runtime/                        # CLI、维护脚本、部署脚本
|-- openclaw-tag-router/            # OpenClaw tag-router 源码 SSOT
|-- data/
|   |-- media_memory/               # 账号画像和复盘记忆
|   `-- media_vault/                # artifact 存储根
|-- tests/
|-- downloads/
`-- outputs/
```

依赖方向、运行副本边界和禁止反向依赖的完整规则见 `docs/architecture.md`。

常见同名路径的职责不要混淆：

```text
selfmedia-tools/media_vault/       # 代码包
selfmedia-tools/data/media_vault/  # 产物根目录
selfmedia-tools/openclaw-tag-router/          # 源码 SSOT
/home/ubuntu/.openclaw/extensions/openclaw-tag-router/  # 部署副本
/home/ubuntu/.openclaw/workspace/openclaw-tag-router/   # 运行工作区
```

## 全局公共组件

跨工作流复用的能力放在 `common/`。当前稳定公共入口包括：

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

LLM 配置统一读取 `config/openclaw_bots.json`。这是 Bot/模型/profile 的唯一可编辑事实源。当前默认文本模型供应方由 `policy.default_provider` 指向 `providers.openclaw_codex`；所有 Bot 和业务 `profiles` 必须引用这个默认 provider，不在业务代码里硬编码模型或直接读取 provider。`providers.qwen` 仅作为明确的多模态辅助 provider 保留。后续切换主模型时，先改 `policy.default_provider`、目标 provider 和对应同步脚本契约，再运行 single-source guard。

`openclaw-tag-router` 运行扩展的源码也统一收口到仓库内的 `openclaw-tag-router/`。运行目录 `/home/ubuntu/.openclaw/extensions/openclaw-tag-router` 只是部署目标，不再当作事实来源。Feishu OpenClaw agent 运行时使用的 `~/.openclaw/agents/feishu-*/agent/models.json`，以及 Gateway 的 `~/.openclaw/openclaw.json` 中 `agents.defaults.model` / `agents.defaults.models`，也都由同一个 `config/openclaw_bots.json` 自动生成，不再手工维护；Codex 运行时使用内置 `openai-codex` provider，不再生成自定义 `models.providers`。`~/.openclaw/agents/main/agent/models.json` 是 OpenClaw runtime 自管缓存，不作为本仓库编辑事实源。部署命令：

```bash
python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/deploy_openclaw_runtime.py
```

如果只想重建 OpenClaw agent 的 `models.json`：

```bash
python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_agent_models.py
```

如果只想同步 runtime 文件、不重启网关：

```bash
python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/deploy_openclaw_runtime.py --no-restart
```

## 各模块是做什么的

| 模块 | 目录 | 主要职责 | 输入 | 主要输出 | 飞书定位 |
| --- | --- | --- | --- | --- | --- |
| 内容采集 | `selfmedia/ingest/content_flow` | 抖音/小红书素材下载和基础字段抽取 | 单条或多条作品链接 | 视频/图片/封面/文案/互动数/评论 | 给后续模块提供原始素材和字段 |
| 音乐资源提取 | `selfmedia/ingest/music_resource` | 汽水音乐分享资源提取 | 汽水音乐链接或 curl 文本 | 音视频资源、本地 Web UI | 素材资源采集 |
| 字段健康诊断 | `selfmedia/ingest/diagnostics/field_health.py` | 字段来源和失败原因诊断 | 作品链接 | 字段来源、缺失字段、失败原因 | 抓取故障排查 |
| 爆款拆解 | `selfmedia/deconstruct/viral_content` | 爆款拆解和拆解-再创 | 带 `【拆解】` 的作品链接 | 飞书拆解文档、拆解-再创文档、多维表格摘要 | 形成可复用创作样本 |
| 创作工作流 | `selfmedia/creation` | 创作、素材创作、灵感、拍摄执行 | 文本、链接、附件、账号上下文 | CreationRun、创作文档、作品档案 | 创作记录表 / 账号监控表 |
| 数据复盘 | `selfmedia/review/data_review.py` | 后台截图/发布数据复盘 | `【数据复盘】` + 截图 | 复盘报告、账号记忆、Media Model 记录 | 作品复盘 |
| 达人档案补全 | `selfmedia/creator_profiles` | 平台 + 平台ID 定位公开主页，生成 candidate，经确认写入 | 平台、平台ID、可选主页/短链 | evidence bundle、CreatorProfile candidate、H02 指标快照 | `【博主-入库】` 自动补全/确认写入 |
| 语言风格润色 | `selfmedia/style` | 读取账号画像/平台机制/历史模式做润色 | `【润色】`、`【网感】` 等 alias | style_polish_run artifact、诊断、版本、评分 | 显式润色默认只落 media_vault |
| 媒体上下文 | `selfmedia/context` | 账号画像、历史创作、复盘记忆 | `账号=`、创作结果、复盘文本 | 本地账号画像、JSONL 创作/复盘流水 | 下一次创作自动注入 |

## 推荐业务流

### 1. 单条素材快速判断

先看字段是不是能拿全，再决定是否下载或拆解：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run ingest \
  --urls 'https://v.douyin.com/xxxx/'
```

用途：

- 抽取平台、作品 ID、互动字段和基础健康状态。
- 如果需要进一步排查字段来源，使用 `selfmedia/ingest/diagnostics/field_health.py`。

### 2. 爆款拆解

拆解必须显式写 `【拆解】`：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run deconstruct \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

selfmedia 爆款拆解会调用内容采集能力下载真实原素材，再基于视频帧或图文证据分析。不能只看链接和标题猜。

### 3. 上传素材生成定位分析和初稿

飞书 Media bot 里可以先上传视频或图片附件，再发送 `【素材创作】` 指令：

```text
第1条：上传视频或多张图片
第2条：【素材创作>小红书】类型=图文 账号=主账号 发布时间=今晚8点 用户想法=更真实一点
```

也可以在同一条消息里同时发送附件和指令：

```text
【素材创作>小红书】类型=图文 账号=主账号 发布时间=今晚8点 用户想法=更真实一点
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

### 5. 每日账号轮询

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

当前方案默认复用 OpenClaw 的 `feishu-media` 媒体 Bot 信息。所有 Bot 的 OpenClaw agent/model/thinking/timeout/cwd 和外部 LLM provider 配置统一在 `config/openclaw_bots.json`，不要再用分散环境变量覆盖。

这份配置会双向同步到 Obsidian：

```bash
python3 /home/ubuntu/selfmedia-tools/runtime/maintenance/deploy/sync_openclaw_bot_config.py
```

服务器端 Obsidian 路径是 `/home/ubuntu/obsidian-日记/openclaw配置/openclaw_bots.json`，对应 Mac 端路径是 `/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/openclaw配置/openclaw_bots.json`。Obsidian 是 repo 配置的只读镜像；定时器 `openclaw-bot-config-sync.timer` 每分钟只按 `repo-to-obsidian` 单向同步，不能重启运行时服务。配置发生变化且需要加载到运行态时，使用 `runtime/maintenance/deploy/deploy_openclaw_runtime.py` 显式重建 OpenClaw agent/runtime 模型配置并重启 `content-flow.service`、`openclaw-gateway.service` 和 `openclaw-feishu-gateway.service`。

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
# Media Model / 复盘 / 创作写入使用的默认输出表
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
runtime/cli/selfmedia.env.example
```

## 飞书写入边界

- 业务 payload 先过 `media_model` 契约、payload 校验和写入权限。
- Feishu 具体写入只在 `integrations/feishu/media_writer.py`。
- 长 JSON、证据包和运行产物写入 `data/media_vault/`。
- Feishu 可见字段只写摘要、推荐版本、链接和必要状态。

## 当前能力目录说明

### selfmedia/ingest/content_flow

负责抖音/小红书素材采集、字段刷新、下载、转写和基础分析。OpenClaw 入口：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run ingest --urls 'https://v.douyin.com/xxxx/'
```

本地 Web UI 仍在能力包内：

```bash
cd /home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow
./run.sh
```

### selfmedia/deconstruct/viral_content

负责 `【拆解】` 和拆解-再创证据链。OpenClaw 入口：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run deconstruct \
  --text '【拆解】 https://v.douyin.com/xxxx/'
```

### integrations/platform_auth/cookies

负责平台 Cookie 导出和本地保存。状态检查仍通过公共 CLI：

```bash
/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py run cookies
```

导出 Cookie：

```bash
cd /home/ubuntu/selfmedia-tools/integrations/platform_auth/cookies
./run_export.sh --save-secrets
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
python3 -m py_compile common/social_runtime.py runtime/cli/selfmedia.py
```

内容采集测试：

```bash
cd /home/ubuntu/selfmedia-tools
PYTHONPATH=. python3 -m pytest -q selfmedia/ingest/content_flow/tests
```

爆款拆解测试：

```bash
cd /home/ubuntu/selfmedia-tools
PYTHONPATH=. python3 -m pytest -q selfmedia/deconstruct/viral_content/tests
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
- 本地运行产物和备份输出

提交前可以检查：

```bash
git status --short
git diff --check
```
