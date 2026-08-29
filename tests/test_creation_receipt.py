from selfmedia.creation.request_parser import CreationRequest
from selfmedia.creation.workflow import format_creation_reply


def test_creation_receipt_hides_internal_telemetry_and_keeps_delivery_details() -> None:
    request = CreationRequest(
        platform="抖音",
        content_type="视频",
        track="跑步训练",
        topic="训练日记",
        publish_time="今天 20:00",
    )

    reply = format_creation_reply(
        request,
        [object()],
        [object()],
        [object()],
        [object()],
        "https://example.test/creation-doc",
        {"ok": True},
        media_context={
            "loaded": {"account_profile": True, "recent_creations": 11},
            "account_profile": {"markdown_path": "/private/telemetry/account-profile.md"},
            "creator_profile_error": "CreatorProfile 字段契约不可用",
        },
        memory={"profile": {"markdown_path": "/private/telemetry/memory-profile.md"}},
        creation_record_id="creation_record_123",
        candidate_counts={"activities": 7, "virals": 6, "inspirations": 5, "businesses": 4},
        platform_fit={"platform_mechanism_version": "internal-mechanism-v42"},
        generation={"provider": "internal-provider", "model": "internal-model", "thinking": "internal-thinking"},
    )

    assert "【创作】草稿已就绪" in reply
    assert "平台：抖音" in reply
    assert "主体：训练日记" in reply
    assert "创作文档：https://example.test/creation-doc" in reply
    assert "创作记录ID：creation_record_123（数据复盘时请一并填写）" in reply
    assert "达人档案暂未加载，不影响当前草稿。" in reply
    assert reply.splitlines()[1] == "创作文档：https://example.test/creation-doc"

    for internal_value in (
        "internal-provider",
        "internal-model",
        "internal-thinking",
        "internal-mechanism-v42",
        "/private/telemetry/account-profile.md",
        "/private/telemetry/memory-profile.md",
        "CreatorProfile 字段契约不可用",
        "候选记忆",
        "LLM选择",
        "平台机制版本",
        "Codex Responses",
    ):
        assert internal_value not in reply
