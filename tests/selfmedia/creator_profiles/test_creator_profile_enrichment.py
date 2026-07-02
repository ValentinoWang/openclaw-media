from __future__ import annotations

from selfmedia.creator_profiles import candidate_builder, extractor, metric_snapshot, resolver


def test_douyin_self_profile_is_blocked():
    assert resolver.is_douyin_self_profile_url("https://www.douyin.com/user/self?from_nav=1")
    assert not resolver.is_douyin_self_profile_url("https://www.douyin.com/user/MS4w")


def test_douyin_shortlink_redirect_url_extracts_sec_uid():
    url = "https://www.iesdouyin.com/share/user/MS4wLjABAAAABXs?sec_uid=MS4wLjABAAAABXs"
    assert resolver.douyin_profile_url_from_redirect_url(url) == "https://www.douyin.com/user/MS4wLjABAAAABXs"


def test_parse_douyin_profile_text_keeps_metric_labels_aligned():
    text = "\n".join(
        [
            "Ty.Mer",
            "关注",
            "62",
            "粉丝",
            "901",
            "获赞",
            "5810",
            "抖音号：22654404058",
            "IP属地：广东",
            "25岁",
            "清华大学普通生1500米 3000米记录保持者",
            "作品",
            "20",
        ]
    )
    parsed = extractor.parse_douyin_profile_text(text, "https://www.douyin.com/user/MS4w", title="Ty.Mer的抖音 - 抖音")
    assert parsed["author_id"] == "22654404058"
    assert parsed["account_name"] == "Ty.Mer"
    assert parsed["following_count"] == 62
    assert parsed["fans_count"] == 901
    assert parsed["total_favorited"] == 5810
    assert parsed["post_count"] == 20


def test_embedded_profile_parser_skips_visible_id_without_metrics():
    html = (
        '<span>抖音号：22654404058</span>'
        '<script>{"nickname":"Ty.Mer","awemeCount":20,"followingCount":62,'
        '"followerCount":901,"mplatformFollowersCount":901,'
        '"totalFavorited":5810,"uniqueId":"22654404058"}</script>'
    )
    parsed = extractor.parse_douyin_embedded_profile_data(html, "22654404058")
    assert parsed["account_name"] == "Ty.Mer"
    assert parsed["following_count"] == 62
    assert parsed["fans_count"] == 901
    assert parsed["total_favorited"] == 5810
    assert parsed["post_count"] == 20


def test_candidate_builder_keeps_candidate_only_and_all_v2_fields():
    resolver_result = {
        "ok": True,
        "platform": "抖音",
        "resolve_status": "exact_profile_resolved",
        "input_platform_id": "22654404058",
        "input_platform_id_type": "douyin_display_id",
        "resolved_author_id": "22654404058",
        "resolved_author_id_type": "douyin_display_id",
        "resolved_profile_url": "https://www.douyin.com/user/MS4w",
        "account_name": "Ty.Mer",
        "extracted_profile": {
            "author_id": "22654404058",
            "account_name": "Ty.Mer",
            "profile_url": "https://www.douyin.com/user/MS4w",
            "fans_count": 901,
            "following_count": 62,
            "total_favorited": 5810,
            "post_count": 20,
        },
    }
    llm_payload = {
        "field_candidates": {
            "identity_summary": {"value": "清华中长跑创作者", "evidence": ["bio"], "confidence": 0.8, "reason": "public bio"},
            "identity_tags": {"value": ["清华", "中长跑"], "evidence": ["bio"], "confidence": 0.8, "reason": "public bio"},
        }
    }

    candidate = candidate_builder.build_candidate(
        run_id="20260630T144713Z",
        resolver_result=resolver_result,
        evidence_uri="media://creator_profiles/douyin/22654404058/20260630T144713Z",
        use_llm=False,
        llm_payload=llm_payload,
    )

    payload = candidate["candidate_payload"]
    assert candidate["write_status"] == "candidate_only_not_written"
    assert len(payload) == 13
    assert payload["current_metrics_summary"] == "粉丝数 901 人；关注 62；获赞 5810；作品 20"
    assert payload["identity_tags"] == ["清华", "中长跑"]


def test_account_metric_snapshots_use_existing_metric_registry():
    payloads = metric_snapshot.build_account_metric_snapshots(
        account_name="Ty.Mer",
        creator_profile_id="creator_douyin_22654404058",
        platform="抖音",
        extracted_profile={"fans_count": 901, "total_favorited": 5810, "post_count": 20, "following_count": 62},
        evidence_uri="media://creator_profiles/douyin/22654404058/20260630T144713Z",
        collected_at="2026-06-30T14:47:13+00:00",
    )

    keys = {payload["metric_key"] for payload in payloads}
    assert keys == {"followers", "likes_total", "works_count"}
    assert "following_count" not in keys
    assert {payload["account_name"] for payload in payloads} == {"Ty.Mer"}
