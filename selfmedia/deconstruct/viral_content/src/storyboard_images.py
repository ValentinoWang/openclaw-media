from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from common.feishu_docx_writer import upload_docx_image

IMAGE2_MODULE = "selfmedia.creation.image_generation"
IMAGE2_OUTPUT_DIR_ENV = "GPT_IMAGE2_OUTPUT_DIR"
# Pre-consolidation this module hardcoded its own FEISHU_BASE (never read
# FEISHU_API_BASE_URL) and relied on callers passing feishu_base= to
# override it -- upload_feishu_doc_image now defaults through
# common.feishu_docx_writer.upload_docx_image, which reads the env var.
DEFAULT_STORYBOARD_IMAGE_MAX_IMAGES = int(os.getenv("STORYBOARD_IMAGE_MAX_IMAGES", "12"))
STORYBOARD_IMAGE_TIMEOUT_SEC = int(os.getenv("STORYBOARD_IMAGE_TIMEOUT_SEC", "60"))


def resolve_image2_output_dir() -> Path:
    configured = os.getenv(IMAGE2_OUTPUT_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openclaw" / "generated" / "gpt-image-2"


def generate_storyboard_images(storyboard: list[dict[str, Any]], out_dir: str, max_images: int = DEFAULT_STORYBOARD_IMAGE_MAX_IMAGES) -> list[str]:
    """Generate visual reference images for storyboard shots via gpt-image-2 script."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    image2_output_dir = resolve_image2_output_dir()
    generated: list[str] = []
    for item in storyboard[:max_images]:
        shot_no = item.get("shot_no") or len(generated) + 1
        prompt = (
            "为自媒体短视频分镜生成一张示意图，竖屏9:16，真实短视频截图风格，不要文字水印。\n"
            f"镜头：{shot_no}\n"
            f"画面：{item.get('visual','')}\n"
            f"道具/场景：{item.get('props','')}\n"
            f"运镜：{item.get('camera_movement','')}\n"
            "要求：只做拍摄示意图，不模仿具体真人，不使用名人脸。"
        )
        before = set(image2_output_dir.glob("*"))
        cmd = [sys.executable, "-m", IMAGE2_MODULE, "--prompt", prompt, "--size", "1024x1536", "--format", "png", "--send", "none"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=STORYBOARD_IMAGE_TIMEOUT_SEC)
        except Exception:
            continue
        after = set(image2_output_dir.glob("*"))
        new_files = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)
        if new_files:
            target = out / f"shot_{shot_no}.png"
            try:
                target.write_bytes(new_files[0].read_bytes())
                generated.append(str(target))
            except OSError:
                generated.append(str(new_files[0]))
    return generated


def upload_feishu_doc_image(
    document_id: str,
    file_path: str,
    token: str,
    feishu_base: str | None = None,
    parent_node: str | None = None,
) -> str:
    """Thin wrapper — upload now lives in common.feishu_docx_writer.upload_docx_image
    (FC-09 dedup audit). Kept here (name and signature unchanged) since
    feishu_doc_writer.py imports this by name."""
    return upload_docx_image(
        document_id,
        file_path,
        token,
        feishu_base=feishu_base,
        parent_node=parent_node,
        error_label="分镜图",
    )


def generate_and_upload_storyboard_images(
    storyboard: list[dict[str, Any]],
    out_dir: str,
    document_id: str,
    token: str,
    max_images: int = DEFAULT_STORYBOARD_IMAGE_MAX_IMAGES,
    feishu_base: str | None = None,
) -> list[dict[str, Any]]:
    """Generate recreate storyboard images and upload them for Docx insertion."""
    paths = generate_storyboard_images(storyboard, out_dir, max_images=max_images)
    assets: list[dict[str, Any]] = []
    for idx, path in enumerate(paths, 1):
        shot = storyboard[idx - 1] if idx - 1 < len(storyboard) else {}
        shot_no = shot.get("shot_no") or idx
        try:
            file_token = upload_feishu_doc_image(document_id, path, token, feishu_base=feishu_base)
            assets.append({"shot_no": str(shot_no), "path": path, "file_token": file_token, "status": "uploaded"})
        except Exception as exc:
            assets.append({"shot_no": str(shot_no), "path": path, "file_token": "", "status": "failed", "error": str(exc)})
    return assets
