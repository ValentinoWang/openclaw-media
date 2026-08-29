from __future__ import annotations

import json
from types import SimpleNamespace

from selfmedia.creation import shooting_execution
from selfmedia.creation.writer import (
    _creator_publish_blocks,
    _evidence_appendix_blocks,
    _shooting_execution_doc_blocks,
)


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        topic="WAIC 探展",
        time_window="",
        publish_time="",
        platform="抖音",
        content_type="视频",
        shooting_goal="完成第一视角探展",
    )


def _shooting_draft(*, first_hour_action: str = "发布后手动置顶提问，并回复前十条有效评论。") -> dict[str, object]:
    return {
        "shooting_goal": {"platform": "抖音", "content_type": "视频", "mainline": "先展示体验再给出结论"},
        "route_map": [{"time_slot": "上午", "location": "展位", "shooting_task": "拍摄体验", "people": "博主", "backup": "补拍特写"}],
        "must_shot_list": [{"priority": "P0", "location": "展位", "people": "博主", "action": "体验", "shot_size": "中景", "reference": "现场素材", "usage": "正片", "reshoot_check": "画面清晰"}],
        "branch_plans": [{"condition": "拥挤", "plan": "先拍设备特写", "priority": "P1"}],
        "storyboard": [{"time": "0-2 秒", "visual": "体验结果", "caption_or_voice": "开场", "sound_or_note": "保留现场声"}],
        "onsite_checklist": ["拍完后回看开场镜头"],
        "publishing_pack": {
            "title_directions": ["主标题"],
            "cover_frame": "人物和设备同框",
            "body_copy": "完整发布文案。",
            "hashtags": ["科技探展"],
            "bgm_suggestion": "克制电子乐",
            "comment_prompt": "你最想体验哪一项？",
            "first_hour_action": first_hour_action,
        },
        "evidence_appendix": [{"source": "现场素材", "source_status": "confirmed", "available_evidence": "已提供素材", "usage_reason": "作为拍摄依据", "risk": "不补写未见细节"}],
    }


def _creator_report() -> dict[str, object]:
    return {
        "overview": {
            "recommended_topic": "主题",
            "core_sentence": "核心句",
            "platform": "抖音",
            "content_type": "视频",
            "suitable_activity": "无",
            "strongly_recommend_activity": "无",
            "biggest_risk": "无",
        },
        "opening_3s": {"visual_0_0_5": "开场", "caption_or_voice_0_5_3": "口播", "do_not_open_like_this": "无"},
        "mainline": {"conflict": "冲突", "evidence": "证据", "emotional_payoff": "回收", "audience_resonance": "共鸣"},
        "storyboard": [],
        "publishing_pack": {
            "title_1": "标题一",
            "title_2": "标题二",
            "cover_text": "封面字",
            "body_copy": "正文",
            "hashtags": [],
            "pinned_comment": "置顶评论",
            "comment_prompt": [],
            "first_hour_action": "发布后手动回复评论",
        },
        "material_checklist": {"must_have": [], "better_to_have": [], "can_rescue_without": [], "must_not_fabricate": []},
        "risk_controls": [],
        "evidence_appendix": {},
    }


def test_shooting_document_renders_manual_first_hour_action_and_evidence_appendix() -> None:
    draft = _shooting_draft()

    validation = shooting_execution.validate_shooting_execution_plan(draft)
    blocks = _shooting_execution_doc_blocks(
        "拍摄执行",
        _request(),
        draft,
        validation,
        media_context={"loaded": {"provider_transport": True}},
    )
    rendered = json.dumps(blocks, ensure_ascii=False)

    assert validation["ok"] is True
    assert "发布后首小时动作（需由创作者手动完成）" in rendered
    assert "发布后手动置顶提问，并回复前十条有效评论。" in rendered
    assert "证据附录" in rendered
    assert "来源状态：已核验" in rendered
    assert "必拍" in rendered
    assert "重要" in rendered
    assert "P0" not in rendered
    assert "P1" not in rendered
    assert "confirmed" not in rendered
    assert "provider_transport" not in rendered


def test_first_hour_action_is_required_and_uses_a_chinese_validation_label() -> None:
    draft = _shooting_draft(first_hour_action="")

    validation = shooting_execution.validate_shooting_execution_plan(draft)
    blocks = _shooting_execution_doc_blocks("拍摄执行", _request(), draft, validation)
    rendered = json.dumps(blocks, ensure_ascii=False)

    assert validation["ok"] is False
    assert validation["missing"] == ["first_hour_action"]
    assert "缺失字段：发布后首小时动作" in rendered
    assert "first_hour_action" not in rendered


def test_creator_reply_hides_provider_and_run_identifiers() -> None:
    reply = shooting_execution.format_shooting_execution_reply(
        _request(),
        "https://example.com/doc",
        {"ok": True},
        {"run_id": "run_creator_123", "provider": "codex_responses"},
        dry_run=False,
    )

    assert "拍摄执行单已生成。" in reply
    assert "https://example.com/doc" in reply
    assert reply.splitlines()[1] == "拍摄执行文档：https://example.com/doc"
    assert "run_creator_123" not in reply
    assert "codex" not in reply.lower()
    assert "provider" not in reply.lower()


def test_unknown_machine_values_use_creator_facing_fallbacks() -> None:
    localized = shooting_execution.localize_shooting_execution_plan_values(
        {
            "must_shot_list": [{"priority": "P9"}],
            "branch_plans": [{"priority": "blocked"}],
            "evidence_appendix": [{"source_status": "provider_pending"}],
        }
    )

    assert localized["must_shot_list"][0]["priority"] == "待人工确认"
    assert localized["branch_plans"][0]["priority"] == "待人工确认"
    assert localized["evidence_appendix"][0]["source_status"] == "待人工核实"


def test_creator_appendices_use_human_labels_and_keep_evidence() -> None:
    record = SimpleNamespace(
        source_table="Obsidian:人性洞察库",
        source_record_id="insight-001",
        title="被理解感",
        status="已验证",
        detail_json={
            "insight_card_path": "人性洞察库/被理解感.md",
            "insight_card_status": "operator_verified",
            "evidence_boundary": "public_content_only",
            "risk_boundary": "避免焦虑营销。",
        },
    )
    inspiration = SimpleNamespace(record=record, reasons={"主题相似": 8}, score=92)
    draft = {
        "recommended_option_id": "option-1",
        "script_options": [
            {
                "option_id": "option-1",
                "score": 92,
                "activity_fit_reason": "活动契合主题。",
                "viral_reference_reason": "迁移开场结构。",
                "inspiration_reference_reason": "落到结尾提问。",
            }
        ],
        "usable_material_brief": {
            "execution_brief": "先拍体验，再收束结论。",
            "source_mapping": [{"source": "insight-001", "transfer": "真实体验", "placement": "开场镜头"}],
        },
    }

    blocks = _evidence_appendix_blocks([], [], [inspiration], [], draft, {"ok": True})
    publish_blocks = _creator_publish_blocks(_creator_report(), {})
    rendered = json.dumps([*blocks, *publish_blocks], ensure_ascii=False)

    assert "评分与追溯信息" in rendered
    assert "活动采用说明" in rendered
    assert "爆款迁移说明" in rendered
    assert "灵感落地说明" in rendered
    assert "引用类型：洞察卡（仅公开内容）" in rendered
    assert "证据边界：仅公开内容" in rendered
    assert "卡片关联：被理解感.md（内部证据已保留）" in rendered
    assert "卡片状态：已人工核验" in rendered
    assert "可用内容：真实体验；落地位置：开场镜头" in rendered
    assert "发布后首小时动作（需由创作者手动完成）：发布后手动回复评论" in rendered
    assert "record_id" not in rendered
    assert "insight-card reference" not in rendered
    assert "public_content_only" not in rendered
    assert "operator_verified" not in rendered
    assert "insight-001" not in rendered
    assert "option-1" not in rendered
    assert "人性洞察库/被理解感.md" not in rendered
