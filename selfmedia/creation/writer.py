from __future__ import annotations

import os
import re
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

import requests

from common.feishu_docx_table_limits import (
    chunk_docx_table_rows,
    ensure_docx_tables_write_budget,
    ensure_docx_table_write_budget,
    sleep_seconds_for_docx_write,
    validate_docx_table_create_shape,
)
from common.social_runtime import (
    FEISHU_BASE,
    feishu_bitable_refs,
    feishu_coerce_value,
    feishu_ensure_fields,
    feishu_field_types,
    feishu_headers,
    feishu_tenant_access_token,
    load_default_env_files,
)
from common.standard_fields import standard_field_specs

from .matcher import RankedRecord
from .request_parser import CreationRequest


FEISHU_DOC_WRITE_SLEEP_SEC = sleep_seconds_for_docx_write()
NATIVE_TABLE_KIND = "_openclaw_feishu_table"
CREATION_TASK_POOL_PARENT_NODE_TOKEN = "Tm69wEqFpi76d9k53KEcqK4Rnkh"
SHOOTING_PRIORITY_LABELS = {
    "P0": "必拍",
    "P1": "重要",
    "P2": "可选",
}
SHOOTING_PLAN_FIELD_LABELS = {
    "shooting_goal": "拍摄目标",
    "route_map": "路线图",
    "must_shot_list": "必拍镜头清单",
    "branch_plans": "分支方案",
    "storyboard": "分镜脚本",
    "onsite_checklist": "现场检查清单",
    "publishing_pack": "发布包",
    "evidence_appendix": "证据附录",
}
EVIDENCE_SOURCE_STATUS_LABELS = {
    "confirmed": "已核验",
    "manual_description_only": "仅凭文字描述，未看过原片",
    "pending_manual": "待人工核实",
}


LEGACY_CREATION_RECORD_FIELD_SPECS = {
    "标题": 1,
    "类型": 3,
    "内容": 1,
    "状态": 3,
    "关联ID": 1,
    "创建时间": 5,
    "更新时间": 5,
    "平台": 1,
    "内容类型": 1,
    "赛道": 1,
    "主题": 1,
    "关键词/标签": 1,
    "发布时间": 1,
    "关联活动ID": 1,
    "关联活动链接": 15,
    "返稿链接": 15,
    "关联商务ID": 1,
    "关联商务链接": 15,
    "账号": 1,
    "素材来源": 1,
    "定位分析": 1,
    "平台策略": 1,
    "发布链接": 15,
    "复盘状态": 1,
    "参考爆款ID": 1,
    "参考灵感ID": 1,
    "参考灵感文档链接": 15,
    "参考拆解文档链接": 15,
    "创作文档链接": 15,
    "活动匹配分": 2,
    "爆款匹配分": 2,
    "灵感匹配分": 2,
    "商务匹配分": 2,
    "匹配理由": 1,
    "标题校验": 1,
    "Tags校验": 1,
    "平台规则校验": 1,
    "校验结果": 1,
    "失败原因": 1,
    "创作请求": 1,
}

_STANDARD_CREATION_RECORD_FIELD_SPECS = standard_field_specs(LEGACY_CREATION_RECORD_FIELD_SPECS)
CREATION_RECORD_FIELD_SPECS = {
    name: _STANDARD_CREATION_RECORD_FIELD_SPECS[name]
    for name in LEGACY_CREATION_RECORD_FIELD_SPECS
    if not name.endswith("JSON")
}


def create_creation_doc(
    request: CreationRequest,
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    businesses: list[RankedRecord] | None = None,
    inspirations: list[RankedRecord] | None = None,
    platform_fit: dict[str, Any] | None = None,
) -> str:
    load_default_env_files()
    token = feishu_tenant_access_token()
    title = f"{request.content_type} - {request.topic} - {request.publish_time or '未定发布时间'}"
    blocks = _creation_doc_blocks(title, request, activities, virals, inspirations or [], businesses or [], draft, validation, platform_fit=platform_fit)
    document_id, node_token, created = _create_doc(title, token)
    if created:
        _append_blocks(document_id, blocks, token)
    else:
        _replace_blocks(document_id, blocks, token)
    return f"https://tcnwueberajc.feishu.cn/docx/{document_id}"


def create_shooting_execution_doc(
    request: Any,
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    media_context: dict[str, Any] | None = None,
) -> str:
    load_default_env_files()
    token = feishu_tenant_access_token()
    title = f"拍摄执行 - {request.topic} - {request.time_window or request.publish_time or '未定时间'}"
    blocks = _shooting_execution_doc_blocks(title, request, draft, validation, media_context=media_context)
    document_id, node_token, created = _create_doc(title, token)
    if created:
        _append_blocks(document_id, blocks, token)
    else:
        _replace_blocks(document_id, blocks, token)
    return f"https://tcnwueberajc.feishu.cn/docx/{document_id}"


def rewrite_shooting_execution_doc(
    doc_url: str,
    request: Any,
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    media_context: dict[str, Any] | None = None,
) -> str:
    """Rewrite an existing shooting document through the canonical renderer."""
    load_default_env_files()
    token = feishu_tenant_access_token()
    parsed = urlparse(str(doc_url or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("拍摄执行回洗缺少有效飞书文档链接")
    kind, target = parts[-2], parts[-1]
    if kind == "wiki":
        node = _get_wiki_node(target, token)
        document_id = str(node.get("obj_token") or "").strip()
        title = str(node.get("title") or "").strip()
        if str(node.get("obj_type") or "").lower() not in {"docx", "doc"} or not document_id:
            raise ValueError("拍摄执行回洗目标不是飞书 Docx 文档")
        canonical_url = f"https://tcnwueberajc.feishu.cn/wiki/{target}"
    elif kind in {"docx", "doc", "docs"}:
        document_id = target
        payload = _request_feishu_json("GET", f"/docx/v1/documents/{document_id}", token, timeout=20)
        title = str((payload.get("data") or {}).get("document", {}).get("title") or "").strip()
        canonical_url = f"https://tcnwueberajc.feishu.cn/docx/{document_id}"
    else:
        raise ValueError("拍摄执行回洗只支持飞书 Wiki/Docx 链接")
    if not title:
        title = f"拍摄执行 - {request.topic} - {request.time_window or request.publish_time or '未定时间'}"
    blocks = _shooting_execution_doc_blocks(title, request, draft, validation, media_context=media_context)
    _replace_blocks(document_id, blocks, token)
    return canonical_url


def _creation_output_fields_for_write(record_fields: dict[str, Any]) -> dict[str, Any]:
    return {
        field: record_fields[field]
        for field in CREATION_RECORD_FIELD_SPECS
        if field in record_fields
    }


def _url_field_value(value: Any, *, text: str = "") -> dict[str, str] | str:
    if value in (None, "", []):
        return ""
    if isinstance(value, dict):
        link = str(value.get("link") or value.get("url") or "").strip()
        label = str(value.get("text") or text or link).strip()
        return {"text": label or link, "link": link} if _is_url(link) else ""
    raw = str(value).strip()
    if _is_url(raw):
        return {"text": text or raw, "link": raw}
    match = re.search(r"https?://[^\s，。；;）)】>]+", raw)
    if not match:
        return ""
    link = match.group(0)
    label = (text or raw[: match.start()].strip(" ：:") or link).strip()
    return {"text": label, "link": link}


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _create_doc(title: str, token: str) -> tuple[str, str, bool]:
    parent_node = os.getenv("FEISHU_CREATION_DOC_PARENT_NODE_TOKEN") or CREATION_TASK_POOL_PARENT_NODE_TOKEN
    if parent_node:
        node = _get_wiki_node(parent_node, token)
        space_id = str(node.get("space_id") or "")
        if space_id:
            existing = _find_wiki_child_doc(space_id, parent_node, title, token)
            if existing:
                return existing[0], existing[1], False
            resp = requests.post(
                f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
                headers=feishu_headers(token),
                json={"obj_type": "docx", "parent_node_token": parent_node, "node_type": "origin", "title": title},
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                raise RuntimeError(f"创建创作文档失败：{payload}")
            created = payload.get("data", {}).get("node") or {}
            return str(created.get("obj_token") or ""), str(created.get("node_token") or ""), True
    body: dict[str, Any] = {"title": title}
    if folder_token := os.getenv("FEISHU_CREATION_DOC_FOLDER_TOKEN") or os.getenv("FEISHU_DOC_FOLDER_TOKEN"):
        body["folder_token"] = folder_token
    resp = requests.post(f"{FEISHU_BASE}/docx/v1/documents", headers=feishu_headers(token), json=body, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"创建创作文档失败：{payload}")
    return str(payload.get("data", {}).get("document", {}).get("document_id") or payload.get("data", {}).get("document_id") or ""), "", True


def _find_wiki_child_doc(space_id: str, parent_node: str, title: str, token: str) -> tuple[str, str] | None:
    matches: list[tuple[str, str]] = []
    page_token = ""
    while True:
        params = {"parent_node_token": parent_node, "page_size": 50}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_BASE}/wiki/v2/spaces/{space_id}/nodes",
            params=params,
            headers=feishu_headers(token),
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"查询创作文档失败：{payload}")
        data = payload.get("data") or {}
        for item in data.get("items") or []:
            if str(item.get("title") or "").strip() != title:
                continue
            if str(item.get("obj_type") or "").lower() not in {"docx", "doc"}:
                continue
            document_id = str(item.get("obj_token") or "").strip()
            node_token = str(item.get("node_token") or "").strip()
            if document_id and node_token:
                matches.append((document_id, node_token))
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "").strip()
        if not page_token:
            break
    return matches[-1] if matches else None


def _get_wiki_node(node_token: str, token: str) -> dict[str, Any]:
    resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": node_token}, headers=feishu_headers(token), timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取知识库父节点失败：{payload}")
    return payload.get("data", {}).get("node") or {}


def _append_blocks(document_id: str, blocks: list[dict[str, Any]], token: str) -> None:
    pending: list[dict[str, Any]] = []

    def flush_pending() -> None:
        if not pending:
            return
        for index in range(0, len(pending), 20):
            _request_feishu_json(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                token,
                json={"children": pending[index:index + 20]},
                timeout=20,
            )
        pending.clear()

    for block in blocks:
        if block.get("_openclaw_kind") == NATIVE_TABLE_KIND:
            flush_pending()
            _append_native_table(document_id, token, block.get("rows") or [])
        else:
            pending.append(block)
    flush_pending()


def _replace_blocks(document_id: str, blocks: list[dict[str, Any]], token: str) -> None:
    children = _get_docx_children(document_id, document_id, token)
    while children:
        end_index = min(len(children), 20)
        _request_feishu_json(
            "DELETE",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
            token,
            params={"document_revision_id": -1},
            json={"start_index": 0, "end_index": end_index},
            timeout=30,
        )
        children = _get_docx_children(document_id, document_id, token)
    _append_blocks(document_id, blocks, token)


def _delete_root_children_from(document_id: str, token: str, start_index: int) -> None:
    children = _get_docx_children(document_id, document_id, token)
    if len(children) <= start_index:
        return
    _request_feishu_json(
        "DELETE",
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
        token,
        params={"document_revision_id": -1},
        json={"start_index": start_index, "end_index": len(children)},
        timeout=30,
    )


def _creation_doc_blocks(
    title: str,
    request: CreationRequest,
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    inspirations: list[RankedRecord],
    businesses: list[RankedRecord],
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    platform_fit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    report = _require_creator_report_for_render(draft, request)
    return [
        _heading(title),
        _heading("创作方案总览"),
        *_creator_overview_blocks(report, request, activities, draft),
        _heading("这条内容怎么拍"),
        *_creator_shooting_blocks(report, draft),
        _heading("这条内容怎么发"),
        *_creator_publish_blocks(report, draft),
        _heading("素材检查清单"),
        *_creator_material_blocks(report, draft),
        _heading("风险控制"),
        *_creator_risk_blocks(report, draft),
        _heading("脚本方案"),
        *_script_option_blocks(draft),
        _heading("证据附录"),
        *_evidence_appendix_blocks(activities, virals, inspirations, businesses, draft, validation, platform_fit=platform_fit),
    ]


def _shooting_execution_doc_blocks(
    title: str,
    request: Any,
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    media_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    goal = draft.get("shooting_goal") if isinstance(draft.get("shooting_goal"), dict) else {}
    pack = draft.get("publishing_pack") if isinstance(draft.get("publishing_pack"), dict) else {}
    return [
        _heading(title),
        _heading("分镜脚本"),
        _table_block(
            ["时间", "画面", "字幕/口播", "声音/拍摄注意"],
            draft.get("storyboard"),
            ["time", "visual", "caption_or_voice", "sound_or_note"],
        ),
        _heading("拍摄目标"),
        _paragraph(
            "\n".join(
                [
                    f"最终平台：{_text(goal.get('platform') or request.platform)}",
                    f"内容形态：{_text(goal.get('content_type') or request.content_type)}",
                    f"核心情绪：{_text(goal.get('core_emotion'))}",
                    f"必须成片的主线：{_text(goal.get('mainline') or request.shooting_goal)}",
                    f"交付物：{_text(goal.get('deliverable'))}",
                ]
            )
        ),
        _heading("路线图"),
        _table_block(
            ["时间段", "地点", "拍摄任务", "人员", "失败替代"],
            draft.get("route_map"),
            ["time_slot", "location", "shooting_task", "people", "backup"],
        ),
        _heading("必拍镜头清单"),
        _table_block(
            ["优先级", "地点", "人物", "动作", "景别", "参考", "用途", "补拍判断"],
            _display_shooting_priorities(draft.get("must_shot_list")),
            ["priority", "location", "people", "action", "shot_size", "reference", "usage", "reshoot_check"],
        ),
        _heading("分支方案"),
        _table_block(
            ["触发条件", "执行方案", "优先级"],
            _display_shooting_priorities(draft.get("branch_plans")),
            ["condition", "plan", "priority"],
        ),
        _heading("现场检查清单"),
        _paragraph("\n".join(f"- {_text(item)}" for item in _as_list(draft.get("onsite_checklist")) if _text(item)) or "待补充"),
        _heading("抽象化拆解口径"),
        _table_block(
            ["原始信号", "抽象后的任务层", "执行含义"],
            draft.get("abstraction_map"),
            ["source_signal", "task_layer", "execution_meaning"],
        ),
        _heading("发布包"),
        _subheading("作品标题"),
        _paragraph(
            "\n".join(
                f"标题 {index}：{_text(item)}"
                for index, item in enumerate(_as_list(pack.get("title_directions")), start=1)
                if _text(item)
            )
            or "待补充"
        ),
        _subheading("封面图方案"),
        _paragraph(_text(pack.get("cover_frame")) or "待补充"),
        _subheading("发布文案"),
        _paragraph(_text(pack.get("body_copy")) or "待补充"),
        _subheading("话题与互动"),
        _paragraph(
            "\n".join(
                [
                    f"话题标签：{_inline_list(pack.get('hashtags'))}",
                    f"评论区引导：{_text(pack.get('comment_prompt'))}",
                ]
            )
        ),
        _subheading("声音方案"),
        _paragraph(
            f"BGM 建议：{_text(pack.get('bgm_suggestion'))}"
        ),
        _heading("校验"),
        _paragraph(
            "\n".join(
                [
                    f"校验状态：{'通过' if validation.get('ok') else '待人工补充'}",
                    f"缺失字段：{_shooting_plan_field_labels(validation.get('missing'))}",
                    f"空列表字段：{_shooting_plan_field_labels(validation.get('empty_lists'))}",
                    f"上下文加载：{_loaded_context_line((media_context or {}).get('loaded'))}",
                ]
            )
        ),
        _heading("证据附录"),
        *_shooting_evidence_appendix_blocks(draft.get("evidence_appendix")),
    ]


def _loaded_context_line(loaded: Any) -> str:
    """把机器态的 loaded 字典翻译成中文；原始 JSON 不进用户文档。"""
    if not isinstance(loaded, dict) or not loaded:
        return "未加载账号上下文"
    labels = {
        "account_profile": "账号画像",
        "creator_profile": "达人档案",
        "recent_creations": "近期创作",
        "recent_reviews": "历史复盘",
        "conversation_context": "会话上下文",
    }
    parts: list[str] = []
    for key, value in loaded.items():
        label = labels.get(str(key))
        if label is None:
            parts.append(f"其他上下文{'已加载' if bool(value) else '未加载'}")
            continue
        if isinstance(value, bool):
            parts.append(f"{label}{'已加载' if value else '未加载'}")
        elif isinstance(value, int):
            parts.append(f"{label} {value} 条")
        else:
            parts.append(f"{label}：{value}")
    return "；".join(parts)


def _shooting_evidence_appendix_blocks(items: Any) -> list[dict[str, Any]]:
    rows = _as_list(items)
    if not rows:
        return [_paragraph("无补充证据。")]
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            blocks.append(_paragraph(f"{index}. {_text(item)}"))
            continue
        lines = [
            f"{index}. 来源：{_text(item.get('source'))}",
            f"来源状态：{_evidence_source_status_label(item.get('source_status'))}",
            f"可用证据：{_text(item.get('available_evidence'))}",
            f"采用理由：{_text(item.get('usage_reason'))}",
            f"风险：{_text(item.get('risk'))}",
        ]
        blocks.append(_paragraph("\n".join(line for line in lines if not line.endswith("："))))
    return blocks


def _shooting_plan_field_labels(fields: Any) -> str:
    return _inline_list(
        [SHOOTING_PLAN_FIELD_LABELS.get(_text(field), "其他项目") for field in _as_list(fields)]
    )


def _evidence_source_status_label(value: Any) -> str:
    raw_status = _text(value)
    return EVIDENCE_SOURCE_STATUS_LABELS.get(raw_status, raw_status)


def _creator_overview_blocks(
    report: dict[str, Any],
    request: CreationRequest,
    activities: list[RankedRecord],
    draft: dict[str, Any],
) -> list[dict[str, Any]]:
    overview = _section(report, "overview")
    backups = _backup_options(draft)
    lines = [
        f"推荐选题：{_text(overview['recommended_topic'])}",
        f"一句话核心：{_text(overview['core_sentence'])}",
        f"内容核心：{_content_core_summary(draft)}",
        f"平台：{_text(overview['platform'])}",
        f"内容类型：{_text(overview['content_type'])}",
        f"适合参与的活动：{_text(overview['suitable_activity'])}",
        f"是否强烈建议参与活动：{_text(overview['strongly_recommend_activity'])}",
        f"最大风险：{_text(overview['biggest_risk'])}",
    ]
    blocks = [_paragraph("\n".join(lines))]
    if backups:
        backup_lines = ["备选方向（只作备选，不展开成完整稿）："]
        backup_lines.extend(f"- {item}" for item in backups[:2])
        blocks.append(_paragraph("\n".join(backup_lines)))
    return blocks


def _creator_shooting_blocks(report: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    opening = _section(report, "opening_3s")
    spine = _section(report, "mainline")
    blocks = [
        _heading("1. 前 3 秒"),
        _paragraph(
            "\n".join(
                [
                    f"0-0.5 秒画面：{_text(opening['visual_0_0_5'])}",
                    f"0.5-3 秒字幕/口播：{_text(opening['caption_or_voice_0_5_3'])}",
                    f"不能这样开头：{_text(opening['do_not_open_like_this'])}",
                ]
            )
        ),
        _heading("2. 视频主线"),
        _paragraph(
            "\n".join(
                [
                    f"冲突：{_text(spine['conflict'])}",
                    f"证据：{_text(spine['evidence'])}",
                    f"情绪回收：{_text(spine['emotional_payoff'])}",
                    f"观众共鸣点：{_text(spine['audience_resonance'])}",
                ]
            )
        ),
    ]
    if _script_options(draft):
        blocks.extend(
            [
                _heading("3. 分镜脚本"),
                _paragraph("完整分镜脚本见下方「脚本方案」区；每个候选方案各保留一张原生分镜表，优先执行推荐方案。"),
            ]
        )
    else:
        blocks.extend([_heading("3. 分镜脚本"), _storyboard_table_block(report)])
    return blocks


def _creator_publish_blocks(report: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    pack = _section(report, "publishing_pack")
    lines = [
        f"标题 1：{_text(pack['title_1'])}",
        f"标题 2：{_text(pack['title_2'])}",
        f"封面字：{_text(pack['cover_text'])}",
        f"正文文案：{_text(pack['body_copy'])}",
        f"话题：{_inline_list(pack['hashtags'])}",
        f"置顶评论：{_text(pack['pinned_comment'])}",
        f"评论区引导问题：{_inline_list(pack['comment_prompt'])}",
        f"发布后 1 小时动作：{_text(pack.get('first_hour_action'))}",
    ]
    return [_paragraph("\n".join(line for line in lines if line.split("：", 1)[-1].strip()))]


def _creator_material_blocks(report: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    checklist = _section(report, "material_checklist")
    lines = [
        f"必须有：{_inline_list(checklist['must_have'])}",
        f"有更好：{_inline_list(checklist['better_to_have'])}",
        f"没有也能补救：{_inline_list(checklist['can_rescue_without'])}",
        f"不能虚构：{_inline_list(checklist['must_not_fabricate'])}",
    ]
    return [_paragraph("\n".join(lines))]


def _creator_risk_blocks(report: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for item in report["risk_controls"]:
        lines.append(f"{_text(item['condition'])}：{_text(item['rewrite_or_action'])}")
    return [_paragraph("\n".join(lines))]


def _script_option_blocks(draft: dict[str, Any]) -> list[dict[str, Any]]:
    options = _script_options(draft)
    if not options:
        return [_paragraph("无完整脚本方案。")]
    recommended_id = str(draft.get("recommended_option_id") or "").strip()
    blocks: list[dict[str, Any]] = [
        _paragraph("以下方案均来自同一次创意请求，保留在同一个创作文档内；优先执行推荐方案，其余作为可切换方向。")
    ]
    for index, option in enumerate(options[:5], 1):
        title = _text(option.get("title") or option.get("angle") or f"方案 {index}")
        suffix = "（推荐）" if str(option.get("option_id") or "").strip() == recommended_id else ""
        blocks.append(_heading(f"方案 {index}{suffix}：{title}"))
        blocks.append(_paragraph(_script_option_summary(option)))
        storyboard_rows = _script_option_storyboard_rows(option)
        if len(storyboard_rows) > 1:
            blocks.append(_heading(f"方案 {index} 分镜脚本"))
            blocks.append({"_openclaw_kind": NATIVE_TABLE_KIND, "rows": storyboard_rows})
    return blocks


def _script_options(draft: dict[str, Any]) -> list[dict[str, Any]]:
    options = draft.get("script_options") if isinstance(draft.get("script_options"), list) else []
    return [item for item in options if isinstance(item, dict)]


def _option_score_reason_lines(draft: dict[str, Any]) -> list[str]:
    """评分与理由只出现在证据附录；执行区与方案正文不再渲染论证。"""
    recommended_id = str(draft.get("recommended_option_id") or "").strip()
    lines: list[str] = []
    for index, option in enumerate(_script_options(draft)[:5], 1):
        score = option.get("score")
        reason = _text(option.get("score_reason"))
        suffix = "（推荐）" if str(option.get("option_id") or "").strip() == recommended_id else ""
        if reason:
            lines.append(f"方案{index}{suffix}：{score}分，评分理由：{reason}")
        else:
            lines.append(f"方案{index}{suffix}：{score}分")
    return lines


def _option_score_summary(draft: dict[str, Any]) -> str:
    recommended_id = str(draft.get("recommended_option_id") or "").strip()
    parts: list[str] = []
    for index, option in enumerate(_script_options(draft)[:5], 1):
        score = option.get("score")
        suffix = "推荐" if str(option.get("option_id") or "").strip() == recommended_id else ""
        gate = "高分" if isinstance(score, int) and score > 90 else "未达90"
        label = f"方案{index}"
        detail = " / ".join(item for item in (suffix, gate) if item)
        parts.append(f"{label}：{score}分（{detail}）" if detail else f"{label}：{score}分")
    return "；".join(parts)


def _script_option_summary(option: dict[str, Any]) -> str:
    # 执行信息在前；评分与选择论证不进入方案正文，统一收进证据附录。
    lines = [
        f"执行角度：{_text(option.get('angle'))}",
        f"开场钩子：{_text(option.get('hook_3s'))}",
        f"成片文案：{_text(option.get('final_copy'))}",
    ]
    voiceover = _text(option.get("voiceover"))
    subtitles = _inline_list(option.get("subtitles"))
    if voiceover:
        lines.append(f"口播：{voiceover}")
    if subtitles:
        lines.append(f"字幕：{subtitles}")
    image_script = _inline_list(option.get("image_script") or option.get("carousel"))
    if image_script:
        lines.append(f"图文页：{image_script}")
    lines.extend(
        [
            f"话题：{_inline_list(option.get('tags'))}",
            f"拍摄清单：{_inline_list(option.get('production_checklist'))}",
            f"发布后验证：{_inline_list(option.get('review_plan'))}",
            f"风险处理：{_inline_list(option.get('risks_or_missing_info'))}",
        ]
    )
    return "\n".join(line for line in lines if line.split("：", 1)[-1].strip())


def _script_option_storyboard(option: dict[str, Any]) -> str:
    rows = _script_option_storyboard_rows(option)
    lines: list[str] = []
    for row in rows[1:]:
        lines.append(f"{row[0]}：{' / '.join(item for item in row[1:] if item)}")
    return "\n".join(lines)


def _script_option_storyboard_rows(option: dict[str, Any]) -> list[list[str]]:
    storyboard = option.get("storyboard") if isinstance(option.get("storyboard"), list) else []
    table_rows = [["时间", "画面", "字幕/口播", "声音/拍摄注意"]]
    for index, raw in enumerate(storyboard[:12], 1):
        if isinstance(raw, dict):
            row_time = _text(raw.get("time") or raw.get("scene") or f"镜头 {index}")
            visual = _text(raw.get("visual"))
            subtitle = _text(raw.get("subtitle") or raw.get("caption") or raw.get("voiceover"))
            sound = _text(raw.get("sound"))
            note = _text(raw.get("shooting_note") or raw.get("note"))
            table_rows.append([
                _table_cell(row_time),
                _table_cell(visual or row_time),
                _table_cell(subtitle),
                _table_cell("\n".join(item for item in (sound, note) if item)),
            ])
            continue
        text = _text(raw)
        if not text:
            continue
        time_label, detail = _split_storyboard_text(text, index)
        table_rows.append([
            _table_cell(time_label),
            _table_cell(detail),
            "",
            "",
        ])
    return table_rows


def _split_storyboard_text(text: str, index: int) -> tuple[str, str]:
    normalized = str(text or "").strip()
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?(?:-[0-9]+(?:\.[0-9]+)?)?s?)\s+(.+)$", normalized)
    if match:
        return match.group(1), match.group(2)
    return f"镜头 {index}", normalized


def _evidence_appendix_blocks(
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    inspirations: list[RankedRecord],
    businesses: list[RankedRecord],
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    platform_fit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    recommended = _recommended_option(draft)
    blocks = [
        _heading("素材 brief 与来源映射"),
        _paragraph(_usable_material_appendix(draft, recommended)),
        _heading("匹配活动"),
        _paragraph(_activity_appendix(activities[:3], recommended)),
        _heading("爆款参考"),
        _paragraph(_reference_appendix(virals[:3], recommended.get("viral_reference_reason") or _compact_text(draft.get("viral_reference") or {}), label="可迁移结构")),
        _heading("创作灵感"),
        _paragraph(_reference_appendix(inspirations[:3], recommended.get("inspiration_reference_reason") or _compact_text(draft.get("inspiration_reference") or {}), label="落地位置")),
        _heading("商务信息"),
        _paragraph(_business_appendix(businesses[:3])),
        _heading("评分和 record_id"),
        _paragraph(_score_id_appendix(activities, virals, inspirations, businesses, draft, validation, platform_fit=platform_fit)),
    ]
    return blocks


def _content_core_summary(draft: dict[str, Any]) -> str:
    core = draft.get("content_core") if isinstance(draft.get("content_core"), dict) else {}
    parts = [
        _text(core.get("content_promise")),
        _text(core.get("viewer_problem")),
        _text(core.get("specific_scene")),
        _text(core.get("memorable_point")),
    ]
    return "；".join(item for item in parts if item)


def _usable_material_appendix(draft: dict[str, Any], option: dict[str, Any]) -> str:
    brief = draft.get("usable_material_brief") if isinstance(draft.get("usable_material_brief"), dict) else {}
    lines = [
        f"执行 brief：{_compact_text(brief.get('execution_brief') or '')}",
        f"来源映射：{_compact_text(brief.get('source_mapping') or '')}",
        f"使用边界：{_compact_text(brief.get('usage_boundaries') or '')}",
        f"活动机器字段：{_text(option.get('activity_fit_reason'))}",
        f"爆款机器字段：{_text(option.get('viral_reference_reason'))}",
        f"灵感机器字段：{_text(option.get('inspiration_reference_reason'))}",
    ]
    return "\n".join(line for line in lines if line.split("：", 1)[-1].strip())


def _recommended_option(draft: dict[str, Any]) -> dict[str, Any]:
    options = draft.get("script_options") if isinstance(draft.get("script_options"), list) else []
    recommended_id = str(draft.get("recommended_option_id") or "").strip()
    for option in options:
        if isinstance(option, dict) and str(option.get("option_id") or "").strip() == recommended_id:
            return option
    return options[0] if options and isinstance(options[0], dict) else {}


def _backup_options(draft: dict[str, Any]) -> list[str]:
    recommended_id = str(draft.get("recommended_option_id") or "").strip()
    backups = []
    for option in draft.get("script_options") or []:
        if not isinstance(option, dict) or str(option.get("option_id") or "").strip() == recommended_id:
            continue
        title = str(option.get("title") or option.get("angle") or "").strip()
        if title:
            backups.append(title)
    return backups[:2]


def _storyboard_table_block(report: dict[str, Any]) -> dict[str, Any]:
    return {"_openclaw_kind": NATIVE_TABLE_KIND, "rows": _storyboard_table_rows(report)}


def _storyboard_table_rows(report: dict[str, Any]) -> list[list[str]]:
    rows = _section(report, "storyboard")
    table_rows = [["时间", "画面", "字幕/口播", "声音/拍摄注意"]]
    for index, row in enumerate(rows[:12], 1):
        row_time = _text(row["time"])
        visual = _text(row["visual"])
        subtitle = _text(row["subtitle"])
        sound = _text(row["sound"])
        note = _text(row["shooting_note"])
        table_rows.append([
            _table_cell(row_time),
            _table_cell(visual),
            _table_cell(subtitle),
            _table_cell("\n".join(item for item in (sound, note) if item)),
        ])
    return table_rows


def _activity_appendix(items: list[RankedRecord], option: dict[str, Any]) -> str:
    if not items:
        return "无匹配活动。"
    reason = str(option.get("activity_fit_reason") or "").strip()
    lines = []
    for item in items:
        record = item.record
        direction = _first_line(record.direction)
        lines.append(
            "\n".join(
                line
                for line in (
                    f"- {record.title or record.topic or record.source_record_id}",
                    f"  选择/放弃理由：{reason or _inline_list(item.reasons)}",
                    f"  推荐子方向：{direction}",
                    f"  record_id：{record.source_record_id}",
                    f"  返稿链接：{record.submission_link}",
                )
                if not line.endswith("：")
            )
        )
    return "\n".join(lines)


def _reference_appendix(items: list[RankedRecord], reason: str, *, label: str) -> str:
    if not items:
        return "无匹配参考。"
    lines = []
    for item in items:
        record = item.record
        title = record.title or record.topic or record.source_record_id
        extra = _insight_card_reference_lines(record)
        lines.append(
            "\n".join(
                [
                    f"- {title}",
                    f"  {label}：{reason or _inline_list(item.reasons)}",
                    f"  record_id：{record.source_record_id}",
                    *extra,
                ]
            )
        )
    return "\n".join(lines)


def _insight_card_reference_lines(record: Any) -> list[str]:
    if getattr(record, "source_table", "") != "Obsidian:人性洞察库":
        return []
    detail = getattr(record, "detail_json", None) if isinstance(getattr(record, "detail_json", None), dict) else {}
    return [
        "  reference_type：insight-card reference",
        f"  card_path：{_text(detail.get('insight_card_path'))}",
        f"  card_status：{_text(detail.get('insight_card_status') or getattr(record, 'status', ''))}",
        f"  evidence_boundary：{_text(detail.get('evidence_boundary') or 'public_content_only')}",
        f"  risk_boundary：{_text(detail.get('risk_boundary') or '未标注')}",
    ]


def _business_appendix(items: list[RankedRecord]) -> str:
    if not items:
        return "无商务信息。"
    return "\n".join(f"- {item.record.title or item.record.source_record_id}；record_id：{item.record.source_record_id}" for item in items)


def _score_id_appendix(
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    inspirations: list[RankedRecord],
    businesses: list[RankedRecord],
    draft: dict[str, Any],
    validation: dict[str, Any],
    *,
    platform_fit: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"推荐方案 id：{draft.get('recommended_option_id') or ''}",
        f"候选方案分数：{', '.join(str(item.get('score')) for item in draft.get('script_options') or [] if isinstance(item, dict))}",
        *_option_score_reason_lines(draft),
        f"活动 record_id：{', '.join(item.record.source_record_id for item in activities)}",
        f"爆款 record_id：{', '.join(item.record.source_record_id for item in virals)}",
        f"灵感 record_id：{', '.join(item.record.source_record_id for item in inspirations)}",
        f"商务 record_id：{', '.join(item.record.source_record_id for item in businesses)}",
        *_score_summary_lines(activities, virals, businesses, inspirations=inspirations),
        f"平台规则校验：{_validation_summary(validation)}",
        f"平台机制版本：{_compact_text((platform_fit or {}).get('platform_mechanism_version') or '')}",
    ]
    return "\n".join(line for line in lines if not line.endswith("："))


def _score_summary_lines(
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    businesses: list[RankedRecord],
    *,
    inspirations: list[RankedRecord] | None = None,
) -> list[str]:
    groups = (
        ("活动匹配分", activities),
        ("爆款匹配分", virals),
        ("灵感匹配分", inspirations or []),
        ("商务匹配分", businesses),
    )
    lines: list[str] = []
    for label, items in groups:
        if not items:
            continue
        summary = "；".join(
            f"{item.record.source_record_id or item.record.title or 'unknown'}：{item.score}"
            for item in items[:5]
        )
        if summary:
            lines.append(f"{label}：{summary}")
    return lines


def _section(report: dict[str, Any], key: str) -> Any:
    return report.get(key) if isinstance(report.get(key), (dict, list)) else {}


def _require_creator_report_for_render(draft: dict[str, Any], request: CreationRequest) -> dict[str, Any]:
    report = draft.get("creator_report")
    if not isinstance(report, dict):
        raise ValueError("creator_report 必须是 object")
    required_sections = {
        "overview": dict,
        "opening_3s": dict,
        "mainline": dict,
        "storyboard": list,
        "publishing_pack": dict,
        "material_checklist": dict,
        "risk_controls": list,
        "evidence_appendix": dict,
    }
    for section, expected_type in required_sections.items():
        if not isinstance(report.get(section), expected_type):
            raise ValueError(f"creator_report.{section} 必须是 {expected_type.__name__}")
    _require_keys(report["overview"], "creator_report.overview", ("recommended_topic", "core_sentence", "platform", "content_type", "suitable_activity", "strongly_recommend_activity", "biggest_risk"))
    if str(report["overview"].get("platform") or "").strip() != request.platform:
        raise ValueError(f"creator_report.overview.platform 必须等于 {request.platform}")
    if str(report["overview"].get("content_type") or "").strip() != request.content_type:
        raise ValueError(f"creator_report.overview.content_type 必须等于 {request.content_type}")
    _require_keys(report["opening_3s"], "creator_report.opening_3s", ("visual_0_0_5", "caption_or_voice_0_5_3", "do_not_open_like_this"))
    _require_keys(report["mainline"], "creator_report.mainline", ("conflict", "evidence", "emotional_payoff", "audience_resonance"))
    _require_keys(report["publishing_pack"], "creator_report.publishing_pack", ("title_1", "title_2", "cover_text", "body_copy", "hashtags", "pinned_comment", "comment_prompt"))
    _require_keys(report["material_checklist"], "creator_report.material_checklist", ("must_have", "better_to_have", "can_rescue_without", "must_not_fabricate"))
    for index, row in enumerate(report["storyboard"], 1):
        if not isinstance(row, dict):
            raise ValueError(f"creator_report.storyboard[{index}] 必须是 object")
        _require_keys(row, f"creator_report.storyboard[{index}]", ("time", "visual", "subtitle", "sound", "shooting_note"))
    for index, item in enumerate(report["risk_controls"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"creator_report.risk_controls[{index}] 必须是 object")
        _require_keys(item, f"creator_report.risk_controls[{index}]", ("condition", "rewrite_or_action"))
    return report


def _require_keys(data: dict[str, Any], path: str, keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValueError(f"{path} 缺少字段：{missing}")


def _table_block(headers: list[str], rows: Any, keys: list[str]) -> dict[str, Any]:
    table_rows = [headers]
    for row in _as_list(rows):
        if isinstance(row, dict):
            table_rows.append([_table_cell(row.get(key, "")) for key in keys])
        else:
            table_rows.append([_table_cell(row), *["" for _ in keys[1:]]])
    if len(table_rows) == 1:
        table_rows.append(["待补充", *["" for _ in headers[1:]]])
    return {"_openclaw_kind": NATIVE_TABLE_KIND, "rows": table_rows}


def _display_shooting_priorities(rows: Any) -> list[Any]:
    display_rows: list[Any] = []
    for row in _as_list(rows):
        if not isinstance(row, dict):
            display_rows.append(row)
            continue
        display_row = dict(row)
        raw_priority = _text(row.get("priority"))
        display_row["priority"] = SHOOTING_PRIORITY_LABELS.get(raw_priority, raw_priority)
        display_rows.append(display_row)
    return display_rows


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _text(value: Any) -> str:
    return _compact_text(value).strip()


def _one_line(value: Any) -> str:
    return _text(value).replace("\n", " ")[:260]


def _table_cell(value: Any) -> str:
    return _text(value)[:900]


def _inline_list(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_one_line(item).strip(" #") for item in value if _one_line(item))
    return _one_line(value)


def _first_line(value: Any) -> str:
    text = _compact_text(value)
    return next((line.strip("- ").strip() for line in text.splitlines() if line.strip()), "")


def _heading(text: str) -> dict[str, Any]:
    return {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": text[:500]}}]}}


def _subheading(text: str) -> dict[str, Any]:
    return {"block_type": 5, "heading3": {"elements": [{"text_run": {"content": text[:500]}}]}}


def _paragraph(text: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": str(text)[:1800]}}]}}


def _request_feishu_json(method: str, path: str, token: str, **kwargs: Any) -> dict[str, Any]:
    resp = requests.request(method, f"{FEISHU_BASE}{path}", headers=feishu_headers(token), **kwargs)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"飞书文档写入失败：{payload}")
    return payload


def _append_native_table(document_id: str, token: str, rows: list[list[str]]) -> None:
    chunks = _table_chunks(rows)
    ensure_docx_tables_write_budget(chunks)
    for chunk in chunks:
        _append_native_table_chunk(document_id, token, chunk)


def _table_chunks(rows: list[list[str]]) -> list[list[list[str]]]:
    return chunk_docx_table_rows(rows)


def _append_native_table_chunk(document_id: str, token: str, rows: list[list[str]]) -> None:
    if not rows:
        return
    row_count = len(rows)
    column_count = max(len(row) for row in rows)
    validate_docx_table_create_shape(row_count, column_count)
    ensure_docx_table_write_budget(rows)
    start_index = len(_get_docx_children(document_id, document_id, token))
    try:
        payload = _request_feishu_json(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={"children": [{"block_type": 31, "table": {"property": {"row_size": row_count, "column_size": column_count}}}], "index": -1},
            timeout=30,
        )
        table_block = _find_created_table(payload)
        time.sleep(1.2)
        table_id = str(table_block.get("block_id") or "")
        expected = row_count * column_count
        cell_ids = _extract_table_cell_ids(table_block, expected)
        if len(cell_ids) < expected and table_id:
            hydrated = _get_docx_block(document_id, table_id, token)
            cell_ids = _extract_table_cell_ids(hydrated, expected)
        if len(cell_ids) < expected and table_id:
            children = _get_docx_children(document_id, table_id, token)
            cell_ids = [_extract_block_id(item) for item in children]
            cell_ids = [item for item in cell_ids if item]
        if len(cell_ids) < expected:
            raise RuntimeError(f"飞书表格 cell id 不足：expected={expected} got={len(cell_ids)} table_id={table_id}")
        for row_index, row in enumerate(rows):
            for column_index in range(column_count):
                text = row[column_index] if column_index < len(row) else ""
                _append_cell_text(document_id, token, cell_ids[row_index * column_count + column_index], text)
    except Exception:
        _delete_root_children_from(document_id, token, start_index)
        raise


def _find_created_table(payload: dict[str, Any]) -> dict[str, Any]:
    children = payload.get("data", {}).get("children") or payload.get("data", {}).get("items") or []
    for child in children:
        if isinstance(child, dict) and child.get("block_type") == 31:
            return child
    return {}


def _extract_block_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("block_id") or item.get("id") or "")
    return ""


def _extract_table_cell_ids(table_block: dict[str, Any], expected: int) -> list[str]:
    table = table_block.get("table") if isinstance(table_block, dict) else {}
    candidates: list[Any] = []
    if isinstance(table, dict):
        candidates.extend(table.get("cells") or [])
    candidates.extend(table_block.get("children") or [])
    ids = [_extract_block_id(item) for item in candidates]
    ids = [item for item in ids if item]
    return ids[:expected] if len(ids) >= expected else ids


def _get_docx_block(document_id: str, block_id: str, token: str) -> dict[str, Any]:
    payload = _request_feishu_json("GET", f"/docx/v1/documents/{document_id}/blocks/{block_id}", token, timeout=30)
    return payload.get("data", {}).get("block") or payload.get("data", {})


def _get_docx_children(document_id: str, block_id: str, token: str) -> list[dict[str, Any]]:
    payload = _request_feishu_json(
        "GET",
        f"/docx/v1/documents/{document_id}/blocks/{block_id}/children",
        token,
        params={"document_revision_id": -1},
        timeout=30,
    )
    return payload.get("data", {}).get("items") or payload.get("data", {}).get("children") or []


def _append_cell_text(document_id: str, token: str, cell_id: str, text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    blocks = [_paragraph(line[:900]) for line in cleaned.splitlines() if line.strip()]
    if not blocks:
        return
    _request_feishu_json(
        "POST",
        f"/docx/v1/documents/{document_id}/blocks/{cell_id}/children",
        token,
        json={"children": blocks, "index": -1},
        timeout=30,
    )
    time.sleep(FEISHU_DOC_WRITE_SLEEP_SEC)


def _score_payload(
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    businesses: list[RankedRecord] | None = None,
    *,
    inspirations: list[RankedRecord] | None = None,
) -> dict[str, Any]:
    businesses = businesses or []
    inspirations = inspirations or []
    def serialize(item: RankedRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_id": item.record.source_record_id,
            "score": item.score,
            "score_scale": item.score_scale,
            "reasons": item.reasons,
        }
        if item.raw_score is not None:
            payload["raw_score"] = item.raw_score
        if isinstance(item.reasons, dict) and item.reasons.get("LLM选择原因"):
            payload["selection_reason"] = item.reasons.get("LLM选择原因")
        return payload

    return {
        "activity": [serialize(item) for item in activities],
        "viral": [serialize(item) for item in virals],
        "inspiration": [serialize(item) for item in inspirations],
        "business": [serialize(item) for item in businesses],
    }


def _top_score(items: list[RankedRecord]) -> float | None:
    if not items:
        return None
    return float(max(item.score for item in items))


def _score_summary(score_payload: dict[str, Any]) -> str:
    labels = {
        "activity": "活动",
        "viral": "爆款",
        "inspiration": "灵感",
        "business": "商务",
    }
    lines: list[str] = []
    for key, label in labels.items():
        items = score_payload.get(key) or []
        if not items:
            continue
        top = items[0]
        reasons = _reason_summary(top.get("reasons") or {})
        lines.append(f"{label} {top.get('record_id', '')}：{top.get('score', '')}；{reasons}")
    return "\n".join(lines)


def _reason_summary(reasons: Any) -> str:
    if not isinstance(reasons, dict):
        return _compact_text(reasons)
    parts: list[str] = []
    for key, value in reasons.items():
        if key == "LLM语义分项":
            continue
        if key == "LLM选择原因":
            text = _compact_text(value)
            if text:
                parts.append(f"{key}：{text}")
            continue
        parts.append(f"{key}({value})")
    return "、".join(parts)


def _validation_summary(validation: dict[str, Any]) -> str:
    status = "通过" if validation.get("ok") else "未通过"
    issues = [
        str(item.get("message") or "").strip()
        for item in validation.get("issues", [])
        if isinstance(item, dict) and str(item.get("message") or "").strip()
    ]
    return f"{status}" + (f"：{'；'.join(issues)}" if issues else "")


def _compact_text(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if item in (None, "", []):
                continue
            items.append(f"{key}：{_compact_text(item)}")
        return "\n".join(items)
    if isinstance(value, list):
        return "\n".join(f"- {_compact_text(item)}" for item in value if item not in (None, "", []))
    return str(value).strip()


def _creation_summary(request: CreationRequest, activities: list[RankedRecord], virals: list[RankedRecord]) -> str:
    return f"{request.platform} {request.content_type}｜{request.track}｜{request.topic}｜活动 {len(activities)} 条｜爆款参考 {len(virals)} 条"


def _creation_relation_id(request: CreationRequest) -> str:
    raw = "|".join([request.platform, request.content_type, request.track, request.topic, request.publish_time])
    return "creation:" + str(abs(hash(raw)))


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
