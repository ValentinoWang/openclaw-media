from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path("/home/ubuntu/selfmedia-tools/tools/openclaw_media/crawl_creator_anchors.py")
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
