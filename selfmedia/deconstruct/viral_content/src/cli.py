from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import extract_evidence_store, partial_deconstruct, run_workflow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="包含【拆解】和链接的文本")
    parser.add_argument("--out", default="", help="输出 JSON 文件路径")
    parser.add_argument("--no-write", action="store_true", help="只生成 JSON，不写飞书")
    parser.add_argument("--source-json", default="", help="退役参数：不再支持从已有拆解 JSON 直接创建任务卡")
    parser.add_argument("--stage-dir", default="", help="阶段 JSON 落盘目录；用于调试时从最近成功阶段继续")
    parser.add_argument("--resume-stage-json", default="", help="从 01_prepared/02_deconstruct_core/03_multi_signal_contract 等阶段 JSON 继续")
    parser.add_argument("--doc", action="store_true", help="退役参数：拆解命令不直接新建创作任务文档")
    parser.add_argument("--partial", action="store_true", help="只做轻量部分拆解，输出 BGM 卡点剪辑卡 JSON，不写 02A/02B")
    parser.add_argument("--evidence-store", action="store_true", help="只抽取并输出 evidence_store DAG 事实层，不写 02A/02B")
    parser.add_argument("--tenant-id", default="", help="写入时必填的 Sub2API tenant id")
    args = parser.parse_args()

    if args.source_json:
        raise RuntimeError("当前入口不允许基于 source-json 单独执行；请使用【素材】保存 SourceAsset 后显式交接【创作】或【创作-拍摄执行】。")
    try:
        if args.evidence_store:
            if not args.no_write:
                raise RuntimeError("--evidence-store 只输出 evidence_store；请同时传 --no-write，避免写入 02A/02B")
            result = extract_evidence_store(args.text)
        elif args.partial:
            if not args.no_write:
                raise RuntimeError("--partial 只输出轻量 JSON；请同时传 --no-write，避免写入完整 02A/02B 拆解库")
            result = {"mode": "partial_deconstruct", "partial_deconstruct": partial_deconstruct(args.text)}
        else:
            if not args.no_write and not args.tenant_id:
                raise RuntimeError("写入 02A/02B 必须提供 --tenant-id")
            result = run_workflow(
                args.text,
                tenant_id=args.tenant_id,
                write_feishu=not args.no_write,
                stage_dir=args.stage_dir or None,
                resume_stage_json=args.resume_stage_json or None,
            )
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
