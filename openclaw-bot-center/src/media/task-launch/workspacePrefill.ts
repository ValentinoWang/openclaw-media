import type { CapabilityCatalog } from '../../schemas/capabilityCatalogSchema'
import type { StructuredPrefill, TaskDraftAction } from './taskDraft'

export function workspacePrefillAction(
  catalog: CapabilityCatalog,
  prefill?: StructuredPrefill,
): TaskDraftAction {
  if (!prefill) return { type: 'clear', catalogVersion: catalog.catalogVersion }
  return {
    type: prefill.capabilityId === 'universal_deletion' ? 'prefillReview' : 'prefill',
    prefill,
    catalog,
  }
}
