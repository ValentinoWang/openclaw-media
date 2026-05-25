from __future__ import annotations

from .tag_router_common import *


class MediaReviewMixin:
    def handle_数据复盘(self, message: Message) -> TaskResult:
        metadata = message.metadata or {}
        downloaded_paths = metadata.get("downloaded_paths") or []
        if not isinstance(downloaded_paths, list):
            downloaded_paths = []
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "data-review",
            "--text",
            message.raw_text,
        ]
        for path in downloaded_paths:
            if str(path).strip():
                command.extend(["--attachment", str(path).strip()])
        self._append_conversation_context_arg(command, message)
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=1860, env=self._subprocess_env_with_context(message))
        except subprocess.TimeoutExpired as exc:
            return TaskResult(ok=False, status="data_review_timeout", reply=f"【数据复盘】处理超时：{exc}", task_id="")
        except OSError as exc:
            return TaskResult(ok=False, status="data_review_failed", reply=f"【数据复盘】无法调用 media 工作流：{exc}", task_id="")
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"data review exited with {proc.returncode}"
            return TaskResult(ok=False, status="data_review_failed", reply=error_text[-3000:], task_id="")
        content_os_review = self._maybe_write_content_os_data_review(message, parsed, reply)
        if content_os_review.get("reply"):
            reply = f"{reply}\n{content_os_review['reply']}" if reply else content_os_review["reply"]
        return TaskResult(
            ok=bool(parsed.get("ok", True)),
            status=str(parsed.get("status") or "data_review_done"),
            reply=reply or "【数据复盘】处理完成",
            task_id=str(parsed.get("record_id") or ""),
            feishu_doc=str(parsed.get("doc_link") or ""),
            extra={**parsed, "content_os_review": content_os_review},
        )

    def _looks_like_media_review(self, body: str) -> bool:
        text = body or ""
        if re.search(r"(平台|账号|作者ID|博主|发布链接|作品链接|创作记录ID|作品档案)\s*[=:：]", text):
            return True
        keyword_hits = sum(1 for keyword in MEDIA_REVIEW_KEYWORDS if keyword in text)
        metric_hits = len(MEDIA_REVIEW_METRIC_RE.findall(text))
        return keyword_hits >= 2 or metric_hits >= 2

    def _record_media_review_memory(self, message: Message) -> dict[str, Any]:
        command = [
            "/home/ubuntu/openclaw-agents/media/scripts/selfmedia.py",
            "review",
            "--text",
            message.raw_text,
            "--source",
            message.source,
        ]
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=120, env=self._subprocess_env_with_context(message))
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "reply": f"媒体复盘记忆写入超时：{exc}"}
        except OSError as exc:
            return {"ok": False, "reply": f"媒体复盘记忆脚本无法调用：{exc}"}
        parsed = self._parse_openclaw_json(proc.stdout)
        reply = str(parsed.get("reply") or "").strip()
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or proc.stdout.strip() or f"media review exited with {proc.returncode}"
            return {"ok": False, "reply": error_text[-2000:], "returncode": proc.returncode}
        parsed["ok"] = bool(parsed.get("ok", True))
        if reply:
            parsed["reply"] = reply
        return parsed
