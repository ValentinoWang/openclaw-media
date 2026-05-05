# Part6 viral-structure-db

爆款结构数据库：沉淀标题、开头、时长、封面、话题、评论、互动率和拆解标签，给再创作和选题复盘提供可检索样本库。

## 目标

- 将 Part1 下载结果、Part2 拆解结果和 Part4 指标快照统一入库
- 支持按平台、赛道、内容结构、互动表现检索案例
- 形成可复用的爆款结构标签体系
- 为再创作提供“相似爆款参考”和“可迁移结构”

## 输入

- Part1 的素材、文案、转写和分析结果
- Part2 的拆解 JSON、分镜、图文脚本和再创作结果
- Part4 的互动数快照和增速指标
- Part5 的评论选题卡

## 运行

从链接直接入库：

```bash
cd /home/ubuntu/selfmedia-tools/Part6/viral-structure-db
python3 cli.py --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

从 Part2 拆解 JSON 入库：

```bash
python3 cli.py --json-input /path/to/deconstruct.json
```

飞书写入：

```bash
export FEISHU_APP_ID='...'
export FEISHU_APP_SECRET='...'
export FEISHU_BITABLE_URL='https://...feishu.cn/wiki/...?table=tblxxx'
export FEISHU_REQUIRED=1
python3 cli.py --urls 'https://v.douyin.com/xxxx/'
```

也可以显式传入 `--require-feishu --feishu-url 'https://...feishu.cn/wiki/...?table=tblxxx'`。飞书多维表格会自动补齐通用字段：参考链接为链接字段，四个互动数、总互动、互动比率和分数为数字字段，运行时间为日期字段；未配置飞书时仍保留本地 SQLite/JSON/Markdown 备份。

## 输出

- `data/viral_structure.sqlite`：结构化样本库
- `outputs/case_index_YYYYMMDD.json`：样本索引
- `outputs/structure_digest_YYYYMMDD.md`：结构复盘摘要
- 飞书多维表格：每个案例一行，摘要包含结构标签、互动总量和质量评分

## 核心数据表

### `cases`

- `case_id`
- `platform`
- `source_url`
- `post_id`
- `media_type`
- `author_name`
- `published_at`
- `caption`
- `transcript`
- `cover_url`
- `duration_seconds`

### `metrics`

- `case_id`
- `like_count`
- `collect_count`
- `comment_count`
- `share_count`
- `collect_ratio`
- `comment_ratio`
- `share_ratio`
- `growth_score`

### `structures`

- `case_id`
- `hook_type`
- `opening_pattern`
- `story_arc`
- `visual_pattern`
- `caption_pattern`
- `topic_tags`
- `audience`
- `pain_or_pleasure_points`

## 标签体系

- 开头：痛点反问、强反差、结果前置、身份代入、悬念
- 主体：步骤教程、案例对比、故事反转、清单盘点、挑战过程
- 结尾：评论引导、收藏引导、观点升华、工具领取
- 画面：口播、教程录屏、Vlog、剧情、图文卡片、前后对比

## MVP

1. 导入现有 Part2 输出 JSON
2. 从 `stats` 计算互动率
3. 将 `video_storyboard` 和 `image_post_script` 归档为结构字段
4. 提供按标签和分数筛选的 JSON/Markdown 索引

## 与现有模块的关系

- Part1 提供原始素材字段
- Part2 提供拆解结构
- Part4 提供增速指标
- Part5 提供评论选题

## Scrapling 可用位置

- 补充页面可见字段，如发布时间、作者、音乐、话题
- 对历史链接做字段回填
- 当平台接口变化时提供 HTML/XHR 备份数据源

## 非目标

- 不替代原始媒体文件存储
- 不把长脚本直接写入飞书多维表格
- 不存储无来源的推测字段
