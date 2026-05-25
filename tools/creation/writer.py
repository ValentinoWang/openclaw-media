from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

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
from common.standard_fields import normalize_standard_fields, select_fields_for_write, standard_field_specs

from .matcher import RankedRecord
from .request_parser import CreationRequest


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
    "关联商务ID": 1,
    "关联商务链接": 15,
    "账号": 1,
    "素材来源": 1,
    "定位分析JSON": 1,
    "发布链接": 15,
    "复盘状态": 1,
    "参考爆款ID": 1,
    "参考灵感ID": 1,
    "参考灵感文档链接": 15,
    "参考拆解文档链接": 15,
    "参考创作-再创文档链接": 15,
    "创作文档链接": 15,
    "匹配分数JSON": 1,
    "标题校验": 1,
    "Tags校验": 1,
    "平台规则校验": 1,
    "失败原因": 1,
    "详情JSON": 1,
}

CREATION_RECORD_FIELD_SPECS = standard_field_specs(LEGACY_CREATION_RECORD_FIELD_SPECS)


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
    document_id, node_token = _create_doc(title, token)
    blocks = _creation_doc_blocks(title, request, activities, virals, inspirations or [], businesses or [], draft, validation, platform_fit=platform_fit)
    _append_blocks(document_id, blocks, token)
    if node_token:
        return f"https://tcnwueberajc.feishu.cn/wiki/{node_token}"
    return f"https://tcnwueberajc.feishu.cn/docx/{document_id}"


def write_creation_record(
    request: CreationRequest,
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    doc_link: str,
    validation: dict[str, Any],
    *,
    businesses: list[RankedRecord] | None = None,
    inspirations: list[RankedRecord] | None = None,
    record_table_url: str = "",
    extra_details: dict[str, Any] | None = None,
) -> str:
    load_default_env_files()
    bitable_url = record_table_url or os.getenv("MEDIA_OS_CREATION_TASKS_URL", "")
    if not bitable_url:
        return ""
    token = feishu_tenant_access_token()
    app_token, table_id, token = feishu_bitable_refs(bitable_url, token)
    feishu_ensure_fields(app_token, table_id, token, CREATION_RECORD_FIELD_SPECS)
    field_types = feishu_field_types(app_token, table_id, token)
    activity_ids = [item.record.relation_id or item.record.source_record_id for item in activities]
    activity_links = [item.record.source_link for item in activities if item.record.source_link]
    viral_ids = [item.record.relation_id or item.record.source_record_id for item in virals]
    businesses = businesses or []
    inspirations = inspirations or []
    business_ids = [item.record.relation_id or item.record.source_record_id for item in businesses]
    business_links = [item.record.doc_links.get("brief") or item.record.doc_links.get("homepage") or item.record.source_link for item in businesses]
    inspiration_ids = [item.record.relation_id or item.record.source_record_id for item in inspirations]
    inspiration_links = [next((link for link in item.record.doc_links.values() if link), item.record.source_link) for item in inspirations]
    decomp_links = [item.record.doc_links.get("decomposition", "") for item in virals if item.record.doc_links.get("decomposition")]
    recreation_links = [item.record.doc_links.get("recreation", "") for item in virals if item.record.doc_links.get("recreation")]
    extra_details = extra_details or {}
    record_fields = {
        "标题": f"{request.content_type} - {request.topic}",
        "类型": "创作",
        "内容": _creation_summary(request, activities, virals),
        "状态": "已生成" if validation.get("ok") else "待修改",
        "关联ID": _creation_relation_id(request),
        "创建时间": _now_ms(),
        "更新时间": _now_ms(),
        "平台": request.platform,
        "内容类型": request.content_type,
        "赛道": request.track,
        "主题": request.topic,
        "关键词/标签": "、".join(request.keywords or []),
        "发布时间": request.publish_time,
        "关联活动ID": "、".join(activity_ids),
        "关联活动链接": activity_links[0] if activity_links else "",
        "关联商务ID": "、".join(business_ids),
        "关联商务链接": next((item for item in business_links if item), ""),
        "账号": request.account or str(extra_details.get("account") or ""),
        "素材来源": str(extra_details.get("material_source") or ""),
        "定位分析JSON": json.dumps(extra_details.get("positioning_analysis") or {}, ensure_ascii=False),
        "发布链接": str(extra_details.get("publish_url") or ""),
        "复盘状态": str(extra_details.get("review_status") or ""),
        "参考爆款ID": "、".join(viral_ids),
        "参考灵感ID": "、".join(inspiration_ids),
        "参考灵感文档链接": next((item for item in inspiration_links if item), ""),
        "参考拆解文档链接": decomp_links[0] if decomp_links else "",
        "参考创作-再创文档链接": recreation_links[0] if recreation_links else "",
        "创作文档链接": doc_link,
        "匹配分数JSON": json.dumps(_score_payload(activities, virals, businesses, inspirations=inspirations), ensure_ascii=False),
        "标题校验": "通过" if validation.get("title_ok", validation.get("ok")) else "未通过",
        "Tags校验": "通过" if validation.get("tags_ok", validation.get("ok")) else "未通过",
        "平台规则校验": "通过" if validation.get("ok") else "未通过",
        "失败原因": "; ".join(item.get("message", "") for item in validation.get("issues", []) if isinstance(item, dict)),
        "详情JSON": json.dumps({"request": request.to_dict(), "validation": validation, "extra": extra_details}, ensure_ascii=False),
    }
    normalized_fields = normalize_standard_fields(record_fields)
    fields = select_fields_for_write(record_fields, normalized_fields=normalized_fields)
    payload_fields = {}
    for key, value in fields.items():
        if key not in field_types or value in (None, "", []):
            continue
        coerced = feishu_coerce_value(value, field_types.get(key))
        if coerced in (None, "", []):
            continue
        payload_fields[key] = coerced
    if not payload_fields:
        return ""
    resp = requests.post(
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        headers=feishu_headers(token),
        json={"fields": payload_fields},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"写入创作记录表失败：{payload}")
    return str(payload.get("data", {}).get("record", {}).get("record_id") or "")


def _create_doc(title: str, token: str) -> tuple[str, str]:
    parent_node = os.getenv("FEISHU_CREATION_DOC_PARENT_NODE_TOKEN") or os.getenv("FEISHU_WIKI_PARENT_NODE_TOKEN", "QA0BwF5Yji0EvfkmOiOcBuMQnze")
    if parent_node:
        node = _get_wiki_node(parent_node, token)
        space_id = str(node.get("space_id") or "")
        if space_id:
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
            return str(created.get("obj_token") or ""), str(created.get("node_token") or "")
    body: dict[str, Any] = {"title": title}
    if folder_token := os.getenv("FEISHU_CREATION_DOC_FOLDER_TOKEN") or os.getenv("FEISHU_DOC_FOLDER_TOKEN"):
        body["folder_token"] = folder_token
    resp = requests.post(f"{FEISHU_BASE}/docx/v1/documents", headers=feishu_headers(token), json=body, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"创建创作文档失败：{payload}")
    return str(payload.get("data", {}).get("document", {}).get("document_id") or payload.get("data", {}).get("document_id") or ""), ""


def _get_wiki_node(node_token: str, token: str) -> dict[str, Any]:
    resp = requests.get(f"{FEISHU_BASE}/wiki/v2/spaces/get_node", params={"token": node_token}, headers=feishu_headers(token), timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取知识库父节点失败：{payload}")
    return payload.get("data", {}).get("node") or {}


def _append_blocks(document_id: str, blocks: list[dict[str, Any]], token: str) -> None:
    for index in range(0, len(blocks), 20):
        resp = requests.post(
            f"{FEISHU_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=feishu_headers(token),
            json={"children": blocks[index:index + 20]},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"写入创作文档失败：{payload}")


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
    return [
        _heading(title),
        _heading("一、创作信息"),
        _paragraph(f"平台：{request.platform}\n内容类型：{request.content_type}\n赛道：{request.track}\n主体：{request.topic}\n发布时间：{request.publish_time}\n用户补充想法：{request.user_idea or ''}"),
        _heading("二、匹配到的活动"),
        *_ranked_blocks(activities, empty="未匹配到可参与活动"),
        _heading("三、匹配到的爆款拆解"),
        *_ranked_blocks(virals, empty="未匹配到爆款拆解样本"),
        _heading("四、匹配到的创作灵感"),
        *_ranked_blocks(inspirations, empty="未匹配到创作灵感素材"),
        _heading("五、匹配到的商务信息"),
        *_ranked_blocks(businesses, empty="未匹配到相关商务记录"),
        _heading("六、选题拆解"),
        _paragraph(json.dumps(draft.get("topic_strategy") or {}, ensure_ascii=False, indent=2)),
        _heading("七、平台推荐拟合"),
        *_platform_fit_blocks(platform_fit or _draft_platform_fit(draft)),
        _heading("八、可迁移灵感"),
        *_list_blocks(draft.get("inspiration") or []),
        _heading("九、平台化初稿"),
        _paragraph(json.dumps(draft, ensure_ascii=False, indent=2)),
        _heading("十、平台规则校验"),
        _paragraph(json.dumps(validation, ensure_ascii=False, indent=2)),
        _heading("十一、参考关系"),
        _paragraph(json.dumps(_score_payload(activities, virals, businesses, inspirations=inspirations), ensure_ascii=False, indent=2)),
    ]


def _draft_platform_fit(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform_strategy": draft.get("platform_strategy") or {},
        "activity_strategy": draft.get("activity_strategy") or {},
        "traffic_hypothesis": draft.get("traffic_hypothesis") or {},
        "creation_reverse_plan": draft.get("creation_reverse_plan") or {},
        "validation_targets": draft.get("validation_targets") or {},
    }


def _platform_fit_blocks(platform_fit: dict[str, Any]) -> list[dict[str, Any]]:
    if not platform_fit:
        return [_paragraph("暂无平台推荐拟合结果")]
    meta = platform_fit.get("platform_fit_meta") or {}
    generation = platform_fit.get("generation") or {}
    fallback_used = bool(meta.get("fallback_used") or generation.get("fallback_used"))
    blocks = [
        _paragraph("元信息：\n" + json.dumps(meta or generation, ensure_ascii=False, indent=2)),
    ]
    if fallback_used:
        blocks.append(_paragraph("提示：本次平台推荐拟合由内置基线生成，未使用完整 LLM 拟合结果，仅作为保底参考。"))
    prediction = {
        "platform_strategy": platform_fit.get("platform_strategy") or {},
        "activity_strategy": platform_fit.get("activity_strategy") or {},
        "traffic_hypothesis": platform_fit.get("traffic_hypothesis") or {},
        "creation_reverse_plan": platform_fit.get("creation_reverse_plan") or {},
    }
    validation = {
        "validation_targets": platform_fit.get("validation_targets") or {},
        "post_publish_correction": platform_fit.get("post_publish_correction") or {},
    }
    blocks.append(_paragraph("【创作前预测】\n" + json.dumps(prediction, ensure_ascii=False, indent=2)))
    blocks.append(_paragraph("【发布后验证】\n" + json.dumps(validation, ensure_ascii=False, indent=2)))
    return blocks


def _ranked_blocks(items: list[RankedRecord], *, empty: str) -> list[dict[str, Any]]:
    if not items:
        return [_paragraph(empty)]
    blocks = []
    for index, item in enumerate(items, 1):
        record = item.record
        blocks.append(_paragraph(f"{index}. {record.title or record.topic or record.source_record_id}\n来源：{record.source_table}\n分数：{item.score}\n理由：{json.dumps(item.reasons, ensure_ascii=False)}\n链接：{record.source_link or record.doc_links.get('decomposition') or ''}"))
    return blocks


def _list_blocks(value: Any) -> list[dict[str, Any]]:
    if not value:
        return [_paragraph("暂无")]
    if isinstance(value, list):
        return [_paragraph(f"{index}. {item}") for index, item in enumerate(value, 1)]
    return [_paragraph(str(value))]


def _heading(text: str) -> dict[str, Any]:
    return {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": text[:500]}}]}}


def _paragraph(text: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": str(text)[:1800]}}]}}


def _score_payload(
    activities: list[RankedRecord],
    virals: list[RankedRecord],
    businesses: list[RankedRecord] | None = None,
    *,
    inspirations: list[RankedRecord] | None = None,
) -> dict[str, Any]:
    businesses = businesses or []
    inspirations = inspirations or []
    return {
        "activity": [{"record_id": item.record.source_record_id, "score": item.score, "reasons": item.reasons} for item in activities],
        "viral": [{"record_id": item.record.source_record_id, "score": item.score, "reasons": item.reasons} for item in virals],
        "inspiration": [{"record_id": item.record.source_record_id, "score": item.score, "reasons": item.reasons} for item in inspirations],
        "business": [{"record_id": item.record.source_record_id, "score": item.score, "reasons": item.reasons} for item in businesses],
    }


def _creation_summary(request: CreationRequest, activities: list[RankedRecord], virals: list[RankedRecord]) -> str:
    return f"{request.platform} {request.content_type}｜{request.track}｜{request.topic}｜活动 {len(activities)} 条｜爆款参考 {len(virals)} 条"


def _creation_relation_id(request: CreationRequest) -> str:
    raw = "|".join([request.platform, request.content_type, request.track, request.topic, request.publish_time])
    return "creation:" + str(abs(hash(raw)))


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
