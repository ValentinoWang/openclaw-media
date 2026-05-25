from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import hashlib
from pathlib import Path
from typing import Any

import requests

from .media_text_cleaner import MEDIA_TEXT_CLEANER, MediaCopyParts
from .utils import ensure_dir
from ..router.openclaw_bot_llm import (
    display_openclaw_model,
    profile_config,
    profile_provider_runtime,
    profile_runtime,
)


CONTENT_FLOW_ROOT = Path(os.getenv("CONTENT_FLOW_ROOT", "/home/ubuntu/selfmedia-tools/01-ingest-content-flow"))


class ContentFlowClient:
    def __init__(self, base_url: str, poll_interval_seconds: float = 0.5, poll_attempts: int = 20, workspace_root: str | Path = "."):
        self.base_url = base_url.rstrip("/")
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_attempts = poll_attempts
        self.workspace_root = Path(workspace_root)
        self.session = requests.Session()
        self.session.trust_env = False

    def _raw_marker_dir(self) -> Path:
        return ensure_dir(self.workspace_root / "content_flow" / "raw")

    def analyze(self, url: str) -> dict[str, Any]:
        marker = self._raw_marker_dir() / "last-selfmedia-link.txt"
        marker.write_text(url + "\n", encoding="utf-8")
        return self._run_job("/api/analyze", url)

    def download_video(self, url: str) -> dict[str, Any]:
        marker = self._raw_marker_dir() / "last-video-link.txt"
        marker.write_text(url + "\n", encoding="utf-8")
        return self._run_job("/api/video", url)

    def _analysis_has_structured_content(self, analysis: dict[str, Any]) -> bool:
        if not analysis:
            return False
        if analysis.get("analysis_status") == "needs_model_rerun":
            return False
        if analysis.get("fallback_reason") in {"missing_GEMINI_API_KEY", "missing_QWEN_API_KEY", "analysis_models_unavailable"}:
            return False
        for key in (
            "summary",
            "breakdown",
            "hooks",
            "action_plan",
            "hidden_info",
            "visual_cues",
            "transferable_expression",
            "target_audience",
            "pain_point",
            "work_copy",
            "tags",
            "title",
        ):
            value = analysis.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

    def _load_analysis_file(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.is_file() or file_path.stat().st_size <= 0:
            return {}
        try:
            loaded = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _analysis_candidate_paths(self, payload: dict[str, Any]) -> list[Path]:
        candidates: list[Path] = []
        analysis_path = str(payload.get("analysis_path") or "")
        if analysis_path:
            candidates.append(Path(analysis_path))
        media_dir = str(payload.get("media_dir") or "")
        if media_dir:
            candidates.append(Path(media_dir) / "analysis.json")

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return deduped

    def _read_optional_text(self, path: str | Path) -> str:
        if not path:
            return ""
        file_path = Path(path)
        if not file_path.is_file():
            return ""
        try:
            return file_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _platform_from_url(self, url: str) -> str:
        lower = (url or "").lower()
        if "douyin.com" in lower or "iesdouyin.com" in lower:
            return "抖音"
        if "xiaohongshu.com" in lower or "xhslink.com" in lower:
            return "小红书"
        if "tiktok.com" in lower:
            return "TikTok"
        if "kuaishou.com" in lower or "gifshow.com" in lower:
            return "快手"
        if "bilibili.com" in lower or "b23.tv" in lower:
            return "B站"
        if "youtube.com" in lower or "youtu.be" in lower:
            return "YouTube"
        return ""

    def _compact_title(self, value: str, *, limit: int = 42) -> str:
        text = re.sub(r"https?://\S+", " ", str(value or ""))
        text = re.sub(r"#\S+", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" -_，。:：|")
        if not text:
            return ""
        return text if len(text) <= limit else text[:limit].rstrip()

    def _extract_hashtags(self, text: str) -> list[str]:
        tags: list[str] = []
        for match in re.finditer(r"#([^#\s\[]{1,24})(?:\[话题\])?#?", text or ""):
            tag = match.group(1).strip()
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= 8:
                break
        return tags

    def _fallback_categories(self, text: str) -> tuple[str, str]:
        lower = (text or "").lower()
        rules = [
            ("AI/工具", "AI工具应用", ["ai", "aigc", "agent", "github", "开源", "工具", "自动化", "插件", "软件", "动捕"]),
            ("运营/管理", "自媒体运营", ["运营", "流量", "账号", "算法", "内容创作", "增长"]),
            ("学习/认知", "认知方法", ["认知", "思维", "学习", "关系", "情绪", "人格"]),
            ("商业/产品", "产品增长", ["商业", "产品", "用户", "品牌", "销售"]),
            ("生活/效率", "生活效率", ["效率", "习惯", "生活", "时间管理"]),
        ]
        for primary, secondary, keywords in rules:
            if any(keyword in lower for keyword in keywords):
                return primary, secondary
        return "其他", "未细分"

    def _fallback_media_analysis(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        caption = str(payload.get("caption") or "").strip()
        if not caption and payload.get("caption_path"):
            caption = self._read_optional_text(str(payload.get("caption_path") or ""))
        transcript = self._read_optional_text(str(payload.get("transcript_path") or ""))
        image_ocr = str(payload.get("image_ocr") or "").strip()
        if not image_ocr and payload.get("ocr_path"):
            image_ocr = self._read_optional_text(str(payload.get("ocr_path") or ""))
        source_text = "\n".join(part for part in [caption, image_ocr, transcript, url] if part).strip()
        if not source_text:
            return {}

        first_caption_line = next((line.strip() for line in caption.splitlines() if line.strip()), "")
        first_transcript_line = next((line.strip() for line in re.split(r"[\n。！？!?]", transcript) if line.strip()), "")
        title = self._compact_title(first_caption_line or first_transcript_line or url) or "未命名自媒体知识"
        primary, secondary = self._fallback_categories(source_text)
        tags = self._extract_hashtags(caption)
        if not tags:
            tags = [item for item in re.split(r"[\s,，、/|｜]+", title) if 1 < len(item) <= 12][:5]

        platform = self._platform_from_url(url)
        media_type = str(payload.get("media_type") or "").strip() or ("video" if payload.get("video_path") else "image" if payload.get("image_paths") else "")
        summary_source = self._compact_title(first_transcript_line or first_caption_line or title, limit=80)
        summary = [
            f"主题围绕“{title}”，已基于已下载文案和逐字稿生成结构化入库字段。",
            f"核心信息：{summary_source}" if summary_source else "核心信息来自已下载媒体、文案或逐字稿。",
            "后续可在完整模型分析可用时覆盖为精细拆解，但当前记录已具备标题、分类、文案、完整内容和标签字段。",
        ]
        action_plan = (
            "1. 【万能结构公式】：先提炼原内容的痛点或利益点，再补充关键证据，最后转成可执行收藏理由。\n"
            "2. 【差异化切入点】：围绕具体使用人群重写角度，避免只做泛泛工具搬运。\n"
            "3. 【低成本拍摄方案】：优先复用录屏、字幕重点词和结果展示，减少额外拍摄成本。"
        )
        visual_cues = ""
        image_count = len(payload.get("image_paths") or []) if isinstance(payload.get("image_paths"), list) else 0
        if image_count:
            visual_cues = f"已下载 {image_count} 张图片/抽帧，可用于后续人工或模型视觉复核。"
        elif payload.get("video_path"):
            visual_cues = "已下载视频原文件，可用于后续抽帧和成片视觉复核。"

        work_copy = MEDIA_TEXT_CLEANER.build_work_copy(caption)
        full_content = MEDIA_TEXT_CLEANER.build_full_content(
            MediaCopyParts(caption=caption, transcript=transcript, image_ocr=image_ocr)
        )

        return {
            "title": title,
            "summary": summary,
            "primary_category": primary,
            "secondary_category": secondary,
            "target_audience": "",
            "pain_point": "",
            "work_copy": work_copy,
            "full_content": full_content,
            "hooks": f"可从标题/开头文案“{title}”提炼首屏抓手。",
            "emotion": "好奇 / 实用",
            "score": 70,
            "tags": tags,
            "action_plan": action_plan,
            "hidden_info": "这是基于已下载文案、逐字稿和媒体文件生成的结构化兜底分析，避免模型延迟导致知识入库中断。",
            "visual_cues": visual_cues,
            "transferable_expression": f"“{title}”可迁移为同类选题的标题或开头表达。",
            "analysis_provider": "tag-router-fallback",
            "analysis_status": "fallback_from_downloaded_assets",
            "platform": platform,
            "caption": caption,
            "image_ocr": image_ocr,
            "media_type": media_type,
        }

    def _complete_analysis_payload(self, url: str, payload: dict[str, Any], *, wait: bool) -> dict[str, Any]:
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        if self._analysis_has_structured_content(analysis):
            return payload

        deadline = time.monotonic() + max(0.0, float(os.getenv("CONTENT_FLOW_ANALYSIS_WAIT_SECONDS", "900"))) if wait else time.monotonic()
        poll_seconds = max(0.5, float(os.getenv("CONTENT_FLOW_ANALYSIS_POLL_SECONDS", "2")))
        while True:
            for path in self._analysis_candidate_paths(payload):
                loaded = self._load_analysis_file(path)
                if not loaded:
                    continue
                payload["analysis"] = loaded
                payload["analysis_path"] = str(path)
                if self._analysis_has_structured_content(loaded):
                    return payload
                analysis = loaded
            if not wait or time.monotonic() >= deadline:
                break
            time.sleep(poll_seconds)

        if not self._analysis_has_structured_content(analysis):
            fallback = self._fallback_media_analysis(url, payload)
            if fallback:
                merged = dict(analysis)
                merged.update({key: value for key, value in fallback.items() if value not in (None, "", [], {})})
                payload["analysis"] = merged
        return payload

    def complete_analysis_payload(self, url: str, payload: dict[str, Any], *, wait: bool = False) -> dict[str, Any]:
        return self._complete_analysis_payload(url, payload, wait=wait)

    def transcribe_file(self, audio_path: str, output_dir: str | Path) -> dict[str, Any]:
        source = Path(audio_path)
        if not source.is_file():
            return {"status": "pending_manual", "reason": f"录音文件不存在：{audio_path}"}

        out_dir = ensure_dir(output_dir)
        python_bin = CONTENT_FLOW_ROOT / ".venv" / "bin" / "python"
        if not python_bin.is_file():
            python_bin = Path(sys.executable)

        script = r'''
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
audio_path = Path(sys.argv[2])
out_dir = Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)

env_path = root / ".env"
if env_path.is_file():
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

sys.path.insert(0, str(root))
from src.config import load_settings
from src.transcriber import transcribe_audio

try:
    transcript = transcribe_audio(str(audio_path), load_settings(), raise_errors=True)
except Exception as exc:
    print(json.dumps({"status": "pending_manual", "reason": str(exc)}, ensure_ascii=False))
    raise SystemExit(0)

if not transcript:
    print(json.dumps({"status": "pending_manual", "reason": "ASR 未产出逐字稿"}, ensure_ascii=False))
    raise SystemExit(0)

transcript_path = out_dir / "transcript.txt"
transcript_path.write_text(transcript.strip() + "\n", encoding="utf-8")
print(json.dumps({
    "status": "done",
    "audio_path": str(audio_path),
    "media_dir": str(out_dir),
    "transcript_path": str(transcript_path),
}, ensure_ascii=False))
'''
        env = self._content_flow_env()
        timeout_seconds = self._transcription_timeout_seconds(env)
        try:
            proc = subprocess.run(
                [str(python_bin), "-c", script, str(CONTENT_FLOW_ROOT), str(source), str(out_dir)],
                text=True,
                capture_output=True,
                cwd=str(CONTENT_FLOW_ROOT),
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return {"status": "pending_manual", "reason": f"录音转写超时：超过 {int(exc.timeout or timeout_seconds)} 秒"}
        except OSError as exc:
            return {"status": "pending_manual", "reason": f"无法调用 content-flow 本地转写：{exc}"}

        parsed = self._parse_last_json_line(proc.stdout)
        if proc.returncode != 0:
            reason = self._clean_transcription_error(
                proc.stderr.strip() or proc.stdout.strip() or f"本地转写退出码 {proc.returncode}"
            )
            if parsed and parsed.get("reason"):
                reason = str(parsed["reason"])
            return {"status": "pending_manual", "reason": reason[-2000:]}
        if not parsed:
            return {"status": "pending_manual", "reason": "本地转写未返回 JSON 结果"}
        return parsed

    def summarize_dialogue_transcript(self, transcript: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, Any]:
        text = transcript.strip()
        if not text:
            return {"status": "pending_manual", "reason": "缺少逐字稿"}

        env = self._content_flow_env()
        if self._env_truthy(env.get("TRANSCRIPTION_POSTPROCESS_CHUNKED", "1")):
            return self._summarize_dialogue_transcript_chunked(text, source_hint, env, artifact_dir=artifact_dir)

        profile = profile_config("transcription_postprocess")
        provider_name = str(profile.get("provider") or "").strip()
        if provider_name == "openclaw_codex":
            return self._summarize_dialogue_transcript_with_openclaw(text, source_hint, env)
        return self._summarize_dialogue_transcript_with_provider("transcription_postprocess", text, source_hint)

    def summarize_inspiration(self, text: str, source_hint: str = "", artifact_dir: str | Path | None = None) -> dict[str, Any]:
        body = text.strip()
        if not body:
            return {"status": "pending_manual", "reason": "缺少灵感内容"}

        env = self._content_flow_env()
        prompt = (
            "你是灵感整理器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "任务不是摘要，而是把口语化碎片完整整理成可执行灵感卡；不得遗漏原文中的实质要素。\n"
            "JSON 字段固定为 title、cleaned_brief、core_theme、content_outline、scenes_materials、concepts_or_views、knowledge_points、execution_plan、pending_questions、suggested_tags、confidence_note。\n"
            "title: 8-28 个汉字，语义化命名，不要照抄长句。\n"
            "cleaned_brief: 清理后的完整灵感脉络，保留原文所有实质信息，去掉口癖和断裂重复。\n"
            "content_outline: 数组，按创作/项目推进顺序拆成章节或段落。\n"
            "scenes_materials: 数组，列出可用素材、画面、证据、截图、地点、人物或时间线。\n"
            "concepts_or_views: 数组，列出要表达的理念、判断、感想、观点。\n"
            "knowledge_points: 数组，列出要传达的 AI、科技、专业知识点。\n"
            "execution_plan: 数组，列出下一步可执行动作。\n"
            "pending_questions: 数组，列出仍需补充或确认的问题。\n"
            "suggested_tags: 数组，给出 3-8 个短标签。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "inspiration": body,
            },
            ensure_ascii=False,
        )
        result = self._call_postprocess_json(prompt, user_content, env, "灵感整理")
        if artifact_dir:
            root = ensure_dir(artifact_dir)
            self._write_json_artifact(root, "inspiration-summary.json", result)
            result.setdefault("postprocess_artifacts", {})["inspiration_summary"] = str(root / "inspiration-summary.json")
        return result

    def clean_activity_brief(self, text: str, *, created_at: str = "", source_hint: str = "") -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            return {"status": "pending_manual", "reason": "缺少活动通知正文"}

        env = self._content_flow_env()
        prompt = (
            "你是活动通知清洗器。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把原始活动通知做语义清洗，输出可直接写入多维表格的字段。不要依赖固定标题词；按语义理解通知。\n"
            "必须保留原文所有关键事实，禁止编造。缺失字段输出空字符串或空数组。\n"
            "字段固定为：title、platform、brief_summary、activity_time、activity_time_start、activity_time_end、main_topic、activity_level、reward、participation_method、participation_form、filling_points、submission_requirements、subtopic_directions、source_links、activity_status、parse_status、missing_info、confidence_note。\n"
            "activity_time: 清洗为可分析文本，优先格式为 YYYY-MM-DD 至 YYYY-MM-DD；如果只有单日则 YYYY-MM-DD；年份缺失时按 created_at 所在年份推断。\n"
            "activity_time_start/activity_time_end: 如果能确定，分别输出 YYYY-MM-DD；不能确定输出空字符串。\n"
            "main_topic: 只放官方要求携带的话题/hashtag 或明确命名的活动话题；不要放活动目的、内容概述或参与条件。没有明确主话题则输出空字符串。\n"
            "participation_method: 只写怎么参与/怎么发布/怎么邀请，不要混入表单入口、登记链接、奖励、方向列表。\n"
            "submission_requirements: 写提交、审核、报名、入口使用等要求；涉及提交入口、表单、是否重复提交的信息放这里，不要放 participation_method。\n"
            "subtopic_directions: 数组，每个元素只是一条内容方向/子话题/选题选项，必须完整保留方向名称和说明；不要把参与资格、发布要求、审核条件、首篇内容要求放进方向列表，也不要用数量概括替代列表。\n"
            "filling_points: 写需要填写或登记的信息、表单/入口；如果只是链接，也要说明链接用途。\n"
            "activity_status: 默认待判断；如果明确已结束可写已过期；如果明确值得参加可写可参与。只使用：待判断、可参与、待投稿、已投稿、已过期、已放弃。\n"
            "parse_status: 只使用：已解析、飞书文档待读取、待人工补充。\n"
            "source_links: 数组，元素为 {label,url}。\n"
            "输出必须是 JSON object。"
        )
        user_content = json.dumps(
            {
                "created_at": created_at,
                "source_hint": source_hint or "",
                "raw_activity_notice": body,
            },
            ensure_ascii=False,
        )
        result = self._call_openclaw_activity_cleaning_json(prompt, user_content, env, "活动 Brief AI清洗")
        if result.get("status") != "done":
            return result
        return self._normalize_activity_clean_result(result)

    def _normalize_activity_clean_result(self, result: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(result)
        for key in (
            "title",
            "platform",
            "brief_summary",
            "activity_time",
            "activity_time_start",
            "activity_time_end",
            "main_topic",
            "activity_level",
            "reward",
            "participation_method",
            "participation_form",
            "filling_points",
            "submission_requirements",
            "activity_status",
            "parse_status",
            "confidence_note",
        ):
            value = normalized.get(key)
            normalized[key] = str(value or "").strip()

        directions = normalized.get("subtopic_directions")
        if isinstance(directions, str):
            directions = [line.strip(" -•\t") for line in directions.splitlines() if line.strip(" -•\t")]
        if not isinstance(directions, list):
            directions = []
        normalized["subtopic_directions"] = [str(item).strip() for item in directions if str(item).strip()]

        links = normalized.get("source_links")
        if not isinstance(links, list):
            links = []
        clean_links: list[dict[str, str]] = []
        for item in links:
            if isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                if url:
                    clean_links.append({"label": str(item.get("label") or "来源链接").strip() or "来源链接", "url": url})
            elif isinstance(item, str) and item.strip().startswith("http"):
                clean_links.append({"label": "来源链接", "url": item.strip()})
        normalized["source_links"] = clean_links

        missing = normalized.get("missing_info")
        if isinstance(missing, str):
            missing = [item.strip() for item in re.split(r"[、,，\n]", missing) if item.strip()]
        if not isinstance(missing, list):
            missing = []
        normalized["missing_info"] = [str(item).strip() for item in missing if str(item).strip()]

        if normalized.get("activity_status") not in {"待判断", "可参与", "待投稿", "已投稿", "已过期", "已放弃"}:
            normalized["activity_status"] = "待判断"
        if normalized.get("parse_status") not in {"已解析", "飞书文档待读取", "待人工补充"}:
            normalized["parse_status"] = "已解析"
        return normalized

    def _call_openclaw_activity_cleaning_json(self, prompt: str, user_content: str, env: dict[str, str], stage: str) -> dict[str, Any]:
        profile = profile_config("activity_cleaning")
        if str(profile.get("provider") or "").strip() != "openclaw_codex":
            return self._call_profile_provider_json("activity_cleaning", prompt, user_content, stage)
        runtime = profile_runtime("activity_cleaning")
        openclaw_bin = runtime.bin
        timeout = int(runtime.timeout)
        model = runtime.model
        display_model = display_openclaw_model(model)
        stage_key = hashlib.sha1(stage.encode("utf-8")).hexdigest()[:12]
        session_id = f"activity-cleaning-{stage_key}-{time.time_ns()}"
        cmd = [
            openclaw_bin,
            "agent",
            "--agent",
            runtime.agent,
            "--session-id",
            session_id,
            "--message",
            f"{prompt}\n\n输入 JSON：\n{user_content}",
            "--json",
            "--timeout",
            str(timeout),
        ]
        cmd.extend(["--model", model])
        if runtime.thinking:
            cmd.extend(["--thinking", runtime.thinking])

        run_env = dict(env)
        run_env.setdefault("HOME", "/home/ubuntu")
        run_env["CODEX_HOME"] = runtime.codex_home
        run_env.setdefault(
            "PATH",
            "/home/ubuntu/.nvm/versions/node/v22.22.2/bin:/home/ubuntu/bin:/usr/local/bin:/usr/bin:/bin",
        )
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout + 60,
                env=run_env,
                cwd=runtime.cwd,
            )
        except subprocess.TimeoutExpired:
            return {"status": "pending_manual", "reason": f"{stage}：OpenClaw 清洗超时，超过 {timeout} 秒"}
        except OSError as exc:
            return {"status": "pending_manual", "reason": f"{stage}：无法调用 OpenClaw：{exc}"}

        parsed_run = self._parse_openclaw_json(proc.stdout)
        reply = self._extract_openclaw_reply(parsed_run) or proc.stdout
        parsed = self._parse_json_payload(reply)
        if proc.returncode != 0:
            reason = self._clean_openclaw_postprocess_error(
                proc.stderr.strip() or reply.strip() or f"OpenClaw 活动清洗退出码 {proc.returncode}"
            )
            return {"status": "pending_manual", "reason": f"{stage}：{reason[-1800:]}"}
        if not parsed:
            return {"status": "pending_manual", "reason": f"{stage}：OpenClaw 未返回可解析 JSON"}
        return {"status": "done", "postprocess_provider": "openclaw", "postprocess_model": display_model, **parsed}

    def _summarize_dialogue_transcript_chunked(
        self,
        text: str,
        source_hint: str,
        env: dict[str, str],
        *,
        artifact_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        sections = self._split_transcript_audio_sections(text)
        chunk_target = self._env_int(env, "TRANSCRIPTION_CHUNK_CHARS_TARGET", 10000)
        chunk_max = self._env_int(env, "TRANSCRIPTION_CHUNK_CHARS_MAX", 12000)
        chunk_overlap = self._env_int(env, "TRANSCRIPTION_CHUNK_OVERLAP", 500)
        artifacts: dict[str, Any] = {}
        artifact_root = ensure_dir(artifact_dir) if artifact_dir else None
        if artifact_root:
            artifacts["dir"] = str(artifact_root)
            self._write_json_artifact(artifact_root, "transcript-sections.json", {"sections": sections})

        chunk_summaries: list[dict[str, Any]] = []

        for section in sections:
            chunks = self._split_text_chunks(str(section["text"]), chunk_target, chunk_max, chunk_overlap)
            section_chunk_ids: list[str] = []
            for index, chunk in enumerate(chunks, start=1):
                chunk_id = f"{section['source_audio']}-chunk-{index:02d}"
                section_chunk_ids.append(chunk_id)
                parsed = self._summarize_transcript_chunk(
                    chunk_id=chunk_id,
                    source_audio=str(section["source_audio"]),
                    source_title=str(section["source_title"]),
                    char_start=int(chunk["char_start"]),
                    char_end=int(chunk["char_end"]),
                    text=str(chunk["text"]),
                    source_hint=source_hint,
                    env=env,
                )
                if parsed.get("status") != "done":
                    if artifact_root:
                        artifacts["failure"] = self._write_json_artifact(
                            artifact_root,
                            f"{chunk_id}-failure.json",
                            {"stage": "chunk", "chunk_id": chunk_id, "result": parsed},
                        )
                    return {
                        "status": "pending_manual",
                        "reason": f"分片整理失败 {chunk_id}：{parsed.get('reason') or '未返回可解析 JSON'}",
                        "stage": "chunk",
                        "chunk_id": chunk_id,
                        "postprocess_artifacts": artifacts,
                    }
                summary = dict(parsed)
                summary.pop("status", None)
                summary.setdefault("schema_version", "1.0")
                summary["chunk_id"] = chunk_id
                summary["source_audio"] = section["source_audio"]
                summary["source_title"] = section["source_title"]
                summary["char_start"] = chunk["char_start"]
                summary["char_end"] = chunk["char_end"]
                self._annotate_evidence_hashes(summary)
                chunk_summaries.append(summary)
                if artifact_root:
                    chunk_path = self._write_json_artifact(artifact_root, f"{chunk_id}.json", summary)
                    artifacts.setdefault("chunks", []).append(chunk_path)
            if artifact_root:
                self._write_json_artifact(
                    artifact_root,
                    f"{section['source_audio']}-chunk-index.json",
                    {"source_audio": section["source_audio"], "source_title": section["source_title"], "chunks": section_chunk_ids},
                )

        attachment_summaries: list[dict[str, Any]] = []
        for section in sections:
            source_audio = section["source_audio"]
            chunks = [item for item in chunk_summaries if item.get("source_audio") == source_audio]
            if not chunks:
                continue
            parsed = self._summarize_attachment_chunks(
                source_audio=str(source_audio),
                source_title=str(section["source_title"]),
                chunks=chunks,
                source_hint=source_hint,
                env=env,
            )
            if parsed.get("status") != "done":
                if artifact_root:
                    artifacts["failure"] = self._write_json_artifact(
                        artifact_root,
                        f"{source_audio}-attachment-summary-failure.json",
                        {"stage": "attachment", "source_audio": source_audio, "result": parsed},
                    )
                return {
                    "status": "pending_manual",
                    "reason": f"单附件合并失败 {source_audio}：{parsed.get('reason') or '未返回可解析 JSON'}",
                    "stage": "attachment",
                    "source_audio": source_audio,
                    "postprocess_artifacts": artifacts,
                }
            attachment = dict(parsed)
            attachment.pop("status", None)
            attachment.setdefault("schema_version", "1.0")
            attachment["attachment_id"] = source_audio
            attachment["source_title"] = section["source_title"]
            attachment_summaries.append(attachment)
            if artifact_root:
                attachment_path = self._write_json_artifact(artifact_root, f"{source_audio}-attachment-summary.json", attachment)
                artifacts.setdefault("attachments", []).append(attachment_path)

        global_input: list[dict[str, Any]] = attachment_summaries
        group_size = self._env_int(env, "TRANSCRIPTION_GLOBAL_GROUP_SIZE", 8)
        if len(attachment_summaries) > group_size:
            grouped: list[dict[str, Any]] = []
            for group_index, start in enumerate(range(0, len(attachment_summaries), group_size), start=1):
                group = attachment_summaries[start : start + group_size]
                parsed = self._summarize_attachment_group(group_index, group, source_hint, env)
                if parsed.get("status") != "done":
                    if artifact_root:
                        artifacts["failure"] = self._write_json_artifact(
                            artifact_root,
                            f"group-{group_index:02d}-summary-failure.json",
                            {"stage": "group", "group_id": f"group-{group_index:02d}", "result": parsed},
                        )
                    return {
                        "status": "pending_manual",
                        "reason": f"中间合并失败 group-{group_index:02d}：{parsed.get('reason') or '未返回可解析 JSON'}",
                        "stage": "group",
                        "postprocess_artifacts": artifacts,
                    }
                parsed.pop("status", None)
                grouped.append(parsed)
                if artifact_root:
                    group_path = self._write_json_artifact(artifact_root, f"group-{group_index:02d}-summary.json", parsed)
                    artifacts.setdefault("groups", []).append(group_path)
            global_input = grouped

        final_note = self._summarize_global_note(global_input, source_hint, env)
        if final_note.get("status") != "done":
            if artifact_root:
                artifacts["failure"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-draft-failure.json",
                    {"stage": "global", "result": final_note},
                )
            return {
                "status": "pending_manual",
                "reason": f"全局整理失败：{final_note.get('reason') or '未返回可解析 JSON'}",
                "stage": "global",
                "postprocess_artifacts": artifacts,
            }

        consistency = self._check_global_note_consistency(final_note, attachment_summaries, env)
        if artifact_root:
            artifacts["global_note_draft"] = self._write_json_artifact(artifact_root, "global-note-draft.json", final_note)
            artifacts["consistency_check"] = self._write_json_artifact(artifact_root, "consistency-check.json", consistency)
        approved_value = consistency.get("approved")
        approved = approved_value is True or str(approved_value).strip().lower() == "true"
        consistency["approved"] = approved
        blocking_issues = consistency.get("blocking_issues") if isinstance(consistency.get("blocking_issues"), list) else []
        if not approved:
            revised_note = self._revise_global_note(final_note, attachment_summaries, consistency, source_hint, env)
            if revised_note.get("status") == "done":
                revised_note.pop("status", None)
                revised_consistency = self._check_global_note_consistency(revised_note, attachment_summaries, env)
                revised_approved_value = revised_consistency.get("approved")
                revised_approved = revised_approved_value is True or str(revised_approved_value).strip().lower() == "true"
                revised_consistency["approved"] = revised_approved
                if artifact_root:
                    artifacts["global_note_revised"] = self._write_json_artifact(artifact_root, "global-note-revised.json", revised_note)
                    artifacts["consistency_check_revised"] = self._write_json_artifact(
                        artifact_root,
                        "consistency-check-revised.json",
                        revised_consistency,
                    )
                if revised_approved:
                    final_note = revised_note
                    consistency = revised_consistency
                    approved = True
                    blocking_issues = []
                else:
                    consistency = revised_consistency
                    blocking_issues = (
                        revised_consistency.get("blocking_issues")
                        if isinstance(revised_consistency.get("blocking_issues"), list)
                        else blocking_issues
                    )
            elif artifact_root:
                artifacts["global_note_revision_failure"] = self._write_json_artifact(
                    artifact_root,
                    "global-note-revision-failure.json",
                    {"stage": "revision", "result": revised_note},
                )

        if not approved:
            if not blocking_issues:
                blocking_issues = ["一致性检查未批准，但未返回具体阻断项"]
            return {
                "status": "pending_manual",
                "reason": "一致性检查未通过：" + "；".join(str(item) for item in blocking_issues[:5]),
                "stage": "consistency",
                "postprocess_artifacts": artifacts,
                "consistency_check": consistency,
            }
        final_note["postprocess_provider"] = final_note.get("postprocess_provider", "chunked")
        final_note["postprocess_pipeline"] = "chunked-map-reduce-final"
        final_note["chunk_count"] = len(chunk_summaries)
        final_note["attachment_count"] = len(attachment_summaries)
        if self._env_truthy(env.get("TRANSCRIPTION_POSTPROCESS_RETURN_INTERMEDIATES", "0")):
            final_note["chunk_summaries"] = chunk_summaries
            final_note["attachment_summaries"] = attachment_summaries
        final_note["consistency_check"] = consistency
        final_note["postprocess_artifacts"] = artifacts
        return final_note

    def _summarize_transcript_chunk(
        self,
        *,
        chunk_id: str,
        source_audio: str,
        source_title: str,
        char_start: int,
        char_end: int,
        text: str,
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议逐字稿分片事实提取器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "这是局部 chunk，不要写全局结论，不要生成最终会议纪要。\n"
            "JSON 字段固定为 schema_version、chunk_id、source_audio、source_title、char_start、char_end、has_signal、signal_level、local_topics、key_points、local_observations、local_decisions_or_claims、pending_questions、action_items、speaker_hints、sensitive_items、noise_or_irrelevant、coverage_note。\n"
            "key_points 每项必须是对象，包含 point、evidence、speaker_hint、confidence；evidence 只能是短证据句。\n"
            "local_decisions_or_claims 每项必须标明 status，使用 discussion_tendency / tentative_decision / confirmed_decision / claim 之一。\n"
            "sensitive_items 从本阶段就标记，handling 可用 do_not_include_in_final_note / keep_private / ok_to_include。\n"
            "如果本段主要是闲聊或噪声，has_signal=false，并在 noise_or_irrelevant 说明。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "chunk_id": chunk_id,
                "source_audio": source_audio,
                "source_title": source_title,
                "char_start": char_start,
                "char_end": char_end,
                "transcript_chunk": text,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "分片整理")

    def _summarize_attachment_chunks(
        self,
        *,
        source_audio: str,
        source_title: str,
        chunks: list[dict[str, Any]],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是单条录音的 reduce 合并器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "只基于 chunk JSON 合并，不要新增事实。需要按 evidence_hash/source range 去重 overlap 内容。\n"
            "JSON 字段固定为 schema_version、attachment_id、attachment_title、covered_chunks、signal_level、main_value、theme_sections、decisions、pending_questions、action_items、speaker_notes、sensitive_summary、low_value_ranges、duplicated_with、unique_contribution。\n"
            "decisions 只能收录多处支持或明确表达的结论；局部倾向要写进 theme_sections，不能伪装成已决定。\n"
            "sensitive_summary 必须说明哪些内容不应进入公开最终纪要。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "attachment_id": source_audio,
                "source_title": source_title,
                "chunks": chunks,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "单附件合并")

    def _summarize_attachment_group(self, group_index: int, attachments: list[dict[str, Any]], source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是会议附件中间合并器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "基于 attachment summaries 合并，不要新增事实。输出字段：group_id、covered_attachments、signal_level、theme_sections、decisions、pending_questions、action_items、speaker_notes、sensitive_summary、unique_contribution。"
        )
        user_content = json.dumps(
            {"source_hint": source_hint.strip() or "无", "group_id": f"group-{group_index:02d}", "attachments": attachments},
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "中间合并")

    def _summarize_global_note(self, summaries: list[dict[str, Any]], source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是最终会议纪要整理器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "只基于 attachment/group summaries 生成最终纪要，不要读取或假设原始逐字稿外的信息。\n"
            "JSON 字段固定为 title、summary、pending_questions、speaker_notes、labeled_transcript、sensitive_summary。\n"
            "title: 8-24 个汉字，必须是语义化会议主题，不得使用录音名、地点名、UUID、附件数量。\n"
            "summary: Markdown 字符串，按主题编号整理，覆盖所有高信号附件的有效信息，合并重复主题。\n"
            "pending_questions: 数组，收录仍需确认/决策/补材料的问题或待办，必须有来源支撑。\n"
            "speaker_notes: 说明说话人或内容角色区分依据和置信度。\n"
            "labeled_transcript: 不要放完整逐字稿，只输出清理后的关键对话脉络或写明完整逐字稿见来源路径。\n"
            "不得把 discussion_tendency 写成 confirmed_decision；不得包含 handling=do_not_include_in_final_note 的敏感细节。"
        )
        user_content = json.dumps(
            {"source_hint": source_hint.strip() or "无", "summaries": summaries},
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "全局整理")

    def _check_global_note_consistency(self, final_note: dict[str, Any], attachments: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
        prompt = (
            "你是会议纪要一致性检查器。只输出合法 JSON。\n"
            "检查最终纪要是否有无来源结论、把讨论误写成决定、遗漏高信号附件、重复主题、敏感信息泄露、行动项缺少上下文。\n"
            "输出字段固定为 approved、blocking_issues、warnings、revision_notes。"
        )
        user_content = json.dumps({"final_note": final_note, "attachments": attachments}, ensure_ascii=False)
        parsed = self._call_postprocess_json(prompt, user_content, env, "一致性检查")
        if parsed.get("status") != "done":
            return {"approved": False, "blocking_issues": [parsed.get("reason") or "一致性检查失败"], "warnings": [], "revision_notes": ""}
        parsed.pop("status", None)
        return parsed

    def _revise_global_note(
        self,
        final_note: dict[str, Any],
        attachments: list[dict[str, Any]],
        consistency: dict[str, Any],
        source_hint: str,
        env: dict[str, str],
    ) -> dict[str, Any]:
        prompt = (
            "你是会议纪要修订器。只输出合法 JSON，不要 Markdown 代码块。\n"
            "任务：基于一致性检查结果，对 final_note 做最小必要修订。\n"
            "必须补齐 blocking_issues 指出的遗漏行动项、上下文或风险说明；不得新增 attachments 中没有来源支撑的事实。\n"
            "如果 consistency 提醒某内容需公开范围弱化，则用概括表述替代敏感细节。\n"
            "保持原 JSON 字段：title、summary、pending_questions、speaker_notes、labeled_transcript、sensitive_summary。\n"
            "pending_questions 必须仍为数组；summary 必须仍为 Markdown 字符串。"
        )
        user_content = json.dumps(
            {
                "source_hint": source_hint.strip() or "无",
                "final_note": final_note,
                "attachments": attachments,
                "consistency": consistency,
            },
            ensure_ascii=False,
        )
        return self._call_postprocess_json(prompt, user_content, env, "一致性修订")

    def _summarize_dialogue_transcript_with_provider(self, profile_name: str, text: str, source_hint: str) -> dict[str, Any]:
        prompt = (
            "你是会议录音和访谈录音整理助手。请只基于用户提供的逐字稿整理，不要新增事实，不要猜真实姓名。\n"
            "输出 JSON，字段固定为 title、summary、pending_questions、speaker_notes、labeled_transcript。\n"
            "title: 8-24 个汉字的会议主题，概括逐字稿核心内容；不要使用来源补充、文件名、上传批次说明或录音数量。\n"
            "summary: 这是“内容整理”，不是摘要。用一个 Markdown 字符串输出，按主题分条分点全面整理逐字稿里的所有非重复有效信息；保留背景、分歧、判断、细节、例子、结论和行动项；合并同义重复，删除无意义重复，不能只写 3-6 条概括。\n"
            "pending_questions: 这是“待解决的问题”，用数组输出，每项是一个仍需确认/决策/补材料的问题或待办；必须来自逐字稿，不要新增任务。不要加 Markdown 复选框，系统会统一转成 checklist。\n"
            "来源补充只用于理解用户是否显式给了主题；不要把上传批次说明、文件名、路径、录音数量写进 title 或 summary。\n"
            "speaker_notes: 不要猜真实姓名，但要尽量按语义轮次、问答关系和观点角色区分说话人 A/B/C，并说明区分依据；只有完全无法分轮次时，才写“说话人 A（未区分）”。\n"
            "labeled_transcript: 按对话顺序输出清理后的说话人标注整理稿，格式为对象数组，每项包含 speaker 和 text。speaker 使用“说话人 A/B/C”或“说话人 A（未区分）”，不要整篇都写“说话人不明”。text 不是原始逐字稿，必须去掉口吃、无意义语气词、明显 ASR 错字、断裂重复和噪声；保留所有实质信息、问答关系和推进顺序，不要压缩成摘要。\n"
            "如果没有声纹证据，不要判断真实身份；但仍应基于内容角色做 A/B/C 标注，并在 speaker_notes 里标注置信度。"
        )
        user_content = (
            f"来源补充：{source_hint.strip() or '无'}\n\n"
            "逐字稿：\n"
            f"{text[:50000]}"
        )
        return self._call_profile_provider_json(profile_name, prompt, user_content, "转写后处理")

    def _summarize_dialogue_transcript_with_openclaw(self, text: str, source_hint: str, env: dict[str, str]) -> dict[str, Any]:
        runtime = profile_runtime("transcription_postprocess")
        openclaw_bin = runtime.bin
        timeout = int(runtime.timeout)
        model = runtime.model
        display_model = display_openclaw_model(model)
        prompt = (
            "你是会议录音和访谈录音整理助手。请只基于用户提供的逐字稿整理，不要新增事实，不要猜真实姓名。\n"
            "只输出 JSON，不要输出 Markdown，不要解释。\n"
            "JSON 字段固定为 title、summary、pending_questions、speaker_notes、labeled_transcript。\n"
            "title: 8-24 个汉字的会议主题，概括逐字稿核心内容；不要使用来源补充、文件名、上传批次说明或录音数量。\n"
            "summary: 这是“内容整理”，不是摘要。用一个 Markdown 字符串输出，按主题分条分点全面整理逐字稿里的所有非重复有效信息；保留背景、分歧、判断、细节、例子、结论和行动项；合并同义重复，删除无意义重复，不能只写 3-6 条概括。\n"
            "pending_questions: 这是“待解决的问题”，用数组输出，每项是一个仍需确认/决策/补材料的问题或待办；必须来自逐字稿，不要新增任务。不要加 Markdown 复选框，系统会统一转成 checklist。\n"
            "来源补充只用于理解用户是否显式给了主题；不要把上传批次说明、文件名、路径、录音数量写进 title 或 summary。\n"
            "speaker_notes: 不要猜真实姓名，但要尽量按语义轮次、问答关系和观点角色区分说话人 A/B/C，并说明区分依据；只有完全无法分轮次时，才写“说话人 A（未区分）”。\n"
            "labeled_transcript: 按对话顺序输出清理后的说话人标注整理稿，格式为对象数组，每项包含 speaker 和 text。speaker 使用“说话人 A/B/C”或“说话人 A（未区分）”，不要整篇都写“说话人不明”。text 不是原始逐字稿，必须去掉口吃、无意义语气词、明显 ASR 错字、断裂重复和噪声；保留所有实质信息、问答关系和推进顺序，不要压缩成摘要。\n"
            "如果没有声纹证据，不要判断真实身份；但仍应基于内容角色做 A/B/C 标注，并在 speaker_notes 里标注置信度。"
        )
        message = (
            f"{prompt}\n\n"
            f"来源补充：{source_hint.strip() or '无'}\n\n"
            "逐字稿：\n"
            f"{text[:50000]}"
        )
        session_id = f"transcription-postprocess-{int(time.time())}"
        cmd = [openclaw_bin, "agent"]
        cmd.extend(["--agent", runtime.agent])
        cmd.extend(
            [
                "--session-id",
                session_id,
                "--message",
                message,
                "--json",
                "--timeout",
                str(timeout),
            ]
        )
        cmd.extend(["--model", model])
        if runtime.thinking:
            cmd.extend(["--thinking", runtime.thinking])

        run_env = dict(env)
        run_env.setdefault("HOME", "/home/ubuntu")
        run_env["CODEX_HOME"] = runtime.codex_home
        run_env.setdefault(
            "PATH",
            "/home/ubuntu/.nvm/versions/node/v22.22.2/bin:/home/ubuntu/bin:/usr/local/bin:/usr/bin:/bin",
        )
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout + 60,
                env=run_env,
                cwd=runtime.cwd,
            )
        except subprocess.TimeoutExpired:
            return {"status": "pending_manual", "reason": f"GPT-5.5 会议纪要整理超时：超过 {timeout} 秒"}
        except OSError as exc:
            return {"status": "pending_manual", "reason": f"无法调用 OpenClaw/Codex 后处理：{exc}"}

        parsed_run = self._parse_openclaw_json(proc.stdout)
        reply = self._extract_openclaw_reply(parsed_run) or proc.stdout
        parsed = self._parse_json_payload(reply)
        if proc.returncode != 0:
            reason = self._clean_openclaw_postprocess_error(
                proc.stderr.strip() or reply.strip() or f"OpenClaw/Codex 后处理退出码 {proc.returncode}"
            )
            return {"status": "pending_manual", "reason": reason[-2000:]}
        if not parsed:
            return {"status": "pending_manual", "reason": "GPT-5.5 未返回可解析 JSON"}
        return {"status": "done", "postprocess_provider": "openclaw", "postprocess_model": display_model, **parsed}

    def _run_job(self, endpoint: str, url: str) -> dict[str, Any]:
        if not self.base_url:
            return {"status": "pending_manual", "reason": "content-flow base_url 未配置"}
        try:
            response = self.session.post(f"{self.base_url}{endpoint}", json={"url": url}, timeout=10)
            response.raise_for_status()
            data = response.json()
            job_id = data.get("job_id") or data.get("id")
            if not job_id:
                return {"status": "done", **data}
            for _ in range(self.poll_attempts):
                status_resp = self.session.get(f"{self.base_url}/api/status", params={"job_id": job_id}, timeout=10)
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status", "")
                if status in {"done", "completed", "success"}:
                    result = status_data.get("result") if isinstance(status_data.get("result"), dict) else {}
                    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
                    analysis_path = str(result.get("analysis_path") or "")
                    if not analysis and analysis_path:
                        try:
                            loaded = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
                            if isinstance(loaded, dict):
                                analysis = loaded
                        except Exception:
                            analysis = {}
                    media_dir = str(result.get("media_dir") or "")
                    video_path = str(result.get("video_path") or "")
                    if not video_path and media_dir:
                        candidate = Path(media_dir) / "video.mp4"
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            video_path = str(candidate)
                    audio_path = str(result.get("audio_path") or "")
                    if not audio_path and media_dir:
                        candidate = Path(media_dir) / "audio.mp3"
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            audio_path = str(candidate)
                    caption_path = str(result.get("caption_path") or "")
                    if not caption_path and media_dir:
                        candidate = Path(media_dir) / "caption.txt"
                        if candidate.is_file():
                            caption_path = str(candidate)
                    transcript_path = str(result.get("transcript_path") or "")
                    if not transcript_path and media_dir:
                        candidate = Path(media_dir) / "transcript.txt"
                        if candidate.is_file():
                            transcript_path = str(candidate)
                    caption = str(result.get("caption") or analysis.get("caption") or "")
                    if not caption and caption_path:
                        try:
                            caption = Path(caption_path).read_text(encoding="utf-8").strip()
                        except Exception:
                            caption = ""
                    image_paths = result.get("image_paths", [])
                    if not isinstance(image_paths, list):
                        image_paths = []
                    if not image_paths and media_dir:
                        image_dir = Path(media_dir) / "images"
                        if image_dir.is_dir():
                            image_paths = [
                                str(path)
                                for path in sorted(image_dir.rglob("*"))
                                if path.is_file() and path.stat().st_size > 0
                            ]
                    payload = {
                        "status": "done",
                        "job_id": job_id,
                        "media_dir": media_dir,
                        "analysis_path": analysis_path,
                        "transcript_path": transcript_path,
                        "caption_path": caption_path,
                        "caption": caption,
                        "ocr_path": result.get("ocr_path", ""),
                        "image_ocr": result.get("image_ocr") or analysis.get("image_ocr") or "",
                        "video_path": video_path,
                        "audio_path": audio_path,
                        "image_paths": image_paths,
                        "media_type": result.get("media_type") or analysis.get("media_type") or "",
                        "interaction_screenshot_path": result.get("interaction_screenshot_path", ""),
                    }
                    if analysis:
                        payload["analysis"] = analysis
                    if endpoint == "/api/analyze":
                        payload = self._complete_analysis_payload(url, payload, wait=True)
                    return payload
                if status in {"failed", "error"}:
                    return {"status": "pending_manual", "reason": str(status_data)}
                time.sleep(self.poll_interval_seconds)
            return {"status": "pending_manual", "reason": f"轮询超时 job_id={job_id}"}
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc)}

    @staticmethod
    def _parse_last_json_line(output: str) -> dict[str, Any]:
        for line in reversed((output or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _parse_json_payload(text: str) -> dict[str, Any]:
        value = (text or "").strip()
        if not value:
            return {}
        try:
            payload = json.loads(value)
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            pass

        decoder = json.JSONDecoder()
        fallback: dict[str, Any] = {}
        preferred_keys = {
            "analysis",
            "labeled_transcript",
            "pending_questions",
            "primary_category",
            "speaker_notes",
            "status",
            "summary",
            "title",
        }
        for match in re.finditer(r"\{", value):
            try:
                payload, _ = decoder.raw_decode(value[match.start() :])
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            if any(key in payload for key in preferred_keys):
                return payload
            if not fallback:
                fallback = payload
        return fallback

    def _call_postprocess_json(self, prompt: str, user_content: str, env: dict[str, str], stage: str) -> dict[str, Any]:
        profile = profile_config("transcription_postprocess")
        if str(profile.get("provider") or "").strip() == "openclaw_codex":
            return self._call_openclaw_postprocess_json(prompt, user_content, env, stage)
        return self._call_profile_provider_json("transcription_postprocess", prompt, user_content, stage)

    def _call_profile_provider_json(self, profile_name: str, prompt: str, user_content: str, stage: str) -> dict[str, Any]:
        profile = profile_config(profile_name)
        provider = profile_provider_runtime(profile_name)
        if provider.api_type != "openai_chat_completions":
            return {"status": "pending_manual", "reason": f"{stage}：provider `{profile_name}` 仅支持 openai_chat_completions"}
        base_url = provider.base_url.rstrip("/")
        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        payload = {
            "model": str(profile.get("model") or provider.model).strip(),
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.session.post(
                endpoint,
                headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=float(profile.get("timeout") or provider.timeout or 300),
            )
            response.raise_for_status()
            raw = response.json()
            content = raw["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
            parsed = self._parse_json_payload(str(content))
            if not parsed:
                return {"status": "pending_manual", "reason": f"{stage}：{profile_name} 未返回可解析 JSON"}
            return {
                "status": "done",
                "postprocess_provider": str(profile.get("provider") or "").strip() or profile_name,
                "postprocess_model": payload["model"],
                **parsed,
            }
        except Exception as exc:
            return {"status": "pending_manual", "reason": f"{stage}：{exc}"}

    def _call_openclaw_postprocess_json(self, prompt: str, user_content: str, env: dict[str, str], stage: str) -> dict[str, Any]:
        runtime = profile_runtime("transcription_postprocess")
        openclaw_bin = runtime.bin
        timeout = int(runtime.timeout)
        model = runtime.model
        display_model = display_openclaw_model(model)
        stage_key = hashlib.sha1(stage.encode("utf-8")).hexdigest()[:12]
        session_id = f"transcription-postprocess-{stage_key}-{time.time_ns()}"
        cmd = [openclaw_bin, "agent"]
        cmd.extend(["--agent", runtime.agent])
        cmd.extend(
            [
                "--session-id",
                session_id,
                "--message",
                f"{prompt}\n\n输入 JSON：\n{user_content}",
                "--json",
                "--timeout",
                str(timeout),
            ]
        )
        cmd.extend(["--model", model])
        if runtime.thinking:
            cmd.extend(["--thinking", runtime.thinking])

        run_env = dict(env)
        run_env.setdefault("HOME", "/home/ubuntu")
        run_env["CODEX_HOME"] = runtime.codex_home
        run_env.setdefault(
            "PATH",
            "/home/ubuntu/.nvm/versions/node/v22.22.2/bin:/home/ubuntu/bin:/usr/local/bin:/usr/bin:/bin",
        )
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout + 60,
                env=run_env,
                cwd=runtime.cwd,
            )
        except subprocess.TimeoutExpired:
            return {"status": "pending_manual", "reason": f"{stage}：GPT-5.5 后处理超时，超过 {timeout} 秒"}
        except OSError as exc:
            return {"status": "pending_manual", "reason": f"{stage}：无法调用 OpenClaw/Codex 后处理：{exc}"}

        parsed_run = self._parse_openclaw_json(proc.stdout)
        reply = self._extract_openclaw_reply(parsed_run) or proc.stdout
        parsed = self._parse_json_payload(reply)
        if proc.returncode != 0:
            reason = self._clean_openclaw_postprocess_error(
                proc.stderr.strip() or reply.strip() or f"OpenClaw/Codex 后处理退出码 {proc.returncode}"
            )
            return {"status": "pending_manual", "reason": f"{stage}：{reason[-1800:]}"}
        if not parsed:
            return {"status": "pending_manual", "reason": f"{stage}：GPT-5.5 未返回可解析 JSON"}
        return {"status": "done", "postprocess_provider": "openclaw", "postprocess_model": display_model, **parsed}

    @staticmethod
    def _split_transcript_audio_sections(text: str) -> list[dict[str, Any]]:
        value = (text or "").strip()
        if not value:
            return []
        pattern = re.compile(r"^###\s*录音\s*(\d+)\s*[:：]\s*(.+?)\s*$", re.M)
        matches = list(pattern.finditer(value))
        if not matches:
            return [{"source_audio": "audio-01", "source_title": "录音 1", "text": value, "char_start": 0, "char_end": len(value)}]

        sections: list[dict[str, Any]] = []
        for item_index, match in enumerate(matches):
            start = match.end()
            end = matches[item_index + 1].start() if item_index + 1 < len(matches) else len(value)
            body = value[start:end].strip()
            if not body:
                continue
            try:
                audio_index = int(match.group(1))
            except ValueError:
                audio_index = item_index + 1
            sections.append(
                {
                    "source_audio": f"audio-{audio_index:02d}",
                    "source_title": match.group(2).strip() or f"录音 {audio_index}",
                    "text": body,
                    "char_start": start,
                    "char_end": end,
                }
            )
        return sections or [{"source_audio": "audio-01", "source_title": "录音 1", "text": value, "char_start": 0, "char_end": len(value)}]

    @staticmethod
    def _split_text_chunks(text: str, target_chars: int, max_chars: int, overlap_chars: int) -> list[dict[str, Any]]:
        value = text or ""
        if not value.strip():
            return []
        target = max(1000, int(target_chars or 10000))
        limit = max(target, int(max_chars or target))
        overlap = max(0, min(int(overlap_chars or 0), target // 2))
        length = len(value)
        if length <= limit:
            return [{"char_start": 0, "char_end": length, "text": value.strip()}]

        chunks: list[dict[str, Any]] = []
        pos = 0
        while pos < length:
            window_end = min(length, pos + limit)
            if window_end >= length:
                end = length
            else:
                window = value[pos:window_end]
                min_boundary = min(len(window), max(1, int(target * 0.65)))
                candidates = [match.end() for match in re.finditer(r"[。！？!?]\s*|\n{2,}", window) if match.end() >= min_boundary]
                end = pos + (candidates[-1] if candidates else min(target, len(window)))
            if end <= pos:
                end = min(length, pos + limit)

            raw = value[pos:end]
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw) - len(raw.rstrip())
            char_start = pos + leading
            char_end = end - trailing
            chunk_text = value[char_start:char_end]
            if chunk_text.strip():
                chunks.append({"char_start": char_start, "char_end": char_end, "text": chunk_text.strip()})
            if end >= length:
                break
            next_pos = max(0, end - overlap)
            pos = next_pos if next_pos > pos else end
        return chunks

    @staticmethod
    def _annotate_evidence_hashes(summary: dict[str, Any]) -> None:
        chunk_id = str(summary.get("chunk_id") or "").strip()
        source_audio = str(summary.get("source_audio") or "").strip()
        char_start = summary.get("char_start")
        char_end = summary.get("char_end")
        fields = (
            "key_points",
            "local_observations",
            "local_decisions_or_claims",
            "pending_questions",
            "action_items",
            "sensitive_items",
        )
        for field in fields:
            items = summary.get(field)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                basis = str(
                    item.get("evidence")
                    or item.get("point")
                    or item.get("claim")
                    or item.get("question")
                    or item.get("action")
                    or item.get("summary")
                    or item.get("text")
                    or ""
                )
                normalized = re.sub(r"\s+", "", basis).lower()
                if normalized and not item.get("evidence_hash"):
                    item["evidence_hash"] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
                if not item.get("source_range"):
                    item["source_range"] = {
                        "source_audio": source_audio,
                        "chunk_id": chunk_id,
                        "char_start": char_start,
                        "char_end": char_end,
                    }

    @staticmethod
    def _write_json_artifact(root: Path, filename: str, payload: dict[str, Any]) -> str:
        path = ensure_dir(root) / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    @staticmethod
    def _env_int(env: dict[str, str], key: str, default: int) -> int:
        try:
            return int(float(str(env.get(key, default)).strip()))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _env_truthy(value: str) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _clean_openclaw_postprocess_error(text: str) -> str:
        value = (text or "").strip()
        if not value:
            return "GPT-5.5 后处理失败"
        if "Token refresh failed" in value or "refresh token" in value or "OAuth token refresh failed" in value:
            return (
                "GPT-5.5 认证失败：openai-codex OAuth token 已失效或 refresh token 被重复使用，"
                "需要重新登录：CODEX_HOME=/home/ubuntu/.openclaw/codex-home openclaw models auth login --provider openai-codex"
            )
        if "provider/model overrides are not authorized" in value:
            return "OpenClaw Gateway 拒绝模型覆盖；当前已禁用转写后处理的模型覆盖，请重试。"
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        diagnostic = [line for line in lines if "EMBEDDED FALLBACK" not in line and "[diagnostic]" not in line and "[model-fallback" not in line]
        return "\n".join(diagnostic[-12:]) or lines[-1]

    @staticmethod
    def _parse_openclaw_json(output: str) -> dict[str, Any]:
        text = (output or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            pass
        decoder = json.JSONDecoder()
        fallback: dict[str, Any] = {}
        for match in re.finditer(r"\{", text):
            try:
                payload, _ = decoder.raw_decode(text[match.start() :])
            except ValueError:
                continue
            if isinstance(payload, dict):
                if any(key in payload for key in ("runId", "result", "payloads", "status")):
                    return payload
                if not fallback:
                    fallback = payload
        return fallback

    @staticmethod
    def _extract_openclaw_reply(parsed: dict[str, Any]) -> str:
        for key in ("reply", "message", "text", "output", "final"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        result = parsed.get("result")
        if isinstance(result, dict):
            payloads = result.get("payloads")
            if isinstance(payloads, list):
                texts = [
                    str(payload.get("text")).strip()
                    for payload in payloads
                    if isinstance(payload, dict) and payload.get("text")
                ]
                if texts:
                    return "\n".join(texts)
            for key in ("reply", "message", "text", "output", "final"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            meta = result.get("meta")
            if isinstance(meta, dict):
                for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                    value = meta.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return ""

    @staticmethod
    def _content_flow_env() -> dict[str, str]:
        env = dict(os.environ)
        env_path = CONTENT_FLOW_ROOT / ".env"
        if env_path.is_file():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return env

    @staticmethod
    def _transcription_timeout_seconds(env: dict[str, str]) -> int:
        provider = (env.get("ASR_PROVIDER") or env.get("TRANSCRIPTION_PROVIDER") or "dashscope").strip().lower()
        if provider in {"openai", "whisper", "openai-whisper"}:
            base = env.get("OPENAI_TRANSCRIPTION_TIMEOUT") or env.get("WHISPER_TIMEOUT") or "600"
        else:
            base = env.get("DASHSCOPE_TIMEOUT") or "180"
        try:
            return max(300, int(float(base)) + 120)
        except ValueError:
            return 720 if provider in {"openai", "whisper", "openai-whisper"} else 300

    @staticmethod
    def _clean_transcription_error(text: str) -> str:
        value = (text or "").strip()
        if not value:
            return "本地转写失败"
        value = re.sub(r"\n+", "\n", value)
        value = re.sub(r"Command '\[.*?\]' timed out after [0-9.]+ seconds", "录音转写超时", value, flags=re.S)
        return value[-800:]
