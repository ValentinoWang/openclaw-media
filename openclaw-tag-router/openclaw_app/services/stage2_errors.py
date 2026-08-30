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
depend on it.
"""

from __future__ import annotations


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


__all__ = [
    "ARTIFACT_IDENTITY_CONFLICT",
    "ARTIFACT_NOT_FOUND",
    "IDEMPOTENCY_CONFLICT",
    "IDEMPOTENCY_IN_PROGRESS",
    "REVISION_CONFLICT",
    "Stage2CodedError",
]
