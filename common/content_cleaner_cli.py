#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.content_cleaner import clean_collected_text, clean_ocr_text, clean_text_by_source, clean_transcript_text


def _read_text(path: str) -> str:
    if not path or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean OCR/transcript/collected text with the shared content cleaner")
    parser.add_argument("--source", choices=["auto", "ocr", "transcript", "content"], default="auto")
    parser.add_argument("--title", default="")
    parser.add_argument("--content-type", default="")
    parser.add_argument("--input", default="-", help="Input text file path, or '-' for stdin")
    parser.add_argument("--output", default="-", help="Output text file path, or '-' for stdout")
    args = parser.parse_args()

    text = _read_text(args.input)
    metadata = {"内容类型": args.content_type} if args.content_type else {}
    if args.source == "ocr":
        cleaned = clean_ocr_text(text, title=args.title, metadata=metadata)
    elif args.source == "transcript":
        cleaned = clean_transcript_text(text, title=args.title, metadata=metadata)
    elif args.source == "content":
        cleaned = clean_collected_text(text, title=args.title, metadata=metadata)
    else:
        cleaned = clean_text_by_source(text, title=args.title, metadata=metadata)

    if args.output == "-":
        sys.stdout.write(cleaned)
        if cleaned and not cleaned.endswith("\n"):
            sys.stdout.write("\n")
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(cleaned, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
