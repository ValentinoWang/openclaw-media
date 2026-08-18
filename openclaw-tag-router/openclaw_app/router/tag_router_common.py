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
from common.model_transport_context import tenant_model_transport_required

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
    is_media_intake_tag,
    render_media_intake_prompt,
)
from .openclaw_bot_llm import bot_runtime, display_openclaw_model, profile_config, profile_provider_runtime, profile_runtime


SOCIAL_THEORY_TAGS = ("女性爱", "性兴趣", "风控", "性资源", "行动")
BRACKET_THEORY_RE = re.compile(r"【(?P<tag>[^】\n]{1,32})】")
CREATION_TAG_RE = re.compile(r"^创作(?:>(小红书|抖音))?$")
TAG_CAPABILITY_MAP = {capability.label: capability for capability in TAG_CAPABILITIES}
BOT_CAPABILITY_IDENTITIES = {
    "media": "Media bot",
    "daily": "Daily bot",
    "knowledge": "Knowledge bot",
    "social": "Social bot",
    "deepmath": "DeepMath bot",
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
    if tenant_model_transport_required():
        raise RuntimeError(
            "authenticated Media execution cannot delegate model work to a process outside the tenant transport"
        )
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
    "DeepMath Bot 的 `【说明】` 只返回 DeepMath 专属能力说明，不展示总文档或其他 Bot 文档。",
    "正文写 `main` 或 `openclaw` 时，`【说明】` 会切换到 OpenClaw bot 的能力说明。",
    "飞书网关没有传入明确 bot 身份时，`【说明】` 不自动猜测 Bot。",
)
BOT_CAPABILITY_EXTRA_LABELS = {
    "Media bot": {"自媒体知识", "归档", "补全", "认知", "学习", "学习-整理", "调研"},
    "Daily bot": {"自媒体知识", "转写", "转写-文字", "归档", "补全", "认知", "学习", "学习-整理"},
    "Knowledge bot": {"转写", "转写-文字"},
    "Social bot": {"自媒体知识", "转写", "转写-文字", "归档", "补全", "认知", "学习", "学习-整理", "博主", "博主-入库"},
    "DeepMath bot": {"思考"},
}
BOT_ENTRY_FACTS = {
    "Media bot": (
        "`【创作】`、`【创作>小红书】`、`【创作>抖音】`、`【创作-拍摄执行】` 统一写入 `03_CreationRuns_创作运行` 或创作任务池子文档；表格不写可见 `*JSON` 字段；素材输入先走 `【素材】` 生成 SourceAsset，再按用途交接既有拆解/创作/拍摄链。",
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
        "`【博主】` 可以发给 Social bot；`能力：查询` 查询已归档博主主页，`能力：入库` 委托既有达人档案入库链路。",
    ),
    "OpenClaw bot": (
        "`【说明】main` 会显示 OpenClaw bot 的统一入口能力。",
        "`【说明】media` 会显示 Media bot 的能力。",
        "`【说明】daily` 会显示 Daily bot 的能力。",
        "`【说明】knowledge` 会显示 Knowledge bot 的能力。",
        "`【说明】social` 会显示 Social bot 的能力。",
    ),
    "DeepMath bot": (
        "`【思考】` 是 DeepMath 当前唯一的持久化入口：先收件，再恰好调用一次 LLM 生成事实/判断/假设拆分、不可变版本提案和私聊审批卡。",
        "审批卡上的批准是当前提案版本的执行授权；修改、拒绝、仅保存、取消、过期或陈旧授权都不会触发执行。",
        "当前已实现版本校验、唯一审批人校验和原子执行 claim；Tasks、Calendar、提醒与通知执行器仍属于 U7–U9，尚未接入。",
    ),
}
BOT_BOUNDARY_FACTS = {
    "Media bot": (
        "Media bot 业务标签只有空正文时只返回填写模板，不写表、不建文档、不生成稿件。",
        "已上传录音的 `【转写】` 先列出当前会话待处理的录音名称和批次号；只有用户发送带批次号的确认指令后才进入转写流程。",
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
        "`【博主】` 只读写 Media OS 的 `06_CreatorProfiles_达人账号档案`，不写入社交私档案；商单交付继续使用独立 `【商单交付】`。",
        "`【人脉】` 默认只写本地与 Obsidian，不同步飞书云文档。",
    ),
    "OpenClaw bot": (
        "OpenClaw bot 只做统一分流说明，不读取其他 Bot 的私有记忆。",
        "明显属于专用 Bot 的任务优先交给对应 Bot。",
    ),
    "DeepMath bot": (
        "DeepMath 只接受 `【思考】` 和 `【说明】`；其他全角标签在 JS/Python 入口直接拒绝。",
        "普通无标签咨询仍由 DeepMath 模型回答，不进入 tag-router 持久化链路。",
        "当前会向唯一审批人私聊发送审批卡；批准只授权当前不可变版本并原子领取，真实任务、通知、提醒或日历写入要等 U7–U9 执行器接入。",
    ),
}
BOT_ROUTING_FACTS = {}
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
CONTENT_OS_SCRIPT_GENERATION_SETTINGS = load_profile_llm_settings("media_creation")
KNOWLEDGE_AGENT_ID = KNOWLEDGE_BOT_RUNTIME.agent
CONTENT_OS_SCRIPT_GENERATION_MODEL = CONTENT_OS_SCRIPT_GENERATION_SETTINGS.model
CONTENT_OS_SCRIPT_GENERATION_THINKING = CONTENT_OS_SCRIPT_GENERATION_SETTINGS.thinking
KNOWLEDGE_THINKING_DEFAULT = profile_runtime("knowledge_delegate").thinking
SELFMEDIA_COGNITION_PARENT_NODE_TOKEN = os.environ.get("SELFMEDIA_COGNITION_PARENT_NODE_TOKEN", "WpNcwUuCpiyDDFk3jOlcqQPZnpc")
MEETING_MINUTES_ROOT = Path("/home/ubuntu/obsidian-日记/会议纪要")
MEETING_MINUTES_DIR = MEETING_MINUTES_ROOT / "整理版"
MEETING_TRANSCRIPTS_DIR = MEETING_MINUTES_ROOT / "原字稿"
MEETING_TOPICAL_ATTACHMENTS_DIR = MEETING_MINUTES_ROOT / "专题附件"
UPLOADED_MEDIA_ROOT = Path(os.environ.get("OPENCLAW_UPLOADED_MEDIA_ROOT", "/home/ubuntu/.openclaw/media/inbound"))
UPLOADED_MEDIA_ROOTS = [
    Path(item.strip())
    for item in re.split(r"[:,]", os.environ.get("OPENCLAW_UPLOADED_MEDIA_ROOTS", ""))
    if item.strip()
] or [UPLOADED_MEDIA_ROOT, Path("/home/ubuntu/openclaw-feishu-gateway/downloads")]
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
