from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "openclaw-tag-router"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from openclaw_app.services.resource_owner_registry import (  # noqa: E402
    ResourceOwnerConflict,
    ResourceOwnerRegistry,
    require_tenant_id,
)
from openclaw_app.services.tenant_owned_resources import (  # noqa: E402
    TenantOwnedResourceService,
)
from openclaw_app.services.resource_access import ResourceLink  # noqa: E402


@lru_cache(maxsize=1)
def canonical_tenant_owned_resources() -> TenantOwnedResourceService:
    path = Path(
        os.getenv(
            "OPENCLAW_RESOURCE_OWNER_DB_PATH",
            str(Path.home() / ".openclaw/state/resource_owners.sqlite3"),
        )
    )
    return TenantOwnedResourceService(ResourceOwnerRegistry(path))


__all__ = [
    "ResourceOwnerRegistry",
    "ResourceOwnerConflict",
    "ResourceLink",
    "TenantOwnedResourceService",
    "canonical_tenant_owned_resources",
    "require_tenant_id",
]
