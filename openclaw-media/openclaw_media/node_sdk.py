from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class OutputBoundaryError(ValueError):
    """A node attempted to publish outside its declared output contract."""


def validate_outputs(
    declared_outputs: list[Mapping[str, Any]],
    produced_outputs: Mapping[str, Mapping[str, Any]],
) -> None:
    declarations = {item["name"]: item for item in declared_outputs}
    unknown = sorted(set(produced_outputs) - set(declarations))
    if unknown:
        raise OutputBoundaryError(f"undeclared outputs: {', '.join(unknown)}")

    for name, descriptor in produced_outputs.items():
        declaration = declarations[name]
        if declaration.get("upload") == "forbidden":
            raise OutputBoundaryError(f"upload forbidden for output: {name}")
        if descriptor.get("cloud_bytes", 0) != 0:
            raise OutputBoundaryError(f"descriptor uploaded bytes for output: {name}")
        mime = descriptor.get("mime_type")
        allowed_mime = declaration.get("mime_types", [])
        if mime not in allowed_mime:
            raise OutputBoundaryError(f"MIME type is not allowed for output: {name}")
        size = descriptor.get("size_bytes")
        if not isinstance(size, int) or size < 0:
            raise OutputBoundaryError(f"invalid size for output: {name}")
        if size > declaration["max_bytes"]:
            raise OutputBoundaryError(f"output exceeds max_bytes: {name}")
        path = descriptor.get("local_path")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise OutputBoundaryError(f"output requires an absolute local_path: {name}")
