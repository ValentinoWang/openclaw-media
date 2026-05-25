from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run_workflow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="包含【拆解】和链接的文本")
    parser.add_argument("--out", default="", help="输出 JSON 文件路径")
    parser.add_argument("--feishu-url", default="", help="飞书多维表格链接；不传则读 MEDIA_OS_VIRAL_URL")
    parser.add_argument("--no-write", action="store_true", help="只生成 JSON，不写飞书")
    parser.add_argument("--source-json", default="", help="【创作-再创】时传入已有拆解 JSON")
    parser.add_argument("--doc", action="store_true", help="【创作-再创】时新建飞书云文档")
    args = parser.parse_args()

    if args.source_json:
        raise RuntimeError("当前入口不允许只有【创作-再创】基于 source-json 单独执行；请使用【拆解】+【创作-再创】让代码保证顺序。")
    try:
        result = run_workflow(args.text, write_feishu=not args.no_write, bitable_url=args.feishu_url or None)
    except Exception as exc:
        raise SystemExit(f"错误：{exc}") from None
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content + "\n", encoding="utf-8")
        print(out)
    else:
        print(content)


if __name__ == "__main__":
    main()
