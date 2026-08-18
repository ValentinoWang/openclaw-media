from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "qa"))
import check_openclaw_bot_center_release_process as guard


RELEASE_ROOT = Path(
    "/home/ubuntu/.openclaw/releases/"
    "openclaw-tag-router-media-tenant-20260807T130016Z-cm1-shared-balance"
)
SETTINGS = str(RELEASE_ROOT / "config" / "settings.yaml")


def production_properties() -> dict[str, str]:
    return {
        "MainPID": "758957",
        "ActiveState": "active",
        "SubState": "running",
        "ExecStart": f"argv[]=/usr/bin/python3 -m openclaw_app.server_cli --settings {SETTINGS}",
    }


def production_cmdline() -> list[str]:
    return [
        "/usr/bin/python3", "-m", "openclaw_app.server_cli", "--settings", SETTINGS,
        "--host", "127.0.0.1", "--port", "8787",
    ]


class ReleaseProcessGuardTests(unittest.TestCase):
    def test_selects_the_user_service_main_pid(self) -> None:
        self.assertEqual(
            guard.validate_release_process(
                production_properties(), production_cmdline(), str(RELEASE_ROOT), RELEASE_ROOT
            ),
            758957,
        )

    def test_rejects_isolated_server_cli_settings(self) -> None:
        d2_root = "/home/ubuntu/d2-dual-end-20260807"
        d2_cmdline = production_cmdline()
        d2_cmdline[d2_cmdline.index(SETTINGS)] = f"{d2_root}/settings.yaml"
        with self.assertRaisesRegex(guard.ReleaseProcessGuardError, "settings"):
            guard.validate_release_process(
                production_properties(), d2_cmdline, d2_root, RELEASE_ROOT
            )

    def test_rejects_inactive_service(self) -> None:
        properties = production_properties()
        properties["ActiveState"] = "inactive"
        with self.assertRaisesRegex(guard.ReleaseProcessGuardError, "not active"):
            guard.validate_release_process(
                properties, production_cmdline(), str(RELEASE_ROOT), RELEASE_ROOT
            )

    def test_rejects_manager_execstart_for_different_release(self) -> None:
        properties = production_properties()
        properties["ExecStart"] = properties["ExecStart"].replace(
            "openclaw-tag-router-media-tenant-20260807T130016Z-cm1-shared-balance",
            "openclaw-tag-router-media-tenant-old",
        )
        with self.assertRaisesRegex(guard.ReleaseProcessGuardError, "ExecStart"):
            guard.validate_release_process(
                properties, production_cmdline(), str(RELEASE_ROOT), RELEASE_ROOT
            )

    def test_source_does_not_scan_arbitrary_processes(self) -> None:
        source = Path(guard.__file__).read_text(encoding="utf-8")
        self.assertNotIn("pgrep", source)
        self.assertNotIn("ps -", source)


if __name__ == "__main__":
    unittest.main()
