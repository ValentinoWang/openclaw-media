from __future__ import annotations

from selfmedia.style import StylePolishRequest, run_style_polish
from media_vault import MediaVaultError, require_tenant_id

from .tag_router_common import *


STYLE_POLISH_TAGS = {"润色", "网感", "文案优化", "改标题", "去AI味", "小红书文案", "抖音文案"}
FEISHU_DOC_REFERENCE_RE = re.compile(
    r"https?://[^\s<>\]\)）\"']*(?:feishu\.cn|larksuite\.com|larkoffice\.com)"
    r"[^\s<>\]\)）\"']*/(?:docx|wiki)(?:/|[?#]|$)",
    re.I,
)
FEISHU_DOC_METADATA_TYPE_KEYS = {"message_type", "obj_type", "object_type", "doc_type", "resource_type", "file_type"}
FEISHU_DOC_METADATA_TYPE_VALUES = {"docx", "wiki"}


class StylePolishMixin:
    def handle_style_polish(self, message: Message) -> TaskResult:
        if self._style_polish_has_feishu_doc_reference(message):
            return TaskResult(
                ok=False,
                status="style_polish_requires_modify",
                reply="【润色】检测到你提供的是飞书 Docx/Wiki 文档链接或回复文档。请改用【修改】处理已有文档；本次不会创建 style_polish_runs。",
                task_id="",
            )
        try:
            request = self._style_polish_request(message)
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
            result = run_style_polish(request, tenant_id=tenant_id)
        except MediaVaultError as exc:
            return TaskResult(
                ok=False,
                status="tenant_context_required",
                reply=str(exc),
                task_id="",
            )
        except Exception as exc:
            return TaskResult(
                ok=False,
                status="style_polish_failed",
                reply=(
                    "【润色】这次没有生成可用成稿。\n"
                    "code：style_polish_llm_failed\n"
                    "原因：写作模型返回的内容没有通过事实或格式校验。\n"
                    f"详情：{exc}\n"
                    "建议：请稍后重试；若持续失败，请把这条错误交给维护人员。"
                ),
                task_id="",
            )
        return TaskResult(
            ok=True,
            status="style_polish_done",
            reply=self._render_style_polish_reply(result.to_dict()),
            task_id=result.run_id,
            extra=result.to_dict(),
        )

    def _style_polish_request(self, message: Message) -> StylePolishRequest:
        body = str(message.body or "").strip()
        raw_text = (
            self._style_labeled_value(body, ("原文", "正文", "文案", "标题"))
            or self._style_body_without_fields(body)
        ).strip()
        tag = str(message.entry_tag or "").strip()
        platform = self._style_labeled_value(body, ("平台", "目标平台")) or self._style_platform_from_tag(tag)
        content_type = self._style_labeled_value(body, ("内容类型", "类型")) or self._style_content_type_from_tag(tag)
        goal = self._style_labeled_value(body, ("目标", "目的")) or self._style_goal_from_tag(tag)
        account = self._style_labeled_value(body, ("账号", "博主", "account"))
        must_keep = self._style_split_items(self._style_labeled_value(body, ("必须保留", "保留", "事实")))
        avoid = self._style_split_items(self._style_labeled_value(body, ("不能出现", "避免", "不要出现")))
        creation_id = self._style_labeled_value(body, ("creation_id", "创作记录ID"))
        material_id = self._style_labeled_value(body, ("material_id", "素材ID"))
        draft_id = self._style_labeled_value(body, ("draft_id", "草稿ID"))
        return StylePolishRequest(
            raw_text=raw_text,
            platform=platform,
            content_type=content_type or "general",
            goal=goal,
            account=account,
            must_keep=tuple(must_keep),
            avoid=tuple(avoid),
            creation_id=creation_id,
            material_id=material_id,
            draft_id=draft_id,
        )

    def _render_style_polish_reply(self, payload: dict[str, Any]) -> str:
        versions = payload.get("versions") or []
        recommended_name = str(payload.get("recommended_version") or "")
        recommended = next((item for item in versions if item.get("name") == recommended_name), versions[0] if versions else {})
        text = str(recommended.get("text") or "").strip()
        if not text:
            raise RuntimeError("StylePolish result has no recommended publishable text")
        return text

    @staticmethod
    def _style_labeled_value(text: str, labels: tuple[str, ...]) -> str:
        label_group = "|".join(re.escape(label) for label in labels)
        stop_labels = (
            "平台|目标平台|内容类型|类型|目标|目的|账号|博主|account|原文|正文|文案|标题|"
            "必须保留|保留|事实|不能出现|避免|不要出现|creation_id|创作记录ID|material_id|素材ID|draft_id|草稿ID"
        )
        pattern = re.compile(
            rf"(?:^|\n)\s*(?:{label_group})\s*[：:=]\s*(?P<value>.*?)(?=\n\s*(?:{stop_labels})\s*[：:=]|\Z)",
            re.S,
        )
        match = pattern.search(text or "")
        return str(match.group("value") or "").strip() if match else ""

    @classmethod
    def _style_body_without_fields(cls, text: str) -> str:
        lines = []
        for line in str(text or "").splitlines():
            if re.match(r"^\s*(平台|目标平台|内容类型|类型|目标|目的|账号|博主|account|必须保留|保留|事实|不能出现|避免|不要出现|creation_id|创作记录ID|material_id|素材ID|draft_id|草稿ID)\s*[：:=]", line):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    @staticmethod
    def _style_split_items(value: str) -> list[str]:
        return [item.strip() for item in re.split(r"[\n,，、;；]+", str(value or "")) if item.strip()]

    @classmethod
    def _style_polish_has_feishu_doc_reference(cls, message: Message) -> bool:
        for text in (message.body, message.raw_text):
            if FEISHU_DOC_REFERENCE_RE.search(str(text or "")):
                return True
        return cls._style_polish_metadata_has_feishu_doc_reference(message.metadata or {})

    @classmethod
    def _style_polish_metadata_has_feishu_doc_reference(cls, value: Any) -> bool:
        if isinstance(value, str):
            return bool(FEISHU_DOC_REFERENCE_RE.search(value))
        if isinstance(value, list):
            return any(cls._style_polish_metadata_has_feishu_doc_reference(item) for item in value)
        if not isinstance(value, dict):
            return False

        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text in FEISHU_DOC_METADATA_TYPE_KEYS and str(item or "").strip().lower() in FEISHU_DOC_METADATA_TYPE_VALUES:
                return True
            if cls._style_polish_metadata_has_feishu_doc_reference(item):
                return True
        return False

    @staticmethod
    def _style_platform_from_tag(tag: str) -> str:
        if tag == "小红书文案":
            return "小红书"
        if tag == "抖音文案":
            return "抖音"
        return ""

    @staticmethod
    def _style_content_type_from_tag(tag: str) -> str:
        if tag == "改标题":
            return "title"
        return "general"

    @staticmethod
    def _style_goal_from_tag(tag: str) -> str:
        if tag == "网感":
            return "强平台化优化，强调钩子、冲突、评论触发和传播压缩"
        if tag == "去AI味":
            return "降低书面腔、模板腔和 AI 腔"
        return "语言风格润色，强调准确、顺滑、像本人"
