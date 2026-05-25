from __future__ import annotations

from .tag_router_common import *
from ..services.media_text_cleaner import MEDIA_TEXT_CLEANER, MediaCopyParts


class MediaKnowledgeFieldsMixin:
    def _knowledge_title(self, body: str, analysis: dict[str, Any]) -> str:
        for key in ("title", "标题", "name", "名称"):
            value = self._knowledge_clean_analysis_value(analysis.get(key))
            if value and not self._knowledge_looks_like_share_text(value):
                return self._knowledge_compact_title(value)

        summary_title = self._knowledge_title_from_summary(analysis.get("summary"))
        if summary_title:
            return summary_title

        markdown_title = self._knowledge_title_from_share_text(body)
        if markdown_title:
            return markdown_title

        caption = analysis.get("caption")
        if isinstance(caption, str) and caption.strip() and not caption.strip().startswith("http"):
            return self._knowledge_compact_title(caption.strip().splitlines()[0])
        return self._knowledge_compact_title(body) or "未命名自媒体知识"

    def _knowledge_compact_title(self, value: str, *, limit: int = 42) -> str:
        text = re.sub(r"^[-*•\d.、\s]+", "", str(value or "")).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            return ""
        if len(text) <= limit:
            return text
        for sep in ("。", "；", ";", "，", ","):
            head = text.split(sep, 1)[0].strip()
            if 12 <= len(head) <= limit:
                return head
        return text[:limit].rstrip()

    def _knowledge_looks_like_share_text(self, value: str) -> bool:
        text = str(value or "")
        return bool(
            "http://" in text
            or "https://" in text
            or "复制打开" in text
            or "复制这段" in text
            or re.search(r"\[[^\]]{8,}\]\(https?://", text)
        )

    def _knowledge_title_from_summary(self, summary: Any) -> str:
        if isinstance(summary, list):
            for item in summary:
                text = self._knowledge_clean_analysis_value(item)
                if text:
                    return self._knowledge_compact_title(text)
        text = self._knowledge_clean_analysis_value(summary)
        if text:
            for line in text.splitlines():
                line = line.strip(" -\t")
                if line:
                    return self._knowledge_compact_title(line)
        return ""

    def _knowledge_title_from_share_text(self, body: str) -> str:
        text = str(body or "")
        match = re.search(r"\[([^\]]{8,160})\]\(https?://", text)
        if match:
            title = match.group(1).strip()
            title = re.sub(r"#\S+", "", title).strip()
            return self._knowledge_compact_title(title)
        cleaned = re.sub(r"https?://\S+", " ", text)
        cleaned = re.sub(r"复制打开\S*", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return self._knowledge_compact_title(cleaned)

    def _knowledge_read_text_file(self, path: str) -> str:
        if not path:
            return ""
        file_path = Path(path)
        if not file_path.is_file():
            return ""
        try:
            return file_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _knowledge_text_value(self, value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value.strip()
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()

    def _knowledge_is_boilerplate_text(self, value: str) -> bool:
        text = " ".join(str(value or "").split())
        if not text:
            return False
        markers = (
            "未明确体现，需人工复核",
            "未明确体现,需人工复核",
            "待复核：模型未提取到明确",
            "待复核:模型未提取到明确",
            "模型未提取到完整视频脚本",
            "模型未提取到完整内容",
            "模型未提取到明确隐形信息",
            "模型未提取到明确镜头",
            "保留原链接和已下载媒体",
            "当前先作为知识素材入库",
            "避免链路阻塞",
            "可重新生成完整拆解",
        )
        if any(marker in text for marker in markers):
            return True
        compact_upper = re.sub(r"[\s/_-]+", "", text).upper()
        return "待配置" in text and ("GEMINI" in compact_upper or "GEMINL" in compact_upper or "DASHSCOPE" in compact_upper)

    def _knowledge_clean_analysis_value(self, value: Any) -> str:
        text = self._knowledge_text_value(value)
        if self._knowledge_is_boilerplate_text(text):
            return ""
        return text

    def _knowledge_video_path(self, media_dir: str) -> str:
        if not media_dir:
            return ""
        video_path = Path(media_dir) / "video.mp4"
        if video_path.is_file() and video_path.stat().st_size > 0:
            return str(video_path)
        return ""

    def _knowledge_result_video_path(self, result: dict[str, Any]) -> str:
        direct_path = str(result.get("video_path") or "")
        if direct_path:
            path = Path(direct_path)
            if path.is_file() and path.stat().st_size > 0:
                return str(path)
        return self._knowledge_video_path(str(result.get("media_dir") or ""))

    def _knowledge_result_image_paths(self, result: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        direct_paths = result.get("image_paths")
        if isinstance(direct_paths, list):
            for item in direct_paths:
                path = Path(str(item or ""))
                if path.is_file() and path.stat().st_size > 0:
                    paths.append(str(path))
        media_dir = str(result.get("media_dir") or "")
        if media_dir:
            image_dir = Path(media_dir) / "images"
            if image_dir.is_dir():
                for path in sorted(image_dir.rglob("*")):
                    if path.is_file() and path.stat().st_size > 0:
                        paths.append(str(path))
        deduped: list[str] = []
        seen: set[str] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)
        return deduped

    def _knowledge_caption_text(self, result: dict[str, Any], analysis: dict[str, Any]) -> str:
        for value in (analysis.get("caption"), result.get("caption")):
            text = self._knowledge_clean_analysis_value(value)
            if text:
                return text
        caption_path = str(result.get("caption_path") or "")
        if not caption_path and result.get("media_dir"):
            caption_path = str(Path(str(result.get("media_dir"))) / "caption.txt")
        return self._knowledge_read_text_file(caption_path)

    def _knowledge_script_text(self, result: dict[str, Any], analysis: dict[str, Any]) -> str:
        explicit = self._knowledge_clean_analysis_value(
            analysis.get("full_content")
            or analysis.get("全部内容")
            or analysis.get("full_script")
            or analysis.get("全部视频脚本")
            or analysis.get("script")
        )
        if explicit:
            return explicit
        transcript = self._knowledge_read_text_file(str(result.get("transcript_path") or ""))
        if transcript:
            return transcript
        return self._knowledge_caption_text(result, analysis)

    def _knowledge_image_ocr_text(self, result: dict[str, Any], analysis: dict[str, Any]) -> str:
        text = self._knowledge_clean_analysis_value(analysis.get("image_ocr") or result.get("image_ocr"))
        if text:
            return text
        ocr_path = str(result.get("ocr_path") or "")
        if not ocr_path and result.get("media_dir"):
            ocr_path = str(Path(str(result.get("media_dir"))) / "ocr.txt")
        return self._knowledge_read_text_file(ocr_path)

    def _knowledge_clean_ocr_for_copy(self, text: str) -> str:
        return MEDIA_TEXT_CLEANER.clean_ocr_for_copy(text)

    def _knowledge_clean_transcript_for_copy(self, transcript: str) -> str:
        return MEDIA_TEXT_CLEANER.clean_transcript_for_copy(transcript)

    def _knowledge_tags(self, analysis: dict[str, Any]) -> list[str]:
        tags = analysis.get("tags")
        if isinstance(tags, list):
            return [str(item).strip() for item in tags if str(item).strip()]
        text = self._knowledge_text_value(tags)
        return MEDIA_TEXT_CLEANER.clean_tags(text)

    def _knowledge_unified_text(self, body: str, result: dict[str, Any], *, allow_body_fallback: bool = True) -> str:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        caption = self._knowledge_caption_text(result, analysis)
        transcript = self._knowledge_read_text_file(str(result.get("transcript_path") or ""))
        image_ocr = self._knowledge_image_ocr_text(result, analysis)
        copy = MEDIA_TEXT_CLEANER.build_unified_copy(
            MediaCopyParts(caption=caption, transcript=transcript, image_ocr=image_ocr, tags=tuple(self._knowledge_tags(analysis)))
        )
        if copy:
            return copy
        if not allow_body_fallback:
            return ""
        return body.strip()

    def _knowledge_has_structured_analysis(self, analysis: dict[str, Any]) -> bool:
        if not analysis:
            return False
        if analysis.get("analysis_status") == "needs_model_rerun":
            return False
        if analysis.get("analysis_status") == "fallback_from_downloaded_assets":
            return False
        if analysis.get("analysis_provider") == "tag-router-fallback":
            return False
        if analysis.get("fallback_reason") == "missing_GEMINI_API_KEY":
            return False
        if analysis.get("fallback_reason") in {"missing_QWEN_API_KEY", "analysis_models_unavailable"}:
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
            "full_content",
            "tags",
        ):
            if self._knowledge_clean_analysis_value(analysis.get(key)):
                return True
        return False

    def _knowledge_completion_issue(self, result: dict[str, Any], *, require_video: bool) -> str:
        if result.get("status") != "done":
            return str(result.get("reason") or "content-flow 未完成")

        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        video_path = self._knowledge_result_video_path(result)
        image_paths = self._knowledge_result_image_paths(result)
        transcript = self._knowledge_read_text_file(str(result.get("transcript_path") or ""))
        caption = self._knowledge_caption_text(result, analysis)
        script_text = self._knowledge_script_text(result, analysis)

        if require_video and not video_path:
            return "content-flow 未产出可用视频文件"
        if not (video_path or image_paths or transcript or caption):
            return "content-flow 未产出可用媒体、字幕或逐字稿"
        if require_video and not script_text:
            return "content-flow 未产出逐字稿或完整内容"
        if not self._knowledge_has_structured_analysis(analysis):
            if analysis.get("fallback_reason") == "missing_GEMINI_API_KEY":
                return "GEMINI_API_KEY 未配置，无法生成完整结构化分析"
            if analysis.get("fallback_reason") == "missing_QWEN_API_KEY":
                return "config/openclaw_bots.json providers.qwen.api_key 未配置，无法生成完整结构化分析"
            if analysis.get("fallback_reason") == "analysis_models_unavailable":
                return "结构化分析模型当前不可用"
            if analysis.get("analysis_status") == "needs_model_rerun":
                return "结构化分析需要重新运行模型"
            if analysis.get("analysis_status") == "fallback_from_downloaded_assets":
                return "当前仅生成兜底分析，需等待正式结构化分析完成"
            if analysis.get("analysis_provider") == "tag-router-fallback":
                return "当前仅生成兜底分析，需等待正式结构化分析完成"
            return "content-flow 未产出可用结构化分析"
        return ""

    def _knowledge_platform_from_text(self, text: str) -> str:
        lower = (text or "").lower()
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

    def _knowledge_content_type(self, body: str, result: dict[str, Any], platform: str) -> str:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        media_type = str(result.get("media_type") or analysis.get("media_type") or "").lower()
        if self._knowledge_result_video_path(result):
            return "短视频"
        if self._knowledge_result_image_paths(result) or media_type in {"image", "images", "photo", "photos", "animated", "图文", "图片"}:
            return "图文"
        if platform in {"抖音", "TikTok", "快手", "B站", "YouTube"}:
            return "短视频"
        if contains_link(body):
            return "网页"
        return "其他"

    def _knowledge_split_category(self, value: Any) -> tuple[str, str]:
        text = self._knowledge_clean_analysis_value(value)
        if not text:
            return "", ""
        for sep in (" - ", "-", "—", "｜", "|", ">", "：", ":"):
            if sep in text:
                primary, secondary = text.split(sep, 1)
                return primary.strip(), secondary.strip()
        return text.strip(), ""

    def _knowledge_normalize_primary_category(self, value: str) -> str:
        text = (value or "").strip()
        compact = re.sub(r"[\s/_-]+", "", text).lower()
        if not text:
            return ""
        aliases = [
            ("AI/工具", ["ai", "aigc", "人工智能", "大模型", "智能体", "自动化", "工具"]),
            ("商业/产品", ["商业", "产品", "增长", "品牌", "销售", "用户"]),
            ("运营/管理", ["运营", "管理", "组织", "流程", "项目", "团队"]),
            ("学习/认知", ["学习", "认知", "思维", "方法", "教育"]),
            ("健康/运动", ["健康", "运动", "健身", "医学", "睡眠"]),
            ("财经/投资", ["财经", "投资", "股票", "基金", "资产", "经济"]),
            ("法律/政策", ["法律", "政策", "合同", "合规", "监管", "版权"]),
            ("生活/效率", ["生活", "效率", "习惯", "沟通", "时间管理"]),
            ("科技/科学", ["科技", "科学", "研究", "论文", "工程"]),
            ("人物/案例", ["人物", "案例", "故事", "访谈", "经历"]),
        ]
        for category, keywords in aliases:
            if any(keyword in compact for keyword in keywords):
                return category
        return text

    def _knowledge_default_secondary_category(self, primary: str) -> str:
        defaults = {
            "AI/工具": "AI工具应用",
            "商业/产品": "产品增长",
            "运营/管理": "流程管理",
            "学习/认知": "学习方法",
            "健康/运动": "健康管理",
            "财经/投资": "投资认知",
            "法律/政策": "合规风险",
            "生活/效率": "生活效率",
            "科技/科学": "科技趋势",
            "人物/案例": "案例拆解",
            "其他": "未细分",
        }
        return defaults.get(primary or "其他", "未细分")

    def _knowledge_category_fields(self, analysis: dict[str, Any], text: str) -> dict[str, str]:
        configured_category = (
            analysis.get("一级分类")
            or analysis.get("primary_category")
            or analysis.get("knowledge_category")
            or analysis.get("content_category")
            or analysis.get("category")
            or analysis.get("赛道/标签")
        )
        configured_secondary = (
            analysis.get("二级分类")
            or analysis.get("secondary_category")
            or analysis.get("subcategory")
            or analysis.get("sub_category")
            or analysis.get("content_subcategory")
        )
        category, secondary = self._knowledge_split_category(configured_category)
        explicit_secondary = self._knowledge_clean_analysis_value(configured_secondary)
        if explicit_secondary:
            secondary = explicit_secondary
        category = self._knowledge_normalize_primary_category(category)
        lower_text = text.lower()
        category_rules = [
            ("AI/工具", "AI视频/自动化", ["剪视频", "自动剪", "视频制作", "remotion", "ffmpeg", "字幕", "剪辑", "口播"]),
            ("AI/工具", "模型/智能体", ["openai", "codex", "智能体", "agent", "大模型", "模型", "transformer", "rag", "token", "提示词"]),
            ("AI/工具", "AI工具应用", ["ai", "aigc", "人工智能", "自动化", "工具", "插件", "软件"]),
            ("商业/产品", "产品增长", ["商业", "产品", "用户", "增长", "转化", "销售", "品牌", "定价"]),
            ("运营/管理", "流程管理", ["运营", "管理", "组织", "流程", "项目", "团队", "效率"]),
            ("学习/认知", "学习方法", ["学习", "认知", "思维", "方法", "复盘", "记忆", "教育"]),
            ("健康/运动", "健康管理", ["健康", "运动", "健身", "训练", "睡眠", "饮食", "医学"]),
            ("财经/投资", "投资认知", ["财经", "投资", "股票", "基金", "资产", "现金流", "经济"]),
            ("法律/政策", "合规风险", ["法律", "政策", "合同", "合规", "监管", "版权"]),
            ("生活/效率", "生活效率", ["生活", "效率", "习惯", "收纳", "时间管理", "沟通"]),
            ("科技/科学", "科技趋势", ["科技", "科学", "研究", "论文", "实验", "工程"]),
            ("人物/案例", "案例拆解", ["案例", "人物", "故事", "访谈", "经历"]),
        ]
        if not category or not secondary:
            for candidate, candidate_secondary, keywords in category_rules:
                if any(keyword in lower_text for keyword in keywords):
                    if not category:
                        category = candidate
                    if not secondary and category == candidate:
                        secondary = candidate_secondary
                    break
        if not category:
            category = "其他"
        if not secondary:
            secondary = self._knowledge_default_secondary_category(category)

        return {"一级分类": category, "二级分类": secondary}

    def _knowledge_full_text(self, body: str, result: dict[str, Any], *, allow_body_fallback: bool = True) -> str:
        return self._knowledge_unified_text(body, result, allow_body_fallback=allow_body_fallback)

    def _knowledge_work_copy_text(self, body: str, result: dict[str, Any], *, allow_body_fallback: bool = True) -> str:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        caption = self._knowledge_caption_text(result, analysis)
        if caption:
            return MEDIA_TEXT_CLEANER.build_work_copy(caption)
        has_extracted_media = bool(
            result.get("transcript_path")
            or result.get("video_path")
            or result.get("image_paths")
            or self._knowledge_result_image_paths(result)
            or self._knowledge_image_ocr_text(result, analysis)
        )
        explicit = self._knowledge_clean_analysis_value(
            analysis.get("copy")
            or analysis.get("文案")
            or analysis.get("全部文案")
            or analysis.get("work_copy")
        )
        if explicit and not has_extracted_media:
            return MEDIA_TEXT_CLEANER.build_work_copy(explicit)
        if not allow_body_fallback:
            return ""
        return MEDIA_TEXT_CLEANER.build_work_copy(body)

    def _knowledge_full_content_text(self, result: dict[str, Any]) -> str:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        explicit = self._knowledge_clean_analysis_value(
            analysis.get("full_content")
            or analysis.get("全部内容")
            or analysis.get("full_script")
            or analysis.get("全部视频脚本")
            or analysis.get("script")
        )
        if explicit:
            return MEDIA_TEXT_CLEANER.clean_generated_copy(explicit)
        transcript = self._knowledge_read_text_file(str(result.get("transcript_path") or ""))
        image_ocr = self._knowledge_image_ocr_text(result, analysis)
        return MEDIA_TEXT_CLEANER.build_full_content(MediaCopyParts(transcript=transcript, image_ocr=image_ocr))

    def _knowledge_topic_fields(self, analysis: dict[str, Any], source_text: str) -> dict[str, str]:
        audience = self._knowledge_clean_analysis_value(
            analysis.get("目标人群") or analysis.get("target_audience") or analysis.get("audience")
        )
        pain_point = self._knowledge_clean_analysis_value(
            analysis.get("核心痛点") or analysis.get("pain_point") or analysis.get("user_pain") or analysis.get("pain")
        )
        lower_text = (source_text or "").lower()
        if not audience:
            audience_rules = [
                ("AI 小白", ["ai 小白", "ai小白", "小白", "入门"]),
                ("职场新人", ["职场新人", "新人"]),
                ("企业老板", ["企业老板", "老板"]),
                ("学生", ["学生", "校园"]),
                ("创作者", ["自媒体", "创作者", "博主"]),
            ]
            for candidate, keywords in audience_rules:
                if any(keyword in lower_text for keyword in keywords):
                    audience = candidate
                    break
        if not pain_point:
            pain_rules = [
                ("不会开始", ["不会开始", "不知道怎么开始"]),
                ("不会提问", ["不会提问", "提示词", "怎么问"]),
                ("标题同质化", ["同质化", "只要10个标题", "直接要标题"]),
                ("工具太多不知道怎么选", ["工具太多", "不知道选"]),
                ("担心学了没用", ["学了没用", "怕学了没用"]),
            ]
            for candidate, keywords in pain_rules:
                if any(keyword in lower_text for keyword in keywords):
                    pain_point = candidate
                    break
        return {
            key: value
            for key, value in {
                "目标人群": audience,
                "核心痛点": pain_point,
            }.items()
            if value
        }

    def _knowledge_questions(self, analysis: dict[str, Any], text: str) -> str:
        explicit = (
            analysis.get("questions")
            or analysis.get("key_questions")
            or analysis.get("问题提取")
            or analysis.get("核心问题")
        )
        explicit_text = self._knowledge_text_value(explicit)
        if explicit_text:
            return explicit_text

        candidates: list[str] = []
        for line in re.split(r"[\n。；;！!]", text):
            cleaned = line.strip(" -\t\r\n")
            if not cleaned:
                continue
            if "?" in cleaned or "？" in cleaned:
                candidates.append(cleaned.rstrip("?？") + "？")
                continue
            if any(keyword in cleaned for keyword in ["为什么", "怎么", "如何", "是什么", "能不能", "有没有", "哪些", "多少", "该不该"]):
                if len(cleaned) <= 80:
                    candidates.append(cleaned.rstrip("?？") + "？")
        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
            if len(deduped) >= 5:
                break
        return "\n".join(f"{idx}. {item}" for idx, item in enumerate(deduped, start=1))

    def _knowledge_extra_fields(self, body: str, result: dict[str, Any], *, allow_body_fallback: bool = True) -> dict[str, Any]:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        full_text = self._knowledge_full_text(body, result, allow_body_fallback=allow_body_fallback)
        work_copy = self._knowledge_work_copy_text(body, result, allow_body_fallback=allow_body_fallback)
        full_content = self._knowledge_full_content_text(result)
        summary = self._knowledge_text_value(analysis.get("summary"))
        breakdown = self._knowledge_text_value(analysis.get("breakdown"))
        action_plan = self._knowledge_clean_analysis_value(analysis.get("action_plan"))
        hooks = self._knowledge_text_value(analysis.get("hooks"))
        hidden_info = self._knowledge_clean_analysis_value(
            analysis.get("hidden_info") or analysis.get("隐形信息") or analysis.get("implicit_message") or analysis.get("潜台词")
        )
        visual_cues = self._knowledge_clean_analysis_value(
            analysis.get("visual_cues") or analysis.get("镜头/画面线索") or analysis.get("visual_info") or analysis.get("画面信息")
        )
        transferable_expression = self._knowledge_clean_analysis_value(
            analysis.get("transferable_expression") or analysis.get("可迁移表达") or analysis.get("expression_template")
        )
        tag_text = "、".join(self._knowledge_tags(analysis))
        source_text = "\n".join([body, work_copy, full_text, summary, breakdown, action_plan, hooks, tag_text])
        category_fields = self._knowledge_category_fields(analysis, source_text)
        topic_fields = self._knowledge_topic_fields(analysis, source_text)
        video_path = self._knowledge_result_video_path(result)
        image_paths = self._knowledge_result_image_paths(result)
        platform = self._knowledge_clean_analysis_value(analysis.get("platform")) or self._knowledge_platform_from_text(body)
        content_type = self._knowledge_content_type(body, result, platform)

        fields: dict[str, Any] = {
            "原链接": self._extract_first_url(body),
            "名称": self._knowledge_title(body, analysis),
            "内容类型": content_type,
            **category_fields,
            **topic_fields,
            "全部文案": work_copy,
            "全部内容": full_content,
            "隐形信息": hidden_info,
            "镜头/画面线索": visual_cues,
            "可迁移表达": transferable_expression,
            "摘要": summary,
            "问题提取": self._knowledge_questions(analysis, source_text),
            "价值判断": action_plan or summary,
            "应用建议": action_plan,
            "待验证问题": self._knowledge_clean_analysis_value(analysis.get("open_questions") or analysis.get("risks")),
            "关键词/标签": tag_text,
        }
        if platform:
            fields["来源平台"] = platform
        if video_path:
            fields["_attachment_fields"] = {"原文件": [video_path]}
        elif image_paths:
            fields["_attachment_fields"] = {"原文件": image_paths}
        return {key: value for key, value in fields.items() if value not in (None, "", [], {})}
