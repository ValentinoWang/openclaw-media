"""Deterministic, fail-closed release metadata for the canonical CLI wheel."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from email import policy
from email.parser import Parser
from importlib.resources import files
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet

from .catalog import catalog_digest

PACKAGE_NAME = "openclaw-media"
MIN_WEB_API_VERSION = "1.0.0"
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){2}(?:[-+][0-9A-Za-z.-]+)?$")
_RELEASE_REQUIREMENTS_RESOURCE = "data/release_requirements.json"


class ReleaseError(ValueError):
    """A wheel is not a publishable canonical CLI release."""


@dataclass(frozen=True)
class CLIRelease:
    package_name: str
    version: str
    requires_python: str
    console_script: str
    wheel_sha256: str
    catalog_digest: str
    min_web_api_version: str
    dependency_sbom: tuple[dict[str, str], ...]
    sbom_sha256: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["dependency_sbom"] = [dict(item) for item in self.dependency_sbom]
        return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _metadata(zf: zipfile.ZipFile) -> tuple[str, Any]:
    names = [name for name in zf.namelist() if name.endswith(".dist-info/METADATA")]
    if len(names) != 1:
        raise ReleaseError("wheel must contain exactly one dist-info METADATA")
    return names[0], Parser(policy=policy.default).parsestr(zf.read(names[0]).decode())


def _canonical_python_requirement() -> SpecifierSet:
    """Read the generated requirement from the installed package data."""
    try:
        payload = json.loads(files("openclaw_media").joinpath(_RELEASE_REQUIREMENTS_RESOURCE).read_text(encoding="utf-8"))
        requirement = payload["requires_python"]
        if set(payload) != {"requires_python"} or not isinstance(requirement, str):
            raise TypeError
        return SpecifierSet(requirement)
    except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseError("canonical Python requirement unavailable") from exc


def build_release(wheel: str | Path, *, min_web_api_version: str = MIN_WEB_API_VERSION) -> CLIRelease:
    path = Path(wheel)
    if not path.is_file() or path.suffix != ".whl":
        raise ReleaseError("wheel path is missing or not a .whl")
    wheel_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(path) as zf:
            _, metadata = _metadata(zf)
            if metadata.get("Name") != PACKAGE_NAME:
                raise ReleaseError("wheel distribution name drift")
            version = metadata.get("Version", "")
            requires_python = metadata.get("Requires-Python", "")
            try:
                requirement_matches = SpecifierSet(requires_python) == _canonical_python_requirement()
            except (ValueError, ReleaseError):
                requirement_matches = False
            if not _VERSION_RE.fullmatch(version) or not requirement_matches:
                raise ReleaseError("wheel version or Requires-Python drift")
            scripts = [line.split(" = ", 1) for line in zf.read(next((n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")), "")).decode().splitlines() if line.startswith("openclaw-media = ")]
            if scripts != [["openclaw-media", "openclaw_media.cli:main"]]:
                raise ReleaseError("wheel must expose exactly one canonical console script")
            raw = json.loads(zf.read("openclaw_media/data/pipelines.json"))
            digest = catalog_digest(raw["pipelines"])
            if raw.get("catalog_digest") != digest or any(item.get("catalog_digest") != digest for item in raw["pipelines"]):
                raise ReleaseError("packaged catalog digest drift")
            dependencies = tuple(sorted(({"name": value.split(";", 1)[0].strip().split("==", 1)[0], "specifier": value.split(";", 1)[0].strip().split("==", 1)[1] if "==" in value.split(";", 1)[0] else ""} for value in metadata.get_all("Requires-Dist", [])), key=lambda item: item["name"].lower()))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ReleaseError("wheel contents are incomplete or invalid") from exc
    if not _VERSION_RE.fullmatch(min_web_api_version):
        raise ReleaseError("minimum Web API version is invalid")
    sbom_hash = hashlib.sha256(_canonical(list(dependencies))).hexdigest()
    return CLIRelease(PACKAGE_NAME, version, requires_python, "openclaw-media=openclaw_media.cli:main", wheel_hash, digest, min_web_api_version, dependencies, sbom_hash)


def write_release_metadata(wheel: str | Path, output: str | Path) -> CLIRelease:
    release = build_release(wheel)
    Path(output).write_text(json.dumps(release.to_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    release = build_release(args.wheel)
    payload = json.dumps(release.to_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
