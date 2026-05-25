from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..models.message import Message
from .utils import ensure_dir, format_display_time, safe_slug, short_id


VLOG_ASSET_EXTS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
    ".mkv",
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".flac",
    ".ogg",
    ".opus",
    ".amr",
    ".caf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".heic",
    ".heif",
    ".pdf",
    ".txt",
    ".md",
    ".doc",
    ".docx",
}

UPLOADED_MEDIA_ROOTS = [
    Path(item.strip())
    for item in re.split(
        r"[:,]",
        os.environ.get(
            "OPENCLAW_UPLOADED_MEDIA_ROOTS",
            "/home/ubuntu/.openclaw/media/inbound:/home/ubuntu/openclaw-feishu-gateway/downloads",
        ),
    )
    if item.strip()
]


class VlogStorageService:
    def __init__(self, workspace_root: str | Path, timezone: str):
        self.workspace_root = Path(workspace_root)
        self.timezone = timezone
        self.package_root = ensure_dir(self.workspace_root / "content_flow" / "vlog_inspirations")
        self.runtime_root = ensure_dir(self.workspace_root / "runtime" / "icloud_auth")
        self.rclone_bin = os.environ.get("OPENCLAW_RCLONE_BIN", "rclone")
        self.remote = os.environ.get("OPENCLAW_VLOG_ICLOUD_REMOTE", "icloud").strip().rstrip(":") or "icloud"
        self.remote_root = os.environ.get("OPENCLAW_VLOG_ICLOUD_ROOT", "OpenClaw/vlog-assets").strip().strip("/")
        self.upload_timeout_seconds = int(os.environ.get("OPENCLAW_VLOG_UPLOAD_TIMEOUT_SECONDS", "900"))
        self.auth_script = Path(__file__).resolve().parents[2] / "scripts" / "icloud_auth_relay.py"
        self.pyicloud_script = Path(__file__).resolve().parents[2] / "scripts" / "pyicloud_bridge.py"
        self.pyicloud_python = os.environ.get("OPENCLAW_PYICLOUD_PYTHON", "/home/ubuntu/.openclaw/venvs/pyicloud/bin/python")
        self.pyicloud_china_mainland = os.environ.get("OPENCLAW_VLOG_ICLOUD_CHINA_MAINLAND", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "cn",
            "china",
            "chinamainland",
        }

    def handle_control_command(self, body: str) -> dict[str, Any] | None:
        text = (body or "").strip()
        compact = re.sub(r"\s+", "", text).lower()
        if not text:
            return None
        if compact in {"icloud状态", "存储状态", "icloud存储状态"} or (
            ("icloud" in compact or "存储" in compact) and ("状态" in compact or "检查" in compact)
        ):
            return {"kind": "status", "result": self.status()}
        if compact in {"icloud认证", "icloud续期", "icloud重连", "认证", "续期"} or (
            "icloud" in compact and any(word in compact for word in ("认证", "续期", "重连", "登录"))
        ):
            return {"kind": "auth_start", "result": self.start_auth_session()}
        if compact in {"取消认证", "icloud取消认证", "取消icloud认证"}:
            return {"kind": "auth_cancel", "result": self.cancel_auth_session()}
        if match := re.match(r"^(?:icloud账号|iCloud账号|apple\s*id|Apple\s*ID|appleid|AppleID|账号)\s*[:：]?\s*(\S+@\S+)\s*$", text, flags=re.IGNORECASE):
            return {"kind": "setup_account", "result": self.save_setup_account(match.group(1))}
        if match := re.match(r"^(?:icloud密码|iCloud密码|apple\s*id\s*密码|Apple\s*ID\s*密码|apple密码|Apple密码|密码)\s*[:：]?\s*(.+?)\s*$", text, flags=re.IGNORECASE | re.DOTALL):
            return {"kind": "setup_password", "result": self.create_remote_with_password(match.group(1))}
        if match := re.match(r"^(?:验证码|验证|2fa|2FA|code|CODE)\s*[:：]?\s*([0-9]{4,8}|sms|SMS|y|Y|yes|YES|n|N|no|NO)\s*$", text):
            return {"kind": "auth_send", "result": self.send_auth_input(match.group(1))}
        if match := re.match(r"^重试上传\s*(?P<vlog_id>VLOG-[A-Za-z0-9_.:-]+)?\s*$", text, flags=re.IGNORECASE):
            return {"kind": "retry", "result": self.retry_pending_uploads((match.group("vlog_id") or "").strip())}
        return None

    def status(self) -> dict[str, Any]:
        list_result = self._run_rclone(["listremotes"], timeout=20)
        configured = f"{self.remote}:" in (list_result.get("stdout") or "").splitlines()
        auth = self._auth_status()
        pyicloud = self._pyicloud_status()
        result: dict[str, Any] = {
            "remote": self.remote,
            "remote_root": self.remote_root,
            "configured": configured,
            "rclone_ok": list_result["ok"],
            "auth": auth,
            "pyicloud": pyicloud,
            "backend": "",
        }
        if pyicloud.get("status") == "ready":
            result["configured"] = True
            result["status"] = "ready"
            result["backend"] = "pyicloud"
            result["probe_ok"] = True
            return result
        if not list_result["ok"]:
            result["error"] = list_result.get("error") or list_result.get("stderr")
            return result
        if not configured:
            result["status"] = "not_configured"
            return result
        probe = self._run_rclone(["lsf", f"{self.remote}:", "--max-depth", "1"], timeout=45)
        result["probe_ok"] = probe["ok"]
        if probe["ok"]:
            result["status"] = "ready"
            result["backend"] = "rclone"
        else:
            result["status"] = "auth_or_network_error" if self._looks_like_auth_error(probe.get("stderr", "")) else "probe_failed"
            result["error"] = probe.get("stderr") or probe.get("error")
            if self._looks_like_china_icloud_redirect(str(result.get("error") or "")):
                result["backend"] = "pyicloud"
            elif self._should_use_pyicloud_china():
                result["backend"] = "pyicloud"
        return result

    def ingest(self, message: Message) -> dict[str, Any]:
        vlog_id = f"VLOG-{message.created_at.strftime('%Y%m%d-%H%M%S')}-{short_id()}"
        package_dir = ensure_dir(self.package_root / vlog_id)
        remote_folder = self._remote_folder(message.created_at, vlog_id)
        asset_paths = self.collect_asset_paths(message)
        timeline = self.timeline_items(message)
        asset_time_contexts = self._asset_time_contexts(message, asset_paths, timeline)
        assets = self._store_assets(asset_paths, remote_folder, asset_time_contexts)
        data_options = self._manifest_data_options(assets)
        package_upload_dt = self._package_upload_datetime(message, assets)
        manifest = {
            "schema_version": "1.0",
            "vlog_id": vlog_id,
            "created_at": format_display_time(message.created_at),
            "upload_timestamp": package_upload_dt.isoformat(timespec="seconds"),
            "upload_time_key": self._upload_time_key(package_upload_dt),
            "data_option_key": f"vlog-upload:{self._upload_time_key(package_upload_dt)}:{vlog_id}",
            "data_option": self._package_data_option(vlog_id, message, package_upload_dt, f"{self.remote}:{remote_folder}"),
            "entry_tag": message.entry_tag,
            "source": message.source,
            "message_id": (message.metadata or {}).get("message_id", ""),
            "chat_id": (message.metadata or {}).get("chat_id", ""),
            "body": message.body,
            "remote": self.remote,
            "remote_root": self.remote_root,
            "remote_folder": f"{self.remote}:{remote_folder}",
            "asset_count": len(assets),
            "assets": assets,
            "data_options": data_options,
            "timeline": timeline,
        }
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path)
        return {
            "vlog_id": vlog_id,
            "title": self._title_from_body(message.body, vlog_id),
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "sections": self.markdown_sections(message, manifest),
            "frontmatter": self.frontmatter(manifest),
            "reply_lines": self.reply_lines(manifest),
        }

    def retry_pending_uploads(self, vlog_id: str = "") -> dict[str, Any]:
        manifest_path = self._find_manifest(vlog_id)
        if not manifest_path:
            return {"ok": False, "status": "manifest_missing", "reply": "未找到可重试的 vlog 素材清单。"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        remote_folder = str(manifest.get("remote_folder") or "").removeprefix(f"{self.remote}:")
        if not remote_folder:
            remote_folder = self._remote_folder(datetime.now(), str(manifest.get("vlog_id") or manifest_path.parent.name))
        retried = 0
        uploaded = 0
        failed: list[str] = []
        for asset in manifest.get("assets") or []:
            if not isinstance(asset, dict) or asset.get("status") == "uploaded":
                continue
            local_path = Path(str(asset.get("local_path") or ""))
            if not local_path.is_file():
                failed.append(f"{asset.get('filename') or local_path.name}：本地文件不存在")
                continue
            retried += 1
            filename = str(asset.get("remote_filename") or asset.get("filename") or local_path.name)
            backend = str(self.status().get("backend") or "")
            upload = self._upload_one(local_path, remote_folder, filename, backend=backend)
            asset.update(upload)
            if upload.get("status") == "uploaded":
                uploaded += 1
                asset["delete_status"] = self._delete_uploaded_cache_file(local_path)
            else:
                failed.append(f"{filename}：{upload.get('reason') or upload.get('error') or upload.get('status')}")
        manifest["assets"] = manifest.get("assets") or []
        manifest["asset_count"] = len(manifest["assets"])
        manifest["retried_at"] = datetime.now().isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "ok": uploaded > 0 and not failed,
            "status": "retried",
            "manifest_path": str(manifest_path),
            "retried": retried,
            "uploaded": uploaded,
            "failed": failed,
            "remote_folder": f"{self.remote}:{remote_folder}",
        }

    def collect_asset_paths(self, message: Message) -> list[str]:
        candidates: list[str] = []

        def add(value: object) -> None:
            if not isinstance(value, str):
                return
            text = value.strip()
            if not text:
                return
            path_matches = re.findall(r"/[^\s\]\)\|`'\"<>]+", text)
            if path_matches:
                candidates.extend(match.rstrip("，。；;,.:：") for match in path_matches)
            else:
                candidates.append(text)

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key in (
                    "path",
                    "file_path",
                    "filePath",
                    "local_path",
                    "localPath",
                    "downloaded_path",
                    "downloadedPath",
                    "url",
                ):
                    add(value.get(key))
                for nested in value.values():
                    if isinstance(nested, (dict, list, tuple)):
                        walk(nested)
                    elif isinstance(nested, str):
                        add(nested)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
            else:
                add(value)

        metadata = message.metadata or {}
        for key in (
            "downloaded_paths",
            "attachment_paths",
            "attachments",
            "files",
            "media",
            "local_paths",
            "file_paths",
            "cached_media",
            "previous_media",
            "previous_attachments",
        ):
            if key in metadata:
                walk(metadata.get(key))
        for text in (message.body, message.raw_text, str((metadata.get("conversation_context") or {}).get("prompt") or "")):
            add(text)

        seen: set[str] = set()
        paths: list[str] = []
        for item in candidates:
            path = Path(item)
            if not path.is_absolute() or not path.is_file():
                continue
            if path.suffix.lower() not in VLOG_ASSET_EXTS:
                continue
            normalized = str(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(normalized)
        return paths

    def timeline_items(self, message: Message) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        context = self._conversation_context(message)
        for item in context.get("items") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text and item.get("attachments"):
                names = [str(att.get("file_name") or att.get("file_key") or "") for att in item.get("attachments") or []]
                text = "附件：" + "、".join(name for name in names if name)
            if not text and not item.get("downloaded_paths"):
                continue
            items.append(
                {
                    "created_at": str(item.get("created_at") or ""),
                    "message_type": str(item.get("message_type") or ""),
                    "message_id": str(item.get("message_id") or ""),
                    "text": text,
                    "attachments": item.get("attachments") or [],
                    "downloaded_paths": item.get("downloaded_paths") or [],
                }
            )
        items.append(
            {
                "created_at": format_display_time(message.created_at),
                "message_type": str((message.metadata or {}).get("message_type") or "text"),
                "message_id": str((message.metadata or {}).get("message_id") or ""),
                "text": message.raw_text,
                "attachments": (message.metadata or {}).get("attachments") or [],
                "downloaded_paths": (message.metadata or {}).get("downloaded_paths") or [],
                "current": True,
            }
        )
        return items

    def markdown_sections(self, message: Message, manifest: dict[str, Any]) -> list[tuple[str, str]]:
        return [
            ("原始灵感", message.body.strip() or "（本条消息没有正文，素材来自同一批附件或最近上下文）"),
            ("时序上下文", self._format_timeline(manifest.get("timeline") or [])),
            ("素材链接", self._format_assets(manifest.get("assets") or [])),
            ("数据选项", self._format_data_options(manifest)),
            (
                "剪辑可能性",
                "\n".join(
                    [
                        "- 保留原始表达和补充回复的时间顺序，后续剪辑 agent 可按本清单取素材。",
                        "- 开头优先使用当前这条灵感的核心问题或现场感表达。",
                        "- 中段按附件上传顺序和上下文时间线组织画面、录音、截图。",
                        "- 结尾保留待补充点，方便后续继续追加素材或重试上传。",
                    ]
                ),
            ),
            ("存储清单", f"- Manifest：{manifest.get('manifest_path')}\n- iCloud 目录：{manifest.get('remote_folder')}"),
        ]

    def frontmatter(self, manifest: dict[str, Any]) -> dict[str, Any]:
        assets = manifest.get("assets") or []
        uploaded = sum(1 for item in assets if isinstance(item, dict) and item.get("status") == "uploaded")
        done = sum(1 for item in assets if isinstance(item, dict) and item.get("status") in {"uploaded", "duplicate"})
        return {
            "status": "archived" if done == len(assets) else "pending_storage",
            "tags": ["灵感-vlog", "vlog素材", "时序素材"],
            "vlog_id": manifest.get("vlog_id", ""),
            "manifest_path": manifest.get("manifest_path", ""),
            "data_option_key": manifest.get("data_option_key", ""),
            "upload_timestamp": manifest.get("upload_timestamp", ""),
            "upload_time_key": manifest.get("upload_time_key", ""),
            "storage_backend": "icloud",
            "storage_remote": self.remote,
            "storage_remote_folder": manifest.get("remote_folder", ""),
            "asset_count": len(assets),
            "asset_uploaded_count": uploaded,
        }

    def reply_lines(self, manifest: dict[str, Any]) -> list[str]:
        assets = [item for item in manifest.get("assets") or [] if isinstance(item, dict)]
        uploaded = [item for item in assets if item.get("status") == "uploaded"]
        pending = [item for item in assets if item.get("status") not in {"uploaded", "duplicate"}]
        lines = [
            "Vlog 灵感已归档。",
            f"素材包：{manifest.get('vlog_id')}",
            f"Manifest：{manifest.get('manifest_path')}",
            f"iCloud目录：{manifest.get('remote_folder')}",
            f"素材：{len(uploaded)}/{len(assets)} 已上传",
        ]
        if not assets:
            lines.append("本次未检测到附件素材，只保存了文字和时序上下文。")
        if pending:
            first_reason = str(pending[0].get("reason") or pending[0].get("error") or pending[0].get("status") or "")
            lines.append(f"待处理：{len(pending)} 个素材未上传。原因：{first_reason[:300]}")
            if any(item.get("status") in {"remote_not_configured", "auth_required"} for item in pending):
                lines.append("可发送：`【灵感-vlog】iCloud状态` 或 `【灵感-vlog】iCloud认证`。续期后发送 `【灵感-vlog】重试上传 " + str(manifest.get("vlog_id") or "") + "`。")
        return lines

    def start_auth_session(self) -> dict[str, Any]:
        if self._should_use_pyicloud_china():
            apple_id = self._configured_apple_id()
            password = self._configured_password()
            if apple_id and password:
                return self._start_pyicloud_session(apple_id, password)
            pyicloud_status = self._pyicloud_status()
            if pyicloud_status.get("status") == "ready":
                return pyicloud_status
            return {
                "ok": False,
                "status": "password_required",
                "backend": "pyicloud",
                "reply": "这个 Apple ID 需要走 iCloud 中国区接口。请发送：`【灵感-vlog】iCloud密码 你的AppleID密码` 重新启动认证。",
            }
        if not self.auth_script.exists():
            return {"ok": False, "status": "auth_script_missing", "error": str(self.auth_script)}
        proc = self._run_auth_script(["start"])
        return proc

    def save_setup_account(self, apple_id: str) -> dict[str, Any]:
        apple_id = apple_id.strip()
        if not apple_id or "@" not in apple_id:
            return {"ok": False, "status": "invalid_apple_id", "reply": "Apple ID 格式不对，请发送：`【灵感-vlog】iCloud账号 name@example.com`。"}
        state = {
            "remote": self.remote,
            "apple_id": apple_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_setup_state(state)
        return {
            "ok": True,
            "status": "account_saved",
            "remote": self.remote,
            "apple_id": apple_id,
            "reply": "账号已记录。下一步发送：`【灵感-vlog】iCloud密码 你的AppleID密码`。",
        }

    def create_remote_with_password(self, password: str) -> dict[str, Any]:
        password = password.strip()
        setup = self._read_setup_state()
        apple_id = str(setup.get("apple_id") or self._configured_apple_id()).strip()
        if not apple_id:
            return {
                "ok": False,
                "status": "missing_account",
                "remote": self.remote,
                "reply": "还没有 Apple ID。请先发送：`【灵感-vlog】iCloud账号 name@example.com`。",
            }
        if not password:
            return {"ok": False, "status": "missing_password", "remote": self.remote, "apple_id": apple_id, "reply": "密码为空，请重新发送 `【灵感-vlog】iCloud密码 ...`。"}

        obscure = self._obscure_password(password)
        if not obscure.get("ok"):
            return {
                "ok": False,
                "status": "obscure_failed",
                "remote": self.remote,
                "apple_id": apple_id,
                "error": obscure.get("error") or obscure.get("stderr"),
                "reply": "rclone password obscure 失败，remote 未创建。",
            }
        obscured_password = str(obscure.get("password") or "").strip()
        configured_before = bool(self.status().get("configured"))
        action = "update" if configured_before else "create"
        create_cmd = ["config", action, self.remote]
        if not configured_before:
            create_cmd.append("iclouddrive")
        create_cmd.extend(
            [
                "apple_id",
                apple_id,
                "password",
                obscured_password,
                "--no-obscure",
                "--non-interactive",
            ]
        )
        create = self._run_rclone(create_cmd, timeout=90)
        # rclone may return a non-zero code while still writing the remote and asking for auth.
        status = self.status()
        configured = bool(status.get("configured"))
        auth: dict[str, Any] = {}
        if configured:
            if self._should_use_pyicloud_china() or status.get("backend") == "pyicloud":
                auth = self._start_pyicloud_session(apple_id, password)
            else:
                auth = self.start_auth_session()
            self._clear_setup_state()
        redacted_error = self._redact_secret(str(create.get("stderr") or create.get("error") or ""), apple_id)
        if configured:
            auth_status = str(auth.get("status") or "")
            auth_ok = bool(auth.get("ok")) and auth_status not in {"failed", "password_required", "missing_credentials"}
            reply = "密码已写入 rclone 配置并已启动 iCloud 认证。下一步按提示发送验证码，例如：`【灵感-vlog】验证码 123456`。"
            if not auth_ok:
                reply = str(auth.get("reply") or "iCloud 认证启动失败，请确认 Apple ID 密码后重试。")
            return {
                "ok": auth_ok,
                "status": "remote_created" if auth_ok else "auth_start_failed",
                "remote": self.remote,
                "apple_id": apple_id,
                "backend": auth.get("backend") or status.get("backend") or "rclone",
                "auth": auth,
                "reply": reply,
            }
        return {
            "ok": False,
            "status": "remote_create_failed",
            "remote": self.remote,
            "apple_id": apple_id,
            "error": redacted_error,
            "reply": "rclone remote 创建失败，请确认 Apple ID 和密码是否正确后重试。",
        }

    def send_auth_input(self, code: str) -> dict[str, Any]:
        pyicloud_status = self._pyicloud_status()
        if pyicloud_status.get("status") in {"starting", "awaiting_2fa", "invalid_code"} and pyicloud_status.get("running"):
            return self._run_pyicloud_script(["send", "--text", code], timeout=30)
        auth_status = self._auth_status()
        if self._looks_like_china_icloud_redirect(str(auth_status.get("tail") or "")):
            started = self.start_auth_session()
            if started.get("status") in {"awaiting_2fa", "starting"}:
                return {
                    **started,
                    "reply": "刚才 rclone 验证码会话已被 Apple 切到 iCloud.com.cn 而失效。我已改用 iCloud 中国区会话并重新请求验证码，请发送新的验证码。",
                }
        proc = self._run_auth_script(["send", "--text", code])
        return proc

    def cancel_auth_session(self) -> dict[str, Any]:
        pyicloud = self._run_pyicloud_script(["cancel"], timeout=20)
        if pyicloud.get("status") == "cancelled":
            self._run_auth_script(["cancel"])
            return pyicloud
        return self._run_auth_script(["cancel"])

    def _auth_status(self) -> dict[str, Any]:
        return self._run_auth_script(["status"])

    def _run_auth_script(self, args: list[str]) -> dict[str, Any]:
        cmd = [sys.executable, str(self.auth_script), *args, "--remote", self.remote]
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        except Exception as exc:
            return {"ok": False, "status": "auth_script_failed", "error": str(exc)}
        try:
            parsed = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            parsed = {"ok": False, "status": "invalid_auth_script_json", "stdout": proc.stdout[-1000:]}
        if proc.returncode != 0 and parsed.get("ok") is not False:
            parsed["ok"] = False
            parsed["status"] = parsed.get("status") or "auth_script_failed"
            parsed["error"] = proc.stderr.strip() or proc.stdout.strip()
        return parsed

    def _setup_state_path(self) -> Path:
        safe_remote = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.remote)
        return self.runtime_root / f"{safe_remote}.setup.json"

    def _read_setup_state(self) -> dict[str, Any]:
        path = self._setup_state_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_setup_state(self, state: dict[str, Any]) -> None:
        path = self._setup_state_path()
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _clear_setup_state(self) -> None:
        try:
            self._setup_state_path().unlink()
        except OSError:
            pass

    def _obscure_password(self, password: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                [self.rclone_bin, "obscure", "-"],
                input=password + "\n",
                text=True,
                capture_output=True,
                timeout=20,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if proc.returncode != 0:
            return {"ok": False, "stderr": proc.stderr.strip(), "returncode": proc.returncode}
        return {"ok": True, "password": proc.stdout.strip()}

    def _configured_apple_id(self) -> str:
        try:
            proc = subprocess.run(
                [self.rclone_bin, "config", "show", self.remote],
                text=True,
                capture_output=True,
                timeout=20,
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        for line in proc.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "apple_id":
                return value.strip()
        return ""

    def _configured_password(self) -> str:
        try:
            proc = subprocess.run(
                [self.rclone_bin, "config", "show", self.remote],
                text=True,
                capture_output=True,
                timeout=20,
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        for line in proc.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "password":
                password = value.strip()
                try:
                    reveal = subprocess.run(
                        [self.rclone_bin, "reveal", password],
                        text=True,
                        capture_output=True,
                        timeout=20,
                    )
                except Exception:
                    return password
                return reveal.stdout.strip() if reveal.returncode == 0 and reveal.stdout.strip() else password
        return ""

    def _pyicloud_status(self) -> dict[str, Any]:
        return self._run_pyicloud_script(["status"], timeout=30)

    def _start_pyicloud_session(self, apple_id: str, password: str) -> dict[str, Any]:
        return self._run_pyicloud_script(
            [
                "start",
                "--apple-id",
                apple_id,
                "--china-mainland",
            ],
            input_text=password + "\n",
            timeout=45,
        )

    def _run_pyicloud_script(self, args: list[str], *, input_text: str | None = None, timeout: int = 30) -> dict[str, Any]:
        script = self.pyicloud_script
        python = Path(self.pyicloud_python)
        if not script.exists():
            return {"ok": False, "status": "pyicloud_script_missing", "error": str(script)}
        if not python.exists():
            return {"ok": False, "status": "pyicloud_python_missing", "error": str(python)}
        cmd = [str(python), str(script), *args, "--remote", self.remote]
        try:
            proc = subprocess.run(cmd, input=input_text, text=True, capture_output=True, timeout=timeout)
        except Exception as exc:
            return {"ok": False, "status": "pyicloud_script_failed", "error": str(exc)}
        try:
            parsed = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            parsed = {"ok": False, "status": "invalid_pyicloud_json", "stdout": proc.stdout[-1000:]}
        if proc.returncode != 0 and parsed.get("ok") is not False:
            parsed["ok"] = False
            parsed["status"] = parsed.get("status") or "pyicloud_script_failed"
            parsed["error"] = proc.stderr.strip() or proc.stdout.strip()
        return parsed

    def _should_use_pyicloud_china(self) -> bool:
        if self.pyicloud_china_mainland:
            return True
        auth = self._auth_status()
        if self._looks_like_china_icloud_redirect(str(auth.get("tail") or "")):
            return True
        pyicloud = self._pyicloud_status()
        return bool(pyicloud.get("apple_id")) and bool(pyicloud.get("china_mainland"))

    @staticmethod
    def _looks_like_china_icloud_redirect(text: str) -> bool:
        lowered = (text or "").lower()
        return "icloud.com.cn" in lowered or "domaintouse" in lowered or "chinamainland" in lowered

    @staticmethod
    def _redact_secret(text: str, apple_id: str = "") -> str:
        redacted = text
        if apple_id:
            redacted = redacted.replace(apple_id, "<apple_id>")
        redacted = re.sub(r"(?i)(password[^\n]*)", "password=<redacted>", redacted)
        return redacted[-1200:]

    def _asset_time_contexts(self, message: Message, asset_paths: list[str], timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        wanted = {str(Path(path)) for path in asset_paths}
        contexts: dict[str, dict[str, Any]] = {}

        def add(path_value: object, item: dict[str, Any], source: str) -> None:
            if not isinstance(path_value, str) or not path_value.strip():
                return
            normalized = str(Path(path_value.strip()))
            if normalized not in wanted or normalized in contexts:
                return
            dt = self._parse_upload_time(str(item.get("created_at") or ""), message.created_at)
            if dt is None:
                dt = message.created_at
            contexts[normalized] = {
                "uploaded_at": dt.isoformat(timespec="seconds"),
                "created_at_raw": str(item.get("created_at") or ""),
                "message_id": str(item.get("message_id") or ""),
                "message_type": str(item.get("message_type") or ""),
                "source": source,
            }

        for item in timeline:
            if not isinstance(item, dict):
                continue
            for path_value in item.get("downloaded_paths") or []:
                add(path_value, item, "timeline.downloaded_paths")
            for attachment in item.get("attachments") or []:
                if not isinstance(attachment, dict):
                    continue
                for key in ("downloaded_path", "path", "local_path"):
                    add(attachment.get(key), item, f"timeline.attachments.{key}")
        return contexts

    def _parse_upload_time(self, raw: str, reference: datetime) -> datetime | None:
        text = (raw or "").strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None and reference.tzinfo is not None:
                parsed = parsed.replace(tzinfo=reference.tzinfo)
            return parsed
        except ValueError:
            pass

        tz = reference.tzinfo or ZoneInfo(self.timezone)
        patterns = (
            ("%y%m%d %H:%M:%S", False),
            ("%y%m%d %H:%M", False),
            ("%Y-%m-%d %H:%M:%S", False),
            ("%Y-%m-%d %H:%M", False),
            ("%m/%d %H:%M:%S", True),
            ("%m/%d %H:%M", True),
        )
        for pattern, needs_year in patterns:
            try:
                parsed = datetime.strptime(text, pattern)
            except ValueError:
                continue
            if needs_year:
                parsed = parsed.replace(year=reference.year)
            return parsed.replace(tzinfo=tz)
        return None

    def _datetime_from_context(self, context: dict[str, Any], fallback_mtime: float) -> datetime:
        parsed = self._parse_upload_time(str(context.get("uploaded_at") or context.get("created_at_raw") or ""), datetime.now(ZoneInfo(self.timezone)))
        if parsed is not None:
            return parsed
        return datetime.fromtimestamp(fallback_mtime, ZoneInfo(self.timezone))

    @staticmethod
    def _upload_time_key(dt: datetime, index: int | None = None) -> str:
        base = dt.strftime("%Y%m%d-%H%M%S")
        return f"{base}-{index:03d}" if index is not None else base

    def _asset_data_option(
        self,
        index: int,
        filename: str,
        uploaded_dt: datetime,
        remote_folder: str,
        remote_filename: str,
        time_context: dict[str, Any],
    ) -> dict[str, Any]:
        key = self._upload_time_key(uploaded_dt, index)
        return {
            "value": key,
            "label": f"{uploaded_dt.strftime('%Y-%m-%d %H:%M:%S')}｜{filename}",
            "uploaded_at": uploaded_dt.isoformat(timespec="seconds"),
            "date": uploaded_dt.strftime("%Y-%m-%d"),
            "time": uploaded_dt.strftime("%H:%M:%S"),
            "sort_key": key,
            "asset_index": index,
            "filename": filename,
            "remote_path": f"{self.remote}:{remote_folder.rstrip('/')}/{remote_filename}",
            "source": time_context.get("source") or "file_mtime",
            "message_id": time_context.get("message_id") or "",
        }

    @staticmethod
    def _manifest_data_options(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for asset in assets:
            if isinstance(asset, dict) and isinstance(asset.get("data_option"), dict):
                options.append(asset["data_option"])
        return options

    def _package_upload_datetime(self, message: Message, assets: list[dict[str, Any]]) -> datetime:
        parsed_assets = [
            self._parse_upload_time(str(asset.get("uploaded_at") or ""), message.created_at)
            for asset in assets
            if isinstance(asset, dict)
        ]
        parsed_assets = [dt for dt in parsed_assets if dt is not None]
        if parsed_assets:
            return min(parsed_assets)
        return message.created_at

    def _package_data_option(self, vlog_id: str, message: Message, uploaded_dt: datetime, remote_folder: str) -> dict[str, Any]:
        key = self._upload_time_key(uploaded_dt)
        title = self._title_from_body(message.body, vlog_id).removeprefix("Vlog灵感：")
        return {
            "value": f"{key}-{vlog_id}",
            "label": f"{uploaded_dt.strftime('%Y-%m-%d %H:%M:%S')}｜{title}",
            "uploaded_at": uploaded_dt.isoformat(timespec="seconds"),
            "date": uploaded_dt.strftime("%Y-%m-%d"),
            "time": uploaded_dt.strftime("%H:%M:%S"),
            "sort_key": key,
            "vlog_id": vlog_id,
            "remote_folder": remote_folder,
        }

    def _store_assets(self, asset_paths: list[str], remote_folder: str, asset_time_contexts: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        remote_status = self.status()
        remote_ready = remote_status.get("status") == "ready"
        remote_configured = bool(remote_status.get("configured"))
        assets: list[dict[str, Any]] = []
        sha_to_index: dict[str, int] = {}
        asset_time_contexts = asset_time_contexts or {}
        for index, asset_path in enumerate(asset_paths, start=1):
            path = Path(asset_path)
            stat = path.stat()
            sha256 = self._file_sha256(path)
            remote_filename = self._remote_filename(index, path.name)
            time_context = asset_time_contexts.get(str(path)) or {}
            uploaded_dt = self._datetime_from_context(time_context, stat.st_mtime)
            data_option = self._asset_data_option(index, path.name, uploaded_dt, remote_folder, remote_filename, time_context)
            duplicate_of = sha_to_index.get(sha256)
            if duplicate_of is None:
                sha_to_index[sha256] = index
            asset: dict[str, Any] = {
                "index": index,
                "filename": path.name,
                "remote_filename": remote_filename,
                "local_path": str(path),
                "size_bytes": stat.st_size,
                "sha256": sha256,
                "uploaded_at": uploaded_dt.isoformat(timespec="seconds"),
                "upload_time_key": data_option["value"],
                "upload_time_source": time_context.get("source") or "file_mtime",
                "data_option": data_option,
                "duplicate_of": duplicate_of or "",
            }
            if not remote_configured:
                asset.update({"status": "remote_not_configured", "reason": f"rclone remote `{self.remote}:` 未配置"})
            elif not remote_ready:
                asset.update(
                    {
                        "status": "auth_required" if remote_status.get("status") == "auth_or_network_error" else "remote_not_ready",
                        "reason": str(remote_status.get("error") or remote_status.get("status") or "iCloud remote 不可用")[:1000],
                    }
                )
            elif duplicate_of:
                asset.update({"status": "duplicate", "reason": f"与第 {duplicate_of} 个素材重复，未重复上传"})
            else:
                upload = self._upload_one(path, remote_folder, remote_filename, backend=str(remote_status.get("backend") or ""))
                asset.update(upload)
                if asset.get("remote_path"):
                    asset["data_option"]["remote_path"] = asset.get("remote_path")
                if upload.get("status") == "uploaded":
                    asset["delete_status"] = self._delete_uploaded_cache_file(path)
                elif upload.get("status") == "auth_required":
                    self.start_auth_session()
            assets.append(asset)
        return assets

    def _upload_one(self, local_path: Path, remote_folder: str, remote_filename: str, *, backend: str = "") -> dict[str, Any]:
        if backend == "pyicloud":
            result = self._run_pyicloud_script(
                [
                    "upload",
                    "--local-path",
                    str(local_path),
                    "--remote-folder",
                    remote_folder,
                    "--remote-filename",
                    remote_filename,
                ],
                timeout=self.upload_timeout_seconds,
            )
            if result.get("ok"):
                return {"status": "uploaded", "backend": "pyicloud", "remote_path": result.get("remote_path") or f"icloud:{remote_folder.rstrip('/')}/{remote_filename}"}
            reason = str(result.get("error") or result.get("reply") or result.get("status") or "pyicloud upload failed")
            return {
                "status": "auth_required" if result.get("status") == "auth_required" else "upload_failed",
                "backend": "pyicloud",
                "remote_path": f"icloud:{remote_folder.rstrip('/')}/{remote_filename}",
                "reason": reason[-1200:],
            }
        remote_path = f"{self.remote}:{remote_folder.rstrip('/')}/{remote_filename}"
        result = self._run_rclone(["copyto", str(local_path), remote_path], timeout=self.upload_timeout_seconds)
        if result["ok"]:
            return {"status": "uploaded", "backend": "rclone", "remote_path": remote_path}
        stderr = str(result.get("stderr") or result.get("error") or "")
        return {
            "status": "auth_required" if self._looks_like_auth_error(stderr) else "upload_failed",
            "backend": "rclone",
            "remote_path": remote_path,
            "reason": stderr[-1200:] or "rclone copyto failed",
        }

    def _run_rclone(self, args: list[str], *, timeout: int) -> dict[str, Any]:
        try:
            proc = subprocess.run([self.rclone_bin, *args], text=True, capture_output=True, timeout=timeout)
        except Exception as exc:
            return {"ok": False, "stdout": "", "stderr": "", "error": str(exc)}
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    def _remote_folder(self, created_at: datetime, vlog_id: str) -> str:
        return "/".join([self.remote_root, created_at.strftime("%Y"), created_at.strftime("%m"), created_at.strftime("%d"), vlog_id])

    @staticmethod
    def _remote_filename(index: int, filename: str) -> str:
        path = Path(filename)
        stem = safe_slug(path.stem, max_len=80)
        suffix = re.sub(r"[^A-Za-z0-9.]+", "", path.suffix.lower())[:12]
        return f"{index:03d}-{stem}{suffix}"

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _delete_uploaded_cache_file(path: Path) -> str:
        try:
            resolved = path.resolve(strict=False)
        except OSError as exc:
            return f"否（路径解析失败：{exc}）"
        for root_path in UPLOADED_MEDIA_ROOTS:
            try:
                root = root_path.resolve()
            except OSError:
                continue
            try:
                is_uploaded = resolved.is_relative_to(root)
            except AttributeError:
                is_uploaded = str(resolved).startswith(str(root) + os.sep)
            if not is_uploaded:
                continue
            try:
                if resolved.exists() and resolved.is_file():
                    resolved.unlink()
                return "是"
            except OSError as exc:
                return f"否（删除失败：{exc}）"
        return "不适用（不是上传缓存文件）"

    @staticmethod
    def _conversation_context(message: Message) -> dict[str, Any]:
        value = (message.metadata or {}).get("conversation_context")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _format_timeline(items: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            text = str(item.get("text") or "").strip()
            attachments = item.get("attachments") or []
            if len(text) > 800:
                text = text[:780].rstrip() + "..."
            prefix = f"{index}. {item.get('created_at') or '未知时间'}"
            if item.get("current"):
                prefix += "（当前标签）"
            line = f"{prefix}：{text or '（无正文）'}"
            if attachments:
                names = [str(att.get("file_name") or att.get("file_key") or "") for att in attachments if isinstance(att, dict)]
                line += "\n   附件：" + "、".join(name for name in names if name)
            lines.append(line)
        return "\n".join(lines) if lines else "暂无上下文。"

    @staticmethod
    def _format_assets(assets: list[dict[str, Any]]) -> str:
        if not assets:
            return "暂无附件素材。"
        lines: list[str] = []
        for item in assets:
            remote_path = str(item.get("remote_path") or "")
            status = str(item.get("status") or "")
            filename = str(item.get("filename") or "")
            size = int(item.get("size_bytes") or 0)
            line = f"- {item.get('index')}. {filename} ({size} bytes)：{status}"
            if remote_path:
                backend = str(item.get("backend") or "icloud")
                line += f"\n  - iCloud/{backend}：{remote_path}"
            else:
                line += f"\n  - 本地暂存：{item.get('local_path')}"
            if item.get("upload_time_key"):
                line += f"\n  - 数据选项：{item.get('upload_time_key')}｜{item.get('uploaded_at')}"
            if item.get("delete_status"):
                line += f"\n  - 本地缓存删除：{item.get('delete_status')}"
            if item.get("reason"):
                line += f"\n  - 原因：{item.get('reason')}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _format_data_options(manifest: dict[str, Any]) -> str:
        lines: list[str] = []
        package_option = manifest.get("data_option") if isinstance(manifest.get("data_option"), dict) else {}
        if package_option:
            lines.append(f"- 素材包选项：{package_option.get('value')}｜{package_option.get('label')}")
        for option in manifest.get("data_options") or []:
            if not isinstance(option, dict):
                continue
            lines.append(
                "\n".join(
                    [
                        f"- 素材选项：{option.get('value')}｜{option.get('label')}",
                        f"  - remote_path：{option.get('remote_path')}",
                    ]
                )
            )
        return "\n".join(lines) if lines else "暂无数据选项。"

    @staticmethod
    def _looks_like_auth_error(text: str) -> bool:
        lowered = (text or "").lower()
        return any(
            marker in lowered
            for marker in (
                "2fa",
                "two-factor",
                "authentication",
                "authenticate",
                "auth",
                "token",
                "expired",
                "reconnect",
                "trust",
                "invalid_grant",
                "401",
            )
        )

    def _find_manifest(self, vlog_id: str) -> Path | None:
        if vlog_id:
            path = self.package_root / vlog_id / "manifest.json"
            return path if path.exists() else None
        manifests = sorted(self.package_root.glob("VLOG-*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        return manifests[0] if manifests else None

    @staticmethod
    def _title_from_body(body: str, fallback: str) -> str:
        for line in (body or "").splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                return f"Vlog灵感：{cleaned[:36]}"
        return f"Vlog灵感：{fallback}"
