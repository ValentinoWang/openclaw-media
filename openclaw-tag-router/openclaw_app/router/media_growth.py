from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .tag_router_common import *
from media_vault import MediaVault, MediaVaultError, require_tenant_id
from selfmedia.growth import MEDIA_GROWTH_LABEL_CAPABILITIES, PRESET_FLOWS, TrackRepository, TrackRepositoryError, parse_media_growth_input, resolve_growth_artifact_type, review_growth_artifact, run_media_growth_capability
from ..services.knowledge_evidence_exporter import KnowledgeEvidenceExporter


MEDIA_GROWTH_ALWAYS_TAGS = {"策略", "Brief", "素材", "选题", "拍摄", "检查", "发布包", "复核", "账号", "赛道", "赛道-关系"}
MEDIA_GROWTH_RESEARCH_TAGS = {"调研"}
MEDIA_GROWTH_CONTEXTUAL_TAGS: set[str] = {"复盘"}
MEDIA_GROWTH_TAGS = MEDIA_GROWTH_ALWAYS_TAGS | MEDIA_GROWTH_RESEARCH_TAGS | MEDIA_GROWTH_CONTEXTUAL_TAGS
MEDIA_GROWTH_EVIDENCE_DRIVEN_CAPABILITIES = {"external_research_brief", "creation_decision_brief", "publishing_pack_build"}
MEDIA_GROWTH_LLM_DRIVEN_CAPABILITIES = MEDIA_GROWTH_EVIDENCE_DRIVEN_CAPABILITIES | {"commercial_brief"}


class MediaGrowthMixin:
    def handle_media_growth(self, message: Message) -> TaskResult:
        if message.entry_tag == "复核":
            return self.handle_media_growth_review(message)
        canonical = self._media_growth_capability_id(message)
        if not canonical:
            return TaskResult(ok=False, status="media_growth_contract_failed", reply=f"【{message.entry_tag}】该标签暂未接入 MediaClaw。", task_id="")
        if canonical in {"track_registry_lookup", "track_creator_membership_query"}:
            return self.handle_track_registry(message, canonical_capability_id=canonical)
        if canonical == "creation_checklist_lookup":
            return self.handle_创作检查(
                Message(
                    entry_tag="创作检查",
                    raw_text=f"【创作检查】{message.body}",
                    body=message.body,
                    source=message.source,
                    chat_type=message.chat_type,
                    created_at=message.created_at,
                    metadata=message.metadata,
                )
            )
        if canonical == "work_acceptance_report":
            return self.handle_作品验收(
                Message(
                    entry_tag="作品验收",
                    raw_text=f"【作品验收】{message.body}",
                    body=message.body,
                    source=message.source,
                    chat_type=message.chat_type,
                    created_at=message.created_at,
                    metadata=message.metadata,
                )
            )
        if canonical == "shooting_execution_plan":
            return self.handle_shooting_execution(
                Message(
                    entry_tag="创作-拍摄执行",
                    raw_text=f"【创作-拍摄执行】{message.body}",
                    body=message.body,
                    source=message.source,
                    chat_type=message.chat_type,
                    created_at=message.created_at,
                    metadata=message.metadata,
                )
            )

        try:
            tenant_id = self._media_growth_tenant_id(message)
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        parsed = parse_media_growth_input(message.raw_text)
        platform = parsed.value("平台", "platform")
        account_id = parsed.value("账号", "account", "account_id")
        track_id = parsed.value("赛道", "track", "track_id")
        explicit_preset = parsed.value("流程", "preset", "preset_flow", "flow")
        artifact_refs = parsed.artifact_refs
        vault = MediaVault(tenant_id=tenant_id)
        artifact_types = tuple(resolve_growth_artifact_type(ref, vault=vault) for ref in artifact_refs)
        if artifact_refs and (not artifact_types or any(not artifact_type for artifact_type in artifact_types)):
            return TaskResult(
                ok=False,
                status="media_growth_contract_failed",
                reply=f"【{message.entry_tag}】输入 artifact 引用无法解析，未写入新产物。",
                task_id="",
                extra={"canonical_capability_id": canonical, "artifact_refs": list(artifact_refs)},
            )
        require_typed_evidence = self._media_growth_requires_typed_evidence(canonical, explicit_preset, message.raw_text)
        knowledge_evidence_bundle = None
        growth_json_provider = None
        if require_typed_evidence:
            knowledge_evidence_bundle = self._media_growth_export_knowledge_evidence(message, query=parsed.content_text or message.body)
        if require_typed_evidence or canonical in MEDIA_GROWTH_LLM_DRIVEN_CAPABILITIES:
            growth_json_provider = self._media_growth_json_provider()
        try:
            plan, payload = run_media_growth_capability(
                canonical,
                message.raw_text,
                platform=platform,
                account_id=account_id,
                track_id=track_id,
                input_artifact_ids=artifact_refs,
                input_artifact_types=artifact_types,
                explicit_preset=explicit_preset,
                vault=vault,
                knowledge_evidence_bundle=knowledge_evidence_bundle,
                growth_json_provider=growth_json_provider,
                require_typed_evidence_for_semantic_runs=require_typed_evidence,
            )
        except Exception as exc:
            return TaskResult(ok=False, status="media_growth_failed", reply=f"【{message.entry_tag}】MediaClaw v2 处理失败：{exc}", task_id="")

        runtime_status = str(payload.get("runtime_status") or payload.get("status") or "")
        task_status, ok = self._media_growth_task_status(runtime_status)
        task_id = str(payload.get("artifact_id") or canonical)
        reply = self._render_media_growth_reply(message, plan.to_dict(), payload)
        return TaskResult(
            ok=ok,
            status=task_status,
            reply=reply,
            task_id=task_id,
            local_path=str(payload.get("artifact_uri") or ""),
            extra={
                "canonical_capability_id": canonical,
                "workflow_plan": plan.to_dict(),
                "artifact": payload,
                "review_card": self._media_growth_review_card_meta(payload),
            },
        )

    def handle_track_registry(self, message: Message, *, canonical_capability_id: str = "track_registry_lookup") -> TaskResult:
        parsed = parse_media_growth_input(message.raw_text)
        action = self._track_action(parsed.value("动作", "操作", "能力", "action"), canonical_capability_id)
        try:
            tenant_id = self._media_growth_tenant_id(message)
            repository = self._track_repository(tenant_id)
            if action == "track_query":
                return self._track_query_result(repository, parsed)
            if action == "track_upsert":
                return self._track_upsert_result(
                    repository,
                    parsed,
                    maintainer_authorized=bool(
                        (message.metadata or {}).get("is_maintainer")
                    ),
                )
            if action == "membership_query":
                return self._track_membership_query_result(repository, parsed)
            if action in {"membership_preview", "membership_confirm"}:
                return self._track_membership_result(repository, parsed, confirm=action == "membership_confirm", raw_text=message.raw_text)
        except TrackRepositoryError as exc:
            pending = "pending_manual" in str(exc) or "manual correction" in str(exc)
            return TaskResult(
                ok=False,
                status="track_pending_manual" if pending else "track_operation_failed",
                reply=f"赛道操作未写入：{exc}",
                task_id="",
            )
        except Exception as exc:
            return TaskResult(ok=False, status="track_operation_failed", reply=f"赛道操作失败：{exc}", task_id="")
        return TaskResult(
            ok=False,
            status="track_unknown_action",
            reply="赛道动作仅支持：查询、注册、关系查询、关系预览、关系确认。",
            task_id="",
        )

    def _track_repository(self, tenant_id: str) -> TrackRepository:
        return TrackRepository.from_env(tenant_id=tenant_id)

    @staticmethod
    def _track_action(value: str, canonical_capability_id: str) -> str:
        normalized = re.sub(r"\s+", "", str(value or "")).lower()
        actions = {
            "": "membership_query" if canonical_capability_id == "track_creator_membership_query" else "track_query",
            "查询": "track_query",
            "赛道查询": "track_query",
            "注册": "track_upsert",
            "新增": "track_upsert",
            "更新": "track_upsert",
            "upsert": "track_upsert",
            "关系查询": "membership_query",
            "查询关系": "membership_query",
            "关系预览": "membership_preview",
            "预览关系": "membership_preview",
            "关系确认": "membership_confirm",
            "确认关系": "membership_confirm",
        }
        return actions.get(normalized, "unknown")

    @staticmethod
    def _track_values(value: Any) -> tuple[str, ...]:
        if isinstance(value, (list, tuple)):
            parts = [str(item).strip() for item in value]
        else:
            parts = [item.strip() for item in re.split(r"[,，、;；|\n]", str(value or ""))]
        return tuple(dict.fromkeys(item for item in parts if item))

    def _track_query_result(self, repository: TrackRepository, parsed: Any) -> TaskResult:
        lookup = parsed.value("赛道id", "track_id", "赛道名称", "名称", "赛道", "track") or parsed.content_text
        tracks = repository.list_tracks(include_inactive=True)
        if lookup:
            matched = repository.find_track(lookup)
            tracks = [matched] if matched else []
        if not tracks:
            return TaskResult(ok=True, status="track_registry_listed", reply="暂无匹配的已注册赛道。", task_id="", extra={"tracks": []})
        lines = [f"已注册赛道：{len(tracks)} 条。"]
        for index, track in enumerate(tracks, start=1):
            aliases = "、".join(track.alias_names) or "无"
            platforms = "、".join(track.platform_scope) or "全部"
            lines.append(f"{index}. {track.track_name}；ID={track.track_id}；状态={track.status}；平台={platforms}；别名={aliases}")
        return TaskResult(
            ok=True,
            status="track_registry_listed",
            reply="\n".join(lines),
            task_id=tracks[0].track_id if len(tracks) == 1 else "",
            extra={"tracks": [item.to_dict() for item in tracks]},
        )

    def _track_upsert_result(
        self,
        repository: TrackRepository,
        parsed: Any,
        *,
        maintainer_authorized: bool,
    ) -> TaskResult:
        track_name = parsed.value("赛道名称", "名称", "赛道", "track_name") or parsed.content_text
        if not track_name:
            return TaskResult(ok=False, status="track_missing_required", reply="赛道注册缺少赛道名称，本次未写入。", task_id="")
        payload = {
            "track_id": parsed.value("赛道id", "track_id"),
            "track_name": track_name,
            "parent_track_id": parsed.value("父赛道id", "parent_track_id"),
            "description": parsed.value("描述", "description"),
            "platform_scope": self._track_values(parsed.value("适用平台", "平台", "platform_scope")),
            "status": parsed.value("状态", "status") or "active",
            "alias_names": self._track_values(parsed.value("别名", "别名列表", "alias_names")),
        }
        result = repository.upsert_track(
            payload,
            maintainer_authorized=maintainer_authorized,
        )
        entity = result.get("entity_payload") or payload
        return TaskResult(
            ok=True,
            status="track_registry_upserted",
            reply=f"赛道已注册并读回：{entity.get('track_name')}；ID={entity.get('track_id')}；mode={result.get('mode')}",
            task_id=str(entity.get("track_id") or ""),
            extra={"track_registry": result},
        )

    def _track_membership_query_result(self, repository: TrackRepository, parsed: Any) -> TaskResult:
        lookup = parsed.value("赛道id", "track_id", "赛道名称", "赛道", "track") or parsed.content_text
        track = repository.find_track(lookup) if lookup else None
        if lookup and not track:
            return TaskResult(ok=True, status="track_creator_memberships_listed", reply="未找到对应已注册赛道，因此没有关系记录。", task_id="", extra={"memberships": []})
        memberships = repository.list_memberships(track_id=track.track_id if track else "", include_rejected=True)
        creator_filter = parsed.value("达人档案id", "creator_profile_id")
        if creator_filter:
            memberships = [item for item in memberships if item.creator_profile_id == creator_filter]
        if not memberships:
            return TaskResult(ok=True, status="track_creator_memberships_listed", reply="暂无匹配的赛道-博主关系。", task_id="", extra={"memberships": []})
        lines = [f"赛道-博主关系：{len(memberships)} 条。"]
        for index, item in enumerate(memberships, start=1):
            lines.append(f"{index}. 赛道={item.track_id}；博主={item.account_name_snapshot or item.creator_profile_id}；角色={item.role}；匹配分={item.fit_score}；状态={item.status}")
        return TaskResult(
            ok=True,
            status="track_creator_memberships_listed",
            reply="\n".join(lines),
            task_id=memberships[0].membership_id if len(memberships) == 1 else "",
            extra={"memberships": [item.to_dict() for item in memberships]},
        )

    def _track_membership_result(self, repository: TrackRepository, parsed: Any, *, confirm: bool, raw_text: str) -> TaskResult:
        track_lookup = parsed.value("赛道id", "track_id", "赛道名称", "赛道", "track")
        track = repository.find_track(track_lookup)
        creator_profile_id = parsed.value("达人档案id", "博主档案id", "creator_profile_id")
        profile = repository.get_creator_profile(creator_profile_id)
        evidence_refs = self._track_values(parsed.value("证据", "证据引用", "evidence", "evidence_refs"))
        fit_reason = parsed.value("匹配理由", "理由", "fit_reason")
        role = parsed.value("角色", "赛道角色", "role")
        fit_score_text = parsed.value("匹配分", "匹配度", "fit_score")
        missing: list[str] = []
        if not track:
            missing.append("已注册赛道ID/名称")
        if not profile:
            missing.append("有效达人档案ID")
        if not role:
            missing.append("角色")
        if not fit_score_text:
            missing.append("匹配分")
        if not fit_reason:
            missing.append("匹配理由")
        if not evidence_refs:
            missing.append("证据引用")
        explicit_confirmation = parsed.value("确认", "confirm").strip().lower() in {"是", "确认", "yes", "true", "1"} or "确认写入" in raw_text
        if missing or not confirm or not explicit_confirmation:
            reason = "、".join(missing) if missing else "显式确认（动作=关系确认 且 确认=是）"
            return TaskResult(
                ok=False,
                status="track_creator_membership_pending_manual",
                reply=f"关系仅生成预览，未写入。仍需：{reason}。系统不会从标签、简介或相似度自动猜测关系。",
                task_id="",
                extra={"membership_preview": {"track_id": getattr(track, "track_id", ""), "creator_profile_id": creator_profile_id, "role": role, "fit_score": fit_score_text, "fit_reason": fit_reason, "evidence_refs": list(evidence_refs)}},
            )
        payload = {
            "track_id": track.track_id,
            "creator_profile_id": creator_profile_id,
            "platform": str(profile.get("platform") or ""),
            "author_id": str(profile.get("author_id") or ""),
            "account_name_snapshot": str(profile.get("account_name") or ""),
            "role": role,
            "fit_score": fit_score_text,
            "fit_reason": fit_reason,
            "content_use_case": parsed.value("内容用途", "content_use_case"),
            "business_use_case": parsed.value("商务用途", "business_use_case"),
            "evidence_refs": evidence_refs,
            "source_capability": parsed.value("来源能力", "source_capability") or "track_creator_membership_query",
            "status": parsed.value("状态", "status") or "active",
            "last_evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "metrics_snapshot_id": parsed.value("指标快照id", "metrics_snapshot_id"),
        }
        result = repository.upsert_membership(payload)
        entity = result.get("entity_payload") or payload
        return TaskResult(
            ok=True,
            status="track_creator_membership_confirmed",
            reply=f"赛道-博主关系已确认并读回：关系ID={entity.get('membership_id')}；赛道={track.track_name}；博主={entity.get('account_name_snapshot') or creator_profile_id}。",
            task_id=str(entity.get("membership_id") or ""),
            extra={"track_creator_membership": result},
        )

    def handle_media_growth_review(self, message: Message) -> TaskResult:
        try:
            tenant_id = self._media_growth_tenant_id(message)
        except MediaVaultError as exc:
            return TaskResult(ok=False, status="tenant_context_required", reply=str(exc), task_id="")
        parsed = parse_media_growth_input(message.raw_text)
        artifact_ref = (
            parsed.value("artifact_id", "artifact", "artifact_ref", "source", "source_asset_id", "run_id", "id")
            or (parsed.artifact_refs[0] if parsed.artifact_refs else "")
        )
        action = parsed.value("动作", "操作", "action", "review_action", "结果", "status")
        note = parsed.value("备注", "note", "说明")
        if not action and parsed.content_text:
            action = parsed.content_text
        if not artifact_ref:
            return TaskResult(
                ok=False,
                status="media_growth_review_failed",
                reply="【复核】缺少 artifact_id/source/artifact_ref，未更新 artifact。",
                task_id="",
            )
        if not action:
            return TaskResult(
                ok=False,
                status="media_growth_review_failed",
                reply="【复核】缺少动作。支持：通过、verify/标记 verified、废弃。",
                task_id=artifact_ref,
            )
        reviewer_id = str((message.metadata or {}).get("operator_id") or (message.metadata or {}).get("user_id") or (message.metadata or {}).get("account_id") or "")
        result = review_growth_artifact(
            artifact_ref,
            action=action,
            reviewer_id=reviewer_id,
            note=note,
            vault=MediaVault(tenant_id=tenant_id),
        )
        if not result.get("ok"):
            return TaskResult(
                ok=False,
                status=str(result.get("status") or "media_growth_review_failed"),
                reply=f"【复核】处理失败：{result.get('reason') or result.get('status') or 'unknown error'}",
                task_id=artifact_ref,
                extra={"media_growth_review": result},
            )
        quality_status = str(result.get("quality_status") or "")
        return TaskResult(
            ok=True,
            status=str(result.get("status") or "media_growth_reviewed"),
            reply=f"【复核】已更新 artifact：{result.get('artifact_id')}；quality_status={quality_status}。",
            task_id=str(result.get("artifact_id") or artifact_ref),
            local_path=str(result.get("artifact_uri") or ""),
            extra={"media_growth_review": result},
        )

    def _media_growth_should_handle(self, message: Message) -> bool:
        if self._media_growth_requested_web_capability(message):
            return True
        if message.entry_tag in MEDIA_GROWTH_ALWAYS_TAGS:
            return True
        if message.entry_tag in MEDIA_GROWTH_RESEARCH_TAGS:
            return self._media_growth_is_media_context(message)
        if message.entry_tag in MEDIA_GROWTH_CONTEXTUAL_TAGS:
            return self._media_growth_is_media_context(message) and self._media_growth_has_explicit_v2_flow(message)
        return False

    @staticmethod
    def _media_growth_tenant_id(message: Message) -> str:
        metadata = message.metadata or {}
        return require_tenant_id(metadata.get("tenant_id"))

    def _media_growth_capability_id(self, message: Message) -> str:
        requested = self._media_growth_requested_web_capability(message)
        if requested:
            return requested
        tag = str(message.entry_tag or "")
        if tag == "检查":
            return self._media_growth_verify_capability_id(message.body)
        capability = TAG_CAPABILITY_MAP.get(tag)
        if capability and capability.canonical_capability_id:
            return capability.canonical_capability_id
        return MEDIA_GROWTH_LABEL_CAPABILITIES.get(tag, "")

    @staticmethod
    def _media_growth_requested_web_capability(message: Message) -> str:
        metadata = message.metadata or {}
        if metadata.get("channel") != "media_web":
            return ""
        requested = str(metadata.get("canonical_capability_id") or "").strip()
        allowed = set(MEDIA_GROWTH_LABEL_CAPABILITIES.values()) | {
            "creation_checklist_lookup",
            "work_acceptance_report",
            "shooting_execution_plan",
            "media_growth_review",
            "track_creator_membership_query",
        }
        return requested if requested in allowed else ""

    def _media_growth_verify_capability_id(self, body: str) -> str:
        text = str(body or "")
        if re.search(r"(publishing_pack_id|发布包ID|发布包|creation_run_id|run_id|创作记录ID)\s*[：:=]", text, flags=re.I):
            return "publish_readiness_gate"
        if re.search(r"(作品内容|稿件|脚本|正文|成片路径|创作要求)\s*[：:=]", text):
            return "work_acceptance_report"
        return "creation_checklist_lookup"

    def _media_growth_is_media_context(self, message: Message) -> bool:
        current_capability_bot = getattr(self, "_current_capability_bot", None)
        if callable(current_capability_bot):
            return current_capability_bot(message) == "Media bot"
        return str((message.metadata or {}).get("account_id") or "").strip() == "media"

    @staticmethod
    def _media_growth_has_explicit_v2_flow(message: Message) -> bool:
        parsed = parse_media_growth_input(message.raw_text)
        flow = parsed.value("流程", "preset", "preset_flow", "flow")
        marker = parsed.value("media_growth", "growth", "v2")
        return flow in {"metrics_to_next_topics"} or marker.lower() in {"1", "true", "yes", "on", "v2"}

    def _media_growth_requires_typed_evidence(self, canonical_capability_id: str, explicit_preset: str, text: str) -> bool:
        capability = str(canonical_capability_id or "").strip()
        if capability in MEDIA_GROWTH_EVIDENCE_DRIVEN_CAPABILITIES:
            return True
        preset = str(explicit_preset or "").strip()
        preset_nodes = PRESET_FLOWS.get(preset, ()) if preset else ()
        if not preset_nodes and capability == "source_asset_intake" and re.search(r"(完整发布方案|一套发布方案|从.+到.+发布|全链路|完整链路)", str(text or "")):
            preset_nodes = PRESET_FLOWS.get("asset_to_topic", ())
        return any(node in MEDIA_GROWTH_EVIDENCE_DRIVEN_CAPABILITIES for node in preset_nodes)

    def _media_growth_export_knowledge_evidence(self, message: Message, *, query: str) -> dict[str, Any]:
        exporter = KnowledgeEvidenceExporter(getattr(self, "content_flow_client", None))
        return exporter.export(message.raw_text, query=query).to_dict()

    def _media_growth_json_provider(self):
        content_flow_client = getattr(self, "content_flow_client", None)
        caller = getattr(content_flow_client, "_call_profile_provider_json", None)
        if not callable(caller):
            return None

        def provider(parts, settings_arg, **kwargs):
            user_content = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
            return caller(
                "media_creation",
                str(kwargs.get("instructions") or ""),
                user_content,
                "MediaClaw evidence JSON",
            )

        return provider

    def _render_media_growth_reply(self, message: Message, plan: dict[str, Any], payload: dict[str, Any]) -> str:
        canonical = str(plan.get("requested_capability_id") or payload.get("source_capability_id") or self._media_growth_capability_id(message))
        lines = [
            f"【{message.entry_tag}】已进入 MediaClaw v2。",
            f"节点：{canonical}",
            f"模式：{plan.get('workflow_mode')}",
        ]
        runtime_status = str(payload.get("runtime_status") or payload.get("status") or "")
        if runtime_status in {"not_implemented", "plan_blocked", "pending_manual", "external_delegation_required", "contract_failed", "execution_failed"}:
            lines.append(f"状态：{self._media_growth_display_status(runtime_status)}")
            if payload.get("blocked_capability_id"):
                lines.append(f"阻塞节点：{payload.get('blocked_capability_id')}")
            reason = self._media_growth_display_reason(payload.get("reason"))
            if runtime_status == "plan_blocked":
                reason = f"{reason} 本次不写入部分产物；请先逐个触发已实装节点，或等阻塞节点接入 canonical runner。"
                node_status_lines = self._media_growth_plan_status_lines(payload)
                if node_status_lines:
                    lines.append("计划节点：")
                    lines.extend(node_status_lines)
                alternative = self._media_growth_executable_alternative_lines(payload)
                if alternative:
                    lines.extend(alternative)
            if runtime_status == "pending_manual":
                reason = f"{reason} 本次未写入 artifact，避免把无证据输入展示到 dashboard。"
            if runtime_status == "external_delegation_required":
                reason = f"{reason} 请触发对应既有标签入口；MediaClaw 不复制该链路。"
                node_status_lines = self._media_growth_plan_status_lines(payload)
                if node_status_lines:
                    lines.append("计划节点：")
                    lines.extend(node_status_lines)
            partial_result_lines = self._media_growth_partial_result_lines(payload)
            if partial_result_lines:
                lines.extend(partial_result_lines)
            lines.append(f"原因：{reason}")
            parse_notice = self._media_growth_parameter_parse_notice(message.raw_text)
            if parse_notice:
                lines.append(parse_notice)
            return "\n".join(lines)

        lines.extend(
            [
                f"artifact_id：{payload.get('artifact_id')}",
                f"artifact_type：{payload.get('artifact_type')}",
                f"artifact：{payload.get('artifact_uri')}",
            ]
        )
        artifact_id = str(payload.get("artifact_id") or "").strip()
        if artifact_id:
            lines.extend(
                [
                    f"通过复核模板：【复核】artifact_id={artifact_id} 动作=通过",
                    f"废弃模板：【复核】artifact_id={artifact_id} 动作=废弃",
                ]
            )
        title = str(payload.get("display_title") or "").strip()
        summary = str(payload.get("display_summary") or "").strip()
        if title:
            lines.append(f"标题：{title}")
        if summary:
            lines.append(f"摘要：{summary}")
        if canonical == "publishing_pack_build":
            lines.append("边界：【发布包】只做发布准备，不自动发布到平台。")
        if canonical == "commercial_brief":
            continuation = self._media_growth_commercial_brief_continuation_lines(payload)
            if continuation:
                lines.extend(continuation)
        if canonical == "source_asset_intake":
            continuation = self._media_growth_source_asset_continuation_lines(payload)
            if continuation:
                lines.extend(continuation)
        parse_notice = self._media_growth_parameter_parse_notice(message.raw_text)
        if parse_notice:
            lines.append(parse_notice)
        return "\n".join(lines)

    @staticmethod
    def _media_growth_display_reason(value: Any) -> str:
        reason = str(value or "当前节点还没有本地执行器").strip()
        lowered = reason.casefold()
        if (
            "knowledgeevidence" in lowered
            or "typed evidence" in lowered
            or "pending_manual" in lowered
            or "evidence_items" in lowered
        ):
            return "可核验的调研证据不足。请补充来源链接、已归档素材或人工确认的事实后再试。"
        return reason

    @staticmethod
    def _media_growth_display_status(value: str) -> str:
        return {
            "not_implemented": "暂未接入执行能力",
            "plan_blocked": "执行计划暂时受阻",
            "pending_manual": "等待人工补充或确认",
            "external_delegation_required": "需要转交既有处理链路",
            "contract_failed": "输入未通过合同校验",
            "execution_failed": "执行失败",
        }.get(str(value or "").strip(), "处理中")

    @staticmethod
    def _media_growth_source_asset_continuation_lines(payload: dict[str, Any]) -> list[str]:
        urls = [str(item).strip() for item in payload.get("urls") or [] if str(item).strip()]
        artifact_ref = str(payload.get("artifact_uri") or payload.get("artifact_id") or "").strip()
        deconstruct_ref = urls[0] if urls else artifact_ref
        constraints = payload.get("request_constraints") if isinstance(payload.get("request_constraints"), dict) else {}
        if not deconstruct_ref:
            return []
        analysis_scope = str(constraints.get("analysis_scope") or "全片").strip()
        time_range = str(constraints.get("analysis_time_range") or "全部").strip()
        focus = [str(item).strip() for item in constraints.get("deconstruction_focus") or [] if str(item).strip()]
        outputs = [str(item).strip() for item in constraints.get("output_types") or [] if str(item).strip()]
        parts = [deconstruct_ref]
        if artifact_ref:
            parts.append(f"source_asset={artifact_ref}")
        if analysis_scope:
            parts.append(f"分析范围={analysis_scope}")
        if time_range:
            parts.append(f"时间片段={time_range}")
        if focus:
            parts.append(f"拆解侧重={'/'.join(focus)}")
        if outputs:
            parts.append(f"输出类型={'/'.join(outputs)}")
        return [
            "默认边界：当前只保存 SourceAsset；不会自动写 02B 或 03。",
            "拆解续跑指令：发送【拆解】" + " ".join(parts),
        ]

    @staticmethod
    def _media_growth_commercial_brief_continuation_lines(payload: dict[str, Any]) -> list[str]:
        artifact_ref = str(payload.get("artifact_uri") or payload.get("artifact_id") or "").strip()
        if not artifact_ref:
            return []
        platforms = [str(item).strip() for item in payload.get("platforms") or [] if str(item).strip()]
        platform = str(payload.get("platform") or (platforms[0] if platforms else "抖音")).strip()
        title = str(payload.get("project_name") or payload.get("display_title") or "品牌 Brief 拍摄").strip()
        locations = payload.get("locations") if isinstance(payload.get("locations"), list) else []
        location_names = [
            str(item.get("name") or item.get("venue") or item.get("location") or "").strip()
            for item in locations
            if isinstance(item, dict)
        ]
        location_text = "；".join(item for item in location_names if item) or "按 Brief 指定展位"
        return [
            "默认边界：当前只整理并落盘 CommercialBrief；不会直接创建 03_CreationRuns。",
            (
                "拍摄执行续跑指令：发送【拍摄】"
                f"source={artifact_ref} 平台={platform} 类型=视频 主体={title} "
                f"场地={location_text} 人物=博主 拍摄目标=按 Brief 生成第一视角展会探秘体验拍摄执行单"
            ),
        ]

    @staticmethod
    def _media_growth_labeled_value(text: str, labels: tuple[str, ...]) -> str:
        return parse_media_growth_input(text).value(*labels)

    @staticmethod
    def _media_growth_plan_status_lines(payload: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for item in payload.get("planned_node_statuses") or []:
            if not isinstance(item, dict):
                continue
            capability_id = str(item.get("canonical_capability_id") or "").strip()
            if not capability_id:
                continue
            implementation_status = str(item.get("implementation_status") or "")
            if implementation_status == "implemented" or item.get("implemented") is True:
                marker = "可执行"
            elif implementation_status == "external":
                marker = "既有链路"
            else:
                marker = "规划中"
            label = MediaGrowthMixin._media_growth_label_for_capability(capability_id)
            suffix = f"（发送【{label}】）" if implementation_status == "external" and label else ""
            lines.append(f"- {marker}：{capability_id}{suffix}")
        return lines

    @staticmethod
    def _media_growth_partial_result_lines(payload: dict[str, Any]) -> list[str]:
        results = [item for item in payload.get("preset_node_results") or [] if isinstance(item, dict)]
        if not results:
            return []
        last = results[-1]
        last_capability = str(last.get("source_capability_id") or "").strip()
        last_ref = str(last.get("artifact_uri") or last.get("artifact_id") or "").strip()
        lines = [
            f"已写入产物：{len(results)} 个",
            f"最后成功：{last_capability or 'unknown'} artifact_id={last.get('artifact_id') or ''}",
        ]
        blocked = str(payload.get("blocked_capability_id") or "").strip()
        label = MediaGrowthMixin._media_growth_label_for_capability(blocked)
        if label and last_ref:
            source_asset_id = MediaGrowthMixin._media_growth_source_asset_id_from_node_results(results)
            source_asset_suffix = f" source_asset_id={source_asset_id}" if source_asset_id else ""
            lines.append(f"续跑指令：发送【{label}】source={last_ref}{source_asset_suffix}")
        elif payload.get("preset_flow") and last_ref:
            lines.append(f"续跑指令：流程={payload.get('preset_flow')} source={last_ref}")
        return lines

    @staticmethod
    def _media_growth_source_asset_id_from_node_results(results: list[dict[str, Any]]) -> str:
        for item in results:
            if not isinstance(item, dict) or item.get("artifact_type") != "SourceAsset":
                continue
            artifact_id = str(item.get("artifact_id") or "").strip()
            if artifact_id:
                return artifact_id
            artifact_uri = str(item.get("artifact_uri") or "").strip()
            match = re.search(r"media://tenants/[1-9][0-9]*/source_assets/([^/\\s]+)", artifact_uri)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _media_growth_executable_alternative_lines(payload: dict[str, Any]) -> list[str]:
        alternative = payload.get("executable_alternative")
        if not isinstance(alternative, dict):
            return []
        description = str(alternative.get("description") or "").strip()
        command = str(alternative.get("command") or "").strip()
        lines: list[str] = []
        if description:
            lines.append(f"可执行子流程：{description}")
        if command:
            lines.append(f"子流程指令：发送{command}")
        return lines

    @staticmethod
    def _media_growth_label_for_capability(capability_id: str) -> str:
        capability = str(capability_id or "").strip()
        if not capability:
            return ""
        preferred_labels = (
            "策略",
            "Brief",
            "素材",
            "调研",
            "选题",
            "创作",
            "拍摄",
            "润色",
            "检查",
            "发布包",
            "复核",
            "复盘",
            "账号",
            "赛道",
            "创作-拍摄执行",
            "创作检查",
            "作品验收",
            "数据复盘",
        )
        capability_map = globals().get("TAG_CAPABILITY_MAP", {})
        for label in preferred_labels:
            item = capability_map.get(label) if isinstance(capability_map, dict) else None
            if item is not None and getattr(item, "canonical_capability_id", "") == capability:
                return label
        if isinstance(capability_map, dict):
            for label, item in capability_map.items():
                if getattr(item, "canonical_capability_id", "") == capability:
                    return str(label)
        return ""

    @staticmethod
    def _media_growth_parameter_parse_notice(text: str) -> str:
        parsed = parse_media_growth_input(text)
        if parsed.params and not parsed.content_text:
            return "提示：纯参数输入会把最后一个 `字段=` 后的自由文本当作该字段值；正文请显式写 `正文=` 或 `草稿=`。"
        return ""

    @staticmethod
    def _media_growth_review_card_meta(payload: dict[str, Any]) -> dict[str, Any]:
        artifact_id = str(payload.get("artifact_id") or "").strip()
        artifact_uri = str(payload.get("artifact_uri") or "").strip()
        artifact_type = str(payload.get("artifact_type") or "").strip()
        if not artifact_id or not artifact_uri or not artifact_type:
            return {}
        return {
            "artifact_id": artifact_id,
            "artifact_ref": artifact_uri,
            "artifact_type": artifact_type,
            "actions": [
                {"action": "approve", "label": "通过复核"},
                {"action": "verify", "label": "标记 verified"},
                {"action": "reject", "label": "废弃"},
            ],
            "next_capability_id": "creation_decision_brief" if artifact_type in {"SourceAsset", "ExternalResearchBrief"} else "",
        }

    @staticmethod
    def _media_growth_task_status(runtime_status: str) -> tuple[str, bool]:
        mapping = {
            "artifact_created": ("media_growth_done", True),
            "not_implemented": ("media_growth_not_implemented", True),
            "plan_blocked": ("media_growth_plan_blocked", True),
            "pending_manual": ("media_growth_pending_manual", True),
            "external_delegation_required": ("media_growth_external_delegation_required", True),
            "contract_failed": ("media_growth_contract_failed", False),
            "execution_failed": ("media_growth_failed", False),
        }
        return mapping.get(runtime_status, ("media_growth_failed", False))
