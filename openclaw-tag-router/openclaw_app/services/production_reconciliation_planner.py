"""Canonical fail-closed facade for Production Reconciliation planning.

The original v1 implementation is retained in
``production_reconciliation_planner_legacy`` so existing imports and plan
identity remain stable.  This facade closes the locked manifest-ordering
obligation before delegating to the audited v1 planner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import production_reconciliation_planner_legacy as _legacy


# Preserve the historical public and private surface for callers that already
# import constants or validators from this module. The canonical entrypoint is
# overridden below with the additional locked-contract guard.
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)


def _manifest_inventory_paths(request: Any) -> list[str] | None:
    if not isinstance(request, Mapping):
        return None
    target_release = request.get("target_release")
    if not isinstance(target_release, Mapping):
        return None
    manifest = target_release.get("manifest")
    if not isinstance(manifest, Mapping):
        return None
    target = manifest.get("target")
    if not isinstance(target, Mapping):
        return None
    files = target.get("files")
    if type(files) is not list:
        return None
    paths: list[str] = []
    for entry in files:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            return None
        paths.append(str(entry["path"]))
    return paths


def plan_production_reconciliation(request: Mapping[str, object]) -> dict[str, object]:
    """Reject unordered release inventories, then run the audited v1 planner."""

    paths = _manifest_inventory_paths(request)
    if paths is not None and (paths != sorted(paths) or len(paths) != len(set(paths))):
        raise PlannerValidationError("MANIFEST_INVALID")
    return _legacy.plan_production_reconciliation(request)


__all__ = list(getattr(_legacy, "__all__", ()))
if "plan_production_reconciliation" not in __all__:
    __all__.append("plan_production_reconciliation")
