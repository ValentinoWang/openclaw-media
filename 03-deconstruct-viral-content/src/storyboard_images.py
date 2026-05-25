from __future__ import annotations

import json
import os
import subprocess
import mimetypes
from pathlib import Path
from typing import Any

import requests

IMAGE2_SCRIPT = "/home/ubuntu/selfmedia-tools/tools/openclaw_media/gpt_image2.py"
FEISHU_BASE = "https://open.feishu.cn/open-apis"
DEFAULT_STORYBOARD_IMAGE_MAX_IMAGES = int(os.getenv("STORYBOARD_IMAGE_MAX_IMAGES", "12"))
STORYBOARD_IMAGE_TIMEOUT_SEC = int(os.getenv("STORYBOARD_IMAGE_TIMEOUT_SEC", "60"))


def generate_storyboard_images(storyboard: list[dict[str, Any]], out_dir: str, max_images: int = DEFAULT_STORYBOARD_IMAGE_MAX_IMAGES) -> list[str]:
    """Generate visual reference images for storyboard shots via gpt-image-2 script."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
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
        before = set(Path('/home/ubuntu/openclaw-agents/media/generated/gpt-image-2').glob('*'))
        cmd = [IMAGE2_SCRIPT, "--prompt", prompt, "--size", "1024x1536", "--format", "png", "--send", "none"]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=STORYBOARD_IMAGE_TIMEOUT_SEC)
        except Exception:
            continue
        after = set(Path('/home/ubuntu/openclaw-agents/media/generated/gpt-image-2').glob('*'))
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
    path = Path(file_path)
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"分镜图不存在，不能插入飞书文档：{file_path}")
    base = (feishu_base or FEISHU_BASE).rstrip("/")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    with path.open("rb") as handle:
        resp = requests.post(
            f"{base}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": path.name,
                "parent_type": "docx_image",
                "parent_node": parent_node or document_id,
                "size": str(path.stat().st_size),
                "mime_type": mime,
            },
            files={"file": (path.name, handle, mime)},
            timeout=60,
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"上传飞书分镜图失败：HTTP {resp.status_code} {resp.text[:300]}") from exc
    if resp.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"上传飞书分镜图失败：{payload}")
    file_token = payload.get("data", {}).get("file_token") or ""
    if not file_token:
        raise RuntimeError(f"上传飞书分镜图未返回 file_token：{payload}")
    return file_token


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
