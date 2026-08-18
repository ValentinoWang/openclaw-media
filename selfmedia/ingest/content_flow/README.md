# content-flow

一个“输入分享链接 -> 下载素材 -> 可选转写与分析 -> 可选写入 Notion”的内容处理流水线。

## 支持的平台

- 抖音：视频 / 图文
- 小红书：视频 / 图文

建议优先使用 App 直接分享出来的原始链接，尤其是小红书的 `xhslink.com` 分享链接，成功率通常更高。

## 主要能力

- 下载视频、图文图片、音频、封面与文案
- 提取部分互动数据与评论信息
- 接入 DashScope/阿里非实时 ASR 做音频转写
- 接入 Codex Responses 做结构化内容分析
- 将结果写入 Notion 数据库
- 提供本地 Web 界面

## 环境要求

- Python 3.11+
- 建议使用 `uv`
- 首次运行 Playwright 时需要安装浏览器

## 快速开始

```bash
cp .env.example .env
uv sync
uv run python -m playwright install webkit
./run.sh
```

服务启动后，浏览器会自动打开本地页面。

## 环境变量

复制 `.env.example` 为 `.env` 后按需填写：

- 音频转写只走 DashScope/阿里 ASR：`ASR_PROVIDER=dashscope`、`DASHSCOPE_API_KEY`、`DASHSCOPE_ASR_MODEL`、`DASHSCOPE_ASR_MODE=batch`
- 结构化内容分析读取 `/home/ubuntu/selfmedia-tools/config/openclaw_bots.json`
- `NOTION_TOKEN` / `NOTION_DATABASE_ID`：用于写入 Notion

如果你只想下载素材，不配置这些变量也可以运行一部分功能。

## 小红书抓取说明

- 推荐直接粘贴 App 分享出来的 `xhslink.com/o/...` 链接，程序会自动跟随重定向并解析页面数据。
- 仅粘贴不带 `xsec_token` 等参数的裸 `xiaohongshu.com/discovery/item/<id>` 链接时，可能无法拿到完整内容。

## 抖音图文抓取说明

- 抖音 `share/note` / `note` 是图文入口，应优先解析 `window._ROUTER_DATA` 里的 `desc` 和 `images`。
- 图文对象里的 `video.play_addr` 可能是配乐/音频流，不能用它覆盖图片资产或把记录判成短视频。
- 经验文档见 `/home/ubuntu/docs/ai-harness/content-flow-douyin-note-ingest-contract.md`。

## 目录说明

- `src/`：后端逻辑
- `frontend/`：本地页面
- `scripts/`：辅助脚本
- `run.sh`：本地启动入口

## 注意事项

- `.env`、`downloads/`、日志文件不应提交到仓库
- 某些平台抓取效果依赖页面返回、Cookie 与请求参数，稳定性会受平台策略影响
