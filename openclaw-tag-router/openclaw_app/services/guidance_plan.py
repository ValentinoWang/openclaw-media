"""Canonical v3 state for read-only capability guidance continuations."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from .capability_registry import CAPABILITY_REGISTRY


PLAN_ID_PREFIX = "capplan_"
DEFAULT_TTL = timedelta(hours=24)
MAX_QUERY_LENGTH = 4000
MAX_STEPS = 5
_PLAN_ID_RE = re.compile(r"^capplan_[A-Za-z0-9_-]{16,128}$")


class GuidancePlanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GuidanceOutputSpec:
    binding_key: str
    source_path: tuple[str, ...]


OUTPUT_ALLOWLIST: dict[str, tuple[GuidanceOutputSpec, ...]] = {
    "source_asset_intake": (GuidanceOutputSpec("source_asset_id", ("extra", "artifact", "artifact_id")),),
    "creation_decision_brief": (GuidanceOutputSpec("artifact_id", ("extra", "artifact", "artifact_id")),),
    "external_research_brief": (GuidanceOutputSpec("artifact_id", ("extra", "artifact", "artifact_id")),),
    "viral_deconstruction": (GuidanceOutputSpec("artifact_id", ("task_id",)),),
    "publishing_pack_build": (GuidanceOutputSpec("artifact_id", ("extra", "artifact", "artifact_id")),),
    "selfmedia_creation": (GuidanceOutputSpec("run_id", ("extra", "run_id")),),
    "commercial_delivery_draft": (GuidanceOutputSpec("feishu_doc", ("feishu_doc",)),),
}


@dataclass
class GuidancePlanStep:
    order: int
    capability_id: str
    variant_id: str
    extracted_params: dict[str, Any]
    confidence: float
    evidence: list[dict[str, str]]
    issues: list[dict[str, str]]
    depends_on_order: int | None = None
    required_outputs: tuple[str, ...] = ()
    completed: bool = False
    continuation_ready: bool = True

    def public_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "order": self.order,
            "capabilityId": self.capability_id,
            "variantId": self.variant_id,
            "extractedParams": deepcopy(self.extracted_params),
            "confidence": self.confidence,
            "evidence": deepcopy(self.evidence),
            "issues": deepcopy(self.issues),
        }
        if self.depends_on_order is not None:
            result["dependsOn"] = {"stepOrder": self.depends_on_order, "requiredOutputs": list(self.required_outputs)}
        return result

    @property
    def label(self) -> str:
        definition = CAPABILITY_REGISTRY.get(self.capability_id)
        if definition is None:
            raise GuidancePlanError("invalid_guidance_plan", "计划引用的能力已不存在。")
        return definition.label


@dataclass
class GuidancePlan:
    guidance_plan_id: str
    original_query: str
    current_bot: str
    need_summary: str
    route_explanation: str
    steps: list[GuidancePlanStep]
    created_at: datetime
    expires_at: datetime
    current_step: int
    status: str = "active"
    bindings: dict[int, dict[str, str]] = field(default_factory=dict)
    result_fingerprints: dict[int, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    completion_receipt: dict[str, Any] | None = None

    def public_response(self) -> dict[str, Any]:
        current = self.steps[self.current_step - 1]
        projection = _copy_projection(current, self.guidance_plan_id) if current.continuation_ready else ""
        return {
            "schemaVersion": "3", "pathStatus": "matched", "needSummary": self.need_summary,
            "routeExplanation": self.route_explanation, "guidancePlanId": self.guidance_plan_id,
            "steps": [step.public_dict() for step in self.steps], "copyProjection": projection,
        }


@dataclass(frozen=True)
class ContinuationContext:
    guidance_plan_id: str
    step_order: int
    original_query: str
    current_bot: str
    step: dict[str, Any]
    bindings: dict[str, str]


@dataclass(frozen=True)
class NextReadyCopy:
    guidance_plan_id: str
    step_order: int
    copy_text: str
    response: dict[str, Any]


@dataclass(frozen=True)
class StaleStepRecovery:
    guidance_plan_id: str
    submitted_step_order: int
    submitted_label: str
    current_step_order: int
    current_label: str
    copy_text: str


@dataclass(frozen=True)
class CompletedPlanRecovery:
    guidance_plan_id: str
    submitted_label: str
    receipt: dict[str, Any]
    submitted_text_changed: bool


@dataclass(frozen=True)
class PendingContinuationRecovery:
    guidance_plan_id: str
    submitted_step_order: int
    submitted_label: str
    context: ContinuationContext


def new_guidance_plan_id() -> str:
    return f"{PLAN_ID_PREFIX}{secrets.token_urlsafe(24)}"


class GuidancePlanStore:
    def __init__(self, storage_root: Path | None = None) -> None:
        self._plans: dict[str, GuidancePlan] = {}
        self._lock = RLock()
        self._submission_locks: dict[str, RLock] = {}
        self._storage_root = storage_root
        if storage_root is not None:
            storage_root.mkdir(parents=True, exist_ok=True)
            os.chmod(storage_root, 0o700)

    @property
    def lock(self) -> RLock:
        return self._lock

    def get(self, plan_id: str) -> GuidancePlan | None:
        with self._lock:
            return self._read_file(plan_id) if self._storage_root is not None else self._plans.get(plan_id)

    def put_if_absent(self, plan: GuidancePlan) -> GuidancePlan:
        with self._lock:
            existing = self.get(plan.guidance_plan_id)
            if existing is not None:
                return existing
            self.save(plan)
            return plan

    def save(self, plan: GuidancePlan) -> None:
        with self._lock:
            if self._storage_root is None:
                self._plans[plan.guidance_plan_id] = plan
            else:
                path = self._path(plan.guidance_plan_id)
                temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
                temporary.write_text(json.dumps(_plan_to_storage(plan), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.chmod(temporary, 0o600)
                temporary.replace(path)

    def purge(self, now: datetime) -> int:
        with self._lock:
            if self._storage_root is None:
                expired = [key for key, plan in self._plans.items() if plan.expires_at <= now]
                for key in expired:
                    del self._plans[key]
                return len(expired)
            count = 0
            for path in self._storage_root.glob(f"{PLAN_ID_PREFIX}*.json"):
                plan = self._read_path(path)
                if plan is None or plan.expires_at <= now:
                    path.unlink(missing_ok=True)
                    count += 1
            return count

    @contextmanager
    def submission_guard(self, plan_id: str):
        if not _PLAN_ID_RE.fullmatch(str(plan_id or "")):
            raise GuidancePlanError("guidance_plan_not_found", "guidancePlanId 无效或已失效，请重新匹配。")
        with self._lock:
            thread_lock = self._submission_locks.setdefault(plan_id, RLock())
        with thread_lock:
            if self._storage_root is None:
                yield
                return
            lock_root = self._storage_root / ".submission-locks"
            lock_root.mkdir(parents=True, exist_ok=True)
            lock_path = lock_root / f"{plan_id}.lock"
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, plan_id: str) -> Path:
        if self._storage_root is None or not _PLAN_ID_RE.fullmatch(plan_id):
            raise GuidancePlanError("guidance_plan_not_found", "guidancePlanId 无效或已失效，请重新匹配。")
        return self._storage_root / f"{plan_id}.json"

    def _read_file(self, plan_id: str) -> GuidancePlan | None:
        return self._read_path(self._path(plan_id))

    @staticmethod
    def _read_path(path: Path) -> GuidancePlan | None:
        try:
            return _plan_from_storage(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None


class GuidancePlanService:
    def __init__(self, *, store: GuidancePlanStore | None = None, ttl: timedelta = DEFAULT_TTL, now_factory: Callable[[], datetime] | None = None) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl 必须为正数。")
        self._store = store or GuidancePlanStore()
        self._ttl = ttl
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    @staticmethod
    def new_plan_id() -> str:
        return new_guidance_plan_id()

    def register_match(self, response: Mapping[str, Any], *, query: str, current_bot: str = "") -> dict[str, Any]:
        if not isinstance(response, Mapping):
            raise GuidancePlanError("invalid_guidance_plan", "能力引导结果必须是对象。")
        if response.get("pathStatus") != "matched":
            return deepcopy(dict(response))
        plan = self._plan_from_response(response, query=query, current_bot=current_bot)
        now = self._now()
        plan.created_at, plan.expires_at = now, now + self._ttl
        with self._store.lock:
            self._store.purge(now)
            existing = self._store.get(plan.guidance_plan_id)
            if existing is not None:
                if existing.original_query != plan.original_query or existing.public_response() != plan.public_response():
                    raise GuidancePlanError("guidance_plan_conflict", "guidancePlanId 已被另一份引导计划使用。")
                return existing.public_response()
            self._store.put_if_absent(plan)
        return plan.public_response()

    def get_public_response(self, plan_id: str) -> dict[str, Any]:
        return self._active_plan(plan_id).public_response()

    def current_ready_step(self, plan_id: str) -> int:
        plan = self._active_plan(plan_id)
        step = self._step(plan, plan.current_step)
        if not step.continuation_ready:
            raise GuidancePlanError("guidance_plan_out_of_order", "当前计划没有可执行步骤。")
        return step.order

    @contextmanager
    def submission_guard(self, plan_id: str):
        with self._store.submission_guard(plan_id):
            yield

    def validate_submitted_step(self, plan_id: str, *, tag: str, text: str) -> StaleStepRecovery | PendingContinuationRecovery | CompletedPlanRecovery | None:
        with self._store.lock:
            plan = self._available_plan(plan_id)
            completed = next((item for item in reversed(plan.steps) if item.completed and item.label == tag), None)
            if plan.status == "completed":
                if completed is None or not isinstance(plan.completion_receipt, Mapping):
                    raise GuidancePlanError("guidance_plan_inactive", "引导计划已结束，且没有可恢复的成功回执。")
                return CompletedPlanRecovery(plan_id, tag, deepcopy(dict(plan.completion_receipt)), str(text).strip() != _copy_projection(completed, plan_id))
            step = self._step(plan, plan.current_step)
            if tag != step.label:
                if completed is None:
                    raise GuidancePlanError("guidance_plan_tag_mismatch", f"当前计划应发送【{step.label}】，不能发送【{tag}】。")
                if not step.continuation_ready:
                    return PendingContinuationRecovery(plan_id, completed.order, completed.label, self._continuation_context(plan, step))
                return StaleStepRecovery(plan_id, completed.order, completed.label, step.order, step.label, _copy_projection(step, plan_id))
            if str(text or "").strip() != _copy_projection(step, plan_id):
                raise GuidancePlanError("invalid_guidance_plan", "提交内容与当前结构化计划投影不一致，请重新使用【说明】。")
            return None

    def bind_step_result(self, plan_id: str, *, step_order: int, task_result: Any) -> ContinuationContext | None:
        with self._store.lock:
            plan = self._active_plan(plan_id)
            step = self._step(plan, step_order)
            if step.completed:
                return self._duplicate_result_context(plan, step_order, task_result)
            if plan.current_step != step_order or not step.continuation_ready or not _task_ok(task_result):
                raise GuidancePlanError("guidance_plan_out_of_order", "当前结果不属于计划中可执行的成功步骤。")
            next_step = self._next_step(plan, step_order)
            bindings = self._extract_required_bindings(step.capability_id, task_result, next_step)
            step.completed = True
            plan.bindings[step_order] = bindings
            plan.result_fingerprints[step_order] = tuple(sorted(bindings.items()))
            if next_step is None:
                plan.status = "completed"
                plan.completion_receipt = _task_result_receipt(task_result)
                self._store.save(plan)
                return None
            plan.current_step = next_step.order
            self._store.save(plan)
            return self._continuation_context(plan, next_step)

    def finalize_next_step(self, plan_id: str, *, step_order: int, step: Mapping[str, Any]) -> NextReadyCopy:
        with self._store.lock:
            plan = self._active_plan(plan_id)
            target = self._step(plan, step_order)
            if target.continuation_ready or target.depends_on_order not in plan.bindings:
                raise GuidancePlanError("guidance_plan_out_of_order", "当前步骤不处于等待结构化续接的状态。")
            if step.get("capabilityId") != target.capability_id or step.get("variantId") != target.variant_id:
                raise GuidancePlanError("invalid_guidance_plan", "续接结果改变了计划能力。")
            params = step.get("extractedParams")
            if not isinstance(params, Mapping):
                raise GuidancePlanError("invalid_guidance_plan", "续接结果缺少结构化参数。")
            issues = CAPABILITY_REGISTRY.validation_issues(target.capability_id, target.variant_id, params)
            if any(item["code"] not in {"required", "at_least_one"} for item in issues):
                raise GuidancePlanError("invalid_guidance_plan", "续接参数未通过能力契约。")
            target.extracted_params = dict(params)
            target.evidence = deepcopy(list(step.get("evidence") or []))
            target.confidence = float(step.get("confidence", target.confidence))
            target.issues = list(issues)
            target.continuation_ready = True
            self._store.save(plan)
            projection = _copy_projection(target, plan_id)
            return NextReadyCopy(plan_id, target.order, projection, plan.public_response())

    def purge_expired(self) -> int:
        return self._store.purge(self._now())

    def _plan_from_response(self, response: Mapping[str, Any], *, query: str, current_bot: str) -> GuidancePlan:
        if response.get("schemaVersion") != "3" or response.get("pathStatus") != "matched":
            raise GuidancePlanError("invalid_guidance_plan", "只能登记 capability guidance v3 matched 结果。")
        plan_id = str(response.get("guidancePlanId") or "")
        if not _PLAN_ID_RE.fullmatch(plan_id):
            raise GuidancePlanError("invalid_guidance_plan", "guidancePlanId 无效。")
        raw_steps = response.get("steps")
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
            raise GuidancePlanError("invalid_guidance_plan", "引导计划必须包含 1 到 5 个步骤。")
        steps = [self._step_from_response(item, index) for index, item in enumerate(raw_steps, 1)]
        for index, step in enumerate(steps):
            if index == 0 and step.depends_on_order is not None:
                raise GuidancePlanError("invalid_guidance_plan", "第一步不能依赖上游结果。")
            if index > 0:
                step.continuation_ready = False
                if step.depends_on_order != index:
                    raise GuidancePlanError("invalid_guidance_plan", "后续步骤必须依赖紧邻上一步。")
                allowed = {item.binding_key for item in OUTPUT_ALLOWLIST.get(steps[index - 1].capability_id, ())}
                if not step.required_outputs or not set(step.required_outputs) <= allowed:
                    raise GuidancePlanError("invalid_guidance_plan", "后续步骤声明了不受支持的真实结果依赖。")
        now = self._now()
        return GuidancePlan(
            plan_id, _required_text(query, "query", MAX_QUERY_LENGTH), str(current_bot or ""),
            _required_text(response.get("needSummary"), "needSummary", 500),
            _required_text(response.get("routeExplanation"), "routeExplanation", 800),
            steps, now, now + self._ttl, 1,
        )

    @staticmethod
    def _step_from_response(value: Any, expected_order: int) -> GuidancePlanStep:
        if not isinstance(value, Mapping) or value.get("order") != expected_order:
            raise GuidancePlanError("invalid_guidance_plan", "引导步骤顺序无效。")
        capability_id, variant_id = str(value.get("capabilityId") or ""), str(value.get("variantId") or "")
        definition = CAPABILITY_REGISTRY.get(capability_id)
        if definition is None or not any(item.variant_id == variant_id for item in definition.variants):
            raise GuidancePlanError("invalid_guidance_plan", "引导步骤能力或操作不存在。")
        params, evidence, issues = value.get("extractedParams"), value.get("evidence"), value.get("issues")
        if not isinstance(params, Mapping) or not isinstance(evidence, list) or not isinstance(issues, list):
            raise GuidancePlanError("invalid_guidance_plan", "引导步骤缺少结构化事实。")
        dependency = value.get("dependsOn")
        return GuidancePlanStep(
            expected_order, capability_id, variant_id, dict(params), float(value.get("confidence", 0)), deepcopy(evidence), deepcopy(issues),
            int(dependency["stepOrder"]) if isinstance(dependency, Mapping) else None,
            tuple(str(item) for item in dependency.get("requiredOutputs") or ()) if isinstance(dependency, Mapping) else (),
        )

    def _active_plan(self, plan_id: str) -> GuidancePlan:
        plan = self._available_plan(plan_id)
        if plan.status != "active":
            raise GuidancePlanError("guidance_plan_inactive", "引导计划已结束，不能继续使用。")
        return plan

    def _available_plan(self, plan_id: str) -> GuidancePlan:
        if not _PLAN_ID_RE.fullmatch(str(plan_id or "")):
            raise GuidancePlanError("guidance_plan_not_found", "guidancePlanId 无效或已失效，请重新匹配。")
        plan = self._store.get(plan_id)
        if plan is None:
            raise GuidancePlanError("guidance_plan_not_found", "引导计划不存在或已过期，请重新匹配。")
        if plan.expires_at <= self._now():
            self._store.purge(self._now())
            raise GuidancePlanError("guidance_plan_expired", "引导计划已过期，请重新匹配。")
        return plan

    @staticmethod
    def _step(plan: GuidancePlan, order: int) -> GuidancePlanStep:
        if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= len(plan.steps):
            raise GuidancePlanError("guidance_plan_out_of_order", "步骤编号无效。")
        return plan.steps[order - 1]

    @staticmethod
    def _next_step(plan: GuidancePlan, order: int) -> GuidancePlanStep | None:
        return plan.steps[order] if order < len(plan.steps) else None

    @staticmethod
    def _extract_required_bindings(capability_id: str, task_result: Any, next_step: GuidancePlanStep | None) -> dict[str, str]:
        if next_step is None:
            return {}
        allowed = {item.binding_key: item.source_path for item in OUTPUT_ALLOWLIST.get(capability_id, ())}
        result: dict[str, str] = {}
        for key in next_step.required_outputs:
            path = allowed.get(key)
            value = _read_result_path(task_result, path) if path else None
            if not isinstance(value, str) or not value.strip():
                raise GuidancePlanError("guidance_binding_missing", "上一步没有返回续接所需的真实结果。")
            result[key] = value.strip()
        return result

    def _duplicate_result_context(self, plan: GuidancePlan, order: int, task_result: Any) -> ContinuationContext | None:
        next_step = self._next_step(plan, order)
        if next_step is None:
            return None
        bindings = self._extract_required_bindings(plan.steps[order - 1].capability_id, task_result, next_step)
        if tuple(sorted(bindings.items())) != plan.result_fingerprints.get(order):
            raise GuidancePlanError("guidance_result_conflict", "同一步骤收到不一致的执行结果。")
        return self._continuation_context(plan, next_step)

    @staticmethod
    def _continuation_context(plan: GuidancePlan, step: GuidancePlanStep) -> ContinuationContext:
        return ContinuationContext(plan.guidance_plan_id, step.order, plan.original_query, plan.current_bot, step.public_dict(), deepcopy(plan.bindings.get(step.depends_on_order or 0, {})))

    def _now(self) -> datetime:
        value = self._now_factory()
        if not isinstance(value, datetime):
            raise TypeError("now_factory 必须返回 datetime。")
        return value if value.tzinfo else value.replace(tzinfo=UTC)


def _copy_projection(step: GuidancePlanStep, plan_id: str) -> str:
    definition = CAPABILITY_REGISTRY.get(step.capability_id)
    if definition is None:
        raise GuidancePlanError("invalid_guidance_plan", "计划能力已不存在。")
    body = CAPABILITY_REGISTRY.render_chat_body(step.capability_id, step.extracted_params)
    return "\n".join([f"【{definition.label}】", f"路径续接ID：{plan_id}", *([body] if body else [])])


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise GuidancePlanError("invalid_guidance_plan", f"{field} 长度无效。")
    return value.strip()


def _task_ok(task_result: Any) -> bool:
    return task_result.get("ok") is True if isinstance(task_result, Mapping) else getattr(task_result, "ok", None) is True


def _read_result_path(task_result: Any, path: tuple[str, ...] | None) -> Any:
    current = task_result
    for part in path or ():
        current = current.get(part) if isinstance(current, Mapping) else getattr(current, part, None)
        if current is None:
            return None
    return current


def _task_result_receipt(task_result: Any) -> dict[str, Any]:
    def read(key: str, default: Any = "") -> Any:
        return task_result.get(key, default) if isinstance(task_result, Mapping) else getattr(task_result, key, default)
    return {"ok": read("ok", False) is True, "status": str(read("status") or "completed"), "reply": str(read("reply") or "任务已完成。"), "task_id": str(read("task_id") or ""), "local_path": str(read("local_path") or ""), "feishu_doc": str(read("feishu_doc") or "")}


def _plan_to_storage(plan: GuidancePlan) -> dict[str, Any]:
    return {
        "schemaVersion": "3", "guidancePlanId": plan.guidance_plan_id, "originalQuery": plan.original_query,
        "currentBot": plan.current_bot, "needSummary": plan.need_summary, "routeExplanation": plan.route_explanation,
        "steps": [{**step.public_dict(), "completed": step.completed, "continuationReady": step.continuation_ready} for step in plan.steps],
        "createdAt": plan.created_at.isoformat(), "expiresAt": plan.expires_at.isoformat(), "currentStep": plan.current_step,
        "status": plan.status, "bindings": {str(k): v for k, v in plan.bindings.items()},
        "resultFingerprints": {str(k): [list(pair) for pair in v] for k, v in plan.result_fingerprints.items()},
        "completionReceipt": plan.completion_receipt,
    }


def _plan_from_storage(value: Any) -> GuidancePlan:
    if not isinstance(value, Mapping) or value.get("schemaVersion") != "3":
        raise ValueError("stored guidance plan is not v3")
    raw_steps = value.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("stored plan steps missing")
    steps: list[GuidancePlanStep] = []
    for raw in raw_steps:
        dependency = raw.get("dependsOn") if isinstance(raw, Mapping) else None
        steps.append(GuidancePlanStep(
            int(raw["order"]), str(raw["capabilityId"]), str(raw["variantId"]), dict(raw["extractedParams"]), float(raw["confidence"]),
            list(raw["evidence"]), list(raw["issues"]), int(dependency["stepOrder"]) if isinstance(dependency, Mapping) else None,
            tuple(dependency.get("requiredOutputs") or ()) if isinstance(dependency, Mapping) else (), raw.get("completed") is True, raw.get("continuationReady") is True,
        ))
    bindings = value.get("bindings") or {}
    fingerprints = value.get("resultFingerprints") or {}
    return GuidancePlan(
        str(value["guidancePlanId"]), str(value["originalQuery"]), str(value.get("currentBot") or ""), str(value["needSummary"]), str(value["routeExplanation"]),
        steps, datetime.fromisoformat(str(value["createdAt"])), datetime.fromisoformat(str(value["expiresAt"])), int(value["currentStep"]), str(value.get("status") or "active"),
        {int(k): {str(a): str(b) for a, b in v.items()} for k, v in bindings.items()},
        {int(k): tuple((str(pair[0]), str(pair[1])) for pair in v) for k, v in fingerprints.items()},
        dict(value["completionReceipt"]) if isinstance(value.get("completionReceipt"), Mapping) else None,
    )
