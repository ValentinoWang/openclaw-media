from __future__ import annotations

from pathlib import Path

from .content_os_feishu_projection import FeishuProjectBoardProjectionAdapter
from .content_os_project_lifecycle import ContentOSContractError, read_project_state, transition_project_status
from .content_os_projections import write_project_registry_projection


class ContentOSStateMixin:
    """Compatibility-shaped router entry points backed by the v0.2 SSOT.

    The old implementation changed ``project_registry.md`` cell by cell.  The
    registry is now regenerated only after the project overview transition has
    succeeded, so a partial projection can never become a project state writer.
    """

    def configure_content_os_feishu_project_board(self, client: object | None) -> None:
        """Inject the authorised live board client; ``None`` disables sync."""

        self._content_os_feishu_project_board_adapter = FeishuProjectBoardProjectionAdapter(client) if client is not None else None

    def _sync_content_os_feishu_project_board(self, vault_root: Path, project_id: str) -> dict[str, str | bool] | None:
        """Refresh a derived board row without ever changing the project itself."""

        adapter = getattr(self, "_content_os_feishu_project_board_adapter", None)
        if adapter is None:
            return None
        return adapter.sync(read_project_state(vault_root, project_id))

    def _set_content_os_project_status(
        self,
        project_id: str,
        status: str,
        *,
        actor: str,
        reason: str,
        evidence: set[str] | None = None,
        vault_root: Path | None = None,
    ) -> None:
        vault_root = vault_root or self._content_os_vault_root()
        transition_project_status(
            vault_root,
            project_id,
            to_status=status,
            actor=actor,
            reason=reason,
            evidence=evidence or set(),
        )
        write_project_registry_projection(vault_root)
        self._sync_content_os_feishu_project_board(vault_root, project_id)

    def _update_content_os_project_registry_status(self, project_id: str, status: str, vault_root: Path) -> None:
        """Regenerate the read-only registry; parameters remain for call compatibility."""

        del project_id, status
        write_project_registry_projection(vault_root)

    def _maybe_advance_content_os_status(
        self,
        *,
        project_id: str,
        from_status: str,
        to_status: str,
        actor: str,
        evidence: set[str],
        reason: str,
        vault_root: Path,
    ) -> bool:
        try:
            current = read_project_state(vault_root, project_id)
            if current.status != from_status:
                return False
            transition_project_status(
                vault_root,
                project_id,
                to_status=to_status,
                actor=actor,
                reason=reason,
                evidence=evidence,
            )
        except ContentOSContractError:
            return False
        write_project_registry_projection(vault_root)
        self._sync_content_os_feishu_project_board(vault_root, project_id)
        return True
