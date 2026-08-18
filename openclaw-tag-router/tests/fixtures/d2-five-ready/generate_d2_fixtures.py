#!/usr/bin/env python3
"""Generate and verify the five fixed D2 canonical-body inputs.

This source-owned package contains deterministic inputs for a real
React/Feishu D2 run. It is not rendering evidence and does not create database
rows or remote documents by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT.parents[2]
OPENAPI = SOURCE_ROOT / "openclaw_app/contracts/media_web_business_pages.openapi.yaml"
MIGRATION = SOURCE_ROOT / "openclaw_app/contracts/media_web_business_pages.migration.yaml"
FIXTURE_DIR = ROOT / "fixtures"
RESOURCE_DIR = ROOT / "resources"
IMAGE_PATH = RESOURCE_DIR / "d2-controlled-image-640x360.png"
ATTACHMENT_PATH = RESOURCE_DIR / "d2-controlled-attachment.pdf"
MANIFEST_PATH = ROOT / "ready-revision-manifest.json"
MATRIX_PATH = ROOT / "coverage-matrix.json"
SUMS_PATH = ROOT / "SHA256SUMS"

ARTIFACTS = (
    ("research_snapshot", "rs", "调研快照：研究结论与证据索引", "evidence_index"),
    ("asset_digest", "ad", "素材摘要：已选择素材与创作模式", "general"),
    ("decision_brief", "db", "选题简报：候选主题与人工决定", "evidence_index"),
    ("creation_document", "cd", "创作文档：分镜与拍摄注意", "storyboard"),
    ("review_report", "rr", "复盘报告：指标快照与人工结论", "metric_snapshot"),
)

PROTECTED_CASES = (
    "whiteboard", "bitable", "sheet", "embedded_webpage", "synced_block",
    "third_party_widget", "agenda", "okr", "mind_note", "flowchart", "lark_task",
)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_path(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def controlled_image_bytes() -> bytes:
    width, height = 640, 360
    scanline = b"\x00" + (b"\x1f\x6f\x8f" * width)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(scanline * height, level=9))
        + png_chunk(b"IEND", b"")
    )


def controlled_attachment_bytes() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 640 360] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length 75 >>\nstream\nBT /F1 18 Tf 36 300 Td (D2 controlled attachment evidence) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def text(value: str, marks: list[Any] | None = None) -> dict[str, Any]:
    return {"type": "text", "text": value, "marks": marks or []}


def row(prefix: str, number: int, values: list[Any]) -> dict[str, Any]:
    return {
        "id": f"blk_{prefix}_row_{number:02d}",
        "cells": [
            {"id": f"blk_{prefix}_cell_{number:02d}_{column:02d}", "content": content if isinstance(content, list) else [content]}
            for column, content in enumerate(values, 1)
        ],
    }


def table(prefix: str, suffix: str, purpose: str, values: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "id": f"blk_{prefix}_table_{suffix}",
        "type": "table",
        "attrs": {"semanticPurpose": purpose, "headerRowCount": 1},
        "rows": [row(f"{prefix}_{suffix}", number, cells) for number, cells in enumerate(values, 1)],
    }


def type_table(kind: str, prefix: str, purpose: str) -> list[dict[str, Any]]:
    if kind == "creation_document":
        header = [text("时间"), text("画面"), text("字幕/口播"), text("声音/拍摄注意")]
        first = [header] + [
            [text(f"00:{second:02d}"), text(f"镜头 {index}"), text(f"口播第 {index} 句"), text("保留环境声")]
            for index, second in enumerate(range(0, 40, 5), 1)
        ]
        continuation = [header] + [
            [text(f"00:{second:02d}"), text(f"补充分镜 {index}"), text("长链接 https://example.test/d2/storyboard"), text("检查收音")]
            for index, second in enumerate(range(40, 55, 5), 9)
        ]
        return [table(prefix, "storyboard_01", purpose, first), table(prefix, "storyboard_02", purpose, continuation)]
    if kind == "review_report":
        header = [text("指标"), text("数值"), text("单位"), text("时间窗"), text("采集时间"), text("证据质量")]
        first = [header] + [
            [text(metric), text(value), text(unit), text(window), text("2026-08-05T10:00:00Z"), text("verified")]
            for metric, value, unit, window in (
                ("播放", "1200", "次", "24h"), ("完播率", "38.5", "%", "24h"),
                ("互动", "86", "次", "24h"), ("关注", "19", "人", "24h"),
                ("播放", "3400", "次", "7d"), ("收藏", "104", "次", "7d"),
                ("分享", "33", "次", "7d"), ("评论", "21", "次", "7d"),
            )
        ]
        continuation = [header] + [
            [text("转化"), text("14"), text("人"), text("7d"), text("2026-08-12T10:00:00Z"), text("reviewed")],
            [text("人工结论"), text("继续测试"), text("状态"), text("7d"), text("2026-08-12T10:00:00Z"), text("human_confirmed")],
        ]
        return [table(prefix, "metrics_01", purpose, first), table(prefix, "metrics_02", purpose, continuation)]
    headers = {
        "research_snapshot": [text("来源"), text("结论"), text("证据质量")],
        "asset_digest": [text("素材"), text("标签"), text("创作模式")],
        "decision_brief": [text("候选选题"), text("信号"), text("人工决定")],
    }[kind]
    cells = {
        "research_snapshot": [[text("公开资料"), text("比较结果已核对"), text("verified")], [text("https://example.test/d2/evidence"), text("保留引用"), text("reviewed")]],
        "asset_digest": [[text("素材 A"), text("中文, English"), text("反差开场")], [text("素材 B"), text("长段落"), text("问题拆解")]],
        "decision_brief": [[text("通勤收纳"), text("趋势上升"), text("confirmed")], [text("桌面改造"), text("活动关联"), text("pending")]],
    }[kind]
    return [table(prefix, "primary", purpose, [headers, *cells])]


def body_for(kind: str, prefix: str, title: str, purpose: str) -> dict[str, Any]:
    image_checksum = digest_bytes(controlled_image_bytes())
    attachment_checksum = digest_bytes(controlled_attachment_bytes())
    blocks: list[dict[str, Any]] = [
        {"id": f"blk_{prefix}_heading_01", "type": "heading_1", "attrs": {}, "content": [text(title, ["bold"])]},
        {"id": f"blk_{prefix}_heading_02", "type": "heading_2", "attrs": {}, "content": [text("等价渲染固定修订 / Fixed ready revision")]},
        {"id": f"blk_{prefix}_paragraph_mixed", "type": "paragraph", "attrs": {}, "content": [text("中文 A English 123，。！？：；（）【】")]} ,
        {"id": f"blk_{prefix}_paragraph_whitespace", "type": "paragraph", "attrs": {}, "content": [text("  前置空格｜中间  空格｜后置空格  ")]},
        {"id": f"blk_{prefix}_paragraph_newlines", "type": "paragraph", "attrs": {}, "content": [text("第一行\n第二行\n\n第四行\n")]} ,
        {
            "id": f"blk_{prefix}_paragraph_marks", "type": "paragraph", "attrs": {},
            "content": [
                text("粗体", ["bold"]), text("、"), text("斜体", ["italic"]), text("、"),
                text("下划线", ["underline"]), text("、"), text("删除线", ["strike"]), text("、"),
                text("行内代码", ["inline_code"]), text("。"),
            ],
        },
        {
            "id": f"blk_{prefix}_paragraph_link", "type": "paragraph", "attrs": {},
            "content": [text("查看"), text("证据链接", [{"type": "link", "href": "https://example.test/d2/evidence?q=%E4%B8%AD%E6%96%87&x=1", "title": "D2 证据链接"}]), text("，随后保留标点。")],
        },
        {
            "id": f"blk_{prefix}_list_bullet", "type": "bullet_list", "attrs": {},
            "items": [{"id": f"blk_{prefix}_item_bullet_01", "content": [text("第一层无序项")], "children": [{"id": f"blk_{prefix}_list_bullet_nested", "type": "bullet_list", "attrs": {}, "items": [{"id": f"blk_{prefix}_item_bullet_02", "content": [text("嵌套无序项")], "children": []}]}]}],
        },
        {
            "id": f"blk_{prefix}_list_ordered", "type": "ordered_list", "attrs": {},
            "items": [{"id": f"blk_{prefix}_item_ordered_01", "content": [text("第一项")], "children": []}, {"id": f"blk_{prefix}_item_ordered_02", "content": [text("第二项")], "children": []}],
        },
        {"id": f"blk_{prefix}_todo_open", "type": "todo_item", "attrs": {"checked": False}, "content": [text("待处理：保留空格")]},
        {"id": f"blk_{prefix}_todo_done", "type": "todo_item", "attrs": {"checked": True}, "content": [text("已核对：中文表格")]},
        {"id": f"blk_{prefix}_quote", "type": "quote", "attrs": {}, "content": [text("引用：必须逐字、逐格式读回。")]} ,
        {"id": f"blk_{prefix}_code", "type": "code_block", "attrs": {"language": "typescript"}, "text": "const 标题 = '中文';\nconsole.log(标题);\n"},
        {"id": f"blk_{prefix}_divider", "type": "divider", "attrs": {}},
        {"id": f"blk_{prefix}_callout", "type": "callout", "attrs": {"semanticTone": "warning"}, "content": [text("提示：保护块测试必须显式失败，不能静默删除。", ["bold"])]},
        {"id": f"blk_{prefix}_image", "type": "image", "attrs": {"publicResourceId": f"res_d2_{prefix}_image_0001", "altText": f"{title}封面图", "width": 640, "height": 360, "contentChecksum": image_checksum}},
        {"id": f"blk_{prefix}_attachment", "type": "attachment", "attrs": {"publicResourceId": f"res_d2_{prefix}_attachment_0001", "fileName": f"{kind}-evidence.pdf", "contentType": "application/pdf", "contentChecksum": attachment_checksum}},
        *type_table(kind, prefix, purpose),
        {"id": f"blk_{prefix}_snapshot", "type": "data_snapshot", "attrs": {"semanticPurpose": "metric_snapshot" if kind == "review_report" else "evidence_index", "publicObjectId": f"snapshot_d2_{prefix}_0001", "sourceRevision": 1, "capturedAt": "2026-08-05T10:00:00Z", "displayFields": {"artifactKind": kind, "verified": True, "sampleCount": 2, "windows": ["24h", "7d"], "note": None}}},
    ]
    return {"schemaVersion": "media.document.body.v1", "blocks": blocks}


def block_ids(body: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []

    def visit(block: dict[str, Any]) -> None:
        identifiers.append(block["id"])
        if block["type"] in {"bullet_list", "ordered_list"}:
            for item in block["items"]:
                identifiers.append(item["id"])
                for child in item["children"]:
                    visit(child)
        if block["type"] == "table":
            for table_row in block["rows"]:
                identifiers.append(table_row["id"])
                identifiers.extend(cell["id"] for cell in table_row["cells"])

    for item in body["blocks"]:
        visit(item)
    return identifiers


def bodies() -> dict[str, dict[str, Any]]:
    return {kind: body_for(kind, prefix, title, purpose) for kind, prefix, title, purpose in ARTIFACTS}


def fixture_manifest(rendered: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for kind, prefix, _title, purpose in ARTIFACTS:
        body = rendered[kind]
        body_hash = digest_bytes(canonical_bytes(body))
        entries.append({
            "artifactKind": kind,
            "publicArtifactId": f"artifact_d2_{prefix}_20260805",
            "revisionId": f"d2-ready-{kind}-r1",
            "revisionNumber": 1,
            "requiredState": "ready",
            "immutableBinding": True,
            "canonicalBodySchema": "media.document.body.v1",
            "bodyFile": f"fixtures/{kind}.ready.body.v1.json",
            "bodySha256": body_hash,
            "orderedCanonicalIds": block_ids(body),
            "bodyAuthorityBySurface": {"react": "internal", "feishu": "lark"},
            "tableSemanticPurpose": purpose,
            "resourceBinding": {
                "required": True,
                "rule": "Bind each declared public resource ID to a real isolated runtime resource with exactly the contentChecksum in the canonical body before capture.",
                "fixtureOnlyIsNotEvidence": True,
                "image": {
                    "file": str(IMAGE_PATH.relative_to(ROOT)),
                    "contentType": "image/png",
                    "width": 640,
                    "height": 360,
                    "sha256": sha256_path(IMAGE_PATH),
                },
                "attachment": {
                    "file": str(ATTACHMENT_PATH.relative_to(ROOT)),
                    "contentType": "application/pdf",
                    "sha256": sha256_path(ATTACHMENT_PATH),
                },
            },
            "realSurfaceRequirements": {
                "react": "real MediaApp document route rendering this exact persisted ready revision",
                "feishu": "authorized isolated real Feishu Docx write, remote version capture, and block-level readback",
                "mockForbidden": True,
            },
        })
    return {
        "schemaVersion": "d2.fixed-ready-revisions.v1",
        "status": "READY_TO_MATERIALIZE",
        "scope": {"stage": "D2", "rule": "R11", "d3Status": "not-run", "acceptanceStatus": "not-accepted"},
        "authority": {
            "ssot": "agents-results/2026-08-04/media-web-business-pages-api-completion/ssot-development-paths.md#5.4-and-D2",
            "canonicalBodyStorage": "media_document.revision_bodies.body_json",
            "canonicalBodySchema": "media.document.body.v1",
            "interfaceFreezeVersion": 2,
            "versionTuple": "5/5/2/5",
            "openapiSha256": sha256_path(OPENAPI),
            "migrationSha256": sha256_path(MIGRATION),
            "runtimeMigration": "cm1-027-media-document-runtime",
        },
        "fixtureBoundary": {
            "notPersisted": True,
            "notRenderingEvidence": True,
            "materializationRequirement": "A future D2 runner must persist each unchanged body as the declared ready revision in an isolated tenant, bind its real resources, then capture real React and real Feishu surfaces.",
            "forbiddenSubstitutes": ["mock Feishu DOM", "Markdown preview", "API-only JSON", "hand-composed screenshot", "surface-specific body rewrite"],
        },
        "revisions": entries,
    }


def coverage_matrix(rendered: dict[str, dict[str, Any]]) -> dict[str, Any]:
    shared = [
        "stable_block_ids", "heading_levels", "chinese_english_digits_punctuation", "leading_internal_trailing_whitespace",
        "exact_lf_and_blank_line", "bold_italic_underline_strike_inline_code", "link_text_target_title",
        "bullet_ordered_nested_lists", "checked_and_unchecked_todos", "quote", "code_language_and_final_lf",
        "callout", "image_alt_dimensions_checksum", "attachment_name_mime_checksum", "divider", "data_snapshot",
    ]
    rows = []
    for kind, _prefix, _title, purpose in ARTIFACTS:
        body = rendered[kind]
        tables = [block for block in body["blocks"] if block["type"] == "table"]
        rows.append({
            "artifactKind": kind,
            "fixtureFile": f"fixtures/{kind}.ready.body.v1.json",
            "allSharedFeatures": shared,
            "tableSemanticPurpose": purpose,
            "tableBlocks": [{"id": item["id"], "rows": len(item["rows"]), "columns": len(item["rows"][0]["cells"])} for item in tables],
            "specificRequirement": {
                "research_snapshot": "research conclusion, source link, evidence index and comparison table",
                "asset_digest": "selected assets, tags, creative pattern and controlled resource references",
                "decision_brief": "candidate topic, platform signal, human decision and risk text",
                "creation_document": "two consecutive storyboard tables with the required four columns and repeated header",
                "review_report": "two consecutive metric tables with the required six columns, 24h/7d windows and evidence quality",
            }[kind],
        })
    return {
        "schemaVersion": "d2.fixture-coverage-matrix.v1",
        "comparisonPolicy": {
            "normalizationAllowedOnly": ["surface_native_block_id", "platform_invisible_container_id"],
            "normalizationForbidden": ["text_trim", "whitespace_collapse", "newline_conversion", "punctuation_folding", "mark_loss", "link_flattening", "table_flattening"],
            "realSurfaceOnly": True,
        },
        "requiredD2EvidenceForEveryRevision": [
            "real React MediaApp screenshot and rendered-block manifest",
            "authorized isolated real Feishu Docx screenshot",
            "write receipt, remote document version and complete block-level readback",
            "one-to-one canonical/react/feishu mapping and field-level diff report",
            "zero unexplained differences, zero console failures and zero overflow",
        ],
        "protectedBlockCasesOutsideCanonicalBody": [{
            "caseId": f"protected_{kind}",
            "fixturePlacement": "pre-existing controlled real Feishu Docx block; never encode an unsupported block in media.document.body.v1",
            "expected": {"status": 422, "code": "unsupported_document_block", "partialWrite": False, "readbackUnchanged": True},
        } for kind in PROTECTED_CASES],
        "revisions": rows,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_outputs() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_PATH.write_bytes(controlled_image_bytes())
    ATTACHMENT_PATH.write_bytes(controlled_attachment_bytes())
    rendered = bodies()
    for kind, body in rendered.items():
        write_json(FIXTURE_DIR / f"{kind}.ready.body.v1.json", body)
    write_json(MANIFEST_PATH, fixture_manifest(rendered))
    write_json(MATRIX_PATH, coverage_matrix(rendered))
    paths = [
        *(FIXTURE_DIR / f"{kind}.ready.body.v1.json" for kind, *_ in ARTIFACTS),
        IMAGE_PATH,
        ATTACHMENT_PATH,
        MANIFEST_PATH,
        MATRIX_PATH,
    ]
    SUMS_PATH.write_text("".join(f"{sha256_path(path)}  {path.relative_to(ROOT)}\n" for path in paths), encoding="utf-8")


def validate_with_source(body: dict[str, Any]) -> None:
    sys.path.insert(0, str(SOURCE_ROOT))
    from openclaw_app.services.media_business.foundation import body_checksum, validate_body
    validated = validate_body(body)
    if body_checksum(validated) != digest_bytes(canonical_bytes(body)):
        raise AssertionError("source body_checksum disagrees with canonical fixture hash")


def check_outputs() -> None:
    if IMAGE_PATH.read_bytes() != controlled_image_bytes():
        raise AssertionError("controlled image bytes drift")
    if ATTACHMENT_PATH.read_bytes() != controlled_attachment_bytes():
        raise AssertionError("controlled attachment bytes drift")
    rendered = bodies()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    if manifest["status"] != "READY_TO_MATERIALIZE" or manifest["fixtureBoundary"]["notRenderingEvidence"] is not True:
        raise AssertionError("fixture boundary drift")
    if len(manifest["revisions"]) != 5 or len(matrix["revisions"]) != 5:
        raise AssertionError("the five dual-end revisions are incomplete")
    if len(matrix["protectedBlockCasesOutsideCanonicalBody"]) != len(PROTECTED_CASES):
        raise AssertionError("protected-block coverage is incomplete")
    for entry in manifest["revisions"]:
        kind = entry["artifactKind"]
        body_path = ROOT / entry["bodyFile"]
        stored = json.loads(body_path.read_text(encoding="utf-8"))
        if stored != rendered[kind]:
            raise AssertionError(f"fixture drift: {kind}")
        if entry["bodySha256"] != digest_bytes(canonical_bytes(stored)):
            raise AssertionError(f"fixture hash drift: {kind}")
        if entry["orderedCanonicalIds"] != block_ids(stored):
            raise AssertionError(f"canonical ID order drift: {kind}")
        if entry["requiredState"] != "ready" or not entry["immutableBinding"]:
            raise AssertionError(f"ready binding drift: {kind}")
        resource_binding = entry["resourceBinding"]
        if resource_binding["image"]["sha256"] != sha256_path(IMAGE_PATH):
            raise AssertionError(f"image binding drift: {kind}")
        if resource_binding["attachment"]["sha256"] != sha256_path(ATTACHMENT_PATH):
            raise AssertionError(f"attachment binding drift: {kind}")
        image_blocks = [block for block in stored["blocks"] if block["type"] == "image"]
        attachment_blocks = [block for block in stored["blocks"] if block["type"] == "attachment"]
        if len(image_blocks) != 1 or image_blocks[0]["attrs"]["contentChecksum"] != sha256_path(IMAGE_PATH):
            raise AssertionError(f"image checksum drift: {kind}")
        if len(attachment_blocks) != 1 or attachment_blocks[0]["attrs"]["contentChecksum"] != sha256_path(ATTACHMENT_PATH):
            raise AssertionError(f"attachment checksum drift: {kind}")
        validate_with_source(stored)
    expected_sums = "".join(
        f"{sha256_path(ROOT / relative)}  {relative}\n"
        for relative in [
            *(f"fixtures/{kind}.ready.body.v1.json" for kind, *_ in ARTIFACTS),
            str(IMAGE_PATH.relative_to(ROOT)),
            str(ATTACHMENT_PATH.relative_to(ROOT)),
            "ready-revision-manifest.json",
            "coverage-matrix.json",
        ]
    )
    if SUMS_PATH.read_text(encoding="utf-8") != expected_sums:
        raise AssertionError("SHA256SUMS drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.write:
        write_outputs()
    if arguments.check:
        check_outputs()
    if not arguments.write and not arguments.check:
        parser.error("choose --write and/or --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
