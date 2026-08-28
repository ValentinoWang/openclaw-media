from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openclaw_app.services.deepmath_resources import (
    DeepMathResourceContractError,
    default_resource_config_path,
    load_resource_config,
    resolve_resource_config_path,
)


class Wave8ConfigPortabilityTest(unittest.TestCase):
    def test_default_resource_config_is_bundled_with_router_repository(self) -> None:
        path = default_resource_config_path()

        self.assertEqual(path.name, "deepmath_ceo_thinking_resources.json")
        self.assertEqual(path.parent.name, "config")
        self.assertEqual(load_resource_config(path).tenant_key, "deepmath")

    def test_explicit_resource_config_path_is_relative_to_settings_and_does_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "config" / "settings.yaml"
            settings_path.parent.mkdir()
            explicit_path = resolve_resource_config_path(
                "missing-resource.json", settings_path=settings_path
            )

            self.assertEqual(explicit_path, settings_path.parent / "missing-resource.json")
            with self.assertRaises(DeepMathResourceContractError):
                load_resource_config(explicit_path)

    def test_empty_explicit_resource_config_path_is_rejected(self) -> None:
        with self.assertRaises(DeepMathResourceContractError):
            resolve_resource_config_path("", settings_path="settings.yaml")


if __name__ == "__main__":
    unittest.main()
