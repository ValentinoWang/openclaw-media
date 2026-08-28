from __future__ import annotations

import json

from openclaw_media import InstalledCatalog
from openclaw_media import cli


def _descriptor(catalog: InstalledCatalog, *, run_ref: str = "runs/cli", pipeline_index: int = 1) -> tuple[str, dict[str, object]]:
    pipeline = catalog.manifest["pipelines"][pipeline_index]
    return pipeline["pipeline_id"], {
        "version": pipeline["version"],
        "catalog_digest": pipeline["catalog_digest"],
        "run_ref": run_ref,
        "confirmed": True,
        "inputs": {"workspace_ref": "media"},
    }


def test_production_cli_wires_one_runtime_and_real_catalog_node(tmp_path, capsys):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "frame.png").write_bytes(b"not-a-real-image-but-a-local-media-file")
    pipeline_id, descriptor = _descriptor(InstalledCatalog())

    code = cli.main(
        ["run", pipeline_id, "--descriptor-json", json.dumps(descriptor), "--workspace", str(tmp_path)],
        package_version="0.2.0",
    )

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "succeeded"
    assert payload["receipt"]["run_ref"] == "runs/cli"
    assert payload["receipt"]["node_receipts"][0]["artifacts"][0]["artifact_ref"].startswith("artifacts/")
    assert str(tmp_path) not in captured.out
    assert "local_path" not in captured.out
    assert captured.err == ""


def test_cli_rejects_invalid_descriptor_without_runner_fallback(capsys):
    code = cli.main(
        ["run", "media.material.organize.v1", "--descriptor-json", "{broken"],
        package_version="0.2.0",
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == (
        "openclaw-media: error: invalid_descriptor — 流程请求描述格式无效；检查 --descriptor-json 后重试。\n"
    )
