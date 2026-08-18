"""Deterministic local dependency health report for the packaged CLI."""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as distribution_version
from typing import Any

from pydantic import BaseModel, ConfigDict


class DoctorItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str
    version: str | None = None
    executable: str | None = None


class TranscodeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str
    code: str


class FfmpegCheck(DoctorItem):
    codecs: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()
    transcode: TranscodeCheck = TranscodeCheck(status="blocked", code="not_checked")


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = 1
    status: str
    platform: str
    python: DoctorItem
    ffmpeg: FfmpegCheck
    ffprobe: DoctorItem
    opentimelineio: DoctorItem
    kdenlive: DoctorItem
    issues: tuple[str, ...]
    repair: str | None = None


class _Runner:
    which = staticmethod(shutil.which)

    @staticmethod
    def run(command: list[str]) -> tuple[int, str, str]:
        try:
            p = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
            return p.returncode, p.stdout, p.stderr
        except (OSError, subprocess.TimeoutExpired):
            return 1, "", ""


def _version(text: str) -> str | None:
    match = re.search(r"version\s+(\d+(?:\.\d+){1,3})", text, re.I)
    return match.group(1) if match else None


def run_doctor(*, runner: Any | None = None, python_version: tuple[int, ...] | None = None,
               otio_version: str | None = None, kdenlive: str | None = None) -> DoctorReport:
    r = _Runner() if runner is None else runner
    def safe_which(name: str) -> str | None:
        try:
            return r.which(name)
        except Exception:
            return None

    def safe_run(command: list[str]) -> tuple[int, str, str]:
        try:
            result = r.run(command)
            if not isinstance(result, tuple) or len(result) != 3:
                return 1, "", ""
            return int(result[0]), str(result[1] or ""), str(result[2] or "")
        except Exception:
            return 1, "", ""

    if otio_version is None:
        try:
            otio_version = distribution_version("OpenTimelineIO")
        except PackageNotFoundError:
            otio_version = None
    if kdenlive is None:
        kdenlive_path = safe_which("kdenlive")
        if kdenlive_path:
            rc, out, _ = safe_run(["kdenlive", "--version"])
            kdenlive = _version(out) if rc == 0 else "installed"
    py = tuple(sys.version_info[:3]) if python_version is None else tuple(python_version)
    issues: list[str] = []
    py_ok = (3, 12) <= py[:2] < (3, 14)
    if not py_ok: issues.append("python_unsupported")
    py_item = DoctorItem(status="ok" if py_ok else "unsupported", version=".".join(map(str, py)))

    ffmpeg_path = safe_which("ffmpeg")
    ffprobe_path = safe_which("ffprobe")
    ffmpeg_version = None
    codecs: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()
    transcode = TranscodeCheck(status="blocked", code="ffmpeg_missing")
    if not ffmpeg_path:
        issues.append("ffmpeg_missing")
    else:
        code, out, _ = safe_run(["ffmpeg", "-version"])
        ffmpeg_version = _version(out) if code == 0 else None
        if ffmpeg_version is None or tuple(map(int, ffmpeg_version.split(".")[:2])) < (6, 1): issues.append("ffmpeg_version_unsupported")
        _, codec_out, _ = safe_run(["ffmpeg", "-codecs"])
        _, filter_out, _ = safe_run(["ffmpeg", "-filters"])
        codecs = tuple(x for x in ("h264", "aac") if re.search(rf"\b{x}\b", codec_out))
        filters = tuple(x for x in ("scale", "aresample") if re.search(rf"\b{x}\b", filter_out))
        if set(codecs) != {"h264", "aac"}: issues.append("ffmpeg_codec_missing")
        if set(filters) != {"scale", "aresample"}: issues.append("ffmpeg_filter_missing")
        rc, _, _ = safe_run(["ffmpeg", "-f", "lavfi", "-i", "color=size=2x2:rate=1", "-frames:v", "1", "-f", "null", "-"])
        transcode = TranscodeCheck(status="ok" if rc == 0 else "blocked", code="ok" if rc == 0 else "transcode_failed")
        if rc != 0: issues.append("transcode_failed")
    if not ffprobe_path: issues.append("ffprobe_missing")
    probe_version = None
    if ffprobe_path:
        rc, out, _ = safe_run(["ffprobe", "-version"]); probe_version = _version(out) if rc == 0 else None
        if probe_version is None: issues.append("ffprobe_unavailable")
        elif tuple(map(int, probe_version.split(".")[:2])) < (6, 1): issues.append("ffprobe_version_unsupported")
    ffmpeg = FfmpegCheck(status="ok" if ffmpeg_path and not any(x.startswith("ffmpeg_") or x == "transcode_failed" for x in issues) else "blocked", version=ffmpeg_version, executable="ffmpeg" if ffmpeg_path else None, codecs=codecs, filters=filters, transcode=transcode)
    ffprobe = DoctorItem(status="ok" if probe_version else "blocked", version=probe_version, executable="ffprobe" if ffprobe_path else None)
    otio = DoctorItem(status="ok" if otio_version else "missing", version=otio_version)
    if not otio_version: issues.append("opentimelineio_missing")
    kden = DoctorItem(status="installed" if kdenlive else "not_installed", version=kdenlive)
    unique_issues = tuple(dict.fromkeys(issues))
    repair_map = {
        "python_unsupported": "Install CPython >=3.12,<3.14, then rerun openclaw-media doctor --json.",
        "opentimelineio_missing": "Install OpenTimelineIO==0.17.0, then rerun openclaw-media doctor --json.",
        "ffprobe_version_unsupported": "Install ffprobe >=6.1, then rerun openclaw-media doctor --json.",
        "ffprobe_unavailable": "Install a working ffprobe >=6.1, then rerun openclaw-media doctor --json.",
    }
    repair = None
    if unique_issues:
        if any(item in unique_issues for item in ("ffmpeg_missing", "ffmpeg_version_unsupported", "ffprobe_missing")):
            repair = "Install FFmpeg >=6.1 (including ffprobe), then rerun openclaw-media doctor --json."
        else:
            repair = repair_map.get(unique_issues[0], "Resolve the reported dependency issue, then rerun openclaw-media doctor --json.")
    return DoctorReport(status="healthy" if not unique_issues else "blocked", platform=platform.system().lower(), python=py_item, ffmpeg=ffmpeg, ffprobe=ffprobe, opentimelineio=otio, kdenlive=kden, issues=unique_issues, repair=repair)
