from __future__ import annotations

from .tag_router_common import *


class VlogInspirationMixin:
    def handle_灵感_vlog(self, message: Message) -> TaskResult:
        control = self.vlog_storage_service.handle_control_command(message.body)
        if control:
            return self._handle_vlog_control(message, control)

        result = self.vlog_storage_service.ingest(message)
        entry = self.archive_service.save_archive(
            message,
            str(result.get("title") or "Vlog灵感"),
            result.get("sections") or [("原始灵感", message.body)],
            result.get("frontmatter") or {},
        )
        manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else {}
        fs = self._sync_vlog_entry_to_feishu(entry, message, manifest)
        reply_lines = list(result.get("reply_lines") or [])
        reply_lines.append(f"本地归档：{entry.local_path}")
        if fs.get("doc"):
            reply_lines.append(f"飞书文档：{fs['doc']}")
        if warning := fs.get("warning"):
            reply_lines.append(f"附加信息：{warning}")
        status = str((result.get("frontmatter") or {}).get("status") or "archived")
        return TaskResult(
            ok=True,
            status=status,
            reply="\n".join(reply_lines),
            task_id=str(manifest.get("vlog_id") or entry.frontmatter["id"]),
            local_path=entry.local_path,
            feishu_doc=fs.get("doc", ""),
            extra={"vlog": manifest},
        )

    def _handle_vlog_control(self, message: Message, control: dict[str, Any]) -> TaskResult:
        kind = str(control.get("kind") or "")
        result = control.get("result") if isinstance(control.get("result"), dict) else {}
        if kind == "status":
            reply = self._format_vlog_storage_status(result)
        elif kind in {"auth_start", "auth_send", "auth_cancel"}:
            reply = self._format_vlog_auth_result(result)
        elif kind in {"setup_account", "setup_password"}:
            reply = self._format_vlog_setup_result(result)
        elif kind == "retry":
            reply = self._format_vlog_retry_result(result)
        else:
            reply = str(result.get("reply") or result.get("status") or "vlog 控制命令已处理")
        archived_body = message.body
        if kind == "setup_password":
            archived_body = self._redact_vlog_password_command(archived_body)
        entry = self.archive_service.save_archive(
            message,
            "Vlog灵感控制命令",
            [
                ("原始内容", archived_body),
                ("处理结果", reply),
                ("结构化结果", json.dumps(result, ensure_ascii=False, indent=2)),
            ],
            {"status": str(result.get("status") or kind or "vlog_control"), "tags": ["灵感>vlog", "控制命令"]},
        )
        return TaskResult(
            ok=bool(result.get("ok", True)),
            status=str(result.get("status") or kind or "vlog_control"),
            reply=reply + f"\n本地记录：{entry.local_path}",
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra={"vlog_control": result},
        )

    def _redact_vlog_password_command(self, text: str) -> str:
        return re.sub(
            r"((?:iCloud|icloud|Apple\s*ID|AppleID|Apple)?\s*密码\s*[:：]?\s*).+",
            r"\1<redacted>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _format_vlog_setup_result(self, result: dict[str, Any]) -> str:
        lines = [
            "iCloud 初始化",
            f"- 状态：{result.get('status') or 'unknown'}",
        ]
        if result.get("apple_id"):
            lines.append(f"- Apple ID：{result['apple_id']}")
        if result.get("remote"):
            lines.append(f"- rclone remote：{result['remote']}:")
        if result.get("backend"):
            lines.append(f"- 存储后端：{result['backend']}")
        if result.get("reply"):
            lines.append(f"- 提示：{result['reply']}")
        auth = result.get("auth") if isinstance(result.get("auth"), dict) else {}
        if auth:
            lines.append(f"- 认证会话：{auth.get('status') or 'unknown'}")
            if auth.get("reply"):
                lines.append(f"- 下一步：{auth['reply']}")
            tail = str(auth.get("tail") or "").strip()
            if tail:
                lines.append("- 最近输出：\n" + tail[-700:])
        if result.get("error"):
            lines.append(f"- 错误：{str(result['error'])[:1000]}")
        return "\n".join(lines)

    def _format_vlog_storage_status(self, result: dict[str, Any]) -> str:
        auth = result.get("auth") if isinstance(result.get("auth"), dict) else {}
        pyicloud = result.get("pyicloud") if isinstance(result.get("pyicloud"), dict) else {}
        lines = [
            "iCloud 存储状态",
            f"- rclone remote：{result.get('remote', 'icloud')}:",
            f"- 当前后端：{result.get('backend') or '未就绪'}",
            f"- 远端目录：{result.get('remote_root', '')}",
            f"- remote 已配置：{'是' if result.get('configured') else '否'}",
            f"- 状态：{result.get('status') or 'unknown'}",
            f"- 认证会话：{auth.get('status') or 'unknown'}",
        ]
        if pyicloud:
            lines.append(f"- 中国区会话：{pyicloud.get('status') or 'unknown'}")
        if auth.get("reply"):
            lines.append(f"- 认证提示：{auth['reply']}")
        if pyicloud.get("reply") and pyicloud.get("status") != "no_session":
            lines.append(f"- 中国区提示：{pyicloud['reply']}")
        if result.get("error"):
            lines.append(f"- 错误：{str(result['error'])[:1000]}")
        if not result.get("configured"):
            lines.append("- 说明：当前还没有可用 iCloud 会话。首次初始化需要 Apple ID 密码；已做日志脱敏，但密码仍建议只在受控私聊里发送。")
        return "\n".join(lines)

    def _format_vlog_auth_result(self, result: dict[str, Any]) -> str:
        lines = [
            "iCloud 认证会话",
            f"- 状态：{result.get('status') or 'unknown'}",
        ]
        if result.get("mode"):
            lines.append(f"- 模式：{result['mode']}")
        if result.get("backend"):
            lines.append(f"- 后端：{result['backend']}")
        if result.get("method"):
            lines.append(f"- 验证方式：{result['method']}")
        if result.get("reply"):
            lines.append(f"- 提示：{result['reply']}")
        tail = str(result.get("tail") or "").strip()
        if tail:
            lines.append("- 最近输出：\n" + tail[-900:])
        return "\n".join(lines)

    def _format_vlog_retry_result(self, result: dict[str, Any]) -> str:
        lines = [
            "Vlog 素材重试上传",
            f"- 状态：{result.get('status') or 'unknown'}",
            f"- Manifest：{result.get('manifest_path') or ''}",
            f"- iCloud目录：{result.get('remote_folder') or ''}",
            f"- 已重试：{result.get('retried', 0)}",
            f"- 已上传：{result.get('uploaded', 0)}",
        ]
        failed = result.get("failed") if isinstance(result.get("failed"), list) else []
        if failed:
            lines.append("- 失败：\n" + "\n".join(f"  - {item}" for item in failed[:10]))
        if result.get("reply"):
            lines.append(str(result["reply"]))
        return "\n".join(lines)

    def _sync_vlog_entry_to_feishu(self, entry, message: Message, manifest: dict[str, Any]) -> dict[str, str]:
        doc_name = "Vlog灵感素材"
        try:
            assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
            timeline = manifest.get("timeline") if isinstance(manifest.get("timeline"), list) else []
            asset_lines = []
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                remote_path = str(asset.get("remote_path") or "")
                line = f"- {asset.get('index')}. {asset.get('filename')}：{asset.get('status')}"
                if remote_path:
                    line += f" | {remote_path}"
                elif asset.get("local_path"):
                    line += f" | 本地暂存：{asset.get('local_path')}"
                if asset.get("reason"):
                    line += f" | 原因：{str(asset.get('reason'))[:240]}"
                asset_lines.append(line)
            timeline_lines = []
            for index, item in enumerate(timeline, start=1):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if len(text) > 500:
                    text = text[:480].rstrip() + "..."
                timeline_lines.append(f"{index}. {item.get('created_at') or '未知时间'}：{text or '（无正文）'}")
            content = "\n".join(
                [
                    f"## {format_display_time(message.created_at)}",
                    "",
                    f"- 来源：{message.source.upper()}",
                    "- 标签：灵感>vlog",
                    f"- 素材包：{manifest.get('vlog_id') or ''}",
                    f"- 本地归档：{entry.local_path}",
                    f"- Manifest：{manifest.get('manifest_path') or ''}",
                    f"- iCloud目录：{manifest.get('remote_folder') or ''}",
                    f"- 素材数：{len(assets)}",
                    "",
                    "### 原始灵感",
                    message.body.strip() or "（无正文）",
                    "",
                    "### 时序上下文",
                    "\n".join(timeline_lines) or "暂无上下文。",
                    "",
                    "### 素材链接",
                    "\n".join(asset_lines) or "暂无附件素材。",
                ]
            ).strip()
            fs = self.feishu_service.append_entry(doc_name, content)
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", "")})
            return fs
        except Exception as exc:
            self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": False, "feishu_doc": doc_name, "feishu_error": str(exc)})
            return {"status": "pending_manual", "doc": doc_name, "warning": f"飞书同步失败：{exc}"}
