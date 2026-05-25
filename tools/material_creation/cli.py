from __future__ import annotations

import argparse
import json
import os

from .workflow import handle_material_creation_command


def main() -> None:
    parser = argparse.ArgumentParser(description="Create positioning analysis and platform draft from uploaded media.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--attachment", dest="attachments", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--creation-record-url", default="")
    parser.add_argument("--conversation-context-json", default="")
    args = parser.parse_args()
    conversation_context_json = args.conversation_context_json or os.environ.get("OPENCLAW_CONVERSATION_CONTEXT_JSON", "")
    conversation_context = json.loads(conversation_context_json) if conversation_context_json else None
    result = handle_material_creation_command(
        args.text,
        attachment_paths=args.attachments,
        dry_run=args.dry_run,
        no_write=args.no_write,
        creation_record_url=args.creation_record_url,
        conversation_context=conversation_context,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
