#!/usr/bin/env python3
"""Save manually exported platform cookies into local-only secret files.

This helper intentionally does not read browser cookie stores. Export cookies
yourself from a browser extension, then pass the exported text/file here.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = ROOT / ".env.local"
DEFAULT_DISCOVER_DIRS = (Path.home() / "Downloads", ROOT)

PLATFORMS = {
    "douyin": {
        "label": "Douyin",
        "aliases": ("douyin", "抖音"),
        "domains": ("douyin.com",),
        "env_prefix": "DOUYIN",
        "header_path": ROOT / "secrets" / "douyin-cookie-header.txt",
        "json_path": ROOT / "private" / "douyin-cookies.json",
    },
    "xiaohongshu": {
        "label": "Xiaohongshu",
        "aliases": ("xiaohongshu", "xhs", "rednote", "小红书"),
        "domains": ("xiaohongshu.com", "xhscdn.com"),
        "env_prefix": "XIAOHONGSHU",
        "header_path": ROOT / "secrets" / "xiaohongshu-cookie-header.txt",
        "json_path": ROOT / "private" / "xiaohongshu-cookies.json",
    },
}
PLATFORM_ORDER = ("douyin", "xiaohongshu")


class CookieInputError(ValueError):
    """Raised when the supplied cookie export is empty or malformed."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Store a Douyin/Xiaohongshu cookie Header or Cookie-Editor JSON "
            "export in a local-only file and optionally update .env.local."
        )
    )
    parser.add_argument(
        "--platform",
        choices=("all", *PLATFORM_ORDER),
        default="all",
        help="Which platform cookie is being saved. Defaults to both platforms.",
    )
    parser.add_argument(
        "--format",
        choices=("auto", "header", "json"),
        default="auto",
        help="Export format from the browser extension. Defaults to auto-detect.",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Read exported cookie content from this file. Use only with one --platform.",
    )
    parser.add_argument(
        "--douyin-input-file",
        type=Path,
        help="Read Douyin exported cookie content from this file.",
    )
    parser.add_argument(
        "--xiaohongshu-input-file",
        type=Path,
        help="Read Xiaohongshu exported cookie content from this file.",
    )
    parser.add_argument(
        "--discover-dir",
        type=Path,
        action="append",
        help="Directory to scan for exported cookie files. Defaults to Downloads and this folder.",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Ask for hidden manual paste if no exported cookie file is found.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination file. Defaults to secrets/header or private/json path.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="Local env file to update. Use --no-env to skip.",
    )
    parser.add_argument(
        "--no-env",
        action="store_true",
        help="Only write the secret file; do not update .env.local.",
    )
    parser.add_argument(
        "--env-style",
        choices=("path", "value"),
        default="path",
        help=(
            "path writes <PREFIX>_COOKIE_HEADER_FILE/<PREFIX>_COOKIES_JSON_PATH; "
            "value writes <PREFIX>_COOKIE_HEADER directly for servers that require it."
        ),
    )
    return parser.parse_args()


def selected_platforms(args: argparse.Namespace) -> tuple[str, ...]:
    if args.platform == "all":
        return PLATFORM_ORDER
    return (args.platform,)


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CookieInputError(f"failed to read input file: {exc}") from exc


def discover_dirs(args: argparse.Namespace) -> tuple[Path, ...]:
    if args.discover_dir:
        return tuple(args.discover_dir)
    return DEFAULT_DISCOVER_DIRS


def format_discover_dirs(args: argparse.Namespace) -> str:
    return ", ".join(str(path) for path in discover_dirs(args))


def classify_cookie_export(platform_key: str, path: Path, raw: str) -> str | None:
    lower_name = path.name.lower()
    platform = PLATFORMS[platform_key]
    has_platform_alias = any(alias.lower() in lower_name for alias in platform["aliases"])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if has_platform_alias and "=" in raw:
            return "header"
        return None

    if not isinstance(data, (dict, list)):
        return None
    if has_platform_alias:
        return "json"

    domains = platform["domains"]
    cookie_items = data if isinstance(data, list) else data.get("cookies", [])
    if not isinstance(cookie_items, list):
        return None
    for item in cookie_items:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or item.get("host") or "").lower()
        if any(expected in domain for expected in domains):
            return "json"
    return None


def detect_export_format(raw: str) -> str | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "header" if "=" in raw else None
    return "json" if isinstance(data, (dict, list)) else None


def discover_cookie_export(args: argparse.Namespace, platform_key: str) -> tuple[str, str] | None:
    candidates: list[Path] = []
    suffixes = {".json", ".txt", ".header", ".cookie"}
    for directory in discover_dirs(args):
        if not directory.exists() or not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            lower_name = path.name.lower()
            if "cookie" not in lower_name and not any(
                alias.lower() in lower_name for alias in PLATFORMS[platform_key]["aliases"]
            ):
                continue
            candidates.append(path)

    newest: tuple[float, str, str] | None = None
    for path in candidates:
        raw = read_text_file(path)
        detected_format = classify_cookie_export(platform_key, path, raw)
        if detected_format is None:
            continue
        if args.format != "auto" and detected_format != args.format:
            continue
        mtime = path.stat().st_mtime
        if newest is None or mtime > newest[0]:
            newest = (mtime, raw, detected_format)

    if newest is None:
        return None
    return newest[1], newest[2]


def read_input(args: argparse.Namespace, platform_key: str, multi_platform: bool) -> tuple[str, str]:
    platform_input_file = getattr(args, f"{platform_key}_input_file")
    if platform_input_file:
        raw = read_text_file(platform_input_file)
        detected_format = classify_cookie_export(platform_key, platform_input_file, raw)
        if args.format != "auto":
            detected_format = args.format
        elif detected_format is None:
            detected_format = detect_export_format(raw)
        if detected_format is None:
            raise CookieInputError(f"could not detect cookie export format: {platform_input_file}")
        return raw, detected_format

    if args.input_file:
        if multi_platform:
            raise CookieInputError(
                "--input-file can only be used with one --platform; use "
                "--douyin-input-file and --xiaohongshu-input-file for both platforms"
            )
        raw = read_text_file(args.input_file)
        detected_format = classify_cookie_export(platform_key, args.input_file, raw)
        if args.format != "auto":
            detected_format = args.format
        elif detected_format is None:
            detected_format = detect_export_format(raw)
        if detected_format is None:
            raise CookieInputError(f"could not detect cookie export format: {args.input_file}")
        return raw, detected_format

    discovered = discover_cookie_export(args, platform_key)
    if discovered is not None:
        return discovered

    if not args.prompt and multi_platform:
        label = PLATFORMS[platform_key]["label"]
        raise CookieInputError(
            f"no exported {label} cookie file was found in: {format_discover_dirs(args)}. "
            "Export cookies with Cookie-Editor first, or pass --input-file / "
            f"--{platform_key}-input-file. Add --prompt to paste manually."
        )

    if not sys.stdin.isatty():
        if multi_platform:
            raise CookieInputError(
                "stdin can only provide one cookie export; use one --platform or "
                "--douyin-input-file and --xiaohongshu-input-file"
            )
        raw = sys.stdin.read().strip()
        if args.format == "auto":
            detected_format = "json" if raw.startswith(("{", "[")) else "header"
        else:
            detected_format = args.format
        return raw, detected_format

    if not args.prompt:
        label = PLATFORMS[platform_key]["label"]
        raise CookieInputError(
            f"no exported {label} cookie file was found in: {format_discover_dirs(args)}. "
            "Export cookies with Cookie-Editor first, or pass --input-file / "
            f"--{platform_key}-input-file. Add --prompt to paste manually."
        )

    if args.format in ("auto", "header"):
        label = PLATFORMS[platform_key]["label"]
        return getpass.getpass(f"Paste {label} Cookie header (input hidden): ").strip(), "header"

    if multi_platform:
        raise CookieInputError(
            "no exported JSON cookie files were found; use --douyin-input-file and "
            "--xiaohongshu-input-file or export files to Downloads"
        )

    print("Paste Cookie-Editor JSON, then press Ctrl-D:")
    return sys.stdin.read().strip(), "json"


def ensure_single_platform_output(args: argparse.Namespace, platforms: tuple[str, ...]) -> None:
    if args.output and len(platforms) > 1:
        raise CookieInputError("--output can only be used with one --platform")


def validate_multi_platform_args(args: argparse.Namespace, platforms: tuple[str, ...]) -> None:
    if len(platforms) == 1:
        return
    if args.input_file:
        raise CookieInputError(
            "--input-file can only be used with one --platform; use "
            "--douyin-input-file and --xiaohongshu-input-file for both platforms"
        )


def build_secret(
    args: argparse.Namespace,
    platform_key: str,
    raw: str,
    detected_format: str,
) -> tuple[Path, str, dict[str, str]]:
    platform = PLATFORMS[platform_key]
    env_prefix = platform["env_prefix"]

    if detected_format == "header":
        content = normalize_header(raw)
        output_path = args.output or platform["header_path"]
        env_entries = (
            {f"{env_prefix}_COOKIE_HEADER": content}
            if args.env_style == "value"
            else {f"{env_prefix}_COOKIE_HEADER_FILE": str(output_path)}
        )
    else:
        content = normalize_json(raw)
        output_path = args.output or platform["json_path"]
        env_entries = {f"{env_prefix}_COOKIES_JSON_PATH": str(output_path)}

    return output_path, content, env_entries


def normalize_header(raw: str) -> str:
    text = raw.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    if not text or "=" not in text:
        raise CookieInputError("cookie header is empty or does not look like name=value pairs")
    return text


def normalize_json(raw: str) -> str:
    if not raw:
        raise CookieInputError("cookie JSON is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CookieInputError(f"invalid JSON export: {exc}") from exc

    if not isinstance(data, (list, dict)):
        raise CookieInputError("cookie JSON must be an object or list")
    if isinstance(data, list) and data:
        first = data[0]
        if not isinstance(first, dict) or "name" not in first or "value" not in first:
            raise CookieInputError("cookie JSON list items should include name and value fields")
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def secure_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def update_env_file(path: Path, entries: dict[str, str]) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    keys = set(entries)
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in keys]
    if kept and kept[-1].strip():
        kept.append("")
    kept.extend(f"{key}={quote_env(value)}" for key, value in entries.items())

    secure_write(path, "\n".join(kept) + "\n")


def main() -> int:
    args = parse_args()
    platforms = selected_platforms(args)
    ensure_single_platform_output(args, platforms)
    validate_multi_platform_args(args, platforms)
    multi_platform = len(platforms) > 1
    env_entries: dict[str, str] = {}
    saved: list[tuple[str, Path]] = []

    for platform_key in platforms:
        raw, detected_format = read_input(args, platform_key, multi_platform)
        output_path, content, platform_env_entries = build_secret(
            args,
            platform_key,
            raw,
            detected_format,
        )
        secure_write(output_path, content)
        env_entries.update(platform_env_entries)
        saved.append((detected_format, output_path))

    if not args.no_env:
        update_env_file(args.env_file, env_entries)

    for detected_format, saved_path in saved:
        print(f"Saved {detected_format} cookie secret to: {saved_path}")
    if not args.no_env:
        print(f"Updated local env file: {args.env_file}")
    print("Secret values were not printed. Keep these files out of git.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CookieInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
