from __future__ import annotations

import re
import unittest

from selfmedia.growth.dashboard import build_dashboard_projection


class MediaGrowthDashboardProjectionTest(unittest.TestCase):
    def test_builds_all_eight_projection_collections_without_legacy_queue(self) -> None:
        projection = build_dashboard_projection(
            [],
            source_assets=[
                {
                    "asset_id": "source-1",
                    "title": "一条可用素材",
                    "platform": "小红书",
                    "status": "ready",
                    "enabled": True,
                    "source_url": "https://example.com/source",
                }
            ],
            creation_runs=[
                {
                    "run_id": "run-1",
                    "input_summary": "生成一条创作稿",
                    "entrypoint": "【创作】",
                    "status": "success",
                }
            ],
            post_reviews=[
                {
                    "post_id": "post-1",
                    "platform": "抖音",
                    "review_node": "发布后 2 小时",
                    "performance_rating": "值得继续",
                    "key_metrics_summary": "完播表现稳定",
                }
            ],
            metric_snapshots=[
                {
                    "post_id": "post-1",
                    "metric_key": "like_rate",
                    "metric_value": 10.2,
                    "unit": "%",
                    "data_quality": "verified",
                }
            ],
            account_metric_snapshots=[
                {
                    "account_name": "Ty.Mer",
                    "platform": "小红书",
                    "metric_key": "followers",
                    "metric_value": 900,
                    "unit": "人",
                    "data_quality": "verified",
                }
            ],
            creator_profiles=[
                {
                    "creator_profile_id": "creator-1",
                    "platform": "小红书",
                    "author_id": "public-author-1",
                    "account_name": "跑者甲",
                    "creator_role": "校园跑者",
                    "identity_tags": ["跑步", "校园"],
                    "expertise_domains": ["马拉松"],
                    "profile_url": "https://example.com/creator-1",
                }
            ],
            generated_at="2026-07-28T00:00:00+00:00",
        )
        keys = (
            "accounts",
            "tracks",
            "creatorProfiles",
            "creatorMemberships",
            "sourceAssets",
            "creationRuns",
            "publishingPacks",
            "reviewSignals",
            "nextActions",
        )
        self.assertEqual(projection["schemaVersion"], "media_growth_dashboard_v2")
        self.assertEqual(projection["source"], "curated_projection")
        for key in keys:
            self.assertIn(key, projection)
            self.assertEqual(projection["counts"][key], len(projection[key]))
        for legacy_key in ("items", "reviewQueue", "publicItems"):
            self.assertNotIn(legacy_key, projection)
        self.assertRegex(projection["accounts"][0]["id"], r"^account_[a-f0-9]{16}$")
        self.assertRegex(projection["creatorProfiles"][0]["id"], r"^creator_[a-f0-9]{16}$")
        self.assertEqual(projection["creatorProfiles"][0]["accountName"], "跑者甲")
        self.assertNotIn("author_id", projection["creatorProfiles"][0])
        self.assertNotIn("creatorProfileCount", projection)
        self.assertRegex(projection["sourceAssets"][0]["id"], r"^asset_[a-f0-9]{16}$")
        self.assertNotIn("source-1", str(projection))

    def test_h03_cannot_create_tracks_and_only_counts_registered_tracks(self) -> None:
        eligible = {
            "artifact_id": "pack-1",
            "artifact_type": "PublishingPack",
            "status": "ready",
            "visibility": "ops",
            "quality_status": "cleaned",
            "front_end_eligible": True,
            "display_title": "今晚发布包",
            "display_summary": "标题、正文与话题已齐备",
            "platform": "抖音",
            "track_id": "校园内容",
            "readiness": {"ready": True, "missing": []},
        }
        projection = build_dashboard_projection([eligible], growth_summaries=[eligible])
        self.assertEqual(projection["provenance"]["visibleGrowthSummaries"], 1)
        self.assertEqual(projection["tracks"], [])
        self.assertEqual(len(projection["publishingPacks"]), 1)
        self.assertTrue(projection["publishingPacks"][0]["readiness"]["ready"])

        registered = build_dashboard_projection(
            [eligible],
            growth_summaries=[eligible],
            track_registry=[
                {
                    "track_id": "校园内容",
                    "track_name": "校园内容",
                    "description": "校园内容赛道",
                    "platform_scope": ["抖音"],
                    "status": "active",
                }
            ],
        )
        self.assertEqual(len(registered["tracks"]), 1)
        self.assertEqual(registered["tracks"][0]["artifactCount"], 1)
        self.assertEqual(registered["tracks"][0]["dataSource"], "07_TrackRegistry_赛道注册表")

        missing_local = build_dashboard_projection([], growth_summaries=[eligible])
        self.assertEqual(missing_local["provenance"]["visibleGrowthSummaries"], 0)
        self.assertEqual(missing_local["tracks"], [])
        self.assertEqual(missing_local["publishingPacks"], [])

        hidden_local = build_dashboard_projection(
            [{**eligible, "visibility": "debug"}],
            growth_summaries=[eligible],
        )
        self.assertEqual(hidden_local["provenance"]["visibleGrowthSummaries"], 0)

    def test_memberships_join_only_explicit_track_and_creator_owners(self) -> None:
        projection = build_dashboard_projection(
            [],
            track_registry=[{"track_id": "t1", "track_name": "跑步", "status": "active"}],
            creator_profiles=[
                {
                    "creator_profile_id": "creator-1",
                    "account_name": "跑者甲",
                    "platform": "抖音",
                    "author_id": "public-author-1",
                }
            ],
            track_creator_memberships=[
                {
                    "membership_id": "m1",
                    "track_id": "t1",
                    "creator_profile_id": "creator-1",
                    "role": "标杆账号",
                    "fit_score": 92,
                    "fit_reason": "已有运营证据",
                    "status": "active",
                }
            ],
        )

        self.assertEqual(len(projection["creatorMemberships"]), 1)
        self.assertEqual(len(projection["creatorProfiles"]), 1)
        self.assertEqual(len(projection["trackGraph"]["nodes"]), 2)
        self.assertEqual(len(projection["trackGraph"]["edges"]), 1)
        membership_coverage = next(item for item in projection["coverage"] if item["key"] == "creatorMemberships")
        self.assertEqual(membership_coverage["status"], "available")
        self.assertIn("已确认 1 条证据式关系", membership_coverage["reason"])
        edge = projection["trackGraph"]["edges"][0]
        node_ids = {node["id"] for node in projection["trackGraph"]["nodes"]}
        self.assertIn(edge["source"], node_ids)
        self.assertIn(edge["target"], node_ids)

    def test_unlinked_creator_remains_visible_without_a_graph_edge(self) -> None:
        projection = build_dashboard_projection(
            [],
            track_registry=[{"track_id": "t1", "track_name": "跑步", "status": "active"}],
            creator_profiles=[
                {
                    "creator_profile_id": "creator-unlinked",
                    "platform": "抖音",
                    "author_id": "public-author-unlinked",
                    "account_name": "未关联博主",
                    "identity_tags": ["跑步"],
                }
            ],
        )
        self.assertEqual(len(projection["creatorProfiles"]), 1)
        self.assertEqual(projection["creatorProfiles"][0]["accountName"], "未关联博主")
        self.assertEqual(projection["creatorMemberships"], [])
        self.assertEqual(len(projection["trackGraph"]["nodes"]), 1)
        self.assertEqual(projection["trackGraph"]["edges"], [])
        membership_coverage = next(item for item in projection["coverage"] if item["key"] == "creatorMemberships")
        self.assertEqual(membership_coverage["status"], "empty")
        self.assertIn("当前没有可证明关系", membership_coverage["reason"])

    def test_orphan_membership_fails_projection(self) -> None:
        with self.assertRaisesRegex(ValueError, "orphan relation"):
            build_dashboard_projection(
                [],
                track_registry=[{"track_id": "t1", "track_name": "跑步", "status": "active"}],
                creator_profiles=[],
                track_creator_memberships=[
                    {
                        "membership_id": "m1",
                        "track_id": "t1",
                        "creator_profile_id": "missing",
                        "role": "标杆账号",
                        "fit_score": 92,
                        "status": "active",
                    }
                ],
            )

    def test_projection_blocks_local_and_private_urls(self) -> None:
        projection = build_dashboard_projection(
            [],
            source_assets=[
                {
                    "asset_id": "a",
                    "title": "素材",
                    "source_url": "media://SourceAsset/a/result.json",
                    "source_doc_link": "http://127.0.0.1/private",
                }
            ],
        )
        asset = projection["sourceAssets"][0]
        self.assertEqual(asset["sourceUrl"], "")
        self.assertNotIn("documentUrl", asset)
        self.assertIsNone(re.search(r"(?:/home/|media://|127\.0\.0\.1)", str(projection)))


if __name__ == "__main__":
    unittest.main()
