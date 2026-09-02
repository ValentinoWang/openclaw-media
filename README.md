# OpenClaw Media

OpenClaw Media 是面向自媒体团队的创作与运营系统：它连接公开内容研究、素材采集与拆解、CreativeProject、Creator Studio、飞书协作、本地媒体 Agent、发布复盘和账号记忆。

本仓库不是一个单独的下载器，也不是一个可以随意堆脚本的目录。每项能力必须有唯一代码责任方、唯一运行入口和唯一产物根。

## 从哪里开始

- **目录与依赖边界的唯一事实源**：[docs/architecture.md](docs/architecture.md)
- **自媒体业务 CLI**：`runtime/cli/selfmedia.py`
- **OpenClaw Media 本地 Agent CLI**：`openclaw-media/openclaw_media/cli.py`
- **Web / Creator Studio**：`openclaw-bot-center/`
- **Tag Router 源码事实源**：`openclaw-tag-router/`
- **完整部署入口**：`runtime/maintenance/deploy/deploy_openclaw_runtime.py`

README 只提供导航和常用命令；目录职责、反向依赖禁令、部署副本和数据边界以 `docs/architecture.md` 为准。

## 产品分层

```text
公开内容 / 用户输入 / 飞书附件
                │
                ▼
selfmedia 业务层
采集 · 拆解 · 创作 · 风格 · 账号画像 · 复盘
                │
       ┌────────┴────────┐
       ▼                 ▼
media_model          media_vault
业务合同与 writer     证据、artifact、media://
       │                 │
       └────────┬────────┘
                ▼
integrations / OpenClaw Tag Router
飞书、平台认证、Bot 入口和会话路由
                │
                ▼
OpenClaw Media Control Plane
pipeline · device · job · archive · readback
                │
                ▼
本地 Media Agent / Photo Content OS
原始媒体、分析缓存、时间线和编辑器工程留在设备
```

## 三个主要入口

### 1. 自媒体业务工作流

本地公共入口：

```bash
python3 runtime/cli/selfmedia.py --help
```

OpenClaw Media Bot 内部只保留一个薄入口，转发到同一业务 CLI；不要在 Bot 工作区复制一套独立业务实现。

常用流程：

```bash
# 单条公开内容采集与字段诊断
python3 runtime/cli/selfmedia.py run ingest --urls 'https://...'

# 基于真实下载素材做爆款拆解
python3 runtime/cli/selfmedia.py run deconstruct --text '【拆解】 https://...'

# 查看指定账号上下文
python3 runtime/cli/selfmedia.py context \
  --tenant-id '<tenant-id>' \
  --platform 小红书 \
  --account 主账号
```

飞书用户入口仍以能力标签为准，例如 `【素材】`、`【创作】`、`【拆解】`、`【复盘】`。标签解析和能力注册只在 `openclaw-tag-router/` 维护。

### 2. 本地 Media Agent

Python 要求：`>=3.12,<3.14`。

```bash
cd openclaw-media
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/openclaw-media --help
```

配对并运行本地 Agent：

```bash
openclaw-media pair \
  --base-url 'https://your-control-plane.example' \
  --pair-code '<pair-code>' \
  --device-label 'My Mac' \
  --workspace '/local/media/workspace'

openclaw-media agent status
openclaw-media agent run --once
openclaw-media agent run --foreground
```

本地 Agent 使用 outbound-only 协作：

```text
queued
→ leased
→ acknowledged
→ running
→ succeeded / blocked / failed
```

配对、设备凭据、租约、结果回传、归档提交和 readback 都由 `openclaw_media` 包统一实现；下游本地工具只实现白名单 pipeline 节点，不能再创建第二套任务状态机。

当前生成 catalog 包含项目准备、素材整理、素材匹配、剪辑交接、可编辑时间线、确认修订、成片复核、节奏复核和语义复核等 pipeline。Web 与本地 CLI 必须使用同一份 catalog digest。

### 3. Web / Creator Studio

```bash
cd openclaw-bot-center
npm ci --ignore-scripts
npm run generate:data
npm run validate:data
npm run build:media
```

开发预览：

```bash
npm run dev
```

Web 负责项目、任务、业务文档、状态、回执和证据投影；它不会假装能够浏览、播放、下载或编辑本地原始视频，也不得向普通用户暴露绝对路径、内部队列名和编辑后端实现细节。

### 不鉴权静态演示站

面向业务流程走查与对外演示的独立构建目标：真实的 `MediaStudioApp` 与全部生产页面组件，配一套浏览器内假后端——没有登录、没有后端、没有真实数据，数据集由业务合同与能力注册表生成并逐字段校验。

```bash
cd openclaw-bot-center
npm run dev:demo      # 本地预览
npm run build:demo    # 构建 dist-demo/
```

演示站与生产前端共用同一批页面组件，一致性由 `npm run qa:media-demo-parity` 强制（它是 `build:media` 的第一步）：改了生产路由、会话授权或业务合同却没同步演示站，生产构建会失败。改动约定见仓库根目录 [CLAUDE.md](CLAUDE.md)，完整说明见 [docs/frontend/media-demo-site.md](docs/frontend/media-demo-site.md)。

## 数据与源码边界

容易混淆的同名目录：

```text
media_vault/                    # Python 代码包：MediaVault API
数据目录 data/media_vault/       # tenant-scoped 产物根
openclaw-tag-router/            # 可编辑的 Tag Router 源码事实源
~/.openclaw/extensions/...      # 部署副本，不是编辑位置
~/.openclaw/workspace/...       # 运行消息、日志与临时状态
openclaw-bot-center/public/...  # 生成的前端投影
openclaw-bot-center/dist*/      # 构建产物
/var/www/openclaw/bots/         # 已发布静态文件
```

核心规则：

- `selfmedia` 可以依赖 `media_model`、`media_vault` 和 `integrations`；反向依赖禁止。
- `data/`、`downloads/`、`outputs/` 和运行 workspace 不能成为 Python 源码位置。
- 长证据与生成产物进入 tenant-scoped Media Vault；飞书可见字段只保存摘要、稳定 ID、链接和状态。
- 原始媒体默认留在本地设备；控制面只接收允许的 `content` 或 `descriptor_only` artifact。
- 绝对路径、凭据、原始 Provider payload 和跨租户数据必须 fail closed。

完整规则见 [docs/architecture.md](docs/architecture.md)。

## 配置事实源

Bot、模型、Provider 和 profile 的唯一可编辑配置：

```text
config/openclaw_bots.json
```

业务代码不得硬编码默认 Provider，也不得各自维护模型映射。切换模型时，先更新配置事实源，再运行同步与 single-source guard。

## 测试与构建

### Python 业务与 Media Agent

```bash
# 仓库业务测试
python3 -m pytest tests

# 打包后的本地 Agent SDK
cd openclaw-media
python -m pytest
```

### Web

```bash
cd openclaw-bot-center
npm run validate:data
npm run lint
npm run build:all
```

Media Web 还包含登录、注册、素材解析、任务确认、删除恢复、项目投影、普通用户文案和生产截图等专项 QA。选择与改动相关的门禁，不要通过删除或弱化测试来获得绿色结果。

## 发布与生产对账

生产发布不能只凭“本地测试通过”或“页面能打开”判断完成。当前发布治理将证据拆成三层：

1. **Manifest**：冻结 release identity、规范化路径、文件摘要和源提交；
2. **Planner**：只生成 planned-only 激活/回滚计划，不执行外部动作；
3. **Readback**：在实际授权执行后回读服务、指针、HTTP/DOM、数据和外部系统证据。

Source-only 合同、红测试或 dry-run 计划都不等于生产已经部署，也不等于 release 已被人工接受。生产结论必须绑定独立的发布 hash、运行证据、readback 和人工验收记录。

## 部署

完整 source-to-runtime 投影只使用：

```bash
python3 runtime/maintenance/deploy/deploy_openclaw_runtime.py
```

它负责同步 Tag Router 源码到 active extension、生成 Agent 模型配置、安装 systemd user timer、生成和构建 Bot Center、发布静态文件，并执行 single-source 与 runtime smoke 门禁。

只重建 OpenClaw Agent 模型配置：

```bash
python3 runtime/maintenance/deploy/sync_openclaw_agent_models.py
```

不重启网关的完整投影：

```bash
python3 runtime/maintenance/deploy/deploy_openclaw_runtime.py --no-restart
```

不要长期直接修改 `~/.openclaw/extensions/`、构建目录或 `/var/www/`。紧急热修必须立即回灌源码事实源，并重新运行部署与一致性校验。

## 目录速览

```text
openclaw-media/
├── common/                     # 跨工作流公共组件
├── config/                     # Bot / Provider / 平台机制配置
├── docs/                       # 架构 SSOT 与运行文档
├── selfmedia/                  # 自媒体业务能力层
├── media_model/                # 业务对象与 writer ports
├── media_vault/                # artifact / evidence API
├── integrations/               # 飞书与平台认证实现
├── runtime/                    # CLI、维护、同步与部署
├── openclaw-tag-router/        # OpenClaw 路由源码事实源
├── openclaw-bot-center/        # Web / Creator Studio
├── openclaw-media/             # pipeline catalog 与本地 Agent SDK
├── data/                       # tenant-scoped 本地产物
├── tests/                      # 仓库级测试
├── downloads/                  # 本地下载缓存
└── outputs/                    # 临时输出与备份
```

## 修改前检查

1. 先在 `docs/architecture.md` 确认代码 owner、运行入口和 artifact root；
2. 不在部署副本、运行 workspace 或数据目录中新增业务实现；
3. 不创建第二份 capability registry、模型配置、任务状态机或 Media Vault writer；
4. 修改生成合同后同时更新生成器、Schema、消费者和受保护测试；
5. 合并前运行与变更范围对应的 Python、Web、single-source 和 release gate。
