# SelfMedia

一个用于整理和处理自媒体内容素材的工具集合，当前包含几个独立的小工具：

- `Part1/content-flow`：输入分享链接，下载素材，可选转写、分析并写入 Notion。
- `Part1/MP4-extract`：从汽水音乐分享内容中提取可下载的音视频资源，并提供本地 Web UI。
- `part3`：保存手动导出的抖音/小红书 Cookie 到本地未提交文件。

## 目录结构

```text
SelfMedia/
├── Part1/
│   ├── content-flow/
│   └── MP4-extract/
├── part3/
├── .gitignore
└── README.md
```

## 项目说明

### 1. `content-flow`

能力概览：

- 支持抖音、小红书分享链接
- 下载视频、图文素材、封面、文案
- 可选接入 DashScope 做音频转写
- 可选接入 Gemini 做内容分析
- 可选写入 Notion 数据库

快速启动：

```bash
cd Part1/content-flow
cp .env.example .env
uv sync
./run.sh
```

如果不用 `uv`，也可以自行创建虚拟环境并按 `pyproject.toml` 安装依赖。

### 2. `MP4-extract`

能力概览：

- 解析汽水音乐分享文本或分享链接
- 支持从 curl 文本提取请求头
- 支持本地浏览器 Cookie 辅助抓取
- 提供简单的本地 Web UI

快速启动：

```bash
cd Part1/MP4-extract
./run_ui.sh
```

## 发布到 GitHub 前已处理

- 移除了下载产物、日志、缓存、`.DS_Store`
- 移除了内嵌 Git 仓库，改为单一仓库结构
- 增加了仓库级 `.gitignore`
- 保留源码、前端页面、脚本和依赖声明

## 建议的 GitHub 仓库信息

- Repository name: `selfmedia-tools`
- Visibility: 先用 `private`，确认无敏感逻辑后再转 `public`
- Topics: `python`, `playwright`, `notion`, `douyin`, `xiaohongshu`, `content-pipeline`

## 注意事项

- 不要提交本地 `.env`
- 不要提交下载目录里的媒体文件
- 如果后续准备公开发布，建议再补一个开源许可证文件
