# Part9 field-health-diagnostics

字段健康诊断：每条链接保存字段来源和失败原因，明确字段是来自 HTML、XHR、Cookie、截图、接口，还是失败于验证码、登录、签名、权限或页面结构变化。

## 目标

- 为每次字段抽取生成可追踪诊断记录
- 记录每个字段的来源、可信度、时间和错误
- 快速判断平台策略变化是否影响采集链路
- 给 Part4/Part8 提供健康状态和失败原因

## 输入

- 单条作品链接
- Part1 字段抽取结果
- Playwright/Scrapling 采集日志
- HTTP 状态码、响应摘要、截图路径

## 运行

```bash
cd /home/ubuntu/selfmedia-tools/Part9/field-health-diagnostics
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

- `data/field_health.sqlite`
- `outputs/field_health_YYYYMMDD.json`
- `outputs/failure_report_YYYYMMDD.md`
- 飞书多维表格：每个诊断运行一行，摘要写字段状态和失败原因，详情 JSON 保留字段来源

## 字段来源分类

- `api_aweme_detail`
- `api_aweme_post`
- `share_html_statistics`
- `xhs_initial_state`
- `xhr_capture`
- `dom_visible_text`
- `screenshot_ocr_pending`
- `manual_cookie`

## 失败原因分类

- `missing_cookie`
- `expired_cookie`
- `captcha`
- `login_required`
- `signature_required`
- `permission_denied`
- `deleted_or_private`
- `field_schema_changed`
- `network_timeout`
- `parser_error`

## 核心数据表

### `field_runs`

- `run_id`
- `platform`
- `url`
- `post_id`
- `started_at`
- `finished_at`
- `overall_status`
- `failure_reason`

### `field_values`

- `run_id`
- `field_name`
- `field_value`
- `source`
- `confidence`
- `raw_path`
- `error`

### `raw_artifacts`

- `run_id`
- `artifact_type`
- `path`
- `summary`
- `created_at`

## MVP

1. 包装 Part1 的字段抽取函数
2. 对每个字段保存 `value/source/status`
3. 对失败链路保存错误摘要和截图路径
4. 输出一份诊断 Markdown
5. 提供给 Part8 做质量评分输入

## 与现有模块的关系

- Part1 负责实际字段抽取
- Part4 使用健康状态决定是否重试采集
- Part8 使用健康状态决定是否入库/拆解
- Part2 可把诊断信息写入拆解结果的 `stats_notice`

## Scrapling 可用位置

- 作为第二采集 backend，与 Playwright/requests 结果对比
- 捕获 XHR 列表和最终 DOM，帮助定位字段消失原因
- 保存 adaptive selector 命中情况，辅助维护解析器

## 非目标

- 不绕过平台验证码
- 不记录敏感 Cookie 原文
- 不把完整 HTML 长期公开存储
