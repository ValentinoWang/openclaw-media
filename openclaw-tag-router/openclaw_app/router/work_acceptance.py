from __future__ import annotations

import json
import re
from typing import Any

from common.social_runtime import now_iso as _now_iso
from media_vault import MediaVault, MediaVaultError, require_tenant_id
from selfmedia.business.work_acceptance import WorkAcceptanceError, WorkAcceptanceWriteback

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
            reason = str(result.get("reason") or "OpenClaw 语义验收未返回可用逐项结果").strip()
            return TaskResult(
                ok=False,
                status="selfmedia_work_acceptance_pending_manual",
                reply=(
                    "作品验收未完成：没有获得可用的语义逐项验收结果。\n"
                    f"原因：{reason}\n\n"
                    "请补充作品正文、创作要求、可见证据，或稍后重试。"
                ),
                task_id="",
                extra={"workflow": "selfmedia_work_acceptance", "reason": reason},
            )

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
            lines.extend(["", f"注意：{result.get('reason') or 'OpenClaw 语义验收结果需要人工复核。'}"])

        creation_run_status = self._persist_creation_run_acceptance(
            message,
            verdict=verdict,
            result=result,
            items=items,
            pass_count=pass_count,
            fail_count=fail_count,
            uncertain_count=uncertain_count,
        )
        if creation_run_status.get("reply"):
            lines.extend(["", str(creation_run_status["reply"])])

        commercial_acceptance_status = self._maybe_write_commercial_acceptance(
            message,
            creation_run_status=creation_run_status,
            verdict=verdict,
            result=result,
            items=items,
        )
        if commercial_acceptance_status.get("reply"):
            lines.extend(["", str(commercial_acceptance_status["reply"])])

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
                "creation_run_status": creation_run_status,
                "commercial_acceptance_status": commercial_acceptance_status,
                "content_os_status": content_os_status,
            },
        )

    @staticmethod
    def _creation_run_id_from_message(message: Message) -> str:
        match = re.search(r"(?:创作记录ID|作品档案)\s*[=:：]\s*([A-Za-z0-9_.-]+)", str(message.raw_text or ""))
        return match.group(1).strip() if match else ""

    def _persist_creation_run_acceptance(
        self,
        message: Message,
        *,
        verdict: str,
        result: dict[str, Any],
        items: list[dict[str, str]],
        pass_count: int,
        fail_count: int,
        uncertain_count: int,
    ) -> dict[str, Any]:
        creation_run_id = self._creation_run_id_from_message(message)
        if not creation_run_id:
            return {
                "status": "creation_record_id_required",
                "reply": "验收结果尚未关联创作记录：请补充 `创作记录ID=...` 后重新验收，系统会把逐项结论写入该创作档案。",
            }
        try:
            tenant_id = require_tenant_id((message.metadata or {}).get("tenant_id"))
        except MediaVaultError as exc:
            return {
                "status": "tenant_context_required",
                "creation_run_id": creation_run_id,
                "reply": f"验收结果未写入创作记录：{exc}",
            }
        vault = MediaVault(tenant_id=tenant_id)
        run_dir = vault.creation_run_dir(creation_run_id)
        if not run_dir.is_dir():
            return {
                "status": "creation_run_not_found",
                "creation_run_id": creation_run_id,
                "reply": f"验收结果未写入：未找到创作记录 {creation_run_id}。请确认创作记录ID属于当前租户。",
            }
        accepted_at = _now_iso()
        artifact = vault.write_json_artifact(
            run_dir,
            "acceptance.json",
            {
                "creation_run_id": creation_run_id,
                "verdict": verdict,
                "counts": {
                    "passed": pass_count,
                    "failed": fail_count,
                    "uncertain": uncertain_count,
                },
                "items": items,
                "summary": str(result.get("summary") or "").strip(),
                "release_advice": str(result.get("release_advice") or "").strip(),
                "next_actions": self._normalize_work_acceptance_actions(result.get("next_actions")),
                "accepted_at": accepted_at,
            },
            owner_type="CreationRun",
            owner_id=creation_run_id,
            artifact_type="work_acceptance",
            artifact_id=f"work_acceptance_{creation_run_id}",
        )
        return {
            "status": "persisted",
            "creation_run_id": creation_run_id,
            "artifact_uri": artifact["uri"],
            "reply": f"验收证据已写入创作记录：{creation_run_id}",
        }

    def _maybe_write_commercial_acceptance(
        self,
        message: Message,
        *,
        creation_run_status: dict[str, Any],
        verdict: str,
        result: dict[str, Any],
        items: list[dict[str, str]],
    ) -> dict[str, Any]:
        loop_id, loop_id_source = self._commercial_acceptance_loop_id(message)
        if not loop_id:
            return {"status": "not_requested"}
        if creation_run_status.get("status") != "persisted":
            return {
                "status": "pending_manual",
                "commercial_loop_id": loop_id,
                "reply": "商单验收未写入：创作记录验收尚未持久化。",
            }

        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        external_verified = metadata.get("commercial_acceptance_external_verified") is True
        evidence_uri = self._commercial_acceptance_evidence_uri(message)
        try:
            writeback = WorkAcceptanceWriteback(
                tenant_id=require_tenant_id(metadata.get("tenant_id")),
                opportunity_id=loop_id,
            )
            written = writeback.record(
                creation_run_id=str(creation_run_status["creation_run_id"]),
                verdict=verdict,
                items=items,
                summary=str(result.get("summary") or "").strip(),
                evidence_uri=evidence_uri,
                external_verified=external_verified,
            )
        except WorkAcceptanceError as exc:
            if str(exc) == "work acceptance requires a confirmed publication":
                return {
                    "status": "awaiting_publication_confirmation",
                    "commercial_loop_id": loop_id,
                    "loop_id_source": loop_id_source,
                    "reply": "商单验收待回写：请先完成受认证的发布核验；当前未写入商单验收记录。",
                }
            return {
                "status": "pending_manual",
                "commercial_loop_id": loop_id,
                "loop_id_source": loop_id_source,
                "reply": "商单验收未写入：请人工核对交付编号和验收记录后重试。",
            }
        except MediaVaultError:
            return {
                "status": "pending_manual",
                "commercial_loop_id": loop_id,
                "loop_id_source": loop_id_source,
                "reply": "商单验收未写入：缺少有效租户上下文。",
            }

        status = str(written.get("status") or "pending_manual")
        response = {
            "status": status,
            "commercial_loop_id": loop_id,
            "loop_id_source": loop_id_source,
            "artifact_uri": str(written.get("artifact_uri") or ""),
            "commercial_loop": written.get("commercial_loop"),
        }
        if status == "confirmed":
            response["reply"] = "商单验收已写入，并已确认商业生命周期。"
        else:
            response["reply"] = "商单验收证据已关联，仍待外部核验，未推进商业生命周期。"
        return response

    @staticmethod
    def _commercial_acceptance_loop_id(message: Message) -> tuple[str, str]:
        raw_text = str(message.raw_text or "")
        for source, labels in (
            ("commercial_delivery_id", ("商单交付ID", "交付编号")),
            ("business_opportunity_fallback", ("商务机会ID", "商机ID")),
        ):
            value = WorkAcceptanceMixin._commercial_acceptance_labeled_line(raw_text, labels)
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value):
                return value, source
        return "", ""

    @staticmethod
    def _commercial_acceptance_evidence_uri(message: Message) -> str:
        return WorkAcceptanceMixin._commercial_acceptance_labeled_line(
            str(message.raw_text or ""),
            ("验收证据链接", "验收链接", "发布链接", "作品链接"),
        )

    @staticmethod
    def _commercial_acceptance_labeled_line(raw_text: str, labels: tuple[str, ...]) -> str:
        label_pattern = "|".join(re.escape(label) for label in labels)
        for line in str(raw_text or "").replace("\r\n", "\n").splitlines():
            match = re.match(rf"\s*(?:{label_pattern})\s*[：:=]\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip()
        return ""

    def _work_acceptance_review(self, message: Message) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 OpenClaw JSON 调用"}
        prompt = (
            "你是 Media bot 的作品验收编辑。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：把用户提供的作品内容逐项对照创作要求，判断每一项是否满足。\n"
            "判定规则：\n"
            "1. 只根据输入文本和最近对话上下文判断。\n"
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
            result = self.content_flow_client._call_postprocess_json(prompt, user_content, "作品验收")
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
