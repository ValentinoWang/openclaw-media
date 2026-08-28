from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_vault.vault import MediaVault, MediaVaultError, resolve_media_vault_root


TENANT_ID = "618ff8c4-cc5a-4034-a2c5-226e3ad6cd37"
VAULT_SOURCE = Path(__file__).resolve().parents[1] / "media_vault" / "vault.py"


class MediaVaultPortabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_root_uses_portable_user_state_without_creating_it(self) -> None:
        home = self.tmp_path / "service-user"
        with patch.dict(os.environ, {"HOME": str(home)}, clear=True):
            root = resolve_media_vault_root()

            self.assertEqual(root, (home / ".openclaw" / "media_vault").resolve())
            self.assertFalse(root.exists())
            self.assertEqual(MediaVault(tenant_id=TENANT_ID).vault_root, root)
            self.assertFalse(root.exists())

    def test_default_root_has_no_personal_host_path_residue(self) -> None:
        source = VAULT_SOURCE.read_text(encoding="utf-8")

        for forbidden in ("/" + "home" + "/ubuntu", "/" + "Users" + "/vsiyo"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_environment_override_expands_and_resolves(self) -> None:
        home = self.tmp_path / "service-user"
        with patch.dict(
            os.environ,
            {"HOME": str(home), "OPENCLAW_MEDIA_VAULT_ROOT": "~/configured/../vault"},
            clear=True,
        ):
            self.assertEqual(resolve_media_vault_root(), (home / "vault").resolve())
            self.assertEqual(MediaVault(tenant_id=TENANT_ID).vault_root, (home / "vault").resolve())

    def test_default_root_is_stable_across_working_directories(self) -> None:
        home = self.tmp_path / "service-user"
        first_cwd = self.tmp_path / "first"
        second_cwd = self.tmp_path / "second"
        first_cwd.mkdir()
        second_cwd.mkdir()
        original_cwd = Path.cwd()
        try:
            with patch.dict(os.environ, {"HOME": str(home)}, clear=True):
                os.chdir(first_cwd)
                first_root = resolve_media_vault_root()
                os.chdir(second_cwd)
                second_root = resolve_media_vault_root()
        finally:
            os.chdir(original_cwd)

        self.assertEqual(first_root, (home / ".openclaw" / "media_vault").resolve())
        self.assertEqual(second_root, first_root)

    def test_empty_environment_override_fails_closed(self) -> None:
        with patch.dict(os.environ, {"OPENCLAW_MEDIA_VAULT_ROOT": "   "}, clear=True):
            with self.assertRaisesRegex(MediaVaultError, "OPENCLAW_MEDIA_VAULT_ROOT must not be empty"):
                resolve_media_vault_root()


if __name__ == "__main__":
    unittest.main()
