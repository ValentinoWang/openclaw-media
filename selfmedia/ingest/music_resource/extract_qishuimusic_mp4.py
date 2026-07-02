#!/usr/bin/env python3
"""
Download MP4/M4A/MP3 from a Qishu Music (汽水音乐) share link.

Usage:
  python3 extract_qishuimusic_mp4.py "<share text or URL>" -o ./downloads
  python3 extract_qishuimusic_mp4.py - --list < share.txt
  python3 extract_qishuimusic_mp4.py --curl "<curl command>" -o ./downloads
  python3 extract_qishuimusic_mp4.py "<share text>" --auto -o ./downloads
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import socket
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Iterator, List


DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

URL_RE = re.compile(r"https?://[^\s<>'\"]+")
ESCAPED_URL_RE = re.compile(r"https?:\\\/\\\/[^\s<>'\"]+")

TRAILING_PUNCT = "\"'<>)]}>,.;"


class DownloadError(Exception):
    pass


def read_text_input(arg: str | None) -> str:
    if arg and arg != "-":
        return arg
    return sys.stdin.read()


def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_curl_command(curl_text: str) -> tuple[str, dict[str, str]]:
    tokens = shlex.split(curl_text)
    if not tokens:
        raise RuntimeError("Empty curl command.")
    if tokens[0] == "curl":
        tokens = tokens[1:]

    headers: dict[str, str] = {}
    url = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("-H", "--header"):
            i += 1
            if i < len(tokens):
                header_line = tokens[i]
                if ":" in header_line:
                    key, value = header_line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    if key.lower() == "cookie":
                        key = "Cookie"
                    elif key.lower() == "user-agent":
                        key = "User-Agent"
                    elif key.lower() == "referer":
                        key = "Referer"
                    headers[key] = value
        elif token in ("-A", "--user-agent"):
            i += 1
            if i < len(tokens):
                headers["User-Agent"] = tokens[i]
        elif token in ("-e", "--referer", "--referrer"):
            i += 1
            if i < len(tokens):
                headers["Referer"] = tokens[i]
        elif token in ("-b", "--cookie"):
            i += 1
            if i < len(tokens):
                headers["Cookie"] = tokens[i]
        elif token == "--url":
            i += 1
            if i < len(tokens):
                url = tokens[i]
        elif token.startswith("http://") or token.startswith("https://"):
            url = token
        i += 1

    if not url:
        raise RuntimeError("No URL found in curl command.")
    return url, headers


def build_playwright_cookies(share_url: str, cookie_header: str | None) -> list[dict]:
    if not cookie_header:
        return []
    cookies = []
    for chunk in cookie_header.split(";"):
        if "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append({"name": name, "value": value, "url": share_url})
    return cookies


def pick_request_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    mapping = {
        "user-agent": "User-Agent",
        "referer": "Referer",
        "cookie": "Cookie",
    }
    picked: dict[str, str] = {}
    for key, value in headers.items():
        normalized = mapping.get(key.lower())
        if normalized and value:
            picked[normalized] = value
    return picked


def capture_media_candidates_with_playwright(
    share_url: str,
    user_agent: str,
    cookie_header: str | None,
    timeout: int,
) -> tuple[list[str], dict[str, dict[str, str]], str]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: python -m pip install playwright "
            "and then: python -m playwright install chromium"
        ) from exc

    candidates: set[str] = set()
    request_headers_by_url: dict[str, dict[str, str]] = {}
    final_url = share_url

    def on_request(request) -> None:
        if request.url not in request_headers_by_url:
            request_headers_by_url[request.url] = dict(request.headers)

    def on_response(response) -> None:
        url = response.url
        headers = response.headers
        content_type = headers.get("content-type", "")
        if (
            is_media_content_type(content_type)
            or "mpegurl" in content_type.lower()
            or response.request.resource_type == "media"
            or any(ext in url.lower() for ext in [".mp4", ".m4a", ".mp3", ".m3u8"])
        ):
            candidates.add(url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=user_agent)
        cookies = build_playwright_cookies(share_url, cookie_header)
        if cookies:
            context.add_cookies(cookies)
        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(share_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(2000)
            final_url = page.url
        finally:
            context.close()
            browser.close()

    return list(candidates), request_headers_by_url, final_url


def extract_first_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    return clean_url(match.group(0))


def clean_url(url: str) -> str:
    url = html.unescape(url)
    while url and url[-1] in TRAILING_PUNCT:
        url = url[:-1]
    return normalize_url(url)


def normalize_url(url: str) -> str:
    url = (
        url.replace("\\u002F", "/")
        .replace("\\u003D", "=")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )
    if url.startswith("//"):
        url = "https:" + url
    return url


def build_headers(
    user_agent: str,
    referer: str | None,
    cookie: str | None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    if extra_headers:
        for key, value in extra_headers.items():
            if value:
                headers[key] = value
    return headers


def fetch_url(
    url: str, headers: dict[str, str], timeout: int
) -> tuple[str, str, bytes]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read()
    return final_url, content_type, data


def decode_html(data: bytes, content_type: str) -> str:
    encoding = "utf-8"
    match = re.search(r"charset=([^\s;]+)", content_type, re.I)
    if match:
        encoding = match.group(1).strip().strip('"')
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def is_media_content_type(content_type: str) -> bool:
    ct = content_type.lower()
    return ct.startswith("video/") or ct.startswith("audio/")


def find_balanced_braces(text: str, start: int) -> str | None:
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def extract_embedded_json(html_text: str) -> List[str]:
    json_blobs: List[str] = []

    for match in re.finditer(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html_text,
        re.S | re.I,
    ):
        json_blobs.append(match.group(1).strip())

    for match in re.finditer(
        r'<script[^>]+id="__NUXT__"[^>]*>(.*?)</script>',
        html_text,
        re.S | re.I,
    ):
        json_blobs.append(match.group(1).strip())

    markers = [
        "window.__INITIAL_STATE__",
        "window.__NUXT__",
        "SIGI_STATE",
    ]
    for marker in markers:
        idx = html_text.find(marker)
        while idx != -1:
            brace_start = html_text.find("{", idx)
            if brace_start == -1:
                break
            blob = find_balanced_braces(html_text, brace_start)
            if blob:
                json_blobs.append(blob)
                idx = html_text.find(marker, brace_start + len(blob))
            else:
                break

    return json_blobs


def extract_urls_from_json(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for value in obj.values():
            yield from extract_urls_from_json(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from extract_urls_from_json(item)
    elif isinstance(obj, str):
        value = normalize_url(obj)
        if value.startswith("http://") or value.startswith("https://") or value.startswith("//"):
            yield value


def collect_candidates(html_text: str) -> List[str]:
    candidates: set[str] = set()

    unescaped = html.unescape(html_text)
    for match in URL_RE.finditer(unescaped):
        candidates.add(clean_url(match.group(0)))

    for match in ESCAPED_URL_RE.finditer(unescaped):
        candidates.add(clean_url(match.group(0)))

    for blob in extract_embedded_json(unescaped):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        for url in extract_urls_from_json(data):
            candidates.add(clean_url(url))

    return sorted(candidates)


def score_url(url: str, prefer_ext: str) -> int:
    lower = url.lower()
    score = 0
    if any(ext in lower for ext in [".mp4", ".m4a", ".mp3", ".m3u8"]):
        score += 10
    if "mime_type=audio" in lower or "audio" in lower:
        score += 6
    if "mime_type=video" in lower or "video" in lower:
        score += 4
    if any(key in lower for key in ["play", "download", "music", "song"]):
        score += 2
    if any(ext in lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js"]):
        score -= 10
    if prefer_ext and prefer_ext in lower:
        score += 3
    return score


def choose_candidate(
    candidates: List[str], prefer_ext: str, select: int | None
) -> tuple[str, List[tuple[int, str, int]]]:
    ranked = [(url, score_url(url, prefer_ext)) for url in candidates]
    ranked.sort(key=lambda item: (item[1], len(item[0])), reverse=True)
    if not ranked:
        raise RuntimeError("No candidates found.")

    sorted_list: List[tuple[int, str, int]] = []
    for idx, (url, score) in enumerate(ranked):
        sorted_list.append((idx, url, score))

    if select is not None:
        if select < 0 or select >= len(sorted_list):
            raise RuntimeError(
                f"--select {select} out of range (0-{len(sorted_list)-1})."
            )
        return sorted_list[select][1], sorted_list

    return sorted_list[0][1], sorted_list


def read_cookie_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = name.strip().strip(".")
    return name or "qishui"


def filename_from_headers(headers: dict[str, str]) -> str | None:
    content_disp = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disp, re.I)
    if match:
        return urllib.parse.unquote(match.group(1))
    match = re.search(r'filename="?([^";]+)"?', content_disp)
    if match:
        return match.group(1)
    return None


def guess_extension(url: str, content_type: str, prefer_ext: str) -> str:
    lower = url.lower()
    for ext in [".mp4", ".m4a", ".mp3", ".m3u8"]:
        if ext in lower:
            return ext

    ct = content_type.lower()
    if "audio/mp4" in ct:
        return ".m4a"
    if "video/mp4" in ct:
        return ".mp4"
    if "audio/mpeg" in ct:
        return ".mp3"
    if "application/vnd.apple.mpegurl" in ct or "application/x-mpegurl" in ct:
        return ".m3u8"

    return f".{prefer_ext}" if prefer_ext else ""


def unique_path(directory: str, filename: str) -> str:
    candidate = os.path.join(directory, filename)
    if not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(filename)
    for i in range(1, 10000):
        candidate = os.path.join(directory, f"{stem}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("Unable to find a free filename.")


def download_file(
    url: str,
    output_path: str,
    headers: dict[str, str],
    timeout: int,
    max_timeouts: int,
) -> dict[str, str]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        meta = {
            "content_type": resp.headers.get("Content-Type", ""),
            "content_length": resp.headers.get("Content-Length", ""),
            "content_disposition": resp.headers.get("Content-Disposition", ""),
        }
        with open(output_path, "wb") as f:
            timeout_hits = 0
            while True:
                try:
                    chunk = resp.read(1024 * 1024)
                except (TimeoutError, socket.timeout) as exc:
                    timeout_hits += 1
                    if timeout_hits >= max_timeouts:
                        raise DownloadError("read_timeout") from exc
                    continue
                if not chunk:
                    break
                timeout_hits = 0
                f.write(chunk)
    return meta


def download_m3u8_with_ffmpeg(
    url: str, output_path: str, headers: dict[str, str]
) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install ffmpeg or omit --ffmpeg.")

    header_lines = []
    for key in ["User-Agent", "Cookie", "Referer"]:
        if key in headers:
            header_lines.append(f"{key}: {headers[key]}")
    header_arg = "\r\n".join(header_lines) + "\r\n" if header_lines else ""

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-headers",
        header_arg,
        "-i",
        url,
        "-c",
        "copy",
        output_path,
    ]
    subprocess.run(cmd, check=True, timeout=int(os.getenv("QISHUI_FFMPEG_DOWNLOAD_TIMEOUT_SECONDS", "1800")))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Download MP4/M4A/MP3 from a Qishu Music share link."
    )
    parser.add_argument(
        "share",
        nargs="?",
        help="Share text or URL. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="./qishui_downloads",
        help="Directory to save downloads. (default: ./qishui_downloads)",
    )
    parser.add_argument(
        "--filename",
        help="Override output filename (extension auto-added if missing).",
    )
    parser.add_argument(
        "--cookie",
        help="Cookie header value for authenticated access.",
    )
    parser.add_argument(
        "--cookie-file",
        help="Read Cookie header value from file.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help="User-Agent header.",
    )
    parser.add_argument(
        "--referer",
        help="Referer header override.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Network timeout in seconds. (default: 60)",
    )
    parser.add_argument(
        "--read-retries",
        type=int,
        default=3,
        help="Retry count when socket read times out. (default: 3)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List candidate media URLs and exit.",
    )
    parser.add_argument(
        "--select",
        type=int,
        help="Select candidate index from --list output.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the selected media URL and exit.",
    )
    parser.add_argument(
        "--save-html",
        help="Save the share page HTML to a file for debugging.",
    )
    parser.add_argument(
        "--media-url",
        help="Download this media URL directly (skip share parsing).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Use Playwright to auto-capture the media request.",
    )
    parser.add_argument(
        "--curl",
        help="Paste a 'Copy as cURL' command from devtools. Use '-' for stdin.",
    )
    parser.add_argument(
        "--curl-file",
        help="Read a cURL command from a file.",
    )
    parser.add_argument(
        "--ffmpeg",
        action="store_true",
        help="Use ffmpeg to download m3u8 URLs if found.",
    )

    args = parser.parse_args(argv)
    prefer_ext = ""

    if args.curl and args.curl_file:
        print("Use only one of --curl or --curl-file.", file=sys.stderr)
        return 2

    cookie = args.cookie
    if args.cookie_file:
        cookie = read_cookie_from_file(args.cookie_file)

    curl_text = None
    if args.curl:
        curl_text = read_text_input(args.curl)
    elif args.curl_file:
        curl_text = read_text_file(args.curl_file)

    media_url = None
    referer = None
    extra_headers: dict[str, str] | None = None

    if curl_text:
        media_url, extra_headers = parse_curl_command(curl_text)
        if cookie:
            extra_headers["Cookie"] = cookie
        if args.user_agent != DEFAULT_UA:
            extra_headers["User-Agent"] = args.user_agent
        if args.referer:
            extra_headers["Referer"] = args.referer
        referer = extra_headers.get("Referer")
    elif args.media_url:
        media_url = args.media_url
        referer = args.referer or None
    elif args.auto:
        if not args.share:
            print("Missing share text or URL.", file=sys.stderr)
            return 2
        share_text = read_text_input(args.share)
        share_url = extract_first_url(share_text)
        if not share_url:
            print("No URL found in input.", file=sys.stderr)
            return 2

        candidates, request_headers_by_url, page_url = (
            capture_media_candidates_with_playwright(
                share_url,
                args.user_agent,
                cookie,
                args.timeout,
            )
        )
        if not candidates:
            print("No media URL captured by Playwright.", file=sys.stderr)
            return 3

        selected, ranked = choose_candidate(candidates, prefer_ext, args.select)

        if args.list:
            for i, url, score in ranked:
                print(f"[{i}] score={score} {url}")
            return 0

        media_url = selected
        extra_headers = pick_request_headers(request_headers_by_url.get(selected))
        if page_url and "Referer" not in extra_headers:
            extra_headers["Referer"] = page_url
        if args.referer:
            extra_headers["Referer"] = args.referer
        referer = extra_headers.get("Referer")
    else:
        if not args.share:
            print("Missing share text or URL.", file=sys.stderr)
            return 2
        share_text = read_text_input(args.share)
        share_url = extract_first_url(share_text)
        if not share_url:
            print("No URL found in input.", file=sys.stderr)
            return 2

        headers = build_headers(args.user_agent, None, cookie)
        final_url, content_type, data = fetch_url(share_url, headers, args.timeout)
        referer = args.referer or final_url

        if is_media_content_type(content_type):
            media_url = final_url
        else:
            html_text = decode_html(data, content_type)
            if args.save_html:
                with open(args.save_html, "w", encoding="utf-8") as f:
                    f.write(html_text)

            candidates = collect_candidates(html_text)
            if not candidates:
                print(
                    "No media URL found. Try --save-html and inspect, or pass --media-url.",
                    file=sys.stderr,
                )
                return 3

            selected, ranked = choose_candidate(candidates, prefer_ext, args.select)

            if args.list:
                for i, url, score in ranked:
                    print(f"[{i}] score={score} {url}")
                return 0

            media_url = selected

    if not media_url:
        print("No media URL resolved.", file=sys.stderr)
        return 4

    if args.print_only:
        print(media_url)
        return 0

    os.makedirs(args.output_dir, exist_ok=True)

    user_agent = args.user_agent
    cookie_header = cookie
    referer_header = referer
    if extra_headers:
        user_agent = extra_headers.get("User-Agent", user_agent)
        cookie_header = extra_headers.get("Cookie", cookie_header)
        referer_header = extra_headers.get("Referer", referer_header)

    headers = build_headers(
        user_agent, referer_header, cookie_header, extra_headers=extra_headers
    )
    ext = None
    if args.filename:
        filename = sanitize_filename(args.filename)
    else:
        parsed = urllib.parse.urlparse(media_url)
        name = os.path.basename(parsed.path)
        filename = sanitize_filename(name) if name else f"qishui_{int(time.time())}"

    output_path = os.path.join(args.output_dir, filename)

    if media_url.lower().endswith(".m3u8") or ".m3u8" in media_url.lower():
        if args.ffmpeg:
            if not output_path.lower().endswith(".mp4"):
                output_path += ".mp4"
            output_path = unique_path(args.output_dir, os.path.basename(output_path))
            try:
                download_m3u8_with_ffmpeg(media_url, output_path, headers)
                print(f"Saved: {output_path}")
                return 0
            except subprocess.CalledProcessError as exc:
                print(f"ffmpeg failed: {exc}", file=sys.stderr)
                return 6

        if not output_path.lower().endswith(".m3u8"):
            output_path += ".m3u8"
        output_path = unique_path(args.output_dir, os.path.basename(output_path))
        try:
            meta = download_file(
                media_url, output_path, headers, args.timeout, args.read_retries
            )
        except DownloadError:
            print(
                "Download timed out. Try --timeout 120 or reduce --read-retries.",
                file=sys.stderr,
            )
            return 5
        print(f"Saved playlist: {output_path}")
        if meta.get("content_type"):
            print(f"Content-Type: {meta['content_type']}")
        return 0

    output_path = unique_path(args.output_dir, os.path.basename(output_path))
    try:
        meta = download_file(
            media_url, output_path, headers, args.timeout, args.read_retries
        )
    except DownloadError:
        print(
            "Download timed out. Try --timeout 120 or reduce --read-retries.",
            file=sys.stderr,
        )
        return 5

    content_type = meta.get("content_type", "")
    content_disp = meta.get("content_disposition", "")

    if not args.filename:
        header_name = filename_from_headers({"Content-Disposition": content_disp})
        if header_name:
            filename = sanitize_filename(header_name)

    if not os.path.splitext(filename)[1]:
        ext = guess_extension(media_url, content_type, prefer_ext)
        filename = filename + ext

    final_path = unique_path(args.output_dir, filename)
    if final_path != output_path:
        os.replace(output_path, final_path)
        output_path = final_path

    print(f"Saved: {output_path}")
    if content_type:
        print(f"Content-Type: {content_type}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
