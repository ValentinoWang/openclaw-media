// Canonical BusinessOperationError -> Chinese-message mapping (cluster FE-05), layered on
// top of businessErrorPresentation.ts's status/code *classification* (isForbiddenError,
// isNotFoundError, etc. -- that module answers "what kind of failure is this", this one
// answers "what should the page say about it").
//
// 14 pages each hand-rolled the same `if (error.status === 401 || error.status === 403) ...`
// chain, but the audit found their *coverage and wording were never actually the same
// thing* -- some split 401 (session expired) from 403 (no entitlement), some fold both into
// one "no permission" sentence; some handle 409/422/5xx, most don't; four pages each check a
// domain-specific `code` no other page recognizes (field_unavailable, monitor_unavailable,
// invalid_request, timeout). Per mediaProductHttpTransport.ts's own comment, an unmapped
// English diagnostic must never reach ordinary-user UI -- so this module does NOT invent a
// single fixed sentence per status the way a naive merge would; it centralizes the
// *classification dispatch* (the repeated if/else chain) while requiring the caller to
// supply the text for whichever branches its page actually distinguishes, exactly as that
// page phrased them before. A page with no override for a branch it doesn't handle falls
// through to `fallback`, matching its prior (unbranched) behavior. This is what preserves
// the divergent wording documented in the audit instead of silently unifying it.
import {
  isConflictError,
  isForbiddenError,
  isNotFoundError,
  isUnauthorizedError,
} from "../businessErrorPresentation";
import { BusinessOperationError } from "../generatedBusinessPagesContract";
import type { LoadState } from "./loadState";

export type BusinessErrorMessages = {
  /** Used whenever no more specific branch below matches (including non-BusinessOperationError throws). */
  fallback: string;
  /** 401 specifically (session expired / not logged in). Omit to fold 401 into `forbidden`. */
  unauthorized?: string;
  /** 403, or a "forbidden"/"admin_required"-coded response; also used for 401 when `unauthorized` is omitted. */
  forbidden?: string;
  /** 404, or a "resource_not_found"-coded response. */
  notFound?: string;
  /** 408, 504, or a "timeout"-coded response. */
  timeout?: string;
  /** 409, or a "revision_conflict"/"idempotency_conflict"-coded response. */
  conflict?: string;
  /** 422 (validation failure on a write). */
  validation?: string;
  /** Any 5xx not otherwise matched above. */
  unavailable?: string;
  /**
   * Domain-specific `error.code` overrides, checked before every status-based branch above
   * (a page-specific code like TracksPage's "monitor_unavailable" or AdminTenantsPage's
   * "invalid_request" is more specific than any generic status bucket and should win
   * regardless of which HTTP status happens to accompany it).
   */
  byCode?: Record<string, string>;
};

/**
 * `describeBusinessError(error, messages) -> string`. Dispatch order: byCode -> unauthorized
 * (401) -> forbidden (403, or 401 falling back to `forbidden` when `unauthorized` is unset)
 * -> notFound (404) -> timeout (408/504) -> conflict (409) -> validation (422) ->
 * unavailable (5xx) -> fallback.
 */
export function describeBusinessError(error: unknown, messages: BusinessErrorMessages): string {
  if (!(error instanceof BusinessOperationError)) return messages.fallback;

  if (messages.byCode && typeof error.code === "string" && messages.byCode[error.code] !== undefined) {
    return messages.byCode[error.code];
  }
  if (isForbiddenError(error)) {
    if (isUnauthorizedError(error) && messages.unauthorized) return messages.unauthorized;
    if (messages.forbidden) return messages.forbidden;
    if (messages.unauthorized) return messages.unauthorized;
  }
  if (isNotFoundError(error) && messages.notFound) return messages.notFound;
  if ((error.status === 408 || error.status === 504) && messages.timeout) return messages.timeout;
  if (isConflictError(error) && messages.conflict) return messages.conflict;
  if (error.status === 422 && messages.validation) return messages.validation;
  if (error.status >= 500 && messages.unavailable) return messages.unavailable;
  return messages.fallback;
}

const DEFAULT_FORBIDDEN = (subject: string) => `${subject}暂无查看权限。请确认当前账户权限后刷新。`;
const DEFAULT_NOT_FOUND = (subject: string) => `${subject}不存在或已不可用。`;
const DEFAULT_ERROR = (subject: string) => `${subject}暂时无法读取。请点击"刷新"重新读取。`;

/**
 * `toResourceState(error, subject) -> LoadState<T>`. The majority pattern among the 14
 * hand-rolled copies: fold 401/403 into one `permission` branch, 404 into `notFound`,
 * everything else into `error`, each with a subject-interpolated sentence -- TracksPage's
 * `toResourceError` (the FE-03 structural baseline) already phrased its two branches
 * exactly this way, which is why this default needs no override to reproduce it verbatim.
 * A page whose prior wording differs from these defaults can pass `overrides`, or use
 * `describeBusinessError` directly for a return shape or dispatch this generic form can't
 * cover (401-vs-403 split, extra status codes, a non-string error payload, ...).
 */
export function toResourceState<T>(
  error: unknown,
  subject: string,
  overrides?: { forbidden?: string; notFound?: string; error?: string },
): LoadState<T> {
  if (isNotFoundError(error)) {
    return { status: "notFound", error: overrides?.notFound ?? DEFAULT_NOT_FOUND(subject) };
  }
  if (isForbiddenError(error)) {
    return { status: "permission", error: overrides?.forbidden ?? DEFAULT_FORBIDDEN(subject) };
  }
  return { status: "error", error: overrides?.error ?? DEFAULT_ERROR(subject) };
}
