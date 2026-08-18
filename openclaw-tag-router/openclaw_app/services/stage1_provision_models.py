"""Typed, storage-independent contracts for the Release 1B provision ledger."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID


DIGEST_SIZE = 32
MIN_IDEMPOTENCY_KEY_LENGTH = 8
MAX_IDEMPOTENCY_KEY_LENGTH = 160


class Stage1LifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"


# Keep the lifecycle vocabulary shared by installation, Binding generation,
# and member identity contracts so a legacy Binding cannot become active by
# being deserialized into a different enum.
ProvisionState = Stage1LifecycleState
ProvisionStatus = Stage1LifecycleState
ProvisionInstallationStatus = Stage1LifecycleState


class ProvisionRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ProvisionStepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


EnumValue = TypeVar("EnumValue", bound=Enum)


def _coerce_enum(value: EnumValue | str, enum_type: type[EnumValue], field_name: str) -> EnumValue:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} must be a valid {enum_type.__name__} value")


def _check_uuid(value: UUID | None, field_name: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


def _check_text(
    value: str | None,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
    required: bool = False,
) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if value != stripped or not minimum <= len(stripped) <= maximum:
        raise ValueError(
            f"{field_name} must contain {minimum} to {maximum} non-whitespace characters"
        )


def _check_idempotency_key(value: str) -> None:
    _check_text(
        value,
        "idempotency_key",
        minimum=MIN_IDEMPOTENCY_KEY_LENGTH,
        maximum=MAX_IDEMPOTENCY_KEY_LENGTH,
        required=True,
    )


def _check_digest(value: bytes | None, field_name: str, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return
    if not isinstance(value, bytes):
        raise ValueError(f"{field_name} must be bytes")
    if len(value) != DIGEST_SIZE:
        raise ValueError(f"{field_name} must be a 32-byte digest")


def _check_attempt(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("attempt must be a positive integer")


def _check_binding_reference(binding_id: int | None, tenant_id: UUID | None) -> None:
    if binding_id is not None:
        if isinstance(binding_id, bool) or not isinstance(binding_id, int) or binding_id <= 0:
            raise ValueError("binding_id must be a positive integer")
        if tenant_id is None:
            raise ValueError("binding_id requires tenant_id")


def _check_datetime(value: datetime | None, field_name: str) -> None:
    if value is not None and not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")


def _check_time_order(
    start: datetime | None,
    end: datetime | None,
    *,
    start_name: str,
    end_name: str,
) -> None:
    _check_datetime(start, start_name)
    _check_datetime(end, end_name)
    if start is None or end is None:
        return
    try:
        if end < start:
            raise ValueError(f"{end_name} must not precede {start_name}")
    except TypeError as exc:
        raise ValueError(f"{start_name} and {end_name} must use comparable datetimes") from exc


def _check_receipt_identity(
    *,
    installation_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    result_digest: bytes | None,
    attempt: int,
    tenant_id: UUID | None,
    binding_id: int | None,
) -> None:
    _check_uuid(installation_id, "installation_id", required=True)
    _check_idempotency_key(idempotency_key)
    _check_digest(request_digest, "request_digest", required=True)
    _check_digest(result_digest, "result_digest")
    _check_attempt(attempt)
    _check_uuid(tenant_id, "tenant_id")
    _check_binding_reference(binding_id, tenant_id)


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class _ProvisionReceiptMixin:
    def to_dict(self) -> dict[str, Any]:
        return {item.name: _serialize(getattr(self, item.name)) for item in fields(self)}

    def to_mapping(self) -> dict[str, Any]:
        return self.to_dict()

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()

    @property
    def binding_generation_id(self) -> int | None:
        return self.binding_id

    def transition_state(self, state: Stage1LifecycleState | str):
        next_state = _coerce_enum(state, Stage1LifecycleState, "state")
        current_state = self.state
        if current_state is Stage1LifecycleState.REVOKED and next_state is not current_state:
            raise ValueError("REVOKED is terminal")
        updates: dict[str, Any] = {"state": next_state}
        if isinstance(getattr(self, "status", None), Stage1LifecycleState):
            updates["status"] = next_state
        return replace(self, **updates)


@dataclass(frozen=True, slots=True)
class ProvisionInstallationReceipt(_ProvisionReceiptMixin):
    installation_id: UUID
    idempotency_key: str
    request_digest: bytes
    status: Stage1LifecycleState = Stage1LifecycleState.NEEDS_ATTENTION
    state: Stage1LifecycleState | None = None
    attempt: int = 1
    tenant_id: UUID | None = None
    binding_id: int | None = None
    result_digest: bytes | None = None
    installation_receipt_id: UUID | None = None
    installation_event_id: str | None = None
    app_id: str | None = None
    tenant_key: str | None = None
    credential_ref: str | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_receipt_identity(
            installation_id=self.installation_id,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            result_digest=self.result_digest,
            attempt=self.attempt,
            tenant_id=self.tenant_id,
            binding_id=self.binding_id,
        )
        _check_uuid(self.installation_receipt_id, "installation_receipt_id")
        _check_text(self.installation_event_id, "installation_event_id", minimum=1, maximum=256)
        _check_text(self.app_id, "app_id", minimum=1, maximum=256)
        _check_text(self.tenant_key, "tenant_key", minimum=1, maximum=128)
        _check_text(self.credential_ref, "credential_ref", minimum=1, maximum=256)
        _check_datetime(self.observed_at, "observed_at")
        status = _coerce_enum(self.status, Stage1LifecycleState, "status")
        state = status if self.state is None else _coerce_enum(self.state, Stage1LifecycleState, "state")
        if status is not state:
            if state is Stage1LifecycleState.NEEDS_ATTENTION:
                state = status
            elif status is Stage1LifecycleState.NEEDS_ATTENTION:
                status = state
            else:
                raise ValueError("status and state must describe the same lifecycle state")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "state", state)


@dataclass(frozen=True, slots=True)
class ProvisionRunReceipt(_ProvisionReceiptMixin):
    installation_id: UUID
    provision_run_id: UUID
    idempotency_key: str
    request_digest: bytes
    status: ProvisionRunStatus = ProvisionRunStatus.PENDING
    state: Stage1LifecycleState = Stage1LifecycleState.NEEDS_ATTENTION
    tenant_id: UUID | None = None
    binding_id: int | None = None
    finished_at: datetime | None = None
    attempt: int = 1
    result_digest: bytes | None = None
    started_at: datetime | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_receipt_identity(
            installation_id=self.installation_id,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            result_digest=self.result_digest,
            attempt=self.attempt,
            tenant_id=self.tenant_id,
            binding_id=self.binding_id,
        )
        _check_uuid(self.provision_run_id, "provision_run_id", required=True)
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProvisionRunStatus, "status"),
        )
        object.__setattr__(
            self,
            "state",
            _coerce_enum(self.state, Stage1LifecycleState, "state"),
        )
        _check_datetime(self.created_at, "created_at")
        _check_time_order(
            self.started_at,
            self.finished_at,
            start_name="started_at",
            end_name="finished_at",
        )
        if self.finished_at is not None and self.started_at is None:
            raise ValueError("finished_at requires started_at")
        _check_time_order(
            self.created_at,
            self.started_at,
            start_name="created_at",
            end_name="started_at",
        )


@dataclass(frozen=True, slots=True)
class ProvisionStepReceipt(_ProvisionReceiptMixin):
    installation_id: UUID
    provision_run_id: UUID
    step_receipt_id: UUID
    step_key: str
    idempotency_key: str
    request_digest: bytes
    status: ProvisionStepStatus = ProvisionStepStatus.PENDING
    state: Stage1LifecycleState = Stage1LifecycleState.NEEDS_ATTENTION
    attempt: int = 1
    tenant_id: UUID | None = None
    binding_id: int | None = None
    result_digest: bytes | None = None
    external_reference: str | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    recovery_of_receipt_id: UUID | None = None
    started_at: datetime | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_receipt_identity(
            installation_id=self.installation_id,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            result_digest=self.result_digest,
            attempt=self.attempt,
            tenant_id=self.tenant_id,
            binding_id=self.binding_id,
        )
        _check_uuid(self.provision_run_id, "provision_run_id", required=True)
        _check_uuid(self.step_receipt_id, "step_receipt_id", required=True)
        _check_text(self.step_key, "step_key", minimum=1, maximum=160, required=True)
        _check_text(self.external_reference, "external_reference", minimum=1, maximum=512)
        _check_text(self.failure_code, "failure_code", minimum=1, maximum=160)
        _check_uuid(self.recovery_of_receipt_id, "recovery_of_receipt_id")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProvisionStepStatus, "status"),
        )
        object.__setattr__(
            self,
            "state",
            _coerce_enum(self.state, Stage1LifecycleState, "state"),
        )
        _check_datetime(self.created_at, "created_at")
        _check_time_order(
            self.started_at,
            self.finished_at,
            start_name="started_at",
            end_name="finished_at",
        )
        if self.finished_at is not None and self.started_at is None:
            raise ValueError("finished_at requires started_at")
        _check_time_order(
            self.created_at,
            self.started_at,
            start_name="created_at",
            end_name="started_at",
        )


__all__ = [
    "ProvisionInstallationReceipt",
    "ProvisionInstallationStatus",
    "ProvisionRunReceipt",
    "ProvisionRunStatus",
    "ProvisionState",
    "ProvisionStatus",
    "ProvisionStepReceipt",
    "ProvisionStepStatus",
    "Stage1LifecycleState",
]
