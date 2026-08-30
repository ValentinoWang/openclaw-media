// Canonical frontend idempotency-key generation (cluster TI-05).
//
// Previously duplicated verbatim in ui/adminAction.ts and ui/ordinaryPagePrimitives.tsx, and
// re-inlined as the same `${scope}-${secureUuid()}` idiom at nine more call sites across the
// codebase. This module owns the shape; everything else imports it.
import { secureUuid } from "./secureUuid"

/** `${scope}-${uuid}` — the general-purpose idempotency key used by admin and ordinary actions alike. */
export function newIdempotencyKey(scope: string): string {
  return `${scope}-${secureUuid()}`
}

/**
 * `web_` + 32 raw hex chars (no dashes) — task-launch drafts use this distinct, denser shape
 * because the key is persisted in draft state across re-renders (see task-launch/taskDraft.ts);
 * changing its shape would change what is already stored in existing drafts, so it is kept
 * separate from newIdempotencyKey rather than unified with it.
 */
export function newTaskIdempotencyKey(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return `web_${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`
}
