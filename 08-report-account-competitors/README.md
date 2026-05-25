# 08 账号竞品报告 account-competitor-weekly

账号竞品周报：跟踪一批抖音/小红书账号，每周输出爆款、互动变化、内容主题迁移和可借鉴方向。

## 目标

- 维护竞品账号清单
- 每周采集账号近期作品和互动数据
- 统计高表现作品、内容主题变化和发布节奏
- 输出周报，辅助选题会和账号策略复盘

## 输入

- `accounts.yaml`：竞品账号列表
- 05 爆款雷达 的作品快照和起量信号
- 07 爆款结构库 的结构数据库

## 运行

当前 MVP 使用作品链接作为账号周报样本，适合先手动维护竞品账号的近期作品。

```bash
cd /home/ubuntu/selfmedia-tools/08-report-account-competitors
python3 cli.py --account '跑步精英' --urls 'https://v.douyin.com/xxxx/' 'http://xhslink.com/o/xxxx'
```

飞书写入：

```bash
export FEISHU_APP_ID='...'
export FEISHU_APP_SECRET='...'
export FEISHU_BITABLE_URL='https://...feishu.cn/wiki/...?table=tblxxx'
export FEISHU_REQUIRED=1
python3 cli.py --account '跑步精英' --urls 'https://v.douyin.com/xxxx/'
```

也可以显式传入 `--require-feishu --feishu-url 'https://...feishu.cn/wiki/...?table=tblxxx'`。飞书多维表格会自动补齐通用字段：参考链接为链接字段，四个互动数、总互动、互动比率和分数为数字字段，运行时间为日期字段；未配置飞书时仍保留本地 SQLite/JSON/Markdown 备份。

示例配置：

```yaml
accounts:
  - platform: douyin
    name: 跑步精英
    account_id: ""
    tags: [田径, 运动]
  - platform: xiaohongshu
    name: AI健身工具作者
    account_id: ""
    tags: [AI, 健身]
```

## 输出

- `outputs/weekly_report_YYYY-WW.md`
- `outputs/account_scores_YYYY-WW.json`
- `data/account_weekly.sqlite`
- 飞书多维表格：每个跟踪作品一行，摘要包含账号名、总互动和周报路径

## 周报结构

- 本周高表现作品
- 本周增长最快作品
- 内容主题变化
- 互动结构变化：点赞、收藏、评论、分享
- 高赞评论洞察
- 可迁移选题
- 下周建议跟踪方向

## 核心数据表

### `accounts`

- `platform`
- `account_id`
- `name`
- `profile_url`
- `tags`
- `enabled`

### `account_posts`

- `account_id`
- `post_id`
- `url`
- `published_at`
- `caption`
- `metrics_snapshot`

### `weekly_insights`

- `account_id`
- `week`
- `top_posts`
- `theme_shift`
- `risk_notes`
- `opportunity_notes`

## MVP

1. 手动维护账号链接和种子作品
2. 每周拉取最近作品的四个互动数
3. 生成账号级排序和作品级排序
4. 用 LLM 生成一份 Markdown 周报

## 与现有模块的关系

- 使用 05 爆款雷达 的采集和增速计算
- 使用 06 评论选题池 的评论选题池
- 使用 07 爆款结构库 的结构标签做主题迁移分析

## Scrapling 可用位置

- 账号主页作品列表采集
- 页面滚动和 XHR 捕获
- 补充账号昵称、简介、粉丝量等公开字段

## 非目标

- 不做粉丝画像推断
- 不抓取私信或非公开数据
- 不自动评价账号商业价值
