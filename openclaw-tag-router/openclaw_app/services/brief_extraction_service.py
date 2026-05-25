from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


class BriefExtractionService:
    """Reusable text compression and structured brief extraction.

    The service is intentionally deterministic: it normalizes source text,
    optionally enriches it with readable Feishu documents, then extracts a
    compact field bundle that domain handlers can map to their own tables.
    """

    URL_RE = re.compile(r"https?://[^\s<>'\"，。；、）)\]】]+")
    HASHTAG_RE = re.compile(r"(#[\w\u4e00-\u9fff-]+)")

    FIELD_LABELS: dict[str, tuple[str, ...]] = {
        "brief_summary": ("活动Brief", "Brief", "简介", "活动简介", "项目简介", "核心信息", "活动说明"),
        "participation_method": ("参与方式", "参与流程", "报名方式", "报名入口", "如何参与", "参加方式", "参与方法"),
        "participation_form": ("参与形式", "活动形式", "作品形式", "内容形式", "投稿形式"),
        "filling_points": ("填写要点", "报名信息", "提报信息", "填写信息", "需填写", "提交信息", "报名表"),
        "submission_requirements": ("提交要求", "发布要求", "投稿要求", "内容要求", "作品要求", "笔记要求", "返稿要求"),
        "activity_time": ("活动时间", "活动周期", "时间", "截止时间", "报名截止", "投稿截止", "ddl", "DDL"),
        "reward": ("活动奖励", "奖励", "权益", "流量扶持", "流量激励", "曝光激励", "激励", "奖品"),
        "platform": ("平台", "平台名称", "发布平台"),
        "source_link": ("Brief链接", "报名链接", "活动链接", "文档链接", "来源链接", "链接"),
        "content_directions": ("内容方向参考", "内容参考方向", "内容方向", "选题方向", "创作方向", "方向参考"),
    }
    ALL_LABELS = tuple(dict.fromkeys(label for labels in FIELD_LABELS.values() for label in labels))

    PLATFORM_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("小红书", ("小红书", "xhslink", "xiaohongshu")),
        ("抖音", ("抖音", "douyin", "iesdouyin")),
        ("视频号", ("视频号", "weixin.qq.com/sph")),
        ("B站", ("B站", "哔哩哔哩", "bilibili")),
        ("微博", ("微博", "weibo")),
        ("公众号", ("公众号", "mp.weixin.qq.com")),
        ("飞书", ("飞书", "feishu.cn")),
    )

    def __init__(self, feishu_service: Any | None = None):
        self.feishu_service = feishu_service

    def extract(self, text: str, *, domain: str = "general", created_at: datetime | None = None) -> dict[str, Any]:
        raw_text = (text or "").strip()
        links = self.extract_links(raw_text)
        source_reads = self._read_link_sources(links)
        readable_texts = [item["text"] for item in source_reads if item.get("ok") and item.get("text")]
        combined_text = self._normalize_text("\n\n".join([raw_text, *readable_texts]))

        fields = self._extract_common_fields(combined_text, links)
        if domain == "activity":
            fields.update(self._extract_activity_fields(combined_text, fields, created_at))

        status = self._source_status(raw_text, links, source_reads)
        missing_info = self._missing_fields(fields, domain=domain)
        manual_needed = status["manual_needed"] or bool(missing_info and self._effective_text_length(raw_text) < 80)

        fields["source_status"] = status["label"]
        fields["source_links"] = links
        fields["source_reads"] = source_reads
        fields["missing_info"] = missing_info
        fields["manual_needed"] = manual_needed
        fields["created_at"] = created_at.isoformat(timespec="seconds") if created_at else ""

        return {
            "ok": True,
            "domain": domain,
            "raw_text": raw_text,
            "combined_text": combined_text,
            "fields": fields,
            "links": links,
            "source_reads": source_reads,
            "source_status": status["label"],
            "manual_needed": manual_needed,
            "missing_info": missing_info,
        }

    def extract_links(self, text: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in self.URL_RE.finditer(text or ""):
            url = match.group(0).rstrip("，。；、.）)]】")
            if url in seen:
                continue
            seen.add(url)
            label = self._link_label_before(text[: match.start()])
            links.append({"label": label, "url": url, "kind": self._link_kind(url)})
        return links

    def _read_link_sources(self, links: list[dict[str, str]]) -> list[dict[str, Any]]:
        reads: list[dict[str, Any]] = []
        for link in links:
            url = link.get("url", "")
            if link.get("kind") != "feishu_doc":
                continue
            if not self.feishu_service or not hasattr(self.feishu_service, "read_document_text"):
                reads.append({"ok": False, "url": url, "kind": "feishu_doc", "text": "", "error": "未配置飞书文档读取服务"})
                continue
            try:
                result = self.feishu_service.read_document_text(url)
            except Exception as exc:  # best-effort enrichment; extraction must keep working.
                result = {"ok": False, "url": url, "kind": "feishu_doc", "text": "", "error": str(exc)}
            if isinstance(result, dict):
                reads.append(result)
            else:
                reads.append({"ok": False, "url": url, "kind": "feishu_doc", "text": "", "error": "飞书读取返回值异常"})
        return reads

    def _extract_common_fields(self, text: str, links: list[dict[str, str]]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for key, labels in self.FIELD_LABELS.items():
            fields[key] = self._clip(self._extract_labeled_block(text, labels) or self._extract_fuzzy_field(text, key))

        fields["title"] = self._clip(self._extract_title(text), 120)
        fields["platform"] = fields.get("platform") or self._extract_platform(text, links)
        fields["main_topic"] = self._extract_main_topic(text)
        fields["source_link_text"] = "\n".join(f"{item['label']}：{item['url']}" for item in links)

        if not fields.get("brief_summary"):
            fields["brief_summary"] = self._clip(self._summarize(text), 1200)
        if not fields.get("participation_method"):
            fields["participation_method"] = self._clip(
                self._infer_participation_method(text) or self._keyword_lines(text, ("参与", "报名", "投稿", "提交", "发布", "填写")),
                1200,
            )
        if not fields.get("participation_form"):
            fields["participation_form"] = self._clip(self._infer_participation_form(text) or self._keyword_lines(text, ("图文", "视频", "直播", "短视频", "打卡", "形式")), 800)
        if not fields.get("filling_points"):
            fields["filling_points"] = self._clip(
                self._infer_filling_points(text) or self._keyword_lines(text, ("填写", "填报", "报名表", "提报", "提交信息", "姓名", "账号", "链接")),
                1200,
            )
        if not fields.get("submission_requirements"):
            fields["submission_requirements"] = self._clip(
                self._infer_submission_requirements(text, fields) or self._keyword_lines(text, ("要求", "必须", "需要", "需", "不得", "至少", "带话题", "返稿")),
                1200,
            )
        return fields

    def _extract_activity_fields(self, text: str, fields: dict[str, Any], created_at: datetime | None = None) -> dict[str, Any]:
        output: dict[str, Any] = {}
        output["activity_time"] = fields.get("activity_time") or self._extract_time_hint(text)
        output["reward"] = fields.get("reward") or self._extract_reward_hint(text)
        level_match = re.search(r"([A-Z]{1,3})\s*级", text)
        output["level"] = level_match.group(1) if level_match else ""
        output["directions"] = self._extract_content_directions(text, fields) or self._extract_inline_content_directions(text) or self._extract_topic_directions(text)
        merged = {**fields, **output}
        output["activity_time"] = self._clean_activity_time(str(output.get("activity_time") or ""), created_at)
        output["participation_method"] = self._clean_participation_method(str(fields.get("participation_method") or ""), merged, text)
        output["submission_requirements"] = self._clean_submission_requirements(str(fields.get("submission_requirements") or ""), merged, text)
        return output

    def _extract_labeled_block(self, text: str, labels: tuple[str, ...]) -> str:
        if not text:
            return ""
        target = "|".join(re.escape(label) for label in labels)
        known = "|".join(re.escape(label) for label in self.ALL_LABELS)
        prefix = r"(?:[^\w\u4e00-\u9fff#]{0,6}\s*)?(?:[-*#>]+\s*)?(?:[（(]?\d{1,2}[）).、]\s*)?"
        label_re = re.compile(rf"^\s*{prefix}(?:{target})\s*[：:]\s*(.*)$", re.IGNORECASE)
        stop_re = re.compile(rf"^\s*{prefix}(?:{known})(?:\s*[：:].*)?$", re.IGNORECASE)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = label_re.match(line)
            if not match:
                continue
            block: list[str] = []
            tail = match.group(1).strip()
            if tail:
                block.append(tail)
            for next_line in lines[index + 1 : index + 8]:
                stripped = next_line.strip()
                if not stripped:
                    if block:
                        break
                    continue
                if stop_re.match(stripped):
                    break
                block.append(stripped.strip("-*#> "))
            return "\n".join(item for item in block if item).strip()
        return ""

    def _extract_fuzzy_field(self, text: str, key: str) -> str:
        lines = [self._clean_line(line) for line in text.splitlines()]
        for index, clean in enumerate(lines):
            if not clean or self._is_noise_line(clean):
                continue
            if key == "activity_time" and self._looks_like_time_line(clean):
                return self._line_payload(clean)
            if key == "reward" and self._looks_like_reward_line(clean):
                return self._line_payload(clean)
            if key == "participation_method" and self._looks_like_participation_line(clean):
                return self._line_payload(clean)
            if key == "filling_points" and self._looks_like_fill_line(clean):
                return self._line_payload(clean)
            if key == "submission_requirements":
                if self._is_content_direction_heading(clean):
                    return self._content_requirement_from_line(clean)
                if self._looks_like_requirement_line(clean):
                    return self._line_payload(clean)
            if key == "content_directions" and self._is_content_direction_heading(clean):
                return "\n".join(self._following_direction_lines(lines[index + 1 : index + 14]))
        return ""

    def _looks_like_time_line(self, line: str) -> bool:
        return bool(re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*日", line)) and any(key in line for key in ("时间", "周期", "截止", "ddl", "DDL"))

    def _looks_like_reward_line(self, line: str) -> bool:
        if any(key in line for key in ("奖励", "激励", "权益", "奖品", "现金", "流量券", "扶持")):
            return True
        if any(key in line for key in ("曝光", "流量", "投流")) and not self._looks_like_time_line(line):
            return True
        return False

    def _looks_like_participation_line(self, line: str) -> bool:
        action_hit = any(key in line for key in ("参与", "报名", "投稿", "返稿", "发布", "邀请", "注册", "填报"))
        context_hit = any(key in line for key in ("主话题", "话题", "笔记", "账号", "链接", "方向", "招募", "内容"))
        return action_hit and context_hit and not self._looks_like_reward_line(line)

    def _looks_like_fill_line(self, line: str) -> bool:
        return any(key in line for key in ("填写", "填报", "报名表", "提报", "表单", "链接", "返稿"))

    def _looks_like_requirement_line(self, line: str) -> bool:
        return any(key in line for key in ("必带", "主话题", "任选", "审核", "通过", "要求", "不得", "至少", "无需重复", "返稿"))

    def _line_payload(self, line: str) -> str:
        clean = self._strip_known_label(line)
        if clean != line:
            return clean
        if "：" in line or ":" in line:
            return re.split(r"[：:]", line, maxsplit=1)[1].strip()
        return line.strip()

    def _clean_activity_time(self, value: str, created_at: datetime | None) -> str:
        text = re.sub(r"[（(].*?[）)]", "", value or "").strip()
        if not text:
            return ""
        base_year = created_at.year if created_at else datetime.now().year
        match = re.search(
            r"(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
            r"(?:\s*[-~—至到]+\s*(?:(\d{1,2})\s*月)?\s*(\d{1,2})\s*日)?",
            text,
        )
        if not match:
            return " ".join(text.split())
        year = int(match.group(1) or base_year)
        start_month = int(match.group(2))
        start_day = int(match.group(3))
        end_month = int(match.group(4) or start_month) if match.group(5) else 0
        end_day = int(match.group(5) or 0)
        start = f"{year:04d}-{start_month:02d}-{start_day:02d}"
        if not end_day:
            return start
        end_year = year + 1 if end_month < start_month else year
        end = f"{end_year:04d}-{end_month:02d}-{end_day:02d}"
        return f"{start} 至 {end}"

    def _clean_participation_method(self, value: str, fields: dict[str, Any], text: str) -> str:
        lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
        cleaned: list[str] = []
        direction_count = len(fields.get("directions") or [])
        for line in lines:
            item = self._clean_content_requirement_text(line, direction_count)
            item = re.sub(r"\s+", " ", item).strip()
            if item:
                cleaned.append(item)

        if not cleaned:
            requirement = self._content_requirement_line(text)
            if requirement:
                cleaned.append(self._clean_content_requirement_text(requirement, direction_count))

        compact = self._dedupe_lines(cleaned)
        return "\n".join(compact)

    def _clean_submission_requirements(self, value: str, fields: dict[str, Any], text: str) -> str:
        lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
        direction_count = len(fields.get("directions") or [])
        cleaned = [self._clean_content_requirement_text(line, direction_count) for line in lines]
        if "返稿链接" in text and not any("返稿" in item or "提交" in item for item in cleaned):
            cleaned.append("通过笔记返稿链接提交，无需重复投稿")
        return "\n".join(self._dedupe_lines([item for item in cleaned if item]))

    def _clean_content_requirement_text(self, line: str, direction_count: int = 0) -> str:
        clean = self._strip_known_label(self._clean_line(line)).strip("；; ")
        clean = clean.replace("+以下任选子话题方向创作", "并从以下子话题方向中任选一个进行创作")
        clean = clean.replace("以下任选子话题方向创作", "从以下子话题方向中任选一个进行创作")
        clean = clean.replace("返稿/提交", "提交")
        topic_match = self.HASHTAG_RE.search(clean)
        if "必带" in clean and "主话题" in clean and topic_match:
            topic = topic_match.group(1)
            suffix = "；从「子话题方向」字段中任选 1 个方向创作" if direction_count else "；从子话题方向中任选 1 个方向创作"
            if "任选" in clean or "方向" in clean:
                return f"发布笔记时必带主话题 {topic}{suffix}"
            return f"发布笔记时必带主话题 {topic}"
        if "带主话题" in clean and topic_match and "发布笔记" in clean:
            topic = topic_match.group(1)
            mention_match = re.search(r"(@[\w\u4e00-\u9fff-]+)", clean)
            mention = f"，并 {mention_match.group(1)}" if mention_match else ""
            return f"发布小红书笔记时带主话题 {topic}{mention}"
        return clean

    def _dedupe_lines(self, lines: list[str]) -> list[str]:
        compact: list[str] = []
        seen: set[str] = set()
        for line in lines:
            clean = line.strip()
            key = re.sub(r"\s+", "", clean)
            if clean and key not in seen:
                seen.add(key)
                compact.append(clean)
        return compact

    def _extract_title(self, text: str) -> str:
        preferred = ""
        for line in text.splitlines():
            clean = self._clean_line(line).lstrip("#").strip()
            clean = re.sub(r"^【[^】]{1,32}】", "", clean).strip()
            if not clean or self.URL_RE.fullmatch(clean) or self._is_noise_line(clean):
                continue
            if any(clean.startswith(f"{label}：") or clean.startswith(f"{label}:") for label in self.ALL_LABELS):
                continue
            named = self._extract_named_campaign(clean)
            if named:
                return named
            if any(keyword in clean for keyword in ("活动", "招募", "征稿", "话题")):
                return self._compact_title(clean)
            if not preferred:
                preferred = clean
        if preferred:
            return self._compact_title(preferred)
        return "未命名 Brief"

    def _summarize(self, text: str) -> str:
        candidates: list[str] = []
        keywords = ("活动", "招募", "征稿", "话题", "奖励", "参与", "报名", "提交", "要求", "截止", "平台")
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean or self.URL_RE.fullmatch(clean) or self._is_noise_line(clean):
                continue
            if len(candidates) == 0:
                candidates.append(clean)
                continue
            if any(key in clean for key in keywords):
                candidates.append(clean)
            if len(candidates) >= 6:
                break
        if not candidates:
            return ""
        return "\n".join(candidates)

    def _keyword_lines(self, text: str, keywords: tuple[str, ...]) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean or clean in seen or self.URL_RE.fullmatch(clean) or self._is_noise_line(clean):
                continue
            if any(keyword in clean for keyword in keywords):
                seen.add(clean)
                lines.append(clean)
            if len(lines) >= 8:
                break
        return "\n".join(lines)

    def _infer_participation_form(self, text: str) -> str:
        forms: list[str] = []
        if "小红书" in text and "笔记" in text:
            forms.append("小红书笔记")
        if "图文" in text:
            forms.append("图文")
        if "视频笔记" in text:
            forms.append("视频笔记")
        elif "视频" in text or "短视频" in text:
            forms.append("视频/短视频")
        if "直播" in text:
            forms.append("直播")
        if "招募" in text and "邀请" in text:
            forms.append("连接人招募")
        if "注册小红书账号" in text and "发布首篇" in text:
            forms.append("邀请注册并发布首篇内容")
        return " / ".join(dict.fromkeys(forms))

    def _infer_participation_method(self, text: str) -> str:
        content_requirement = self._content_requirement_line(text)
        if content_requirement:
            parts = [content_requirement]
            if "返稿链接" in text:
                parts.append("通过笔记返稿链接返稿/提交，无需重复投稿")
            return "\n".join(parts)
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean or self._is_noise_line(clean):
                continue
            if "招募" in clean and "邀请" in clean and ("：" in clean or ":" in clean):
                before, _, after = re.split(r"[：:]", clean, maxsplit=1)[0], "：", re.split(r"[：:]", clean, maxsplit=1)[1]
                audience = ""
                audience_match = re.search(r"如果你(?:现在)?(?P<audience>.*?)(?:，欢迎参与|欢迎参与|，?参与)", before)
                if audience_match:
                    audience = "适合人群：" + audience_match.group("audience").strip("，,；; ")
                action = "参与动作：" + after.strip("；; ")
                parts = [item for item in (audience, action) if item]
                return "\n".join(parts)
        return ""

    def _infer_filling_points(self, text: str) -> str:
        points: list[str] = []
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean or self._is_noise_line(clean):
                continue
            if any(key in clean for key in ("填报", "报名", "身边有", "资源", "同事", "同学", "球迷群", "社群伙伴")):
                points.append(clean)
        if self.extract_links(text):
            points.append("填写/填报链接：" + "；".join(item["url"] for item in self.extract_links(text)))
        compact: list[str] = []
        seen: set[str] = set()
        for item in points:
            key = re.sub(r"\s+", "", item)
            if item and key not in seen:
                seen.add(key)
                compact.append(item)
        return "\n".join(compact[:6])

    def _infer_submission_requirements(self, text: str, fields: dict[str, Any]) -> str:
        requirements: list[str] = []
        content_requirement = self._content_requirement_line(text)
        if content_requirement:
            requirements.append(content_requirement)
        if "返稿链接" in text:
            requirements.append("通过笔记返稿链接返稿/提交，无需重复投稿")
        method = str(fields.get("participation_method") or "")
        if method:
            for method_line in method.splitlines():
                if "主话题" in method_line or "#" in method_line:
                    requirements.append(method_line)
                elif "@ " in method_line or "@" in method_line:
                    requirements.append(method_line)
                elif "邀请" in method_line and "发布" in method_line:
                    requirements.append(method_line)
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean or self._is_noise_line(clean):
                continue
            if self._is_content_direction_heading(clean):
                continue
            if any(key in clean for key in ("带主话题", "并 @", "并@", "符合话题方向", "投稿链接", "报名链接", "填报", "完整注册", "审核通过", "发布首篇")):
                requirements.append(self._strip_known_label(clean))
        directions = self._extract_content_directions(text, fields)
        if directions:
            requirements.append("内容方向参考：" + "；".join(directions))
        compact: list[str] = []
        seen: set[str] = set()
        for item in requirements:
            key = re.sub(r"\s+", "", item)
            if item and key not in seen:
                seen.add(key)
                compact.append(item)
        return "\n".join(compact[:8])

    def _extract_platform(self, text: str, links: list[dict[str, str]]) -> str:
        haystack = "\n".join([text or "", *[item.get("url", "") for item in links]]).lower()
        for platform, hints in self.PLATFORM_HINTS:
            if any(hint.lower() in haystack for hint in hints):
                return platform
        return "未识别"

    def _extract_main_topic(self, text: str) -> str:
        match = self.HASHTAG_RE.search(text or "")
        return match.group(1) if match else ""

    def _extract_time_hint(self, text: str) -> str:
        match = re.search(r"(\d{1,2}\s*月\s*\d{1,2}\s*日(?:\s*[-~至到]\s*\d{1,2}\s*月?\s*\d{1,2}\s*日)?(?:\s*\d{1,2}[:：]\d{2})?)", text)
        return match.group(1).replace(" ", "") if match else ""

    def _extract_reward_hint(self, text: str) -> str:
        strong_keywords = ("奖励", "奖品", "激励", "权益", "扶持")
        for line in text.splitlines():
            clean = self._clean_line(line)
            if any(key in clean for key in strong_keywords):
                return clean
        for line in text.splitlines():
            clean = self._clean_line(line)
            if "活动时间" in clean or "截止时间" in clean:
                continue
            if any(key in clean for key in ("流量", "曝光")):
                return clean
        return ""

    def _extract_topic_directions(self, text: str) -> list[str]:
        directions: list[str] = []
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean.startswith("#"):
                continue
            if clean not in directions:
                directions.append(clean)
        return directions[:20]

    def _extract_content_directions(self, text: str, fields: dict[str, Any] | None = None) -> list[str]:
        directions: list[str] = []
        labeled = str((fields or {}).get("content_directions") or "").strip()
        if labeled:
            for line in labeled.splitlines():
                clean = self._clean_direction_line(line)
                if clean:
                    directions.append(clean)

        lines = text.splitlines()
        in_section = False
        for line in lines:
            clean = self._clean_line(line)
            if not clean:
                if in_section and directions:
                    break
                continue
            if self._is_content_direction_heading(clean):
                in_section = True
                continue
            if not in_section:
                continue
            direction = self._clean_direction_line(clean)
            if not direction:
                if directions:
                    break
                continue
            directions.append(direction)
            if len(directions) >= 12:
                break

        compact: list[str] = []
        seen: set[str] = set()
        for item in directions:
            if item not in seen:
                seen.add(item)
                compact.append(item)
        return compact[:12]

    def _is_content_direction_heading(self, line: str) -> bool:
        clean = self._clean_line(line)
        has_direction = "方向" in clean or "选题" in clean or "子话题" in clean
        has_context = any(key in clean for key in ("内容", "参考", "创作", "话题", "任选", "必带"))
        return has_direction and has_context

    def _following_direction_lines(self, lines: list[str]) -> list[str]:
        directions: list[str] = []
        for line in lines:
            clean = self._clean_line(line)
            if not clean:
                if directions:
                    break
                continue
            if self._looks_like_time_line(clean) or self._looks_like_reward_line(clean) or self._looks_like_fill_line(clean):
                break
            if self._is_content_direction_heading(clean):
                continue
            if any(key in clean for key in ("文档参考", "活动文档", "链接参考", "报名链接", "投稿链接", "返稿链接")):
                break
            if clean.startswith("http"):
                break
            direction = self._clean_direction_line(clean)
            if direction:
                directions.append(direction)
            if len(directions) >= 12:
                break
        return directions

    def _extract_inline_content_directions(self, text: str) -> list[str]:
        match = re.search(r"分享(?:他们|你|大家)?的?([^。\n；;]+?)(?:。|；|;|\n)", text)
        if not match:
            return []
        segment = match.group(1).strip()
        if not any(key in segment for key in ("日记", "故事", "文化", "预测", "reaction", "内容")):
            return []
        raw_items = re.split(r"[、,，]|和", segment)
        items = [item.strip(" 的") for item in raw_items if item.strip(" 的")]
        return items[:8]

    def _missing_fields(self, fields: dict[str, Any], *, domain: str) -> list[str]:
        required = ["brief_summary", "participation_method", "participation_form", "filling_points", "submission_requirements"]
        label_map = {
            "brief_summary": "Brief",
            "participation_method": "参与方式",
            "participation_form": "参与形式",
            "filling_points": "填写要点",
            "submission_requirements": "提交要求",
        }
        return [label_map[key] for key in required if not fields.get(key)]

    def _source_status(self, raw_text: str, links: list[dict[str, str]], reads: list[dict[str, Any]]) -> dict[str, Any]:
        feishu_links = [item for item in links if item.get("kind") == "feishu_doc"]
        read_ok = any(item.get("ok") and item.get("text") for item in reads)
        raw_len = self._effective_text_length(raw_text)
        if read_ok:
            return {"label": "已读取飞书文档并合并解析", "manual_needed": False}
        if feishu_links and raw_len < 120:
            return {"label": "飞书文档待读取，需人工复制正文补充", "manual_needed": True}
        if feishu_links:
            return {"label": "飞书文档待读取，已按消息文本解析", "manual_needed": False}
        return {"label": "已按消息文本解析", "manual_needed": False}

    def _effective_text_length(self, text: str) -> int:
        clean = self.URL_RE.sub("", text or "")
        clean = re.sub(r"^【[^】]{1,32}】", "", clean.strip())
        return len(clean.strip())

    def _link_label_before(self, prefix: str) -> str:
        tail = prefix.splitlines()[-1] if prefix.splitlines() else ""
        match = re.search(r"([^\s：:]{1,24})\s*[：:]\s*$", tail)
        if match:
            return match.group(1).strip("🔗🧩- ")
        return "来源链接"

    def _link_kind(self, url: str) -> str:
        host = urlparse(url).netloc.lower()
        if "feishu.cn" in host or "larksuite.com" in host:
            return "feishu_doc"
        return "external"

    def _normalize_text(self, text: str) -> str:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _clean_line(self, line: str) -> str:
        clean = line.strip().strip(" \t-•*")
        return re.sub(r"^[📢📅🎉📝🔗🧩🌟]+\s*", "", clean)

    def _clean_direction_line(self, line: str) -> str:
        clean = self._clean_line(line)
        clean = re.sub(r"^\s*(?:\d+\ufe0f?\u20e3|[（(]?\d{1,2}[）).、]|[一二三四五六七八九十]+[、.])\s*", "", clean)
        return clean.strip("；; ")

    def _compact_title(self, text: str) -> str:
        clean = text.strip()
        if any(keyword in clean for keyword in ("活动", "招募", "征稿", "话题")):
            first_sentence = re.split(r"[。！？!?]", clean, maxsplit=1)[0].strip()
            if first_sentence:
                clean = first_sentence
        return clean[:120].strip()

    def _extract_named_campaign(self, text: str) -> str:
        match = re.search(r"[「“](?P<name>[^」”]{2,40})[」”]\s*(?P<kind>招募|活动|征集|计划)", text)
        if not match:
            return ""
        return f"{match.group('name')}{match.group('kind')}"

    def _strip_known_label(self, line: str) -> str:
        prefix = r"(?:[^\w\u4e00-\u9fff#]{0,6}\s*)?(?:[-*#>]+\s*)?(?:[（(]?\d{1,2}[）).、]\s*)?"
        known = "|".join(re.escape(label) for label in self.ALL_LABELS)
        clean = self._clean_line(line)
        return re.sub(rf"^\s*{prefix}(?:{known})\s*[：:]\s*", "", clean, flags=re.IGNORECASE).strip()

    def _content_requirement_line(self, text: str) -> str:
        for line in text.splitlines():
            clean = self._clean_line(line)
            if not clean:
                continue
            if self._is_content_direction_heading(clean) and ("必带" in clean or "主话题" in clean or "任选" in clean):
                return self._content_requirement_from_line(clean)
        return ""

    def _content_requirement_from_line(self, line: str) -> str:
        requirement = re.sub(r"^.*?[（(](.*?)[）)]\s*$", r"\1", line).strip()
        return requirement or self._line_payload(line)

    def _is_noise_line(self, line: str) -> bool:
        clean = line.strip()
        return clean in {"@所有人", "@all", "@All", "所有人"} or clean.startswith("@所有人")

    def _clip(self, text: str, limit: int = 2000) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"
