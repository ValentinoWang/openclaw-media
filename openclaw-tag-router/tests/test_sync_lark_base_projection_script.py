from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.sync_lark_base_projection import _load_registry_table_bindings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "sync_lark_base_projection.py"


def test_sync_script_can_start_outside_project_root(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--execute" in result.stdout


def test_registry_v2_array_resolves_current_source_asset_binding(tmp_path: Path) -> None:
    registry_path = tmp_path / "media-bitable-registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": "media_operations_registry_v2",
                "tables": [
                    {
                        "table_key": "source_asset",
                        "base_token": "base_current",
                        "table_id": "tbl_current_assets",
                        "observed_feishu_table_display_name": "02A_SourceAssets_素材源",
                        "target_feishu_table_display_name": "A01_素材",
                        "postgres_target": "assets",
                        "binding_status": "readback_verified_current",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    base_token, bindings = _load_registry_table_bindings(registry_path)

    assert base_token == "base_current"
    assert bindings["assets"]["table_id"] == "tbl_current_assets"
    assert bindings["assets"]["table_name"] == "02A_SourceAssets_素材源"
    assert bindings["assets"]["target_table_name"] == "A01_素材"
