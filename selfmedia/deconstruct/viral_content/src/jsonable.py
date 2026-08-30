"""Recursively convert a pydantic model's ``.dict()`` output into plain JSON-able data (SV-07).

schemas.py, multi_signal_schema.py, and evidence/schemas.py each carried
their own copy of this walk. multi_signal_schema.py's version was the only
one with an ``Enum`` branch (needed for its own ``SignalDimensionStatus(str,
Enum)`` field); the other two never had an Enum field to exercise, so
picking up the Enum branch here is a pure increment with no behavior change
for them.

Lives at the package root (a sibling of evidence/, not inside it) rather
than in schemas.py or evidence/schemas.py: evidence/ is a sub-package of
this one, and neither schemas.py nor multi_signal_schema.py imports the
other, so anchoring the shared helper in either of them would introduce an
architecturally backwards or at least unnecessary coupling.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


def jsonable_model_dict(model: BaseModel) -> dict[str, Any]:
    return jsonable(model.dict())


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value
