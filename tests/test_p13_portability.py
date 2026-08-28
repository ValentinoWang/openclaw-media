from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROUTER_ROOT = ROOT / "openclaw-tag-router"
if str(ROUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ROUTER_ROOT))

from media_model.contract import (  # noqa: E402
    MEDIA_MODEL_CONTRACT_PATH_ENV,
    MediaModelContract,
    MediaModelContractError,
    resolve_media_model_contract_path,
)
from codex_maintenance_worker import CodexMaintenanceWorker  # noqa: E402
from openclaw_app.services import codex_maintenance_tasks as maintenance_tasks  # noqa: E402
from openclaw_app.services import media_archive_service  # noqa: E402
from openclaw_app.services import vlog_storage_service  # noqa: E402
from openclaw_app.services.codex_maintenance_tasks import agent_command  # noqa: E402
from openclaw_app.services.wardrobe_markdown_renderer import resolve_wardrobe_items_root  # noqa: E402
from selfmedia.deconstruct.viral_content.src.storyboard_images import resolve_image2_output_dir  # noqa: E402


PORTABILITY_SOURCES = (
    "media_model/contract.py",
    "selfmedia/deconstruct/viral_content/src/storyboard_images.py",
    "openclaw-tag-router/codex_maintenance_worker.py",
    "openclaw-tag-router/transcription-queue.js",
    "openclaw-tag-router/openclaw_app/services/codex_maintenance_tasks.py",
    "openclaw-tag-router/openclaw_app/services/media_archive_service.py",
    "openclaw-tag-router/openclaw_app/services/wardrobe_markdown_renderer.py",
    "openclaw-tag-router/openclaw_app/services/vlog_storage_service.py",
)
FORBIDDEN_HOST_PATHS = ("/Users/vsiyo", "/home/ubuntu")


def portability_violations(source: str) -> list[str]:
    return [path for path in FORBIDDEN_HOST_PATHS if path in source]


def test_p13_runtime_sources_do_not_embed_personal_or_fixed_host_paths() -> None:
    violations = {
        path: portability_violations((ROOT / path).read_text(encoding="utf-8"))
        for path in PORTABILITY_SOURCES
    }
    assert violations == {path: [] for path in PORTABILITY_SOURCES}


def test_p13_static_guard_calibrates_against_both_forbidden_path_families() -> None:
    assert portability_violations('Path("/Users/vsiyo/private")') == ["/Users/vsiyo"]
    assert portability_violations('Path("/home/ubuntu/private")') == ["/home/ubuntu"]


def test_non_personal_home_produces_portable_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "service-user"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("GPT_IMAGE2_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("OPENCLAW_WARDROBE_ITEMS_ROOT", raising=False)
    monkeypatch.delenv("OPENCLAW_UPLOADED_MEDIA_ROOTS", raising=False)
    monkeypatch.delenv("OPENCLAW_CODEX_TASK_ROOT", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("OPENCLAW_DEEPMATH_ENV_FILE", raising=False)

    assert resolve_image2_output_dir() == home / ".openclaw" / "generated" / "gpt-image-2"
    assert resolve_wardrobe_items_root() == home / "obsidian-日记" / "物品"
    assert vlog_storage_service.uploaded_media_roots() == [
        home / ".openclaw" / "media" / "inbound",
        home / "openclaw-feishu-gateway" / "downloads",
    ]
    assert maintenance_tasks.task_root() == home / ".openclaw" / "state" / "codex_maintenance_tasks"
    assert maintenance_tasks.codex_home() == home / ".codex"
    assert maintenance_tasks.deepmath_env_file() == home / ".openclaw-deepmath" / "openclaw.env"


def test_explicit_portability_environment_overrides_are_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    output = tmp_path / "storyboard-output"
    wardrobe = tmp_path / "wardrobe"
    uploaded_a = tmp_path / "uploaded-a"
    uploaded_b = tmp_path / "uploaded-b"
    task_root = tmp_path / "tasks"
    codex_home = tmp_path / "codex-home"
    deepmath_env = tmp_path / "deepmath.env"
    workdir = tmp_path / "workdir"
    archive_contract = ROOT / "media-agent-cli" / "generated_product_contract.py"
    monkeypatch.setenv(MEDIA_MODEL_CONTRACT_PATH_ENV, str(contract))
    monkeypatch.setenv("GPT_IMAGE2_OUTPUT_DIR", str(output))
    monkeypatch.setenv("OPENCLAW_WARDROBE_ITEMS_ROOT", str(wardrobe))
    monkeypatch.setenv("OPENCLAW_UPLOADED_MEDIA_ROOTS", os.pathsep.join((str(uploaded_a), str(uploaded_b))))
    monkeypatch.setenv("OPENCLAW_CODEX_TASK_ROOT", str(task_root))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("OPENCLAW_DEEPMATH_ENV_FILE", str(deepmath_env))
    monkeypatch.setenv("OPENCLAW_CODEX_WORKING_DIRECTORY", str(workdir))
    monkeypatch.setenv("OPENCLAW_BIN", "/opt/openclaw/bin/openclaw")
    monkeypatch.setenv("OPENCLAW_CODEX_BIN", "/opt/codex/bin/codex")
    monkeypatch.setenv("OPENCLAW_MEDIA_GENERATED_CONTRACT", str(archive_contract))

    assert resolve_media_model_contract_path() == contract
    assert resolve_image2_output_dir() == output
    assert resolve_wardrobe_items_root() == wardrobe
    assert vlog_storage_service.uploaded_media_roots() == [uploaded_a, uploaded_b]
    assert maintenance_tasks.task_root() == task_root
    assert maintenance_tasks.codex_home() == codex_home
    assert maintenance_tasks.deepmath_env_file() == deepmath_env
    assert maintenance_tasks.codex_working_directory() == workdir
    assert maintenance_tasks.openclaw_bin() == "/opt/openclaw/bin/openclaw"
    assert media_archive_service.resolve_archive_contract_path() == archive_contract
    command = agent_command(tmp_path / "task", "codex_" + "a" * 24, "test-provider")
    assert command[0] == "/opt/codex/bin/codex"
    assert command[command.index("--cd") + 1] == str(workdir)
    assert CodexMaintenanceWorker(root=task_root, working_directory=workdir).working_directory == workdir


def test_vlog_python_uses_explicit_value_or_running_interpreter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENCLAW_PYICLOUD_PYTHON", str(tmp_path / "pyicloud-python"))
    configured = vlog_storage_service.VlogStorageService(tmp_path / "configured", "Asia/Shanghai")
    assert configured.pyicloud_python == str(tmp_path / "pyicloud-python")

    monkeypatch.delenv("OPENCLAW_PYICLOUD_PYTHON")
    defaulted = vlog_storage_service.VlogStorageService(tmp_path / "defaulted", "Asia/Shanghai")
    assert defaulted.pyicloud_python == sys.executable


def test_missing_explicit_contract_path_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(MediaModelContractError, match="contract is unavailable"):
        _ = MediaModelContract(tmp_path / "missing-contract.json").data
