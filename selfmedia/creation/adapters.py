from __future__ import annotations

from typing import Any

from .field_contract import (
    CanonicalMediaRecord,
    CREATION_SOURCE_TABLE_CONTRACTS,
    get_exact_datetime,
    get_exact_link,
    get_exact_value,
    get_first_datetime,
    get_first_link,
    get_first_value,
    normalize_content_type,
    normalize_platform,
    split_tags,
)


class ViralContentAdapter:
    source_table = CREATION_SOURCE_TABLE_CONTRACTS["viral"]["table"]

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        asset_id = get_first_value(row, "asset_id")
        source_asset_id = get_first_value(row, "source_asset_id")
        deconstruction_id = get_first_value(row, "deconstruction_id")
        relation_id = deconstruction_id or asset_id
        record_id = str(row.get("record_id") or relation_id or "")
        title = get_first_value(row, "title") or get_first_value(row, "original_title")
        summary = get_first_value(row, "summary")
        hook = get_first_value(row, "hook")
        transferable_points = get_first_value(row, "transferable_points")
        non_transferable_points = get_first_value(row, "non_transferable_points")
        analysis_scope = get_first_value(row, "analysis_scope")
        analysis_time_range = get_first_value(row, "analysis_time_range")
        deconstruction_focus = get_first_value(row, "deconstruction_focus")
        output_types = get_first_value(row, "output_types")
        reference_shots_status = get_first_value(row, "reference_shots_status")
        reference_shot_count = get_first_value(row, "reference_shot_count")
        recommended_production_route = get_first_value(row, "recommended_production_route")
        motion_type_summary = get_first_value(row, "motion_type_summary")
        reference_shots_summary = get_first_value(row, "reference_shots_summary")
        cover_opening_hook = get_first_value(row, "cover_opening_hook")
        core_data_summary = get_first_value(row, "core_data_summary")
        top_comment_insight = get_first_value(row, "top_comment_insight")
        target_audience_summary = get_first_value(row, "target_audience_summary")
        pain_pleasure_summary = get_first_value(row, "pain_pleasure_summary")
        attention_elements = get_first_value(row, "attention_elements")
        viral_breakdown = get_first_value(row, "viral_breakdown")
        viral_migration = get_first_value(row, "viral_migration")
        creative_upgrade_suggestion = get_first_value(row, "creative_upgrade_suggestion")
        evidence_uri = get_first_value(row, "evidence_uri")
        source_doc_link = get_first_link(row, "source_doc_link")
        deconstruction_doc_link = get_first_link(row, "deconstruction_doc_link")
        topic = " ".join(item for item in (title, hook, cover_opening_hook, attention_elements, viral_breakdown) if item)
        tags = split_tags(" ".join(item for item in (title, hook, transferable_points, attention_elements, viral_migration) if item))
        core_value = "\n".join(
            item
            for item in (
                transferable_points,
                viral_migration,
                creative_upgrade_suggestion,
                viral_breakdown,
                summary,
            )
            if item
        )
        detail_json = {
            "asset_id": asset_id,
            "source_asset_id": source_asset_id,
            "author_id": get_first_value(row, "author_id"),
            "account_name_snapshot": get_first_value(row, "account_name_snapshot"),
            "enabled": get_first_value(row, "enabled"),
            "deconstruction_id": deconstruction_id,
            "summary": summary,
            "hook": hook,
            "transferable_points": transferable_points,
            "non_transferable_points": non_transferable_points,
            "analysis_scope": analysis_scope,
            "analysis_time_range": analysis_time_range,
            "deconstruction_focus": deconstruction_focus,
            "output_types": output_types,
            "reference_shots_status": reference_shots_status,
            "reference_shot_count": reference_shot_count,
            "recommended_production_route": recommended_production_route,
            "motion_type_summary": motion_type_summary,
            "reference_shots_summary": reference_shots_summary,
            "cover_opening_hook": cover_opening_hook,
            "core_data_summary": core_data_summary,
            "top_comment_insight": top_comment_insight,
            "target_audience_summary": target_audience_summary,
            "pain_pleasure_summary": pain_pleasure_summary,
            "attention_elements": attention_elements,
            "viral_breakdown": viral_breakdown,
            "viral_migration": viral_migration,
            "creative_upgrade_suggestion": creative_upgrade_suggestion,
            "prompt_bundle_version": get_first_value(row, "prompt_bundle_version"),
            "model": get_first_value(row, "model"),
            "skill_version": get_first_value(row, "skill_version"),
            "evidence_uri": evidence_uri,
        }
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="素材拆解",
            title=title,
            content=summary,
            status=get_first_value(row, "review_status") or get_first_value(row, "status"),
            relation_id=relation_id,
            platform=normalize_platform(get_first_value(row, "platform")),
            content_type=normalize_content_type(""),
            track="",
            topic=topic,
            tags=tags,
            audience=target_audience_summary,
            pain_points=pain_pleasure_summary or hook,
            core_value=core_value,
            publish_time=None,
            source_link=get_first_link(row, "source_url"),
            doc_links={
                "evidence": evidence_uri,
                "source_doc": source_doc_link,
                "deconstruction": deconstruction_doc_link,
            },
            metrics={
                "source_asset_id": source_asset_id,
                "confidence": get_first_value(row, "confidence"),
                "content_fingerprint": get_first_value(row, "content_fingerprint"),
                "core_data_summary": core_data_summary,
                "top_comment_insight": top_comment_insight,
                "analysis_scope": analysis_scope,
                "analysis_time_range": analysis_time_range,
                "deconstruction_focus": deconstruction_focus,
                "output_types": output_types,
            },
            created_at="",
            updated_at="",
            detail_json=detail_json,
        )


class ActivityAdapter:
    source_table = CREATION_SOURCE_TABLE_CONTRACTS["activity"]["table"]

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_exact_value(row, "关联ID")
        record_id = str(row.get("record_id") or relation_id or "")
        brief_link = get_exact_link(row, "Brief链接")
        viral_example_link = get_exact_link(row, "爆款示范链接")
        submission_link = get_exact_link(row, "返稿链接")
        activity_doc_link = get_exact_link(row, "活动文档链接")
        activity_brief = get_exact_value(row, "活动Brief")
        guidance = get_exact_value(row, "填写要点")
        subtopic_direction = get_exact_value(row, "子话题方向")
        submission_requirement = get_exact_value(row, "提交要求")
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="活动",
            title=get_exact_value(row, "标题"),
            content=get_exact_value(row, "内容"),
            status=get_exact_value(row, "主状态"),
            relation_id=relation_id,
            platform=normalize_platform(get_exact_value(row, "平台名称")),
            topic=get_exact_value(row, "主话题"),
            tags=split_tags(" ".join(item for item in (get_exact_value(row, "主话题"), subtopic_direction) if item)),
            start_time=get_exact_datetime(row, "活动开始时间") or get_exact_value(row, "活动开始时间"),
            end_time=get_exact_datetime(row, "活动结束时间") or get_exact_value(row, "活动结束时间"),
            boost_date=get_exact_datetime(row, "冲榜日期") or get_exact_value(row, "冲榜日期"),
            source_link=activity_doc_link or brief_link,
            doc_links={
                "brief": brief_link,
                "viral_example": viral_example_link,
                "submission": submission_link,
                "activity_doc": activity_doc_link,
            },
            activity_level=get_exact_value(row, "活动级别"),
            activity_reward=get_exact_value(row, "活动奖励"),
            direction=subtopic_direction,
            activity_brief=activity_brief,
            activity_guidance=guidance,
            participation_method=get_exact_value(row, "参与方式"),
            participation_form=get_exact_value(row, "参与形式"),
            submission_requirement=submission_requirement,
            brief_link=brief_link,
            viral_example_link=viral_example_link,
            submission_link=submission_link,
            activity_doc_link=activity_doc_link,
            created_at=get_exact_datetime(row, "创建时间") or get_exact_value(row, "创建时间"),
        )


class BusinessAdapter:
    source_table = CREATION_SOURCE_TABLE_CONTRACTS["business"]["table"]

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_first_value(row, "opportunity_id")
        record_id = str(row.get("record_id") or relation_id or "")
        business_account_id = get_first_value(row, "business_account_id")
        brand = get_first_value(row, "brand")
        product = get_first_value(row, "product")
        brief_link = get_first_link(row, "brief_link")
        quote_amount = get_first_value(row, "current_quote_amount")
        title_parts = [item for item in (brand, product, business_account_id) if item]
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="商务",
            title=" / ".join(title_parts) or relation_id or record_id,
            content=" / ".join(item for item in (brand, product, f"报价={quote_amount}" if quote_amount else "") if item),
            status="active",
            relation_id=relation_id,
            platform="",
            content_type_requirement=_business_content_type_requirement(row),
            track="",
            topic=" ".join(item for item in (brand, product) if item),
            tags=split_tags(" ".join(item for item in (brand, product, business_account_id) if item)),
            source_link=brief_link,
            doc_links={"brief": brief_link, "quote_snapshot": get_first_link(row, "quote_snapshot_uri")},
            metrics={"quote_amount": quote_amount, "rebate_ratio": get_first_value(row, "rebate_ratio")},
            start_time=get_first_datetime(row, "valid_from") or get_first_value(row, "valid_from"),
            end_time=get_first_datetime(row, "valid_until") or get_first_value(row, "valid_until"),
            detail_json={
                "business_account_id": business_account_id,
                "brand": brand,
                "product": product,
                "brief_link": brief_link,
                "current_quote_amount": quote_amount,
                "rebate_ratio": get_first_value(row, "rebate_ratio"),
                "quote_snapshot_uri": get_first_value(row, "quote_snapshot_uri"),
            },
        )


class CreationInspirationAdapter:
    source_table = CREATION_SOURCE_TABLE_CONTRACTS["inspiration"]["table"]

    def to_record(self, row: dict[str, Any]) -> CanonicalMediaRecord:
        relation_id = get_first_value(row, "pattern_id")
        record_id = str(row.get("record_id") or relation_id or "")
        title = get_first_value(row, "pattern_name")
        content = "\n".join(
            item
            for item in (
                get_first_value(row, "opening_template"),
                get_first_value(row, "structure_template"),
                get_first_value(row, "visual_template"),
            )
            if item
        )
        topic = get_first_value(row, "applicable_scenarios")
        score_reason = get_first_value(row, "historical_performance_summary")
        return CanonicalMediaRecord(
            source_table=self.source_table,
            source_record_id=record_id,
            record_type="创作模式",
            title=title,
            content=content,
            status=get_first_value(row, "pattern_status"),
            relation_id=relation_id,
            platform=normalize_platform(get_first_value(row, "platform")),
            content_type=normalize_content_type(get_first_value(row, "content_type")),
            track=get_first_value(row, "applicable_persona"),
            topic=topic,
            tags=split_tags(get_first_value(row, "emotional_levers")),
            audience=get_first_value(row, "applicable_persona"),
            pain_points=get_first_value(row, "emotional_levers"),
            core_value=get_first_value(row, "structure_template"),
            source_link="",
            doc_links={},
            metrics={"score_reason": score_reason},
            direction=get_first_value(row, "applicable_scenarios"),
            created_at="",
            updated_at="",
            detail_json={
                "pattern_status": get_first_value(row, "pattern_status"),
                "opening_template": get_first_value(row, "opening_template"),
                "structure_template": get_first_value(row, "structure_template"),
                "visual_template": get_first_value(row, "visual_template"),
                "forbidden_scenarios": get_first_value(row, "forbidden_scenarios"),
                "historical_performance_summary": score_reason,
            },
        )


def _business_content_type_requirement(row: dict[str, Any]) -> str:
    return "不限" if get_first_value(row, "current_quote_amount") else ""
