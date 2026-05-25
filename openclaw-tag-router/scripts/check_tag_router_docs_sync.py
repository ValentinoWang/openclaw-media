#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from openclaw_app.router.tag_capabilities import TAG_CAPABILITIES, TAG_LABELS, tag_capability_dicts  # noqa: E402

ROUTER_PATH = PLUGIN_ROOT / "openclaw_app" / "router" / "tag_router.py"
DOC_PATH = Path("/home/ubuntu/docs/说明书/OpenClaw 标签功能说明.md")
AUXILIARY_DOC_PATHS = [
    Path("/home/ubuntu/docs/说明书/OpenClaw Social bot 使用说明.md"),
]

START_MARKER = "<!-- TAG_ROUTER_DOC_SYNC_START"
END_MARKER = "TAG_ROUTER_DOC_SYNC_END -->"

EXCLUDED_HANDLER_SUFFIXES = {"generic"}
SPECIAL_HANDLER_LABELS = {"id_business": "商务-ID"}


def _find_tag_router_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TagRouter":
            return node
    raise ValueError("TagRouter class not found")


def extract_supported_labels(router_path: Path = ROUTER_PATH) -> list[str]:
    validate_router_capabilities(router_path=router_path, raise_on_error=True)
    return list(TAG_LABELS)


def _router_handler_methods(router_path: Path = ROUTER_PATH) -> set[str]:
    tree = ast.parse(router_path.read_text(encoding="utf-8"), filename=str(router_path))
    tag_router = _find_tag_router_class(tree)
    methods: set[str] = set()
    for node in tag_router.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("handle_"):
            continue
        suffix = node.name.removeprefix("handle_")
        if suffix in EXCLUDED_HANDLER_SUFFIXES:
            continue
        methods.add(node.name)
    return methods


def validate_router_capabilities(router_path: Path = ROUTER_PATH, *, raise_on_error: bool = False) -> list[str]:
    errors: list[str] = []
    labels = list(TAG_LABELS)
    duplicate_labels = sorted({label for label in labels if labels.count(label) > 1})
    if duplicate_labels:
        errors.append(f"duplicate tag capability labels: {', '.join(duplicate_labels)}")

    expected_methods = {
        capability.handler
        for capability in TAG_CAPABILITIES
        if capability.handler.startswith("handle_") and capability.handler != "handle_generic"
    }
    actual_methods = _router_handler_methods(router_path)
    missing_methods = sorted(expected_methods - actual_methods)
    undocumented_methods = sorted(actual_methods - expected_methods)
    if missing_methods:
        errors.append(f"registered handlers missing in TagRouter: {', '.join(missing_methods)}")
    if undocumented_methods:
        labels = [SPECIAL_HANDLER_LABELS.get(method.removeprefix("handle_"), method.removeprefix("handle_")) for method in undocumented_methods]
        errors.append(f"TagRouter handlers missing in TAG_CAPABILITIES: {', '.join(labels)}")

    if raise_on_error and errors:
        raise RuntimeError("; ".join(errors))
    return errors


def render_sync_block(labels: list[str]) -> str:
    lines = [START_MARKER]
    lines.extend(labels)
    lines.append(END_MARKER)
    return "\n".join(lines)


def replace_sync_block(doc_text: str, sync_block: str) -> str:
    start = doc_text.find(START_MARKER)
    end = doc_text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        suffix = "\n\n## Tag Router 同步清单\n\n" + sync_block + "\n"
        return doc_text.rstrip() + suffix
    end += len(END_MARKER)
    return doc_text[:start] + sync_block + doc_text[end:]


def strip_html_comments(doc_text: str) -> str:
    return re.sub(r"<!--.*?-->", "", doc_text, flags=re.DOTALL)


def combined_visible_doc_text() -> str:
    texts = [strip_html_comments(DOC_PATH.read_text(encoding="utf-8"))]
    for path in AUXILIARY_DOC_PATHS:
        if path.exists():
            texts.append(strip_html_comments(path.read_text(encoding="utf-8")))
    return "\n".join(texts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check tag-router route labels are synced to the cloud-doc source markdown.")
    parser.add_argument("--fix", action="store_true", help="rewrite the marker block in the doc source")
    parser.add_argument("--list", action="store_true", help="print supported labels and exit")
    parser.add_argument("--json", action="store_true", help="print registered tag capabilities as JSON and exit")
    args = parser.parse_args()

    capability_errors = validate_router_capabilities()
    if capability_errors:
        print("tag-router capability registry check failed:", file=sys.stderr)
        for error in capability_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    labels = extract_supported_labels()
    sync_block = render_sync_block(labels)
    if args.json:
        print(json.dumps(tag_capability_dicts(), ensure_ascii=False, indent=2))
        return 0
    if args.list:
        print("\n".join(labels))
        return 0

    doc_text = DOC_PATH.read_text(encoding="utf-8")
    visible_doc_text = combined_visible_doc_text()
    missing_visible_labels = [label for label in labels if f"【{label}】" not in visible_doc_text]
    if missing_visible_labels:
        print(
            "tag-router docs sync check failed: user-facing doc is missing visible tag labels: "
            + "、".join(missing_visible_labels),
            file=sys.stderr,
        )
        return 1
    expected_text = replace_sync_block(doc_text, sync_block)
    if args.fix:
        if expected_text != doc_text:
            DOC_PATH.write_text(expected_text, encoding="utf-8")
            print(f"updated {DOC_PATH}")
        else:
            print(f"{DOC_PATH} is already synced")
        return 0

    if expected_text != doc_text:
        print(
            "tag-router docs sync check failed: supported route labels changed.\n"
            f"Update {DOC_PATH} and run:\n"
            f"  python3 {Path(__file__).relative_to(PLUGIN_ROOT)} --fix",
            file=sys.stderr,
        )
        return 1

    print("tag-router docs sync check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
