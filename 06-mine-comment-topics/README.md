# 06 评论选题池 comment-topic-pool

高赞评论选题池：抓取抖音/小红书作品的高赞评论，聚类痛点、争议点、需求点，并生成可复用的选题方向。

## 目标

- 对指定作品或爆款雷达候选作品抓取高赞评论
- 提取用户问题、反驳、共鸣、需求和情绪
- 聚类成选题卡片，避免只看单条评论做判断
- 给 03 爆款拆解 创作-再创提供评论侧选题依据

## 输入

- 作品链接列表
- 05 爆款雷达 输出的起量作品
- 03 爆款拆解 拆解结果中的 `top_comments`
- 可选：账号或话题维度的评论池

## 运行

```bash
cd /home/ubuntu/selfmedia-tools/06-mine-comment-topics
python3 cli.py --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
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

- `data/comments.sqlite`：评论原始数据和聚类结果
- `outputs/topic_cards_YYYYMMDD.json`：结构化选题卡
- `outputs/topic_pool_YYYYMMDD.md`：人工筛选用选题池
- 飞书多维表格：每个选题卡一行，摘要包含选题类型和证据评论

## 核心数据表

### `comments`

- `platform`
- `post_id`
- `comment_id`
- `author_name`
- `text`
- `like_count`
- `captured_at`
- `reply_to`

### `comment_topics`

- `topic_id`
- `topic_type`
- `title`
- `summary`
- `evidence_comments`
- `pain_points`
- `pleasure_points`
- `content_angle`
- `priority_score`

## 选题类型

- `pain`：用户痛点和阻碍
- `question`：高频问题
- `controversy`：争议和反对意见
- `identity`：人群身份和场景
- `demand`：明确想要教程、工具、模板或清单
- `meme`：可复用梗、口头禅、情绪表达

## MVP

1. 从作品链接抓取 Top N 评论
2. 清洗表情、空白、重复评论
3. 基于规则先分出问题、痛点、争议、需求
4. 调用 LLM 聚类并生成选题卡
5. 输出每个选题的证据评论和优先级

## 与现有模块的关系

- 复用 `01-ingest-content-flow` 的评论抓取能力
- 可接收 `05-detect-viral-radar` 的候选作品
- 生成的选题卡可进入 `03-deconstruct-viral-content` 创作-再创提示词

## Scrapling 可用位置

- 在官方接口拿不到评论时，从渲染页面提取可见评论
- 批量滚动评论区并捕获评论 XHR
- 记录评论字段来源，辅助字段健康诊断

## 非目标

- 不做水军识别或账号画像推断
- 不抓取私密内容
- 不自动发布内容
