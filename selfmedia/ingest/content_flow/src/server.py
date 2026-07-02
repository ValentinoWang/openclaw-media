from __future__ import annotations

import functools
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from .config import load_settings
from .music import MusicDownloadError, download_music, download_video
from .pipeline import build_graph
from .storage import ensure_media_paths, list_image_files, load_json, load_text, media_exists, save_json
from .utils import detect_platform, extract_douyin_id, extract_xhs_id
from .notion_writer import write_to_notion


_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _iso_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).astimezone().isoformat(timespec="seconds")


def _round_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(value, 0.0), 1)


def _close_current_stage(job: dict[str, Any], now: float) -> None:
    stage = job.get("stage")
    if not stage or stage in {"queued", "done", "error"}:
        return
    started_at = job.get("stage_started_at")
    if not isinstance(started_at, (int, float)):
        return
    durations = dict(job.get("stage_durations") or {})
    durations[stage] = round(float(durations.get(stage, 0.0)) + max(now - started_at, 0.0), 3)
    job["stage_durations"] = durations


def _snapshot_job(job: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(job)
    now = time.time()
    started_at = snapshot.get("started_at")
    finished_at = snapshot.get("finished_at")
    end_at = finished_at if isinstance(finished_at, (int, float)) else now
    if isinstance(started_at, (int, float)):
        snapshot["elapsed_seconds"] = _round_seconds(end_at - started_at)
    stage_started_at = snapshot.get("stage_started_at")
    if isinstance(stage_started_at, (int, float)):
        snapshot["stage_elapsed_seconds"] = _round_seconds(end_at - stage_started_at)
    snapshot["started_at_iso"] = _iso_timestamp(started_at)
    snapshot["updated_at_iso"] = _iso_timestamp(snapshot.get("updated_at"))
    snapshot["finished_at_iso"] = _iso_timestamp(finished_at)
    snapshot["stage_durations"] = {
        key: _round_seconds(value)
        for key, value in dict(snapshot.get("stage_durations") or {}).items()
    }
    return snapshot


def _set_job(job_id: str, **updates: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        now = time.time()
        finished_at = updates.get("finished_at")
        transition_at = finished_at if isinstance(finished_at, (int, float)) else now
        new_stage = updates.get("stage")
        if new_stage and new_stage != job.get("stage"):
            _close_current_stage(job, transition_at)
            updates.setdefault("stage_started_at", transition_at)
        if "finished_at" in updates and updates["finished_at"] is None:
            updates.pop("finished_at")
        elif isinstance(finished_at, (int, float)) and not new_stage:
            _close_current_stage(job, finished_at)
        updates.setdefault("updated_at", now)
        job.update(updates)


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _snapshot_job(job) if job else None


def _create_job(url: str) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "url": url,
            "status": "queued",
            "stage": "queued",
            "percent": 0,
            "message": "queued",
            "result": None,
            "error": None,
            "started_at": now,
            "updated_at": now,
            "stage_started_at": now,
            "stage_durations": {},
            "finished_at": None,
        }
    return job_id


def _make_progress(job_id: str):
    def progress(stage: str, percent: int, message: str) -> None:
        _set_job(
            job_id,
            status="running",
            stage=stage,
            percent=percent,
            message=message,
        )

    return progress


def _run_job(job_id: str, url: str) -> None:
    progress = _make_progress(job_id)
    progress("prepare", 5, "starting")
    try:
        settings = load_settings()
        app = build_graph(settings, progress=progress)
        result = app.invoke(
            {
                "url": url,
                "video_path": None,
                "audio_path": None,
                "image_paths": None,
                "media_type": None,
                "caption": None,
                "image_ocr": None,
                "cover_url": None,
                "transcript": "",
                "analysis_result": {},
                "is_success": True,
                "notion_page_id": None,
                "platform": None,
                "like_count": None,
                "collect_count": None,
                "comment_count": None,
                "share_count": None,
                "top_comments": None,
                "video_id": None,
                "stats_sources": None,
                "interaction_status": None,
                "stats_notice": None,
                "missing_interaction_fields": None,
                "interaction_screenshot_path": None,
                "interaction_screenshot_status": None,
                "interaction_screenshot_error": None,
            }
        )
        cleaned_url = str(result.get("url") or url)
        paths = ensure_media_paths(cleaned_url)
        if result.get("is_success"):
            _set_job(
                job_id,
                status="done",
                stage="done",
                percent=100,
                message="completed",
                result={
                    "notion_page_id": result.get("notion_page_id"),
                    "media_dir": paths.item_dir,
                    "analysis_path": paths.analysis_path,
                    "transcript_path": paths.transcript_path,
                    "interaction_screenshot_path": result.get("interaction_screenshot_path"),
                },
                finished_at=time.time(),
            )
            return

        _set_job(
            job_id,
            status="error",
            stage="error",
            message="flow_failed",
            error="flow_failed",
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )


def _run_music_job(job_id: str, url: str) -> None:
    progress = _make_progress(job_id)
    progress("prepare", 5, "starting")
    try:
        settings = load_settings()
        result = download_music(url, settings, progress=progress)
        _set_job(
            job_id,
            status="done",
            stage="done",
            percent=100,
            message="completed",
            result={
                "audio_path": result.audio_path,
                "media_dir": result.media_dir,
            },
            finished_at=time.time(),
        )
    except MusicDownloadError as exc:
        error_map = {
            "unsupported_media": "仅支持视频链接，图文内容无法提取音频。",
            "audio_extract_failed": "音频提取失败，请确认已安装 ffmpeg。",
        }
        error_code = getattr(exc, "code", str(exc))
        message = error_map.get(error_code, str(exc))
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=message,
            error=error_code,
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )


def _run_video_job(job_id: str, url: str) -> None:
    progress = _make_progress(job_id)
    progress("prepare", 5, "starting")
    try:
        settings = load_settings()
        result = download_video(url, settings, progress=progress)
        _set_job(
            job_id,
            status="done",
            stage="done",
            percent=100,
            message="completed",
            result={
                "video_path": result.video_path,
                "media_dir": result.media_dir,
            },
            finished_at=time.time(),
        )
    except MusicDownloadError as exc:
        error_map = {
            "unsupported_media": "仅支持视频链接，图文内容无法下载视频。",
            "video_download_failed": "视频下载失败，请稍后重试。",
        }
        error_code = getattr(exc, "code", str(exc))
        message = error_map.get(error_code, str(exc))
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=message,
            error=error_code,
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )


def _clean_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in (
        "summary",
        "hooks",
        "emotion",
        "score",
        "tags",
        "action_plan",
        "hidden_info",
        "visual_cues",
        "transferable_expression",
    ):
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if not value.strip():
                continue
            cleaned[key] = value.strip()
        elif isinstance(value, list):
            trimmed = [item for item in value if item is not None and str(item).strip()]
            if trimmed:
                cleaned[key] = trimmed
        else:
            cleaned[key] = value
    return cleaned


def _run_analysis_job(job_id: str, url: str) -> None:
    progress = _make_progress(job_id)
    progress("prepare", 5, "starting")
    try:
        settings = load_settings()
        app = build_graph(settings, progress=progress, include_notion=False)
        result = app.invoke(
            {
                "url": url,
                "video_path": None,
                "audio_path": None,
                "image_paths": None,
                "media_type": None,
                "caption": None,
                "cover_url": None,
                "transcript": "",
                "analysis_result": {},
                "is_success": True,
                "notion_page_id": None,
                "platform": None,
                "like_count": None,
                "collect_count": None,
                "comment_count": None,
                "share_count": None,
                "top_comments": None,
                "video_id": None,
                "stats_sources": None,
                "interaction_status": None,
                "stats_notice": None,
                "missing_interaction_fields": None,
                "interaction_screenshot_path": None,
                "interaction_screenshot_status": None,
                "interaction_screenshot_error": None,
            }
        )
        cleaned_url = str(result.get("url") or url)
        paths = ensure_media_paths(cleaned_url)
        if result.get("is_success"):
            video_path = str(result.get("video_path") or "")
            if not video_path and media_exists(paths.video_path):
                video_path = paths.video_path
            audio_path = str(result.get("audio_path") or "")
            if not audio_path and media_exists(paths.audio_path):
                audio_path = paths.audio_path
            image_paths = result.get("image_paths")
            if not isinstance(image_paths, list):
                image_paths = list_image_files(paths)
            caption = str(result.get("caption") or load_text(paths.caption_path) or "")
            image_ocr = str(result.get("image_ocr") or load_text(paths.ocr_path) or "")
            _set_job(
                job_id,
                status="done",
                stage="done",
                percent=100,
                message="completed",
                result={
                    "analysis": result.get("analysis_result", {}),
                    "media_dir": paths.item_dir,
                    "analysis_path": paths.analysis_path,
                    "transcript_path": paths.transcript_path,
                    "caption_path": paths.caption_path,
                    "caption": caption,
                    "image_ocr": image_ocr,
                    "ocr_path": paths.ocr_path,
                    "video_path": video_path,
                    "audio_path": audio_path,
                    "image_paths": image_paths,
                    "media_type": result.get("media_type"),
                    "interaction_screenshot_path": result.get("interaction_screenshot_path")
                    or (result.get("analysis_result", {}) or {}).get("interaction_screenshot_path"),
                },
                finished_at=time.time(),
            )
            return

        _set_job(
            job_id,
            status="error",
            stage="error",
            message="analysis_failed",
            error="analysis_failed",
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )


def _run_save_job(job_id: str, url: str, analysis: dict[str, Any]) -> None:
    progress = _make_progress(job_id)
    progress("save", 60, "写入 Notion")
    try:
        settings = load_settings()
        paths = ensure_media_paths(url)
        cached_analysis = load_json(paths.analysis_path) or {}
        transcript = load_text(paths.transcript_path) or ""
        caption = load_text(paths.caption_path) or ""

        cleaned = _clean_analysis(analysis)
        analysis_payload = dict(cleaned)

        platform = (
            analysis_payload.get("platform")
            or cached_analysis.get("platform")
            or detect_platform(url)
        )
        if platform:
            analysis_payload["platform"] = platform

        video_id = analysis_payload.get("video_id") or cached_analysis.get("video_id")
        if not video_id:
            _kind, extracted_id = extract_douyin_id(url)
            if extracted_id:
                video_id = extracted_id
            else:
                video_id = extract_xhs_id(url)
        if video_id:
            analysis_payload["video_id"] = video_id

        for key in (
            "like_count",
            "collect_count",
            "comment_count",
            "share_count",
            "top_comments",
            "cover_url",
            "stats_sources",
            "interaction_status",
            "stats_notice",
            "missing_interaction_fields",
            "interaction_screenshot_path",
            "interaction_screenshot_status",
            "interaction_screenshot_error",
        ):
            if analysis_payload.get(key) is None and cached_analysis.get(key) is not None:
                analysis_payload[key] = cached_analysis[key]

        if cached_analysis:
            updated = False
            if video_id and cached_analysis.get("video_id") != video_id:
                cached_analysis["video_id"] = video_id
                updated = True
            if platform and not cached_analysis.get("platform"):
                cached_analysis["platform"] = platform
                updated = True
            if updated:
                save_json(paths.analysis_path, cached_analysis)

        page_id = write_to_notion(url, transcript, caption, analysis_payload, settings)
        if page_id:
            _set_job(
                job_id,
                status="done",
                stage="done",
                percent=100,
                message="completed",
                result={
                    "notion_page_id": page_id,
                    "media_dir": paths.item_dir,
                },
                finished_at=time.time(),
            )
            return
        _set_job(
            job_id,
            status="error",
            stage="error",
            message="notion_write_failed",
            error="notion_write_failed",
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )


def _run_manual_job(job_id: str, url: str, summary: str) -> None:
    progress = _make_progress(job_id)
    progress("manual", 60, "准备写入 Notion")
    try:
        settings = load_settings()
        platform = detect_platform(url)
        _kind, video_id = extract_douyin_id(url)
        if not video_id:
            video_id = extract_xhs_id(url)
        analysis = {
            "summary": summary,
            "platform": platform,
            "video_id": video_id,
        }
        page_id = write_to_notion(url, "", "", analysis, settings)
        paths = ensure_media_paths(url)
        if page_id:
            _set_job(
                job_id,
                status="done",
                stage="done",
                percent=100,
                message="completed",
                result={
                    "notion_page_id": page_id,
                    "media_dir": paths.item_dir,
                },
                finished_at=time.time(),
            )
            return
        _set_job(
            job_id,
            status="error",
            stage="error",
            message="notion_write_failed",
            error="notion_write_failed",
            finished_at=time.time(),
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="error",
            message=str(exc),
            error=str(exc),
            finished_at=time.time(),
        )


class RequestHandler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._handle_status(parsed)
            return
        if parsed.path == "/api/audio/file":
            self._handle_audio_file(parsed)
            return
        if parsed.path == "/api/video/file":
            self._handle_video_file(parsed)
            return
        if parsed.path == "/api/screenshot/file":
            self._handle_screenshot_file(parsed)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in (
            "/api/run",
            "/api/manual",
            "/api/analyze",
            "/api/save",
            "/api/audio",
            "/api/video",
        ):
            self.send_error(404, "Not Found")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        url = str(payload.get("url", "")).strip()
        if not url:
            self._send_json(400, {"error": "missing_url"})
            return

        if parsed.path == "/api/audio":
            job_id = _create_job(url)
            worker = threading.Thread(
                target=_run_music_job,
                args=(job_id, url),
                daemon=True,
            )
            worker.start()
            self._send_json(200, {"job_id": job_id})
            return

        if parsed.path == "/api/video":
            job_id = _create_job(url)
            worker = threading.Thread(
                target=_run_video_job,
                args=(job_id, url),
                daemon=True,
            )
            worker.start()
            self._send_json(200, {"job_id": job_id})
            return

        if parsed.path == "/api/analyze":
            job_id = _create_job(url)
            worker = threading.Thread(
                target=_run_analysis_job,
                args=(job_id, url),
                daemon=True,
            )
            worker.start()
            self._send_json(200, {"job_id": job_id})
            return

        if parsed.path == "/api/save":
            analysis = payload.get("analysis")
            if not isinstance(analysis, dict):
                self._send_json(400, {"error": "missing_analysis"})
                return
            job_id = _create_job(url)
            worker = threading.Thread(
                target=_run_save_job,
                args=(job_id, url, analysis),
                daemon=True,
            )
            worker.start()
            self._send_json(200, {"job_id": job_id})
            return

        if parsed.path == "/api/manual":
            summary = str(payload.get("summary", "")).strip()
            if not summary:
                self._send_json(400, {"error": "missing_summary"})
                return
            job_id = _create_job(url)
            worker = threading.Thread(
                target=_run_manual_job,
                args=(job_id, url, summary),
                daemon=True,
            )
            worker.start()
            self._send_json(200, {"job_id": job_id})
            return

        job_id = _create_job(url)
        worker = threading.Thread(target=_run_job, args=(job_id, url), daemon=True)
        worker.start()
        self._send_json(200, {"job_id": job_id})

    def _handle_status(self, parsed) -> None:
        params = parse_qs(parsed.query)
        job_id = params.get("job_id", [""])[0]
        if not job_id:
            self._send_json(400, {"error": "missing_job_id"})
            return
        job = _get_job(job_id)
        if not job:
            self._send_json(404, {"error": "job_not_found"})
            return
        self._send_json(200, job)

    def _handle_media_file(
        self,
        parsed,
        field_name: str,
        content_type: str,
        missing_code: str,
        read_code: str,
    ) -> None:
        params = parse_qs(parsed.query)
        job_id = params.get("job_id", [""])[0]
        if not job_id:
            self._send_json(400, {"error": "missing_job_id"})
            return
        job = _get_job(job_id)
        if not job:
            self._send_json(404, {"error": "job_not_found"})
            return
        if job.get("status") != "done":
            self._send_json(409, {"error": "job_not_ready"})
            return
        result = job.get("result") or {}
        media_path = result.get(field_name)
        if not media_path or not os.path.isfile(media_path):
            self._send_json(404, {"error": missing_code})
            return
        try:
            file_size = os.path.getsize(media_path)
            filename = os.path.basename(media_path)
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Content-Disposition", f'attachment; filename=\"{filename}\"')
            self.end_headers()
            with open(media_path, "rb") as handle:
                shutil.copyfileobj(handle, self.wfile)
        except OSError:
            self._send_json(500, {"error": read_code})

    def _handle_audio_file(self, parsed) -> None:
        self._handle_media_file(
            parsed,
            "audio_path",
            "audio/mpeg",
            "audio_not_found",
            "audio_read_failed",
        )

    def _handle_video_file(self, parsed) -> None:
        self._handle_media_file(
            parsed,
            "video_path",
            "video/mp4",
            "video_not_found",
            "video_read_failed",
        )

    def _handle_screenshot_file(self, parsed) -> None:
        self._handle_media_file(
            parsed,
            "interaction_screenshot_path",
            "image/png",
            "screenshot_not_found",
            "screenshot_read_failed",
        )

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str, port: int) -> None:
    base_dir = Path(__file__).resolve().parents[1]
    frontend_dir = base_dir / "frontend"
    handler = functools.partial(RequestHandler, directory=str(frontend_dir))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main() -> None:
    load_dotenv(".env")
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))
    run_server(host, port)


if __name__ == "__main__":
    main()
