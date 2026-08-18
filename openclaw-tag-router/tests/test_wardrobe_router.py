from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openclaw_app.models.message import Message
from openclaw_app.router.wardrobe import WardrobeMixin, _wardrobe_item_id_from_message
from openclaw_app.services.wardrobe_weather import WardrobeWeatherError


class DummyWardrobeRouter(WardrobeMixin):
    pass


def test_wardrobe_item_id_reads_replied_bot_confirmation_metadata() -> None:
    item_id = "123e4567-e89b-12d3-a456-426614174000"
    message = Message(
        entry_tag="衣橱",
        raw_text="【衣橱】补充订单截图",
        body="补充订单截图",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={"reply_text": f"已写入衣橱。\n衣物ID：{item_id}"},
    )

    assert _wardrobe_item_id_from_message(message) == item_id


def test_wardrobe_item_id_reads_matched_conversation_bot_reply_only() -> None:
    item_id = "123e4567-e89b-12d3-a456-426614174001"
    message = Message(
        entry_tag="衣橱",
        raw_text="【衣橱】补充洗标截图",
        body="补充洗标截图",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={
            "parent_id": "om_reply_1",
            "conversation_context": {
                "items": [
                    {"message_id": "other", "bot_reply": "已写入衣橱。\n衣物ID：123e4567-e89b-12d3-a456-426614174099"},
                    {"message_id": "om_user_1", "bot_reply_message_id": "om_reply_1", "bot_reply": f"已写入衣橱。\n衣物ID：{item_id}"},
                ]
            },
        },
    )

    assert _wardrobe_item_id_from_message(message) == item_id


def test_wardrobe_item_id_does_not_scan_unmatched_conversation_context() -> None:
    message = Message(
        entry_tag="衣橱",
        raw_text="【衣橱】补充订单截图",
        body="补充订单截图",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={
            "parent_id": "om_current_parent",
            "conversation_context": {
                "items": [
                    {"message_id": "other", "bot_reply": "已写入衣橱。\n衣物ID：123e4567-e89b-12d3-a456-426614174099"},
                ]
            },
        },
    )

    assert _wardrobe_item_id_from_message(message) == ""


def test_wardrobe_update_requires_item_id_for_posthoc_screenshots(tmp_path: Path) -> None:
    image = tmp_path / "order.png"
    image.write_bytes(b"not-real-image")
    router = DummyWardrobeRouter()
    message = Message(
        entry_tag="衣橱",
        raw_text="【衣橱】补充订单截图",
        body="补充订单截图",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={"downloaded_paths": [str(image)]},
    )

    result = router.handle_衣物_入库(message)

    assert result.ok is False
    assert result.status == "wardrobe_item_link_pending"
    assert "衣物ID" in result.reply


def test_wardrobe_recommendation_missing_context_does_not_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WARDROBE_OBSIDIAN_ITEMS_ROOT", str(tmp_path))
    monkeypatch.delenv("WARDROBE_DEFAULT_LOCATION", raising=False)
    monkeypatch.delenv("WARDROBE_WEATHER_CONTEXT_JSON", raising=False)
    router = DummyWardrobeRouter()
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】今天通勤穿什么",
        body="今天通勤穿什么",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={},
    )

    result = router.handle_穿搭(message)

    assert result.ok is False
    assert result.status == "wardrobe_context_pending"
    assert "Daily/待办/日程的结构化地点字段" in result.reply
    assert "手填天气" in result.reply
    assert "Codex 搜索" in result.reply
    assert "请补充当前位置" not in result.reply
    assert not list(tmp_path.glob("*.md"))


def test_wardrobe_context_reads_daily_context_from_env(monkeypatch) -> None:
    monkeypatch.setenv("WARDROBE_DEFAULT_LOCATION", "深圳")
    monkeypatch.setenv("WARDROBE_WEATHER_CONTEXT_JSON", '{"summary":"小雨","temperature":"28C"}')
    monkeypatch.setenv("WARDROBE_DAILY_CONTEXT_JSON", '{"todo":["通勤","夜跑"]}')
    router = DummyWardrobeRouter()
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】今天怎么穿",
        body="今天怎么穿",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={},
    )

    context = router._wardrobe_context(message)

    assert context["missing"] == []
    assert context["location"] == "深圳"
    assert context["weather"]["summary"] == "小雨"
    assert context["daily_context"] == {"todo": ["通勤", "夜跑"]}


def test_wardrobe_context_reads_explicit_location_from_daily_context(monkeypatch) -> None:
    monkeypatch.delenv("WARDROBE_DEFAULT_LOCATION", raising=False)
    monkeypatch.delenv("WARDROBE_WEATHER_CONTEXT_JSON", raising=False)
    router = DummyWardrobeRouter()
    monkeypatch.setattr(
        router,
        "_resolve_wardrobe_weather",
        lambda location: {"summary": "多云", "temperature": "28°C", "source": "open-meteo", "location": location},
    )
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】今天怎么穿",
        body="今天怎么穿",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={"daily_context": {"today": [{"title": "通勤", "地点": "深圳"}]}},
    )

    context = router._wardrobe_context(message)

    assert context["missing"] == []
    assert context["location"] == "深圳"
    assert context["weather_location"] == "深圳"
    assert context["weather"]["source"] == "open-meteo"


def test_wardrobe_context_does_not_guess_location_from_todo_text(monkeypatch) -> None:
    monkeypatch.delenv("WARDROBE_DEFAULT_LOCATION", raising=False)
    monkeypatch.delenv("WARDROBE_WEATHER_CONTEXT_JSON", raising=False)
    router = DummyWardrobeRouter()
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】今天怎么穿",
        body="今天怎么穿",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={"daily_context": {"todo": ["今天去深圳通勤"]}},
    )

    context = router._wardrobe_context(message)

    assert "current_location" in context["missing"]
    assert context["location"] == ""
    assert context["weather"] == {}


def test_wardrobe_context_fetches_weather_from_location(monkeypatch) -> None:
    monkeypatch.delenv("WARDROBE_WEATHER_CONTEXT_JSON", raising=False)
    router = DummyWardrobeRouter()
    monkeypatch.setattr(
        router,
        "_resolve_wardrobe_weather",
        lambda location: {
            "summary": "多云",
            "temperature": "28°C",
            "source": "open-meteo",
            "location": location,
        },
    )
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】位置：深圳 今天通勤",
        body="位置：深圳 今天通勤",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={},
    )

    context = router._wardrobe_context(message)

    assert context["missing"] == []
    assert context["location"] == "深圳"
    assert context["inventory_location"] == "深圳"
    assert context["weather_location"] == "深圳"
    assert context["weather"]["summary"] == "多云"
    assert context["weather"]["source"] == "open-meteo"


def test_wardrobe_context_weather_provider_failure_is_pending(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WARDROBE_OBSIDIAN_ITEMS_ROOT", str(tmp_path))
    monkeypatch.delenv("WARDROBE_WEATHER_CONTEXT_JSON", raising=False)
    router = DummyWardrobeRouter()

    def fail_weather(location: str) -> dict:
        raise WardrobeWeatherError("provider unavailable")

    monkeypatch.setattr(router, "_resolve_wardrobe_weather", fail_weather)
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】位置：深圳 今天通勤",
        body="位置：深圳 今天通勤",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={},
    )

    result = router.handle_穿搭(message)

    assert result.ok is False
    assert result.status == "wardrobe_context_pending"
    assert "天气获取失败" in result.reply
    assert not list(tmp_path.glob("*.md"))


def test_wardrobe_recommendation_writes_obsidian_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WARDROBE_OBSIDIAN_ITEMS_ROOT", str(tmp_path))
    router = DummyWardrobeRouter()
    monkeypatch.setattr(router, "_resolve_wardrobe_weather", lambda location: {"summary": "小雨", "temperature": "28°C"})
    monkeypatch.setattr(router, "_wardrobe_token", lambda: "tenant-token")
    monkeypatch.setattr(
        router,
        "_wardrobe_table_ref",
        lambda: {"app_token": "app", "table_id": "tbl", "url": "https://example.test/base/app?table=tbl"},
    )
    monkeypatch.setattr(router, "_wardrobe_field_defs", lambda token, table_ref: {})
    monkeypatch.setattr(
        router,
        "_wardrobe_records",
        lambda token, table_ref, field_defs: [
            {
                "record_id": "rec1",
                "fields": {
                    "衣物ID": "item-1",
                    "名称": "黑色速干T",
                    "颜色": "黑色",
                    "品牌": "UNIQLO",
                    "用途/场景": ["通勤", "运动"],
                    "状态": "在穿",
                    "位置": "深圳",
                },
            }
        ],
    )
    monkeypatch.setattr(
        router,
        "_wardrobe_llm_json",
        lambda prompt, image_paths: {
            "status": "done",
            "title": "今日深圳通勤穿搭",
            "summary": "轻便，适合小雨通勤。",
            "sections": [
                {
                    "heading": "出门",
                    "items": [
                        {
                            "item_id": "item-1",
                            "display_name": "黑色速干T",
                            "color": "黑色",
                            "brand": "UNIQLO",
                            "occasion": ["通勤"],
                            "note": "小雨通勤可内搭",
                        }
                    ],
                }
            ],
        },
    )
    message = Message(
        entry_tag="穿搭",
        raw_text="【穿搭】位置：深圳 今天通勤",
        body="位置：深圳 今天通勤",
        created_at=datetime(2026, 7, 5, 10, 0, 0),
        metadata={},
    )

    result = router.handle_穿搭(message)

    assert result.ok is True
    assert result.status == "wardrobe_recommendation_written"
    artifact = Path(result.local_path)
    assert artifact.exists()
    text = artifact.read_text(encoding="utf-8")
    assert "# 今日深圳通勤穿搭" in text
    assert "- [ ] 黑色/UNIQLO 通勤 黑色速干T (小雨通勤可内搭)" in text
