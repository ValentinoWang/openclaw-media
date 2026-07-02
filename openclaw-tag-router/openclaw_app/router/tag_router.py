from __future__ import annotations

from .tag_router_common import *
from .activity_daily import ActivityDailyMixin
from .business_vlog import BusinessVlogMixin
from .creator_profile_router import CreatorProfilesMixin
from .vlog_inspiration import VlogInspirationMixin
from .document_tools import DocumentToolsMixin
from .knowledge_delegate import KnowledgeDelegateMixin
from .media_creation import MediaCreationMixin
from .media_knowledge_fields import MediaKnowledgeFieldsMixin
from .media_material_fields import MediaMaterialFieldsMixin
from .media_review import MediaReviewMixin
from .recreation import RecreationMixin
from .router_shared_helpers import RouterSharedHelpersMixin
from .selfmedia_cognition import SelfmediaCognitionMixin
from .social_archive import SocialArchiveMixin
from .style_polish import STYLE_POLISH_TAGS, StylePolishMixin
from .system_routes import SystemRoutesMixin
from .task_commands import TaskCommandMixin
from .transcription import TranscriptionMixin
from .transcription_formatters import TranscriptionFormattersMixin
from .transcription_storage import TranscriptionStorageMixin
from .weekly_self_model import WeeklySelfModelMixin
from .work_acceptance import WorkAcceptanceMixin
from .content_os_bridge import ContentOSBridgeMixin
from .content_os_renderers import ContentOSRenderersMixin
from .content_os_state import ContentOSStateMixin
from .content_os_utils import ContentOSUtilsMixin
from .development import DevelopmentMixin
from .deletion import DeletionMixin
from .unified_creation import (
    UNIFIED_CREATION_TABLE_URL,
    UNIFIED_CREATION_PARENT_NODE_TOKEN,
    UnifiedCreationMixin,
)

class TagRouter(
    UnifiedCreationMixin,
    ContentOSBridgeMixin,
    ContentOSStateMixin,
    ContentOSRenderersMixin,
    ContentOSUtilsMixin,
    RouterSharedHelpersMixin,
    DocumentToolsMixin,
    SelfmediaCognitionMixin,
    RecreationMixin,
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
    MediaCreationMixin,
    MediaKnowledgeFieldsMixin,
    MediaMaterialFieldsMixin,
    MediaReviewMixin,
    StylePolishMixin,
    ActivityDailyMixin,
    DevelopmentMixin,
    DeletionMixin,
    WorkAcceptanceMixin,
):
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
        schedule_service: ScheduleService,
        reminder_service: ReminderService,
        obsidian_daily_checklist_service: Any,
        vlog_storage_service: VlogStorageService,
        completion_guard: CompletionGuard,
    ):
        self.workspace_root = Path(workspace_root)
        self.source = source
        self.chat_type = chat_type
        self.timezone = timezone
        self.archive_service = archive_service
        self.rule_service = rule_service
        self.feishu_service = feishu_service
        self.content_flow_client = content_flow_client
        self.schedule_service = schedule_service
        self.reminder_service = reminder_service
        self.obsidian_daily_checklist_service = obsidian_daily_checklist_service
        self.vlog_storage_service = vlog_storage_service
        self.completion_guard = completion_guard

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
        if tag in UNIVERSAL_KNOWLEDGE_TAGS or tag in RESEARCH_KNOWLEDGE_TAGS:
            return self._delegate_to_knowledge_bot(message, thinking_level=self._knowledge_thinking_level(message))
        if tag == "说明":
            return self.handle_说明(message)
        if tag == "删除":
            return self.handle_删除(message)
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
        if tag == "创作-灵感":
            return self.handle_创作灵感(message)
        if tag in {"拆解-再创", "拆解-再创-简略", "拆解-再创-详细"}:
            return self.handle_再创作(message)
        if tag == "创作-拍摄执行":
            return self.handle_shooting_execution(message)
        if MATERIAL_CREATION_TAG_RE.match(tag):
            return self.handle_material_creation(message)
        if CREATION_TAG_RE.match(tag):
            return self.handle_creation(message)
        if tag == "灵感>vlog":
            return self.handle_灵感_vlog(message)
        if tag == "补充":
            return self.handle_补充(message)
        if tag == "待办-开发":
            return self.handle_待办_开发(message)
        if tag == "开发-完成":
            return self.handle_开发_完成(message)
        if tag == "开发-验证":
            return self.handle_开发_验证(message)

        if tag not in {"内容素材", "活动", "知识", "自媒体知识"}:
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

    def handle_去补丁(self, message: Message) -> TaskResult:
        return super().handle_去补丁(message)

    def handle_补充(self, message: Message) -> TaskResult:
        return super().handle_补充(message)

    def handle_selfmedia_cognition(self, message: Message) -> TaskResult:
        return super().handle_selfmedia_cognition(message)

    def handle_再创作(self, message: Message) -> TaskResult:
        return super().handle_再创作(message)

    def handle_社交(self, message: Message) -> TaskResult:
        return super().handle_社交(message)

    def handle_人脉(self, message: Message) -> TaskResult:
        return super().handle_人脉(message)

    def handle_id_business(self, message: Message) -> TaskResult:
        return super().handle_id_business(message)

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

    def handle_内容素材(self, message: Message) -> TaskResult:
        return super().handle_内容素材(message)

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

    def handle_创作灵感(self, message: Message) -> TaskResult:
        return super().handle_创作灵感(message)

    def handle_material_creation(self, message: Message) -> TaskResult:
        return super().handle_material_creation(message)

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

    def handle_开发_完成(self, message: Message) -> TaskResult:
        return super().handle_开发_完成(message)

    def handle_开发_验证(self, message: Message) -> TaskResult:
        return super().handle_开发_验证(message)

    def handle_整理(self, message: Message) -> TaskResult:
        return super().handle_整理(message)

    def handle_周记(self, message: Message) -> TaskResult:
        return super().handle_周记(message)

    def handle_删除(self, message: Message) -> TaskResult:
        return super().handle_删除(message)
