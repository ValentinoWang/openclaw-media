from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from _support import load_script_module


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "media-agent-cli/generate_product_clients.py"
GENERATED_CLIENTS = (
    ROOT / "media-agent-cli/generated_product_contract.py",
    ROOT / "media-agent-cli/src/openclaw_media/product_contract.py",
    ROOT / "openclaw-media/openclaw_media/generated_product_contract.py",
    ROOT / "media-agent-cli/generatedProductContract.ts",
    ROOT / "media-agent-cli/web/src/generated/productContract.ts",
    ROOT / "openclaw-bot-center/src/media/generatedProductContract.ts",
)


def _load_generator() -> ModuleType:
    return load_script_module("product_client_generator", GENERATOR)


def _client_hashes() -> dict[Path, str]:
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in GENERATED_CLIENTS}


def test_generator_resolves_a_valid_explicit_checkout_root_and_rejects_an_invalid_one(tmp_path: Path) -> None:
    module = _load_generator()
    checkout = tmp_path / "checkout"
    copied_generator = checkout / "media-agent-cli/generate_product_clients.py"
    copied_generator.parent.mkdir(parents=True)
    (checkout / "docs/ai-harness").mkdir(parents=True)
    shutil.copyfile(GENERATOR, copied_generator)
    shutil.copyfile(
        ROOT / "docs/ai-harness/openclaw-media-product-contract.json",
        checkout / "docs/ai-harness/openclaw-media-product-contract.json",
    )

    assert module.resolve_repository_root(
        environment={module.REPOSITORY_ROOT_ENV: str(checkout)},
        script_path=copied_generator,
    ) == checkout.resolve()

    with pytest.raises(RuntimeError, match=module.REPOSITORY_ROOT_ENV):
        module.resolve_repository_root(environment={module.REPOSITORY_ROOT_ENV: str(tmp_path / "missing")})


@pytest.mark.parametrize("use_explicit_root", (False, True))
def test_generator_check_is_portable_and_never_writes_generated_clients(
    tmp_path: Path,
    use_explicit_root: bool,
) -> None:
    environment = os.environ.copy()
    environment.pop("OPENCLAW_MEDIA_PRODUCT_CLIENTS_ROOT", None)
    if use_explicit_root:
        environment["OPENCLAW_MEDIA_PRODUCT_CLIENTS_ROOT"] = str(ROOT)
    before = _client_hashes()

    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert completed.stdout.strip() == "PASS: deterministic product clients"
    assert _client_hashes() == before
