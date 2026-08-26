from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "selfmedia/creator_profiles/anchor_crawler.py"
SPEC = importlib.util.spec_from_file_location("crawl_creator_anchors", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_parse_chinese_count():
    assert MODULE.parse_chinese_count("1.2万") == 12000
    assert MODULE.parse_chinese_count("68") == 68
    assert MODULE.parse_chinese_count("3k") == 3000


def test_choose_xhs_candidate_prefers_exact_platform_id():
    candidates = [
        {"text": "清华AI小王冲一级\n小红书号：111\n粉丝・100", "href": "https://a"},
        {"text": "清华AI小王冲一级\n小红书号：396554716\n粉丝・1.2万", "href": "https://b"},
    ]
    chosen = MODULE.choose_xhs_candidate(
        candidates,
        creator_name="清华AI小王冲一级",
        platform_id="396554716",
    )
    assert chosen == candidates[1]


def test_parse_xhs_candidate():
    parsed = MODULE.parse_xhs_candidate(
        "清华AI小王冲一级\n你的关注\n2天前更新\n小红书号：396554716\n粉丝・1.2万\n笔记・68\n已关注",
        "https://www.xiaohongshu.com/user/profile/5f39f7b8?xsec_token=abc",
    )
    assert parsed["account_name"] == "清华AI小王冲一级"
    assert parsed["author_id"] == "396554716"
    assert parsed["fans_count"] == 12000
    assert parsed["post_count"] == 68


def test_douyin_self_profile_is_blocked():
    assert MODULE.is_douyin_self_profile_url("https://www.douyin.com/user/self?from_nav=1")
    assert MODULE.is_douyin_self_profile_url("https://www.douyin.com/user/self")
    assert not MODULE.is_douyin_self_profile_url("https://www.douyin.com/user/MS4wLjAB")


def test_douyin_redirect_url_builds_profile_url_from_sec_uid():
    url = (
        "https://www.iesdouyin.com/share/user/MS4wLjABAAAABXs"
        "?from=web_code_link&sec_uid=MS4wLjABAAAABXs"
    )
    assert MODULE.douyin_profile_url_from_redirect_url(url) == "https://www.douyin.com/user/MS4wLjABAAAABXs"


def test_choose_douyin_candidate_ignores_self_profile():
    candidates = [
        {"text": "我的", "href": "https://www.douyin.com/user/self?from_nav=1"},
        {"text": "Ty.Mer\n抖音号：22654404058", "href": "https://www.douyin.com/user/MS4wLjAB"},
    ]
    chosen = MODULE.choose_douyin_candidate(candidates, creator_name="Ty.Mer", platform_id="22654404058")
    assert chosen == candidates[1]


def test_parse_douyin_profile_text_extracts_display_id_and_metrics():
    text = "\n".join(
        [
            "Ty.Mer",
            "关注",
            "62",
            "粉丝",
            "900",
            "获赞",
            "1200",
            "抖音号：22654404058",
            "清华大学普通生1500米 3000米记录保持者",
            "作品",
            "20",
        ]
    )
    parsed = MODULE.parse_douyin_profile_text(
        text,
        "https://www.douyin.com/user/MS4wLjAB",
        title="Ty.Mer的抖音 - 抖音",
    )
    assert parsed["account_name"] == "Ty.Mer"
    assert parsed["author_id"] == "22654404058"
    assert parsed["fans_count"] == 900
    assert parsed["following_count"] == 62
    assert parsed["total_favorited"] == 1200
    assert parsed["post_count"] == 20


def test_parse_douyin_embedded_profile_data_requires_exact_unique_id():
    html = (
        'self.__pace_f.push([1,"{\\"user\\":{\\"nickname\\":\\"Other\\",'
        '\\"awemeCount\\":1,\\"followerCount\\":3,\\"uniqueId\\":\\"000\\"}}"]);'
        'self.__pace_f.push([1,"{\\"user\\":{\\"nickname\\":\\"Ty.Mer\\",'
        '\\"desc\\":\\"清华大学普通生1500米 3000米记录保持者\\",'
        '\\"awemeCount\\":20,\\"followingCount\\":62,\\"followerCount\\":901,'
        '\\"mplatformFollowersCount\\":901,\\"totalFavorited\\":5810,'
        '\\"uniqueId\\":\\"22654404058\\"}}"]);'
    )
    parsed = MODULE.parse_douyin_embedded_profile_data(html, "22654404058")
    assert parsed["author_id"] == "22654404058"
    assert parsed["account_name"] == "Ty.Mer"
    assert parsed["bio"] == "清华大学普通生1500米 3000米记录保持者"
    assert parsed["fans_count"] == 901
    assert parsed["post_count"] == 20
    assert parsed["following_count"] == 62
    assert parsed["total_favorited"] == 5810
