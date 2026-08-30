from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from common.llm_settings import load_profile_llm_settings
from common.llm_validation import LLMPostValidationError, validate_llm_payload

from .knowledge_evidence_contract import (
    KnowledgeEvidenceBundle,
    KnowledgeEvidenceContractError,
    coerce_knowledge_evidence_bundle,
)
from .llm_contracts import (
    CONTRACT_ID_BY_TASK,
    MAPPING_LIST_FIELDS,
    TASK_LIST_FIELDS,
    TASK_REQUIRED_FIELDS,
)


DEFAULT_GROWTH_LLM_PROFILE = "media_analysis"
GROWTH_LLM_SUCCESS_STATUSES = frozenset(
    {"done", "complete", "completed", "structured", "ready", "success", "succeeded"}
)
GROWTH_JSON_INSTRUCTIONS = (
    "你是一名中文内容增长与运营编辑。你的输出为创作者提供基于已验证证据的增长判断、可执行策略和人工复核所需的风险提示。\n\n"
    "输出协议：\n"
    "只输出一个合法 JSON object，不要输出 Markdown 或解释。不得将 Knowledge bot 的自然语言回复作为证据；"
    "只能使用提供的已类型化 KnowledgeEvidenceBundle evidence_items。收到账号长期上下文时，必须继承其中已验证的账号定位和复盘结论；"
    "上下文缺少时只能在风险字段说明待补材料，不得补造账号事实、实时指标或已经发布的结果。"
    "所有创作者可见字段必须使用自然、具体的中文，禁止英文句式直译或机器腔；JSON 键名保持既有合同。"
)

GrowthJsonProvider = Callable[..., dict[str, Any]]
SettingsLoader = Callable[[str], Any]


# dedup(llm-wrapper-04 + SV-10): the five TASK_* field tables and the
# DECISION_CANDIDATE_*/CHINESE_OUTPUT_MIN_RATIO constants that used to live
# here now live in .llm_contracts, registered as LLMValidationContract
# instances validate_llm_payload() dispatches to (see
# _task_payload_validation_error below and llm_contracts.py's module
# docstring). TASK_LIST_FIELDS, TASK_REQUIRED_FIELDS and MAPPING_LIST_FIELDS
# are imported above because _normalize_task_payload_shapes and
# _semantic_repair_part below still need them for shape coercion and repair
# prompts -- neither of which is validation.
#
# Mirrors common.llm_client.generate_json_from_parts's own default inter-attempt
# delay for a non-capacity retry (r6 audit cluster: tight zero-delay retries can
# hammer a rate-limited/at-capacity provider back-to-back). GrowthLLMJsonRunner
# cannot call that shared retry loop directly -- its retry is a semantic
# required-field repair pass over an already-parsed payload via an injected,
# test-substitutable `provider` callable, not a JSON/schema parse retry -- so
# it mirrors the same backoff here instead of duplicating a tight loop.
GROWTH_JSON_RETRY_DELAY_SECONDS = 0.5


@dataclass(frozen=True)
class GrowthLLMJsonRunner:
    provider: GrowthJsonProvider | None = None
    settings: Any | None = None
    settings_loader: SettingsLoader = load_profile_llm_settings
    profile_name: str = DEFAULT_GROWTH_LLM_PROFILE
    max_retries: int = 1
    instructions: str = GROWTH_JSON_INSTRUCTIONS

    def run_json(
        self,
        *,
        task: str,
        prompt: str,
        evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
        parts: Iterable[dict[str, Any]] = (),
        require_evidence: bool = True,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bundle: KnowledgeEvidenceBundle | None = None
        if require_evidence or evidence_bundle is not None:
            bundle = coerce_knowledge_evidence_bundle(evidence_bundle)
        if require_evidence:
            try:
                assert bundle is not None
                bundle.require_ready()
            except KnowledgeEvidenceContractError as exc:
                return _pending_manual(
                    f"知识证据尚未满足本次增长任务条件：{exc}。请补齐可验证资料后重试。",
                    task=task,
                    evidence_bundle=bundle,
                )
        request_parts = _build_request_parts(
            task=task,
            prompt=prompt,
            base_parts=parts,
            evidence_bundle=bundle,
            extra_context=extra_context or {},
        )
        if self.provider is None:
            return _pending_manual(
                "增长内容生成服务暂不可用，未写入语义产物；请检查服务配置后重试。",
                task=task,
                evidence_bundle=bundle,
                blocked_sources=("growth_llm_json_provider",),
            )
        provider = self.provider
        settings = self.settings if self.settings is not None else self.settings_loader(self.profile_name)
        provider_parts = request_parts
        for attempt in range(self.max_retries + 1):
            try:
                payload = provider(
                    provider_parts,
                    settings,
                    max_retries=self.max_retries,
                    error_prefix="增长内容 JSON 校验失败",
                    instructions=self.instructions,
                )
            except Exception:
                return _pending_manual(
                    "增长内容生成服务调用失败，未写入语义产物；请稍后重试或人工补充。",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            if not isinstance(payload, dict):
                return _pending_manual(
                    "增长内容生成服务返回格式无效，未写入语义产物；请人工补充或稍后重试。",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            status = str(payload.get("status") or payload.get("runtime_status") or "").strip()
            if not status:
                return _pending_manual(
                    "增长内容生成服务未返回处理状态，未写入语义产物；请人工确认后重试。",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            if status not in GROWTH_LLM_SUCCESS_STATUSES:
                return _pending_manual(
                    "增长内容生成未完成，未写入语义产物；请人工确认输入和服务状态后重试。",
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=tuple(payload.get("blocked_sources") or ()),
                )
            result = dict(payload)
            result["status"] = "done"
            if "runtime_status" in result:
                result["runtime_status"] = "done"
            result = _normalize_task_payload_shapes(task, result)
            validation_error = _task_payload_validation_error(task, result)
            if not validation_error:
                if bundle is not None:
                    result.setdefault("evidence_bundle_id", bundle.bundle_id)
                    result.setdefault("evidence_status", bundle.status)
                return result
            if attempt >= self.max_retries:
                return _pending_manual(
                    validation_error,
                    task=task,
                    evidence_bundle=bundle,
                    blocked_sources=("growth_llm_json_provider",),
                )
            time.sleep(GROWTH_JSON_RETRY_DELAY_SECONDS)
            provider_parts = [*request_parts, _semantic_repair_part(task, validation_error, result)]
        raise AssertionError("unreachable Growth LLM retry state")


def run_growth_json(
    *,
    task: str,
    prompt: str,
    evidence_bundle: KnowledgeEvidenceBundle | dict[str, Any] | None = None,
    provider: GrowthJsonProvider | None = None,
    settings: Any | None = None,
    require_evidence: bool = True,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runner = GrowthLLMJsonRunner(provider=provider, settings=settings)
    return runner.run_json(
        task=task,
        prompt=prompt,
        evidence_bundle=evidence_bundle,
        require_evidence=require_evidence,
        extra_context=extra_context,
    )


def _build_request_parts(
    *,
    task: str,
    prompt: str,
    base_parts: Iterable[dict[str, Any]],
    evidence_bundle: KnowledgeEvidenceBundle | None,
    extra_context: dict[str, Any],
) -> list[dict[str, Any]]:
    request_parts = [dict(part) for part in base_parts]
    request = {
        "task": str(task or "").strip(),
        "prompt": str(prompt or "").strip(),
        "extra_context": dict(extra_context),
    }
    if evidence_bundle is not None:
        request["knowledge_evidence_bundle"] = evidence_bundle.to_dict()
    request_parts.append(
        {
            "text": (
                "增长内容 JSON 请求：\n"
                + json.dumps(request, ensure_ascii=False, sort_keys=True, indent=2)
            )
        }
    )
    return request_parts


def _semantic_repair_part(task: str, validation_error: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": (
            "上一版 JSON 字段不完整。只返回一个修正后的 JSON object，不要 Markdown 或解释。"
            "保留已有的可验证内容，不得补造证据外事实；没有证据的可选字段才可使用空数组或空对象；必须补齐全部必填字段。\n"
            + json.dumps(
                {
                    "task": task,
                    "validation_error": validation_error,
                    "required_fields": list(TASK_REQUIRED_FIELDS.get(task, ())),
                    "previous_payload": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
    }


def _pending_manual(
    reason: str,
    *,
    task: str,
    evidence_bundle: KnowledgeEvidenceBundle | None,
    blocked_sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    limitations = list(evidence_bundle.limitations) if evidence_bundle is not None else []
    bundle_blocked_sources = list(evidence_bundle.blocked_sources) if evidence_bundle is not None else []
    return {
        "status": "pending_manual",
        "runtime_status": "pending_manual",
        "task": str(task or "").strip(),
        "reason": reason,
        "evidence_bundle_id": evidence_bundle.bundle_id if evidence_bundle is not None else "",
        "evidence_status": evidence_bundle.status if evidence_bundle is not None else "pending_manual",
        "limitations": limitations,
        "blocked_sources": _dedupe((*bundle_blocked_sources, *blocked_sources)),
    }


def _task_payload_validation_error(task: str, payload: dict[str, Any]) -> str:
    # dedup(llm-wrapper-04 + SV-10): dispatches to the registered
    # LLMValidationContract for this task (see .llm_contracts) via the same
    # common.llm_validation.validate_llm_payload() call surface every other
    # LLM JSON consumer in the repo uses, instead of a hand-rolled field-table
    # walk. validate_llm_payload re-raises a validator's own
    # LLMPostValidationError unchanged, so the Chinese error text callers
    # (run_json's _pending_manual reason, _semantic_repair_part) see is
    # unchanged too.
    contract_id = CONTRACT_ID_BY_TASK.get(str(task or "").strip())
    if not contract_id:
        return ""
    try:
        validate_llm_payload(payload, contract_id, context={"task": task})
    except LLMPostValidationError as exc:
        return str(exc)
    return ""


def _normalize_task_payload_shapes(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    mapping_list_fields = set(MAPPING_LIST_FIELDS.get(task, ()))
    for field in TASK_LIST_FIELDS.get(task, ()):
        if field not in result or isinstance(result[field], list):
            continue
        value = result[field]
        if field in mapping_list_fields and isinstance(value, dict):
            result[field] = [value]
        elif field not in mapping_list_fields and isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
            result[field] = [text] if text else []
    if task == "commercial_brief" and "technical_specs" in result and not isinstance(result["technical_specs"], dict):
        value = result["technical_specs"]
        if isinstance(value, list):
            result["technical_specs"] = {"items": value}
        elif isinstance(value, (str, int, float, bool)) and str(value).strip():
            result["technical_specs"] = {"description": str(value).strip()}
    if task == "creation_decision_brief" and isinstance(result.get("topic_candidates"), list):
        normalized_candidates: list[Any] = []
        for candidate in result["topic_candidates"]:
            if not isinstance(candidate, dict):
                normalized_candidates.append(candidate)
                continue
            normalized = dict(candidate)
            pain_point = normalized.get("pain_point") or normalized.get("audience_pain")
            if pain_point is not None:
                normalized["pain_point"] = pain_point
                # Keep the released Growth key readable for existing consumers.
                normalized.setdefault("audience_pain", pain_point)
            normalized_candidates.append(normalized)
        result["topic_candidates"] = normalized_candidates
    return result


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
