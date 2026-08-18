"""DeepMath U5 proposal, card, approval, and executor boundary."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from typing import Any, Callable, Mapping

from .deepmath_approval_store import (
    DeepMathApprovalStore,
    DeepMathApprovalStoreConflict,
    DeepMathApprovalStoreNotFound,
    DeepMathApprovalStoreStale,
    DeepMathApprovalStoreTransitionError,
)
from .deepmath_ceo_thinking_schema import canonical_json, payload_fingerprint


CALLBACK_ACTIONS = frozenset({"approve", "modify", "reject", "save", "cancel", "expire"})
TERMINAL_EXECUTION_STATES = frozenset({"执行成功", "执行失败", "结果未知", "已跳过", "人工处理"})


class DeepMathApprovalServiceError(RuntimeError):
    """Service-level input or configuration error."""


@dataclass(frozen=True)
class DeepMathExecutionClaim:
    item: Mapping[str, Any]

    @property
    def execution_key(self) -> str:
        return str(self.item["execution_key"])

    @property
    def attempt_no(self) -> int:
        return int(self.item["attempt_no"])

    @property
    def payload(self) -> Mapping[str, Any]:
        value = self.item.get("canonical_payload")
        return value if isinstance(value, Mapping) else {}


Executor = Callable[[DeepMathExecutionClaim], Mapping[str, Any] | None]
PeopleResolver = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class DeepMathExecutorRegistry:
    """Small injectable registry; it has no production writers by default."""

    def __init__(self) -> None:
        self._executors: dict[tuple[str, str], Executor] = {}

    def register(self, object_type: str, action: str, executor: Executor) -> None:
        object_type = str(object_type or "").strip()
        action = str(action or "").strip()
        if not object_type or not action or not callable(executor):
            raise ValueError("executor registration is incomplete")
        self._executors[(object_type, action)] = executor

    def resolve(self, item: Mapping[str, Any]) -> Executor | None:
        payload = item.get("canonical_payload")
        if not isinstance(payload, Mapping):
            return None
        value = self._executors.get((str(payload.get("object_type") or ""), str(payload.get("action") or "")))
        return value


class DeepMathApprovalCardRenderer:
    """Render a card whose actions carry structured, non-natural-language facts."""

    def render(self, item: Mapping[str, Any], token: str) -> dict[str, Any]:
        payload = item.get("canonical_payload") if isinstance(item.get("canonical_payload"), Mapping) else {}
        proposal_id = str(item.get("proposal_id") or "")
        proposal_version = int(item.get("proposal_version") or 0)
        approval_id = str(item.get("approval_id") or "")
        fingerprint = str(item.get("payload_sha256") or "")
        common = {
            "openclaw_action": "deepmath_approval",
            "tenant_key": str(item.get("tenant_key") or ""),
            "proposal_id": proposal_id,
            "proposal_version": proposal_version,
            "approval_id": approval_id,
            "payload_sha256": fingerprint,
            "token": token,
        }
        people = payload.get("people_assignment") if isinstance(payload.get("people_assignment"), Mapping) else None
        people_confirmed = people is None or people.get("status") == "confirmed"
        actions = []
        if people_confirmed:
            actions.append(("批准并执行", "approve", "primary"))
        actions.extend([
            ("修改提案", "modify", "default"),
            ("拒绝", "reject", "default"),
            ("仅保存", "save", "default"),
            ("取消", "cancel", "default"),
        ])
        content = [
            f"提案：{proposal_id}  ·  版本：{proposal_version}",
            f"项：{approval_id}",
            f"摘要：{str(payload.get('summary') or '')}",
            f"对象：{str(payload.get('object_type') or '')} / {str(payload.get('action') or '')}",
            f"参数指纹：{fingerprint}",
            f"有效期至：{str(item.get('expires_at') or '')}",
        ]
        if people is not None:
            candidates = people.get("candidates") if isinstance(people.get("candidates"), list) else []
            recommendation = people.get("recommendation") if isinstance(people.get("recommendation"), list) else []
            candidate_by_ref = {
                str(candidate.get("candidate_ref") or ""): candidate
                for candidate in candidates if isinstance(candidate, Mapping)
            }
            lines = []
            for assignment in recommendation:
                if not isinstance(assignment, Mapping):
                    continue
                candidate = candidate_by_ref.get(str(assignment.get("candidate_ref") or ""), {})
                lines.append(
                    f"- {str(assignment.get('role') or '')}: {str(candidate.get('name') or '候选人')}；"
                    f"职责 {str(candidate.get('responsibilities') or '')}；"
                    f"未来7天可分配 {str(candidate.get('declared_hours') or '')}h"
                )
            content.append("人员建议：\n" + ("\n".join(lines) if lines else "暂无可确认建议"))
            content.append("人员状态：" + ("已人工确认" if people_confirmed else "待人工确认（确认后生成新版本）"))

        elements: list[dict[str, Any]] = [{"tag": "markdown", "content": "\n".join(content)}]
        if people is not None and not people_confirmed:
            candidates = people.get("candidates") if isinstance(people.get("candidates"), list) else []
            options = [
                {
                    "text": {"tag": "plain_text", "content": str(candidate.get("name") or "候选人")[:80]},
                    "value": str(candidate.get("candidate_ref") or ""),
                }
                for candidate in candidates
                if isinstance(candidate, Mapping) and str(candidate.get("candidate_ref") or "")
            ]
            fingerprint_value = str(people.get("workload_fingerprint") or "")
            form_elements: list[dict[str, Any]] = [
                {
                    "tag": "select_static",
                    "name": "people_dri",
                    "placeholder": {"tag": "plain_text", "content": "选择 DRI"},
                    "options": options,
                },
                {
                    "tag": "select_static",
                    "name": "people_reviewer",
                    "placeholder": {"tag": "plain_text", "content": "选择 Reviewer（可留空）"},
                    "options": options,
                },
                {
                    "tag": "multi_select_static",
                    "name": "people_participants",
                    "placeholder": {"tag": "plain_text", "content": "选择参与者（可多选）"},
                    "options": options,
                },
                {
                    "tag": "button",
                    "name": "confirm_people",
                    "text": {"tag": "plain_text", "content": "确认人员并生成新版本"},
                    "type": "primary",
                    "action_type": "form_submit",
                    "value": {"action": "modify", "workload_fingerprint": fingerprint_value, **common},
                },
            ]
            elements.append({"tag": "form", "name": "deepmath_people_confirmation", "elements": form_elements})
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": style,
                    "value": {"action": action, **common},
                }
                for label, action, style in actions
            ],
        })
        return {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "DeepMath 待确认提案"}},
            "body": {"elements": elements},
        }


class DeepMathApprovalService:
    """Own the single approval state machine above the canonical store."""

    def __init__(
        self,
        store: DeepMathApprovalStore | str | Path,
        *,
        approver_user_id: str,
        authorized_actor_ids: Mapping[str, Any] | set[str] | tuple[str, ...] | list[str] | frozenset[str] = (),
        executor_registry: DeepMathExecutorRegistry | Mapping[Any, Executor] | Any | None = None,
        token_signing_secret: str | bytes | None = None,
        clock: Callable[[], datetime] | None = None,
        proposal_ttl: timedelta = timedelta(days=7),
        renderer: DeepMathApprovalCardRenderer | None = None,
        people_resolver: PeopleResolver | None = None,
    ):
        self.store = store if isinstance(store, DeepMathApprovalStore) else DeepMathApprovalStore(store)
        self.approver_user_id = str(approver_user_id or "").strip()
        if not self.approver_user_id:
            raise ValueError("approver user id is required")
        actor_values = {str(value).strip() for value in authorized_actor_ids if str(value).strip()}
        if actor_values and actor_values != {self.approver_user_id}:
            raise ValueError("only the configured DeepMath approver may authorize callbacks")
        self.authorized_actor_ids = frozenset({self.approver_user_id})
        self.executor_registry = executor_registry or DeepMathExecutorRegistry()
        if isinstance(token_signing_secret, str):
            token_signing_secret = token_signing_secret.encode("utf-8")
        self.token_signing_secret = bytes(token_signing_secret or b"")
        if not self.token_signing_secret:
            raise ValueError("approval token signing secret is required")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.proposal_ttl = proposal_ttl
        self.renderer = renderer or DeepMathApprovalCardRenderer()
        self.people_resolver = people_resolver

    @staticmethod
    def _people_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        value = payload.get("people_assignment")
        return value if isinstance(value, Mapping) else None

    def _resolve_people(self, selection: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.people_resolver is None:
            raise DeepMathApprovalServiceError("people resolver is unavailable")
        result = self.people_resolver(selection)
        if not isinstance(result, Mapping) or result.get("status") != "accepted":
            raise DeepMathApprovalServiceError(str(result.get("reason") or "people evidence rejected") if isinstance(result, Mapping) else "people evidence rejected")
        assignments = result.get("assignments")
        if not isinstance(assignments, list) or not assignments:
            raise DeepMathApprovalServiceError("people resolution is incomplete")
        return result

    def _confirm_people_payload(self, payload: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any]:
        people = self._people_payload(payload)
        if people is None or people.get("status") != "recommended":
            raise DeepMathApprovalServiceError("people confirmation is not available")
        allowed_refs = {
            str(candidate.get("candidate_ref") or "")
            for candidate in people.get("candidates", [])
            if isinstance(candidate, Mapping)
        }
        assignments = selection.get("assignments")
        if not isinstance(assignments, list) or not assignments:
            raise DeepMathApprovalServiceError("people selection is required")
        selected_refs = {
            str(assignment.get("candidate_ref") or "")
            for assignment in assignments if isinstance(assignment, Mapping)
        }
        if len(selected_refs) != len(assignments) or not selected_refs.issubset(allowed_refs):
            raise DeepMathApprovalServiceError("people selection is outside eligible candidates")
        expected = str(people.get("workload_fingerprint") or "")
        if str(selection.get("workload_fingerprint") or "") != expected:
            raise DeepMathApprovalServiceError("people workload fingerprint is stale")
        resolved = self._resolve_people(selection)
        merged = dict(payload)
        merged["people_assignment"] = {
            "status": "confirmed",
            "workload_fingerprint": str(resolved.get("workload_fingerprint") or ""),
            "candidates": list(people.get("candidates") or []),
            "recommendation": list(assignments),
            "resolved_assignments": list(resolved["assignments"]),
        }
        return merged

    def _people_fresh(self, payload: Mapping[str, Any]) -> bool:
        people = self._people_payload(payload)
        if people is None:
            return True
        if people.get("status") != "confirmed":
            return False
        selection = {
            "workload_fingerprint": people.get("workload_fingerprint"),
            "assignments": people.get("recommendation"),
        }
        try:
            resolved = self._resolve_people(selection)
        except DeepMathApprovalServiceError:
            return False
        return (
            resolved.get("workload_fingerprint") == people.get("workload_fingerprint")
            and resolved.get("assignments") == people.get("resolved_assignments")
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    @staticmethod
    def _safe_text(value: Any, limit: int = 300) -> str:
        return str(value or "").strip()[:limit]

    def _token(self, *, tenant_key: str, proposal_id: str, proposal_version: int, approval_id: str, fingerprint: str, expires_at: str) -> str:
        nonce = secrets.token_urlsafe(32)
        body = canonical_json({
            "tenant_key": tenant_key,
            "proposal_id": proposal_id,
            "proposal_version": proposal_version,
            "approval_id": approval_id,
            "payload_sha256": fingerprint,
            "expires_at": expires_at,
            "nonce": nonce,
        })
        encoded = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
        signature = hmac.new(self.token_signing_secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        return f"dm1.{encoded}.{signature}"

    def _token_valid(self, item: Mapping[str, Any], token: str) -> bool:
        value = str(token or "")
        if not value:
            return False
        try:
            candidate_hash = self.store.hash_token(value)
        except ValueError:
            return False
        if not hmac.compare_digest(candidate_hash, str(item.get("token_hash") or "")):
            return False
        try:
            version, encoded, signature = value.split(".", 2)
            if version != "dm1":
                return False
            expected = hmac.new(self.token_signing_secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return False
            padded = encoded + "=" * (-len(encoded) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
            return False
        return all(
            claims.get(key) == item.get(key)
            for key in ("tenant_key", "proposal_id", "proposal_version", "approval_id", "payload_sha256", "expires_at")
        )

    def _lookup(self, *, tenant_key: str, proposal_id: str, proposal_version: int, approval_id: str, payload_sha256: str, token: str, actor_id: str, require_approver: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        actor_id = str(actor_id or "").strip()
        item = self.store.get_item(
            tenant_key=tenant_key,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            approval_id=approval_id,
        )
        if item is None or not self._token_valid(item, token):
            return None, self._result("unauthorized", "unauthorized", item=item)
        if actor_id not in self.authorized_actor_ids:
            return None, self._result("unauthorized", "unauthorized", item=item)
        if require_approver and actor_id != self.approver_user_id:
            return None, self._result("unauthorized", "unauthorized", item=item)
        if str(payload_sha256 or "") != str(item.get("payload_sha256") or ""):
            return None, self._result("stale_or_expired", "stale_version", item=item)
        current = self.store.get_current_item(
            tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id
        )
        if current is None or int(current.get("proposal_version") or 0) != proposal_version:
            return None, self._result("stale_or_expired", "stale_version", item=item)
        if item.get("proposal_state") == "待确认":
            expires_at = datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
            if expires_at <= self._now():
                expired = self.store.expire_current_item(
                    tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id, now=self._now()
                )
                return None, self._result("stale_or_expired", "expired", item=expired or item)
        return item, None

    def _result(self, status: str, code: str, *, item: Mapping[str, Any] | None = None, replayed: bool = False, card: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": status in {"executed", "replayed", "in_progress", "modified", "rejected", "saved", "cancelled"},
            "status": status,
            "code": code,
            "replayed": replayed,
        }
        if item is not None:
            for key in ("tenant_key", "proposal_id", "proposal_version", "approval_id", "payload_sha256", "proposal_state", "decision_state", "execution_state", "attempt_no", "receipt", "error_code", "external_object_id", "external_url"):
                if key in item and item[key] is not None:
                    result[key] = item[key]
        if card is not None:
            result["card"] = card
        return result

    def create_item(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        approval_id: str,
        payload: Mapping[str, Any],
        expires_at: datetime,
        proposal_version: int = 1,
    ) -> dict[str, Any]:
        canonical = canonical_json(payload)
        fingerprint = payload_fingerprint(payload)
        expires_at_text = self._iso(expires_at)
        token = self._token(
            tenant_key=tenant_key,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            approval_id=approval_id,
            fingerprint=fingerprint,
            expires_at=expires_at_text,
        )
        item = self.store.insert_proposal_item(
            tenant_key=tenant_key,
            proposal_id=proposal_id,
            proposal_version=proposal_version,
            approval_id=approval_id,
            canonical_payload_value=canonical,
            token=token,
            expires_at=expires_at_text,
        )
        if not hmac.compare_digest(str(item.get("token_hash") or ""), self.store.hash_token(token)):
            return {"status": "idempotent_replay", "item": item}
        return {"status": "created", "item": item, "token": token, "card": self.renderer.render(item, token)}

    def create_proposal(
        self,
        *,
        tenant_key: str,
        proposal_id: str,
        items: list[Mapping[str, Any]],
        expires_at: datetime,
    ) -> dict[str, Any]:
        created = []
        for index, payload in enumerate(items, 1):
            approval_id = str(payload.get("approval_id") or f"{proposal_id}-{index}")
            content = {key: value for key, value in payload.items() if key != "approval_id"}
            created.append(
                self.create_item(
                    tenant_key=tenant_key,
                    proposal_id=proposal_id,
                    approval_id=approval_id,
                    payload=content,
                    expires_at=expires_at,
                )
            )
        return {"status": "created", "proposal_id": proposal_id, "items": created}

    def approve(self, *, tenant_key: str, proposal_id: str, proposal_version: int, approval_id: str, payload_sha256: str, token: str, actor_id: str) -> dict[str, Any]:
        item, failure = self._lookup(
            tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version,
            approval_id=approval_id, payload_sha256=payload_sha256, token=token, actor_id=actor_id,
            require_approver=True,
        )
        if failure:
            return failure
        assert item is not None
        payload = item.get("canonical_payload") if isinstance(item.get("canonical_payload"), Mapping) else {}
        if not self._people_fresh(payload):
            return self._result("stale_or_expired", "people_confirmation_required_or_stale", item=item)
        try:
            claimed, claimed_new = self.store.claim_approval(
                tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id,
                expected_version=proposal_version, expected_payload_sha256=payload_sha256,
                actor_id=actor_id, now=self._now(),
            )
        except (DeepMathApprovalStoreStale, DeepMathApprovalStoreNotFound):
            return self._result("stale_or_expired", "stale_version", item=item)
        except DeepMathApprovalStoreTransitionError:
            current = self.store.get_current_item(tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id)
            return self._result("replayed", "already_decided", item=current or item, replayed=True)
        if not claimed_new:
            status = "in_progress" if claimed.get("execution_state") == "执行中" else "replayed"
            return self._result(status, "persisted_receipt" if claimed.get("receipt") is not None else status, item=claimed, replayed=True)

        executor = self._resolve_executor(claimed)
        if executor is None:
            stored = self.store.record_execution(
                tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version,
                approval_id=approval_id, claim_token=str(claimed.get("claim_token") or ""),
                execution_state="人工处理", receipt={"status": "manual", "reason": "executor_not_registered"},
                error_code="executor_not_registered", now=self._now(),
            )
            return self._result("manual", "executor_not_registered", item=stored)
        claim = DeepMathExecutionClaim(claimed)
        try:
            raw_receipt = executor(claim)
            result = raw_receipt if isinstance(raw_receipt, Mapping) else {"status": "success", "receipt": raw_receipt}
            status = str(result.get("status") or "success").strip().lower()
            if status in {"unknown", "result_unknown"}:
                execution_state, code = "结果未知", "result_unknown"
            elif status in {"failed", "failure", "error"}:
                execution_state, code = "执行失败", str(result.get("error_code") or "executor_failed")
            elif status in {"skipped", "skip"}:
                execution_state, code = "已跳过", "skipped"
            else:
                execution_state, code = "执行成功", "ok"
            receipt = result.get("receipt", dict(result))
            stored = self.store.record_execution(
                tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version,
                approval_id=approval_id, claim_token=str(claimed.get("claim_token") or ""),
                execution_state=execution_state, receipt=receipt, error_code=code if code != "ok" else None,
                upstream_request_id=result.get("upstream_request_id"),
                external_object_id=result.get("external_object_id"), external_url=result.get("external_url"),
                last_readback_at=result.get("last_readback_at"), now=self._now(),
            )
            return self._result("executed" if execution_state == "执行成功" else execution_state, code, item=stored)
        except Exception:
            stored = self.store.record_execution(
                tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version,
                approval_id=approval_id, claim_token=str(claimed.get("claim_token") or ""),
                execution_state="结果未知", receipt={"status": "unknown"}, error_code="executor_exception", now=self._now(),
            )
            return self._result("unknown", "executor_exception", item=stored)

    def _resolve_executor(self, item: Mapping[str, Any]) -> Executor | None:
        registry = self.executor_registry
        if hasattr(registry, "resolve"):
            resolved = registry.resolve(item)
            return resolved if callable(resolved) else None
        payload = item.get("canonical_payload") if isinstance(item.get("canonical_payload"), Mapping) else {}
        key = (str(payload.get("object_type") or ""), str(payload.get("action") or ""))
        if isinstance(registry, Mapping):
            candidate = registry.get(key) or registry.get(f"{key[0]}:{key[1]}")
            return candidate if callable(candidate) else None
        return None

    def modify(self, *, tenant_key: str, proposal_id: str, proposal_version: int, approval_id: str, payload_sha256: str, token: str, actor_id: str, new_payload: Mapping[str, Any]) -> dict[str, Any]:
        item, failure = self._lookup(
            tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version,
            approval_id=approval_id, payload_sha256=payload_sha256, token=token, actor_id=actor_id,
        )
        if failure:
            return failure
        assert item is not None
        if set(new_payload) == {"people_selection"} and isinstance(new_payload.get("people_selection"), Mapping):
            current_payload = item.get("canonical_payload") if isinstance(item.get("canonical_payload"), Mapping) else {}
            try:
                new_payload = self._confirm_people_payload(current_payload, new_payload["people_selection"])
            except DeepMathApprovalServiceError:
                return self._result("stale_or_expired", "people_confirmation_rejected", item=item)
        try:
            new_token = self._token(
                tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version + 1,
                approval_id=approval_id, fingerprint=payload_fingerprint(new_payload),
                expires_at=self._iso(self._now() + self.proposal_ttl),
            )
            updated = self.store.replace_current_item(
                tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id,
                expected_version=proposal_version, expected_payload_sha256=payload_sha256,
                new_payload=new_payload, new_token=new_token,
                expires_at=self._now() + self.proposal_ttl, now=self._now(),
            )
        except DeepMathApprovalStoreStale:
            return self._result("stale_or_expired", "stale_version", item=item)
        except DeepMathApprovalStoreTransitionError:
            return self._result("replayed", "already_decided", item=item, replayed=True)
        except DeepMathApprovalStoreConflict:
            return self._result("invalid", "payload_conflict", item=item)
        return self._result("modified", "ok", item=updated, card=self.renderer.render(updated, new_token))

    def _decide(self, *, action: str, tenant_key: str, proposal_id: str, proposal_version: int, approval_id: str, payload_sha256: str, token: str, actor_id: str) -> dict[str, Any]:
        item, failure = self._lookup(
            tenant_key=tenant_key, proposal_id=proposal_id, proposal_version=proposal_version,
            approval_id=approval_id, payload_sha256=payload_sha256, token=token, actor_id=actor_id,
        )
        if failure:
            return failure
        assert item is not None
        mapping = {
            "reject": ("已取消", "已拒绝", "rejected"),
            "save": ("待确认", "仅保存", "saved"),
            "cancel": ("已取消", "仅保存", "cancelled"),
        }
        proposal_state, decision_state, status = mapping[action]
        try:
            stored = self.store.finalize_current_item(
                tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id,
                expected_version=proposal_version, expected_payload_sha256=payload_sha256,
                proposal_state=proposal_state, decision_state=decision_state, actor_id=actor_id, now=self._now(),
            )
        except (DeepMathApprovalStoreStale, DeepMathApprovalStoreNotFound):
            return self._result("stale_or_expired", "stale_version", item=item)
        except DeepMathApprovalStoreTransitionError:
            current = self.store.get_current_item(tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id)
            return self._result("replayed", "already_decided", item=current or item, replayed=True)
        return self._result(status, "ok", item=stored)

    def expire(self, *, tenant_key: str, proposal_id: str, approval_id: str) -> dict[str, Any]:
        item = self.store.expire_current_item(
            tenant_key=tenant_key, proposal_id=proposal_id, approval_id=approval_id, now=self._now()
        )
        if item is None:
            return self._result("not_found", "not_found")
        return self._result("expired", "expired", item=item)

    def handle_callback(self, facts: Mapping[str, Any]) -> dict[str, Any]:
        action = str(facts.get("action") or "").strip()
        if action not in CALLBACK_ACTIONS:
            return self._result("invalid", "unsupported_action")
        if action == "expire":
            return self.expire(
                tenant_key=str(facts.get("tenant_key") or ""),
                proposal_id=str(facts.get("proposal_id") or ""),
                approval_id=str(facts.get("approval_id") or ""),
            )
        try:
            proposal_version = int(facts.get("proposal_version") or 0)
        except (TypeError, ValueError):
            return self._result("invalid", "invalid_version")
        if proposal_version < 1:
            return self._result("invalid", "invalid_version")
        common = {
            "tenant_key": str(facts.get("tenant_key") or ""),
            "proposal_id": str(facts.get("proposal_id") or ""),
            "proposal_version": proposal_version,
            "approval_id": str(facts.get("approval_id") or ""),
            "payload_sha256": str(facts.get("payload_sha256") or ""),
            "token": str(facts.get("token") or ""),
            "actor_id": str(facts.get("actor_id") or ""),
        }
        if action == "approve":
            return self.approve(**common)
        if action == "modify":
            payload = facts.get("new_payload")
            if not isinstance(payload, Mapping):
                return self._result("invalid", "structured_payload_required")
            return self.modify(**common, new_payload=payload)
        return self._decide(action=action, **common)
