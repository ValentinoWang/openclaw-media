from __future__ import annotations

import json
from typing import Any

from ..models.message import Message
from .tag_router_common import CONTENT_OS_SCRIPT_GENERATION_MODEL, CONTENT_OS_SCRIPT_GENERATION_THINKING


class ContentOSRenderersMixin:
    def _render_content_os_creation_script_section(self, message: Message, parsed: dict[str, Any], reply: str, doc_link: str, record_id: str) -> str:
        payload = json.dumps({key: value for key, value in parsed.items() if key not in {"ok"}}, ensure_ascii=False, indent=2, default=str)
        return f"""来源：`{message.entry_tag}`

飞书创作文档：{doc_link or "未记录"}
创作记录 ID：`{record_id or "未记录"}`

## 原始输入

```text
{message.raw_text[:3000]}
```

## 生成结果

```text
{(reply or parsed.get("reply") or "未记录")[:5000]}
```

## 结构化结果

```json
{payload[:8000]}
```
"""
    def _render_content_os_publish_pack_section(self, message: Message, parsed: dict[str, Any], reply: str, doc_link: str, record_id: str) -> str:
        return f"""来源：`{message.entry_tag}`

- 飞书创作文档：{doc_link or "未记录"}
- 创作记录 ID：`{record_id or "未记录"}`
- 发布动作负责人：人

## 发布前使用稿

```text
{(reply or parsed.get("reply") or "未记录")[:5000]}
```

## 发布检查

- [ ] 标题已人工确认
- [ ] 正文/字幕已人工确认
- [ ] 封面已人工确认
- [ ] 平台话题已人工确认
- [ ] 成片路径已回填
- [ ] 发布链接已回填
"""
    def _render_content_os_data_review_section(self, message: Message, parsed: dict[str, Any], reply: str) -> str:
        payload = json.dumps({key: value for key, value in parsed.items() if key not in {"ok"}}, ensure_ascii=False, indent=2, default=str)
        return f"""复盘来源：`{message.entry_tag}`

飞书复盘文档：{parsed.get("doc_link") or "未记录"}
复盘记录 ID：`{parsed.get("record_id") or parsed.get("review_id") or "未记录"}`

## 原始输入

```text
{message.raw_text[:3000]}
```

## 复盘结论

```text
{(reply or parsed.get("reply") or "未记录")[:5000]}
```

## 结构化结果

```json
{payload[:8000]}
```
"""
    def _render_content_os_project_index(
        self,
        *,
        project_id: str,
        idea_id: str,
        title: str,
        theme: str,
        local_project_path: str,
        batch_note_path: str,
        inbox_batch_path: str,
        local_material_binding: str,
        mac_task_status: str,
        platform: str,
        content_type: str,
        created_date: str,
        account: str,
        inspiration_doc: str,
        inspiration_record_id: str,
    ) -> str:
        next_owner = "mac_openclaw" if local_material_binding == "bound" and mac_task_status == "ready" else "human"
        task_status_line = (
            "- [x] 云端派发 Mac 本地素材分析任务"
            if mac_task_status == "ready"
            else "- [ ] 等人在 Mac 上把素材批次和项目包绑定，再派发 Mac 本地素材分析任务"
        )
        return f"""---
spec_version: content_os_v0.2
doc_type: project_overview
project_id: {project_id}
idea_id: {idea_id}
title: {self._yaml_scalar(title)}
theme: {self._yaml_scalar(theme or title)}
status: captured
project_revision: 1
editor_backend: handoff_pack
owner: cloud_openclaw
owner_agent: cloud_openclaw
next_owner: {next_owner}
next_action: {self._yaml_scalar("等待云端核对计划材料" if local_material_binding == "bound" else "补充本地素材绑定或确认下一步")}
blocked: false
blocked_reason: ""
created_at: {created_date}
updated_at: {created_date}
local_project_path: {self._yaml_scalar(local_project_path)}
batch_note_path: {self._yaml_scalar(batch_note_path)}
inbox_batch_path: {self._yaml_scalar(inbox_batch_path)}
local_material_binding: {local_material_binding}
target_platforms: {self._yaml_scalar(platform or "未指定")}
content_type: {self._yaml_scalar(content_type or "短视频")}
---

# 项目目标

{theme or title}

# 本地素材绑定

```text
local_material_binding: {local_material_binding}
local_project_path: {local_project_path or "未绑定"}
batch_note_path: {batch_note_path or "未绑定"}
inbox_batch_path: {inbox_batch_path or "未绑定"}
```

# 当前状态

- [x] 云端根据飞书创作灵感完成立项
- [x] 云端生成 `01_idea_card.md`
- [x] 云端生成 `02_project_brief.md`
- [x] 云端生成 `04_script.md` 初稿
{task_status_line}
- [ ] Mac 完成本地素材分析
- [ ] Mac 输出 Storyboard / EDL
- [ ] 腾讯云核对 Mac 回传的证据后再决定是否进入剪辑准备阶段
- [ ] 人工剪辑和发布

# 关联文件

- [[01_idea_card]]
- [[02_project_brief]]
- [[04_script]]
- [[03_material_match_report]]
- [[05_storyboard]]
- [[06_edit_decision_list.json]]
- [[08_local_assets]]
- [[09_publish_pack]]
- [[10_review]]

# 飞书来源

- 创作运行记录：`{inspiration_record_id or "未记录"}`
- 任务池文档：{inspiration_doc or "未记录"}
- 账号：{account or "未指定"}

# 写入边界

- 项目整体阶段、当前版本和剪辑方式只由本文件 frontmatter 保存。
- 腾讯云 OpenClaw 主写：`01_idea_card.md`、`02_project_brief.md`、`04_script.md`、`09_publish_pack.md`、`10_review.md`。
- Mac OpenClaw 主写：`03_material_match_report.md`、`05_storyboard.md`、`06_edit_decision_list.json`、`08_local_assets.md`。
- 原始素材、剪辑工程和导出文件继续留在 Mac 本地项目目录。
"""
    def _render_content_os_idea_card(
        self,
        *,
        idea_id: str,
        project_id: str,
        title: str,
        theme: str,
        result: dict[str, Any],
        platform: str,
        account: str,
        emotion: str,
        created_date: str,
        source_text: str,
        inspiration_doc: str,
        inspiration_record_id: str,
    ) -> str:
        hooks = self._markdown_list(result.get("hook_options") or [])
        strengths = self._markdown_list(result.get("strengths") or [])
        risks = self._markdown_list(result.get("risks") or [])
        return f"""---
spec_version: content_os_v0.2
doc_type: idea_card
idea_id: {idea_id}
project_id: {project_id}
evidence_status: selected
created_by: cloud_openclaw
created_at: {created_date}
---

# 选题卡：{title}

## 一句话选题

{theme or result.get("cleaned_inspiration") or title}

## 平台与账号

- 平台：{platform or "未指定"}
- 账号：{account or "未指定"}
- 情绪：{emotion or "未指定"}

## 内容钩子

{hooks or "- 待 Mac 根据素材补强"}

## 已有优势

{strengths or "- 待验证"}

## 风险与待验证

{risks or "- 待 Mac 素材分析后补充"}

## 飞书来源

- 创作运行记录：`{inspiration_record_id or "未记录"}`
- 任务池文档：{inspiration_doc or "未记录"}

## 原始输入摘要

```text
{source_text[:3000]}
```
"""
    def _render_content_os_project_brief(
        self,
        *,
        project_id: str,
        idea_id: str,
        title: str,
        theme: str,
        local_project_path: str,
        batch_note_path: str,
        inbox_batch_path: str,
        local_material_binding: str,
        mac_task_status: str,
        result: dict[str, Any],
        platform: str,
        account: str,
        emotion: str,
        track: str,
        content_type: str,
        created_date: str,
    ) -> str:
        next_actions = self._markdown_list(result.get("next_actions") or [])
        formats = self._markdown_list(result.get("publishable_formats") or [])
        outline = self._markdown_list(result.get("script_outline") or [])
        material_requirements = self._markdown_list(
            result.get("material_requirements")
            or result.get("needed_materials")
            or result.get("required_materials")
            or result.get("material_checklist")
            or []
        )
        default_next = (
            "- Mac 读取 task 后先完成素材分析，再回传 result。"
            if mac_task_status == "ready"
            else "- 人先在 Mac 上用批次说明把真实素材绑定到本项目；腾讯云不判断本地素材是否存在。"
        )
        return f"""---
spec_version: content_os_v0.2
doc_type: project_brief
project_id: {project_id}
idea_id: {idea_id}
evidence_status: current
owner_agent: cloud_openclaw
next_owner: {"mac_openclaw" if mac_task_status == "ready" else "human"}
created_at: {created_date}
local_material_binding: {local_material_binding}
---

# Project Brief：{title}

## 项目目标

{theme or result.get("cleaned_inspiration") or title}

## 本地素材绑定状态

```text
local_material_binding: {local_material_binding}
local_project_path: {local_project_path or "未绑定"}
batch_note_path: {batch_note_path or "未绑定"}
inbox_batch_path: {inbox_batch_path or "未绑定"}
```

腾讯云只记录协议层绑定线索，不声称 Mac 本地已有这些素材；真实素材、画质、可用性和缺口只能由 Mac 扫描后回写。

## 内容定位

| 维度 | 要求 |
| --- | --- |
| 平台 | {self._md_cell(platform or "未指定")} |
| 账号 | {self._md_cell(account or "未指定")} |
| 内容类型 | {self._md_cell(content_type or "短视频")} |
| 赛道 | {self._md_cell(track or "未指定")} |
| 情绪 | {self._md_cell(emotion or "未指定")} |

## 建议结构

{outline or "- 待 Mac 根据素材补强"}

## 素材需求

{material_requirements or "- 待云端初稿或人工补充素材需求；这不是本地素材事实。"}

## 建议产物

{formats or "- 主短视频"}

## Mac 素材匹配任务

Mac OpenClaw 在本地素材绑定后，读取真实素材并输出：

- `03_material_match_report.md`：素材是否足够、关键片段分类、缺口。
- `05_storyboard.md`：按镜头顺序组织故事板。
- `06_edit_decision_list.json`：剪辑执行单，包含素材路径、入出点、镜头用途。
- `08_local_assets.md`：本地素材 manifest、关键帧摘要、Final 预期路径。

## 下一步

{next_actions or default_next}
"""
    def _render_content_os_initial_script(
        self,
        *,
        project_id: str,
        idea_id: str,
        title: str,
        result: dict[str, Any],
        platform: str,
        created_date: str,
        record_text: str,
    ) -> str:
        title_options = self._markdown_list(result.get("title_options") or [])
        hooks = self._markdown_list(result.get("hook_options") or [])
        outline = self._markdown_list(result.get("script_outline") or [])
        formats = self._markdown_list(result.get("publishable_formats") or [])
        risks = self._markdown_list(result.get("risks") or [])
        direction = str(result.get("creative_direction") or result.get("cleaned_inspiration") or "")
        return f"""---
spec_version: content_os_v0.2
doc_type: script
project_id: {project_id}
idea_id: {idea_id}
evidence_status: draft
writer_agent: cloud_openclaw
owner_agent: cloud_openclaw
next_owner: mac_openclaw
generation_model: {CONTENT_OS_SCRIPT_GENERATION_MODEL}
generation_thinking: {CONTENT_OS_SCRIPT_GENERATION_THINKING}
created_at: {created_date}
---

# 初稿脚本：{title}

## 一句话主线

{direction}

## 成片目标

| 项目 | 要求 |
| --- | --- |
| 时长 | 50-60 秒；如果素材证据不足，Mac 可建议改为 30-45 秒。 |
| 形式 | 第一视角 / 第三视角 / 字幕 / 原声按素材情况组合，不允许只停留在选题描述。 |
| 核心悬念 | 前 3 秒必须提出一个可验证的问题、结果或冲突。 |
| 核心情绪 | 中段必须让观众感到情绪变化，而不是平铺信息。 |
| 结果揭晓 | 结尾必须兑现开头悬念，或明确留下下一条钩子。 |
| 平台 | {platform or "未指定"} |

## 标题候选

{title_options or "- 待补充"}

## 封面候选

| 画面 | 字幕 |
| --- | --- |
| 最能证明结果或冲突的一帧 | {title} |
| 情绪最强的一帧 | 把核心悬念写成 8-12 个字 |
| 人物动作最清楚的一帧 | 用结果数字或反差词做封面字 |

## 开头钩子候选

{hooks or "- 待补充"}

## 完整时间轴脚本

| 时间 | 画面 | 旁白 / 字幕 | 声音与剪辑 |
| --- | --- | --- | --- |
| 0.0-2.0s | 用最强结果、冲突或动作画面开场。没有强画面时，用素材中最清楚的人物/场景建立主题。 | 直接抛出核心悬念：这条内容到底要验证什么？ | 快切；保留原声冲击点；字幕不要超过一行。 |
| 2.0-5.0s | 补一帧背景证据：人物、地点、任务、挑战条件。 | 交代“我是谁 / 在哪 / 要做什么”。 | 音乐压低，保证信息读得清楚。 |
| 5.0-12.0s | 第一组过程镜头，优先使用动作开始、任务开始、冲突开始。 | 说明第一阶段的心理或判断。 | 节奏快，镜头 1-2 秒一切。 |
| 12.0-20.0s | 第二组过程镜头，必须出现变化：速度、表情、环境、身体状态或事件走向。 | 观众需要知道：情况开始不一样了。 | 用原声、呼吸、现场声或画面晃动做情绪证据。 |
| 20.0-32.0s | 进入核心段落。优先安排最有情绪张力的素材。 | 把“难点 / 反差 / 转折”讲清楚。 | 可做一次音乐下压或短暂停顿，突出转折。 |
| 32.0-42.0s | 结果前最后推进。用多角度或证据镜头避免只靠口播。 | 把观众带到结果揭晓前。 | 镜头切换跟动作节奏走，不要平均铺。 |
| 42.0-50.0s | 结果揭晓：成绩、结论、反应、对比或证据截图。 | 兑现开头悬念。 | 结果字幕定格 0.5-1 秒。 |
| 50.0-60.0s | 情绪收束或下一条钩子。 | 给出一句人味结尾，或明确预告下一条。 | 结尾留干净画面，方便停留和转场。 |

## 口播版

```text
开头：用一句话抛出悬念。

背景：我为什么要做这件事，以及它和账号人设/上一条内容有什么关系。

过程第一段：一开始我以为还可以控制。

过程第二段：中途开始出现真实变化。

核心转折：这里是最难、最痛、最意外或最值得看的地方。

结果：直接揭晓结果，不要绕。

结尾：把结果落到人的感受，并给下一条留下钩子。
```

## 字幕版

```text
第 1 屏：核心悬念
第 2 屏：任务条件
第 3 屏：第一阶段状态
第 4 屏：变化开始
第 5 屏：最难的一段
第 6 屏：结果揭晓
第 7 屏：一句情绪收束 / 下一条预告
```

## 原始结构参考

{outline or "- 待 Mac 根据素材补强"}

## 剪辑节奏

- 前 0-5 秒必须交代悬念、人物和任务，不允许只做氛围铺垫。
- 中段必须至少出现一次明确转折：状态变化、信息变化、情绪变化或结果风险。
- 关键结果必须有画面或数据证据支撑；如果没有，Mac 需要标记为缺口。
- 字幕使用短句，不要把长段文案塞进同一屏。
- 结尾必须服务发布：要么完成情绪落点，要么引导下一条。

## Mac 二次修订重点

Mac OpenClaw 读取素材后，需要优先确认：

1. 哪些镜头能承担开头 3 秒悬念。
2. 哪些镜头能证明过程变化，而不是只有重复画面。
3. 哪些镜头能证明结果、成绩、结论或关键事实。
4. 哪些原声可以保留：呼吸、脚步、环境声、现场反馈、人物反应。
5. 是否需要拆成两条：主片 + 完整过程 / 复盘 / 花絮。
6. 如果素材无法支撑当前脚本，必须在 `03_material_match_report.md` 里写明缺口，并给出替代结构。

## 素材匹配清单

| 素材类型 | 必须程度 | 用途 |
| --- | --- | --- |
| 开头强钩子画面 | 必须 | 3 秒内留住观众 |
| 过程变化证据 | 必须 | 支撑中段叙事 |
| 结果证据 | 必须 | 兑现悬念 |
| 人物反应 / 情绪画面 | 强烈建议 | 形成记忆点 |
| 环境 / 场景交代 | 建议 | 建立真实感 |
| 原声素材 | 建议 | 增强沉浸感 |

## 发布包草案

### 平台形式

{formats or "- 主短视频"}

### 正文方向

```text
用 1-2 句交代挑战/事件，用 1 句说结果或感受，最后用 1 句引导下一条或评论。
```

### 话题方向

```text
#账号人设 #内容主题 #平台场景 #情绪关键词
```

## 待验证风险

{risks or "- 待 Mac 根据素材补充"}

## 当前版本说明

- 目标平台：{platform or "未指定"}
- 这是云端初稿，不是 Final。
- `04_script.md` 必须达到可剪辑执行稿粒度：时间轴、画面、口播/字幕、声音剪辑、Mac 检查项和发布草案都要具备。
- Mac 需要根据真实素材、画面稳定性、证明镜头、声音和结果证据进行二次修订。

## 原始任务卡摘录

```text
{record_text[:5000]}
```
"""
    def _render_content_os_material_match_task(
        self,
        *,
        task_id: str,
        project_id: str,
        idea_id: str,
        local_project_path: str,
        batch_note_path: str = "",
        inbox_batch_path: str = "",
        status: str = "ready",
        project_revision: int = 1,
        editor_backend: str = "handoff_pack",
    ) -> str:
        return f"""spec_version: content_os_v0.2
doc_type: mac_task
task_id: {task_id}
task_type: local_material_match
created_by: cloud_openclaw
owner: mac_openclaw
status: {status}

project_id: {project_id}
project_revision: {project_revision}
idea_id: {idea_id}
change_request_id: ""
editor_backend: {editor_backend}
human_confirmed_impact: false

inputs:
  project_brief_path: 08_内容项目/{project_id}/02_project_brief.md
  script_path: 08_内容项目/{project_id}/04_script.md
  batch_note_path: {self._yaml_scalar(batch_note_path)}
  inbox_batch_path: {self._yaml_scalar(inbox_batch_path)}
  local_project_hint: {self._yaml_scalar(self._content_os_path_name(local_project_path))}
  local_project_path: {self._yaml_scalar(local_project_path)}

expected_outputs:
  - 08_内容项目/{project_id}/03_material_match_report.md
  - 08_内容项目/{project_id}/05_storyboard.md
  - 08_内容项目/{project_id}/06_edit_decision_list.json
  - 08_内容项目/{project_id}/08_local_assets.md

allowed_actions:
  - analyze_project
  - match_materials_to_brief
  - generate_storyboard_edl
  - write_local_assets

notes:
  - 不要把原始素材搬进 Obsidian。
  - 先分析本地素材，再按 brief 匹配镜头和生成 storyboard / EDL。
  - Mac 只写 result 和 Mac 负责的项目产物，不推进项目主状态。
"""
