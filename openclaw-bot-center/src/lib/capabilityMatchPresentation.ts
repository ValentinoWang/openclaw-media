import type { Capability } from '../schemas/dashboardSchema'
import type { CapabilityMatchResponse } from '../schemas/capabilityMatchSchema'

export type ResolvedMatch = {
  order: number
  reason: string
  step: Extract<CapabilityMatchResponse, { pathStatus: 'matched' }>['steps'][number]
  capability: Capability
}

export function capabilityMatchLabel(label: string): string {
  const trimmed = label.trim()
  const bracketed = /^【(.+)】$/.exec(trimmed)
  return bracketed ? bracketed[1].trim() : trimmed
}

export function resolveMatchedCapabilities(
  response: Extract<CapabilityMatchResponse, { pathStatus: 'matched' }>,
  capabilities: Capability[],
): ResolvedMatch[] | null {
  const orderedSteps = [...response.steps].sort((left, right) => left.order - right.order)
  if (orderedSteps.some((step, index) => step.order !== index + 1)) return null

  return orderedSteps.reduce<ResolvedMatch[] | null>((resolved, step) => {
    if (!resolved) return null
    const candidates = capabilities.filter((capability) => capability.canonicalCapabilityId === step.capabilityId)
    if (candidates.length !== 1) return null
    const [capability] = candidates
    resolved.push({ order: step.order, reason: response.routeExplanation, step, capability })
    return resolved
  }, [])
}
