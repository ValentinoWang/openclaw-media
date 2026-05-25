from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib import request


BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen-vl-ocr-latest"
FPS_INTERVAL_SECONDS = 12

# These frames were hand-picked from a quick contact-sheet pass.
# They are sampled from `fps=1/12`, so frame_0001 ~= 12s, frame_0002 ~= 24s, etc.
SELECTED_SAMPLE_FRAMES = [
    5,
    6,
    10,
    19,
    25,
    37,
    45,
    55,
    65,
    71,
    76,
    79,
    81,
    95,
    100,
    102,
    113,
    116,
    121,
    127,
    128,
    133,
    136,
    141,
    146,
    148,
]


@dataclass(frozen=True)
class SlideAsset:
    sample_index: int
    timestamp_seconds: int
    source_path: Path
    crop_path: Path
    raw_output_path: Path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def ensure_sample_frames(video_path: Path, frames_dir: Path) -> None:
    existing = sorted(frames_dir.glob("frame_*.jpg"))
    if existing:
        return
    frames_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{FPS_INTERVAL_SECONDS},scale=1280:-1",
            "-q:v",
            "2",
            str(frames_dir / "frame_%04d.jpg"),
        ]
    )


def crop_slide_image(source_path: Path, crop_path: Path) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            "crop=iw*0.92:ih*0.82:iw*0.04:ih*0.04",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(crop_path),
        ]
    )


def prepare_assets(video_path: Path, output_dir: Path) -> list[SlideAsset]:
    frames_dir = output_dir / "sample_frames"
    crops_dir = output_dir / "slides"
    raw_dir = output_dir / "ocr_raw"
    ensure_sample_frames(video_path, frames_dir)
    crops_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    assets: list[SlideAsset] = []
    for sample_index in SELECTED_SAMPLE_FRAMES:
        source_path = frames_dir / f"frame_{sample_index:04d}.jpg"
        if not source_path.exists():
            continue

        slide_number = len(assets) + 1
        crop_path = crops_dir / f"slide_{slide_number:02d}_frame_{sample_index:04d}.jpg"
        if not crop_path.exists():
            crop_slide_image(source_path, crop_path)

        raw_output_path = raw_dir / f"slide_{slide_number:02d}.txt"
        assets.append(
            SlideAsset(
                sample_index=sample_index,
                timestamp_seconds=sample_index * FPS_INTERVAL_SECONDS,
                source_path=source_path,
                crop_path=crop_path,
                raw_output_path=raw_output_path,
            )
        )
    return assets


def encode_image(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def make_headers() -> dict[str, str]:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing DASHSCOPE_API_KEY")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def ocr_slide(headers: dict[str, str], image_path: Path) -> str:
    data_url = f"data:image/jpeg;base64,{encode_image(image_path)}"
    prompt = (
        "你是 PPT 文字提取助手。请只提取当前幻灯片中央主视觉中的正文内容。"
        "严格忽略底部视频字幕、讲者姓名、品牌水印、赞助商名称、logo、角落里的 YiXi、"
        "华泰证券、bilibili、一席精选等固定字样，以及与 PPT 无关的舞台元素。"
        "如果这一页主要是图片或插画，没有足够清晰文字，请输出“[图像页] ”并补一句简短说明。"
        "如果能辨认出标题和要点，请优先保留标题，再逐行写要点。输出纯文本，不要加解释。"
    )
    payload = {
        "model": os.getenv("DASHSCOPE_MODEL", MODEL),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                        "min_pixels": 32 * 32 * 3,
                        "max_pixels": 32 * 32 * 8192,
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    req = request.Request(
        url=os.getenv("DASHSCOPE_BASE_URL", BASE_URL).rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    try:
        return (body["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        raise RuntimeError(f"unexpected_response: {json.dumps(body, ensure_ascii=False)[:800]}") from exc


def seconds_to_timestamp(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def clean_ocr_text(text: str) -> str:
    lines: list[str] = []
    noise_exact = {
        "YiXi",
        "听君一席话 Get inspired",
        "华泰证券",
        "HUTAI SECURITIES",
        "bilibili",
        "一席精选 bili",
        "一席精选",
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\[?\d{2,4},\d{2,4},\d{1,4},\d{1,4},\d{1,3}\]?\s*", "", line)
        line = re.sub(r"^\d{2,4},\d{2,4},\d{1,4},\d{1,4},\d{1,3}\s*", "", line)
        line = line.strip("[] ,")
        line = line.replace("图像页]", "图像页").strip()
        if not line or line in noise_exact:
            continue
        if line.lower() in {"yixi", "bilibili"}:
            continue
        lines.append(line)
    if not lines:
        return "[空]"
    return "\n".join(lines)


def build_markdown(assets: list[SlideAsset], output_dir: Path) -> Path:
    md_path = output_dir / "ppt_outline_qwen_ocr.md"
    lines = [
        "# PPT 提取结果",
        "",
        f"- 模型：`{os.getenv('DASHSCOPE_MODEL', MODEL)}`",
        f"- Base URL：`{os.getenv('DASHSCOPE_BASE_URL', BASE_URL)}`",
        f"- 抽帧间隔：每 {FPS_INTERVAL_SECONDS} 秒 1 帧",
        "",
        "## 幻灯片大纲",
        "",
    ]
    for idx, asset in enumerate(assets, start=1):
        if asset.raw_output_path.exists():
            text = clean_ocr_text(asset.raw_output_path.read_text(encoding="utf-8").strip())
        else:
            text = "[待 OCR]"
        rel_image = asset.crop_path.relative_to(output_dir)
        lines.extend(
            [
                f"### Slide {idx:02d}",
                "",
                f"- 采样帧：`frame_{asset.sample_index:04d}`",
                f"- 时间点：`{seconds_to_timestamp(asset.timestamp_seconds)}`",
                f"- 图片：`{rel_image.as_posix()}`",
                "",
                "```text",
                text or "[空]",
                "```",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--force-ocr", action="store_true")
    args = parser.parse_args()

    video_path = args.video.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    assets = prepare_assets(video_path, output_dir)
    if not args.skip_ocr:
        headers = make_headers()
        for asset in assets:
            if asset.raw_output_path.exists() and not args.force_ocr:
                continue
            text = ocr_slide(headers, asset.crop_path)
            asset.raw_output_path.write_text(text + "\n", encoding="utf-8")

    md_path = build_markdown(assets, output_dir)
    print(json.dumps({"slides": len(assets), "markdown": str(md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
