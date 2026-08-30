// Canonical frontend identifier validation (cluster TI-08).
//
// `canonicalUuid`/`UUID_PATTERN` and the `^[A-Za-z0-9_-]{8,160}$` "public id" rule were each
// duplicated (with drifting names) across ui/adminAction.ts and six page files. Consolidated here
// with their exact original behavior preserved — including the case-insensitive UUID match (the
// dedup audit flags that as a possible cross-layer mismatch with a backend check that may be
// case-sensitive; that is a behavior question for whoever owns the backend validator, not
// something this consolidation should silently change, so the /i flag stays as-is).
export const CANONICAL_UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function isCanonicalUuid(value: string): boolean {
  return CANONICAL_UUID_PATTERN.test(value)
}

/** Alias kept for call sites migrating from ui/adminAction.ts's original export name. */
export const canonicalUuid = isCanonicalUuid

export const PUBLIC_ID_PATTERN = /^[A-Za-z0-9_-]{8,160}$/

/** Same rule as PUBLIC_ID_PATTERN, as an HTML `pattern` attribute source string (no ^$ anchors; `-` escaped). */
export const PUBLIC_ID_HTML_PATTERN = "[A-Za-z0-9_\\-]{8,160}"

export function isPublicId(value: string): boolean {
  return PUBLIC_ID_PATTERN.test(value)
}
