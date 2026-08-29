from common.platform_links import classify_post_link


def test_classifies_supported_post_links() -> None:
    cases = [
        ("https://www.douyin.com/video/1234567890123456789", "douyin", "post", "1234567890123456789"),
        ("https://www.douyin.com/note/1234567890123456789", "douyin", "post", "1234567890123456789"),
        ("https://www.xiaohongshu.com/explore/65abc123456789", "xiaohongshu", "post", "65abc123456789"),
        ("https://www.xiaohongshu.com/discovery/item/65abc123456789", "xiaohongshu", "post", "65abc123456789"),
    ]
    for url, platform, kind, content_id in cases:
        result = classify_post_link(url)
        assert result["platform"] == platform
        assert result["kind"] == kind
        assert result["content_id"] == content_id
        assert result["canonical_url"]


def test_classifies_profiles_without_treating_them_as_posts() -> None:
    for url, platform in (
        ("https://www.douyin.com/user/abc", "douyin"),
        ("https://www.xiaohongshu.com/user/profile/abc", "xiaohongshu"),
    ):
        result = classify_post_link(url)
        assert result["platform"] == platform
        assert result["kind"] == "profile"
        assert result["content_id"] is None


def test_keeps_supported_short_links_unresolved() -> None:
    for url, platform in (
        ("https://v.douyin.com/AbCdEf/", "douyin"),
        ("https://xhslink.com/a/AbCdEf", "xiaohongshu"),
    ):
        result = classify_post_link(url)
        assert result["platform"] == platform
        assert result["kind"] == "short"
        assert result["content_id"] is None


def test_rejects_garbage_and_unrecognized_paths() -> None:
    for url in ("", "not-a-url", "https://example.com/video/123", "https://www.douyin.com/live/123"):
        result = classify_post_link(url)
        assert result["kind"] == "unknown"
        assert result["content_id"] is None
