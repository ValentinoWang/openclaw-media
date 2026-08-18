#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import ast
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELFMEDIA_TOOLS_ROOT = Path("/home/ubuntu/selfmedia-tools")
if str(SELFMEDIA_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SELFMEDIA_TOOLS_ROOT))
ACTIVE_TAG_ROUTER_ROOT = Path("/home/ubuntu/.openclaw/extensions/openclaw-tag-router")
if str(ACTIVE_TAG_ROUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ACTIVE_TAG_ROUTER_ROOT))
from common.llm_validation import llm_prompt_validation_bindings
from openclaw_app.services.capability_input_contracts import get_input_contract


SOURCE_PATH = Path("/home/ubuntu/.openclaw/extensions/openclaw-tag-router/openclaw_app/router/tag_capabilities.py")
OUTPUT_PATH = PROJECT_ROOT / "public/data/openclaw-bot-center.generated.json"
TERM_TABLE_PATH = Path("/home/ubuntu/docs/ai-harness/bot-center-normal-view-term-translation-table.json")
MEDIA_REGISTRY_PATH = Path("/home/ubuntu/openclaw-feishu-reminder/media-bitable-registry.json")
CONTENT_OS_CONFIG_PATH = Path("/home/ubuntu/openclaw-feishu-reminder/content-os-config.json")
DAILY_CONFIG_PATH = Path("/home/ubuntu/openclaw-feishu-reminder/config.json")
KNOWLEDGE_CONFIG_PATH = Path("/home/ubuntu/openclaw-feishu-reminder/knowledge-config.json")
WARDROBE_CONFIG_PATH = Path("/home/ubuntu/openclaw-feishu-reminder/wardrobe-config.json")
CONTENT_OS_PROJECTS_ROOT = Path("/home/ubuntu/obsidian-自媒体/08_内容项目")
KNOWLEDGE_AGENT_INSTRUCTIONS_PATH = Path("/home/ubuntu/openclaw-agents/knowledge/AGENTS.md")
KNOWLEDGE_AGENT_TOOLS_PATH = Path("/home/ubuntu/openclaw-agents/knowledge/TOOLS.md")
KNOWLEDGE_AGENT_USER_PATH = Path("/home/ubuntu/openclaw-agents/knowledge/USER.md")
TAG_ROUTER_ROOT = Path("/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app")
CONTENT_FLOW_CLIENT_PATH = TAG_ROUTER_ROOT / "services/content_flow_client.py"
DEEPMATH_THINKING_INTAKE_PATH = TAG_ROUTER_ROOT / "services/deepmath_thinking_intake.py"
ACTIVITY_DAILY_PATH = TAG_ROUTER_ROOT / "router/activity_daily.py"
DAILY_JOURNAL_CONTRACT_PATH = TAG_ROUTER_ROOT / "router/daily_journal_contract.py"
DOCUMENT_TOOLS_PATH = TAG_ROUTER_ROOT / "router/document_tools.py"
KNOWLEDGE_DELEGATE_PATH = TAG_ROUTER_ROOT / "router/knowledge_delegate.py"
SELFMEDIA_COGNITION_PATH = TAG_ROUTER_ROOT / "router/selfmedia_cognition.py"
SOCIAL_ARCHIVE_PATH = TAG_ROUTER_ROOT / "router/social_archive.py"
SOCIAL_PROFILE_SKILL_PATH = Path("/home/ubuntu/openclaw-agents/social/person-profile-skill/SKILL.md")
SOCIAL_METADATA_CONTRACT_PATH = Path("/home/ubuntu/openclaw-agents/social/person-profile-skill/references/social-archive-metadata-contract.md")
WORK_ACCEPTANCE_PATH = TAG_ROUTER_ROOT / "router/work_acceptance.py"
WARDROBE_ROUTER_PATH = TAG_ROUTER_ROOT / "router/wardrobe.py"
CAPABILITY_MATCHER_PATH = TAG_ROUTER_ROOT / "services/capability_matcher.py"
CONTENT_FLOW_ANALYZER_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/ingest/content_flow/src/analyzer.py")
DECONSTRUCTION_PROMPT_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/deconstruct/viral_content/src/prompt.py")
CREATION_LLM_GENERATOR_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/creation/llm_generator.py")
STYLE_POLISH_SERVICE_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/style/service.py")
CREATION_CONSULTATION_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/creation/consultation.py")
SHOOTING_EXECUTION_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/creation/shooting_execution.py")
SHOOTING_BACKWASH_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/creation/backwash.py")
DATA_REVIEW_WORKFLOW_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/review/data_review.py")
BUSINESS_ID_PATH = Path("/home/ubuntu/selfmedia-tools/selfmedia/business/id_business.py")
COMMERCIAL_DELIVERY_PATH = Path("/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app/router/commercial_delivery.py")
COMMERCIAL_DELIVERY_TARGET_TOKEN = "HJ8awfpZAiiFofkOk6Ncw8NKnNM"
COMMERCIAL_DELIVERY_TARGET_URL = f"https://tcnwueberajc.feishu.cn/wiki/{COMMERCIAL_DELIVERY_TARGET_TOKEN}?fromScene=spaceOverview"
COPY_TEMPLATE_PROMPT_LABEL = "复制模版提示词格式"
COPY_TEMPLATE_LABEL_ALIASES = {"复制输入模板", "复制当前模板", COPY_TEMPLATE_PROMPT_LABEL}
WARDROBE_LABELS = {"衣橱", "穿搭"}
CONTENT_OS_SPEC_VERSION = "content_os_v0.2"
CONTENT_OS_PROJECT_STAGES = {
    "captured": "已收集想法",
    "planned": "已形成计划",
    "edit_ready": "可开始剪辑",
    "editing": "正在剪辑",
    "final_ready": "待发布确认",
    "published": "已发布",
}
CONTENT_OS_EDITING_METHODS = {
    "handoff_pack": "标准剪辑",
    "otio_kdenlive": "可编辑时间线",
}
CONTENT_OS_OWNER_NAMES = {
    "human": "人工负责人",
    "cloud": "云端协作",
    "mac": "Mac 协作",
    "cloud_openclaw": "云端协作",
    "mac_openclaw": "Mac 协作",
}
CONTENT_OS_NEXT_ACTIONS = {
    "human": "等待人工负责人继续处理",
    "cloud": "等待云端协作继续处理",
    "mac": "等待 Mac 协作继续处理",
    "cloud_openclaw": "等待云端协作继续处理",
    "mac_openclaw": "等待 Mac 协作继续处理",
}
MEDIA_BOT_MODIFICATION_ENTRY = {
    "label": "在 Media Bot 对话中提交修改",
    "url": "#/bots/media",
    "instruction": "在 Media Bot 发送【修改】修改项目；先选择项目名称，再按填写单说明改哪里、改成什么、为什么、是否紧急和可选参考。确认后才会执行修改。",
}

PROMPT_VALIDATION_BINDINGS = {
    item.prompt_contract_id: {
        "contractId": item.contract_id,
        "profile": item.profile,
        "states": ["validated", "pending_manual"],
        "source": "selfmedia-tools/common/llm_validation.py",
    }
    for item in llm_prompt_validation_bindings()
}

BOT_IDS = ("media", "daily", "knowledge", "social", "deepmath")
DISPLAY_ARCHETYPES = (
    "Entry Hub",
    "Direct Action",
    "Gate/Review",
    "Creation Handoff",
    "Entity Store",
    "System/Maintenance",
)
SUPPORTED_ATTACHMENT_KINDS = {"url", "image", "video", "audio", "document", "text"}
RECOMMENDED_ENTRY_LABELS = {
    "今日",
    "素材",
    "调研",
    "选题",
    "创作",
    "拍摄",
    "润色",
    "检查",
    "发布包",
    "复盘",
    "博主",
    "商单交付",
    "衣橱",
}

VISIBLE_BY_BOT: dict[str, set[str]] = {
    "media": {
        "灵感",
        "灵感>vlog",
        "策略",
        "素材",
        "调研",
        "选题",
        "拍摄",
        "检查",
        "发布包",
        "复核",
        "账号",
        "赛道",
        "赛道-关系",
        "活动",
        "修改",
        "拆解",
        "创作",
        "创作>小红书",
        "创作>抖音",
        "创作-拍摄执行",
        "创作咨询",
        "数据复盘",
        "自媒体-认知",
        "创作检查",
        "作品验收",
        "润色",
        "网感",
        "文案优化",
        "改标题",
        "去AI味",
        "小红书文案",
        "抖音文案",
        "自媒体知识",
        "转写",
        "转写-文字",
        "商务>ID",
        "商单交付",
        "博主",
        "博主-入库",
        "归档",
        "补全",
        "认知",
        "学习",
        "学习-整理",
        "复盘",
        "整理",
        "说明",
        "最近",
        "同步",
        "状态",
        "删除",
    },
    "daily": {
        "灵感",
        "待办",
        "日程",
        "日记",
        "待办-开发",
        "今日",
        "周记",
        "开发-完成",
        "开发-验证",
        "衣橱",
        "穿搭",
        "修改",
        "自媒体知识",
        "转写",
        "转写-文字",
        "归档",
        "补全",
        "认知",
        "学习",
        "学习-整理",
        "复盘",
        "整理",
        "说明",
        "最近",
        "同步",
        "状态",
        "删除",
    },
    "knowledge": {
        "灵感",
        "修改",
        "自媒体知识",
        "转写",
        "转写-文字",
        "归档",
        "补全",
        "认知",
        "学习",
        "学习-整理",
        "复盘",
        "整理",
        "说明",
        "最近",
        "同步",
        "状态",
        "删除",
    },
    "social": {
        "灵感",
        "修改",
        "自媒体知识",
        "转写",
        "转写-文字",
        "博主",
        "博主-入库",
        "归档",
        "补全",
        "认知",
        "学习",
        "学习-整理",
        "社交",
        "人脉",
        "复盘",
        "整理",
        "说明",
        "最近",
        "同步",
        "状态",
        "删除",
    },
    "deepmath": {
        "思考",
        "说明",
    },
}

LABEL_IDS = {
    "灵感": "inspiration",
    "灵感>vlog": "inspiration-vlog",
    "待办": "todo",
    "日程": "calendar",
    "日记": "daily-journal",
    "待办-开发": "development-todo-traceability",
    "今日": "today",
    "周记": "weekly",
    "开发-完成": "development-complete",
    "开发-验证": "development-verify",
    "衣橱": "wardrobe-item-ingest",
    "穿搭": "wardrobe-recommendation",
    "策略": "media-strategy",
    "素材": "media-source-asset",
    "选题": "media-topic-decision",
    "拍摄": "media-shooting",
    "检查": "media-check",
    "发布包": "publishing-pack",
    "复核": "media-growth-review",
    "账号": "owned-media-account",
    "赛道": "track-registry",
    "活动": "activity",
    "修改": "document-edit",
    "拆解": "deconstruction",
    "创作": "creation",
    "创作>小红书": "creation-xiaohongshu",
    "创作>抖音": "creation-douyin",
    "创作-拍摄执行": "creation-shooting-execution",
    "创作咨询": "creation-consultation",
    "数据复盘": "data-review",
    "自媒体-认知": "selfmedia-cognition",
    "创作检查": "creation-check",
    "作品验收": "work-acceptance",
    "润色": "style-polish",
    "网感": "style-polish-net-sense",
    "文案优化": "style-polish-copy",
    "改标题": "style-polish-title",
    "去AI味": "style-polish-anti-ai",
    "小红书文案": "style-polish-xiaohongshu",
    "抖音文案": "style-polish-douyin",
    "自媒体知识": "selfmedia-knowledge",
    "转写": "transcription",
    "转写-文字": "transcription-text",
    "商务>ID": "business-id",
    "思考": "deepmath-ceo-thinking",
    "商单交付": "commercial-delivery-draft",
    "博主": "creator-profile",
    "博主-入库": "creator-profile-upsert",
    "归档": "archive",
    "补全": "complete-knowledge",
    "认知": "cognition",
    "学习": "learning",
    "学习-整理": "learning-organize",
    "调研": "research",
    "社交": "social",
    "人脉": "contacts",
    "复盘": "retrospective",
    "整理": "organize",
    "说明": "help",
    "最近": "recent",
    "同步": "sync",
    "状态": "status",
    "删除": "delete",
}

BOT_MAP = {
    "Media bot": "media",
    "Daily bot": "daily",
    "Knowledge bot": "knowledge",
    "Social bot": "social",
    "DeepMath bot": "deepmath",
    "DeepMath AI4Math Bot": "deepmath",
    "deepmath": "deepmath",
    "任意 Bot": "media",
}

DEEPMATH_HELP_FORBIDDEN_TERMS = ("Media", "Daily", "Knowledge", "Social", "total")

OBSIDIAN_KNOWLEDGE_LABELS = {
    "归档",
    "补全",
    "认知",
    "学习",
    "学习-整理",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


MEDIA_REGISTRY = read_json(MEDIA_REGISTRY_PATH)
CONTENT_OS_CONFIG = read_json(CONTENT_OS_CONFIG_PATH)
DAILY_CONFIG = read_json(DAILY_CONFIG_PATH)
KNOWLEDGE_CONFIG = read_json(KNOWLEDGE_CONFIG_PATH)
WARDROBE_CONFIG = read_json(WARDROBE_CONFIG_PATH)


def _table_url(base_url: str, table_id: str) -> str | None:
    if not base_url.startswith("https://") or not table_id:
        return None
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["table"] = table_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def registry_url(table_key: str) -> str | None:
    tables = MEDIA_REGISTRY.get("tables")
    if not isinstance(tables, list):
        return None
    node = next(
        (
            item
            for item in tables
            if isinstance(item, dict) and str(item.get("table_key") or "").strip() == table_key
        ),
        None,
    )
    if not isinstance(node, dict):
        return None
    base_token = str(node.get("base_token") or "").strip()
    table_id = str(node.get("table_id") or "").strip()
    if not base_token:
        return None
    return _table_url(f"https://tcnwueberajc.feishu.cn/base/{base_token}", table_id)


def content_os_url(table_key: str) -> str | None:
    tables = CONTENT_OS_CONFIG.get("tables")
    node = tables.get(table_key) if isinstance(tables, dict) else None
    if not isinstance(node, dict):
        return None
    base_url = str(CONTENT_OS_CONFIG.get("url") or "").strip()
    table_id = str(node.get("table_id") or "").strip()
    return _table_url(base_url, table_id)
    return None


def commercial_delivery_target_url() -> str:
    return COMMERCIAL_DELIVERY_TARGET_URL


def wardrobe_registry_url(key: str = "wardrobe_items") -> str | None:
    node = (WARDROBE_CONFIG.get("tables") or {}).get(key)
    if not isinstance(node, dict):
        return None
    env = node.get("env")
    if isinstance(env, dict):
        value = env.get("WARDROBE_ITEMS_URL")
        if isinstance(value, str) and value.startswith("https://"):
            return value
    table = node.get("table")
    if isinstance(table, dict):
        value = table.get("url")
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return None


def destination_link(label: str, url: str | None, storage_type: str, description: str) -> dict[str, str] | None:
    if not url:
        return None
    return {
        "label": label,
        "url": url,
        "storageType": storage_type,
        "description": description,
    }


def compact_links(*items: dict[str, str] | None) -> list[dict[str, str]]:
    seen: set[str] = set()
    links: list[dict[str, str]] = []
    for item in items:
        if not item:
            continue
        key = f"{item['label']}|{item['url']}"
        if key in seen:
            continue
        seen.add(key)
        links.append(item)
    return links


def import_source() -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("openclaw_tag_capabilities", SOURCE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {SOURCE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return [asdict(item) for item in module.TAG_CAPABILITIES]


def safe_text(value: str) -> str:
    value = re.sub(r"/home/ubuntu/[^\s，；。)）]+", "内部沉淀区", value)
    value = re.sub(r"/Users/[^\s，；。)）]+", "Mac 本地路径线索", value)
    value = re.sub(r"\btoken\b|\bsecret\b|\bcookie\b|\bapp[_ -]?key\b", "敏感字段", value, flags=re.I)
    return value.strip()


def read_markdown_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    """Read only simple project overview fields needed by the public view."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    frontmatter: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            frontmatter[key] = value
    return frontmatter, text[end + 4 :]


def project_display_title(frontmatter: dict[str, str], body: str) -> str:
    explicit = frontmatter.get("title", "").strip()
    if explicit:
        return safe_text(explicit)
    goal = re.search(r"^#\s*项目目标\s*$\s*^\s*(.+?)\s*$", body, flags=re.MULTILINE)
    if goal:
        return safe_text(goal.group(1))[:48]
    return "未命名内容项目"


def public_project_text(value: str, *, empty: str) -> str:
    """Keep project cards useful without exposing execution identifiers/errors."""
    text = safe_text(value).strip()
    if not text:
        return empty
    if re.search(r"(?i)traceback|exception|raw error|error_code", text):
        return "需要人工查看阻塞详情"
    text = re.sub(r"(?i)\b(?:task|change_request|project_revision|editor_backend)\b[\w.-]*", "待处理事项", text)
    return text


def build_content_os_project_dashboard() -> dict[str, Any]:
    """Project cards are a read-only projection of v0.2 project overviews.

    Old project formats are intentionally not translated.  Showing them would
    leak retired state names and local execution details into the operator UI.
    """
    projects: list[dict[str, str]] = []
    if CONTENT_OS_PROJECTS_ROOT.is_dir():
        for overview_path in sorted(CONTENT_OS_PROJECTS_ROOT.glob("*/00_项目总览.md")):
            frontmatter, body = read_markdown_frontmatter(overview_path)
            if frontmatter.get("spec_version") != CONTENT_OS_SPEC_VERSION:
                continue
            status = frontmatter.get("status", "")
            if status not in CONTENT_OS_PROJECT_STAGES:
                continue
            revision = frontmatter.get("project_revision", "").strip()
            editor_backend = frontmatter.get("editor_backend", "").strip()
            next_action = public_project_text(frontmatter.get("next_action", ""), empty="")
            projects.append(
                {
                    "id": frontmatter.get("project_id", overview_path.parent.name),
                    "title": public_project_text(project_display_title(frontmatter, body), empty="未命名内容项目"),
                    "stage": CONTENT_OS_PROJECT_STAGES[status],
                    "revision": revision or "待确认",
                    "editingMethod": CONTENT_OS_EDITING_METHODS.get(editor_backend, "待选择"),
                    "owner": CONTENT_OS_OWNER_NAMES.get(frontmatter.get("owner_agent", "").strip(), public_project_text(frontmatter.get("owner_agent", ""), empty="待分配")),
                    "nextAction": next_action or CONTENT_OS_NEXT_ACTIONS.get(frontmatter.get("next_owner", "").strip(), "等待负责人确认下一步"),
                    "blockedReason": public_project_text(frontmatter.get("blocked_reason", ""), empty="当前没有阻塞项"),
                }
            )
    return {
        "schemaVersion": "content_os_project_dashboard_v0.2",
        "title": "项目详情",
        "summary": "这里展示项目当前阶段和下一步。修改先由人说明并确认影响，再交给对应流程处理。",
        "emptyText": "暂时没有可展示的 v0.2 项目。旧项目会在迁移完成后再显示。",
        "modificationEntry": MEDIA_BOT_MODIFICATION_ENTRY,
        "projects": projects,
    }


def display_action_label(label: Any) -> str:
    text = safe_text(str(label))
    if text in COPY_TEMPLATE_LABEL_ALIASES:
        return COPY_TEMPLATE_PROMPT_LABEL
    return text


def extract_markdown_prompt_body(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"### `{heading}` 送入 LLM 的提示词正文"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"missing prompt heading in {path.name}: {marker}")
    body_start = text.find("\n", start)
    if body_start < 0:
        raise RuntimeError(f"empty prompt heading in {path.name}: {marker}")
    body_start += 1
    end_candidates = []
    for pattern in ("\n### ", "\n## ", "\n执行后用本地脚本写入：", "\n执行后用本地脚本写入:"):
        pos = text.find(pattern, body_start)
        if pos >= 0:
            end_candidates.append(pos)
    body_end = min(end_candidates) if end_candidates else len(text)
    body = text[body_start:body_end].strip()
    if not body:
        raise RuntimeError(f"empty prompt body in {path.name}: {marker}")
    return body


def extract_markdown_section(path: Path, heading_prefix: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^##\s+{re.escape(heading_prefix)}.*$", text, flags=re.M)
    if not match:
        raise RuntimeError(f"missing markdown section in {path.name}: {heading_prefix}")
    body_start = match.start()
    next_match = re.search(r"^##\s+", text[match.end() :], flags=re.M)
    body_end = match.end() + next_match.start() if next_match else len(text)
    body = text[body_start:body_end].strip()
    if not body:
        raise RuntimeError(f"empty markdown section in {path.name}: {heading_prefix}")
    return body


def social_metadata_prompt() -> str:
    """Render the same canonical Skill + contract prompt used by Social runtime."""
    missing = [str(path) for path in (SOCIAL_PROFILE_SKILL_PATH, SOCIAL_METADATA_CONTRACT_PATH) if not path.is_file()]
    if missing:
        raise RuntimeError("missing Social metadata prompt source: " + ", ".join(missing))
    skill_text = SOCIAL_PROFILE_SKILL_PATH.read_text(encoding="utf-8")
    contract_text = SOCIAL_METADATA_CONTRACT_PATH.read_text(encoding="utf-8")
    return (
        "你必须按以下项目 Skill 及其社交档案元数据抽取合同处理输入。只输出合同要求的 JSON object，"
        "不要输出 Markdown 或额外解释。\n\n"
        f"<project-skill>\n{skill_text}\n</project-skill>\n\n"
        f"<project-contract>\n{contract_text}\n</project-contract>"
    )


def _parse_python(path: Path) -> tuple[ast.Module, str]:
    source = path.read_text(encoding="utf-8")
    return ast.parse(source), source


def _expr_to_prompt_template(node: ast.AST, source: str) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                expr = ast.get_source_segment(source, value.value) or "dynamic_value"
                parts.append("{" + expr + "}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _expr_to_prompt_template(node.left, source) + _expr_to_prompt_template(node.right, source)
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "text":
                return _expr_to_prompt_template(value, source)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        if len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
            separator = _expr_to_prompt_template(node.func.value, source)
            return separator.join(_expr_to_prompt_template(item, source) for item in node.args[0].elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _expr_to_prompt_template(node.func.value, source)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "strip":
        return _expr_to_prompt_template(node.func.value, source).strip()
    segment = ast.get_source_segment(source, node)
    if segment:
        return segment.strip()
    raise RuntimeError(f"unsupported prompt expression: {type(node).__name__}")


def python_string_constant(path: Path, name: str) -> str:
    tree, source = _parse_python(path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return safe_text(_expr_to_prompt_template(node.value, source))
    raise RuntimeError(f"missing Python string constant {name} in {path}")


def python_prompt_assignment(path: Path, function_name: str, variable_name: str = "prompt") -> str:
    tree, source = _parse_python(path)
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        ),
        None,
    )
    if function is None:
        raise RuntimeError(f"missing function {function_name} in {path}")
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == variable_name for target in node.targets):
                return safe_text(_expr_to_prompt_template(node.value, source))
    raise RuntimeError(f"missing assignment {variable_name}=... in {path}::{function_name}")


def python_function_return(path: Path, function_name: str) -> str:
    tree, source = _parse_python(path)
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        ),
        None,
    )
    if function is None:
        raise RuntimeError(f"missing function {function_name} in {path}")
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node.value is not None:
            return safe_text(_expr_to_prompt_template(node.value, source))
    raise RuntimeError(f"missing return prompt in {path}::{function_name}")


def safe_file_text(path: Path) -> str:
    return safe_text(path.read_text(encoding="utf-8"))


def knowledge_capability_prompt_body(label: str) -> str:
    raw_label = f"【{label}】"
    return safe_text(extract_markdown_prompt_body(KNOWLEDGE_AGENT_INSTRUCTIONS_PATH, raw_label))


def knowledge_section_prompt_body(label: str) -> str:
    if label in {"学习", "学习-整理"}:
        return safe_text(extract_markdown_section(KNOWLEDGE_AGENT_INSTRUCTIONS_PATH, "`【学习】` / `【学习-整理】` 学习拆解规则"))
    if label == "归档":
        return safe_text(extract_markdown_section(KNOWLEDGE_AGENT_INSTRUCTIONS_PATH, "`【归档】` Obsidian 周记归档规则"))
    if label == "调研":
        return safe_text(python_prompt_assignment(KNOWLEDGE_DELEGATE_PATH, "_delegate_to_knowledge_provider", "system_prompt"))
    return knowledge_capability_prompt_body(label)


def source_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(SELFMEDIA_TOOLS_ROOT), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def release_version() -> str:
    try:
        tag = subprocess.check_output(
            ["git", "-C", str(SELFMEDIA_TOOLS_ROOT), "describe", "--tags", "--abbrev=0"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if tag:
            return tag
    except Exception:
        pass
    return "unreleased"


def capability_id(label: str) -> str:
    if label in LABEL_IDS:
        return LABEL_IDS[label]
    suffix = hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]
    return f"capability-{suffix}"


def canonical_source_system(value: Any) -> str:
    normalized = safe_text(str(value or "")).strip().lower().replace("_", "-")
    if normalized in {"deepmath", "deep-math"}:
        return "deepmath"
    return normalized


def primary_bot(raw_bot: str, source_system: Any = "") -> str:
    source_id = canonical_source_system(source_system)
    if source_id == "deepmath":
        return "deepmath"
    if raw_bot in BOT_MAP:
        return BOT_MAP[raw_bot]
    return "media"


def visible_bots_for(label: str, item: dict[str, Any], primary: str) -> list[str]:
    if canonical_source_system(item.get("source_system")) == "deepmath":
        return ["deepmath"]
    visible = [bot for bot in BOT_IDS if label in VISIBLE_BY_BOT[bot]]
    if primary not in visible:
        visible.insert(0, primary)
    return visible


def category_for(label: str, capability: str) -> str:
    if label in WARDROBE_LABELS:
        return "wardrobe"
    if label in {"待办", "日程", "日记", "今日", "周记"}:
        return "daily"
    if label == "待办-开发" or label.startswith("开发"):
        return "development"
    if label in {"策略", "选题", "拍摄", "发布包"}:
        return "creation"
    if label == "素材":
        return "material"
    if label == "检查":
        return "review"
    if label in {"账号", "赛道"}:
        return "entity"
    if "调研" in label or label == "研究":
        return "research"
    if label in {"归档", "补全", "认知", "学习", "学习-整理", "自媒体知识", "转写", "转写-文字"}:
        return "knowledge"
    if label in {"社交", "人脉", "博主", "博主-入库"}:
        return "social"
    if label in {"Brief", "商务>ID", "商单交付"}:
        return "business"
    if label == "拆解":
        return "material"
    if label in {"数据复盘", "自媒体-认知", "创作检查", "作品验收", "复盘"}:
        return "review"
    if capability == "system" or label in {"说明", "最近", "同步", "状态", "整理", "修改", "删除"}:
        return "system"
    return "creation"


def task_groups_for(label: str, category: str, source_system: Any = "") -> list[str]:
    if canonical_source_system(source_system) == "deepmath":
        return ["deepmath"]
    groups: list[str] = []
    if category in {"creation", "material", "review", "business", "entity", "research"} or label in {"活动", "博主", "博主-入库"}:
        groups.append("content")
    if category in {"daily", "development"}:
        groups.append("daily")
    if category == "wardrobe":
        groups.append("daily")
    if category == "knowledge":
        groups.append("knowledge")
    if category == "social" or label in {"社交", "人脉"}:
        groups.append("social")
    if not groups:
        groups.append("knowledge")
    return groups


def type_for(label: str, category: str, visible_bots: list[str]) -> str:
    if label in {"说明", "最近", "同步", "状态", "删除"}:
        return "common"
    if label in {"社交", "人脉"}:
        return "boundary"
    if len(visible_bots) > 1 and category in {"knowledge", "system", "review"}:
        return "collaboration"
    return "main"


def availability_for(label: str, primary: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for bot in BOT_IDS:
        if bot == primary:
            result[bot] = "primary"
        elif label in VISIBLE_BY_BOT[bot]:
            result[bot] = "visible"
        else:
            result[bot] = "hidden"
    return result


def public_title_description(label: str, item: dict[str, Any]) -> tuple[str, str]:
    overrides = {
        "归档": (
            "Obsidian 周记归档",
            "把【归档】正文整理成周记知识条目，写入 Knowledge bot 的 Obsidian 周记 # 知识 小节；默认不写飞书知识表。",
        ),
        "补全": (
            "Obsidian 周记认知补全",
            "把已有转写或半成品文字补全为可沉淀内容，写入 Obsidian 周记 # 认知 小节；默认不写飞书知识表。",
        ),
        "认知": (
            "Obsidian 周记认知沉淀",
            "把具体经历、观察或判断提炼成可复用认知条目，写入 Knowledge bot 的 Obsidian 周记 # 认知 小节；默认不写飞书知识表。",
        ),
        "学习": (
            "学习拆解并落盘",
            "按解释或学习拆解格式整理材料，写入 Obsidian 学习/每日学习，并在对应周记 # 知识 小节追加链接。",
        ),
        "学习-整理": (
            "学习材料整理并落盘",
            "强制按整理类处理课程、笔记或长材料，写入 Obsidian 学习/每日学习，并回链到周记 # 知识 小节。",
        ),
        "转写": (
            "异步录音转写与细节保真纪要",
            "Knowledge Bot 的每条裸音频自动形成独立任务并立即回执；Daily Bot 保留批次确认。任务按持久化顺序处理，会议纪要正文逐条保留受限业务细节。",
        ),
        "调研": (
            "Media 内容机会调研",
            "把明确链接、粘贴文字或可核验证据摘要登记为 ExternalResearchBrief，供选题和创作使用；证据不足时返回 pending_manual，不把空壳当作调研结论。",
        ),
        "Brief": (
            "品牌拍摄 Brief 整理落盘",
            "把品牌或商单拍摄要求清洗成 CommercialBrief，写入 media_vault/commercial_briefs，供后续【拍摄】或【商单交付】引用；不直接创建 03_CreationRuns，也不替代甲方发布前确认。",
        ),
        "修改": (
            "定向修改同一个飞书文档",
            "读取被回复或正文显式指定的飞书文档并识别文档家族，长任务提供读取、规划、写入、读回阶段回执。普通文档走分块文本 patch；拍摄执行文档必须唯一映射原 CreationRun，由创作模型整份回洗结构化执行单并经语义验收，再通过 canonical shooting renderer 清空重建同一链接，分镜保持置顶且证据附录不展示，失败时不得降级到通用 patch。商单交付图片脚本原生表格补足行走 insert_table_row，并同步 COM01 契约。",
        ),
        "复盘": (
            "记录项目或内容复盘",
            "把项目、内容或账号复盘整理成本地归档；配置允许时可同步到对应飞书目标。",
        ),
        "最近": (
            "查询最近记录",
            "按数量、标签或日期读取最近归档记录并返回摘要；只读，不新增业务写入。",
        ),
        "同步": (
            "补同步已有记录",
            "尝试把最近未同步的已有记录补同步到其所属目标，并返回成功、失败和待人工处理项。",
        ),
        "状态": (
            "查询任务状态",
            "按任务 ID 或最近任务线索返回状态、匹配结果和下一步；任务不明确时应先补充线索。",
        ),
        "说明": (
            "唯一 Bot 能力说明与可执行路径引导入口",
            "空正文返回 Bot 能力文档；明确能力返回用途和输入；自然语言需求会生成可复制步骤。维护长任务用【codex】写入唯一 v2 队列，由独立 Codex CLI worker 使用 gpt-5.6-sol/high 执行；遇到模型容量暂满时恢复同一 Codex thread、不会重放已完成工具，也不会读取或等待描述自身的任务状态，最多续跑 3 次，每 120 秒主动推送进度并在终态主动通知。",
        ),
        "衣橱": (
            "衣橱与穿搭入口",
            "先把衣物保存进衣橱，再按位置、天气和场景生成今日穿搭或旅行行李建议。",
        ),
        "穿搭": (
            "今日穿搭与旅行行李",
            "读取已入库衣物，结合明确位置、自动天气和日程背景，生成可执行的搭配或行李清单。",
        ),
        "商单交付": (
            "商单交付初稿生成",
            "根据品牌、产品、创作方向、产品卖点、Tags 和可选平台要求/博主档案上下文生成商单交付初稿，创建包含完整可发布正文、独立 Tags 和原生脚本表格的可公开编辑飞书云文档，并写入 COM01 摘要表。",
        ),
    }
    if label in overrides:
        return overrides[label]
    return safe_text(item["purpose"]), safe_text(item["result"])


def deletion_contract(label: str, category: str) -> dict[str, Any]:
    archive_targets = [
        "历史归档 ID，如 20260412-030515-qq-灵感-0056",
        "历史归档 ID 前缀，如 20260412-030515-qq-灵感",
        "inbox/archive 文件名 stem",
    ]
    base_entities = [
        "workspace inbox json",
        "workspace archive markdown",
        "frontmatter 声明的 obsidian_path/local_path",
        "frontmatter 声明的 media_dir/assets_dir",
    ]
    contract = {
        "coverage": "partial",
        "adapterId": "archive",
        "targetPatterns": archive_targets,
        "previewRequired": True,
        "confirmationRequired": True,
        "deletableEntities": base_entities,
        "manualEntities": ["飞书文档、多维表格记录、日历事件、外部系统记录需专用 adapter 或人工确认"],
        "source": "openclaw_app/router/deletion_adapters/archive_adapter.py",
    }
    if label == "删除":
        return {
            "coverage": "automatic",
            "adapterId": "universal_deletion",
            "targetPatterns": archive_targets + ["公开素材引用，如 asset_0123456789abcdef", "公开复盘引用，如 review_0123456789abcdef", "创作运行 ID，如 run_router_xxx", "转写/内容流任务 ID 或 URL 中可解析 ID"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": [
                "创作运行清理脚本声明的记录、文档和本地文件",
                "历史 archive/inbox 记录",
                "转写产生的 json/markdown/会议纪要/原字稿/中间目录",
                "bitable_record adapter 删除并读回 Feishu 多维表格记录",
                "source_asset adapter 唯一解析公开 asset_ 引用，删除并读回 02A_SourceAssets_素材源记录",
                "published_post_review adapter 唯一解析公开 review_ 引用，先删除并读回 H01 指标快照，再删除并读回 04 发布复盘主记录",
                "feishu_doc adapter 只在根删除 API 可用且归属明确时删除飞书文档",
                "reminder_calendar adapter 删除提醒记录和日历事件",
                "obsidian_block adapter 删除带 openclaw anchor 的周记块",
                "content_os adapter 删除 Content OS 项目包、Mac 队列任务和 registry 行",
                "frontmatter 和正文路径声明的安全根目录内实体文件",
            ],
            "manualEntities": ["无法确认归属的外部引用", "缺少专用 adapter 的飞书/多维表格/日历对象"],
            "source": "openclaw_app/router/deletion.py",
        }
    if label == "思考":
        return {
            "coverage": "manual_required",
            "adapterId": "system_manual",
            "targetPatterns": ["思考ID TH-...", "决策ID DC-...", "审批ID AP-...", "DeepMath Base record_id"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["DeepMath CEO Thinking / 思考收件箱记录", "关联决策池候选", "关联审批记录候选"],
            "manualEntities": ["U3 不开放删除入口；删除必须先确认完整关联链，并按审批记录、决策池、思考收件箱的顺序人工处理"],
            "source": "openclaw_app/services/deepmath_thinking_intake.py + U3 boundary",
        }
    if label == "数据复盘":
        return {
            "coverage": "automatic",
            "adapterId": "published_post_review",
            "targetPatterns": ["公开复盘引用，如 review_0123456789abcdef"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["H01_MetricSnapshot_作品指标快照中同一发布作品 ID 的全部记录", "04_PostReviews_发布复盘中公开 review_ 引用唯一匹配的主记录"],
            "manualEntities": ["复盘文档、Content OS 10_review.md 与本地 review artifact 不在本次表记录级联范围内"],
            "source": "openclaw_app/router/deletion_adapters/review_adapter.py + media-bitable-registry.json:post_reviews,metric_snapshot",
        }
    if label == "素材":
        return {
            "coverage": "automatic",
            "adapterId": "source_asset",
            "targetPatterns": ["公开素材引用，如 asset_0123456789abcdef"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["02A_SourceAssets_素材源中公开 asset_ 引用唯一匹配的 Feishu Bitable 记录"],
            "manualEntities": ["匹配不唯一、来源表不可读或下游引用需要级联删除时阻断自动删除"],
            "source": "openclaw_app/router/deletion_adapters/source_asset_adapter.py + media-bitable-registry.json:source_assets",
        }
    if label == "衣橱":
        return {
            "coverage": "manual_required",
            "adapterId": "system_manual",
            "targetPatterns": ["衣物ID UUID", "Feishu 衣橱 record_id", "衣橱表记录 URL"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["Wardrobe OS 衣橱表记录"],
            "manualEntities": ["当前未接入通用删除自动 adapter；删除衣物事实必须人工确认目标 item_id/record_id 后处理"],
            "source": "openclaw_app/router/wardrobe.py + openclaw-feishu-reminder/wardrobe-config.json",
        }
    if label == "穿搭":
        return {
            "coverage": "manual_required",
            "adapterId": "system_manual",
            "targetPatterns": ["Obsidian 物品/*.md 推荐 artifact 路径", "穿搭推荐 markdown 文件名"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["Wardrobe OS 穿搭/行李建议 markdown artifact"],
            "manualEntities": ["衣橱事实不由【穿搭】创建；删除推荐 artifact 不得删除衣橱表记录"],
            "source": "openclaw_app/router/wardrobe.py + openclaw_app/services/wardrobe_markdown_renderer.py",
        }
    if label == "商单交付":
        return {
            "coverage": "manual_required",
            "adapterId": "system_manual",
            "targetPatterns": ["商单交付ID", "COM01 record_id", "商单交付飞书文档 URL"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["COM01_CommercialDelivery_商单交付 记录", "商单交付 Feishu Docx 子页面"],
            "manualEntities": ["当前未接入自动删除 adapter；删除商单交付记录和可公开编辑文档必须人工确认 doc URL 与 record_id 后处理"],
            "source": "openclaw_app/router/commercial_delivery.py + docs/ai-harness/commercial-delivery-contract.json",
        }
    if label == "Brief":
        return {
            "coverage": "manual_required",
            "adapterId": "system_manual",
            "targetPatterns": ["commercial_brief_id", "CommercialBrief artifact_id", "media://commercial_briefs/.../result.json"],
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": ["media_vault/commercial_briefs/<artifact_id>/result.json"],
            "manualEntities": ["当前未接入 MediaClaw artifact 专用删除 adapter；删除 CommercialBrief 需人工确认 artifact_id 和下游引用"],
            "source": "selfmedia.growth.service.build_commercial_brief",
        }
    if label in {"转写", "转写-文字"}:
        return {
            "coverage": "automatic",
            "adapterId": "transcription",
            "targetPatterns": archive_targets,
            "previewRequired": True,
            "confirmationRequired": True,
            "deletableEntities": base_entities
            + [
                "transcript_paths/text_attachment_paths",
                "obsidian_transcript_path",
                "postprocess_artifacts",
                "content_flow/uploaded_transcripts 与 text_transcripts 任务目录",
            ],
            "manualEntities": ["Knowledge 周记摘要仅在缺少 openclaw block anchor 时人工处理"],
            "source": "openclaw_app/router/deletion_adapters/transcription_adapter.py",
        }
    if label in {"说明", "最近", "状态", "同步"}:
        contract["coverage"] = "manual_required"
        contract["adapterId"] = "system_manual"
        contract["deletableEntities"] = ["仅删除该能力产生的本地 archive/inbox 记录；系统配置或查询结果不得被通用删除自动修改"]
        contract["manualEntities"] = ["规则配置、同步状态、运行状态、跨能力索引需要专用维护流程"]
        contract["source"] = "openclaw_app/router/deletion_adapters/archive_adapter.py + system boundary"
    elif category in {"daily", "business", "social"}:
        contract["manualEntities"] = [
            "飞书提醒/日历/多维表格记录需专用 adapter 或人工确认",
            "本地 archive/inbox 和 frontmatter 文件可由 archive adapter 预览/确认删除",
        ]
    elif category in {"creation", "material", "review"}:
        contract["adapterId"] = "archive_or_creation_run"
        contract["manualEntities"] = [
            "03_CreationRuns 运行索引用 run_router_xxx 交给 creation_run adapter",
            "创作任务池、飞书文档和表格记录未被专用 adapter 覆盖时需人工确认",
        ]
    return contract


def _variant_fields(variant: dict[str, Any]) -> list[str]:
    fields = list(variant.get("requiredFields") or [])
    for group in variant.get("requiredAnyOf") or []:
        if group:
            fields.append(" / ".join(str(field) for field in group))
    return list(dict.fromkeys(fields))


def canonical_quick_copy_templates(label: str, contract: dict[str, Any]) -> list[dict[str, str]]:
    if contract.get("inputMode") == "freeform":
        entry_shape = str(contract.get("entryShape") or "").strip()
        body = entry_shape if entry_shape.startswith(f"【{label}】\n") else f"【{label}】"
        variants = list(contract.get("variants") or [])
        if not variants:
            variants = [{"id": "default", "description": "直接输入", "preActions": []}]
        if len(variants) == 1:
            return [{
                "id": str(variants[0].get("id") or "default"),
                "title": "直接输入",
                "description": str(contract.get("entryShape") or "按入口接受的自由正文输入。"),
                "body": body,
            }]
        templates: list[dict[str, str]] = []
        for variant in variants:
            variant_id = str(variant.get("id") or "default")
            title = str(variant.get("description") or ("直接输入" if variant_id == "default" else variant_id))
            description = title
            actions = [str(value) for value in variant.get("preActions") or [] if str(value).strip()]
            if actions:
                description += "；复制前先完成：" + "；".join(actions)
            templates.append({"id": variant_id, "title": title, "description": description, "body": body})
        return templates
    templates: list[dict[str, str]] = []
    all_fields = list(contract.get("copyFields") or [])
    for variant in contract.get("variants") or []:
        variant_id = str(variant.get("id") or "default")
        required = list(variant.get("requiredFields") or [])
        any_of = [list(group) for group in variant.get("requiredAnyOf") or []]
        controlled = set(variant.get("controlledInputFields") or [])
        field_values = variant.get("fieldValues") if isinstance(variant.get("fieldValues"), dict) else {}
        selected_fields = list(required)
        selected_fields.extend(group[0] for group in any_of if group)
        template_values = contract.get("templateValues") if isinstance(contract.get("templateValues"), dict) else {}
        if variant_id == "default" and template_values:
            selected_fields = all_fields
        elif variant_id == "default" and not selected_fields:
            selected_fields = all_fields
        selected_fields = list(dict.fromkeys(selected_fields))
        lines = [f"【{label}】"]
        for field in selected_fields:
            allowed_values = field_values.get(field) if isinstance(field_values.get(field), list) else []
            value = str(
                template_values.get(field)
                or ("[你要粘贴的内容]" if field in controlled else "")
                or (allowed_values[0] if allowed_values else "")
            )
            lines.append(f"{field}：{value}")
        actions = list(variant.get("preActions") or [])
        description = str(variant.get("description") or "按字段填写")
        if actions:
            description += "；复制前先完成：" + "；".join(actions)
        templates.append({
            "id": variant_id,
            "title": str(variant.get("description") or variant_id),
            "description": description,
            "body": "\n".join(lines),
        })
    return templates


def canonical_default_input_template(label: str, contract: dict[str, Any]) -> str:
    templates = canonical_quick_copy_templates(label, contract)
    return templates[0]["body"] if templates else f"【{label}】"


def canonical_supported_attachments(label: str, contract: dict[str, Any]) -> list[str]:
    attachments = list(contract.get("supportedAttachments") or [])
    if not attachments:
        raise RuntimeError(f"【{label}】canonical input contract 缺少 supportedAttachments")
    if len(attachments) != len(set(attachments)):
        raise RuntimeError(f"【{label}】canonical input contract 的 supportedAttachments 存在重复值")
    unknown = sorted(set(attachments) - SUPPORTED_ATTACHMENT_KINDS)
    if unknown:
        raise RuntimeError(f"【{label}】canonical input contract 包含未知附件类型：{', '.join(unknown)}")
    return attachments


def apply_canonical_input_projection(label: str, display: dict[str, Any], contract: dict[str, Any]) -> None:
    fields = list(contract.get("copyFields") or [])
    required = list(contract.get("requiredFields") or [])
    required.extend(" / ".join(group) for group in contract.get("requiredAnyOf") or [] if group)
    variants = list(contract.get("variants") or [])
    if len(variants) == 1 and variants[0].get("id") == "default":
        required = list(dict.fromkeys([*required, *_variant_fields(variants[0])]))
    elif variants:
        required.extend(
            f"输入分支：{variant.get('description') or variant.get('id')}（{'；'.join(_variant_fields(variant)) or '按分支前置动作提供证据'}）"
            for variant in variants
        )
    display["requiredInputs"] = list(dict.fromkeys(required)) or [str(contract.get("entryShape") or "直接发送能力标签")]
    atomic_required = {field for field in contract.get("requiredFields") or []}
    display["optionalInputs"] = [field for field in fields if field not in atomic_required]
    display["examplePrompt"] = canonical_default_input_template(label, contract)


def build_capability(item: dict[str, Any]) -> dict[str, Any]:
    label = item["label"]
    aliases = []
    for value in [label]:
        text = str(value or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    source_system = canonical_source_system(item.get("source_system"))
    primary = primary_bot(item.get("bot", "任意 Bot"), source_system)
    visible = visible_bots_for(label, item, primary)
    category = category_for(label, item["capability"])
    implementation_status = item.get("implementation_status") or "external"
    task_groups = task_groups_for(label, category, source_system)
    raw_label = f"【{label}】"
    words = re.split(r"[>\\-_\s]+", label)
    keywords = sorted({part for part in words + [label, item["capability"], category] if part})
    title, description = public_title_description(label, item)
    input_contract = get_input_contract(label)
    if input_contract is None:
        raise RuntimeError(f"【{label}】缺少 canonical input contract")
    capability = {
        "id": capability_id(label),
        "canonicalCapabilityId": item.get("canonical_capability_id") or item["capability"],
        "implementationStatus": implementation_status,
        "recommendedEntry": label in RECOMMENDED_ENTRY_LABELS and implementation_status != "not_implemented",
        "label": raw_label,
        "rawLabel": raw_label,
        "title": title,
        "description": description,
        "primaryBot": primary,
        "visibleBots": visible,
        "type": type_for(label, category, visible),
        "category": category,
        "taskGroups": task_groups,
        "aliases": aliases,
        "keywords": keywords,
        "commonInputs": list(input_contract.get("copyFields") or []) or [str(input_contract.get("entryShape") or raw_label)],
        "supportedAttachments": canonical_supported_attachments(label, input_contract),
        "commonOutputs": output_hints(label, category, safe_text(item["result"])),
        "outputDetail": output_detail(label, category),
        "defaultInputTemplate": canonical_default_input_template(label, input_contract),
        "quickCopyTemplates": canonical_quick_copy_templates(label, input_contract),
        "deletionContract": deletion_contract(label, category),
        "suitableFor": suitable_for(label, category),
        "notSuitableFor": not_suitable_for(label, category),
        "relatedCapabilityIds": [],
        "flowStageIds": flow_stage_ids_for(label, category),
        "promptReferenceIds": [],
        "llmPromptContracts": llm_prompt_contracts_for(label, category),
        "sensitivity": "public_description_only",
        "botAvailability": availability_for(label, primary),
    }
    capability["displayProjection"] = display_projection(label, item, capability)
    apply_canonical_input_projection(label, capability["displayProjection"], input_contract)
    capability["executionGraph"] = execution_graph_for(capability, item)
    return capability


def _risk_label(risk_level: str) -> str:
    return {
        "low": "低风险",
        "medium": "中风险",
        "high": "高风险",
        "destructive": "高风险需确认",
    }.get(risk_level or "", "风险待确认")


def _layer_label(layer: str) -> str:
    return {
        "Strategy": "策略阶段",
        "Collect": "素材阶段",
        "Decide": "决策阶段",
        "Create": "创作阶段",
        "Polish": "表达优化",
        "Verify": "检查阶段",
        "Publish": "发布准备",
        "Learn": "复盘学习",
        "Daily": "日常记录",
        "Entity": "实体管理",
        "Govern": "治理维护",
        "Operate": "通用操作",
    }.get(layer or "", "通用操作")


def _next_action(label: str, target_capability_id: str | None = None, action_type: str | None = None) -> dict[str, str]:
    if action_type == "copy_template":
        label = COPY_TEMPLATE_PROMPT_LABEL
    result = {
        "label": label,
        "actionType": action_type or ("open_capability" if target_capability_id else "reference"),
    }
    if target_capability_id:
        result["targetCapabilityId"] = target_capability_id
    return result


def _regex_flags(raw_flags: Any, term_id: str) -> int:
    flags = 0
    if raw_flags is None:
        return flags
    if not isinstance(raw_flags, list):
        raise ValueError(f"{TERM_TABLE_PATH}: term {term_id} flags must be a list")
    for raw_flag in raw_flags:
        if raw_flag == "IGNORECASE":
            flags |= re.IGNORECASE
        elif raw_flag == "MULTILINE":
            flags |= re.MULTILINE
        else:
            raise ValueError(f"{TERM_TABLE_PATH}: term {term_id} has unsupported regex flag {raw_flag!r}")
    return flags


def load_normal_view_terms() -> list[dict[str, Any]]:
    table = json.loads(TERM_TABLE_PATH.read_text(encoding="utf-8"))
    if table.get("scope") != "bot_center_normal_view":
        raise ValueError(f"{TERM_TABLE_PATH}: scope must be bot_center_normal_view")
    terms: list[dict[str, Any]] = []
    for index, item in enumerate(table.get("terms") or []):
        if not isinstance(item, dict):
            raise ValueError(f"{TERM_TABLE_PATH}: terms[{index}] must be an object")
        term_id = str(item.get("id") or "").strip()
        pattern = str(item.get("pattern") or "")
        normal_view = str(item.get("normal_view") or "").strip()
        if not term_id or not pattern or not normal_view:
            raise ValueError(f"{TERM_TABLE_PATH}: terms[{index}] requires id, pattern and normal_view")
        terms.append(
            {
                "id": term_id,
                "pattern": re.compile(pattern, _regex_flags(item.get("flags"), term_id)),
                "normal_view": normal_view,
            }
        )
    if not terms:
        raise ValueError(f"{TERM_TABLE_PATH}: terms must be non-empty")
    return terms


def _normal_view_replacement(term: dict[str, Any], capability: dict[str, Any]) -> str:
    choices = [part.strip() for part in str(term["normal_view"]).split(" / ") if part.strip()]
    replacement = choices[0] if choices else str(term["normal_view"]).strip()
    category = str(capability.get("category") or "")
    if term["id"] == "media_vault" and len(choices) >= 2 and category not in {"material", "creation", "review"}:
        replacement = choices[-1]
    elif term["id"] == "artifact" and len(choices) >= 2 and category == "review":
        replacement = choices[-1]
    elif term["id"] == "contract" and len(choices) >= 2 and category in {"review", "system"}:
        replacement = choices[-1]
    return replacement.replace("（维护区）", "").strip()


def _translate_normal_text(value: str, capability: dict[str, Any], terms: list[dict[str, Any]]) -> str:
    translated = value
    for term in terms:
        translated = term["pattern"].sub(lambda _match, term=term: _normal_view_replacement(term, capability), translated)
    translated = translated.replace("复核状态=pending_review", "待复核")
    translated = translated.replace("复核状态：pending_review", "待复核")
    translated = translated.replace("pending_review", "待复核")
    return translated


def _translate_normal_value(value: Any, capability: dict[str, Any], terms: list[dict[str, Any]]) -> Any:
    if isinstance(value, str):
        return _translate_normal_text(value, capability, terms)
    if isinstance(value, list):
        return [_translate_normal_value(item, capability, terms) for item in value]
    if isinstance(value, dict):
        return {key: _translate_normal_value(item, capability, terms) for key, item in value.items()}
    return value


def display_archetype_for(capability: dict[str, Any]) -> str:
    label = str(capability.get("rawLabel") or "").strip("【】")
    category = str(capability.get("category") or "")
    capability_type = str(capability.get("type") or "")
    canonical = str(capability.get("canonicalCapabilityId") or "")
    entry_tree = capability.get("entryTree") if isinstance(capability.get("entryTree"), dict) else {}
    child_count = len(entry_tree.get("children") or []) if isinstance(entry_tree, dict) else 0
    next_action_count = len(
        [
            action
            for action in capability.get("displayProjection", {}).get("nextActions", [])
            if isinstance(action, dict) and action.get("targetCapabilityId")
        ]
    )

    if category in {"system", "development"} or capability_type == "boundary":
        return "System/Maintenance"
    if category == "review" or label in {"复核", "检查", "创作检查", "作品验收", "数据复盘"}:
        return "Gate/Review"
    if category in {"entity", "social", "business"}:
        return "Entity Store"
    if child_count > 0 or (capability.get("recommendedEntry") and next_action_count >= 4):
        return "Entry Hub"
    if label.startswith("创作") or canonical in {"selfmedia_creation"}:
        return "Creation Handoff"
    if category == "wardrobe":
        return "Entity Store"
    return "Direct Action"


def apply_display_contracts(capabilities: list[dict[str, Any]]) -> None:
    terms = load_normal_view_terms()
    top_level_normal_fields = (
        "title",
        "description",
        "commonOutputs",
        "suitableFor",
        "notSuitableFor",
    )
    display_normal_fields = (
        "displayTitle",
        "displaySubtitle",
        "operatorSummary",
        "whenToUse",
        "whenNotToUse",
        "outputSummary",
        "nextActions",
        "evidenceSummary",
        "riskBadges",
        "savedAs",
        "operatorFlow",
    )
    entry_node_normal_fields = (
        "displayName",
        "purpose",
        "outputContract",
        "supportedAttachments",
        "riskLevel",
        "visibility",
    )
    output_detail_normal_fields = ("contentForms", "destinations", "nextActions", "boundaries")
    for capability in capabilities:
        display = capability.get("displayProjection") or {}
        display["displayArchetype"] = display_archetype_for(capability)
        for field in top_level_normal_fields:
            if field in capability:
                capability[field] = _translate_normal_value(capability[field], capability, terms)
        for field in display_normal_fields:
            if field in display:
                display[field] = _translate_normal_value(display[field], capability, terms)
        output_detail = capability.get("outputDetail") or {}
        for field in output_detail_normal_fields:
            if field in output_detail:
                output_detail[field] = _translate_normal_value(output_detail[field], capability, terms)
        entry_tree = capability.get("entryTree")
        if isinstance(entry_tree, dict):
            nodes = [entry_tree.get("root"), *(entry_tree.get("children") or [])]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                for field in entry_node_normal_fields:
                    if field in node:
                        node[field] = _translate_normal_value(node[field], capability, terms)


def display_projection(label: str, item: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    canonical = str(capability["canonicalCapabilityId"])
    lifecycle = str(item.get("lifecycle_layer") or "")
    risk = str(item.get("risk_level") or "")
    source_system = canonical_source_system(item.get("source_system") or capability["primaryBot"])
    writes_to = [safe_text(str(value)) for value in item.get("writes_to", ()) if str(value).strip()]
    produces = [safe_text(str(value)) for value in item.get("produces", ()) if str(value).strip()]
    ssot_refs = [safe_text(str(value)) for value in item.get("ssot_refs", ()) if str(value).strip()]
    if source_system == "deepmath":
        ssot_refs = [
            "DeepMath CEO Thinking" if ref.lower().startswith("daily.") else ref
            for ref in ssot_refs
        ]
    saved_as = {
        "account_track_strategy": "保存策略 Brief",
        "commercial_brief": "保存品牌 Brief",
        "source_asset_intake": "保存素材 Brief",
        "external_research_brief": "保存调研 Brief",
        "creation_decision_brief": "保存选题判断",
        "selfmedia_creation": "保存创作草稿",
        "shooting_execution_plan": "保存拍摄执行方案",
        "style_polish_run": "返回自然成稿并保存内部审计",
        "creation_checklist_lookup": "只返回检查清单",
        "publishing_pack_build": "保存发布包",
        "post_review_signal": "保存复盘信号",
        "wardrobe_item_ingest": "保存衣物记录",
        "wardrobe_recommendation": "保存穿搭建议",
    }.get(canonical, (produces[0] if produces else "保存能力结果"))

    overrides: dict[str, dict[str, Any]] = {
        "说明": {
            "displayTitle": "能力说明、执行路径与后台维护入口",
            "displaySubtitle": "查找 Bot 能力并生成可复制步骤；【codex】长任务由独立 v2 worker 执行，DeepMath 可开发本地工程文档，飞书修改绑定专用身份并写后回读。",
            "operatorSummary": "普通能力从【说明】生成真实标签和输入格式；维护长任务写入唯一 v2 队列，由 Codex CLI full access、gpt-5.6-sol/high 执行。DeepMath Bot 收到任意位置的【codex】时直接进入同一队列并冻结 tenantProfile=deepmath；本地代码、配置、测试、Markdown、Obsidian 和仓库文档开发不要求飞书 URL。只有飞书 Wiki/Docx 修改必须带本轮显式 URL，并只使用 DeepMath 专用应用身份读取 live block tree、原位修改安全文本块并写后回读，禁止整篇 Markdown 压平、追加补丁或另建 v2 副本，终态仍由 DeepMath Bot 通知。模型容量暂满时在同一冻结契约上恢复原 thread，最多续跑 3 次，Gateway 重启不影响任务。",
            "whenToUse": ["不知道应该使用哪个 Bot 或标签", "需要把自然语言需求转换成可复制执行步骤", "需要发起较长的 OpenClaw 维护任务并持续查询进度", "需要通过 DeepMath Bot 用【codex】修复代码、配置、测试或开发仓库文档", "需要通过 DeepMath Bot 用【codex】修改明确 URL 对应的 AI4Math 飞书 Wiki/Docx"],
            "whenNotToUse": ["已经知道业务标签时直接使用对应标签", "【说明】本身不执行归档、创作、入库或同步", "DeepMath 文档目标缺少显式 URL、权限不足或结构无法安全修改时不得写入", "不要在公开状态查询中粘贴私有正文或完整命令"],
            "requiredInputs": ["能力说明：直接发送【说明】和需求", "后台维护或本地文档开发：消息中包含【codex】和授权范围内的目标", "DeepMath 飞书文档修改：本轮显式 Feishu Wiki/Docx URL 与明确修改要求"],
            "optionalInputs": ["目标 Bot", "已有材料或链接", "需保护的图片、附件、callout、原生表格或富文本结构", "维护任务的验收要求"],
            "outputSummary": ["能力说明或可复制执行路径", "v2 维护 task_id", "DeepMath 同文档修改与写后读回结果", "模型容量暂满时的持久化重试状态", "每 120 秒主动进度", "由触发 Bot 返回的终态通知"],
            "nextActions": [_next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【codex】检查指定维护问题并给出证据",
            "evidenceSummary": ["当前能力目录", "用户明确提供的需求", "后台任务的安全状态字段"],
            "operatorFlow": ["发送【说明】获取路径，或用【codex】发起维护/开发任务", "DeepMath 请求绑定 tenantProfile=deepmath；仅飞书文档写入校验显式 URL", "入队回执显示计划模型和 task_id", "Codex 修复本地工程或开发仓库文档；飞书任务读取 live block tree 并只执行安全的同文档修改", "运行相应测试；飞书任务额外写后回读目标块与受保护结构", "接收同 Bot 终态通知或使用【codex】状态 task_id 查询"],
        },
        "今日": {
            "displayTitle": "今日执行与记录入口",
            "displaySubtitle": "查看今天要做什么，并从这里进入待办、日程、日记和周记。",
            "operatorSummary": "用于快速查看当日执行状态；如果要新增事实，转到待办、日程或日记，周末再用周记做提取。",
            "whenToUse": ["想看今天的待办、日程和开发任务", "想确认今天有没有遗漏", "想从 Daily 根入口进入日记或周记"],
            "whenNotToUse": ["要保存每日经验时用【日记】", "要生成本周总结时用【周记】", "要创建正式开发任务时用【待办-开发】"],
            "requiredInputs": ["直接发送【今日】"],
            "optionalInputs": ["日期", "筛选范围"],
            "outputSummary": ["今日执行清单", "提醒/日程/待办摘要", "开发任务摘要", "下一步记录入口"],
            "nextActions": [_next_action("新建待办", "todo"), _next_action("新建日程", "calendar"), _next_action("写日记", "daily-journal"), _next_action("生成周记", "weekly"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【今日】",
            "evidenceSummary": ["Daily 本地归档", "提醒与日程镜像", "开发任务状态"],
            "operatorFlow": ["发送【今日】", "读取当天执行上下文", "返回执行清单", "按需要跳到待办/日程/日记/周记"],
        },
        "日记": {
            "displayTitle": "每日自我记录",
            "displaySubtitle": "把今天真正值得保留的事实、情绪、判断、退缩、开发和经验写进独立日记。",
            "operatorSummary": "每天 22:00 推荐填写；模板字段和自由正文都会送入 LLM 整理成日记全文总结，并同步投影到本周 Archieve 的日期块：三级主题标题 + 3-5 句精炼总结 + 日记链接。",
            "whenToUse": ["今天有一个值得保留的经验或教训", "想记录情绪触发、判断依据或退缩原因", "想沉淀开发、工程经验、内容创作或承诺未完成"],
            "whenNotToUse": ["要创建提醒或截止时间时用【待办】", "要安排日历事件时用【日程】", "要直接生成本周总结时用【周记】"],
            "requiredInputs": ["至少填写一个日记字段或一段自然语言正文"],
            "optionalInputs": ["情绪/压力", "决策/判断", "退缩/逃避", "开发/工作", "工程经验", "内容/创作", "承诺/未完成"],
            "outputSummary": ["独立日记文件", "一段整理后总结", "底部原文", "周 Archieve 日期块投影", "周记可读取索引"],
            "nextActions": [_next_action("查看今日", "today"), _next_action("生成周记", "weekly"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": python_string_constant(DAILY_JOURNAL_CONTRACT_PATH, "DAILY_JOURNAL_TEMPLATE"),
            "evidenceSummary": ["完整日记原文", "LLM 整理后总结", "openclaw 日记块锚点"],
            "operatorFlow": ["填写日记模板或自由正文", "LLM 生成日记整理和周归档投影", "写入 YYYY-MM-DD.md", "原文保留在底部", "同步写入 Archieve #YYYYMMDD -> ##日记", "周记按周读取隐藏整理信号"],
        },
        "周记": {
            "displayTitle": "周记自我模型提取",
            "displaySubtitle": "每周 23:59 从本周日记提取固定总结和动态主题簇。",
            "operatorSummary": "读取本周独立日记文件；少于 3 篇只写样本不足索引，样本足够才生成稳定模式相关总结。",
            "whenToUse": ["本周已经有至少 3 篇日记", "想看重复情绪触发、逃避模式、关键决策和承诺完成情况", "想把开发、工程经验、内容创作信号汇总出来"],
            "whenNotToUse": ["还没有写日记时先用【日记】", "只想看今天安排时用【今日】", "不用于替代原始日记"],
            "requiredInputs": ["直接发送【周记】或指定周范围"],
            "optionalInputs": ["YYYYMMDD-YYYYMMDD 周范围", "最近 N 周"],
            "outputSummary": ["固定周记总结", "动态主题簇", "日记索引", "样本不足状态"],
            "nextActions": [_next_action("补写日记", "daily-journal"), _next_action("查看今日", "today"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【周记】20260629-20260705",
            "evidenceSummary": ["本周日记文件", "隐藏整理信号", "样本数检查"],
            "operatorFlow": ["读取周范围", "收集 7 篇日记", "检查样本数", "LLM 生成周记总结", "写入 Archieve 周记文件"],
        },
        "衣橱": {
            "displayTitle": "衣橱与穿搭入口",
            "displaySubtitle": "先把衣物保存进衣橱，再按位置、天气和场景生成今日穿搭或旅行行李建议。",
            "operatorSummary": "这是衣橱工作流的主入口。新衣物用【衣橱】保存；需要搭配时在同页选择【穿搭】，系统只基于已入库衣物和明确上下文生成建议。",
            "whenToUse": ["新买或已有衣物需要进入衣橱", "需要从淘宝标题、订单截图、洗标或实物照整理品牌/颜色/材质/尺码", "需要补充某件已入库衣物的订单或洗标截图", "想从衣橱继续生成今日穿搭或旅行行李清单"],
            "whenNotToUse": ["只想生成搭配建议时直接选同页的【穿搭】", "要写内容脚本或创作任务时用 Media bot 创作类入口", "补旧衣物截图但无法确认是哪件衣服时，系统会要求补充衣物ID或回复入库确认消息"],
            "requiredInputs": ["衣物标题/说明或图片附件", "补充旧衣物截图时提供衣物ID，或直接回复入库确认消息"],
            "optionalInputs": ["用途", "颜色", "品牌", "位置", "订单/洗标/吊牌截图"],
            "outputSummary": ["衣橱单品记录", "系统生成衣物ID", "识别字段", "待补信息"],
            "nextActions": [_next_action("生成穿搭", "wardrobe-recommendation"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【衣橱】优衣库黑色速干T，运动和通勤都能穿，位置：深圳",
            "evidenceSummary": ["用户正文", "上传图片或截图", "衣橱表读回结果"],
            "operatorFlow": ["发送衣物说明或附件", "整理衣物字段", "生成衣物ID", "写入衣橱", "返回衣物ID和待补信息"],
        },
        "穿搭": {
            "displayTitle": "今日穿搭与旅行行李",
            "displaySubtitle": "读取已入库衣物，按明确位置、自动天气、日程和场景生成搭配或行李清单。",
            "operatorSummary": "只读取衣橱，不新增或修改衣物。你给出当前位置或旅行目的地后，系统自动查天气并结合场景生成建议；缺少位置或天气不可用时会让你补充，不会用历史消息猜位置。",
            "whenToUse": ["今天不知道穿什么", "需要按明确位置、天气和日程组合衣物", "旅行前想从已有衣橱生成行李清单"],
            "whenNotToUse": ["要新增或修正衣橱单品时用【衣橱】", "没有位置、目的地或已登记默认位置时会要求补充", "不用于内容创作、脚本或发布准备"],
            "requiredInputs": ["当前位置或旅行目的地", "通勤、运动、正式场合、旅行天数等场景"],
            "optionalInputs": ["今日安排", "待办背景", "穿着偏好", "运动或正式要求"],
            "outputSummary": ["今日穿搭建议", "旅行行李清单", "备选单品", "需要补充的位置或衣物"],
            "nextActions": [_next_action("补衣物入库", "wardrobe-item-ingest"), _next_action("查看今日", "today"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【穿搭】位置：深圳，今天通勤，晚上可能跑步",
            "evidenceSummary": ["衣橱单品库", "当前位置或旅行目的地", "自动天气", "可选日程/待办背景"],
            "operatorFlow": ["确认位置和场景", "自动获取天气", "读取衣橱单品", "筛选可用衣物", "生成穿搭或行李建议", "保存推荐结果"],
        },
        "策略": {
            "displayTitle": "内容打法诊断",
            "displaySubtitle": "帮你把账号、平台和赛道放在一起，整理出当前最适合的内容打法。",
            "operatorSummary": "围绕账号、平台和赛道，判断这条内容线该怎么做、为什么做、什么不做；不直接写稿，也不自动发布。",
            "whenToUse": ["不确定某个赛道值不值得做", "想整理账号接下来一段时间的内容方向", "想判断一个活动、热点或主题该怎么切入", "想把零散想法变成可执行策略"],
            "whenNotToUse": ["已经有文案，只想改表达时用【润色】", "已经有素材想直接出稿时用【创作】", "想发布前检查时用【检查】或【发布包】"],
            "requiredInputs": ["账号", "平台", "赛道或主题", "当前想解决的问题"],
            "optionalInputs": ["目标人群", "参考素材", "最近数据", "不想做的方向", "希望输出形式"],
            "outputSummary": ["账号打法判断", "赛道切入角度", "可做内容方向", "不建议做的方向", "风险提示", "下一步建议"],
            "nextActions": [_next_action("生成选题", "media-topic-decision"), _next_action("补充调研", "research"), _next_action("进入创作", "creation"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【策略】账号=小王 平台=抖音 赛道=校园体育\n目标=判断下周应该主打什么内容方向",
            "evidenceSummary": ["账号画像", "赛道策略", "平台机制", "历史复盘", "已确认的创作模式"],
            "operatorFlow": ["填写策略需求", "读取账号和赛道背景", "生成策略判断", "保存策略 Brief", "给出下一步动作"],
        },
        "素材": {
            "displayTitle": "素材资产唯一入口",
            "displaySubtitle": "只用【素材】接收可访问链接、粘贴文字、活动 brief、转写稿文字或 vlog 文字说明。",
            "operatorSummary": "先生成素材资产；再按用途暂存、入库、拆解、选题、创作或拍摄。素材入口只保留【素材】。",
            "whenToUse": ["拿到可访问链接、活动 brief、转写稿文字或其他文字资料，想先沉淀证据", "想把灵感或外部资料变成可追踪素材资产", "需要把素材交给选题、创作、拍摄或拆解继续处理"],
            "whenNotToUse": ["已经有明确脚本需求且无新增素材时直接用【创作】", "只想改现成文案时用【润色】", "正式活动入库用【活动】"],
            "requiredInputs": ["素材类型", "用途", "链接或文字素材"],
            "optionalInputs": ["平台", "账号", "赛道", "补充说明"],
            "outputSummary": ["素材资产", "素材资产 ID", "待复核", "用途对应的续跑命令或投影"],
            "nextActions": [
                _next_action("拆解爆款", "deconstruction"),
                _next_action("生成选题", "media-topic-decision"),
                _next_action("进入创作", "creation"),
                _next_action("拍摄执行", "media-shooting"),
                _next_action("复制输入模板", action_type="copy_template"),
            ],
            "examplePrompt": "【素材】\n素材类型：链接\n用途：选题\n平台：抖音\n链接或文字素材：https://...\n补充说明：判断能不能作为校园体育选题素材",
            "evidenceSummary": ["原始链接或粘贴文字", "素材资产处理产物", "素材资产 ID", "素材证据库"],
            "operatorFlow": ["提交【素材】", "生成素材资产", "按用途映射到下游处理流程", "给出可追溯下游命令"],
        },
        "拆解": {
            "displayTitle": "证据化拆解视频与图文素材",
            "displaySubtitle": "先选择分析范围、重点和输出类型，再从可访问证据中拆出结构、节奏、AI 片段与复用边界。",
            "operatorSummary": "【拆解】读取已登记或可访问的素材证据，按明确范围分析钩子、转场、BGM、节奏、AI 片段或人性洞察；证据不足时不会补写不存在的画面、声音和评论。",
            "whenToUse": [
                "拆全片、开头、转场或指定时间段，并保留证据引用",
                "分析钩子、BGM、节奏、镜头结构和结尾引导",
                "判断 AI / 实拍 / 混合片段，并分析现实素材与 AI 镜头如何衔接",
                "按需生成结构迁移、AI 分镜提示词、人性洞察候选或后续素材清单",
            ],
            "whenNotToUse": ["只想保存资料或暂时不分析时用【素材】", "已经有明确脚本需求且不需要素材分析时用【创作】", "没有可访问素材链接时不应把描述当成已分析的素材事实"],
            "requiredInputs": ["素材链接"],
            "optionalInputs": [],
            "outputSummary": [
                "拆解摘要、爆点机制与核心证据",
                "视频前 60 秒证据化分镜或图文结构",
                "按请求生成 AI 片段分析与 AI 分镜提示词",
                "结构迁移、原创边界和复用建议",
                "按请求生成人性洞察候选与后续素材清单",
            ],
            "nextActions": [_next_action("进入创作", "creation"), _next_action("拍摄执行", "media-shooting"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【拆解】\n素材链接：https://...\n拆解目标：分析前 15 秒如何从实拍过渡到 AI 片段",
            "evidenceSummary": ["可访问的素材链接", "关键帧、ASR、OCR、互动和评论证据", "逐镜头拆解文档", "素材拆解记录", "结构库或同款拆解 Markdown"],
            "operatorFlow": ["确认素材证据", "选择范围、重点和输出", "生成受证据约束的拆解", "人工决定是否交接创作或拍摄"],
        },
        "调研": {
            "displayTitle": "内容机会调研",
            "displaySubtitle": "围绕自媒体增长目标，把外部信息转成可用于选题和创作的调研 Brief。",
            "operatorSummary": "调研结论必须落到内容机会、可用角度、不可用角度和下一步动作，不把通用知识回答直接当内容决策。",
            "whenToUse": ["需要判断一个趋势、赛道或话题有没有内容机会", "需要补充外部证据再做选题", "需要比较多个方向的优先级"],
            "whenNotToUse": ["只想保存一条资料时用【素材】", "已经确定选题想写稿时用【创作】", "纯知识问答不属于 Media 调研"],
            "requiredInputs": ["研究问题", "账号或目标人群", "平台", "赛道或内容目标"],
            "optionalInputs": ["已有资料", "比较维度", "时间范围", "风险边界"],
            "outputSummary": ["内容机会", "可用角度", "不可用角度", "证据摘要", "风险提示", "下一步内容动作"],
            "nextActions": [_next_action("生成选题", "media-topic-decision"), _next_action("进入创作", "creation"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【调研】账号=小王 平台=抖音 赛道=校园体育\n问题=最近校园体育内容有哪些可做角度？",
            "evidenceSummary": ["外部证据包", "账号赛道策略", "平台机制", "source_trace"],
            "operatorFlow": ["提出调研问题", "补充账号和赛道上下文", "收集证据", "转成内容机会", "给出下一步动作"],
        },
        "选题": {
            "displayTitle": "选题判断与候选排序",
            "displaySubtitle": "把素材、策略和调研结果转成一组能拍、能写、能排序的内容候选。",
            "operatorSummary": "判断哪些题值得做、为什么现在做、先做哪个，并说明不建议做的方向。",
            "whenToUse": ["手里有多个素材或想法，需要排序", "想判断一个题是否适合当前账号", "需要把活动 brief 转成可执行选题"],
            "whenNotToUse": ["还没有资料时先用【素材】或【调研】", "已经确定题目要写稿时用【创作】", "只想发布前检查时用【检查】"],
            "requiredInputs": ["账号", "平台", "候选主题或素材", "目标"],
            "optionalInputs": ["策略 Brief", "调研 Brief", "近期复盘", "拍摄限制"],
            "outputSummary": ["候选选题", "优先级", "取舍理由", "风险和限制", "推荐进入创作的题"],
            "nextActions": [_next_action("进入创作", "creation"), _next_action("补充调研", "research"), _next_action("拍摄执行", "media-shooting"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【选题】账号=小王 平台=抖音\n来源=最近素材和复盘\n目标=找 5 个下周可拍选题",
            "evidenceSummary": ["SourceAsset", "Strategy Brief", "Research Brief", "历史复盘"],
            "operatorFlow": ["提交候选或来源", "读取策略和素材", "比较机会和风险", "输出优先级", "给出推荐下一步"],
        },
        "创作": {
            "displayTitle": "内容草稿生成",
            "displaySubtitle": "把选题、素材或活动 brief 转成可继续润色、检查和发布准备的内容草稿。",
            "operatorSummary": "生成脚本、标题、正文或分镜草案；不替代最终发布确认。",
            "whenToUse": ["已经有明确选题或素材", "想从活动、爆款或灵感生成一版草稿", "需要脚本、封面、正文或分镜初稿"],
            "whenNotToUse": ["只想改表达时用【润色】", "还没判断做不做时用【选题】", "想检查能不能发时用【检查】"],
            "requiredInputs": ["平台", "内容类型", "主题或来源", "目标人群"],
            "optionalInputs": ["素材链接", "选题 Brief", "账号边界", "必须保留和不能出现的内容"],
            "outputSummary": ["内容草稿", "标题或封面建议", "脚本/分镜", "发布检查项", "可继续润色或发布准备"],
            "nextActions": [_next_action("润色表达", "style-polish"), _next_action("发布前检查", "media-check"), _next_action("生成发布包", "publishing-pack"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【创作】平台=抖音 内容类型=短视频脚本\n主题=校园体育训练复盘\n目标=生成 30 秒口播稿",
            "evidenceSummary": ["素材源", "选题判断", "账号画像", "平台机制", "创作模式"],
            "operatorFlow": ["提交创作需求", "读取素材和账号背景", "生成草稿", "保存创作运行", "推荐润色或检查"],
        },
        "拍摄": {
            "displayTitle": "拍摄执行计划",
            "displaySubtitle": "把内容想法转成现场能执行的镜头、场地、人员和备选方案。",
            "operatorSummary": "面向拍摄执行；飞书文档标题后先展示分镜脚本，证据保留在 CreationRun 后台 artifact，不在前台文档展示。",
            "whenToUse": ["已经有题目或脚本，需要落到怎么拍", "需要镜头清单、场地和人员安排", "需要现场 B 方案和 checklist"],
            "whenNotToUse": ["还没确定做什么时用【选题】", "只想写文案时用【创作】", "已经成稿只需检查时用【检查】"],
            "requiredInputs": ["平台", "内容主题", "拍摄场景", "可用人员或素材"],
            "optionalInputs": ["脚本草稿", "场地限制", "时间限制", "设备条件"],
            "outputSummary": ["首屏分镜脚本原生表格", "拍摄路线", "镜头清单", "现场 checklist", "B 方案", "交付给剪辑或发布包的材料"],
            "nextActions": [_next_action("进入创作", "creation"), _next_action("生成发布包", "publishing-pack"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【拍摄】平台=抖音 主题=校园短跑训练\n场景=操场\n目标=给出明天能拍的镜头清单",
            "evidenceSummary": ["创作草稿", "拍摄限制", "素材清单", "账号风格"],
            "operatorFlow": ["提交拍摄需求", "拆成场景和镜头", "安排执行顺序", "补充风险和 B 方案", "输出现场 checklist"],
        },
        "润色": {
            "displayTitle": "语言风格与网感润色",
            "displaySubtitle": "把已有标题、正文、封面文案或口播稿改成自然、可直接发布的中文。",
            "operatorSummary": "由 Media 写作模型按口头转述顺序重写；聊天只交付成稿，诊断与来源追踪保留在内部 artifact。",
            "whenToUse": ["已有文案但太平、太 AI 或不够像本人", "想把说明书式表达改成真人叙述", "想针对抖音或小红书调整语感"],
            "whenNotToUse": ["没有原文时先用【创作】", "需要判断题值不值得做时用【选题】", "需要发布前完整检查时用【检查】"],
            "requiredInputs": ["原文", "平台", "内容类型", "目标"],
            "optionalInputs": ["账号", "语气", "必须保留", "不能出现"],
            "outputSummary": ["一个可直接发布的自然成稿", "内部事实保留校验", "内部诊断与 source_trace artifact"],
            "nextActions": [_next_action("发布前检查", "media-check"), _next_action("生成发布包", "publishing-pack"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【润色】平台=小红书 内容类型=标题+正文\n目标=更有网感但不要油\n原文=...",
            "evidenceSummary": ["账号画像", "平台机制", "CreativePattern", "历史反馈", "anti_patterns"],
            "operatorFlow": ["提交原文", "读取风格上下文", "按口头转述重写", "校验事实与边界", "返回成稿并保存内部审计"],
        },
        "检查": {
            "displayTitle": "发布前检查",
            "displaySubtitle": "检查稿件、脚本或发布包是否完整、是否有风险、下一步该改哪里。",
            "operatorSummary": "根据输入对象判断是查清单、做验收，还是执行发布前 gate；不自动发布。",
            "whenToUse": ["想知道发之前要注意什么", "已有脚本或文案，需要逐项验收", "已有发布包，需要判断是否 ready"],
            "whenNotToUse": ["只想改文字风格时用【润色】", "还没生成草稿时用【创作】", "需要真实发布动作不在当前能力范围"],
            "requiredInputs": ["平台", "内容类型或稿件", "检查目标"],
            "optionalInputs": ["creation_run_id", "publishing_pack_id", "风险关注点", "账号边界"],
            "outputSummary": ["检查结论", "缺失项", "风险提示", "修改建议", "可继续进入发布包或润色"],
            "nextActions": [_next_action("润色表达", "style-polish"), _next_action("生成发布包", "publishing-pack"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【检查】平台=抖音 内容类型=短视频脚本\n目标=发布前检查\n正文=...",
            "evidenceSummary": ["创作草稿", "发布包", "平台机制", "检查清单"],
            "operatorFlow": ["提交待检查内容", "识别检查类型", "逐项检查", "输出风险和缺口", "给出修改下一步"],
        },
        "发布包": {
            "displayTitle": "发布准备包",
            "displaySubtitle": "整理标题、封面文案、正文、标签、评论引导和发布前检查项。",
            "operatorSummary": "只生成 PublishingPack 和 readiness 摘要，不自动发布到任何平台。",
            "whenToUse": ["草稿基本确定，需要整理成可发布材料", "需要标题、封面、正文、标签和评论引导", "需要发前 checklist"],
            "whenNotToUse": ["想直接平台发布不属于当前 v2 默认能力", "文案还很粗糙时先用【润色】", "内容方向没定时先用【选题】"],
            "requiredInputs": ["平台", "草稿或 creation_run_id", "发布目标"],
            "optionalInputs": ["润色结果", "封面限制", "标签偏好", "风险边界"],
            "outputSummary": ["标题", "封面文案", "正文", "hashtags", "评论引导", "发布 checklist", "readiness 摘要"],
            "nextActions": [_next_action("发布前检查", "media-check"), _next_action("发布后复盘", "retrospective"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【发布包】run_id=creation_run_123 平台=抖音\n目标=整理成可发布版本",
            "evidenceSummary": ["创作草稿", "润色结果", "平台机制", "发布检查项"],
            "operatorFlow": ["提交草稿或 run_id", "整理发布字段", "补齐标签和评论引导", "生成 readiness 摘要", "输出发布前检查项"],
        },
        "复盘": {
            "displayTitle": "发布后复盘信号",
            "displaySubtitle": "把作品表现、评论和人工判断整理成下一轮可用的增长信号。",
            "operatorSummary": "沉淀有效模式、失败原因和下一步建议，供后续【策略】【选题】【创作】复用。",
            "whenToUse": ["作品发布后有数据或评论", "想判断这次内容为什么好或差", "想把复盘变成下一轮选题建议"],
            "whenNotToUse": ["还没发布时用【检查】或【发布包】", "只是保存资料时用【素材】", "要写下一条稿子时先进入【创作】"],
            "requiredInputs": ["作品链接或标题", "平台", "正文填写的表现数据", "想复盘的问题"],
            "optionalInputs": ["原始创作 run_id", "评论关键词", "人工观察", "下一轮目标"],
            "outputSummary": ["复盘结论", "有效模式", "失败原因", "风险或误判", "下一轮选题建议"],
            "nextActions": [_next_action("更新策略", "media-strategy"), _next_action("生成选题", "media-topic-decision"), _next_action("进入创作", "creation"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": "【复盘】平台=抖音 作品=...\n数据=播放/点赞/评论/收藏\n目标=判断下周怎么调整",
            "evidenceSummary": ["MetricSnapshot", "PublishedPost", "recent_reviews", "人工复盘备注"],
            "operatorFlow": ["提交作品和数据", "整理表现信号", "判断有效/无效模式", "保存复盘结果", "给出下一轮动作"],
        },
        "商单交付": {
            "displayTitle": "商单交付初稿生成",
            "displaySubtitle": "把品牌 brief、创作方向、产品卖点、Tags 和博主档案上下文生成可公开编辑的飞书云文档初稿，正文是可直接发布的完整文案。",
            "operatorSummary": "用于生成商单交付初稿并写入 COM01 摘要表；创作方向、产品卖点、Tags 是必填输入，正文必须是一段完整可发布文案，PR备注、平台要求 / 禁区和博主人设 / 语气是选填约束，PR备注未填默认无特殊要求。",
            "whenToUse": ["需要把品牌 brief、创作方向、产品卖点和 Tags 生成商单交付初稿", "需要创建包含完整可发布正文、独立 Tags 和脚本表格的飞书云文档子页面", "需要把作品初稿链接、初稿时间和发布时间写入 COM01 摘要表"],
            "whenNotToUse": ["要做达人建档时用【博主-入库】", "要处理报价或商务机会时用【商务>ID】", "缺少创作方向、产品卖点或 Tags 时先补齐再交付"],
            "requiredInputs": ["品牌", "产品", "博主名称", "平台", "内容形式与规格", "初稿时间", "发布时间", "创作方向", "产品卖点", "Tags"],
            "optionalInputs": ["平台要求 / 禁区", "博主人设 / 语气", "PR备注"],
            "outputSummary": ["飞书云文档初稿", "完整可直接发布正文", "互联网所有人可编辑权限读回", "图片脚本 / 分镜脚本原生表格", "COM01 多维表摘要记录"],
            "nextActions": [_next_action("复制输入模板", action_type="copy_template"), _next_action("作品验收", "work-acceptance"), _next_action("数据复盘", "data-review")],
            "examplePrompt": default_input_template("商单交付", "business"),
            "evidenceSummary": ["用户提供的品牌 brief", "创作方向", "产品卖点", "Tags", "PR备注", "06_CreatorProfiles_达人账号档案（可选）"],
            "operatorFlow": ["填写商单交付模板", "按博主名称读取可用博主档案上下文", "校验创作方向、产品卖点和 Tags", "缺省 PR备注写入无特殊要求", "生成单一标题、完整可发布正文和独立 Tags", "创建可公开编辑 Docx 子页面", "写入 COM01 摘要表"],
        },
        "转写": {
            "displayTitle": "异步录音转写与细节保真纪要",
            "displaySubtitle": "Knowledge Bot 裸音频自动独立入队；Daily Bot 保留批次确认。任务严格 FIFO，敏感业务细节逐条保留在主纪要受限附录。",
            "operatorSummary": "在 Knowledge Bot 中直接发送一条裸音频即可立即获得独立任务 ID，同一 message ID 重放不会重复建任务；在 Daily Bot 中先核对录音批次再确认。每个任务只绑定自己的 MediaPath，并由发起 Bot 推送阶段和终态。",
            "whenToUse": ["在 Knowledge Bot 中发送单条录音并希望立即独立转写", "在 Daily Bot 中整理一批已上传录音", "需要完整保留报价、条件、技术路线、例子、争议、风险和未决信息"],
            "whenNotToUse": ["已有完整文字稿时使用【转写-文字】", "附件不可读时不会编造逐字稿", "敏感性不能作为删除、泛化或省略业务细节的理由"],
            "requiredInputs": ["Knowledge Bot：直接发送单条裸音频，无需二次确认", "Daily Bot：上传录音后发送【转写】，再确认返回的批次号"],
            "optionalInputs": ["主题", "参与人", "转写要求", "补充要求", "可访问音视频链接"],
            "outputSummary": ["独立转写任务 ID 与即时回执", "严格 FIFO 的阶段通知", "六节主纪要", "受限细节保全附录", "角色化原字稿", "非空专题附件"],
            "nextActions": [_next_action("复制 Daily Bot 输入模板", action_type="copy_template")],
            "examplePrompt": "Knowledge Bot：直接发送一条录音文件\nDaily Bot：【转写】\n要求：完整整理并保留全部业务细节",
            "evidenceSummary": ["飞书 message ID", "单消息 MediaPath", "持久化 enqueue_order", "逐段事实覆盖", "一致性与 schema artifact"],
            "operatorFlow": ["按 Bot 选择自动入队或批次确认", "持久化独立任务并立即回执", "worker 按 enqueue_order FIFO 执行", "逐段转写与角色整理", "schema 修复和一致性有界复检", "写入六节纪要与原字稿", "由发起 Bot 推送终态"],
        },
        "Brief": {
            "displayTitle": "品牌拍摄 Brief 整理落盘",
            "displaySubtitle": "把混乱或 OCR 噪声较多的品牌拍摄要求整理成可追溯 CommercialBrief。",
            "operatorSummary": "用于保存品牌、产品、展位、必拍桥段、禁忌、交付规格和审批要求；产物写入 media_vault/commercial_briefs，可作为后续【拍摄】或【商单交付】证据输入。",
            "whenToUse": ["拿到品牌拍摄 brief，需要先清洗、归档和标出不确定项", "需要把展位、产品、禁忌、交付物和验收要求拆成后续执行依据", "需要保留原始 brief 追溯而不是直接生成脚本"],
            "whenNotToUse": ["已经要生成可拍摄执行单时用【拍摄】", "要直接生成商单交付初稿时用【商单交付】", "要保存普通素材链接时用【素材】"],
            "requiredInputs": ["平台", "品牌/项目", "原始 Brief 全文"],
            "optionalInputs": ["后续用途", "整理目标", "需要重点抽取的字段"],
            "outputSummary": ["CommercialBrief artifact", "结构化品牌/产品/展位/禁忌/交付要求", "原始 brief 追溯", "不确定项", "后续拍摄执行续跑指令"],
            "nextActions": [_next_action("进入拍摄执行", "media-shooting"), _next_action("生成商单交付稿", "commercial-delivery-draft"), _next_action("人工复核", "media-growth-review"), _next_action("复制输入模板", action_type="copy_template")],
            "examplePrompt": default_input_template("Brief", "business"),
            "evidenceSummary": ["用户粘贴的原始 Brief", "LLM 结构化 CommercialBrief", "source_trace"],
            "operatorFlow": ["粘贴品牌 Brief", "LLM 清洗 OCR 噪声并抽取结构化字段", "标出不确定项和合规风险", "保存 CommercialBrief artifact", "返回拍摄执行续跑指令"],
        },
    }

    base = overrides.get(label, {})
    required_inputs = base.get("requiredInputs") or capability["commonInputs"][:4] or ["当前要处理的内容"]
    optional_inputs = base["optionalInputs"] if "optionalInputs" in base else ["账号或平台", "目标", "限制条件", "已有资料"]
    output_summary = base.get("outputSummary") or capability["commonOutputs"][:6] or ["能力处理结果", "下一步建议"]
    when_to_use = base.get("whenToUse") or capability["suitableFor"][:4] or ["需要使用该能力处理当前任务"]
    when_not_to_use = base.get("whenNotToUse") or capability["notSuitableFor"][:3] or ["任务目标不属于该能力时，先回到任务页选择入口"]
    evidence_summary = base.get("evidenceSummary") or ssot_refs[:5] or ["用户输入", "能力说明", "上下文证据"]
    next_actions = base.get("nextActions") or [_next_action("复制输入模板", action_type="copy_template")]
    media_web_owned = label != "说明" and (source_system == "media" or capability["primaryBot"] == "media")
    operator_summary = base.get("operatorSummary") or capability["description"]
    if media_web_owned:
        operator_summary = f"唯一执行入口：/openclaw/media。飞书只接收数据、文档和通知，不再执行 Media 命令。{operator_summary}"
    projection = {
        "displayTitle": base.get("displayTitle") or capability["title"],
        "displaySubtitle": base.get("displaySubtitle") or capability["description"],
        "lifecycleLayer": lifecycle or "Operate",
        "operatorSummary": operator_summary,
        "whenToUse": when_to_use,
        "whenNotToUse": when_not_to_use,
        "requiredInputs": required_inputs,
        "optionalInputs": optional_inputs,
        "outputSummary": output_summary,
        "nextActions": next_actions,
        "examplePrompt": base.get("examplePrompt") or capability["defaultInputTemplate"],
        "evidenceSummary": evidence_summary,
        "riskBadges": [_layer_label(lifecycle), _risk_label(risk), saved_as],
        "savedAs": saved_as,
        "operatorFlow": base.get("operatorFlow") or ["填写需求", "读取必要上下文", "生成结果", "保存或回复", "给出下一步"],
        "maintainerFields": [
            {"label": "canonical_capability_id", "value": canonical},
            {"label": "handler", "value": safe_text(str(item.get("handler") or "")) or "未声明"},
            {"label": "runtime capability", "value": safe_text(str(item.get("capability") or "")) or "未声明"},
            {"label": "source_system", "value": source_system},
            {"label": "execution_channel", "value": "Media Web /openclaw/media" if media_web_owned else "由 owning Bot channel 决定"},
            {"label": "produces", "value": " / ".join(produces) or "未声明"},
            {"label": "writes_to", "value": " / ".join(writes_to) or "当前 Bot 回复"},
            {"label": "ssot_refs", "value": " / ".join(ssot_refs) or "未声明"},
            {"label": "default_mode", "value": safe_text(str(item.get("default_mode") or "")) or "未声明"},
        ],
    }
    return projection


def execution_graph_for(capability: dict[str, Any], runtime_item: dict[str, Any]) -> dict[str, Any]:
    facts = capability_runtime_facts(capability, runtime_item)
    facts = enrich_runtime_facts(facts)
    return translate_facts_to_execution_graph(facts)


def capability_runtime_facts(capability: dict[str, Any], runtime_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability_id": capability["id"],
        "raw_label": capability["rawLabel"],
        "title": capability["title"],
        "description": capability["description"],
        "category": capability["category"],
        "type": capability["type"],
        "primary_bot": capability["primaryBot"],
        "task_groups": capability["taskGroups"],
        "common_inputs": capability["commonInputs"],
        "common_outputs": capability["commonOutputs"],
        "prompt_contracts": capability["llmPromptContracts"],
        "output_detail": capability["outputDetail"],
        "flow_stage_ids": capability["flowStageIds"],
        "runtime_branch_contracts": runtime_item.get("execution_branches") or [],
        "known_runtime_components": [],
    }


def enrich_runtime_facts(facts: dict[str, Any]) -> dict[str, Any]:
    capability_id_value = str(facts["capability_id"])
    components: list[dict[str, Any]] = []

    if capability_id_value == "deconstruction":
        components.extend(
            [
                {
                    "id": "download-evidence",
                    "title": "下载视频/图文证据",
                    "componentName": "selfmedia/deconstruct/viral_content::prepare_inputs",
                    "nodeType": "data_fetch",
                    "source": "selfmedia/deconstruct/viral_content/src/runner.py",
                    "summary": "解析抖音等素材链接，下载真实视频、图文和截图证据。",
                    "body": "\n".join(
                        [
                            "拆解必须基于真实下载到的内容证据。",
                            "如果未下载到真实视频或图片，流程必须失败或返回未确认完成，禁止仅根据链接、标题或用户描述生成拆解。",
                            "该阶段不直接调用主拆解 LLM；它为后续视觉读取和主拆解 prompt 准备 evidence bundle。",
                        ]
                    ),
                    "inputBoundary": ["用户消息中的素材链接", "用户对拆解重点的补充说明"],
                    "outputContract": ["本地媒体证据文件", "source_url", "evidence_bundle", "evidence_assets"],
                    "writesTo": ["本地临时下载目录", "media_vault source evidence"],
                    "completionSignals": ["至少存在一个真实视频、图片或可验证证据资产"],
                },
                {
                    "id": "vision-read",
                    "title": "视觉读取图片/视频帧",
                    "componentName": "runner.py::_evidence_parts_for_llm",
                    "nodeType": "vision_read",
                    "source": "selfmedia/deconstruct/viral_content/src/runner.py",
                    "summary": "将图片或视频帧作为 Responses image parts 直接交给主拆解 LLM。",
                    "body": "\n".join(
                        [
                            "prepare_media_evidence() 生成的图片和视频帧保持为 image parts。",
                            "runner._evidence_parts_for_llm() 直接返回全部 evidence parts，由 Codex Responses 同时消费文本、图片和音频证据。",
                            "该节点是视觉证据直传契约，不是主拆解 prompt。",
                        ]
                    ),
                    "inputBoundary": ["已下载的图片", "抽帧后的关键帧", "证据 asset_id"],
                    "outputContract": ["带 asset_id 的 image/text parts", "可被主拆解 LLM 引用的 evidence refs"],
                    "writesTo": ["LLM request parts", "运行时 evidence bundle"],
                    "completionSignals": ["Codex Responses 请求包含应消费的全部图片和文本证据"],
                },
                {
                    "id": "render-deconstruct-doc",
                    "title": "生成飞书拆解文档",
                    "componentName": "feishu_doc_writer.py::create_doc",
                    "nodeType": "document_render",
                    "source": "selfmedia/deconstruct/viral_content/src/feishu_doc_writer.py",
                    "summary": "把主拆解结果渲染为飞书 Wiki/Docx 拆解文档。",
                    "body": "该节点根据 LLM 拆解结果生成可阅读的飞书拆解文档。它是文档渲染契约，不是直接送入 LLM 的提示词。",
                    "inputBoundary": ["主拆解 LLM JSON", "证据资产", "父 Wiki 节点配置"],
                    "outputContract": ["飞书拆解文档 URL", "图文/分镜/复用建议结构"],
                    "writesTo": ["Feishu Wiki/Docx 拆解父节点"],
                    "completionSignals": ["返回 deconstruct_doc_url"],
                },
                {
                    "id": "write-source-assets",
                    "title": "写入 02A 素材源",
                    "componentName": "feishu_writer.py::write_deconstruction",
                    "nodeType": "bitable_write",
                    "source": "selfmedia/deconstruct/viral_content/src/feishu_writer.py",
                    "summary": "将原始素材登记到 Media Model v2 的素材源表。",
                    "body": "该节点写入 02A_SourceAssets_素材源，记录素材 ID、平台、来源链接、标题、证据 URI 和文档链接。它是多维表格写入契约，不是直接送入 LLM 的提示词。",
                    "inputBoundary": ["source_url", "platform", "title", "evidence_uri", "deconstruct_doc_url"],
                    "outputContract": ["SourceAsset upsert 记录"],
                    "writesTo": ["02A_SourceAssets_素材源"],
                    "completionSignals": ["素材 ID 可读回", "素材状态为已解析或等价状态"],
                },
                {
                    "id": "write-material-deconstructions",
                    "title": "写入 02B 素材拆解",
                    "componentName": "feishu_writer.py::write_deconstruction",
                    "nodeType": "bitable_write",
                    "source": "selfmedia/deconstruct/viral_content/src/feishu_writer.py",
                    "summary": "将拆解摘要和复用约束写入 Media Model v2 素材拆解表。",
                    "body": "该节点写入 02B_MaterialDeconstructions_素材拆解，记录拆解 ID、素材 ID、摘要、开头钩子、可迁移点、不可迁移点、提示词版本、模型、技能版本、置信度、证据 URI 和拆解文档链接。它是多维表格写入契约，不是直接送入 LLM 的提示词。",
                    "inputBoundary": ["主拆解 LLM JSON", "source_asset_id", "deconstruction artifact"],
                    "outputContract": ["MaterialDeconstruction upsert 记录", "feishu_record_id"],
                    "writesTo": ["02B_MaterialDeconstructions_素材拆解"],
                    "completionSignals": ["返回 feishu_record_id", "记录可通过 record_id 读回"],
                },
            ]
        )

    if capability_id_value in {"transcription", "transcription-text"}:
        components.extend(
            [
                {
                    "id": "transcribe-source",
                    "title": "音频/文本转写输入",
                    "componentName": "content_flow_client.py::transcription入口",
                    "nodeType": "data_fetch",
                    "source": "openclaw-tag-router/openclaw_app/services/content_flow_client.py",
                    "summary": "读取用户上传的音频、文本或附件；音频任务先固定消息身份和独立媒体边界。",
                    "body": "该节点负责准备转写输入，不是直接送入 LLM 的提示词。对于【转写】，Knowledge Bot 裸音频以飞书 message ID 绑定该消息自己的 MediaPath，Daily Bot 仍按批次确认；对于【转写-文字】，直接形成文字分片。后续处理不得跨消息合并 Knowledge Bot 的独立音频任务。",
                    "inputBoundary": ["用户上传音频或文本", "飞书 message ID", "附件元数据与 MediaPath", "当前 Bot 身份"],
                    "outputContract": ["单消息独立音频边界或文字分片", "source_message_id", "逐字稿分块上下文"],
                    "writesTo": ["transcription-queue", "transcription-jobs", "运行时转写输入"],
                    "completionSignals": ["音频任务的消息身份与 MediaPath 对应", "存在可供后处理的文本分片"],
                },
                {
                    "id": "transcription-consistency-loop",
                    "title": "有界一致性修订与复核",
                    "componentName": "content_flow_client.py::_summarize_dialogue_transcript_chunked",
                    "nodeType": "quality_check",
                    "source": "openclaw-tag-router/openclaw_app/services/content_flow_client.py",
                    "summary": "每轮定向修订先过 schema 再复检；坏 JSON 记为单轮失败并继续有界重试。",
                    "body": "运行时根据 consistency blocking_issues 的 repair_fields 只修改被点名的最终纪要字段。每次修订后必须先通过最终纪要 schema，再执行一致性复检；schema 修复默认最多 3 次且硬上限 5 次。默认最多执行 5 轮一致性修订，并保留逐轮 artifact；修订返回不可解析 JSON 时记录该轮失败并继续，只有耗尽上限、没有可修字段或所有后续修订均失败时才返回 pending_manual。该节点是有界状态机合同，不是直接发送给 LLM 的提示词。",
                    "inputBoundary": ["一致性检查结果", "当前最终纪要", "附件摘要", "剩余修订轮次"],
                    "outputContract": ["approved：进入最终输出", "revision_limit_exhausted：保留阻断项并转人工"],
                    "writesTo": ["转写后处理 artifact", "运行时一致性状态"],
                    "completionSignals": ["approved=true", "或记录修订轮数、最终阻断项和 pending_manual 原因"],
                },
                {
                    "id": "transcription-final-output",
                    "title": "输出逐字稿/纪要",
                    "componentName": "transcription formatter",
                    "nodeType": "document_render",
                    "source": "openclaw-tag-router/openclaw_app/router/transcription_formatters.py",
                    "summary": "输出六节主纪要、原字稿和受限细节附录；敏感性只控制权限，不删除业务细节。",
                    "body": "该节点负责输出格式，不是直接送入 LLM 的提示词。主纪要固定为 1 结论摘要、2 决策清单、3 议题分析与行动项、4 下次会议、5 细节保全附录（受限）、6 关联文档。detail_coverage 与敏感权限信息逐条写入第 5 节；任何有业务含义的敏感细节都不能删除、泛化或省略，只能标记可见范围、核验状态和公开权限。正文中至少五个项目符号且项目符号字符占比达到 90% 时，完成状态仍会被阻断。",
                    "inputBoundary": ["转写后处理结果", "一致性检查结果"],
                    "outputContract": ["六节主纪要", "第 5 节逐条受限业务细节", "原字稿", "决定、行动项与必要的待确认说明"],
                    "writesTo": ["当前 Bot 回复", "Obsidian 会议纪要/整理版", "Obsidian 会议纪要/原字稿"],
                    "completionSignals": ["内容整理低于 90% bullet-ratio 阈值且主题名非空，或返回明确失败原因"],
                },
            ]
        )
        facts["runtime_branch_contracts"] = [
            *list(facts.get("runtime_branch_contracts") or []),
            {
                "contract_id": "transcription-consistency-loop-v1",
                "anchor_node_id": "transcription-consistency-loop",
                "placement": "insert_after",
                "decision_id": "transcription-consistency-outcome",
                "title": "一致性闭环终止判定",
                "source": "openclaw-tag-router/openclaw_app/services/content_flow_client.py",
                "summary": "通过复核时输出纪要；只有耗尽修订上限或无法继续修订时才转人工。",
                "outcomes": [
                    {
                        "outcome_id": "transcription-consistency-approved",
                        "title": "一致性复核通过",
                        "edge_label": "approved",
                        "summary": "纪要通过一致性复核，继续执行最终合同校验与输出。",
                        "disposition": "continue",
                    },
                    {
                        "outcome_id": "transcription-consistency-pending-manual",
                        "title": "修订上限耗尽或无法修订",
                        "edge_label": "revision_limit_exhausted",
                        "summary": "保留最终阻断项、修订轮数和 artifact，停止业务写入并返回人工处理。",
                        "disposition": "terminal",
                    },
                ],
            },
        ]

    if capability_id_value in {"creation", "creation-xiaohongshu", "creation-douyin"}:
        components.extend(
            [
                {
                    "id": "creation-context-retrieval",
                    "title": "检索创作上下文",
                    "componentName": "selfmedia/creation/retrieval.py",
                    "nodeType": "data_fetch",
                    "source": "selfmedia-tools/selfmedia/creation/retrieval.py",
                    "summary": "读取活动、爆款、灵感、商务和账号上下文，供创作主 prompt 使用。",
                    "body": "该节点是上下文检索契约，不直接调用 LLM。它读取活动、素材、爆款、灵感、商务和账号上下文，只把可追溯候选交给创作主 prompt，缺失部分必须显式说明。",
                    "inputBoundary": ["用户创作需求", "平台", "主题", "候选范围"],
                    "outputContract": ["活动候选", "素材/爆款候选", "商务候选", "账号上下文"],
                    "writesTo": ["运行时上下文包"],
                    "completionSignals": ["候选来源和缺失原因明确"],
                },
                {
                    "id": "creation-document-render",
                    "title": "渲染创作子文档",
                    "componentName": "selfmedia/creation/writer.py",
                    "nodeType": "document_render",
                    "source": "selfmedia-tools/selfmedia/creation/writer.py",
                    "summary": "将 creator_report 渲染为飞书创作子文档。",
                    "body": "该节点控制创作者执行稿的展示结构，不直接生成业务语义。它负责把 creator_report、script_options 和证据附录渲染成可执行的飞书创作子文档，避免把原始 JSON 或评分细节放到执行区。",
                    "inputBoundary": ["creator_report", "script_options", "evidence_appendix"],
                    "outputContract": ["飞书创作子文档", "可执行分镜/发布包"],
                    "writesTo": ["Feishu 创作子文档"],
                    "completionSignals": ["返回创作文档链接"],
                },
            ]
        )

    if capability_id_value == "commercial-delivery-draft":
        components.extend(
            [
                {
                    "id": "commercial-doc-render",
                    "title": "渲染商单交付云文档",
                    "componentName": "commercial_delivery.py::_commercial_delivery_doc_blocks",
                    "nodeType": "document_render",
                    "source": "selfmedia-tools/openclaw-tag-router/openclaw_app/router/commercial_delivery.py",
                    "summary": "把 LLM JSON 初稿渲染成飞书 Docx blocks，文案区输出完整可发布正文和独立 Tags，图片脚本/分镜脚本表格由 Docx renderer 处理。",
                    "body": "该节点是商单交付文档渲染契约，不是直接发送给 LLM 的提示词。content.title 只能有一个可发布标题：用户已给标题时沿用，未给标题时才生成；正文来自 content.publish_copy，不能把多标题、正文和 CTA 混在一起；图文内容写成图片脚本，视频内容写成分镜脚本，Markdown pipe table 只作为 renderer 输入，最终必须写为 Feishu 原生表格。",
                    "inputBoundary": ["LLM 结构化商单交付 payload", "content.title 单一标题", "content.publish_copy 完整正文", "脚本类型：图片脚本 / 分镜脚本", "文档名：YYYY-MM-DD｜一句话总结"],
                    "outputContract": ["Feishu Docx blocks", "正文（可直接发布）", "独立 Tags", "原生表格 marker"],
                    "writesTo": ["Feishu Docx 子页面"],
                    "completionSignals": ["返回 document_id 和 doc URL"],
                },
                {
                    "id": "commercial-public-permission",
                    "title": "设置公开编辑权限并读回",
                    "componentName": "feishu_service.py::set_docx_public_editable",
                    "nodeType": "quality_check",
                    "source": "selfmedia-tools/openclaw-tag-router/openclaw_app/services/feishu_service.py",
                    "summary": "把生成的飞书云文档设置为互联网所有人可编辑，并读回 external_access=true 与 link_share_entity=anyone_editable。",
                    "body": "该节点是 Feishu 权限读回门禁，不是直接发送给 LLM 的提示词。权限未读回为互联网所有人可编辑时，运行时必须失败并返回明确错误，不继续写入多维表记录。",
                    "inputBoundary": ["document_id", "Feishu drive permission public API"],
                    "outputContract": ["external_access=true", "link_share_entity=anyone_editable"],
                    "writesTo": ["Feishu Docx 权限设置"],
                    "completionSignals": ["权限读回为互联网所有人可编辑"],
                },
                {
                    "id": "commercial-native-table-readback",
                    "title": "读回原生表格",
                    "componentName": "feishu_service.py::document_has_native_table",
                    "nodeType": "quality_check",
                    "source": "selfmedia-tools/openclaw-tag-router/openclaw_app/services/feishu_service.py",
                    "summary": "检查 Docx 根 blocks 是否存在 block_type=31，防止图片脚本/分镜脚本退化为 Markdown 表格。",
                    "body": "该节点是 Docx 读回门禁，不是直接发送给 LLM 的提示词。未读到 block_type=31 时，运行时必须失败，不把不合格文档当成已交付。",
                    "inputBoundary": ["document_id", "Docx block readback"],
                    "outputContract": ["至少一个 block_type=31 原生表格"],
                    "writesTo": ["运行时质量门禁状态"],
                    "completionSignals": ["Docx readback 找到原生表格"],
                },
                {
                    "id": "commercial-delivery-bitable-write",
                    "title": "写入商单交付摘要表",
                    "componentName": "commercial_delivery.py::_commercial_delivery_write_record",
                    "nodeType": "bitable_write",
                    "source": "selfmedia-tools/openclaw-tag-router/openclaw_app/router/commercial_delivery.py",
                    "summary": "把作品初稿链接、初稿时间、发布时间、平台、内容形式、脚本类型和权限状态写入 COM01 多维表。",
                    "body": "该节点是多维表格写入契约，不是直接发送给 LLM 的提示词。只有 Docx 已创建、公开编辑权限读回通过、原生表格读回通过后，才允许写入 COM01_CommercialDelivery_商单交付。",
                    "inputBoundary": ["已通过读回的 doc URL", "商单交付字段 payload", "MEDIA_OS_COMMERCIAL_DELIVERY_URL"],
                    "outputContract": ["COM01 记录 ID", "记录读回 fields", "record URL"],
                    "writesTo": ["COM01_CommercialDelivery_商单交付"],
                    "completionSignals": ["Feishu Bitable record_id 可读回"],
                },
            ]
        )

    if facts.get("raw_label") == "【删除】":
        components.extend(
            [
                {
                    "id": "delete-target-resolution",
                    "title": "解析删除目标",
                    "componentName": "universal delete runtime::resolve_target",
                    "nodeType": "data_fetch",
                    "source": "openclaw-tag-router universal delete route",
                    "summary": "只接受明确 ID 或 URL 作为删除目标，按适配器发现对应能力和产物，禁止按模糊描述猜测要删除的对象。",
                    "body": "\n".join(
                        [
                            "删除能力必须先解析显式目标 ID，包括 asset_xxx 公开素材引用、review_xxx 公开复盘引用、run_router_xxx、历史归档 ID、inbox/archive 文件名或 URL 中可解析 ID。",
                            "当前自动删除覆盖 adapter：universal_deletion、source_asset、published_post_review、archive_or_creation_run、transcription；新增自动删除 adapter 时必须同步扩展本图和 Harness guard。",
                            "目标归属不明确、没有适配器覆盖、或缺少路径证据时，只能返回预览中的人工处理项，不能自动扩大删除范围。",
                            "该节点是删除目标解析契约，不是直接送入 LLM 的提示词。",
                        ]
                    ),
                    "inputBoundary": ["用户显式提供的目标 ID 或 URL", "模式：预览 / 确认删除", "确认说明"],
                    "outputContract": ["目标 ID", "匹配到的能力 adapter", "候选删除对象清单", "缺失或冲突原因"],
                    "writesTo": ["运行时删除目标上下文"],
                    "completionSignals": ["目标唯一明确", "没有模糊匹配或猜测删除"],
                },
                {
                    "id": "delete-preview-plan",
                    "title": "生成删除预览",
                    "componentName": "universal delete runtime::preview",
                    "nodeType": "supporting_contract",
                    "source": "openclaw-tag-router universal delete route",
                    "summary": "在执行任何删除前展示将影响的记录、文档和文件。",
                    "body": "\n".join(
                        [
                            "预览模式只生成将删除/跳过/无法访问的对象清单，不执行删除。",
                            "预览必须按对象类型列出影响范围，包括 archive/inbox、转写中间产物、创作运行记录、飞书文档或本地文件候选。",
                            "该节点是删除预览契约，不是直接送入 LLM 的提示词。",
                        ]
                    ),
                    "inputBoundary": ["已解析目标 ID", "匹配 adapter", "关联记录、文档和文件候选"],
                    "outputContract": ["删除预览清单", "跳过/无法访问对象", "下一步确认指令"],
                    "writesTo": ["当前 Bot 回复草稿"],
                    "completionSignals": ["预览回复包含 run_id 和对象级影响范围"],
                },
                {
                    "id": "delete-confirmation-gate",
                    "title": "确认删除门禁",
                    "componentName": "universal delete runtime::confirm_gate",
                    "nodeType": "quality_check",
                    "source": "openclaw-tag-router universal delete route",
                    "summary": "确认删除必须同时满足目标 ID、确认模式和确认说明，不能由预览自动升级为执行。",
                    "body": "\n".join(
                        [
                            "只有用户明确选择确认删除，并且确认说明与同一个目标 ID 对齐时，才允许进入执行删除。",
                            "预览请求、缺少确认说明、目标 ID 变化或目标清单变化时，必须停在预览/待确认状态。",
                            "该节点是删除确认门禁契约，不是直接送入 LLM 的提示词。",
                        ]
                    ),
                    "inputBoundary": ["预览清单", "确认删除模式", "确认说明", "目标 ID"],
                    "outputContract": ["允许执行 / 停止并要求确认 的判断"],
                    "writesTo": ["运行时确认状态"],
                    "completionSignals": ["确认对象和执行对象一致", "未确认时没有删除动作"],
                },
                {
                    "id": "delete-execution-boundary",
                    "title": "执行删除边界",
                    "componentName": "universal delete runtime::execute",
                    "nodeType": "storage_write",
                    "source": "openclaw-tag-router universal delete route",
                    "summary": "只删除预览清单中被确认的对象，并保留跳过、失败和执行结果。",
                    "body": "\n".join(
                        [
                            "执行删除只能覆盖预览清单中已经确认的对象，不能扩展到其他运行、其他能力或模糊关联资源。",
                            "source_asset 覆盖 02A_SourceAssets_素材源记录的唯一匹配删除与读回；published_post_review 按 review_ 公开引用先删除并读回 H01 指标快照，再删除并读回 04 发布复盘主记录；archive_or_creation_run 覆盖历史归档/创作运行；transcription 覆盖转写 json、markdown、会议纪要、原字稿和中间目录；universal_deletion 统一编排预览和确认。",
                            "每个对象都必须返回已删除、跳过或失败原因；部分失败不能回复笼统处理完成。",
                            "该节点是删除执行边界契约，不是直接送入 LLM 的提示词。",
                        ]
                    ),
                    "inputBoundary": ["确认通过的目标 ID", "确认过的对象清单", "允许自动删除根目录"],
                    "outputContract": ["已删除对象", "跳过对象", "失败对象和原因"],
                    "writesTo": ["workspace archive/inbox", "转写中间产物", "03_CreationRuns_创作运行", "04_PostReviews_发布复盘", "H01_MetricSnapshot_作品指标快照", "Feishu 创作文档", "本地能力产物"],
                    "completionSignals": ["删除结果逐对象可解释", "失败/跳过不被吞掉"],
                },
            ]
        )

    facts["known_runtime_components"] = components
    return facts


def translate_facts_to_execution_graph(facts: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(
        node_id: str,
        title: str,
        component_name: str,
        node_type: str,
        *,
        source: str,
        summary: str,
        body: str,
        input_boundary: list[str] | None = None,
        output_contract: list[str] | None = None,
        writes_to: list[str] | None = None,
        completion_signals: list[str] | None = None,
        public_summary: list[str] | None = None,
        prompt_contract_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_body = str(body)
        if node_type != "actual_llm_prompt" and not any(marker in normalized_body for marker in ("不是直接", "非直接", "不直接")):
            normalized_body = "该节点是执行契约，不是直接发送给 LLM 的提示词。\n\n" + normalized_body
        item = {
            "id": node_id,
            "title": title,
            "componentName": component_name,
            "nodeType": node_type,
            "source": display_source(source),
            "summary": summary,
            "body": normalized_body,
            "inputBoundary": input_boundary or [f"{facts['raw_label']} 触发上下文"],
            "outputContract": output_contract or [summary],
            "writesTo": writes_to or ["当前 Bot 回复"],
            "completionSignals": completion_signals or ["返回用户可理解的处理结果"],
            "publicSummary": public_summary or [summary],
        }
        if prompt_contract_id:
            item["promptContractId"] = prompt_contract_id
        nodes.append(item)
        return item

    def connect(source_id: str, target_id: str, label: str | None = None) -> None:
        edge = {"from": source_id, "to": target_id}
        if label:
            edge["label"] = label
        edges.append(edge)

    def display_source(value: Any) -> str:
        text = str(value or "").strip()
        if text == "Knowledge bot AGENTS.md":
            return "Knowledge 能力提示词段落"
        return text

    detail = facts["output_detail"]
    destinations = [safe_text(str(item)) for item in detail.get("destinations", []) if str(item).strip()]
    boundaries = [safe_text(str(item)) for item in detail.get("boundaries", []) if str(item).strip()]
    outputs = [safe_text(str(item)) for item in facts.get("common_outputs", []) if str(item).strip()]
    inputs = [safe_text(str(item)) for item in facts.get("common_inputs", []) if str(item).strip()]
    entry_trigger_boundary = (
        "消息只允许以 【商务>ID】 或作者参数入口 【商务>作者ID】 触发"
        if facts["raw_label"] == "【商务>ID】"
        else f"消息只允许以 {facts['raw_label']} 触发"
    )

    entry = node(
        "entry",
        f"触发入口 {facts['raw_label']}",
        "tag-router capability dispatch",
        "entry",
        source="tag_capabilities.py",
        summary=f"用户以 {facts['raw_label']} 触发 {facts['title']}。",
        body="\n".join(
            [
                f"能力标签：{facts['raw_label']}",
                f"能力标题：{facts['title']}",
                "",
                "该节点只描述入口分发，不是直接发送给 LLM 的提示词。",
            ]
        ),
        input_boundary=[entry_trigger_boundary, *inputs[:4]],
        output_contract=["进入该能力的统一执行链路", f"主归属 Bot：{facts['primary_bot']}"],
        writes_to=["tag-router 路由上下文"],
        completion_signals=["能力 ID 和入口标签已确定"],
    )
    parse = node(
        "input-parse",
        "解析输入与边界",
        "Capability Runtime Facts translator",
        "input_parse",
        source="openclaw-bot-center/scripts/generateDashboardData.py",
        summary="根据能力输入提示、分类和任务组确定本次执行边界。",
        body="\n".join(
            [
                "该节点由能力事实翻译器生成。",
                "它说明运行时需要从用户正文、附件、被回复对象或显式上下文中读取哪些信息。",
                "它不是直接发送给 LLM 的提示词。",
            ]
        ),
        input_boundary=inputs or [f"{facts['raw_label']} 用户正文"],
        output_contract=["结构化执行边界", "缺失信息或证据不足时的待确认条件"],
        writes_to=["运行时请求上下文"],
        completion_signals=["输入范围明确", "不跨能力处理"],
    )
    connect(entry["id"], parse["id"])
    previous_ids = [parse["id"]]

    runtime_components = list(facts.get("known_runtime_components") or [])
    pre_prompt_components = [
        item
        for item in runtime_components
        if item.get("nodeType") in {"data_fetch", "vision_read"} and not str(item.get("id", "")).startswith("transcription-final")
    ]
    post_prompt_components = [item for item in runtime_components if item not in pre_prompt_components]

    for component in pre_prompt_components:
        current = node(
            str(component["id"]),
            str(component["title"]),
            str(component["componentName"]),
            str(component["nodeType"]),
            source=str(component["source"]),
            summary=str(component["summary"]),
            body=str(component["body"]),
            input_boundary=[safe_text(str(item)) for item in component.get("inputBoundary", [])],
            output_contract=[safe_text(str(item)) for item in component.get("outputContract", [])],
            writes_to=[safe_text(str(item)) for item in component.get("writesTo", [])],
            completion_signals=[safe_text(str(item)) for item in component.get("completionSignals", [])],
        )
        for previous_id in previous_ids:
            connect(previous_id, current["id"])
        previous_ids = [current["id"]]

    prompt_contracts = list(facts.get("prompt_contracts") or [])
    prompt_nodes: list[dict[str, Any]] = []
    for index, contract in enumerate(prompt_contracts):
        prompt_kind = str(contract.get("promptKind") or "")
        node_type = "actual_llm_prompt" if prompt_kind == "actual_llm_prompt" else str(prompt_kind or "generated_execution_contract")
        prompt_node = node(
            f"prompt-{safe_text(str(contract['id']))}",
            str(contract["title"]),
            str(contract["componentName"]),
            node_type,
            source=str(contract["source"]),
            summary=str(contract["purpose"]),
            body=str(contract["promptBody"]),
            input_boundary=[safe_text(str(item)) for item in contract.get("inputBoundary", [])],
            output_contract=[safe_text(str(item)) for item in contract.get("outputContract", [])],
            writes_to=[safe_text(str(item)) for item in contract.get("writesTo", [])],
            completion_signals=["LLM 返回符合输出契约的结构化或可读结果"] if node_type == "actual_llm_prompt" else ["执行契约已明确"],
            public_summary=[safe_text(str(item)) for item in contract.get("publicSummary", [])],
            prompt_contract_id=str(contract["id"]),
        )
        if index == 0:
            for previous_id in previous_ids:
                connect(previous_id, prompt_node["id"])
        else:
            connect(prompt_nodes[-1]["id"], prompt_node["id"])
        prompt_nodes.append(prompt_node)

    if prompt_nodes:
        previous_ids = [prompt_nodes[-1]["id"]]
    else:
        generated = node(
            "generated-execution-contract",
            "生成的执行契约",
            "能力中心生成器",
            "generated_execution_contract",
            source="openclaw-bot-center/scripts/generateDashboardData.py",
            summary="当前能力没有独立的 LLM prompt，由能力事实生成执行边界说明。",
            body="\n".join(
                [
                    "当前能力中心没有发现该能力独立的 LLM prompt。",
                    "本节点是根据能力说明、输入输出和边界自动生成的执行契约。",
                    "它不是运行时直接送入 LLM 的提示词。",
                ]
            ),
            input_boundary=inputs or [f"{facts['raw_label']} 用户正文"],
            output_contract=outputs or ["按能力说明返回结果"],
            writes_to=destinations or ["当前 Bot 回复"],
            completion_signals=["执行契约已明确"],
        )
        for previous_id in previous_ids:
            connect(previous_id, generated["id"])
        previous_ids = [generated["id"]]

    for component in post_prompt_components:
        current = node(
            str(component["id"]),
            str(component["title"]),
            str(component["componentName"]),
            str(component["nodeType"]),
            source=str(component["source"]),
            summary=str(component["summary"]),
            body=str(component["body"]),
            input_boundary=[safe_text(str(item)) for item in component.get("inputBoundary", [])],
            output_contract=[safe_text(str(item)) for item in component.get("outputContract", [])],
            writes_to=[safe_text(str(item)) for item in component.get("writesTo", [])],
            completion_signals=[safe_text(str(item)) for item in component.get("completionSignals", [])],
        )
        for previous_id in previous_ids:
            connect(previous_id, current["id"])
        previous_ids = [current["id"]]

    output_targets = destinations or [safe_text(str(item)) for item in set().union(*(set(contract.get("writesTo", [])) for contract in prompt_contracts))] or ["当前 Bot 回复"]
    if not any(node_item["nodeType"] in {"document_render", "bitable_write", "storage_write"} for node_item in nodes):
        output_node_type = "storage_write" if any("Obsidian" in item or "media_vault" in item for item in output_targets) else "document_render"
        output_node = node(
            "output-materialize",
            "产物落地与展示",
            "capability output contract",
            output_node_type,
            source="capability.outputDetail",
            summary="根据能力输出契约生成回复、文档、表格记录或本地沉淀。",
            body="\n".join(
                [
                    "该节点根据 outputDetail 和 prompt contract 的 writesTo 生成。",
                    "它描述产物落地位置和展示边界，不是直接发送给 LLM 的提示词。",
                ]
            ),
            input_boundary=outputs or ["上游执行结果"],
            output_contract=outputs or ["用户可读结果"],
            writes_to=output_targets,
            completion_signals=["产物位置明确", "用户可见输出可读"],
        )
        for previous_id in previous_ids:
            connect(previous_id, output_node["id"])
        previous_ids = [output_node["id"]]

    check = node(
        "completion-check",
        "完成校验",
        "capability completion guard",
        "quality_check",
        source="capability.outputDetail + route completion guards",
        summary="检查该能力是否满足输出、写入和边界要求。",
        body="\n".join(
            [
                "该节点描述完成条件和失败时的边界。",
                "它不是直接发送给 LLM 的提示词。",
                "如果关键产物缺失，能力不应回复处理完成。",
            ]
        ),
        input_boundary=["上游产物", "写入结果", "边界条件"],
        output_contract=["完成 / 未确认完成 / 待补充 的判断"],
        writes_to=["当前 Bot 回复状态"],
        completion_signals=(boundaries[:4] or ["输出不越界", "关键产物存在", "失败时说明原因"]),
    )
    for previous_id in previous_ids:
        connect(previous_id, check["id"])

    reply = node(
        "reply",
        "回复用户",
        "tag-router reply contract",
        "reply",
        source="tag-router TaskResult",
        summary="把执行结果整理为用户可读回复。",
        body="\n".join(
            [
                "该节点定义用户可见回复格式。",
                "成功时应包含关键产物或下一步；失败或缺证时应说明原因。",
                "它不是直接发送给 LLM 的提示词。",
            ]
        ),
        input_boundary=["完成校验结果", "用户可见产物链接或记录 ID"],
        output_contract=["用户可读 reply", "必要时包含文档链接、记录 ID 或下一步"],
        writes_to=["当前 Bot 对话"],
        completion_signals=["用户收到明确结果"],
    )
    connect(check["id"], reply["id"])

    def graph_node(node_id: str) -> dict[str, Any]:
        result = next((item for item in nodes if item["id"] == node_id), None)
        if result is None:
            raise ValueError(f"execution branch references missing node: {node_id}")
        return result

    def take_outgoing(node_id: str) -> list[dict[str, Any]]:
        outgoing = [edge for edge in edges if edge["from"] == node_id]
        edges[:] = [edge for edge in edges if edge["from"] != node_id]
        return outgoing

    def branch_body(contract: dict[str, Any]) -> str:
        labels = [str(item.get("edge_label") or "") for item in contract.get("outcomes") or []]
        return "\n".join(
            [
                str(contract.get("summary") or "运行时根据明确状态选择后续路径。"),
                "",
                "分支状态：",
                *[f"- {label}" for label in labels],
                "",
                "该节点投影运行时源码声明的分支合同，不是直接发送给 LLM 的提示词。",
            ]
        )

    def add_branch_outcomes(
        contract: dict[str, Any],
        decision_id: str,
        default_continue_target: str,
    ) -> None:
        for outcome in contract.get("outcomes") or []:
            outcome_id = str(outcome["outcome_id"])
            summary = str(outcome["summary"])
            outcome_node = node(
                outcome_id,
                str(outcome["title"]),
                str(contract["contract_id"]),
                str(outcome.get("node_type") or "supporting_contract"),
                source=str(contract["source"]),
                summary=summary,
                body="\n".join(
                    [
                        summary,
                        "",
                        f"运行时结果：{outcome['edge_label']}",
                        "该节点是运行时分支结果，不是直接发送给 LLM 的提示词。",
                    ]
                ),
                input_boundary=[f"{contract['title']} 的运行时判断结果"],
                output_contract=[summary],
                writes_to=[safe_text(str(item)) for item in outcome.get("writes_to") or ["当前 Bot 回复"]],
                completion_signals=[safe_text(str(item)) for item in outcome.get("completion_signals") or [summary]],
                public_summary=[summary],
            )
            if outcome.get("disposition") == "terminal":
                outcome_node["terminalState"] = str(outcome["edge_label"])
            connect(decision_id, outcome_node["id"], str(outcome["edge_label"]))
            target_node_id = str(outcome.get("target_node_id") or "")
            if not target_node_id:
                target_node_id = reply["id"] if outcome.get("disposition") == "terminal" else default_continue_target
            if target_node_id:
                graph_node(target_node_id)
                connect(outcome_node["id"], target_node_id)

    for contract in facts.get("runtime_branch_contracts") or []:
        anchor_node_id = str(contract["anchor_node_id"])
        placement = str(contract["placement"])
        if placement == "replace_node":
            decision = graph_node(anchor_node_id)
            outgoing = take_outgoing(anchor_node_id)
            if len(outgoing) != 1:
                raise ValueError(f"replace-node branch {contract['contract_id']} requires one outgoing edge")
            decision.update(
                {
                    "title": str(contract["title"]),
                    "componentName": str(contract["contract_id"]),
                    "nodeType": "quality_check",
                    "source": display_source(contract["source"]),
                    "summary": str(contract["summary"]),
                    "body": branch_body(contract),
                    "inputBoundary": ["上游运行结果", "运行时明确状态或动作"],
                    "outputContract": [str(item["edge_label"]) for item in contract.get("outcomes") or []],
                    "writesTo": ["运行时分支状态"],
                    "completionSignals": ["分支状态与运行时合同一致"],
                    "publicSummary": [str(contract["summary"])],
                }
            )
            add_branch_outcomes(contract, anchor_node_id, str(outgoing[0]["to"]))
            continue
        if placement == "insert_after":
            graph_node(anchor_node_id)
            outgoing = take_outgoing(anchor_node_id)
            if len(outgoing) != 1:
                raise ValueError(f"insert-after branch {contract['contract_id']} requires one outgoing edge")
            decision = node(
                str(contract["decision_id"]),
                str(contract["title"]),
                str(contract["contract_id"]),
                "quality_check",
                source=str(contract["source"]),
                summary=str(contract["summary"]),
                body=branch_body(contract),
                input_boundary=["上游运行结果", "运行时明确状态或动作"],
                output_contract=[str(item["edge_label"]) for item in contract.get("outcomes") or []],
                writes_to=["运行时分支状态"],
                completion_signals=["分支状态与运行时合同一致"],
                public_summary=[str(contract["summary"])],
            )
            connect(anchor_node_id, decision["id"])
            add_branch_outcomes(contract, decision["id"], str(outgoing[0]["to"]))
            continue
        raise ValueError(f"unsupported runtime branch placement: {placement}")

    for contract in prompt_contracts:
        post_validation = contract.get("postValidation")
        if not post_validation:
            continue
        prompt_node_id = f"prompt-{safe_text(str(contract['id']))}"
        graph_node(prompt_node_id)
        outgoing = take_outgoing(prompt_node_id)
        if len(outgoing) != 1:
            raise ValueError(f"post-validation prompt {contract['id']} requires one outgoing edge")
        validator_id = f"post-validation-{safe_text(str(contract['id']))}"
        validator = node(
            validator_id,
            "全局 JSON 后置校验",
            str(post_validation["contractId"]),
            "quality_check",
            source=str(post_validation["source"]),
            summary=f"按 {post_validation['profile']} profile 校验模型 JSON，决定继续执行或停止等待人工。",
            body="\n".join(
                [
                    f"validation_contract：{post_validation['contractId']}",
                    f"profile：{post_validation['profile']}",
                    "成功状态：validated",
                    "人工状态：pending_manual",
                    "只有 validated payload 可以进入后续业务节点；pending_manual 不得到达文档、表格或存储写入。",
                    "该节点是运行时全局后置校验合同，不是直接发送给 LLM 的提示词。",
                ]
            ),
            input_boundary=["模型返回的 JSON object", f"validation contract {post_validation['contractId']}"],
            output_contract=["validated", "pending_manual"],
            writes_to=["运行时校验状态"],
            completion_signals=["字段、类型、证据和状态满足运行时合同", "或明确返回人工处理原因"],
            public_summary=["展示该 Prompt 在运行时实际绑定的全局 JSON 后置校验。"],
        )
        pending = node(
            f"pending-manual-{safe_text(str(contract['id']))}",
            "停止业务写入并转人工确认",
            str(post_validation["contractId"]),
            "supporting_contract",
            source=str(post_validation["source"]),
            summary="模型明确要求人工处理，或 JSON 在校验后仍不满足合同；停止后续业务写入。",
            body="\n".join(
                [
                    "状态：pending_manual",
                    "保留缺失字段、证据不足或合同失败原因，返回用户补充信息或人工处理要求。",
                    "该节点不能连接到 document_render、bitable_write 或 storage_write。",
                    "该节点是运行时人工处理边界，不是直接发送给 LLM 的提示词。",
                ]
            ),
            input_boundary=["后置校验返回 pending_manual"],
            output_contract=["人工处理原因", "待补充信息", "用户可读下一步"],
            writes_to=["当前 Bot 回复"],
            completion_signals=["没有业务写入节点被执行", "用户收到明确补充要求"],
            public_summary=["后置校验未通过时停止业务写入。"],
        )
        pending["terminalState"] = "pending_manual"
        connect(prompt_node_id, validator["id"])
        connect(validator["id"], str(outgoing[0]["to"]), "validated")
        connect(validator["id"], pending["id"], "pending_manual")
        connect(pending["id"], reply["id"])

    has_actual_prompt = any(str(contract.get("promptKind") or "") == "actual_llm_prompt" for contract in prompt_contracts)
    graph_kind = "manual" if facts.get("known_runtime_components") else ("generated_from_prompts" if has_actual_prompt else "generated_contract")
    validate_execution_graph_edges(nodes, edges)
    return {
        "id": f"{facts['capability_id']}-execution-graph",
        "title": f"{facts['raw_label']} 执行链路",
        "summary": "由运行时能力事实、Prompt 校验绑定、业务分支合同和输出契约自动翻译，展示真实可能路径而非节点数组顺序。",
        "graphKind": graph_kind,
        "nodes": nodes,
        "edges": edges,
    }


def validate_execution_graph_edges(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    node_ids = {str(item.get("id") or "") for item in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("execution graph node ids must be unique")
    seen_edges: set[tuple[str, str]] = set()
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source_id = str(edge.get("from") or "")
        target_id = str(edge.get("to") or "")
        if source_id not in node_ids or target_id not in node_ids:
            raise ValueError(f"execution graph edge has unknown endpoint: {source_id} -> {target_id}")
        if source_id == target_id:
            raise ValueError(f"execution graph edge cannot reference itself: {source_id}")
        edge_key = (source_id, target_id)
        if edge_key in seen_edges:
            raise ValueError(f"execution graph edge is duplicated: {source_id} -> {target_id}")
        seen_edges.add(edge_key)
        outgoing.setdefault(source_id, []).append(edge)
    for source_id, source_edges in outgoing.items():
        if len(source_edges) > 1 and any(not str(edge.get("label") or "").strip() for edge in source_edges):
            raise ValueError(f"execution graph branch edges require labels: {source_id}")

    root_id = str(nodes[0].get("id") or "") if nodes else ""
    reachable: set[str] = set()
    queue = [root_id] if root_id else []
    while queue:
        node_id = queue.pop(0)
        if node_id in reachable:
            continue
        reachable.add(node_id)
        queue.extend(str(edge["to"]) for edge in outgoing.get(node_id, []))
    unreachable = sorted(node_ids - reachable)
    if unreachable:
        raise ValueError(f"execution graph has unreachable nodes: {unreachable}")

    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        indegree[str(edge["to"])] += 1
    acyclic_queue = [node_id for node_id, count in indegree.items() if count == 0]
    acyclic_count = 0
    while acyclic_queue:
        node_id = acyclic_queue.pop(0)
        acyclic_count += 1
        for edge in outgoing.get(node_id, []):
            target_id = str(edge["to"])
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                acyclic_queue.append(target_id)
    if acyclic_count != len(nodes):
        raise ValueError("execution graph must be acyclic")


def output_hints(label: str, category: str, result: str) -> list[str]:
    label_outputs: dict[str, list[str]] = {
        "思考": ["原始思考证据", "事实/判断/假设结构", "决策候选", "字段完整的待审批动作候选或人工处理状态"],
        "修改": ["同一文档的安全文本 patch", "修改点处理说明", "保护块和人工项", "无补充记录或追加内容残留"],
        "归档": ["周记知识条目", "逻辑检查摘要", "Obsidian 写入结果"],
        "补全": ["补全后的自然文本", "周记认知条目", "处理说明"],
        "认知": ["周记认知条目", "核心认知 / 可复用场景 / 行动提醒 / 反例边界", "沉淀文本", "处理说明"],
        "学习": ["学习拆解文档", "周记知识回链", "结构化学习笔记"],
        "学习-整理": ["学习整理文档", "周记知识回链", "结构化学习笔记"],
        "调研": ["调研结论", "证据摘要", "不确定项", "下一步建议"],
        "删除": ["删除预览或执行结果", "json/markdown/中间产物/文档/文件动作清单"],
        "复盘": ["复盘结论", "问题/原因/下次动作", "可同步归档摘要"],
        "日记": ["独立日记文件", "一段整理后总结", "底部原文", "周 Archieve 日期块投影", "周记可读取索引"],
        "周记": ["固定周记总结", "动态主题簇", "日记索引", "样本不足状态"],
        "说明": ["能力说明文档链接", "可用标签和边界"],
        "最近": ["最近记录摘要", "筛选结果"],
        "同步": ["同步候选摘要", "成功/失败结果", "待人工处理项"],
        "状态": ["任务状态", "最近任务匹配结果", "下一步提示"],
        "衣橱": ["衣橱单品记录", "系统生成衣物ID", "识别字段和待补信息", "衣橱写入结果"],
        "穿搭": ["今日穿搭建议", "旅行行李清单", "使用到的衣橱单品", "需要补充的位置或衣物"],
        "Brief": ["CommercialBrief artifact", "结构化品牌/产品/展位/禁忌/交付要求", "原始 brief 追溯", "后续拍摄执行续跑指令"],
        "商单交付": ["飞书云文档初稿", "互联网所有人可编辑权限读回", "图片脚本 / 分镜脚本原生表格", "COM01 多维表摘要记录"],
        "转写": ["独立转写任务 ID", "FIFO 阶段通知", "六节主纪要", "受限细节保全附录", "角色化原字稿"],
        "转写-文字": ["整理后的文字稿", "六节主纪要", "受限细节保全附录", "角色化原字稿"],
    }
    if label in label_outputs:
        return label_outputs[label]
    if label == "创作-拍摄执行":
        return ["首屏分镜脚本原生表格", "拍摄路线", "镜头清单", "人员和场地安排", "B 方案", "现场 checklist"]
    if category == "creation":
        return ["创作初稿", "结构建议", "发布检查项"]
    if category == "material":
        return ["素材分析", "结构拆解", "可复用方向"]
    if category == "daily":
        return ["执行清单", "提醒或状态更新"]
    if category == "wardrobe":
        return ["衣橱记录或穿搭推荐", "上下文缺口", "下一步补充项"]
    if category == "development":
        return ["开发需求卡", "验收标准", "本地状态"]
    if category in {"knowledge", "research"}:
        return ["结构化摘要", "知识归档", "后续问题"]
    if category == "review":
        return ["复盘/验收结论", "证据", "下一步动作"]
    if category == "social":
        return ["人物或人脉档案", "边界提示", "下一步跟进"]
    return [result[:44] + ("..." if len(result) > 44 else "")]


def output_detail(label: str, category: str) -> dict[str, list[str]]:
    special: dict[str, dict[str, list[str]]] = {
        "思考": {
            "contentForms": ["原始思考证据", "事实/判断/假设结构", "真实决策候选", "待审批副作用候选"],
            "destinations": ["DeepMath CEO Thinking / 思考收件箱", "DeepMath CEO Thinking / 决策池", "DeepMath CEO Thinking / 审批记录"],
            "nextActions": ["在 DeepMath AI4Math Bot 授权私聊发送，或在显式 allowlist 群中由授权提交人 @Bot 发送", "群内收到 ID 后转私聊查看完整结果；等待 U4 审批入口后逐项审批候选"],
            "boundaries": ["DeepMath 账号和显式发送人 allowlist 专属", "群聊必须 @Bot 且只返回收件 ID/私聊提示", "只保存字段完整的候选，不创建任务、提醒、通知或日历事件", "模型、证据或候选字段不完整时进入人工处理，不使用规则 fallback"],
        },
        "灵感": {
            "contentForms": ["碎片想法归档", "未来可展开内容线", "周记灵感小节摘要"],
            "destinations": ["Obsidian / Daily 本地归档", "周记 # 灵感 小节"],
            "nextActions": ["复制到对应 Bot 发送", "后续需要做成素材证据时转入【素材】；需要直接写稿时转入【创作】"],
            "boundaries": ["不是创作运行记录", "不写入 03_CreationRuns_创作运行"],
        },
        "灵感>vlog": {
            "contentForms": ["vlog 灵感卡", "附件素材时序索引", "原始表达保存摘要"],
            "destinations": ["Media 本地/Obsidian 灵感归档", "大文件只保留 iCloud Drive 索引和临时缓存说明"],
            "nextActions": ["复制到 Media bot 发送", "需要立项时转入【素材】生成 SourceAsset，或直接转入【创作】"],
            "boundaries": ["不是创作运行记录", "服务器不长期保存大文件原件"],
        },
        "策略": {
            "contentForms": ["账号-赛道策略候选", "内容支柱建议", "证据缺口", "下一步能力节点"],
            "destinations": ["media_vault/account_track_strategy_runs", "稳定摘要再进入 AccountTrackStrategy"],
            "nextActions": ["补账号、平台、赛道和复盘证据", "进入素材、调研或选题节点"],
            "boundaries": ["不新建第二套账号画像", "证据不足时返回 pending/manual"],
        },
        "素材": {
            "contentForms": ["SourceAsset artifact", "显式链接", "素材摘要", "source_trace"],
            "destinations": ["media_vault/source_assets"],
            "nextActions": ["继续进入调研、选题、拆解、创作或拍摄节点", "用【复核】通过后再进入 dashboard 可见集合"],
            "boundaries": ["默认落 media_vault/source_assets；长期素材库投影必须走 02A/02B 契约", "素材入口只保留【素材】且不设置 alias", "不把链接描述当成已读取正文事实"],
        },
        "选题": {
            "contentForms": ["DecisionBrief artifact", "候选选题", "证据缺口", "推荐下一节点"],
            "destinations": ["media_vault/decision_briefs", "必要摘要进入决策轨迹"],
            "nextActions": ["证据足够时进入创作", "证据不足时返回调研或素材补充"],
            "boundaries": ["不直接替用户决定发布", "证据不足不生成正式创作结论"],
        },
        "拍摄": {
            "contentForms": ["拍摄执行候选", "镜头/场景/人员约束", "待补证据", "下一步"],
            "destinations": ["创作运行或 media_vault draft artifact"],
            "nextActions": ["补场地、人物、镜头和素材线索", "进入创作-拍摄执行或发布准备"],
            "boundaries": ["未接入完整 workflow 时返回 pending/manual", "不伪造成片计划"],
        },
        "检查": {
            "contentForms": ["checklist 查询", "作品验收入口", "publish_readiness_gate 规划节点"],
            "destinations": ["当前 Bot 回复", "既有【创作检查】/【作品验收】链路"],
            "nextActions": ["只有场景时查看清单", "有稿件时改用【作品验收】", "发布包 readiness gate 本地 runner 接入后再执行"],
            "boundaries": ["不自动发布", "不伪造尚未接入的 readiness gate 结论"],
        },
        "发布包": {
            "contentForms": ["PublishingPack", "标题/封面/正文/标签", "评论引导", "发布前检查项"],
            "destinations": ["media_vault/publishing_packs", "Feishu 只允许摘要和 artifact 链接"],
            "nextActions": ["人工确认后再去平台发布", "需要时进入检查节点"],
            "boundaries": ["不自动发布到抖音/小红书/B站", "不新增草稿事实或平台数据"],
        },
        "复核": {
            "contentForms": ["ReviewDecision", "quality_status 晋升", "review_history 留痕"],
            "destinations": ["media_vault/*/result.json"],
            "nextActions": ["通过后进入 dashboard 可见集合", "废弃后停止后续链路", "证据不足时保留 pending_review"],
            "boundaries": ["只更新已有 Growth artifact", "不写 03_CreationRuns_创作运行", "不新增 Feishu 表记录"],
        },
        "账号": {
            "contentForms": ["OwnedMediaAccount 查询", "账号内容地图", "账号画像来源", "待补字段"],
            "destinations": ["OwnedMediaAccount / media_memory 只读投影"],
            "nextActions": ["进入策略或赛道节点", "人工确认账号画像缺口"],
            "boundaries": ["只代表自有账号实体，不读取或写入 06_CreatorProfiles 外部达人档案", "不新建 Feishu 字段"],
        },
        "赛道": {
            "contentForms": ["TrackRegistry 查询", "赛道别名候选", "账号-赛道关系线索", "待确认命名"],
            "destinations": ["TrackRegistry 只读投影", "必要候选落 media_vault"],
            "nextActions": ["进入账号-赛道策略", "人工确认别名和父赛道"],
            "boundaries": ["不让自由文本赛道长期分叉", "不直接改 live schema"],
        },
        "待办-开发": {
            "contentForms": ["正式开发任务卡", "机器与地址锚点", "验收口径", "Codex 追溯状态"],
            "destinations": ["Obsidian checklist", "飞书多维表格结构化台账", "checklist 勾选后的详细任务文档"],
            "nextActions": ["复制到 Daily bot 发送", "完成后勾选 Obsidian checklist 触发 Mac 侧 Codex high 后置梳理"],
            "boundaries": ["不是临时开发碎片入口", "不在任务卡塞完整复盘"],
        },
        "今日": {
            "contentForms": ["今日执行清单", "提醒/日程/待办摘要", "开发任务摘要"],
            "destinations": ["Daily 本地归档读取结果", "当前 Bot 回复"],
            "nextActions": ["发送【日记】补今日记录", "发送【周记】提取本周总结", "按 Obsidian checklist 勾选执行"],
            "boundaries": ["只读最近归档", "不打开多维表格", "不新增提醒"],
        },
        "日记": {
            "contentForms": ["每日独立日记", "一段整理后总结", "底部原文", "周 Archieve 日期块投影", "openclaw 日记块锚点"],
            "destinations": ["Obsidian 日记/YYYY-MM-DD.md", "Obsidian Archieve/YYYYMMDD-YYYYMMDD.md 的 #YYYYMMDD -> ##日记", "周记读取索引"],
            "nextActions": ["复制到 Daily bot 发送", "晚上 22:00 按模板填写", "本周结束后发送【周记】"],
            "boundaries": ["空正文不写入", "不写飞书多维表格", "不把单篇日记升级成人格结论"],
        },
        "周记": {
            "contentForms": ["固定周记总结", "动态主题簇", "日记索引", "样本不足状态"],
            "destinations": ["Obsidian Archieve/YYYYMMDD-YYYYMMDD.md"],
            "nextActions": ["复制到 Daily bot 发送", "补齐缺失日记后重新生成", "从周记提取下周行为实验"],
            "boundaries": ["只读取独立日记文件", "少于 3 篇只写样本不足索引", "不生成稳定人格判断"],
        },
        "开发-完成": {
            "contentForms": ["开发需求完成状态", "任务匹配结果", "验收摘要"],
            "destinations": ["Daily 本地开发需求归档"],
            "nextActions": ["复制到 Daily bot 发送", "必要时补充验收证据"],
            "boundaries": ["不创建提醒", "不写入日程多维表格"],
        },
        "开发-验证": {
            "contentForms": ["开发需求待验证状态", "任务匹配结果", "验证口径摘要"],
            "destinations": ["Daily 本地开发需求归档"],
            "nextActions": ["复制到 Daily bot 发送", "补充要验证的行为和证据"],
            "boundaries": ["不创建提醒", "不写入日程多维表格"],
        },
        "创作": {
            "contentForms": ["标题候选", "正文/脚本初稿", "结构建议", "发布检查项"],
            "destinations": ["飞书创作任务池子文档", "03_CreationRuns_创作运行可读运行索引", "Mac 本地项目文件由 Mac 侧素材流程生成"],
            "nextActions": ["复制到 Media bot 发送", "人工确认方向", "已有本地素材时补本地路径或批次说明给 Mac 侧接力"],
            "boundaries": ["不自动证明 Mac 已有素材", "不替代最终发布和审美判断"],
        },
        "创作>小红书": {
            "contentForms": ["小红书标题", "图文正文", "标签建议", "发布检查项"],
            "destinations": ["飞书创作任务池子文档", "03_CreationRuns_创作运行可读运行索引", "本地素材和项目 Markdown 由 Mac 侧处理"],
            "nextActions": ["复制到 Media bot 发送", "人工确认封面、图片顺序和发布时间"],
            "boundaries": ["网页只生成待发送模板", "实际写入由 Media bot 完成"],
        },
        "创作>抖音": {
            "contentForms": ["抖音脚本", "开头钩子", "分镜建议", "标题和发布检查项"],
            "destinations": ["飞书创作任务池子文档", "03_CreationRuns_创作运行可读运行索引", "本地素材和项目 Markdown 由 Mac 侧处理"],
            "nextActions": ["复制到 Media bot 发送", "人工确认节奏、镜头和剪辑方向"],
            "boundaries": ["不直接剪辑视频", "不自动读取 Mac 本地素材"],
        },
        "创作-拍摄执行": {
            "contentForms": ["首屏分镜脚本原生表格", "拍摄路线", "镜头清单", "人员和场地安排", "B 方案", "现场 checklist", "交付物清单", "分级发布包：作品标题、封面图方案、发布文案、话题互动、声音方案"],
            "destinations": ["飞书创作任务池子文档", "03_CreationRuns_创作运行可读运行索引"],
            "nextActions": ["复制到 Media bot 发送", "现场按 checklist 执行", "拍完后再进入素材整理或创作链路"],
            "boundaries": ["飞书文档标题后必须先展示分镜脚本原生表格", "发布包使用 H3 下一级标题区分作品标题、封面图方案、发布文案、话题互动和声音方案", "封面图方案是拍摄或选帧说明，不冒充已生成图片文件", "证据保留在 CreationRun artifact，前台文档不渲染证据附录", "这是拍摄执行单，不是灵感卡", "不默认创建 Mac 素材任务"],
        },
        "活动": {
            "contentForms": ["活动 Brief", "平台活动规则摘要", "参与方式/参与形式/提交要求", "时间节点", "人工待补字段"],
            "destinations": ["01_近期活动", "活动字段：平台名称、活动Brief、填写要点、参与方式、参与形式、提交要求、活动开始时间、活动结束时间、返稿链接、活动文档链接等"],
            "nextActions": ["复制到 Media bot 发送", "人工补齐平台、时间、链接和提交要求", "需要做内容时再转入创作或拍摄执行"],
            "boundaries": ["这是活动信息入库，不是创作运行记录", "不写入 03_CreationRuns_创作运行", "看不清或缺失的活动字段应标为需人工补充"],
        },
        "拆解": {
            "contentForms": ["逐镜头拆解", "素材结构分析", "同款拆解/结构库 Markdown", "素材拆解记录"],
            "destinations": ["02B_MaterialDeconstructions_素材拆解", "必要时沉淀到 Obsidian Media 同款拆解或结构库"],
            "nextActions": ["复制到 Media bot 发送", "人工决定是否转成创作模式或创作任务"],
            "boundaries": ["这是素材拆解记录，不是创作运行记录", "不默认写入 03_CreationRuns_创作运行"],
        },
        "创作咨询": {
            "contentForms": ["创作决策建议", "活动/素材/商务/复盘依据摘要", "下一步建议"],
            "destinations": ["当前 Bot 回复", "不新建文档"],
            "nextActions": ["复制到 Media bot 发送", "人工决定是否转入创作或拍摄执行"],
            "boundaries": ["只回答决策问题", "不写入 03_CreationRuns_创作运行"],
        },
        "作品验收": {
            "contentForms": ["满足/不满足/不确定判定", "证据", "缺口", "修改建议", "项目状态推进建议"],
            "destinations": ["飞书回复或验收文档", "正文带项目且证据满足时可推进 Obsidian 项目状态"],
            "nextActions": ["复制到 Media bot 发送", "人工决定 Final、返修或发布"],
            "boundaries": ["不替代人的最终发布决定", "证据不足时应返回不确定"],
        },
        "数据复盘": {
            "contentForms": ["复盘结论", "关键指标解释", "问题清单", "下次动作", "账号记忆候选"],
            "destinations": ["数据复盘表", "复盘文档", "媒体账号记忆", "正文带项目时可同步到项目 10_review.md"],
            "nextActions": ["复制到 Media bot 发送", "人工确认是否调整选题、发布时间或内容结构"],
            "boundaries": ["必须先上传抖音或小红书后台数据截图，上传完成后再发送【数据复盘】指令", "没有截图时返回缺少证据，不凭空判断后台数据"],
        },
        "自媒体-认知": {
            "contentForms": ["自媒体认知条目", "纠正/沉淀说明", "同标题整合结果"],
            "destinations": ["自媒体认知池子文档"],
            "nextActions": ["复制到 Media bot 发送", "人工确认是否作为规则或创作参考"],
            "boundaries": ["不是数据复盘表", "不写入 03_CreationRuns_创作运行"],
        },
        "创作检查": {
            "contentForms": ["checklist 云文档链接", "按场景可审阅检查项"],
            "destinations": ["当前 Bot 回复"],
            "nextActions": ["复制到 Media bot 发送", "按返回的 checklist 人工检查作品"],
            "boundaries": ["不新建文档", "不写入版本", "不写入 03_CreationRuns_创作运行"],
        },
        "转写": {
            "contentForms": ["独立任务回执", "严格 FIFO 阶段通知", "六节会议纪要", "第 5 节细节保全附录（受限）", "角色化原字稿", "非空专题附件"],
            "destinations": ["Local transcription-queue / transcription-jobs", "Obsidian 会议纪要/整理版（含受限细节附录）", "Obsidian 会议纪要/原字稿", "发起任务的 Bot 主动通知"],
            "nextActions": ["Knowledge Bot 直接发送一条裸音频", "Daily Bot 上传录音并确认返回的批次号", "用任务 ID 查询状态或删除对应转写产物"],
            "boundaries": ["Knowledge Bot 每条裸音频自动独立入队且无需二次确认", "Daily Bot 保留批次确认", "同一 message ID 重放不得重复创建任务", "任务必须按持久化 enqueue_order FIFO", "任何有业务含义的敏感细节都不能删除、泛化或省略，只能标记可见范围、核验状态和公开权限", "附件不可读时不编造逐字稿", "不是自媒体知识表写入"],
        },
        "转写-文字": {
            "contentForms": ["文字稿整理", "问题清单", "说话人标注", "六节会议纪要", "第 5 节细节保全附录（受限）"],
            "destinations": ["Obsidian 会议纪要/整理版（含受限细节附录）", "Obsidian 会议纪要/原字稿"],
            "nextActions": ["复制到 Media bot 发送", "粘贴文字稿或上传文字附件"],
            "boundaries": ["任何有业务含义的敏感细节都不能删除、泛化或省略，只能标记可见范围、核验状态和公开权限", "不是自媒体知识表写入", "缺少原文时不生成假纪要"],
        },
        "商单交付": {
            "contentForms": ["商单交付初稿", "完整可直接发布正文", "飞书云文档子页面", "图片脚本 / 分镜脚本原生表格", "多维表交付摘要"],
            "destinations": ["Feishu Docx 子页面（互联网所有人可编辑）", "COM01_CommercialDelivery_商单交付", "作品初稿链接、初稿时间、发布时间等摘要字段"],
            "nextActions": ["复制到 Media bot 发送", "补齐创作方向、产品卖点和 Tags", "PR 审核后进入作品验收或数据复盘"],
            "boundaries": ["创作方向、产品卖点、Tags 必填", "文案区必须输出完整可直接发布正文，不把多标题、正文和 CTA 混在一起", "PR备注选填；未填默认无特殊要求", "平台要求 / 禁区选填；未填默认无特殊要求", "博主人设 / 语气选填；未填则读取 06_CreatorProfiles_达人账号档案作为上下文", "文档权限必须读回为互联网所有人可编辑", "图文输出图片脚本，视频输出分镜脚本", "脚本表格必须是飞书原生表格", "不写入 03_CreationRuns_创作运行", "不把 05B 商务机会表当交付稿事实源"],
        },
        "Brief": {
            "contentForms": ["CommercialBrief", "品牌/产品/展位/必拍/禁忌/交付结构化清单", "原始 brief 追溯", "后续拍摄执行续跑指令"],
            "destinations": ["media_vault/commercial_briefs/<artifact_id>/result.json"],
            "nextActions": ["复制到 Media bot 发送", "人工复核 OCR 不确定项", "用【拍摄】续接生成拍摄执行单"],
            "boundaries": ["只整理和落盘 brief", "不直接创建 03_CreationRuns", "不生成商单交付初稿", "不替代甲方发布前书面确认", "LLM 不可用时返回 pending_manual，不用关键词硬猜语义"],
        },
        "待办": {
            "contentForms": ["Obsidian 独立每日待办 checklist", "飞书提醒记录的 Obsidian 镜像 checkbox", "显式完成状态同步结果"],
            "destinations": ["Obsidian 待办/YYYY-MM-DD.md", "有明确时间/提醒/截止时写入 OpenClaw 提醒与日程多维表格"],
            "nextActions": ["复制到 Daily bot 发送", "在 Obsidian 勾选 checklist；带 feishu_record 的已勾选项由 Mac 侧显式同步为飞书主状态=已完成"],
            "boundaries": ["普通 checklist 不写飞书", "没有 feishu_record 的 checklist 只保留在 Obsidian", "飞书反向改 Obsidian 不做", "模型容量重试耗尽时不创建、不落盘，并返回 DAILY_LLM_MODEL_AT_CAPACITY、底层容量详情和稍后重试建议"],
        },
        "日程": {
            "contentForms": ["飞书日历事件", "提醒与日程记录"],
            "destinations": ["飞书日历", "OpenClaw 提醒与日程多维表格"],
            "nextActions": ["复制到 Daily bot 发送", "人工确认时间、地点和参与人"],
            "boundaries": ["时间不清楚时应先补充或确认"],
        },
        "自媒体知识": {
            "contentForms": ["图文/视频结构化分析", "可复用认知", "行动建议"],
            "destinations": ["自媒体知识表", "必要时沉淀到 Obsidian Media 知识库"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工决定是否转成创作素材或规则"],
            "boundaries": ["视频链路可能需要下载/转写/分析证据", "LLM 失败时不应写入假结论"],
        },
        "归档": {
            "contentForms": ["周记知识条目", "来源/关键事实/行动项整合", "逻辑检查摘要"],
            "destinations": ["Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 知识 小节"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工确认标题、日期或归档周", "需要飞书入库时必须在正文里明确要求"],
            "boundaries": ["默认不写飞书知识表", "正文没有日期时按当前消息所在周", "不整段粗暴粘贴原文"],
        },
        "补全": {
            "contentForms": ["补全后的自然文本", "周记认知条目", "处理说明"],
            "destinations": ["Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工确认日期范围、目标周记文件和待补全文字来源"],
            "boundaries": ["只基于已提供文字、附件、被回复对象和明确加载的上下文", "默认不写飞书知识表", "缺少正文时直接返回缺少待补全文字", "无法确认日期范围或目标周记文件时只返回整理后内容，不假设路径"],
        },
        "认知": {
            "contentForms": ["周记认知条目", "核心认知 / 可复用场景 / 行动提醒 / 反例边界", "沉淀文本", "处理说明"],
            "destinations": ["Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工确认标题、日期和需要沉淀的经历/观察/判断"],
            "boundaries": ["只基于已提供正文、附件、被回复对象和明确加载的上下文", "默认不写飞书知识表", "不处理原始音频/视频 ASR", "缺少正文时直接返回缺少待沉淀内容", "无法确认日期范围或目标周记文件时只返回整理后内容，不假设路径"],
        },
        "学习": {
            "contentForms": ["学习拆解文档", "概念解释", "结构化学习笔记"],
            "destinations": ["Obsidian 学习/每日学习", "Obsidian 周记 # 知识 小节"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工确认主题和需要拆解的材料"],
            "boundaries": ["默认不写飞书知识表", "不把缺证据内容写成事实"],
        },
        "学习-整理": {
            "contentForms": ["学习整理文档", "结构化知识笔记", "周记知识链接"],
            "destinations": ["Obsidian 学习/每日学习", "Obsidian 周记 # 知识 小节"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工确认整理目标和原文来源"],
            "boundaries": ["默认不写飞书知识表", "不替代来源核验"],
        },
        "调研": {
            "contentForms": ["ExternalResearchBrief", "证据摘要", "内容机会", "待补证据项"],
            "destinations": ["media_vault/research_briefs"],
            "nextActions": ["复制到 Media bot 发送", "补充链接、粘贴文字或可核验来源", "进入选题"],
            "boundaries": ["只处理 Media 内容机会", "没有显式证据时返回 pending_manual", "不委托 Knowledge 深度研究", "不把推测写成事实"],
        },
        "修改": {
            "contentForms": ["同一文档的分块文本 patch", "保护块和人工项", "拍摄执行叙事规划与规划审查", "拍摄执行 CreationRun 整份回洗", "逐镜连贯性验收", "canonical renderer 原生表格与分级发布包重建", "商单交付图片脚本原生表格 insert_table_row 补行", "读回校验证据"],
            "destinations": ["被回复或正文指定的同一个飞书文档", "拍摄执行文档对应的原 CreationRun artifact"],
            "nextActions": ["在飞书里回复目标文档或粘贴文档 URL", "写明修改要求；需要额外边界时再补约束"],
            "boundaries": ["必须有明确目标文档", "先读取文档结构并识别文档家族", "普通文档只修改同一文档的可安全文本块", "拍摄执行文档必须唯一映射原 CreationRun", "拍摄执行回洗先生成并审核结构化叙事规划", "每个产品连续成章；无明确setup/payoff时禁止A→B→A主体回流", "逐镜审核相邻转场、主体回流和场地跳转", "连贯性低于90分或任何问题未清零时禁止写入", "拍摄执行回洗只用 canonical shooting renderer 清空重建原链接", "拍摄执行发布包使用H3下一级标题区分作品标题、封面图方案、发布文案、话题互动和声音方案", "拍摄执行回洗失败不得降级到通用 patch", "分镜置顶且证据附录不在创作者文档展示", "保护图片、附件、callout 和产品事实", "商单交付图片脚本原生表格可用 insert_table_row 补足行", "真实删除图片、替换图片或未验证结构调整仍列为人工项", "不新建 v2 文档", "不生成补充记录", "不追加内容或尾部补丁块", "旧【补充】/【去补丁】入口不保留迁移入口"],
        },
        "复盘": {
            "contentForms": ["复盘结论", "问题/原因/下次动作", "可同步归档摘要"],
            "destinations": ["本地复盘归档", "配置允许时同步到对应飞书目标"],
            "nextActions": ["复制到对应 Bot 发送", "补充项目、内容、数据或事实依据", "需要后台截图指标时改用数据复盘"],
            "boundaries": ["普通复盘不是数据复盘表", "需要事实或数据依据", "不替代作品验收"],
        },
        "整理": {
            "contentForms": ["最近记录摘要", "按标签/日期/数量筛选的归档汇总", "整理条件和整理结果"],
            "destinations": ["本地整理输出归档", "当前 Bot 回复", "配置允许时同步到对应飞书目标"],
            "nextActions": ["复制到对应 Bot 发送", "必要时补充标签、日期或数量范围", "需要继续沉淀时再转归档或同步"],
            "boundaries": ["读取已有本地归档，不是能力说明入口", "不写飞书多维表格", "不生成状态或同步诊断"],
        },
        "说明": {
            "contentForms": ["当前 Bot 能力说明", "重点入口", "标签索引", "输入格式和边界"],
            "destinations": ["当前 Bot 回复", "能力说明文档链接"],
            "nextActions": ["复制到对应 Bot 发送", "正文写当前 Bot、能力标签或自然语言需求以切换说明对象"],
            "boundaries": ["只返回说明", "不执行归档、创作、入库或同步", "不展示私密运行日志"],
        },
        "最近": {
            "contentForms": ["最近记录摘要", "按数量/标签/日期筛选结果"],
            "destinations": ["当前 Bot 回复", "本地归档读取结果"],
            "nextActions": ["复制到对应 Bot 发送", "可补充最近 N 条、标签或今天等筛选条件"],
            "boundaries": ["只读本地归档", "不补同步", "不修改记录"],
        },
        "同步": {
            "contentForms": ["同步候选摘要", "成功/失败结果", "待人工处理项"],
            "destinations": ["目标系统由原记录规则决定", "当前 Bot 回复"],
            "nextActions": ["复制到对应 Bot 发送", "同步后用状态或最近核对结果"],
            "boundaries": ["只补同步已有未同步记录", "失败会返回 pending/manual", "不凭空创建新业务内容"],
        },
        "状态": {
            "contentForms": ["任务状态", "最近任务匹配结果", "下一步提示"],
            "destinations": ["当前 Bot 回复"],
            "nextActions": ["复制到对应 Bot 发送", "提供任务 ID；不提供时查询最近任务"],
            "boundaries": ["只读归档 frontmatter", "不修改任务状态", "不触发同步或删除"],
        },
        "删除": {
            "contentForms": ["删除预览或执行结果", "json/markdown/中间产物/文档/文件动作清单", "跳过/失败原因"],
            "destinations": ["workspace archive/inbox、转写中间产物、03_CreationRuns 及关联文档/文件", "当前 Bot 回复"],
            "nextActions": ["先发送目标 ID 预览", "确认无误后再发送确认删除 目标 ID 执行"],
            "boundaries": ["必须提供明确 ID 或可解析 URL", "默认只是预览", "不按模糊描述盲删"],
        },
        "衣橱": {
            "contentForms": ["衣橱单品记录", "系统生成衣物ID", "识别字段", "待补信息", "图片/截图附件引用"],
            "destinations": ["衣橱单品库"],
            "nextActions": ["复制到 Daily bot 发送", "补旧衣物截图时带衣物ID或直接回复入库确认消息", "人工确认待补信息"],
            "boundaries": ["只写衣橱单品库", "不写其他业务域表", "无法确认旧截图属于哪件衣服时会要求补充，不猜测更新对象"],
        },
        "穿搭": {
            "contentForms": ["今日穿搭建议", "旅行行李清单", "备选单品", "需要补充的位置或衣物"],
            "destinations": ["穿搭/行李建议文件"],
            "nextActions": ["复制到 Daily bot 发送", "没有位置、目的地或已登记默认位置时先补充位置", "需要新增衣物时先用【衣橱】"],
            "boundaries": ["只读取衣橱单品库", "按明确位置或目的地自动获取天气", "不要求手填天气", "不用服务器位置、历史消息或普通待办正文猜当前位置", "只保存推荐结果", "不回写衣橱事实", "不写其他业务域表"],
        },
        "社交": {
            "contentForms": ["人物交互档案", "事实摘要", "关系分析", "下一步建议"],
            "destinations": ["Social bot 本地/Obsidian 档案", "符合规则时可同步一人一份飞书云文档"],
            "nextActions": ["复制到 Social bot 发送", "人工确认隐私边界和下一步动作"],
            "boundaries": ["公开能力中心不展示具体人名、聊天原文或私密资料"],
        },
        "人脉": {
            "contentForms": ["人脉档案", "合作线索", "跟进建议"],
            "destinations": ["Social bot 本地/Obsidian 人脉档案"],
            "nextActions": ["复制到 Social bot 发送", "人工确认是否跟进"],
            "boundaries": ["不写飞书多维表格", "不展示私密联系方式"],
        },
        "博主": {
            "contentForms": ["已归档博主查询结果", "外部系统唯一ID", "账号名称/作者ID/主页链接", "结构化身份信息"],
            "destinations": ["06_CreatorProfiles_达人账号档案"],
            "nextActions": ["复制到 Media bot 发送", "人工确认查询关键词或平台"],
            "boundaries": ["只读取已归档外部达人/竞品/合作博主档案", "不是自有账号画像入口", "不写入 Social 私密人脉资料"],
        },
        "博主-入库": {
            "contentForms": ["达人账号档案 upsert", "身份定位", "身份标签", "公开表达边界", "可创作身份卖点"],
            "destinations": ["06_CreatorProfiles_达人账号档案"],
            "nextActions": ["复制到 Media bot 发送", "补齐平台、作者ID/平台ID、主页链接和身份信息"],
            "boundaries": ["写入外部达人账号档案，不写 OwnedMediaAccount", "不写 Social 私密人脉表", "同平台同作者ID应更新同一档案"],
        },
    }
    if label in special:
        return with_destination_links(label, category, special[label])

    if category == "material":
        return with_destination_links(label, category, {
            "contentForms": ["素材分析", "定位判断", "结构拆解", "可复用方向"],
            "destinations": ["飞书创作任务池子文档", "03_CreationRuns_创作运行可读运行索引", "本地素材文件由 Mac 侧素材流程管理"],
            "nextActions": ["复制到 Media bot 发送", "人工确认素材是否进入正式创作"],
            "boundaries": ["网页不上传素材", "附件仍需发到对应 Bot 对话"],
        })
    if category == "creation":
        return with_destination_links(label, category, {
            "contentForms": ["创作建议", "初稿", "结构化清单", "发布检查项"],
            "destinations": ["飞书创作任务池子文档", "03_CreationRuns_创作运行可读运行索引"],
            "nextActions": ["复制到 Media bot 发送", "人工确认是否立项或发布"],
            "boundaries": ["不默认读取 Mac 本地素材", "不直接发布"],
        })
    if category == "daily":
        return with_destination_links(label, category, {
            "contentForms": ["执行清单", "提醒记录", "状态更新"],
            "destinations": ["OpenClaw 提醒与日程归档", "需要时写入飞书提醒/日历"],
            "nextActions": ["复制到 Daily bot 发送", "按 Obsidian checklist 或对应 Daily 能力继续推进"],
            "boundaries": ["不处理内容创作正文"],
        })
    if category == "wardrobe":
        return with_destination_links(label, category, {
            "contentForms": ["衣橱单品记录或穿搭建议"],
            "destinations": ["衣橱单品库", "穿搭/行李建议文件"],
            "nextActions": ["复制到 Daily bot 发送", "缺少位置、目的地或默认位置时先补充位置；Daily/待办/日程的明确地点可作为位置来源"],
            "boundaries": ["只写该能力声明的目标", "不写其他业务域表"],
        })
    if category == "development":
        return with_destination_links(label, category, {
            "contentForms": ["开发需求卡", "问题背景", "验收标准", "状态更新"],
            "destinations": ["Daily 本地开发需求归档", "必要时进入开发过程文档"],
            "nextActions": ["复制到 Daily bot 发送", "人工确认优先级和验收"],
            "boundaries": ["不直接改代码", "不自动创建日程提醒"],
        })
    if category == "knowledge":
        return with_destination_links(label, category, {
            "contentForms": ["结构化摘要", "知识卡", "调研结论", "后续问题"],
            "destinations": ["Knowledge bot 知识归档", "Obsidian 知识/研究目录"],
            "nextActions": ["复制到 Knowledge bot 发送", "人工确认是否转为规则、素材或任务"],
            "boundaries": ["证据不足时应标不确定", "不把推测写成事实"],
        })
    if category == "research":
        return with_destination_links(label, category, {
            "contentForms": ["ExternalResearchBrief", "证据摘要", "内容机会", "待补证据项"],
            "destinations": ["media_vault/research_briefs"],
            "nextActions": ["复制到 Media bot 发送", "补充链接、粘贴文字或可核验来源", "进入选题"],
            "boundaries": ["只处理 Media 内容机会", "没有显式证据时返回 pending_manual", "不委托 Knowledge 深度研究", "不把推测写成事实"],
        })
    if category == "social":
        return with_destination_links(label, category, {
            "contentForms": ["人物/人脉档案", "事实摘要", "跟进建议"],
            "destinations": ["Social bot 本地/Obsidian 档案"],
            "nextActions": ["复制到 Social bot 发送", "人工确认隐私边界"],
            "boundaries": ["不公开具体对象资料", "不展示聊天原文"],
        })
    if category == "business":
        return with_destination_links(label, category, {
            "contentForms": ["达人身份信息", "商务线索", "报价/授权/排期字段候选"],
            "destinations": ["Media OS 达人/商务相关表或文档"],
            "nextActions": ["复制到 Media bot 发送", "人工确认商务真实性和授权边界"],
            "boundaries": ["不凭空补商务价格", "需要主页或商务信息证据"],
        })
    return with_destination_links(label, category, {
        "contentForms": ["能力说明", "查询结果", "状态或同步提示"],
        "destinations": ["当前 Bot 回复", "必要时更新对应系统记录"],
        "nextActions": ["复制到对应 Bot 发送", "按回复继续补充或确认"],
        "boundaries": ["网页本身不执行业务写入"],
    })


def with_destination_links(label: str, category: str, detail: dict[str, list[str]]) -> dict[str, list[Any]]:
    links: list[dict[str, str]] = []
    activity_table = destination_link(
        "01_近期活动",
        registry_url("platform_event"),
        "Feishu Bitable",
        "Media OS 平台活动 Brief、参与规则、时间节点、链接和人工待补字段的当前写入表。",
    )
    creation_runs = destination_link(
        "03_CreationRuns_创作运行",
        registry_url("creation_run"),
        "Feishu Bitable",
        "Media 创作、拍摄执行和素材交接后的运行索引当前写入表。",
    )
    content_projects = destination_link(
        "00_Projects_项目看板",
        content_os_url("Projects"),
        "Feishu Bitable",
        "Content OS 项目状态和项目包索引。",
    )
    content_tasks = destination_link(
        "01_Tasks_任务队列",
        content_os_url("Tasks"),
        "Feishu Bitable",
        "云端派发到 Mac 或项目协作的任务队列。",
    )
    source_assets = {
        "label": "media_vault/source_assets",
        "url": "#/capabilities/detail/media-source-asset",
        "storageType": "Local artifact store",
        "description": "SourceAsset 当前唯一事实源；02A/02B 只作为显式投影目标，不是默认写入位置。",
    }
    material_deconstructions = destination_link(
        "02B_MaterialDeconstructions_素材拆解",
        registry_url("material_deconstruction"),
        "Feishu Bitable",
        "素材拆解和结构化分析记录。",
    )
    post_reviews = destination_link(
        "04_PostReviews_发布复盘",
        registry_url("post_review"),
        "Feishu Bitable",
        "发布后复盘主记录。",
    )
    metric_snapshot = destination_link(
        "H01_MetricSnapshot_作品指标快照",
        registry_url("post_metric_snapshot"),
        "Feishu Bitable",
        "作品数据指标快照。",
    )
    business_accounts = destination_link(
        "05A_BusinessAccounts_商务账号",
        registry_url("business_account"),
        "Feishu Bitable",
        "商务账号身份与联系方式结构化记录。",
    )
    business_opportunities = destination_link(
        "05B_BusinessOpportunities_商务机会",
        registry_url("business_opportunity"),
        "Feishu Bitable",
        "商务机会、报价、授权、排期线索。",
    )
    commercial_delivery_url = commercial_delivery_target_url()
    commercial_delivery = destination_link(
        "COM01_CommercialDelivery_商单交付",
        commercial_delivery_url,
        "Feishu Bitable",
        "商单交付摘要表，记录作品初稿链接、初稿时间、发布时间、脚本类型和公开编辑权限状态。",
    )
    commercial_delivery_doc = destination_link(
        "Feishu Docx 子页面（互联网所有人可编辑）",
        f"{commercial_delivery_url}#docx-child-pages" if commercial_delivery_url else None,
        "Feishu Wiki/Docx",
        "商单交付初稿正文；包含完整可直接发布正文、独立 Tags，并使用原生表格承载图片脚本/分镜脚本。",
    )
    creator_profiles = destination_link(
        "06_CreatorProfiles_达人账号档案",
        registry_url("creator_profile"),
        "Feishu Bitable",
        "达人账号档案和公开身份信息。",
    )
    wardrobe_items = destination_link(
        "衣橱",
        wardrobe_registry_url("wardrobe_items"),
        "Feishu Bitable",
        "Wardrobe OS 单品库；【衣橱】写入，穿搭推荐只读。",
    )
    daily_table = destination_link(
        DAILY_CONFIG.get("name", "OpenClaw 提醒与日程 v2"),
        DAILY_CONFIG.get("url"),
        "Feishu Bitable / Calendar",
        "Daily bot 的提醒、待办、日程记录。",
    )
    knowledge_table = destination_link(
        KNOWLEDGE_CONFIG.get("name", "OpenClaw 自媒体知识"),
        KNOWLEDGE_CONFIG.get("url"),
        "Feishu Bitable",
        "Knowledge bot 的自媒体知识结构化沉淀表。",
    )

    no_auto_destination_links = {
        "灵感",
        "灵感>vlog",
        "待办-开发",
        "今日",
        "周记",
        "开发-完成",
        "开发-验证",
        "修改",
        "创作咨询",
        "自媒体-认知",
        "创作检查",
        "作品验收",
        "转写",
        "转写-文字",
        "复盘",
        *OBSIDIAN_KNOWLEDGE_LABELS,
    }
    creation_run_labels = {
        "创作",
        "创作>小红书",
        "创作>抖音",
        "创作-拍摄执行",
    }

    if label in no_auto_destination_links:
        pass
    elif label == "活动":
        links.extend(compact_links(activity_table))
    elif label in creation_run_labels:
        links.extend(compact_links(creation_runs))
    if label == "素材":
        links.extend(compact_links(source_assets))
    if label == "拆解":
        links.extend(compact_links(material_deconstructions))
    if label == "数据复盘":
        links.extend(compact_links(post_reviews, metric_snapshot))
    if label in {"待办", "日程"}:
        links.extend(compact_links(daily_table))
    if label == "删除":
        links.extend(compact_links(creation_runs))
    if label == "自媒体知识":
        links.extend(compact_links(knowledge_table))
    if label in {"商务>ID"}:
        links.extend(compact_links(business_accounts, business_opportunities, creator_profiles))
    if label == "商单交付":
        links.extend(compact_links(commercial_delivery_doc, commercial_delivery))
    if label in {"博主", "博主-入库"}:
        links.extend(compact_links(creator_profiles))
    if label in WARDROBE_LABELS:
        links.extend(compact_links(wardrobe_items))

    detail["destinationLinks"] = compact_links(*links)
    return detail


def default_input_template(label: str, category: str) -> str:
    del category
    contract = get_input_contract(label)
    if contract is None:
        raise RuntimeError(f"【{label}】缺少 canonical input contract")
    return canonical_default_input_template(label, contract)
def suitable_for(label: str, category: str) -> list[str]:
    label_suitable: dict[str, list[str]] = {
        "思考": ["需要把 DeepMath CEO 的原始文字、链接、语音、图片或文件先保存为证据，再由一次 LLM 区分事实、判断、假设，并形成字段完整的决策/最小实验/动作候选时使用。"],
        "修改": ["需要定向修改已有飞书文档时使用；普通文档走安全文本 patch，拍摄执行文档从原 CreationRun 整份回洗并通过 canonical renderer 重建同一链接。"],
        "归档": ["需要把知识、学习材料或资料条目整理进 Obsidian 周记 # 知识 小节时使用。"],
        "补全": ["需要把已转写文字或半成品内容补全成 Obsidian 周记 # 认知 条目时使用。"],
        "认知": ["需要把经历、观察或判断提炼成以后还能复用的认知、行动提醒、反例或边界条件时使用。"],
        "学习": ["需要拆解概念或学习材料，并生成学习文件和周记回链时使用。"],
        "学习-整理": ["需要把课程、笔记或长资料强制按整理类学习文档沉淀时使用。"],
        "调研": ["需要围绕一个明确问题得到调研结论、依据和不确定项时使用。"],
        "删除": ["需要按历史归档 ID、创作运行 ID 或可解析 URL 预览/确认删除关联记录、文档、中间产物和本地文件时使用。"],
        "复盘": ["需要记录项目、内容或账号的事实复盘、结论和下一步时使用。"],
        "日记": ["需要把当天值得保留的事实、情绪、判断、退缩、开发、经验或承诺写入独立日记时使用。"],
        "周记": ["需要按周读取日记，提取重复触发、逃避模式、关键决策、开发经验和下周行为实验时使用。"],
        "说明": ["不知道某个 Bot 能力、标签格式或边界时使用。"],
        "最近": ["需要查看最近本地归档记录，并按数量、标签或日期筛选时使用。"],
        "同步": ["需要把未同步的本地归档补同步到对应飞书文档时使用。"],
        "状态": ["需要按任务 ID 或最近任务查询归档状态时使用。"],
        "衣橱": ["需要把衣物实物照、淘宝标题、订单截图、洗标或吊牌整理进 Wardrobe OS 衣橱表时使用。"],
        "穿搭": ["需要基于已入库衣物、明确位置或旅行目的地、自动天气和日程背景生成今日穿搭或旅行行李建议时使用。"],
        "Brief": ["需要把品牌或商单拍摄 brief 清洗成可追溯 CommercialBrief，并供后续拍摄执行或商单交付引用时使用。"],
        "商单交付": ["需要把品牌 brief、创作方向、产品卖点、Tags 和可用博主档案上下文生成商单交付初稿，并创建可公开编辑的飞书云文档时使用。"],
    }
    if label in label_suitable:
        return label_suitable[label]
    if label == "整理":
        return ["需要把最近本地归档按数量、标签或日期汇总成可读摘要时使用。"]
    if category == "creation":
        return ["需要生成内容方案、脚本、拍摄执行或素材交接后的创作任务时使用。"]
    if category == "material":
        return ["需要保存素材证据、拆解素材，或把 SourceAsset 交接到选题/创作/拍摄时使用。"]
    if category == "daily":
        return ["需要安排、查看或推进个人执行事项时使用。"]
    if category == "wardrobe":
        return ["需要维护衣橱单品或生成穿搭/行李建议时使用。"]
    if category == "development":
        return ["需要沉淀开发需求、缺陷或推进开发需求状态时使用。"]
    if category == "knowledge":
        return ["需要沉淀知识或整理材料时使用。"]
    if category == "research":
        return ["需要把明确来源或附件登记为内容机会证据，并继续进入选题或创作时使用。"]
    if category == "review":
        return ["需要做内容复盘、作品验收、账号认知沉淀或创作检查时使用。"]
    if category == "social":
        return ["需要整理社交对象、人脉资料或跟进线索时使用。"]
    if category == "business":
        return ["需要处理达人主页、商务线索、博主查询或博主档案入库时使用。"]
    if category == "system":
        return ["需要处理系统辅助入口时使用。"]
    return ["需要按该标签定义处理对应材料时使用。"]


def not_suitable_for(label: str, category: str) -> list[str]:
    base = ["不用于查看密钥、凭据、配置、处理函数、运行日志或私密原始记录。"]
    if label == "思考":
        base.append("不用于在未授权群、未 @Bot 的群消息或未授权提交人下收件；群内不返回结构化详情、候选数量或失败原因；U3 不执行任务、提醒、通知、日历或审批动作。")
        return base
    if label == "修改":
        base.append("不用于给文档尾部追加补丁块、生成补充记录、处理旧【补充】/【去补丁】入口或新建 v2 文档；真实删除/替换图片仍需人工确认或专用已验证 writer；旧入口不保留迁移入口。")
    if label == "删除":
        base.append("不用于按模糊描述删除；没有明确 ID 或可解析 URL 时只返回缺少目标。")
    if label == "整理":
        base.append("不用于查看能力说明、同步状态或执行飞书表入库。")
    if label in {"归档", "补全", "认知", "学习", "学习-整理"}:
        base.append("不默认写入飞书知识表；需要飞书入库时必须明确提出。")
    if label == "调研":
        base.append("不默认持久化到飞书或 Obsidian；需要沉淀时应明确目标。")
    if label == "日记":
        base.append("不用于创建提醒、日程或开发任务；这些应使用【待办】、【日程】或【待办-开发】。")
    if label == "周记":
        base.append("不用于保存原始日记；少于 3 篇日记时只写样本不足索引。")
    if label == "衣橱":
        base.append("不用于创作内容或写入 Media OS 任务池；补旧衣物截图但无法确认是哪件衣服时不猜测关联对象。")
    if label == "穿搭":
        base.append("不用于新增或修改衣橱事实；缺少明确位置、旅行目的地或默认位置，或自动天气不可用时不会强行生成推荐。")
    if label == "Brief":
        base.append("不用于直接生成拍摄执行单、商单交付初稿或发布动作；LLM 不可用或 brief 证据不足时不写结构化语义。")
    if label == "商单交付":
        base.append("不用于达人建档、报价机会入库或自动发布；字段不足、权限未读回或原生表格未读回时不创建已完成记录。")
    if label in {"说明", "最近", "同步", "状态"}:
        base.append("不用于替代具体业务标签的归档、创作或入库流程。")
    if category == "social":
        base.append("不在公开能力中心展示具体人名、关系细节或聊天原文。")
    if category == "creation":
        base.append("不默认声明已经知道 Mac 本地素材事实，素材事实应由 Mac 扫描后回写。")
    return base


ENTRY_TREE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "今日": {
        "lifecycleLayer": "Daily",
        "root": {
            "displayName": "Daily 执行与记录",
            "purpose": "查看今日执行状态，并把待办、日程、日记和周记串成日常记录闭环。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [
            ("待办", "direct_entry", "记录待办", "保存普通清单、指定日期 checklist、提醒或层级事项。"),
            ("日程", "direct_entry", "安排日程", "创建明确时间、地点、参与人和提醒的日历事件。"),
            ("日记", "direct_entry", "写每日记录", "保存今天值得保留的事实、情绪、判断、退缩、开发和经验。"),
            ("周记", "direct_entry", "提取周总结", "读取本周日记，生成固定周记总结和动态主题簇。"),
            ("待办-开发", "direct_entry", "创建开发任务", "把开发需求写成可追溯任务卡和验收口径。"),
            ("开发-完成", "direct_entry", "标记完成", "按任务 ID 或关键词推进开发任务完成状态。"),
            ("开发-验证", "direct_entry", "标记待验证", "按任务 ID 或关键词推进开发任务待验证状态。"),
        ],
    },
    "素材": {
        "lifecycleLayer": "Collect",
        "root": {
            "displayName": "素材输入",
            "purpose": "唯一素材入口：把链接、粘贴文字、活动 brief、转写稿或 vlog 文字说明沉淀成素材资产。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [],
    },
    "衣橱": {
        "lifecycleLayer": "Entity",
        "root": {
            "displayName": "衣橱与穿搭",
            "purpose": "先把衣物保存进衣橱，再按位置、天气和场景生成今日穿搭或旅行行李建议。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [
            ("穿搭", "direct_entry", "生成穿搭或行李", "读取已入库衣物，结合明确位置、自动天气和日程背景生成建议。"),
        ],
    },
    "创作": {
        "lifecycleLayer": "Create",
        "root": {
            "displayName": "内容创作",
            "purpose": "从明确选题、素材或活动 brief 生成脚本、图文结构、标题和分镜草案。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [
            ("创作>小红书", "direct_entry", "小红书创作", "生成小红书图文或视频稿件。"),
            ("创作>抖音", "direct_entry", "抖音创作", "生成抖音视频脚本、开头钩子和分镜建议。"),
            ("创作-拍摄执行", "direct_entry", "拍摄执行单", "把主题落成现场可拍的镜头、场地、人员和 checklist。"),
            ("创作咨询", "direct_entry", "创作决策咨询", "基于已有数据回答最近该做什么选题或方向。"),
        ],
    },
    "调研": {
        "lifecycleLayer": "Decide",
        "root": {
            "displayName": "内容机会调研",
            "purpose": "围绕账号、平台、赛道和问题形成内容机会判断。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [],
    },
    "润色": {
        "lifecycleLayer": "Polish",
        "root": {
            "displayName": "表达优化",
            "purpose": "把已有标题、正文、封面文案或口播稿改得更像账号、更适合平台。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [
            ("网感", "intent_entry", "增强网感", "强化钩子、冲突、平台语感和评论触发。"),
            ("文案优化", "intent_entry", "整体文案优化", "优化标题、正文、封面文案或评论回复。"),
            ("改标题", "intent_entry", "标题短句", "只改标题、封面短句或第一屏表达。"),
            ("去AI味", "intent_entry", "降低模板腔", "降低书面腔、模板腔和 AI 腔。"),
            ("小红书文案", "intent_entry", "小红书表达", "按小红书机制优化标题、正文和封面文案。"),
            ("抖音文案", "intent_entry", "抖音表达", "按抖音机制优化视频开头、口播和标题。"),
        ],
    },
    "检查": {
        "lifecycleLayer": "Verify",
        "root": {
            "displayName": "检查验收",
            "purpose": "根据输入判断是查清单、验收作品，还是做发布前 gate。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [
            ("创作检查", "direct_entry", "查看检查清单", "按场景返回可审阅的创作 checklist。"),
            ("作品验收", "direct_entry", "验收成稿或成片", "逐项判定作品是否满足创作要求并给出修改建议。"),
        ],
    },
    "博主": {
        "lifecycleLayer": "Entity",
        "root": {
            "displayName": "外部达人账号",
            "purpose": "查询或补充外部达人、竞品或合作博主档案，服务商务和创作判断；不是自有账号画像。",
            "dispatchMode": "smart_dispatch",
        },
        "children": [
            ("博主-入库", "intent_entry", "入库", "用 `能力：入库` 补充公开主页、作者 ID、身份定位和可创作身份卖点。"),
        ],
    },
}


def artifact_refs_for(capability: dict[str, Any]) -> list[str]:
    canonical = str(capability.get("canonicalCapabilityId") or "")
    by_canonical = {
        "source_asset_intake": ["SourceAsset"],
        "raw_expression_capture": ["Transcript", "RawExpression"],
        "commercial_brief": ["CommercialBrief"],
        "external_research_brief": ["ExternalResearchBrief"],
        "creation_decision_brief": ["DecisionBrief"],
        "selfmedia_creation": ["DraftPackage"],
        "shooting_execution_plan": ["ShootingExecutionPlan"],
        "style_polish_run": ["StylePolishResult"],
        "creation_checklist_lookup": ["VerificationReport"],
        "work_acceptance_report": ["VerificationReport"],
        "publishing_pack_build": ["PublishingPack"],
        "post_review_signal": ["ReviewSignal"],
        "daily_journal_entry": ["DailyJournalEntry", "ObsidianDailyJournalFile"],
        "weekly_self_model_summary": ["WeeklySelfModelSummary", "DailyJournalIndex"],
        "creator_profile_lookup": ["CreatorProfile"],
        "creator_profile_upsert": ["CreatorProfile"],
        "commercial_delivery_draft": ["CommercialDeliveryDraft", "FeishuDocxChildPage", "CommercialDeliveryRecord"],
        "wardrobe_item_ingest": ["衣橱单品记录"],
        "wardrobe_recommendation": ["穿搭/行李建议"],
    }
    artifacts = by_canonical.get(canonical, [])
    if artifacts:
        return artifacts
    content_forms = capability.get("outputDetail", {}).get("contentForms", [])
    return [safe_text(str(item)) for item in content_forms[:2] if str(item).strip()] or ["能力输出"]


def input_fields_from_templates(templates: list[dict[str, str]]) -> list[str]:
    for template in templates:
        body = str(template.get("body") or "")
        fields: list[str] = []
        for line in body.splitlines()[1:]:
            if "：" not in line:
                continue
            field = safe_text(line.split("：", 1)[0])
            if field and field not in fields:
                fields.append(field)
        if fields:
            return fields
    return []


def entry_node_for(
    capability: dict[str, Any],
    *,
    entry_role: str,
    dispatch_mode: str,
    recommended: bool,
    display_name: str | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    display = capability["displayProjection"]
    output = capability["outputDetail"]
    canonical_input_contract = get_input_contract(str(capability["aliases"][0]))
    if canonical_input_contract is None:
        raise RuntimeError(f"{capability['rawLabel']} missing canonical input contract")
    templates = capability["quickCopyTemplates"] or [
        {
            "id": "structured",
            "title": "结构化输入",
            "description": "按默认字段补齐上下文。",
            "body": capability["defaultInputTemplate"],
        }
    ]
    next_capability_ids = [
        str(action["targetCapabilityId"])
        for action in display.get("nextActions", [])
        if action.get("targetCapabilityId")
    ]
    required_fields = display["requiredInputs"]
    optional_fields = display["optionalInputs"]
    writes_to = [safe_text(str(item)) for item in output.get("destinations", []) if str(item).strip()]
    return {
        "id": capability["id"],
        "capabilityId": capability["id"],
        "trigger": capability["rawLabel"],
        "displayName": display_name or display["displayTitle"],
        "purpose": purpose or display["operatorSummary"],
        "entryRole": entry_role,
        "dispatchMode": dispatch_mode,
        "recommended": recommended,
        "canonicalCapabilityId": capability["canonicalCapabilityId"],
        "inputContract": {
            "title": f"{capability['rawLabel']} 输入格式",
            "summary": display["whenToUse"][0] if display.get("whenToUse") else display["operatorSummary"],
            "requiredFields": required_fields,
            "optionalFields": optional_fields,
            "templates": templates,
        },
        "outputContract": {
            "summary": " / ".join(display["outputSummary"][:2]) if display.get("outputSummary") else capability["description"],
            "userReplySections": display["outputSummary"] or output.get("contentForms", []),
            "artifacts": artifact_refs_for(capability),
            "writesTo": writes_to or ["当前 Bot 回复"],
            "nextActions": [
                display_action_label(action.get("label") or "")
                for action in display.get("nextActions", [])
                if display_action_label(action.get("label") or "")
            ] or [display_action_label(item) for item in output.get("nextActions", [])] or ["按回复继续补充或确认"],
        },
        "nextCapabilityIds": next_capability_ids,
        "templateId": templates[0]["id"],
        "supportedAttachments": canonical_supported_attachments(
            str(capability["aliases"][0]), canonical_input_contract
        ),
        "riskLevel": display["riskBadges"][1] if len(display.get("riskBadges", [])) > 1 else "风险待确认",
        "visibility": capability["sensitivity"],
    }


def add_entry_trees(capabilities: list[dict[str, Any]]) -> None:
    by_label = {cap["aliases"][0]: cap for cap in capabilities}
    for root_label, definition in ENTRY_TREE_DEFINITIONS.items():
        root_capability = by_label.get(root_label)
        if not root_capability:
            continue
        root_definition = definition["root"]
        root_node = entry_node_for(
            root_capability,
            entry_role="root_entry",
            dispatch_mode=str(root_definition.get("dispatchMode") or "smart_dispatch"),
            recommended=True,
            display_name=str(root_definition.get("displayName") or root_capability["rawLabel"]),
            purpose=str(root_definition.get("purpose") or root_capability["description"]),
        )
        children = []
        for label, role, display_name, purpose in definition["children"]:
            child = by_label.get(label)
            if not child:
                continue
            child_node = entry_node_for(
                child,
                entry_role=str(role),
                dispatch_mode="direct",
                recommended=False,
                display_name=str(display_name),
                purpose=str(purpose),
            )
            children.append(child_node)
        root_capability["entryTree"] = {
            "lifecycleLayer": str(definition["lifecycleLayer"]),
            "root": root_node,
            "children": children,
        }


def add_relationships(capabilities: list[dict[str, Any]]) -> None:
    by_label = {cap["aliases"][0]: cap["id"] for cap in capabilities}
    relation_labels: dict[str, list[str]] = {label: [] for label in by_label}

    def add_edge(left: str, right: str) -> None:
        if left == right or left not in relation_labels or right not in relation_labels:
            return
        if right not in relation_labels[left]:
            relation_labels[left].append(right)
        if left not in relation_labels[right]:
            relation_labels[right].append(left)

    def add_hub(hub: str, targets: list[str]) -> None:
        for target in targets:
            add_edge(hub, target)

    def add_chain(labels: list[str]) -> None:
        for left, right in zip(labels, labels[1:]):
            add_edge(left, right)

    add_hub("策略", ["账号", "赛道", "调研", "选题", "复盘", "创作咨询"])
    add_hub("素材", ["拆解", "选题", "调研", "创作", "拍摄"])
    add_hub("选题", ["素材", "调研", "创作", "策略", "复盘"])
    add_hub("拍摄", ["创作-拍摄执行", "创作", "发布包", "检查"])
    add_hub("检查", ["创作检查", "作品验收", "发布包", "创作"])
    add_hub("发布包", ["润色", "检查", "创作", "数据复盘"])
    add_hub("复核", ["素材", "调研", "选题", "发布包", "检查"])
    add_hub("账号", ["策略", "赛道", "数据复盘"])
    add_hub("赛道", ["赛道-关系", "账号", "策略", "调研"])
    add_hub("赛道-关系", ["赛道", "博主", "博主-入库"])
    add_hub("创作", ["创作>小红书", "创作>抖音", "创作-拍摄执行", "创作咨询", "活动", "灵感", "灵感>vlog", "素材"])
    add_hub("商单交付", ["商务>ID", "创作", "创作咨询", "作品验收", "数据复盘", "博主"])
    add_hub("Brief", ["素材", "拍摄", "创作-拍摄执行", "商单交付", "复核"])
    add_hub("创作>小红书", ["数据复盘", "作品验收", "创作检查"])
    add_hub("创作>抖音", ["数据复盘", "作品验收", "创作检查"])
    add_hub("润色", ["网感", "文案优化", "改标题", "去AI味", "小红书文案", "抖音文案", "创作", "创作>小红书", "创作>抖音"])
    add_hub("网感", ["润色", "文案优化", "改标题"])
    add_hub("文案优化", ["润色", "网感", "去AI味"])
    add_hub("改标题", ["润色", "小红书文案", "抖音文案"])
    add_hub("去AI味", ["润色", "文案优化"])
    add_hub("小红书文案", ["润色", "改标题", "创作>小红书"])
    add_hub("抖音文案", ["润色", "改标题", "创作>抖音"])
    add_hub("数据复盘", ["作品验收", "创作检查", "复盘", "自媒体-认知", "创作"])
    add_hub("热榜", ["调研", "选题"])
    add_hub("学习", ["学习-整理", "归档", "补全", "认知", "自媒体知识"])
    add_hub("自媒体知识", ["转写", "转写-文字", "调研"])
    add_hub("待办-开发", ["开发-完成", "开发-验证", "待办"])
    add_hub("今日", ["待办", "日程", "日记", "周记", "待办-开发"])
    add_hub("日记", ["今日", "周记"])
    add_hub("思考", ["日记"])
    add_hub("日程", ["待办", "今日", "周记"])
    add_hub("衣橱", ["穿搭", "今日", "待办"])
    add_hub("穿搭", ["衣橱", "今日", "日程"])
    add_hub("社交", ["人脉", "博主", "博主-入库"])
    add_hub("博主", ["博主-入库", "商务>ID", "创作", "商单交付"])
    add_hub("说明", ["最近", "同步", "状态"])
    add_hub("整理", ["归档", "修改", "同步", "状态"])
    add_hub("删除", ["创作", "最近", "同步", "状态"])

    add_chain(["灵感", "灵感>vlog", "素材", "创作"])
    add_chain(["策略", "素材", "调研", "选题", "创作", "润色", "检查", "发布包", "复核", "复盘"])
    add_chain(["素材", "拆解", "创作"])
    add_chain(["润色", "网感", "文案优化", "去AI味"])
    add_chain(["润色", "改标题", "小红书文案", "抖音文案"])
    add_chain(["数据复盘", "作品验收", "创作检查"])
    add_chain(["待办", "日程", "今日", "日记", "周记", "复盘"])
    add_chain(["衣橱", "穿搭", "今日"])
    add_chain(["自媒体知识", "学习", "学习-整理", "归档", "认知", "整理"])
    add_chain(["转写", "转写-文字", "自媒体知识"])
    add_chain(["说明", "最近", "同步", "状态"])

    for cap in capabilities:
        label = cap["aliases"][0]
        targets = relation_labels.get(label, [])
        cap["relatedCapabilityIds"] = [by_label[item] for item in targets]
        cap["promptReferenceIds"] = prompt_references_for(label, cap["category"], by_label)


def prompt_references_for(label: str, category: str, by_label: dict[str, str]) -> list[str]:
    mapping = {
        "数据复盘": ["创作", "创作>小红书", "创作>抖音", "作品验收", "创作咨询"],
        "作品验收": ["创作", "创作>小红书", "创作>抖音", "数据复盘", "创作检查"],
        "创作检查": ["创作", "创作>小红书", "创作>抖音", "作品验收"],
        "创作-拍摄执行": ["创作", "创作>抖音", "素材", "作品验收"],
        "素材": ["拆解", "选题", "创作", "创作-拍摄执行"],
    }
    targets = mapping.get(label)
    if not targets and category == "review":
        targets = ["创作", "创作>小红书", "创作>抖音"]
    if not targets:
        return []
    return [by_label[item] for item in targets if item in by_label]


def flow_stage_ids_for(label: str, category: str) -> list[str]:
    stage_ids: list[str] = []

    def add(stage_id: str) -> None:
        if stage_id not in stage_ids:
            stage_ids.append(stage_id)

    if label == "思考":
        add("local-binding-gate")

    if label in {"创作", "创作>小红书", "创作>抖音", "创作咨询", "创作-拍摄执行"}:
        add("cloud-project-package")
    if label in {"活动", "灵感", "灵感>vlog"}:
        add("mac-intake")
    if label in {"拆解"} or category == "material":
        add("mac-material-analysis")
    if label in {"创作检查", "作品验收"}:
        add("creative-assembly")
    if label in {"创作-拍摄执行", "创作检查", "作品验收"}:
        add("editing-packaging")
    if label in {"作品验收", "数据复盘", "创作检查", "复盘"} or category == "review":
        add("output-review-writeback")
    if label in {"数据复盘"}:
        add("publish-archive")
    if label in {"自媒体知识", "转写", "转写-文字"}:
        add("knowledge-source-capture")
    if label in {"归档", "补全", "认知", "学习", "学习-整理"}:
        add("knowledge-weekly-archive")
    if label == "调研":
        add("media-growth-research")
    if label in {"修改", "整理", "说明", "最近", "同步", "状态"}:
        add("system-document-actions")
    if category == "wardrobe":
        add("local-binding-gate")
    if not stage_ids:
        if category in {"daily", "development"}:
            add("local-binding-gate")
        elif category == "knowledge":
            add("knowledge-source-capture")
        elif category == "research":
            add("media-growth-research")
        elif category == "system":
            add("system-document-actions")
        elif category in {"social", "business"}:
            add("cloud-project-package")
        else:
            add("cloud-project-package")
    return stage_ids


def llm_prompt_contracts_for(label: str, category: str) -> list[dict[str, Any]]:
    raw_label = f"【{label}】"
    policy = "维护视图展示从源码或能力契约提取的脱敏提示词正文或执行契约；它不代表某次运行的完整请求；密钥、私密原文、运行日志和完整外部上下文不进入公开 JSON。"

    def safe_contract_id(text: str) -> str:
        return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-") or "runtime-contract"

    def component_name_from_source(source: str, title: str) -> str:
        if "::" in source:
            module, symbol = source.rsplit("::", 1)
            module_name = Path(module).name if module else module
            return f"{module_name}::{symbol}"
        if source == "Knowledge bot AGENTS.md":
            return "Knowledge 能力提示词段落"
        if source.endswith(".md"):
            return "文档提示词段落"
        if source:
            return source
        return title

    def prompt_kind_for_source_type(source_type: str) -> tuple[str, str]:
        if source_type == "execution_contract":
            return "generated_execution_contract", "生成的执行契约（非 LLM prompt）"
        if source_type == "runtime_prompt":
            return "actual_llm_prompt", "源码定义的 LLM 提示词"
        if source_type == "prompt_doc":
            return "actual_llm_prompt", "源码定义的提示词文档"
        if source_type == "renderer_contract":
            return "supporting_contract", "渲染契约（非直接 LLM prompt）"
        if source_type == "quality_contract":
            return "supporting_contract", "质量契约（非直接 LLM prompt）"
        return "supporting_contract", "辅助契约"

    def prompt_body_from_contract(contract: dict[str, Any]) -> str:
        lines = [
            str(contract["title"]),
            "",
            "用途：",
            str(contract["purpose"]),
            "",
            "适用入口：",
            "、".join(str(item) for item in contract["appliesTo"]),
            "",
            "输入边界：",
            *[f"- {item}" for item in contract["inputBoundary"]],
            "",
            "输出契约：",
            *[f"- {item}" for item in contract["outputContract"]],
            "",
            "写入位置：",
            *[f"- {item}" for item in contract["writesTo"]],
        ]
        return "\n".join(lines)

    def contracts(*items: dict[str, Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            contract = dict(item)
            contract.setdefault("promptBody", prompt_body_from_contract(contract))
            prompt_kind, prompt_kind_label = prompt_kind_for_source_type(str(contract["sourceType"]))
            contract.setdefault("promptKind", prompt_kind)
            contract.setdefault("promptKindLabel", prompt_kind_label)
            contract.setdefault("componentName", component_name_from_source(str(contract["source"]), str(contract["title"])))
            post_validation = PROMPT_VALIDATION_BINDINGS.get(str(contract.get("id") or ""))
            if post_validation:
                if contract["promptKind"] != "actual_llm_prompt":
                    raise RuntimeError(f"post-validation binding requires actual LLM prompt: {contract['id']}")
                contract["postValidation"] = dict(post_validation)
            normalized.append(contract)
        return normalized

    def actual_prompt_contract(
        *,
        contract_id: str,
        title: str,
        source: str,
        prompt_body: str,
        applies_to: list[str],
        purpose: str,
        input_boundary: list[str],
        output_contract: list[str],
        writes_to: list[str],
        source_type: str = "runtime_prompt",
    ) -> dict[str, Any]:
        return {
            "id": contract_id,
            "title": title,
            "sourceType": source_type,
            "source": source,
            "appliesTo": applies_to,
            "purpose": purpose,
            "promptBody": safe_text(prompt_body),
            "inputBoundary": input_boundary,
            "outputContract": output_contract,
            "writesTo": writes_to,
            "publicSummary": [
                "维护页展示从源码或能力契约提取的该能力提示词正文。",
                "它不代表某次运行的完整请求；用户正文、附件、被回复对象和运行时上下文不在这里展开。",
            ],
            "fullPromptPolicy": policy,
            "exposure": "summary_only",
        }

    def default_runtime_contract(label: str, category: str) -> dict[str, Any]:
        raw_label = f"【{label}】"
        detail = output_detail(label, category)
        destinations = detail.get("destinations") or ["当前 Bot 回复"]
        content_forms = detail.get("contentForms") or output_hints(label, category, "")
        boundaries = detail.get("boundaries") or not_suitable_for(label, category)
        template = default_input_template(label, category)
        source_type = "execution_contract"
        title = f"{raw_label} 运行提示词"
        purpose = f"按 {raw_label} 能力边界处理用户正文、附件和已加载上下文，产出 {safe_text('、'.join(content_forms))}。"
        trigger_boundary = (
            "入口必须以 【商务>ID】 或作者参数入口 【商务>作者ID】 触发。"
            if label == "商务>ID"
            else f"入口必须以 {raw_label} 触发。"
        )
        input_boundary = [
            trigger_boundary,
            "只使用用户正文、上传附件、被回复对象和运行时明确加载的上下文；证据不足时标为待确认或返回缺少目标。",
            *boundaries[:3],
        ]
        output_contract = [
            f"输出必须围绕 {raw_label} 的用途，不得改写成其他标签能力。",
            *[f"产出 {item}" for item in content_forms[:4]],
        ]
        writes_to = [safe_text(item) for item in destinations[:4]]
        prompt_body = "\n".join(
            [
                f"能力标签：{raw_label}",
                f"能力标题：{public_title_description(label, {'purpose': label, 'result': ''})[0]}",
                "",
                "LLM 调用：",
                "当前本地路由没有为该能力直接发送独立 LLM prompt；运行时由确定性路由、脚本、外部服务或状态查询处理。",
                "",
                "触发输入模板：",
                template,
                "",
                "执行边界：",
                f"- 识别到 {raw_label} 后，只按该能力处理，不自动切换到其他标签。",
                *[f"- {item}" for item in input_boundary],
                "",
                "返回/写入位置：",
                *[f"- {item}" for item in writes_to],
            ]
        )
        return {
            "id": f"{capability_id(label)}-{safe_contract_id(category)}-runtime",
            "title": title,
            "sourceType": source_type,
            "source": "tag_capabilities.py + Bot AGENTS/TOOLS/USER + 能力数据生成器",
            "promptKind": "generated_execution_contract",
            "promptKindLabel": "生成的执行契约（非 LLM prompt）",
            "componentName": "能力中心生成器",
            "appliesTo": [raw_label],
            "purpose": purpose,
            "promptBody": prompt_body,
            "inputBoundary": input_boundary,
            "outputContract": output_contract,
            "writesTo": writes_to,
            "publicSummary": [
                "这是该能力在维护页展示的生成执行契约，不是源码定义的 LLM prompt。",
                "当前未接入单次运行 prompt trace，因此不代表某次实际请求的完整 payload。",
                "实际运行还会叠加对应 Bot 的 AGENTS、TOOLS、USER 和当前对话上下文。",
            ],
            "fullPromptPolicy": policy,
            "exposure": "summary_only",
        }
    complete_knowledge = {
        "id": "complete-knowledge-weekly-cognition-completion",
        "title": "【补全】 周记认知补全运行提示词",
        "sourceType": "runtime_prompt",
        "source": "Knowledge bot AGENTS.md",
        "appliesTo": ["【补全】"],
        "purpose": "把用户提供的零散、口语化、未完成表达补全成适合写入 Obsidian 周记 # 认知 小节的自然文字。",
        "promptBody": knowledge_capability_prompt_body("补全"),
        "inputBoundary": [
            "消息必须以【补全】开头，只执行周记认知补全。",
            "只基于用户提供的文字、附件、被回复对象和明确加载的上下文整理。",
            "不得编造用户未提供的事实、链接内容、附件内容、飞书记录、Obsidian 记录或本地素材。",
            "信息不足时用待确认标出；缺少正文时直接返回缺少待补全文字。",
            "默认不写入飞书知识表。",
        ],
        "outputContract": [
            "一、补全后的自然文本：整理成一段或数段可直接放进周记的自然文字。",
            "二、周记认知条目：包含核心认知、触发来源、适用场景、后续行动 / 待确认。",
            "三、处理说明：说明本次整理动作和证据不足未补全的内容。",
            "目标是补全周记认知，不重写成报告，并保留用户原本判断和语气。",
        ],
        "writesTo": [
            "Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节",
            "无法确认日期范围或目标周记文件时只返回整理后的内容，不假设路径",
        ],
        "publicSummary": [
            "这是【补全】能力在详情页展示的脱敏运行提示词。",
            "LLM 负责把用户提供的原始表达补全成周记认知文本；脚本只负责读取、路由、校验、写入或返回。",
        ],
        "fullPromptPolicy": policy,
        "exposure": "summary_only",
    }
    cognition_weekly = {
        "id": "cognition-weekly-cognition-deposit",
        "title": "【认知】 周记认知沉淀运行提示词",
        "sourceType": "runtime_prompt",
        "source": "Knowledge bot AGENTS.md",
        "appliesTo": ["【认知】"],
        "purpose": "把一次具体经历、观察或判断提炼成以后还能复用的认知条目，并沉淀到 Obsidian 周记 # 认知 小节。",
        "promptBody": knowledge_capability_prompt_body("认知"),
        "inputBoundary": [
            "消息必须以【认知】开头，只执行周记认知沉淀。",
            "只基于用户提供的正文、附件、被回复对象和明确加载的上下文整理。",
            "不得编造用户未提供的事实、链接内容、附件内容、飞书记录、Obsidian 记录或本地素材。",
            "信息不足时用待确认标出；缺少正文时直接返回缺少待沉淀内容。",
            "默认不写入飞书知识表；不处理原始音频/视频 ASR。",
        ],
        "outputContract": [
            "一、周记认知条目：包含标题、来源、核心认知、可复用场景、行动提醒、反例 / 边界条件、待确认。",
            "二、沉淀文本：整理成适合写入 Obsidian 周记的自然文本，像用户自己的复盘而不是外部报告。",
            "三、处理说明：说明整理动作和证据不足保留为待确认的内容。",
            "目标是提炼以后还能用的判断，不是补全文字、写鸡汤或扩写文章。",
        ],
        "writesTo": [
            "Obsidian 周记 Archieve/YYYYMMDD-YYYYMMDD.md 的 # 认知 小节",
            "无法确认日期范围或目标周记文件时只返回整理后的内容，不假设路径",
        ],
        "publicSummary": [
            "这是【认知】能力在详情页展示的脱敏运行提示词。",
            "LLM 负责提炼核心认知、可复用场景、反例边界和行动提醒；脚本只负责读取、路由、校验、写入或返回。",
        ],
        "fullPromptPolicy": policy,
        "exposure": "summary_only",
    }
    creation_main = {
        "id": "creation-main-editor",
        "title": "创作总编 LLM 主生成契约",
        "sourceType": "runtime_prompt",
        "source": "selfmedia-tools/selfmedia/creation/llm_generator.py::build_creation_prompt",
        "appliesTo": ["【创作】", "【创作>小红书】", "【创作>抖音】", "【创作-拍摄执行】"],
        "purpose": "让 LLM 基于用户请求、活动记忆、爆款记忆、创作灵感、商务信息和账号上下文生成平台化创作初稿。",
        "promptBody": python_function_return(CREATION_LLM_GENERATOR_PATH, "build_creation_prompt"),
        "inputBoundary": [
            "活动、商务、爆款、创作灵感和账号事实只能来自输入候选或已加载上下文。",
            "LLM 可以创作表达、标题、脚本、分镜和叙事结构，但不能编造活动规则、商务承诺、互动数据或个人经历。",
            "爆款只迁移结构、冲突、节奏和画面组织；不得复刻原文。",
        ],
        "outputContract": [
            "必须输出 content_core、topic_strategy、usable_material_brief、script_options、editor_pass 和 creator_report。",
            "script_options 必须保留 2-5 个完整方案，recommended_option_id 必须指向其中一个方案。",
            "creator_report 固定为 overview、opening_3s、mainline、storyboard、publishing_pack、material_checklist、risk_controls、evidence_appendix。",
        ],
        "writesTo": [
            "03_CreationRuns_创作运行",
            "Feishu 创作子文档",
            "media_vault/creation_runs 运行 artifact",
        ],
        "publicSummary": [
            "这是给 LLM 写稿的内部主 prompt，不是用户复制到飞书的输入模板。",
            "页面只展示契约摘要，帮助理解生成逻辑和产物位置。",
        ],
        "fullPromptPolicy": policy,
        "exposure": "summary_only",
    }
    creation_renderer = {
        "id": "creator-report-renderer",
        "title": "创作者执行稿渲染契约",
        "sourceType": "renderer_contract",
        "source": "openclaw-creation-source-fields Skill + creation writer renderer",
        "appliesTo": ["【创作】", "【创作-拍摄执行】"],
        "purpose": "约束 LLM 的 creator_report 如何渲染成真人可执行的飞书创作文档。",
        "inputBoundary": [
            "执行区只放拍摄、文案、发布和风险动作。",
            "证据、候选 id、评分细节和来源映射后置到证据附录。",
            "历史回洗也必须保持与实时入口相同的 creator brief 形状。",
        ],
        "outputContract": [
            "第一屏给一个主方案，最多两个备选方向摘要。",
            "脚本方案区保留 2-5 个完整 script_options，并显示方案分数。",
            "分镜优先用 Feishu 原生表格，常规列为时间、画面、字幕/口播、声音/拍摄注意。",
        ],
        "writesTo": [
            "Feishu 创作子文档",
            "03_CreationRuns_创作运行的飞书文档链接",
        ],
        "publicSummary": [
            "它控制的是创作文档长什么样，不负责重新生成业务语义。",
            "防止把检索报告、原始 JSON 或长链接堆到创作者执行区。",
        ],
        "fullPromptPolicy": policy,
        "exposure": "summary_only",
    }
    data_review = {
        "id": "data-review-analysis",
        "title": "数据复盘 LLM 分析契约",
        "sourceType": "runtime_prompt",
        "source": "selfmedia-tools/selfmedia/review/data_review.py::run_data_review_analysis",
        "appliesTo": ["【数据复盘】"],
        "purpose": "让 LLM 根据抖音/小红书后台数据截图做 OCR、指标判断、内容指导和发布建议。",
        "promptBody": python_prompt_assignment(DATA_REVIEW_WORKFLOW_PATH, "analyze_data_screenshots"),
        "inputBoundary": [
            "只从截图、用户文字、飞书模板和最近对话上下文抽取数据。",
            "看不清的字段必须写入 data_quality_notes，不得编造。",
            "截图曲线、媒体形式和关键指标必须单独给证据。",
        ],
        "outputContract": [
            "必须输出 platform、account、media_format、metrics、atomic_facts、priority_metrics、trend_curves、conclusion。",
            "content_guidance 聚焦内容生产调整，publishing_guidance 聚焦发布策略。",
            "atomic_facts 必须是一条一事实，后续作为创作记忆和改稿依据。",
        ],
        "writesTo": [
            "04_PostReviews_发布复盘",
            "H01_MetricSnapshot_作品指标快照",
            "数据复盘 Feishu 子文档",
            "media_context review memory",
        ],
        "publicSummary": [
            "这个 prompt 不直接写创作稿，但它会沉淀复盘记忆，影响后续创作主链路。",
            "它和创作总编 prompt 的关系是：先把作品表现变成可复用事实，再供后续创作使用。",
        ],
        "fullPromptPolicy": policy,
        "exposure": "summary_only",
    }
    work_acceptance = {
        "id": "work-acceptance-review",
        "title": "作品验收 LLM 检查契约",
        "sourceType": "runtime_prompt",
        "source": "openclaw-tag-router/openclaw_app/router/work_acceptance.py::_work_acceptance_review",
        "appliesTo": ["【作品验收】", "【创作检查】"],
        "purpose": "让 LLM 按创作要求逐项检查成稿或成片文本是否满足发布前要求。",
        "promptBody": python_prompt_assignment(WORK_ACCEPTANCE_PATH, "_work_acceptance_review"),
        "inputBoundary": [
            "只根据作品正文、创作要求和最近对话上下文判断。",
            "缺少作品正文、缺少创作要求或证据不足时必须判为不确定。",
            "不根据想当然的画面或素材内容补证据。",
        ],
        "outputContract": [
            "每条要求只能判为满足、不满足或不确定。",
            "items 固定包含 requirement、judgment、evidence、gap、fix。",
            "必须给 summary、release_advice 和 next_actions。",
        ],
        "writesTo": [
            "作品验收回复",
            "项目状态推进证据",
        ],
        "publicSummary": [
            "这个 prompt 用于发布前检查，不负责重新创作完整内容。",
            "它是数据复盘和创作主链路之间的质量门槛之一。",
        ],
        "fullPromptPolicy": policy,
        "exposure": "summary_only",
    }
    def actual_for_current(
        contract_id: str,
        title: str,
        source: str,
        prompt_body: str,
        *,
        source_type: str = "runtime_prompt",
        applies_to: list[str] | None = None,
    ) -> dict[str, Any]:
        detail = output_detail(label, category)
        input_boundary = [
            (
                "入口必须以 【商务>ID】 或作者参数入口 【商务>作者ID】 触发。"
                if label == "商务>ID"
                else f"入口必须以 {raw_label} 触发。"
            ),
            "只使用用户正文、上传附件、被回复对象和运行时明确加载的上下文。",
            "证据不足时返回 pending/manual、待确认或缺少目标，不编造事实。",
        ]
        if label == "商单交付":
            input_boundary.extend(
                [
                    "必填输入：创作方向、产品卖点、Tags。",
                    "选填输入：PR备注、平台要求 / 禁区、博主人设 / 语气；PR备注和平台要求 / 禁区未填默认无特殊要求。",
                ]
            )
        return actual_prompt_contract(
            contract_id=contract_id,
            title=title,
            source=source,
            prompt_body=prompt_body,
            applies_to=applies_to or [raw_label],
            purpose=f"{title}。",
            input_boundary=input_boundary,
            output_contract=detail.get("contentForms") or output_hints(label, category, ""),
            writes_to=detail.get("destinations") or ["当前 Bot 回复"],
            source_type=source_type,
        )

    def transcription_contracts() -> list[dict[str, Any]]:
        detail_contract = python_string_constant(CONTENT_FLOW_CLIENT_PATH, "TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT")
        stages = [
            ("transcription-chunk-fact-extraction", "转写后处理：分片事实提取", "_summarize_transcript_chunk"),
            ("transcription-attachment-reduce", "转写后处理：单附件合并", "_summarize_attachment_chunks"),
            ("transcription-group-reduce", "转写后处理：附件中间合并", "_summarize_attachment_group"),
            ("transcription-global-note", "转写后处理：最终会议纪要", "_summarize_global_note"),
            ("transcription-schema-patch", "转写后处理：按需字段级 schema 修复", "_repair_global_note_contract"),
            ("transcription-consistency-check", "转写后处理：一致性检查", "_check_global_note_consistency"),
            ("transcription-consistency-revision", "转写后处理：有界一致性定向修订", "_revise_global_note"),
        ]
        return contracts(
            *[
                actual_for_current(
                    stage_id,
                    title,
                    f"{CONTENT_FLOW_CLIENT_PATH.name}::{function_name}",
                    python_prompt_assignment(CONTENT_FLOW_CLIENT_PATH, function_name).replace(
                        "{TRANSCRIPTION_DETAIL_FIDELITY_CONTRACT}",
                        detail_contract,
                    ),
                )
                for stage_id, title, function_name in stages
            ]
        )

    if label == "灵感":
        return contracts(actual_for_current("inspiration-summary", "灵感归档 LLM 提示词", "content_flow_client.py::summarize_inspiration", python_prompt_assignment(CONTENT_FLOW_CLIENT_PATH, "summarize_inspiration")))
    if label == "活动":
        return contracts(actual_for_current("activity-brief-cleaning", "活动 Brief AI 清洗提示词", "content_flow_client.py::clean_activity_brief", python_prompt_assignment(CONTENT_FLOW_CLIENT_PATH, "clean_activity_brief")))
    if label == "Brief":
        return contracts(
            actual_for_current(
                "commercial-brief-structuring",
                "品牌拍摄 Brief 结构化提示词",
                "selfmedia.growth.service::build_commercial_brief",
                "Clean and structure a brand video shooting brief for MediaClaw. Use only the pasted brief and loaded input artifacts. Repair OCR noise when the intended wording is clear; mark unclear items in risk_notes instead of inventing facts. Do not claim medical diagnosis functions.",
            )
        )
    if label == "待办":
        return contracts(
            actual_for_current("daily-todo-intake", "Daily 待办清单与提醒分流提示词", "activity_daily.py::DAILY_TODO_INTAKE_PROMPT", python_string_constant(ACTIVITY_DAILY_PATH, "DAILY_TODO_INTAKE_PROMPT")),
            actual_for_current("daily-task-extraction", "Daily 自然语言事项抽取提示词", "activity_daily.py::DAILY_TASK_EXTRACTION_PROMPT", python_string_constant(ACTIVITY_DAILY_PATH, "DAILY_TASK_EXTRACTION_PROMPT")),
            actual_for_current("daily-hierarchy-records", "Daily 层级结构清洗提示词", "activity_daily.py::DAILY_HIERARCHY_RECORDS_PROMPT", python_string_constant(ACTIVITY_DAILY_PATH, "DAILY_HIERARCHY_RECORDS_PROMPT")),
        )
    if label == "日程":
        return contracts(
            actual_for_current("daily-task-extraction", "Daily 自然语言事项抽取提示词", "activity_daily.py::DAILY_TASK_EXTRACTION_PROMPT", python_string_constant(ACTIVITY_DAILY_PATH, "DAILY_TASK_EXTRACTION_PROMPT")),
            actual_for_current("daily-hierarchy-records", "Daily 层级结构清洗提示词", "activity_daily.py::DAILY_HIERARCHY_RECORDS_PROMPT", python_string_constant(ACTIVITY_DAILY_PATH, "DAILY_HIERARCHY_RECORDS_PROMPT")),
        )
    if label == "日记":
        return contracts(actual_for_current("daily-journal-arrangement", "Daily 日记整理提示词", "daily_journal_contract.py::DAILY_JOURNAL_ARRANGEMENT_PROMPT", python_string_constant(DAILY_JOURNAL_CONTRACT_PATH, "DAILY_JOURNAL_ARRANGEMENT_PROMPT")))
    if label == "周记":
        return contracts(actual_for_current("weekly-self-model-summary", "Daily 周记提取提示词", "daily_journal_contract.py::WEEKLY_SELF_MODEL_SUMMARY_PROMPT", python_string_constant(DAILY_JOURNAL_CONTRACT_PATH, "WEEKLY_SELF_MODEL_SUMMARY_PROMPT")))
    if label == "修改":
        return contracts(
            actual_for_current("document-edit-stage1-target-plan", "文档分块修改 Stage 1 定位提示词", "document_tools.py::_build_document_edit_patch_target_plan", python_prompt_assignment(DOCUMENT_TOOLS_PATH, "_build_document_edit_patch_target_plan")),
            actual_for_current("document-edit-stage2-patch-plan", "文档分块修改 Stage 2 patch 提示词", "document_tools.py::_build_document_edit_stage2_patch_plan", python_prompt_assignment(DOCUMENT_TOOLS_PATH, "_build_document_edit_stage2_patch_plan")),
            actual_for_current("shooting-backwash-narrative-planner", "拍摄执行回洗叙事规划提示词", "backwash.py::_narrative_plan_prompt", python_function_return(SHOOTING_BACKWASH_PATH, "_narrative_plan_prompt")),
            actual_for_current("shooting-backwash-narrative-plan-review", "拍摄执行回洗叙事规划验收提示词", "backwash.py::_review_narrative_plan", python_prompt_assignment(SHOOTING_BACKWASH_PATH, "_review_narrative_plan")),
            actual_for_current("shooting-backwash-revision", "拍摄执行 CreationRun 整份回洗提示词", "backwash.py::_revision_prompt", python_prompt_assignment(SHOOTING_BACKWASH_PATH, "_revision_prompt")),
            actual_for_current("shooting-backwash-coherence-review", "拍摄执行回洗逐镜连贯性验收提示词", "backwash.py::_review_revision", python_prompt_assignment(SHOOTING_BACKWASH_PATH, "_review_revision")),
        )
    if label in {"自媒体知识"}:
        return contracts(actual_for_current(f"{capability_id(label)}-content-flow-analysis", "content-flow 链接内容分析提示词", "selfmedia/ingest/content_flow/src/analyzer.py::ANALYST_SYSTEM_PROMPT", python_string_constant(CONTENT_FLOW_ANALYZER_PATH, "ANALYST_SYSTEM_PROMPT")))
    if label == "拆解":
        return contracts(actual_for_current("viral-deconstruction-main", "爆款内容拆解提示词", "selfmedia/deconstruct/viral_content/src/prompt.py::DECONSTRUCT_PROMPT", python_string_constant(DECONSTRUCTION_PROMPT_PATH, "DECONSTRUCT_PROMPT")))
    if label in {"转写", "转写-文字"}:
        return transcription_contracts()
    if label == "创作-拍摄执行":
        return contracts(
            actual_for_current("shooting-execution-request-parser", "拍摄执行请求解析提示词", "shooting_execution.py::infer_shooting_execution_request", python_prompt_assignment(SHOOTING_EXECUTION_PATH, "infer_shooting_execution_request")),
            actual_for_current("shooting-execution-director", "拍摄执行导演生成提示词", "shooting_execution.py::generate_shooting_execution_plan", python_prompt_assignment(SHOOTING_EXECUTION_PATH, "generate_shooting_execution_plan")),
        )
    if label == "创作咨询":
        return contracts(actual_for_current("creation-consultation-advisor", "创作咨询顾问提示词", "consultation.py::generate_consultation_answer", python_prompt_assignment(CREATION_CONSULTATION_PATH, "generate_consultation_answer")))
    if label == "自媒体-认知":
        return contracts(
            actual_for_current("selfmedia-cognition-routing", "自媒体认知分流提示词", "selfmedia_cognition.py::_selfmedia_cognition_plan", python_prompt_assignment(SELFMEDIA_COGNITION_PATH, "_selfmedia_cognition_plan")),
            actual_for_current("selfmedia-cognition-merge", "自媒体认知整合提示词", "selfmedia_cognition.py::_selfmedia_cognition_merge_content", python_prompt_assignment(SELFMEDIA_COGNITION_PATH, "_selfmedia_cognition_merge_content")),
        )
    if label == "商务>ID":
        return contracts(
            actual_for_current("business-id-field-extraction", "商务>ID 字段清洗提示词", "id_business.py::BUSINESS_ID_EXTRACTION_PROMPT", python_string_constant(BUSINESS_ID_PATH, "BUSINESS_ID_EXTRACTION_PROMPT")),
            actual_for_current("business-id-reply", "商务>ID 商务回复提示词", "id_business.py::BUSINESS_REPLY_PROMPT", python_string_constant(BUSINESS_ID_PATH, "BUSINESS_REPLY_PROMPT")),
        )
    if label == "商单交付":
        return contracts(
            actual_for_current(
                "commercial-delivery-draft-generation",
                "商单交付初稿生成提示词",
                "commercial_delivery.py::COMMERCIAL_DELIVERY_PROMPT",
                python_string_constant(COMMERCIAL_DELIVERY_PATH, "COMMERCIAL_DELIVERY_PROMPT"),
            )
        )
    if label in {"社交", "人脉"}:
        return contracts(
            actual_for_current(
                "social-metadata-extraction",
                "社交档案元数据抽取提示词",
                "openclaw-agents/social/person-profile-skill/SKILL.md + references/social-archive-metadata-contract.md",
                social_metadata_prompt(),
            )
        )
    if label == "衣橱":
        return contracts(
            {
                "id": "wardrobe-item-ingest-runtime",
                "title": "【衣橱】 Wardrobe 入库结构化契约",
                "sourceType": "runtime_prompt",
                "source": "openclaw_app/router/wardrobe.py::_wardrobe_intake_prompt",
                "appliesTo": ["【衣橱】"],
                "purpose": "让 LLM 基于用户正文和图片证据抽取 WardrobeItem 允许字段；Python 生成 item_id、写入附件和 Feishu 衣橱表。",
                "promptBody": "\n".join(
                    [
                        "能力标签：【衣橱】",
                        "任务：Wardrobe OS 新衣物入库或补充已入库衣服的截图/OCR字段。",
                        "只返回 JSON object，不要 Markdown。",
                        "fields 只能使用 wardrobe-model-contract.json 的 agent_write_fields 英文 key。",
                        "item_id、created_at、photo、receipts 由 Python 写入，不能由 LLM 改写。",
                        "证据不足时返回 status=pending_manual 和 reason，不写入衣橱。",
                        "后补截图没有当前正文衣物ID、回复确认消息或命中 bot reply 上下文时返回 wardrobe_item_link_pending，不猜测关联对象。",
                    ]
                ),
                "inputBoundary": [
                    "入口必须以【衣橱】触发。",
                    "只使用用户正文、上传附件、被回复对象和运行时明确加载的上下文。",
                    "新衣物可没有 item_id；补订单/洗标/吊牌截图必须带入库确认里的 item_id。",
                    "禁止写入该能力声明目标以外的业务域表。",
                ],
                "outputContract": [
                    "成功时返回 Feishu 衣橱记录、名称、item_id、识别字段和待补字段。",
                    "LLM 只写 display_name/color/brand/occasion/category/fit/season/style_tags/status/location 等契约允许字段。",
                    "缺 display_name、证据不足或无法通过 item_id/reply/context 关联后补截图时返回 pending/manual，不写入。",
                ],
                "writesTo": ["Feishu Bitable 衣橱 / WARDROBE_ITEMS_URL"],
                "publicSummary": ["这是 Wardrobe 入库运行契约；用户正文、图片内容和 Feishu 凭据不进入公开 JSON。"],
                "fullPromptPolicy": policy,
                "exposure": "summary_only",
            }
        )
    if label == "穿搭":
        return contracts(
            {
                "id": "wardrobe-recommendation-runtime",
                "title": "【穿搭】 Wardrobe 推荐结构化契约",
                "sourceType": "runtime_prompt",
                "source": "openclaw_app/router/wardrobe.py::_wardrobe_recommendation_prompt",
                "appliesTo": ["【穿搭】"],
                "purpose": "让 LLM 基于已入库 WardrobeItem、当前位置/目的地或 Daily 显式地点、Open-Meteo 自动天气和可选 Daily 上下文生成穿搭或行李建议。",
                "promptBody": "\n".join(
                    [
                        "能力标签：【穿搭】",
                        "任务：Wardrobe OS outfit or packing recommendation。",
                        "只返回 JSON object，不要 Markdown。",
                        "只能基于 wardrobe_items 中存在的单品推荐，不要发明衣服。",
                        "缺 current_location 或自动天气不可用时返回 wardrobe_context_pending，不写推荐 artifact。",
                        "推荐只写 Obsidian artifact，不更新衣橱事实。",
                    ]
                ),
                "inputBoundary": [
                    "入口必须以【穿搭】触发。",
                    "必须有当前位置、旅行目的地或同次 Daily/待办/日程上下文里的显式地点字段；天气由运行时根据位置调用 Open-Meteo 自动获取。",
                    "不得要求用户手填天气，不得用 Codex 搜索、服务器 IP、历史消息或普通待办正文猜测补位置。",
                    "只读取 Wardrobe OS 衣橱表、显式 Daily 上下文和运行时天气结果。",
                    "禁止写入该能力声明目标以外的业务域表。",
                ],
                "outputContract": [
                    "输出 status/title/summary/source/sections JSON。",
                    "sections.items 的 item_id 必须来自读取到的 wardrobe_items。",
                    "成功后 Python 渲染为 Obsidian 物品/*.md 推荐 artifact。",
                ],
                "writesTo": ["Obsidian 物品/*.md"],
                "publicSummary": ["这是 Wardrobe 推荐运行契约；页面只展示脱敏边界，不展示用户位置历史或私密上下文。"],
                "fullPromptPolicy": policy,
                "exposure": "summary_only",
            }
        )
    if label == "思考":
        return contracts(
            actual_for_current(
                "deepmath-ceo-thinking-structure",
                "DeepMath CEO 思考结构化提示词",
                "deepmath_thinking_intake.py::DeepMathThinkingIntakeService.prompt",
                python_function_return(DEEPMATH_THINKING_INTAKE_PATH, "prompt"),
            )
        )
    if label == "归档":
        return contracts(actual_for_current("knowledge-weekly-archive", "Knowledge Obsidian 周记归档提示词", "Knowledge bot AGENTS.md", knowledge_section_prompt_body("归档")))
    if label in {"学习", "学习-整理"}:
        return contracts(actual_for_current("knowledge-learning", "Knowledge 学习拆解提示词", "Knowledge bot AGENTS.md", knowledge_section_prompt_body(label)))
    if label == "说明":
        return contracts(
            actual_for_current(
                "capability-matcher-guidance",
                "能力匹配与路径引导提示词",
                "capability_matcher.py::_build_prompt",
                python_function_return(CAPABILITY_MATCHER_PATH, "_build_prompt"),
            ),
            actual_prompt_contract(
                contract_id="capability-matcher-continuation",
                title="能力路径续接提示词",
                source="capability_matcher.py::compose_continuation.prompt",
                prompt_body=python_prompt_assignment(CAPABILITY_MATCHER_PATH, "compose_continuation"),
                applies_to=[raw_label],
                purpose="在上游步骤真实完成并绑定 allowlist 产物后，生成下一步可直接发送的完整指令。",
                input_boundary=[
                    "只接受已登记 guidance plan、当前 waiting step、原始需求和真实 allowlist bindings。",
                    "不得编造 source_asset_id、run_id 或其他上游产物；原始 URL 必须逐字保留。",
                    "同一 guidancePlanId 的重复或并发提交按 plan 串行化；已完成的上游 handler 不得再次执行。",
                ],
                output_contract=[
                    "只返回 capabilityId、variantId、extractedParams、confidence 和 evidence 组成的结构化 JSON object。",
                    "服务端根据 CapabilityRegistry v3 重新校验字段、类型、枚举和 evidence，再派生可复制投影。",
                    "续接模型或校验失败时保留真实 bindings；用户重发原指令只重试续接生成，不重复创建上游 artifact。",
                ],
                writes_to=["当前 Bot 回复中的下一步可复制指令"],
                source_type="runtime_prompt",
            ),
        )
    if label == "调研":
        return contracts(default_runtime_contract(label, category))
    if label == "补全":
        return contracts(complete_knowledge)
    if label == "认知":
        return contracts(cognition_weekly)
    if label == "数据复盘":
        return contracts(data_review)
    if label == "作品验收":
        return contracts(work_acceptance)
    if label in {"润色", "网感", "文案优化", "改标题", "去AI味", "小红书文案", "抖音文案"}:
        return contracts(
            actual_for_current(
                "style-polish-editor",
                "自然中文润色 LLM 编辑契约",
                "selfmedia/style/service.py::_build_style_prompt",
                python_function_return(STYLE_POLISH_SERVICE_PATH, "_build_style_prompt"),
                applies_to=["【润色】", "【网感】", "【文案优化】", "【改标题】", "【去AI味】", "【小红书文案】", "【抖音文案】"],
            )
        )
    if label in {"创作", "创作>小红书", "创作>抖音", "创作-拍摄执行"}:
        return contracts(creation_main)
    return contracts(default_runtime_contract(label, category))


def deepmath_help_projection(
    capabilities: list[dict[str, Any]],
    runtime_items: list[dict[str, Any]],
) -> dict[str, Any]:
    source: tuple[dict[str, Any], dict[str, Any]] | None = None
    for capability, runtime_item in zip(capabilities, runtime_items):
        if capability["primaryBot"] != "deepmath":
            continue
        if source is not None:
            raise RuntimeError("DeepMath help projection requires exactly one canonical runtime capability")
        source = (capability, runtime_item)
    if source is None:
        raise RuntimeError("DeepMath help projection cannot find its canonical runtime capability")
    capability, runtime_item = source
    status = safe_text(str(runtime_item.get("implementation_status") or "")).strip()
    current_by_status = {
        "implemented": ["已实现：收件、恰好一次 LLM 结构化、生成候选；除收件和候选持久化外零外部副作用。"],
        "not_implemented": ["当前尚未实现 DeepMath 思考收件，不得声称已写入或已执行。"],
        "external": ["当前只由外部链路承接，不得误报为 DeepMath 本地实现。"],
    }
    if status not in current_by_status:
        raise RuntimeError(
            f"{capability['rawLabel']} DeepMath help projection requires a known implementation_status; got {status!r}"
        )
    projection: dict[str, Any] = {
        "title": "DeepMath 能力说明",
        "summary": "只展示 DeepMath 当前实现事实、尚未实现边界和冻结目标。",
        "statusSourceCapabilityId": capability["canonicalCapabilityId"],
        "implementationStatus": status,
        "current": current_by_status[status],
        "notYet": ["尚未实现：审批卡片和真实执行。"],
        "frozenTarget": ["冻结目标：用户确认就是执行授权，确认后立即执行当前版本提案。"],
    }
    projection_text = json.dumps(projection, ensure_ascii=False)
    for forbidden in DEEPMATH_HELP_FORBIDDEN_TERMS:
        if re.search(rf"\b{re.escape(forbidden)}\b", projection_text, flags=re.IGNORECASE):
            raise RuntimeError(f"DeepMath help projection contains forbidden cross-Bot text: {forbidden}")
    return projection


def build_bots(
    capabilities: list[dict[str, Any]] | None = None,
    runtime_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    deepmath_projection = deepmath_help_projection(capabilities or [], runtime_items or [])
    return [
        {
            "id": "media",
            "name": "Media bot",
            "title": "内容创作 Bot",
            "description": "处理活动、素材、拆解、创作、拍摄执行、作品验收、数据复盘和商务内容协作。",
            "primaryTaskGroups": ["content"],
            "featuredCapabilityIds": [
                "creation",
                "creation-xiaohongshu",
                "creation-shooting-execution",
                "media-source-asset",
                "work-acceptance",
            ],
            "entryLinks": [{"label": "查看 Media bot 能力", "url": "#/bots/media", "status": "active"}],
        },
        {
            "id": "daily",
            "name": "Daily bot",
            "title": "日程执行 Bot",
            "description": "处理待办、日程、今日清单、日记、周记、正式开发任务和开发任务状态推进。",
            "primaryTaskGroups": ["daily"],
            "featuredCapabilityIds": ["today", "todo", "calendar", "daily-journal", "weekly", "development-todo-traceability", "development-complete"],
            "entryLinks": [{"label": "查看 Daily bot 能力", "url": "#/bots/daily", "status": "active"}],
        },
        {
            "id": "knowledge",
            "name": "Knowledge bot",
            "title": "知识整理 Bot",
            "description": "处理归档、补全、认知沉淀、学习整理和自媒体知识。",
            "primaryTaskGroups": ["knowledge"],
            "featuredCapabilityIds": ["selfmedia-knowledge", "learning", "archive", "cognition"],
            "entryLinks": [{"label": "查看 Knowledge bot 能力", "url": "#/bots/knowledge", "status": "active"}],
        },
        {
            "id": "social",
            "name": "Social bot",
            "title": "社交人脉 Bot",
            "description": "处理社交对象、人脉资料和可公开的创作者档案入口；不在能力中心暴露具体私密资料。",
            "primaryTaskGroups": ["social"],
            "featuredCapabilityIds": ["social", "contacts", "creator-profile"],
            "entryLinks": [{"label": "查看 Social bot 能力", "url": "#/bots/social", "status": "active"}],
        },
        {
            "id": "deepmath",
            "name": "DeepMath bot",
            "title": "DeepMath 思考 Bot",
            "description": "接收 DeepMath 原始思考并沉淀为事实、判断、假设和待审批候选。",
            "primaryTaskGroups": ["deepmath"],
            "featuredCapabilityIds": ["deepmath-ceo-thinking"],
            "entryLinks": [{"label": "查看 DeepMath bot 能力", "url": "#/bots/deepmath", "status": "active"}],
            "helpProjection": deepmath_projection,
        },
    ]


def build_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "content",
            "title": "内容生产",
            "group": "content",
            "description": "写稿、拆解素材、生成拍摄执行单、验收作品或做数据复盘。",
            "recommendedBot": "media",
            "recommendedCapabilityIds": [
                "creation",
                "creation-xiaohongshu",
                "creation-douyin",
                "creation-shooting-execution",
                "media-source-asset",
                "research",
                "work-acceptance",
            ],
        },
        {
            "id": "daily",
            "title": "日程执行",
            "group": "daily",
            "description": "创建提醒、查看今日安排、记录日记、提取周记、创建正式开发任务并推进开发任务完成或验证。",
            "recommendedBot": "daily",
            "recommendedCapabilityIds": ["today", "todo", "calendar", "daily-journal", "weekly", "development-todo-traceability", "development-complete", "development-verify"],
        },
        {
            "id": "knowledge",
            "title": "知识整理",
            "group": "knowledge",
            "description": "沉淀知识、认知、补全文档、整理学习材料和处理自媒体知识。",
            "recommendedBot": "knowledge",
            "recommendedCapabilityIds": ["selfmedia-knowledge", "archive", "cognition", "complete-knowledge", "learning"],
        },
        {
            "id": "social",
            "title": "社交人脉",
            "group": "social",
            "description": "整理社交对象、人脉档案、博主资料和后续跟进线索。",
            "recommendedBot": "social",
            "recommendedCapabilityIds": ["social", "contacts", "creator-profile"],
        },
    ]


def build_flows(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capability_ids = {capability["id"] for capability in capabilities}

    def related(*ids: str) -> list[str]:
        return [item for item in ids if item in capability_ids]

    stage_enrichment = {
        "cloud-project-package": {
            "entryConditions": ["你已经明确想做一个内容项目", "平台、主题或表达方向基本清楚"],
            "completionSignals": ["项目卡、brief 或脚本初稿已经生成", "项目可以进入等素材绑定的状态", "本地素材还没绑定也没关系"],
            "blockers": ["只有一堆素材，但还不知道要做什么内容", "非要先填 Mac 路径才允许立项", "把想要的素材写成已经确认拥有的素材"],
            "handoffArtifacts": ["项目总览", "选题卡", "项目 brief", "脚本初稿"],
        },
        "local-binding-gate": {
            "entryConditions": ["内容项目已经立项", "你希望 Mac 参与找素材、配素材或生成剪辑方案"],
            "completionSignals": ["已经给出批次说明、本地项目线索或 Mac 回写结果", "任务可以放心交给 Mac 侧继续处理"],
            "blockers": ["没有任何本地线索却派成可执行任务", "腾讯云自己猜 Mac 上的目录", "把待绑定误当成已经可执行"],
            "handoffArtifacts": ["待绑定状态", "可交给 Mac 的任务", "批次说明"],
        },
        "mac-intake": {
            "entryConditions": ["你在 Mac 上拿到了新照片、视频或录屏", "同一事件的素材已经放在同一批次里", "批次说明只写必要事实和项目线索"],
            "completionSignals": ["这批素材能被 Mac 侧读取", "大概属于哪个项目已经清楚", "需要人工确认的地方被标出来"],
            "blockers": ["按手机、相机等设备来源混放多个事件", "把整篇云端初稿复制进批次说明", "把批次说明写成最终整理结论"],
            "handoffArtifacts": ["批次说明", "事件素材批次", "内容项目线索"],
        },
        "mac-material-analysis": {
            "entryConditions": ["Mac 能读到真实素材文件", "项目说明、脚本、任务或批次说明至少有一个可用线索"],
            "completionSignals": ["素材清单、关键帧和摘要已经生成", "Raw、Live Photo、360、录屏等素材类型已识别"],
            "blockers": ["Mac 看不到素材", "证据不足却说素材质量已经满足", "把 AI 分析缓存当成精选照片库"],
            "handoffArtifacts": ["素材清单", "关键帧", "素材摘要", "AI 分析记录"],
        },
        "creative-assembly": {
            "entryConditions": ["云端脚本和本地素材证据都能读到", "项目方向或叙事目标已经有人确认"],
            "completionSignals": ["素材匹配、分镜和剪辑交接包已经形成", "需要人工决定的叙事、节奏和审美点被标出来"],
            "blockers": ["只有脚本，没有素材证据", "只有素材，不知道要讲什么", "把 AI 建议当成最终剪辑决定"],
            "handoffArtifacts": ["素材匹配报告", "分镜", "标准剪辑交接包或可编辑时间线", "字幕包"],
        },
        "editing-packaging": {
            "entryConditions": ["已经有可剪素材和剪辑方案", "人决定是否需要标题卡、信息卡或动态图文包装"],
            "completionSignals": ["包装素材或候选成片已经产出", "剪辑方式与当前项目版本一致"],
            "blockers": ["把包装素材当成可编辑时间线", "把工程缓存当项目素材", "缺少人工节奏和审美确认"],
            "handoffArtifacts": ["标题卡", "信息卡", "透明叠加素材", "标准剪辑交接包或可编辑时间线", "候选成片"],
        },
        "output-review-writeback": {
            "entryConditions": ["候选成片已经导出", "有创作要求、平台目标或项目上下文可以对照检查"],
            "completionSignals": ["成片检查完成", "问题清单、证据和返修建议已经写清楚"],
            "blockers": ["把本地检查通过当成已经能发布", "没有证据就给 Final 结论", "返修问题说得太笼统"],
            "handoffArtifacts": ["成片质检报告", "证据截图或指标", "结果回写", "返修建议"],
        },
        "publish-archive": {
            "entryConditions": ["人已经确认 Final 或发布状态", "需要做数据复盘、精选入库或归档"],
            "completionSignals": ["复盘结论、账号记忆或归档索引已经形成", "后续再创作能基于这些事实继续"],
            "blockers": ["把 iCloud 云盘当成全量素材库", "发布后不做复盘", "旧项目没有恢复索引"],
            "handoffArtifacts": ["发布包", "数据复盘", "账号记忆", "精选入库", "冷归档索引"],
        },
        "knowledge-source-capture": {
            "entryConditions": ["材料来自明确链接、正文或附件", "需要把内容转成可复用知识或会议纪要"],
            "completionSignals": ["来源、关键事实、可复用认知或逐字稿已经整理清楚", "需要人工确认的字段已标出"],
            "blockers": ["附件不可读却生成结论", "链接内容没有证据就写成事实", "把转写和知识入库混成一个不清楚的动作"],
            "handoffArtifacts": ["来源摘要", "关键事实", "结构化知识候选", "待人工确认项"],
        },
        "knowledge-weekly-archive": {
            "entryConditions": ["用户明确发送归档、补全、认知、学习或学习整理标签", "需要写入 Obsidian 周记或学习目录"],
            "completionSignals": ["周记条目或学习文件已经生成", "日期、标题、来源和逻辑检查可追溯"],
            "blockers": ["把默认 Obsidian 归档误当成飞书知识表入库", "没有正文却补出事实", "标题只写归档或学习内容"],
            "handoffArtifacts": ["周记知识条目", "周记认知条目", "学习文件链接", "逻辑检查摘要"],
        },
        "media-growth-research": {
            "entryConditions": ["用户给出明确内容问题", "存在链接、粘贴文字或可核验的证据摘要"],
            "completionSignals": ["ExternalResearchBrief 已记录证据摘要和内容机会", "证据不足时明确为 pending_manual"],
            "blockers": ["没有显式证据", "把通用知识回答写成内容机会", "委托 Knowledge 深度研究"],
            "handoffArtifacts": ["ExternalResearchBrief", "证据摘要", "内容机会", "待补证据项"],
        },
        "system-document-actions": {
            "entryConditions": ["用户调用说明、最近、同步、状态、规则、整理或修改等辅助入口，或明确用【codex】提交维护任务", "目标文档、查询范围或维护目标足够明确"],
            "completionSignals": ["只返回说明、查询结果、后台 task_id 或明确的处理结果", "长任务可按 task_id 查询心跳并在完成后读取最终文本", "需要人工补充的信息被标出来"],
            "blockers": ["把说明入口当成业务执行", "目标文档不明确却尝试修改", "查询类入口顺手新增业务记录", "在公开状态中暴露维护请求正文、完整命令、本机路径或受控日志"],
            "handoffArtifacts": ["能力说明", "最近记录摘要", "同步结果", "状态结果", "Codex 后台 task_id 与最终文本", "同文档修改结果"],
        },
    }

    flows = [
        {
            "id": "cloud-mac-materials",
            "title": "内容从选题到成片怎么流转",
            "description": "给媒体运营看的流程看板：看清一个内容项目现在停在哪、该由腾讯云、人工还是 Mac 继续处理，以及下一环节要拿到什么材料。",
            "sourceDoc": "06_技术栈与自动化/腾讯云OpenClaw与MAC_OpenClaw本地素材协同流转规范.md",
            "visibility": "normal",
            "stages": [
                {
                    "id": "cloud-project-package",
                    "title": "先把选题立成项目",
                    "summary": "先把选题、平台和内容方向整理成项目卡、brief 和脚本初稿；这一步只写创作需求，不假装已经看过 Mac 上的素材。",
                    "owner": "cloud",
                    "inputs": ["想做什么内容", "准备发在哪个平台", "希望先出初稿、brief 或脚本", "目标人群或表达重点"],
                    "outputs": ["选题卡", "项目 brief", "脚本初稿", "项目进入可继续推进状态"],
                    "relatedCapabilityIds": related(
                        "creation",
                        "creation-xiaohongshu",
                        "creation-douyin",
                        "creation-shooting-execution",
                        "creation-consultation",
                        "media-source-asset",
                    ),
                    "boundaries": ["这一步不需要先知道素材在 Mac 哪里", "只能写需要什么素材，不能写已经有什么素材", "还不能直接派 Mac 执行素材任务"],
                    "nextStep": "如果这个选题要用本地素材，就先确认素材线索能不能交给 Mac。",
                },
                {
                    "id": "local-binding-gate",
                    "title": "确认素材能不能交给 Mac",
                    "summary": "判断这个项目有没有足够线索交给 Mac 去找素材；没有线索就先停在待绑定，不要派成可执行任务。",
                    "owner": "mixed",
                    "inputs": ["已立项内容", "批次说明线索", "素材批次线索", "已回写的结果"],
                    "outputs": ["待绑定状态", "可交给 Mac 的任务", "给 Mac 的处理说明"],
                    "relatedCapabilityIds": related("media-source-asset", "creation", "creation-shooting-execution"),
                    "boundaries": ["没有本地线索时不能派成可执行任务", "腾讯云不自己猜 Mac 上有什么素材"],
                    "nextStep": "素材线索够了以后，人把素材批次放进 Mac 的素材入口。",
                },
                {
                    "id": "mac-intake",
                    "title": "把素材按事件收进 Mac",
                    "summary": "人在 Mac 上把同一事件的照片、视频和录屏放到同一个批次，批次说明只写必要事实和项目线索。",
                    "owner": "human",
                    "inputs": ["新导入照片、视频或录屏", "同一事件的素材批次", "批次说明", "已立项内容"],
                    "outputs": ["待整理素材批次", "内容归属候选", "需要人工确认的问题"],
                    "relatedCapabilityIds": related("activity", "inspiration", "inspiration-vlog"),
                    "boundaries": ["批次说明不是最终整理结论", "原始素材不放进 Obsidian", "普通页面不展示真实本地位置"],
                    "nextStep": "Mac 侧读取批次说明、任务和素材信息后，开始盘点素材。",
                },
                {
                    "id": "mac-material-analysis",
                    "title": "让 Mac 盘点素材",
                    "summary": "Mac 侧读取真实素材，整理素材清单、关键帧和摘要，让云端后续能基于证据改脚本或做剪辑方案。",
                    "owner": "mac",
                    "inputs": ["本地素材", "任务说明", "项目 brief", "脚本初稿", "文件信息和关键帧"],
                    "outputs": ["素材清单", "关键帧", "素材摘要", "素材类型和可用性判断"],
                    "relatedCapabilityIds": related(
                        "media-source-asset",
                        "deconstruction",
                        "creation",
                    ),
                    "boundaries": ["不替人决定最终审美", "不把分析缓存当精选库", "不直接发布"],
                    "nextStep": "把云端脚本和素材证据合在一起，生成剪辑方案。",
                },
                {
                    "id": "creative-assembly",
                    "title": "生成剪辑方案",
                    "summary": "把 brief、脚本和素材证据合起来，整理成素材匹配、分镜、标准剪辑交接包或可编辑时间线，并配好字幕。",
                    "owner": "mixed",
                    "inputs": ["云端初稿", "本地素材清单", "关键帧", "脚本", "项目目标"],
                    "outputs": ["素材匹配报告", "分镜", "标准剪辑交接包或可编辑时间线", "字幕包"],
                    "relatedCapabilityIds": related(
                        "creation",
                        "creation",
                        "creation-shooting-execution",
                        "creation-check",
                        "work-acceptance",
                    ),
                    "boundaries": ["不替代人工叙事和节奏判断", "需要人确认哪些素材保留、删除和怎么剪"],
                    "nextStep": "方案确认后，进入包装制作或人工精剪。",
                },
                {
                    "id": "editing-packaging",
                    "title": "做包装和人工精剪",
                    "summary": "需要标题卡、信息卡或动态图文包装时先做包装素材；节奏、字幕、音乐和封面仍由人来把关。",
                    "owner": "human",
                    "inputs": ["分镜", "标准剪辑交接包或可编辑时间线", "包装需求", "可剪素材", "人工审美判断"],
                    "outputs": ["标题卡", "信息卡", "透明叠加素材", "候选成片"],
                    "relatedCapabilityIds": related("creation-shooting-execution", "creation-check", "work-acceptance", "creation"),
                    "boundaries": ["包装素材不等于可编辑时间线", "素材和交接包必须对应当前项目版本", "最终剪辑由人负责"],
                    "nextStep": "候选成片导出后，交给 Mac 做成片检查。",
                },
                {
                    "id": "output-review-writeback",
                    "title": "检查成片并回写结果",
                    "summary": "Mac 侧对候选成片做发布前检查，输出证据、问题清单和返修建议；是否发布仍由人决定。",
                    "owner": "mac",
                    "inputs": ["V1、V2 或 Final 成片", "创作要求", "平台目标", "项目上下文"],
                    "outputs": ["成片质检报告", "问题清单", "结果回写", "返修或 Final 建议"],
                    "relatedCapabilityIds": related("work-acceptance", "data-review", "creation-check", "retrospective"),
                    "boundaries": ["本地检查通过不等于已经发布", "是否发布仍由人确认"],
                    "nextStep": "人确认 Final 后，进入发布、复盘和归档。",
                },
                {
                    "id": "publish-archive",
                    "title": "发布复盘和归档",
                    "summary": "发布稳定后，把表现数据、复盘结论、精选素材和归档索引沉淀下来，方便后续再创作和找旧素材。",
                    "owner": "mixed",
                    "inputs": ["Final 成片", "发布结果", "复盘结论", "精选入口", "归档索引"],
                    "outputs": ["发布包", "数据复盘", "账号记忆", "精选入库", "冷归档索引"],
                    "relatedCapabilityIds": related("data-review", "retrospective"),
                    "boundaries": ["不把 iCloud 云盘当全量素材库", "腾讯云后续不能直接猜 Mac 目录", "旧项目源素材按归档索引恢复"],
                    "nextStep": "以后再创作时，从复盘记忆、回写事实和归档索引重新进入流程。",
                },
            ],
        },
        {
            "id": "media-growth-research-flow",
            "title": "调研证据到选题怎么流转",
            "description": "给 Media bot 使用者看的证据登记流程：只把明确来源转成 ExternalResearchBrief，再交给选题；不再存在 Knowledge 深度研究分支。",
            "sourceDoc": "selfmedia-tools/openclaw-tag-router/openclaw_app/router/media_growth.py",
            "visibility": "normal",
            "stages": [
                {
                    "id": "media-growth-research",
                    "title": "登记调研证据",
                    "summary": "把用户提供的链接、粘贴文字或可核验证据摘要登记为 ExternalResearchBrief，标出内容机会和待补证据项。",
                    "owner": "cloud",
                    "inputs": ["内容问题", "账号或目标人群", "平台", "赛道或内容目标", "链接/粘贴文字/证据摘要"],
                    "outputs": ["ExternalResearchBrief", "证据摘要", "内容机会", "待补证据项"],
                    "relatedCapabilityIds": related("research"),
                    "boundaries": ["没有显式证据时返回 pending_manual", "不委托 Knowledge 深度研究", "不把推测写成事实"],
                    "nextStep": "证据足够后，用【选题】比较候选方向并进入创作。",
                },
            ],
        },
        {
            "id": "knowledge-archive-flow",
            "title": "知识从材料到沉淀怎么流转",
            "description": "给 Knowledge bot 使用者看的流程看板：区分链接/附件分析、Obsidian 周记归档和通用系统入口，避免把默认回复误解成飞书入库。",
            "sourceDoc": "openclaw-agents/knowledge/AGENTS.md",
            "visibility": "normal",
            "stages": [
                {
                    "id": "knowledge-source-capture",
                    "title": "整理来源材料",
                    "summary": "把链接、正文或附件整理成可复用知识、会议纪要或自媒体知识候选；能写飞书表的只有明确拥有表目标的能力。",
                    "owner": "cloud",
                    "inputs": ["链接或原文", "上传附件", "想沉淀的问题", "证据范围"],
                    "outputs": ["来源摘要", "关键事实", "结构化知识候选", "待确认项"],
                    "relatedCapabilityIds": related("selfmedia-knowledge", "transcription", "transcription-text"),
                    "boundaries": ["附件不可读时不编造逐字稿", "自媒体知识写表，转写默认写 Obsidian 会议纪要"],
                    "nextStep": "需要长期沉淀时，按能力目标写入自媒体知识表、会议纪要或继续转成周记归档。",
                },
                {
                    "id": "knowledge-weekly-archive",
                    "title": "写入 Obsidian 周记",
                    "summary": "归档、补全、认知和学习类入口默认写 Obsidian，不默认写飞书知识表；页面需要明确日期、标题、来源和写入小节。",
                    "owner": "storage",
                    "inputs": ["日期或周范围", "标题", "来源", "正文或学习材料", "整理目标"],
                    "outputs": ["周记知识条目", "周记认知条目", "学习文件", "逻辑检查摘要"],
                    "relatedCapabilityIds": related("archive", "complete-knowledge", "cognition", "learning", "learning-organize"),
                    "boundaries": ["默认不写飞书知识表", "没有日期时用当前消息所在周", "不把整段原文直接粘贴进周记"],
                    "nextStep": "需要飞书入库时，用户必须明确提出入库目标，再进入对应知识表能力。",
                },
                {
                    "id": "system-document-actions",
                    "title": "执行说明、查询和文档辅助",
                    "summary": "说明、最近、同步、状态、整理和修改是辅助入口；说明会生成可执行路径但不代替对应 Bot 执行业务。【codex】维护长任务会快速返回 task_id，模型容量暂满时按同一冻结契约恢复原 Codex thread，并支持状态心跳与最终文本查询。",
                    "owner": "mixed",
                    "inputs": ["目标 Bot 或标签", "数量、日期或查询范围", "目标飞书文档", "修改要求", "授权范围内的维护目标"],
                    "outputs": ["能力说明或可复制路径指令", "最近记录摘要", "同步结果", "状态结果", "Codex 后台 task_id 与最终文本", "同文档修改结果"],
                    "relatedCapabilityIds": related("help", "recent", "sync", "status", "organize", "document-edit"),
                    "boundaries": ["说明只规划和生成待发送指令，不执行业务", "查询类入口不新增业务记录", "修改必须有明确目标文档", "后台状态不公开请求正文、完整命令、本机路径或受控日志"],
                    "nextStep": "复制当前 ready 指令发送到对应 Bot；Codex 长任务使用【codex】状态 task_id 查询；多步骤在真实结果绑定后继续。",
                },
            ],
        }
    ]
    for flow in flows:
        for stage in flow["stages"]:
            stage.update(stage_enrichment[stage["id"]])
    return flows


def build_links() -> list[dict[str, str]]:
    return [
        {
            "id": "link-overview",
            "group": "bot_entry",
            "title": "能力中心总览",
            "description": "回到总览，从任务、Bot 或能力入口继续查找。",
            "url": "#/",
            "visibility": "normal",
            "status": "active",
            "sensitivity": "public",
        },
        {
            "id": "link-capabilities",
            "group": "capability_doc",
            "title": "能力目录",
            "description": "普通视图按 canonical 折叠入口；维护视图可查看完整真实触发标签。",
            "url": "#/capabilities",
            "visibility": "normal",
            "status": "active",
            "sensitivity": "public",
        },
        {
            "id": "link-matrix",
            "group": "capability_doc",
            "title": "能力对照",
            "description": "按四个 Bot 对照主能力、可见能力和不可见能力。",
            "url": "#/capabilities/matrix",
            "visibility": "normal",
            "status": "active",
            "sensitivity": "public",
        },
        {
            "id": "link-flow-cloud-mac",
            "group": "collaboration_doc",
            "title": "内容从选题到成片怎么流转",
            "description": "查看一个内容项目从选题、素材、剪辑、检查到发布复盘，每一步该谁处理、交接什么。",
            "url": "#/flows/cloud-mac-materials",
            "visibility": "normal",
            "status": "active",
            "sensitivity": "public",
        },
        {
            "id": "link-flow-knowledge",
            "group": "collaboration_doc",
            "title": "知识从材料到沉淀怎么流转",
            "description": "查看 Knowledge bot 从来源材料、Obsidian 周记、研究回答到系统辅助入口的边界。",
            "url": "#/flows/knowledge-archive-flow",
            "visibility": "normal",
            "status": "active",
            "sensitivity": "public",
        },
        {
            "id": "link-ia",
            "group": "collaboration_doc",
            "title": "四 Bot 能力页面 IA",
            "description": "页面信息架构的协作文档入口；公开页面不展示文档正文。",
            "url": "#/links",
            "visibility": "maintainer",
            "status": "unknown",
            "sensitivity": "internal",
        },
        {
            "id": "link-deploy",
            "group": "maintainer_doc",
            "title": "腾讯云静态部署说明",
            "description": "Nginx / COS 静态部署和缓存策略说明。",
            "url": "docs/deploy.md",
            "visibility": "maintainer",
            "status": "active",
            "sensitivity": "internal",
        },
    ]


def main() -> None:
    raw = import_source()
    capabilities = [build_capability(item) for item in raw]
    add_relationships(capabilities)
    add_entry_trees(capabilities)
    apply_display_contracts(capabilities)
    commit = source_commit()
    release = release_version()
    canonical_count = len({capability["canonicalCapabilityId"] for capability in capabilities})
    recommended_count = sum(1 for capability in capabilities if capability["recommendedEntry"])
    meta = {
        "schemaVersion": "1.0.0",
        "releaseVersion": release,
        "contentVersion": release,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "tag_capabilities.py",
        "generatorVersion": release,
        "capabilityCount": len(capabilities),
        "triggerLabelCount": len(capabilities),
        "canonicalCapabilityCount": canonical_count,
        "recommendedEntryCount": recommended_count,
        "warningCount": 0,
    }
    if commit:
        meta["sourceCommit"] = commit
    data = {
        "meta": meta,
        "bots": build_bots(capabilities, raw),
        "capabilities": capabilities,
        "tasks": build_tasks(),
        "flows": build_flows(capabilities),
        "contentOsProjectDashboard": build_content_os_project_dashboard(),
        "links": build_links(),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(capabilities)} capabilities")


if __name__ == "__main__":
    main()
