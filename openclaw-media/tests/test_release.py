import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from openclaw_media.catalog import catalog_digest
from openclaw_media.release import ReleaseError, build_release


PROJECT_ROOT = Path(__file__).parents[1]
PRODUCT_CONTRACT = PROJECT_ROOT.parent / "docs/ai-harness/openclaw-media-product-contract.json"


def _uv_executable() -> str:
    """Resolve uv without depending on a login-shell PATH."""
    candidate = shutil.which("uv")
    if candidate:
        return candidate
    fallback = Path.home() / ".local" / "bin" / "uv"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return os.fspath(fallback)
    pytest.skip("uv is required for fresh-wheel release validation")


def _wheel(tmp_path: Path, *, name="openclaw-media", version="0.2.0", requires_python=">=3.12,<3.14", catalog=None, corrupt=False):
    wheel = tmp_path / "openclaw_media-0.2.0-py3-none-any.whl"
    pipelines = catalog or [{"pipeline_id": "p", "version": "1.0.0", "nodes": [{"node_id": "n", "depends_on": [], "type": "x"}]}]
    digest = catalog_digest(pipelines)
    manifest = {"catalog_digest": ("sha256:" + "0" * 64 if corrupt else digest), "pipelines": [dict(item, catalog_digest=digest) for item in pipelines]}
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: {requires_python}\nRequires-Dist: pydantic==2.11.7\nRequires-Dist: httpx==0.28.1\n\n"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("openclaw_media-0.2.0.dist-info/METADATA", metadata)
        zf.writestr("openclaw_media-0.2.0.dist-info/entry_points.txt", "[console_scripts]\nopenclaw-media = openclaw_media.cli:main\n")
        zf.writestr("openclaw_media/data/pipelines.json", json.dumps(manifest))
    return wheel


def test_release_is_deterministic_and_reads_catalog(tmp_path):
    wheel = _wheel(tmp_path)
    first, second = build_release(wheel), build_release(wheel)
    assert first == second
    assert first.package_name == "openclaw-media"
    assert first.console_script == "openclaw-media=openclaw_media.cli:main"
    assert first.catalog_digest.startswith("sha256:")
    assert first.wheel_sha256 == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert [item["name"] for item in first.dependency_sbom] == ["httpx", "pydantic"]


def test_python_requires_matches_canonical_product_contract():
    contract = json.loads(PRODUCT_CONTRACT.read_text(encoding="utf-8"))
    package_metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    packaged_requirements = json.loads((PROJECT_ROOT / "openclaw_media/data/release_requirements.json").read_text(encoding="utf-8"))

    assert package_metadata["requires-python"] == contract["release"]["python_requires"]
    assert packaged_requirements["requires_python"] == contract["release"]["python_requires"]
    assert packaged_requirements["requires_python"] == package_metadata["requires-python"]


def test_release_dependency_is_pinned_and_declared_in_project():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "packaging==26.2" in project["dependencies"]


def test_fresh_wheel_runs_release_validation_outside_source_tree(tmp_path):
    dist = tmp_path / "dist"
    target = tmp_path / "installed"
    outside = tmp_path / "outside"
    dist.mkdir()
    target.mkdir()
    outside.mkdir()
    uv = _uv_executable()
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    wheel = next(dist.glob("*.whl"))
    subprocess.run([uv, "pip", "install", "--python", os.fspath(sys.executable), "--no-deps", "--target", str(target), os.fspath(wheel)], check=True, capture_output=True, text=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.fspath(target)
    result = subprocess.run(
        [os.fspath(sys.executable), "-c", "from pathlib import Path; from openclaw_media.release import build_release; import sys; assert not (Path.cwd() / 'pyproject.toml').exists(); print(build_release(Path(sys.argv[1]).resolve()).version)", os.fspath(wheel)],
        cwd=outside,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "0.2.0"


@pytest.mark.parametrize("kwargs", [{"name": "other"}, {"version": "dev"}])
def test_release_rejects_metadata_drift(tmp_path, kwargs):
    with pytest.raises(ReleaseError):
        build_release(_wheel(tmp_path, **kwargs))


def test_release_rejects_catalog_drift(tmp_path):
    with pytest.raises(ReleaseError):
        build_release(_wheel(tmp_path, corrupt=True))


def test_release_accepts_setuptools_normalized_requirement_order(tmp_path):
    release = build_release(_wheel(tmp_path, requires_python="<3.14,>=3.12"))
    assert release.requires_python == "<3.14,>=3.12"


def test_release_rejects_semantic_python_requirement_drift(tmp_path):
    with pytest.raises(ReleaseError):
        build_release(_wheel(tmp_path, requires_python=">=3.12,<3.15"))
