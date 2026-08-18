from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from common.llm_client import generate_json_from_parts
from common.llm_settings import API_TYPE_OPENCLAW_AGENT, load_profile_llm_settings
from common.model_transport_context import ModelTransportError
from common.llm_validation import LLMValidationContract, register_llm_validation_contract

from .capability_registry import CAPABILITY_REGISTRY, CapabilityDefinition, CapabilityRegistry


SCHEMA_VERSION = "3"
MAX_QUERY_LENGTH = 4000
MAX_MATCHES = 5
SYSTEM_GUIDE_PROFILE = "system_guide"
PLAN_ID_RE = re.compile(r"^capplan_[A-Za-z0-9_-]{16,128}$")
BOT_IDS = {
    "media": "Media bot",
    "daily": "Daily bot",
    "knowledge": "Knowledge bot",
    "social": "Social bot",
    "deepmath": "DeepMath bot",
}


CAPABILITY_MATCHER_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tag_router.capability_matcher.v3",
        profile="strict_structured",
        required_fields=("pathStatus", "needSummary"),
        allowed_fields=frozenset({"pathStatus", "needSummary", "routeExplanation", "steps", "candidates", "clarificationQuestion", "knownParams"}),
        field_types={"pathStatus": str, "needSummary": str},
        non_empty_fields=("pathStatus", "needSummary"),
    )
)

CAPABILITY_CONTINUATION_VALIDATION_CONTRACT = register_llm_validation_contract(
    LLMValidationContract(
        contract_id="tag_router.capability_continuation.v3",
        profile="strict_structured",
        required_fields=("extractedParams", "evidence"),
        allowed_fields=frozenset({"extractedParams", "evidence", "confidence"}),
        field_types={"extractedParams": dict, "evidence": list},
        non_empty_fields=(),
    )
)


class CapabilityMatcherError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


ModelCall = Callable[[str], Mapping[str, Any]]
PlanIdFactory = Callable[[], str]


class CapabilityMatcher:
    """Single read-only semantic matcher for 【说明】 and Media task launch."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry = CAPABILITY_REGISTRY,
        model_call: ModelCall | None = None,
        continuation_model_call: ModelCall | None = None,
        plan_id_factory: PlanIdFactory | None = None,
        **_: Any,
    ) -> None:
        self._registry = registry
        self._model_call = model_call or self._call_system_guide
        self._continuation_model_call = continuation_model_call or model_call or self._call_system_guide_continuation
        self._plan_id_factory = plan_id_factory or self._new_guidance_plan_id

    def match(self, request: Mapping[str, Any]) -> dict[str, Any]:
        query, current_bot = self._parse_request(request)
        allowed_bot_labels = {current_bot}
        if current_bot != "DeepMath bot":
            allowed_bot_labels.add("任意 Bot")
        allowed = tuple(
            definition for definition in self._registry.definitions
            if not current_bot or set(definition.bots) & allowed_bot_labels
        )
        allowed_ids = frozenset(definition.capability_id for definition in allowed)
        exact = self._exact_capability(query)
        if exact is not None and exact.capability_id not in allowed_ids:
            exact = None
        prompt = self._build_prompt(query, current_bot, exact, allowed)
        for attempt in range(2):
            try:
                return self._validated_model_response(
                    self._model_call(prompt),
                    query=query,
                    guidance_plan_id=self._new_plan_id(),
                    locked_capability_id=exact.capability_id if exact else "",
                    allowed_capability_ids=allowed_ids,
                )
            except CapabilityMatcherError as exc:
                if exc.code != "invalid_model_response" or attempt:
                    raise
                prompt += "\n上一轮输出未通过契约：" + exc.message + "。只输出规定 JSON；不得新增字段、不得输出不可用能力、不得伪造证据。"
            except ModelTransportError:
                raise
            except Exception as exc:
                detail = str(exc).strip() or f"{type(exc).__name__}（底层未提供详情）"
                raise CapabilityMatcherError("provider_unavailable", detail) from exc
        raise CapabilityMatcherError("invalid_model_response", "能力匹配返回了无效结构。")

    def compose_continuation(self, plan: Mapping[str, Any], bindings: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(plan, Mapping) or not isinstance(bindings, Mapping):
            raise CapabilityMatcherError("invalid_request", "续接计划和绑定结果必须是对象。")
        plan_id = str(plan.get("guidancePlanId") or plan.get("guidance_plan_id") or "")
        if not PLAN_ID_RE.fullmatch(plan_id):
            raise CapabilityMatcherError("invalid_request", "续接计划缺少有效 guidancePlanId。")
        query = str(plan.get("originalQuery") or plan.get("original_query") or "").strip()
        raw_steps = plan.get("steps")
        if not isinstance(raw_steps, list):
            single = plan.get("step")
            raw_steps = [single] if isinstance(single, Mapping) else []
        target = next((item for item in raw_steps if isinstance(item, Mapping) and item.get("dependsOn")), None)
        if target is None:
            raise CapabilityMatcherError("invalid_request", "续接计划没有等待中的步骤。")
        capability_id = str(target.get("capabilityId") or "")
        variant_id = str(target.get("variantId") or "")
        definition, _ = self._definition_variant(capability_id, variant_id)
        dependency = target.get("dependsOn")
        required_outputs = dependency.get("requiredOutputs") if isinstance(dependency, Mapping) else None
        if not isinstance(required_outputs, list) or any(str(key) not in bindings for key in required_outputs):
            raise CapabilityMatcherError("invalid_request", "续接所需真实上游输出不完整。")
        prompt = "\n".join(
            (
                "你是 OpenClaw 只读能力续接器。只输出 JSON，不调用工具、不执行任务。",
                f"原始需求：{query}",
                "目标能力：" + json.dumps(self._public_definition(definition), ensure_ascii=False),
                "真实绑定输出：" + json.dumps({key: bindings[key] for key in required_outputs}, ensure_ascii=False),
                "输出字段只能是 extractedParams、evidence、confidence。evidence 每项包含 fieldKey（可选）、quote、source=bound_result。",
            )
        )
        try:
            raw = self._continuation_model_call(prompt)
        except CapabilityMatcherError:
            raise
        except ModelTransportError:
            raise
        except Exception as exc:
            raise CapabilityMatcherError("provider_unavailable", str(exc) or "续接模型不可用。") from exc
        if not isinstance(raw, Mapping) or set(raw) - {"extractedParams", "evidence", "confidence"}:
            raise CapabilityMatcherError("invalid_model_response", "续接结果包含未定义字段。")
        step = self._validate_step(
            {
                "order": target.get("order"), "capabilityId": capability_id, "variantId": variant_id,
                "extractedParams": raw.get("extractedParams"), "confidence": raw.get("confidence", 1), "evidence": raw.get("evidence"),
            },
            evidence_sources={str(value) for value in bindings.values()},
        )
        step.pop("dependsOn", None)
        step["copyProjection"] = self._copy_projection(definition, step["extractedParams"], plan_id)
        return step

    def public_catalog(self) -> list[dict[str, Any]]:
        return [self._public_definition(item) for item in self._registry.definitions]

    def _parse_request(self, request: Mapping[str, Any]) -> tuple[str, str]:
        if not isinstance(request, Mapping):
            raise CapabilityMatcherError("invalid_request", "匹配请求必须是对象。")
        if set(request) - {"query", "currentBot", "catalogVersion"}:
            raise CapabilityMatcherError("invalid_request", "匹配请求包含未定义字段。")
        query = request.get("query")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > MAX_QUERY_LENGTH:
            raise CapabilityMatcherError("invalid_request", f"query 长度必须介于 1 和 {MAX_QUERY_LENGTH} 之间。")
        catalog_version = request.get("catalogVersion")
        if catalog_version is not None and catalog_version != self._registry.catalog_version:
            raise CapabilityMatcherError("invalid_request", "能力目录版本已更新，请刷新后重试。")
        current_bot = request.get("currentBot", "")
        if not isinstance(current_bot, str) or current_bot and current_bot not in BOT_IDS:
            raise CapabilityMatcherError("invalid_request", "currentBot 不是受支持的 Bot。")
        return query.strip(), BOT_IDS.get(current_bot, "")

    def _exact_capability(self, query: str) -> CapabilityDefinition | None:
        normalized = query.strip()
        if normalized.startswith("【") and normalized.endswith("】"):
            normalized = normalized[1:-1].strip()
        return self._registry.resolve_alias(normalized)

    def _build_prompt(
        self,
        query: str,
        current_bot: str,
        exact: CapabilityDefinition | None,
        allowed: tuple[CapabilityDefinition, ...],
    ) -> str:
        catalog = [self._public_definition(exact)] if exact else [self._public_definition(item) for item in allowed if item.enabled]
        return "\n".join(
            (
                "你是 OpenClaw 唯一的只读能力拆解器。只做语义匹配和字段提取，不调用工具、不创建任务、不写入任何系统。",
                "只能输出一个 JSON object，不要 Markdown。pathStatus 只能是 matched、ambiguous、needs_clarification。",
                "matched 输出 {pathStatus,needSummary,routeExplanation,steps}；每个 step 只含 order,capabilityId,variantId,extractedParams,confidence,evidence,dependsOn(可选)。",
                "ambiguous 输出 {pathStatus,needSummary,candidates}，至少两个 candidate；candidate 只含 capabilityId,variantId,confidence,reason。",
                "needs_clarification 输出 {pathStatus,needSummary,clarificationQuestion,candidates,knownParams}，只问一个必要问题。",
                "extractedParams 的 key 必须来自能力 fields；不得为缺失事实编造值。",
                "evidence 每项严格使用 {\"fieldKey\":\"对应字段key\",\"quote\":\"用户原文中的连续片段\",\"source\":\"query\"}；fieldKey 可省略，但 quote 和 source 必须存在。禁止使用 text、content 或其他字段替代 quote。",
                "缺少必填字段不应阻止 matched；服务端会重算 issues。not_implemented 能力不得作为首选。多步骤仅在真实依赖时使用 dependsOn。",
                f"当前 Bot：{current_bot or '未指定'}",
                "候选目录：" + json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
                "用户需求：" + query,
            )
        )

    def _validated_model_response(
        self,
        raw: Mapping[str, Any],
        *,
        query: str,
        guidance_plan_id: str,
        locked_capability_id: str,
        allowed_capability_ids: frozenset[str],
    ) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise CapabilityMatcherError("invalid_model_response", "能力匹配返回了无效结构。")
        status = raw.get("pathStatus")
        need_summary = self._text(raw.get("needSummary"), "needSummary", 500)
        if status == "matched":
            if set(raw) != {"pathStatus", "needSummary", "routeExplanation", "steps"}:
                raise CapabilityMatcherError("invalid_model_response", "matched 分支字段不完整或包含未定义字段。")
            route = self._text(raw.get("routeExplanation"), "routeExplanation", 700)
            raw_steps = raw.get("steps")
            if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_MATCHES:
                raise CapabilityMatcherError("invalid_model_response", "matched 必须包含 1 到 5 个步骤。")
            steps = [self._validate_step(item, query=query) for item in raw_steps]
            if any(step["capabilityId"] not in allowed_capability_ids for step in steps):
                raise CapabilityMatcherError("invalid_model_response", "能力不属于当前 Bot。")
            if [step["order"] for step in steps] != list(range(1, len(steps) + 1)):
                raise CapabilityMatcherError("invalid_model_response", "步骤序号必须连续。")
            if locked_capability_id and (len(steps) != 1 or steps[0]["capabilityId"] != locked_capability_id):
                raise CapabilityMatcherError("invalid_model_response", "精确能力请求不能改选其他能力。")
            first_definition = self._registry.get(steps[0]["capabilityId"])
            assert first_definition is not None
            return {
                "schemaVersion": SCHEMA_VERSION, "pathStatus": "matched", "needSummary": need_summary,
                "routeExplanation": route, "guidancePlanId": guidance_plan_id, "steps": steps,
                "copyProjection": self._copy_projection(first_definition, steps[0]["extractedParams"], guidance_plan_id),
            }
        if status == "ambiguous":
            if set(raw) != {"pathStatus", "needSummary", "candidates"}:
                raise CapabilityMatcherError("invalid_model_response", "ambiguous 分支字段无效。")
            candidates = self._validate_candidates(raw.get("candidates"), minimum=2)
            if any(item["capabilityId"] not in allowed_capability_ids for item in candidates):
                raise CapabilityMatcherError("invalid_model_response", "候选能力不属于当前 Bot。")
            return {"schemaVersion": SCHEMA_VERSION, "pathStatus": status, "needSummary": need_summary, "candidates": candidates}
        if status == "needs_clarification":
            if set(raw) != {"pathStatus", "needSummary", "clarificationQuestion", "candidates", "knownParams"}:
                raise CapabilityMatcherError("invalid_model_response", "needs_clarification 分支字段无效。")
            known = raw.get("knownParams")
            if not isinstance(known, Mapping):
                raise CapabilityMatcherError("invalid_model_response", "knownParams 必须是对象。")
            candidates = self._validate_candidates(raw.get("candidates"), minimum=0)
            if any(item["capabilityId"] not in allowed_capability_ids for item in candidates):
                raise CapabilityMatcherError("invalid_model_response", "候选能力不属于当前 Bot。")
            return {
                "schemaVersion": SCHEMA_VERSION, "pathStatus": status, "needSummary": need_summary,
                "clarificationQuestion": self._text(raw.get("clarificationQuestion"), "clarificationQuestion", 300),
                "candidates": candidates, "knownParams": dict(known),
            }
        raise CapabilityMatcherError("invalid_model_response", "能力匹配缺少有效 pathStatus。")

    def _validate_step(
        self,
        raw: Any,
        *,
        query: str = "",
        evidence_sources: set[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw, Mapping) or set(raw) - {"order", "capabilityId", "variantId", "extractedParams", "confidence", "evidence", "dependsOn"}:
            raise CapabilityMatcherError("invalid_model_response", "能力步骤包含未定义字段。")
        try:
            order = int(raw.get("order"))
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise CapabilityMatcherError("invalid_model_response", "步骤序号或置信度无效。") from exc
        if not 1 <= order <= MAX_MATCHES or not 0 <= confidence <= 1:
            raise CapabilityMatcherError("invalid_model_response", "步骤序号或置信度越界。")
        capability_id, variant_id = str(raw.get("capabilityId") or ""), str(raw.get("variantId") or "")
        definition, _ = self._definition_variant(capability_id, variant_id)
        if not definition.enabled:
            raise CapabilityMatcherError("invalid_model_response", "不可执行能力不能作为推荐步骤。")
        params = raw.get("extractedParams")
        if not isinstance(params, Mapping):
            raise CapabilityMatcherError("invalid_model_response", "extractedParams 必须是对象。")
        issues = list(self._registry.validation_issues(capability_id, variant_id, params))
        if any(item["code"] not in {"required", "at_least_one"} for item in issues):
            raise CapabilityMatcherError("invalid_model_response", "提取字段未通过能力契约。")
        evidence = self._validate_evidence(raw.get("evidence"), query=query, evidence_sources=evidence_sources)
        result: dict[str, Any] = {
            "order": order, "capabilityId": capability_id, "variantId": variant_id, "extractedParams": dict(params),
            "confidence": confidence, "evidence": evidence, "issues": issues,
        }
        dependency = raw.get("dependsOn")
        if dependency is not None:
            if not isinstance(dependency, Mapping) or set(dependency) != {"stepOrder", "requiredOutputs"}:
                raise CapabilityMatcherError("invalid_model_response", "步骤依赖结构无效。")
            outputs = dependency.get("requiredOutputs")
            if not isinstance(outputs, list) or not outputs or not all(isinstance(item, str) and item for item in outputs):
                raise CapabilityMatcherError("invalid_model_response", "步骤依赖输出无效。")
            result["dependsOn"] = {"stepOrder": int(dependency["stepOrder"]), "requiredOutputs": outputs}
        return result

    def _validate_candidates(self, raw: Any, *, minimum: int) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not minimum <= len(raw) <= MAX_MATCHES:
            raise CapabilityMatcherError("invalid_model_response", "候选能力数量无效。")
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw:
            if not isinstance(item, Mapping) or set(item) != {"capabilityId", "variantId", "confidence", "reason"}:
                raise CapabilityMatcherError("invalid_model_response", "候选能力结构无效。")
            capability_id, variant_id = str(item["capabilityId"]), str(item["variantId"])
            definition, _ = self._definition_variant(capability_id, variant_id)
            if not definition.enabled or (capability_id, variant_id) in seen:
                raise CapabilityMatcherError("invalid_model_response", "候选能力不可用或重复。")
            confidence = float(item["confidence"])
            if not 0 <= confidence <= 1:
                raise CapabilityMatcherError("invalid_model_response", "候选置信度越界。")
            seen.add((capability_id, variant_id))
            result.append({"capabilityId": capability_id, "variantId": variant_id, "confidence": confidence, "reason": self._text(item["reason"], "reason", 300)})
        return result

    def _validate_evidence(self, raw: Any, *, query: str, evidence_sources: set[str] | None) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            raise CapabilityMatcherError("invalid_model_response", "evidence 必须是数组。")
        result: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, Mapping) or set(item) - {"fieldKey", "quote", "source"} or not {"quote", "source"} <= set(item):
                raise CapabilityMatcherError("invalid_model_response", "证据结构无效。")
            quote, source = str(item["quote"]).strip(), str(item["source"])
            if not quote or source not in {"query", "bound_result"}:
                raise CapabilityMatcherError("invalid_model_response", "证据内容或来源无效。")
            if source == "query" and quote not in query:
                raise CapabilityMatcherError("invalid_model_response", "字段证据无法在用户原文中定位。")
            if source == "bound_result" and evidence_sources is not None and not any(quote in value for value in evidence_sources):
                raise CapabilityMatcherError("invalid_model_response", "字段证据无法在真实上游输出中定位。")
            projected = {"quote": quote, "source": source}
            if item.get("fieldKey"):
                projected["fieldKey"] = str(item["fieldKey"])
            result.append(projected)
        return result

    def _definition_variant(self, capability_id: str, variant_id: str) -> tuple[CapabilityDefinition, Any]:
        definition = self._registry.get(capability_id)
        if definition is None:
            raise CapabilityMatcherError("invalid_model_response", "能力 ID 不存在。")
        variant = next((item for item in definition.variants if item.variant_id == variant_id), None)
        if variant is None:
            raise CapabilityMatcherError("invalid_model_response", "具体操作不存在。")
        return definition, variant

    def _copy_projection(self, definition: CapabilityDefinition, params: Mapping[str, Any], plan_id: str) -> str:
        body = self._registry.render_chat_body(definition.capability_id, params)
        lines = [f"【{definition.label}】", f"路径续接ID：{plan_id}"]
        if body:
            lines.append(body)
        return "\n".join(lines)

    @staticmethod
    def _public_definition(definition: CapabilityDefinition) -> dict[str, Any]:
        return {
            "capabilityId": definition.capability_id, "label": definition.label, "aliases": list(definition.aliases),
            "path": list(definition.hierarchy.path_names), "description": definition.description,
            "status": definition.status, "enabled": definition.enabled, "effect": definition.effect,
            "fields": [{"key": item.key, "label": item.label, "type": item.input_type, "required": item.required, "options": [option.value for option in item.options]} for item in definition.fields],
            "variants": [{"variantId": item.variant_id, "label": item.label, "requiredFields": list(item.required_fields), "requiredAnyOf": [list(group) for group in item.required_any_of], "forbiddenFields": list(item.forbidden_fields), "fieldValues": dict(item.field_values)} for item in definition.variants],
            "produces": list(definition.produces),
        }

    @staticmethod
    def _text(value: Any, field: str, limit: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise CapabilityMatcherError("invalid_model_response", f"{field} 长度无效。")
        return value.strip()

    def _new_plan_id(self) -> str:
        value = str(self._plan_id_factory())
        if not PLAN_ID_RE.fullmatch(value):
            raise CapabilityMatcherError("invalid_model_response", "路径续接 ID 无效。")
        return value

    @staticmethod
    def _new_guidance_plan_id() -> str:
        return f"capplan_{uuid.uuid4().hex}"

    def _call_system_guide(self, prompt: str) -> Mapping[str, Any]:
        return self._call_system_guide_json(prompt, validation_contract=CAPABILITY_MATCHER_VALIDATION_CONTRACT, error_prefix="能力匹配模型输出校验失败")

    def _call_system_guide_continuation(self, prompt: str) -> Mapping[str, Any]:
        return self._call_system_guide_json(prompt, validation_contract=CAPABILITY_CONTINUATION_VALIDATION_CONTRACT, error_prefix="能力续接模型输出校验失败")

    @staticmethod
    def _call_system_guide_json(prompt: str, *, validation_contract: str, error_prefix: str) -> Mapping[str, Any]:
        settings = load_profile_llm_settings(SYSTEM_GUIDE_PROFILE)
        if settings.api_type != API_TYPE_OPENCLAW_AGENT:
            raise CapabilityMatcherError("provider_unavailable", "system_guide 必须通过 canonical OpenClaw OAuth provider 执行只读能力匹配。")
        runtime_agent = str(os.getenv("OPENCLAW_SYSTEM_GUIDE_AGENT") or "").strip()
        if runtime_agent:
            settings = replace(settings, agent=runtime_agent)
        try:
            return generate_json_from_parts(
                [{"text": prompt}], settings, max_retries=1, error_prefix=error_prefix,
                instructions="只输出符合用户请求结构的 JSON object；不要调用工具，不要执行任何任务。",
                validation_contract=validation_contract,
            )
        except ModelTransportError:
            raise
        except Exception as exc:
            detail = str(exc).strip() or f"{type(exc).__name__}（底层未提供详情）"
            code = "invalid_model_response" if detail.startswith(f"{error_prefix}：") else "provider_unavailable"
            raise CapabilityMatcherError(code, detail) from exc
