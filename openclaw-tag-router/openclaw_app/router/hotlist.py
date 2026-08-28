from __future__ import annotations

from selfmedia.hotlist import HotlistService, HotlistValidationError
from selfmedia.hotlist.service import SHANGHAI_TZ
from selfmedia.context.media_context import record_hotlist_memory
from media_vault import MediaVaultError, require_tenant_id

from .tag_router_common import *


_HOTLIST_BLOCKED_SOURCE_LABELS = {
    "brave_web_search": "公开候选搜索",
    "candidate_discovery": "公开候选搜索",
    "platform_share_page": "抖音作品页",
    "platform_note_page": "小红书作品页",
}


class HotlistMixin:
    def _hotlist_service(self) -> HotlistService:
        service = getattr(self, "hotlist_service", None)
        if isinstance(service, HotlistService) or callable(getattr(service, "run", None)):
            return service
        service = HotlistService()
        self.hotlist_service = service
        return service

    def handle_热榜(self, message: Message) -> TaskResult:
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        try:
            result = self._hotlist_service().run(message.body)
        except HotlistValidationError as exc:
            return TaskResult(
                ok=False,
                status="invalid_hotlist_request",
                reply=f"热榜参数有误：{exc}\n\n请发送空标签 `【热榜】` 查看填写模板。",
                task_id="",
                extra={"persisted": False, "error_code": "HOTLIST_INVALID_REQUEST"},
            )

        request = result.request
        scope = (
            f"平台：{request.platform}｜关键词：{request.keyword}｜时间：{request.time_window.label}"
            f"｜排序：{request.sort_label}｜数量：{request.limit}"
        )
        source = result.source_status
        discovery = source.get("candidate_discovery") if isinstance(source, dict) else {}
        lines = ["【热榜】", scope]

        if result.status == "pending_manual":
            lines.extend(
                [
                    "状态：需要人工处理",
                    f"阻塞来源：{_hotlist_blocked_source_label(result.blocked_source)}",
                    f"原因：{result.reason}",
                    "说明：本次未生成排名，也未补写点赞数或发布时间。",
                ]
            )
            if request.platform == "小红书":
                lines.append("处理建议：更新小红书登录态后重试，或提供带有效 xsec_token 的作品来源。")
            elif discovery.get("error_code") == "HOTLIST_SEARCH_RATE_LIMITED":
                lines.append("处理建议：公开候选搜索源限流，稍后重试。")
            else:
                lines.append("处理建议：恢复可读的平台来源后重试。")
            return TaskResult(
                ok=False,
                status="pending_manual",
                reply="\n".join(lines),
                task_id=result.trace_id,
                extra={"hotlist": result.as_dict(), "persisted": False},
            )

        lines.append("口径：本次可读取候选中的排序，不代表平台官方全站榜。")
        lines.append(
            "来源：公开搜索索引发现候选；平台作品页核验标题、作者、点赞数和发布时间。"
        )
        lines.append(
            f"核验情况：候选 {result.discovered_count} 条，详情核验 {result.verified_count} 条，入榜 {len(result.items)} 条。"
        )

        if not result.items:
            lines.extend(
                [
                    "结果：没有同时满足关键词、时间和标签条件的已核验作品。",
                    f"原因：{result.reason}",
                ]
            )
            return TaskResult(
                ok=True,
                status="hotlist_no_verified_results",
                reply="\n".join(lines),
                task_id=result.trace_id,
                extra={"hotlist": result.as_dict(), "persisted": False},
            )

        lines.append("")
        for index, item in enumerate(result.items, start=1):
            published_at = item.published_at.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")
            tags = "、".join(f"#{tag}" for tag in item.tags) or "无可核验标签"
            lines.extend(
                [
                    f"{index}. {item.title}",
                    f"作者：{item.author}｜点赞：{item.like_count:,}｜发布：{published_at}",
                    f"标签：{tags}",
                    f"链接：{item.url}",
                    "核验状态：已核验",
                    "",
                ]
            )
        try:
            memory_result = record_hotlist_memory(result, tenant_id=tenant_id)
        except OSError:
            return TaskResult(
                ok=False,
                status="hotlist_memory_persistence_failed",
                reply="热榜结果已获取，但本地创作上下文保存失败，请稍后重试。",
                task_id=result.trace_id,
                extra={"hotlist": result.as_dict(), "persisted": False},
            )
        if not memory_result.get("persisted"):
            return TaskResult(
                ok=False,
                status="hotlist_memory_persistence_failed",
                reply="热榜结果未能保存到本地创作上下文，请稍后重试。",
                task_id=result.trace_id,
                extra={"hotlist": result.as_dict(), "persisted": False},
            )
        return TaskResult(
            ok=True,
            status="hotlist_ranked",
            reply="\n".join(lines).rstrip(),
            task_id=result.trace_id,
            extra={"hotlist": result.as_dict(), "persisted": True, "hotlist_memory": memory_result},
        )


def _hotlist_blocked_source_label(value: object) -> str:
    return _HOTLIST_BLOCKED_SOURCE_LABELS.get(str(value or "").strip(), "外部平台来源")
