# Part2 viral-deconstruct

显性触发的爆款拆解工作流：流程分流由代码保证，不交给 LLM 判断。

- 无标签：只返回普通素材整理跳过状态，不拆解、不再创作
- 只有 `【拆解】`：执行拆解
- `【拆解】` + `【再创作】`：先拆解，再基于拆解结果再创作
- 只有 `【再创作】`：报错中止，不下载、不分析、不建文档、不写多维表格

目标：输入爆款视频/图文链接，下载原视频或原图文素材，生成可复刻但不照搬的：

- 视频分镜脚本
- 图文发布脚本
- 可直接复制发布稿
- 避重/差异化建议

## 运行

```bash
cd /home/ubuntu/selfmedia-tools/Part2/viral-deconstruct
uv run python -m src.cli '【拆解】 https://v.douyin.com/xxxx/' --out outputs/demo.json
```

不含 `【拆解】` 的输入会直接跳过，避免普通素材整理被误触发。

## Cookie

本模块优先复用 Part1 的下载能力。Linux 服务器无图形界面时，建议通过同步文件提供 Cookie：

- 抖音：`/home/ubuntu/obsidian-diary/自媒体/cookies/douyin.cookie`
- 小红书：`/home/ubuntu/obsidian-diary/自媒体/cookies/xiaohongshu.cookie`

也支持环境变量：`DOUYIN_COOKIE_FILE` / `XHS_COOKIE_FILE`。


## 写入飞书多维表格

本模块写飞书，不写 Notion。传入 `--feishu-url`，或配置：

```bash
export FEISHU_BITABLE_URL='https://...feishu.cn/wiki/...?table=tblxxx&view=vewxxx'
```

多维表格只写索引、摘要、附件、文档链接。代码会用字段白名单和黑名单禁止写入 `final_script`、`republish_copy`、`video_storyboard`、`image_post_script`、`分镜脚本`、`图文脚本`、`可复制发布稿` 等长脚本字段。

附件字段由代码归类：

- `封面图/前五秒`：封面、首帧或预览素材
- `原文件`：完整原视频或全部原图
- `原音频`：单独音频文件

写入顺序由代码保证：真实素材校验 -> LLM JSON schema 校验 -> 拆解文档创建并校验可访问 -> 再创作文档创建并校验可访问（如有）-> 附件归类校验 -> 最后写入多维表格。

拆解视觉证据会分配稳定 ID：

- 视频关键帧：`frame_001`、`frame_002` ...
- 图文原图：`image_001`、`image_002` ...

LLM 输出的 `video_storyboard` / `image_post_script` 必须用 `evidence_asset_id` 引用这些 ID。代码会校验 ID 合法性，非法会重试，仍失败则中止。拆解文档里的「画面图」列使用上传后的飞书图片块，不写本地路径或 file token 文本。

## 视频理解模型路线

默认路线仍是 `gpt_frames`：本地抽帧/提音频形成证据包，最终由主模型输出拆解 JSON。

主模型会优先读取显式环境变量 `SELFMEDIA_LLM_API_KEY` / `OPENAI_API_KEY`。如果没有普通 OpenAI API key，会自动读取 Codex 登录文件 `~/.codex/auth.json`，并使用 OpenClaw 的 `openai-codex/gpt-5.5` 配置走 `https://chatgpt.com/backend-api/codex/responses`。这条 Codex 路线是 stream Responses API，不是 `/v1/chat/completions`。

可选配置：

```bash
export VIDEO_UNDERSTANDING_PROVIDER='gpt_frames' # gpt_frames | qwen_omni | hybrid
export QWEN_MODEL='qwen3.5-omni-plus'
export QWEN_FPS='2.0'
export QWEN_API_KEY='...'
```

- `qwen_omni` / `hybrid` 会把原视频传给 Qwen-Omni 生成 `native_video_observation`。
- Qwen-Omni 调用走阿里云百炼 OpenAI 兼容接口，使用 `video_url` + `stream=true` + `modalities=["text"]`。
- Qwen-Omni 只负责音视频观察，不直接写最终飞书文档。
- 最终拆解仍由主模型基于证据包 + observation 输出，并继续校验 `evidence_asset_id`。
- `hybrid` 下 Qwen 调用失败会回退到本地抽帧证据包；主模型不可用则直接中止，不写文档、不写表。
