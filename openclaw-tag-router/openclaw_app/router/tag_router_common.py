from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

SELFMEDIA_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_ROOT))

from common.llm_settings import load_profile_llm_settings

from ..models.message import Message
from ..models.task import TaskResult
from ..services.archive_service import ArchiveService
from ..services.completion_guard import CompletionGuard
from ..services.content_flow_client import ContentFlowClient
from ..services.feishu_service import FeishuService
from ..services.reminder_service import ReminderService
from ..services.reply_service import ReplyService
from ..services.rule_service import RuleService
from ..services.schedule_service import ScheduleService
from ..services.utils import cleanup_generated_file_duplicates, contains_link, ensure_dir, format_display_time, make_record_id, now_in_tz, safe_slug
from ..services.vlog_storage_service import VlogStorageService
from .tag_capabilities import (
    TAG_CAPABILITIES,
    GENERIC_TAGS,
    RESEARCH_KNOWLEDGE_TAGS,
    SYSTEM_TAGS,
    TAG_LABELS,
    UNIVERSAL_KNOWLEDGE_TAGS,
)
from .media_intake_guides import (
    GUIDES,
    GUIDE_MODEL,
    GUIDE_THINKING,
    is_media_intake_tag,
    render_media_intake_prompt,
)
from .openclaw_bot_llm import bot_runtime, display_openclaw_model, profile_config, profile_provider_runtime, profile_runtime


SOCIAL_THEORY_TAGS = ("女性爱", "性兴趣", "风控", "性资源", "行动")
BRACKET_THEORY_RE = re.compile(r"【(?P<tag>[^】\n]{1,32})】")
CREATION_TAG_RE = re.compile(r"^创作(?:>(小红书|抖音))?$")
MATERIAL_CREATION_TAG_RE = re.compile(r"^素材创作(?:>(小红书|抖音))?$")
TAG_CAPABILITY_MAP = {capability.label: capability for capability in TAG_CAPABILITIES}
BOT_CAPABILITY_IDENTITIES = {
    "media": "Media bot",
    "daily": "Daily bot",
    "knowledge": "Knowledge bot",
    "social": "Social bot",
    "main": "OpenClaw bot",
    "openclaw": "OpenClaw bot",
}
COMMON_ENTRY_FACTS = (
    "`【说明】` 是所有 Bot 的唯一能力说明入口。",
)


def run_media_subprocess_with_watchdog(
    command: list[str],
    *,
    env: dict[str, str] | None,
    timeout: int,
    cwd: str | Path | None = None,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    heartbeat_seconds = max(10, int(float(os.getenv("OPENCLAW_TAG_ROUTER_SUBPROCESS_WATCHDOG_HEARTBEAT_SECONDS", "60"))))
    started_at = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    watchdog_lines: list[str] = []
    pending_input = input
    while True:
        elapsed = time.monotonic() - started_at
        remaining = max(0.1, float(timeout) - elapsed)
        wait_for = min(float(heartbeat_seconds), remaining)
        try:
            stdout, stderr = process.communicate(input=pending_input, timeout=wait_for)
            if watchdog_lines:
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
            return subprocess.CompletedProcess(command, process.returncode, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            pending_input = None
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout:
                process.kill()
                stdout, stderr = process.communicate()
                watchdog_lines.append(f"[watchdog] timeout_after={int(elapsed)}s limit={timeout}s command={command[0]}")
                stderr = "\n".join([*(line for line in watchdog_lines if line), stderr or ""]).strip()
                return subprocess.CompletedProcess(command, -9, stdout or "", stderr)
            watchdog_lines.append(f"[watchdog] still_running elapsed={int(elapsed)}s command={command[0]}")
COMMON_BOUNDARY_FACTS = (
    "`【说明】` 只返回能力说明，不执行归档、创作、入库或同步。",
    "自然语言能力展示请求只回复 `请发送【说明】`。",
)
COMMON_ROUTING_FACTS = (
    "正文写 `media` 时，`【说明】` 会切换到 Media bot 的能力说明。",
    "正文写 `daily` 时，`【说明】` 会切换到 Daily bot 的能力说明。",
    "正文写 `knowledge` 时，`【说明】` 会切换到 Knowledge bot 的能力说明。",
    "正文写 `social` 时，`【说明】` 会切换到 Social bot 的能力说明。",
    "正文写 `main` 或 `openclaw` 时，`【说明】` 会切换到 OpenClaw bot 的能力说明。",
    "飞书网关没有传入明确 bot 身份时，`【说明】` 不自动猜测 Bot。",
)
BOT_CAPABILITY_EXTRA_LABELS = {
    "Media bot": {"自媒体知识", "归档", "补全", "认知", "学习", "学习-整理"},
    "Daily bot": {"自媒体知识", "转写", "转写-文字", "归档", "补全", "认知", "学习", "学习-整理"},
    "Knowledge bot": {"转写", "转写-文字"},
    "Social bot": {"自媒体知识", "转写", "转写-文字", "归档", "补全", "认知", "学习", "学习-整理", "博主", "博主-入库"},
}
BOT_ENTRY_FACTS = {
    "Media bot": (
        "`【创作】`、`【创作>小红书】`、`【创作>抖音】`、`【创作-拍摄执行】`、`【素材创作】`、`【素材创作>小红书】`、`【素材创作>抖音】`、`【创作-灵感】`、`【拆解-再创】` 统一写入 `03_CreationRuns_创作运行` 或创作任务池子文档；表格字段使用可读字段，不写可见 `*JSON` 字段。",
        "`【自媒体知识】` 可以发给 Media bot，但执行链路是知识表写入，不进入媒体素材链路。",
        "`【归档】` 可以发给 Media bot，但执行者是 Knowledge bot。",
        "`【补全】` 可以发给 Media bot，但执行者是 Knowledge bot。",
        "`【认知】` 可以发给 Media bot，但执行者是 Knowledge bot。",
        "`【学习】` 可以发给 Media bot，但执行者是 Knowledge bot。",
        "`【学习-整理】` 可以发给 Media bot，但执行者是 Knowledge bot。",
    ),
    "Daily bot": (
        "`【待办】` 用于创建 Obsidian 当日 checklist，或在有明确时间/提醒/截止时创建飞书提醒并留下 Obsidian 镜像 checkbox；知识记录、素材记录或链接查看诉求也只整理成待办，不打开 Base/表格/文档、不请求飞书用户授权。",
        "`【日程】` 用于创建明确时间的日历事件。",
        "`【待办-开发】` 用于创建需要追溯、复盘和回档的正式开发任务。",
        "`【今日】` 用于返回今日提醒、日程、待办和开发需求清单。",
        "`【开发-完成】` 和 `【开发-验证】` 用于推进开发需求状态。",
        "`【自媒体知识】` 可以发给 Daily bot，但执行链路是知识表写入，不进入日程或待办链路。",
        "`【转写】` 可以发给 Daily bot，但执行链路是会议纪要转写，必须生成会议纪要和原字稿，不进入日程或待办链路。",
        "`【转写-文字】` 可以发给 Daily bot，但只整理已有文字稿，必须生成会议纪要和原字稿，不进入日程或待办链路。",
        "`【归档】` 可以发给 Daily bot，但执行者是 Knowledge bot。",
        "`【补全】` 可以发给 Daily bot，但执行者是 Knowledge bot。",
        "`【认知】` 可以发给 Daily bot，但执行者是 Knowledge bot。",
        "`【学习】` 可以发给 Daily bot，但执行者是 Knowledge bot。",
        "`【学习-整理】` 可以发给 Daily bot，但执行者是 Knowledge bot。",
    ),
    "Knowledge bot": (
        "`【归档】` 是 Knowledge bot 的原生知识归档入口。",
        "`【补全】` 是 Knowledge bot 的原生文字补全入口。",
        "`【认知】` 是 Knowledge bot 的原生认知沉淀入口。",
        "`【学习】` 是 Knowledge bot 的原生学习拆解入口。",
        "`【学习-整理】` 是 Knowledge bot 的原生整理类学习拆解入口。",
        "`【转写】` 可以发给 Knowledge bot，但执行链路是会议纪要转写，必须生成会议纪要和原字稿，不等同于 `【补全】`。",
        "`【转写-文字】` 可以发给 Knowledge bot，用于把已有语音转文字稿合并成会议纪要和原字稿。",
    ),
    "Social bot": (
        "`【社交】` 是 Social bot 的原生人物交互档案入口。",
        "`【人脉】` 是 Social bot 的原生无性关系或合作人脉档案入口。",
        "`【自媒体知识】` 可以发给 Social bot，但执行链路是知识表写入，不进入社交档案链路。",
        "`【转写】` 可以发给 Social bot，但默认执行链路是会议纪要转写，必须生成会议纪要和原字稿，不进入社交档案链路。",
        "`【转写-文字】` 可以发给 Social bot，但只生成会议纪要和原字稿，不进入社交档案链路。",
        "`【归档】` 可以发给 Social bot，但执行者是 Knowledge bot。",
        "`【补全】` 可以发给 Social bot，但执行者是 Knowledge bot。",
        "`【认知】` 可以发给 Social bot，但执行者是 Knowledge bot。",
        "`【学习】` 可以发给 Social bot，但执行者是 Knowledge bot。",
        "`【学习-整理】` 可以发给 Social bot，但执行者是 Knowledge bot。",
        "`【博主】` 可以发给 Social bot，用于商务邀约前查询已归档博主的主页链接。",
        "`【博主-入库】` 可以发给 Social bot，用于手工写入达人账号档案，或用平台+平台ID自动补全候选；自动补全必须用 run_id 确认后才写入。",
    ),
    "OpenClaw bot": (
        "`【说明】main` 会显示 OpenClaw bot 的统一入口能力。",
        "`【说明】media` 会显示 Media bot 的能力。",
        "`【说明】daily` 会显示 Daily bot 的能力。",
        "`【说明】knowledge` 会显示 Knowledge bot 的能力。",
        "`【说明】social` 会显示 Social bot 的能力。",
    ),
}
BOT_BOUNDARY_FACTS = {
    "Media bot": (
        "Media bot 业务标签只有空正文时只返回填写模板，不写表、不建文档、不生成稿件。",
        "带录音附件的 `【转写】` 直接进入转写流程，不停在填写模板。",
        "带上传素材的 `【素材创作】` 直接处理素材，不停在填写模板。",
        "带上传素材的 `【灵感>vlog】` 直接处理素材，不停在填写模板。",
    ),
    "Daily bot": (
        "Daily bot 的 `【待办】` 先由 LLM intake 分流；普通清单写 Obsidian checklist，提醒型待办写飞书提醒并留 Obsidian 镜像。",
        "Daily bot 只把 `【日程】` 写入日历事件链路。",
        "Daily bot 把 `【待办-开发】` 写入正式开发任务卡、Obsidian checklist 与飞书多维表格结构化台账。",
        "`【今日】` 只生成轻量执行清单，不打开或改写多维表格。",
        "`【开发-完成】`、`【开发-验证】` 更新正式开发任务状态；完整复盘由 checklist 勾选后的 Mac 侧 Codex high 生成。",
        "`【自媒体知识】` 不会创建日程或待办。",
        "`【转写】` 不会创建日程或待办。",
        "`【转写-文字】` 不会创建日程或待办。",
    ),
    "Knowledge bot": (
        "`【补全】` 只处理已经提供的转写文本。",
        "`【补全】` 不直接处理原始音频 ASR。",
        "`【认知】` 只处理已经提供的文字或口语化记录，不直接处理原始音频 ASR。",
        "`【转写-文字】` 只处理已有文字稿，不调用原始音频 ASR。",
        "普通文字里的“学习”不会触发 `【学习】`。",
        "`【学习-整理】` 固定进入整理类学习拆解。",
    ),
    "Social bot": (
        "裸理论标签不是公开入口，必须写在 `【社交】` 正文里。",
        "`【自媒体知识】` 不会写入社交档案。",
        "`【转写】` 默认不会写入社交档案。",
        "`【转写-文字】` 默认不会写入社交档案。",
        "`【博主】`、`【博主-入库】` 只读写 Media OS 的 `06_CreatorProfiles_达人账号档案`，不写入社交私档案。",
        "`【人脉】` 默认只写本地与 Obsidian，不同步飞书云文档。",
    ),
    "OpenClaw bot": (
        "OpenClaw bot 只做统一分流说明，不读取其他 Bot 的私有记忆。",
        "明显属于专用 Bot 的任务优先交给对应 Bot。",
    ),
}
BOT_ROUTING_FACTS = {}
TAG_USAGE_FORMATS = {
    "待办": (
        "清单格式：`【待办】购买\\n1. 杠铃杆\\n2. 起泡器`，写入 Obsidian 周记当天 checklist。",
        "提醒格式：`【待办】2026-06-28 18:00 前购买杠铃杆，提前30分钟提醒`，写入飞书提醒表并在 Obsidian 留镜像 checkbox。",
        "推荐字段：普通清单写编号列表；提醒型可写 `事项：`、`时间：`、`提醒：`、`备注：`。",
    ),
    "日程": (
        "最简格式：`【日程】明天上午10点 开项目会`。",
        "详细格式：`【日程】\\n标题：项目会\\n时间：明天上午10点\\n地点：飞书会议\\n参与人：A、B\\n提醒：提前1小时\\n备注：讨论5月内容排期`。",
        "推荐字段：`标题：`、`时间：`、`地点：`、`参与人：`、`提醒：`、`备注：`。",
    ),
    "待办-开发": (
        "最简格式：`【待办-开发】\\n机器：VM-0-14-ubuntu\\n地址：ubuntu@106.52.146.37\\n任务：修复 Knowledge bot 归档后 Mac 不同步的问题`。",
        "本机格式：`【待办-开发】\\n机器：MacBook Pro\\n地址：localhost\\n任务：修复本机轮询脚本无法识别 checklist 完成\\n验收：勾选后生成详细任务文档`。",
        "推荐字段：`机器：` 可从 `VM-0-14-ubuntu（云服务器）/ 15 M3 MacBook Air（本机 Mac）` 选；`地址：` 可从 `ubuntu@106.52.146.37（云服务器）/ localhost（本机 Mac）` 选；再补 `任务：`、`验收：`、`补充：`。飞书写入时间由 bot 自动写入，不需要人工填写。",
    ),
    "今日": (
        "最简格式：`【今日】`。",
        "可选格式：`【今日】开发` 或 `【今日】提醒`，用于表达你只想看某类清单；当前实现会返回本地归档里的今日执行清单。",
        "推荐字段：通常不需要字段。",
    ),
    "整理": (
        "格式：`【整理】最近10条内容素材`。",
        "可选格式：`【整理】今天` 或 `【整理】灵感 最近5条`。",
        "用途：汇总最近本地归档记录，帮助快速回看。",
    ),
    "开发-完成": (
        "按ID格式：`【开发-完成】ID：20260523-180747-feishu-开发-5afb`。",
        "按关键词格式：`【开发-完成】关键词：修复 Knowledge bot 归档同步`。",
        "推荐字段：`ID：`、`关键词：`、`结果：`。",
    ),
    "开发-验证": (
        "按ID格式：`【开发-验证】ID：20260523-180747-feishu-开发-5afb`。",
        "按关键词格式：`【开发-验证】关键词：修复 Knowledge bot 归档同步`。",
        "推荐字段：`ID：`、`关键词：`、`验收：`、`测试结果：`。",
    ),
    "内容素材": (
        "链接格式：`【内容素材】\\n链接：https://example.com/post\\n平台：小红书\\n用途：选题参考\\n备注：开头钩子好`。",
        "文字格式：`【内容素材】\\n标题：一个可复用选题\\n内容：...\\n标签：AI工具,自媒体`。",
        "推荐字段：`链接：`、`平台：`、`标题：`、`内容：`、`用途：`、`标签：`、`备注：`。",
    ),
    "活动": (
        "链接格式：`【活动】\\n平台：小红书\\n活动链接：https://example.com\\n活动时间：5月20日-6月1日\\n主话题：#校园生活`。",
        "Brief格式：`【活动】` 后直接粘贴活动 Brief 原文。",
        "推荐字段：`平台：`、`活动链接：`、`活动时间：`、`主话题：`、`奖励：`、`提交要求：`。",
    ),
    "补充": (
        "回复文档时：回复目标文档消息后发送 `【补充】这段需要并入原文`。",
        "显式链接格式：`【补充】\\n文档链接：https://...\\n补充内容：...`。",
        "推荐字段：`文档链接：`、`ID：`、`补充内容：`。",
    ),
    "自媒体知识": (
        "链接格式：`【自媒体知识】\\n链接：https://xhslink.com/...\\n平台：小红书\\n备注：重点提取选题方法`。",
        "带文案格式：`【自媒体知识】\\n链接：...\\n全部文案：作品正文和 tags\\n全部内容：转写或图文 OCR\\n问题：...`。",
        "推荐字段：`链接：`、`平台：`、`标题：`、`目标人群：`、`核心痛点：`、`全部文案：`、`全部内容：`、`备注：`、`问题：`；图文/视频由后台自动识别。",
    ),
    "转写": (
        "常规格式：先上传录音附件，再发送 `【转写】`。",
        "补充格式：`【转写】\\n主题：会议主题\\n参与人：A、B\\n要求：标注说话人并生成纪要`。",
        "推荐字段：`主题：`、`参与人：`、`要求：`；录音本身通过附件上传。",
    ),
    "转写-文字": (
        "正文格式：`【转写-文字】\\n主题：会议主题\\n文字稿：...`。",
        "附件格式：上传 `.txt` 或 `.md` 后发 `【转写-文字】\\n主题：会议主题`。",
        "推荐字段：`主题：`、`参与人：`、`文字稿：`、`补充要求：`；不做原始音频 ASR。",
    ),
    "周记": (
        "格式：`【周记】20260525-20260531`。",
    ),
    "归档": (
        "格式：`【归档】\\n日期：2026-05-23\\n标题：一句话标题\\n内容：需要归档的正文`。",
        "简写格式：`【归档】需要归档的一段知识或想法`。",
        "推荐字段：`日期：`、`标题：`、`内容：`、`来源：`。",
    ),
    "补全": (
        "格式：`【补全】\\n日期：2026-05-23\\n主题：录音主题\\n原文：已经转出来的文字稿`。",
        "注意：`【补全】` 处理已有文字，不直接做原始音频 ASR。",
        "推荐字段：`日期：`、`主题：`、`原文：`、`补充要求：`。",
    ),
    "认知": (
        "格式：`【认知】观察、判断或经历`；多字段可写 `日期/标题/内容/待确认`。",
        "注意：详文写 `认知/`，周记留宏观总结、5句摘要和链接；默认不写飞书。",
    ),
    "学习": (
        "格式：`【学习】API` 或 `【学习】\\n主题：API\\n材料：...`。",
        "推荐字段：`主题：`、`材料：`、`目标：`、`难点：`。",
    ),
    "学习-整理": (
        "格式：`【学习-整理】\\n主题：课程笔记\\n材料：...`。",
        "推荐字段：`主题：`、`材料：`、`目标：`；该入口强制按整理类学习沉淀。",
    ),
    "商务>ID": (
        "格式：`【商务>ID】\\n平台：小红书\\n主页链接：https://example.com/user\\n品牌：某品牌\\n商务信息：邮箱/微信/报价`。",
        "推荐字段：`平台：`、`主页链接：`、`账号ID：`、`品牌：`、`商务信息：`、`备注：`。",
    ),
    "删除": (
        "预览格式：`【删除】20260412-030515-qq-灵感-0056` 或 `【删除】run_router_xxx`。",
        "执行格式：`【删除】确认删除 20260412-030515-qq-灵感-0056`。",
        "注意：未明确写确认删除时只返回预览，不删除 archive/inbox、json、markdown、中间产物、文档或文件。",
    ),
    "博主": (
        "查看全部：`【博主】`。",
        "筛选格式：`【博主】平台：抖音`、`【博主】平台ID：93130816637`、`【博主】清华` 或 `【博主】小王`。",
        "返回必须包含：外部唯一ID（平台:平台ID）、博主IP、账号名称/作者ID、结构化身份信息、主页和档案链接。",
    ),
    "博主-入库": (
        "手工格式：`【博主-入库】\\n账号名称：清华AI小王冲一级\\n平台：抖音\\n平台ID：93130816637\\n身份定位：清华AI硕短跑博主\\n身份标签：清华、AI、体育生、短跑、校园`。",
        "自动补全：`【博主-入库】\\n平台：抖音\\n平台ID：22654404058\\nID类型：抖音号\\n链接：https://v.douyin.com/...\\n模式：自动补全`，只生成候选，不写库。",
        "确认写入：`【博主-入库】\\n确认写入\\nrun_id：...`。",
        "推荐字段：`账号名称：`、`作者ID：`、`主页链接：`、`当前指标摘要：`、`身份定位：`、`身份标签：`、`教育背景：`、`专业/能力领域：`、`创作者角色：`、`公开表达边界：`、`可创作身份卖点：`。",
    ),
    "社交": (
        "格式：`【社交】\\n对象：姓名或昵称\\n材料：聊天截图/文字记录\\n目标：生成或更新交互档案`。",
        "推荐字段：`对象：`、`关系：`、`材料：`、`时间：`、`目标：`、`备注：`。",
    ),
    "人脉": (
        "格式：`【人脉】\\n对象：张三\\n身份：AI教育创业者\\n城市：北京\\n需求：...\\n下次跟进：...`。",
        "推荐字段：`对象：`、`身份：`、`城市：`、`来源：`、`需求：`、`我能提供：`、`下次跟进：`。",
    ),
    "复盘": (
        "格式：`【复盘】\\n平台：小红书\\n账号：主账号\\n作品链接：https://...\\n播放：1000\\n点赞：100\\n结论：...`。",
        "推荐字段：`平台：`、`账号：`、`作品链接：`、`数据：`、`结论：`、`下一步：`。",
    ),
    "最近": (
        "格式：`【最近】10` 或 `【最近】最近20条内容素材`。",
        "推荐字段：可直接写数量、标签或日期。",
    ),
    "同步": (
        "格式：`【同步】飞书` 或 `【同步】重新处理任务 ID：20260509-...`。",
        "推荐字段：`ID：`、`目标：`、`要求：`。",
    ),
    "状态": (
        "格式：`【状态】20260509-082057-feishu-自媒体知识-b4ef`。",
        "推荐字段：`ID：`；也可以直接把任务ID放在正文里。",
    ),
    "说明": (
        "格式：`【说明】` 查看当前 Bot 可用完整标签；`【说明】daily` / `【说明】media` / `【说明】knowledge` / `【说明】social` / `【说明】main` 查看指定 Bot。",
        "推荐字段：通常不需要字段；需要指定 Bot 时只在正文写 bot 名称。",
    ),
}
BOT_CAPABILITY_IDENTITY_KEYS = (
    "account_id",
    "account",
)
MEDIA_REVIEW_METRIC_RE = re.compile(r"(播放|阅读|曝光|点赞|收藏|评论|分享|转发|完播率|互动率|新增关注|涨粉)\s*[=:：]?\s*[0-9]")
MEDIA_REVIEW_KEYWORDS = (
    "小红书",
    "抖音",
    "视频",
    "图文",
    "发布链接",
    "作品链接",
    "创作记录",
    "作品档案",
    "播放",
    "阅读",
    "点赞",
    "收藏",
    "评论",
    "分享",
    "完播",
    "账号",
)
THEORY_TAG_SUFFIXES = ("进行分析", "来分析", "分析一下", "分析")
KNOWLEDGE_BOT_RUNTIME = bot_runtime("knowledge")
KNOWLEDGE_DELEGATE_PROFILE = profile_config("knowledge_delegate")
KNOWLEDGE_RESEARCH_RUNTIME = profile_runtime("knowledge_research")
CONTENT_OS_SCRIPT_GENERATION_SETTINGS = load_profile_llm_settings("media_creation")
KNOWLEDGE_AGENT_ID = KNOWLEDGE_BOT_RUNTIME.agent
CONTENT_OS_SCRIPT_GENERATION_MODEL = CONTENT_OS_SCRIPT_GENERATION_SETTINGS.model
CONTENT_OS_SCRIPT_GENERATION_THINKING = CONTENT_OS_SCRIPT_GENERATION_SETTINGS.thinking
COMPLEX_RESEARCH_KEYWORDS = (
    "复杂调研",
    "深度调研",
    "深入调研",
    "系统调研",
    "专题调研",
    "行业调研",
    "竞品调研",
    "论文调研",
    "research",
    "deep research",
)
KNOWLEDGE_THINKING_DEFAULT = str(
    KNOWLEDGE_DELEGATE_PROFILE.get("thinking") or profile_provider_runtime("knowledge_delegate").thinking or "high"
).strip().lower()
KNOWLEDGE_THINKING_RESEARCH = KNOWLEDGE_RESEARCH_RUNTIME.thinking
SELFMEDIA_COGNITION_PARENT_NODE_TOKEN = os.environ.get("SELFMEDIA_COGNITION_PARENT_NODE_TOKEN", "WpNcwUuCpiyDDFk3jOlcqQPZnpc")
MEETING_MINUTES_ROOT = Path("/home/ubuntu/obsidian-日记/会议纪要")
MEETING_MINUTES_DIR = MEETING_MINUTES_ROOT / "整理版"
MEETING_TRANSCRIPTS_DIR = MEETING_MINUTES_ROOT / "原字稿"
UPLOADED_MEDIA_ROOT = Path(os.environ.get("OPENCLAW_UPLOADED_MEDIA_ROOT", "/home/ubuntu/.openclaw/media/inbound"))
UPLOADED_MEDIA_ROOTS = [
    Path(item.strip())
    for item in re.split(r"[:,]", os.environ.get("OPENCLAW_UPLOADED_MEDIA_ROOTS", ""))
    if item.strip()
] or [UPLOADED_MEDIA_ROOT, Path("/home/ubuntu/openclaw-feishu-gateway/downloads")]
TRANSCRIPTION_BATCH_WINDOW_SECONDS = int(os.environ.get("OPENCLAW_TRANSCRIPTION_BATCH_WINDOW_SECONDS", "30"))
TRANSCRIPTION_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".amr", ".caf", ".webm", ".mp4", ".mov", ".m4v"}
# Documentation sync requirement:
# Any addition, removal, or rename of tag-router entry labels in handlers,
# universal knowledge tags, or route-local tag sets must also update
# /home/ubuntu/docs/说明书/OpenClaw 标签功能说明.md, sync the matching
# Feishu cloud doc, and pass npm run check:docs.
DEMOTE_TO_ASEXUAL_KEYWORDS = (
    "不适合发展为异性关系",
    "不适合异性关系",
    "不发展为异性关系",
    "不做异性关系",
    "不再做异性关系",
    "不适合亲密推进",
    "不适合约会推进",
    "不适合发展亲密关系",
    "只做人脉",
    "只做朋友",
    "只做合作",
    "转无性关系",
    "转为无性关系",
    "转入无性关系",
    "归入无性关系",
    "移入无性关系",
    "合并到无性关系",
    "降级为无性关系",
    "降级到无性关系",
    "从异性关系提取",
)
