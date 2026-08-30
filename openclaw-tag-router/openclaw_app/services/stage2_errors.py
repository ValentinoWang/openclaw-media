"""Shared Stage-2 coded-error skeleton and canonical machine-code constants.

Every Stage-2 layer (runtime, external document, writer router, organization
pipeline, artifact state, personal pipeline) raises its own fail-closed error
type so that ``except <LayerError>`` selectivity keeps working at each layer
boundary -- those six classes stay distinct on purpose, because
``stage2_runtime.py`` catches them selectively to gate genuinely different
recovery policies. What used to be duplicated six times was only the
``(code, message)`` skeleton underneath them; that skeleton now lives here
once, and the six layer base classes reparent onto it.

This module is a leaf: it must never import any of the layer modules that
depend on it -- callers pass their own layer-specific exception classes into
the helpers below rather than this module importing them back.
"""

from __future__ import annotations

from typing import NoReturn, Type


IDEMPOTENCY_CONFLICT = "idempotency_conflict"
IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
REVISION_CONFLICT = "revision_conflict"
ARTIFACT_NOT_FOUND = "artifact_not_found"
ARTIFACT_IDENTITY_CONFLICT = "artifact_identity_conflict"


class Stage2CodedError(RuntimeError):
    """Fail-closed error carrying a stable machine ``code`` and ``message``.

    Shared skeleton for every Stage-2 layer error base class. Layers reparent
    onto this instead of each redefining the same two-line ``__init__``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class Stage2StoreConflict(Stage2CodedError):
    """A durable Stage-2 state transition could not be applied safely.

    Shared by the personal and organization store implementations, which
    otherwise defined byte-identical conflict classes:
    ``stage2_personal_store._StoreConflict`` (aliased onto this class) and
    ``stage2_organization_pipeline.OrganizationStoreConflict`` (which also
    keeps its ``OrganizationPipelineError`` base via multiple inheritance, so
    ``except OrganizationPipelineError`` at stage2_runtime.py's catch sites
    keeps matching it).
    """


def raise_pipeline_error(
    exc: Stage2CodedError,
    *,
    layer_error: Type[Stage2CodedError],
    idempotency_conflict: Type[Stage2CodedError] | None = None,
    revision_conflict: Type[Stage2CodedError] | None = None,
) -> NoReturn:
    """Translate a caught store-conflict exception into the calling layer's
    own exception vocabulary.

    This factors the five near-identical
    ``except <StoreConflict> as exc: if exc.code == ...: raise ...`` blocks
    that used to live in stage2_personal_pipeline.py and
    stage2_organization_pipeline.py into one place. ``idempotency_conflict``
    / ``revision_conflict`` codes re-raise the caller's own subclass (so
    ``except IdempotencyConflict`` / ``except RevisionConflict`` at call
    sites and in tests keeps matching the concrete type); every other code
    falls back to ``layer_error(exc.code, exc.message)``, preserving both
    call sites that never special-cased idempotency at all
    (readback_mirror / record_remote_edit_and_readback in
    stage2_organization_pipeline.py, where passing the class is a no-op
    because those code paths cannot actually produce that code) and the two
    personal-pipeline call sites that also special-case ``revision_conflict``.
    """

    if idempotency_conflict is not None and exc.code == IDEMPOTENCY_CONFLICT:
        raise idempotency_conflict() from exc
    if revision_conflict is not None and exc.code == REVISION_CONFLICT:
        raise revision_conflict() from exc
    raise layer_error(exc.code, exc.message) from exc


__all__ = [
    "ARTIFACT_IDENTITY_CONFLICT",
    "ARTIFACT_NOT_FOUND",
    "IDEMPOTENCY_CONFLICT",
    "IDEMPOTENCY_IN_PROGRESS",
    "REVISION_CONFLICT",
    "Stage2CodedError",
    "Stage2StoreConflict",
    "raise_pipeline_error",
]
