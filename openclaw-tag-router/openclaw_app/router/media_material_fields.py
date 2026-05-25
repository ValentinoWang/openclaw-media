from __future__ import annotations

from .tag_router_common import *


class MediaMaterialFieldsMixin:
    def _format_content_material_record(self, body: str, result: dict[str, Any]) -> str:
        summary = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        breakdown = summary.get("breakdown")
        if isinstance(breakdown, str) and breakdown.strip():
            return breakdown.strip()
        if isinstance(breakdown, list) and breakdown:
            return "\n".join(f"{idx}. {item}" for idx, item in enumerate(breakdown, start=1) if str(item).strip())
        parts = []
        if result.get("media_dir"):
            parts.append(f"- 素材目录：{result.get('media_dir')}")
        if summary.get("summary"):
            parts.append("- 摘要：" + yaml.safe_dump(summary.get("summary"), allow_unicode=True, sort_keys=False).strip())
        if summary.get("hooks"):
            parts.append("- 钩子：" + yaml.safe_dump(summary.get("hooks"), allow_unicode=True, sort_keys=False).strip())
        if summary.get("emotion"):
            parts.append("- 情绪：" + yaml.safe_dump(summary.get("emotion"), allow_unicode=True, sort_keys=False).strip())
        if summary.get("score"):
            parts.append("- 推荐指数：" + yaml.safe_dump(summary.get("score"), allow_unicode=True, sort_keys=False).strip())
        if not parts:
            parts.append("待补充爆点拆解。")
        return "\n".join(part for part in parts if part is not None).strip()

    def _content_material_title(self, body: str, analysis: dict[str, Any]) -> str:
        for key in ("title", "标题"):
            value = analysis.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:80]
        caption = analysis.get("caption")
        if isinstance(caption, str) and caption.strip() and not caption.strip().startswith("http"):
            first_line = caption.strip().splitlines()[0]
            return first_line[:80]
        return body[:80] or "内容素材"

    def _content_material_extra_fields(self, body: str, result: dict[str, Any], tag_rule: dict[str, Any]) -> dict[str, Any]:
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        text_parts = [
            body,
            str(analysis.get("caption") or ""),
            yaml.safe_dump(analysis.get("tags") or [], allow_unicode=True, sort_keys=False),
            yaml.safe_dump(analysis.get("summary") or "", allow_unicode=True, sort_keys=False),
        ]
        text = "\n".join(text_parts).lower()
        platform = analysis.get("platform")
        fields: dict[str, Any] = {}
        fields["素材来源类型"] = self._content_material_source_type(body, result)
        fields["素材状态"] = "已拆解" if analysis else "原始信号"
        if isinstance(platform, str) and platform.strip():
            fields["平台"] = platform.strip()
        hot_fields = analysis.get("hot_fields") or analysis.get("热榜字段")
        if isinstance(hot_fields, str) and hot_fields.strip():
            fields["热榜字段"] = hot_fields.strip()
        elif isinstance(hot_fields, list) and hot_fields:
            fields["热榜字段"] = "\n".join(str(item).strip() for item in hot_fields if str(item).strip())
        else:
            caption = analysis.get("caption")
            if isinstance(caption, str) and caption.strip():
                fields["热榜字段"] = caption.strip()
        tags = analysis.get("tags")
        if isinstance(tags, list) and tags:
            tag_text = "、".join(str(item).strip() for item in tags if str(item).strip())
            if tag_text and "标签：" not in fields.get("热榜字段", ""):
                fields["热榜字段"] = "\n".join(part for part in [fields.get("热榜字段", ""), f"标签：{tag_text}"] if part)
        stats_parts = []
        for label, key in [("点赞", "like_count"), ("评论", "comment_count"), ("分享", "share_count"), ("收藏", "collect_count")]:
            value = analysis.get(key)
            if value is not None:
                stats_parts.append(f"{label} {value}")
        if analysis.get("video_id"):
            stats_parts.append(f"视频 ID：{analysis.get('video_id')}")
        if stats_parts:
            fields["核心数据"] = "；".join(stats_parts)
        action_plan = self._knowledge_clean_analysis_value(analysis.get("action_plan"))
        if action_plan:
            fields["爆点迁移"] = action_plan
        reusable_angle = self._content_material_reusable_angle(analysis, text)
        if reusable_angle:
            fields["可复用角度"] = reusable_angle
        creation_scene = self._content_material_creation_scene(analysis, text)
        if creation_scene:
            fields["适合创作场景"] = creation_scene
        attachment_paths = self._content_material_attachment_paths(str(result.get("media_dir") or ""))
        if attachment_paths:
            fields["_attachment_paths"] = attachment_paths
        ai_category = analysis.get("content_category") or analysis.get("赛道/标签") or analysis.get("category")
        if isinstance(ai_category, str) and ai_category.strip():
            fields["赛道/标签"] = ai_category.strip()
            return fields
        configured_rules = tag_rule.get("category_rules") if isinstance(tag_rule, dict) else None
        category_rules = configured_rules if isinstance(configured_rules, list) and configured_rules else [
            {"name": "运动-记录", "keywords": ["运动", "健身", "跑步", "训练", "骑行", "篮球", "足球", "瑜伽"]},
            {"name": "AI工具-创作者提效", "keywords": ["ai", "openclaw", "codex", "skill", "工具", "提示词", "自动化", "效率"]},
            {"name": "内容运营-爆款拆解", "keywords": ["小红书运营", "爆款", "创作者", "涨粉", "选题", "文案", "拆解"]},
            {"name": "教育-学习成长", "keywords": ["高考", "学习", "校园", "考研", "备考", "课程", "学生"]},
            {"name": "本地生活-探店美食", "keywords": ["探店", "美食", "餐厅", "咖啡", "打卡", "门店"]},
            {"name": "旅行-记录", "keywords": ["旅行", "旅拍", "城市", "景点", "攻略", "出行"]},
            {"name": "职场生活-身份反差", "keywords": ["毕业", "应届", "打工", "工厂", "车床", "职场", "上班", "厂仔", "身份反差"]},
            {"name": "情绪共鸣-青春回忆", "keywords": ["青春", "回忆", "高三", "毕业季", "遗憾", "成长"]},
        ]
        for rule in category_rules:
            if isinstance(rule, dict):
                keywords = rule.get("keywords") or []
                category = rule.get("name") or rule.get("category")
            elif isinstance(rule, (list, tuple)) and len(rule) == 2:
                category, keywords = rule
            else:
                continue
            if not category or not isinstance(keywords, list):
                continue
            if any(keyword.lower() in text for keyword in keywords):
                fields["赛道/标签"] = category
                break
        return fields

    def _content_material_source_type(self, body: str, result: dict[str, Any]) -> str:
        text = (body or "").lower()
        platform = ""
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        if isinstance(analysis, dict):
            platform = str(analysis.get("platform") or "").strip()
        if "xhslink.com" in text or "xiaohongshu.com" in text or platform == "小红书":
            return "外部平台素材-小红书"
        if "douyin.com" in text or platform == "抖音":
            return "外部平台素材-抖音"
        if contains_link(body):
            return "外部平台素材"
        return "手动录入素材"

    def _content_material_reusable_angle(self, analysis: dict[str, Any], text: str) -> str:
        explicit = self._knowledge_clean_analysis_value(
            analysis.get("content_angle")
            or analysis.get("内容角度")
            or analysis.get("reusable_angle")
            or analysis.get("可复用角度")
        )
        if explicit:
            return explicit
        rules = [
            ("误区纠偏", ["误区", "不要只", "别只", "错误"]),
            ("清单教程", ["清单", "步骤", "sop", "方法"]),
            ("案例复盘", ["案例", "复盘", "经历"]),
            ("问题解答", ["为什么", "怎么", "如何", "问答"]),
            ("反常识观点", ["反常识", "其实", "不是", "而是"]),
        ]
        for label, keywords in rules:
            if any(keyword in text for keyword in keywords):
                return label
        return ""

    def _content_material_creation_scene(self, analysis: dict[str, Any], text: str) -> str:
        audience = self._knowledge_clean_analysis_value(analysis.get("target_audience") or analysis.get("目标人群") or analysis.get("audience"))
        pain = self._knowledge_clean_analysis_value(analysis.get("pain_point") or analysis.get("核心痛点") or analysis.get("pain"))
        if audience and pain:
            return f"写给{audience}，解决“{pain}”"
        if audience:
            return f"写给{audience}"
        if pain:
            return f"解决“{pain}”"
        if "自媒体" in text or "选题" in text:
            return "自媒体选题/内容创作"
        return ""

    def _content_material_attachment_paths(self, media_dir: str) -> list[str]:
        if not media_dir:
            return []
        root = Path(media_dir)
        if not root.exists():
            return []
        image_dir = root / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        video_path = root / "video.mp4"
        clip_dir = root / "clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip_path = clip_dir / "first-5s.mp4"
        if video_path.exists():
            if not clip_path.exists() or clip_path.stat().st_size <= 0:
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(video_path),
                            "-t",
                            "5",
                            "-c",
                            "copy",
                            str(clip_path),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=30,
                        check=False,
                    )
                except Exception:
                    pass
            if clip_path.exists() and clip_path.stat().st_size > 0:
                return [str(clip_path)]
        expected = [image_dir / f"frame-{seconds:03d}s.jpg" for seconds in range(5)]
        if video_path.exists():
            for seconds, path in enumerate(expected):
                if path.exists() and path.stat().st_size > 0:
                    continue
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-ss",
                            str(seconds),
                            "-i",
                            str(video_path),
                            "-frames:v",
                            "1",
                            "-q:v",
                            "2",
                            str(path),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=20,
                        check=False,
                    )
                except Exception:
                    pass
        images = []
        preferred_names = [
            "cover.jpg",
            "frame-000s.jpg",
            "frame-001s.jpg",
            "frame-002s.jpg",
            "frame-003s.jpg",
            "frame-004s.jpg",
        ]
        for name in preferred_names:
            path = image_dir / name
            if path.is_file() and path.stat().st_size > 0:
                images.append(path)
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            images.extend(image_dir.glob(pattern))
        selected = []
        seen = set()
        for path in images:
            if not path.is_file() or path.stat().st_size <= 0 or path in seen:
                continue
            seen.add(path)
            selected.append(str(path))
        return selected[:5]
