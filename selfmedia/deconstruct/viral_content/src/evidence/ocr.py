from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from common.ocr_lines import clean_ocr_lines as _clean_ocr_text

from .schemas import OcrEvidence


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _image_size(path: str) -> tuple[int, int]:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return (0, 0)
    match = re.search(r"(\d+)x(\d+)", proc.stdout)
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def _run_tesseract_tsv(path: str) -> list[dict[str, Any]]:
    if not shutil.which("tesseract"):
        return []
    try:
        proc = subprocess.run(
            ["tesseract", path, "stdout", "-l", "chi_sim+eng", "--psm", "6", "tsv"],
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    lines = proc.stdout.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for raw in lines[1:]:
        parts = raw.split("\t")
        if len(parts) < len(header):
            parts.extend([""] * (len(header) - len(parts)))
        row = dict(zip(header, parts))
        if str(row.get("text") or "").strip():
            rows.append(row)
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""))
        groups.setdefault(key, []).append(row)
    width, height = _image_size(path)
    segments: list[dict[str, Any]] = []
    for group_rows in groups.values():
        text = _clean_ocr_text(" ".join(row.get("text", "") for row in group_rows))
        if not text:
            continue
        confidences = []
        boxes = []
        for row in group_rows:
            try:
                conf = float(row.get("conf", "-1"))
                if conf >= 0:
                    confidences.append(conf / 100 if conf > 1 else conf)
            except (TypeError, ValueError):
                pass
            try:
                left = float(row.get("left", "0"))
                top = float(row.get("top", "0"))
                w = float(row.get("width", "0"))
                h = float(row.get("height", "0"))
                boxes.append((left, top, left + w, top + h))
            except (TypeError, ValueError):
                pass
        bbox: list[float] = []
        if boxes and width > 0 and height > 0:
            x1 = min(item[0] for item in boxes) / width
            y1 = min(item[1] for item in boxes) / height
            x2 = max(item[2] for item in boxes) / width
            y2 = max(item[3] for item in boxes) / height
            bbox = [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]
        confidence = sum(confidences) / len(confidences) if confidences else None
        segments.append({"text": text, "bbox": bbox, "confidence": confidence})
    return segments


def _select_assets(visual_assets: list[dict[str, Any]], max_frames: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in visual_assets:
        kind = str(item.get("kind") or "")
        if kind in {"cover_image", "source_image"}:
            selected.append(item)
    first5 = [item for item in visual_assets if str(item.get("kind") or "") == "first5s_frame"]
    selected.extend(first5[: min(8, max_frames)])
    remaining = [item for item in visual_assets if item not in selected]
    if remaining:
        step = max(1, len(remaining) // max(1, max_frames - len(selected)))
        selected.extend(remaining[::step])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected:
        asset_id = str(item.get("asset_id") or "")
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        deduped.append(item)
        if len(deduped) >= max_frames:
            break
    return deduped


def _tracks_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    by_norm: dict[str, dict[str, Any]] = {}
    for item in segments:
        norm = _normalize_text(str(item.get("text") or ""))
        if not norm:
            continue
        current = by_norm.get(norm)
        if not current:
            current = {
                "track_id": f"txt_{len(by_norm) + 1:03d}",
                "text": item["text"],
                "start_asset_id": item["asset_id"],
                "end_asset_id": item["asset_id"],
                "asset_ids": [],
                "_conf": [],
            }
            by_norm[norm] = current
            tracks.append(current)
        current["end_asset_id"] = item["asset_id"]
        if item["asset_id"] not in current["asset_ids"]:
            current["asset_ids"].append(item["asset_id"])
        if item.get("confidence") is not None:
            current["_conf"].append(float(item["confidence"]))
    result: list[dict[str, Any]] = []
    for track in tracks:
        confidences = track.pop("_conf", [])
        track["confidence_avg"] = round(sum(confidences) / len(confidences), 4) if confidences else None
        result.append(track)
    return result


def build_ocr_evidence(
    visual_assets: list[dict[str, Any]],
    *,
    ocr_path: str | None = None,
    max_frames: int = 16,
) -> dict[str, Any]:
    sampling_policy = {
        "cover": "platform_cover_first",
        "video_frames": "cover + first5_priority + post5_interval_or_scene_change",
        "dedupe": "normalized_text_similarity",
        "max_frames": max_frames,
    }
    if not visual_assets:
        return OcrEvidence(status="no_visible_text", sampling_policy=sampling_policy, reason="no_visual_assets").dict()

    selected = _select_assets(visual_assets, max_frames=max_frames)
    segments: list[dict[str, Any]] = []
    seen_segment_text: set[tuple[str, str]] = set()
    for item in selected:
        asset_id = str(item.get("asset_id") or "")
        path = str(item.get("path") or "")
        if not asset_id or not path or not os.path.isfile(path):
            continue
        raw_segments = _run_tesseract_tsv(path)
        for raw in raw_segments:
            text = _clean_ocr_text(str(raw.get("text") or ""))
            norm_key = (asset_id, _normalize_text(text))
            if not text or norm_key in seen_segment_text:
                continue
            seen_segment_text.add(norm_key)
            segments.append(
                {
                    "text_segment_id": f"ocr_{len(segments) + 1:03d}",
                    "asset_id": asset_id,
                    "bbox": raw.get("bbox") or [],
                    "text": text,
                    "confidence": raw.get("confidence"),
                }
            )

    if not segments:
        return OcrEvidence(status="no_visible_text", sampling_policy=sampling_policy, reason="no_reliable_text").dict()

    tracks = _tracks_from_segments(segments)
    first_asset = segments[0]["asset_id"]
    cover_candidates = [
        {
            "source": "first_frame",
            "asset_id": first_asset,
            "text": segments[0]["text"],
            "confidence": segments[0].get("confidence"),
        }
    ]
    return OcrEvidence(
        status="success",
        sampling_policy=sampling_policy,
        visible_text_segments=segments,
        text_tracks=tracks,
        cover_text_candidates=cover_candidates,
    ).dict()


def ocr_summary_for_prompt(ocr: dict[str, Any], *, max_items: int = 40) -> str:
    status = str(ocr.get("status") or "")
    if status != "success":
        return f"ocr.status={status or 'unknown'}；无可靠屏幕文字证据，LLM 不得编造 OCR 证据引用。原因：{ocr.get('reason', '')}"
    lines = ["ocr.status=success；以下屏幕文字可被 LLM 引用，必须使用真实 text_segment_id 和 asset_id："]
    for item in ocr.get("visible_text_segments") or []:
        lines.append(f"- {item.get('text_segment_id')} asset_id={item.get('asset_id')} text={str(item.get('text') or '').strip()[:160]}")
        if len(lines) > max_items:
            lines.append("- ...（已截断，完整 visible_text_segments 见 facts/ocr_facts.json 与 evidence_store）")
            break
    if ocr.get("text_tracks"):
        lines.append("合并后的 text_tracks：")
        for track in (ocr.get("text_tracks") or [])[:10]:
            lines.append(f"- {track.get('track_id')} {track.get('start_asset_id')}->{track.get('end_asset_id')} text={str(track.get('text') or '').strip()[:160]}")
    return "\n".join(lines)
