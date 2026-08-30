// Canonical BusinessOperationError -> page-state classification (cluster exc-10).
//
// ~22 pages each hand-rolled their own `error.status === 401 || error.status === 403` (some also
// checking `error.code === 'forbidden'`, some not -- an inconsistency that was a real bug: a
// forbidden response that arrives without a 401/403 status falls through to a page's generic
// error state on the pages that only checked status) condition to classify a caught
// BusinessOperationError into a page state (forbidden/notFound/conflict/etc). That classification
// -- the *condition*, not the Chinese sentence shown for it -- is what this module centralizes.
//
// Each page's own subject-specific Chinese sentence ("当前账户没有确认权限。" vs "当前账户没有
//读取商务机会的权限。" etc.) is left where it is and phrased however that page phrased it before:
// this module answers "what kind of failure is this", not "what should the page say about it".
// Consolidating the wording itself is a separate, larger product-copy question this change does
// not take on.
import { BusinessOperationError } from "./generatedBusinessPagesContract";

/**
 * True for a 401, a 403, or a "forbidden"/"admin_required"-coded response -- the general
 * "no permission" family most pages collapse 401 and 403 into. Prefer this unless the page
 * genuinely needs to tell a session-expired 401 apart from an entitlement-not-provisioned 403
 * (see isUnauthorizedError / isMissingEntitlementError for that split).
 */
export function isForbiddenError(error: unknown): boolean {
  return (
    error instanceof BusinessOperationError &&
    (error.status === 401 ||
      error.status === 403 ||
      error.code === "forbidden" ||
      error.code === "admin_required")
  );
}

/** True specifically for a 401 (session expired / not logged in), distinct from a 403 entitlement gap. */
export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof BusinessOperationError && error.status === 401;
}

/** True specifically for a 403 or "forbidden"/"admin_required"-coded response, distinct from a 401. */
export function isMissingEntitlementError(error: unknown): boolean {
  return (
    error instanceof BusinessOperationError &&
    (error.status === 403 || error.code === "forbidden" || error.code === "admin_required")
  );
}

export function isNotFoundError(error: unknown): boolean {
  return (
    error instanceof BusinessOperationError &&
    (error.status === 404 || error.code === "resource_not_found")
  );
}

/** Revision/idempotency conflicts -- a 409, or the two conflict codes the backend uses for one. */
export function isConflictError(error: unknown): boolean {
  return (
    error instanceof BusinessOperationError &&
    (error.status === 409 ||
      error.code === "revision_conflict" ||
      error.code === "idempotency_conflict")
  );
}
