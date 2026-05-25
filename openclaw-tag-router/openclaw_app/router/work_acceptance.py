from __future__ import annotations

import json
import re
from typing import Any

from ..models.message import Message
from ..models.task import TaskResult
from .media_intake_guides import render_media_intake_prompt
from .tag_capabilities import TAG_CAPABILITIES


TAG_CAPABILITY_MAP = {capability.label: capability for capability in TAG_CAPABILITIES}


SELFMEDIA_CHECKLIST_DOCS: tuple[dict[str, Any], ...] = (
    {
        "title": "自媒体认知｜所有赛道｜作品发布检查清单",
        "url": "https://tcnwueberajc.feishu.cn/wiki/H0jiwnslmiewLakXxK9ccT04n8d",
        "summary": "用于发布前 30 秒检查：主旨、受众、停留、完整、复盘、阻力、决定。",
        "keywords": ("作品", "发布", "发作品", "发出", "检查", "checklist", "清单", "成熟", "不够精", "不完美", "完美", "阻力", "草稿"),
    },
    {
        "title": "自媒体认知｜所有赛道｜防止懈怠",
        "url": "https://tcnwueberajc.feishu.cn/wiki/So9JwDgU8iUFQ9kQzN7cvcwsn3g",
        "summary": "用于处理拖延、懈怠、启动成本过高、总想等作品更完美再发的问题。",
        "keywords": ("懈怠", "拖延", "启动", "最低动作", "停摆", "不想发", "不敢发", "发布阻力", "随手发", "不够好"),
    },
)


class WorkAcceptanceMixin:
    def handle_作品验收(self, message: Message) -> TaskResult:
        body = str(message.body or "").strip()
        if not body:
            return TaskResult(ok=False, status="empty_work_acceptance", reply=render_media_intake_prompt("作品验收", TAG_CAPABILITY_MAP.get("作品验收")), task_id="")

        result = self._work_acceptance_review(message)
        items = self._normalize_work_acceptance_items(result.get("items"))
        if not items:
            items = self._fallback_work_acceptance_items(body)
            if not result.get("summary"):
                result["summary"] = "未获得稳定的语义验收结果，已按可解析文本做保守检查。"

        pass_count = sum(1 for item in items if item["judgment"] == "满足")
        fail_count = sum(1 for item in items if item["judgment"] == "不满足")
        uncertain_count = sum(1 for item in items if item["judgment"] == "不确定")
        verdict = self._normalize_work_acceptance_verdict(str(result.get("verdict") or ""), pass_count, fail_count, uncertain_count)

        lines = [
            f"作品验收结果：{verdict}",
            f"统计：满足 {pass_count} / 不满足 {fail_count} / 不确定 {uncertain_count}",
        ]
        summary = str(result.get("summary") or "").strip()
        if summary:
            lines.extend(["", f"总结：{summary}"])
        lines.append("")
        lines.append("逐项验收：")
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. 【{item['judgment']}】{item['requirement']}")
            if item["evidence"]:
                lines.append(f"   证据：{item['evidence']}")
            if item["gap"]:
                lines.append(f"   缺口：{item['gap']}")
            if item["fix"]:
                lines.append(f"   修改建议：{item['fix']}")

        release_advice = str(result.get("release_advice") or "").strip()
        next_actions = self._normalize_work_acceptance_actions(result.get("next_actions"))
        if release_advice:
            lines.extend(["", f"发布判断：{release_advice}"])
        if next_actions:
            lines.append("")
            lines.append("下一步：")
            lines.extend(f"- {action}" for action in next_actions)
        if result.get("status") == "pending_manual":
            lines.extend(["", f"注意：{result.get('reason') or 'OpenClaw 语义验收不可用，已使用保守本地检查。'}"])

        content_os_status = self._maybe_apply_content_os_work_acceptance(message, verdict, result, items)
        if content_os_status.get("reply"):
            lines.extend(["", content_os_status["reply"]])

        return TaskResult(
            ok=True,
            status="selfmedia_work_acceptance_replied",
            reply="\n".join(lines),
            task_id="",
            extra={
                "workflow": "selfmedia_work_acceptance",
                "verdict": verdict,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "uncertain_count": uncertain_count,
                "content_os_status": content_os_status,
            },
        )

    def _work_acceptance_review(self, message: Message) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 OpenClaw JSON 调用"}
        prompt = (
            "你是 Media bot 的作品验收编辑。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把用户提供的作品内容逐项对照创作要求，判断每一项是否满足。\n"
            "判定规则：\n"
            "1. 只根据输入文本和最近对话上下文判断，不要编造作品中没有的证据。\n"
            "2. 每条要求只能判为“满足”“不满足”“不确定”三者之一。\n"
            "3. 作品内容明确覆盖并能指出证据时，判为“满足”。\n"
            "4. 作品内容明确违背、缺失或与要求冲突时，判为“不满足”。\n"
            "5. 缺少作品正文、缺少创作要求、要求依赖图片/视频但没有可见证据、或语义证据不足时，判为“不确定”。\n"
            "6. 修改建议要可执行，避免空泛表述。\n"
            "输出字段：status、verdict、summary、items、release_advice、next_actions。\n"
            "items 数组元素字段固定为 requirement、judgment、evidence、gap、fix。"
        )
        user_content = json.dumps(
            {
                "tag": message.entry_tag,
                "raw_text": message.body,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            env.setdefault("TRANSCRIPTION_POSTPROCESS_PROVIDER", "openclaw")
            result = self.content_flow_client._call_postprocess_json(prompt, user_content, env, "作品验收")
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc)}
        return result if isinstance(result, dict) else {"status": "pending_manual", "reason": "OpenClaw 返回非 JSON object"}

    @staticmethod
    def _normalize_work_acceptance_items(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        for raw in value:
            if not isinstance(raw, dict):
                continue
            requirement = str(raw.get("requirement") or raw.get("要求") or "").strip()
            if not requirement:
                continue
            judgment = str(raw.get("judgment") or raw.get("判定") or "").strip()
            if judgment not in {"满足", "不满足", "不确定"}:
                judgment = "不确定"
            items.append(
                {
                    "requirement": requirement,
                    "judgment": judgment,
                    "evidence": str(raw.get("evidence") or raw.get("证据") or "").strip(),
                    "gap": str(raw.get("gap") or raw.get("缺口") or "").strip(),
                    "fix": str(raw.get("fix") or raw.get("修改建议") or "").strip(),
                }
            )
        return items[:40]

    @staticmethod
    def _normalize_work_acceptance_actions(value: Any) -> list[str]:
        if isinstance(value, str):
            candidates = re.split(r"[\n；;]+", value)
        elif isinstance(value, list):
            candidates = [str(item) for item in value]
        else:
            return []
        actions = []
        for item in candidates:
            clean = re.sub(r"^\s*[-*0-9.、\[\] ]+", "", item).strip()
            if clean:
                actions.append(clean)
        return actions[:8]

    @staticmethod
    def _normalize_work_acceptance_verdict(verdict: str, pass_count: int, fail_count: int, uncertain_count: int) -> str:
        if verdict in {"通过", "需修改", "信息不足"}:
            return verdict
        if fail_count:
            return "需修改"
        if uncertain_count:
            return "信息不足"
        if pass_count:
            return "通过"
        return "信息不足"

    @classmethod
    def _fallback_work_acceptance_items(cls, body: str) -> list[dict[str, str]]:
        requirement_text, work_text = cls._split_work_acceptance_text(body)
        requirements = cls._extract_requirement_lines(requirement_text)
        if not requirements:
            return [
                {
                    "requirement": "提供可逐项检查的创作要求",
                    "judgment": "不确定",
                    "evidence": "",
                    "gap": "没有识别到明确的创作要求。",
                    "fix": "按“创作要求：...”和“作品内容：...”补充后重新发送。",
                }
            ]
        items = []
        for requirement in requirements[:40]:
            hit = cls._requirement_keyword_hit(requirement, work_text)
            items.append(
                {
                    "requirement": requirement,
                    "judgment": "满足" if hit else "不确定",
                    "evidence": hit,
                    "gap": "" if hit else "本地检查未找到足够明确的作品证据。",
                    "fix": "" if hit else "补充对应正文、标题、封面文案、分镜或截图证据；或把该要求改成可检查的客观标准。",
                }
            )
        return items

    @staticmethod
    def _split_work_acceptance_text(body: str) -> tuple[str, str]:
        text = body.strip()
        req_match = re.search(r"(?:创作要求|验收要求|品牌要求|Brief|brief|要求|标准|checklist)\s*[：:]\s*", text)
        work_match = re.search(r"(?:作品内容|作品正文|作品|稿件|文案|脚本|标题|封面文案)\s*[：:]\s*", text)
        if req_match and work_match and req_match.start() < work_match.start():
            return text[req_match.end():work_match.start()].strip(), text[work_match.end():].strip()
        if work_match and req_match and work_match.start() < req_match.start():
            return text[req_match.end():].strip(), text[work_match.end():req_match.start()].strip()
        return text, text

    @staticmethod
    def _extract_requirement_lines(text: str) -> list[str]:
        lines = []
        for raw_line in text.splitlines():
            clean = re.sub(r"^\s*(?:[-*•]|\d+[.、)]|[（(]?\d+[）)])\s*", "", raw_line).strip()
            clean = re.sub(r"^\s*(?:要求|标准|checklist)\s*[：:]\s*", "", clean, flags=re.I).strip()
            if not clean or len(clean) < 3:
                continue
            if re.search(r"(作品内容|作品正文|稿件|文案|脚本|标题|封面文案)\s*[：:]", clean):
                break
            lines.append(clean)
        if len(lines) <= 1 and "；" in text:
            lines = [part.strip() for part in re.split(r"[；;]", text) if len(part.strip()) >= 3]
        return lines

    @staticmethod
    def _requirement_keyword_hit(requirement: str, work_text: str) -> str:
        if not work_text.strip():
            return ""
        explicit_terms = re.findall(r"(?:出现|包含|带上|带有|必须有|要有|需有|需要有)\s*([#\w\u4e00-\u9fff-]{2,24})", requirement)
        for term in explicit_terms:
            term = re.sub(r"(?:这个|这些|明确|相关|对应|元素|内容|文案|标题)$", "", term).strip()
            index = work_text.find(term)
            if term and index >= 0:
                start = max(0, index - 18)
                end = min(len(work_text), index + len(term) + 28)
                return work_text[start:end].replace("\n", " ").strip()
        if "痛点" in requirement:
            match = re.search(r"(你是不是|是否|有没有|总觉得|担心|害怕|很慢|太慢|困难|问题|痛点).{0,40}", work_text)
            if match:
                return match.group(0).replace("\n", " ").strip()
        if "评论" in requirement or "互动" in requirement:
            match = re.search(r".{0,20}(评论区|评论|留言|告诉我|你觉得|你最想).{0,40}", work_text)
            if match:
                return match.group(0).replace("\n", " ").strip()
        keywords = []
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9#]{2,}", requirement):
            if token in {"必须", "需要", "要求", "不能", "不要", "一个", "包含", "体现", "突出", "文案", "作品", "标题"}:
                continue
            if len(token) >= 2:
                keywords.append(token)
            if len(token) >= 5:
                keywords.extend(token[start:end] for start in range(0, min(4, len(token) - 1)) for end in range(start + 2, min(len(token), start + 8) + 1))
        for keyword in keywords[:12]:
            index = work_text.find(keyword)
            if index >= 0:
                start = max(0, index - 18)
                end = min(len(work_text), index + len(keyword) + 28)
                return work_text[start:end].replace("\n", " ").strip()
        return ""

    @staticmethod
    def _matching_selfmedia_checklists(body: str) -> list[dict[str, Any]]:
        text = body.lower()
        matched: list[dict[str, Any]] = []
        for doc in SELFMEDIA_CHECKLIST_DOCS:
            keywords = tuple(str(item).lower() for item in doc.get("keywords", ()))
            if not text or any(keyword and keyword in text for keyword in keywords):
                matched.append(doc)
        if matched:
            return matched
        return [SELFMEDIA_CHECKLIST_DOCS[0]]
