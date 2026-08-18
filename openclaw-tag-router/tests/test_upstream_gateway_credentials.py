from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from openclaw_app.services.upstream_gateway_credentials import (
    CanonicalFileSecretStore,
    PlatformCredentialService,
    UpstreamCredentialError,
)


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _service(root: Path) -> tuple[PlatformCredentialService, Path, Path]:
    active = root / "api-token"
    staged = root / "api-token.staged"
    _write_secret(active, "platform-secret-one")
    service = PlatformCredentialService(
        root / "state.json",
        CanonicalFileSecretStore(active, staged),
    )
    service.adopt_existing()
    return service, active, staged


def test_platform_rotation_replaces_canonical_secret_without_plaintext_state() -> None:
    with tempfile.TemporaryDirectory() as root:
        service, active, staged = _service(Path(root))
        _write_secret(staged, "platform-secret-two")

        rotated = service.rotate_from_staged(lambda value: value.endswith("two"))

        assert rotated.version == 2
        assert service.resolve() == "platform-secret-two"
        assert active.read_text(encoding="utf-8") == "platform-secret-two"
        assert not staged.exists()
        raw = service.state_path.read_text(encoding="utf-8")
        assert "platform-secret-one" not in raw and "platform-secret-two" not in raw


def test_failed_rotation_keeps_old_secret_and_deletes_staging_file() -> None:
    with tempfile.TemporaryDirectory() as root:
        service, active, staged = _service(Path(root))
        _write_secret(staged, "rejected-platform-secret")

        with pytest.raises(UpstreamCredentialError):
            service.rotate_from_staged(lambda _value: False)

        assert active.read_text(encoding="utf-8") == "platform-secret-one"
        assert service.health()["version"] == 1
        assert not staged.exists()


def test_revoke_fails_closed_and_health_never_exposes_reference() -> None:
    with tempfile.TemporaryDirectory() as root:
        service, active, _staged = _service(Path(root))
        assert set(service.health()) == {"provider", "status", "version"}

        retired = service.revoke()

        assert retired.status == "retired"
        assert not active.exists()
        with pytest.raises(UpstreamCredentialError):
            service.resolve()
        assert "platform-secret-one" not in json.dumps(service.health.__annotations__)


def test_symlink_and_permissive_secret_files_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as root:
        base = Path(root)
        target = base / "target"
        _write_secret(target, "platform-secret")
        active = base / "api-token"
        active.symlink_to(target)
        service = PlatformCredentialService(
            base / "state.json",
            CanonicalFileSecretStore(active, base / "api-token.staged"),
        )
        with pytest.raises(UpstreamCredentialError):
            service.adopt_existing()

        active.unlink()
        _write_secret(active, "platform-secret")
        active.chmod(0o640)
        with pytest.raises(UpstreamCredentialError):
            service.adopt_existing()
