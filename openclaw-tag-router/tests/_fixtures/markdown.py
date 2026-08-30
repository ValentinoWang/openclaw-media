"""Shared frontmatter-writing fixture for router tests.

test_deletion.py and test_deletion_phase2_adapters.py each hand-rolled a
``write_frontmatter`` that only rendered one of ``list``/``dict`` values
correctly (list for the former, dict for the latter) and didn't escape
scalars that need it (a colon or newline in a string) -- the files these
suites write are read back by production's real YAML-based frontmatter
reader, so an under-escaped fixture can silently pass while producing
invalid YAML.

``write_frontmatter`` here mirrors production's
content_os_project_lifecycle.py ``_write_frontmatter`` payload shape
exactly (``yaml.safe_dump(frontmatter, allow_unicode=True,
sort_keys=False)``), skipping only the temp-file + ``os.replace`` atomic
swap that a test fixture doesn't need.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _yaml_safe(value: Any) -> Any:
    """Recursively stringify pathlib.Path values.

    YAML has no native representation for a Path object, but several
    existing call sites in these suites build frontmatter with real Path
    values (obsidian_path, media_dir, weekly_path, and lists containing
    them) -- the two hand-rolled serializers this replaces tolerated that
    silently (an f-string implicitly stringifies), so this keeps those
    call sites working unchanged against yaml.safe_dump.
    """

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _yaml_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_yaml_safe(item) for item in value]
    return value


def write_frontmatter(path: Path, frontmatter: dict[str, Any], body: str = "") -> None:
    rendered = yaml.safe_dump(_yaml_safe(frontmatter), allow_unicode=True, sort_keys=False).strip()
    payload = f"---\n{rendered}\n---\n\n{body.lstrip()}".rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
