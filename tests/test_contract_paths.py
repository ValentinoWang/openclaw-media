from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openclaw_app.account.contract import (
    REPOSITORY_CONTRACT_PATH as REPOSITORY_ACCOUNT_CONTRACT_PATH,
    load_account_contract,
    resolve_account_contract_path,
)
from openclaw_app.services.media_device_job_contract import (
    FROZEN_CONTRACT,
    REPOSITORY_FROZEN_CONTRACT,
)
from media_model.contract import (
    MediaModelContract,
    REPOSITORY_CREATION_RUN_DETAIL_CONTRACT_PATH,
    REPOSITORY_MEDIA_MODEL_CONTRACT_PATH,
    resolve_creation_run_detail_contract_path,
    resolve_media_model_contract_path,
)
from runtime.evidence.agent_results import (
    REPOSITORY_CONTRACT_PATH as REPOSITORY_AGENT_RESULTS_CONTRACT_PATH,
    agent_results_contract,
    resolve_agent_results_contract_path,
)


ROOT = Path(__file__).resolve().parents[1]
LEGACY_MEDIA_MODEL_PATH = "/home/ubuntu/docs/ai-harness/media-model-v2-contract.json"


def test_repository_contracts_are_the_default_and_loadable() -> None:
    assert REPOSITORY_MEDIA_MODEL_CONTRACT_PATH.is_file()
    assert REPOSITORY_CREATION_RUN_DETAIL_CONTRACT_PATH.is_file()
    assert resolve_media_model_contract_path() == REPOSITORY_MEDIA_MODEL_CONTRACT_PATH
    assert resolve_creation_run_detail_contract_path() == REPOSITORY_CREATION_RUN_DETAIL_CONTRACT_PATH
    assert MediaModelContract().path == REPOSITORY_MEDIA_MODEL_CONTRACT_PATH
    assert json.loads(REPOSITORY_CREATION_RUN_DETAIL_CONTRACT_PATH.read_text(encoding="utf-8"))["schema_version"] == "media_creation_run_detail_v1"


def test_repository_owned_product_account_and_evidence_contracts_are_loadable() -> None:
    assert FROZEN_CONTRACT == REPOSITORY_FROZEN_CONTRACT
    assert REPOSITORY_FROZEN_CONTRACT.is_file()
    product = json.loads(REPOSITORY_FROZEN_CONTRACT.read_text(encoding="utf-8"))
    assert product["contract_id"] == "openclaw_media_product_v1"
    assert len(product["api_operations"]) == 20
    assert resolve_account_contract_path() == REPOSITORY_ACCOUNT_CONTRACT_PATH
    assert load_account_contract().database_namespace == "openclaw_account"
    assert resolve_agent_results_contract_path() == REPOSITORY_AGENT_RESULTS_CONTRACT_PATH
    assert agent_results_contract().required_folders == ("media", "daily", "social", "knowledge", "public")


def test_product_client_mirrors_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "media-agent-cli/generate_product_clients.py"), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_explicit_environment_overrides_are_honored(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "media-model-contract.json"
    override.write_text(REPOSITORY_MEDIA_MODEL_CONTRACT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_MEDIA_MODEL_CONTRACT_PATH", str(override))
    assert resolve_media_model_contract_path() == override
    assert MediaModelContract().path == override


def test_runtime_readers_do_not_hardcode_the_legacy_model_contract_path() -> None:
    readers = (
        ROOT / "selfmedia/context/media_context.py",
        ROOT / "selfmedia/style/context_loader.py",
        ROOT / "openclaw-tag-router/openclaw_app/router/deletion_adapters/review_adapter.py",
    )
    assert all(LEGACY_MEDIA_MODEL_PATH not in reader.read_text(encoding="utf-8") for reader in readers)
