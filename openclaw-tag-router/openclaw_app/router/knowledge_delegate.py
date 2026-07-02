from __future__ import annotations

import requests
from pathlib import Path

from .tag_router_common import *
from .openclaw_bot_llm import normalize_openclaw_thinking, openclaw_subprocess_env


class KnowledgeDelegateMixin:
    def _knowledge_thinking_level(self, message: Message) -> str:
        explicit = normalize_openclaw_thinking(str((message.metadata or {}).get("tag_thinking") or ""))
        if explicit:
            return explicit
        if message.entry_tag in RESEARCH_KNOWLEDGE_TAGS:
            return KNOWLEDGE_THINKING_RESEARCH
        body_lower = message.body.lower()
        if any(keyword.lower() in body_lower for keyword in COMPLEX_RESEARCH_KEYWORDS):
            return KNOWLEDGE_THINKING_RESEARCH
        return KNOWLEDGE_THINKING_DEFAULT

    def _delegate_to_knowledge_bot(self, message: Message, *, thinking_level: str) -> TaskResult:
        profile_name = "knowledge_research" if thinking_level == KNOWLEDGE_THINKING_RESEARCH else "knowledge_delegate"
        profile = profile_config(profile_name)
        provider_name = str(profile.get("provider") or "").strip()
        if provider_name and provider_name != "openclaw_codex":
            return self._delegate_to_knowledge_provider(message, profile_name=profile_name, thinking_level=thinking_level)
        runtime = profile_runtime(profile_name)
        cmd = [
            runtime.bin,
            "agent",
            "--agent",
            runtime.agent,
            "--message",
            self._knowledge_delegate_user_message(message),
            "--thinking",
            thinking_level,
            "--json",
            "--timeout",
            str(int(runtime.timeout)),
        ]
        try:
            proc = run_media_subprocess_with_watchdog(
                cmd,
                timeout=int(runtime.timeout) + 60,
                env=self._subprocess_env_with_context(message, runtime=runtime),
                cwd=runtime.cwd,
            )
        except OSError as exc:
            return TaskResult(
                ok=False,
                status="knowledge_delegate_failed",
                reply=f"已识别为 `{message.entry_tag}` 通用知识入口，但无法调用 OpenClaw CLI 转交 knowledge Bot。\n错误：{exc}",
                task_id="",
            )
        if proc.returncode == -9:
            return TaskResult(
                ok=False,
                status="knowledge_delegate_timeout",
                reply=f"已识别为 `{message.entry_tag}` 通用知识入口，但转交 knowledge Bot 超时。请稍后重试或直接发给 knowledge Bot。\n错误：{proc.stderr.strip()}",
                task_id="",
            )

        parsed = self._parse_openclaw_json(proc.stdout)
        reply = self._extract_openclaw_reply(parsed)
        if not reply:
            reply = self._extract_latest_openclaw_session_reply(runtime)
        if proc.returncode != 0:
            error_text = proc.stderr.strip() or self._summarize_openclaw_output(parsed, proc.stdout) or f"openclaw agent exited with {proc.returncode}"
            return TaskResult(ok=False, status="knowledge_delegate_failed", reply=error_text, task_id="")
        return TaskResult(
            ok=True,
            status="delegated_to_knowledge",
            reply=reply or self._summarize_openclaw_output(parsed, proc.stdout) or f"已转交 {runtime.agent} 处理完成，但未返回可见文本。",
            task_id=str(parsed.get("task_id") or parsed.get("taskId") or parsed.get("id") or ""),
            extra={
                "knowledge_agent": runtime.agent,
                "thinking_level": thinking_level,
                "model": runtime.model,
                "conversation_context_count": self._conversation_context(message).get("loaded_count", 0),
                "delegate_result": parsed,
            },
        )

    def _delegate_to_knowledge_provider(self, message: Message, *, profile_name: str, thinking_level: str) -> TaskResult:
        profile = profile_config(profile_name)
        provider = profile_provider_runtime(profile_name)
        provider_name = str(profile.get("provider") or "").strip() or profile_name
        if provider.api_type != "openai_chat_completions":
            return TaskResult(
                ok=False,
                status="knowledge_delegate_failed",
                reply=f"knowledge_delegate provider `{profile_name}` 仅支持 openai_chat_completions，当前是 `{provider.api_type}`。",
                task_id="",
            )

        base_url = provider.base_url.rstrip("/")
        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        timeout = float(profile.get("timeout") or provider.timeout or 300)
        system_prompt = (
            "你现在运行在 Knowledge bot 直连模式。"
            "处理标签包括【归档】、【补全】、【认知】、【学习】、【学习-整理】。"
            "优先直接给出最终可用结果，保持中文输出，保留用户原文中的关键信息，不要编造来源。"
            "如果请求本应依赖外部系统写入或知识库工具，而当前消息里没有实际执行条件，"
            "不要伪造“已写入”或“已同步”；直接输出整理结果，并明确说明当前是直连模式未执行外部写入。"
            f"当前目标思考强度：{thinking_level or str(profile.get('thinking') or '').strip().lower() or 'high'}。"
        )
        user_prompt = self._knowledge_delegate_user_message(message)
        payload = {
            "model": str(profile.get("model") or provider.model).strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            raw = response.json()
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="knowledge_delegate_failed",
                reply=f"knowledge_delegate 直连 `{provider_name}` 失败：{exc}",
                task_id="",
            )

        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        reply = str(content or "").strip()
        if not reply:
            return TaskResult(
                ok=False,
                status="knowledge_delegate_failed",
                reply=f"knowledge_delegate 直连 `{provider_name}` 未返回可见文本。",
                task_id="",
            )
        return TaskResult(
            ok=True,
            status="delegated_to_knowledge",
            reply=reply,
            task_id="",
            extra={
                "knowledge_agent": provider_name,
                "thinking_level": thinking_level,
                "model": payload["model"],
                "conversation_context_count": self._conversation_context(message).get("loaded_count", 0),
                "delegate_mode": "provider_direct",
                "delegate_result": raw,
            },
        )

    def _parse_openclaw_json(self, output: str) -> dict[str, Any]:
        text = output.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()
        candidate_payload: dict[str, Any] = {}
        for match in re.finditer(r"\{", text):
            try:
                parsed, _ = decoder.raw_decode(text[match.start() :])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                if any(key in parsed for key in ("runId", "result", "payloads", "status")):
                    return parsed
                if not candidate_payload:
                    candidate_payload = parsed
        return candidate_payload

    def _extract_openclaw_reply(self, parsed: dict[str, Any]) -> str:
        for key in ("reply", "message", "text", "output", "final", "final_answer"):
            value = parsed.get(key)
            text = self._extract_openclaw_content_text(value)
            if text:
                return text
        result = parsed.get("result")
        if isinstance(result, dict):
            for key in ("reply", "message", "text", "output", "final", "final_answer"):
                value = result.get(key)
                text = self._extract_openclaw_content_text(value)
                if text:
                    return text
            meta = result.get("meta")
            if isinstance(meta, dict):
                for key in (
                    "finalAssistantVisibleText",
                    "finalAssistantRawText",
                    "finalAssistantText",
                    "finalAssistantMessage",
                    "lastAssistantMessage",
                ):
                    text = self._extract_openclaw_content_text(meta.get(key))
                    if text:
                        return text
            for key in ("payloads", "messages", "items", "events"):
                text = self._extract_openclaw_payload_text(result.get(key))
                if text:
                    return text
        for key in ("payloads", "messages", "items", "events"):
            text = self._extract_openclaw_payload_text(parsed.get(key))
            if text:
                return text
        return ""

    def _extract_openclaw_content_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            texts = []
            for item in value:
                if isinstance(item, str):
                    text = item.strip()
                elif isinstance(item, dict):
                    text = self._extract_openclaw_content_text(item.get("text") or item.get("content"))
                else:
                    text = ""
                if text:
                    texts.append(text)
            return "\n".join(texts).strip()
        if isinstance(value, dict):
            for key in ("text", "content", "message", "reply", "output", "final"):
                text = self._extract_openclaw_content_text(value.get(key))
                if text:
                    return text
        return ""

    def _extract_openclaw_payload_text(self, value: Any) -> str:
        if not isinstance(value, list):
            return ""
        final_texts: list[str] = []
        assistant_texts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            message = item.get("message") if isinstance(item.get("message"), dict) else item
            role = str(message.get("role") or item.get("role") or "").strip()
            if role and role != "assistant":
                continue
            content = message.get("content") if isinstance(message, dict) else item.get("content")
            if isinstance(content, list):
                for content_item in content:
                    if not isinstance(content_item, dict) or content_item.get("type") not in (None, "text"):
                        continue
                    text = str(content_item.get("text") or "").strip()
                    if not text:
                        continue
                    if "final_answer" in str(content_item.get("textSignature") or ""):
                        final_texts.append(text)
                    else:
                        assistant_texts.append(text)
            else:
                text = self._extract_openclaw_content_text(content or item.get("text"))
                if text:
                    assistant_texts.append(text)
        if final_texts:
            return "\n".join(final_texts).strip()
        return "\n".join(assistant_texts[-1:]).strip()

    def _extract_latest_openclaw_session_reply(self, runtime: Any) -> str:
        candidates: list[Path] = []
        agent = str(getattr(runtime, "agent", "") or "").strip()
        if agent:
            candidates.append(Path.home() / ".openclaw" / "agents" / agent / "sessions")
        cwd = str(getattr(runtime, "cwd", "") or "").strip()
        if cwd:
            candidates.append(Path(cwd) / "sessions")
        for session_dir in candidates:
            if not session_dir.is_dir():
                continue
            files = [
                file_path
                for file_path in session_dir.glob("*.jsonl")
                if not file_path.name.endswith(".trajectory.jsonl")
                and ".bak-" not in file_path.name
                and ".reset." not in file_path.name
            ]
            files.sort(key=lambda file_path: file_path.stat().st_mtime, reverse=True)
            for file_path in files[:3]:
                text = self._extract_final_reply_from_session_file(file_path)
                if text:
                    return text
        return ""

    def _extract_final_reply_from_session_file(self, path: Path) -> str:
        final_text = ""
        last_assistant_text = ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "message":
                continue
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            content = message.get("content")
            texts = []
            final_texts = []
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "text":
                        continue
                    text = str(item.get("text") or "").strip()
                    if not text:
                        continue
                    if "final_answer" in str(item.get("textSignature") or ""):
                        final_texts.append(text)
                    else:
                        texts.append(text)
            else:
                text = self._extract_openclaw_content_text(content)
                if text:
                    texts.append(text)
            if final_texts:
                final_text = "\n".join(final_texts).strip()
            elif texts:
                last_assistant_text = "\n".join(texts).strip()
        return final_text or last_assistant_text

    def _summarize_openclaw_output(self, parsed: dict[str, Any], stdout: str) -> str:
        run_id = str(parsed.get("runId") or parsed.get("id") or "").strip()
        status = str(parsed.get("status") or "").strip()
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        summary = str(result.get("summary") or parsed.get("summary") or "").strip() if isinstance(result, dict) else ""
        if run_id or status or summary:
            parts = ["OpenClaw 已返回结果，但没有可见回复文本。"]
            if summary:
                parts.append(f"summary={summary}")
            if status:
                parts.append(f"status={status}")
            if run_id:
                parts.append(f"runId={run_id}")
            return " ".join(parts)
        text = stdout.strip()
        if not text:
            return ""
        if text.startswith("{") or text.startswith("["):
            return "OpenClaw 已返回结构化结果，但没有可见回复文本。"
        return text[-1000:]

    def _summarize_process_output(self, parsed: dict[str, Any], stdout: str) -> str:
        if parsed:
            status = str(parsed.get("status") or "").strip()
            ok = parsed.get("ok")
            if status or ok is not None:
                return f"脚本返回结构化结果，但没有可见错误文本。status={status or 'unknown'} ok={ok}"
            return "脚本返回结构化结果，但没有可见错误文本。"
        text = stdout.strip()
        if not text:
            return ""
        if text.startswith("{") or text.startswith("["):
            return "脚本返回结构化结果，但没有可见错误文本。"
        return text[-1000:]

    def _conversation_context(self, message: Message) -> dict[str, Any]:
        value = (message.metadata or {}).get("conversation_context")
        if isinstance(value, dict):
            return value
        raw = os.environ.get("OPENCLAW_CONVERSATION_CONTEXT_JSON", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _conversation_context_prompt(self, message: Message) -> str:
        return str(self._conversation_context(message).get("prompt") or "").strip()

    def _message_with_conversation_context(self, message: Message) -> str:
        prompt = self._conversation_context_prompt(message)
        if not prompt:
            return message.raw_text
        return "\n\n".join([prompt, "当前标签请求：", message.raw_text])

    def _knowledge_delegate_user_message(self, message: Message) -> str:
        prompt = self._conversation_context_prompt(message)
        body = message.body.strip() or "（空）"
        delegated = "\n".join(
            [
                "tag-router 内部委托请求：请直接处理，不要调用 tag-router bridge，不要再次执行标签路由。",
                f"请按 Knowledge bot 的【{message.entry_tag}】能力处理以下原始用户内容。",
                f"原始标签：{message.entry_tag}",
                "原始正文：",
                body,
            ]
        )
        if not prompt:
            return delegated
        return "\n\n".join([prompt, delegated])

    def _conversation_context_json(self, message: Message) -> str:
        context = self._conversation_context(message)
        if not context:
            return ""
        return json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    def _subprocess_env_with_context(self, message: Message, *, runtime: BotLLMRuntime | None = None) -> dict[str, str]:
        env = openclaw_subprocess_env(runtime.codex_home if runtime else "")
        context_json = self._conversation_context_json(message)
        if context_json:
            env["OPENCLAW_CONVERSATION_CONTEXT_JSON"] = context_json
        return env

    def _subprocess_env_for_content_os_script_generation(self, message: Message) -> dict[str, str]:
        env = self._subprocess_env_with_context(message)
        return env

    def _append_conversation_context_arg(self, command: list[str], message: Message) -> None:
        context_json = self._conversation_context_json(message)
        if context_json:
            command.extend(["--conversation-context-json", context_json])
