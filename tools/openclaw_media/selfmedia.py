#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


BRIDGE = Path("/home/ubuntu/selfmedia-tools/tools/selfmedia_openclaw.py")
CONTENT_OS_SCRIPT_MODEL = "gpt-5.5"
CONTENT_OS_SCRIPT_THINKING = "xhigh"
CONTENT_OS_SCRIPT_AGENT = "feishu-media"
CONTENT_OS_SCRIPT_CWD = "/home/ubuntu/openclaw-agents/media"
CONTENT_OS_SCRIPT_TIMEOUT = "1800"
CREATIVE_GENERATION_COMMANDS = ("creation-inspiration", "material-creation")
SOCIAL_THEORY_TAGS = ("/女性爱", "/性兴趣", "/风控", "/性资源", "/行动")
DEPRECATED_SOCIAL_THEORY_TAGS = ("/风控量表",)
SLASH_THEORY_RE = re.compile(r"/([\w\u4e00-\u9fff-]+)")
THEORY_TAG_SUFFIXES = ("进行分析", "来分析", "分析一下", "分析")


def clean_slash_theory_tag(value: str) -> str:
    tag = value.strip().strip("/")
    for suffix in THEORY_TAG_SUFFIXES:
        if tag.endswith(suffix) and len(tag) > len(suffix):
            tag = tag[: -len(suffix)]
            break
    return f"/{tag.strip()}" if tag.strip() else ""


def social_theory_matches(text: str) -> list[str]:
    normalized = re.sub(r"https?://\S+", " ", text or "")
    slash_tags = {clean_slash_theory_tag(match) for match in SLASH_THEORY_RE.findall(normalized)}
    return [tag for tag in (*DEPRECATED_SOCIAL_THEORY_TAGS, *SOCIAL_THEORY_TAGS) if tag in slash_tags]


def reject_social_theory_tags(argv: list[str]) -> None:
    text = " ".join(argv)
    matched = social_theory_matches(text)
    if matched:
        if any(tag in DEPRECATED_SOCIAL_THEORY_TAGS for tag in matched):
            raise SystemExit(
                "社交理论入口不属于 media/爆款入口，已拒绝执行："
                + "、".join(tag for tag in matched if tag in DEPRECATED_SOCIAL_THEORY_TAGS)
            )
        raise SystemExit(
            "社交理论标签只能由 social bot 调用，media/爆款入口拒绝执行："
            + "、".join(matched)
        )


def argv_uses_creative_generation_model(argv: list[str]) -> bool:
    if any(command in argv for command in CREATIVE_GENERATION_COMMANDS):
        return True
    if "creation" in argv and ("run" in argv or "creation" in argv):
        return True
    return False


def main() -> None:
    reject_social_theory_tags(sys.argv[1:])
    command = [sys.executable, str(BRIDGE), *sys.argv[1:]]
    env = os.environ.copy()
    if argv_uses_creative_generation_model(sys.argv[1:]):
        env.setdefault("SELFMEDIA_CREATION_OPENCLAW_AGENT", CONTENT_OS_SCRIPT_AGENT)
        env.setdefault("SELFMEDIA_CREATION_OPENCLAW_MODEL", CONTENT_OS_SCRIPT_MODEL)
        env.setdefault("SELFMEDIA_CREATION_OPENCLAW_THINKING", CONTENT_OS_SCRIPT_THINKING)
        env.setdefault("SELFMEDIA_CREATION_OPENCLAW_TIMEOUT", CONTENT_OS_SCRIPT_TIMEOUT)
        env.setdefault("SELFMEDIA_CREATION_OPENCLAW_CWD", CONTENT_OS_SCRIPT_CWD)
    completed = subprocess.run(command, text=True, check=False, env=env)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
