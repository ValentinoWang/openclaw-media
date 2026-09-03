"""Hand written business seed for the static MediaClaw demo site.

Only content lives here: every payload is merged onto a skeleton instantiated
from the OpenAPI response schema by `generate_demo_dataset.py`, so a field that
the contract does not declare fails generation instead of reaching the browser.
The world described below is fictional demo material — no real creators,
tenants, credentials or URLs.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from demo_seed_admin import ADMIN_LIST_SIZES, ADMIN_PARAMETER_PAYLOADS, ADMIN_SEED

DEMO_NOW = "2026-09-02T10:00:00+08:00"
_NOW = datetime.fromisoformat(DEMO_NOW)


def ago(days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    return (_NOW - timedelta(days=days, hours=hours, minutes=minutes)).isoformat()


def ahead(days: int = 0, hours: int = 0) -> str:
    return (_NOW + timedelta(days=days, hours=hours)).isoformat()


# Demo world identifiers. Every id matches ^[A-Za-z0-9_-]{8,160}$ so the
# contract's PublicId pattern accepts it.
PROJECT_CAMERA = "proj_autumn_camera"
PROJECT_CITYWALK = "proj_citywalk_suzhou"
PROJECT_COFFEE = "proj_brand_coffee"
PROJECT_REVIEW = "proj_october_review"
PROJECT_ASSETS = "proj_asset_bank"

RUN_CAMERA = "run_autumn_camera_01"
RUN_CITYWALK = "run_citywalk_suzhou_02"
RUN_COFFEE = "run_coffee_brief_03"
RUN_DECONSTRUCT = "run_deconstruct_hotpot"
RUN_REVIEW = "run_october_review_05"

ARTIFACT_CREATION = "artifact_creation_camera"
ARTIFACT_DECISION = "artifact_decision_camera"
ARTIFACT_PUBLISHING = "artifact_publishing_citywalk"
ARTIFACT_REVIEW = "artifact_review_october"
ARTIFACT_ASSET_DIGEST = "artifact_asset_digest_autumn"
ARTIFACT_RESEARCH = "artifact_research_hotlist"
ARTIFACT_SUMMARY = "artifact_project_summary_camera"
EXPORT_CREATION_DOCX = "export_creation_camera_docx"

ACCOUNT_XHS = "account_xhs_xiaoman"
ACCOUNT_DOUYIN = "account_douyin_xiaoman"
ACCOUNT_BILIBILI = "account_bilibili_xiaoman"
ACCOUNT_WEIXIN = "account_weixin_xiaoman"

TRACK_CITYWALK = "track_city_walk"
TRACK_CAMERA = "track_camera_review"
TRACK_COFFEE = "track_coffee_shop"
TRACK_TRAVEL = "track_travel_vlog"
TRACK_LIFESTYLE = "track_lifestyle"

CREATOR_LUMI = "creator_lumi_street"
CREATOR_HEYE = "creator_heye_camera"
CREATOR_MOKA = "creator_moka_coffee"
CREATOR_QINGZHOU = "creator_qingzhou_travel"
CREATOR_XINYE = "creator_xinye_life"

ASSET_HOTPOT = "asset_hotpot_opening"
ASSET_CITY_NIGHT = "asset_city_night_broll"
ASSET_CAMERA_HANDS = "asset_camera_hands"
ASSET_COFFEE_POUR = "asset_coffee_pour"
ASSET_RIVER_WALK = "asset_river_walk"
ASSET_SUBWAY_LIGHT = "asset_subway_light"

DECISION_CAMERA = "decision_autumn_camera"
DECISION_CITYWALK = "decision_citywalk_route"
DECISION_COFFEE = "decision_coffee_brand"
DECISION_HOTPOT = "decision_hotpot_pattern"

PACKAGE_XHS = "package_xhs_autumn_camera"
PACKAGE_DOUYIN = "package_douyin_citywalk"
PACKAGE_BILIBILI = "package_bilibili_camera_long"

POST_XHS = "post_xhs_autumn_camera"
POST_DOUYIN = "post_douyin_citywalk"

REVIEW_XHS = "review_xhs_autumn_camera"
REVIEW_DOUYIN = "review_douyin_citywalk"

# The generator only fabricates array items when the seed does not supply them.
LIST_SIZES: dict[str, int] = {
    "listDecisionSignals.items": 0,
    "listAccountMetrics.items": 0,
    "listContentMetrics.items": 0,
    **ADMIN_LIST_SIZES,
}

# Operations whose behaviour is stateful and therefore implemented directly in
# `src/demo/demoBackend.ts` (task lifecycle, capability catalog, session).
BACKEND_OWNED_OPERATIONS = frozenset(
    {
        "getMediaSession",
        "listMediaCapabilities",
        "matchMediaCapability",
        "listMediaTasks",
        "getDocumentRevision",
        "getMediaTask",
        "createMediaTask",
        "confirmMediaTask",
        "cancelMediaTask",
        "listMediaTaskEvents",
        "createMediaUpload",
    }
)

# Word pools for the fields the seed leaves to the generator.
WORD_POOLS: dict[str, list[str]] = {
    "_fallback": ["示例内容", "演示数据", "占位说明"],
    # 契约把 schemaVersion 声明成普通字符串，但页面会严格校验它的取值。
    "schemaVersion": ["media_web_business_pages_v2"],
    "title": ["秋日相机测评脚本", "城市漫步选题", "咖啡探店脚本"],
    "platform": ["小红书", "抖音", "B站", "视频号"],
    "status": ["进行中", "待确认", "已完成"],
    "reason": ["演示环境自动生成", "示例说明"],
    "label": ["证据快照", "素材来源", "复盘记录"],
    "kind": ["截图", "链接", "文档"],
    "name": ["演示条目"],
    "service": ["内容生产服务", "素材解析服务", "复盘服务"],
    "model": ["deepseek-chat", "gpt-image-2", "claude-sonnet"],
    "unit": ["千 token", "张", "次"],
    "currency": ["CNY"],
    "role": ["对标账号", "同赛道创作者"],
    "action": ["更新准入策略", "补发余额", "冻结租户"],
    "summary": ["示例摘要"],
    "description": ["演示用描述文案"],
    "displayName": ["演示用户"],
    "accountName": ["演示账号"],
    "mediaType": ["video", "image"],
    "contentType": ["图文", "短视频", "长视频"],
    "entrypoint": ["Web 工作台", "飞书标签", "本机 Agent"],
    "trackName": ["城市漫步", "相机测评", "咖啡探店"],
    "sourceLabel": ["公开内容采集", "本机导入", "商单素材"],
    "qualityStatus": ["verified", "partial"],
    "materialStatus": ["已下载", "待下载"],
    "evidenceQuality": ["verified", "partial"],
    "humanDecision": ["保留选题", "调整封面"],
    "modelSuggestion": ["建议保留开头 3 秒的强钩子"],
    "detail": ["演示环境返回的示例说明"],
    "affiliateCode": ["MEDIACLAW-DEMO"],
    "metricKey": ["曝光量", "互动量", "涨粉数"],
    "targetType": ["租户", "用户", "账单"],
    "creatorRole": ["对标账号"],
    "authorizationScope": ["站内二次剪辑授权"],
    "product": ["秋季限定礼盒"],
    "brand": ["演示品牌"],
    "operation": ["read"],
    "remoteDocumentVersion": ["v12"],
    "errorCode": [""],
    "templateVersion": ["v3"],
    "rendererVersion": ["docx-2026.08"],
    "planCode": ["balance_starter"],
    "batchId": ["batch_demo_0001"],
    "filename": ["演示素材.mp4"],
    "reasonSummary": ["演示环境示例原因"],
}


def _stage_counts() -> list[dict[str, Any]]:
    return [
        {"stage": "research", "count": 2},
        {"stage": "assets", "count": 3},
        {"stage": "decision", "count": 2},
        {"stage": "creation", "count": 4},
        {"stage": "publishing", "count": 2},
        {"stage": "review", "count": 3},
    ]


def _evidence(label: str, *, quality: str = "verified", days: int = 2) -> dict[str, Any]:
    # 用 sha256 而不是内置 hash()：后者按进程加盐，会让生成结果每次都不同。
    reference = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:6], 16) % 9000 + 1000
    return {
        "kind": "证据快照",
        "label": label,
        "publicUrl": f"https://demo.mediaclaw.example/evidence/{reference}",
        "capturedAt": ago(days=days),
        "qualityStatus": quality,
    }


def _paragraph(block_id: str, text: str) -> dict[str, Any]:
    return {"id": block_id, "type": "paragraph", "attrs": {}, "content": [{"type": "text", "text": text, "marks": []}]}


def _heading(block_id: str, text: str, level: int = 2) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": f"heading_{level}",
        "attrs": {},
        "content": [{"type": "text", "text": text, "marks": []}],
    }


def _bullets(block_id: str, texts: list[str]) -> dict[str, Any]:
    return {
        "id": block_id,
        "type": "bullet_list",
        "attrs": {},
        "items": [
            {
                "id": f"{block_id}_item{index}",
                "content": [{"type": "text", "text": text, "marks": []}],
                "children": [],
            }
            for index, text in enumerate(texts, start=1)
        ],
    }


CREATION_DOCUMENT_BLOCKS = [
    _heading("blk_camera_title", "秋日相机测评：X100VI 城市实拍脚本", 1),
    _paragraph("blk_camera_intro", "面向想买第一台随身相机的城市通勤人群，用一条 3 分钟视频回答「值不值得背出门」。"),
    _heading("blk_camera_hook", "开场钩子（0-8 秒）"),
    _bullets(
        "blk_camera_hook_list",
        [
            "第一句台词：把相机塞进外套口袋，走进早高峰地铁。",
            "画面：手持特写 + 站台灯光扫过机身，禁止使用商单素材。",
            "字幕：一台不换镜头的相机，能拍完整个秋天吗？",
        ],
    ),
    _heading("blk_camera_body", "主体结构（8-150 秒）"),
    {
        "id": "blk_camera_table",
        "type": "table",
        "attrs": {"semanticPurpose": "storyboard", "headerRowCount": 1},
        "rows": [
            {
                "id": "blk_camera_table_r1",
                "cells": [
                    {"id": "blk_camera_table_r1c1", "content": [{"type": "text", "text": "段落", "marks": ["bold"]}]},
                    {"id": "blk_camera_table_r1c2", "content": [{"type": "text", "text": "画面", "marks": ["bold"]}]},
                    {"id": "blk_camera_table_r1c3", "content": [{"type": "text", "text": "证据", "marks": ["bold"]}]},
                ],
            },
            {
                "id": "blk_camera_table_r2",
                "cells": [
                    {"id": "blk_camera_table_r2c1", "content": [{"type": "text", "text": "通勤实拍", "marks": []}]},
                    {"id": "blk_camera_table_r2c2", "content": [{"type": "text", "text": "地铁换乘通道逆光人流", "marks": []}]},
                    {"id": "blk_camera_table_r2c3", "content": [{"type": "text", "text": "素材库：地铁光影", "marks": []}]},
                ],
            },
            {
                "id": "blk_camera_table_r3",
                "cells": [
                    {"id": "blk_camera_table_r3c1", "content": [{"type": "text", "text": "夜景对比", "marks": []}]},
                    {"id": "blk_camera_table_r3c2", "content": [{"type": "text", "text": "同机位手机 / 相机双画面", "marks": []}]},
                    {"id": "blk_camera_table_r3c3", "content": [{"type": "text", "text": "素材库：城市夜景空镜", "marks": []}]},
                ],
            },
        ],
    },
    {
        "id": "blk_camera_callout",
        "type": "callout",
        "attrs": {"semanticTone": "warning"},
        "content": [{"type": "text", "text": "结尾不得出现未获授权的品牌口播；商单版本走 Campaigns 单独交付。", "marks": []}],
    },
    {
        "id": "blk_camera_snapshot",
        "type": "data_snapshot",
        "attrs": {
            "semanticPurpose": "metric_snapshot",
            "publicObjectId": POST_XHS,
            "sourceRevision": 4,
            "capturedAt": ago(days=1),
            "displayFields": {"24 小时曝光": 18422, "互动率": "6.1%", "涨粉": 213},
        },
    },
]

REVIEW_DOCUMENT_BLOCKS = [
    _heading("blk_review_title", "10 月账号复盘：城市漫步与相机测评双线", 1),
    _paragraph("blk_review_intro", "本月共发布 7 条内容，其中 3 条进入平台推荐池，商单转化 1 单。"),
    _bullets(
        "blk_review_points",
        [
            "涨粉主要来自相机测评线，但互动率最高的是城市漫步线。",
            "封面文字超过 12 字的内容，完播率平均下降 9 个百分点。",
            "夜景素材复用率最高，建议下月补拍 2 组雨天空镜。",
        ],
    ),
    {
        "id": "blk_review_callout",
        "type": "callout",
        "attrs": {"semanticTone": "info"},
        "content": [{"type": "text", "text": "下月重点：把相机测评的钩子模板迁移到城市漫步线做 A/B。", "marks": []}],
    },
]


def _document_body(artifact_id: str, project_id: str, kind: str, blocks: list[dict[str, Any]], revision: int) -> dict[str, Any]:
    return {
        "data": {
            "artifact": {
                "publicArtifactId": artifact_id,
                "publicProjectId": project_id,
                "artifactKind": kind,
                "workspaceMode": "personal_web",
                "bodyAuthority": "internal",
                "currentRevision": revision,
                "updatedAt": ago(hours=6),
            },
            "revision": {
                "publicArtifactId": artifact_id,
                "artifactKind": kind,
                "bodyAuthority": "internal",
                "revision": revision,
                "baseRevision": revision - 1,
                "state": "ready",
                "remoteDocumentVersion": None,
                "body": {"schemaVersion": "media.document.body.v1", "blocks": blocks},
                "createdAt": ago(days=1),
                "updatedAt": ago(hours=6),
            },
        }
    }


SEED: dict[str, Any] = {
    "getAuthEntryState": {
        "schemaVersion": "media_auth_entry_state_v1",
        "mode": "personal",
        "state": "none",
        "entry": None,
        "fallback": "password",
    },
    "getDashboard": {
        "summary": {
            "counts": {
                "contentProjects": 5,
                "runs": 12,
                "assets": 46,
                "tracks": 5,
                "creators": 18,
                "publishedPosts": 9,
                "reviews": 6,
            },
            "contentProjectStages": _stage_counts(),
            "pendingDecisions": 2,
            "pendingPublishing": 1,
            "pendingReviews": 2,
            "taskSummary": {"queued": 1, "running": 1, "needsAttention": 2, "failed": 0},
            "coverage": {"known": 38, "unknown": 6, "unavailable": 2},
            "generatedAt": ago(minutes=12),
            "revision": 87,
        }
    },
    "listContentProjects": {
        "items": [
            {
                "publicProjectId": PROJECT_CAMERA,
                "title": "秋日相机测评：X100VI 城市实拍",
                "workspaceMode": "personal_web",
                "stage": "creation",
                "status": "active",
                "artifactCounts": {"创作文档": 2, "决策简报": 1, "素材摘要": 1},
                "updatedAt": ago(hours=3),
            },
            {
                "publicProjectId": PROJECT_CITYWALK,
                "title": "城市漫步·苏州河支线",
                "workspaceMode": "personal_web",
                "stage": "publishing",
                "status": "active",
                "artifactCounts": {"创作文档": 1, "发布包": 1},
                "updatedAt": ago(hours=9),
            },
            {
                "publicProjectId": PROJECT_COFFEE,
                "title": "三顿半秋季联名商单",
                "workspaceMode": "personal_web",
                "stage": "decision",
                "status": "active",
                "artifactCounts": {"决策简报": 1, "商单简报": 1},
                "updatedAt": ago(days=1, hours=2),
            },
            {
                "publicProjectId": PROJECT_REVIEW,
                "title": "10 月复盘与账号学习",
                "workspaceMode": "personal_web",
                "stage": "review",
                "status": "active",
                "artifactCounts": {"复盘报告": 1},
                "updatedAt": ago(days=2),
            },
            {
                "publicProjectId": PROJECT_ASSETS,
                "title": "素材银行：秋季空镜补拍",
                "workspaceMode": "personal_web",
                "stage": "assets",
                "status": "paused",
                "artifactCounts": {"素材摘要": 2},
                "updatedAt": ago(days=3),
            },
        ],
        "nextCursor": None,
        "revision": 87,
    },
    "listProjectArtifacts": {
        "items": [
            {
                "publicArtifactId": ARTIFACT_CREATION,
                "publicProjectId": PROJECT_CAMERA,
                "artifactType": "creation_document",
                "displayName": "秋日相机测评脚本 v4",
                "bodyAuthority": "internal",
                "currentRevision": 4,
                "syncStatus": "not_applicable",
                "updatedAt": ago(hours=6),
                "allowedActions": ["read", "edit", "export"],
            },
            {
                "publicArtifactId": ARTIFACT_DECISION,
                "publicProjectId": PROJECT_CAMERA,
                "artifactType": "decision_brief",
                "displayName": "选题决策简报：为什么是 X100VI",
                "bodyAuthority": "internal",
                "currentRevision": 2,
                "syncStatus": "not_applicable",
                "updatedAt": ago(days=1),
                "allowedActions": ["read", "export"],
            },
            {
                "publicArtifactId": ARTIFACT_ASSET_DIGEST,
                "publicProjectId": PROJECT_CAMERA,
                "artifactType": "asset_digest",
                "displayName": "秋季空镜素材摘要",
                "bodyAuthority": "internal",
                "currentRevision": 1,
                "syncStatus": "not_applicable",
                "updatedAt": ago(days=2),
                "allowedActions": ["read"],
            },
        ],
        "nextCursor": None,
        "revision": 41,
    },
    "getDocumentBody": _document_body(ARTIFACT_CREATION, PROJECT_CAMERA, "creation_document", CREATION_DOCUMENT_BLOCKS, 4),
    "listArtifactSyncBatches": {"items": [], "nextCursor": None, "revision": 3},
    "listRuns": {
        "items": [
            {
                "publicRunId": RUN_CAMERA,
                "title": "秋日相机测评：X100VI 城市实拍",
                "platform": "小红书",
                "contentType": "图文",
                "trackName": "相机测评",
                "entrypoint": "Web 工作台",
                "status": "succeeded",
                "availableSections": ["sources", "decisions", "outputs"],
                "publicProjectId": PROJECT_CAMERA,
                "createdAt": ago(days=2),
                "updatedAt": ago(hours=3),
                "revision": 4,
            },
            {
                "publicRunId": RUN_CITYWALK,
                "title": "城市漫步·苏州河支线脚本",
                "platform": "抖音",
                "contentType": "短视频",
                "trackName": "城市漫步",
                "entrypoint": "飞书标签",
                "status": "awaiting_confirmation",
                "availableSections": ["sources", "outputs"],
                "publicProjectId": PROJECT_CITYWALK,
                "createdAt": ago(days=4),
                "updatedAt": ago(hours=9),
                "revision": 6,
            },
            {
                "publicRunId": RUN_COFFEE,
                "title": "三顿半联名商单脚本初稿",
                "platform": "小红书",
                "contentType": "图文",
                "trackName": "咖啡探店",
                "entrypoint": "Web 工作台",
                "status": "awaiting_confirmation",
                "availableSections": ["sources", "decisions"],
                "publicProjectId": PROJECT_COFFEE,
                "createdAt": ago(days=1, hours=6),
                "updatedAt": ago(days=1, hours=2),
                "revision": 2,
            },
            {
                "publicRunId": RUN_DECONSTRUCT,
                "title": "爆款拆解：冬季火锅开场结构",
                "platform": "抖音",
                "contentType": "短视频",
                "trackName": "生活方式",
                "entrypoint": "飞书标签",
                "status": "succeeded",
                "availableSections": ["sources", "decisions", "outputs"],
                "publicProjectId": None,
                "createdAt": ago(days=6),
                "updatedAt": ago(days=5),
                "revision": 3,
            },
            {
                "publicRunId": RUN_REVIEW,
                "title": "10 月账号复盘",
                "platform": "小红书",
                "contentType": "图文",
                "trackName": "相机测评",
                "entrypoint": "Web 工作台",
                "status": "generating",
                "availableSections": ["outputs"],
                "publicProjectId": PROJECT_REVIEW,
                "createdAt": ago(days=3),
                "updatedAt": ago(days=2),
                "revision": 2,
            },
        ],
        "nextCursor": None,
        "revision": 52,
    },
    "getRun": {
        "run": {
            "publicRunId": RUN_CAMERA,
            "title": "秋日相机测评：X100VI 城市实拍",
            "platform": "小红书",
            "contentType": "图文",
            "trackName": "相机测评",
            "entrypoint": "Web 工作台",
            "status": "succeeded",
            "availableSections": ["sources", "decisions", "outputs"],
            "publicProjectId": PROJECT_CAMERA,
            "createdAt": ago(days=2),
            "updatedAt": ago(hours=3),
            "revision": 4,
        }
    },
    "getRunSources": {
        "section": {
            "publicRunId": RUN_CAMERA,
            "items": [
                {"来源": "小红书", "标题": "秋天第一台随身相机怎么选", "互动量": 12800, "采集时间": ago(days=3), "质量": "verified"},
                {"来源": "抖音", "标题": "地铁通勤 vlog 的三种开场", "互动量": 24100, "采集时间": ago(days=4), "质量": "partial"},
                {"来源": "本机素材", "标题": "城市夜景空镜 12 条", "互动量": 0, "采集时间": ago(days=2), "质量": "verified"},
            ],
            "sourceKinds": ["公开内容", "本机素材"],
            "evidenceRefs": [_evidence("公开内容采集快照"), _evidence("素材清单", quality="partial", days=2)],
            "revision": 4,
        }
    },
    "getRunDecisions": {
        "section": {
            "publicRunId": RUN_CAMERA,
            "decisionItems": [
                {
                    "publicDecisionId": DECISION_CAMERA,
                    "candidateTitle": "以「口袋里的秋天」作为主标题",
                    "candidateType": "material",
                    "platform": "小红书",
                    "trackName": "相机测评",
                    "decisionStatus": "confirmed",
                    "evidenceCount": 4,
                    "humanConfirmedAt": ago(days=1),
                    "updatedAt": ago(days=1),
                },
                {
                    "publicDecisionId": DECISION_HOTPOT,
                    "candidateTitle": "复用火锅开场的三段式钩子",
                    "candidateType": "pattern",
                    "platform": "抖音",
                    "trackName": "相机测评",
                    "decisionStatus": "recommended",
                    "evidenceCount": 2,
                    "humanConfirmedAt": None,
                    "updatedAt": ago(hours=20),
                },
            ],
            "humanState": "已确认主标题，钩子结构待确认",
            "revision": 4,
        }
    },
    "getRunOutputs": {
        "section": {
            "publicRunId": RUN_CAMERA,
            "outputVariants": [
                {"版本": "v4 剪辑交接版", "状态": "可编辑", "时长": "3 分 08 秒", "更新时间": ago(hours=3)},
                {"版本": "v3 初稿", "状态": "已归档", "时长": "3 分 24 秒", "更新时间": ago(days=1)},
            ],
            "artifactSummaries": [
                {
                    "publicArtifactId": ARTIFACT_CREATION,
                    "publicProjectId": PROJECT_CAMERA,
                    "artifactType": "creation_document",
                    "displayName": "秋日相机测评脚本 v4",
                    "bodyAuthority": "internal",
                    "currentRevision": 4,
                    "syncStatus": "not_applicable",
                    "updatedAt": ago(hours=6),
                    "allowedActions": ["read", "edit", "export"],
                }
            ],
            "verificationReports": [
                {"检查项": "素材授权", "结果": "通过", "说明": "全部素材来自本机拍摄"},
                {"检查项": "平台规则", "结果": "待复核", "说明": "标题含品牌词，需要确认是否触发商业内容标记"},
            ],
            "revision": 4,
        }
    },
    "listBusinessOpportunities": {
        "items": [
            {
                "publicOpportunityId": "opportunity_coffee_autumn",
                "brand": "三顿半（演示）",
                "product": "秋季限定礼盒",
                "platform": "小红书",
                "contentType": "图文",
                "validFrom": ago(days=5),
                "validUntil": ahead(days=20),
                "authorizationScope": "站内二次剪辑授权，不含线下投放",
                "status": "履约中",
            },
            {
                "publicOpportunityId": "opportunity_camera_brand",
                "brand": "光影相机（演示）",
                "product": "随身相机 X100VI",
                "platform": "B站",
                "contentType": "长视频",
                "validFrom": ago(days=2),
                "validUntil": ahead(days=45),
                "authorizationScope": "全平台分发授权",
                "status": "报价确认中",
            },
            {
                "publicOpportunityId": "opportunity_travel_hotel",
                "brand": "云宿酒店（演示）",
                "product": "城市周末套餐",
                "platform": "抖音",
                "contentType": "短视频",
                "validFrom": ahead(days=7),
                "validUntil": ahead(days=60),
                "authorizationScope": "仅限账号主页与话题页",
                "status": "待排期",
            },
        ],
        "nextCursor": None,
        "revision": 12,
    },
    "listTracks": {
        "items": [
            {
                "publicTrackId": TRACK_CITYWALK,
                "name": "城市漫步",
                "description": "以步行路线串联城市细节，主打通勤人群的周末替代方案。",
                "parentPublicTrackId": None,
                "status": "主赛道",
                "platforms": ["小红书", "抖音"],
                "aliases": ["citywalk", "城市徒步"],
                "artifactCount": 14,
                "updatedAt": ago(hours=8),
            },
            {
                "publicTrackId": TRACK_CAMERA,
                "name": "相机测评",
                "description": "随身相机与镜头的真实使用体验，强调通勤与旅行场景。",
                "parentPublicTrackId": None,
                "status": "主赛道",
                "platforms": ["小红书", "B站"],
                "aliases": ["camera", "器材"],
                "artifactCount": 21,
                "updatedAt": ago(hours=3),
            },
            {
                "publicTrackId": TRACK_COFFEE,
                "name": "咖啡探店",
                "description": "商单密度最高的支线，主要承接品牌联名。",
                "parentPublicTrackId": TRACK_CITYWALK,
                "status": "支线",
                "platforms": ["小红书"],
                "aliases": ["coffee"],
                "artifactCount": 9,
                "updatedAt": ago(days=1),
            },
            {
                "publicTrackId": TRACK_TRAVEL,
                "name": "旅行 Vlog",
                "description": "季度性内容，用于拉新与账号破圈。",
                "parentPublicTrackId": None,
                "status": "观察中",
                "platforms": ["抖音", "B站"],
                "aliases": ["travel"],
                "artifactCount": 6,
                "updatedAt": ago(days=4),
            },
            {
                "publicTrackId": TRACK_LIFESTYLE,
                "name": "生活方式",
                "description": "承接爆款拆解结论的实验赛道。",
                "parentPublicTrackId": None,
                "status": "实验",
                "platforms": ["抖音"],
                "aliases": ["lifestyle"],
                "artifactCount": 4,
                "updatedAt": ago(days=6),
            },
        ],
        "nextCursor": None,
        "revision": 31,
    },
    "listCreators": {
        "items": [
            {
                "publicCreatorId": CREATOR_LUMI,
                "accountName": "陆米在街头",
                "platform": "小红书",
                "creatorRole": "对标账号",
                "identityTags": ["城市摄影", "步行路线"],
                "expertiseDomains": ["城市漫步"],
                "profileUrl": "https://demo.mediaclaw.example/creators/lumi",
                "avatarUrl": None,
                "updatedAt": ago(days=1),
            },
            {
                "publicCreatorId": CREATOR_HEYE,
                "accountName": "禾也测评",
                "platform": "B站",
                "creatorRole": "对标账号",
                "identityTags": ["器材测评", "长视频"],
                "expertiseDomains": ["相机测评"],
                "profileUrl": "https://demo.mediaclaw.example/creators/heye",
                "avatarUrl": None,
                "updatedAt": ago(days=2),
            },
            {
                "publicCreatorId": CREATOR_MOKA,
                "accountName": "摩卡不加糖",
                "platform": "小红书",
                "creatorRole": "商单竞品",
                "identityTags": ["咖啡", "探店"],
                "expertiseDomains": ["咖啡探店"],
                "profileUrl": "https://demo.mediaclaw.example/creators/moka",
                "avatarUrl": None,
                "updatedAt": ago(days=3),
            },
            {
                "publicCreatorId": CREATOR_QINGZHOU,
                "accountName": "轻舟旅行日记",
                "platform": "抖音",
                "creatorRole": "破圈参考",
                "identityTags": ["旅行", "剧情化"],
                "expertiseDomains": ["旅行 Vlog"],
                "profileUrl": "https://demo.mediaclaw.example/creators/qingzhou",
                "avatarUrl": None,
                "updatedAt": ago(days=5),
            },
            {
                "publicCreatorId": CREATOR_XINYE,
                "accountName": "新野生活",
                "platform": "抖音",
                "creatorRole": "同赛道创作者",
                "identityTags": ["生活方式"],
                "expertiseDomains": ["生活方式"],
                "profileUrl": "https://demo.mediaclaw.example/creators/xinye",
                "avatarUrl": None,
                "updatedAt": ago(days=7),
            },
        ],
        "nextCursor": None,
        "revision": 24,
    },
    "listTrackRelationships": {
        "items": [
            {
                "publicRelationshipId": "relationship_citywalk_lumi",
                "revision": 3,
                "publicTrackId": TRACK_CITYWALK,
                "publicCreatorId": CREATOR_LUMI,
                "role": "对标账号",
                "fitScore": 0.92,
                "fitReason": "路线选题与更新节奏最接近，封面语言可直接对照。",
                "status": "已确认",
                "lastEvaluatedAt": ago(days=1),
            },
            {
                "publicRelationshipId": "relationship_camera_heye",
                "revision": 2,
                "publicTrackId": TRACK_CAMERA,
                "publicCreatorId": CREATOR_HEYE,
                "role": "对标账号",
                "fitScore": 0.86,
                "fitReason": "同为随身相机测评，但长视频占比更高，可参考结构不参考时长。",
                "status": "已确认",
                "lastEvaluatedAt": ago(days=2),
            },
            {
                "publicRelationshipId": "relationship_coffee_moka",
                "revision": 1,
                "publicTrackId": TRACK_COFFEE,
                "publicCreatorId": CREATOR_MOKA,
                "role": "商单竞品",
                "fitScore": 0.71,
                "fitReason": "同期承接同品牌，需要避开同款拍摄地。",
                "status": "待确认",
                "lastEvaluatedAt": ago(days=3),
            },
            {
                "publicRelationshipId": "relationship_travel_qingzhou",
                "revision": 1,
                "publicTrackId": TRACK_TRAVEL,
                "publicCreatorId": CREATOR_QINGZHOU,
                "role": "破圈参考",
                "fitScore": 0.58,
                "fitReason": "剧情化程度高于本账号，仅参考选题不参考表达。",
                "status": "待确认",
                "lastEvaluatedAt": ago(days=6),
            },
        ],
        "nextCursor": None,
        "revision": 18,
    },
    "listOwnedAccounts": {
        "items": [
            {
                "publicAccountId": ACCOUNT_XHS,
                "platform": "小红书",
                "accountName": "小满在城市",
                "operationalStatus": "active",
                "responsiblePerson": "小满",
                "teamName": "个人工作室",
                "accountPositioning": "城市漫步 + 随身相机的通勤视角",
                "dataSource": "授权接口",
                "platformAccountId": "xhs_demo_88421",
                "profileUrl": "https://demo.mediaclaw.example/accounts/xhs",
                "avatarUrl": None,
                "publicTrackIds": [TRACK_CITYWALK, TRACK_CAMERA],
                "lastSyncedAt": ago(hours=2),
                "updatedAt": ago(hours=2),
            },
            {
                "publicAccountId": ACCOUNT_DOUYIN,
                "platform": "抖音",
                "accountName": "小满Vlog",
                "operationalStatus": "active",
                "responsiblePerson": "小满",
                "teamName": "个人工作室",
                "accountPositioning": "短视频版城市漫步，主打节奏与音乐",
                "dataSource": "人工录入",
                "platformAccountId": "dy_demo_20913",
                "profileUrl": "https://demo.mediaclaw.example/accounts/douyin",
                "avatarUrl": None,
                "publicTrackIds": [TRACK_CITYWALK, TRACK_LIFESTYLE],
                "lastSyncedAt": ago(hours=14),
                "updatedAt": ago(hours=14),
            },
            {
                "publicAccountId": ACCOUNT_BILIBILI,
                "platform": "B站",
                "accountName": "小满的器材柜",
                "operationalStatus": "paused",
                "responsiblePerson": "阿岚",
                "teamName": "外部剪辑",
                "accountPositioning": "长视频测评，季度更新",
                "dataSource": "人工录入",
                "platformAccountId": "bili_demo_5521",
                "profileUrl": "https://demo.mediaclaw.example/accounts/bilibili",
                "avatarUrl": None,
                "publicTrackIds": [TRACK_CAMERA],
                "lastSyncedAt": ago(days=9),
                "updatedAt": ago(days=9),
            },
            {
                "publicAccountId": ACCOUNT_WEIXIN,
                "platform": "视频号",
                "accountName": "小满在城市（视频号）",
                "operationalStatus": "disabled",
                "responsiblePerson": None,
                "teamName": None,
                "accountPositioning": "暂停运营，仅做内容同步",
                "dataSource": None,
                "platformAccountId": None,
                "profileUrl": None,
                "avatarUrl": None,
                "publicTrackIds": [],
                "lastSyncedAt": None,
                "updatedAt": ago(days=30),
            },
        ],
        "nextCursor": None,
        "revision": 27,
    },
    "getOwnedAccount": {
        "item": {
            "publicAccountId": ACCOUNT_XHS,
            "platform": "小红书",
            "accountName": "小满在城市",
            "operationalStatus": "active",
            "responsiblePerson": "小满",
            "teamName": "个人工作室",
            "accountPositioning": "城市漫步 + 随身相机的通勤视角",
            "dataSource": "授权接口",
            "platformAccountId": "xhs_demo_88421",
            "profileUrl": "https://demo.mediaclaw.example/accounts/xhs",
            "avatarUrl": None,
            "publicTrackIds": [TRACK_CITYWALK, TRACK_CAMERA],
            "lastSyncedAt": ago(hours=2),
            "updatedAt": ago(hours=2),
        }
    },
    "getAccountMonitor": {
        "status": "available",
        "publicAccountId": ACCOUNT_XHS,
        "accountName": "小满在城市",
        "platform": "小红书",
        "checkedAt": ago(hours=2),
        "detail": "最近 3 条内容均已回读到互动数据。",
        "enabled": True,
        "recentPostUrls": [
            "https://demo.mediaclaw.example/posts/xhs-autumn-camera",
            "https://demo.mediaclaw.example/posts/xhs-citywalk-suzhou",
        ],
        "recentPostLinkResults": [
            {
                "url": "https://demo.mediaclaw.example/posts/xhs-autumn-camera",
                "platform": "小红书",
                "kind": "post",
                "content_id": "xhs_demo_post_001",
                "canonical_url": "https://demo.mediaclaw.example/posts/xhs-autumn-camera",
            }
        ],
        "recentStatus": "已回读",
        "recentPostCount": 3,
        "recentTotalInteractions": 41230,
        "recentError": None,
        "recentReportSummary": "24 小时曝光 18422，互动率 6.1%，高于账号均值。",
    },
    "getAccountTrackStrategy": {
        "strategy": {
            "publicStrategyId": "strategy_xhs_autumn",
            "publicAccountId": ACCOUNT_XHS,
            "targetPublicTrackIds": [TRACK_CITYWALK, TRACK_CAMERA],
            "evidenceRefs": [_evidence("赛道占比统计"), _evidence("对标账号更新节奏", quality="partial", days=4)],
            "recommendations": [
                "把相机测评的钩子模板迁移到城市漫步线做 A/B。",
                "咖啡探店支线只承接商单，不再单独排期。",
                "视频号账号维持同步，不投入新内容。",
            ],
            "humanStatus": "confirmed",
            "revision": 5,
            "updatedAt": ago(days=1),
        }
    },
    "listAssets": {
        "items": [
            {
                "publicAssetId": ASSET_HOTPOT,
                "title": "火锅开场：三段式钩子参考",
                "mediaType": "video",
                "platform": "抖音",
                "sourceLabel": "公开内容采集",
                "platformHashtags": ["#冬季美食", "#开场"],
                "trackNames": ["生活方式"],
                "qualityStatus": "verified",
                "materialStatus": "已下载",
                "createdAt": ago(days=6),
                "usageCount": 3,
                "thumbnail": {"kind": "descriptor_only", "label": "本机素材，未上传原片", "durationSeconds": 42},
            },
            {
                "publicAssetId": ASSET_CITY_NIGHT,
                "title": "城市夜景空镜 12 条",
                "mediaType": "video",
                "platform": "本机",
                "sourceLabel": "本机导入",
                "platformHashtags": [],
                "trackNames": ["城市漫步", "相机测评"],
                "qualityStatus": "verified",
                "materialStatus": "已下载",
                "createdAt": ago(days=2),
                "usageCount": 5,
                "thumbnail": {"kind": "descriptor_only", "label": "12 段夜景素材，共 4 分 12 秒"},
            },
            {
                "publicAssetId": ASSET_CAMERA_HANDS,
                "title": "相机手持特写",
                "mediaType": "image",
                "platform": "本机",
                "sourceLabel": "本机导入",
                "platformHashtags": [],
                "trackNames": ["相机测评"],
                "qualityStatus": "verified",
                "materialStatus": "已下载",
                "createdAt": ago(days=2, hours=4),
                "usageCount": 2,
                "thumbnail": {"kind": "descriptor_only", "label": "静态图 6 张"},
            },
            {
                "publicAssetId": ASSET_COFFEE_POUR,
                "title": "咖啡注水慢镜",
                "mediaType": "video",
                "platform": "本机",
                "sourceLabel": "商单素材",
                "platformHashtags": ["#咖啡"],
                "trackNames": ["咖啡探店"],
                "qualityStatus": "partial",
                "materialStatus": "待下载",
                "createdAt": ago(days=1, hours=8),
                "usageCount": 0,
                "thumbnail": {"kind": "descriptor_only", "label": "品牌方提供，待确认授权范围"},
            },
            {
                "publicAssetId": ASSET_RIVER_WALK,
                "title": "苏州河步道跟拍",
                "mediaType": "video",
                "platform": "本机",
                "sourceLabel": "本机导入",
                "platformHashtags": [],
                "trackNames": ["城市漫步"],
                "qualityStatus": "verified",
                "materialStatus": "已下载",
                "createdAt": ago(days=4),
                "usageCount": 4,
                "thumbnail": {"kind": "descriptor_only", "label": "跟拍 3 段，共 2 分 05 秒"},
            },
            {
                "publicAssetId": ASSET_SUBWAY_LIGHT,
                "title": "地铁通道光影",
                "mediaType": "video",
                "platform": "本机",
                "sourceLabel": "本机导入",
                "platformHashtags": [],
                "trackNames": ["城市漫步", "相机测评"],
                "qualityStatus": "verified",
                "materialStatus": "已下载",
                "createdAt": ago(days=5),
                "usageCount": 6,
                "thumbnail": {"kind": "descriptor_only", "label": "逆光人流 5 段"},
            },
        ],
        "nextCursor": None,
        "revision": 63,
    },
    "getAsset": {
        "item": {
            "summary": {
                "publicAssetId": ASSET_HOTPOT,
                "title": "火锅开场：三段式钩子参考",
                "mediaType": "video",
                "platform": "抖音",
                "sourceLabel": "公开内容采集",
                "platformHashtags": ["#冬季美食", "#开场"],
                "trackNames": ["生活方式"],
                "qualityStatus": "verified",
                "materialStatus": "已下载",
                "createdAt": ago(days=6),
                "usageCount": 3,
                "thumbnail": {"kind": "descriptor_only", "label": "本机素材，未上传原片", "durationSeconds": 42},
            },
            "evidenceRefs": [_evidence("采集页面快照"), _evidence("互动数据回读", quality="partial", days=5)],
            "previewDescriptor": {"kind": "descriptor_only", "说明": "原始媒体保存在本机设备，控制面只接收描述信息。"},
            "deconstructions": [
                {"结构": "痛点前置", "秒数": "0-3", "说明": "用一句反问替代自我介绍"},
                {"结构": "冲突展示", "秒数": "3-9", "说明": "画面直接给出对比结果"},
                {"结构": "承诺兑现", "秒数": "9-18", "说明": "给出可复现的操作步骤"},
            ],
            "creativePatterns": [
                {"模式": "三段式钩子", "适配赛道": "城市漫步 / 相机测评", "复用次数": 3},
            ],
            "usageRefs": [RUN_CAMERA, RUN_DECONSTRUCT],
            "revision": 3,
        }
    },
    "listDecisions": {
        "items": [
            {
                "publicDecisionId": DECISION_CAMERA,
                "candidateTitle": "以「口袋里的秋天」作为主标题",
                "candidateType": "material",
                "platform": "小红书",
                "trackName": "相机测评",
                "decisionStatus": "confirmed",
                "evidenceCount": 4,
                "humanConfirmedAt": ago(days=1),
                "updatedAt": ago(days=1),
            },
            {
                "publicDecisionId": DECISION_CITYWALK,
                "candidateTitle": "苏州河支线改为夜拍路线",
                "candidateType": "activity",
                "platform": "抖音",
                "trackName": "城市漫步",
                "decisionStatus": "recommended",
                "evidenceCount": 3,
                "humanConfirmedAt": None,
                "updatedAt": ago(hours=10),
            },
            {
                "publicDecisionId": DECISION_COFFEE,
                "candidateTitle": "商单内容改为「一日两杯」结构",
                "candidateType": "business",
                "platform": "小红书",
                "trackName": "咖啡探店",
                "decisionStatus": "candidate",
                "evidenceCount": 2,
                "humanConfirmedAt": None,
                "updatedAt": ago(days=1, hours=2),
            },
            {
                "publicDecisionId": DECISION_HOTPOT,
                "candidateTitle": "复用火锅开场的三段式钩子",
                "candidateType": "pattern",
                "platform": "抖音",
                "trackName": "相机测评",
                "decisionStatus": "recommended",
                "evidenceCount": 2,
                "humanConfirmedAt": None,
                "updatedAt": ago(hours=20),
            },
            {
                "publicDecisionId": "decision_travel_reject",
                "candidateTitle": "十一假期跨城旅行专题",
                "candidateType": "activity",
                "platform": "抖音",
                "trackName": "旅行 Vlog",
                "decisionStatus": "rejected",
                "evidenceCount": 1,
                "humanConfirmedAt": ago(days=4),
                "updatedAt": ago(days=4),
            },
        ],
        "nextCursor": None,
        "revision": 44,
    },
    "getDecision": {
        "decision": {
            "publicDecisionId": DECISION_CITYWALK,
            "candidateTitle": "苏州河支线改为夜拍路线",
            "candidateType": "activity",
            "platform": "抖音",
            "trackName": "城市漫步",
            "decisionStatus": "recommended",
            "evidenceCount": 3,
            "humanConfirmedAt": None,
            "updatedAt": ago(hours=10),
        }
    },
    "listDecisionSignals": {
        "items": [
            {
                "publicSignalId": "signal_xhs_hotlist",
                "kind": "hotlist",
                "platform": "小红书",
                "title": "秋天的第一支 vlog",
                "rank": 3,
                "sourceUrl": "https://demo.mediaclaw.example/hotlist/xhs-autumn",
                "capturedAt": ago(hours=5),
                "qualityStatus": "verified",
            },
            {
                "publicSignalId": "signal_douyin_hotlist",
                "kind": "hotlist",
                "platform": "抖音",
                "title": "城市夜骑路线推荐",
                "rank": 7,
                "sourceUrl": "https://demo.mediaclaw.example/hotlist/douyin-night",
                "capturedAt": ago(hours=6),
                "qualityStatus": "verified",
            },
            {
                "publicSignalId": "signal_activity_coffee",
                "kind": "activity",
                "platform": "小红书",
                "title": "平台咖啡季征稿活动",
                "rank": 1,
                "sourceUrl": "https://demo.mediaclaw.example/activity/coffee-season",
                "capturedAt": ago(days=1),
                "qualityStatus": "partial",
            },
            {
                "publicSignalId": "signal_research_camera",
                "kind": "research",
                "platform": "B站",
                "title": "随身相机搜索热度环比上升 18%",
                "rank": 2,
                "sourceUrl": "https://demo.mediaclaw.example/research/camera-trend",
                "capturedAt": ago(days=2),
                "qualityStatus": "partial",
            },
        ],
        "nextCursor": None,
        "revision": 19,
    },
    "listPublishingPackages": {
        "items": [
            {
                "publicPackageId": PACKAGE_XHS,
                "publicRunId": RUN_CAMERA,
                "platform": "小红书",
                "contentFields": {
                    "标题": "口袋里的秋天：X100VI 通勤实拍",
                    "正文": "背了 14 天的随身相机，最后留下的三个理由。",
                    "话题": "#随身相机 #城市漫步 #通勤",
                    "封面": "地铁通道逆光人流",
                },
                "ruleChecks": [
                    {"检查项": "话题数量", "结果": "通过", "说明": "3 个，未超过平台上限"},
                    {"检查项": "商业内容标记", "结果": "待确认", "说明": "标题含品牌词，需人工判断"},
                ],
                "artifactDescriptor": {
                    "publicArtifactId": ARTIFACT_CREATION,
                    "publicProjectId": PROJECT_CAMERA,
                    "artifactType": "creation_document",
                    "displayName": "秋日相机测评脚本 v4",
                    "bodyAuthority": "internal",
                    "currentRevision": 4,
                    "syncStatus": "not_applicable",
                    "updatedAt": ago(hours=6),
                    "allowedActions": ["read", "export"],
                },
                "humanChecks": [
                    {"确认项": "封面已定稿", "状态": "已确认", "确认人": "小满"},
                    {"确认项": "商业内容标记", "状态": "待确认", "确认人": ""},
                ],
                "status": "checking",
                "revision": 3,
            },
            {
                "publicPackageId": PACKAGE_DOUYIN,
                "publicRunId": RUN_CITYWALK,
                "platform": "抖音",
                "contentFields": {
                    "标题": "苏州河夜拍路线，一小时走完",
                    "正文": "从武宁路桥走到外白渡桥的完整路线。",
                    "话题": "#城市漫步 #夜拍",
                    "封面": "河岸灯带",
                },
                "ruleChecks": [{"检查项": "时长", "结果": "通过", "说明": "58 秒，符合推荐区间"}],
                "artifactDescriptor": {
                    "publicArtifactId": ARTIFACT_PUBLISHING,
                    "publicProjectId": PROJECT_CITYWALK,
                    "artifactType": "publishing_package",
                    "displayName": "苏州河夜拍发布包",
                    "bodyAuthority": "internal",
                    "currentRevision": 2,
                    "syncStatus": "not_applicable",
                    "updatedAt": ago(hours=9),
                    "allowedActions": ["read", "export"],
                },
                "humanChecks": [{"确认项": "路线安全提示", "状态": "已确认", "确认人": "小满"}],
                "status": "ready",
                "revision": 2,
            },
            {
                "publicPackageId": PACKAGE_BILIBILI,
                "publicRunId": RUN_CAMERA,
                "platform": "B站",
                "contentFields": {
                    "标题": "随身相机长测：14 天通勤实拍",
                    "正文": "长视频版本，包含完整参数对比。",
                    "话题": "#器材测评",
                    "封面": "机身特写",
                },
                "ruleChecks": [{"检查项": "分区选择", "结果": "通过", "说明": "数码 - 摄影摄像"}],
                "artifactDescriptor": {
                    "publicArtifactId": ARTIFACT_CREATION,
                    "publicProjectId": PROJECT_CAMERA,
                    "artifactType": "creation_document",
                    "displayName": "秋日相机测评脚本 v4",
                    "bodyAuthority": "internal",
                    "currentRevision": 4,
                    "syncStatus": "not_applicable",
                    "updatedAt": ago(hours=6),
                    "allowedActions": ["read"],
                },
                "humanChecks": [{"确认项": "长视频剪辑交接", "状态": "待确认", "确认人": ""}],
                "status": "draft",
                "revision": 1,
            },
        ],
        "nextCursor": None,
        "revision": 22,
    },
    "getPublishedPost": {
        "publishedPost": {
            "publicPostId": POST_XHS,
            "publicPackageId": PACKAGE_XHS,
            "platform": "小红书",
            "publishedUrl": "https://demo.mediaclaw.example/posts/xhs-autumn-camera",
            "publishedAt": ago(days=1, hours=4),
            "recordedBy": "user",
            "evidenceQuality": "verified",
        }
    },
    "listReviews": {
        "items": [
            {
                "publicReviewId": REVIEW_XHS,
                "publicPostId": POST_XHS,
                "postTitle": "口袋里的秋天：X100VI 通勤实拍",
                "documentUrl": "https://demo.mediaclaw.example/documents/review-autumn",
                "platform": "小红书",
                "snapshot24h": "曝光 18422 · 互动 1124 · 涨粉 213",
                "snapshot7d": None,
                "evidenceQuality": "verified",
                "modelSuggestion": "开头 3 秒的反问是主要留存来源，建议沉淀为模板。",
                "humanDecision": None,
                "status": "awaiting_confirmation",
                "revision": 2,
            },
            {
                "publicReviewId": REVIEW_DOUYIN,
                "publicPostId": POST_DOUYIN,
                "postTitle": "苏州河夜拍路线，一小时走完",
                "documentUrl": None,
                "platform": "抖音",
                "snapshot24h": "曝光 96210 · 互动 5340 · 涨粉 486",
                "snapshot7d": "曝光 214800 · 互动 9120 · 涨粉 702",
                "evidenceQuality": "verified",
                "modelSuggestion": "完播率在 35 秒处明显下降，建议压缩中段路线讲解。",
                "humanDecision": "下条内容压缩中段",
                "status": "confirmed",
                "revision": 4,
            },
            {
                "publicReviewId": "review_bilibili_camera",
                "publicPostId": "post_bilibili_camera",
                "postTitle": "随身相机长测（B站版）",
                "documentUrl": None,
                "platform": "B站",
                "snapshot24h": None,
                "snapshot7d": None,
                "evidenceQuality": "unavailable",
                "modelSuggestion": None,
                "humanDecision": None,
                "status": "pending",
                "revision": 1,
            },
        ],
        "nextCursor": None,
        "revision": 16,
    },
    "getReviewsSummary": {
        "summary": {
            "reviewCount": 6,
            "pending24h": 1,
            "pending7d": 2,
            "confirmedCount": 3,
            "evidenceCoverage": 0.78,
            "generatedAt": ago(hours=4),
        }
    },
    "listContentMetrics": {
        "items": [
            {
                "publicSnapshotId": "snapshot_xhs_24h",
                "subjectType": "content",
                "publicSubjectId": POST_XHS,
                "reviewWindow": "24h",
                "metricKey": "曝光量",
                "metricValue": 18422,
                "unit": "次",
                "evidenceQuality": "verified",
                "collectedAt": ago(hours=6),
            },
            {
                "publicSnapshotId": "snapshot_xhs_24h_engage",
                "subjectType": "content",
                "publicSubjectId": POST_XHS,
                "reviewWindow": "24h",
                "metricKey": "互动量",
                "metricValue": 1124,
                "unit": "次",
                "evidenceQuality": "verified",
                "collectedAt": ago(hours=6),
            },
            {
                "publicSnapshotId": "snapshot_douyin_7d",
                "subjectType": "content",
                "publicSubjectId": POST_DOUYIN,
                "reviewWindow": "7d",
                "metricKey": "曝光量",
                "metricValue": 214800,
                "unit": "次",
                "evidenceQuality": "verified",
                "collectedAt": ago(days=1),
            },
        ],
        "nextCursor": None,
        "revision": 11,
    },
    "listAccountMetrics": {
        "items": [
            {
                "publicSnapshotId": "snapshot_account_xhs",
                "subjectType": "account",
                "publicSubjectId": ACCOUNT_XHS,
                "reviewWindow": "7d",
                "metricKey": "涨粉数",
                "metricValue": 913,
                "unit": "人",
                "evidenceQuality": "verified",
                "collectedAt": ago(hours=8),
            },
            {
                "publicSnapshotId": "snapshot_account_douyin",
                "subjectType": "account",
                "publicSubjectId": ACCOUNT_DOUYIN,
                "reviewWindow": "7d",
                "metricKey": "涨粉数",
                "metricValue": 1420,
                "unit": "人",
                "evidenceQuality": "partial",
                "collectedAt": ago(hours=20),
            },
        ],
        "nextCursor": None,
        "revision": 9,
    },
    "getBillingBalance": {"balance": {"available": "486.20", "currency": "CNY", "asOf": ago(minutes=30), "revision": 64}},
    "getBillingUsageSummary": {
        "summary": {
            "textQuantity": 1284.5,
            "imageQuantity": 36,
            "totalCharge": "213.80",
            "currency": "CNY",
            "from": ago(days=30),
            "to": ago(minutes=30),
            "revision": 64,
        }
    },
    "listBillingUsage": {
        "items": [
            {
                "publicUsageId": "usage_creation_0912",
                "kind": "text",
                "model": "deepseek-chat",
                "quantity": 128.4,
                "unit": "千 token",
                "charge": "12.84",
                "status": "succeeded",
                "createdAt": ago(hours=3),
            },
            {
                "publicUsageId": "usage_cover_0912",
                "kind": "image",
                "model": "gpt-image-2",
                "quantity": 4,
                "unit": "张",
                "charge": "6.00",
                "status": "succeeded",
                "createdAt": ago(hours=5),
            },
            {
                "publicUsageId": "usage_review_0911",
                "kind": "text",
                "model": "claude-sonnet",
                "quantity": 96.2,
                "unit": "千 token",
                "charge": "14.43",
                "status": "succeeded",
                "createdAt": ago(days=1),
            },
            {
                "publicUsageId": "usage_redeem_0910",
                "kind": "credit",
                "model": "余额充值",
                "quantity": 1,
                "unit": "次",
                "charge": "-300.00",
                "status": "succeeded",
                "createdAt": ago(days=2),
            },
            {
                "publicUsageId": "usage_compensate_0909",
                "kind": "compensation",
                "model": "deepseek-chat",
                "quantity": 12.5,
                "unit": "千 token",
                "charge": "-1.25",
                "status": "compensated",
                "createdAt": ago(days=3),
            },
            {
                "publicUsageId": "usage_pending_0908",
                "kind": "text",
                "model": "deepseek-chat",
                "quantity": 42.1,
                "unit": "千 token",
                "charge": "4.21",
                "status": "pending_reconciliation",
                "createdAt": ago(days=4),
            },
        ],
        "nextCursor": None,
        "revision": 64,
    },
    "listBillingBalancePacks": {
        "items": [
            {
                "balancePackCode": "balance_starter",
                "name": "入门包 · 100 元",
                "creditAmount": 100,
                "priceCny": "100.00",
                "currency": "CNY",
                "audience": "all",
                "productKind": "balance_pack",
                "purchaseAvailable": True,
                "purchaseUrl": "https://demo.mediaclaw.example/purchase/starter",
            },
            {
                "balancePackCode": "balance_creator",
                "name": "创作者包 · 300 元",
                "creditAmount": 330,
                "priceCny": "300.00",
                "currency": "CNY",
                "audience": "personal",
                "productKind": "balance_pack",
                "purchaseAvailable": True,
                "purchaseUrl": "https://demo.mediaclaw.example/purchase/creator",
            },
            {
                "balancePackCode": "balance_studio",
                "name": "工作室包 · 1000 元",
                "creditAmount": 1180,
                "priceCny": "1000.00",
                "currency": "CNY",
                "audience": "organization",
                "productKind": "balance_pack",
                "purchaseAvailable": False,
                "purchaseUrl": None,
            },
        ],
        "nextCursor": None,
        "revision": 8,
    },
    "getAffiliateProfile": {
        "profile": {
            "affiliateCode": "MEDIACLAW-DEMO-8842",
            "enabled": True,
            "quota": 20,
            "used": 6,
            "expiresAt": ahead(days=90),
            "revision": 7,
        }
    },
    "listInvitees": {
        "items": [
            {"publicUserId": "user_invitee_alan", "displayName": "阿岚（外部剪辑）", "status": "已加入", "joinedAt": ago(days=12)},
            {"publicUserId": "user_invitee_zhou", "displayName": "周周（选题助理）", "status": "已加入", "joinedAt": ago(days=20)},
            {"publicUserId": "user_invitee_lin", "displayName": "林同学（实习）", "status": "待激活", "joinedAt": ago(days=2)},
            {"publicUserId": "user_invitee_mo", "displayName": "默默（摄影）", "status": "已加入", "joinedAt": ago(days=45)},
        ],
        "nextCursor": None,
        "revision": 7,
    },
    "createDocumentExport": {
        "data": {
            "publicExportId": EXPORT_CREATION_DOCX,
            "publicArtifactId": ARTIFACT_CREATION,
            "revision": 4,
            "format": "docx",
            "state": "queued",
            "templateVersion": "v3",
            "rendererVersion": "docx-2026.08",
            "createdAt": ago(minutes=1),
            "updatedAt": ago(minutes=1),
        }
    },
    "getDocumentExport": {
        "data": {
            "publicExportId": EXPORT_CREATION_DOCX,
            "publicArtifactId": ARTIFACT_CREATION,
            "revision": 4,
            "format": "docx",
            "state": "ready",
            "templateVersion": "v3",
            "rendererVersion": "docx-2026.08",
            "createdAt": ago(minutes=3),
            "updatedAt": ago(minutes=1),
        }
    },
    "getDocumentExportDownload": {
        "data": {
            "publicExportId": EXPORT_CREATION_DOCX,
            "format": "docx",
            # 演示站保持离线：下载链接是自带说明文字的 data URI，不指向任何外部服务。
            "downloadUrl": "data:text/plain;charset=utf-8,MediaClaw%20%E6%BC%94%E7%A4%BA%E7%AB%99%EF%BC%9A%E8%BF%99%E9%87%8C%E4%B8%8D%E6%8F%90%E4%BE%9B%E7%9C%9F%E5%AE%9E%E7%9A%84%E6%96%87%E6%A1%A3%E5%AF%BC%E5%87%BA%E6%96%87%E4%BB%B6%E3%80%82%E7%9C%9F%E5%AE%9E%E7%8E%AF%E5%A2%83%E4%BC%9A%E8%BF%94%E5%9B%9E%E5%B8%A6%E6%A0%A1%E9%AA%8C%E5%80%BC%E7%9A%84%20docx%2Fpdf%E3%80%82",
            "expiresAt": ahead(hours=2),
        }
    },
    "getResourceDocxLink": {
        "document": {
            "publicArtifactId": ARTIFACT_CREATION,
            "url": "https://demo.mediaclaw.example/documents/creation-camera.docx",
            "expiresAt": ahead(hours=2),
        }
    },
    **ADMIN_SEED,
}

# Detail payloads keyed by the last path parameter, so list pages and detail
# pages describe the same demo world.
PARAMETER_PAYLOADS: dict[str, dict[str, Any]] = {
    "getRun": {
        RUN_CAMERA: {},
        RUN_CITYWALK: {
            "run": {
                "publicRunId": RUN_CITYWALK,
                "title": "城市漫步·苏州河支线脚本",
                "platform": "抖音",
                "contentType": "短视频",
                "trackName": "城市漫步",
                "entrypoint": "飞书标签",
                "status": "awaiting_confirmation",
                "availableSections": ["sources", "outputs"],
                "publicProjectId": PROJECT_CITYWALK,
                "createdAt": ago(days=4),
                "updatedAt": ago(hours=9),
                "revision": 6,
            }
        },
        RUN_COFFEE: {
            "run": {
                "publicRunId": RUN_COFFEE,
                "title": "三顿半联名商单脚本初稿",
                "platform": "小红书",
                "contentType": "图文",
                "trackName": "咖啡探店",
                "entrypoint": "Web 工作台",
                "status": "awaiting_confirmation",
                "availableSections": ["sources", "decisions"],
                "publicProjectId": PROJECT_COFFEE,
                "createdAt": ago(days=1, hours=6),
                "updatedAt": ago(days=1, hours=2),
                "revision": 2,
            }
        },
    },
    "getRunSources": {RUN_CAMERA: {}, RUN_CITYWALK: {"section": {"publicRunId": RUN_CITYWALK, "revision": 6}}},
    "getRunDecisions": {RUN_CAMERA: {}, RUN_COFFEE: {"section": {"publicRunId": RUN_COFFEE, "revision": 2}}},
    "getRunOutputs": {RUN_CAMERA: {}, RUN_CITYWALK: {"section": {"publicRunId": RUN_CITYWALK, "revision": 6}}},
    "listProjectArtifacts": {
        PROJECT_CAMERA: {},
        PROJECT_CITYWALK: {
            "items": [
                {
                    "publicArtifactId": ARTIFACT_PUBLISHING,
                    "publicProjectId": PROJECT_CITYWALK,
                    "artifactType": "publishing_package",
                    "displayName": "苏州河夜拍发布包",
                    "bodyAuthority": "internal",
                    "currentRevision": 2,
                    "syncStatus": "not_applicable",
                    "updatedAt": ago(hours=9),
                    "allowedActions": ["read", "edit", "export"],
                }
            ]
        },
        PROJECT_REVIEW: {
            "items": [
                {
                    "publicArtifactId": ARTIFACT_REVIEW,
                    "publicProjectId": PROJECT_REVIEW,
                    "artifactType": "review_report",
                    "displayName": "10 月复盘报告",
                    "bodyAuthority": "internal",
                    "currentRevision": 3,
                    "syncStatus": "not_applicable",
                    "updatedAt": ago(days=2),
                    "allowedActions": ["read", "edit", "export"],
                }
            ]
        },
    },
    "getDocumentBody": {
        ARTIFACT_CREATION: {},
        ARTIFACT_REVIEW: _document_body(ARTIFACT_REVIEW, PROJECT_REVIEW, "review_report", REVIEW_DOCUMENT_BLOCKS, 3),
        ARTIFACT_PUBLISHING: _document_body(
            ARTIFACT_PUBLISHING,
            PROJECT_CITYWALK,
            "publishing_package",
            [
                _heading("blk_pub_title", "苏州河夜拍发布包", 1),
                _paragraph("blk_pub_intro", "抖音版本 58 秒，封面为河岸灯带，发布前需确认路线安全提示。"),
                _bullets("blk_pub_check", ["话题：#城市漫步 #夜拍", "发布时间：周五 20:30", "评论区置顶：完整路线图"]),
            ],
            2,
        ),
    },
    "getAsset": {ASSET_HOTPOT: {}, ASSET_CITY_NIGHT: {"item": {"summary": {"publicAssetId": ASSET_CITY_NIGHT}, "revision": 2}}},
    "getPublishingPackage": {PACKAGE_XHS: {}, PACKAGE_DOUYIN: {}},
    "getOwnedAccount": {ACCOUNT_XHS: {}, ACCOUNT_DOUYIN: {"item": {"publicAccountId": ACCOUNT_DOUYIN, "accountName": "小满Vlog", "platform": "抖音"}}},
    "getAccountMonitor": {ACCOUNT_XHS: {}},
    "getAccountTrackStrategy": {ACCOUNT_XHS: {}},
    "getDecision": {DECISION_CITYWALK: {}, DECISION_CAMERA: {"decision": {"publicDecisionId": DECISION_CAMERA, "decisionStatus": "confirmed"}}},
    **ADMIN_PARAMETER_PAYLOADS,
}


# 详情类读取沿用列表里的同一条记录，避免同一个对象在列表页和详情页对不上。
SEED["getTrack"] = {"item": SEED["listTracks"]["items"][0]}
SEED["getCreator"] = {"item": SEED["listCreators"]["items"][0]}
SEED["getPublishingPackage"] = {"package": SEED["listPublishingPackages"]["items"][0]}
SEED["createProjectSummary"] = {
    "item": {
        "publicArtifactId": ARTIFACT_SUMMARY,
        "publicProjectId": PROJECT_CAMERA,
        "artifactType": "project_summary",
        "displayName": "秋日相机测评 · 项目摘要",
        "bodyAuthority": "internal",
        "currentRevision": 1,
        "syncStatus": "not_applicable",
        "updatedAt": ago(minutes=2),
        "allowedActions": ["read", "export"],
    }
}
SEED["createArtifactRevision"] = {
    "item": {
        "publicArtifactId": ARTIFACT_CREATION,
        "publicProjectId": PROJECT_CAMERA,
        "artifactType": "creation_document",
        "displayName": "秋日相机测评脚本 v5",
        "bodyAuthority": "internal",
        "currentRevision": 5,
        "syncStatus": "not_applicable",
        "updatedAt": ago(minutes=1),
        "allowedActions": ["read", "edit", "export"],
    }
}

PARAMETER_PAYLOADS["getTrack"] = {
    item["publicTrackId"]: {"item": item} for item in SEED["listTracks"]["items"]
}
PARAMETER_PAYLOADS["getCreator"] = {
    item["publicCreatorId"]: {"item": item} for item in SEED["listCreators"]["items"]
}
PARAMETER_PAYLOADS["getPublishingPackage"] = {
    item["publicPackageId"]: {"package": item} for item in SEED["listPublishingPackages"]["items"]
}
PARAMETER_PAYLOADS["getOwnedAccount"] = {
    item["publicAccountId"]: {"item": item} for item in SEED["listOwnedAccounts"]["items"]
}
PARAMETER_PAYLOADS["getDecision"] = {
    item["publicDecisionId"]: {"decision": item} for item in SEED["listDecisions"]["items"]
}

# 复盘相关的写操作返回的是产物描述，页面会把它当成刚生成的复盘报告展示。
_REVIEW_ARTIFACT = {
    "item": {
        "publicArtifactId": ARTIFACT_REVIEW,
        "publicProjectId": PROJECT_REVIEW,
        "artifactType": "review_report",
        "displayName": "10 月复盘报告",
        "bodyAuthority": "internal",
        "currentRevision": 3,
        "syncStatus": "not_applicable",
        "updatedAt": ago(minutes=2),
        "allowedActions": ["read", "edit", "export"],
    }
}
SEED["createReview"] = _REVIEW_ARTIFACT
SEED["confirmReview"] = _REVIEW_ARTIFACT
