# 爆款拆解 viral-deconstruct

显性触发的爆款拆解工作流：流程分流由代码保证，不交给 LLM 判断。

- 无标签：只返回普通素材整理跳过状态，不拆解
- 只有 `【拆解】`：执行拆解
- 需要发布脚本、分镜或任务卡时，由 `【素材】` SourceAsset 续跑后显式交接 `【创作】` 或 `【创作-拍摄执行】`

目标：输入爆款视频/图文链接，下载原视频或原图文素材，生成可复刻但不照搬的：

- 视频分镜脚本
- 图文发布脚本
- 避重/差异化建议

## 运行

```bash
cd /home/ubuntu/selfmedia-tools
python3 -m selfmedia.deconstruct.viral_content.src.cli '【拆解】 https://v.douyin.com/xxxx/' --out data/media_vault/deconstruct_demo.json
```

不含 `【拆解】` 的输入会直接跳过，避免普通素材整理被误触发。

## Cookie

本模块优先复用 `selfmedia/ingest/content_flow` 的下载能力。Linux 服务器无图形界面时，建议通过同步文件提供 Cookie：

- 抖音：`/home/ubuntu/obsidian-自媒体/cookies/douyin.cookie`
- 小红书：`/home/ubuntu/obsidian-自媒体/cookies/xiaohongshu.cookie`

也支持环境变量：`DOUYIN_COOKIE_FILE` / `XHS_COOKIE_FILE`。


## 写入飞书多维表格

本模块写飞书，不写 Notion。传入 `--feishu-url`，或配置：

```bash
export FEISHU_BITABLE_URL='https://...feishu.cn/wiki/...?table=tblxxx&view=vewxxx'
```

多维表格只写索引、摘要、附件、文档链接。代码会用字段白名单和黑名单禁止写入 `final_script`、`republish_copy`、`video_storyboard`、`image_post_script`、`分镜脚本`、`图文脚本`、`可复制发布稿` 等长脚本字段。

附件字段由代码归类：

- `封面图/前五秒`：封面、首帧或预览素材；视频分析证据会对前 5 秒强制按 10fps 抽帧，5 秒之后按 fps=2 连续采样
- `原文件`：完整原视频或全部原图
- `原音频`：单独音频文件

写入顺序由代码保证：真实素材校验 -> LLM JSON schema 校验 -> 拆解文档创建并校验可访问 -> 附件归类校验 -> 最后写入多维表格。创作任务文档不由本拆解入口直接创建。

拆解视觉证据会分配稳定 ID：

- 视频前 5 秒高密度帧：`frame_001`、`frame_002` ...，元数据 `kind=first5s_frame`
- 视频 5 秒后关键帧：继续使用 `frame_xxx`，元数据 `kind=keyframe`
- 图文首图：`image_001`，元数据 `kind=cover_image`
- 图文后续原图：`image_002` ...，元数据 `kind=source_image`

LLM 输出的 `video_storyboard` / `image_post_script` 必须用 `evidence_asset_id` 引用这些 ID。代码会校验 ID 合法性，非法会重试，仍失败则中止。拆解文档里的「画面图」列使用上传后的飞书图片块，不写本地路径或 file token 文本。

## 视频理解模型路线

当前路线固定为本地抽帧/提音频形成证据包，全部关键帧/图文图片 parts 直接交给 `media_analysis` profile 的 Codex Responses API，由同一个主模型输出拆解 JSON。

主模型配置读取 `/home/ubuntu/selfmedia-tools/config/openclaw_bots.json` 的 `media_analysis` profile；`api_key` 可使用 `codex_auth_file` 从本机 Codex auth 文件解析。最终拆解继续校验 `evidence_asset_id`，主模型不可用则中止，不写文档、不写表。
