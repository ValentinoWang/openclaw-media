from __future__ import annotations

from ..models.task import TaskResult
from .tag_router_common import Message


class DeepMathCeoThinkingMixin:
    def handle_思考(self, message: Message) -> TaskResult:
        service = getattr(self, "deepmath_thinking_intake_service", None)
        if service is None:
            return TaskResult(ok=False, status="deepmath_intake_unavailable", reply="思考收件服务尚未就绪，请稍后重试。", task_id="")
        try:
            result = service.ingest(
                body=message.body,
                chat_type=message.chat_type,
                metadata=message.metadata,
                created_at=message.created_at,
            )
        except Exception as exc:
            return TaskResult(ok=False, status="deepmath_intake_blocked", reply=f"思考未收件：{exc}", task_id="")
        thought_id = str(result.get("thought_id") or "")
        if result.get("group_receipt_only") is True:
            return TaskResult(
                ok=True,
                status="deepmath_thinking_group_received",
                reply=f"已收件（思考ID：{thought_id}）。完整内容和后续审批仅在私聊处理。",
                task_id=thought_id,
                extra=result,
            )
        if result.get("status") == "pending_manual":
            return TaskResult(
                ok=False, status="pending_manual",
                reply=f"已保留原始证据（思考ID：{thought_id}），但结构化需要人工处理：{result.get('reason') or '证据不足或模型不可用'}",
                task_id=thought_id, extra=result,
            )
        if result.get("status") == "idempotent_replay":
            return TaskResult(ok=True, status="idempotent_replay", reply=f"这条思考已收件，不会重复创建（思考ID：{thought_id}）。", task_id=thought_id, extra=result)
        status = result.get("processing_status")
        counts = f"决策候选 {result.get('decision_count', 0)} 项，待审批动作 {result.get('approval_count', 0)} 项"
        note = "；未执行任务、提醒、通知或日历操作"
        return TaskResult(ok=True, status="deepmath_thinking_structured", reply=f"已收件并完成结构化（思考ID：{thought_id}，状态：{status}，{counts}{note}）。", task_id=thought_id, extra=result)
