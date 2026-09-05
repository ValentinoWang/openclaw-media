"""Redacted administrator status for platform browser-cookie configuration."""

from __future__ import annotations

import os
import stat as stat_module
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


SCHEMA_VERSION = "media_web_business_pages_v2"
SELFMEDIA_ROOT = Path(
    os.getenv("OPENCLAW_SELFMEDIA_ROOT") or Path(__file__).resolve().parents[4]
).expanduser()
PLATFORMS = ("douyin", "xiaohongshu")
# NOTE (H8 dedup survey): these Chinese strings are cookie-store LOOKUP KEYS
# passed straight into id_business.load_playwright_cookies() /
# load_cookie_candidates() below -- not display labels. They are
# deliberately NOT wired up to common/platform_labels.py: changing the
# value here changes what key this service looks up in the on-disk cookie
# store, which would silently stop finding already-saved cookies.
_PLATFORM_LABELS = {"douyin": "抖音", "xiaohongshu": "小红书"}


def _load_cookie_runtime() -> Any:
    if str(SELFMEDIA_ROOT) not in sys.path:
        sys.path.insert(0, str(SELFMEDIA_ROOT))
    from selfmedia.business import id_business

    return id_business


def _load_cookies(platform: str) -> list[dict[str, Any]]:
    return _load_cookie_runtime().load_playwright_cookies(_PLATFORM_LABELS[platform])


def _candidate_paths(platform: str) -> Sequence[Path]:
    return _load_cookie_runtime().load_cookie_candidates(_PLATFORM_LABELS[platform])


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


class AdminPlatformCookiesService:
    """Read effective cookie health without ever returning cookie material."""

    def __init__(
        self,
        *,
        loader: Callable[[str], Sequence[dict[str, Any]]] | None = None,
        candidate_paths: Callable[[str], Sequence[Path]] | None = None,
    ) -> None:
        self._loader = loader or _load_cookies
        self._candidate_paths = candidate_paths or _candidate_paths

    def _item(self, platform: str) -> dict[str, Any]:
        existing_mtimes: list[float] = []
        metadata_error = False
        try:
            paths = tuple(self._candidate_paths(platform))
        except Exception:
            paths = ()
            metadata_error = True

        for path in paths:
            try:
                file_stat = path.stat()
            except FileNotFoundError:
                continue
            except OSError:
                metadata_error = True
                continue
            if stat_module.S_ISREG(file_stat.st_mode):
                existing_mtimes.append(file_stat.st_mtime)

        updated_at = _timestamp(max(existing_mtimes)) if existing_mtimes else None
        base = {
            "platform": platform,
            "configured": bool(existing_mtimes),
            "updatedAt": updated_at,
            "validationStatus": "error",
            "errorCode": "cookie_metadata_unavailable" if metadata_error else None,
        }
        if metadata_error:
            return base

        try:
            cookies = self._loader(platform)
            is_valid = bool(cookies)
        except Exception:
            base["errorCode"] = "cookie_validation_error"
            return base

        if is_valid:
            base.update(configured=True, validationStatus="valid", errorCode=None)
        elif existing_mtimes:
            base.update(configured=True, validationStatus="invalid", errorCode="cookie_invalid")
        else:
            base.update(validationStatus="missing", errorCode="cookie_not_configured")
        return base

    def get_admin_platform_cookies(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "platforms": [self._item(platform) for platform in PLATFORMS],
        }
