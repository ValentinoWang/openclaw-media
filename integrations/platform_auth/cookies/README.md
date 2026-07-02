# Cookie Secret Helper

导出并保存抖音/小红书 Cookie 到本地未提交文件。

## 快速开始

### 前提：先在浏览器登录

在 Chrome/Safari/Firefox 中访问并登录：
- 抖音：https://www.douyin.com
- 小红书：https://www.xiaohongshu.com

### 方式 1: 自动导出（推荐）

```bash
# 一键导出并保存
./run_export.sh --save-secrets
```

10 秒完成，适合频繁更新 cookie。

### 方式 2: 手动导出

如果自动导出失败，使用浏览器扩展手动导出（见下方详细步骤）。

## 自动导出详细说明

### 安装依赖（首次使用）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install playwright
playwright install chromium
```

### 使用方式

**一键导出并保存**：
```bash
./run_export.sh --save-secrets
```

**只导出单个平台**：
```bash
./run_export.sh --platform douyin
./run_export.sh --platform xiaohongshu
```

**无界面模式**：
```bash
./run_export.sh --headless --save-secrets
```

### 工作原理

1. 脚本启动浏览器访问平台网站
2. 读取你已登录的 cookies（你运行脚本 = 明确授权）
3. 保存到 `~/Downloads/` 的 JSON 文件
4. 自动调用 `save_platform_cookie_secret.py` 保存到 secrets/

### 为什么这样是安全的？

- ✅ 你主动运行脚本 = 明确授权
- ✅ 不会后台自动运行或定时执行
- ✅ 完全透明，你知道导出了什么
- ✅ 本地存储，不上传到任何服务器

## 手动导出（备用方案）

如果自动导出失败，可以使用浏览器扩展手动导出。

### 1. 安装 Cookie-Editor 扩展

- Chrome/Edge: https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
- Firefox: https://addons.mozilla.org/firefox/addon/cookie-editor/

### 2. 导出 Cookie

1. 在目标网站页面点击 Cookie-Editor 图标
2. 点击 "Export" → "JSON"
3. 保存到 `~/Downloads/`（建议命名：`douyin-cookies.json`、`xiaohongshu-cookies.json`）

### 3. 运行保存脚本

```bash
# 自动发现 Downloads 中的文件
python3 save_platform_cookie_secret.py

# 或指定文件
python3 save_platform_cookie_secret.py \
  --douyin-input-file ~/Downloads/douyin-cookies.json \
  --xiaohongshu-input-file ~/Downloads/xiaohongshu-cookies.json
```

## 生成的文件

脚本会创建以下本地文件（已在 `.gitignore` 中）：

```
04-manage-platform-cookies/
├── secrets/
│   ├── douyin-cookie-header.txt          # Cookie Header 格式
│   └── xiaohongshu-cookie-header.txt
├── private/
│   ├── douyin-cookies.json               # Cookie-Editor JSON 格式
│   └── xiaohongshu-cookies.json
└── .env.local                             # 环境变量配置
```

`.env.local` 内容示例：

```bash
DOUYIN_COOKIE_HEADER_FILE="secrets/douyin-cookie-header.txt"
DOUYIN_COOKIES_JSON_PATH="private/douyin-cookies.json"
XIAOHONGSHU_COOKIE_HEADER_FILE="secrets/xiaohongshu-cookie-header.txt"
XIAOHONGSHU_COOKIES_JSON_PATH="private/xiaohongshu-cookies.json"
```

## 安全特性

1. **用户主动授权** - 只在你运行脚本时执行，不会后台自动运行
2. **不打印敏感值** - Cookie 内容不会显示在终端
3. **严格文件权限** - 生成的文件权限为 `0600`（仅所有者可读写）
4. **Git 忽略** - `secrets/`、`private/`、`.env.local` 已在 `.gitignore` 中
5. **本地存储** - 不上传到任何服务器

## 高级选项

### 环境变量格式

默认保存文件路径到 `.env.local`。如果需要直接保存 cookie 值：

```bash
python3 save_platform_cookie_secret.py --env-style value
```

### 自定义扫描目录

```bash
python3 save_platform_cookie_secret.py --discover-dir ~/Desktop
```

## 在其他项目中使用

在 `content-flow` 或其他项目中读取 cookie：

```python
import os
from pathlib import Path

# 方式 1: 从文件路径读取
cookie_file = Path(os.getenv("DOUYIN_COOKIE_HEADER_FILE"))
cookie_header = cookie_file.read_text().strip()

# 方式 2: 直接从环境变量读取（需要 --env-style value）
cookie_header = os.getenv("DOUYIN_COOKIE_HEADER")
```

## 常见问题

### Q: 自动导出提示未登录？

```
⚠️  Warning: No 抖音 cookies found!
```

**解决**：在浏览器中访问对应平台并登录，然后重新运行脚本。

### Q: Cookie 多久需要更新一次？

A: 取决于平台的会话过期策略。通常：
- 抖音：7-30 天
- 小红书：7-14 天

当请求返回 401/403 错误时，重新导出并运行脚本更新。

### Q: 可以在 CI/CD 中使用吗？

A: 不建议。Cookie 是短期凭证，不适合自动化环境。建议使用平台的官方 API 和长期 token。

### Q: 导出的 Cookie 文件可以分享吗？

A: **绝对不可以**。Cookie 包含你的登录凭证，任何人获取后都可以冒充你的身份操作账号。

## 故障排除

### 找不到导出文件

```
error: no exported Douyin cookie file was found in: ~/Downloads, /path/to/04-manage-platform-cookies
```

**解决方案**：
1. 确认已用 Cookie-Editor 导出文件
2. 检查文件名包含 "cookie" 或平台名称
3. 使用 `--input-file` 明确指定文件路径

### 格式检测失败

```
error: could not detect cookie export format
```

**解决方案**：
1. 确认导出的是 JSON 格式或 Header String 格式
2. 使用 `--format json` 或 `--format header` 明确指定格式

### 权限错误

```
error: failed to read input file: Permission denied
```

**解决方案**：
```bash
chmod 600 ~/Downloads/douyin-cookies.json
```

## 相关项目

- `selfmedia/ingest/content_flow` - 使用这些 cookie 下载抖音/小红书内容
- `selfmedia/ingest/music_resource` - 汽水音乐资源提取工具
