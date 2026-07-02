#!/usr/bin/env python3
"""Run OpenClaw's gpt-image-2 workflow for the Media bot."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


OUTPUT_DIR = Path(os.getenv("GPT_IMAGE2_OUTPUT_DIR", "/home/ubuntu/openclaw-agents/media/generated/gpt-image-2"))
SESSION_STORES = [
    Path.home() / ".openclaw" / "agents" / "feishu-media" / "sessions" / "sessions.json",
    Path.home() / ".openclaw" / "agents" / "feishu-main" / "sessions" / "sessions.json",
]
DEFAULT_MODEL = "openai/gpt-image-2"
DEFAULT_SIZE = "1024x1024"
DEFAULT_FORMAT = "png"
DEFAULT_TIMEOUT_MS = 1500000
SOCIAL_THEORY_TAGS = ("/女性爱", "/性兴趣", "/风控", "/性资源", "/行动")
BLOCKED_SOCIAL_THEORY_TAGS = ("/风控量表",)
SLASH_THEORY_RE = re.compile(r"/([\w\u4e00-\u9fff-]+)")
THEORY_TAG_SUFFIXES = ("进行分析", "来分析", "分析一下", "分析")


def clean_slash_theory_tag(value: str) -> str:
    tag = value.strip().strip("/")
    for suffix in THEORY_TAG_SUFFIXES:
        if tag.endswith(suffix) and len(tag) > len(suffix):
            tag = tag[: -len(suffix)]
            break
    return f"/{tag.strip()}" if tag.strip() else ""


def social_theory_matches(text: str) -> list[str]:
    normalized = re.sub(r"https?://\S+", " ", text or "")
    slash_tags = {clean_slash_theory_tag(match) for match in SLASH_THEORY_RE.findall(normalized)}
    return [tag for tag in (*BLOCKED_SOCIAL_THEORY_TAGS, *SOCIAL_THEORY_TAGS) if tag in slash_tags]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit images with openai/gpt-image-2.")
    parser.add_argument("--prompt", required=True, help="Image generation or edit prompt.")
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="Input image for edit mode. Repeat for multiple images.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model override. Default: {DEFAULT_MODEL}")
    parser.add_argument("--size", default=DEFAULT_SIZE, help=f"Output size. Default: {DEFAULT_SIZE}")
    parser.add_argument("--format", default=DEFAULT_FORMAT, choices=["png", "jpeg", "webp"], help="Output format.")
    parser.add_argument("--count", type=int, default=1, help="Number of images to request.")
    parser.add_argument("--background", choices=["transparent", "opaque", "auto"], help="Background hint.")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS, help="Provider timeout in milliseconds.")
    parser.add_argument("--output-stem", help="Optional output filename stem.")
    parser.add_argument(
        "--send",
        choices=["auto", "none"],
        default="auto",
        help="Send generated images to the current/recent Feishu media conversation when possible.",
    )
    parser.add_argument("--target", help="Explicit Feishu target, e.g. user:ou_xxx or ou_xxx.")
    parser.add_argument("--account", default="media", help="Feishu account id used for delivery.")
    args = parser.parse_args()
    matched = social_theory_matches(args.prompt or "")
    if matched:
        if any(tag in BLOCKED_SOCIAL_THEORY_TAGS for tag in matched):
            raise SystemExit(
                "社交理论入口不属于 media 图像入口，已拒绝执行："
                + "、".join(tag for tag in matched if tag in BLOCKED_SOCIAL_THEORY_TAGS)
            )
        raise SystemExit(
            "社交理论标签只能由 social bot 调用，media 图像入口拒绝执行："
            + "、".join(matched)
        )
    return args


def sanitize_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())[:80].strip("-._")
    return stem or "image"


def extract_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise RuntimeError("OpenClaw did not return JSON.")
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    candidate_payload: dict[str, Any] | None = None
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            if any(key in value for key in ("ok", "outputs", "result", "runId", "status")):
                return value
            if candidate_payload is None:
                candidate_payload = value
    if candidate_payload is not None:
        return candidate_payload
    raise RuntimeError(f"OpenClaw did not return JSON. Output tail:\n{stdout[-1000:]}")


def summarize_command_failure(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = (completed.stderr or "").strip()
    if stderr:
        return stderr[-1000:]
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return "OpenClaw image command failed."
    try:
        parsed = extract_json(stdout)
    except RuntimeError:
        return stdout[-1000:] if not stdout.startswith(("{", "[")) else "OpenClaw image command failed with structured output but no visible error."
    error = parsed.get("error") or parsed.get("message")
    if error:
        return str(error)[-1000:]
    run_id = parsed.get("runId") or parsed.get("id") or ""
    status = parsed.get("status") or ""
    return f"OpenClaw image command failed. status={status} runId={run_id}".strip()


def summarize_command_success(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""
    try:
        parsed = extract_json(text)
    except RuntimeError:
        return text[-1000:] if not text.startswith(("{", "[")) else "OpenClaw structured output without visible text."
    result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
    payloads = result.get("payloads") if isinstance(result, dict) else None
    if isinstance(payloads, list):
        texts = [
            str(payload.get("text")).strip()
            for payload in payloads
            if isinstance(payload, dict) and payload.get("text")
        ]
        if texts:
            return "\n".join(texts)[:1000]
    for key in ("text", "message", "summary"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1000]
    run_id = parsed.get("runId") or parsed.get("id") or ""
    status = parsed.get("status") or ""
    return f"OpenClaw structured output status={status} runId={run_id}".strip()[:1000]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    timeout = int(float(os.getenv("GPT_IMAGE2_OPENCLAW_TIMEOUT_SECONDS", "1800")))
    try:
        return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            cmd,
            124,
            exc.stdout or "",
            f"[watchdog] gpt-image2 OpenClaw timeout_after={timeout}s: {exc}",
        )


def run_image(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    prompt_stem = sanitize_stem(args.output_stem or args.prompt[:36])
    output_path = OUTPUT_DIR / f"{now}-{prompt_stem}.{args.format}"

    command = [
        "openclaw",
        "capability",
        "image",
        "edit" if args.file else "generate",
        "--prompt",
        args.prompt,
        "--model",
        args.model,
        "--size",
        args.size,
        "--output-format",
        args.format,
        "--timeout-ms",
        str(args.timeout_ms),
        "--output",
        str(output_path),
        "--json",
    ]
    for file_path in args.file:
        command.extend(["--file", str(Path(file_path).expanduser())])
    if not args.file:
        command.extend(["--count", str(args.count)])
    if args.background:
        command.extend(["--background", args.background])

    completed = run(command)
    if completed.returncode != 0:
        raise RuntimeError(summarize_command_failure(completed))
    result = extract_json(completed.stdout)
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or json.dumps(result, ensure_ascii=False))
    return result


def normalize_target(target: str | None) -> str | None:
    if not target:
        return None
    target = target.strip()
    if not target:
        return None
    if target.startswith(("user:", "channel:")):
        return target
    if target.startswith("ou_"):
        return f"user:{target}"
    if target.startswith("oc_"):
        return f"channel:{target}"
    return target


def latest_stored_target() -> str | None:
    env_target = normalize_target(
        os.environ.get("OPENCLAW_DELIVERY_TO")
        or os.environ.get("OPENCLAW_LAST_TO")
        or os.environ.get("OPENCLAW_TARGET")
    )
    if env_target:
        return env_target
    candidates: list[tuple[int, str]] = []
    for session_store in SESSION_STORES:
        if not session_store.exists():
            continue
        data = json.loads(session_store.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for item in data.values():
            if not isinstance(item, dict):
                continue
            target = normalize_target(
                ((item.get("deliveryContext") or {}).get("to") if isinstance(item.get("deliveryContext"), dict) else None)
                or item.get("lastTo")
            )
            updated = item.get("updatedAt") or item.get("lastUpdatedAt") or 0
            if target and isinstance(updated, int):
                candidates.append((updated, target))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def send_outputs(args: argparse.Namespace, outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target = normalize_target(args.target) or latest_stored_target()
    if args.send == "none" or not target:
        return []
    deliveries = []
    for output in outputs:
        path = output.get("path")
        if not isinstance(path, str) or not path:
            continue
        command = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "feishu",
            "--account",
            args.account,
            "--target",
            target,
            "--message",
            "gpt-image-2 生成结果",
            "--media",
            path,
            "--json",
        ]
        completed = run(command)
        deliveries.append(
            {
                "target": target,
                "path": path,
                "ok": completed.returncode == 0,
                "stdout_summary": summarize_command_success(completed.stdout),
                "stderr": completed.stderr.strip()[-1000:],
            }
        )
    return deliveries


def main() -> int:
    args = parse_args()
    try:
        result = run_image(args)
        outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
        deliveries = send_outputs(args, outputs)
        delivery_failures = [item for item in deliveries if not item.get("ok")]
        if args.send != "none" and deliveries and delivery_failures:
            raise RuntimeError(
                "Image generated but delivery failed: "
                + "; ".join(str(item.get("stderr") or item.get("stdout") or item.get("path")) for item in delivery_failures)
            )
        print(
            json.dumps(
                {
                    "ok": True,
                    "model": result.get("model"),
                    "provider": result.get("provider"),
                    "outputs": outputs,
                    "deliveries": deliveries,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
