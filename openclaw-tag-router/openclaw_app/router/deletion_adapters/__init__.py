from __future__ import annotations

from ..deletion_discovery import DiscoveryResult
from .archive_adapter import ArchiveDeletionAdapter
from .base import CapabilityDeletionAdapter, DeletionContext
from .bitable_record_adapter import BitableRecordDeletionAdapter
from .content_os_adapter import ContentOSDeletionAdapter
from .creation_run_adapter import CreationRunDeletionAdapter
from .feishu_doc_adapter import FeishuDocDeletionAdapter
from .obsidian_block_adapter import ObsidianBlockDeletionAdapter
from .reminder_calendar_adapter import ReminderCalendarDeletionAdapter
from .transcription_adapter import TranscriptionDeletionAdapter


def deletion_adapters() -> list[CapabilityDeletionAdapter]:
    return [
        CreationRunDeletionAdapter(),
        TranscriptionDeletionAdapter(),
        ReminderCalendarDeletionAdapter(),
        ContentOSDeletionAdapter(),
        ObsidianBlockDeletionAdapter(),
        FeishuDocDeletionAdapter(),
        BitableRecordDeletionAdapter(),
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
