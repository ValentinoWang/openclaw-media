from __future__ import annotations

from ..deletion_discovery import DiscoveryResult
from .archive_adapter import ArchiveDeletionAdapter
from .base import CapabilityDeletionAdapter, DeletionContext
from .content_os_adapter import ContentOSDeletionAdapter
from .creation_run_adapter import CreationRunDeletionAdapter
from .obsidian_block_adapter import ObsidianBlockDeletionAdapter
from .reminder_calendar_adapter import ReminderCalendarDeletionAdapter
from .review_adapter import ReviewDeletionAdapter
from .source_asset_adapter import SourceAssetDeletionAdapter
from .transcription_adapter import TranscriptionDeletionAdapter


def deletion_adapters() -> list[CapabilityDeletionAdapter]:
    return [
        SourceAssetDeletionAdapter(),
        ReviewDeletionAdapter(),
        CreationRunDeletionAdapter(),
        TranscriptionDeletionAdapter(),
        ReminderCalendarDeletionAdapter(),
        ContentOSDeletionAdapter(),
        ObsidianBlockDeletionAdapter(),
        ArchiveDeletionAdapter(),
    ]


def adapter_for(discovery: DiscoveryResult) -> CapabilityDeletionAdapter | None:
    for adapter in deletion_adapters():
        if adapter.can_handle(discovery):
            return adapter
    return None


def adapters_for(discovery: DiscoveryResult) -> list[CapabilityDeletionAdapter]:
    return [adapter for adapter in deletion_adapters() if adapter.can_handle(discovery)]


__all__ = ["DeletionContext", "adapter_for", "adapters_for", "deletion_adapters"]
