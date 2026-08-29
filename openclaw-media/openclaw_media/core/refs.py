from __future__ import annotations

import re
from pathlib import PurePosixPath

_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")
_IDENTITY = re.compile(r"sha256:[0-9a-f]{64}")


def ref_path(value: object) -> PurePosixPath | None:
    """Return a validated PurePosixPath for a safe cross-device relative reference, or None.

    A value is safe when it is a non-empty str, contains no backslashes, is not a
    Windows drive-absolute path, is not POSIX-absolute, has no empty/"."/".." segments
    or embedded NUL bytes in any segment, and round-trips through as_posix() unchanged
    (rejecting inputs such as "a//b" or "./a" that need normalization to be safe).
    """
    if not isinstance(value, str) or "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        return None
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} or "\x00" in part for part in path.parts)
        or path.as_posix() != value
    ):
        return None
    return path


def is_relative_ref(value: object) -> bool:
    """Return True when value is a safe relative reference (see ref_path)."""
    return ref_path(value) is not None


def relative_ref(value: object) -> str | None:
    """Return value as a safe relative reference string, or None."""
    path = ref_path(value)
    return str(path) if path is not None else None


def issue_ref(value: object) -> str | None:
    """Return value unchanged when it is a safe relative reference, else None.

    Intended for surfacing an untrusted ref inside an issue/error record without
    ever propagating an unsafe value.
    """
    return value if is_relative_ref(value) else None
