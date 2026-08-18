from copy import deepcopy
from pathlib import Path

import pytest

from openclaw_app.services.media_business.lark_base_projection import (
    TABLE_SPECS,
    LarkBaseProjection,
    _stable_public_id,
)


def _spec(target_table: str):
    return next(item for item in TABLE_SPECS if item.target_table == target_table)


def test_public_id_normalizes_backend_only_separators_deterministically():
    spec = _spec("decision_traces")
    fields = {"决策轨迹ID": "trace:f5061b3039af1adb58a4aa453d58fffa233af94f"}

    first = _stable_public_id(spec, fields, "record-1")
    second = _stable_public_id(spec, fields, "record-1")

    assert first == second
    assert first.startswith("trace_f5061b3039af1adb58a4aa453d58fffa233af94f_")
    assert ":" not in first
    assert 8 <= len(first) <= 160


def test_run_projection_satisfies_web_read_model_contract():
    spec = _spec("creation_runs")
    canonical = LarkBaseProjection._canonical_data(
        spec,
        {"table_id": "runs"},
        {
            "record_id": "run-record",
            "fields": {
                "创作运行ID": "run_20260807_example",
                "输入需求摘要": "毕业典礼第一视角",
                "平台": "抖音",
                "内容类型": "视频",
                "赛道": "校园生活",
                "入口标签": "【创作】",
                "状态": "success",
            },
        },
    )

    assert canonical["title"] == "毕业典礼第一视角"
    assert canonical["platform"] == "抖音"
    assert canonical["contentType"] == "视频"
    assert canonical["trackName"] == "校园生活"
    assert canonical["entrypoint"] == "【创作】"
    assert canonical["status"] == "success"
    assert canonical["availableSections"] == []


def test_decision_projection_satisfies_web_read_model_contract():
    spec = _spec("decision_traces")
    canonical = LarkBaseProjection._canonical_data(
        spec,
        {"table_id": "decisions"},
        {
            "record_id": "decision-record",
            "fields": {
                "决策轨迹ID": "trace:example",
                "候选记录ID": "activity-1",
                "候选类型": "activity",
                "是否入选": True,
            },
        },
        {
            "activity-1": {
                "title": "用毕业影像给青春抽一支上上签",
                "platform": "抖音",
                "sourceType": "activity",
            }
        },
    )

    assert canonical["candidateTitle"] == "用毕业影像给青春抽一支上上签"
    assert canonical["candidateType"] == "activity"
    assert canonical["platform"] == "抖音"
    assert canonical["trackName"] == "未标注"
    assert canonical["decisionStatus"] == "recommended"
    assert canonical["evidenceRefs"] == []
    assert canonical["evidenceCount"] == 0


def test_decision_projection_does_not_expose_internal_candidate_id_as_title():
    spec = _spec("decision_traces")
    canonical = LarkBaseProjection._canonical_data(
        spec,
        {"table_id": "decisions"},
        {
            "record_id": "decision-record",
            "fields": {
                "决策轨迹ID": "trace:example",
                "候选记录ID": "recvmQ3It24K6y-direction-7eec490a25e7",
                "候选类型": "activity",
                "是否入选": False,
            },
        },
        {},
    )

    assert canonical["candidateTitle"] == "活动候选（标题待同步）"
    assert canonical["candidateTitle"] != canonical["fields"]["候选记录ID"]


def test_asset_projection_satisfies_web_read_model_contract():
    canonical = LarkBaseProjection._canonical_data(
        _spec("assets"),
        {"table_id": "assets"},
        {
            "record_id": "asset-record",
            "fields": {
                "标题": "训练视频",
                "平台": "抖音",
                "素材状态": "已解析",
                "标签": ["AI"],
                "主题标签": ["旧字段"],
                "视频附件": [{"name": "clip.mp4"}],
                "来源链接": {"link": "https://example.com/video", "text": "https://example.com/video"},
            },
        },
    )

    assert canonical["title"] == "训练视频"
    assert canonical["mediaType"] == "视频"
    assert canonical["platform"] == "抖音"
    assert canonical["sourceLabel"] == "抖音"
    assert canonical["platform_hashtags"] == []
    assert canonical["trackNames"] == []
    assert canonical["qualityStatus"] == "unverified"
    assert canonical["materialStatus"] == "已解析"
    assert canonical["source_url"] == "https://example.com/video"
    assert "fields" not in canonical
    assert "标签" not in __import__("json").dumps(canonical, ensure_ascii=False)
    assert "主题标签" not in __import__("json").dumps(canonical, ensure_ascii=False)


def test_asset_projection_reads_only_platform_hashtag_field_or_explicit_title_tag():
    spec = _spec("assets")
    from_field = LarkBaseProjection._canonical_data(
        spec,
        {"table_id": "assets"},
        {
            "record_id": "asset-hashtag-field",
            "fields": {
                "标题": "普通标题",
                "平台话题标签": ["#短跑", {"name": "训练"}],
                "标签": ["AI"],
                "主题标签": ["旧字段"],
            },
        },
    )
    without_field = LarkBaseProjection._canonical_data(
        spec,
        {"table_id": "assets"},
        {
            "record_id": "asset-hashtag-title",
            "fields": {
                "标题": "标题 #校园跑",
                "标签": ["AI"],
                "主题标签": ["运动"],
            },
        },
    )

    assert from_field["platform_hashtags"] == ["短跑", "训练"]
    assert without_field["platform_hashtags"] == []
    assert "fields" not in from_field
    assert "fields" not in without_field


def test_asset_cover_attachment_projects_stable_preview_without_expiring_or_secret_values():
    canonical = LarkBaseProjection._canonical_data(
        _spec("assets"),
        {"table_id": "tbl_assets"},
        {
            "record_id": "rec_asset_cover",
            "fields": {
                "素材ID": "asset_cover_123",
                "标题": "封面素材",
                "封面附件": [{
                    "file_token": "secret-file-token",
                    "fileToken": "secret-file-token-camel",
                    "name": "cover.jpg",
                    "type": "image/jpeg",
                    "tmp_url": "https://open.feishu.cn/temporary/expired",
                    "tmpUrl": "https://open.feishu.cn/temporary/expired-camel",
                    "width": 1280,
                    "height": 720,
                }],
            },
        },
    )

    encoded = __import__("json").dumps(canonical, ensure_ascii=False)
    assert "tmp_url" not in encoded
    assert "secret-file-token" not in encoded
    assert "secret-file-token-camel" not in encoded
    assert canonical["preview"]["url"] == "/openclaw/media/api/assets/asset_cover_123/preview"
    assert canonical["preview"]["kind"] == "image"
    assert canonical["preview"]["status"] == "available"


def test_business_opportunity_projection_satisfies_web_read_model_contract():
    canonical = LarkBaseProjection._canonical_data(
        _spec("business_opportunities"),
        {"table_id": "opportunities"},
        {
            "record_id": "opportunity-record",
            "fields": {
                "品牌": "示例品牌",
                "产品": "跑鞋",
                "平台": "小红书",
                "内容类型": "视频",
                "授权范围": "全渠道使用",
                "档期": "8月上旬",
                "有效开始时间": None,
                "有效结束时间": None,
            },
        },
    )

    assert canonical["brand"] == "示例品牌"
    assert canonical["product"] == "跑鞋"
    assert canonical["platform"] == "小红书"
    assert canonical["contentType"] == "视频"
    assert canonical["authorizationScope"] == "全渠道使用"
    assert canonical["status"] == "8月上旬"


def test_creator_and_track_projections_satisfy_web_read_model_contracts():
    creator = LarkBaseProjection._canonical_data(
        _spec("creator_profiles"),
        {"table_id": "creators"},
        {
            "record_id": "creator-record",
            "fields": {
                "账号名称": "校园跑者",
                "平台": "抖音",
                "作者ID": "93130816637",
                "创作者角色": "校园创作者",
                "身份标签": ["校园", "跑步"],
                "专业能力领域": ["短跑"],
                "主页链接": {"link": "https://example.com/creator", "text": "https://example.com/creator"},
                "头像链接": {"link": "https://cdn.example.com/avatar.jpg", "text": "https://cdn.example.com/avatar.jpg"},
            },
        },
    )
    track = LarkBaseProjection._canonical_data(
        _spec("tracks"),
        {"table_id": "tracks"},
        {
            "record_id": "track-record",
            "fields": {
                "赛道名称": "校园体育",
                "赛道说明": "校园体育内容",
                "状态": "active",
                "适用平台": ["抖音"],
                "赛道别名": None,
                "父赛道ID": None,
            },
        },
    )

    assert creator["account_name"] == "校园跑者"
    assert creator["author_id"] == "93130816637"
    assert creator["creator_role"] == "校园创作者"
    assert creator["identity_tags"] == ["校园", "跑步"]
    assert creator["expertise_domains"] == ["短跑"]
    assert creator["profile_url"] == "https://example.com/creator"
    assert creator["avatar_url"] == "https://cdn.example.com/avatar.jpg"
    creator_without_profile = LarkBaseProjection._canonical_data(
        _spec("creator_profiles"),
        {"table_id": "creators"},
        {
            "record_id": "creator-without-profile",
            "fields": {
                "账号名称": "未提供主页的博主",
                "平台": "抖音",
                "创作者角色": "校园创作者",
            },
        },
    )
    assert creator_without_profile["profile_url"] is None
    assert creator_without_profile["avatar_url"] is None
    assert creator_without_profile["author_id"] is None
    assert track["track_name"] == "校园体育"
    assert track["description"] == "校园体育内容"
    assert track["platforms"] == ["抖音"]
    assert track["aliases"] == []
    assert track["artifact_count"] == 0
    assert track["parent_track_id"] is None


def test_relationship_projection_supplies_join_and_display_fields():
    fields = {
        "赛道ID": "校园体育",
        "达人档案ID": "creator_example",
        "赛道角色": "标杆账号",
        "匹配分": "93",
        "匹配理由": "身份与内容方向匹配",
        "状态": "active",
        "最近评估时间": 1785321237000,
    }
    canonical = LarkBaseProjection._canonical_data(
        _spec("track_creator_memberships"),
        {"table_id": "memberships"},
        {"record_id": "membership-record", "fields": fields},
    )

    assert canonical["public_track_id"] == _stable_public_id(
        _spec("tracks"), {"赛道ID": "校园体育"}, "unused"
    )
    assert canonical["public_creator_id"] == "creator_example"
    assert canonical["fit_score"] == 93
    assert canonical["last_evaluated_at"] == "2026-07-29T10:33:57Z"


def test_metric_projections_supply_numeric_values_and_source_timestamps():
    content = LarkBaseProjection._canonical_data(
        _spec("metric_snapshots"),
        {"table_id": "content-metrics"},
        {
            "record_id": "metric-record",
            "last_modified_time": 1785321237000,
            "fields": {
                "发布作品ID": "post_example",
                "指标键": "likes",
                "指标值": "18.04",
                "单位": "%",
                "数据质量": "screenshot_only",
            },
        },
    )
    account = LarkBaseProjection._canonical_data(
        _spec("account_metric_snapshots"),
        {"table_id": "account-metrics"},
        {
            "record_id": "account-metric-record",
            "created_time": 1785321237000,
            "fields": {
                "达人档案ID": "creator_example",
                "指标键": "followers",
                "指标值": "37000",
                "单位": "人",
                "数据质量": "partial",
            },
        },
    )

    assert content["subject_type"] == "content"
    assert content["public_subject_id"] == "post_example"
    assert content["metric_value"] == 18.04
    assert content["evidence_quality"] == "partial"
    assert content["collected_at"] == "2026-07-29T10:33:57Z"
    assert account["subject_type"] == "account"
    assert account["public_subject_id"] == "creator_example"
    assert account["metric_value"] == 37000


def test_post_review_projection_targets_review_read_model():
    spec = _spec("review_records")
    assert spec.table_key == "post_review"
    canonical = LarkBaseProjection._canonical_data(
        spec,
        {"table_id": "reviews"},
        {
            "record_id": "review-record",
            "fields": {
                "发布作品ID": "post_example",
                "平台": "抖音",
                "表现评级": "值得重剪",
                "关键指标摘要": "开头留存需要改善",
            },
        },
    )

    assert canonical["public_post_id"] == "post_example"
    assert canonical["platform"] == "抖音"
    assert canonical["evidence_quality"] == "partial"
    assert canonical["model_suggestion"] == "开头留存需要改善"
    assert canonical["human_decision"] == "值得重剪"
    assert canonical["status"] == "confirmed"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e", "https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e"),
        ("https://www.larksuite.com/docx/UkSMwA36fiZuBdkk63ncnm84n0e", "https://www.larksuite.com/docx/UkSMwA36fiZuBdkk63ncnm84n0e"),
        ("http://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e", None),
        ("https://tenant.feishu.cn.evil.example/wiki/UkSMwA36fiZuBdkk63ncnm84n0e", None),
        ("https://user@tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e", None),
        ("https://tenant.feishu.cn:443/wiki/UkSMwA36fiZuBdkk63ncnm84n0e", None),
        ("https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e?from=base", None),
        ("https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e#section", None),
        ("https://tenant.feishu.cn/wiki/short", None),
        ("https://tenant.feishu.cn/wiki/UkSMwA36fiZuBdkk63ncnm84n0e/extra", None),
        ("https://tenant.larkoffice.com/docx/UkSMwA36fiZuBdkk63ncnm84n0e", "https://tenant.larkoffice.com/docx/UkSMwA36fiZuBdkk63ncnm84n0e"),
        ("https://tenant.feishu.cn/drive/UkSMwA36fiZuBdkk63ncnm84n0e", None),
        (None, None),
    ],
)
def test_post_review_projection_only_projects_safe_document_links(value, expected):
    canonical = LarkBaseProjection._canonical_data(
        _spec("review_records"),
        {"table_id": "reviews"},
        {
            "record_id": "review-record",
            "fields": {
                "发布作品ID": "post_example",
                "复盘文档链接": value,
            },
        },
    )

    assert canonical["document_url"] == expected


def test_dry_run_validates_every_canonical_projection():
    projection = LarkBaseProjection(None, None)
    projection.fetch_records = lambda: (
        [
            (
                _spec("account_metric_snapshots"),
                {"table_id": "account-metrics"},
                {
                    "record_id": "broken-record",
                    "last_modified_time": 1785321237000,
                    "fields": {
                        "达人档案ID": "creator_example",
                        "指标键": "followers",
                        "指标值": "not-a-number",
                        "单位": "人",
                        "数据质量": "partial",
                    },
                },
            )
        ],
        {"tables": {}},
    )

    with pytest.raises(RuntimeError, match="numeric Base field is invalid"):
        projection.project(dry_run=True)


_REGISTRY_TABLES = (
    ("source_asset", "assets", "tbl_source_asset"),
    ("material_deconstruction", "material_deconstructions", "tbl_material_deconstruction"),
    ("creative_pattern", "creative_patterns", "tbl_creative_pattern"),
    ("creation_run", "creation_runs", "tbl_creation_run"),
    ("post_review", "review_records", "tbl_post_review"),
    ("business_account", "business_accounts", "tbl_business_account"),
    ("business_opportunity", "business_opportunities", "tbl_business_opportunity"),
    ("creator_profile", "creator_profiles", "tbl_creator_profile"),
    ("track", "tracks", "tbl_track"),
    ("material_usage", "material_usages", "tbl_material_usage"),
    ("decision_trace", "decision_traces", "tbl_decision_trace"),
    ("track_creator_membership", "track_creator_memberships", "tbl_track_creator_membership"),
    ("post_metric_snapshot", "metric_snapshots", "tbl_post_metric_snapshot"),
    ("account_metric_snapshot", "account_metric_snapshots", "tbl_account_metric_snapshot"),
    ("growth_summary", "growth_summaries", "tbl_growth_summary"),
)


def _registry_document() -> dict[str, object]:
    active_tables = [
        {
            "resource_scope": "table",
            "resource_type": "table",
            "base_key": "media_operations",
            "base_token": "base-main",
            "table_key": table_key,
            "table_id": table_id,
            "observed_feishu_table_display_name": f"target-{table_key}",
            "target_feishu_table_display_name": f"target-{table_key}",
            "postgres_target": target_table,
            "binding_status": "readback_verified_current",
        }
        for table_key, target_table, table_id in _REGISTRY_TABLES
    ]
    active_tables.extend(
        [
            {
                "resource_scope": "table",
                "resource_type": "table",
                "base_key": "media_operations",
                "base_token": "base-main",
                "table_key": "candidate_topic",
                "table_id": "tbl_candidate_topic",
                "observed_feishu_table_display_name": "D01_候选选题",
                "target_feishu_table_display_name": "D01_候选选题",
                "postgres_target": "candidate_topics",
                "binding_status": "target_applied_verified",
            },
            {
                "resource_scope": "table",
                "resource_type": "table",
                "base_key": "media_external_signals",
                "base_token": "base-activity",
                "table_key": "platform_event",
                "table_id": "tbl_platform_event",
                "observed_feishu_table_display_name": "E01_平台活动",
                "target_feishu_table_display_name": "E01_平台活动",
                "postgres_target": "external_signals",
                "binding_status": "readback_verified_current",
            },
        ]
    )
    return {
        "version": "media_operations_registry_v2",
        "bases": [
            {"base_key": "media_operations", "base_token": "base-main"},
            {"base_key": "media_external_signals", "base_token": "base-activity"},
        ],
        "tables": active_tables,
        "pending_tables": [],
    }


class _ProjectionFeishu:
    def __init__(self, table_items: dict[str, list[dict[str, str]]]) -> None:
        self.table_items = table_items
        self.table_list_reads: list[str] = []
        self.record_reads: list[tuple[str, str]] = []

    def _request(self, method: str, path: str, *, params: dict[str, object]) -> dict[str, object]:
        assert method == "GET"
        self.table_list_reads.append(path)
        base_token = path.split("/")[4]
        return {"data": {"items": self.table_items.get(base_token, []), "has_more": False}}

    def list_bitable_records(
        self,
        base_token: str,
        table_id: str,
        *,
        page_size: int,
        automatic_fields: bool,
    ) -> list[dict[str, object]]:
        assert page_size == 500
        assert automatic_fields is True
        self.record_reads.append((base_token, table_id))
        if base_token == "base-activity":
            return [{"record_id": "activity-record", "fields": {"标题": "活动标题", "关联ID": "activity-1"}}]
        return [{"record_id": f"record-{table_id}", "fields": {}}]


def _table_items(document: dict[str, object], base_token: str) -> list[dict[str, str]]:
    return [
        {
            "table_id": str(table["table_id"]),
            "name": str(table["observed_feishu_table_display_name"]),
        }
        for table in document["tables"]  # type: ignore[index]
        if table["base_token"] == base_token  # type: ignore[index]
    ]


def _projection_feishu(registry: dict[str, object]) -> _ProjectionFeishu:
    return _ProjectionFeishu(
        {
            "base-main": _table_items(registry, "base-main"),
            "base-activity": _table_items(registry, "base-activity"),
        }
    )


def test_projection_reads_by_registry_physical_id_and_reports_display_name_drift() -> None:
    registry = _registry_document()
    table_items = _table_items(registry, "base-main")
    table_items[0]["name"] = "renamed-after-migration"
    feishu = _ProjectionFeishu(
        {"base-main": table_items, "base-activity": _table_items(registry, "base-activity")}
    )

    rows, stats = LarkBaseProjection(feishu, None, registry=registry).fetch_records()

    assert [table_id for _base_token, table_id in feishu.record_reads] == [
        table_id for _table_key, _target, table_id in _REGISTRY_TABLES
    ]
    assert len(rows) == len(_REGISTRY_TABLES)
    assert stats["warnings"] == [
        {
            "code": "DISPLAY_NAME_DRIFT",
            "table_key": "source_asset",
            "observed_name": "renamed-after-migration",
            "target_name": "target-source_asset",
        }
    ]


def test_missing_physical_binding_fails_before_any_record_read() -> None:
    registry = _registry_document()
    del registry["tables"][0]  # type: ignore[index]
    feishu = _projection_feishu(registry)

    with pytest.raises(RuntimeError, match="MISSING_TABLE_BINDING"):
        LarkBaseProjection(feishu, None, registry=registry).fetch_records()

    assert feishu.record_reads == []


@pytest.mark.parametrize(
    "mutation, error_code",
    [
        (lambda document: document["tables"][0].update({"base_token": "other-base"}), "BASE_MEMBERSHIP"),  # type: ignore[index]
        (lambda document: document["tables"][1].update({"table_id": document["tables"][0]["table_id"]}), "DUPLICATE_TABLE_ID"),  # type: ignore[index]
        (lambda document: document["tables"].append(deepcopy(document["tables"][0]) | {"table_key": "legacy_alias"}), "UNKNOWN_TABLE_KEY"),  # type: ignore[index]
    ],
)
def test_physical_identity_errors_fail_before_any_record_read(mutation, error_code: str) -> None:
    registry = _registry_document()
    mutation(registry)
    feishu = _projection_feishu(registry)

    with pytest.raises(RuntimeError, match=error_code):
        LarkBaseProjection(feishu, None, registry=registry).fetch_records()

    assert feishu.record_reads == []


def test_active_candidate_topic_binding_resolves_physical_id() -> None:
    registry = _registry_document()
    binding = LarkBaseProjection(None, None, registry=registry).resolve_table_binding("candidate_topic")

    assert binding["table_id"] == "tbl_candidate_topic"
    assert binding["binding_status"] == "target_applied_verified"


def test_pending_table_has_no_runtime_identity() -> None:
    registry = _registry_document()
    candidate = registry["tables"].pop(-2)  # type: ignore[index]
    candidate.pop("table_id")
    candidate["binding_status"] = "pending_create"
    registry["pending_tables"].append(candidate)  # type: ignore[index]

    with pytest.raises(RuntimeError, match="PENDING_BINDING"):
        LarkBaseProjection(None, None, registry=registry).resolve_table_binding("candidate_topic")


def test_projection_source_has_no_name_or_document_url_lookup() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "openclaw_app/services/media_business/lark_base_projection.py",
        root / "openclaw_app/server_cli.py",
        root / "scripts/sync_lark_base_projection.py",
    ]
    text = "\n".join(source.read_text(encoding="utf-8") for source in sources)

    forbidden = (
        "tables.get(",
        "spec.name",
        "BASE_WIKI_URL",
        "wiki_url",
        "activity_url",
        "--wiki-url",
        "MEDIA_OS_ACTIVITY_URL",
        "resolve_document_reference",
        "source_assets_base_wiki_url",
        "OPENCLAW_MEDIA_SOURCE_BASE_TOKEN",
    )
    assert all(value not in text for value in forbidden)


def test_auxiliary_physical_binding_fails_before_any_record_read() -> None:
    registry = _registry_document()
    feishu = _ProjectionFeishu({"base-main": _table_items(registry, "base-main"), "base-activity": []})

    with pytest.raises(RuntimeError, match="MISSING_TABLE_BINDING: platform_event"):
        LarkBaseProjection(feishu, None, registry=registry).fetch_records()

    assert feishu.record_reads == []


def test_identity_failure_does_not_open_database_transaction() -> None:
    registry = _registry_document()
    feishu = _ProjectionFeishu({"base-main": _table_items(registry, "base-main"), "base-activity": []})
    opened: list[bool] = []

    def connection_factory():
        opened.append(True)
        raise AssertionError("database transaction must not open after identity failure")

    with pytest.raises(RuntimeError, match="MISSING_TABLE_BINDING: platform_event"):
        LarkBaseProjection(feishu, connection_factory, registry=registry).project(dry_run=False)

    assert opened == []
    assert feishu.record_reads == []


def test_activity_title_projection_reads_platform_event_by_registry_id() -> None:
    registry = _registry_document()
    feishu = _projection_feishu(registry)
    projection = LarkBaseProjection(feishu, None, registry=registry)
    rows, _stats = projection.fetch_records()
    before = len(feishu.record_reads)
    rows.append(
        (
            _spec("decision_traces"),
            {"table_id": "tbl_decision_trace"},
            {
                "record_id": "decision-activity",
                "fields": {
                    "决策轨迹ID": "trace_activity_example",
                    "候选记录ID": "activity-1",
                    "候选类型": "activity",
                },
            },
        )
    )

    candidates, activity_count = projection._candidate_index(rows)

    assert candidates["activity-1"]["title"] == "活动标题"
    assert activity_count == 1
    assert feishu.record_reads[before:] == [("base-activity", "tbl_platform_event")]
