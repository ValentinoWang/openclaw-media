from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "runtime" / "cli" / "selfmedia.py"
TEST_TENANT_ID = "00000000-0000-4000-8000-000000000101"


def _run_cli(*args: str) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "smoke"
    assert payload["write_policy"] == "no_feishu_write_no_llm_generation"
    return payload


def test_creation_cli_smoke_validates_canonical_entrypoint_without_llm() -> None:
    payload = _run_cli(
        "run",
        "creation",
        "--text",
        "【创作>抖音】平台=抖音 类型=视频 赛道=旅行 账号=主账号 主题=天水麦积山石窟毕业旅行避坑提问",
        "--smoke",
        "--limit",
        "5",
        "--tenant-id",
        TEST_TENANT_ID,
    )
    assert payload["module"] == "selfmedia.creation.workflow"
    assert payload["request"]["platform"] == "抖音"  # type: ignore[index]


def test_retired_material_creation_cli_is_not_exposed() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(CLI), "material-creation", "--text", "旧素材创作"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr


def test_retired_creation_inspiration_cli_is_not_exposed() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(CLI), "creation-inspiration", "--text", "旧创作灵感"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr


def test_deconstruct_cli_smoke_validates_url_and_route_without_llm() -> None:
    payload = _run_cli(
        "run",
        "deconstruct",
        "--text",
        "【拆解】https://v.douyin.com/fKD3JbS5aXk/ 【再创作】田径服转场金牌视频",
        "--smoke",
    )
    assert payload["module"] == "selfmedia.deconstruct.viral_content"
    assert payload["source_url"] == "https://v.douyin.com/fKD3JbS5aXk/"


def test_id_business_cli_smoke_validates_trigger_without_llm() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "selfmedia.business.id_business",
            "ingest",
            "--text",
            "【商务>ID】小王 项目：HF绿氨糖",
            "--smoke",
            "--no-screenshot",
            "--tenant-id",
            TEST_TENANT_ID,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "smoke"
    assert payload["module"] == "selfmedia.business.id_business"
    assert payload["fields"]["作者ID"] == "小王"
    assert payload["fields"]["项目"] == "HF绿氨糖"
