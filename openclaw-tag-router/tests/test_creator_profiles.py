from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from openclaw_app.models.message import Message
from openclaw_app.router.creator_profile_router import CreatorProfilesMixin


TZ = ZoneInfo("Asia/Shanghai")


def make_message(tag: str, body: str) -> Message:
    return Message(
        entry_tag=tag,
        raw_text=f"【{tag}】{body}",
        body=body,
        source="feishu",
        chat_type="private",
        created_at=datetime(2026, 5, 29, 13, 30, tzinfo=TZ),
    )


class CreatorProfileHarness(CreatorProfilesMixin):
    def __init__(self, records: list[dict] | None = None):
        self.records = records or []
        self.upserted: list[dict] = []
        self.generated_candidates: list[dict] = []
        self.confirmed_runs: list[dict] = []
        self.timezone = "Asia/Shanghai"

    def _creator_profile_records(self, *, url: str | None = None, token: str | None = None) -> list[dict]:
        return self.records

    def _creator_upsert_profile(self, fields: dict) -> dict:
        self.upserted.append(fields)
        return {"ok": True, "action": "created", "record_id": "rec-test", "table_url": "https://bitable.test"}

    def _generate_creator_profile_candidate_run(self, **kwargs) -> dict:
        self.generated_candidates.append(kwargs)
        return {
            "write_status": "candidate_only_not_written",
            "run_id": "20260630T144713Z",
            "evidence_uri": "media://creator_profiles/douyin/22654404058/20260630T144713Z",
            "resolver": {
                "platform": "抖音",
                "input_platform_id": kwargs.get("platform_id"),
                "resolve_status": "exact_profile_resolved",
            },
            "candidate_payload": {
                "platform": "抖音",
                "author_id": "22654404058",
                "account_name": "Ty.Mer",
                "profile_url": "https://www.douyin.com/user/MS4w",
                "identity_summary": "",
                "identity_tags": [],
                "education_background": "",
                "expertise_domains": [],
                "creator_role": "",
                "public_persona_boundaries": "",
                "story_usable_identity_points": "",
                "current_metrics_summary": "粉丝数 901 人；关注 62；获赞 5810；作品 20",
            },
        }

    def _confirm_creator_profile_candidate_run(self, run_id: str, *, user_edits: dict | None = None) -> dict:
        payload = {"run_id": run_id, "user_edits": user_edits or {}}
        self.confirmed_runs.append(payload)
        return {
            "write_status": "written",
            "run_id": run_id,
            "creator_profile": {"record_id": "rec-profile", "mode": "created"},
            "metric_snapshot_status": "written",
            "metric_snapshots": [{"record_id": "rec-metric"}],
            "evidence_uri": "media://creator_profiles/douyin/22654404058/20260630T144713Z",
        }


class CreatorProfilesTest(unittest.TestCase):
    def test_blogger_list_includes_external_unique_id_and_traits(self) -> None:
        harness = CreatorProfileHarness(
            [
                {
                    "record_id": "rec-1",
                    "fields": {
                        "博主IP": "清华AI小王冲一级",
                        "平台": ["抖音"],
                        "平台ID": "93130816637",
                        "账号名称": "小王冲一级",
                        "作者ID": "qinghua-ai-runner",
                        "主页链接": "https://example.com/xiaowang",
                        "关键词标签": "清华AI硕、体育生、跑步",
                        "院校背景": "清华大学",
                        "粉丝数(k)": 37,
                    },
                }
            ]
        )

        result = harness.handle_博主(make_message("博主", ""))

        self.assertTrue(result.ok)
        self.assertIn("外部唯一ID：抖音:qinghua-ai-runner", result.reply)
        self.assertIn("账号名称", result.reply)
        self.assertIn("身份信息", result.reply)
        self.assertIn("清华AI硕", result.reply)

    def test_blogger_upsert_requires_platform_id(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(make_message("博主-入库", "博主IP：清华AI小王冲一级\n平台：抖音"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "creator_profile_missing_required")
        self.assertIn("平台ID", result.reply)
        self.assertEqual(harness.upserted, [])

    def test_blogger_upsert_maps_personal_traits_to_identity_tags(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(
            make_message(
                "博主-入库",
                "博主IP：清华AI小王冲一级\n平台：抖音\n平台ID：93130816637\n个人特征：清华AI硕、体育生、跑步\n粉丝数：3.7万",
            )
        )

        self.assertTrue(result.ok)
        fields = harness.upserted[0]
        self.assertEqual(fields["identity_tags"], ["清华AI硕", "体育生", "跑步"])
        self.assertEqual(fields["粉丝数(k)"], 37)
        self.assertIn("外部唯一ID：抖音:93130816637", result.reply)

    def test_blogger_upsert_preserves_explicit_current_metrics_summary(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(
            make_message(
                "博主-入库",
                "\n".join(
                    [
                        "账号名称：Ty.Mer",
                        "平台：抖音",
                        "平台ID：22654404058",
                        "当前指标摘要：粉丝数 901 人；关注 62；获赞 5810；作品 20",
                    ]
                ),
            )
        )

        self.assertTrue(result.ok)
        payload = harness._creator_profile_v2_payload(harness.upserted[0])
        self.assertEqual(payload["current_metrics_summary"], "粉丝数 901 人；关注 62；获赞 5810；作品 20")

    def test_blogger_auto_enrichment_generates_candidate_without_write(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(
            make_message(
                "博主-入库",
                "\n".join(
                    [
                        "平台：抖音",
                        "平台ID：22654404058",
                        "ID类型：抖音号",
                        "链接：https://v.douyin.com/SJjgn_2KjYs/",
                        "模式：自动补全",
                    ]
                ),
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "creator_profile_candidate_ready")
        self.assertEqual(harness.upserted, [])
        self.assertEqual(harness.generated_candidates[0]["platform"], "抖音")
        self.assertEqual(harness.generated_candidates[0]["platform_id"], "22654404058")
        self.assertIn("暂未写入", result.reply)
        self.assertIn("run_id：20260630T144713Z", result.reply)

    def test_blogger_confirm_write_uses_run_id_and_user_edits(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(
            make_message(
                "博主-入库",
                "\n".join(
                    [
                        "确认写入",
                        "run_id：20260630T144713Z",
                        "身份定位：清华中长跑创作者",
                    ]
                ),
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "creator_profile_confirmed_written")
        self.assertEqual(harness.confirmed_runs[0]["run_id"], "20260630T144713Z")
        self.assertEqual(harness.confirmed_runs[0]["user_edits"]["identity_summary"], "清华中长跑创作者")
        self.assertIn("指标快照：written", result.reply)

    def test_blogger_lookup_accepts_keyword_filter(self) -> None:
        harness = CreatorProfileHarness(
            [
                {
                    "record_id": "rec-1",
                    "fields": {
                        "博主IP": "清华AI小王冲一级",
                        "平台": "抖音",
                        "平台ID": "93130816637",
                        "关键词标签": "清华AI硕、体育生、跑步",
                    },
                }
            ]
        )

        result = harness.handle_博主(make_message("博主", "关键词：体育生"))

        self.assertTrue(result.ok)
        self.assertIn("外部唯一ID：抖音:93130816637", result.reply)

    def test_blogger_lookup_normalizes_case_and_spaces(self) -> None:
        harness = CreatorProfileHarness(
            [
                {
                    "record_id": "rec-1",
                    "fields": {
                        "博主IP": "清华AI小王冲一级",
                        "平台": "小红书",
                        "平台ID": "396554716",
                        "账号名称": "清华AI小王冲一级",
                        "主页链接": "https://example.com/xhs",
                    },
                }
            ]
        )

        result = harness.handle_博主(make_message("博主", "清华 ai 小王冲一级"))

        self.assertTrue(result.ok)
        self.assertIn("外部唯一ID：小红书:396554716", result.reply)
        self.assertIn("账号名称：清华AI小王冲一级", result.reply)

    def test_blogger_upsert_accepts_external_unique_id_field(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(
            make_message("博主-入库", "博主IP：清华AI小王冲一级\n外部唯一ID：抖音:93130816637\n个人特征：清华AI硕")
        )

        self.assertTrue(result.ok)
        fields = harness.upserted[0]
        self.assertEqual(fields["平台"], "抖音")
        self.assertEqual(fields["平台ID"], "93130816637")

    def test_blogger_upsert_routes_profile_details_to_structured_identity_not_legacy_persona(self) -> None:
        harness = CreatorProfileHarness()

        result = harness.handle_博主_入库(
            make_message(
                "博主-入库",
                "博主IP：清华AI小王冲一级\n平台：小红书\n平台ID：396554716\n身份定位：清华AI硕短跑创作者\n个人特征：体育生\n可创作身份卖点：短跑",
            )
        )

        self.assertTrue(result.ok)
        fields = harness.upserted[0]
        payload = harness._creator_profile_v2_payload(fields)
        self.assertEqual(fields["identity_summary"], "清华AI硕短跑创作者")
        self.assertEqual(fields["identity_tags"], ["体育生"])
        self.assertEqual(fields["story_usable_identity_points"], "短跑")
        self.assertNotIn("persona_summary", payload)
        self.assertNotIn("详情JSON", fields)

    def test_blogger_v2_payload_includes_structured_identity_fields(self) -> None:
        harness = CreatorProfileHarness()
        fields = harness._parse_creator_profile_fields(
            "账号名称：清华AI小王冲一级\n"
            "平台：小红书\n"
            "作者ID：小王\n"
            "主页链接：https://example.com/xiaowang\n"
            "身份定位：清华AI硕短跑博主\n"
            "身份标签：清华、AI、体育生、短跑、校园\n"
            "教育背景：清华大学AI硕士\n"
            "专业/能力领域：AI科研、短跑训练、自媒体创作\n"
            "创作者角色：校园AI运动博主\n"
            "公开表达边界：可说清华和短跑，不提私人联系方式\n"
            "可创作身份卖点：AI硕士冲短跑一级的反差"
        )

        payload = harness._creator_profile_v2_payload(fields)

        self.assertEqual(payload["identity_summary"], "清华AI硕短跑博主")
        self.assertEqual(payload["identity_tags"], ["清华", "AI", "体育生", "短跑", "校园"])
        self.assertEqual(payload["education_background"], "清华大学AI硕士")
        self.assertEqual(payload["expertise_domains"], ["AI科研", "短跑训练", "自媒体创作"])
        self.assertEqual(payload["creator_role"], "校园AI运动博主")
        self.assertEqual(payload["profile_url"], "https://example.com/xiaowang")
        self.assertEqual(payload["public_persona_boundaries"], "可说清华和短跑，不提私人联系方式")
        self.assertEqual(payload["story_usable_identity_points"], "AI硕士冲短跑一级的反差")
        self.assertNotIn("persona_summary", payload)


if __name__ == "__main__":
    unittest.main()
