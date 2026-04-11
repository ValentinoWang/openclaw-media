# MP4-extract

一个面向汽水音乐分享内容的本地提取工具，支持直接解析分享文本、分享链接或 curl 文本，并通过本地 Web UI 发起下载。

## 功能

- 解析分享文本中的链接
- 支持传入 curl 文本复用请求头
- 支持读取本地浏览器 Cookie
- 可下载到本地 `downloads/` 目录
- 提供简单的本地页面操作界面

## 运行方式

```bash
./run_ui.sh
```

脚本会自动：

- 创建本地虚拟环境
- 安装 `requirements.txt`
- 安装 Playwright Chromium
- 启动 UI 服务

## 注意事项

- `downloads/` 为运行产物，不应提交到 GitHub
- 某些内容依赖 Cookie、请求头或平台限制，不能保证长期稳定
