from __future__ import annotations

from ..services.document_edit_contract import (
    DocumentEditContractViolation,
    DocumentEditIntentOperation,
    DocumentEditPatchPlan,
    DocumentEditWorkingCopy,
    load_document_edit_op_whitelist,
)
from .tag_router_common import *
from ..services.tenant_execution_context import current_session_tenant_id


FEISHU_DOCUMENT_TOKEN_LENGTH = 27


class DocumentToolsMixin:
    def _emit_document_edit_progress_event(
        self,
        stage: str,
        *,
        source: dict[str, Any] | None = None,
        error_code: str = "",
        reason: str = "",
        manual_actions: list[dict[str, Any]] | None = None,
        applied_operations: list[dict[str, Any]] | None = None,
    ) -> None:
        progress_file = str(os.getenv("OPENCLAW_TAG_ROUTER_PROGRESS_FILE") or "").strip()
        if not progress_file:
            return
        facts: dict[str, Any] = {}
        if isinstance(source, dict):
            patchable_blocks = source.get("patchable_blocks") or []
            protected_blocks = source.get("protected_blocks") or []
            protected_table_shapes = source.get("protected_table_shapes") or []
            facts = {
                "document_id": str(source.get("document_id") or ""),
                "document_family": str(source.get("document_family") or "generic_docx"),
                "source_hash": str(source.get("source_block_hash") or source.get("source_hash") or ""),
                "patchable_block_count": len(patchable_blocks) if isinstance(patchable_blocks, list) else 0,
                "protected_block_count": len(protected_blocks) if isinstance(protected_blocks, list) else len(source.get("protected_block_ids") or []),
                "protected_table_count": len(protected_table_shapes) if isinstance(protected_table_shapes, list) else 0,
                "truncated": bool(source.get("truncated")),
            }
        event = {
            "schema": "openclaw.document_edit.progress_event.v1",
            "workflow": "document_edit",
            "event_id": f"document_edit:{stage}:{time.time_ns()}",
            "stage": stage,
            "known_facts": facts,
            "error_code": error_code,
            "reason": reason,
            "manual_action_count": len(manual_actions or []),
            "applied_operation_count": len(applied_operations or []),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            Path(progress_file).parent.mkdir(parents=True, exist_ok=True)
            with Path(progress_file).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            return

    def handle_修改(self, message: Message) -> TaskResult:
        content_os_handler = getattr(self, "_maybe_handle_content_os_change_request", None)
        if callable(content_os_handler):
            content_os_result = content_os_handler(message)
            if content_os_result is not None:
                return content_os_result
        edit_request = self._build_document_edit_request(message)
        doc_url = edit_request.get("target_doc_url", "")
        if not doc_url:
            return TaskResult(
                ok=False,
                status="missing_target_document",
                reply="请在正文写明飞书文档链接，或回复目标飞书文档后发送【修改】。",
                task_id="",
            )
        if not edit_request.get("edit_requirements"):
            return TaskResult(
                ok=False,
                status="missing_edit_requirements",
                reply="请在【修改】后写明修改要求；例如：修改要求：把标题改得更像小红书真实体验。",
                task_id="",
                feishu_doc=doc_url,
            )
        source = self._prepare_document_edit_patch_source(doc_url, message)
        if not source.get("ok"):
            return TaskResult(
                ok=False,
                status=str(source.get("status") or "document_edit_source_unavailable"),
                reply=self._document_edit_public_preflight_failure(source),
                task_id="",
                feishu_doc=doc_url,
                extra={"workflow": "document_edit", "target_doc": doc_url, "source": source},
            )
        original_text = str(source.get("text") or "").strip()
        if not original_text:
            return TaskResult(ok=False, status="read_document_failed", reply="读取文档失败：正文为空，已停止写入。", task_id="", feishu_doc=doc_url)
        resolve_document_reference = getattr(self.feishu_service, "resolve_document_reference", None)
        if callable(resolve_document_reference) and not source.get("document_id"):
            try:
                source.update(resolve_document_reference(doc_url))
            except Exception:
                pass
        source = self._enrich_document_edit_family_contract(source)
        if source.get("document_family") == "shooting_execution":
            return self._handle_shooting_execution_backwash(message, edit_request, source)
        read_bitable_record = getattr(self.feishu_service, "read_bitable_record", None)
        if source.get("document_family") != "commercial_delivery":
            commercial_probe = self._resolve_document_edit_commercial_delivery_record(source, read_bitable_record)
            if commercial_probe.get("ok"):
                source.update(
                    {
                        "document_family": "commercial_delivery",
                        "producer_capability": "commercial_delivery_draft",
                        "family_contract_id": "document_edit.commercial_delivery.COM01",
                        "document_family_provenance": "COM01_unique_record_link",
                        "commercial_delivery_record": commercial_probe,
                    }
                )
            elif int(commercial_probe.get("match_count") or 0) > 0:
                source.update(
                    {
                        "document_family": "commercial_delivery",
                        "producer_capability": "commercial_delivery_draft",
                        "family_contract_id": "document_edit.commercial_delivery.COM01",
                        "document_family_provenance": "COM01_non_unique_record_link",
                    }
                )
        source_block_snapshot = source.get("source_block_snapshot") or source.get("root_blocks") or []
        source_block_hash = str(source.get("source_block_hash") or source.get("source_hash") or "")
        preflight_status = str(source.get("preflight_status") or "passed")
        unsupported_block_types = source.get("unsupported_block_types") or []
        document_family = str(source.get("document_family") or "generic_docx")
        producer_capability = str(source.get("producer_capability") or "")
        family_contract_id = str(source.get("family_contract_id") or "document_edit.generic_docx")
        commercial_delivery_record_unresolved = False
        self._emit_document_edit_progress_event("source_loaded", source=source)
        if document_family == "commercial_delivery":
            commercial_record = source.get("commercial_delivery_record") if isinstance(source.get("commercial_delivery_record"), dict) else {}
            if not commercial_record.get("ok"):
                commercial_record = self._resolve_document_edit_commercial_delivery_record(source, read_bitable_record)
            if not commercial_record.get("ok"):
                commercial_delivery_record_unresolved = True
                response_envelope = self._document_edit_response_envelope(
                    "planning_failed",
                    source=source,
                    error_code="COMMERCIAL_DELIVERY_RECORD_UNRESOLVED",
                    reason=str(commercial_record.get("reply") or "商单交付文档无法唯一映射 COM01 记录，已停止写入。"),
                    manual_actions=[
                        {
                            "reason": "commercial_delivery_record_unresolved",
                            "instructions": "先确认该飞书文档在 COM01 商单交付表中有且仅有一条关联记录，再重新发送【修改】。",
                            "requested_op": "resolve_commercial_delivery_record",
                        }
                    ],
                    applied_operations=[],
                )
                self._emit_document_edit_progress_event(
                    "error",
                    source=source,
                    error_code="COMMERCIAL_DELIVERY_RECORD_UNRESOLVED",
                    reason=str(commercial_record.get("reply") or "商单交付文档无法唯一映射 COM01 记录，已停止写入。"),
                    manual_actions=response_envelope.get("manual_actions") or [],
                    applied_operations=[],
                )
                return TaskResult(
                    ok=False,
                    status="commercial_delivery_record_unresolved",
                    reply=self._render_document_edit_response_envelope(response_envelope),
                    task_id="",
                    feishu_doc=doc_url,
                    extra={
                        "workflow": "document_edit",
                        "target_doc": doc_url,
                        "source_block_hash": source_block_hash,
                        "snapshot_path": source.get("snapshot_path"),
                        "preflight_status": preflight_status,
                        "unsupported_block_types": unsupported_block_types,
                        "document_family": document_family,
                        "producer_capability": producer_capability,
                        "family_contract_id": family_contract_id,
                        "document_family_provenance": str(source.get("document_family_provenance") or ""),
                        "commercial_delivery_record_unresolved": commercial_delivery_record_unresolved,
                        "response_envelope": response_envelope,
                    },
                )
            source["commercial_delivery_record"] = commercial_record
            source["producer_capability"] = "commercial_delivery_draft"
            source["family_contract_id"] = "document_edit.commercial_delivery.COM01"
            source["document_family_provenance"] = "COM01_unique_record_link"
            producer_capability = "commercial_delivery_draft"
            family_contract_id = "document_edit.commercial_delivery.COM01"

        response_envelope = self._document_edit_response_envelope(
            "planning",
            source=source,
            error_code="",
            reason="",
            manual_actions=[],
            applied_operations=[],
        )
        self._emit_document_edit_progress_event("planning", source=source)
        plan_result = self._build_document_edit_patch_plan(source, edit_request, message)
        if plan_result.get("status") == "pending_manual":
            error_code = str(plan_result.get("error_code") or "DOCUMENT_EDIT_PATCH_PLAN_PENDING_MANUAL")
            response_envelope = self._document_edit_response_envelope(
                "planning_failed",
                source=source,
                error_code=error_code,
                reason=str(plan_result.get("reason") or "LLM 未返回可用 patch plan"),
                manual_actions=plan_result.get("manual_actions") or [],
                applied_operations=[],
            )
            self._emit_document_edit_progress_event(
                "error",
                source=source,
                error_code=error_code,
                reason=str(plan_result.get("reason") or "LLM 未返回可用 patch plan"),
                manual_actions=plan_result.get("manual_actions") or [],
                applied_operations=[],
            )
            return TaskResult(
                ok=False,
                status="document_edit_pending_manual",
                reply=self._render_document_edit_response_envelope(response_envelope),
                task_id="",
                feishu_doc=doc_url,
                extra={"workflow": "document_edit", "target_doc": doc_url, "error_code": error_code, "response_envelope": response_envelope},
            )
        schema = self._validate_document_edit_patch_plan(plan_result)
        if not schema.get("ok"):
            response_envelope = self._document_edit_response_envelope(
                "planning_failed",
                source=source,
                error_code="DOCUMENT_EDIT_PATCH_SCHEMA_INVALID",
                reason=str(schema.get("reply") or "文档修改失败：LLM 返回的 patch plan 不满足合同，已停止写入。"),
                manual_actions=plan_result.get("manual_actions") or [],
                applied_operations=[],
            )
            self._emit_document_edit_progress_event(
                "error",
                source=source,
                error_code="DOCUMENT_EDIT_PATCH_SCHEMA_INVALID",
                reason=str(schema.get("reply") or "文档修改失败：LLM 返回的 patch plan 不满足合同，已停止写入。"),
                manual_actions=plan_result.get("manual_actions") or [],
                applied_operations=[],
            )
            return TaskResult(
                ok=False,
                status=str(schema.get("status") or "document_edit_patch_schema_invalid"),
                reply=self._render_document_edit_response_envelope(response_envelope),
                task_id="",
                feishu_doc=doc_url,
                extra={"workflow": "document_edit", "target_doc": doc_url, "schema": schema, "response_envelope": response_envelope},
            )
        plan_payload = schema["plan"]
        plan_payload = self._document_edit_drop_noop_operations(plan_payload)
        if not plan_payload.get("operations"):
            manual_actions = list(plan_payload.get("manual_actions") or [])
            if manual_actions:
                response_envelope = self._document_edit_response_envelope(
                    "manual_required",
                    source=source,
                    error_code="DOCUMENT_EDIT_ONLY_MANUAL_ACTIONS_REMAIN",
                    reason="可执行文本块已是目标状态或没有可安全自动写入项；剩余图片、附件、表格或结构调整需人工处理。",
                    manual_actions=manual_actions,
                    applied_operations=[],
                )
                self._emit_document_edit_progress_event(
                    "error",
                    source=source,
                    error_code="DOCUMENT_EDIT_ONLY_MANUAL_ACTIONS_REMAIN",
                    reason="可执行文本块已是目标状态或没有可安全自动写入项；剩余图片、附件、表格或结构调整需人工处理。",
                    manual_actions=manual_actions,
                    applied_operations=[],
                )
                return TaskResult(
                    ok=False,
                    status="document_edit_pending_manual",
                    reply=self._render_document_edit_response_envelope(response_envelope) + self._document_edit_snapshot_hint(source),
                    task_id="",
                    feishu_doc=doc_url,
                    extra={
                        "workflow": "document_edit",
                        "target_doc": doc_url,
                        "source": source,
                        "patch_plan": plan_payload,
                        "noop_operations": plan_payload.get("noop_operations") or [],
                        "response_envelope": response_envelope,
                    },
                )
            response_envelope = self._document_edit_response_envelope(
                "final",
                source=source,
                error_code="",
                reason="可执行文本块已是目标状态，无需写入。",
                manual_actions=[],
                applied_operations=[],
            )
            self._emit_document_edit_progress_event("final", source=source)
            return TaskResult(
                ok=True,
                status="document_edit_noop",
                reply=self._render_document_edit_response_envelope(response_envelope),
                task_id="",
                feishu_doc=doc_url,
                extra={"workflow": "document_edit", "target_doc": doc_url, "source": source, "patch_plan": plan_payload, "response_envelope": response_envelope},
            )
        self._emit_document_edit_progress_event("applying_patch", source=source)
        fs = self._apply_document_edit_patch_plan(plan_payload)
        if not fs.get("ok", True):
            response_envelope = self._document_edit_response_envelope(
                "apply_failed",
                source=source,
                error_code=str(fs.get("status") or "DOCUMENT_EDIT_PATCH_APPLY_FAILED"),
                reason=str(fs.get("reply") or fs.get("error") or "分块文本 patch 执行失败。"),
                manual_actions=plan_payload.get("manual_actions") or [],
                applied_operations=fs.get("applied_operations") or [],
            )
            self._emit_document_edit_progress_event(
                "error",
                source=source,
                error_code=str(fs.get("status") or "DOCUMENT_EDIT_PATCH_APPLY_FAILED"),
                reason=str(fs.get("reply") or fs.get("error") or "分块文本 patch 执行失败。"),
                manual_actions=plan_payload.get("manual_actions") or [],
                applied_operations=fs.get("applied_operations") or [],
            )
            return TaskResult(
                ok=False,
                status=str(fs.get("status") or "document_edit_patch_apply_failed"),
                reply=self._render_document_edit_response_envelope(response_envelope) + self._document_edit_snapshot_hint(source),
                task_id="",
                feishu_doc=doc_url,
                extra={"workflow": "document_edit", "target_doc": doc_url, "source": source, "patch_plan": plan_payload, "apply": fs, "response_envelope": response_envelope},
            )
        self._emit_document_edit_progress_event("readback", source=source, applied_operations=fs.get("applied_operations") or [])
        readback = self._verify_document_edit_patch_readback(plan_payload, fs)
        readback_status = str(readback.get("status") or ("ok" if readback.get("ok") else "failed"))
        if not readback.get("ok"):
            response_envelope = self._document_edit_response_envelope(
                "readback_failed",
                source=source,
                error_code=str(readback.get("status") or "DOCUMENT_EDIT_PATCH_READBACK_FAILED"),
                reason=str(readback.get("reply") or readback.get("error") or "文档 patch 读回校验失败。"),
                manual_actions=fs.get("manual_actions") or plan_payload.get("manual_actions") or [],
                applied_operations=fs.get("applied_operations") or [],
            )
            self._emit_document_edit_progress_event(
                "error",
                source=source,
                error_code=str(readback.get("status") or "DOCUMENT_EDIT_PATCH_READBACK_FAILED"),
                reason=str(readback.get("reply") or readback.get("error") or "文档 patch 读回校验失败。"),
                manual_actions=fs.get("manual_actions") or plan_payload.get("manual_actions") or [],
                applied_operations=fs.get("applied_operations") or [],
            )
            return TaskResult(
                ok=False,
                status=str(readback.get("status") or "document_edit_patch_readback_failed"),
                reply=self._render_document_edit_response_envelope(response_envelope) + self._document_edit_snapshot_hint(source),
                task_id="",
                feishu_doc=doc_url,
                extra={"workflow": "document_edit", "target_doc": doc_url, "source": source, "patch_plan": plan_payload, "apply": fs, "readback": readback, "response_envelope": response_envelope},
            )
        commercial_sync: dict[str, Any] = {}
        readback_text = str(readback.get("text") or "")
        if document_family == "commercial_delivery":
            commercial_sync = self._sync_document_edit_commercial_delivery_record(source, plan_result, readback_text, readback)
            source["commercial_delivery_sync"] = commercial_sync
            if not commercial_sync.get("ok"):
                response_envelope = self._document_edit_response_envelope(
                    "readback_failed",
                    source=source,
                    error_code=str(commercial_sync.get("status") or "COMMERCIAL_DELIVERY_RECORD_SYNC_FAILED"),
                    reason=str(commercial_sync.get("reply") or commercial_sync.get("error") or "商单交付 COM01 记录同步失败。"),
                    manual_actions=fs.get("manual_actions") or plan_payload.get("manual_actions") or [],
                    applied_operations=fs.get("applied_operations") or [],
                )
                self._emit_document_edit_progress_event(
                    "error",
                    source=source,
                    error_code=str(commercial_sync.get("status") or "COMMERCIAL_DELIVERY_RECORD_SYNC_FAILED"),
                    reason=str(commercial_sync.get("reply") or commercial_sync.get("error") or "商单交付 COM01 记录同步失败。"),
                    manual_actions=fs.get("manual_actions") or plan_payload.get("manual_actions") or [],
                    applied_operations=fs.get("applied_operations") or [],
                )
                return TaskResult(
                    ok=False,
                    status=str(commercial_sync.get("status") or "commercial_delivery_record_sync_failed"),
                    reply=self._render_document_edit_response_envelope(response_envelope) + self._document_edit_snapshot_hint(source),
                    task_id="",
                    feishu_doc=doc_url,
                    extra={
                        "workflow": "document_edit",
                        "target_doc": doc_url,
                        "source": source,
                        "apply": fs,
                        "readback": readback,
                        "COM01": source.get("commercial_delivery_record"),
                        "commercial_delivery_sync": commercial_sync,
                        "readback_status": readback_status,
                        "response_envelope": response_envelope,
                    },
                )
        family_readback = self._document_edit_family_readback(source, readback)
        if not family_readback.get("ok"):
            response_envelope = self._document_edit_response_envelope(
                "readback_failed",
                source=source,
                error_code=str(family_readback.get("status") or "DOCUMENT_EDIT_FAMILY_READBACK_FAILED"),
                reason=str(family_readback.get("reply") or family_readback.get("error") or "文档家族读回校验失败。"),
                manual_actions=fs.get("manual_actions") or plan_payload.get("manual_actions") or [],
                applied_operations=fs.get("applied_operations") or [],
            )
            self._emit_document_edit_progress_event(
                "error",
                source=source,
                error_code=str(family_readback.get("status") or "DOCUMENT_EDIT_FAMILY_READBACK_FAILED"),
                reason=str(family_readback.get("reply") or family_readback.get("error") or "文档家族读回校验失败。"),
                manual_actions=fs.get("manual_actions") or plan_payload.get("manual_actions") or [],
                applied_operations=fs.get("applied_operations") or [],
            )
            return TaskResult(
                ok=False,
                status=str(family_readback.get("status") or "document_edit_family_readback_failed"),
                reply=self._render_document_edit_response_envelope(response_envelope) + self._document_edit_snapshot_hint(source),
                task_id="",
                feishu_doc=doc_url,
                extra={
                    "workflow": "document_edit",
                    "target_doc": doc_url,
                    "source": source,
                    "apply": fs,
                    "readback": readback,
                    "family_readback": family_readback,
                    "readback_status": readback_status,
                    "response_envelope": response_envelope,
                },
            )
        changed_sections = plan_result.get("changed_sections") or [
            str(item.get("block_id") or item.get("operation_id") or "")
            for item in fs.get("applied_operations") or []
            if isinstance(item, dict)
        ]
        manual_actions = fs.get("manual_actions") or plan_payload.get("manual_actions") or []
        response_envelope = self._document_edit_response_envelope(
            "final",
            source=source,
            error_code="",
            reason="",
            manual_actions=manual_actions,
            applied_operations=fs.get("applied_operations") or [],
        )
        self._emit_document_edit_progress_event(
            "final",
            source=source,
            manual_actions=manual_actions,
            applied_operations=fs.get("applied_operations") or [],
        )
        entry = self.archive_service.save_archive(
            message,
            "修改文档",
            [
                ("目标文档", doc_url),
                ("目标来源", str(edit_request.get("target_source") or "")),
                ("定位", "、".join(edit_request.get("target_sections") or []) or "由系统判断"),
                ("修改要求", str(edit_request.get("edit_requirements") or "")),
                ("原文字数", str(len(original_text))),
                ("执行 patch 数", str(len(fs.get("applied_operations") or []))),
                ("人工项数", str(len(manual_actions))),
                ("变更章节", "、".join(str(item) for item in changed_sections) if isinstance(changed_sections, list) else str(changed_sections)),
                ("source_block_hash", source_block_hash),
                ("preflight_status", preflight_status),
                ("快照路径", str(source.get("snapshot_path") or "")),
                ("文档家族", document_family),
                ("family_contract_id", family_contract_id),
                ("document_family_provenance", str(source.get("document_family_provenance") or "")),
                ("readback_status", readback_status),
                ("状态", "已分块修改同一文档"),
            ],
            {"workflow": "document_edit", "target_doc": doc_url},
        )
        self.archive_service.update_frontmatter(entry.local_path, {"feishu_synced": True, "feishu_doc": fs.get("doc", "") or doc_url})
        reply = "\n".join(
            [
                "已完成修改，并以分块文本 patch 更新同一文档。",
                f"文档：{fs.get('doc') or doc_url}",
                f"已执行 patch：{len(fs.get('applied_operations') or [])}",
                f"人工项：{len(manual_actions)}",
            ]
        )
        return TaskResult(
            ok=True,
            status="document_edited",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            feishu_doc=fs.get("doc", "") or doc_url,
            extra={
                "workflow": "document_edit",
                "target_doc": fs.get("doc") or doc_url,
                "changed_sections": changed_sections,
                "snapshot_path": source.get("snapshot_path"),
                "patch_plan": plan_payload,
                "source_block_snapshot": source_block_snapshot,
                "source_block_hash": source_block_hash,
                "preflight_status": preflight_status,
                "unsupported_block_types": unsupported_block_types,
                "unsupported_document_blocks": source.get("unsupported_document_blocks") or [],
                "document_family": document_family,
                "producer_capability": producer_capability,
                "family_contract_id": family_contract_id,
                "document_family_provenance": str(source.get("document_family_provenance") or ""),
                "family_requirements_checked": family_readback.get("family_requirements_checked") or source.get("family_requirements_checked") or [],
                "native_table_count": family_readback.get("native_table_count", readback.get("native_table_count", source.get("native_table_count") or 0)),
                "markdown_table_residue_found": family_readback.get("markdown_table_residue_found", readback.get("markdown_table_residue_found", False)),
                "commercial_delivery_record_unresolved": commercial_delivery_record_unresolved,
                "not_commercial_delivery_document": document_family != "commercial_delivery",
                "COM01": source.get("commercial_delivery_record") or "not_commercial_delivery_document",
                "commercial_delivery_sync": commercial_sync,
                "family_readback": family_readback,
                "readback_status": readback_status,
                "response_envelope": response_envelope,
                "readback": readback,
                "apply": fs,
            },
        )

    def _handle_shooting_execution_backwash(
        self, message: Message, edit_request: dict[str, Any], source: dict[str, Any]
    ) -> TaskResult:
        doc_url = str(edit_request.get("target_doc_url") or "").strip()
        try:
            from selfmedia.creation.backwash import handle_shooting_execution_backwash

            parsed = handle_shooting_execution_backwash(
                doc_url,
                str(edit_request.get("edit_requirements") or ""),
                tenant_id=str(current_session_tenant_id()),
            )
        except Exception as exc:
            if getattr(exc, "code", ""):
                raise
            return TaskResult(
                ok=False,
                status="shooting_execution_backwash_failed",
                reply=(
                    "拍摄执行回洗未完成（SHOOTING_EXECUTION_BACKWASH_FAILED）："
                    "目标文档未写入，请稍后重试或由维护流程检查 CreationRun 映射。"
                ),
                task_id="",
                feishu_doc=doc_url,
                extra={
                    "workflow": "shooting_execution_backwash",
                    "document_family": "shooting_execution",
                    "error_code": "SHOOTING_EXECUTION_BACKWASH_FAILED",
                },
            )
        return TaskResult(
            ok=bool(parsed.get("ok")),
            status=str(parsed.get("status") or "shooting_execution_backwashed"),
            reply=str(parsed.get("reply") or f"已回洗拍摄执行文档：{doc_url}"),
            task_id=str(parsed.get("creation_run_id") or ""),
            feishu_doc=str(parsed.get("doc_link") or doc_url),
            extra={**parsed, "workflow": "shooting_execution_backwash", "document_family": "shooting_execution"},
        )

    def _prepare_document_edit_patch_source(self, doc_url: str, message: Message) -> dict[str, Any]:
        preparer = getattr(self.feishu_service, "prepare_document_edit_patch_source", None)
        if not callable(preparer):
            return {
                "ok": False,
                "status": "document_edit_patch_preflight_unavailable",
                "reply": "当前飞书服务缺少文档 patch 预检能力，已停止写入。",
            }
        try:
            source = preparer(
                doc_url,
                snapshot_reason="document_edit_patch",
            )
        except TypeError:
            source = preparer(doc_url)
        except Exception as exc:
            return {"ok": False, "status": "document_edit_patch_preflight_failed", "error": f"文档 patch 预检失败：{exc}"}
        if not isinstance(source, dict):
            return {"ok": False, "status": "document_edit_patch_preflight_failed", "error": "文档 patch 预检返回值无效。"}
        if not source.get("ok"):
            return source
        if not source.get("snapshot_path") or not source.get("source_hash") or not source.get("revision_token"):
            return {
                **source,
                "ok": False,
                "status": "document_edit_patch_preflight_incomplete",
                "reply": "文档 patch 预检缺少 snapshot_path、source_hash 或 revision_token，已停止写入。",
            }
        source["source_block_snapshot"] = source.get("root_blocks") or []
        source["source_block_hash"] = source.get("source_hash")
        source["preflight_status"] = "patch_preflight_ok"
        source["unsupported_document_blocks"] = source.get("protected_blocks") or []
        source["unsupported_block_types"] = sorted(
            {
                str(item.get("block_type") or item.get("kind") or "")
                for item in source.get("protected_blocks") or []
                if isinstance(item, dict)
            }
        )
        return source

    @staticmethod
    def _document_edit_public_preflight_failure(source: dict[str, Any]) -> str:
        raw = str(source.get("reply") or source.get("error") or "").strip()
        lowered = raw.lower()
        if "131005" in raw or ("get_node" in lowered and "not found" in lowered):
            return (
                "[DOCUMENT_EDIT_TARGET_NOT_FOUND] 未找到目标飞书文档。"
                "请确认链接指向当前应用可访问的 Wiki/Docx 文档后重试。"
            )
        if any(marker in lowered for marker in ("feishu api request failed", "traceback", "troubleshooter", "log_id")):
            return (
                "[DOCUMENT_EDIT_PREFLIGHT_FAILED] 目标文档安全预检未通过，已停止写入。"
                "请确认文档链接和访问权限后重试。"
            )
        return raw or "[DOCUMENT_EDIT_PREFLIGHT_FAILED] 目标文档安全预检未通过，已停止写入。"

    def _build_document_edit_patch_plan(self, source: dict[str, Any], edit_request: dict[str, Any], message: Message) -> dict[str, Any]:
        if not hasattr(self.content_flow_client, "_call_postprocess_json"):
            return {"status": "pending_manual", "reason": "content_flow_client 缺少 LLM JSON 调用"}
        try:
            working_copy = DocumentEditWorkingCopy.from_patch_source(
                source,
                target_doc_url=str(edit_request.get("target_doc_url") or ""),
            )
        except DocumentEditContractViolation as exc:
            return {
                "status": "pending_manual",
                "reason": str(exc),
                "error_code": "DOCUMENT_EDIT_WORKING_COPY_INVALID",
            }
        if working_copy.truncated and not self._document_edit_has_visible_heading_chunks(working_copy):
            return {
                "status": "pending_manual",
                "reason": "文档结构读取已截断，当前不能基于残缺视图自动 patch；请缩小到明确章节后重试。",
                "error_code": "DOCUMENT_EDIT_WORKING_COPY_TRUNCATED",
                "manual_actions": [
                    {
                        "reason": "working_copy_truncated",
                        "instructions": "文档块视图不完整；先指定要修改的章节或等待 chunked planning 能力完成后再自动执行。",
                        "requested_op": "chunked_planning_required",
                    }
                ],
            }
        stage1 = self._build_document_edit_patch_target_plan(working_copy, edit_request, message)
        if str(stage1.get("status") or "") == "pending_manual":
            error_code = str(stage1.get("error_code") or "")
            if error_code == "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT":
                if working_copy.truncated:
                    return stage1
                stage1 = self._document_edit_degraded_target_plan(working_copy, stage1)
            else:
                return stage1
        if working_copy.truncated:
            stage1 = self._document_edit_limit_truncated_stage1_to_visible_heading_chunks(working_copy, stage1)
            if str(stage1.get("status") or "") == "pending_manual":
                return stage1
        stage2_scopes = self._document_edit_stage2_scopes(stage1)
        if len(stage2_scopes) == 1:
            stage_compact_view = self._document_edit_stage_compact_view(working_copy, stage1)
            result = self._build_document_edit_stage2_patch_plan(
                working_copy,
                edit_request,
                message,
                stage1,
                stage_compact_view,
            )
            if str(result.get("status") or "") == "pending_manual":
                return result
            enriched = self._enrich_document_edit_patch_operations(result, working_copy)
            if stage1.get("intent_ops"):
                intent_fanout = self._document_edit_expand_intent_ops(working_copy, stage1.get("intent_ops") or [])
                enriched["operations"] = list(intent_fanout.get("operations") or []) + list(enriched.get("operations") or [])
                enriched["manual_actions"] = list(intent_fanout.get("manual_actions") or []) + list(enriched.get("manual_actions") or [])
                enriched["intent_trace"] = intent_fanout.get("intent_trace") or []
            if stage1.get("manual_actions"):
                enriched["manual_actions"] = list(stage1.get("manual_actions") or []) + list(enriched.get("manual_actions") or [])
            if stage1.get("stage1_trace"):
                enriched["stage1_trace"] = stage1.get("stage1_trace")
            return enriched

        stage2_results: list[dict[str, Any]] = []
        stage2_manual_actions: list[dict[str, Any]] = []
        for scoped_stage1 in stage2_scopes:
            stage_compact_view = self._document_edit_stage_compact_view(working_copy, scoped_stage1)
            stage2_result = self._build_document_edit_stage2_patch_plan(
                working_copy,
                edit_request,
                message,
                scoped_stage1,
                stage_compact_view,
            )
            if str(stage2_result.get("status") or "") == "pending_manual":
                stage2_manual_actions.extend(self._document_edit_stage2_manual_actions(scoped_stage1, stage2_result))
                continue
            chunk_enriched = self._enrich_document_edit_patch_operations(stage2_result, working_copy)
            chunk_schema = self._validate_document_edit_patch_plan(chunk_enriched)
            if not chunk_schema.get("ok"):
                stage2_manual_actions.extend(
                    self._document_edit_stage2_manual_actions(
                        scoped_stage1,
                        {
                            "status": "pending_manual",
                            "reason": str(chunk_schema.get("reply") or "Stage 2 patch plan failed schema validation."),
                            "error_code": "DOCUMENT_EDIT_PATCH_SCHEMA_INVALID",
                        },
                    )
                )
                continue
            stage2_results.append(chunk_schema["plan"])
        if not stage2_results:
            if stage2_manual_actions:
                return {
                    "status": "pending_manual",
                    "reason": "Stage 2 patch planner could not produce any executable operations.",
                    "error_code": "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT"
                    if any(str(item.get("error_code") or "") == "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT" for item in stage2_manual_actions)
                    else "DOCUMENT_EDIT_PATCH_PLAN_PENDING_MANUAL",
                    "manual_actions": stage2_manual_actions,
                }
            return {
                "status": "pending_manual",
                "reason": "Stage 2 patch planner produced no result.",
                "error_code": "DOCUMENT_EDIT_PATCH_PLAN_PENDING_MANUAL",
            }
        result = self._merge_document_edit_stage2_results(stage2_results)
        result["manual_actions"] = stage2_manual_actions + list(result.get("manual_actions") or [])
        enriched = self._enrich_document_edit_patch_operations(result, working_copy)
        if stage1.get("intent_ops"):
            intent_fanout = self._document_edit_expand_intent_ops(working_copy, stage1.get("intent_ops") or [])
            enriched["operations"] = list(intent_fanout.get("operations") or []) + list(enriched.get("operations") or [])
            enriched["manual_actions"] = list(intent_fanout.get("manual_actions") or []) + list(enriched.get("manual_actions") or [])
            enriched["intent_trace"] = intent_fanout.get("intent_trace") or []
        if stage1.get("manual_actions"):
            enriched["manual_actions"] = list(stage1.get("manual_actions") or []) + list(enriched.get("manual_actions") or [])
        if stage1.get("stage1_trace"):
            enriched["stage1_trace"] = stage1.get("stage1_trace")
        return enriched

    def _build_document_edit_stage2_patch_plan(
        self,
        working_copy: DocumentEditWorkingCopy,
        edit_request: dict[str, Any],
        message: Message,
        stage1: dict[str, Any],
        stage_compact_view: str,
    ) -> dict[str, Any]:
        patch_source = working_copy.patch_source()
        prompt = (
            "你是 OpenClaw 飞书 Docx 分块修改 Stage 2 planner。只输出合法 JSON，不要 Markdown 代码块，不要解释。\n"
            "任务：根据用户修改要求、Stage 1 定位结果和 scoped compact_view 输出 patch plan；不得输出完整正文 content/markdown/full_markdown。\n"
            "默认不变量：不改变产品事实；不删除或移动图片、附件、callout、表格结构；不改 protected_block_ids；无法安全定位的要求进入 manual_actions。\n"
            "可执行 operations 只能使用白名单：replace_text、insert_text_after、delete_text_block、append_text_to_cell、insert_table_row。\n"
            "replace_text 会替换整个 Feishu text_elements 列表：你只给 block_id 和完整 new_text；expected_old_text、path、source、block_refs 由系统从 WorkingCopy 回填，禁止你复制旧文本。\n"
            "replace_text 必须给 block_id、new_text；insert_text_after 必须给 anchor_block_id、parent_block_id、new_text，禁止 index/static_index；append_text_to_cell 必须给 cell_block_id、new_text；delete_text_block 只允许删除纯文本块且必须给 block_id、parent_block_id。\n"
            "insert_table_row 只允许用于商单交付图片脚本原生表格补足图片脚本行；必须给 table_block_id 或 block_id、row_index=-1、cell_texts 数组、minimum_rows 和 content_spec。它只新增表格行和新增 cell 文本，不删除旧表格、旧图片或旧 cell。\n"
            "图片删除、真实图片文件替换或无法定位到具体表格/文字块时必须输出 manual_actions；但“图片至少 N 张”命中图片脚本表格时不要退 manual，应输出 insert_table_row。\n"
            "不要回传 source、block_refs、document_text、protected_blocks。只输出 JSON 形状：{\"status\":\"done\",\"operations\":[{\"op\":\"replace_text\",\"operation_id\":\"op1\",\"block_id\":\"...\",\"new_text\":\"目标块完整新文本\",\"source_evidence\":[\"来自原文或用户要求\"]},{\"op\":\"insert_table_row\",\"operation_id\":\"op-img-8\",\"table_block_id\":\"...\",\"row_index\":-1,\"cell_texts\":[\"图8\",\"草坪球场/H5活动补图\",\"...\"],\"minimum_rows\":9,\"content_spec\":\"图文至少9张\",\"source_evidence\":[\"用户要求图片至少9张\"]}],\"manual_actions\":[{\"reason\":\"protected_block\",\"instructions\":\"...\",\"requested_op\":\"...\",\"block_id\":\"...\"}],\"changed_sections\":[\"...\"],\"product_facts_checked\":[\"...\"],\"commercial_delivery_record_fields\":{}}。"
        )
        user_content = json.dumps(
            {
                "document_url": patch_source["url"],
                "working_copy_summary": working_copy.summary(),
                "planner_stage": "stage2_generate_patch",
                "stage1_target_plan": stage1,
                "compact_view": stage_compact_view,
                "edit_request": edit_request,
                "created_at": format_display_time(message.created_at),
                "recent_conversation_context": self._conversation_context_prompt(message),
                "style_context_prompt": self._document_edit_style_context_prompt(edit_request, stage_compact_view),
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            result = self.content_flow_client._call_postprocess_json(
                prompt,
                user_content,
                env,
                "文档修改 patch plan",
                timeout_seconds=self._document_edit_patch_plan_timeout_seconds(),
                max_retries=0,
                thinking=self._document_edit_patch_plan_thinking(),
            )
        except Exception as exc:
            return {"status": "pending_manual", "reason": str(exc), "error_code": self._document_edit_patch_plan_error_code(str(exc))}
        if not isinstance(result, dict):
            return {
                "status": "pending_manual",
                "reason": "LLM patch plan 不是 JSON object",
                "error_code": "DOCUMENT_EDIT_PATCH_PLAN_INVALID_JSON",
            }
        if str(result.get("status") or "") == "pending_manual":
            result["error_code"] = self._document_edit_patch_plan_error_code(str(result.get("reason") or ""))
            return result
        return result

    @staticmethod
    def _document_edit_has_visible_heading_chunks(working_copy: DocumentEditWorkingCopy) -> bool:
        return bool(working_copy.visible_heading_paths())

    def _document_edit_limit_truncated_stage1_to_visible_heading_chunks(self, working_copy: DocumentEditWorkingCopy, stage1: dict[str, Any]) -> dict[str, Any]:
        block_by_id = working_copy.block_by_id()
        visible_targets: list[dict[str, Any]] = []
        manual_actions: list[dict[str, Any]] = list(stage1.get("manual_actions") or [])
        for target in stage1.get("targets") or []:
            if not isinstance(target, dict):
                continue
            block_ids = [str(item) for item in target.get("block_ids") or [] if str(item)]
            visible_heading_block_ids = [
                block_id
                for block_id in block_ids
                if block_by_id.get(block_id) is not None and block_by_id[block_id].heading_path
            ]
            missing_or_unscoped_block_ids = [block_id for block_id in block_ids if block_id not in visible_heading_block_ids]
            if missing_or_unscoped_block_ids:
                manual_actions.append(
                    {
                        "reason": "truncated_target_not_in_visible_heading_chunk",
                        "instructions": "文档读取已截断；该修改要求命中的块不在可验证的可见 heading chunk 内，已改为人工项。",
                        "requested_op": "stage1_locate_targets",
                        "requirement_id": str(target.get("requirement_id") or ""),
                        "target_block_ids": missing_or_unscoped_block_ids,
                    }
                )
            if visible_heading_block_ids:
                scoped = dict(target)
                scoped["block_ids"] = visible_heading_block_ids
                scoped["truncated_visible_heading_chunk"] = True
                visible_targets.append(scoped)
        manual_actions.append(
            {
                "reason": "working_copy_truncated_unknown_sections",
                "instructions": "文档块视图已截断；系统只会修改当前已读取且带 heading_path 的可见章节块，未读取到的章节需人工复核。",
                "requested_op": "review_unread_sections",
            }
        )
        if not visible_targets:
            return {
                "status": "pending_manual",
                "reason": "文档结构读取已截断，Stage 1 未定位到可验证的可见 heading chunk，已停止自动 patch。",
                "error_code": "DOCUMENT_EDIT_WORKING_COPY_TRUNCATED",
                "manual_actions": manual_actions,
            }
        limited = dict(stage1)
        limited["targets"] = visible_targets
        limited["manual_actions"] = manual_actions
        limited["truncated_visible_heading_planning"] = True
        return limited

    @staticmethod
    def _document_edit_stage2_scopes(stage1: dict[str, Any]) -> list[dict[str, Any]]:
        targets = [item for item in stage1.get("targets") or [] if isinstance(item, dict)]
        if len(targets) <= 1:
            return [stage1]
        scopes: list[dict[str, Any]] = []
        for target in targets:
            scope = dict(stage1)
            scope["targets"] = [target]
            scope["intent_ops"] = []
            scope["manual_actions"] = []
            scope["stage2_scope"] = {
                "requirement_id": str(target.get("requirement_id") or ""),
                "block_ids": [str(item) for item in target.get("block_ids") or [] if str(item)],
                "reason": str(target.get("reason") or ""),
            }
            scopes.append(scope)
        return scopes

    def _document_edit_stage2_manual_actions(self, scoped_stage1: dict[str, Any], stage2_result: dict[str, Any]) -> list[dict[str, Any]]:
        scope = scoped_stage1.get("stage2_scope") if isinstance(scoped_stage1.get("stage2_scope"), dict) else {}
        target_ids: list[str] = []
        for target in scoped_stage1.get("targets") or []:
            if isinstance(target, dict):
                target_ids.extend(str(item) for item in target.get("block_ids") or [] if str(item))
        error_code = str(stage2_result.get("error_code") or self._document_edit_patch_plan_error_code(str(stage2_result.get("reason") or "")))
        reason = str(stage2_result.get("reason") or "Stage 2 patch planner did not return executable operations.")
        return [
            {
                "reason": "stage2_patch_plan_failed",
                "instructions": reason,
                "requested_op": "stage2_generate_patch",
                "requirement_id": str(scope.get("requirement_id") or ""),
                "block_id": target_ids[0] if target_ids else "",
                "target_block_ids": target_ids,
                "error_code": error_code,
            }
        ]

    @staticmethod
    def _merge_document_edit_stage2_results(stage2_results: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "status": "done",
            "operations": [],
            "manual_actions": [],
            "changed_sections": [],
            "product_facts_checked": [],
            "commercial_delivery_record_fields": {},
            "stage2_trace": [],
        }
        for index, result in enumerate(stage2_results, start=1):
            merged["operations"].extend(item for item in result.get("operations") or [] if isinstance(item, dict))
            merged["manual_actions"].extend(item for item in result.get("manual_actions") or [] if isinstance(item, dict))
            merged["changed_sections"].extend(str(item) for item in result.get("changed_sections") or [] if str(item))
            merged["product_facts_checked"].extend(str(item) for item in result.get("product_facts_checked") or [] if str(item))
            record_fields = result.get("commercial_delivery_record_fields")
            if isinstance(record_fields, dict):
                merged["commercial_delivery_record_fields"].update(record_fields)
            merged["stage2_trace"].append(
                {
                    "index": index,
                    "operation_count": len(result.get("operations") or []),
                    "manual_action_count": len(result.get("manual_actions") or []),
                }
            )
        merged["changed_sections"] = list(dict.fromkeys(merged["changed_sections"]))
        merged["product_facts_checked"] = list(dict.fromkeys(merged["product_facts_checked"]))
        if not merged["commercial_delivery_record_fields"]:
            merged.pop("commercial_delivery_record_fields", None)
        return merged

    def _document_edit_expand_intent_ops(self, working_copy: DocumentEditWorkingCopy, intent_payloads: list[Any]) -> dict[str, Any]:
        intent_operations: list[DocumentEditIntentOperation] = []
        manual_actions: list[dict[str, Any]] = []
        for item in intent_payloads:
            if not isinstance(item, dict):
                manual_actions.append(
                    {
                        "reason": "invalid_intent_operation",
                        "instructions": "Review manually because an intent operation was not an object.",
                        "requested_op": "replace_terms",
                    }
                )
                continue
            try:
                intent_operations.append(DocumentEditIntentOperation.from_mapping(item))
            except DocumentEditContractViolation as exc:
                manual_actions.append(
                    {
                        "reason": "invalid_intent_operation",
                        "instructions": f"Review replace_terms manually because the intent contract failed: {exc}",
                        "requested_op": str(item.get("op") or item.get("intent") or "replace_terms"),
                    }
                )
        fanout = working_copy.fanout_intent_operations(intent_operations) if intent_operations else {"operations": [], "manual_actions": []}
        return {
            "operations": list(fanout.get("operations") or []),
            "manual_actions": [*manual_actions, *list(fanout.get("manual_actions") or [])],
            "intent_trace": [operation.to_mapping() for operation in intent_operations],
        }

    def _build_document_edit_patch_target_plan(self, working_copy: DocumentEditWorkingCopy, edit_request: dict[str, Any], message: Message) -> dict[str, Any]:
        prompt = (
            "你是 OpenClaw 飞书 Docx 修改 Stage 1 locator。只输出 JSON，不要 Markdown。\n"
            "任务：只定位每条修改要求命中的 block_id、不可自动执行的 manual_actions、以及可由代码机械扇出的 intent_ops；不要生成 new_text，不要输出完整正文。\n"
            "intent_ops 只能在用户明确提出替换词时输出，且必须选定一个具体替换词；形状为 {\"op\":\"replace_terms\",\"target_block_ids\":[\"...\"],\"old_text\":\"世界杯\",\"new_text\":\"赛事\",\"source_evidence\":[\"...\"]}。\n"
            "如果 compact_view 含 [TRUNCATED]，只能定位已出现在 compact_view 且带 [h=...] heading_path 的可见章节块；任何未读取章节、无 heading_path 块或全局性修改必须进 manual_actions。\n"
            "图片数量要求如果命中商单交付图片脚本原生表格，定位 table block_id 作为 target，不要退 manual；后续 Stage 2 会用已验证的 insert_table_row 追加行。\n"
            "删除真实图片文件、替换图片文件、附件、callout、富文本不确定项必须进入 manual_actions；只改图文脚本文字或追加图片脚本行不属于真实图片文件删除。\n"
            "输出形状：{\"status\":\"done\",\"targets\":[{\"requirement_id\":\"r1\",\"block_ids\":[\"...\"],\"reason\":\"...\"}],\"intent_ops\":[],\"manual_actions\":[]}。"
        )
        user_content = json.dumps(
            {
                "document_url": working_copy.url,
                "working_copy_summary": working_copy.summary(),
                "planner_stage": "stage1_locate_targets",
                "compact_view": working_copy.compact_view(),
                "edit_request": edit_request,
                "created_at": format_display_time(message.created_at),
            },
            ensure_ascii=False,
        )
        try:
            env = self.content_flow_client._content_flow_env()
            result = self.content_flow_client._call_postprocess_json(
                prompt,
                user_content,
                env,
                "文档修改 target plan",
                timeout_seconds=self._document_edit_patch_stage1_timeout_seconds(),
                max_retries=0,
                thinking=self._document_edit_patch_stage1_thinking(),
            )
        except Exception as exc:
            return {
                "status": "pending_manual",
                "reason": str(exc),
                "error_code": self._document_edit_patch_plan_error_code(str(exc)),
            }
        if not isinstance(result, dict):
            return {
                "status": "pending_manual",
                "reason": "LLM target plan 不是 JSON object",
                "error_code": "DOCUMENT_EDIT_PATCH_PLAN_INVALID_JSON",
            }
        if str(result.get("status") or "") == "pending_manual":
            result["error_code"] = self._document_edit_patch_plan_error_code(str(result.get("reason") or ""))
            return result
        if not result.get("targets") and result.get("operations"):
            target_ids = [
                str(item.get("block_id") or item.get("target_block_id") or "")
                for item in result.get("operations") or []
                if isinstance(item, dict) and str(item.get("block_id") or item.get("target_block_id") or "")
            ]
            result["targets"] = [{"requirement_id": "r1", "block_ids": target_ids, "reason": "derived_from_lightweight_operations"}]
        result.setdefault("intent_ops", [])
        result.setdefault("manual_actions", [])
        return result

    def _document_edit_degraded_target_plan(self, working_copy: DocumentEditWorkingCopy, failed_stage1: dict[str, Any]) -> dict[str, Any]:
        block_ids = [block.block_id for block in working_copy.blocks if not block.protected]
        return {
            "status": "done",
            "targets": [
                {
                    "requirement_id": "all",
                    "block_ids": block_ids,
                    "reason": "stage1_locator_timeout_degraded_to_full_patchable_view",
                }
            ],
            "intent_ops": [],
            "manual_actions": [
                {
                    "reason": "stage1_locator_timeout",
                    "instructions": "定位器超时；系统已改用完整可改文字块视图继续让 LLM 生成 patch，受保护结构仍需人工确认。",
                    "requested_op": "stage1_locate_targets",
                }
            ],
            "stage1_trace": {
                "degraded": True,
                "error_code": str(failed_stage1.get("error_code") or "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT"),
                "reason": str(failed_stage1.get("reason") or ""),
            },
        }

    def _document_edit_stage_compact_view(self, working_copy: DocumentEditWorkingCopy, stage1: dict[str, Any]) -> str:
        target_ids: set[str] = set()
        for target in stage1.get("targets") or []:
            if not isinstance(target, dict):
                continue
            target_ids.update(str(item) for item in target.get("block_ids") or [] if str(item))
        for intent in stage1.get("intent_ops") or []:
            if isinstance(intent, dict):
                target_ids.update(str(item) for item in intent.get("target_block_ids") or [] if str(item))
        if not target_ids:
            return working_copy.compact_view()
        if working_copy.truncated:
            block_by_id = working_copy.block_by_id()
            target_headings = {
                tuple(block_by_id[block_id].heading_path)
                for block_id in target_ids
                if block_by_id.get(block_id) is not None and block_by_id[block_id].heading_path
            }
            if target_headings:
                return working_copy.compact_view_for_heading_paths([list(path) for path in target_headings])
        lines: list[str] = []
        for index, block in enumerate(working_copy.blocks):
            if block.block_id in target_ids:
                if index > 0:
                    lines.append(working_copy.blocks[index - 1].compact_line())
                lines.append(block.compact_line())
                if index + 1 < len(working_copy.blocks):
                    lines.append(working_copy.blocks[index + 1].compact_line())
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line not in seen:
                deduped.append(line)
                seen.add(line)
        return "\n".join(deduped) if deduped else working_copy.compact_view()

    def _enrich_document_edit_patch_operations(self, result: dict[str, Any], working_copy: DocumentEditWorkingCopy) -> dict[str, Any]:
        block_by_id = working_copy.block_by_id()
        operations: list[dict[str, Any]] = []
        for item in result.get("operations") or []:
            if not isinstance(item, dict):
                continue
            op_payload = dict(item)
            op_name = str(op_payload.get("op") or op_payload.get("operation") or "")
            block_id = str(
                op_payload.get("block_id")
                or op_payload.get("target_block_id")
                or op_payload.get("table_block_id")
                or op_payload.get("anchor_block_id")
                or op_payload.get("cell_block_id")
                or ""
            ).strip()
            block = block_by_id.get(block_id)
            if block is not None:
                op_payload["block_id"] = block.block_id
                op_payload.setdefault("path", list(block.path))
                op_payload.setdefault("block_type", block.block_type)
                op_payload.setdefault("table_shape", dict(block.table_shape))
                op_payload["protected"] = block.protected
                if block.protection_reason:
                    op_payload["protection_reason"] = block.protection_reason
                op_payload["has_non_plain_text_elements"] = block.has_non_plain_text_elements
                op_payload["has_style_run_proof"] = block.has_style_run_proof
                if op_name in {"replace_text", "delete_text_block"}:
                    op_payload["expected_old_text"] = block.text
                if op_name == "delete_text_block":
                    op_payload.setdefault("new_text", "")
            operations.append(op_payload)
        enriched = dict(result)
        enriched["operations"] = operations
        enriched["source"] = working_copy.patch_source()
        enriched["block_refs"] = working_copy.block_map()
        enriched.setdefault("manual_actions", [])
        return enriched

    @staticmethod
    def _document_edit_drop_noop_operations(plan_payload: dict[str, Any]) -> dict[str, Any]:
        operations: list[dict[str, Any]] = []
        noop_operations: list[dict[str, Any]] = list(plan_payload.get("noop_operations") or [])
        for item in plan_payload.get("operations") or []:
            if not isinstance(item, dict):
                continue
            op_name = str(item.get("op") or item.get("operation") or "")
            if op_name == "replace_text" and str(item.get("expected_old_text") or "") == str(item.get("new_text") or ""):
                noop_operations.append(item)
                continue
            operations.append(item)
        if len(operations) == len(plan_payload.get("operations") or []) and not noop_operations:
            return plan_payload
        filtered = dict(plan_payload)
        filtered["operations"] = operations
        filtered["noop_operations"] = noop_operations
        return filtered

    @staticmethod
    def _document_edit_patch_plan_timeout_seconds() -> float:
        raw = str(os.getenv("DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT_SECONDS", "120") or "").strip()
        try:
            value = float(raw)
        except ValueError:
            value = 120.0
        return max(15.0, min(value, 300.0))

    @staticmethod
    def _document_edit_patch_stage1_timeout_seconds() -> float:
        raw = str(os.getenv("DOCUMENT_EDIT_PATCH_STAGE1_TIMEOUT_SECONDS", "45") or "").strip()
        try:
            value = float(raw)
        except ValueError:
            value = 45.0
        return max(10.0, min(value, 120.0))

    @staticmethod
    def _document_edit_patch_plan_thinking() -> str:
        value = str(os.getenv("DOCUMENT_EDIT_PATCH_PLAN_THINKING", "medium") or "").strip().lower()
        return value if value in {"off", "minimal", "low", "medium", "high"} else "medium"

    @staticmethod
    def _document_edit_patch_stage1_thinking() -> str:
        value = str(os.getenv("DOCUMENT_EDIT_PATCH_STAGE1_THINKING", "low") or "").strip().lower()
        return value if value in {"off", "minimal", "low", "medium", "high"} else "low"

    @staticmethod
    def _document_edit_patch_plan_error_code(reason: str) -> str:
        value = str(reason or "").lower()
        if "timeout" in value or "timed out" in value or "exceeded hard total timeout" in value:
            return "DOCUMENT_EDIT_PATCH_PLAN_TIMEOUT"
        if "429" in value or "too many requests" in value:
            return "DOCUMENT_EDIT_PATCH_PLAN_RATE_LIMITED"
        if "json" in value:
            return "DOCUMENT_EDIT_PATCH_PLAN_INVALID_JSON"
        return "DOCUMENT_EDIT_PATCH_PLAN_PENDING_MANUAL"

    def _document_edit_response_envelope(
        self,
        stage: str,
        *,
        source: dict[str, Any],
        error_code: str,
        reason: str,
        manual_actions: list[Any],
        applied_operations: list[Any],
    ) -> dict[str, Any]:
        protected_blocks = source.get("protected_blocks") or source.get("unsupported_document_blocks") or []
        return {
            "schema": "openclaw.document_edit.response_envelope.v1",
            "stage": stage,
            "document_id": str(source.get("document_id") or ""),
            "snapshot_path": str(source.get("snapshot_path") or ""),
            "source_hash": str(source.get("source_hash") or source.get("source_block_hash") or ""),
            "revision_token": str(source.get("revision_token") or ""),
            "known_facts": {
                "block_count": len(source.get("patchable_blocks") or []) + len(protected_blocks),
                "patchable_block_count": len(source.get("patchable_blocks") or []),
                "protected_block_count": len(protected_blocks),
                "protected_table_count": len(source.get("protected_table_shapes") or []),
                "truncated": bool(source.get("truncated") or source.get("tree_truncated")),
            },
            "error_code": error_code,
            "reason": reason,
            "manual_actions": manual_actions,
            "applied_operations": applied_operations,
        }

    def _render_document_edit_response_envelope(self, envelope: dict[str, Any]) -> str:
        stage = str(envelope.get("stage") or "")
        known = envelope.get("known_facts") if isinstance(envelope.get("known_facts"), dict) else {}
        if stage == "final":
            title = "已完成修改，并以分块文本 patch 更新同一文档。"
        else:
            title = f"文档修改未完成：{envelope.get('error_code') or stage}"
        lines = [
            title,
            f"已读取：可改文字块 {known.get('patchable_block_count', 0)}，保护块 {known.get('protected_block_count', 0)}，保护表格 {known.get('protected_table_count', 0)}",
        ]
        if envelope.get("reason"):
            lines.append(f"原因：{envelope.get('reason')}")
        lines.append(f"已执行 patch：{len(envelope.get('applied_operations') or [])}")
        lines.append(f"人工项：{len(envelope.get('manual_actions') or [])}")
        return "\n".join(lines)

    def _validate_document_edit_patch_plan(self, result: dict[str, Any]) -> dict[str, Any]:
        if str(result.get("status") or "") != "done":
            return {"ok": False, "status": "document_edit_patch_schema_invalid", "reply": "文档修改失败：LLM 未返回 status=done，已停止写入。"}
        try:
            plan = DocumentEditPatchPlan.from_mapping(
                result,
                executable_op_whitelist=load_document_edit_op_whitelist(),
            )
        except DocumentEditContractViolation as exc:
            return {"ok": False, "status": "document_edit_patch_schema_invalid", "reply": f"文档修改失败：{exc}，已停止写入。"}
        return {"ok": True, "status": "document_edit_patch_schema_ok", "plan": plan.to_mapping()}

    def _apply_document_edit_patch_plan(self, plan_payload: dict[str, Any]) -> dict[str, Any]:
        applier = getattr(self.feishu_service, "apply_document_edit_patch_plan", None)
        if not callable(applier):
            return {"ok": False, "status": "document_edit_patch_apply_unavailable", "reply": "当前飞书服务缺少分块 patch 写入能力，已停止写入。"}
        try:
            result = applier(plan_payload)
        except Exception as exc:
            return {"ok": False, "status": "document_edit_patch_apply_failed", "error": str(exc)}
        if isinstance(result, dict) and result.get("status") == "document_changed_since_read":
            return result
        return result if isinstance(result, dict) else {"ok": bool(result), "status": "patch_apply_ok" if result else "patch_apply_failed"}

    def _verify_document_edit_patch_readback(self, plan_payload: dict[str, Any], apply_result: dict[str, Any]) -> dict[str, Any]:
        verifier = getattr(self.feishu_service, "verify_document_edit_patch_readback", None)
        if not callable(verifier):
            return {"ok": False, "status": "document_edit_patch_readback_unavailable", "reply": "当前飞书服务缺少分块 patch 读回校验能力。"}
        try:
            result = verifier(plan_payload, apply_result)
        except Exception as exc:
            return {"ok": False, "status": "document_edit_patch_readback_failed", "error": str(exc)}
        return result if isinstance(result, dict) else {"ok": bool(result)}

    def _document_edit_block_refs_from_snapshot(self, blocks: list[Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []

        def visit(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                block_id = str(item.get("block_id") or "")
                text = str(item.get("text") or "")
                block_type = item.get("block_type")
                if block_id and text and not item.get("non_plain_text_element_kinds"):
                    refs.append(
                        {
                            "block_id": block_id,
                            "path": [str(item.get("path") or "")],
                            "block_type": str(block_type or ""),
                            "text": text,
                            "protected": False,
                            "has_non_plain_text_elements": False,
                        }
                    )
                visit(item.get("children"))

        visit(blocks)
        return refs

    def _document_edit_style_context_prompt(self, edit_request: dict[str, Any], original_text: str) -> str:
        request_text = "\n".join(
            str(edit_request.get(key) or "")
            for key in ("edit_requirements", "raw_edit_text")
        )
        if not self._document_edit_needs_style_context(request_text):
            return ""
        try:
            from selfmedia.style import StylePolishRequest
            from selfmedia.style.context_loader import load_style_context
        except Exception:
            return "style_context_unavailable: selfmedia.style context loader not importable"
        platform = self._document_edit_style_platform(request_text + "\n" + str(original_text or ""))
        content_type = "title" if re.search(r"标题|封面", request_text) else "general"
        goal = "文档定向修改中的表达润色；只提供平台机制、账号记忆和 CreativePattern 上下文，不写 style_polish_runs"
        try:
            context = load_style_context(
                StylePolishRequest(
                    raw_text=request_text[:2000],
                    platform=platform,
                    content_type=content_type,
                    goal=goal,
                ),
                tenant_id=str(current_session_tenant_id()),
            )
        except Exception as exc:
            return f"style_context_unavailable: {exc}"
        payload = context.to_dict() if hasattr(context, "to_dict") else {}
        media_context = payload.get("media_context") if isinstance(payload.get("media_context"), dict) else {}
        platform_mechanism = payload.get("platform_mechanism") if isinstance(payload.get("platform_mechanism"), dict) else {}
        compact = {
            "style_target_type": "feishu_docx_target",
            "redirect_to": "document_edit",
            "source": "style_polish_context_reuse",
            "loaded": media_context.get("loaded") or {},
            "media_memory_prompt": str(media_context.get("prompt") or "")[:3000],
            "platform_mechanism": {
                "platform": platform_mechanism.get("platform") or platform,
                "baseline_summary": platform_mechanism.get("baseline_summary") or "",
                "forbidden_claim_patterns": platform_mechanism.get("forbidden_claim_patterns") or [],
            },
            "style_defaults": payload.get("style_defaults") or {},
            "anti_patterns": payload.get("anti_patterns") or [],
            "source_trace": payload.get("source_trace") or [],
            "write_boundary": "Only document_edit may overwrite Feishu Docx; do not create style_polish_runs or CreativePattern records.",
        }
        return json.dumps(compact, ensure_ascii=False, default=str)

    def _document_edit_needs_style_context(self, text: str) -> bool:
        return bool(re.search(r"网感|去\s*AI\s*味|AI腔|改标题|标题|封面|润色|文案优化|小红书文案|抖音文案|口语|像本人|不像硬广", str(text or ""), re.I))

    def _document_edit_style_platform(self, text: str) -> str:
        if "小红书" in str(text or ""):
            return "小红书"
        if "抖音" in str(text or ""):
            return "抖音"
        return ""

    def _enrich_document_edit_family_contract(self, source: dict[str, Any]) -> dict[str, Any]:
        text = str(source.get("text") or "")
        document_family = "generic_docx"
        producer_capability = "unknown"
        family_contract_id = "document_edit.generic_docx"
        provenance = "generic_default"
        if self._document_edit_matches_shooting_execution_contract(text, source.get("root_blocks") or []):
            document_family = "shooting_execution"
            producer_capability = "shooting_execution_plan"
            family_contract_id = "document_edit.shooting_execution.creation_run"
            provenance = "document_structure_contract"
        elif self._document_edit_matches_commercial_contract(text, source.get("root_blocks") or []):
            document_family = "commercial_delivery"
            producer_capability = "commercial_delivery_draft"
            family_contract_id = "document_edit.commercial_delivery.COM01"
            provenance = "document_structure_contract"
        elif self._document_edit_matches_creation_contract(text, source.get("root_blocks") or []):
            document_family = "creation"
            producer_capability = "media_creation"
            family_contract_id = "document_edit.creation_docx"
            provenance = "document_structure_contract"
        existing_family = str(source.get("document_family") or "").strip()
        if existing_family and existing_family not in {"generic_docx", "unknown"}:
            document_family = existing_family
            provenance = "source_explicit_metadata"
        existing_capability = str(source.get("producer_capability") or "").strip()
        existing_contract = str(source.get("family_contract_id") or "").strip()
        existing_provenance = str(source.get("document_family_provenance") or "").strip()
        if existing_capability:
            producer_capability = existing_capability
        if existing_contract:
            family_contract_id = existing_contract
        if existing_provenance:
            provenance = existing_provenance
        source.update(
            {
                "document_family": document_family,
                "producer_capability": producer_capability,
                "family_contract_id": family_contract_id,
                "document_family_provenance": provenance,
                "family_requirements_checked": source.get("family_requirements_checked") or ["generic_readback"],
                "not_commercial_delivery_document": document_family != "commercial_delivery",
                "COM01": source.get("COM01") or ("pending_resolution" if document_family == "commercial_delivery" else "not_commercial_delivery_document"),
            }
        )
        return source

    def _document_edit_matches_shooting_execution_contract(self, text: str, root_blocks: Any) -> bool:
        text_blob = str(text or "")
        headings = self._document_edit_heading_text(root_blocks)
        title_match = "拍摄执行 -" in text_blob or "拍摄执行 -" in headings
        markers = ("分镜脚本", "路线图", "必拍镜头清单", "发布包")
        return title_match and all(marker in text_blob or marker in headings for marker in markers)

    def _document_edit_matches_commercial_contract(self, text: str, root_blocks: Any) -> bool:
        required = {"作品信息", "作品内容", "PR备注"}
        script_markers = {"图片脚本", "分镜脚本"}
        text_blob = str(text or "")
        if required.issubset(set(marker for marker in required if marker in text_blob)) and any(marker in text_blob for marker in script_markers):
            return True
        headings = self._document_edit_heading_text(root_blocks)
        return all(marker in headings for marker in required) and any(marker in headings for marker in script_markers)

    def _document_edit_matches_creation_contract(self, text: str, root_blocks: Any) -> bool:
        stable_markers = {"分镜脚本", "图片脚本", "创作方案", "拍摄方案", "发布建议", "证据附录"}
        text_blob = str(text or "")
        if sum(1 for marker in stable_markers if marker in text_blob) >= 2:
            return True
        heading_text = self._document_edit_heading_text(root_blocks)
        return sum(1 for marker in stable_markers if marker in heading_text) >= 2

    def _document_edit_heading_text(self, root_blocks: Any) -> str:
        headings: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                block_type = self._coerce_document_edit_int(value.get("block_type"))
                if block_type in range(3, 12):
                    headings.append(str(value.get("text") or ""))
                for child in value.get("children") or []:
                    visit(child)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(root_blocks)
        return "\n".join(headings)

    @staticmethod
    def _coerce_document_edit_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _document_edit_native_table_count(self, blocks: Any) -> int:
        count = 0

        def visit(value: Any) -> None:
            nonlocal count
            if isinstance(value, dict):
                if value.get("block_type") == 31 or value.get("kind") == "table":
                    count += 1
                for child in value.get("children") or []:
                    visit(child)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(blocks)
        return count

    def _resolve_document_edit_commercial_delivery_record(self, source: dict[str, Any], read_bitable_record: Any) -> dict[str, Any]:
        if not callable(read_bitable_record):
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": "商单交付文档需要先唯一映射 COM01 记录，但当前飞书服务缺少 read_bitable_record，已停止写入。",
            }
        table_url_resolver = getattr(self, "_commercial_delivery_table_url", None)
        refs_resolver = getattr(self, "_commercial_delivery_bitable_refs", None)
        if not callable(table_url_resolver) or not callable(refs_resolver) or not hasattr(self.feishu_service, "_request"):
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": "商单交付文档需要唯一映射 COM01 记录，但当前运行时缺少商单交付表解析能力，已停止写入。",
            }
        try:
            table_url = table_url_resolver()
            app_token, table_id, resolved_url = refs_resolver(table_url)
            records = self._document_edit_list_bitable_records(app_token, table_id)
        except Exception as exc:
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": f"商单交付 COM01 记录定位失败：{exc}",
            }
        document_id = str(source.get("document_id") or "").strip()
        doc_url = str(source.get("url") or source.get("doc_url") or source.get("target_doc_url") or "").strip()
        matches = [
            record
            for record in records
            if self._document_edit_commercial_record_matches(record, doc_url=doc_url, document_id=document_id)
        ]
        if len(matches) != 1:
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": f"商单交付文档无法唯一映射 COM01 记录：匹配到 {len(matches)} 条，已停止写入。",
                "match_count": len(matches),
                "document_id": document_id,
                "doc_url": doc_url,
            }
        record = matches[0]
        record_id = str(record.get("record_id") or "")
        if not record_id:
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": "商单交付 COM01 记录缺少 record_id，已停止写入。",
            }
        return {
            "ok": True,
            "status": "commercial_delivery_record_resolved",
            "app_token": app_token,
            "table_id": table_id,
            "table_url": resolved_url,
            "record_id": record_id,
            "fields": record.get("fields") or {},
            "document_id": document_id,
            "doc_url": doc_url,
        }

    def _document_edit_list_bitable_records(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            payload = self.feishu_service._request("GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params=params)
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            batch = data.get("items") if isinstance(data, dict) else []
            if isinstance(batch, list):
                records.extend(item for item in batch if isinstance(item, dict))
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                break
        return records

    def _document_edit_commercial_record_matches(self, record: dict[str, Any], *, doc_url: str, document_id: str) -> bool:
        fields = record.get("fields") if isinstance(record, dict) else {}
        if not isinstance(fields, dict):
            return False
        field_text = self._document_edit_plain_text(fields)
        return bool((document_id and document_id in field_text) or (doc_url and doc_url in field_text))

    def _sync_document_edit_commercial_delivery_record(
        self,
        source: dict[str, Any],
        llm_result: dict[str, Any],
        content: str,
        doc_readback: dict[str, Any],
    ) -> dict[str, Any]:
        record = source.get("commercial_delivery_record")
        if not isinstance(record, dict) or not record.get("ok"):
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": "商单交付文档必须先唯一映射 COM01 记录，已停止 COM01 同步。",
            }
        fields = self._document_edit_commercial_delivery_sync_fields(source, llm_result, content)
        if not fields:
            return {
                "ok": False,
                "status": "commercial_delivery_record_sync_empty",
                "reply": "商单交付文档修改后缺少可同步的 COM01 字段，已停止报告成功。",
            }
        try:
            app_token = str(record.get("app_token") or "")
            table_id = str(record.get("table_id") or "")
            record_id = str(record.get("record_id") or "")
            field_types = self._commercial_delivery_field_types(app_token, table_id)
            ensure_options = getattr(self, "_ensure_commercial_delivery_select_options", None)
            if callable(ensure_options):
                ensure_options(app_token, table_id, fields)
                field_types = self._commercial_delivery_field_types(app_token, table_id)
            coerce = getattr(self, "_commercial_delivery_coerce_value", None)
            if not callable(coerce):
                return {
                    "ok": False,
                    "status": "commercial_delivery_record_sync_failed",
                    "reply": "商单交付 COM01 同步缺少字段类型转换能力。",
                }
            payload_fields = {
                name: coerce(value, field_types.get(name))
                for name, value in fields.items()
                if name in field_types and value not in (None, "", [])
            }
            payload_fields = {name: value for name, value in payload_fields.items() if value not in (None, "", [])}
            if not payload_fields:
                return {
                    "ok": False,
                    "status": "commercial_delivery_record_sync_empty",
                    "reply": "商单交付 COM01 同步字段不在当前表结构中或值为空，已停止报告成功。",
                }
            self.feishu_service._request(
                "PUT",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
                json_body={"fields": payload_fields},
            )
            readback = self.feishu_service.read_bitable_record(app_token, table_id, record_id)
        except Exception as exc:
            return {
                "ok": False,
                "status": "commercial_delivery_record_sync_failed",
                "error": f"商单交付 COM01 记录同步失败：{exc}",
            }
        readback_fields = readback.get("fields") if isinstance(readback, dict) else {}
        if not isinstance(readback_fields, dict) or not readback_fields:
            return {
                "ok": False,
                "status": "commercial_delivery_record_readback_failed",
                "reply": "商单交付 COM01 记录写入后读回为空。",
            }
        parity = self._document_edit_commercial_delivery_field_parity(payload_fields, readback_fields)
        if not parity.get("ok"):
            return {
                "ok": False,
                "status": "commercial_delivery_record_parity_failed",
                "reply": "商单交付 COM01 记录写入后读回字段不一致：" + "、".join(parity.get("mismatched_fields") or []),
                "written_fields": sorted(payload_fields),
                "readback": readback,
                "field_parity": parity,
            }
        return {
            "ok": True,
            "status": "commercial_delivery_record_synced",
            "record_id": record_id,
            "table_id": str(record.get("table_id") or ""),
            "written_fields": sorted(payload_fields),
            "readback": readback,
            "field_parity": parity,
            "doc_readback_status": doc_readback.get("status") or "ok",
        }

    def _document_edit_commercial_delivery_field_parity(
        self,
        payload_fields: dict[str, Any],
        readback_fields: dict[str, Any],
    ) -> dict[str, Any]:
        mismatched: list[str] = []
        checked: dict[str, dict[str, str]] = {}
        for name, expected in payload_fields.items():
            actual = readback_fields.get(name)
            expected_text = self._normalize_document_edit_field_text(expected)
            actual_text = self._normalize_document_edit_field_text(actual)
            checked[name] = {"expected": expected_text, "actual": actual_text}
            if expected_text and expected_text != actual_text:
                mismatched.append(name)
        return {"ok": not mismatched, "checked_fields": checked, "mismatched_fields": mismatched}

    def _normalize_document_edit_field_text(self, value: Any) -> str:
        text = self._document_edit_plain_text(value)
        return re.sub(r"\s+", " ", text).strip()

    def _document_edit_commercial_delivery_sync_fields(
        self,
        source: dict[str, Any],
        llm_result: dict[str, Any],
        content: str,
    ) -> dict[str, Any]:
        allowed = {
            "标题",
            "一句话总结",
            "PR备注",
            "初稿时间",
            "发布时间",
            "平台",
            "内容形式",
            "内容规格",
            "脚本类型",
            "博主名称",
            "账号定位",
            "品牌",
            "产品",
        }
        raw = (
            llm_result.get("commercial_delivery_record_fields")
            or llm_result.get("COM01")
            or llm_result.get("record_fields")
            or {}
        )
        fields: dict[str, Any] = {}
        if isinstance(raw, dict):
            for name, value in raw.items():
                key = str(name or "").strip()
                if key in allowed and value not in (None, "", []):
                    fields[key] = value
        structural_content_spec = self._document_edit_content_spec_from_table_ops(llm_result)
        if structural_content_spec:
            fields.setdefault("内容规格", structural_content_spec)
        doc_url = str(source.get("url") or source.get("doc_url") or source.get("target_doc_url") or "").strip()
        document_id = str(source.get("document_id") or "").strip()
        if doc_url:
            fields["作品初稿链接"] = doc_url
        if document_id:
            fields["文档ID"] = document_id
        if content:
            fields["来源输入摘要"] = str(content).strip()[:500]
        return fields

    def _document_edit_content_spec_from_table_ops(self, llm_result: dict[str, Any]) -> str:
        explicit_specs: list[str] = []
        minimum_rows: list[int] = []
        for item in llm_result.get("operations") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("op") or item.get("operation") or "") != "insert_table_row":
                continue
            content_spec = str(item.get("content_spec") or "").strip()
            if content_spec:
                explicit_specs.append(content_spec)
            try:
                minimum = int(item.get("minimum_rows") or 0)
            except (TypeError, ValueError):
                minimum = 0
            if minimum > 0:
                minimum_rows.append(minimum)
        if explicit_specs:
            return explicit_specs[-1]
        if minimum_rows:
            return f"图文至少{max(minimum_rows)}张"
        return ""

    def _document_edit_plain_text(self, value: Any) -> str:
        parts: list[str] = []

        def visit(item: Any) -> None:
            if item in (None, "", []):
                return
            if isinstance(item, dict):
                for key in ("text", "link", "name", "value", "url", "document_id"):
                    if item.get(key) not in (None, "", []):
                        visit(item.get(key))
                for child in item.values():
                    if isinstance(child, (dict, list, tuple)):
                        visit(child)
                return
            if isinstance(item, (list, tuple, set)):
                for child in item:
                    visit(child)
                return
            parts.append(str(item))

        visit(value)
        return "\n".join(parts)

    def _document_edit_family_readback(self, source: dict[str, Any], readback: dict[str, Any]) -> dict[str, Any]:
        document_family = str(source.get("document_family") or "generic_docx")
        if document_family == "commercial_delivery":
            sync = source.get("commercial_delivery_sync") if isinstance(source.get("commercial_delivery_sync"), dict) else {}
            if sync.get("ok"):
                checked = list(readback.get("family_requirements_checked") or [])
                for item in ("generic_docx_readback", "commercial_delivery_COM01_readback"):
                    if item not in checked:
                        checked.append(item)
                return {
                    "ok": True,
                    "status": "family_readback_ok",
                    "document_family": document_family,
                    "family_requirements_checked": checked,
                    "COM01": sync,
                    "native_table_count": readback.get("native_table_count", source.get("native_table_count") or 0),
                    "markdown_table_residue_found": bool(readback.get("markdown_table_residue_found")),
                }
            return {
                "ok": False,
                "status": "commercial_delivery_record_unresolved",
                "reply": "商单交付文档必须完成 COM01 记录同步和 readback 后才能报告成功。",
            }
        checks = ["generic_docx_readback", "no_patch_residue"]
        if document_family in {"creation", "shooting_execution"}:
            checks.append("block_type=31")
        for item in readback.get("family_requirements_checked") or []:
            if item not in checks:
                checks.append(item)
        return {
            "ok": bool(readback.get("ok")),
            "status": "family_readback_ok" if readback.get("ok") else "family_readback_failed",
            "document_family": document_family,
            "family_requirements_checked": checks,
            "native_table_count": readback.get("native_table_count", source.get("native_table_count") or 0),
            "markdown_table_residue_found": bool(readback.get("markdown_table_residue_found")),
        }

    def _document_edit_snapshot_hint(self, source: dict[str, Any]) -> str:
        snapshot_path = str(source.get("snapshot_path") or "").strip()
        return f"\n恢复快照：{snapshot_path}" if snapshot_path else ""

    def _build_document_edit_request(self, message: Message) -> dict[str, Any]:
        doc_url, target_source = self._extract_document_edit_target_url(message)
        raw_text = self._document_edit_text_without_target(message.body, doc_url)
        fields = self._parse_document_edit_fields(raw_text)
        edit_requirements = fields.get("修改要求") or fields.get("要求") or fields.get("修改") or self._document_edit_body_without_labels(raw_text)
        target_sections: list[str] = []
        optional_constraints = fields.get("约束") or fields.get("约束（选填）") or fields.get("限制") or fields.get("边界") or fields.get("注意")
        preserve_constraints = self._split_document_edit_list(optional_constraints or "")
        forbidden_changes: list[str] = []
        return {
            "target_doc_url": doc_url,
            "target_source": target_source,
            "edit_requirements": str(edit_requirements or "").strip(),
            "target_sections": target_sections,
            "preserve_constraints": preserve_constraints,
            "forbidden_changes": forbidden_changes,
            "raw_edit_text": raw_text,
            "created_at": format_display_time(message.created_at),
        }

    def _extract_document_edit_target_url(self, message: Message) -> tuple[str, str]:
        body_url = self._extract_first_feishu_document_url(message.body)
        if body_url:
            return body_url, "explicit_body_url"
        metadata = message.metadata or {}
        for key in (
            "target_doc_url",
            "target_document_url",
            "replied_document_url",
            "reply_document_url",
            "replied_doc_url",
            "quoted_document_url",
            "parent_document_url",
        ):
            found = self._extract_first_feishu_document_url(metadata.get(key))
            if found:
                return found, "replied_document"
        for key in ("replied_message", "quoted_message", "parent_message", "reply", "quote"):
            found = self._extract_first_feishu_document_url(metadata.get(key))
            if found:
                return found, "replied_document"
        return "", ""

    def _metadata_pick(self, metadata: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = metadata.get(key)
            if value not in (None, "", [], {}):
                return value
        return ""

    def _extract_first_feishu_document_url(self, value: Any) -> str:
        if isinstance(value, dict):
            priority_keys = (
                "target_doc_url",
                "target_document_url",
                "document_url",
                "doc_url",
                "feishu_doc",
                "url",
                "link",
                "text",
                "content",
                "raw_text",
                "message",
                "reply",
                "quote",
                "quoted_message",
                "replied_message",
                "parent_message",
                "raw_event",
            )
            for key in priority_keys:
                if key in value:
                    found = self._extract_first_feishu_document_url(value.get(key))
                    if found:
                        return found
            for child in value.values():
                found = self._extract_first_feishu_document_url(child)
                if found:
                    return found
            return ""
        if isinstance(value, (list, tuple)):
            for item in value:
                found = self._extract_first_feishu_document_url(item)
                if found:
                    return found
            return ""
        text = str(value or "")
        for match in re.finditer(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", text):
            url = match.group(0).strip()
            lowered = url.lower()
            if ("feishu.cn" in lowered or "larksuite.com" in lowered) and re.search(r"/(?:wiki|docx|doc|docs)/", lowered):
                return self._trim_attached_document_scope_suffix(text, match.end(), url)
        return ""

    @staticmethod
    def _trim_attached_document_scope_suffix(text: str, url_end: int, url: str) -> str:
        token_match = re.search(r"/(?:wiki|docx|doc|docs)/([A-Za-z0-9_-]+)$", url, re.I)
        if not token_match:
            return url
        token = token_match.group(1)
        attached_scope = text[url_end:]
        numeric_suffix = token[FEISHU_DOCUMENT_TOKEN_LENGTH:]
        if (
            len(token) > FEISHU_DOCUMENT_TOKEN_LENGTH
            and numeric_suffix.isdigit()
            and re.match(r"^(?:秒|分钟|分|小时|帧)", attached_scope)
        ):
            return url[: -len(numeric_suffix)]
        return url

    def _document_edit_text_without_target(self, body: str, doc_url: str) -> str:
        text = str(body or "").strip()
        if not text:
            return ""
        lines = [line for line in text.splitlines() if doc_url not in line]
        stripped = "\n".join(lines).strip()
        stripped = stripped or text.replace(doc_url, "").strip()
        stripped = re.sub(r"^\s*【修改】\s*", "", stripped).strip()
        stripped = re.sub(r"^(?:目标文档链接|文档链接|目标文档|文档|链接)\s*[=:：]\s*", "", stripped).strip()
        return stripped

    def _parse_document_edit_fields(self, text: str) -> dict[str, str]:
        fields: dict[str, list[str]] = {}
        current = ""
        for raw_line in str(text or "").splitlines():
            line = raw_line.rstrip()
            match = re.match(r"^\s*([^：:=]{1,24})\s*[：:=]\s*(.*)$", line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                if key in {"文档链接", "目标文档链接", "目标文档", "链接"}:
                    current = ""
                    continue
                current = key
                fields.setdefault(current, [])
                if value:
                    fields[current].append(value)
                continue
            if current and line.strip():
                fields[current].append(line.strip())
        return {key: "\n".join(value).strip() for key, value in fields.items()}

    def _document_edit_body_without_labels(self, text: str) -> str:
        lines: list[str] = []
        skip_keys = {"文档链接", "目标文档链接", "目标文档", "链接", "约束", "约束（选填）", "限制", "边界", "注意"}
        current_skip = False
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            match = re.match(r"^([^：:=]{1,24})\s*[：:=]\s*(.*)$", line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                current_skip = key in skip_keys
                if key in {"修改要求", "要求", "修改"} and value:
                    lines.append(value)
                elif not current_skip and value:
                    lines.append(value)
                continue
            if not current_skip and line:
                lines.append(line)
        return "\n".join(lines).strip()

    def _split_document_edit_list(self, value: str) -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        parts = re.split(r"[\n,，、；;]+", text)
        return [part.strip("- *\t ") for part in parts if part.strip("- *\t ")]

    def _normalize_document_edit_content(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _patch_like_document_edit_reason(self, content: str) -> str:
        text = str(content or "")
        patch_heading = re.search(
            r"(?m)^\s{0,3}(?:#{1,6}\s*)?(?:补充|用户补充|追加内容|追加记录|修改记录|补丁|新版|v[2-9])\s*[:：]",
            text,
            flags=re.I,
        )
        if patch_heading:
            return "LLM 输出仍像文末补丁或修改记录，没有把修改吸收进原文结构"
        if re.search(r"(?m)^\s{0,3}(?:#{1,6}\s*)?.{0,30}融合版\s*$", text):
            return "LLM 输出保留了独立“融合版”补丁标题"
        return ""
