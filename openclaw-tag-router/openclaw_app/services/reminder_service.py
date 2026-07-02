from __future__ import annotations

import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


class ReminderService:
    def __init__(
        self,
        enabled: bool,
        command: str,
        script: str,
        env_files: list[str] | None = None,
        timeout_seconds: int = 30,
        bitable_url: str = "",
        config_paths: dict[str, str] | None = None,
    ):
        self.enabled = enabled
        self.command = command
        self.script = script
        self.env_files = env_files or []
        self.timeout_seconds = timeout_seconds
        self.bitable_url = bitable_url
        self.config_paths = config_paths or {}

    def add(
        self,
        *,
        kind: str,
        title: str,
        text: str,
        due_at: datetime | None,
        remind_at: datetime | None = None,
        source: str = "openclaw",
        ref_id: str = "",
        local_path: str = "",
        priority: str = "",
        extra_fields: dict[str, Any] | None = None,
        omit_management_fields: bool = False,
        config_path_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "skipped": True, "reason": "disabled"}
        env = self._build_env()
        config_key = kind if config_path_key is None else config_path_key
        if config_key and (config_path := self.config_paths.get(config_key)):
            env["FEISHU_REMINDER_CONFIG"] = config_path
        args = [
            self.command,
            self.script,
            "add",
            "--type",
            kind,
            "--title",
            title,
            "--text",
            text,
            "--source",
            source,
            "--ref-id",
            ref_id,
            "--local-path",
            local_path,
        ]
        if due_at is not None:
            args.extend(["--due-at", due_at.isoformat(timespec="seconds")])
        if remind_at is not None:
            args.extend(["--remind-at", remind_at.isoformat(timespec="seconds")])
        if priority and not omit_management_fields:
            args.extend(["--priority", priority])
        if omit_management_fields:
            args.append("--omit-management-fields")
        if extra_fields:
            args.extend(["--extra-fields", json.dumps(extra_fields, ensure_ascii=False)])
        try:
            proc = subprocess.run(
                args,
                cwd=str(Path(self.script).resolve().parent),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = ""
            if exc.output:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output)
            return {
                "ok": False,
                "timeout": True,
                "error": f"飞书多维表格写入超时：超过 {self.timeout_seconds} 秒。{output[-1800:]}".strip(),
            }
        except OSError as exc:
            return {"ok": False, "error": f"无法调用飞书多维表格写入脚本：{exc}"}
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stdout[-2000:]}
        output = proc.stdout.strip()
        parsed: dict[str, Any] = {}
        if output:
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                parsed = {}
        return {"ok": True, "output": output, "data": parsed}

    def delete(self, *, record_id: str, dry_run: bool = False, delete_calendar: bool = True, config_path_key: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "skipped": True, "reason": "disabled"}
        env = self._build_env()
        if config_path_key and (config_path := self.config_paths.get(config_path_key)):
            env["FEISHU_REMINDER_CONFIG"] = config_path
        args = [self.command, self.script, "delete-record", "--record-id", record_id]
        if dry_run:
            args.append("--dry-run")
        if delete_calendar:
            args.append("--delete-calendar")
        try:
            proc = subprocess.run(
                args,
                cwd=str(Path(self.script).resolve().parent),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = ""
            if exc.output:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output)
            return {"ok": False, "timeout": True, "error": f"飞书提醒删除超时：超过 {self.timeout_seconds} 秒。{output[-1800:]}".strip()}
        except OSError as exc:
            return {"ok": False, "error": f"无法调用飞书提醒删除脚本：{exc}"}
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stdout[-2000:]}
        output = proc.stdout.strip()
        parsed: dict[str, Any] = {}
        if output:
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                parsed = {}
        return {"ok": True, "output": output, "data": parsed}

    def update(
        self,
        *,
        record_id: str,
        record_type: str = "待办",
        fields: dict[str, Any] | None = None,
        config_path_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "skipped": True, "reason": "disabled"}
        env = self._build_env()
        if config_path_key and (config_path := self.config_paths.get(config_path_key)):
            env["FEISHU_REMINDER_CONFIG"] = config_path
        args = [
            self.command,
            self.script,
            "update-record",
            "--record-id",
            record_id,
            "--type",
            record_type,
            "--extra-fields",
            json.dumps(fields or {}, ensure_ascii=False),
        ]
        try:
            proc = subprocess.run(
                args,
                cwd=str(Path(self.script).resolve().parent),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = ""
            if exc.output:
                output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output)
            return {"ok": False, "timeout": True, "error": f"飞书提醒更新超时：超过 {self.timeout_seconds} 秒。{output[-1800:]}".strip()}
        except OSError as exc:
            return {"ok": False, "error": f"无法调用飞书提醒更新脚本：{exc}"}
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stdout[-2000:]}
        output = proc.stdout.strip()
        parsed: dict[str, Any] = {}
        if output:
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                parsed = {}
        return {"ok": True, "output": output, "data": parsed}

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for env_file in self.env_files:
            self._load_env_file(Path(env_file), env)
        return env

    @staticmethod
    def _load_env_file(path: Path, env: dict[str, str]) -> None:
        if not path.exists():
            return
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
