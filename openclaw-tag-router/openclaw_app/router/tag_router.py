from __future__ import annotations

from .tag_router_common import *
from .activity_daily import ActivityDailyMixin
from .business_vlog import BusinessVlogMixin
from .commercial_delivery import CommercialDeliveryMixin
from .creator_profile_router import CreatorProfilesMixin
from .vlog_inspiration import VlogInspirationMixin
from .content_os_change_router import ContentOSChangeRouterMixin
from .document_tools import DocumentToolsMixin
from .hotlist import HotlistMixin
from .knowledge_delegate import KnowledgeDelegateMixin
from .media_creation import MediaCreationMixin
from .media_growth import MEDIA_GROWTH_TAGS, MediaGrowthMixin
from .media_knowledge_fields import MediaKnowledgeFieldsMixin
from .media_review import MediaReviewMixin
from .router_shared_helpers import RouterSharedHelpersMixin
from .selfmedia_cognition import SelfmediaCognitionMixin
from .social_archive import SocialArchiveMixin
from .style_polish import STYLE_POLISH_TAGS, StylePolishMixin
from .system_routes import SystemRoutesMixin
from .task_commands import TaskCommandMixin
from .transcription import TranscriptionMixin
from .transcription_formatters import TranscriptionFormattersMixin
from .transcription_storage import TranscriptionStorageMixin
from .wardrobe import WardrobeMixin
from .weekly_self_model import WeeklySelfModelMixin
from .work_acceptance import WorkAcceptanceMixin
from .content_os_bridge import ContentOSBridgeMixin
from .content_os_renderers import ContentOSRenderersMixin
from .content_os_state import ContentOSStateMixin
from .content_os_utils import ContentOSUtilsMixin
from .development import DevelopmentMixin
from .deletion import DeletionMixin
from .deepmath_ceo_thinking import DeepMathCeoThinkingMixin
from .unified_creation import (
    UNIFIED_CREATION_TABLE_URL,
    UNIFIED_CREATION_PARENT_NODE_TOKEN,
    UnifiedCreationMixin,
)


class TagRouter(
    DeepMathCeoThinkingMixin,
    UnifiedCreationMixin,
    ContentOSBridgeMixin,
    ContentOSStateMixin,
    ContentOSRenderersMixin,
    ContentOSUtilsMixin,
    RouterSharedHelpersMixin,
    ContentOSChangeRouterMixin,
    DocumentToolsMixin,
    HotlistMixin,
    SelfmediaCognitionMixin,
    KnowledgeDelegateMixin,
    CreatorProfilesMixin,
    BusinessVlogMixin,
    VlogInspirationMixin,
    SocialArchiveMixin,
    SystemRoutesMixin,
    WeeklySelfModelMixin,
    TaskCommandMixin,
    TranscriptionMixin,
    TranscriptionFormattersMixin,
    TranscriptionStorageMixin,
    CommercialDeliveryMixin,
    MediaGrowthMixin,
    MediaCreationMixin,
    MediaKnowledgeFieldsMixin,
    MediaReviewMixin,
    StylePolishMixin,
    ActivityDailyMixin,
    DevelopmentMixin,
    DeletionMixin,
    WardrobeMixin,
    WorkAcceptanceMixin,
):
    def handle_思考(self, message: Message) -> TaskResult:
        """Keep registry introspection on TagRouter while routing to the canonical mixin."""
        return super().handle_思考(message)

    def __init__(
        self,
        workspace_root: str,
        source: str,
        chat_type: str,
        timezone: str,
        archive_service: ArchiveService,
        rule_service: RuleService,
        feishu_service: FeishuService,
        content_flow_client: ContentFlowClient,
        reminder_service: ReminderService,
        obsidian_daily_checklist_service: Any,
        obsidian_development_checklist_service: Any,
        vlog_storage_service: VlogStorageService,
        completion_guard: CompletionGuard,
        daily_journal_settings: dict[str, Any] | None = None,
        guidance_plan_service: Any | None = None,
        tenant_owned_resources: Any | None = None,
        deepmath_thinking_intake_service: Any | None = None,
    ):
        self.workspace_root = Path(workspace_root)
        self.source = source
        self.chat_type = chat_type
        self.timezone = timezone
        self.archive_service = archive_service
        self.rule_service = rule_service
        self.feishu_service = feishu_service
        self.content_flow_client = content_flow_client
        self.reminder_service = reminder_service
        self.obsidian_daily_checklist_service = obsidian_daily_checklist_service
        self.obsidian_development_checklist_service = obsidian_development_checklist_service
        self.vlog_storage_service = vlog_storage_service
        self.completion_guard = completion_guard
        self.daily_journal_settings = daily_journal_settings or {}
        self.guidance_plan_service = guidance_plan_service
        self.tenant_owned_resources = tenant_owned_resources
        self.deepmath_thinking_intake_service = deepmath_thinking_intake_service

    @staticmethod
    def _is_deepmath_account(value: Any) -> bool:
        normalized = str(value or "").strip().lower().replace("_", "-")
        if normalized.startswith("feishu-"):
            normalized = normalized[len("feishu-"):]
        return normalized == "deepmath"

    def route(
        self,
        tag: str,
        body: str,
        created_at: datetime | None = None,
        *,
        source: str | None = None,
        chat_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskResult:
        account_id = str((metadata or {}).get("account_id") or "").strip()
        is_deepmath = self._is_deepmath_account(account_id)
        if is_deepmath and tag not in {"思考", "说明"}:
            return TaskResult(ok=False, status="deepmath_label_blocked", reply="DeepMath 当前仅开放【思考】和【说明】入口；普通咨询请直接发送自然语言。", task_id="")
        if tag == "思考" and not is_deepmath:
            return TaskResult(ok=False, status="deepmath_account_required", reply="【思考】仅属于 DeepMath AI4Math Bot。", task_id="")
        if tag not in TAG_LABELS:
            return TaskResult(ok=False, status="unsupported_tag", reply="未识别这个标签。请发送【说明】查看当前支持的标签。", task_id="")
        message_metadata = dict(metadata or {})
        created_at = created_at or now_in_tz(self.timezone)
        message = Message(
            entry_tag=tag,
            raw_text=f"【{tag}】{body}",
            body=body,
            source=source or self.source,
            chat_type=chat_type or self.chat_type,
            created_at=created_at,
            metadata=message_metadata,
        )
        blocked_theory_tags = self._blocked_social_theory_tags(tag, body)
        if blocked_theory_tags:
            tags = "、".join(f"【{theory_tag}】" for theory_tag in blocked_theory_tags)
            return TaskResult(
                ok=False,
                status="blocked_social_theory_scope",
                reply=f"已阻止调用：{tags} 只能写在 `【社交】` 正文里使用。",
                task_id="",
            )
        if tag in RESEARCH_KNOWLEDGE_TAGS:
            if self._media_growth_should_handle(message):
                return self.handle_media_growth(message)
            return TaskResult(ok=False, status="unsupported_tag", reply="未识别这个标签。请发送【说明】查看当前支持的标签。", task_id="")
        if tag in UNIVERSAL_KNOWLEDGE_TAGS:
            return self._delegate_to_knowledge_bot(message, thinking_level=self._knowledge_thinking_level(message))
        if tag == "说明":
            return self.handle_说明(message)
        if tag == "删除":
            return self.handle_删除(message)
        if tag == "思考":
            return self.handle_思考(message)
        intake_prompt = self._media_intake_prompt(message)
        if intake_prompt:
            return TaskResult(
                ok=True,
                status="media_intake_prompt",
                reply=intake_prompt,
                task_id="",
            )
        if tag == "拆解":
            return self.handle_拆解(message)
        if tag == "商务>ID":
            return self.handle_id_business(message)
        if tag == "商单交付":
            return self.handle_商单交付(message)
        if tag == "博主":
            return self.handle_博主(message)
        if tag == "博主-入库":
            return self.handle_博主_入库(message)
        if tag == "自媒体-认知":
            return self.handle_selfmedia_cognition(message)
        if tag == "创作检查":
            return self.handle_创作检查(message)
        if tag == "作品验收":
            return self.handle_作品验收(message)
        if tag in STYLE_POLISH_TAGS:
            return self.handle_style_polish(message)
        if tag in MEDIA_GROWTH_TAGS and self._media_growth_should_handle(message):
            return self.handle_media_growth(message)
        if tag == "热榜":
            return self.handle_热榜(message)
        if tag == "创作-拍摄执行":
            return self.handle_shooting_execution(message)
        if CREATION_TAG_RE.match(tag):
            return self.handle_creation(message)
        if tag == "灵感>vlog":
            return self.handle_灵感_vlog(message)
        if tag == "修改":
            return self.handle_修改(message)
        if tag == "待办-开发":
            return self.handle_待办_开发(message)
        if tag == "开发-完成":
            return self.handle_开发_完成(message)
        if tag == "开发-验证":
            return self.handle_开发_验证(message)
        if tag == "衣橱":
            return self.handle_衣物_入库(message)
        if tag == "穿搭":
            return self.handle_穿搭(message)

        if tag not in {"活动", "自媒体知识"}:
            self.archive_service.save_inbox(message)

        if tag == "转写-文字":
            return self.handle_转写_文字(message)
        handler = getattr(self, f"handle_{tag}", None)
        if handler:
            return handler(message)
        if tag in GENERIC_TAGS:
            return self.handle_generic(message)
        if tag in SYSTEM_TAGS:
            return getattr(self, f"handle_{tag}")(message)
        return self.handle_generic(message)

    def handle_generic(self, message: Message) -> TaskResult:
        return super().handle_generic(message)

    def handle_创作检查(self, message: Message) -> TaskResult:
        return super().handle_创作检查(message)

    def handle_作品验收(self, message: Message) -> TaskResult:
        return super().handle_作品验收(message)

    def handle_style_polish(self, message: Message) -> TaskResult:
        return super().handle_style_polish(message)

    def handle_media_growth(self, message: Message) -> TaskResult:
        return super().handle_media_growth(message)

    def handle_media_growth_review(self, message: Message) -> TaskResult:
        return super().handle_media_growth_review(message)

    def handle_热榜(self, message: Message) -> TaskResult:
        return super().handle_热榜(message)

    def handle_修改(self, message: Message) -> TaskResult:
        return super().handle_修改(message)

    def handle_selfmedia_cognition(self, message: Message) -> TaskResult:
        return super().handle_selfmedia_cognition(message)

    def handle_社交(self, message: Message) -> TaskResult:
        return super().handle_社交(message)

    def handle_人脉(self, message: Message) -> TaskResult:
        return super().handle_人脉(message)

    def handle_id_business(self, message: Message) -> TaskResult:
        return super().handle_id_business(message)

    def handle_商单交付(self, message: Message) -> TaskResult:
        return super().handle_商单交付(message)

    def handle_博主(self, message: Message) -> TaskResult:
        return super().handle_博主(message)

    def handle_博主_入库(self, message: Message) -> TaskResult:
        return super().handle_博主_入库(message)

    def handle_灵感(self, message: Message) -> TaskResult:
        return super().handle_灵感(message)

    def handle_灵感_vlog(self, message: Message) -> TaskResult:
        return super().handle_灵感_vlog(message)

    def handle_说明(self, message: Message) -> TaskResult:
        return super().handle_说明(message)

    def handle_最近(self, message: Message) -> TaskResult:
        return super().handle_最近(message)

    def handle_同步(self, message: Message) -> TaskResult:
        return super().handle_同步(message)

    def handle_状态(self, message: Message) -> TaskResult:
        return super().handle_状态(message)

    def handle_待办_开发(self, message: Message) -> TaskResult:
        return super().handle_待办_开发(message)

    def handle_自媒体知识(self, message: Message) -> TaskResult:
        return super().handle_自媒体知识(message)

    def handle_转写(self, message: Message) -> TaskResult:
        return super().handle_转写(message)

    def handle_转写_文字(self, message: Message) -> TaskResult:
        return super().handle_转写_文字(message)

    def handle_拆解(self, message: Message) -> TaskResult:
        return super().handle_拆解(message)

    def handle_creation(self, message: Message) -> TaskResult:
        return super().handle_creation(message)

    def handle_shooting_execution(self, message: Message) -> TaskResult:
        return super().handle_shooting_execution(message)

    def handle_创作咨询(self, message: Message) -> TaskResult:
        return super().handle_创作咨询(message)

    def handle_数据复盘(self, message: Message) -> TaskResult:
        return super().handle_数据复盘(message)

    def handle_活动(self, message: Message) -> TaskResult:
        return super().handle_活动(message)

    def handle_日程(self, message: Message) -> TaskResult:
        return super().handle_日程(message)

    def handle_待办(self, message: Message) -> TaskResult:
        return super().handle_待办(message)

    def handle_今日(self, message: Message) -> TaskResult:
        return super().handle_今日(message)

    def handle_日记(self, message: Message) -> TaskResult:
        return super().handle_日记(message)

    def handle_开发_完成(self, message: Message) -> TaskResult:
        return super().handle_开发_完成(message)

    def handle_开发_验证(self, message: Message) -> TaskResult:
        return super().handle_开发_验证(message)

    def handle_整理(self, message: Message) -> TaskResult:
        return super().handle_整理(message)

    def handle_周记(self, message: Message) -> TaskResult:
        return super().handle_周记(message)

    def handle_衣物_入库(self, message: Message) -> TaskResult:
        return super().handle_衣物_入库(message)

    def handle_穿搭(self, message: Message) -> TaskResult:
        return super().handle_穿搭(message)

    def handle_删除(self, message: Message) -> TaskResult:
        return super().handle_删除(message)
