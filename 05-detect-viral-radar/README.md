# 05 爆款雷达 viral-radar

爆款雷达：按账号、关键词、话题定时采集抖音/小红书内容，持续记录点赞、收藏、评论、分享增速，发现正在起量的内容。

## 目标

- 按配置跟踪一组账号、关键词、话题或手动种子链接
- 周期性抓取作品基础字段和四个互动数
- 计算短期增速、互动率、收藏率、评论率、分享率
- 输出“正在起量”“高收藏潜力”“争议讨论高”的候选内容
- 将候选内容交给 01 内容采集 下载，或交给 03 爆款拆解 拆解

## 输入

- `targets.yaml`：账号、关键词、话题、种子链接配置
- `schedule.yaml`：采集频率、时间窗口、平台开关
- Cookie：复用 `04-manage-platform-cookies` 导出的抖音/小红书 Cookie

## 运行

本模块已经提供可运行 CLI。默认写本地 SQLite/JSON/Markdown；配置飞书后同时写入飞书多维表格。

```bash
cd /home/ubuntu/selfmedia-tools/05-detect-viral-radar
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

也可以显式传入：

```bash
python3 cli.py --require-feishu --feishu-url 'https://...feishu.cn/wiki/...?table=tblxxx' --urls 'https://v.douyin.com/xxxx/'
```

飞书多维表格会自动补齐通用字段：参考链接为链接字段，四个互动数、总互动、互动比率和分数为数字字段，运行时间为日期字段；未配置飞书时仍保留本地 SQLite/JSON/Markdown 备份。

示例配置：

```yaml
targets:
  - platform: douyin
    type: keyword
    value: AI健身
  - platform: xiaohongshu
    type: topic
    value: RPG健身教练
  - platform: douyin
    type: account
    value: 跑步精英

windows:
  collect_interval_minutes: 60
  rising_window_hours: 6
```

## 输出

- `data/posts.sqlite`：作品快照和指标增量
- `outputs/rising_posts_YYYYMMDD.json`：起量作品列表
- `outputs/radar_report_YYYYMMDD.md`：人工可读日报
- 飞书多维表格：模块、运行时间、平台、作品 ID、链接、四个互动数、状态、分数、摘要、详情 JSON

## 核心数据表

### `posts`

- `platform`
- `post_id`
- `url`
- `author_id`
- `author_name`
- `title`
- `caption`
- `cover_url`
- `published_at`
- `tags`

### `post_snapshots`

- `post_id`
- `captured_at`
- `like_count`
- `collect_count`
- `comment_count`
- `share_count`
- `field_sources`
- `health_status`

### `radar_signals`

- `post_id`
- `signal_type`
- `score`
- `reason`
- `window_start`
- `window_end`

## 评分逻辑

- `growth_score`：互动数在窗口内的增速
- `collect_ratio_score`：收藏 / 点赞，判断实用价值
- `comment_ratio_score`：评论 / 点赞，判断讨论度
- `share_ratio_score`：分享 / 点赞，判断传播性
- `freshness_score`：发布时间越近权重越高
- `composite_score`：综合排序，用于推荐进入拆解

## MVP

1. 读取种子链接列表
2. 调用 01 内容采集 字段抽取能力刷新互动数
3. 写入 SQLite 快照
4. 对同一作品两次快照计算增量
5. 输出 Top 20 起量内容

## 与现有模块的关系

- 使用 `04-manage-platform-cookies` 的 Cookie
- 复用 `01-ingest-content-flow` 的 URL 清洗和互动数字段抽取
- 输出候选链接给 `03-deconstruct-viral-content`

## Scrapling 可用位置

- 批量打开账号页/话题页，采集列表页里的作品链接
- 捕获动态页面 XHR，补齐作品列表和互动字段
- 作为 Playwright 被验证码挡住时的候选采集器

## 非目标

- 不直接下载视频素材
- 不直接生成拆解文档
- 不绕过登录、验证码或平台权限限制
