from pathlib import Path

import pytest

from openclaw_app.services.production_release_manifest import (
    ManifestValidationError,
    build_manifest,
)


@pytest.mark.parametrize("path", ["app/./main.py", "app//main.py", "app/main.py/"])
def test_manifest_builder_rejects_noncanonical_relative_path_segments(
    tmp_path: Path,
    path: str,
) -> None:
    with pytest.raises(ManifestValidationError) as caught:
        build_manifest(tmp_path, file_paths=(path,))

    assert caught.value.code == "PATH_TRAVERSAL"
